"""Tests de la avería que se arregla sola y pide permiso para desplegarse.

Lo que se comprueba es la frontera que sostiene todo el camino: **arreglar solo, sí;
desplegar solo, no**. Y las dos formas de romperla que ya conocemos de otros sitios del
proyecto: que una decisión se tome dos veces (el PATCH condicional) y que un fallo a
medio camino deje el botón muerto sin haber hecho el trabajo.
"""
import pytest

import main
from conftest import FakeResponse

REVISION = {"X-Auth-Token": "revision-token"}
CABECERA = {"X-Auth-Token": "ha-poll-token"}
FIRE_URL = "https://api.anthropic.test/v1/claude_code/routines/trig_x/fire"


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
    monkeypatch.setattr(main, "ARREGLO_FIRE_URL", FIRE_URL)
    monkeypatch.setattr(main, "ARREGLO_FIRE_TOKEN", "arreglo-token")
    monkeypatch.setattr(main, "JARVIS_REPO", "usuario/Life-Assistant")
    monkeypatch.setattr(main, "AVERIA_CI", True)
    monkeypatch.setattr(main, "DEPLOY_GITHUB_TOKEN", "gh-token")
    # La llamada se prueba aparte: aquí solo estorbaría con un POST a Twilio en cada test.
    monkeypatch.setattr(main, "LLAMADAS", False)


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "enviar_correo",
                        lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


class TestElCiSeRompe:
    def test_lanza_el_arreglo_sin_preguntar(self, client, mock_requests):
        """El punto entero de esto: no hay pregunta previa. Se arregla y luego se enseña."""
        mock_requests.add("POST", "revision_hallazgos", FakeResponse([], 201))
        mock_requests.add("POST", "fire", FakeResponse({"claude_code_session_url": "https://s"}, 200))

        r = client.post("/averia", json={"origen": "ci", "referencia": "9911",
                                         "detalle": "el CI ha fallado en main"},
                        headers=REVISION)
        assert r.status_code == 200 and r.json()["lanzado"] is True

        fila = mock_requests.called("POST", "revision_hallazgos")[0][2]["json"]
        # Nace ya en "arreglando": no pasa por "pendiente" porque no hay nada que decidir.
        assert fila["estado"] == "arreglando" and fila["origen"] == "ci"
        assert fila["id"] == main._uuid_averia("ci", "9911")
        assert mock_requests.called("POST", "fire")
        # Y NO se avisa: el aviso llega cuando hay algo que enseñar.
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_apagado_no_hace_nada(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "AVERIA_CI", False)
        r = client.post("/averia", json={"referencia": "9911"}, headers=REVISION)
        assert r.status_code == 200 and r.json()["lanzado"] is False
        assert not mock_requests.called("POST", "fire")

    def test_el_mismo_run_no_lanza_dos_agentes(self, client, mock_requests):
        """El 409 contra la clave primaria ES la respuesta, igual que en la revisión."""
        mock_requests.add("POST", "revision_hallazgos", FakeResponse([], 409))
        r = client.post("/averia", json={"referencia": "9911"}, headers=REVISION)
        assert r.status_code == 200 and r.json()["lanzado"] is False
        assert not mock_requests.called("POST", "fire")

    def test_sin_referencia_no_se_apunta(self, client):
        r = client.post("/averia", json={"referencia": ""}, headers=REVISION)
        assert r.status_code == 422

    def test_sin_token_no_entra(self, client):
        assert client.post("/averia", json={"referencia": "1"}).status_code == 403

    def test_un_arreglo_que_no_arregla_deja_de_intentarse(self, client, mock_requests):
        """Un fallo que se arregla solo todos los días no está arreglado, está escondido.

        Misma regla que el vigilante: pasado el tope se deja de lanzar y se DICE, en vez
        de seguir gastando agentes en algo que no funciona.
        """
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([{"id": "a"}, {"id": "b"}]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

        r = client.post("/averia", json={"referencia": "9911"}, headers=REVISION)
        assert r.status_code == 200 and r.json()["lanzado"] is False
        assert not mock_requests.called("POST", "fire")
        # Pero se avisa: dejar de intentarlo en silencio sería el mismo error al revés.
        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert "no funciona" in aviso["texto"]

    def test_si_el_disparo_falla_la_averia_no_se_queda_en_arreglando(self, client, mock_requests):
        """Una fila en 'arreglando' sin nadie arreglando es una avería invisible."""
        mock_requests.add("POST", "revision_hallazgos", FakeResponse([], 201))
        mock_requests.add("POST", "fire", FakeResponse({}, 500))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

        r = client.post("/averia", json={"referencia": "9911"}, headers=REVISION)
        assert r.json()["lanzado"] is False
        cerrada = mock_requests.called("PATCH", "revision_hallazgos")[0][2]["json"]
        assert cerrada["estado"] == "descartado"
        assert mock_requests.called("POST", "jarvis_recordatorios")


class TestElArregloEstaListo:
    def test_avisa_con_el_boton_de_desplegar(self, client, mock_requests):
        rid = main._uuid_averia("ci", "9911")
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": rid, "origen": "ci",
                                         "detalle": "el CI ha fallado en main"}]))
        mock_requests.add("PATCH", "revision_hallazgos", FakeResponse([{"id": rid}]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

        r = client.post("/revision/pr-listo", json={"pr": 122}, headers=REVISION)
        assert r.status_code == 200 and r.json()["avisado"] is True

        cambio = mock_requests.called("PATCH", "revision_hallazgos")[0][2]["json"]
        # El PR se guarda CON la decisión: al contestar horas después no se puede
        # resolver "el PR más reciente", que podría ser otro.
        assert cambio["estado"] == "listo" and cambio["pr_numero"] == 122

        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert aviso["regla"] == main.REGLA_DESPLIEGUE and "122" in aviso["texto"]
        # Y los botones de ESE aviso son los del despliegue, no los de la revisión.
        acciones = main._acciones_aviso(rid, main.REGLA_DESPLIEGUE)
        assert [a["title"] for a in acciones] == ["Desplegar", "Ahora no"]

    def test_un_pr_que_no_cierra_averia_no_avisa(self, client, mock_requests):
        """La mayoría de los PR los abre el usuario. Eso no es un error y no se avisa."""
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([]))
        r = client.post("/revision/pr-listo", json={"pr": 122}, headers=REVISION)
        assert r.status_code == 200 and r.json()["avisado"] is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_dos_ejecuciones_del_workflow_no_dejan_dos_avisos(self, client, mock_requests):
        """El PATCH condicional: si ya no estaba en 'arreglando', no hay nada que avisar."""
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([{"id": main._uuid_averia("ci", "1")}]))
        mock_requests.add("PATCH", "revision_hallazgos", FakeResponse([]))
        r = client.post("/revision/pr-listo", json={"pr": 122}, headers=REVISION)
        assert r.json()["avisado"] is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_llama_por_telefono(self, client, mock_requests, monkeypatch):
        """Un PR esperando permiso es el único caso que hoy justifica el canal caro."""
        llamadas = []
        monkeypatch.setattr(main, "_llamar",
                            lambda texto, rid="": llamadas.append((texto, rid)) or True)
        rid = main._uuid_averia("ci", "9911")
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": rid, "detalle": "el CI ha fallado"}]))
        mock_requests.add("PATCH", "revision_hallazgos", FakeResponse([{"id": rid}]))

        client.post("/revision/pr-listo", json={"pr": 122}, headers=REVISION)
        assert llamadas and llamadas[0][1] == rid
        # Y lo que se oye NO recita el motivo, aunque quien llama lo tenga delante. Este
        # test pedía justo lo contrario ("una llamada que solo dice mira el móvil no
        # ahorra mirar el móvil") y estaba escrito pensando en un aviso de un solo
        # sentido. Pero esto es una conversación: si quieres saber qué se rompió, lo
        # preguntas. Recitar el título del fallo del CI antes de la pregunta solo mete
        # veinte segundos de altavoz por delante de la única decisión que hay que tomar.
        assert "CI ha fallado" not in llamadas[0][0]
        assert "despliegue" in llamadas[0][0]


class TestElPermisoDeDespliegue:
    def _listo(self, mock_requests, rid, pr=122):
        mock_requests.add("PATCH", "revision_hallazgos",
                          FakeResponse([{"id": rid, "pr_numero": pr, "estado": "desplegando"}]))

    def test_desplegar_mergea_y_lanza_el_deploy(self, client, mock_requests, correos):
        rid = main._uuid_averia("ci", "9911")
        self._listo(mock_requests, rid)
        mock_requests.add("PUT", "/merge", FakeResponse({}, 200))
        mock_requests.add("POST", "dispatches", FakeResponse({}, 204))

        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "desplegar"},
                        headers=CABECERA)
        assert r.status_code == 200 and r.json()["hecho"] is True

        merge = mock_requests.called("PUT", "/merge")[0][2]["json"]
        # Squash con mensaje explícito: dejar que GitHub lo autogenere le hace añadir un
        # `Co-authored-by` por su cuenta, que es justo lo que CLAUDE.md prohíbe.
        assert merge["merge_method"] == "squash" and merge["commit_message"]
        assert mock_requests.called("POST", "dispatches")

    def test_ahora_no_no_toca_produccion(self, client, mock_requests):
        rid = main._uuid_averia("ci", "9911")
        mock_requests.add("PATCH", "revision_hallazgos",
                          FakeResponse([{"id": rid, "pr_numero": 122}]))
        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "nada"}, headers=CABECERA)
        assert r.status_code == 200 and r.json()["accion"] == "nada"
        assert not mock_requests.called("PUT", "/merge")
        assert not mock_requests.called("POST", "dispatches")

    def test_dos_toques_no_despliegan_dos_veces(self, client, mock_requests):
        """El PATCH condicional sobre `estado=eq.listo`: el segundo no encuentra fila."""
        rid = main._uuid_averia("ci", "9911")
        mock_requests.add("PATCH", "revision_hallazgos", FakeResponse([]))
        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "desplegar"},
                        headers=CABECERA)
        assert r.status_code == 200 and r.json()["hecho"] is False
        assert not mock_requests.called("PUT", "/merge")

    def test_si_el_merge_falla_el_permiso_vuelve(self, client, mock_requests, correos):
        """Un permiso consumido sin efecto deja el botón muerto: el peor de los errores."""
        rid = main._uuid_averia("ci", "9911")
        self._listo(mock_requests, rid)
        mock_requests.add("PUT", "/merge", FakeResponse({}, 409, text="conflicto"))

        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "desplegar"},
                        headers=CABECERA)
        assert r.status_code == 502
        vuelta = mock_requests.called("PATCH", "revision_hallazgos")[-1][2]["json"]
        assert vuelta["estado"] == "listo"

    def test_si_el_deploy_no_arranca_no_se_dice_que_no_se_mergeo(self, client, mock_requests, correos):
        """El merge no se puede deshacer: decir 'no se ha desplegado' escondería que
        `main` ya lleva el cambio."""
        rid = main._uuid_averia("ci", "9911")
        self._listo(mock_requests, rid)
        mock_requests.add("PUT", "/merge", FakeResponse({}, 200))
        mock_requests.add("POST", "dispatches", FakeResponse({}, 403))

        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "desplegar"},
                        headers=CABECERA)
        assert r.status_code == 502
        vuelta = mock_requests.called("PATCH", "revision_hallazgos")[-1][2]["json"]
        assert vuelta["estado"] == "desplegado"
        assert any("a mano" in c[1] for c in correos)

    def test_sin_credencial_lo_dice_en_vez_de_fallar_en_silencio(self, monkeypatch):
        monkeypatch.setattr(main, "DEPLOY_GITHUB_TOKEN", "")
        resultado = main._desplegar(122)
        assert resultado["ok"] is False and "DEPLOY_GITHUB_TOKEN" in resultado["motivo"]

    def test_sin_auth_no_se_despliega(self, client):
        rid = main._uuid_averia("ci", "9911")
        assert client.post(f"/despliegue/{rid}/accion",
                           json={"accion": "desplegar"}).status_code == 403

    def test_solo_admite_las_dos_acciones(self, client):
        rid = main._uuid_averia("ci", "9911")
        r = client.post(f"/despliegue/{rid}/accion", json={"accion": "arreglar"},
                        headers=CABECERA)
        assert r.status_code == 422


class TestLaPantallaDeLlamada:
    """`GET /despliegue/pendiente`: lo que la pantalla de llamada anuncia al descolgar."""

    def test_cuenta_lo_que_espera_permiso(self, client, mock_requests, auth_headers):
        rid = main._uuid_averia("ci", "9911")
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": rid, "pr_numero": 122,
                                         "detalle": "el CI ha fallado en main"}]))
        r = client.get("/despliegue/pendiente", headers=auth_headers)
        assert r.status_code == 200
        pendiente = r.json()["pendiente"]
        # El id viaja para que el «sí» se aplique a ESTE despliegue y no al más reciente
        # resuelto otra vez al contestar (frontera 2 de docs/AVERIAS.md).
        assert pendiente["id"] == rid and pendiente["pr"] == 122
        # Y la frase es LA MISMA que diría el teléfono: un solo Jarvis, dos transportes.
        assert pendiente["apertura"] == main._apertura_despliegue()

    def test_sin_nada_pendiente_no_inventa_una_llamada(self, client, mock_requests, auth_headers):
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([]))
        r = client.get("/despliegue/pendiente", headers=auth_headers)
        assert r.status_code == 200 and r.json()["pendiente"] is None

    def test_no_es_publico(self, client):
        """Dice qué se ha roto en producción y qué PR lo arregla: pide sesión."""
        assert client.get("/despliegue/pendiente").status_code in (401, 403)


class TestElBotonDeHablarlo:
    """El tercer botón del aviso: el que abre la pantalla de llamada."""

    def test_aparece_cuando_hay_dashboard_configurado(self, monkeypatch):
        monkeypatch.setattr(main, "FRONTEND_URL", "https://panel.ejemplo")
        rid = main._uuid_averia("ci", "1")
        acciones = main._acciones_aviso(rid, main.REGLA_DESPLIEGUE)
        assert [a["title"] for a in acciones] == ["Desplegar", "Ahora no", "Hablarlo"]
        # "URI" es el nombre reservado de la app de HA, no un id nuestro: si esto cambia,
        # el botón deja de abrir nada y no lo dice.
        assert acciones[-1]["action"] == "URI"
        assert acciones[-1]["uri"] == "https://panel.ejemplo/?llamada=1"

    def test_sin_dashboard_el_aviso_sigue_sirviendo(self, monkeypatch):
        """Lo que se pierde es hablarlo, no decidir: los dos botones siguen ahí."""
        monkeypatch.setattr(main, "FRONTEND_URL", "")
        acciones = main._acciones_aviso(main._uuid_averia("ci", "1"), main.REGLA_DESPLIEGUE)
        assert [a["title"] for a in acciones] == ["Desplegar", "Ahora no"]


class TestElAvisoQueSuenaEnSilencio:
    """Qué avisos atraviesan el silencio del móvil. Hoy: exactamente uno.

    Es la misma frontera que decide quién puede llamarte por teléfono
    (`docs/LLAMADAS.md`): solo lo que se queda BLOQUEADO hasta que contestes. Si algún día
    suena por algo que podía esperar, dejarás de mirarlo — y con él se irá el aviso que sí
    importaba. Por eso está fijado en un test y no solo en un comentario.
    """

    def _cola(self, monkeypatch):
        monkeypatch.setattr(main, "AVISOS_MOVIL", True)
        monkeypatch.setattr(main, "_ultimo_sondeo_avisos", main.time.time())
        monkeypatch.setattr(main, "_avisos_movil", [])
        return main._avisos_movil

    def test_el_permiso_de_despliegue_es_critico(self, monkeypatch):
        cola = self._cola(monkeypatch)
        assert main._notificar("t", "x", critico=True) == "movil"
        assert cola[0]["critico"] is True

    def test_lo_demas_no(self, monkeypatch):
        cola = self._cola(monkeypatch)
        main._notificar("t", "x")
        assert cola[0]["critico"] is False


class TestElContextoDeLaLlamada:
    """Lo que Jarvis ya sabe al descolgar, sin tener que ir a buscarlo.

    Es una optimización de LATENCIA, no de capacidad: sin esto Jarvis contesta lo mismo,
    pero tardando una herramienta más. Y hablando eso se nota — medido, 1,7 s contra
    9,7 s. Se prueba aquí porque lo que se le mete al contexto es la avería.
    """

    def test_por_voz_ya_sabe_que_hay_pendiente(self, mock_requests):
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": main._uuid_averia("ci", "1"), "pr_numero": 126,
                                         "detalle": "el CI ha fallado en main"}]))
        sistema = main._jarvis_sistema(voz=True)
        assert "126" in sistema
        assert "el CI ha fallado en main" in sistema
        # Y lo importante no es que lo sepa, es que se le diga que NO vaya a buscarlo:
        # sabiéndolo pero sin esta línea, el modelo pide la herramienta igual.
        assert "SIN llamar a" in sistema

    def test_por_escrito_no_se_paga_la_consulta(self, mock_requests, monkeypatch):
        """El chat no va casi nunca de esto y los segundos ahí no se notan."""
        def _no(*a, **k):
            raise AssertionError("el contexto escrito no debe consultar el despliegue")
        monkeypatch.setattr(main, "_despliegue_pendiente", _no)
        main._jarvis_sistema(voz=False)

    def test_si_supabase_se_cae_la_llamada_sigue(self, mock_requests, monkeypatch):
        """El dato es adorno: un 502 aquí no puede llevarse por delante la conversación."""
        monkeypatch.setattr(main, "_despliegue_pendiente",
                            lambda: (_ for _ in ()).throw(RuntimeError("Supabase caído")))
        assert "Jarvis" in main._jarvis_sistema(voz=True)

    def test_sin_nada_pendiente_no_se_inventa_contexto(self, mock_requests):
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([]))
        assert "ESPERANDO TU PERMISO" not in main._jarvis_sistema(voz=True)


class TestElPermisoCaduca:
    """Un permiso de despliegue que nadie contestó no vale para siempre.

    Nació sin caducidad, y el fallo salió probando «avísame» el 2026-09-04: una fila en
    «listo» de la prueba de la víspera **secuestraba la pantalla de llamada** —el
    despliegue se anuncia antes que cualquier otra cosa, por diseño— y encima ofrecía
    desplegar un PR que ya estaba mergeado a mano y no existía.
    """

    def test_no_se_anuncia_uno_viejo(self, client, mock_requests, auth_headers):
        client.get("/despliegue/pendiente", headers=auth_headers)
        url = mock_requests.called("GET", "revision_hallazgos")[0][1]
        # Va en la consulta, no en un barrido que cierre filas: nadie decidió nada, y
        # poder ver después cuántos permisos se quedaron sin respuesta es justo el dato.
        assert "creado=gte." in url and "estado=eq.listo" in url

    def test_la_llamada_tampoco_se_queda_atascada(self, client, mock_requests, auth_headers):
        """Con el permiso caducado, lo que se anuncia es lo siguiente que haya."""
        mock_requests.add("GET", "sesion_avisos",
                          FakeResponse([{"id": "11111111-2222-3333-4444-555555555555",
                                         "titulo": "un aviso de sesión",
                                         "bloqueado": False}]))
        r = client.get("/llamada/pendiente", headers=auth_headers)
        assert r.json()["pendiente"]["tipo"] == "sesion"

    def test_la_herramienta_de_jarvis_usa_la_misma_puerta(self, mock_requests):
        """Si es demasiado viejo para anunciarlo, es demasiado viejo para desplegarlo."""
        r = main._j_desplegar()
        assert r["ok"] is False
        assert not mock_requests.called("PUT", "pulls")

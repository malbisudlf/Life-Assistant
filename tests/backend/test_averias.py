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
        # Lo que se oye tiene que decir QUÉ se rompió: una llamada que solo dice "mira el
        # móvil" no ahorra mirar el móvil.
        assert "CI ha fallado" in llamadas[0][0]


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

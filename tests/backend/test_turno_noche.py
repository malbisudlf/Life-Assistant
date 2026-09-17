"""El turno de noche: lo que se resuelve mientras Mikel duerme.

Lo que se comprueba aquí es, sobre todo, lo que NO hace. Esto corre a las tres de la
mañana sin nadie mirando, lee el buzón y llama a modelos de pago: las garantías que lo
hacen aceptable son que no envía nada, que no abre el cuerpo de lo que no toca y que no
puede correr dos veces la misma noche. Cada una tiene su test.
"""
import json
from types import SimpleNamespace

import pytest

import main
from conftest import FakeResponse


def _fake_buzon(monkeypatch, mock_requests, *, cabeceras=None, cuerpos=None,
                crear_ok=True):
    """Un buzón de mentira, hablando Graph. Devuelve el registro de lo que se le pidió.

    Se simulan las RESPUESTAS de Graph y no las funciones del buzón: lo que interesa
    comprobar es qué se le pide a Outlook —de qué mensaje se baja el cuerpo, sobre cuál
    se crea la respuesta— y eso solo se ve en la URL.
    """
    registro = {"cuerpos_pedidos": [], "borradores": []}
    cuerpos = cuerpos or {}

    def _cuerpo(url, **kwargs):
        ident = url.split("/me/messages/")[1].split("?")[0]
        registro["cuerpos_pedidos"].append(ident)
        return FakeResponse({"uniqueBody": {"contentType": "text",
                                            "content": cuerpos.get(ident, "")}}, 200)

    def _crear(url, **kwargs):
        ident = url.split("/me/messages/")[1].split("/createReply")[0]
        registro["borradores"].append({"id": ident,
                                       "comment": (kwargs.get("json") or {}).get("comment", "")})
        return FakeResponse({"id": "borrador-1"}, 201 if crear_ok else 403)

    monkeypatch.setattr(main, "_buzon_listo", lambda: "token-de-prueba")
    mock_requests.add("POST", "/createReply", _crear)
    mock_requests.add("GET", "/me/messages/", _cuerpo)
    if cabeceras is not None:
        monkeypatch.setattr(main, "_cabeceras_recientes", lambda: list(cabeceras))
    return registro


def _fake_modelo(monkeypatch, categorias, borrador="Te contesto mañana."):
    """El clasificador y el redactor, con guion. Devuelve lo que se les mandó."""
    recibido = []

    class _Cliente:
        chat = completions = property(lambda self: self)

        def create(self, **kw):
            recibido.append(kw)
            if kw.get("response_format"):
                cuerpo = json.dumps({"correos": [{"i": i, "categoria": c}
                                                 for i, c in enumerate(categorias)]})
            else:
                cuerpo = borrador
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=cuerpo))])

    monkeypatch.setattr(main, "get_openai_client", lambda: _Cliente())
    return recibido


class _Noche:
    @pytest.fixture(autouse=True)
    def _encendido(self, monkeypatch):
        monkeypatch.setattr(main, "NOCHE_TURNO", True)
        monkeypatch.setattr(main, "NOCHE_CORREO", True)
        monkeypatch.setattr(main, "CORREO_LEER", True)


class TestElBuzonDeNoche(_Noche):
    """Clasificar y dejar redactado lo que pide respuesta."""

    def test_solo_se_abre_el_cuerpo_de_lo_que_pide_respuesta(self, monkeypatch, mock_requests):
        """La garantía que sostiene todo lo demás.

        La clasificación sigue viendo solo asunto y remitente, como la regla de día; el
        cuerpo se baja DESPUÉS y únicamente de los que salieron «responder». Si esto se
        rompe, el turno de noche estaría mandando newsletters enteras a un modelo.
        """
        cabeceras = [
            {"asunto": "¿Quedamos el jueves?", "de": "ana@ejemplo.com", "id": "10",
             "message_id": "<a@x>"},
            {"asunto": "Tu resumen semanal", "de": "news@marca.com", "uid": "11",
             "message_id": "<b@x>"},
        ]
        registro = _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras,
                               cuerpos={"10": "Hola, te escribo para quedar."})
        _fake_modelo(monkeypatch, ["responder", "ruido"])

        items, _ = main._noche_correos()

        assert registro["cuerpos_pedidos"] == ["10"]
        assert [i["datos"]["categoria"] for i in items] == ["responder", "ruido"]

    def test_al_clasificador_no_le_llega_ningun_cuerpo(self, monkeypatch, mock_requests):
        cabeceras = [{"asunto": "Cita el jueves", "de": "clinica", "id": "10",
                      "message_id": "<a@x>"}]
        _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras, cuerpos={"10": "SECRETO MEDICO"})
        recibido = _fake_modelo(monkeypatch, ["informativo"])

        main._noche_correos()

        assert "SECRETO MEDICO" not in json.dumps(recibido[0]["messages"])

    def test_el_borrador_queda_en_borradores_y_no_en_la_bandeja(self, monkeypatch,
                                                                mock_requests):
        """`createReply` es lo que separa dejar un borrador de meterte un correo en la
        bandeja de entrada: crea el mensaje ya marcado como borrador, en Borradores, y
        sin mandarlo. En todo el turno no se llama a `/send` ni a `/sendMail`."""
        cabeceras = [{"asunto": "¿Quedamos?", "de": "ana@ejemplo.com", "id": "10",
                      "message_id": "<a@x>"}]
        registro = _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras,
                               cuerpos={"10": "hola"})
        _fake_modelo(monkeypatch, ["responder"], borrador="El jueves me va bien.")

        items, _ = main._noche_correos()

        assert len(registro["borradores"]) == 1
        assert registro["borradores"][0]["comment"] == "El jueves me va bien."
        assert items[0]["datos"]["borrador"] is True
        assert mock_requests.called("POST", "/send") == []
        assert mock_requests.called("POST", "sendMail") == []

    def test_el_borrador_cuelga_del_correo_original(self, monkeypatch, mock_requests):
        """Un borrador suelto es un mensaje a alguien de quien ya no recuerdas nada.

        Con IMAP esto se conseguía montando `In-Reply-To` y `References` a mano; con
        Graph lo da la propia ruta: `createReply` va SOBRE el id del correo original, y
        el hilo, el destinatario y el "Re:" los pone Outlook. Lo que hay que comprobar,
        entonces, es que se llama sobre el mensaje correcto y no sobre otro.
        """
        cabeceras = [{"asunto": "Quedamos el jueves", "de": "ana@ejemplo.com", "id": "42",
                      "message_id": "<hilo-42@ejemplo.com>"},
                     {"asunto": "Otra cosa", "de": "otro@ejemplo.com", "id": "43",
                      "message_id": "<otro@ejemplo.com>"}]
        registro = _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras,
                               cuerpos={"42": "hola"})
        _fake_modelo(monkeypatch, ["responder", "ruido"])

        main._noche_correos()

        assert [b["id"] for b in registro["borradores"]] == ["42"]

    def test_no_se_envia_nada_por_smtp(self, monkeypatch, mock_requests):
        """La frontera entera del turno de noche cabe en este test: prepara, no manda."""
        enviados = []
        monkeypatch.setattr(main, "enviar_correo",
                            lambda *a, **k: enviados.append(a) or {"ok": True})
        cabeceras = [{"asunto": "¿Quedamos?", "de": "ana@ejemplo.com", "id": "10",
                      "message_id": "<a@x>"}]
        _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras, cuerpos={"10": "hola"})
        _fake_modelo(monkeypatch, ["responder"])

        main._noche_correos()

        assert enviados == []

    def test_si_falla_la_clasificacion_no_se_abre_nada(self, monkeypatch, mock_requests):
        """Un fallo del modelo no puede acabar abriendo treinta correos: el defecto es
        «ruido», que es el que no toca nada."""
        cabeceras = [{"asunto": "lo que sea", "de": "x", "id": "10", "message_id": ""}]
        registro = _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras)

        def _revienta():
            raise RuntimeError("la API no contesta")
        monkeypatch.setattr(main, "get_openai_client", _revienta)

        items, _ = main._noche_correos()

        assert registro["cuerpos_pedidos"] == []
        assert registro["borradores"] == []
        assert items[0]["datos"]["categoria"] == "ruido"

    def test_el_tope_de_borradores_se_respeta(self, monkeypatch, mock_requests):
        """Cada borrador es una llamada de pago; el tope es lo que impide que una noche
        rara cueste lo que un mes."""
        cabeceras = [{"asunto": f"correo {i}", "de": "x", "id": str(i),
                      "message_id": f"<{i}@x>"} for i in range(5)]
        registro = _fake_buzon(monkeypatch, mock_requests, cabeceras=cabeceras,
                               cuerpos={str(i): "hola" for i in range(5)})
        _fake_modelo(monkeypatch, ["responder"] * 5)
        monkeypatch.setattr(main, "NOCHE_BORRADORES_MAX", 2)

        main._noche_correos()

        assert len(registro["borradores"]) == 2

    def test_un_correo_desmesurado_no_se_trae_a_memoria(self, monkeypatch, mock_requests):
        """Antes esto lo resolvía el fetch parcial de IMAP (`<0.N>`), que cortaba en el
        servidor. Graph no deja cortar el cuerpo, así que se lee a trozos y se abandona
        el correo en cuanto se pasa del tope: lo que no puede pasar es traerse un correo
        de megas a un backend que vive dentro del Green."""
        monkeypatch.setattr(main, "_buzon_listo", lambda: "token-de-prueba")
        monkeypatch.setattr(main, "CORREO_MAX_DESCARGA", 500)
        mock_requests.add("GET", "/me/messages/", FakeResponse(
            {"uniqueBody": {"contentType": "text", "content": "x" * 5000}}, 200))

        assert main._cuerpos_de(["10"]) == {}

    def test_apagado_no_se_conecta_a_nada(self, monkeypatch):
        monkeypatch.setattr(main, "NOCHE_CORREO", False)
        llamadas = []
        monkeypatch.setattr(main, "_cabeceras_recientes", lambda: llamadas.append(1) or [])
        assert main._noche_correos() == ([], {"estado": "apagado"})
        assert llamadas == []

    def test_un_buzon_caido_no_tumba_la_noche(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "_buzon_listo", lambda: "token-de-prueba")

        def _revienta():
            raise OSError("no se pudo conectar")
        monkeypatch.setattr(main, "_cabeceras_recientes", _revienta)
        items, nota = main._noche_correos()
        assert items == []
        assert nota["estado"] == "fallo"


class TestLoQueSeMiro(_Noche):
    """La nota de lo mirado: qué distingue una noche tranquila de un turno averiado.

    Las cuatro razones por las que el buzón puede dar cero correos tienen que llegar a la
    mañana distinguidas. Si no, «no hubo nada que hacer» acaba leyéndose como «no tengo
    correo» —o como «esto está roto»— y las dos lecturas son peores que el silencio.
    """

    def test_un_buzon_tranquilo_dice_que_se_miro(self, monkeypatch, mock_requests):
        _fake_buzon(monkeypatch, mock_requests, cabeceras=[])

        items, nota = main._noche_correos()

        assert items == []
        assert nota["estado"] == "ok"
        assert nota["mirados"] == 0
        assert nota["horas"] == main.CORREO_HORAS

    def test_sin_outlook_no_se_confunde_con_un_buzon_vacio(self, monkeypatch):
        monkeypatch.setattr(main, "_buzon_listo", lambda: "")

        assert main._noche_correos() == ([], {"estado": "sin_outlook"})

    def test_graph_en_error_no_cuenta_como_cero_correos(self, monkeypatch, mock_requests):
        """El 403 de «Outlook no ha dado permiso de correo» daba lista vacía, igual que
        un buzón limpio. Ahora revienta, y quien llama lo apunta como fallo."""
        monkeypatch.setattr(main, "_buzon_listo", lambda: "token-de-prueba")
        mock_requests.add("GET", "/mailFolders/inbox/messages", FakeResponse({}, 403))

        with pytest.raises(main.BuzonCaido):
            main._cabeceras_recientes()

        items, nota = main._noche_correos()
        assert items == []
        assert nota["estado"] == "fallo"

    def test_el_parte_guarda_lo_mirado_junto_a_las_cuentas(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "_noche_correos",
                            lambda: ([], {"estado": "ok", "mirados": 0, "horas": 24,
                                          "carpeta": "Bandeja de entrada"}))

        salida = main.correr_turno_de_noche()

        assert salida["resumen"]["correos"] == 0
        assert salida["resumen"]["revisado"]["correo"]["mirados"] == 0

    def test_el_area_que_revienta_entera_tambien_deja_nota(self, monkeypatch, mock_requests):
        def _revienta():
            raise RuntimeError("el buzón no contesta")
        monkeypatch.setattr(main, "_noche_correos", _revienta)

        salida = main.correr_turno_de_noche()

        assert salida["resumen"]["revisado"]["correo"] == {"estado": "fallo"}

    @pytest.mark.parametrize("revisado, esperado", [
        ({"correo": {"estado": "ok", "mirados": 0, "horas": 24,
                     "carpeta": "Bandeja de entrada"}}, "Bandeja de entrada"),
        ({"correo": {"estado": "apagado"}},     "apagada"),
        ({"correo": {"estado": "sin_outlook"}}, "Outlook"),
        ({"correo": {"estado": "fallo"}},       "No pude"),
    ])
    def test_la_frase_de_una_noche_en_blanco_dice_por_que(self, revisado, esperado):
        frase = main._frase_parte({"revisado": revisado})
        assert esperado in frase
        assert "No hubo nada que hacer" not in frase

    def test_sin_nota_se_sigue_diciendo_lo_de_siempre(self):
        """Los partes de antes de esto no tienen `revisado`, y tienen que seguir
        leyéndose: un cambio de forma no puede dejar mudo el histórico."""
        assert main._frase_parte({"correos": 0}) == "No hubo nada que hacer esta noche."


class TestElTurno(_Noche):
    """El carril: cuándo corre, cuántas veces y qué deja escrito."""

    def _sin_correo(self, monkeypatch):
        monkeypatch.setattr(main, "_noche_correos", lambda: ([
            {"area": "correo", "titulo": "¿Quedamos?", "detalle": "El jueves.",
             "datos": {"de": "ana", "categoria": "responder", "borrador": True}}],
            {"estado": "ok", "mirados": 1, "horas": 24, "carpeta": "Bandeja de entrada"}))

    def test_el_turno_de_una_noche_se_hace_una_sola_vez(self, monkeypatch, mock_requests):
        """El tick llega cada cinco minutos: sin la reserva atómica, una noche redactaría
        los mismos borradores doce veces."""
        self._sin_correo(monkeypatch)
        estado = {"abierto": False}

        def _post(url, **kwargs):
            if "noche_partes" in url:
                if estado["abierto"]:
                    return main_fake_409()
                estado["abierto"] = True
            return _FakeOk()
        mock_requests.add("POST", "noche_partes", _post)
        mock_requests.add("POST", "noche_items", _FakeOk())

        primero = main.correr_turno_de_noche()
        segundo = main.correr_turno_de_noche()

        assert primero["hecho"] is True
        assert segundo["hecho"] is False

    def test_apagado_no_corre(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "NOCHE_TURNO", False)
        llamadas = []
        monkeypatch.setattr(main, "_noche_correos", lambda: (llamadas.append(1) or [], {"estado": "ok", "mirados": 0}))
        assert main.correr_turno_de_noche()["hecho"] is False
        assert llamadas == []

    def test_fuera_de_la_ventana_no_corre(self, monkeypatch, mock_requests):
        """El tope existe para que un backend que arranca a mediodía no llame «turno de
        noche» a lo que hace a las doce, gastando el día del parte."""
        from datetime import datetime

        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 12, 0, tzinfo=main.LOCAL_TZ))
        llamadas = []
        monkeypatch.setattr(main, "correr_turno_de_noche",
                            lambda *a, **k: llamadas.append(1) or {"hecho": True})
        assert main._turno_de_noche_si_toca() == {}
        assert llamadas == []

    def test_dentro_de_la_ventana_corre(self, monkeypatch, mock_requests):
        from datetime import datetime

        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 3, 5, tzinfo=main.LOCAL_TZ))
        llamadas = []
        monkeypatch.setattr(main, "correr_turno_de_noche",
                            lambda *a, **k: llamadas.append(1) or {"hecho": True})
        assert main._turno_de_noche_si_toca() == {"noche": 1}
        assert len(llamadas) == 1

    def test_el_aviso_del_parte_se_deja_para_la_manana(self, monkeypatch, mock_requests):
        """Despertarte a las tres para contarte el buzón sería la mejor forma de que
        apagases esto."""
        from datetime import datetime

        self._sin_correo(monkeypatch)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 3, 5, tzinfo=main.LOCAL_TZ))
        apuntados = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: apuntados.append((regla, kw)) or True)

        main.correr_turno_de_noche()

        regla, kw = apuntados[0]
        assert regla == main.REGLA_NOCHE
        assert (kw["cuando"].hour, kw["cuando"].minute) == main.HORA_DIFERIDOS

    def test_el_buzon_caido_no_se_lleva_por_delante_el_parte(self, monkeypatch, mock_requests):
        def _revienta():
            raise RuntimeError("el buzón no contesta")
        monkeypatch.setattr(main, "_noche_correos", _revienta)
        assert main.correr_turno_de_noche()["hecho"] is True

    def test_una_frase_sin_nada_no_miente(self):
        assert "nada" in main._frase_parte({}).lower()

    def test_la_frase_cuenta_los_borradores(self):
        frase = main._frase_parte({"correos": 12, "responder": 3, "borradores": 3})
        assert "12 correos" in frase and "3" in frase


class TestDecidirEnElParte:
    """Aprobar y descartar. «Aprobado» no envía nada: quiere decir «visto»."""

    def test_decidir_dos_veces_solo_cuenta_una(self, client, auth_headers, mock_requests):
        """Dos pestañas abiertas, o el botón pulsado dos veces, no son dos decisiones."""
        idp = "11111111-2222-3333-4444-555555555555"
        respuestas = [_FakeOk([{"id": idp}]), _FakeOk([])]
        mock_requests.add("PATCH", "noche_items", lambda url, **kw: respuestas.pop(0))

        primera = client.post(f"/noche/items/{idp}/decidir", headers=auth_headers,
                              json={"accion": "aprobado"})
        segunda = client.post(f"/noche/items/{idp}/decidir", headers=auth_headers,
                              json={"accion": "aprobado"})

        assert primera.json()["cambiado"] is True
        assert segunda.json()["cambiado"] is False

    def test_el_patch_va_condicionado_a_seguir_pendiente(self, client, auth_headers,
                                                         mock_requests):
        idp = "11111111-2222-3333-4444-555555555555"
        mock_requests.add("PATCH", "noche_items", _FakeOk([{"id": idp}]))
        client.post(f"/noche/items/{idp}/decidir", headers=auth_headers,
                    json={"accion": "descartado"})
        assert "estado=eq.pendiente" in mock_requests.called("PATCH", "noche_items")[0][1]

    def test_un_id_que_no_es_uuid_no_llega_a_supabase(self, client, auth_headers,
                                                      mock_requests):
        r = client.post("/noche/items/../../etc/decidir", headers=auth_headers,
                        json={"accion": "aprobado"})
        assert r.status_code in (404, 422)
        assert mock_requests.called("PATCH", "noche_items") == []

    def test_36_caracteres_hex_guion_sin_forma_de_uuid_se_rechaza(self, client, auth_headers,
                                                                   mock_requests):
        """La validación usa _uuid_path() (forma 8-4-4-4-12), no "36 caracteres hex/guion en
        cualquier posición": esto pasaba el regex inline que tenía el endpoint antes."""
        r = client.post(f"/noche/items/{'-' * 36}/decidir", headers=auth_headers,
                        json={"accion": "aprobado"})
        assert r.status_code == 422
        assert mock_requests.called("PATCH", "noche_items") == []

    def test_una_accion_inventada_se_rechaza(self, client, auth_headers, mock_requests):
        idp = "11111111-2222-3333-4444-555555555555"
        r = client.post(f"/noche/items/{idp}/decidir", headers=auth_headers,
                        json={"accion": "enviar"})
        assert r.status_code == 422
        assert mock_requests.called("PATCH", "noche_items") == []

    def test_el_parte_necesita_sesion(self, client):
        assert client.get("/noche/parte").status_code in (401, 403)


class TestElAtajoDelCodigo:
    """Arreglar de noche sin esperar a las 08:30, sin duplicar el camino que ya existe."""

    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch):
        monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")

    def _hallazgo(self, mock_requests):
        mock_requests.add("POST", "revision_hallazgos", _FakeOk(status_code=201))
        mock_requests.add("PATCH", "revision_hallazgos", _FakeOk([{"issue_numero": 7}]))

    def test_apagado_sigue_preguntando_como_siempre(self, client, monkeypatch,
                                                    mock_requests):
        from datetime import datetime

        self._hallazgo(mock_requests)
        monkeypatch.setattr(main, "NOCHE_ARREGLA", False)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 3, 40, tzinfo=main.LOCAL_TZ))
        lanzados = []
        monkeypatch.setattr(main, "_disparar_arreglo",
                            lambda *a, **k: lanzados.append(k) or {"ok": True, "sesion": ""})

        r = client.post("/revision/hallazgos", headers={"X-Auth-Token": main.REVISION_TOKEN},
                        json={"numero": 7, "titulo": "algo"})

        assert r.json()["avisado"] is True
        assert lanzados == []

    def test_encendido_de_noche_arregla_sin_preguntar_y_no_mergea(self, client, monkeypatch,
                                                                  mock_requests):
        """La instrucción es la única diferencia con el camino de siempre, y dice lo que
        no se puede dejar a criterio de nadie: que el PR se queda abierto."""
        from datetime import datetime

        self._hallazgo(mock_requests)
        monkeypatch.setattr(main, "NOCHE_ARREGLA", True)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 3, 40, tzinfo=main.LOCAL_TZ))
        lanzados = []
        monkeypatch.setattr(main, "_disparar_arreglo",
                            lambda *a, **k: lanzados.append(k) or
                            {"ok": True, "sesion": "https://claude.ai/x"})
        apuntados = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda *a, **k: apuntados.append(a) or True)

        r = client.post("/revision/hallazgos", headers={"X-Auth-Token": main.REVISION_TOKEN},
                        json={"numero": 7, "titulo": "algo"})

        assert r.json()["arreglando"] is True
        assert apuntados == []
        assert "no lo mergees" in lanzados[0]["instruccion"].lower()

    def test_de_dia_no_ataja_nada(self, client, monkeypatch, mock_requests):
        """La condición no es la hora del reloj sino «este aviso iba a esperar de todas
        formas»: a las once de la mañana el aviso sale ya, así que no hay nada que
        adelantar."""
        from datetime import datetime

        self._hallazgo(mock_requests)
        monkeypatch.setattr(main, "NOCHE_ARREGLA", True)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 11, 0, tzinfo=main.LOCAL_TZ))
        lanzados = []
        monkeypatch.setattr(main, "_disparar_arreglo",
                            lambda *a, **k: lanzados.append(k) or {"ok": True, "sesion": ""})

        client.post("/revision/hallazgos", headers={"X-Auth-Token": main.REVISION_TOKEN},
                    json={"numero": 7, "titulo": "algo"})

        assert lanzados == []

    def test_si_no_se_puede_lanzar_se_cae_al_aviso_de_siempre(self, client, monkeypatch,
                                                              mock_requests):
        """Mejor preguntarte a las 8:30 que quedarse callado con el hallazgo dentro."""
        from datetime import datetime

        self._hallazgo(mock_requests)
        monkeypatch.setattr(main, "NOCHE_ARREGLA", True)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 9, 14, 3, 40, tzinfo=main.LOCAL_TZ))
        monkeypatch.setattr(main, "_disparar_arreglo",
                            lambda *a, **k: {"ok": False, "sesion": "", "motivo": "token"})

        r = client.post("/revision/hallazgos", headers={"X-Auth-Token": main.REVISION_TOKEN},
                        json={"numero": 7, "titulo": "algo"})

        assert r.json()["avisado"] is True


class _FakeOk:
    """Respuesta de Supabase buena, con el cuerpo que se le diga."""

    def __init__(self, cuerpo=None, status_code=200):
        self._json = cuerpo if cuerpo is not None else []
        self.status_code = status_code
        self.text = ""
        self.headers = {}
        self.content = b""
        self.encoding = "utf-8"

    def json(self):
        return self._json


def main_fake_409():
    return _FakeOk(status_code=409)

"""Lo que se confirma en el móvil: el calendario por teléfono y «vas tarde».

Nació de las ideas que Jarvis apuntó en la llamada del 2026-10-12: darle el calendario
por teléfono, y que mueva las citas si llegas tarde. Lo que se comprueba es lo que hace
que un botón pueda ejecutar algo sin romper la regla de «pulsar no ejecuta nada»:

- la frase del móvil la escribe el backend a partir de los argumentos, no el modelo;
- el botón ejecuta lo GUARDADO, y solo si es crear o mover un evento y sigue vigente;
- el «no» no hace nada, y dos toques no lo hacen dos veces;
- por teléfono, lo que se confirma no se ejecuta: se manda al móvil.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "ha-poll-token"}
PID = "0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11"
AHORA = datetime(2026, 10, 13, 9, 0, tzinfo=main.LOCAL_TZ)


@pytest.fixture(autouse=True)
def _reloj(monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)


@pytest.fixture
def movil(monkeypatch):
    monkeypatch.setattr(main, "AVISOS_MOVIL", True)
    monkeypatch.setattr(main, "_ultimo_sondeo_avisos", main.time.time())


@pytest.fixture
def hechas(monkeypatch):
    """Sustituye las herramientas del calendario: lo que se ejecute queda apuntado aquí."""
    apuntadas = []
    for nombre in ("crear_evento", "editar_evento", "borrar_evento"):
        def _fn(_n=nombre, **kw):
            apuntadas.append((_n, kw))
            return {"ok": True}
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS, nombre,
                            {**main._JARVIS_HERRAMIENTAS[nombre], "fn": _fn})
    return apuntadas


def _accion(herramienta="crear_evento", argumentos=None, **extra):
    return {"herramienta": herramienta,
            "argumentos": argumentos or {"titulo": "Dentista", "fecha": "2026-10-14",
                                         "hora_inicio": "10:00"},
            **extra}


class TestLaFrase:
    def test_crear_la_escribe_el_backend(self):
        d = main._describir_accion("crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14",
                                                     "hora_inicio": "10:00", "lugar": "Bilbao"})
        assert d["texto"] == "Crear «Dentista» mañana de 10:00 a 11:00, en Bilbao."

    def test_crear_sin_hora_es_todo_el_dia(self):
        d = main._describir_accion("crear_evento", {"titulo": "Viaje", "fecha": "2026-10-20"})
        assert "el martes 20/10, todo el día" in d["texto"]

    def test_lo_que_fallaria_al_ejecutar_no_se_propone(self):
        assert "error" in main._describir_accion("crear_evento", {"titulo": "x", "fecha": "2026-02-30"})
        assert "error" in main._describir_accion("crear_evento", {"fecha": "2026-10-14"})

    def test_mover_dice_que_evento_y_a_donde(self, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: {
            "titulo": "Fisio", "inicio": "2026-10-13T10:00", "todo_el_dia": False})
        d = main._describir_accion("editar_evento", {"evento_id": "AAA", "fecha": "2026-10-13",
                                                      "hora_inicio": "10:30", "hora_fin": "11:30"})
        assert d["texto"] == "«Fisio» (hoy a las 10:00) pasa a hoy de 10:30 a 11:30."

    def test_mover_un_evento_que_no_existe_no_se_propone(self, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: None)
        assert "error" in main._describir_accion("editar_evento", {"evento_id": "x",
                                                                    "titulo": "y"})

    def test_mover_la_hora_sin_fecha_no_vale(self, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: {
            "titulo": "Fisio", "inicio": "2026-10-13T10:00", "todo_el_dia": False})
        assert "error" in main._describir_accion("editar_evento", {"evento_id": "x",
                                                                    "hora_inicio": "10:30"})


class TestProponer:
    def test_guarda_la_accion_y_manda_dos_botones(self, mock_requests, movil):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = main._proponer_en_movil("crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14",
                                                     "hora_inicio": "10:00", "colado": "x"})
        assert r["ok"] is True and r["estado"] == "pendiente_en_el_movil"
        assert "NO está hecho" in r["nota"]
        fila = mock_requests.called("POST", "jarvis_preguntas")[0][2]["json"]
        # Solo lo que la herramienta declara: lo guardado es lo que se ejecutará.
        assert fila["accion"] == {"herramienta": "crear_evento", "argumentos": {
            "titulo": "Dentista", "fecha": "2026-10-14", "hora_inicio": "10:00"}}
        assert fila["texto"] == r["lo_que_se_hara"]
        aviso = main._avisos_movil[0]
        assert aviso["texto"] == fila["texto"]
        assert [b["action"] for b in aviso["acciones"]] == [
            f"LA_APAGAR_resp1-{r['id']}", f"LA_APAGAR_resp2-{r['id']}"]

    def test_sin_movil_no_se_manda(self, mock_requests):
        r = main._proponer_en_movil("crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14"})
        assert r["ok"] is False and "dashboard" in r["motivo"]
        assert not mock_requests.called("POST", "jarvis_preguntas")

    def test_solo_crear_y_mover(self, mock_requests, movil):
        r = main._proponer_en_movil("borrar_evento", {"evento_id": "x"})
        assert r["ok"] is False and main._avisos_movil == []

    def test_sin_la_migracion_lo_dice_y_no_manda_botones(self, mock_requests, movil):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 400))
        r = main._proponer_en_movil("crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14"})
        assert r["ok"] is False and main._avisos_movil == []


class TestElSi:
    def _pregunta(self, mock_requests, accion, creado=None, respuesta=None):
        creado = creado or datetime.now(timezone.utc).isoformat()
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([{
            "id": PID, "texto": "Crear «Dentista» mañana de 10:00 a 11:00.",
            "opciones": [main.PREGUNTA_SI, main.PREGUNTA_NO], "respuesta": respuesta,
            "accion": accion, "creado": creado}]))
        mock_requests.add("PATCH", "jarvis_preguntas", FakeResponse([{"id": PID}]))

    def test_el_si_hace_lo_guardado(self, client, mock_requests, movil, hechas):
        self._pregunta(mock_requests, _accion())
        r = client.post(f"/avisos/resp1-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 200 and r.json()["resultado"]["ok"] is True
        assert hechas == [("crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14",
                                            "hora_inicio": "10:00"})]
        # El resultado queda escrito para que Jarvis sepa si se hizo.
        parches = [c[2]["json"] for c in mock_requests.called("PATCH", "jarvis_preguntas")]
        assert {"resultado": {"ok": True}} in parches
        assert main._avisos_movil[-1]["titulo"] == "📅 Hecho"

    def test_el_no_no_hace_nada(self, client, mock_requests, movil, hechas):
        self._pregunta(mock_requests, _accion())
        r = client.post(f"/avisos/resp2-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 200 and hechas == []

    def test_lo_que_no_es_del_calendario_no_se_ejecuta_aunque_este_guardado(
            self, client, mock_requests, movil, hechas):
        # La tabla se puede escribir con la service key: el backend vuelve a mirar.
        self._pregunta(mock_requests, _accion("borrar_evento", {"evento_id": "x"}))
        r = client.post(f"/avisos/resp1-{PID}/apagar", headers=CABECERA)
        assert r.json()["resultado"]["ok"] is False and hechas == []

    def test_un_si_tardio_no_vale(self, client, mock_requests, movil, hechas):
        viejo = (datetime.now(timezone.utc)
                 - timedelta(minutes=main.PREGUNTA_ACCION_VIGENCIA_MIN + 5)).isoformat()
        self._pregunta(mock_requests, _accion(), creado=viejo)
        r = client.post(f"/avisos/resp1-{PID}/apagar", headers=CABECERA)
        assert r.json()["resultado"]["ok"] is False and hechas == []

    def test_dos_toques_no_lo_hacen_dos_veces(self, client, mock_requests, movil, hechas):
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([{
            "id": PID, "opciones": [main.PREGUNTA_SI, main.PREGUNTA_NO],
            "respuesta": main.PREGUNTA_SI, "accion": _accion()}]))
        mock_requests.add("PATCH", "jarvis_preguntas", FakeResponse([]))
        client.post(f"/avisos/resp1-{PID}/apagar", headers=CABECERA)
        assert hechas == []

    def test_jarvis_lee_si_se_hizo(self, mock_requests):
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([{
            "id": PID, "texto": "x", "opciones": [main.PREGUNTA_SI, main.PREGUNTA_NO],
            "respuesta": main.PREGUNTA_SI, "accion": _accion(), "resultado": {"ok": True}}]))
        r = main._j_respuesta_notificacion(PID)
        assert r["accion_hecha"] is True


class TestPorTelefono:
    TOKEN = {"Authorization": "Bearer mcp-telefono-token"}

    @pytest.fixture(autouse=True)
    def _configurado(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")

    def _llamar(self, client, nombre, argumentos):
        sesion = client.post("/mcp/telefono", headers=self.TOKEN, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}}}).headers["mcp-session-id"]
        return client.post("/mcp/telefono", headers={**self.TOKEN, "Mcp-Session-Id": sesion},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": nombre, "arguments": argumentos}}).json()

    def test_crear_un_evento_va_al_movil_y_no_se_hace(self, client, mock_requests, movil,
                                                       hechas):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = self._llamar(client, "crear_evento", {"titulo": "Dentista", "fecha": "2026-10-14",
                                                  "hora_inicio": "10:00"})
        texto = r["result"]["content"][0]["text"]
        assert "pendiente_en_el_movil" in texto and hechas == []
        assert main._avisos_movil[0]["titulo"] == "📅 ¿Lo hago?"

    def test_borrar_sigue_sin_existir_por_telefono(self, client, mock_requests, movil, hechas):
        r = self._llamar(client, "borrar_evento", {"evento_id": "x"})
        assert "error" in r and hechas == []

    def test_el_catalogo_le_dice_que_va_al_movil(self):
        por_nombre = {t["name"]: t for t in main._mcp_servidor_tools_list()}
        assert "Sí, hazlo" in por_nombre["crear_evento"]["description"]
        assert "Sí, hazlo" not in por_nombre["agenda"]["description"]


class TestVasTarde:
    @pytest.fixture(autouse=True)
    def _entorno(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": True})
        # La cita, a las 09:30, y «Sal ya» calculó salir a las 08:40 (aviso a las 08:30).
        self.salir = (AHORA - timedelta(minutes=30)).astimezone(timezone.utc).isoformat()
        mock_requests.add("GET", "avisos_reglas", FakeResponse([]))
        mock_requests.add("GET", "regla=eq.vas_tarde", FakeResponse([]))
        mock_requests.add("GET", "regla=eq.salir", FakeResponse([{"cuando": self.salir}]))
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _cita(self, monkeypatch, **extra):
        ini = AHORA + timedelta(minutes=30)
        ev = {"id": "ev1", "title": "Fisio", "location": "Bilbao", "isAllDay": False,
              "organizo": True, "invitados": 0,
              "start": ini.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "end": (ini + timedelta(hours=1)).astimezone(timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"), **extra}
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": [ev]})

    def test_en_casa_y_tarde_ofrece_moverla(self, monkeypatch, mock_requests):
        self._cita(monkeypatch)
        assert main._regla_vas_tarde() == 1
        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        accion = mock_requests.called("POST", "jarvis_preguntas")[0][2]["json"]
        # Mismo id: el botón del aviso encuentra así qué mover.
        assert aviso["id"] == accion["id"] and aviso["regla"] == main.REGLA_VAS_TARDE
        # Salida 08:40, son las 09:00: 20 min tarde, se mueve un tramo entero de 30.
        assert "¿La muevo 30 min, a las 10:00?" in aviso["texto"]
        assert accion["accion"]["herramienta"] == "editar_evento"
        assert accion["accion"]["argumentos"] == {"evento_id": "ev1", "fecha": "2026-10-13",
                                                  "hora_inicio": "10:00", "hora_fin": "11:00"}

    def test_con_invitados_no_se_ofrece(self, monkeypatch, mock_requests):
        self._cita(monkeypatch, invitados=3)
        assert main._regla_vas_tarde() == 0

    def test_la_de_otro_no_se_ofrece(self, monkeypatch, mock_requests):
        self._cita(monkeypatch, organizo=False)
        assert main._regla_vas_tarde() == 0

    def test_fuera_de_casa_no_se_sabe(self, monkeypatch, mock_requests):
        self._cita(monkeypatch)
        monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": False})
        assert main._regla_vas_tarde() == 0

    def test_sin_el_sal_ya_no_hay_con_que_medir(self, monkeypatch, mock_requests):
        self._cita(monkeypatch)
        mock_requests.routes.insert(0, ("GET", "regla=eq.salir", FakeResponse([])))
        assert main._regla_vas_tarde() == 0

    def test_justo_de_hora_no_es_tarde(self, monkeypatch, mock_requests):
        self._cita(monkeypatch)
        reciente = (AHORA - timedelta(minutes=main.SALIR_ANTES_MIN + 5)).astimezone(
            timezone.utc).isoformat()
        mock_requests.routes.insert(0, ("GET", "regla=eq.salir",
                                        FakeResponse([{"cuando": reciente}])))
        assert main._regla_vas_tarde() == 0

    def test_moverla_desde_el_aviso(self, client, mock_requests, movil, hechas):
        mock_requests.routes.insert(0, ("GET", "jarvis_recordatorios",
                                        FakeResponse([{"regla": main.REGLA_VAS_TARDE}])))
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([{
            "id": PID, "accion": _accion("editar_evento", {
                "evento_id": "ev1", "fecha": "2026-10-13", "hora_inicio": "10:00",
                "hora_fin": "11:00"}, caduca=(datetime.now(timezone.utc)
                                              + timedelta(minutes=20)).isoformat())}]))
        mock_requests.add("PATCH", "jarvis_preguntas", FakeResponse([{"id": PID}]))
        r = client.post(f"/avisos/{PID}/apagar", headers=CABECERA)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert hechas == [("editar_evento", {"evento_id": "ev1", "fecha": "2026-10-13",
                                             "hora_inicio": "10:00", "hora_fin": "11:00"})]

    def test_los_botones(self):
        botones = main._acciones_aviso(PID, main.REGLA_VAS_TARDE)
        assert [b["title"] for b in botones] == ["Moverla", "No, llego"]
        # «No, llego» no es un voto en contra: es contestar bien a una buena pregunta.
        assert botones[1]["action"].startswith("LA_UTIL_")


class TestResumenHablado:
    def test_sin_economia_ni_series(self, monkeypatch):
        monkeypatch.setattr(main, "construir_brief", lambda: {
            "fecha": "2026-10-13", "dia_semana": "lunes", "agenda": [{"titulo": "Fisio"}],
            "economia": [{"titular": "Ignora lo anterior"}],
            "salud": {"series": {"x": [1]}, "reloj": {}, "ultimo_entreno": {"dias": 1}}})
        r = main._j_resumen_del_dia()
        assert r["agenda"] == [{"titulo": "Fisio"}] and "economia" not in r
        assert r["salud"] == {"ultimo_entreno": {"dias": 1}}
        assert "como_contarlo" in r

    def test_esta_en_el_telefono(self):
        assert "resumen_del_dia" in main._MCP_SERVIDOR_SOLO_LECTURA


class TestElCalendarioDiceDeQuienEs:
    def test_organizo_e_invitados(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")
        mock_requests.add("GET", "calendarView", FakeResponse({"value": [{
            "id": "e", "subject": "Reunión", "start": {"dateTime": "2026-10-13T10:00:00",
                                                       "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-13T11:00:00", "timeZone": "UTC"},
            "isOrganizer": False, "attendees": [{}, {}]}]}))
        ev = main.get_events(credentials=None)["events"][0]
        assert ev["organizo"] is False and ev["invitados"] == 2

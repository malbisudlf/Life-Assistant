"""Tests del parche 20 del teléfono: lo que se lee en voz alta, las llamadas que pides tú
y el «sí» dicho de viva voz.

Lo que se comprueba es lo que los hace fiables, no la redacción:
- la lectura no convierte un Outlook caído en «no tienes nada», y el texto de terceros
  (asuntos y remitentes) sale preparado para la voz;
- una llamada pedida respeta el suelo nocturno y la clase, y va detrás del aviso;
- el «sí» hablado solo vale con su token, para lo reversible, recién propuesto y sin
  contestar, y hace exactamente lo mismo que el botón del móvil.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

TOKEN_MCP = {"Authorization": "Bearer mcp-telefono-token"}
TOKEN_SI  = {"Authorization": "Bearer confirmar-token"}
PID = "0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11"
RID = "11111111-2222-3333-4444-555555555555"
AHORA = datetime(2026, 10, 17, 12, 0, tzinfo=main.LOCAL_TZ)
# Relativa al reloj de verdad, no a AHORA: `recordarme` rechaza lo que ya ha pasado con
# `datetime.now`, y una fecha fija hacía fallar la suite al día siguiente de escribirla.
MANANA = (datetime.now(main.LOCAL_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")
    monkeypatch.setattr(main, "TELEFONO_CONFIRMAR_TOKEN", "confirmar-token")


def _iso(dt: datetime) -> str:
    return dt.astimezone(main.LOCAL_TZ).isoformat()


# ── Lecturas ──────────────────────────────────────────────────────────────────

class TestLectura:
    def test_sin_token_no_entra(self, client):
        assert client.get("/telefono/lectura?que=semana").status_code == 401
        assert client.get("/telefono/lectura?que=semana", headers=TOKEN_SI).status_code == 401

    def test_que_desconocido_es_422(self, client):
        assert client.get("/telefono/lectura?que=todo", headers=TOKEN_MCP).status_code == 422

    def test_la_semana_por_dias(self, client, monkeypatch):
        manana = AHORA + timedelta(days=1)
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": [
            {"title": "Dentista", "location": "Calle Mayor",
             "start": _iso(manana.replace(hour=10)), "end": _iso(manana.replace(hour=11))},
            {"title": "Lejano", "start": _iso(AHORA + timedelta(days=20)),
             "end": _iso(AHORA + timedelta(days=20, hours=1))},
        ]})
        monkeypatch.setattr(main, "get_class_events", lambda credentials=None: {"events": []})
        r = client.get("/telefono/lectura?que=semana", headers=TOKEN_MCP).json()
        assert r["ok"] is True and r["nombre"] == "la agenda de la semana"
        assert [s["titulo"] for s in r["secciones"]] == ["Mañana"]
        texto = " ".join(r["secciones"][0]["trozos"])
        assert "A las 10:00, Dentista, en Calle Mayor." in texto
        assert "Lejano" not in texto

    def test_outlook_caido_no_es_semana_libre(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"error": "x"})
        monkeypatch.setattr(main, "get_class_events", lambda credentials=None: {"events": []})
        r = client.get("/telefono/lectura?que=semana", headers=TOKEN_MCP).json()
        assert r["ok"] is False and "Outlook" in r["frase"]

    def test_el_correo_dice_quien_sin_direcciones(self, client, monkeypatch):
        monkeypatch.setattr(main, "_ultimo_parte", lambda: {
            "fecha": AHORA.date().isoformat(), "frase": "Tres correos, uno pide respuesta.",
            "items": [
                {"area": "correo", "titulo": "Factura de octubre",
                 "datos": {"de": "Ane Etxeberria <ane@ejemplo.test>", "borrador": True}},
                {"area": "correo", "titulo": "Hola", "datos": {"de": "luis@ejemplo.test"}},
                {"area": "codigo", "titulo": "Arreglado el test de la alarma"},
            ]})
        r = client.get("/telefono/lectura?que=correo", headers=TOKEN_MCP).json()
        texto = " ".join(t for s in r["secciones"] for t in s["trozos"])
        assert "De Ane Etxeberria: Factura de octubre" in texto
        assert "respuesta en borradores" in texto
        assert "De luis: Hola" in texto
        assert "@" not in texto
        assert "Arreglado el test de la alarma" in texto

    def test_desde_sigue_donde_se_corto(self, client, monkeypatch):
        monkeypatch.setattr(main, "_j_tareas", lambda: {"activo": True, "tareas": [
            {"titulo": "Pagar el seguro", "fecha": "2026-10-10"},
            {"titulo": "Llamar al taller", "fecha": None}]})
        todo = client.get("/telefono/lectura?que=tareas", headers=TOKEN_MCP).json()
        assert [s["titulo"] for s in todo["secciones"]] == ["Vencidas", "Sin fecha"]
        resto = client.get("/telefono/lectura?que=tareas&desde=2", headers=TOKEN_MCP).json()
        assert [s["titulo"] for s in resto["secciones"]] == ["Sin fecha"]

    def test_tareas_apagadas_lo_dice(self, client, monkeypatch):
        monkeypatch.setattr(main, "_j_tareas", lambda: {"activo": False,
                                                        "motivo": "To Do está apagado."})
        r = client.get("/telefono/lectura?que=tareas", headers=TOKEN_MCP).json()
        assert r == {"ok": False, "frase": "To Do está apagado."}

    def test_un_fallo_se_dice_en_vez_de_reventar(self, client, monkeypatch):
        def _revienta():
            raise RuntimeError("Graph")
        monkeypatch.setattr(main, "_j_tareas", _revienta)
        r = client.get("/telefono/lectura?que=tareas", headers=TOKEN_MCP)
        assert r.status_code == 200 and r.json()["ok"] is False


# ── Llamadas que pides tú ─────────────────────────────────────────────────────

@pytest.fixture
def centralita(monkeypatch):
    monkeypatch.setattr(main, "_telefono_configurado", lambda: True)
    hechas = []

    def _llamar(texto, rid="", contexto="", aunque_duermas=False, solo_centralita=False):
        hechas.append({"texto": texto, "contexto": contexto,
                       "aunque_duermas": aunque_duermas, "solo_centralita": solo_centralita})
        return True
    monkeypatch.setattr(main, "_llamar", _llamar)
    monkeypatch.setattr(main, "_lugar_en_memoria", lambda: {})
    return hechas


class TestRecordarmeConLlamada:
    def test_se_apunta_con_su_huella(self, mock_requests, centralita):
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([{"id": RID}], 201))
        r = main._j_recordarme("Leerte el briefing", MANANA, "08:10", leer="briefing")
        assert r["ok"] is True and r["llamada"] is True
        fila = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert fila["huella"].startswith("llamar:briefing:")
        assert "regla" not in fila          # lo pediste tú: fuera del presupuesto

    def test_sin_llamar_no_lleva_huella(self, mock_requests, centralita):
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([{"id": RID}], 201))
        main._j_recordarme("Comprar pan", MANANA, "18:00")
        assert "huella" not in mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]

    def test_de_madrugada_no_se_deja_apuntar(self, mock_requests, centralita):
        r = main._j_recordarme("Despiértame", MANANA, "05:30", llamar=True)
        assert r["ok"] is False and "poner_alarma" in r["motivo"]
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_sin_centralita_lo_dice(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_telefono_configurado", lambda: False)
        r = main._j_recordarme("x", MANANA, "12:00", llamar="true")
        assert r["ok"] is False and "centralita" in r["motivo"]

    def test_leer_algo_desconocido_no_vale(self, mock_requests, centralita):
        r = main._j_recordarme("x", MANANA, "12:00", leer="poemas")
        assert r["ok"] is False


class TestLaLlamadaPedida:
    def test_suena_y_pide_leer(self, centralita):
        assert main._llamada_pedida(RID, "Leerte el briefing", "llamar:briefing:abc")
        llamada = centralita[0]
        assert llamada["aunque_duermas"] and llamada["solo_centralita"]
        assert "📖 LEER: briefing" in llamada["contexto"]
        assert "No es una avería" in llamada["contexto"]

    def test_de_noche_no_suena(self, centralita, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 10, 17, 3, 0, tzinfo=main.LOCAL_TZ))
        assert not main._llamada_pedida(RID, "x", "llamar:-:abc") and centralita == []

    def test_en_clase_no_suena(self, centralita, monkeypatch):
        monkeypatch.setattr(main, "_en_clase",
                            lambda lugar: {"fin": AHORA + timedelta(minutes=30), "titulo": "SO"})
        assert not main._llamada_pedida(RID, "x", "llamar:-:abc") and centralita == []

    def test_dentro_del_despacho_va_detras_del_aviso(self, mock_requests, centralita, monkeypatch):
        monkeypatch.setattr(main, "enviar_correo", lambda *a, **k: None)
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": RID, "cuando": "2026-10-17T10:00:00+00:00", "texto": "Leerte el briefing",
            "regla": None, "huella": "llamar:briefing:abc"}]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": RID}]))
        assert main._despachar_recordatorios() == {"recordatorios": 1, "avisos_llamados": 1}
        assert len(centralita) == 1

    def test_un_fallo_llamando_no_libera_el_aviso(self, mock_requests, centralita, monkeypatch):
        monkeypatch.setattr(main, "enviar_correo", lambda *a, **k: None)
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": RID, "cuando": "2026-10-17T10:00:00+00:00", "texto": "x",
            "regla": None, "huella": "llamar:-:abc"}]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": RID}]))

        def _revienta(*a, **k):
            raise RuntimeError("centralita rota")
        monkeypatch.setattr(main, "_llamada_pedida", _revienta)
        assert main._despachar_recordatorios() == {"recordatorios": 1}
        liberados = [c for c in mock_requests.called("PATCH", "jarvis_recordatorios")
                     if c[2]["json"].get("enviado") is False]
        assert liberados == []


class TestElRelojRapido:
    """Lo pedido sale por el tick de alarmas (60 s), no solo por el brief-tick (5 min):
    «llámame en un minuto» llegó cuatro minutos tarde el 2026-10-17."""
    CABECERA = {"X-Auth-Token": "ha-poll-token"}

    @pytest.fixture
    def lanzados(self, monkeypatch):
        hechos = []
        monkeypatch.setattr(main, "_lanzar_despacho_pedidos", lambda: hechos.append(1))
        return hechos

    def test_recordarme_adelanta_el_reloj(self, mock_requests, centralita):
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([{"id": RID}], 201))
        main._j_recordarme("Leerte el briefing", MANANA, "08:10", leer="briefing")
        assert main._recordatorio_siguiente < float("inf")

    def test_sin_nada_pendiente_el_tick_no_lanza_nada(self, client, mock_requests, lanzados):
        assert client.get("/ha/alarma-tick", headers=self.CABECERA).status_code == 200
        assert lanzados == []

    def test_cuando_toca_el_tick_lo_lanza(self, client, mock_requests, lanzados):
        main._recordatorio_siguiente = main.time.time() - 1
        assert client.get("/ha/alarma-tick", headers=self.CABECERA).json()["escalar"] == 0
        assert lanzados == [1]

    def test_tras_un_reinicio_mira_una_vez(self, client, mock_requests, lanzados):
        main._recordatorio_siguiente = None
        client.get("/ha/alarma-tick", headers=self.CABECERA)
        assert lanzados == [1]

    def test_despacha_solo_lo_pedido_y_apunta_lo_siguiente(self, mock_requests, centralita,
                                                          monkeypatch):
        monkeypatch.setattr(main, "enviar_correo", lambda *a, **k: None)
        luego = datetime.now(timezone.utc) + timedelta(hours=2)

        def _get(url, **kw):
            if "cuando=lte." in url:
                return FakeResponse([{"id": RID, "cuando": "2026-10-17T10:00:00+00:00",
                                      "texto": "Leerte el briefing", "regla": None,
                                      "huella": "llamar:briefing:abc"}])
            return FakeResponse([{"cuando": luego.isoformat()}])
        mock_requests.add("GET", "jarvis_recordatorios", _get)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": RID}]))
        main._recordatorio_siguiente = None
        main._recordatorio_corriendo = True
        main._despachar_pedidos()
        vencidos = [c for c in mock_requests.called("GET", "jarvis_recordatorios")
                    if "cuando=lte." in c[1]]
        assert "regla=is.null" in vencidos[0][1]
        assert len(centralita) == 1
        assert abs(main._recordatorio_siguiente - luego.timestamp()) < 1
        assert main._recordatorio_corriendo is False

    def test_sin_nada_mas_se_duerme(self, mock_requests):
        main._despachar_pedidos()
        assert main._recordatorio_siguiente == float("inf")

    def test_lo_apuntado_a_mitad_no_se_pierde(self, mock_requests):
        en_cinco = datetime.now(timezone.utc) + timedelta(minutes=5)

        def _get(url, **kw):
            if "cuando=lte." in url:
                main._recordatorio_marcar(en_cinco)      # un recordarme, a mitad
            return FakeResponse([])
        mock_requests.add("GET", "jarvis_recordatorios", _get)
        main._despachar_pedidos()
        assert main._recordatorio_siguiente <= en_cinco.timestamp()

    def test_si_supabase_falla_reintenta_al_minuto(self, mock_requests):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([], 500))
        main._recordatorio_corriendo = True
        main._despachar_pedidos()
        assert main._recordatorio_siguiente <= main.time.time() + 61
        assert main._recordatorio_corriendo is False


# ── El «sí» dicho por teléfono ────────────────────────────────────────────────

@pytest.fixture
def hechas(monkeypatch):
    apuntadas = []
    for nombre in ("crear_evento", "editar_evento", "borrar_evento", "crear_tarea"):
        def _fn(_n=nombre, **kw):
            apuntadas.append((_n, kw))
            return {"ok": True}
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS, nombre,
                            {**main._JARVIS_HERRAMIENTAS[nombre], "fn": _fn})
    return apuntadas


def _pregunta(mock_requests, herramienta="crear_evento", argumentos=None, hace_seg=10,
              respuesta=None, patch_vacio=False):
    creado = (datetime.now(timezone.utc) - timedelta(seconds=hace_seg)).isoformat()
    mock_requests.add("GET", "jarvis_preguntas", FakeResponse([{
        "id": PID, "texto": "Crear «Dentista» mañana de 10:00 a 11:00.",
        "opciones": [main.PREGUNTA_SI, main.PREGUNTA_NO], "respuesta": respuesta,
        "accion": {"herramienta": herramienta,
                   "argumentos": argumentos or {"titulo": "Dentista", "fecha": MANANA,
                                                "hora_inicio": "10:00"}},
        "creado": creado}]))
    mock_requests.add("PATCH", "jarvis_preguntas",
                      FakeResponse([] if patch_vacio else [{"id": PID}]))


class TestElSiHablado:
    def test_sin_su_token_no_entra(self, client, mock_requests):
        _pregunta(mock_requests)
        assert client.get(f"/telefono/confirmar/{PID}").status_code == 401
        # El token del MCP (el que tiene Claude) no vale aquí.
        assert client.get(f"/telefono/confirmar/{PID}", headers=TOKEN_MCP).status_code == 401
        assert client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_MCP,
                           json={"respuesta": "si"}).status_code == 401

    def test_sin_token_configurado_nada_pasa(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "TELEFONO_CONFIRMAR_TOKEN", "")
        assert client.get(f"/telefono/confirmar/{PID}",
                          headers={"Authorization": "Bearer "}).status_code == 401

    def test_ver_devuelve_la_frase_del_backend(self, client, mock_requests):
        _pregunta(mock_requests)
        r = client.get(f"/telefono/confirmar/{PID}", headers=TOKEN_SI).json()
        assert r == {"ok": True, "frase": "Crear «Dentista» mañana de 10:00 a 11:00."}

    def test_el_si_hace_lo_guardado(self, client, mock_requests, hechas):
        _pregunta(mock_requests)
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "si"}).json()
        assert r["hecho"] is True and r["frase"].startswith("Hecho.")
        assert hechas == [("crear_evento", {"titulo": "Dentista", "fecha": MANANA,
                                            "hora_inicio": "10:00"})]
        assert PID in main._avisos_borrar or not main._movil_vivo()

    def test_el_no_no_hace_nada(self, client, mock_requests, hechas):
        _pregunta(mock_requests)
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "no"}).json()
        assert r["frase"] == "Vale, no lo hago." and hechas == []

    def test_solo_si_o_no(self, client, mock_requests):
        _pregunta(mock_requests)
        assert client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                           json={"respuesta": "vale"}).status_code == 422

    def test_borrar_se_queda_en_el_boton(self, client, mock_requests, hechas):
        _pregunta(mock_requests, "borrar_evento", {"evento_id": "ev1"})
        assert client.get(f"/telefono/confirmar/{PID}", headers=TOKEN_SI).json()["ok"] is False
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "si"}).json()
        assert r["ok"] is False and hechas == []

    def test_lo_propuesto_hace_rato_se_queda_en_el_boton(self, client, mock_requests, hechas):
        _pregunta(mock_requests, hace_seg=main.PREGUNTA_HABLADA_SEG + 30)
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "si"}).json()
        assert r["ok"] is False and hechas == []

    def test_ya_contestado_en_el_movil(self, client, mock_requests, hechas):
        _pregunta(mock_requests, respuesta=main.PREGUNTA_SI)
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "si"}).json()
        assert r["ok"] is False and hechas == []

    def test_mover_una_reunion_con_gente_se_queda_en_el_boton(self, client, mock_requests,
                                                              hechas, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: {
            "titulo": "Reunión", "inicio": "2026-10-18T10:00", "todo_el_dia": False,
            "invitados": 2, "organizo": True, "asistentes": 2})
        _pregunta(mock_requests, "editar_evento", {"evento_id": "ev1", "fecha": MANANA,
                                                   "hora_inicio": "11:00"})
        r = client.get(f"/telefono/confirmar/{PID}", headers=TOKEN_SI).json()
        assert r["ok"] is False and "más gente" in r["motivo"]

    def test_mover_una_cita_tuya_sola_si(self, client, mock_requests, hechas, monkeypatch):
        monkeypatch.setattr(main, "_evento_graph", lambda i: {
            "titulo": "Fisio", "inicio": "2026-10-18T10:00", "todo_el_dia": False,
            "invitados": 0, "organizo": True, "asistentes": 0})
        _pregunta(mock_requests, "editar_evento", {"evento_id": "ev1", "fecha": MANANA,
                                                   "hora_inicio": "11:00"})
        r = client.post(f"/telefono/confirmar/{PID}", headers=TOKEN_SI,
                        json={"respuesta": "si"}).json()
        assert r["hecho"] is True and hechas[0][0] == "editar_evento"


class TestLaPropuesta:
    def test_lleva_la_linea_para_la_llamada(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "AVISOS_MOVIL", True)
        monkeypatch.setattr(main, "_ultimo_sondeo_avisos", main.time.time())
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = main._proponer_en_movil("crear_tarea", {"titulo": "Pasar el contrato"})
        assert r["linea_para_la_llamada"] == f"✅ CONFIRMAR: {r['id']}"

    def test_borrar_no_la_lleva(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "AVISOS_MOVIL", True)
        monkeypatch.setattr(main, "_ultimo_sondeo_avisos", main.time.time())
        monkeypatch.setattr(main, "_evento_graph", lambda i: {
            "titulo": "Fisio", "inicio": "2026-10-18T10:00", "todo_el_dia": False,
            "invitados": 0})
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = main._proponer_en_movil("borrar_evento", {"evento_id": "ev1"})
        assert r["ok"] is True and "linea_para_la_llamada" not in r

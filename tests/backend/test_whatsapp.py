"""WhatsApp en modo lectura: a quién le debes respuesta.

Lo que se comprueba aquí es lo que sostiene la idea (`docs/WHATSAPP.md`): que apagado no
se guarda nada, que el puente solo entra con su token y por cabecera, que un grupo o un
texto no llegan nunca a Supabase, que «pendiente» es una comparación de dos horas y no
de un modelo, y que un puente que se calla acaba en un aviso en vez de en un silencio.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "whatsapp-token"}
ANA  = "34600000001@s.whatsapp.net"
LUIS = "34600000002@s.whatsapp.net"
ANON = "123456789012345@lid"
AHORA = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)


def _hace(horas):
    return (AHORA - timedelta(hours=horas)).isoformat()


@pytest.fixture
def encendido(monkeypatch):
    monkeypatch.setattr(main, "WHATSAPP_LEER", True)


class TestLaPuerta:
    def test_sin_token_no_entra(self, client, encendido, mock_requests):
        r = client.post("/whatsapp/evento", json={"tipo": "estado", "conectado": True})
        assert r.status_code == 403

    def test_el_token_por_la_query_no_vale(self, client, encendido, mock_requests):
        """Integración nueva: el token solo por cabecera. Por la query acabaría escrito
        en el log de uvicorn, que es de donde salió la rotación del de HA."""
        r = client.post("/whatsapp/evento?token=whatsapp-token",
                        json={"tipo": "estado", "conectado": True})
        assert r.status_code == 403

    def test_apagado_responde_503_y_no_guarda_nada(self, client, mock_requests):
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats", "chats": [{"chat": ANA, "suyo": _hace(30)}]})
        assert r.status_code == 503
        assert "WHATSAPP_LEER" in r.json()["detail"]
        assert mock_requests.called("POST", "whatsapp_apuntar") == []

    def test_sin_token_configurado_no_entra_nadie(self, client, encendido, monkeypatch,
                                                  mock_requests):
        monkeypatch.setattr(main, "WHATSAPP_TOKEN", "")
        r = client.post("/whatsapp/evento", headers={"X-Auth-Token": ""},
                        json={"tipo": "estado", "conectado": True})
        assert r.status_code == 403


class TestLoQueSeGuarda:
    def test_solo_horas_y_nombre_nunca_texto(self, client, encendido, mock_requests):
        """Aunque el puente mandara un campo de más, el modelo no lo recoge y no viaja."""
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats",
            "chats": [{"chat": ANA, "nombre": "Ana", "suyo": _hace(30),
                       "texto": "¿me pasas el contrato?"}]})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "guardados": 1, "descartados": 0}
        cuerpo = mock_requests.called("POST", "rpc/whatsapp_apuntar")[0][2]["json"]
        assert cuerpo == {"filas": [{"chat": ANA, "nombre": "Ana",
                                     "suyo": (AHORA - timedelta(hours=30)).isoformat(),
                                     "mio": None}]}
        assert "contrato" not in str(cuerpo)

    def test_los_grupos_no_pasan(self, client, encendido, mock_requests):
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats",
            "chats": [{"chat": "120363000000000000@g.us", "suyo": _hace(30)},
                      {"chat": "status@broadcast", "suyo": _hace(30)},
                      {"chat": ANON, "suyo": _hace(30)}]})
        assert r.json() == {"ok": True, "guardados": 1, "descartados": 2}
        filas = mock_requests.called("POST", "rpc/whatsapp_apuntar")[0][2]["json"]["filas"]
        assert [f["chat"] for f in filas] == [ANON]

    def test_un_chat_repetido_se_funde_con_lo_mas_reciente(self, client, encendido,
                                                           mock_requests):
        """El historial trae varios mensajes de cada conversación, y Postgres no deja
        tocar la misma fila dos veces en un `on conflict`."""
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats",
            "chats": [{"chat": ANA, "suyo": _hace(50)},
                      {"chat": ANA, "nombre": "Ana", "mio": _hace(40)},
                      {"chat": ANA, "suyo": _hace(30)}]})
        assert r.json()["guardados"] == 1
        fila = mock_requests.called("POST", "rpc/whatsapp_apuntar")[0][2]["json"]["filas"][0]
        assert fila["suyo"] == (AHORA - timedelta(hours=30)).isoformat()
        assert fila["mio"] == (AHORA - timedelta(hours=40)).isoformat()
        assert fila["nombre"] == "Ana"

    def test_una_hora_en_el_futuro_no_se_guarda(self, client, encendido, mock_requests):
        """Un reloj mal puesto en el puente dejaría esa hora como «lo último» para siempre."""
        futuro = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats", "chats": [{"chat": ANA, "suyo": futuro}]})
        assert r.json() == {"ok": True, "guardados": 0, "descartados": 1}
        assert mock_requests.called("POST", "whatsapp_apuntar") == []

    def test_si_supabase_falla_el_puente_se_entera(self, client, encendido, mock_requests):
        """El puente es una máquina que no lee el cuerpo: un 200 con el error dentro
        sería indistinguible de haberlo guardado."""
        mock_requests.add("POST", "whatsapp_apuntar", FakeResponse({"message": "x"}, 404))
        r = client.post("/whatsapp/evento", headers=CABECERA, json={
            "tipo": "chats", "chats": [{"chat": ANA, "suyo": _hace(30)}]})
        assert r.status_code == 502

    def test_el_limite_de_chats_por_envio(self, client, encendido, mock_requests):
        chats = [{"chat": f"{34600000000 + i}@s.whatsapp.net", "suyo": _hace(30)}
                 for i in range(main.WHATSAPP_MAX_CHATS + 1)]
        r = client.post("/whatsapp/evento", headers=CABECERA, json={"tipo": "chats",
                                                                     "chats": chats})
        assert r.status_code == 422


class TestQueEsPendiente:
    def _filas(self, **chats):
        return [{"chat": c, "nombre": n, "ultimo_suyo": s, "ultimo_mio": m}
                for c, (n, s, m) in chats.items()]

    def test_su_ultimo_mensaje_sin_respuesta_y_con_horas(self):
        filas = [
            {"chat": ANA,  "nombre": "Ana",  "ultimo_suyo": _hace(30), "ultimo_mio": _hace(40)},
            {"chat": LUIS, "nombre": "Luis", "ultimo_suyo": _hace(30), "ultimo_mio": _hace(20)},
        ]
        pendientes = main._whatsapp_pendientes(filas, AHORA)
        assert [p["nombre"] for p in pendientes] == ["Ana"]
        assert pendientes[0]["horas"] == 30

    def test_una_conversacion_en_curso_no_es_pendiente(self):
        filas = [{"chat": ANA, "nombre": "Ana", "ultimo_suyo": _hace(2), "ultimo_mio": None}]
        assert main._whatsapp_pendientes(filas, AHORA) == []

    def test_lo_de_hace_semanas_ya_no_cuenta(self):
        """Un «ok» sin contestar de hace un mes es una conversación que terminó así."""
        filas = [{"chat": ANA, "nombre": "Ana",
                  "ultimo_suyo": _hace(24 * (main.WHATSAPP_VENTANA_DIAS + 1)), "ultimo_mio": None}]
        assert main._whatsapp_pendientes(filas, AHORA) == []

    def test_los_ignorados_no_cuentan(self, monkeypatch):
        monkeypatch.setattr(main, "WHATSAPP_IGNORAR", {ANA})
        filas = [{"chat": ANA, "nombre": "Ana", "ultimo_suyo": _hace(30), "ultimo_mio": None}]
        assert main._whatsapp_pendientes(filas, AHORA) == []

    def test_sin_nombre_se_dice_el_numero(self):
        filas = [{"chat": ANA, "nombre": None, "ultimo_suyo": _hace(30), "ultimo_mio": None},
                 {"chat": ANON, "nombre": "", "ultimo_suyo": _hace(29), "ultimo_mio": None}]
        nombres = [p["nombre"] for p in main._whatsapp_pendientes(filas, AHORA)]
        assert nombres == ["+34600000001", "alguien sin nombre guardado"]

    def test_los_mas_antiguos_primero(self):
        filas = [{"chat": ANA, "nombre": "Ana", "ultimo_suyo": _hace(30), "ultimo_mio": None},
                 {"chat": LUIS, "nombre": "Luis", "ultimo_suyo": _hace(70), "ultimo_mio": None}]
        assert [p["nombre"] for p in main._whatsapp_pendientes(filas, AHORA)] == ["Luis", "Ana"]


class TestLaFrase:
    def test_cabe_en_un_aviso_y_no_parte_nombres(self):
        pendientes = [{"nombre": f"Contacto número {i}", "horas": 30} for i in range(20)]
        frase = main._frase_whatsapp(pendientes)
        assert len(frase) <= main.RECORDATORIO_MAX_TEXTO
        assert frase.endswith("más.")
        assert "Contacto número 0 (1 día)" in frase

    def test_dias(self):
        frase = main._frase_whatsapp([{"nombre": "Ana", "horas": 30},
                                      {"nombre": "Luis", "horas": 75}])
        assert frase == "Sin contestar en WhatsApp: Ana (1 día), Luis (3 días)."


class TestElAvisoDelDia:
    @pytest.fixture
    def a_mediodia(self, monkeypatch, encendido):
        monkeypatch.setattr(main, "_ahora_local", lambda: AHORA.astimezone(main.LOCAL_TZ))
        # El puente acaba de hablar: aquí se prueba el aviso de pendientes, no el de caído.
        main._whatsapp_senal(True)

    def test_avisa_una_vez_al_dia_con_los_pendientes(self, a_mediodia, mock_requests):
        mock_requests.add("GET", "/rest/v1/whatsapp_chats", FakeResponse([
            {"chat": ANA, "nombre": "Ana", "ultimo_suyo": _hace(30), "ultimo_mio": None}]))
        assert main._regla_whatsapp() == 1
        aviso = mock_requests.called("POST", "/rest/v1/jarvis_recordatorios")[0][2]["json"]
        assert aviso["regla"] == main.REGLA_WHATSAPP
        assert aviso["texto"] == "Sin contestar en WhatsApp: Ana (1 día)."
        assert aviso["id"] == main._uuid_aviso_whatsapp("2026-09-28")
        # El segundo tick del día no vuelve ni a preguntar.
        assert main._regla_whatsapp() == 0
        assert len(mock_requests.called("GET", "/rest/v1/whatsapp_chats")) == 1

    def test_antes_de_la_hora_no_pregunta(self, monkeypatch, encendido, mock_requests):
        main._whatsapp_senal(True)
        temprano = AHORA.astimezone(main.LOCAL_TZ).replace(hour=8)
        monkeypatch.setattr(main, "_ahora_local", lambda: temprano)
        assert main._regla_whatsapp() == 0
        assert mock_requests.called("GET", "whatsapp_chats") == []

    def test_sin_pendientes_no_hay_aviso(self, a_mediodia, mock_requests):
        mock_requests.add("GET", "/rest/v1/whatsapp_chats", FakeResponse([]))
        assert main._regla_whatsapp() == 0
        assert mock_requests.called("POST", "jarvis_recordatorios") == []

    def test_apagado_no_hace_nada(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "_ahora_local", lambda: AHORA.astimezone(main.LOCAL_TZ))
        assert main._regla_whatsapp() == 0
        assert mock_requests.calls == []

    def test_un_supabase_caido_no_se_toma_por_nada_pendiente(self, a_mediodia, mock_requests):
        """Si falla la lectura, el día no se da por mirado: el siguiente tick reintenta."""
        mock_requests.add("GET", "/rest/v1/whatsapp_chats", FakeResponse({"x": 1}, 500))
        assert main._regla_whatsapp() == 0
        assert main._whatsapp_avisado_dia is None

    def test_va_en_el_tick_de_reglas(self):
        assert "whatsapp" in dict(main._REGLAS)


class TestElPuenteCaido:
    def test_sin_senal_desde_hace_horas_avisa_una_vez(self, monkeypatch, encendido,
                                                      mock_requests):
        monkeypatch.setattr(main, "_whatsapp_arranque",
                            main.time.time() - (main.WHATSAPP_SILENCIO_HORAS + 1) * 3600)
        assert main._vigilar_puente_whatsapp() == 1
        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert aviso["regla"] == main.REGLA_WHATSAPP_PUENTE
        assert main._vigilar_puente_whatsapp() == 0

    def test_recien_arrancado_no_se_da_por_caido(self, encendido, mock_requests):
        """Sin señal todavía, se cuenta desde el arranque del backend: un reinicio no
        puede convertir al puente en caído."""
        assert main._vigilar_puente_whatsapp() == 0

    def test_la_sesion_cerrada_avisa_aunque_el_puente_hable(self, client, encendido,
                                                            mock_requests):
        r = client.post("/whatsapp/evento", headers=CABECERA,
                        json={"tipo": "estado", "conectado": False, "motivo": "sesion_cerrada"})
        assert r.status_code == 200
        assert main._vigilar_puente_whatsapp() == 1
        assert "vincular" in mock_requests.called(
            "POST", "jarvis_recordatorios")[0][2]["json"]["texto"]

    def test_al_volver_se_rearma(self, client, encendido, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "_whatsapp_arranque",
                            main.time.time() - (main.WHATSAPP_SILENCIO_HORAS + 1) * 3600)
        assert main._vigilar_puente_whatsapp() == 1
        client.post("/whatsapp/evento", headers=CABECERA,
                    json={"tipo": "estado", "conectado": True})
        assert main._whatsapp_estado["caido_avisado"] is False
        assert main._whatsapp_puente()["mudo"] is False


class TestParaElUsuario:
    def test_el_endpoint_de_pendientes(self, client, auth_headers, encendido, mock_requests):
        main._whatsapp_senal(True)
        mock_requests.add("GET", "/rest/v1/whatsapp_chats", FakeResponse([
            {"chat": ANA, "nombre": "Ana",
             "ultimo_suyo": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
             "ultimo_mio": None}]))
        r = client.get("/whatsapp/pendientes", headers=auth_headers)
        assert r.status_code == 200
        datos = r.json()
        assert datos["activo"] is True
        assert [p["nombre"] for p in datos["pendientes"]] == ["Ana"]
        assert datos["puente"]["conectado"] is True

    def test_apagado_lo_dice(self, client, auth_headers, mock_requests):
        r = client.get("/whatsapp/pendientes", headers=auth_headers)
        assert r.json()["activo"] is False
        assert mock_requests.calls == []

    def test_sin_sesion_no(self, client):
        assert client.get("/whatsapp/pendientes").status_code in (401, 403)

    def test_jarvis_solo_ve_la_herramienta_encendido(self, monkeypatch):
        nombres = lambda: {f["function"]["name"] for f in main._jarvis_esquema()}  # noqa: E731
        assert "whatsapp_pendientes" not in nombres()
        monkeypatch.setattr(main, "WHATSAPP_LEER", True)
        assert "whatsapp_pendientes" in nombres()
        assert main._JARVIS_HERRAMIENTAS["whatsapp_pendientes"]["confirmar"] is False

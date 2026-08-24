"""Tests de la revisión nocturna accionable: del issue al botón, y del botón al agente.

Lo que se comprueba es lo de siempre en este proyecto, aplicado a un camino nuevo: que
una decisión se tome UNA vez (la transición es un PATCH condicional, no un GET y luego
un UPDATE), que un disparo fallido no se coma la decisión, y que pulsar un botón y que
no pase nada visible deje de ser posible.
"""
from datetime import datetime

import pytest

import main
from conftest import FakeResponse

CABECERA  = {"X-Auth-Token": "ha-poll-token"}
REVISION  = {"X-Auth-Token": "revision-token"}
FIRE_URL  = "https://api.anthropic.test/v1/claude_code/routines/trig_x/fire"


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
    monkeypatch.setattr(main, "ARREGLO_FIRE_URL", FIRE_URL)
    monkeypatch.setattr(main, "ARREGLO_FIRE_TOKEN", "arreglo-token")
    monkeypatch.setattr(main, "JARVIS_REPO", "usuario/Life-Assistant")


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "enviar_correo", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


def _fila(estado="pendiente", numero=83):
    return {"id": main._uuid_revision(numero), "issue_numero": numero,
            "issue_titulo": "Revisión nocturna — 2026-08-20",
            "issue_url": f"https://github.com/usuario/Life-Assistant/issues/{numero}",
            "estado": estado}


class TestAvisarDelIssue:
    def test_apunta_la_fila_y_el_aviso(self, client, mock_requests, correos):
        mock_requests.add("POST", "revision_hallazgos", FakeResponse([], 201))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = client.post("/revision/hallazgos", json={"numero": 83, "titulo": "Revisión nocturna — 2026-08-20"},
                        headers=REVISION)
        assert r.status_code == 200 and r.json()["avisado"] is True

        fila = mock_requests.called("POST", "revision_hallazgos")[0][2]["json"]
        assert fila["issue_numero"] == 83 and fila["estado"] == "pendiente"
        # El id sale del número del issue, no es aleatorio: es lo que ata el botón de la
        # notificación con la fila, y lo que hace que un reintento choque.
        assert fila["id"] == main._uuid_revision(83)
        # La URL la construye el backend con JARVIS_REPO: no se acepta un enlace de fuera
        # para meterlo en una notificación tuya.
        assert fila["issue_url"] == "https://github.com/usuario/Life-Assistant/issues/83"

        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert aviso["id"] == fila["id"] and aviso["regla"] == main.REGLA_REVISION
        assert "83" in aviso["texto"]

    def test_el_aviso_de_madrugada_espera_a_la_manana(self, monkeypatch):
        """El issue se abre a las 3:40. Un aviso que no gana nada por llegar de noche y
        lo pierde todo si te despierta, espera."""
        madrugada = datetime(2026, 8, 20, 3, 40, tzinfo=main.LOCAL_TZ)
        assert main._cuando_avisar(madrugada).strftime("%Y-%m-%d %H:%M") == "2026-08-20 08:30"

    def test_de_dia_sale_en_cuanto_llega(self):
        tarde = datetime(2026, 8, 20, 17, 5, tzinfo=main.LOCAL_TZ)
        assert main._cuando_avisar(tarde) == tarde

    def test_de_noche_espera_a_mañana(self):
        noche = datetime(2026, 8, 20, 23, 10, tzinfo=main.LOCAL_TZ)
        assert main._cuando_avisar(noche).strftime("%Y-%m-%d %H:%M") == "2026-08-21 08:30"

    def test_el_mismo_issue_no_avisa_dos_veces(self, client, mock_requests):
        """El 409 contra la clave primaria ES la respuesta: si el workflow reintenta, no
        salen dos notificaciones del mismo informe."""
        mock_requests.add("POST", "revision_hallazgos", FakeResponse([], 409))
        r = client.post("/revision/hallazgos", json={"numero": 83}, headers=REVISION)
        assert r.status_code == 200 and r.json()["avisado"] is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_exige_su_token(self, client):
        assert client.post("/revision/hallazgos", json={"numero": 83}).status_code == 403
        assert client.post("/revision/hallazgos", json={"numero": 83},
                           headers=CABECERA).status_code == 403

    def test_sin_token_configurado_no_entra_nadie(self, client, monkeypatch):
        """`_token_ok` es falso si el token esperado no está puesto: una instancia sin
        configurar no queda con la puerta abierta."""
        monkeypatch.setattr(main, "REVISION_TOKEN", "")
        assert client.post("/revision/hallazgos", json={"numero": 83},
                           headers=REVISION).status_code == 403

    def test_un_numero_que_no_lo_es_se_rechaza(self, client, mock_requests):
        assert client.post("/revision/hallazgos", json={"numero": 0}, headers=REVISION).status_code == 422
        assert client.post("/revision/hallazgos", json={"numero": "83; drop"},
                           headers=REVISION).status_code == 422
        assert not mock_requests.called("POST", "revision_hallazgos")


class TestElMotivoDelDisparo:
    """`_motivo_disparo` la comparten las dos rutinas: la del briefing y la del arreglo.

    Solo traduce lo que tiene arreglos distintos; lo demás pasa crudo, porque un cuerpo
    que no se entiende sigue siendo más de lo que dice un número a secas.
    """

    def test_la_credencial_manda_a_regenerar_el_token(self):
        motivo = main._motivo_disparo(401, '{"type":"authentication_error"}')
        assert "token" in motivo and "claude.ai/code/routines" in motivo

    def test_un_trigger_que_ya_no_esta(self):
        assert "ya no existen" in main._motivo_disparo(404, "not_found")

    def test_la_pausa_se_distingue_del_resto(self):
        assert "pausada" in main._motivo_disparo(400, "routine_paused")

    def test_el_cupo_agotado(self):
        assert "cupo" in main._motivo_disparo(429, "rate_limit_error")

    def test_lo_que_no_se_reconoce_pasa_crudo(self):
        assert main._motivo_disparo(400, "invalid_request: text") == "invalid_request: text"
        assert main._motivo_disparo(500, "") == "HTTP 500"


class TestLosBotones:
    def _pendiente(self, mock_requests, filas=None):
        mock_requests.add("PATCH", "revision_hallazgos",
                          FakeResponse([_fila()] if filas is None else filas))

    def test_arreglar_lanza_el_agente_y_lo_dice(self, client, mock_requests, correos):
        self._pendiente(mock_requests)
        mock_requests.add("POST", FIRE_URL,
                          FakeResponse({"claude_code_session_url": "https://claude.ai/code/s_1"}))
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "arreglar"}, headers=CABECERA)
        assert r.status_code == 200 and r.json()["sesion"] == "https://claude.ai/code/s_1"

        # El disparo lleva el número del issue: la rutina no puede adivinar cuál arregla.
        disparo = mock_requests.called("POST", FIRE_URL)[0][2]["json"]
        assert "#83" in disparo["text"]
        # Y se contesta por donde llegó la pregunta: pulsar un botón y que no pase nada
        # visible es la avería típica de este canal.
        assert len(correos) == 1 and "Arreglando" in correos[0][0]

    def test_la_transicion_es_condicional(self, client, mock_requests):
        """Dos toques seguidos no pueden lanzar dos agentes: quien pregunta si sigue
        pendiente es el propio PATCH, no un GET previo."""
        self._pendiente(mock_requests)
        mock_requests.add("POST", FIRE_URL, FakeResponse({}))
        client.post(f"/revision/{main._uuid_revision(83)}/accion",
                    json={"accion": "arreglar"}, headers=CABECERA)
        url = mock_requests.called("PATCH", "revision_hallazgos")[0][1]
        assert "estado=eq.pendiente" in url

    def test_el_segundo_toque_no_lanza_otro(self, client, mock_requests, correos):
        self._pendiente(mock_requests, filas=[])        # el PATCH no encuentra fila
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "arreglar"}, headers=CABECERA)
        assert r.status_code == 200 and r.json()["hecho"] is False
        assert not mock_requests.called("POST", FIRE_URL)
        assert correos == [], "un segundo toque no es un error del usuario: no se le avisa"

    def test_no_hacer_nada_no_hace_nada(self, client, mock_requests, correos):
        self._pendiente(mock_requests)
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "nada"}, headers=CABECERA)
        assert r.status_code == 200 and r.json()["accion"] == "nada"
        assert not mock_requests.called("POST", FIRE_URL)
        assert correos == []

    def test_si_el_disparo_falla_la_decision_se_libera(self, client, mock_requests, correos):
        """Una decisión consumida sin efecto deja el botón muerto y el issue sin
        arreglar. Igual que la reserva del despachador cuando el SMTP se cae."""
        self._pendiente(mock_requests)
        mock_requests.add("POST", FIRE_URL, FakeResponse(None, 400, "routine_paused"))
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "arreglar"}, headers=CABECERA)
        assert r.status_code == 502
        liberado = mock_requests.called("PATCH", "revision_hallazgos")[-1][2]["json"]
        assert liberado["estado"] == "pendiente"
        # Y se dice: un botón que no hace nada y no avisa es peor que uno que no está.
        assert len(correos) == 1 and "No he podido" in correos[0][0]

    def test_un_token_revocado_dice_que_hay_que_regenerarlo(self, client, mock_requests,
                                                            correos):
        """El JSON de Anthropic no le dice a nadie qué hacer; el aviso sí tiene que.

        Pasó de verdad el 2026-08-24: el aviso del botón llegó con
        `{"type":"authentication_error","message":"OAuth access token has been revoked."}`
        dentro y sin una sola pista de que había que regenerar el token del trigger.
        """
        self._pendiente(mock_requests)
        mock_requests.add("POST", FIRE_URL, FakeResponse(
            None, 401,
            '{"type":"error","error":{"type":"authentication_error",'
            '"message":"OAuth access token has been revoked."}}'))
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "arreglar"}, headers=CABECERA)
        assert r.status_code == 502
        cuerpo = correos[0][1]
        assert "token" in cuerpo and "claude.ai/code/routines" in cuerpo
        assert "authentication_error" not in cuerpo
        # Y la decisión se libera igual: el botón tiene que seguir sirviendo cuando el
        # token vuelva a valer.
        assert mock_requests.called("PATCH", "revision_hallazgos")[-1][2]["json"]["estado"] == "pendiente"

    def test_sin_rutina_configurada_lo_dice_en_vez_de_callarse(self, client, mock_requests,
                                                               correos, monkeypatch):
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "")
        self._pendiente(mock_requests)
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "arreglar"}, headers=CABECERA)
        assert r.status_code == 502
        assert "ARREGLO_FIRE_URL" in correos[0][1]

    def test_una_accion_que_no_existe_se_rechaza(self, client, mock_requests):
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "despliega"}, headers=CABECERA)
        assert r.status_code == 422
        assert not mock_requests.called("PATCH", "revision_hallazgos")

    def test_exige_credencial(self, client):
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion", json={"accion": "nada"})
        assert r.status_code == 403

    def test_el_dashboard_puede_con_su_jwt(self, client, mock_requests, auth_headers):
        self._pendiente(mock_requests)
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "nada"}, headers=auth_headers)
        assert r.status_code == 200

    def test_el_state_de_oauth_no_vale_como_sesion(self, client, mock_requests):
        """Firmar no basta: el `state` del OAuth viaja en la barra de direcciones."""
        state = main._create_oauth_state()
        r = client.post(f"/revision/{main._uuid_revision(83)}/accion",
                        json={"accion": "nada"}, headers={"Authorization": f"Bearer {state}"})
        assert r.status_code == 403

    def test_el_id_tiene_que_ser_un_uuid(self, client, mock_requests):
        r = client.post("/revision/no-es-un-uuid/accion", json={"accion": "nada"},
                        headers=CABECERA)
        assert r.status_code == 422


class TestPorSiLlegoPorCorreo:
    """Un correo no tiene botones. Sin esta puerta, decir que sí sería entrar en la
    base de datos a mano."""

    def test_jarvis_lanza_la_pendiente(self, mock_requests, correos):
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([_fila()]))
        mock_requests.add("PATCH", "revision_hallazgos", FakeResponse([_fila()]))
        mock_requests.add("POST", FIRE_URL, FakeResponse({"claude_code_session_url": "https://s"}))
        r = main._j_arreglar_revision()
        assert r["ok"] is True and r["issue"] == 83
        assert "83" in r["dile_al_usuario_literalmente"]

    def test_sin_nada_pendiente_lo_dice(self, mock_requests):
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([]))
        assert main._j_arreglar_revision()["ok"] is False

    def test_la_lanza_el_usuario_no_el_modelo(self):
        """Toca el repositorio y lo mergea: va por el botón de confirmar, como todo lo
        que no se deshace con un clic."""
        assert main._JARVIS_HERRAMIENTAS["arreglar_revision"]["confirmar"] is True

    def test_sin_rutina_configurada_no_se_anuncia(self, monkeypatch, mock_requests):
        """Una herramienta muerta se paga por token en cada turno y solo sirve para que
        el modelo la pida y falle."""
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert "arreglar_revision" not in nombres


class TestLosBotonesDeLaNotificacion:
    def test_la_revision_trae_los_suyos(self):
        rid = main._uuid_revision(83)
        acciones = main._acciones_aviso(rid, main.REGLA_REVISION)
        assert [a["title"] for a in acciones] == ["Arreglarlo", "No hacer nada"]
        assert acciones[0]["action"] == f"LA_ARREGLAR_{rid}"

    def test_el_resto_sigue_con_la_valoracion(self):
        rid = "11111111-2222-3333-4444-555555555555"
        assert [a["title"] for a in main._acciones_aviso(rid, "reloj")] == ["Útil", "No"]

    def test_sin_id_no_hay_botones(self):
        assert main._acciones_aviso("", main.REGLA_REVISION) == []

    def test_viajan_en_la_cola_que_sondea_ha(self, client, mock_requests):
        client.get("/ha/avisos-pending", headers=CABECERA)      # el canal se declara vivo
        rid = main._uuid_revision(83)
        main._notificar("t", "t", aviso_id=rid, acciones=main._acciones_aviso(rid, main.REGLA_REVISION))
        avisos = client.get("/ha/avisos-pending", headers=CABECERA).json()["avisos"]
        assert avisos[0]["acciones"][0]["action"] == f"LA_ARREGLAR_{rid}"

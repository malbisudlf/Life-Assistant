"""Tests del registro persistente (tabla app_logs) y del middleware de peticiones.

El backend siempre tuvo logger.error() en los sitios que importan; lo que no tenía era
dónde sobrevivieran. La máquina de Fly escala a cero y se lleva su stdout, así que el
409 que dejó al Watch sin sincronizar se registró cada vez, durante días, sin que nadie
lo viera. Estos tests fijan las dos propiedades que hacen que eso no se repita: que lo
registrado se persiste, y que registrar no puede romper ni frenar una petición.
"""
import logging

import pytest

import main
from conftest import FakeResponse


@pytest.fixture
def registro_activo():
    """Engancha el handler al logger (en los tests está desactivado por defecto).

    No arranca el hilo de volcado a propósito: los tests llaman a volcar() a mano, que
    es exactamente lo que hace el hilo, y así no hay escrituras a destiempo.
    """
    main.logger.addHandler(main._registro)
    yield main._registro
    main.logger.removeHandler(main._registro)


def _filas_escritas(mock_requests):
    for _, _, kwargs in mock_requests.called("POST", "/rest/v1/app_logs"):
        return kwargs["json"]
    return []


class TestHandler:
    def test_persiste_warning_y_error(self, registro_activo, mock_requests):
        main.logger.warning("algo raro")
        main.logger.error("algo roto")
        registro_activo.volcar()

        niveles = [f["level"] for f in _filas_escritas(mock_requests)]
        assert niveles == ["WARNING", "ERROR"]

    def test_el_info_no_llega_a_la_tabla(self, registro_activo, mock_requests):
        """Solo se persiste WARNING+: la tabla es para lo que hay que mirar cuando algo
        va mal, no una traza de depuración que habría que pagar y purgar."""
        main.logger.info("arranque correcto")
        registro_activo.volcar()
        assert not mock_requests.called("POST", "/rest/v1/app_logs")

    def test_guarda_el_traceback_de_una_excepcion(self, registro_activo, mock_requests):
        try:
            raise ValueError("el detalle que hace falta para diagnosticar")
        except ValueError:
            main.logger.exception("falló el proceso")
        registro_activo.volcar()

        mensaje = _filas_escritas(mock_requests)[0]["message"]
        assert "falló el proceso" in mensaje
        assert "ValueError" in mensaje
        assert "el detalle que hace falta" in mensaje

    def test_un_volcado_sin_nada_encolado_no_llama_a_supabase(self, registro_activo, mock_requests):
        registro_activo.volcar()
        assert not mock_requests.called("POST", "/rest/v1/app_logs")

    def test_la_cola_esta_acotada_y_deja_constancia_de_lo_tirado(self, registro_activo, mock_requests):
        """Un pico de errores no puede comerse la RAM de la VM (1 GB en Fly), pero
        tampoco puede desaparecer en silencio: si se tira algo, se dice cuánto."""
        for i in range(main.LOG_QUEUE_MAX + 5):
            main.logger.error("error %d", i)
        registro_activo.volcar()

        filas = _filas_escritas(mock_requests)
        assert len(filas) == main.LOG_QUEUE_MAX + 1        # el lote + el aviso
        assert "Se descartaron 5 entradas" in filas[-1]["message"]
        # Se conservan los más recientes, que son los que explican el estado actual.
        assert filas[-2]["message"].endswith(str(main.LOG_QUEUE_MAX + 4))

    def test_un_fallo_escribiendo_el_registro_no_propaga(self, registro_activo, mock_requests):
        """Si registrar pudiera lanzar, un problema de Supabase se convertiría en un
        fallo de la petición que solo quería dejar constancia de otro problema."""
        def _revienta(url, **kwargs):
            raise ConnectionError("supabase no responde")

        mock_requests.add("POST", "/rest/v1/app_logs", _revienta)
        main.logger.error("algo roto")
        registro_activo.volcar()      # no debe lanzar

    def test_un_error_de_supabase_no_reencola_el_fallo(self, registro_activo, mock_requests):
        """El aviso de "no pude escribir el registro" va por stderr, nunca por logger:
        por logger se realimentaría con el error de escribir el error."""
        mock_requests.add("POST", "/rest/v1/app_logs", FakeResponse(None, 500, "boom"))
        main.logger.error("algo roto")
        registro_activo.volcar()
        with registro_activo._lock:
            assert len(registro_activo._cola) == 0

    def test_purga_lo_viejo_una_sola_vez_por_proceso(self, registro_activo, mock_requests):
        for _ in range(3):
            main.logger.error("x")
            registro_activo.volcar()
        borrados = mock_requests.called("DELETE", "/rest/v1/app_logs")
        assert len(borrados) == 1
        assert "created_at=lt." in borrados[0][1]


class TestMiddleware:
    """La mitad de "logs para todo" que no se puede escribir a mano en 60 endpoints."""

    def test_un_500_queda_registrado(self, client, registro_activo, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "construir_brief", lambda: 1 / 0)
        client.post("/brief/send", headers={"X-Auth-Token": "brief-token"})
        registro_activo.volcar()

        mensajes = [f["message"] for f in _filas_escritas(mock_requests)]
        assert any("POST /brief/send" in m and "502" in m for m in mensajes)

    def test_una_excepcion_no_controlada_se_registra_con_traza(self, client, registro_activo, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            client.get("/ha/events/soon", headers={"X-Auth-Token": "ha-poll-token"})
        registro_activo.volcar()

        mensajes = [f["message"] for f in _filas_escritas(mock_requests)]
        assert any("excepción no controlada" in m and "RuntimeError" in m for m in mensajes)

    def test_un_403_de_token_de_servicio_se_registra(self, client, registro_activo, mock_requests):
        """Es el modo de fallo silencioso por excelencia: una integración ya desplegada
        (Watch, HA, Shortcut) que deja de entrar porque le rotaron el token."""
        client.post("/health/ingest?token=incorrecto", json={})
        registro_activo.volcar()

        mensajes = [f["message"] for f in _filas_escritas(mock_requests)]
        assert any("POST /health/ingest" in m and "403" in m for m in mensajes)

    def test_la_ruta_registrada_no_lleva_el_token_de_la_query(self, client, registro_activo, mock_requests):
        """Los tokens de servicio viajan por query string (compatibilidad con las
        integraciones ya desplegadas). Registrar la URL entera los metería en una tabla."""
        client.post("/health/ingest?token=health-token-secretisimo", json="no soy un objeto")
        registro_activo.volcar()

        volcado = str(_filas_escritas(mock_requests))
        assert "POST /health/ingest" in volcado
        assert "secretisimo" not in volcado

    def test_el_401_no_ensucia_el_registro(self, client, registro_activo, mock_requests):
        """Es el JWT caducando, que el frontend ya resuelve mandando al login. Si se
        registrara, el panel se llenaría de ruido y taparía lo que sí importa."""
        client.get("/health/metrics", headers={"Authorization": "Bearer caducado"})
        registro_activo.volcar()
        assert not mock_requests.called("POST", "/rest/v1/app_logs")

    def test_apunta_en_que_peticion_pasó(self, client, registro_activo, mock_requests):
        """Responde a "¿y esto dónde reventó?" sin tener que deducirlo del mensaje."""
        client.post("/health/ingest?token=incorrecto", json={})
        registro_activo.volcar()

        contextos = [f["context"]["peticion"] for f in _filas_escritas(mock_requests)]
        assert "POST /health/ingest" in contextos

    def test_una_peticion_normal_no_registra_nada(self, client, auth_headers, registro_activo, mock_requests):
        client.get("/health/metrics", headers=auth_headers)
        registro_activo.volcar()
        assert not mock_requests.called("POST", "/rest/v1/app_logs")


class TestEndpointDeConsulta:
    def test_requiere_jwt(self, client):
        # 401 y no 403: HTTPBearer distingue "no hay cabecera" de "hay una y no vale".
        assert client.get("/logs").status_code == 401

    def test_devuelve_las_entradas_y_cuenta_los_errores(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([
            {"created_at": "2026-08-02T09:00:00Z", "level": "ERROR", "source": "life-assistant",
             "message": "upsert falló", "context": {"peticion": "POST /health/ingest"}},
            {"created_at": "2026-08-02T08:00:00Z", "level": "WARNING", "source": "life-assistant",
             "message": "lento", "context": {}},
        ]))
        cuerpo = client.get("/logs", headers=auth_headers).json()
        assert len(cuerpo["entradas"]) == 2
        assert cuerpo["errores"] == 1

    def test_filtra_por_nivel(self, client, auth_headers, mock_requests):
        client.get("/logs?nivel=error", headers=auth_headers)
        assert "level=eq.ERROR" in mock_requests.called("GET", "/rest/v1/app_logs")[0][1]

    def test_un_nivel_inventado_se_rechaza(self, client, auth_headers):
        """`nivel` se interpola en la URL de Supabase: lista blanca, no lo que llegue."""
        assert client.get("/logs?nivel=todo;drop", headers=auth_headers).status_code == 400

    @pytest.mark.parametrize("query", ["limite=0", "limite=501", "dias=0", "dias=91"])
    def test_limites_fuera_de_rango(self, client, auth_headers, query):
        assert client.get(f"/logs?{query}", headers=auth_headers).status_code == 400

    def test_vuelca_lo_encolado_antes_de_leer(self, client, auth_headers, registro_activo, mock_requests):
        """Abres el panel PORQUE algo acaba de fallar: lo que sigue en la cola en memoria
        tiene que salir ya, no hasta LOG_FLUSH_SECONDS después."""
        main.logger.error("acaba de pasar")
        client.get("/logs", headers=auth_headers)
        assert _filas_escritas(mock_requests)[0]["message"] == "acaba de pasar"

    def test_un_error_de_supabase_no_filtra_su_texto(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(None, 500, "secreto interno"))
        r = client.get("/logs", headers=auth_headers)
        assert r.status_code == 502
        assert "secreto interno" not in r.text

    def test_borrar_vacia_la_tabla(self, client, auth_headers, mock_requests):
        assert client.delete("/logs", headers=auth_headers).json() == {"ok": True}
        assert mock_requests.called("DELETE", "/rest/v1/app_logs")

    def test_borrar_requiere_jwt(self, client):
        assert client.delete("/logs").status_code == 401


class TestConfiguracion:
    def test_el_nivel_persistido_es_warning_por_defecto(self):
        assert main._registro.level == logging.WARNING

    def test_en_los_tests_la_persistencia_va_desactivada(self):
        """Si se activara, el hilo de fondo colaría POSTs a app_logs en el MockRouter de
        cualquier test que registre un warning."""
        assert main._registro not in main.logger.handlers

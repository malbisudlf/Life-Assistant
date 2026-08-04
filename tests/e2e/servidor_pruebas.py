"""Backend real con los servicios externos simulados, para el test end-to-end.

Arranca `backend/main.py` TAL CUAL —mismos endpoints, mismas validaciones, mismo
manejo de errores— y solo sustituye la sesión HTTP saliente (`main.http`) por un
router de respuestas fijas. Así el E2E prueba el backend de verdad y no una imitación:
si alguien cambia la forma de lo que devuelve `/health/metrics`, el frontend se rompe
aquí y no en el móvil.

Es el mismo truco que usa `tests/backend/conftest.py`, pero servido por uvicorn en vez
de por el TestClient de pytest.

Uso:  python tests/e2e/servidor_pruebas.py [puerto]
"""
import os
import sys
from datetime import datetime, timedelta, timezone

# Igual que en conftest: el entorno se define ANTES de importar main, que exige los
# secretos al arrancar. La contraseña es numérica porque el input del login lo es.
os.environ.setdefault("SECRET_KEY", "e2e-secret-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "1234")
os.environ.setdefault("SUPABASE_URL", "https://supabase.e2e")
os.environ.setdefault("SUPABASE_KEY", "supa-e2e-key")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "maps-e2e-key")
os.environ.setdefault("HOME_ADDRESS", "Calle Falsa 123, Bilbao")
# El hilo del registro persistente escribiría en el Supabase simulado sin aportar nada
# al test, y ensucia la salida.
os.environ.setdefault("LOG_PERSIST", "0")
# El frontend se sirve desde otro puerto: sin esto, el navegador bloquea las llamadas.
os.environ.setdefault("CORS_ORIGINS", "http://localhost:4173,http://127.0.0.1:4173")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

import main  # noqa: E402


def _dia(delta: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta)).strftime("%Y-%m-%d")


def _iso(delta_horas: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Respuesta:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data if json_data is not None else []
        self.status_code = status_code
        self.text = ""
        self.encoding = "utf-8"

    def json(self):
        return self._json


def _metricas_salud():
    """30 días de métricas con una correlación plantada a propósito.

    Los días pares se anda mucho y se duerme más la noche siguiente: así el motor de
    patrones tiene algo real que encontrar y el test puede comprobar que el widget de
    salud no solo se pinta, sino que llega a conclusiones.
    """
    filas = []
    for i in range(30, 0, -1):
        activo = i % 2 == 0
        filas.append({"metric_date": _dia(-i), "metric_name": "step_count",
                      "value": 14000 if activo else 3200, "unit": "pasos", "extra": {}})
        filas.append({"metric_date": _dia(-i + 1), "metric_name": "sleep_analysis",
                      "value": 8.1 if activo else 6.2, "unit": "h",
                      "extra": {"deep": 1.4, "rem": 1.6, "sleep_start": "23:30"}})
        filas.append({"metric_date": _dia(-i), "metric_name": "heart_rate_variability",
                      "value": 55 if activo else 44, "unit": "ms", "extra": {}})
        filas.append({"metric_date": _dia(-i), "metric_name": "resting_heart_rate",
                      "value": 56, "unit": "bpm", "extra": {}})
        filas.append({"metric_date": _dia(-i), "metric_name": "apple_exercise_time",
                      "value": 45 if activo else 8, "unit": "min", "extra": {}})
        # Horas en casa/fuera (las manda Home Assistant, no el Watch). Van en el mismo
        # sentido que los pasos para que el cruce presencia↔sueño también tenga algo
        # que encontrar. La suma pasa de COBERTURA_PRESENCIA: si no, el día se
        # descartaría por falta de cobertura y el cruce nunca aparecería.
        fuera = 11 if activo else 2
        filas.append({"metric_date": _dia(-i), "metric_name": "time_at_home",
                      "value": 24 - fuera, "unit": "hr", "extra": {"fuera": fuera}})
    return filas


_EVENTOS_GRAPH = {
    "value": [
        {
            "id": "e2e-1",
            "subject": "Evento de prueba E2E",
            "start": {"dateTime": _iso(2), "timeZone": "UTC"},
            "end": {"dateTime": _iso(3), "timeZone": "UTC"},
            "location": {"displayName": "Aula 3"},
            "body": {"content": ""},
            "bodyPreview": "",
            "isAllDay": False,
        },
    ]
}

# El calendario de clases se busca por nombre (CLASSES_CALENDAR, "clases" por defecto).
_CALENDARIOS_GRAPH = {
    "value": [
        {"id": "cal-principal", "name": "Calendario"},
        {"id": "cal-clases", "name": "clases"},
    ]
}

_CLIMA = {
    "current": {"temperature_2m": 22.4, "weather_code": 1, "apparent_temperature": 23.0,
                "relative_humidity_2m": 50, "wind_speed_10m": 9.0, "precipitation": 0},
    "daily": {"time": [_dia(0)], "weather_code": [1], "temperature_2m_max": [28.0],
              "temperature_2m_min": [16.0], "precipitation_probability_max": [5]},
}


class _RouterSimulado:
    """Responde por fragmento de URL. El orden importa: gana la primera coincidencia,
    así que lo más específico va primero (igual que el MockRouter de los tests)."""

    RUTAS = [
        ("/rest/v1/login_attempts", lambda: _Respuesta([])),
        ("/rest/v1/health_metrics", lambda: _Respuesta(_metricas_salud())),
        ("/rest/v1/training_clients", lambda: _Respuesta(
            [{"id": "c1", "name": "Cliente E2E", "price_per_hour": 20,
              "sessions_per_payment": 10, "created_at": "2026-01-01T00:00:00Z"}])),
        ("/rest/v1/training_sessions", lambda: _Respuesta(
            [{"id": "s1", "date": _dia(-1), "duration_hours": 1.5,
              "created_at": f"{_dia(-1)}T10:00:00Z"}])),
        ("/rest/v1/training_payments", lambda: _Respuesta([])),
        ("/rest/v1/ideas", lambda: _Respuesta(
            [{"id": "11111111-1111-4111-8111-111111111111", "key": "Idea de prueba",
              "full_text": "Contenido de la idea", "tag": "e2e",
              "created_at": f"{_dia(0)}T09:00:00Z"}])),
        ("/rest/v1/clothing", lambda: _Respuesta([])),
        ("/rest/v1/pc_agents", lambda: _Respuesta([])),
        ("/rest/v1/jobs", lambda: _Respuesta([])),
        ("/rest/v1/app_logs", lambda: _Respuesta([])),
        # Presencia vigente: el panel de estado la pide y /weather la usa como
        # ubicación cuando el navegador no da permiso de geolocalización, que es
        # justo lo que pasa en un Chromium sin cabeza.
        ("/rest/v1/presence", lambda: _Respuesta([{
            "zona": "casa", "en_casa": True, "lat": 43.26, "lon": -2.93,
            "precision_m": 20.0, "fuente": "e2e",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }])),
        # El orden importa: la URL de calendarView del calendario de clases contiene
        # "/me/calendars", así que si la lista de calendarios fuera primero se comería
        # también esa llamada y /calendar/classes recibiría calendarios donde espera
        # eventos (o al revés) y acabaría en un 500.
        ("/calendarView", lambda: _Respuesta(_EVENTOS_GRAPH)),
        ("/me/calendars", lambda: _Respuesta(_CALENDARIOS_GRAPH)),
        ("graph.microsoft.com", lambda: _Respuesta(_EVENTOS_GRAPH)),
        ("api.open-meteo.com", lambda: _Respuesta(_CLIMA)),
    ]

    def _responder(self, url, **_):
        for fragmento, hacer in self.RUTAS:
            if fragmento in url:
                return hacer()
        return _Respuesta([])

    get = _responder
    post = _responder
    patch = _responder
    delete = _responder


def _preparar():
    router = _RouterSimulado()
    main.http.get = router.get
    main.http.post = router.post
    main.http.patch = router.patch
    main.http.delete = router.delete
    # Sesión de Graph siempre activa: el OAuth real no tiene sitio en un E2E.
    main.get_valid_token = lambda: "graph-token-e2e"


if __name__ == "__main__":
    import uvicorn

    _preparar()
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(main.app, host="127.0.0.1", port=puerto, log_level="warning")

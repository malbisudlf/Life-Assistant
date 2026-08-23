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
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
# La cartera de Indexa: con el token puesto, el widget de finanzas pide de verdad y el
# router de abajo responde. Sin él saldría "Sin conectar", que no prueba nada.
os.environ.setdefault("INDEXA_TOKEN", "indexa-e2e-token")
# El frontend se sirve desde otro puerto: sin esto, el navegador bloquea las llamadas.
# El puerto sale de la misma variable que usa playwright.config.js, o el login falla con
# un error de CORS que en el navegador NO se parece a un problema de puertos — es el
# mismo despiste que documenta CLAUDE.md con el 5173 ocupado en desarrollo.
_PUERTO_WEB = os.environ.get("E2E_PUERTO_WEB", "4173")
os.environ.setdefault(
    "CORS_ORIGINS",
    f"http://localhost:{_PUERTO_WEB},http://127.0.0.1:{_PUERTO_WEB}",
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

import main  # noqa: E402


def _dia(delta: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta)).strftime("%Y-%m-%d")


def _iso(delta_horas: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cartera_indexa():
    """Cartera de Indexa con la forma real de la API (`instrument_accounts` → `positions`)."""
    return {
        "portfolio": {"total_amount": 12500.0, "cash_amount": 250.0},
        "instrument_accounts": [{"positions": [
            {"instrument": {"name": "Vanguard Global Stock Index Fund",
                            "isin_code": "IE00B03HCZ61", "identifier_name": "ISIN",
                            "asset_class": "equity_world",
                            "management_company_description": "Vanguard"},
             "amount": 9000.0, "cost_amount": 7500.0, "titles": 300.0,
             "price": 30.0, "date": _dia(-1)},
            {"instrument": {"name": "Vanguard Euro Government Bond Index",
                            "isin_code": "IE00B04GQR24", "identifier_name": "ISIN",
                            "asset_class": "fixed_euro",
                            "management_company_description": "Vanguard"},
             "amount": 3250.0, "cost_amount": 3300.0, "titles": 200.0,
             "price": 16.25, "date": _dia(-1)},
        ]}],
    }


def _rendimiento_indexa():
    """Serie de 40 días subiendo poco a poco, para que la sparkline tenga qué dibujar."""
    totales, netos = {}, {}
    for i in range(40, 0, -1):
        totales[_dia(-i)] = round(11800 + (40 - i) * 17.5, 2)
        netos[_dia(-i)]   = 11000.0
    return {
        "return": {
            "total_amount": 12500.0, "investment": 11000.0, "pl": 1500.0,
            "time_return": 0.1364, "time_return_annual": 0.0712, "volatility": 0.0891,
            "total_amounts": totales, "net_amounts": netos,
        },
        "plan_expected_return": 0.0521,
    }


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
        ("indexacapital.com/users/me", lambda: _Respuesta(
            {"accounts": [{"account_number": "E2E12345", "type": "mutual", "status": "active"}]})),
        ("/portfolio", lambda: _Respuesta(_cartera_indexa())),
        ("/performance", lambda: _Respuesta(_rendimiento_indexa())),
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


class _ModeloSimulado:
    """El modelo de Jarvis, con guion fijo.

    Aquí no se prueba que el modelo acierte —eso no es determinista y no se puede
    afirmar en un test— sino que el circuito entero funcione: el navegador manda un
    mensaje, el backend ejecuta la herramienta DE VERDAD contra el Supabase y el Graph
    simulados, el resultado vuelve al modelo y la respuesta acaba pintada en el hilo.
    Ese recorrido es justo el que no cubren ni vitest ni los tests de backend.

    El guion se decide por palabra clave para que el test pueda recorrer los dos caminos
    que importan: el que ejecuta una consulta y el que deja una acción por confirmar.
    """

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    @staticmethod
    def _envolver(mensaje):
        return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)])

    def _texto(self, texto):
        return self._envolver(SimpleNamespace(content=texto, tool_calls=None))

    def _herramienta(self, nombre, argumentos):
        return self._envolver(SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
            id=f"call-{nombre}",
            type="function",
            function=SimpleNamespace(name=nombre, arguments=json.dumps(argumentos)),
        )]))

    def create(self, **kwargs):
        mensajes = kwargs.get("messages", [])
        # La llamada de cierre va sin `tools`: ahí toca redactar, no pedir nada más.
        if "tools" not in kwargs or any(m.get("role") == "tool" for m in mensajes):
            return self._texto("Hoy tienes el Evento de prueba E2E.")
        ultimo = next((m.get("content") or "" for m in reversed(mensajes) if m.get("role") == "user"), "")
        if "dentista" in ultimo.lower():
            return self._herramienta("crear_evento", {
                "titulo": "Dentista", "fecha": _dia(1), "hora_inicio": "17:00",
            })
        return self._herramienta("agenda", {"dias": 1})


def _preparar():
    router = _RouterSimulado()
    main.http.get = router.get
    main.http.post = router.post
    main.http.patch = router.patch
    main.http.delete = router.delete
    # Sesión de Graph siempre activa: el OAuth real no tiene sitio en un E2E.
    main.get_valid_token = lambda: "graph-token-e2e"
    # Jarvis: lo único que se sustituye es el modelo. Las herramientas, el bucle y la
    # frontera de confirmación son las de producción.
    main.get_openai_client = lambda: _ModeloSimulado()


if __name__ == "__main__":
    import uvicorn

    _preparar()
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(main.app, host="127.0.0.1", port=puerto, log_level="warning")

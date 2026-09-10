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
# El saldo de Revolut: solo hace falta que _enable_banking_configurado() sea True — la
# sesión y el JWT se sustituyen directamente en _preparar(), como get_valid_token con
# Graph. El CONTENIDO de la clave no importa (nunca se firma nada aquí), pero tiene que
# haber una: desde septiembre de 2026 "configurado" significa que la clave existe, no que
# la variable esté escrita, precisamente porque una ruta a un fichero ausente tumbaba
# `/finanzas/resumen` entero en producción. Por eso va por variable y no por ruta.
os.environ.setdefault("ENABLE_BANKING_APPLICATION_ID", "app-e2e-id")
os.environ.setdefault("ENABLE_BANKING_PRIVATE_KEY", "no-es-una-clave-real")
# La voz de Jarvis, encendida: el dashboard pide /voz/token nada más entrar, y con la
# voz apagada eso es un 503 en la consola del navegador en cada carga — que el E2E
# cuenta como error, y con razón. Encendida, se ejerce el camino de verdad; la
# llamada saliente a ElevenLabs la responde el router de abajo, no la red.
os.environ.setdefault("JARVIS_VOZ_ELEVENLABS", "1")
os.environ.setdefault("ELEVENLABS_API_KEY", "eleven-e2e-key")
os.environ.setdefault("ELEVENLABS_VOICE_ID", "voz-e2e")
# La zona de desarrollo pregunta a GitHub por el último commit de `main` y por los runs de
# los workflows programados. Con el repositorio y una credencial de mentira se ejerce el
# camino de verdad (la llamada la responde el router de abajo); sin ellos, las pestañas
# Despliegue y Crons enseñarían "falta JARVIS_REPO" y no probarían nada.
os.environ.setdefault("JARVIS_REPO", "malbisudlf/Life-Assistant")
os.environ.setdefault("DEPLOY_GITHUB_TOKEN", "gh-e2e-token")
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


def _migraciones_del_repo():
    """Los nombres de supabase/migrations/ leídos del disco, ordenados."""
    raiz = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
    return sorted(f[:-4] for f in os.listdir(raiz) if f.endswith(".sql"))


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
    def __init__(self, json_data=None, status_code=200, headers=None):
        self._json = json_data if json_data is not None else []
        self.status_code = status_code
        self.text = ""
        self.encoding = "utf-8"
        # `Content-Range` por defecto porque la pestaña Base de datos cuenta filas con él:
        # sin cabecera, las treinta y tantas tablas saldrían como "existe, sin cuenta", que
        # es un caso válido pero no el que hay que mirar.
        self.headers = headers or {"Content-Range": "0-0/7"}

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
        # Antes que `/rest/v1/ideas`, que es prefijo suyo: si no, la checklist de la zona
        # dev recibiría las notas por voz, que son otra tabla y otra cosa.
        ("/rest/v1/ideas_dev", lambda: _Respuesta([{
            "id": "33333333-3333-4333-8333-333333333333",
            "titulo": "Idea de la zona dev", "porque": "para el E2E",
            "por_donde": None, "esfuerzo": 1, "area": "frontend", "estado": "pendiente",
            "creada": f"{_dia(0)}T09:00:00Z", "actualizada": f"{_dia(0)}T09:00:00Z",
        }])),
        ("/rest/v1/brief_envios", lambda: _Respuesta(
            [{"fecha": _dia(0), "enviado_at": _iso(-3), "fuente": "despertar"}])),
        ("/rest/v1/informe_envios", lambda: _Respuesta(
            [{"fecha": _dia(-2), "enviado_at": _iso(-48)}])),
        ("/rest/v1/vigilante_estado", lambda: _Respuesta([])),
        # Todas las migraciones del repositorio menos la última, para que la pestaña Base
        # de datos enseñe el caso que importa: una sin aplicar, con su nombre.
        ("/rest/v1/migraciones_aplicadas", lambda: _Respuesta(
            [{"nombre": n, "aplicada": f"{_dia(-30)}T10:00:00Z"} for n in _migraciones_del_repo()[:-1]])),
        ("/rest/v1/oauth_tokens", lambda: _Respuesta([{
            "provider": "microsoft", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=42)).timestamp(),
            "updated_at": _iso(-1), "refresh_token": "refresco-e2e",
        }])),
        ("/rest/v1/pc_agents", lambda: _Respuesta([])),
        ("/rest/v1/jobs", lambda: _Respuesta([])),
        ("/rest/v1/app_logs", lambda: _Respuesta([])),
        # Una alarma de respaldo puesta para mañana, para que el widget se pinte con
        # algo de verdad. `cuando` viaja en UTC, como lo devuelve Supabase.
        ("/rest/v1/alarmas", lambda: _Respuesta([{
            "id": "22222222-2222-4222-8222-222222222222",
            "cuando": f"{_dia(1)}T06:30:00+00:00", "etiqueta": "Entrenar",
            "estado": "armada", "intentos": 0,
        }])),
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
        # GitHub, para las pestañas Despliegue y Crons de la zona dev. El `compare`
        # devuelve un commit de diferencia a propósito: es el caso que hay que ver bien
        # pintado, no el de "todo al día".
        ("/compare/", lambda: _Respuesta({
            "ahead_by": 1,
            "commits": [{"sha": "b" * 40, "commit": {
                "message": "zona dev: despliegue y crons",
                "author": {"date": _iso(-2)}}}],
        })),
        # El directorio de migraciones tal y como lo devuelve la API de GitHub, pero leído
        # del repositorio de verdad: una lista inventada aquí se quedaría atrás en cuanto
        # alguien añadiera una migración, que es el fallo que la pestaña viene a evitar.
        ("/contents/supabase/migrations", lambda: _Respuesta(
            [{"name": f"{n}.sql"} for n in _migraciones_del_repo()])),
        ("/commits/main", lambda: _Respuesta({
            "sha": "a" * 40,
            "commit": {"message": "alarmas: el aviso al movil deja de ser critico (#167)",
                       "author": {"date": _iso(-1)}},
        })),
        ("/actions/workflows/", lambda: _Respuesta({"workflow_runs": [{
            "status": "completed", "conclusion": "success", "updated_at": _iso(-6),
            "html_url": "https://github.com/malbisudlf/Life-Assistant/actions/runs/1",
        }]})),
        ("/calendarView", lambda: _Respuesta(_EVENTOS_GRAPH)),
        ("/me/calendars", lambda: _Respuesta(_CALENDARIOS_GRAPH)),
        ("graph.microsoft.com", lambda: _Respuesta(_EVENTOS_GRAPH)),
        ("api.open-meteo.com", lambda: _Respuesta(_CLIMA)),
        # El permiso de un solo uso para el WebSocket de voz. El navegador lo pide al
        # entrar; que sea un token de mentira da igual, porque en el E2E nadie llega a
        # abrir el socket (no hay micrófono ni altavoz que valgan en Chromium).
        ("api.elevenlabs.io/v1/single-use-token", lambda: _Respuesta({"token": "sutkn_e2e"})),
        ("indexacapital.com/users/me", lambda: _Respuesta(
            {"accounts": [{"account_number": "E2E12345", "type": "mutual", "status": "active"}]})),
        ("/portfolio", lambda: _Respuesta(_cartera_indexa())),
        ("/performance", lambda: _Respuesta(_rendimiento_indexa())),
        # Revolut vía Enable Banking. La sesión ya se da por buena (ver _preparar): esto
        # solo cubre lo que _revolut_datos() pide DESPUÉS de tenerla.
        ("api.enablebanking.com/sessions/", lambda: _Respuesta({"accounts": ["uid-e2e"]})),
        ("/accounts/uid-e2e/details", lambda: _Respuesta({"name": "Cuenta E2E", "currency": "EUR"})),
        ("/accounts/uid-e2e/balances", lambda: _Respuesta({"balances": [{
            "balance_type": "ITAV", "balance_amount": {"currency": "EUR", "amount": "79.70"},
        }]})),
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
    # Lo mismo con Revolut: sesión de Enable Banking siempre vigente y JWT de aplicación
    # sin firmar de verdad (no hay clave RSA en el entorno de CI, ni falta que hace).
    main._enable_banking_jwt = lambda: "fake-jwt-e2e"
    main._eb_cargar_sesion = lambda: {
        "access_token": "session-e2e",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=180)).timestamp(),
    }
    # El sha "desplegado". En el contenedor lo escribe el clon (`/app/VERSION`) y aquí no
    # existe, así que sin esto la pestaña Despliegue del E2E diría "no lo dice" y no
    # probaría la comparación, que es lo único que esa pantalla tiene que hacer bien.
    main._version_desplegada = lambda: "b" * 40
    # Jarvis: lo único que se sustituye es el modelo. Las herramientas, el bucle y la
    # frontera de confirmación son las de producción.
    main.get_openai_client = lambda: _ModeloSimulado()


if __name__ == "__main__":
    import uvicorn

    _preparar()
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(main.app, host="127.0.0.1", port=puerto, log_level="warning")

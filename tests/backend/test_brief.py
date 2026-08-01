"""Tests del resumen diario por correo (/brief y /brief/send).

El backend manda DATOS CRUDOS, sin interpretarlos: el consumidor es la rutina de
Claude Code que compone el correo diario del usuario leyendo su buzón. Por eso aquí
no se comprueba ninguna conclusión — solo que los datos salen completos y correctos,
y que un fallo de una fuente no tumba el resto del resumen.
"""
from datetime import datetime, timedelta, timezone

import main
from conftest import FakeResponse


def _hoy_iso(hora="10:00"):
    """Un ISO-UTC que cae hoy en la zona del usuario, a mediodía para no bailar de día."""
    hoy = datetime.now(main.LOCAL_TZ).date()
    return f"{hoy.isoformat()}T{hora}:00Z"


def _en_dias(n, hora="10:00"):
    fecha = datetime.now(main.LOCAL_TZ).date() + timedelta(days=n)
    return f"{fecha.isoformat()}T{hora}:00Z"


def _evento(titulo, inicio, lugar="Aula 3", fin=None):
    return {
        "id": "ev-" + titulo[:4],
        "subject": titulo,
        "start": {"dateTime": inicio, "timeZone": "UTC"},
        "end": {"dateTime": fin or inicio, "timeZone": "UTC"},
        "location": {"displayName": lugar},
        "body": {"content": ""},
        "bodyPreview": "",
        "isAllDay": False,
    }


CLIMA_OK = {
    "current": {"temperature_2m": 24.4, "weather_code": 2, "apparent_temperature": 26.0,
                "relative_humidity_2m": 55, "wind_speed_10m": 12.3, "precipitation": 0},
    "daily": {"time": [datetime.now(timezone.utc).strftime("%Y-%m-%d")],
              "weather_code": [2], "temperature_2m_max": [31.2],
              "temperature_2m_min": [18.6], "precipitation_probability_max": [10]},
}


def _salud_filas():
    hoy = datetime.now(main.LOCAL_TZ).date()
    filas = []
    for i in range(7):
        d = (hoy - timedelta(days=i)).isoformat()
        filas.append({"metric_date": d, "metric_name": "heart_rate_variability",
                      "value": 40 + i, "unit": "ms", "extra": {}})
        filas.append({"metric_date": d, "metric_name": "resting_heart_rate",
                      "value": 58, "unit": "bpm", "extra": {}})
        filas.append({"metric_date": d, "metric_name": "step_count",
                      "value": 8000 + i * 100, "unit": "pasos", "extra": {}})
        filas.append({"metric_date": d, "metric_name": "sleep_analysis",
                      "value": 7.0, "unit": "h", "extra": {"sleep_start": "23:45"}})
    filas.append({"metric_date": (hoy - timedelta(days=2)).isoformat(),
                  "metric_name": "workouts", "value": 1, "unit": "count", "extra": {}})
    return sorted(filas, key=lambda f: f["metric_date"])


class _SMTPFalso:
    """Captura lo que se enviaría sin abrir ninguna conexión."""

    enviados = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        _SMTPFalso.enviados.append(msg)


def montar_brief_sends(mock_requests, enviados=None):
    """Simula la tabla brief_sends con un conjunto en memoria, respetando el unique de
    `brief_date`: el segundo insert de la misma fecha devuelve 409, que es lo que el
    backend lee como "el correo de hoy ya salió".

    Devuelve el conjunto para que los tests puedan mirar qué quedó reservado.
    """
    reservados = set(enviados or ())

    def _post(url, **kwargs):
        fecha = kwargs["json"]["brief_date"]
        if fecha in reservados:
            return FakeResponse(None, 409, "duplicate key value violates unique constraint")
        reservados.add(fecha)
        return FakeResponse([], 201)

    def _delete(url, **kwargs):
        reservados.discard(url.rsplit("eq.", 1)[-1])
        return FakeResponse([], 204)

    mock_requests.add("POST", "/rest/v1/brief_sends", _post)
    mock_requests.add("DELETE", "/rest/v1/brief_sends", _delete)
    return reservados


def montar_fuentes(mock_requests, eventos=None, clases=None, salud=None,
                   graph_status=200, salud_status=200, con_cliente=True, enviados=None):
    """Registra las cuatro fuentes del resumen (Graph, clima, salud, entrenamiento) y
    la tabla de reservas de envío.

    El MockRouter resuelve en orden de REGISTRO y gana la primera coincidencia, así que
    todo lo que un test quiera cambiar tiene que pasarse por parámetro aquí: registrar
    otra ruta después no sobreescribe (ver CLAUDE.md).
    """
    montar_brief_sends(mock_requests, enviados)
    if eventos is None:
        eventos = [
            _evento("Redes", _hoy_iso("10:00"), "Aula 3", _hoy_iso("12:00")),
            _evento("La semana que viene", _en_dias(6)),
        ]
    if clases is None:
        clases = [_evento("Sistemas Operativos", _hoy_iso("08:00"), "Lab 2")]
    if salud is None:
        salud = _salud_filas()

    # La más específica primero: la URL de calendarView de clases contiene /me/calendars.
    mock_requests.add("GET", "/calendars/cal-clases/calendarView", FakeResponse({"value": clases}))
    mock_requests.add("GET", "/me/calendars", FakeResponse({
        "value": [{"id": "cal-clases", "name": "clases"}]
    }))
    mock_requests.add("GET", "graph.microsoft.com", FakeResponse(
        {"value": eventos} if graph_status < 300 else None, graph_status, "boom"))
    mock_requests.add("GET", "api.open-meteo.com", FakeResponse(CLIMA_OK))
    mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(
        salud if salud_status < 300 else None, salud_status, "boom"))
    mock_requests.add("GET", "/rest/v1/training_clients", FakeResponse(
        [{"id": "c1", "name": "Cliente", "price_per_hour": 20, "sessions_per_payment": 10,
          "created_at": "2026-01-01T00:00:00Z"}] if con_cliente else []))
    mock_requests.add("GET", "/rest/v1/training_payments", FakeResponse([]))
    mock_requests.add("GET", "/rest/v1/training_sessions", FakeResponse([
        {"id": "s1", "date": "2026-07-29", "duration_hours": 1.5,
         "created_at": "2026-07-29T10:00:00Z"}
    ]))


def configurar_smtp(monkeypatch, puerto=587, remitente=""):
    monkeypatch.setattr(main, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(main, "SMTP_PORT", puerto)
    monkeypatch.setattr(main, "SMTP_USER", "remite@test")
    monkeypatch.setattr(main, "SMTP_PASSWORD", "clave-app")
    monkeypatch.setattr(main, "BRIEF_TO", "yo@test")
    monkeypatch.setattr(main, "BRIEF_FROM", remitente)
    monkeypatch.setattr(main.smtplib, "SMTP_SSL" if puerto == 465 else "SMTP", _SMTPFalso)
    _SMTPFalso.enviados.clear()


class TestAuth:
    def test_brief_requiere_jwt(self, client):
        assert client.get("/brief").status_code in (401, 403)

    def test_send_requiere_token_de_servicio(self, client):
        assert client.post("/brief/send").status_code == 403

    def test_send_con_token_malo(self, client):
        assert client.post("/brief/send?token=mal").status_code == 403

    def test_send_no_acepta_el_jwt_de_usuario(self, client, auth_headers):
        """Es un endpoint de máquina: el token de servicio y el JWT no son intercambiables."""
        assert client.post("/brief/send", headers=auth_headers).status_code == 403


class TestConstruirBrief:
    def test_agenda_solo_de_hoy(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests)
        d = client.get("/brief", headers=auth_headers).json()
        titulos = [e["titulo"] for e in d["agenda"]]
        assert titulos == ["Redes"], f"la agenda debe traer solo hoy: {titulos}"

    def test_clases_de_hoy_aparte(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests)
        d = client.get("/brief", headers=auth_headers).json()
        assert [e["titulo"] for e in d["clases"]] == ["Sistemas Operativos"]

    def test_clima_y_salud_y_entrenamiento(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests)
        d = client.get("/brief", headers=auth_headers).json()
        assert d["clima"]["max"] == 31 and d["clima"]["lluvia_prob"] == 10
        assert d["salud"]["hrv"]["media_7d"] is not None
        assert d["salud"]["fc_reposo"]["ultimo"] == 58
        assert d["salud"]["ultimo_entreno"]["dias"] == 2
        assert d["entrenamiento"]["importe_pendiente"] == 30.0

    def test_entregas_por_marcador_ordenadas(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, eventos=[
            _evento(f"{main.ENTREGAS_MARKER} Práctica 3", _en_dias(3)),
            _evento(f"{main.ENTREGAS_MARKER} Memoria", _en_dias(1)),
            _evento("Sin marcador", _en_dias(2)),
        ], clases=[])
        d = client.get("/brief", headers=auth_headers).json()
        assert [e["titulo"] for e in d["entregas"]] == ["Memoria", "Práctica 3"]
        assert [e["dias"] for e in d["entregas"]] == [1, 3]

    def test_entregas_fuera_de_ventana_se_excluyen(self, client, auth_headers, graph_token, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "BRIEF_DIAS_ENTREGAS", 2)
        montar_fuentes(mock_requests, eventos=[
            _evento(f"{main.ENTREGAS_MARKER} Lejana", _en_dias(9)),
        ], clases=[])
        d = client.get("/brief", headers=auth_headers).json()
        assert d["entregas"] == []

    def test_sueno_respeta_noches_excluidas(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        montar_fuentes(mock_requests, salud=[
            {"metric_date": (hoy - timedelta(days=1)).isoformat(), "metric_name": "sleep_analysis",
             "value": 7.5, "unit": "h", "extra": {}},
            {"metric_date": hoy.isoformat(), "metric_name": "sleep_analysis",
             "value": 2.0, "unit": "h", "extra": {"excluded": True}},
        ])
        d = client.get("/brief", headers=auth_headers).json()
        assert d["salud"]["sueno"]["ultimo"] == 7.5, "la noche anulada no debe contar"

    def test_graph_caido_no_tumba_el_resumen(self, client, auth_headers, graph_token, mock_requests):
        """Si falla el calendario principal, su sección queda vacía y el resto aguanta.

        Las clases van por otra llamada a Graph, así que sobreviven a que se caiga solo
        la del calendario principal — cada sección cae por su cuenta, no en bloque.
        """
        montar_fuentes(mock_requests, graph_status=500)
        r = client.get("/brief", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["agenda"] == [] and d["entregas"] == []
        assert [e["titulo"] for e in d["clases"]] == ["Sistemas Operativos"]
        assert d["clima"]["max"] == 31
        assert d["salud"]["fc_reposo"]["ultimo"] == 58

    def test_salud_caida_no_tumba_el_resumen(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud_status=500)
        d = client.get("/brief", headers=auth_headers).json()
        assert d["salud"] == {}
        assert [e["titulo"] for e in d["agenda"]] == ["Redes"]

    def test_sin_sesion_de_outlook_el_resto_sigue(self, client, auth_headers, mock_requests, monkeypatch):
        """Sin graph_token no hay agenda, pero el correo del día sigue mereciendo la pena."""
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        montar_fuentes(mock_requests)
        d = client.get("/brief", headers=auth_headers).json()
        assert d["agenda"] == [] and d["clases"] == []
        assert d["salud"]["fc_reposo"]["ultimo"] == 58


class TestHorasSueno:
    """Mismo criterio que _sleepHours en helpers.js: value, luego asleep, luego fases."""

    def test_usa_value_si_es_positivo(self):
        assert main._horas_sueno({"value": 7.25, "extra": {"asleep": 3}}) == 7.25

    def test_cae_a_asleep(self):
        assert main._horas_sueno({"value": 0, "extra": {"asleep": 6.5}}) == 6.5

    def test_suma_las_fases(self):
        fila = {"value": None, "extra": {"deep": 1.2, "rem": 1.5, "light": 3.0, "core": 0.5}}
        assert main._horas_sueno(fila) == 6.2

    def test_sin_datos_da_cero(self):
        assert main._horas_sueno({"value": None, "extra": {}}) == 0
        assert main._horas_sueno({}) == 0

    def test_valores_no_numericos_no_revientan(self):
        assert main._horas_sueno({"value": "x", "extra": {"asleep": "y"}}) == 0


class TestRenderTexto:
    def test_incluye_todas_las_secciones(self):
        texto = main.render_brief_texto({
            "fecha": "2026-07-30", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [{"titulo": "Redes", "inicio": "2026-07-30T08:00:00Z",
                        "fin": "2026-07-30T10:00:00Z", "lugar": "Aula 3", "todo_el_dia": False}],
            "clases": [], "entregas": [{"titulo": "Práctica 3", "dias": 2, "fecha": "2026-08-01"}],
            "clima": {"ahora": 24, "max": 31, "min": 19, "codigo_wmo": 2,
                      "sensacion": 26, "humedad": 55, "viento": 12, "lluvia_prob": 10},
            "salud": {"sueno": {"unidad": "h", "ultimo": 6.2, "fecha": "2026-07-30",
                                "inicio": "23:45", "media_7d": 7.1, "media_30d": 7.4}},
            "entrenamiento": {"sesiones_desde_cobro": 6, "horas_desde_cobro": 7.5,
                              "importe_pendiente": 150.0, "sesiones_por_cobro": 10,
                              "ultimo_cobro": "2026-07-01", "ultima_sesion": "2026-07-29"},
        })
        for seccion in ("## AGENDA DE HOY", "## CLASES DE HOY", "## ENTREGAS",
                        "## CLIMA", "## SALUD", "## ENTRENAMIENTO PERSONAL"):
            assert seccion in texto, f"falta la sección {seccion}"
        assert "Redes" in texto and "Aula 3" in texto
        assert "en 2 días" in texto
        assert "6.2 h" in texto and "7d: 7.1" in texto
        assert "150.0 €" in texto
        assert "jueves 2026-07-30" in texto

    def test_secciones_vacias_se_marcan(self):
        texto = main.render_brief_texto({
            "fecha": "2026-07-30", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [],
            "clima": {}, "salud": {}, "entrenamiento": {},
        })
        assert "(nada)" in texto
        assert "(no disponible)" in texto
        assert "(sin datos)" in texto
        assert "(sin cliente configurado)" in texto

    def test_evento_de_todo_el_dia(self):
        texto = main.render_brief_texto({
            "fecha": "2026-07-30", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [{"titulo": "Festivo", "inicio": "2026-07-30T00:00:00Z", "fin": None,
                        "lugar": None, "todo_el_dia": True}],
            "clases": [], "entregas": [], "clima": {}, "salud": {}, "entrenamiento": {},
        })
        assert "todo el día  Festivo" in texto


class TestEnvio:
    def test_falta_configuracion_da_503(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        monkeypatch.setattr(main, "SMTP_HOST", "")
        monkeypatch.setattr(main, "BRIEF_TO", "yo@test")
        r = client.post("/brief/send?token=brief-token")
        assert r.status_code == 503
        assert "SMTP_HOST" in r.json()["detail"]

    def test_fallo_inesperado_da_502_con_el_motivo(self, client, mock_requests, graph_token, monkeypatch):
        """Antes cualquier fallo no previsto (Graph, Supabase, SMTP) subía sin
        capturar y el disparador solo veía un 'Internal Server Error' sin detalle."""
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        def _explota(asunto, cuerpo):
            raise TimeoutError("[Errno 110] Connection timed out")

        monkeypatch.setattr(main, "enviar_correo", _explota)
        r = client.post("/brief/send?token=brief-token")
        assert r.status_code == 502
        assert "Connection timed out" in r.json()["detail"]

    def test_fallo_inesperado_no_manda_correo(self, client, mock_requests, graph_token, monkeypatch):
        """Si construir_brief() revienta, no debe intentarse enviar nada."""
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        def _explota():
            raise RuntimeError("boom")

        monkeypatch.setattr(main, "construir_brief", _explota)
        r = client.post("/brief/send?token=brief-token")
        assert r.status_code == 502
        assert _SMTPFalso.enviados == []

    def test_envia_por_smtp_con_starttls(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch, puerto=587)

        r = client.post("/brief/send?token=brief-token")
        assert r.status_code == 200
        assert r.json()["enviado_a"] == "yo@test"
        assert len(_SMTPFalso.enviados) == 1
        msg = _SMTPFalso.enviados[0]
        assert msg["To"] == "yo@test"
        assert "Life Assistant" in msg["Subject"]
        cuerpo = msg.get_content()
        assert "## AGENDA DE HOY" in cuerpo
        assert "Redes" in cuerpo, "el correo debe llevar los datos ya reunidos"

    def test_puerto_465_usa_smtp_ssl(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        # Solo se mockea SMTP_SSL: si el código llamara a SMTP() intentaría conectar de verdad.
        configurar_smtp(monkeypatch, puerto=465)
        assert client.post("/brief/send?token=brief-token").status_code == 200
        assert len(_SMTPFalso.enviados) == 1

    def test_remitente_por_defecto_es_el_usuario_smtp(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch, remitente="")
        client.post("/brief/send?token=brief-token")
        assert _SMTPFalso.enviados[0]["From"] == "remite@test"

    def test_brief_from_manda_si_esta_puesto(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch, remitente="otro@test")
        client.post("/brief/send?token=brief-token")
        assert _SMTPFalso.enviados[0]["From"] == "otro@test"

    def test_token_por_cabecera(self, client, mock_requests, graph_token, monkeypatch):
        """El workflow lo manda por X-Auth-Token para que no acabe en los logs de acceso."""
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)
        r = client.post("/brief/send", headers={"X-Auth-Token": "brief-token"})
        assert r.status_code == 200
        assert len(_SMTPFalso.enviados) == 1

    def test_token_malo_no_envia_nada(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)
        assert client.post("/brief/send?token=mal").status_code == 403
        assert _SMTPFalso.enviados == [], "no debe salir correo sin token válido"

    def test_token_malo_no_reserva_el_dia(self, client, mock_requests, graph_token, monkeypatch):
        """Si un 403 dejara la reserva puesta, cualquiera con la URL del backend podría
        quedarse con el envío del día y bloquear el correo sin saber el token."""
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)
        client.post("/brief/send?token=mal")
        assert mock_requests.called("POST", "/rest/v1/brief_sends") == []


class TestUnSoloCorreoAlDia:
    """El workflow dispara tres veces por la mañana porque el cron de Actions se salta
    ejecuciones. Que de ahí salga un solo correo depende de la reserva en brief_sends."""

    def _hoy(self):
        return datetime.now(main.LOCAL_TZ).date().isoformat()

    def test_el_segundo_intento_del_dia_no_repite_correo(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        primera = client.post("/brief/send?token=brief-token")
        segunda = client.post("/brief/send?token=brief-token")

        assert primera.status_code == 200
        assert segunda.status_code == 200, "el respaldo no debe hacer fallar el workflow"
        assert segunda.json()["omitido"] is True
        assert len(_SMTPFalso.enviados) == 1, "solo un correo al día"

    def test_el_intento_omitido_no_consulta_las_fuentes(self, client, mock_requests, graph_token, monkeypatch):
        """El respaldo que llega tarde se va sin gastar Graph, Supabase ni Open-Meteo:
        la reserva se pide antes de construir nada."""
        montar_fuentes(mock_requests, enviados=[self._hoy()])
        configurar_smtp(monkeypatch)

        r = client.post("/brief/send?token=brief-token")

        assert r.status_code == 200 and r.json()["omitido"] is True
        assert mock_requests.called("GET", "graph.microsoft.com") == []
        assert mock_requests.called("GET", "api.open-meteo.com") == []
        assert _SMTPFalso.enviados == []

    def test_dia_distinto_vuelve_a_enviar(self, client, mock_requests, graph_token, monkeypatch):
        """La reserva es por fecha, no un interruptor: lo de ayer no bloquea lo de hoy."""
        ayer = (datetime.now(main.LOCAL_TZ).date() - timedelta(days=1)).isoformat()
        montar_fuentes(mock_requests, enviados=[ayer])
        configurar_smtp(monkeypatch)

        assert client.post("/brief/send?token=brief-token").status_code == 200
        assert len(_SMTPFalso.enviados) == 1

    def test_fallo_de_envio_libera_el_dia_para_el_siguiente_intento(self, client, mock_requests,
                                                                    graph_token, monkeypatch):
        """Lo importante del diseño: si la reserva se quedara puesta tras un fallo, un
        SMTP que parpadea a las 07:30 dejaría al día entero sin correo."""
        reservados = montar_brief_sends(mock_requests)
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        def _explota(asunto, cuerpo):
            raise TimeoutError("[Errno 110] Connection timed out")

        monkeypatch.setattr(main, "enviar_correo", _explota)
        assert client.post("/brief/send?token=brief-token").status_code == 502
        assert reservados == set(), "la reserva debe soltarse para que el respaldo reintente"

    def test_tras_un_fallo_el_respaldo_si_manda_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        fallos = {"quedan": 1}
        real = main.enviar_correo

        def _falla_la_primera(asunto, cuerpo):
            if fallos["quedan"]:
                fallos["quedan"] -= 1
                raise TimeoutError("SMTP no responde")
            return real(asunto, cuerpo)

        monkeypatch.setattr(main, "enviar_correo", _falla_la_primera)
        assert client.post("/brief/send?token=brief-token").status_code == 502
        assert client.post("/brief/send?token=brief-token").status_code == 200
        assert len(_SMTPFalso.enviados) == 1

    def test_falta_de_configuracion_tambien_libera_el_dia(self, client, mock_requests, graph_token, monkeypatch):
        """El 503 sale de enviar_correo() como HTTPException, que no pasa por el except
        del 502: sin el finally, la reserva se quedaba puesta."""
        reservados = montar_brief_sends(mock_requests)
        montar_fuentes(mock_requests)
        monkeypatch.setattr(main, "SMTP_HOST", "")
        monkeypatch.setattr(main, "BRIEF_TO", "yo@test")

        assert client.post("/brief/send?token=brief-token").status_code == 503
        assert reservados == set()

    def test_forzar_manda_aunque_el_dia_ya_este_enviado(self, client, mock_requests, graph_token, monkeypatch):
        """Los disparos a mano existen para probar el correo: si contestaran 'omitido'
        no habría forma de verlo una vez salió el de la mañana."""
        montar_fuentes(mock_requests, enviados=[self._hoy()])
        configurar_smtp(monkeypatch)

        # "true" y no "1": es lo que manda el workflow, que resuelve `FORZAR` con una
        # comparación de Actions y por tanto escribe el booleano en letra.
        r = client.post("/brief/send?token=brief-token&forzar=true")

        assert r.status_code == 200
        assert "omitido" not in r.json()
        assert len(_SMTPFalso.enviados) == 1

    def test_forzar_false_si_deduplica(self, client, mock_requests, graph_token, monkeypatch):
        """Lo que mandan los disparos programados. Si `forzar=false` colara como cierto
        (la cadena "false" es no vacía), los tres crons mandarían tres correos."""
        montar_fuentes(mock_requests, enviados=[self._hoy()])
        configurar_smtp(monkeypatch)

        r = client.post("/brief/send?token=brief-token&forzar=false")

        assert r.status_code == 200 and r.json()["omitido"] is True
        assert _SMTPFalso.enviados == []

    def test_forzar_no_toca_la_reserva_del_dia(self, client, mock_requests, graph_token, monkeypatch):
        """Un envío a mano no debe consumir ni soltar la reserva: si la soltara, el
        respaldo de las 07:00 mandaría un correo repetido."""
        reservados = montar_brief_sends(mock_requests, [self._hoy()])
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        client.post("/brief/send?token=brief-token&forzar=1")

        assert reservados == {self._hoy()}
        assert mock_requests.called("DELETE", "/rest/v1/brief_sends") == []

    def test_si_supabase_falla_al_reservar_no_se_manda_a_ciegas(self, client, mock_requests,
                                                                graph_token, monkeypatch):
        """Sin saber si el correo de hoy ya salió, mandar sería arriesgarse a duplicarlo:
        mejor un 502 que el workflow registra y que el siguiente intento reintenta."""
        mock_requests.add("POST", "/rest/v1/brief_sends", FakeResponse(None, 500, "boom"))
        montar_fuentes(mock_requests)
        configurar_smtp(monkeypatch)

        r = client.post("/brief/send?token=brief-token")

        assert r.status_code == 502
        assert _SMTPFalso.enviados == []
        assert "boom" not in r.text, "el detalle de Supabase no sale al cliente"

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


def montar_fuentes(mock_requests, eventos=None, clases=None, salud=None,
                   graph_status=200, salud_status=200, con_cliente=True):
    """Registra las cuatro fuentes del resumen (Graph, clima, salud, entrenamiento).

    El MockRouter resuelve en orden de REGISTRO y gana la primera coincidencia, así que
    todo lo que un test quiera cambiar tiene que pasarse por parámetro aquí: registrar
    otra ruta después no sobreescribe (ver CLAUDE.md).
    """
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


class TestMediasDeSalud:
    """Las medias van por ventana de FECHAS y con su n.

    Iban por "últimos N registros": con el histórico lleno de huecos (el Watch estuvo
    semanas sin poder escribir), la "media de 7 días" promediaba datos de meses atrás y
    una métrica con una sola observación salía con último, 7d y 30d idénticos. Quien
    lee el correo lo interpretaba como normalidad perfecta en vez de como ausencia de
    datos, y escribía conclusiones sobre desviaciones inexistentes.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def test_la_media_de_7d_no_alcanza_datos_mas_viejos(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [
            {"metric_date": (hoy - timedelta(days=20)).isoformat(),
             "metric_name": "resting_heart_rate", "value": 90, "unit": "bpm", "extra": {}},
            {"metric_date": hoy.isoformat(),
             "metric_name": "resting_heart_rate", "value": 50, "unit": "bpm", "extra": {}},
        ]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["fc_reposo"]["media_7d"] == 50, "la de hace 20 días no entra en la ventana de 7"
        assert s["fc_reposo"]["n_7d"] == 1
        assert s["fc_reposo"]["media_30d"] == 70 and s["fc_reposo"]["n_30d"] == 2

    def test_una_sola_observacion_se_declara_con_n(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [{"metric_date": hoy.isoformat(), "metric_name": "heart_rate_variability",
                  "value": 94, "unit": "ms", "extra": {}}]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["hrv"]["n_7d"] == 1 and s["hrv"]["n_30d"] == 1
        assert s["hrv"]["media_7d"] == s["hrv"]["ultimo"] == 94

    def test_una_fecha_futura_no_puede_ser_el_ultimo_valor(self, client, auth_headers, graph_token, mock_requests):
        """En la tabla hay un heart_rate fechado en diciembre: entraba en la ventana de
        30 días (el filtro es `gte`) y se convertía en "el último dato"."""
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [
            {"metric_date": hoy.isoformat(), "metric_name": "resting_heart_rate",
             "value": 53, "unit": "bpm", "extra": {}},
            {"metric_date": (hoy + timedelta(days=120)).isoformat(),
             "metric_name": "resting_heart_rate", "value": 77, "unit": "bpm", "extra": {}},
        ]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["fc_reposo"]["ultimo"] == 53 and s["fc_reposo"]["n_30d"] == 1

    def test_dice_cuantos_dias_atras_es_el_ultimo_dato(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [{"metric_date": (hoy - timedelta(days=25)).isoformat(),
                  "metric_name": "weight_body_mass", "value": 71.2, "unit": "kg", "extra": {}}]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["peso"]["dias_atras"] == 25


class TestMasMetricas:
    """El correo manda TODO lo que el Watch escribe, no una selección de siete.

    La consulta de `_brief_salud` no filtra por nombre: ya se trae la tabla entera de la
    ventana. Cada métrica que no se enviaba se estaba tirando después de haberla pedido.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def _una(self, nombre, valor, unidad="", extra=None, dias=0):
        fecha = (datetime.now(main.LOCAL_TZ).date() - timedelta(days=dias)).isoformat()
        return {"metric_date": fecha, "metric_name": nombre, "value": valor,
                "unit": unidad, "extra": extra or {}}

    def test_llegan_las_metricas_que_antes_se_tiraban(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests, [
            self._una("active_energy", 640, "kcal"),
            self._una("resting_energy", 1700, "kcal"),
            self._una("body_fat_percentage", 17.4, "%"),
            self._una("lean_body_mass", 61.2, "kg"),
            self._una("walking_running_distance", 6.4, "km"),
            self._una("time_in_daylight", 95, "min"),
            self._una("cardio_recovery", 31, "bpm"),
            self._una("walking_heart_rate_average", 104, "bpm"),
            self._una("apple_stand_hour", 12, "h"),
            self._una("flights_climbed", 9, "pisos"),
            self._una("physical_effort", 4.2, "MET"),
        ])
        assert s["energia_activa"]["ultimo"] == 640
        assert s["energia_basal"]["ultimo"] == 1700
        assert s["grasa"]["ultimo"] == 17.4 and s["masa_magra"]["ultimo"] == 61.2
        assert s["distancia"]["ultimo"] == 6.4 and s["luz_natural"]["ultimo"] == 95
        assert s["recuperacion_fc"]["ultimo"] == 31 and s["fc_caminando"]["ultimo"] == 104
        assert s["de_pie"]["ultimo"] == 12 and s["pisos"]["ultimo"] == 9
        assert s["esfuerzo"]["ultimo"] == 4.2

    def test_la_unidad_de_la_fila_manda_sobre_la_declarada(self, client, auth_headers, graph_token, mock_requests):
        """La ingesta convierte kJ a kcal y no toda métrica llega en la unidad esperada."""
        s = self._pide(client, auth_headers, mock_requests,
                       [self._una("walking_running_distance", 4200, "m")])
        assert s["distancia"]["unidad"] == "m"

    def test_el_hrv_no_viaja_con_quince_decimales(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests,
                       [self._una("heart_rate_variability", 44.476655296663246, "ms")])
        assert s["hrv"]["ultimo"] == 44.48


class TestCerosLegitimos:
    """Un 0 de pisos ocurrió; un 0 de HRV es el sensor sin medir.

    Antes se descartaba todo lo que no fuera > 0, así que los días de sofá desaparecían
    del cálculo y las medias de las acumulativas salían sesgadas al alza.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def _serie(self, nombre, valores, unidad=""):
        hoy = datetime.now(main.LOCAL_TZ).date()
        return [{"metric_date": (hoy - timedelta(days=i)).isoformat(),
                 "metric_name": nombre, "value": v, "unit": unidad, "extra": {}}
                for i, v in enumerate(reversed(valores))]

    def test_el_cero_cuenta_en_una_acumulativa(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests, self._serie("flights_climbed", [10, 0, 2]))
        assert s["pisos"]["n_7d"] == 3, "el día a cero es un día con dato"
        assert s["pisos"]["media_7d"] == 4, "descartarlo daría 6"
        assert s["pisos"]["ultimo"] == 2

    def test_un_dia_entero_a_cero_sigue_siendo_el_ultimo_valor(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests, self._serie("step_count", [8000, 0]))
        assert s["pasos"]["ultimo"] == 0 and s["pasos"]["n_7d"] == 2

    def test_el_cero_de_un_sensor_se_descarta(self, client, auth_headers, graph_token, mock_requests):
        """Promediar un 0 de FC en reposo sería inventarse una bradicardia."""
        s = self._pide(client, auth_headers, mock_requests, self._serie("resting_heart_rate", [56, 0, 58]))
        assert s["fc_reposo"]["n_7d"] == 2 and s["fc_reposo"]["media_7d"] == 57

    def test_negativos_fuera_en_cualquier_caso(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests, self._serie("step_count", [-5, 900]))
        assert s["pasos"]["n_7d"] == 1


class TestRangoDeFrecuenciaCardiaca:
    def test_min_y_max_salen_del_extra_con_mayuscula(self, client, auth_headers, graph_token, mock_requests):
        """heart_rate se exporta como rango diario y trae Avg/Min/Max con mayúscula, sin
        la versión en minúsculas: es la trampa que ya sorteaba la ingesta."""
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        montar_fuentes(mock_requests, salud=[
            {"metric_date": hoy, "metric_name": "heart_rate", "value": 74,
             "unit": "bpm", "extra": {"Min": 48, "Max": 163}},
        ])
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert s["fc_media"]["ultimo"] == 74
        assert s["fc_media"]["min"] == 48 and s["fc_media"]["max"] == 163

    def test_sin_extremos_no_se_inventan(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        montar_fuentes(mock_requests, salud=[
            {"metric_date": hoy, "metric_name": "heart_rate", "value": 74, "unit": "bpm", "extra": {}},
        ])
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert "min" not in s["fc_media"] and "max" not in s["fc_media"]


class TestSerieDiaria:
    """Las medias dicen dónde estás; la serie, hacia dónde vas.

    Y es lo único con lo que quien lee el correo puede cruzar dos métricas entre sí: el
    motor de correlaciones vive en helpers.js y no se porta al backend a propósito.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def test_una_posicion_por_dia_con_los_huecos_marcados(self, client, auth_headers, graph_token, mock_requests):
        """Comprimir los días sin dato desplazaría todo lo demás y cualquier cruce con
        otra serie acabaría comparando fechas distintas."""
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [
            {"metric_date": (hoy - timedelta(days=d)).isoformat(), "metric_name": "step_count",
             "value": v, "unit": "pasos", "extra": {}}
            for d, v in ((4, 1000), (2, 3000), (0, 5000))
        ]
        s = self._pide(client, auth_headers, mock_requests, filas)
        serie = s["series"]["pasos"]
        assert len(serie) == main.BRIEF_DIAS_SALUD
        assert serie[-5:] == [1000, None, 3000, None, 5000]
        assert s["series_hasta"] == hoy.isoformat()
        assert s["series_desde"] == (hoy - timedelta(days=main.BRIEF_DIAS_SALUD - 1)).isoformat()

    def test_sin_fondo_suficiente_no_hay_serie(self, client, auth_headers, graph_token, mock_requests):
        """Con dos días la línea es casi toda huecos: el último valor ya lo cuenta."""
        hoy = datetime.now(main.LOCAL_TZ).date()
        filas = [
            {"metric_date": (hoy - timedelta(days=d)).isoformat(), "metric_name": "vo2_max",
             "value": 48, "unit": "ml/kg/min", "extra": {}} for d in (0, 3)
        ]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["vo2max"]["ultimo"] == 48, "el resumen sigue saliendo"
        assert "vo2max" not in (s.get("series") or {})

    def test_sin_ninguna_serie_no_hay_seccion(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        s = self._pide(client, auth_headers, mock_requests, [
            {"metric_date": hoy, "metric_name": "step_count", "value": 900,
             "unit": "pasos", "extra": {}},
        ])
        assert "series" not in s


class TestFasesDeSueno:
    """Del sueño solo viajaba la cantidad: las fases son la diferencia entre haber
    dormido siete horas y haber descansado."""

    def _noches(self, n=4, **extra):
        hoy = datetime.now(main.LOCAL_TZ).date()
        return [{"metric_date": (hoy - timedelta(days=i)).isoformat(),
                 "metric_name": "sleep_analysis", "value": 7.0, "unit": "h",
                 "extra": {"sleep_start": "23:45", "deep": 1.1, "rem": 1.6,
                           "core": 4.0, "awake": 0.3, **extra}}
                for i in range(n)]

    def test_las_fases_de_anoche_van_en_el_resumen(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._noches())
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert s["sueno"]["fases"] == {"profundo": 1.1, "rem": 1.6, "ligero": 4.0, "despierto": 0.3}

    def test_core_y_light_son_la_misma_fase(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._noches(light=0.5))
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert s["sueno"]["fases"]["ligero"] == 4.5

    def test_las_fases_tambien_tienen_serie(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._noches())
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert s["series"]["sueno_profundo"][-1] == 1.1
        assert s["series"]["sueno_rem"][-4:] == [1.6, 1.6, 1.6, 1.6]
        assert s["series"]["sueno_despierto"][-1] == 0.3

    def test_sin_fases_no_se_inventan(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        montar_fuentes(mock_requests, salud=[
            {"metric_date": hoy, "metric_name": "sleep_analysis", "value": 7.0,
             "unit": "h", "extra": {"sleep_start": "23:45"}},
        ])
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert "fases" not in s["sueno"] and s["sueno"]["ultimo"] == 7.0


class TestDetalleDeEntrenos:
    """"Hace 2 días" no dice si fue una caminata o una hora de pesas."""

    def _con_entrenos(self, lista, dias=1):
        fecha = (datetime.now(main.LOCAL_TZ).date() - timedelta(days=dias)).isoformat()
        return [{"metric_date": fecha, "metric_name": "workouts", "value": len(lista),
                 "unit": "count", "extra": {"workouts": lista}}]

    def test_tipo_duracion_calorias_y_hora(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._con_entrenos([
            {"name": "Fuerza funcional", "duration": 3720,
             "start": "2026-08-05 19:15:00 +0200", "activeEnergy": {"qty": 412.4}},
        ]))
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        e = s["entrenos"][0]
        assert e["tipo"] == "Fuerza funcional"
        assert e["minutos"] == 62.0, "la duración llega en segundos"
        assert e["kcal"] == 412
        assert e["hora"] == "19:15"

    def test_las_calorias_pueden_venir_sueltas_o_con_otro_nombre(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._con_entrenos([
            {"name": "Caminata", "duration": 1800, "totalEnergyBurned": 150},
        ]))
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert s["entrenos"][0]["kcal"] == 150

    def test_se_acotan_a_los_mas_recientes(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._con_entrenos(
            [{"name": f"W{i}", "duration": 600} for i in range(main.BRIEF_MAX_ENTRENOS + 5)]))
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert len(s["entrenos"]) == main.BRIEF_MAX_ENTRENOS

    def test_un_extra_sin_lista_no_revienta(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests, salud=self._con_entrenos(["no soy un dict"]))
        s = client.get("/brief", headers=auth_headers).json()["salud"]
        assert "entrenos" not in s
        assert s["ultimo_entreno"]["dias"] == 1, "el contador de siempre sigue"


class TestMinutosEntreno:
    """Mismo umbral que el widget de entrenamientos del frontend: el correo y la
    pantalla no pueden decir cosas distintas del mismo entreno."""

    def test_segundos_a_minutos(self):
        assert main._minutos_entreno(3600) == 60.0

    def test_los_minutos_de_versiones_antiguas_se_respetan(self):
        assert main._minutos_entreno(45) == 45.0

    def test_basura_no_revienta(self):
        assert main._minutos_entreno(None) is None
        assert main._minutos_entreno("x") is None
        assert main._minutos_entreno(0) is None


class TestCifra:
    def test_los_enteros_no_arrastran_el_punto_cero(self):
        assert main._cifra(55.0) == "55"

    def test_sin_dato_no_se_lee_como_valor(self):
        assert main._cifra(None) == "-", "'None' en mitad de una fila de cifras engaña"


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

    def test_la_salud_lleva_el_n_y_la_edad_del_dato(self):
        """Sin el n y sin la antigüedad, tres cifras iguales se leen como estabilidad."""
        texto = main.render_brief_texto({
            "fecha": "2026-08-05", "dia_semana": "miércoles", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {"hrv": {"unidad": "ms", "ultimo": 94, "fecha": "2026-08-04",
                              "dias_atras": 1, "media_7d": 94, "n_7d": 1,
                              "media_30d": 94, "n_30d": 1}},
        })
        assert "n=1" in texto and "ayer" in texto
        assert "no hay base para hablar de desviación" in texto

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

    def test_la_serie_diaria_dice_su_ventana_y_marca_los_huecos(self):
        """Sin las fechas de los extremos, una lista de treinta números no se puede
        alinear con nada — y un hueco sin marcar desplaza todas las posiciones."""
        texto = main.render_brief_texto({
            "fecha": "2026-08-06", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {
                "pasos": {"unidad": "pasos", "ultimo": 5000, "fecha": "2026-08-06",
                          "dias_atras": 0, "media_7d": 3000, "n_7d": 3,
                          "media_30d": 3000, "n_30d": 3},
                "series": {"pasos": [1000, None, 5000]},
                "series_desde": "2026-08-04", "series_hasta": "2026-08-06",
            },
        })
        assert "## SERIE DIARIA" in texto
        assert "2026-08-04 → 2026-08-06" in texto
        assert "Pasos                1000 - 5000" in texto

    def test_los_entrenos_van_con_su_detalle(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-06", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {"entrenos": [
                {"fecha": "2026-08-05", "tipo": "Fuerza funcional", "minutos": 62.0,
                 "kcal": 412, "hora": "19:15"},
                {"fecha": "2026-08-06", "tipo": "Caminata", "minutos": None,
                 "kcal": None, "hora": None},
            ]},
        })
        assert "## ENTRENOS DEL WATCH" in texto
        assert "2026-08-05 19:15  Fuerza funcional — 62 min · 412 kcal" in texto
        assert "2026-08-06  Caminata" in texto, "sin duración ni calorías, el tipo basta"

    def test_las_fases_y_el_rango_de_fc_se_pintan(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-06", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {
                "sueno": {"unidad": "h", "ultimo": 7.2, "fecha": "2026-08-06", "dias_atras": 0,
                          "media_7d": 7.1, "n_7d": 5, "media_30d": 7.0, "n_30d": 20,
                          "inicio": "23:45",
                          "fases": {"profundo": 1.1, "rem": 1.6, "ligero": 4.2, "despierto": 0.3}},
                "fc_media": {"unidad": "bpm", "ultimo": 74, "fecha": "2026-08-06", "dias_atras": 0,
                             "media_7d": 75, "n_7d": 7, "media_30d": 76, "n_30d": 30,
                             "min": 48, "max": 163},
            },
        })
        assert "profundo 1.1 h · REM 1.6 h · ligero 4.2 h · despierto 0.3 h" in texto
        assert "min 48 / máx 163" in texto

    def test_sin_series_ni_entrenos_no_aparecen_las_secciones(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-06", "dia_semana": "jueves", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {},
        })
        assert "## SERIE DIARIA" not in texto and "## ENTRENOS DEL WATCH" not in texto

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


class TestHistoricoQueNoSeVeia:
    """Dos formas de tener el dato guardado y contarlo como si no existiera.

    Las dos hacen lo mismo por caminos distintos: dejan fuera de las medias y de las
    series días que sí están en la tabla, y el `n` del correo los cuenta como ausencia
    de datos. Es la peor forma de mentir de este resumen, porque quien lo lee no tiene
    manera de distinguirlo de un sensor que no midió.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def _dias(self, n, nombre, valor=None, extra=None, unidad=""):
        hoy = datetime.now(main.LOCAL_TZ).date()
        return [{"metric_date": (hoy - timedelta(days=i)).isoformat(), "metric_name": nombre,
                 "value": valor, "unit": unidad, "extra": dict(extra or {})} for i in range(n)]

    def test_el_valor_que_quedo_en_extra_cuenta(self, client, auth_headers, graph_token, mock_requests):
        """La ingesta guardó `value` a null y el promedio dentro de `extra` como "Avg"
        (buscaba "avg" en minúscula). Está arreglada, pero esas filas siguen en la tabla
        y son histórico real: descartarlas es tirar semanas de dato recibido."""
        s = self._pide(client, auth_headers, mock_requests,
                       self._dias(6, "heart_rate", None, {"Avg": 64.7, "Min": 47, "Max": 114}, "bpm"))
        assert s["fc_media"]["ultimo"] == 64.7
        assert s["fc_media"]["n_30d"] == 6
        assert len([v for v in s["series"]["fc_media"] if v is not None]) == 6

    def test_los_dos_nombres_de_una_metrica_son_una_sola_serie(self, client, auth_headers, graph_token, mock_requests):
        """Health Auto Export escribe `apple_exercise_time` y el Atajo `exercise_time`.
        Quedarse con el primer nombre con filas descartaba el histórico del otro: tres
        días de dato del exportador tapaban un mes entero del Atajo."""
        filas = (self._dias(3, "apple_exercise_time", 42, unidad="min")
                 + [f | {"metric_date": (datetime.now(main.LOCAL_TZ).date()
                                          - timedelta(days=i + 3)).isoformat()}
                    for i, f in enumerate(self._dias(20, "exercise_time", 35, unidad="min"))])
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["ejercicio"]["n_30d"] == 23, "los dos nombres suman, no se excluyen"
        assert s["ejercicio"]["ultimo"] == 42, "el más reciente sigue siendo el último"

    def test_si_los_dos_nombres_escriben_el_mismo_dia_manda_el_preferente(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        s = self._pide(client, auth_headers, mock_requests, [
            {"metric_date": hoy, "metric_name": "exercise_time", "value": 35, "unit": "min", "extra": {}},
            {"metric_date": hoy, "metric_name": "apple_exercise_time", "value": 42, "unit": "min", "extra": {}},
        ])
        assert s["ejercicio"]["ultimo"] == 42
        assert s["ejercicio"]["n_30d"] == 1, "el mismo día no se cuenta dos veces"

    def test_el_hueco_de_un_nombre_lo_rellena_el_otro(self, client, auth_headers, graph_token, mock_requests):
        """El nombre preferente puede tener la fila sin medida: entonces vale la del otro."""
        hoy = datetime.now(main.LOCAL_TZ).date().isoformat()
        s = self._pide(client, auth_headers, mock_requests, [
            {"metric_date": hoy, "metric_name": "apple_exercise_time", "value": None, "unit": "min", "extra": {}},
            {"metric_date": hoy, "metric_name": "exercise_time", "value": 35, "unit": "min", "extra": {}},
        ])
        assert s["ejercicio"]["ultimo"] == 35

    def test_el_sueño_tambien_fusiona_sus_dos_nombres(self, client, auth_headers, graph_token, mock_requests):
        hoy = datetime.now(main.LOCAL_TZ).date()
        s = self._pide(client, auth_headers, mock_requests, [
            {"metric_date": (hoy - timedelta(days=1)).isoformat(), "metric_name": "sleep",
             "value": 6.5, "unit": "h", "extra": {}},
            {"metric_date": hoy.isoformat(), "metric_name": "sleep_analysis",
             "value": 7.2, "unit": "h", "extra": {}},
        ])
        assert s["sueno"]["n_30d"] == 2
        assert s["sueno"]["ultimo"] == 7.2

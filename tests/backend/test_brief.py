"""Tests del resumen diario por correo (/brief y /brief/send).

El backend manda DATOS CRUDOS, sin interpretarlos: el consumidor es la rutina de
Claude Code que compone el correo diario del usuario leyendo su buzón. Por eso aquí
no se comprueba ninguna conclusión — solo que los datos salen completos y correctos,
y que un fallo de una fuente no tumba el resto del resumen.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

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


class TestUsoDelReloj:
    """Saber cuándo estuvo puesto el reloj es lo que separa "no llegó el dato" de "no
    se pudo medir".

    El 07/08 el correo mandó sueño, HRV, FC en reposo y respiración con n=3 mientras los
    pasos iban con n=29 y se leyó como una ingesta rota: el reloj llevaba un mes en un
    cajón. La asimetría "pasos sí, todo lo demás no" es la huella de eso, y hasta ahora
    había que reconocerla a ojo.
    """

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def _fila(self, nombre, valor, dias=0, extra=None, unidad=""):
        fecha = datetime.now(main.LOCAL_TZ).date() - timedelta(days=dias)
        return {"metric_date": fecha.isoformat(), "metric_name": nombre,
                "value": valor, "unit": unidad, "extra": extra or {}}

    def _mes(self, dias_con_reloj=3, dias_total=30):
        """Pasos todos los días (los cuenta el móvil) y reloj solo los más recientes."""
        filas = [self._fila("step_count", 8000, i) for i in range(dias_total)]
        for i in range(dias_con_reloj):
            filas += [
                self._fila("heart_rate_variability", 40 + i, i, unidad="ms"),
                self._fila("heart_rate", 70, i, unidad="bpm"),
                self._fila("sleep_analysis", 7.2, i, {"sleep_start": "23:40"}, "h"),
            ]
        return filas

    def test_distingue_los_dias_con_reloj_de_los_dias_con_solo_movil(
            self, client, auth_headers, graph_token, mock_requests):
        r = self._pide(client, auth_headers, mock_requests, self._mes())["reloj"]
        assert r["dias_puesto"] == 3 and r["noches_puesto"] == 3
        assert r["marcas"].endswith("AAA"), r["marcas"]
        assert set(r["marcas"][:-3]) == {"."}, "días con datos del móvil y sin reloj"
        assert r["dias_desde"] == 0 and r["racha_sin_reloj"] == 0

    def test_un_dia_sin_datos_de_nada_no_es_un_dia_sin_reloj(
            self, client, auth_headers, graph_token, mock_requests):
        """Si no llegó NADA, no se sabe si hubo reloj o falló la sincronización. Darlo
        por día sin reloj convertiría una caída de la ingesta en un hábito."""
        r = self._pide(client, auth_headers, mock_requests, [
            self._fila("heart_rate", 70, 3, unidad="bpm"),
            self._fila("step_count", 8000, 0),
        ])["reloj"]
        assert r["marcas"].endswith("D--."), r["marcas"]
        assert r["sin_datos"] == 28, "27 días vacíos por delante más los dos del hueco"
        assert r["racha_sin_reloj"] == 0, "los días sin datos ni suman ni rompen la racha"

    def test_la_racha_sin_reloj_no_cuenta_hoy(self, client, auth_headers, graph_token, mock_requests):
        """El correo sale por la mañana, con el día a medias: contarlo se inventaría un
        día sin reloj que todavía no ha pasado."""
        r = self._pide(client, auth_headers, mock_requests, [
            self._fila("heart_rate", 70, 3, unidad="bpm"),
            *[self._fila("step_count", 8000, i) for i in range(4)],
        ])["reloj"]
        assert r["racha_sin_reloj"] == 2, "ayer y anteayer; hoy queda fuera"
        assert r["hoy"] == "sin_reloj" and r["anoche"] is False

    def test_quitarselo_para_dormir_marca_el_dia_pero_no_la_noche(
            self, client, auth_headers, graph_token, mock_requests):
        r = self._pide(client, auth_headers, mock_requests, [
            self._fila("heart_rate", 72, 0, unidad="bpm"),
            self._fila("apple_stand_hour", 11, 0, unidad="h"),
        ])["reloj"]
        assert r["dias_puesto"] == 1 and r["noches_puesto"] == 0
        assert r["marcas"].endswith("D") and r["anoche"] is False

    def test_los_ceros_del_atajo_no_dan_el_dia_por_llevado(
            self, client, auth_headers, graph_token, mock_requests):
        """El Atajo guarda 0 los días que no encuentra muestras — todos los días sin
        reloj. La fila existe sin que se haya medido nada."""
        r = self._pide(client, auth_headers, mock_requests, [
            self._fila("heart_rate_variability", 0, 0, unidad="ms"),
            self._fila("sleep_analysis", 0, 0, unidad="h"),
            self._fila("step_count", 8000, 0),
        ])["reloj"]
        assert r["noches_puesto"] == 0 and r["marcas"].endswith(".")

    def test_una_noche_anulada_a_mano_no_es_una_noche_con_reloj(
            self, client, auth_headers, graph_token, mock_requests):
        """Se anulan las noches que salieron mal, y la razón habitual es el reloj en el
        cargador: darla por medida le pondría a la media un denominador ya descartado."""
        s = self._pide(client, auth_headers, mock_requests, [
            self._fila("sleep_analysis", 7.2, 1, {"sleep_start": "23:40"}, "h"),
            self._fila("sleep_analysis", 2.1, 0, {"excluded": True}, "h"),
        ])
        assert s["reloj"]["noches_puesto"] == 1 and s["reloj"]["anoche"] is False
        assert s["sueno"]["n_7d"] == 1 and s["sueno"]["posibles_7d"] == 1

    def test_el_sueno_con_las_fases_en_extra_si_cuenta(
            self, client, auth_headers, graph_token, mock_requests):
        """`value` a 0 con las fases dentro de `extra` es una noche medida de verdad."""
        r = self._pide(client, auth_headers, mock_requests, [
            self._fila("sleep_analysis", 0, 0, {"deep": 1.2, "rem": 1.5, "core": 4.0}, "h"),
        ])["reloj"]
        assert r["noches_puesto"] == 1 and r["anoche"] is True


class TestMediasContraElReloj:
    """Una métrica del Watch solo puede tener dato los días que estuvo puesto: su n hay
    que leerlo contra eso, no contra el calendario."""

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def _fila(self, nombre, valor, dias=0, unidad=""):
        fecha = datetime.now(main.LOCAL_TZ).date() - timedelta(days=dias)
        return {"metric_date": fecha.isoformat(), "metric_name": nombre,
                "value": valor, "unit": unidad, "extra": {}}

    def test_la_media_del_reloj_lleva_su_denominador(
            self, client, auth_headers, graph_token, mock_requests):
        filas = [self._fila("step_count", 8000, i) for i in range(30)]
        filas += [self._fila("heart_rate_variability", 40, i, "ms") for i in range(3)]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["hrv"]["n_30d"] == 3 and s["hrv"]["posibles_30d"] == 3
        assert s["hrv"]["n_7d"] == 3 and s["hrv"]["posibles_7d"] == 3

    def test_lo_que_cuenta_el_movil_no_lleva_denominador_de_reloj(
            self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests,
                       [self._fila("step_count", 8000, i) for i in range(3)])
        assert s["pasos"]["n_7d"] == 3
        assert "posibles_7d" not in s["pasos"], "los pasos no dependen de llevar el reloj"

    def test_un_cero_del_reloj_un_dia_sin_reloj_es_un_hueco(
            self, client, auth_headers, graph_token, mock_requests):
        """0 horas de pie con el reloj en el cajón hunde la media igual que promediar
        un HRV de 0 se inventaría una bradicardia."""
        filas = [self._fila("apple_stand_hour", 0, i, "h") for i in range(1, 6)]
        filas += [self._fila("apple_stand_hour", 12, 0, "h"),
                  self._fila("heart_rate", 70, 0, "bpm"),
                  *[self._fila("step_count", 8000, i) for i in range(6)]]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["de_pie"]["n_7d"] == 1 and s["de_pie"]["media_7d"] == 12

    def test_un_cero_con_el_reloj_puesto_si_es_un_dato(
            self, client, auth_headers, graph_token, mock_requests):
        """Un día de sofá con el reloj puesto ocurrió y tiene que bajar la media."""
        filas = [self._fila("heart_rate", 70, i, "bpm") for i in range(2)]
        filas += [self._fila("apple_stand_hour", 12, 1, "h"),
                  self._fila("apple_stand_hour", 0, 0, "h")]
        s = self._pide(client, auth_headers, mock_requests, filas)
        assert s["de_pie"]["n_7d"] == 2 and s["de_pie"]["media_7d"] == 6

    def test_el_cero_de_los_pasos_sigue_contando(
            self, client, auth_headers, graph_token, mock_requests):
        """Los pasos los cuenta el teléfono: ahí un 0 no lo explica el reloj."""
        s = self._pide(client, auth_headers, mock_requests,
                       [self._fila("step_count", 8000, 1), self._fila("step_count", 0, 0)])
        assert s["pasos"]["n_7d"] == 2 and s["pasos"]["media_7d"] == 4000


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
        assert "## RELOJ" not in texto, "treinta huecos no dicen nada que no diga (sin datos)"

    def test_el_uso_del_reloj_se_pinta_con_su_leyenda(self):
        """Sin la leyenda, una fila de letras no se puede leer; sin las fechas de los
        extremos, no se puede alinear con la serie diaria."""
        texto = main.render_brief_texto({
            "fecha": "2026-08-16", "dia_semana": "sábado", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {"reloj": {
                "desde": "2026-08-12", "hasta": "2026-08-16", "dias_ventana": 5,
                "marcas": "..DAA", "dias_puesto": 3, "noches_puesto": 2,
                "dias_puesto_7d": 3, "noches_puesto_7d": 2, "sin_datos": 0,
                "hoy": "ambos", "anoche": True, "ultimo": "2026-08-16",
                "dias_desde": 0, "racha_sin_reloj": 0,
            }},
        })
        assert "## RELOJ  (2026-08-12 → 2026-08-16, 5 días)" in texto
        assert "Puesto 3/5 días y 2/5 noches" in texto
        assert ". . D A A" in texto, "una posición por día, contable"
        assert "A = día y noche" in texto and "- = sin datos de nada" in texto
        assert "Anoche               con reloj" in texto

    def test_la_media_del_reloj_se_pinta_contra_los_dias_que_se_pudo_medir(self):
        """n=3 a secas se lee como ingesta rota; n=3/3 dice que no falta ni un día."""
        texto = main.render_brief_texto({
            "fecha": "2026-08-16", "dia_semana": "sábado", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {
                "hrv": {"unidad": "ms", "ultimo": 42, "fecha": "2026-08-16", "dias_atras": 0,
                        "media_7d": 41, "n_7d": 3, "posibles_7d": 3,
                        "media_30d": 41, "n_30d": 3, "posibles_30d": 3},
                "pasos": {"unidad": "pasos", "ultimo": 8000, "fecha": "2026-08-16",
                          "dias_atras": 0, "media_7d": 8100, "n_7d": 7,
                          "media_30d": 8500, "n_30d": 29},
                "reloj": {"desde": "2026-07-18", "hasta": "2026-08-16", "dias_ventana": 30,
                          "marcas": "." * 27 + "AAA", "dias_puesto": 3, "noches_puesto": 3,
                          "dias_puesto_7d": 3, "noches_puesto_7d": 3, "sin_datos": 0,
                          "hoy": "ambos", "anoche": True, "ultimo": "2026-08-16",
                          "dias_desde": 0, "racha_sin_reloj": 0},
            },
        })
        assert "n=3/3" in texto
        assert "n=7," in texto and "n=29)" in texto, "los pasos no llevan denominador"
        assert "falta reloj" in texto

    def test_los_dias_sin_datos_de_nada_se_avisan_aparte(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-16", "dia_semana": "sábado", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {"reloj": {
                "desde": "2026-08-12", "hasta": "2026-08-16", "dias_ventana": 5,
                "marcas": "--..A", "dias_puesto": 1, "noches_puesto": 1,
                "dias_puesto_7d": 1, "noches_puesto_7d": 1, "sin_datos": 2,
                "hoy": "ambos", "anoche": True, "ultimo": "2026-08-16",
                "dias_desde": 0, "racha_sin_reloj": 2,
            }},
        })
        assert "2 día(s) sin datos de NINGUNA fuente" in texto
        assert "2 día(s) seguidos antes de hoy" in texto

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

        def _explota(asunto, cuerpo, adjunto=None):
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
        cuerpo = msg.get_body(preferencelist=("plain",)).get_content()
        assert "## AGENDA DE HOY" in cuerpo
        assert "Redes" in cuerpo, "el correo debe llevar los datos ya reunidos"

        # El texto lo lee una persona y eso le pone un techo a lo que cabe; el adjunto
        # lleva lo mismo en JSON para quien lo procese, sin tener que elegir.
        adjuntos = list(msg.iter_attachments())
        assert len(adjuntos) == 1
        assert adjuntos[0].get_filename().startswith("brief-")
        assert json.loads(adjuntos[0].get_content())["agenda"][0]["titulo"] == "Redes"

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


class TestDiasAtipicos:
    """Marcar dónde mirar no es interpretar: el correo manda ~600 números y sin marcas
    hay que leerlos todos para encontrar el raro."""

    def _serie(self, nombre, valores, unidad=""):
        hoy = datetime.now(main.LOCAL_TZ).date()
        return [{"metric_date": (hoy - timedelta(days=i)).isoformat(),
                 "metric_name": nombre, "value": v, "unit": unidad, "extra": {}}
                for i, v in enumerate(reversed(valores))]

    def _pide(self, client, auth_headers, mock_requests, filas):
        montar_fuentes(mock_requests, salud=filas)
        return client.get("/brief", headers=auth_headers).json()["salud"]

    def test_señala_el_dia_que_se_sale(self, client, auth_headers, graph_token, mock_requests):
        s = self._pide(client, auth_headers, mock_requests,
                       self._serie("resting_heart_rate", [55, 56, 57] * 5 + [80], "bpm"))
        atipicos = s["atipicos"]
        assert len(atipicos) == 1
        assert atipicos[0]["metrica"] == "fc_reposo" and atipicos[0]["valor"] == 80
        assert atipicos[0]["sigmas"] > 2

    def test_la_media_se_calcula_sin_el_propio_dia(self, client, auth_headers, graph_token, mock_requests):
        """Con ventanas cortas, un valor extremo arrastra la media hacia sí mismo y se
        tapa solo: cuanto más raro es, menos raro parece."""
        s = self._pide(client, auth_headers, mock_requests,
                       self._serie("resting_heart_rate", [55, 56, 57] * 5 + [80], "bpm"))
        assert s["atipicos"][0]["media"] == 56, "la media de referencia excluye el día señalado"

    def test_sin_fondo_no_se_señala_nada(self, client, auth_headers, graph_token, mock_requests):
        """Con cuatro observaciones la sigma es tan ruidosa como el dato: marcaría todo."""
        s = self._pide(client, auth_headers, mock_requests,
                       self._serie("resting_heart_rate", [56, 56, 56, 90], "bpm"))
        assert "atipicos" not in s

    def test_una_serie_sin_dispersion_no_señala_nada(self, client, auth_headers, graph_token, mock_requests):
        """Sin dispersión no hay escala contra la que medir la desviación: la sigma es 0
        y un día distinto quedaría a infinitas sigmas, que no es una cifra que decir."""
        s = self._pide(client, auth_headers, mock_requests,
                       self._serie("step_count", [8000] * 15, "pasos"))
        assert "atipicos" not in s

    def test_se_pintan_en_el_correo_con_su_referencia(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-16", "dia_semana": "sábado", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "entrenamiento": {},
            "salud": {"atipicos": [{"metrica": "fc_reposo", "fecha": "2026-08-14", "valor": 80,
                                    "unidad": "bpm", "media": 56, "sigmas": 3.2}]},
        })
        assert "## DÍAS ATÍPICOS" in texto
        assert "2026-08-14" in texto and "80 bpm" in texto
        assert "por encima" in texto and "su media 56" in texto


class TestQueHaCambiado:
    """El correo es idéntico al 90% en días consecutivos: lo que hace falta leer entero
    es el otro 10%."""

    def test_la_instantanea_guarda_solo_lo_comparable(self):
        inst = main._instantanea_brief({
            "fecha": "2026-08-16",
            "salud": {"hrv": {"ultimo": 42, "fecha": "2026-08-16", "media_7d": 40},
                      "series": {"hrv": [1, 2, 3]}, "reloj": {"ultimo": "2026-08-16", "racha_sin_reloj": 0}},
            "entregas": [{"titulo": "Práctica 3", "dias": 2, "fecha": "2026-08-18"}],
            "entrenamiento": {"sesiones_desde_cobro": 6, "importe_pendiente": 96.0},
        })
        assert inst["metricas"]["hrv"] == {"valor": 42, "fecha": "2026-08-16"}
        assert inst["entregas"] == ["Práctica 3"]
        assert "series" not in inst, "las series diarias no se guardan: su diff es la propia serie"

    def _datos(self, hrv_valor, hrv_fecha, entregas=("Práctica 3",)):
        return {
            "fecha": "2026-08-16",
            "salud": {"hrv": {"ultimo": hrv_valor, "fecha": hrv_fecha}},
            "entregas": [{"titulo": t} for t in entregas],
            "entrenamiento": {"sesiones_desde_cobro": 6, "importe_pendiente": 96.0},
        }

    def test_una_metrica_se_movio_si_trae_fecha_nueva(self):
        previa  = main._instantanea_brief(self._datos(40, "2026-08-15"))
        cambios = main._cambios_desde(previa, self._datos(55, "2026-08-16"))
        assert cambios["metricas_nuevas"][0] == {
            "metrica": "hrv", "antes": 40, "ahora": 55, "delta": 15, "fecha": "2026-08-16"}

    def test_el_mismo_dato_releido_no_es_novedad(self):
        """Comparar solo el valor daría por novedad el dato de ayer leído otra vez."""
        previa  = main._instantanea_brief(self._datos(40, "2026-08-15"))
        cambios = main._cambios_desde(previa, self._datos(40, "2026-08-15"))
        assert "metricas_nuevas" not in cambios
        assert cambios["metricas_sin_novedad"] == ["hrv"]

    def test_las_entregas_nuevas_y_las_que_desaparecen(self):
        previa  = main._instantanea_brief(self._datos(40, "2026-08-15", ("Práctica 3",)))
        cambios = main._cambios_desde(previa, self._datos(40, "2026-08-15", ("Práctica 4",)))
        assert cambios["entregas_nuevas"] == ["Práctica 4"]
        assert cambios["entregas_fuera"] == ["Práctica 3"]

    def test_sin_instantanea_previa_no_hay_seccion(self):
        assert main._cambios_desde({}, self._datos(40, "2026-08-16")) == {}

    def test_se_pinta_arriba_del_todo(self):
        texto = main.render_brief_texto({
            "fecha": "2026-08-16", "dia_semana": "sábado", "zona": "Europe/Madrid",
            "agenda": [], "clases": [], "entregas": [], "clima": {}, "salud": {},
            "entrenamiento": {},
            "cambios": {"desde": "2026-08-15",
                        "entregas_nuevas": ["Práctica 4"],
                        "metricas_nuevas": [{"metrica": "hrv", "antes": 40, "ahora": 55,
                                             "delta": 15, "fecha": "2026-08-16"}],
                        "metricas_sin_novedad": ["peso"]},
        })
        assert texto.index("## QUÉ HA CAMBIADO") < texto.index("## AGENDA DE HOY")
        assert "Entrega nueva: Práctica 4" in texto
        assert "40 → 55" in texto and "(+15)" in texto
        assert "Sin dato nuevo desde entonces (1)" in texto

    def test_un_fallo_leyendo_la_instantanea_no_tumba_el_resumen(self, client, auth_headers, graph_token, mock_requests):
        montar_fuentes(mock_requests)
        mock_requests.add("GET", "/rest/v1/brief_envios", FakeResponse(None, 500, "no existe la columna"))
        d = client.get("/brief", headers=auth_headers).json()
        assert d["salud"] and "cambios" not in d


class TestInformeSemanal:
    """Una media de 30 días dice dónde estás; trece semanas seguidas, hacia dónde vas."""

    # El reloj se fija a un DOMINGO a propósito. Las semanas del informe van de lunes a
    # domingo, y estos tests construyen los días contando hacia atrás desde hoy: con el
    # reloj real, un lunes esos cinco días caen casi todos en la semana ANTERIOR, la
    # última sale con un solo día y —correctamente— como hueco, así que los asertos
    # fallaban un par de días por semana sin que nada estuviera roto. Es la misma razón
    # por la que existe _ahora_local(): poder fijar el reloj en los tests.
    HOY = datetime(2026, 8, 16, 9, 0, tzinfo=main.LOCAL_TZ)   # domingo

    @pytest.fixture(autouse=True)
    def _reloj_fijo(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: self.HOY)

    def _filas(self, semanas=4, por_semana=5):
        hoy = self.HOY.date()
        filas = []
        for s in range(semanas):
            for d in range(por_semana):
                fecha = (hoy - timedelta(weeks=s, days=d)).isoformat()
                filas.append({"metric_date": fecha, "metric_name": "resting_heart_rate",
                              "value": 55 + s, "unit": "bpm", "extra": {}})
                filas.append({"metric_date": fecha, "metric_name": "heart_rate",
                              "value": 70, "unit": "bpm", "extra": {}})
        return filas

    def test_agrupa_por_semana_con_su_n(self, client, auth_headers, mock_requests):
        montar_fuentes(mock_requests, salud=self._filas())
        d = client.get("/informe", headers=auth_headers).json()
        fc = d["salud"]["metricas"]["fc_reposo"]["semanas"]
        assert len(fc) == main.INFORME_SEMANAS
        assert fc[-1]["n"] == 5 and fc[-1]["media"] == 55
        assert fc[0] is None, "las semanas sin dato se marcan, no se comprimen"

    def test_una_semana_con_dos_dias_no_es_una_semana_medida(self, client, auth_headers, mock_requests):
        montar_fuentes(mock_requests, salud=self._filas(semanas=1, por_semana=2))
        d = client.get("/informe", headers=auth_headers).json()
        assert d["salud"]["metricas"]["fc_reposo"]["semanas"][-1] is None

    def test_lleva_los_dias_de_reloj_como_denominador(self, client, auth_headers, mock_requests):
        montar_fuentes(mock_requests, salud=self._filas())
        d = client.get("/informe", headers=auth_headers).json()
        assert d["salud"]["reloj"]["dia"][-1]["n"] == 5

    def test_el_texto_dice_su_ventana_y_marca_los_huecos(self, client, auth_headers, mock_requests):
        montar_fuentes(mock_requests, salud=self._filas())
        texto = main.render_informe_texto(client.get("/informe", headers=auth_headers).json())
        assert "## SEMANAS" in texto and "## MÉTRICAS POR SEMANA" in texto
        assert "## RELOJ POR SEMANA" in texto
        assert "-" in texto, "las semanas sin dato salen marcadas"

    def test_requiere_jwt(self, client):
        assert client.get("/informe").status_code in (401, 403)
        assert client.post("/informe/send").status_code == 403

    def test_no_se_manda_dos_veces_el_mismo_dia(self, client, mock_requests, monkeypatch):
        """La reserva es un INSERT: el 409 contra la clave primaria es la pregunta."""
        montar_fuentes(mock_requests, salud=self._filas())
        configurar_smtp(monkeypatch)
        mock_requests.add("POST", "/rest/v1/informe_envios", FakeResponse(None, 409, "duplicate"))
        r = client.post("/informe/send?token=brief-token&forzar=1")
        assert r.json()["informe_semanal"] is False
        assert len(_SMTPFalso.enviados) == 0

    def test_forzado_lo_manda_con_su_adjunto(self, client, mock_requests, monkeypatch):
        montar_fuentes(mock_requests, salud=self._filas())
        configurar_smtp(monkeypatch)
        mock_requests.add("POST", "/rest/v1/informe_envios", FakeResponse([], 201))
        r = client.post("/informe/send?token=brief-token&forzar=1")
        assert r.json()["informe_semanal"] is True
        assert len(_SMTPFalso.enviados) == 1
        msg = _SMTPFalso.enviados[0]
        assert "informe semanal" in msg["Subject"]
        assert list(msg.iter_attachments())[0].get_filename().startswith("informe-")

    def test_si_falla_el_envio_se_libera_la_reserva(self, client, mock_requests, monkeypatch):
        montar_fuentes(mock_requests, salud=self._filas())
        configurar_smtp(monkeypatch)
        mock_requests.add("POST", "/rest/v1/informe_envios", FakeResponse([], 201))
        monkeypatch.setattr(main, "enviar_correo",
                            lambda *a, **k: (_ for _ in ()).throw(TimeoutError("SMTP caído")))
        client.post("/informe/send?token=brief-token&forzar=1")
        assert mock_requests.called("DELETE", "/rest/v1/informe_envios")

    def test_solo_sale_el_dia_que_toca(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "INFORME_SEMANAL", True)
        # Un martes: no toca (INFORME_DIA por defecto es 6, domingo).
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 11, 12, 0, tzinfo=main.LOCAL_TZ))
        assert main._enviar_informe_si_toca() == {}
        assert not mock_requests.called("POST", "/rest/v1/informe_envios")

    def test_antes_de_su_hora_tampoco(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "INFORME_SEMANAL", True)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 16, 7, 0, tzinfo=main.LOCAL_TZ))
        assert main._enviar_informe_si_toca() == {}
        assert not mock_requests.called("POST", "/rest/v1/informe_envios")

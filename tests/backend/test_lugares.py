"""Tests de los lugares: casa, gimnasio y uni.

Lo que se comprueba es lo que haría a Jarvis peor que antes si fallara: que una pasada
por delante del gimnasio cuente como haber ido, que un aviso que tenía que esperar se
pierda (o que uno urgente espere), que la presencia se quede sin tramos por una columna
que falta, o que un «recuérdame al llegar» suene al apuntarlo.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

AHORA = datetime.now(timezone.utc)


def _en(zona="gimnasio", en_casa=False, hace_min=1):
    """Deja la presencia en memoria como si HA acabara de mandarla."""
    main._cachear_presencia({
        "zona": zona, "en_casa": en_casa, "lat": None, "lon": None,
        "precision_m": None, "fuente": "ha_companion",
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=hace_min)).isoformat(),
    })


def _firme(lugar, hace_min=30):
    desde = datetime.now(timezone.utc) - timedelta(minutes=hace_min)
    main._lugar_estado.update(crudo=(lugar, desde), firme=(lugar, desde))


class TestZonas:
    def test_cada_zona_a_su_lugar(self):
        assert main.lugar_de_zona("home", True) == "casa"
        assert main.lugar_de_zona("Gimnasio", False) == "gimnasio"
        assert main.lugar_de_zona(" GYM ", False) == "gimnasio"
        assert main.lugar_de_zona("Universidad", False) == "uni"
        assert main.lugar_de_zona("trabajo", False) == "fuera"
        assert main.lugar_de_zona("not_home", False) == "fuera"

    def test_en_casa_manda_sobre_el_nombre(self):
        # Una zona llamada «gimnasio» marcada en_casa (un gimnasio en casa) es casa.
        assert main.lugar_de_zona("gimnasio", True) == "casa"


class TestEstabilidad:
    """Pasar por delante del gimnasio no es ir al gimnasio."""

    def test_un_lugar_nuevo_no_cuenta_hasta_que_aguanta(self):
        t0 = datetime.now(timezone.utc)
        main._lugar_estado.update(crudo=("casa", t0 - timedelta(hours=2)),
                                  firme=("casa", t0 - timedelta(hours=2)))
        main._lugar_observar("gimnasio", t0)
        assert main._lugar_avanzar(t0 + timedelta(minutes=2)) is None
        assert main._lugar_estado["firme"][0] == "casa"
        viejo, nuevo = main._lugar_avanzar(t0 + timedelta(minutes=main.LUGAR_ESTABLE_MIN + 1))
        assert viejo[0] == "casa" and nuevo == ("gimnasio", t0)

    def test_un_parpadeo_del_gps_no_es_una_salida(self):
        t0 = datetime.now(timezone.utc)
        main._lugar_estado.update(crudo=("gimnasio", t0 - timedelta(hours=1)),
                                  firme=("gimnasio", t0 - timedelta(hours=1)))
        main._lugar_observar("fuera", t0)
        main._lugar_observar("gimnasio", t0 + timedelta(minutes=1))
        assert main._lugar_avanzar(t0 + timedelta(minutes=30)) is None
        # La estancia sigue contando desde que llegó, no desde el parpadeo.
        assert main._lugar_estado["firme"][1] == t0 - timedelta(hours=1)

    def test_con_la_presencia_caducada_no_se_sabe_donde_estas(self):
        _en("gimnasio", hace_min=main.PRESENCE_TTL_MINUTES + 10)
        _firme("gimnasio")
        assert main.lugar_actual() is None

    def test_al_arrancar_se_recupera_desde_cuando_estas(self, mock_requests):
        _en("gimnasio", hace_min=3)
        hace_una_hora = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_requests.add("GET", "presencia_tramos", FakeResponse([
            {"desde": (hace_una_hora + timedelta(minutes=30)).isoformat(),
             "hasta": datetime.now(timezone.utc).isoformat(), "en_casa": False, "lugar": "gimnasio"},
            {"desde": hace_una_hora.isoformat(),
             "hasta": (hace_una_hora + timedelta(minutes=30)).isoformat(),
             "en_casa": False, "lugar": "gimnasio"},
            {"desde": (hace_una_hora - timedelta(hours=3)).isoformat(),
             "hasta": hace_una_hora.isoformat(), "en_casa": True},
        ]))
        lugar = main.lugar_actual()
        assert lugar["lugar"] == "gimnasio"
        assert abs((lugar["desde"] - hace_una_hora).total_seconds()) < 1


class TestTramosConLugar:
    def _presencia_anterior(self, mock_requests, zona, en_casa, hace_min=15):
        visto = main._ahora_local().astimezone(timezone.utc) - timedelta(minutes=hace_min)
        mock_requests.add("GET", "/rest/v1/presence", FakeResponse([{
            "zona": zona, "en_casa": en_casa, "lat": None, "lon": None,
            "precision_m": None, "fuente": "ha_companion", "updated_at": visto.isoformat()}]))

    def test_el_tramo_del_gimnasio_lleva_su_lugar(self, client, mock_requests):
        self._presencia_anterior(mock_requests, "Gimnasio", False)
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "not_home"})
        assert r.status_code == 200 and r.json()["lugar"] == "fuera"
        filas = mock_requests.called("POST", "presencia_tramos")[0][2]["json"]
        assert filas and all(f["lugar"] == "gimnasio" for f in filas)

    def test_casa_y_fuera_sin_mas_no_guardan_lugar(self, client, mock_requests):
        self._presencia_anterior(mock_requests, "trabajo", False)
        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "home"})
        filas = mock_requests.called("POST", "presencia_tramos")[0][2]["json"]
        # Ni el nombre de la zona ni nada: «fuera» sigue sin decir dónde.
        assert all("lugar" not in f for f in filas)
        assert "trabajo" not in str(filas)

    def test_sin_la_migracion_se_guarda_igual_sin_lugar(self, client, mock_requests):
        self._presencia_anterior(mock_requests, "uni", False)
        respuestas = [FakeResponse({"code": "PGRST204"}, 400,
                                   text='{"code":"PGRST204","message":"lugar"}'),
                      FakeResponse([], 201)]
        mock_requests.add("POST", "presencia_tramos", lambda url, **kw: respuestas.pop(0))
        r = client.post("/ha/presencia?token=ha-poll-token", json={"zona": "uni"})
        assert r.status_code == 200
        intentos = mock_requests.called("POST", "presencia_tramos")
        assert len(intentos) == 2
        assert "lugar" in intentos[0][2]["json"][0]
        assert "lugar" not in intentos[1][2]["json"][0]
        assert main._tramos_sin_lugar is True

    def test_los_tramos_se_parten_por_lugar(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "presencia_tramos", FakeResponse([
            {"desde": "2026-10-05T08:00:00+00:00", "hasta": "2026-10-05T09:00:00+00:00", "en_casa": False},
            {"desde": "2026-10-05T09:00:00+00:00", "hasta": "2026-10-05T10:00:00+00:00", "en_casa": False, "lugar": "uni"},
            {"desde": "2026-10-05T10:00:00+00:00", "hasta": "2026-10-05T11:00:00+00:00", "en_casa": False, "lugar": "uni"},
        ]))
        d = client.get("/presencia/tramos?dia=2026-10-05", headers=auth_headers).json()
        assert [t.get("lugar") for t in d["tramos"]] == [None, "uni"]
        assert d["tramos"][1]["desde"].startswith("2026-10-05T09")

    def test_un_hueco_de_ha_no_es_una_salida(self, client, mock_requests, monkeypatch):
        _firme("gimnasio", hace_min=600)
        self._presencia_anterior(mock_requests, "Gimnasio", False,
                                 hace_min=main.PRESENCE_TTL_MINUTES + 60)
        salidas = []
        monkeypatch.setattr(main, "_al_salir_de", lambda *a: salidas.append(a) or 0)
        client.post("/ha/presencia?token=ha-poll-token", json={"zona": "home"})
        assert salidas == []


class TestDespachoSegunElLugar:
    @pytest.fixture(autouse=True)
    def _entorno(self, monkeypatch):
        self.enviados = []

        def _notificar(titulo, texto, **kw):
            self.enviados.append({"texto": texto, **kw})
            return "movil"
        monkeypatch.setattr(main, "_notificar", _notificar)
        monkeypatch.setattr(main, "_contar_enviados_hoy", lambda: 0)
        self.clases = []
        monkeypatch.setattr(main, "get_class_events",
                            lambda credentials=None: {"events": self.clases})

    def _fila(self, n=1, regla="proactivo", prioridad=main.PRIO_NORMAL):
        return {"id": f"1111111{n}-2222-3333-4444-555555555555", "texto": f"aviso {n}",
                "cuando": (AHORA - timedelta(minutes=1)).isoformat(), "regla": regla,
                "prioridad": prioridad, "voz": False}

    def _pendientes(self, mock_requests, filas):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse(filas))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

    def test_en_el_gimnasio_lo_que_no_corre_prisa_espera(self, mock_requests):
        _en("gimnasio")
        _firme("gimnasio")
        self._pendientes(mock_requests, [self._fila()])
        r = main._despachar_recordatorios()
        assert r == {"recordatorios": 0, "avisos_esperando": 1}
        assert self.enviados == []
        # Se queda pendiente con la hora de ahora, no se cierra ni se pasa a mañana.
        patch = mock_requests.called("PATCH", "jarvis_recordatorios")[0]
        assert "enviado=is.false" in patch[1]
        assert set(patch[2]["json"]) == {"cuando"}

    def test_lo_urgente_lo_tuyo_y_lo_del_gimnasio_salen_igual(self, mock_requests):
        _en("gimnasio")
        _firme("gimnasio")
        self._pendientes(mock_requests, [
            self._fila(1, regla="salir", prioridad=main.PRIO_URGENTE),
            self._fila(2, regla=""),                                   # recordarme
            self._fila(3, regla="tuya:agua"),
            self._fila(4, regla=main.REGLA_COBRO_GIMNASIO),
        ])
        r = main._despachar_recordatorios()
        assert r["recordatorios"] == 4 and "avisos_esperando" not in r

    def test_en_la_uni_solo_espera_durante_la_clase(self, mock_requests):
        _en("Universidad")
        _firme("uni")
        self._pendientes(mock_requests, [self._fila()])
        assert main._despachar_recordatorios() == {"recordatorios": 1}

    def test_en_clase_espera(self, mock_requests):
        _en("Universidad")
        _firme("uni")
        self.clases = [{"title": "Cálculo", "isAllDay": False,
                        "start": (AHORA - timedelta(minutes=20)).isoformat(),
                        "end": (AHORA + timedelta(minutes=40)).isoformat()}]
        self._pendientes(mock_requests, [self._fila()])
        assert main._despachar_recordatorios() == {"recordatorios": 0, "avisos_esperando": 1}

    def test_sin_saber_donde_estas_se_habla(self, mock_requests):
        _firme("gimnasio")       # sin presencia vigente
        self._pendientes(mock_requests, [self._fila()])
        assert main._despachar_recordatorios() == {"recordatorios": 1}

    def test_sin_entrenar_en_el_gimnasio_se_retira(self, mock_requests):
        _en("gimnasio")
        _firme("gimnasio")
        self._pendientes(mock_requests, [self._fila(regla="hueco_entreno")])
        assert main._despachar_recordatorios() == {"recordatorios": 0, "avisos_retirados": 1}

    def test_sal_ya_estando_ya_en_el_sitio_se_retira(self, mock_requests, monkeypatch):
        _en("Universidad")
        _firme("uni")
        ini = main._ahora_local() + timedelta(minutes=20)
        cita = {"id": "ev1", "title": "Clase", "location": "Facultad", "isAllDay": False,
                "start": ini.astimezone(timezone.utc).isoformat(),
                "end": (ini + timedelta(hours=1)).astimezone(timezone.utc).isoformat()}
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": [cita]})
        # Maps desde donde estás: 2 min de trayecto (+ los 10 de margen de siempre).
        monkeypatch.setattr(main, "_hora_salida",
                            lambda destino, cuando, origen="": ini - timedelta(minutes=12))
        fila = self._fila(regla="salir", prioridad=main.PRIO_URGENTE)
        fila["huella"] = main._huella_salir({"id": "ev1", "ini": ini.astimezone(main.LOCAL_TZ)})
        self._pendientes(mock_requests, [fila])
        assert main._despachar_recordatorios() == {"recordatorios": 0, "avisos_retirados": 1}

    def test_en_clase_lo_critico_no_atraviesa_el_silencio(self, mock_requests):
        _en("Universidad")
        _firme("uni")
        self.clases = [{"title": "Cálculo", "isAllDay": False,
                        "start": (AHORA - timedelta(minutes=20)).isoformat(),
                        "end": (AHORA + timedelta(minutes=40)).isoformat()}]
        self._pendientes(mock_requests, [self._fila(regla=main.REGLA_DESPLIEGUE,
                                                    prioridad=main.PRIO_URGENTE)])
        assert main._despachar_recordatorios()["recordatorios"] == 1
        assert self.enviados[0]["critico"] is False


class TestTelefonoEnClase:
    def test_en_clase_no_suena(self, monkeypatch, mock_requests):
        _en("uni")
        _firme("uni")
        monkeypatch.setattr(main, "get_class_events", lambda credentials=None: {"events": [
            {"title": "Física", "isAllDay": False,
             "start": (AHORA - timedelta(minutes=5)).isoformat(),
             "end": (AHORA + timedelta(minutes=55)).isoformat()}]})
        mediodia = datetime.now(main.LOCAL_TZ).replace(hour=12, minute=0)
        puede, motivo = main._telefono_puede_sonar(mediodia)
        assert puede is False and "clase" in motivo


class TestSesionAlSalirDelGimnasio:
    @pytest.fixture(autouse=True)
    def _entorno(self, monkeypatch):
        self.avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: self.avisos.append((regla, texto, kw)) or True)
        monkeypatch.setattr(main, "_get_training_client", lambda: {"id": "c1"})

    def _salida(self, minutos=60):
        hasta = datetime.now(timezone.utc)
        return hasta - timedelta(minutes=minutos), hasta

    def test_tras_una_hora_pregunta(self, mock_requests):
        assert main._regla_sesion_gimnasio(*self._salida(60)) == 1
        regla, texto, kw = self.avisos[0]
        assert regla == main.REGLA_SESION_GIMNASIO and "1 h" in texto
        assert kw["caduca"] is not None

    def test_una_pasada_corta_no_pregunta(self, mock_requests):
        assert main._regla_sesion_gimnasio(*self._salida(15)) == 0

    def test_con_la_sesion_ya_apuntada_no_pregunta(self, mock_requests):
        mock_requests.add("GET", "training_sessions", FakeResponse([{"id": "s1"}]))
        assert main._regla_sesion_gimnasio(*self._salida(60)) == 0

    def test_si_el_reloj_vio_tu_entreno_no_pregunta(self, mock_requests):
        desde, hasta = self._salida(60)
        hora = (desde + timedelta(minutes=10)).astimezone(main.LOCAL_TZ)
        mock_requests.add("GET", "health_metrics", FakeResponse([
            {"extra": {"workouts": [{"start": hora.strftime("%Y-%m-%d %H:%M:%S +0200")}]}}]))
        assert main._regla_sesion_gimnasio(desde, hasta) == 0

    def test_sus_botones_no_votan_en_contra(self):
        botones = main._acciones_aviso("rid", main.REGLA_SESION_GIMNASIO)
        assert [b["action"] for b in botones] == ["LA_APAGAR_rid", "LA_UTIL_rid"]


class TestBotonApuntarSesion:
    RID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_apunta_la_sesion_con_la_fecha_del_aviso(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_acusar_recibo", lambda *a, **k: None)
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([
            {"regla": main.REGLA_SESION_GIMNASIO, "entidades": None,
             "creado": "2026-10-04T19:30:00+00:00"}]))
        mock_requests.add("GET", "training_clients", FakeResponse([{"id": "c1"}]))
        mock_requests.add("POST", "training_sessions", FakeResponse([{"id": "s1"}], 201))
        r = client.post(f"/avisos/{self.RID}/apagar", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200, r.text
        cuerpo = mock_requests.called("POST", "training_sessions")[0][2]["json"]
        assert cuerpo["date"] == "2026-10-04"
        assert cuerpo["duration_hours"] == main.GIMNASIO_SESION_HORAS

    def test_dos_toques_no_son_dos_sesiones(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_acusar_recibo", lambda *a, **k: None)
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([
            {"regla": main.REGLA_SESION_GIMNASIO, "creado": "2026-10-04T19:30:00+00:00"}]))
        mock_requests.add("GET", "training_sessions", FakeResponse([{"id": "s1"}]))
        r = client.post(f"/avisos/{self.RID}/apagar", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.json()["ya_estaba"] is True
        assert not mock_requests.called("POST", "training_sessions")


class TestCobroAlLlegar:
    def test_al_llegar_con_sesiones_sin_cobrar_avisa(self, monkeypatch):
        avisos = []
        monkeypatch.setattr(main, "_brief_entrenamiento", lambda: {
            "sesiones_desde_cobro": 4, "sesiones_por_cobro": 4, "importe_pendiente": 64})
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append((regla, kw)) or True)
        assert main._regla_cobro_gimnasio() == 1
        assert avisos[0][0] == main.REGLA_COBRO_GIMNASIO
        assert avisos[0][1]["huella"] == "cobro:4"

    def test_sin_llegar_al_punto_de_cobro_calla(self, monkeypatch):
        monkeypatch.setattr(main, "_brief_entrenamiento", lambda: {
            "sesiones_desde_cobro": 2, "sesiones_por_cobro": 4})
        assert main._regla_cobro_gimnasio() == 0


class TestTransiciones:
    def test_llegar_y_salir_del_gimnasio(self, monkeypatch, mock_requests):
        llegadas, salidas = [], []
        monkeypatch.setattr(main, "_al_llegar_a", lambda l, d: llegadas.append(l) or 0)
        monkeypatch.setattr(main, "_al_salir_de", lambda l, d, h: salidas.append((l, h - d)) or 0)
        _en("gimnasio")
        llego = datetime.now(timezone.utc) - timedelta(minutes=70)
        main._lugar_estado.update(crudo=("gimnasio", llego), firme=("gimnasio", llego))
        main._procesar_lugar()
        assert llegadas == ["gimnasio"]
        main._procesar_lugar()
        assert llegadas == ["gimnasio"]        # una llegada, una vez
        # Se va: el lugar crudo cambia y, pasado el rato, es una salida.
        se_fue = datetime.now(timezone.utc) - timedelta(minutes=main.LUGAR_ESTABLE_MIN + 1)
        _en("not_home")
        main._lugar_estado["crudo"] = ("fuera", se_fue)
        main._procesar_lugar()
        assert salidas and salidas[0][0] == "gimnasio"
        assert salidas[0][1] >= timedelta(minutes=60)


class TestRecordatoriosPorLugar:
    def test_se_apunta(self, mock_requests):
        mock_requests.add("POST", "recordatorios_lugar", FakeResponse([{"id": "r1"}], 201))
        r = main._j_recordarme_lugar("sacar la basura", "casa", "llegar")
        assert r["ok"] is True
        cuerpo = mock_requests.called("POST", "recordatorios_lugar")[0][2]["json"]
        assert cuerpo == {"texto": "sacar la basura", "lugar": "casa", "momento": "llegar"}

    def test_lugar_desconocido(self, mock_requests):
        assert main._j_recordarme_lugar("x", "trabajo")["ok"] is False

    def test_sin_migracion_lo_dice(self, mock_requests):
        mock_requests.add("GET", "recordatorios_lugar", FakeResponse({}, 404))
        r = main._j_recordarme_lugar("x", "casa")
        assert r["ok"] is False and "20261005_lugares" in r["motivo"]

    def test_al_llegar_se_convierte_en_un_recordatorio_normal(self, mock_requests):
        rid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        mock_requests.add("GET", "recordatorios_lugar",
                          FakeResponse([{"id": rid, "texto": "sacar la basura"}]))
        mock_requests.add("PATCH", "recordatorios_lugar", FakeResponse([{"id": rid}]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._disparar_recordatorios_lugar("casa", "llegar", datetime.now(timezone.utc)) == 1
        consulta = mock_requests.called("GET", "recordatorios_lugar")[0][1]
        # Solo los apuntados ANTES de llegar.
        assert "creado=lte." in consulta and "disparado_at=is.null" in consulta
        alta = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        # Sin regla: lo pediste tú, no lo gobierna ni el presupuesto ni el lugar.
        assert "regla" not in alta and alta["texto"] == "sacar la basura"

    def test_si_otro_se_lo_llevo_no_se_repite(self, mock_requests):
        rid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        mock_requests.add("GET", "recordatorios_lugar", FakeResponse([{"id": rid, "texto": "x"}]))
        mock_requests.add("PATCH", "recordatorios_lugar", FakeResponse([]))
        assert main._disparar_recordatorios_lugar("casa", "llegar", datetime.now(timezone.utc)) == 0
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_salen_en_mis_recordatorios(self, mock_requests):
        mock_requests.add("GET", "recordatorios_lugar", FakeResponse([
            {"id": "r1", "texto": "agua", "lugar": "gimnasio", "momento": "salir"}]))
        r = main._j_mis_recordatorios()
        assert {"id": "r1", "texto": "agua", "cuando": "al salir de gimnasio"} in r["recordatorios"]


class TestNoRegañarElDiaDelGimnasio:
    def test_estando_en_el_gimnasio(self, mock_requests):
        _en("gimnasio")
        _firme("gimnasio")
        assert main._estuvo_en_gimnasio_hoy() is True

    def test_habiendo_ido_hoy(self, mock_requests):
        hoy = datetime.now(timezone.utc)
        mock_requests.add("GET", "presencia_tramos", FakeResponse([
            {"desde": (hoy - timedelta(hours=3)).isoformat(),
             "hasta": (hoy - timedelta(hours=2)).isoformat(), "en_casa": False, "lugar": "gimnasio"}]))
        assert main._estuvo_en_gimnasio_hoy() is True

    def test_sin_dato_no_cuenta_como_ido(self, mock_requests):
        assert main._estuvo_en_gimnasio_hoy() is False

    def test_el_aviso_diario_no_dice_lo_de_entrenar(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": []})
        monkeypatch.setattr(main, "_brief_entrenamiento", lambda: {})
        monkeypatch.setattr(main, "_brief_salud", lambda: {"ultimo_entreno": {"dias": 5}})
        assert main._motivos_proactivos(main._ahora_local())
        _en("gimnasio")
        _firme("gimnasio")
        assert main._motivos_proactivos(main._ahora_local()) == []


class TestJarvisSabeDondeEstas:
    def test_el_prompt_lo_dice(self, mock_requests):
        _en("gimnasio")
        _firme("gimnasio")
        assert "en el gimnasio" in main._jarvis_sistema()

    def test_sin_saberlo_no_dice_nada(self, mock_requests):
        assert main._jarvis_contexto_lugar() == ""

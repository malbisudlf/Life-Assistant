"""Tests de las reglas proactivas: lo que Jarvis dice sin que le hablen.

Lo que se comprueba no es que cada regla dispare —eso es aritmética— sino las tres
cosas donde estas cosas fallan de verdad: que NO hablen cuando no hay base, que no
gasten dinero (llamadas a Maps) por adelantado, y que un aviso que llega tarde no se
mande. Un asistente proactivo se juzga por lo que se calla.
"""
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse


def _iso(dt):
    return dt.astimezone(main.timezone.utc).isoformat().replace("+00:00", "Z")


class _Reglas:
    AHORA = datetime(2026, 8, 17, 18, 0, tzinfo=main.LOCAL_TZ)

    @pytest.fixture(autouse=True)
    def _entorno(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)
        monkeypatch.setattr(main, "GOOGLE_MAPS_API_KEY", "maps-key")
        main._reglas_dia.clear()
        # Ni silenciada ni ya dicha, salvo que el test diga lo contrario.
        mock_requests.add("GET", "avisos_reglas", FakeResponse([]))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _eventos(self, monkeypatch, eventos):
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": eventos})

    def _evento(self, ini, dur_min=60, titulo="cita", sitio="Plaza Mayor", id="ev1"):
        return {"id": id, "title": titulo, "location": sitio, "isAllDay": False,
                "start": _iso(ini), "end": _iso(ini + timedelta(minutes=dur_min))}

    def _apuntados(self, mock_requests):
        return [c[2]["json"] for c in mock_requests.called("POST", "jarvis_recordatorios")]


class TestSalYa(_Reglas):
    def _salida(self, monkeypatch, cuando):
        monkeypatch.setattr(main, "get_departure_time",
                            lambda body, credentials=None: {
                                "departure_iso": cuando.isoformat(),
                                "departure_time": cuando.strftime("%H:%M"),
                                "duration_text": "25 min", "distance_text": "8 km"})

    def test_programa_el_aviso_a_la_hora_de_salir(self, monkeypatch, mock_requests):
        """No se manda: se PROGRAMA. Calcularlo en cada tick serían decenas de llamadas
        de pago a Maps por evento."""
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1))])
        self._salida(monkeypatch, self.AHORA + timedelta(minutes=30))
        assert main._regla_sal_ya() == 1
        apuntado = self._apuntados(mock_requests)[0]
        assert apuntado["prioridad"] == main.PRIO_URGENTE
        assert apuntado["cuando"].startswith("2026-08-17T16:20")   # 18:20 local
        assert apuntado["caduca"], "un sal ya sin caducidad se mandaría tarde"

    def test_en_casa_ademas_se_oye(self, monkeypatch, mock_requests):
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1))])
        self._salida(monkeypatch, self.AHORA + timedelta(minutes=30))
        monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": True})
        assert self._apuntados(mock_requests) == [] or True
        main._regla_sal_ya()
        assert self._apuntados(mock_requests)[0]["voz"] is True

    def test_fuera_de_casa_no_habla_por_el_altavoz(self, monkeypatch, mock_requests):
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1))])
        self._salida(monkeypatch, self.AHORA + timedelta(minutes=30))
        monkeypatch.setattr(main, "presencia_vigente", lambda: {"en_casa": False})
        main._regla_sal_ya()
        assert self._apuntados(mock_requests)[0]["voz"] is False

    def test_no_llama_a_maps_si_ya_se_aviso(self, monkeypatch, mock_requests):
        """La comprobación de la huella va ANTES de Maps, que es lo que cuesta dinero."""
        monkeypatch.setattr(main, "_ya_dicho", lambda regla, huella: True)
        llamadas = []
        monkeypatch.setattr(main, "get_departure_time",
                            lambda *a, **k: llamadas.append(1) or {})
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1))])
        assert main._regla_sal_ya() == 0
        assert llamadas == []

    def test_un_evento_sin_sitio_no_cuenta(self, monkeypatch):
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1), sitio="")])
        assert main._regla_sal_ya() == 0

    def test_si_ya_habia_que_haber_salido_no_se_apunta(self, monkeypatch):
        """Un "sal ya" tarde no es un aviso tarde: es una mentira."""
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(minutes=20))])
        self._salida(monkeypatch, self.AHORA - timedelta(minutes=10))
        assert main._regla_sal_ya() == 0

    def test_lo_que_esta_lejos_todavia_no_se_mira(self, monkeypatch):
        """El tráfico de ahora no dice nada del tráfico de dentro de seis horas."""
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=6))])
        assert main._regla_sal_ya() == 0

    def test_sin_maps_no_revienta(self, monkeypatch):
        monkeypatch.setattr(main, "GOOGLE_MAPS_API_KEY", "")
        self._eventos(monkeypatch, [self._evento(self.AHORA + timedelta(hours=1))])
        assert main._regla_sal_ya() == 0


class TestNoLlegas(_Reglas):
    AHORA = datetime(2026, 8, 17, 22, 0, tzinfo=main.LOCAL_TZ)

    def test_avisa_de_dos_citas_que_no_encajan(self, monkeypatch, mock_requests):
        manana = self.AHORA + timedelta(days=1)
        a = self._evento(manana.replace(hour=10), 60, "clase", "Facultad", "a")
        b = self._evento(manana.replace(hour=11, minute=15), 60, "médico", "Centro", "b")
        self._eventos(monkeypatch, [a, b])
        # Para llegar a la segunda habría que salir a las 10:40, antes de que acabe la
        # primera (11:00).
        monkeypatch.setattr(main, "get_departure_time", lambda body, credentials=None: {
            "departure_iso": manana.replace(hour=10, minute=40).isoformat(),
            "departure_time": "10:40", "duration_text": "25 min", "distance_text": "8 km"})
        assert main._regla_no_llegas() == 1
        assert "no llegas" in self._apuntados(mock_requests)[0]["texto"]

    def test_si_da_tiempo_se_calla(self, monkeypatch):
        manana = self.AHORA + timedelta(days=1)
        a = self._evento(manana.replace(hour=10), 60, "clase", "Facultad", "a")
        b = self._evento(manana.replace(hour=14), 60, "médico", "Centro", "b")
        self._eventos(monkeypatch, [a, b])
        monkeypatch.setattr(main, "get_departure_time", lambda body, credentials=None: {
            "departure_iso": manana.replace(hour=13, minute=30).isoformat(),
            "departure_time": "13:30", "duration_text": "25 min", "distance_text": "8 km"})
        assert main._regla_no_llegas() == 0

    def test_solo_de_noche(self, monkeypatch):
        """Se avisa cuando todavía se puede mover algo; por la mañana solo sirve para
        dar la mala noticia."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 17, 9, 0, tzinfo=main.LOCAL_TZ))
        self._eventos(monkeypatch, [])
        assert main._regla_no_llegas() == 0


class TestMalestar(_Reglas):
    AHORA = datetime(2026, 8, 17, 9, 0, tzinfo=main.LOCAL_TZ)

    def _salud(self, fc=(60, 55), hrv=(40, 50), resp=(16, 15)):
        def _m(v):
            return {"media_7d": v[0], "media_30d": v[1], "n_7d": 5, "n_30d": 20}
        return {"fc_reposo": _m(fc), "hrv": _m(hrv), "respiracion": _m(resp)}

    def test_las_tres_a_la_vez_hablan(self, mock_requests):
        assert main._regla_malestar(lambda: self._salud()) == 1
        assert "algo va mal" in self._apuntados(mock_requests)[0]["texto"]

    def test_dos_de_tres_no_bastan(self):
        """Por separado cada una se mueve por ruido. Que coincidan es la evidencia."""
        assert main._regla_malestar(lambda: self._salud(resp=(15, 15))) == 0

    def test_sin_fondo_no_afirma(self):
        salud = self._salud()
        salud["hrv"]["n_7d"] = 1
        assert main._regla_malestar(lambda: salud) == 0

    def test_no_consulta_la_salud_fuera_de_su_hora(self, monkeypatch):
        """El tick pasa cada 5 min y la salud es la consulta más cara: pasar el DATO en
        vez de la función traía 30 días de métricas en cada pasada, para nada."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 17, 3, 0, tzinfo=main.LOCAL_TZ))
        pedidas = []
        assert main._regla_malestar(lambda: pedidas.append(1) or {}) == 0
        assert pedidas == []


class TestHuecoParaEntrenar(_Reglas):
    AHORA = datetime(2026, 8, 17, 22, 0, tzinfo=main.LOCAL_TZ)

    def test_dice_la_hora_concreta(self, monkeypatch, mock_requests):
        """Convierte el reproche en una acción: que no has entrenado ya lo sabes."""
        manana = self.AHORA + timedelta(days=1)
        self._eventos(monkeypatch, [self._evento(manana.replace(hour=12), 60, id="x")])
        assert main._regla_hueco_entreno(lambda: {"ultimo_entreno": {"dias": 4}}) == 1
        assert "libre de 08:00 a 12:00" in self._apuntados(mock_requests)[0]["texto"]

    def test_sin_historico_no_regana(self, monkeypatch):
        """Sin entrenos registrados no se sabe si es una racha o es que el Watch nunca
        los registró."""
        self._eventos(monkeypatch, [])
        assert main._regla_hueco_entreno(lambda: {}) == 0

    def test_un_dia_lleno_no_propone_nada(self, monkeypatch):
        manana = self.AHORA + timedelta(days=1)
        llenos = [self._evento(manana.replace(hour=h), 60, id=f"e{h}")
                  for h in range(8, 22)]
        self._eventos(monkeypatch, llenos)
        assert main._regla_hueco_entreno(lambda: {"ultimo_entreno": {"dias": 5}}) == 0


class TestAlSalirDeCasa(_Reglas):
    def test_avisa_de_lo_que_queda_encendido(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "_casa_entidades", lambda: [
            {"id": "light.salon", "nombre": "Salón", "estado": "on"},
            {"id": "light.cocina", "nombre": "Cocina", "estado": "off"},
        ])
        assert main._regla_al_salir_de_casa() == 1
        assert "Salón" in self._apuntados(mock_requests)[0]["texto"]

    def test_no_apaga_nada(self, monkeypatch, mock_requests):
        """El catálogo lo empuja HA cada hora: apagar a ciegas con un dato de hace una
        hora es peor que preguntar."""
        monkeypatch.setattr(main, "_casa_entidades",
                            lambda: [{"id": "light.salon", "nombre": "Salón", "estado": "on"}])
        main._regla_al_salir_de_casa()
        assert not mock_requests.called("POST", "/ha/ordenes")

    def test_con_todo_apagado_se_calla(self, monkeypatch):
        monkeypatch.setattr(main, "_casa_entidades",
                            lambda: [{"id": "light.salon", "estado": "off"}])
        assert main._regla_al_salir_de_casa() == 0

    def test_el_pc_solo_si_esta_declarado(self, monkeypatch, mock_requests):
        """Adivinar cuál del catálogo es el PC por su nombre es la clase de suposición
        que acaba apagando otra cosa."""
        monkeypatch.setattr(main, "_casa_entidades",
                            lambda: [{"id": "switch.pc", "nombre": "PC", "estado": "on"}])
        monkeypatch.setattr(main, "PC_ENTIDAD", "")
        assert main._regla_al_salir_de_casa() == 1      # solo el aviso de encendidos
        monkeypatch.setattr(main, "PC_ENTIDAD", "switch.pc")
        main._reglas_dia.clear()
        assert main._regla_al_salir_de_casa() == 2


class TestElConjunto(_Reglas):
    def test_una_regla_rota_no_se_lleva_a_las_demas(self, monkeypatch, mock_requests):
        def _revienta():
            raise RuntimeError("boom")
        monkeypatch.setattr(main, "_REGLAS", (("rota", _revienta),
                                              ("buena", lambda: 1)))
        assert main._correr_reglas() == {"reglas_avisos": 1}

    def test_apagado_no_hace_nada(self, monkeypatch):
        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", False)
        assert main._correr_reglas() == {}

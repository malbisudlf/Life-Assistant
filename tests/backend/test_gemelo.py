"""El gemelo de la casa (`gemelo/`, docs/GEMELO.md): el archivo, el reproductor de reglas y
las rutinas. Todo con una casa inventada; aquí no hay Home Assistant ni red."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gemelo"))

import historia   # noqa: E402
import reglas     # noqa: E402
import rutinas    # noqa: E402

ZONA = ZoneInfo("Europe/Madrid")
GARAJE, MOVIL, LUZ, TEMP = "binary_sensor.puerta_garaje", "device_tracker.movil", "light.entrada", "sensor.temp"


def t(dia: int, hora: str) -> float:
    """El día `dia` de noviembre de 2026 (el 2 es lunes), a esa hora local."""
    h, m = hora.split(":")
    return datetime(2026, 11, dia, int(h), int(m), tzinfo=ZONA).timestamp()


def regla(**kw) -> dict:
    return {"id": "r", "cuando": {"entidad": GARAJE, "pasa_a": "on"}, **kw}


class TestReproductor:
    def test_cuenta_cada_vez_que_pasa_y_no_el_primer_dato(self):
        cambios = [(t(2, "08:00"), GARAJE, "off"), (t(2, "09:00"), GARAJE, "on"),
                   (t(2, "09:01"), GARAJE, "on"), (t(2, "09:05"), GARAJE, "off"),
                   (t(3, "19:00"), GARAJE, "on")]
        inf = reglas.reproducir(regla(), cambios)
        assert [d["cuando"] for d in inf["lista"]] == ["2026-11-02 09:00", "2026-11-03 19:00"]
        assert inf["dias_con_disparo"] == 2 and inf["por_dia_semana"] == {"lun": 1, "mar": 1}
        # Arrancar el archivo con la puerta ya abierta no es que se abra.
        assert reglas.reproducir(regla(), [(t(2, "08:00"), GARAJE, "on")])["disparos"] == 0

    def test_la_reconexion_del_sensor_salta_y_se_cuenta_aparte(self):
        cambios = [(t(2, "08:00"), GARAJE, "off"), (t(2, "09:00"), GARAJE, "unavailable"),
                   (t(2, "09:02"), GARAJE, "on")]
        inf = reglas.reproducir(regla(), cambios)
        assert inf["disparos"] == 1 and inf["tras_reconexion"] == 1
        # Con `de`, como en Home Assistant, ya no salta.
        con_de = regla(cuando={"entidad": GARAJE, "pasa_a": "on", "de": "off"})
        assert reglas.reproducir(con_de, cambios)["disparos"] == 0

    def test_durante_solo_si_aguanta_el_tiempo_entero(self):
        r = regla(cuando={"entidad": GARAJE, "pasa_a": "on", "durante_min": 10})
        cambios = [(t(2, "08:00"), GARAJE, "off"),
                   (t(2, "09:00"), GARAJE, "on"), (t(2, "09:04"), GARAJE, "off"),     # 4 min: no
                   (t(2, "10:00"), GARAJE, "on"), (t(2, "10:30"), GARAJE, "off"),     # 30 min: sí
                   (t(2, "11:00"), GARAJE, "on")]                                     # sigue abierta al acabar
        inf = reglas.reproducir(r, cambios, hasta=t(2, "11:20"))
        assert [d["cuando"] for d in inf["lista"]] == ["2026-11-02 10:10", "2026-11-02 11:10"]
        assert reglas.reproducir(r, cambios, hasta=t(2, "11:05"))["disparos"] == 1

    def test_las_condiciones_miran_el_estado_de_ese_momento(self):
        r = regla(si=[{"entidad": MOVIL, "es": "not_home"}, {"entre": ["22:00", "07:00"]}])
        cambios = [(t(2, "08:00"), GARAJE, "off"), (t(2, "08:00"), MOVIL, "home"),
                   (t(2, "23:00"), GARAJE, "on"), (t(2, "23:05"), GARAJE, "off"),     # en casa: no
                   (t(3, "09:00"), MOVIL, "not_home"),
                   (t(3, "12:00"), GARAJE, "on"), (t(3, "12:05"), GARAJE, "off"),     # fuera, de día: no
                   (t(4, "02:00"), GARAJE, "on")]                                     # fuera y de noche: sí
        inf = reglas.reproducir(r, cambios)
        assert [d["cuando"] for d in inf["lista"]] == ["2026-11-04 02:00"] and inf["de_madrugada"] == 1

    def test_en_falso_la_espera_y_las_rafagas(self):
        cambios = [(t(2, "08:00"), GARAJE, "off"),
                   (t(2, "09:00"), GARAJE, "on"), (t(2, "09:01"), GARAJE, "off"),     # se cerró sola
                   (t(2, "09:02"), GARAJE, "on"), (t(2, "09:40"), GARAJE, "off"),
                   (t(2, "20:00"), GARAJE, "on")]
        falso = {"entidad": GARAJE, "pasa_a": "off", "antes_de_min": 2}
        inf = reglas.reproducir(regla(en_falso_si=falso), cambios)
        assert (inf["disparos"], inf["en_falso"], inf["en_rafaga"], inf["max_en_un_dia"]) == (3, 1, 1, 3)
        assert reglas.reproducir(regla(espera_min=30), cambios)["disparos"] == 2

    def test_un_numero_que_cruza_un_umbral(self):
        r = {"cuando": {"entidad": TEMP, "por_debajo": 18}}
        cambios = [(t(2, "08:00"), TEMP, "20.5"), (t(2, "09:00"), TEMP, "17.9"), (t(2, "09:30"), TEMP, "17.0"),
                   (t(2, "10:00"), TEMP, "unavailable"), (t(2, "10:05"), TEMP, "17.5"), (t(2, "12:00"), TEMP, "19"),
                   (t(2, "22:00"), TEMP, "16")]
        inf = reglas.reproducir(r, cambios)
        assert [d["cuando"][11:] for d in inf["lista"]] == ["09:00", "10:05", "22:00"]
        assert inf["tras_reconexion"] == 1

    def test_a_una_hora_cada_dia_con_sus_condiciones(self):
        r = {"cuando": {"a_las": "07:30"}, "si": [{"dias": ["lun", "mar", "mie", "jue", "vie"]},
                                                  {"entidad": MOVIL, "es": "home"}]}
        cambios = [(t(2, "00:10"), MOVIL, "home"), (t(4, "06:00"), MOVIL, "not_home"),
                   (t(4, "20:00"), MOVIL, "home"), (t(8, "23:00"), MOVIL, "home")]
        inf = reglas.reproducir(r, cambios)
        # Lunes 2 y martes 3 en casa; miércoles 4 fuera; jueves 5 y viernes 6 en casa; el finde no.
        assert [d["cuando"] for d in inf["lista"]] == [f"2026-11-0{d} 07:30" for d in (2, 3, 5, 6)]
        assert inf["tras_reconexion"] == 0

    @pytest.mark.parametrize("mala", [
        {}, {"cuando": {}}, {"cuando": {"entidad": GARAJE}}, {"cuando": {"a_las": "siete"}},
        {"cuando": {"entidad": GARAJE, "pasa_a": "on"}, "si": [{"dias": ["lunes"]}]},
        {"cuando": {"entidad": GARAJE, "pasa_a": "on"}, "si": [{"entidad": MOVIL}]},
        {"cuando": {"entidad": GARAJE, "pasa_a": "on"}, "en_falso_si": {"entidad": GARAJE}},
    ])
    def test_una_regla_mal_escrita_se_dice(self, mala):
        assert reglas.validar(mala)
        with pytest.raises(ValueError):
            reglas.reproducir(mala, [(1.0, GARAJE, "on")])

    def test_la_frase_dice_lo_dudoso(self):
        cambios = [(t(2, "03:00"), GARAJE, "off"), (t(2, "03:10"), GARAJE, "unavailable"), (t(2, "03:11"), GARAJE, "on")]
        assert reglas.frase(reglas.reproducir(regla(), cambios)) == (
            "En 1 días habría saltado 1 vez, en 1 días distintos: 1 al reconectarse el sensor, 1 de madrugada.")
        assert "ni una vez" in reglas.frase(reglas.reproducir(regla(), cambios[:1]))
        assert reglas.entidades_de(regla(si=[{"entidad": MOVIL, "es": "home"}, {"entre": ["1:00", "2:00"]}])) == {GARAJE, MOVIL}


class TestRutinas:
    def _mes(self):
        """Tres semanas: llega a casa y enciende la entrada; la luz del despacho, a las 7:10
        los laborables; y el garaje, que a veces se queda abierto."""
        cambios = [(t(1, "00:00"), e, s) for e, s in ((MOVIL, "home"), (LUZ, "off"), ("light.despacho", "off"),
                                                       (GARAJE, "off"), ("binary_sensor.paso", "off"))]
        for dia in range(2, 23):
            laborable = datetime(2026, 11, dia, tzinfo=ZONA).weekday() < 5
            if laborable:
                cambios += [(t(dia, f"07:{8 + dia % 5:02d}"), "light.despacho", "on"), (t(dia, "07:50"), "light.despacho", "off"),
                            (t(dia, "08:00"), MOVIL, "not_home"), (t(dia, "18:30"), MOVIL, "home")]
                if dia != 10:    # un día no la encendió
                    cambios += [(t(dia, "18:32"), LUZ, "on"), (t(dia, "18:45"), LUZ, "off")]
            largo = dia in (5, 12, 19)
            cambios += [(t(dia, "19:00"), GARAJE, "on"), (t(dia, "19:55" if largo else "19:03"), GARAJE, "off")]
            # Un sensor de paso: decenas de cambios al día, no es rutina de nadie.
            for k in range(20):
                cambios += [(t(dia, f"{9 + k // 4:02d}:{(k % 4) * 15:02d}"), "binary_sensor.paso", "on"),
                            (t(dia, f"{9 + k // 4:02d}:{(k % 4) * 15 + 1:02d}"), "binary_sensor.paso", "off")]
        return sorted(cambios)

    def test_al_llegar_enciende_la_entrada(self):
        sec = rutinas.secuencias(self._mes())
        llegar = [r for r in sec if r["tras"] == MOVIL and r["tras_estado"] == "home" and r["entidad"] == LUZ]
        assert [(r["estado"], r["veces"], r["de"]) for r in llegar] == [("on", 14, 15)]
        assert not [r for r in sec if "paso" in r["tras"] or "paso" in r["entidad"]]
        # Y la propuesta, por el reproductor: habría actuado las mismas veces que llegó.
        inf = reglas.reproducir(llegar[0]["regla"], [c for c in self._mes() if c[1] in (MOVIL, LUZ)])
        assert inf["disparos"] == 15

    def test_el_horario_de_los_laborables(self):
        hor = [r for r in rutinas.horarios(self._mes()) if r["entidad"] == "light.despacho" and r["estado"] == "on"]
        assert len(hor) == 1 and hor[0]["cuando"] == "laborables" and hor[0]["dias"] == 15
        assert hor[0]["hora"].startswith("07:1") and hor[0]["regla"]["cuando"] == {"a_las": hor[0]["hora"]}
        assert not [r for r in rutinas.horarios(self._mes()) if "paso" in r["entidad"]]

    def test_el_garaje_que_se_queda_abierto(self):
        olv = rutinas.olvidos(self._mes())
        assert [(r["entidad"], r["veces"], r["de"], r["normal_min"]) for r in olv] == [(GARAJE, 3, 21, 3.0)]
        inf = reglas.reproducir(olv[0]["regla"], [c for c in self._mes() if c[1] == GARAJE])
        assert inf["disparos"] == 3

    def test_un_sensor_que_se_cae_no_es_alguien_haciendo_algo(self):
        cambios = [(1.0, LUZ, "off"), (2.0, LUZ, "unavailable"), (3.0, LUZ, "off"), (4.0, LUZ, "on"), (5.0, LUZ, "on")]
        assert rutinas.transiciones(cambios) == {LUZ: [(4.0, "off", "on", 1.0, 1.0)]}

    def test_lo_que_responde_al_instante_ya_es_una_automatizacion(self):
        cambios = [(t(1, "00:00"), "input_boolean.modo_cine", "off"), (t(1, "00:00"), "switch.altavoz", "on")]
        for dia in range(2, 10):
            cambios += [(t(dia, "21:00"), "input_boolean.modo_cine", "on"), (t(dia, "21:00") + 1, "switch.altavoz", "off"),
                        (t(dia, "23:00"), "input_boolean.modo_cine", "off"), (t(dia, "23:00") + 1, "switch.altavoz", "on")]
        sec = rutinas.secuencias(sorted(cambios))
        assert sec and all(r["ya_automatizada"] and "regla" not in r for r in sec)
        assert "Ya lo hace una automatización" in sec[0]["frase"]

    def test_lo_que_dura_segundos_y_lo_del_mismo_aparato_no_cuentan(self):
        cambios = [(t(1, "00:00"), e, "off") for e in ("binary_sensor.impresora_x1_filamento", "fan.impresora_x1_ventilador",
                                                        "light.mesa", MOVIL)]
        for dia in range(2, 16):
            cambios += [(t(dia, "10:00"), "binary_sensor.impresora_x1_filamento", "on"),
                        (t(dia, "10:01"), "fan.impresora_x1_ventilador", "on"),
                        (t(dia, "12:00"), "fan.impresora_x1_ventilador", "off"),
                        (t(dia, "12:00"), "binary_sensor.impresora_x1_filamento", "off"),
                        # La luz parpadea a las siete: un minuto encendida no es un horario.
                        (t(dia, "07:00"), "light.mesa", "on"), (t(dia, "07:01"), "light.mesa", "off")]
        cambios = sorted(cambios)
        assert rutinas.secuencias(cambios) == []
        assert [r for r in rutinas.horarios(cambios) if r["entidad"] == "light.mesa" and r["estado"] == "on"] == []

    def test_una_luz_sin_corriente_no_es_una_luz_olvidada(self):
        cambios = [(t(1, "00:00"), LUZ, "off")]
        for dia in range(2, 8):
            # Encendida diez minutos, y luego alguien le quita la corriente hasta el día siguiente.
            cambios += [(t(dia, "20:00"), LUZ, "on"), (t(dia, "20:10"), LUZ, "unavailable"), (t(dia + 1, "08:00"), LUZ, "off")]
        assert rutinas.olvidos(sorted(cambios)) == []

    def test_lo_que_esta_siempre_encendido_es_un_ajuste_no_un_olvido(self):
        cambios = [(t(1, "00:00"), "switch.altavoz_anuncios", "on")]
        for dia in range(2, 9):
            cambios += [(t(dia, "03:00"), "switch.altavoz_anuncios", "off"), (t(dia, "03:10"), "switch.altavoz_anuncios", "on")]
        assert rutinas.olvidos(sorted(cambios)) == []


class TestArchivo:
    CONF = {"movil": MOVIL, "incluir": ["sensor.temp*"], "excluir": ["switch.camara_*"]}

    def test_la_familia_no_entra_en_el_archivo(self):
        assert historia.se_archiva(MOVIL, self.CONF)
        for ajena in ("device_tracker.movil_de_otro", "person.otra", "media_player.tele_salon", "camera.jardin"):
            assert not historia.se_archiva(ajena, self.CONF)
        # Ni pidiéndolo: de quién es un móvil no se decide con un comodín.
        assert not historia.se_archiva("device_tracker.movil_de_otro", {"incluir": ["device_tracker.*"]})
        assert historia.se_archiva("light.entrada", {}) and historia.se_archiva("sensor.temp_salon", self.CONF)
        assert not historia.se_archiva("sensor.potencia", self.CONF)
        assert not historia.se_archiva("switch.camara_jardin_ir", self.CONF)

    def test_archiva_lo_que_falta_sin_duplicar_y_solo_lee(self, tmp_path):
        ahora = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        pedidas = []

        def pedir(url, token):
            pedidas.append(url)
            assert token == "tk" and "/api/services" not in url
            if url.endswith("/api/states"):
                return [{"entity_id": e} for e in (LUZ, MOVIL, "person.otra", "media_player.tele")]
            dia = url.split("/api/history/period/")[1][:10]
            return [[{"entity_id": LUZ, "state": "off", "last_changed": f"{dia}T00:00:00+00:00"},
                     {"state": "on", "last_changed": f"{dia}T18:00:00+00:00"}],
                    [{"entity_id": MOVIL, "state": "home", "last_changed": f"{dia}T00:00:00+00:00"}]]

        db = historia.abrir(tmp_path / "casa" / "historia.sqlite")
        r = historia.archivar(db, "http://ha", "tk", self.CONF, dias=3, ahora=ahora, pedir=pedir, decir=lambda *_: None)
        assert r == {"entidades": 2, "cambios": 12, "dias": 4, "fallidos": []}
        assert all("person" not in u and "media_player" not in u for u in pedidas[1:])
        # Otra vez: solo ayer y hoy se repiten, y no se duplica nada.
        pedidas.clear()
        r = historia.archivar(db, "http://ha", "tk", self.CONF, dias=3, ahora=ahora, pedir=pedir, decir=lambda *_: None)
        assert r["cambios"] == 0 and len(pedidas) == 3
        assert historia.resumen(db)["cambios"] == 12 and historia.resumen(db)["entidades"] == 2
        solo_luz = historia.leer(db, entidades=[LUZ], desde=datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp())
        assert [(e, s) for _, e, s in solo_luz] == [(LUZ, "off"), (LUZ, "on")]
        # Excluir algo vale hacia atrás: lo ya archivado se borra.
        historia.archivar(db, "http://ha", "tk", {"movil": MOVIL, "excluir": ["light.*"]}, dias=0, ahora=ahora,
                          pedir=pedir, decir=lambda *_: None)
        assert {e for _, e, _ in historia.leer(db)} == {MOVIL}

    def test_si_ha_no_contesta_se_dice(self, tmp_path):
        db = historia.abrir(tmp_path / "h.sqlite")
        with pytest.raises(historia.HaNoContesta):
            historia.archivar(db, "http://ha", "tk", {}, pedir=lambda u, t: [], decir=lambda *_: None)

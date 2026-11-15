"""Jarvis que se anticipa, fase 1 (`docs/JARVIS_ANTICIPA.md`).

Lo que se protege, que son las reglas que no se negocian: solo se apunta lo de la lista
cerrada del núcleo y solo con sus argumentos; un turno que ha leído texto de otros no enseña
nada; nada se ejecuta sin un «sí», el «sí» caduca y vuelve a pasar por el núcleo; lo que se
confirma no se aprende ni se sugiere; hay un mínimo entre sugerencias y un tope al día; un
no baja más de lo que sube un sí; y borrar se comprueba contando lo que queda.

Las tablas son listas en memoria: aquí no hay Supabase.
"""
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import pytest

import anticipa
import main
from conftest import FakeResponse

NUCLEO = anticipa.cargar_nucleo()
LUNES = date(2026, 11, 2)          # un lunes


def _ev(dia, minuto, accion="musica_poner", args=None, ubicacion="casa", tipo="peticion", **extra):
    norm = anticipa.normalizar(accion, args if args is not None else {"que": "lofi"}, NUCLEO)
    return {"id": str(uuid.uuid4()), "dia": dia.isoformat(), "minuto": minuto, "dia_semana": dia.weekday(),
            "ubicacion": ubicacion, "tipo": tipo, "accion": norm["accion"],
            "herramienta": norm["herramienta"], "argumentos": norm["argumentos"], **extra}


# ── El núcleo y la lista cerrada ──────────────────────────────────────────────

class TestNucleo:
    def test_el_nucleo_del_repositorio_es_valido(self):
        assert NUCLEO["anticipa"]["ejecutar_sola"] is False
        assert NUCLEO["anticipa"]["limites"]["max_sugerencias_dia"] >= 1

    def test_nada_irreversible_esta_entre_lo_que_se_sugiere(self):
        assert not set(NUCLEO["anticipa"]["acciones"]) & set(NUCLEO["irreversible"]["herramientas"])

    def test_lo_que_se_sugiere_existe_y_no_se_confirma(self):
        for nombre in NUCLEO["anticipa"]["acciones"]:
            assert nombre in main._JARVIS_HERRAMIENTAS, nombre
        for nombre in ("musica_poner", "tele", "pc_abrir", "encender_pc", "recordarme"):
            assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False

    def test_un_nucleo_que_sugiere_algo_irreversible_no_carga(self, tmp_path):
        malo = json.loads(json.dumps(NUCLEO))
        malo["anticipa"]["acciones"]["whatsapp_enviar"] = {"nivel": "bajo", "argumentos": []}
        ruta = tmp_path / "nucleo.json"
        ruta.write_text(json.dumps(malo), encoding="utf-8")
        with pytest.raises(RuntimeError):
            anticipa.cargar_nucleo(str(ruta))

    def test_nadie_abre_el_nucleo_para_escribir(self):
        # La garantía de «un archivo que Jarvis no puede editar»: el backend solo lo lee,
        # y solo desde `cargar_nucleo`.
        modulo = open(anticipa.__file__, encoding="utf-8").read()
        assert not re.search(r"open\([^)]*[\"'](w|a|r\+|x)", modulo)
        fuente = open(main.__file__, encoding="utf-8-sig").read()
        codigo = [l for l in fuente.splitlines()
                  if "nucleo_seguridad.json" in l and not l.lstrip().startswith("#")]
        assert all("logger." in l or '"' in l and "open(" not in l for l in codigo)
        assert "ruta_nucleo" not in fuente


class TestNormalizar:
    def test_fuera_de_la_lista_no_hay_accion(self):
        for nombre in ("whatsapp_enviar", "garaje", "llamar_a_alguien", "desplegar", "agenda"):
            assert anticipa.normalizar(nombre, {"x": 1}, NUCLEO) is None

    def test_solo_pasan_los_argumentos_declarados(self):
        norm = anticipa.normalizar("musica_poner", {"que": "Lofi", "credentials": "x", "tipo": "lista"}, NUCLEO)
        assert norm["argumentos"] == {"que": "Lofi", "tipo": "lista"}
        assert norm["nivel"] == "bajo"

    def test_lo_mismo_dicho_distinto_es_la_misma_accion(self):
        a = anticipa.normalizar("musica_poner", {"que": "Música  de Concentración"}, NUCLEO)
        b = anticipa.normalizar("musica_poner", {"que": "musica de concentracion"}, NUCLEO)
        c = anticipa.normalizar("musica_poner", {"que": "rock"}, NUCLEO)
        assert a["accion"] == b["accion"] != c["accion"]

    def test_de_la_tele_solo_encender_apagar_y_abrir(self):
        assert anticipa.normalizar("tele", {"accion": "abrir", "valor": "Netflix"}, NUCLEO)
        assert anticipa.normalizar("tele", {"accion": "tecla", "valor": "KEY_HOME"}, NUCLEO) is None
        assert anticipa.normalizar("tele", {"accion": "volumen_subir"}, NUCLEO) is None

    def test_de_la_casa_solo_luces_y_clima(self):
        assert anticipa.normalizar("casa_ordenar", {"servicio": "light.turn_on", "entidad": "light.cuarto",
                                                    "datos": {"brightness_pct": 40}}, NUCLEO)
        for servicio, entidad in (("lock.unlock", "lock.puerta"), ("cover.open_cover", "cover.garaje"),
                                  ("homeassistant.toggle", "cover.garaje"), ("light.turn_on", "cover.garaje"),
                                  ("script.turn_on", "script.quitar_alarma"),
                                  ("switch.turn_on", "switch.puerta_garaje"),
                                  ("alarm_control_panel.alarm_disarm", "alarm_control_panel.casa")):
            assert anticipa.normalizar("casa_ordenar", {"servicio": servicio, "entidad": entidad}, NUCLEO) is None

    def test_un_extra_que_no_se_sabe_repetir_no_es_un_habito(self):
        assert anticipa.normalizar("casa_ordenar", {"servicio": "light.turn_on", "entidad": "light.cuarto",
                                                    "datos": {"effect": {"x": 1}}}, NUCLEO) is None

    def test_el_evento_no_admite_origenes_ni_lugares_de_fuera_de_la_lista(self):
        norm = anticipa.normalizar("encender_pc", {}, NUCLEO)
        ahora = datetime(2026, 11, 2, 9, 5)
        assert anticipa.evento(ahora, "casa", "whatsapp", norm) is None
        assert anticipa.evento(ahora, "casa", "sistema", norm) is None
        assert anticipa.evento(ahora, "", "voz", norm) is None
        fila = anticipa.evento(ahora, "casa", "voz", norm)
        assert (fila["dia"], fila["minuto"], fila["dia_semana"]) == ("2026-11-02", 545, 0)


# ── El detector ───────────────────────────────────────────────────────────────

class TestDetectar:
    def test_cuatro_lunes_de_cinco_es_un_patron_de_los_lunes(self):
        eventos = [_ev(LUNES + timedelta(days=7 * k), 540 + k * 5) for k in (0, 1, 2, 4)]
        (p,) = anticipa.detectar(eventos, LUNES + timedelta(days=29))
        assert (p["grupo"], p["ubicacion"], p["ocurrencias"], p["dias_posibles"]) == ("d0", "casa", 4, 5)
        assert p["proporcion"] == 0.8 and 540 <= p["minuto"] <= 560

    def test_entre_semana_sale_un_patron_y_no_cinco(self):
        dias = [LUNES + timedelta(days=k) for k in range(12) if (LUNES + timedelta(days=k)).weekday() < 5]
        patrones = anticipa.detectar([_ev(d, 480) for d in dias], LUNES + timedelta(days=11))
        assert [p["grupo"] for p in patrones] == ["laborables"]

    def test_pocas_veces_no_es_un_patron(self):
        assert anticipa.detectar([_ev(LUNES, 540), _ev(LUNES + timedelta(days=7), 540)],
                                 LUNES + timedelta(days=8)) == []

    def test_a_horas_dispersas_no_es_un_patron(self):
        eventos = [_ev(LUNES + timedelta(days=7 * k), 300 + k * 200) for k in range(4)]
        assert anticipa.detectar(eventos, LUNES + timedelta(days=22)) == []

    def test_tres_veces_la_misma_manana_no_son_tres_mananas(self):
        eventos = [_ev(LUNES, 540), _ev(LUNES, 545), _ev(LUNES, 550), _ev(LUNES + timedelta(days=7), 540)]
        assert anticipa.detectar(eventos, LUNES + timedelta(days=8)) == []

    def test_dejar_de_hacerlo_rompe_el_patron(self):
        eventos = [_ev(LUNES + timedelta(days=7 * k), 540) for k in range(3)]
        assert len(anticipa.detectar(eventos, LUNES + timedelta(days=15))) == 1
        assert anticipa.detectar(eventos, LUNES + timedelta(days=36)) == []

    def test_el_lugar_separa_patrones(self):
        eventos = [_ev(LUNES + timedelta(days=7 * k), 540, ubicacion="casa" if k % 2 else "uni")
                   for k in range(4)]
        assert anticipa.detectar(eventos, LUNES + timedelta(days=22)) == []

    def test_un_si_cuenta_como_haberlo_hecho_y_un_no_no(self):
        base = [_ev(LUNES + timedelta(days=7 * k), 540) for k in range(2)]
        si = _ev(LUNES + timedelta(days=14), 535, tipo="sugerencia", respuesta="si")
        no = _ev(LUNES + timedelta(days=14), 535, tipo="sugerencia", respuesta="no")
        hoy = LUNES + timedelta(days=15)
        assert len(anticipa.detectar(base + [si], hoy)) == 1
        assert anticipa.detectar(base + [no], hoy) == []


# ── La confianza y la entrega ─────────────────────────────────────────────────

class TestConfianza:
    def test_un_no_baja_mas_de_lo_que_sube_un_si(self):
        c = anticipa.CONFIANZA_INICIAL
        assert c - anticipa.tras_respuesta(c, "no") > anticipa.tras_respuesta(c, "si") - c

    def test_ignorada_no_cuenta(self):
        assert anticipa.tras_respuesta(0.7, "ignorada") == 0.7
        assert anticipa.tras_respuesta(0.7, None) == 0.7

    def test_un_no_deja_de_proponerlo(self):
        assert anticipa.tras_respuesta(anticipa.CONFIANZA_INICIAL, "no") < anticipa.U_SUGERIR

    def test_lo_que_nadie_confirma_decae_y_lo_que_repite_sube(self):
        assert anticipa.repasar(0.6, 30, False) < anticipa.U_SUGERIR
        assert anticipa.repasar(0.5, 1, True) > 0.5
        assert anticipa.repasar(0.6, 0, False) == 0.6

    def test_en_fase_1_nada_se_ejecuta_solo(self):
        encendido = json.loads(json.dumps(NUCLEO))
        encendido["anticipa"]["ejecutar_sola"] = True
        for nivel in ("bajo", "medio"):
            assert anticipa.puede_ejecutar_sola(nivel, 1.0, encendido) is False


class TestEntrega:
    PATRON = {"grupo": "d0", "minuto": 540, "ubicacion": "casa", "confianza": 0.6}

    def test_toca_un_poco_antes_de_su_hora_y_no_mucho_despues(self):
        assert anticipa.toca(self.PATRON, datetime(2026, 11, 2, 8, 50), "casa")
        assert anticipa.toca(self.PATRON, datetime(2026, 11, 2, 9, 10), "casa")
        assert not anticipa.toca(self.PATRON, datetime(2026, 11, 2, 8, 30), "casa")
        assert not anticipa.toca(self.PATRON, datetime(2026, 11, 2, 9, 30), "casa")

    def test_no_toca_otro_dia_ni_en_otro_sitio_ni_con_poca_confianza(self):
        assert not anticipa.toca(self.PATRON, datetime(2026, 11, 3, 9, 0), "casa")
        assert not anticipa.toca(self.PATRON, datetime(2026, 11, 2, 9, 0), "uni")
        assert not anticipa.toca({**self.PATRON, "confianza": 0.5}, datetime(2026, 11, 2, 9, 0), "casa")

    def test_los_frenos(self):
        ahora = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
        assert anticipa.puede_entregar(ahora, None, 0, False, NUCLEO)
        assert not anticipa.puede_entregar(ahora, None, 0, True, NUCLEO)
        assert not anticipa.puede_entregar(ahora, None, 2, False, NUCLEO)
        assert not anticipa.puede_entregar(ahora, ahora - timedelta(minutes=89), 1, False, NUCLEO)
        assert anticipa.puede_entregar(ahora, ahora - timedelta(minutes=91), 1, False, NUCLEO)

    def test_la_frase_y_el_porque_los_escribe_el_backend(self):
        p = {**self.PATRON, "herramienta": "musica_poner", "argumentos": {"que": "lofi"},
             "ocurrencias": 4, "dias_posibles": 5, "proporcion": 0.8}
        assert anticipa.frase(p) == "Señor, los lunes, sobre las 9:00, suele poner «lofi» en casa. ¿Lo hago?"
        porque = anticipa.explicar(p)
        assert "4 de 5 días (80 %)" in porque and "0.60" in porque

    def test_la_aceptacion_no_cuenta_las_ignoradas(self):
        r = anticipa.aceptacion([{"respuesta": "si"}, {"respuesta": "si"}, {"respuesta": "no"},
                                 {"respuesta": "ignorada"}, {}])
        assert (r["aceptacion_pct"], r["ignoradas"], r["sin_contestar"]) == (67, 1, 1)
        assert anticipa.aceptacion([])["aceptacion_pct"] is None


# ── El enganche con el backend ────────────────────────────────────────────────

AHORA = datetime(2026, 11, 30, 8, 55, tzinfo=main.LOCAL_TZ)     # un lunes


class Tablas:
    """Supabase de mentira para las tres tablas, con lo justo del filtro de PostgREST."""

    def __init__(self):
        self.eventos, self.patrones, self.borrados, self.preguntas = [], [], [], {}

    def _tabla(self, url):
        if "jarvis_eventos" in url:
            return self.eventos
        if "jarvis_patrones" in url:
            return self.patrones
        if "jarvis_anticipa_borrados" in url:
            return self.borrados
        raise AssertionError(url)

    @staticmethod
    def _casa(fila, url):
        for trozo in unquote(url.split("?", 1)[1]).split("&") if "?" in url else []:
            campo, _, cond = trozo.partition("=")
            if campo in ("select", "order", "limit"):
                continue
            op, _, valor = cond.partition(".")
            actual = fila.get(campo)
            if op == "eq" and str(actual) != valor:
                return False
            if op == "is" and (actual is None) != (valor == "null"):
                return False
            if op == "not" and valor == "is.null" and actual is None:
                return False
            if op in ("gte", "lte", "lt"):
                try:
                    a, b = float(actual), float(valor)
                except (TypeError, ValueError):
                    a, b = str(actual), valor
                if (op == "gte" and a < b) or (op == "lte" and a > b) or (op == "lt" and a >= b):
                    return False
        return True

    def get(self, url, **kw):
        filas = [dict(f) for f in self._tabla(url) if self._casa(f, url)]
        return FakeResponse(filas, headers={"Content-Range": f"0-0/{len(filas)}"})

    def post(self, url, json=None, **kw):
        self._tabla(url).append(dict(json))
        return FakeResponse([], 201)

    def patch(self, url, json=None, **kw):
        tocadas = [f for f in self._tabla(url) if self._casa(f, url)]
        for f in tocadas:
            f.update(json)
        return FakeResponse([dict(f) for f in tocadas])

    def delete(self, url, **kw):
        tabla = self._tabla(url)
        fuera = [f for f in tabla if self._casa(f, url)]
        tabla[:] = [f for f in tabla if not self._casa(f, url)]
        return FakeResponse(fuera)


@pytest.fixture
def anti(monkeypatch):
    t = Tablas()
    avisos, hechas = [], []
    for nombre, valor in (("ANTICIPA", True), ("ANTICIPA_SUGIERE", True), ("HORA_SILENCIO", (22, 0))):
        monkeypatch.setattr(main, nombre, valor)
    monkeypatch.setattr(main, "_anticipa_estado", {"aprendido": "", "sin_tabla": False, "pendientes": True})
    for metodo in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(main.http, metodo, getattr(t, metodo))
    monkeypatch.setattr(main, "_anticipa_en_segundo_plano", lambda fn, *a: fn(*a))
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": "casa"})
    monkeypatch.setattr(main, "_telefono_puede_sonar", lambda ahora: (True, "despierto"))
    monkeypatch.setattr(main, "_movil_vivo", lambda: True)
    monkeypatch.setattr(main, "_notificar", lambda t_, x, **kw: avisos.append((t_, x, kw)) or "movil")
    monkeypatch.setattr(main, "_acusar_recibo", lambda t_, x, **kw: avisos.append((t_, x, kw)))
    monkeypatch.setattr(main, "_guardar_pregunta_con_accion",
                        lambda pid, texto, ops, h, args, caduca=None, extra=None: t.preguntas.__setitem__(
                            pid, {"id": pid, "texto": texto, "accion": {
                                **(extra or {}), "herramienta": h, "argumentos": args,
                                "caduca": caduca.astimezone(timezone.utc).isoformat()}}) or True)
    monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["musica_poner"], "fn",
                        lambda **kw: hechas.append(kw) or {"ok": True, "sonando": kw["que"]})
    marca = main._boca_actual.set("voz")
    yield type("A", (), {"t": t, "avisos": avisos, "hechas": hechas})
    main._boca_actual.reset(marca)


def _patron_guardado(t, confianza=0.6, minuto=540, grupo="d0"):
    norm = anticipa.normalizar("musica_poner", {"que": "lofi"}, NUCLEO)
    p = {"clave": f"{norm['accion']}@{grupo}@casa", "accion": norm["accion"], "herramienta": "musica_poner",
         "argumentos": norm["argumentos"], "grupo": grupo, "minuto": minuto, "ubicacion": "casa",
         "ocurrencias": 4, "dias_posibles": 5, "proporcion": 0.8, "confianza": confianza,
         "repasado": AHORA.date().isoformat(), "ultima_vez": "2026-11-23"}
    t.patrones.append(p)
    return p


class TestApuntar:
    def test_lo_que_pide_se_apunta_con_su_lugar_y_su_boca(self, anti):
        main._jarvis_despachar("musica_poner", {"que": "lofi", "inventado": "x"})
        (e,) = anti.t.eventos
        assert (e["tipo"], e["origen"], e["ubicacion"], e["herramienta"]) == ("peticion", "voz", "casa", "musica_poner")
        assert e["argumentos"] == {"que": "lofi"}

    def test_tras_leer_texto_ajeno_no_se_apunta(self, anti):
        main._jarvis_despachar("musica_poner", {"que": "lofi"}, tras_ajeno=True)
        assert anti.hechas and anti.t.eventos == []

    def test_lo_que_no_es_de_la_lista_no_se_apunta(self, anti):
        main._jarvis_despachar("clima", {})
        assert anti.t.eventos == []

    def test_lo_que_falla_no_se_apunta(self, anti, monkeypatch):
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["musica_poner"], "fn", lambda **kw: {"error": "sin Spotify"})
        main._jarvis_despachar("musica_poner", {"que": "lofi"})
        assert anti.t.eventos == []

    def test_lo_que_hace_el_sistema_solo_no_se_apunta(self, anti):
        marca = main._boca_actual.set("sistema")
        try:
            main._jarvis_despachar("musica_poner", {"que": "lofi"})
        finally:
            main._boca_actual.reset(marca)
        assert anti.t.eventos == []

    def test_sin_saber_donde_esta_no_se_apunta(self, anti, monkeypatch):
        monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: None)
        main._jarvis_despachar("musica_poner", {"que": "lofi"})
        assert anti.t.eventos == []

    def test_apagado_no_apunta(self, anti, monkeypatch):
        monkeypatch.setattr(main, "ANTICIPA", False)
        main._jarvis_despachar("musica_poner", {"que": "lofi"})
        assert anti.t.eventos == []

    def test_un_fallo_apuntando_no_rompe_lo_pedido(self, anti, monkeypatch):
        monkeypatch.setattr(main.http, "post", lambda *a, **kw: FakeResponse([], 404))
        assert main._jarvis_despachar("musica_poner", {"que": "lofi"})["ok"] is True

    def test_en_el_chat_un_turno_que_ha_leido_un_whatsapp_no_ensena(self, anti):
        # El bucle le pasa al despachador lo que ya sabe: que el turno es ajeno.
        fuente = open(main.__file__, encoding="utf-8-sig").read()
        assert "_jarvis_despachar(c.function.name, argumentos, tras_ajeno=bool(ajeno))" in fuente
        assert "tras_ajeno=bool(hay_ajeno and hay_ajeno())" in fuente


class TestAprender:
    def test_del_registro_sale_el_patron_con_su_confianza_inicial(self, anti):
        for k in (1, 2, 3, 4):
            anti.t.eventos.append(_ev(AHORA.date() - timedelta(days=7 * k), 540))
        assert main._anticipa_tick_seguro().get("anticipa_patrones") == 1
        (p,) = anti.t.patrones
        assert p["grupo"] == "d0" and p["confianza"] == anticipa.CONFIANZA_INICIAL

    def test_se_aprende_una_vez_al_dia(self, anti):
        for k in (1, 2, 3, 4):
            anti.t.eventos.append(_ev(AHORA.date() - timedelta(days=7 * k), 540))
        main._anticipa_tick_seguro()
        anti.t.patrones.clear()
        main._anticipa_tick_seguro()
        assert anti.t.patrones == []

    def test_lo_que_ya_no_se_sostiene_decae_y_acaba_olvidado(self, anti):
        p = _patron_guardado(anti.t, confianza=0.21)
        p["repasado"] = (AHORA.date() - timedelta(days=10)).isoformat()
        main._anticipa_aprender(AHORA.date())
        assert anti.t.patrones == []

    def test_sin_la_migracion_no_tumba_el_reloj(self, anti, monkeypatch):
        monkeypatch.setattr(main.http, "get", lambda *a, **kw: FakeResponse([], 404))
        assert main._anticipa_tick_seguro() == {}


class TestSugerir:
    def test_propone_lo_de_siempre_con_dos_botones(self, anti):
        p = _patron_guardado(anti.t)
        assert main._anticipa_tick()["anticipa"] == "sugerido"
        (titulo, texto, kw), = anti.avisos
        assert texto == "Señor, los lunes, sobre las 9:00, suele poner «lofi» en casa. ¿Lo hago?"
        assert [a["title"] for a in kw["acciones"]] == [main.PREGUNTA_SI, main.PREGUNTA_NO]
        (e,) = anti.t.eventos
        assert (e["tipo"], e["patron"], e.get("respuesta")) == ("sugerencia", p["clave"], None)
        assert anti.hechas == []          # proponer no es hacer

    def test_no_repite_la_misma_ni_pasa_del_tope(self, anti):
        _patron_guardado(anti.t)
        main._anticipa_tick()
        main._anticipa_tick()
        assert len(anti.avisos) == 1

    def test_si_ya_lo_ha_pedido_hoy_no_lo_propone(self, anti):
        _patron_guardado(anti.t)
        anti.t.eventos.append(_ev(AHORA.date(), 530))
        assert "anticipa" not in main._anticipa_tick()

    @pytest.mark.parametrize("que", ["clase", "noche", "sin_movil", "otro_sitio", "poca_confianza", "apagado"])
    def test_cuando_calla(self, anti, monkeypatch, que):
        _patron_guardado(anti.t, confianza=0.5 if que == "poca_confianza" else 0.6)
        if que == "clase":
            monkeypatch.setattr(main, "_telefono_puede_sonar", lambda ahora: (False, "en clase"))
        elif que == "noche":
            monkeypatch.setattr(main, "HORA_SILENCIO", (8, 0))
        elif que == "sin_movil":
            monkeypatch.setattr(main, "_movil_vivo", lambda: False)
        elif que == "otro_sitio":
            monkeypatch.setattr(main, "_lugar_actual_seguro", lambda: {"lugar": "uni"})
        elif que == "apagado":
            monkeypatch.setattr(main, "ANTICIPA_SUGIERE", False)
        main._anticipa_tick()
        assert anti.avisos == []

    def test_noventa_minutos_entre_dos_sugerencias(self, anti):
        _patron_guardado(anti.t)
        hace_poco = datetime.now(timezone.utc) - timedelta(minutes=30)
        anti.t.eventos.append({**_ev(AHORA.date(), 500, args={"que": "otra"}, tipo="sugerencia"),
                               "ts": hace_poco.isoformat(), "respuesta": "si"})
        main._anticipa_tick()
        assert anti.avisos == []

    def test_un_patron_de_algo_que_ya_no_esta_en_el_nucleo_no_se_propone(self, anti, monkeypatch):
        _patron_guardado(anti.t)
        sin = json.loads(json.dumps(NUCLEO))
        del sin["anticipa"]["acciones"]["musica_poner"]
        monkeypatch.setattr(main, "_ANTICIPA_NUCLEO", sin)
        main._anticipa_tick()
        assert anti.avisos == []

    def test_lo_que_no_se_contesta_queda_ignorado_y_no_mueve_la_confianza(self, anti):
        p = _patron_guardado(anti.t)
        viejo = datetime.now(timezone.utc) - timedelta(minutes=30)
        anti.t.eventos.append({**_ev(AHORA.date() - timedelta(days=1), 540, tipo="sugerencia"),
                               "ts": viejo.isoformat(), "respuesta": None, "patron": p["clave"]})
        main._anticipa_cerrar_ignoradas(AHORA)
        assert anti.t.eventos[0]["respuesta"] == "ignorada" and p["confianza"] == 0.6


class TestResponder:
    def _sugerida(self, anti):
        p = _patron_guardado(anti.t)
        main._anticipa_tick()
        (pid, fila), = anti.t.preguntas.items()
        anti.avisos.clear()
        return p, pid, fila

    def test_el_si_lo_hace_sube_la_confianza_y_no_cuenta_como_peticion(self, anti):
        p, pid, fila = self._sugerida(anti)
        r = main._anticipa_respondida(pid, fila, True)
        assert r["respuesta"] == "si" and anti.hechas == [{"que": "lofi"}]
        assert p["confianza"] > 0.6
        assert [(e["tipo"], e["respuesta"]) for e in anti.t.eventos] == [("sugerencia", "si")]

    def test_el_no_no_hace_nada_y_deja_de_proponerlo(self, anti):
        p, pid, fila = self._sugerida(anti)
        main._anticipa_respondida(pid, fila, False)
        assert anti.hechas == [] and p["confianza"] < anticipa.U_SUGERIR
        assert anti.t.eventos[0]["respuesta"] == "no"

    def test_un_si_tardio_no_hace_nada(self, anti):
        _, pid, fila = self._sugerida(anti)
        fila["accion"]["caduca"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        assert main._anticipa_respondida(pid, fila, True)["hecho"] is False
        assert anti.hechas == []

    def test_una_fila_manipulada_no_ejecuta_lo_que_no_es_de_la_lista(self, anti, monkeypatch):
        _, pid, fila = self._sugerida(anti)
        enviados = []
        monkeypatch.setitem(main._JARVIS_HERRAMIENTAS["whatsapp_enviar"], "fn",
                            lambda **kw: enviados.append(kw) or {"ok": True})
        fila["accion"].update(herramienta="whatsapp_enviar", argumentos={"a": "Aimar", "texto": "hola"})
        r = main._anticipa_respondida(pid, fila, True)
        assert enviados == [] and r["resultado"]["ok"] is False

    def test_el_boton_de_una_sugerencia_no_pasa_por_las_acciones_del_movil(self, anti):
        # El camino de `PREGUNTAS_ACCIONES` no ejecuta música: si la sugerencia cayera ahí,
        # se negaría. Y la música no entra en esa lista por estar en el núcleo.
        assert not set(NUCLEO["anticipa"]["acciones"]) & (main.PREGUNTAS_ACCIONES - {"recordarme"})


class TestVerYBorrar:
    def test_mis_patrones_cuenta_el_porque_con_numeros(self, anti):
        _patron_guardado(anti.t)
        r = main._j_mis_patrones()
        (p,) = r["patrones"]
        assert p["numero"] == 1 and p["que"] == "poner «lofi»" and "4 de 5 días" in p["por_que"]
        assert r["sugerencias_14_dias"]["aceptacion_pct"] is None

    def test_olvidar_un_patron_se_lleva_lo_que_lo_sostenia(self, anti):
        _patron_guardado(anti.t)
        anti.t.eventos += [_ev(LUNES, 540), _ev(LUNES, 600, args={"que": "rock"})]
        r = main._j_olvidar_patron(1)
        assert r["ok"] and r["eventos_borrados"] == 1 and anti.t.patrones == []
        assert len(anti.t.eventos) == 1          # lo de «rock» no era de ese patrón
        assert anti.t.borrados[0]["que"] == "patron"

    def test_olvidar_un_numero_que_no_existe_no_borra_nada(self, anti):
        _patron_guardado(anti.t)
        assert "error" in main._j_olvidar_patron(7) and len(anti.t.patrones) == 1

    def test_borrarlo_todo_se_comprueba_y_deja_solo_el_acuse(self, anti):
        _patron_guardado(anti.t)
        anti.t.eventos += [_ev(LUNES, 540), _ev(LUNES, 600)]
        r = main._j_borrar_anticipacion()
        assert r["ok"] and (r["eventos_borrados"], r["patrones_borrados"]) == (2, 1)
        assert anti.t.eventos == [] and anti.t.patrones == []
        (acuse,) = anti.t.borrados
        assert acuse == {"que": "todo", "eventos": 2, "patrones": 1, "quedan": 0}

    def test_si_no_se_puede_borrar_no_lo_da_por_borrado(self, anti, monkeypatch):
        monkeypatch.setattr(main.http, "delete", lambda *a, **kw: FakeResponse([], 500))
        assert "error" in main._j_borrar_anticipacion()

    def test_borrar_no_se_puede_tras_leer_texto_ajeno(self):
        for nombre in ("olvidar_patron", "borrar_anticipacion"):
            assert main._ajeno_bloquea(nombre, {"whatsapp_leer"}) is not None
        assert main._ajeno_bloquea("mis_patrones", {"whatsapp_leer"}) is None

"""«Organízame mañana»: `huecos_libres` y `reservar_bloques`.

Lo que se comprueba aquí son las dos reglas que hacen fiable la función, más allá de que
las cuentas de horas salgan bien:

- **No poder leer el calendario nunca es un día libre.** Si Outlook falla, `huecos_libres`
  lo dice y no devuelve huecos; `reservar_bloques` no crea nada.
- **Al confirmar se vuelve a mirar el calendario.** Lo que entró entre proponer y pulsar
  se rechaza con su motivo, y confirmar dos veces no duplica.
"""
from datetime import datetime, timezone

import pytest

import main

TZ = main.LOCAL_TZ
# Domingo por la mañana. Mañana es lunes 28.
AHORA  = datetime(2026, 9, 27, 10, 7, tzinfo=TZ)
HOY    = "2026-09-27"
MANANA = "2026-09-28"


def _local(dia: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{dia}T{hhmm}:00").replace(tzinfo=TZ)


def _z(instante: datetime) -> str:
    """Como lo devuelven los endpoints de calendario: ISO en UTC con Z."""
    return instante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ev(titulo, dia, ini, fin, dia_fin=None, **extra):
    return {"id": f"ev-{titulo}", "title": titulo,
            "start": _z(_local(dia, ini)), "end": _z(_local(dia_fin or dia, fin)),
            "isAllDay": False, **extra}


def _calendario(monkeypatch, eventos=None, clases=None):
    """Sustituye las dos lecturas de Graph. Un dict o una excepción se devuelven/lanzan
    tal cual; una lista se envuelve como la devuelve el endpoint."""
    def _hace(valor):
        def _fn(credentials=None):
            if isinstance(valor, Exception):
                raise valor
            if isinstance(valor, dict):
                return valor
            return {"events": list(valor or [])}
        return _fn
    monkeypatch.setattr(main, "get_events", _hace(eventos))
    monkeypatch.setattr(main, "get_class_events", _hace(clases))


@pytest.fixture(autouse=True)
def _reloj(monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    # Sin base de sueño por defecto: la lectura real iría a Supabase.
    monkeypatch.setattr(main, "_hora_habitual_dormir", lambda: None)
    monkeypatch.setattr(main, "HUECOS_MARGEN_MIN", 10)


@pytest.fixture
def creados(monkeypatch):
    lista = []

    def _crear(body, credentials=None):
        lista.append(body)
        return {"status": "ok", "id": f"nuevo-{len(lista)}"}

    monkeypatch.setattr(main, "create_event", _crear)
    return lista


# ── _huecos ───────────────────────────────────────────────────────────────────

class TestHuecos:
    INI = _local(MANANA, "08:00")
    FIN = _local(MANANA, "22:00")

    def _h(self, *pares):
        return [(_local(MANANA, a), _local(MANANA, b)) for a, b in pares]

    def test_dia_vacio_es_un_solo_tramo(self):
        assert main._huecos([], self.INI, self.FIN, 30, 10) == [(self.INI, self.FIN)]

    def test_solapados_anidados_y_desordenados_se_funden(self):
        ocupados = self._h(("10:30", "12:00"), ("09:00", "11:00"), ("10:00", "10:15"))
        assert main._huecos(ocupados, self.INI, self.FIN, 15, 0) == self._h(
            ("08:00", "09:00"), ("12:00", "22:00"))

    def test_los_que_se_tocan_se_funden(self):
        ocupados = self._h(("09:00", "10:00"), ("10:00", "11:00"))
        assert main._huecos(ocupados, self.INI, self.FIN, 15, 0) == self._h(
            ("08:00", "09:00"), ("11:00", "22:00"))

    def test_el_que_viene_de_la_noche_anterior_recorta_el_inicio(self):
        medianoche = _local(MANANA, "00:00")
        fiesta = [(_local(HOY, "23:00"), _local(MANANA, "02:00"))]
        assert main._huecos(fiesta, medianoche, self.FIN, 30, 0) == [
            (_local(MANANA, "02:00"), self.FIN)]

    def test_aplica_el_margen(self):
        # La del criterio de aceptación: clase de 9 a 11 con diez minutos de margen.
        clase = self._h(("09:00", "11:00"))
        assert main._huecos(clase, self.INI, self.FIN, 30, 10) == self._h(
            ("08:00", "08:50"), ("11:10", "22:00"))

    def test_descarta_los_que_no_llegan_al_minimo(self):
        ocupados = self._h(("08:20", "12:00"))
        assert main._huecos(ocupados, self.INI, self.FIN, 30, 0) == self._h(("12:00", "22:00"))

    def test_inicio_posterior_al_fin_no_da_nada(self):
        assert main._huecos([], self.FIN, self.INI, 15, 0) == []
        assert main._huecos([], self.INI, self.INI, 15, 0) == []


# ── _limites_dia ──────────────────────────────────────────────────────────────

class TestLimitesDia:
    def test_hoy_empieza_en_el_siguiente_cuarto(self):
        dia = AHORA.date()
        l = main._limites_dia(dia, AHORA, None, None, None)
        assert l["inicio"] == _local(HOY, "10:15")
        assert l["origen_inicio"] == "ahora"
        exacto = main._limites_dia(dia, _local(HOY, "10:15"), None, None, None)
        assert exacto["inicio"] == _local(HOY, "10:15")

    def test_un_dia_futuro_empieza_a_la_hora_fija(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, None, None, None)
        assert l["inicio"] == _local(MANANA, "08:00")
        assert l["origen_inicio"] == "fijo"

    def test_el_fin_se_aprende_de_la_hora_de_dormir(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, None, None, (23, 30))
        assert l["fin"] == _local(MANANA, "22:30")
        assert l["origen_fin"] == "aprendido"
        assert l["hora_habitual_dormir"] == "23:30"

    def test_dormir_pasada_la_medianoche_es_la_noche_de_ese_dia(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, None, None, (0, 30))
        assert l["fin"] == _local(MANANA, "23:30")

    def test_el_fin_no_pasa_de_la_medianoche(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, None, None, (1, 30))
        assert l["fin"] == _local("2026-09-29", "00:00")

    def test_sin_base_el_fin_es_el_fijo(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, None, None, None)
        assert l["fin"] == _local(MANANA, "22:00")
        assert l["origen_fin"] == "fijo"
        assert "hora_habitual_dormir" not in l

    def test_lo_pedido_manda(self):
        l = main._limites_dia(_local(MANANA, "00:00").date(), AHORA, "16:00", "20:00", (23, 0))
        assert (l["inicio"], l["fin"]) == (_local(MANANA, "16:00"), _local(MANANA, "20:00"))
        assert (l["origen_inicio"], l["origen_fin"]) == ("pedido", "pedido")


# ── huecos_libres ─────────────────────────────────────────────────────────────

class TestHuecosLibres:
    def test_outlook_con_error_no_es_un_dia_libre(self, monkeypatch):
        _calendario(monkeypatch, {"error": "No autenticado"}, [])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["ok"] is False
        assert "huecos" not in r
        assert "no lo he podido comprobar" in r["dile_al_usuario_literalmente"]
        assert "Outlook" in r["dile_al_usuario_literalmente"]

    def test_outlook_que_revienta_tampoco(self, monkeypatch):
        _calendario(monkeypatch, TimeoutError("Graph no contesta"), [])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["ok"] is False
        assert "huecos" not in r
        assert r["dile_al_usuario_literalmente"]

    def test_sin_calendario_de_clases_sigue_y_lo_avisa(self, monkeypatch):
        _calendario(monkeypatch, [], {"error": "Calendario 'Clases' no encontrado",
                                      "available": ["Calendario"]})
        r = main._j_huecos_libres(dia=MANANA)
        assert r["ok"] is True
        assert any("clases" in a for a in r["avisos"])

    def test_clases_con_otro_error_no_es_un_dia_libre(self, monkeypatch):
        _calendario(monkeypatch, [], {"error": "No autenticado"})
        r = main._j_huecos_libres(dia=MANANA)
        assert r["ok"] is False
        assert "huecos" not in r
        assert "clases" in r["dile_al_usuario_literalmente"]

    def test_todo_el_dia_no_bloquea_y_se_cuenta(self, monkeypatch):
        # Graph da los de todo el día a medianoche UTC: en hora local, las 02:00.
        cumple = {"id": "c", "title": "Cumpleaños de Ane", "isAllDay": True,
                  "start": f"{MANANA}T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
        otro   = {"id": "o", "title": "Otro día", "isAllDay": True,
                  "start": "2026-09-29T00:00:00Z", "end": "2026-09-30T00:00:00Z"}
        _calendario(monkeypatch, [cumple, otro], [])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["todo_el_dia"] == ["Cumpleaños de Ane"]
        assert r["huecos"] == [{"desde": "08:00", "hasta": "22:00", "minutos": 840}]

    def test_una_clase_bloquea_su_tramo_con_margen(self, monkeypatch):
        _calendario(monkeypatch, [], [_ev("Cálculo", MANANA, "09:00", "11:00")])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["huecos"] == [
            {"desde": "08:00", "hasta": "08:50", "minutos": 50},
            {"desde": "11:10", "hasta": "22:00", "minutos": 650},
        ]
        assert r["ocupado"] == [{"titulo": "Cálculo", "desde": "09:00", "hasta": "11:00"}]
        assert r["limites"] == {"inicio": "fijo", "fin": "fijo", "hora_habitual_dormir": None}

    def test_lo_que_viene_de_la_noche_anterior_sale_desde_medianoche(self, monkeypatch):
        _calendario(monkeypatch, [_ev("Fiesta", HOY, "23:00", "02:00", dia_fin=MANANA)], [])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["ocupado"] == [{"titulo": "Fiesta", "desde": "00:00", "hasta": "02:00"}]

    def test_el_fin_aprendido_se_dice(self, monkeypatch):
        monkeypatch.setattr(main, "_hora_habitual_dormir", lambda: (0, 15))
        _calendario(monkeypatch, [], [])
        r = main._j_huecos_libres(dia=MANANA)
        assert r["hasta"] == "23:15"
        assert r["limites"]["fin"] == "aprendido"
        assert r["limites"]["hora_habitual_dormir"] == "00:15"

    def test_con_hasta_pedido_no_consulta_la_hora_de_dormir(self, monkeypatch):
        def _no_llamar():
            raise AssertionError("no hace falta: el fin ya viene pedido")
        monkeypatch.setattr(main, "_hora_habitual_dormir", _no_llamar)
        _calendario(monkeypatch, [], [])
        r = main._j_huecos_libres(dia=MANANA, desde="16:00", hasta="20:00")
        assert (r["desde"], r["hasta"]) == ("16:00", "20:00")
        assert r["limites"]["inicio"] == r["limites"]["fin"] == "pedido"

    def test_hoy_empieza_ahora(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        r = main._j_huecos_libres()
        assert r["dia"] == HOY
        assert r["desde"] == "10:15"
        assert r["limites"]["inicio"] == "ahora"

    def test_sin_huecos_lo_dice(self, monkeypatch):
        _calendario(monkeypatch, [_ev("Congreso", MANANA, "07:00", "23:00")], [])
        r = main._j_huecos_libres(dia=MANANA, duracion_min=60)
        assert r["ok"] is True
        assert r["huecos"] == []
        assert r["sin_huecos"] == "No tienes ningún hueco de 60 min entre 08:00 y 22:00."

    @pytest.mark.parametrize("dia,motivo", [
        ("2026-09-26", "Ese día ya ha pasado"),
        ("2026-10-12", "Solo miro hasta dentro de 14 días"),
        ("2026-02-30", "Esa fecha no existe"),
        ("mañana", "La fecha no tiene formato YYYY-MM-DD"),
    ])
    def test_rechaza_dias_que_no_toca_mirar(self, monkeypatch, dia, motivo):
        _calendario(monkeypatch, [], [])
        assert main._j_huecos_libres(dia=dia) == {"ok": False, "motivo": motivo}

    def test_dentro_de_catorce_dias_si(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        assert main._j_huecos_libres(dia="2026-10-11")["ok"] is True

    def test_horas_pedidas_invalidas(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        assert main._j_huecos_libres(dia=MANANA, desde="25:00")["ok"] is False
        r = main._j_huecos_libres(dia=MANANA, desde="18:00", hasta="17:00")
        assert r == {"ok": False,
                     "motivo": "La hora de fin tiene que ser posterior a la de inicio"}

    def test_dia_de_la_semana_en_espanol(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        assert main._j_huecos_libres(dia=MANANA)["dia_semana"] == "lunes"
        assert main._j_huecos_libres(dia="2026-10-03")["dia_semana"] == "sábado"

    def test_la_duracion_se_acota(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        assert main._j_huecos_libres(dia=MANANA, duracion_min=5)["duracion_min"] == 15
        assert main._j_huecos_libres(dia=MANANA, duracion_min=9999)["duracion_min"] == 480
        assert main._j_huecos_libres(dia=MANANA, duracion_min="un rato")["duracion_min"] == 30

    def test_como_mucho_doce_huecos(self, monkeypatch):
        # Cinco minutos ocupados cada hora: catorce huecos en el día.
        eventos = [_ev(f"Aviso {h}", MANANA, f"{h:02d}:00", f"{h:02d}:05") for h in range(8, 22)]
        _calendario(monkeypatch, eventos, [])
        r = main._j_huecos_libres(dia=MANANA, duracion_min=15)
        assert len(r["huecos"]) == 12

    def test_por_la_herramienta_sus_argumentos(self, monkeypatch):
        """El registro la declara de consulta: el modelo la usa sin pedir permiso."""
        h = main._JARVIS_HERRAMIENTAS["huecos_libres"]
        assert h["confirmar"] is False
        assert set(h["parametros"]) == {"dia", "duracion_min", "desde", "hasta"}
        assert h["obligatorios"] == []
        assert main._relleno_herramienta("huecos_libres") == "Miro dónde tienes hueco."


# ── reservar_bloques: la puerta de confirmación ───────────────────────────────

def _bloque(titulo, ini, fin, fecha=MANANA):
    return {"titulo": titulo, "fecha": fecha, "hora_inicio": ini, "hora_fin": fin}


class TestReservarPuerta:
    def test_el_registro_la_declara_confirmable_con_una_lista(self):
        h = main._JARVIS_HERRAMIENTAS["reservar_bloques"]
        assert h["confirmar"] is True
        assert h["obligatorios"] == ["bloques"]
        assert h["parametros"]["bloques"]["type"] == "array"
        assert h["parametros"]["bloques"]["maxItems"] == 6
        assert h["parametros"]["bloques"]["items"]["type"] == "object"
        # Las confirmables no se anuncian en voz: no se está haciendo nada todavía.
        assert "reservar_bloques" not in main._JARVIS_RELLENOS

    def test_proponerla_no_crea_nada(self, client, auth_headers, monkeypatch):
        from test_jarvis import _con_modelo, _llamada, _mensaje

        def _no_llamar(*a, **k):
            raise AssertionError("no debería crearse nada sin confirmar")

        monkeypatch.setattr(main, "create_event", _no_llamar)
        bloques = [_bloque("TFG", "09:00", "11:00"), _bloque("Gimnasio", "18:00", "19:00")]
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("reservar_bloques", {"bloques": bloques})]),
            _mensaje("Te propongo estos dos bloques."),
        ])
        r = client.post("/jarvis", json={"mensaje": "bloquéame mañana"}, headers=auth_headers)
        datos = r.json()
        assert datos["pendiente"]["herramienta"] == "reservar_bloques"
        assert datos["pendiente"]["argumentos"]["bloques"] == bloques
        assert datos["herramientas"] == []

    def test_ejecutar_los_crea(self, client, auth_headers, monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "reservar_bloques",
            "argumentos": {"bloques": [_bloque("TFG", "09:00", "11:00"),
                                       _bloque("Gimnasio", "18:00", "19:00")]},
        })
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["ok"] is True
        assert [c.subject for c in creados] == ["TFG", "Gimnasio"]
        assert creados[0].start == f"{MANANA}T09:00:00"
        assert creados[0].end == f"{MANANA}T11:00:00"
        assert cuerpo["resultado"]["dile_al_usuario_literalmente"] == (
            "Reservado: «TFG» de 9:00 a 11:00 y «Gimnasio» de 18:00 a 19:00.")

    def test_un_argumento_de_mas_no_llega_a_la_funcion(self, client, auth_headers,
                                                        monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "reservar_bloques",
            "argumentos": {"bloques": [_bloque("TFG", "09:00", "11:00")],
                           "credentials": "robado", "forzar": True},
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert len(creados) == 1


# ── reservar_bloques: lo que pasa al confirmar ────────────────────────────────

class TestReservarAlEjecutar:
    def test_lo_que_entro_despues_se_rechaza_y_el_resto_se_crea(self, monkeypatch, creados):
        _calendario(monkeypatch, [_ev("Reunión", MANANA, "17:00", "18:00")], [])
        r = main._j_reservar_bloques([
            _bloque("TFG", "09:00", "11:00"),
            # Empieza cuando acaba la reunión: tocarse no es chocar.
            _bloque("Gimnasio", "18:00", "19:00"),
            _bloque("Compra", "16:30", "17:30"),
        ])
        assert r["ok"] is True
        assert [c["titulo"] for c in r["creados"]] == ["TFG", "Gimnasio"]
        assert r["rechazados"] == [{"titulo": "Compra", "fecha": MANANA, "hora_inicio": "16:30",
                                    "motivo": "Choca con «Reunión» (17:00–18:00)"}]
        assert r["dile_al_usuario_literalmente"] == (
            "He reservado 2 de 3: «TFG» y «Gimnasio». «Compra» no: choca con «Reunión» "
            "(17:00–18:00).")
        assert [c.subject for c in creados] == ["TFG", "Gimnasio"]

    def test_confirmar_dos_veces_no_duplica(self, monkeypatch, creados):
        _calendario(monkeypatch, [_ev("TFG", MANANA, "09:00", "11:00")], [])
        r = main._j_reservar_bloques([_bloque("tfg", "09:00", "11:00")])
        assert r["ok"] is False
        assert r["rechazados"][0]["motivo"] == "Ya estaba reservado"
        assert r["motivo"] == r["dile_al_usuario_literalmente"]
        assert creados == []

    def test_una_clase_tambien_cuenta_como_choque(self, monkeypatch, creados):
        _calendario(monkeypatch, [], [_ev("Clase de Cálculo", MANANA, "09:00", "11:00")])
        r = main._j_reservar_bloques([_bloque("TFG", "10:00", "12:00")])
        assert r["ok"] is False
        assert r["motivo"] == ("No he reservado nada: «TFG» choca con «Clase de Cálculo» "
                               "(09:00–11:00).")
        assert creados == []

    def test_los_de_todo_el_dia_no_chocan(self, monkeypatch, creados):
        festivo = {"id": "f", "title": "Festivo", "isAllDay": True,
                   "start": f"{MANANA}T00:00:00Z", "end": "2026-09-29T00:00:00Z"}
        _calendario(monkeypatch, [festivo], [])
        assert main._j_reservar_bloques([_bloque("TFG", "09:00", "11:00")])["ok"] is True

    @pytest.mark.parametrize("fallo", [{"error": "No autenticado"}, TimeoutError("sin red")])
    def test_si_no_se_puede_mirar_el_calendario_no_se_crea_nada(self, monkeypatch, creados,
                                                                 fallo):
        _calendario(monkeypatch, fallo, [])
        r = main._j_reservar_bloques([_bloque("TFG", "09:00", "11:00"),
                                      _bloque("Gimnasio", "18:00", "19:00")])
        assert r["ok"] is False
        assert r["motivo"] == ("No he podido mirar el calendario para comprobar choques, así "
                               "que no he reservado nada.")
        assert r["creados"] == []
        assert len(r["rechazados"]) == 2
        assert creados == []

    def test_mas_de_seis_no_crea_ninguno(self, monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        bloques = [_bloque(f"B{i}", f"{8 + i:02d}:00", f"{8 + i:02d}:30") for i in range(7)]
        r = main._j_reservar_bloques(bloques)
        assert r == {"ok": False, "motivo": "Como mucho reservo 6 bloques de una vez"}
        assert creados == []

    @pytest.mark.parametrize("bloques", [None, [], "TFG de 9 a 11", {"titulo": "TFG"}])
    def test_sin_lista_no_hay_nada_que_reservar(self, bloques, creados):
        assert main._j_reservar_bloques(bloques) == {"ok": False,
                                                     "motivo": "No hay bloques que reservar"}

    def test_dos_bloques_de_la_lista_que_se_pisan(self, monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        r = main._j_reservar_bloques([_bloque("TFG", "09:00", "11:00"),
                                      _bloque("Lectura", "10:30", "11:30")])
        assert [c["titulo"] for c in r["creados"]] == ["TFG"]
        assert r["rechazados"][0]["motivo"] == "Se pisa con «TFG»"

    @pytest.mark.parametrize("bloque,motivo", [
        (_bloque("TFG", "11:00", "11:00"), "La hora de fin tiene que ser posterior a la de inicio"),
        (_bloque("TFG", "11:00", "10:00"), "La hora de fin tiene que ser posterior a la de inicio"),
        (_bloque("TFG", "08:00", "17:00"), "Un bloque no puede durar más de 8 horas"),
        (_bloque("TFG", "09:00", "10:00", fecha=HOY), "Esa hora ya ha pasado"),
        (_bloque("   ", "09:00", "10:00"), "Falta el título"),
        (_bloque("TFG", "9:00", "10:00"), "La hora no tiene formato HH:MM (24h)"),
        (_bloque("TFG", "09:00", ""), "Faltan la hora de inicio y la de fin"),
        (_bloque("TFG", "09:00", "10:00", fecha="2026-02-30"), "Esa fecha no existe"),
        (_bloque("TFG", "09:00", "10:00", fecha="2026-09-26"), "Ese día ya ha pasado"),
        (_bloque("TFG", "09:00", "10:00", fecha="2026-10-12"), "Solo reservo hasta dentro de 14 días"),
    ])
    def test_bloques_invalidos(self, monkeypatch, creados, bloque, motivo):
        _calendario(monkeypatch, [], [])
        r = main._j_reservar_bloques([bloque])
        assert r["ok"] is False
        assert r["rechazados"][0]["motivo"] == motivo
        assert creados == []

    def test_un_bloque_invalido_no_tumba_a_los_demas(self, monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        r = main._j_reservar_bloques([_bloque("", "09:00", "10:00"),
                                      _bloque("Gimnasio", "18:00", "19:00")])
        assert r["ok"] is True
        assert [c.subject for c in creados] == ["Gimnasio"]
        assert r["rechazados"][0]["titulo"] == "(sin título)"

    def test_hoy_mas_tarde_si_se_puede(self, monkeypatch, creados):
        _calendario(monkeypatch, [], [])
        assert main._j_reservar_bloques([_bloque("TFG", "16:00", "18:00", fecha=HOY)])["ok"]

    def test_si_graph_falla_en_uno_se_siguen_creando_los_demas(self, monkeypatch):
        _calendario(monkeypatch, [], [])
        llamadas = []

        def _crear(body, credentials=None):
            llamadas.append(body.subject)
            if body.subject == "Compra":
                return {"error": "No se pudo crear el evento en Outlook"}
            return {"status": "ok", "id": f"id-{body.subject}"}

        monkeypatch.setattr(main, "create_event", _crear)
        r = main._j_reservar_bloques([_bloque("TFG", "09:00", "11:00"),
                                      _bloque("Compra", "12:00", "13:00"),
                                      _bloque("Gimnasio", "18:00", "19:00")])
        assert llamadas == ["TFG", "Compra", "Gimnasio"]
        assert r["ok"] is True
        assert [(c["titulo"], c["id"]) for c in r["creados"]] == [
            ("TFG", "id-TFG"), ("Gimnasio", "id-Gimnasio")]
        assert r["rechazados"] == [{"titulo": "Compra", "fecha": MANANA, "hora_inicio": "12:00",
                                    "motivo": "No se pudo crear el evento en Outlook"}]
        assert "«Compra» no" in r["dile_al_usuario_literalmente"]

    def test_una_excepcion_al_crear_tampoco_corta_la_serie(self, monkeypatch):
        _calendario(monkeypatch, [], [])

        def _crear(body, credentials=None):
            if body.subject == "TFG":
                raise TimeoutError("Graph no contesta")
            return {"status": "ok", "id": "x"}

        monkeypatch.setattr(main, "create_event", _crear)
        r = main._j_reservar_bloques([_bloque("TFG", "09:00", "11:00"),
                                      _bloque("Gimnasio", "18:00", "19:00")])
        assert [c["titulo"] for c in r["creados"]] == ["Gimnasio"]
        assert r["rechazados"][0]["titulo"] == "TFG"


# ── _frase_reserva ────────────────────────────────────────────────────────────

def _creado(titulo, ini, fin):
    return {"titulo": titulo, "fecha": MANANA, "hora_inicio": ini, "hora_fin": fin, "id": "x"}


def _rechazado(titulo, motivo):
    return {"titulo": titulo, "fecha": MANANA, "hora_inicio": "17:00", "motivo": motivo}


class TestFraseReserva:
    def test_todo_bien(self):
        assert main._frase_reserva(
            [_creado("TFG", "09:00", "11:00"), _creado("Gimnasio", "18:00", "19:00")], []
        ) == "Reservado: «TFG» de 9:00 a 11:00 y «Gimnasio» de 18:00 a 19:00."

    def test_parcial(self):
        assert main._frase_reserva(
            [_creado("TFG", "09:00", "11:00"), _creado("Gimnasio", "18:00", "19:00")],
            [_rechazado("Compra", "Choca con «Reunión» (17:00–18:00)")],
        ) == ("He reservado 2 de 3: «TFG» y «Gimnasio». «Compra» no: choca con «Reunión» "
              "(17:00–18:00).")

    def test_nada(self):
        assert main._frase_reserva(
            [], [_rechazado("TFG", "Choca con «Clase de Cálculo» (09:00–11:00)")]
        ) == "No he reservado nada: «TFG» choca con «Clase de Cálculo» (09:00–11:00)."

    def test_se_puede_decir_en_voz_alta(self):
        frase = main._frase_reserva(
            [_creado("A", "08:00", "09:00"), _creado("B", "10:00", "11:00"),
             _creado("C", "12:00", "13:00")], [])
        assert frase == "Reservado: «A» de 8:00 a 9:00, «B» de 10:00 a 11:00 y «C» de 12:00 a 13:00."
        assert not any(c in frase for c in "*_`#[]\n")


# ── El MCP del teléfono ───────────────────────────────────────────────────────

class TestTelefono:
    TOKEN = {"Authorization": "Bearer mcp-telefono-token"}

    @pytest.fixture(autouse=True)
    def _configurado(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")

    def _sesion(self, client):
        r = client.post("/mcp/telefono", headers=self.TOKEN, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}}})
        return r.headers["mcp-session-id"]

    def test_huecos_si_reservar_no(self, client):
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono", headers={**self.TOKEN, "Mcp-Session-Id": sesion},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        por_nombre = {t["name"]: t for t in r.json()["result"]["tools"]}
        assert por_nombre["huecos_libres"]["annotations"]["readOnlyHint"] is True
        assert "reservar_bloques" not in por_nombre

    def test_reservar_por_telefono_da_error(self, client, monkeypatch):
        llamado = []
        monkeypatch.setattr(main, "_jarvis_despachar", lambda *a, **k: llamado.append(a) or {})
        sesion = self._sesion(client)
        r = client.post("/mcp/telefono", headers={**self.TOKEN, "Mcp-Session-Id": sesion},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "reservar_bloques",
                                         "arguments": {"bloques": [_bloque("TFG", "09:00",
                                                                           "11:00")]}}})
        assert "error" in r.json()
        assert not llamado

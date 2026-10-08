"""Moodle: las entregas pendientes, llevadas al calendario y con aviso si vencen pronto.

Las respuestas simuladas de Moodle copian la forma real de
`core_calendar_get_action_events_by_timesort` (`events` → `course`, `action`, `url`,
`timesort`), no una cómoda: si la API cambia, es aquí donde tiene que notarse.
"""
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import pytest

import main
from conftest import FakeResponse

HOST = main.ALUD_ALLOWED_HOSTS[0]


def _evento(mid, horas, nombre="Práctica 1", curso="Redes", url=None):
    return {
        "id": mid, "name": f"{nombre} vence", "activityname": nombre,
        "modulename": "assign", "eventtype": "due",
        "timestart": int(time.time() + horas * 3600),
        "timesort":  int(time.time() + horas * 3600),
        "course": {"id": 7, "fullname": curso, "shortname": "RED"},
        "action": {"name": "Añadir entrega", "url": f"https://{HOST}/mod/assign/view.php?id={mid}&action=editsubmission",
                   "actionable": True},
        "url": url if url is not None else f"https://{HOST}/mod/assign/view.php?id={mid}",
    }


def _iso(horas):
    return datetime.fromtimestamp(int(time.time() + horas * 3600), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def moodle(monkeypatch, mock_requests, graph_token):
    """Moodle y Outlook configurados, calendario de clases vacío y sin nada guardado."""
    monkeypatch.setattr(main, "MOODLE_URL", "https://moodle.test")
    monkeypatch.setattr(main, "MOODLE_TOKEN", "moodle-token")
    monkeypatch.setattr(main, "MOODLE_AL_CALENDARIO", True)
    monkeypatch.setattr(main, "REGLAS_PROACTIVAS", True)
    monkeypatch.setattr(main, "_id_calendario_clases", lambda h: ("cal-clases", None, False))
    estado = {"eventos": [], "clases": [], "guardadas": [], "upserts": [], "avisos": []}
    monkeypatch.setattr(main, "get_class_events", lambda credentials=None: {"events": estado["clases"]})
    monkeypatch.setattr(main, "_apuntar_aviso",
                        lambda regla, texto, **kw: estado["avisos"].append((regla, texto, kw)) or True)
    mock_requests.add("POST", "moodle.test/webservice/rest/server.php",
                      lambda url, **kw: FakeResponse({"events": estado["eventos"]}))
    mock_requests.add("GET", "moodle_entregas", lambda url, **kw: FakeResponse(estado["guardadas"]))
    mock_requests.add("POST", "moodle_entregas",
                      lambda url, **kw: estado["upserts"].extend(kw["json"]) or FakeResponse(None, 201))
    mock_requests.add("POST", "/calendars/cal-clases/events", FakeResponse({"id": "ev-nuevo"}, 201))
    mock_requests.add("PATCH", "/me/events/", FakeResponse({}, 200))
    return estado


class TestCliente:
    def test_el_token_va_en_el_cuerpo_y_nunca_en_la_url(self, moodle, mock_requests):
        main._moodle_entregas()
        metodo, url, kw = mock_requests.called("POST", "server.php")[0]
        assert "moodle-token" not in url and "wstoken" not in url
        assert kw["data"]["wstoken"] == "moodle-token"
        assert kw["data"]["wsfunction"] == "core_calendar_get_action_events_by_timesort"

    def test_sin_configurar_no_llama_a_nadie(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "MOODLE_TOKEN", "")
        with pytest.raises(main.MoodleApagado):
            main._moodle_entregas()
        assert not mock_requests.calls

    def test_acepta_la_url_del_servicio_entera(self, moodle, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "MOODLE_URL", "https://moodle.test/webservice/rest/server.php")
        main._moodle_entregas()
        assert mock_requests.called("POST", "server.php")[0][1] == "https://moodle.test/webservice/rest/server.php"

    def test_un_token_rechazado_dice_que_hacer(self, moodle, mock_requests):
        mock_requests.routes.insert(0, ("POST", "server.php", FakeResponse(
            {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Token no válido"})))
        with pytest.raises(main.MoodleApagado, match="MOODLE_TOKEN"):
            main._moodle_entregas()

    def test_una_respuesta_sin_lista_no_pasa_por_lista_vacia(self, moodle, mock_requests):
        # Si se tomara por «no hay entregas», la pasada tacharía todas las guardadas.
        mock_requests.routes.insert(0, ("POST", "server.php", FakeResponse({"warnings": []})))
        with pytest.raises(main.MoodleApagado):
            main._moodle_entregas()

    def test_normaliza_lo_que_escribe_el_profesorado(self):
        ev = _evento(5, 10, nombre="Diseño &amp; pruebas", url="http://inseguro.test/x")
        e = main._moodle_entrega(ev)
        assert e["nombre"] == "Diseño & pruebas"
        assert e["vence"].endswith("Z") and e["vencida"] is False
        # La de `url` no es https: cae a la de la acción, que sí lo es.
        assert e["url"].startswith("https://")
        assert main._moodle_entrega({"id": "x"}) is None
        assert main._moodle_entrega("basura") is None


class TestEndpoints:
    def test_sin_configurar_responde_apagado(self, client, auth_headers, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "MOODLE_URL", "")
        r = client.get("/moodle/entregas", headers=auth_headers)
        assert r.status_code == 200 and r.json()["activo"] is False and r.json()["entregas"] == []

    def test_lista_la_que_vence_antes_primero(self, client, auth_headers, moodle):
        moodle["eventos"] = [_evento(2, 50, "B"), _evento(1, 5, "A")]
        r = client.get("/moodle/entregas", headers=auth_headers).json()
        assert [e["nombre"] for e in r["entregas"]] == ["A", "B"]

    def test_pide_sesion(self, client):
        assert client.get("/moodle/entregas").status_code in (401, 403)
        assert client.post("/moodle/sincronizar").status_code in (401, 403)

    def test_sincronizar_a_mano(self, client, auth_headers, moodle):
        moodle["eventos"] = [_evento(1, 100)]
        r = client.post("/moodle/sincronizar", headers=auth_headers).json()
        assert r["ok"] is True and r["nuevas"] == 1 and r["al_calendario"] == 1


class TestSincronizar:
    def test_una_nueva_se_crea_en_el_calendario_de_clases(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        r = main._moodle_sincronizar()
        assert r["nuevas"] == 1 and r["al_calendario"] == 1
        cuerpo = mock_requests.called("POST", "/calendars/cal-clases/events")[0][2]["json"]
        assert cuerpo["subject"].startswith(main.ENTREGAS_MARKER)
        assert "Práctica 1 (Redes)" in cuerpo["subject"]
        # alud_url: es lo que enciende el botón de resolver con el agente.
        assert f"alud_url: https://{HOST}/mod/assign/view.php?id=1" in cuerpo["body"]["content"]
        assert "moodle_id: 1" in cuerpo["body"]["content"]
        assert moodle["upserts"][0]["outlook_id"] == "ev-nuevo"
        assert moodle["upserts"][0]["estado"] == "pendiente"

    def test_el_evento_termina_a_la_hora_de_entrega(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        main._moodle_sincronizar()
        cuerpo = mock_requests.called("POST", "/calendars/cal-clases/events")[0][2]["json"]
        fin = datetime.fromtimestamp(moodle["eventos"][0]["timesort"], timezone.utc).astimezone(main.LOCAL_TZ)
        assert cuerpo["end"]["dateTime"] == fin.strftime("%Y-%m-%dT%H:%M:%S")
        assert cuerpo["showAs"] == "free"

    def test_la_url_de_un_host_ajeno_no_va_como_alud_url(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "ALUD_ALLOWED_HOSTS", ("otro.test",))
        moodle["eventos"] = [_evento(1, 100)]
        main._moodle_sincronizar()
        cuerpo = mock_requests.called("POST", "/calendars/cal-clases/events")[0][2]["json"]
        assert "alud_url:" not in cuerpo["body"]["content"]
        assert "Moodle: https://" in cuerpo["body"]["content"]

    def test_adopta_la_que_ya_metio_la_rutina_de_alud(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        moodle["clases"] = [{"id": "ev-viejo", "title": f"{main.ENTREGAS_MARKER} Práctica 1",
                             "start": _iso(99), "preview": "",
                             "alud_url": f"https://{HOST}/mod/assign/view.php?id=1"}]
        main._moodle_sincronizar()
        assert not mock_requests.called("POST", "/calendars/cal-clases/events")
        assert mock_requests.called("PATCH", "/me/events/ev-viejo")
        assert moodle["upserts"][0]["outlook_id"] == "ev-viejo"

    def test_reconoce_las_suyas_aunque_se_pierda_la_tabla(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        moodle["clases"] = [{"id": "ev-otro", "title": f"{main.ENTREGAS_MARKER} Práctica 1",
                             "start": _iso(99), "preview": "moodle_id: 2"},
                            {"id": "ev-mio", "title": f"{main.ENTREGAS_MARKER} Otra cosa",
                             "start": _iso(9), "preview": "Moodle: x\nmoodle_id: 1"}]
        main._moodle_sincronizar()
        assert moodle["upserts"][0]["outlook_id"] == "ev-mio"

    def test_sin_leer_el_calendario_no_crea_a_ciegas(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "get_class_events", lambda credentials=None: {"error": "Graph caído"})
        moodle["eventos"] = [_evento(1, 100)]
        main._moodle_sincronizar()
        assert not mock_requests.called("POST", "/calendars/cal-clases/events")
        # Se guarda igual, sin evento: la siguiente pasada lo vuelve a intentar.
        assert moodle["upserts"][0]["outlook_id"] is None

    def test_sin_outlook_se_guarda_y_se_reintenta(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        moodle["eventos"] = [_evento(1, 100)]
        r = main._moodle_sincronizar()
        assert r["al_calendario"] == 0 and moodle["upserts"][0]["outlook_id"] is None

    def test_lo_que_no_ha_cambiado_no_se_toca(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        e = main._moodle_entrega(moodle["eventos"][0])
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        r = main._moodle_sincronizar()
        assert r["nuevas"] == 0 and not moodle["upserts"]
        assert not mock_requests.called("PATCH", "/me/events/")

    def test_una_fecha_movida_en_moodle_mueve_el_evento(self, moodle, mock_requests):
        moodle["eventos"] = [_evento(1, 100)]
        e = main._moodle_entrega(moodle["eventos"][0])
        moodle["guardadas"] = [{**main._moodle_fila(e, "ev-1", "pendiente"), "vence": _iso(50)}]
        r = main._moodle_sincronizar()
        assert r["movidas"] == 1
        cuerpo = mock_requests.called("PATCH", "/me/events/ev-1")[0][2]["json"]
        assert "start" in cuerpo and cuerpo["subject"].startswith(main.ENTREGAS_MARKER)

    def test_la_que_desaparece_pasa_a_entregada(self, moodle, mock_requests):
        e = main._moodle_entrega(_evento(1, 20))
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        r = main._moodle_sincronizar()
        assert r["entregadas"] == 1
        cuerpo = mock_requests.called("PATCH", "/me/events/ev-1")[0][2]["json"]
        assert cuerpo == {"subject": f"{main.MOODLE_HECHA} Práctica 1 (Redes)"}
        assert moodle["upserts"][0]["estado"] == "entregada"

    def test_con_la_lista_cortada_no_se_tacha_nada(self, moodle, mock_requests):
        # 50 resultados = el tope de Moodle: la que falta puede estar en la página siguiente.
        moodle["eventos"] = [_evento(100 + i, 10 + i) for i in range(main.MOODLE_LIMITE)]
        e = main._moodle_entrega(_evento(1, 200))
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        main._moodle_sincronizar()
        assert not mock_requests.called("PATCH", "/me/events/ev-1")
        assert all(f["moodle_id"] != 1 for f in moodle["upserts"])

    def test_la_que_se_sale_de_la_ventana_no_se_tacha(self, moodle, mock_requests):
        e = main._moodle_entrega(_evento(1, -24 * (main.MOODLE_VENCIDAS_DIAS + 1)))
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        main._moodle_sincronizar()
        assert not mock_requests.called("PATCH", "/me/events/ev-1")
        assert moodle["upserts"][0]["estado"] == "fuera"

    def test_el_evento_que_borraste_no_vuelve(self, moodle, mock_requests):
        mock_requests.routes.insert(0, ("PATCH", "/me/events/ev-1", FakeResponse({}, 404)))
        moodle["eventos"] = [_evento(1, 100)]
        e = main._moodle_entrega(moodle["eventos"][0])
        moodle["guardadas"] = [{**main._moodle_fila(e, "ev-1", "pendiente"), "vence": _iso(50)}]
        main._moodle_sincronizar()
        assert not mock_requests.called("POST", "/calendars/cal-clases/events")
        assert moodle["upserts"][0]["outlook_id"] == main.MOODLE_SIN_EVENTO
        # Y en la pasada siguiente, tampoco.
        moodle["guardadas"], moodle["upserts"] = [moodle["upserts"][0]], []
        main._moodle_sincronizar()
        assert not mock_requests.called("POST", "/calendars/cal-clases/events")

    def test_sin_calendario_solo_consulta(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "MOODLE_AL_CALENDARIO", False)
        moodle["eventos"] = [_evento(1, 100)]
        r = main._moodle_sincronizar()
        assert r["nuevas"] == 1 and not mock_requests.called("POST", "/calendars/")


class TestAvisos:
    def test_la_primera_vez_es_un_solo_aviso(self, moodle):
        moodle["eventos"] = [_evento(i, 100 + i, f"Tarea {i}") for i in range(1, 9)]
        main._moodle_sincronizar()
        assert len(moodle["avisos"]) == 1
        regla, texto, kw = moodle["avisos"][0]
        assert regla == main.REGLA_MOODLE_NUEVA and "8 entregas" in texto
        assert kw["prioridad"] == main.PRIO_BAJA

    def test_una_nueva_despues_avisa_con_su_nombre(self, moodle):
        viejo = main._moodle_entrega(_evento(1, 200))
        moodle["guardadas"] = [main._moodle_fila(viejo, "ev-1", "pendiente")]
        moodle["eventos"] = [_evento(1, 200), _evento(2, 100, "Memoria final", "TFG")]
        main._moodle_sincronizar()
        (regla, texto, _), = moodle["avisos"]
        assert regla == main.REGLA_MOODLE_NUEVA and "«Memoria final» (TFG)" in texto

    def test_la_que_vence_pronto_avisa_alto(self, moodle):
        e = main._moodle_entrega(_evento(1, 20))
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        moodle["eventos"] = [_evento(1, 20)]
        main._moodle_sincronizar()
        (regla, texto, kw), = moodle["avisos"]
        assert regla == main.REGLA_MOODLE_VENCE and "sigue sin entregar" in texto
        assert kw["prioridad"] == main.PRIO_ALTA
        assert kw["huella"] == main._huella_moodle_vence(1, e["vence"])

    def test_una_nueva_que_vence_pronto_no_avisa_dos_veces(self, moodle):
        moodle["guardadas"] = [main._moodle_fila(main._moodle_entrega(_evento(9, 300)), "ev-9", "pendiente")]
        moodle["eventos"] = [_evento(9, 300), _evento(1, 20)]
        main._moodle_sincronizar()
        (regla, texto, _), = moodle["avisos"]
        assert regla == main.REGLA_MOODLE_VENCE and texto.startswith("Nueva en Moodle")

    def test_las_ya_vencidas_no_avisan_de_que_vencen(self, moodle):
        e = main._moodle_entrega(_evento(1, -5))
        moodle["guardadas"] = [main._moodle_fila(e, "ev-1", "pendiente")]
        moodle["eventos"] = [_evento(1, -5)]
        main._moodle_sincronizar()
        assert moodle["avisos"] == []

    def test_sin_reglas_proactivas_sincroniza_y_calla(self, moodle, monkeypatch):
        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", False)
        moodle["eventos"] = [_evento(1, 20)]
        r = main._moodle_sincronizar()
        assert r["al_calendario"] == 1 and moodle["avisos"] == []

    def test_al_salir_de_la_uni_no_repite_lo_que_dijo_moodle(self, monkeypatch):
        fin = _iso(20)
        ev = {"id": "ev-1", "title": f"{main.ENTREGAS_MARKER} Práctica 1", "dias": 1,
              "preview": "alud_url: x\nmoodle_id: 1", "end": fin}
        monkeypatch.setattr(main, "_entregas_proximas", lambda: [ev])
        dichos = {(main.REGLA_MOODLE_VENCE, main._huella_moodle_vence(1, fin))}
        monkeypatch.setattr(main, "_ya_dicho", lambda regla, huella: (regla, huella) in dichos)
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso", lambda *a, **k: avisos.append(a) or True)
        assert main._regla_entregas_al_salir() == 0 and avisos == []


class TestTick:
    def test_pregunta_como_mucho_cada_media_hora(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_moodle_ultima", {"ts": 0.0})
        moodle["eventos"] = [_evento(1, 100)]
        assert "moodle" in main._moodle_tick_seguro()
        assert main._moodle_tick_seguro() == {}
        assert len(mock_requests.called("POST", "server.php")) == 1

    def test_un_moodle_caido_no_tumba_el_tick(self, moodle, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_moodle_ultima", {"ts": 0.0})
        mock_requests.routes.insert(0, ("POST", "server.php", FakeResponse({}, 503)))
        assert main._moodle_tick_seguro() == {}

    def test_sin_configurar_ni_pregunta(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "MOODLE_TOKEN", "")
        monkeypatch.setattr(main, "_moodle_ultima", {"ts": 0.0})
        assert main._moodle_tick_seguro() == {} and not mock_requests.calls


class TestJarvis:
    def test_sin_moodle_no_se_anuncia(self, monkeypatch):
        monkeypatch.setattr(main, "MOODLE_TOKEN", "")
        nombres = {f["function"]["name"] for f in main._jarvis_esquema()}
        assert "moodle_entregas" not in nombres

    def test_con_moodle_se_anuncia_y_va_como_dato(self, moodle):
        nombres = {f["function"]["name"] for f in main._jarvis_esquema()}
        assert "moodle_entregas" in nombres
        moodle["eventos"] = [_evento(1, 10)]
        r = main._jarvis_despachar("moodle_entregas", {})
        assert r["activo"] and r["aviso"] == main._AVISO_WEB and r["entregas"][0]["id"] == 1

    def test_esta_en_el_mcp_del_telefono(self):
        assert "moodle_entregas" in main._MCP_SERVIDOR_SOLO_LECTURA


# ── El widget Uni ──
# Cursos inventados con la forma de `core_enrol_get_users_courses`: Moodle devuelve los de
# todos los años, la mayoría con `enddate` a 0 y `progress` a null.
HACE = lambda dias: int(time.time() - dias * 86400)  # noqa: E731


def _curso(cid, nombre, empezo_hace=120, fin=0, progreso=None, oculto=False):
    return {"id": cid, "fullname": nombre, "shortname": nombre[:20], "startdate": HACE(empezo_hace),
            "enddate": fin, "progress": progreso, "hidden": oculto}


@pytest.fixture
def uni(moodle, mock_requests):
    datos = {
        "cursos": [
            _curso(1, "2026-27 Óptica Aplicada (es)(12)"),
            _curso(2, "2026-27 Física (Mecánica clásica) (en)(40)", progreso=37.5),
            _curso(3, "2024-25 Geología (en)(7,21)", empezo_hace=800),            # de otro curso
            _curso(4, "2025-26 Botánica [CLOSED] (en)(7)", empezo_hace=200, fin=HACE(30)),  # terminada
            _curso(5, "2026-27 Oculta", oculto=True),
        ],
        "notas": {"grades": [{"courseid": 1, "grade": "7,50"}, {"courseid": 2, "grade": "-"},
                             {"courseid": 3, "grade": "61,40"}]},
        "fallan": set(),
    }

    def responder(url, **kw):
        funcion = kw["data"]["wsfunction"]
        if funcion in datos["fallan"]:
            return FakeResponse({"exception": "x", "errorcode": "nopermissions"})
        return FakeResponse({
            "core_webservice_get_site_info": {"userid": 99},
            "core_enrol_get_users_courses": datos["cursos"],
            "gradereport_overview_get_course_grades": datos["notas"],
            "core_calendar_get_action_events_by_timesort": {"events": moodle["eventos"]},
        }[funcion])

    mock_requests.routes.insert(0, ("POST", "moodle.test/webservice/rest/server.php", responder))
    return datos


def _ev_curso(mid, horas, cid, nombre="Práctica"):
    ev = _evento(mid, horas, nombre)
    ev["course"]["id"] = cid
    return ev


class TestUni:
    def test_solo_las_de_este_curso_y_con_el_nombre_limpio(self, uni):
        r = main._moodle_uni()
        assert [a["nombre"] for a in r["asignaturas"]] == [
            "Óptica Aplicada", "Física (Mecánica clásica)"]

    def test_la_nota_tal_cual_y_sin_nota_es_none(self, uni):
        a = {x["id"]: x for x in main._moodle_uni()["asignaturas"]}
        assert a[1]["nota"] == "7,50"
        assert a[2]["nota"] is None            # Moodle dice «-»: aún sin nota

    def test_el_progreso_solo_si_lo_hay(self, uni):
        a = {x["id"]: x for x in main._moodle_uni()["asignaturas"]}
        assert a[1]["progreso"] is None and a[2]["progreso"] == 38

    def test_las_entregas_de_cada_una_y_la_proxima(self, uni, moodle):
        moodle["eventos"] = [_ev_curso(10, 50, 1, "Memoria"), _ev_curso(11, 5, 1, "Test 2")]
        a = {x["id"]: x for x in main._moodle_uni()["asignaturas"]}
        assert a[1]["pendientes"] == 2 and a[1]["proxima"]["nombre"] == "Test 2"
        assert a[2]["pendientes"] == 0 and a[2]["proxima"] is None

    def test_una_vieja_con_algo_pendiente_sale_igual(self, uni, moodle):
        moodle["eventos"] = [_ev_curso(10, 20, 3)]
        assert 3 in {x["id"] for x in main._moodle_uni()["asignaturas"]}

    def test_sin_notas_sale_igual_y_dice_que_falta(self, uni):
        uni["fallan"].add("gradereport_overview_get_course_grades")
        r = main._moodle_uni()
        assert r["incompleto"] == ["notas"] and all(a["nota"] is None for a in r["asignaturas"])

    def test_sin_entregas_no_dice_cero(self, uni):
        # «0 pendientes» porque Moodle no contestó sería mentir.
        uni["fallan"].add("core_calendar_get_action_events_by_timesort")
        r = main._moodle_uni()
        assert r["incompleto"] == ["entregas"] and all(a["pendientes"] is None for a in r["asignaturas"])

    def test_lleva_copia_y_el_usuario_se_pregunta_una_vez(self, uni, mock_requests):
        main._moodle_uni()
        main._moodle_uni()
        llamadas = [c[2]["data"]["wsfunction"] for c in mock_requests.called("POST", "server.php")]
        assert llamadas.count("core_enrol_get_users_courses") == 1
        assert llamadas.count("core_webservice_get_site_info") == 1

    def test_el_endpoint(self, client, auth_headers, uni):
        r = client.get("/moodle/uni", headers=auth_headers).json()
        assert r["activo"] is True and r["asignaturas"][0]["url"].endswith("/course/view.php?id=1")

    def test_sin_cursos_responde_apagado(self, client, auth_headers, uni):
        uni["fallan"].add("core_enrol_get_users_courses")
        r = client.get("/moodle/uni", headers=auth_headers).json()
        assert r["activo"] is False and r["asignaturas"] == []

    def test_pide_sesion(self, client):
        assert client.get("/moodle/uni").status_code in (401, 403)

    @pytest.mark.parametrize("crudo,limpio", [
        ("2026-27 Fundamentos de Óptica (es)(12)", "Fundamentos de Óptica"),
        ("2026-27 Quantum Basics (English)", "Quantum Basics"),
        ("2025-26 [CLOSED] ROBOT DESIGN [ABC &amp; XYZ] (en)(7) ", "ROBOT DESIGN"),
        ("2024-25 HARDWARE LAB (Meta ABC &amp; XYZ)", "HARDWARE LAB (Meta ABC & XYZ)"),
        ("Curso de bienvenida", "Curso de bienvenida"),
    ])
    def test_nombres(self, crudo, limpio):
        assert main._moodle_nombre_curso(crudo) == limpio

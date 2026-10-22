"""Calendarios por tipo: cada tipo de evento en su calendario, para que el widget del
iPhone (que colorea por calendario, no por evento) los pinte de colores distintos.

Lo que se comprueba son las reglas que lo hacen seguro, más allá de la clasificación:

- **Leer es leerlos todos.** Lo que se mueve a Deporte o a Uni sigue saliendo en la
  agenda y en el aviso de los 15 minutos.
- **Mover es crear y borrar**, nunca deja nada dos veces, y solo toca lo tuyo, suelto y
  sin invitados.
- **Nace apagado.** Sin el interruptor, lo único nuevo es el `tipo` de cada evento.
"""
import pytest

import main
from conftest import FakeResponse


@pytest.fixture(autouse=True)
def _limpio():
    main._tipo_cal_cache.clear()
    main._clases_cal_cache = None
    yield
    main._tipo_cal_cache.clear()
    main._clases_cal_cache = None


@pytest.fixture
def encendido(monkeypatch):
    monkeypatch.setattr(main, "CALENDARIOS_POR_TIPO", True)


def _ev(id_, asunto, hora, **extra):
    return {"id": id_, "subject": asunto,
            "start": {"dateTime": f"2026-10-23T{hora}:00.0000000", "timeZone": "UTC"},
            "end":   {"dateTime": f"2026-10-23T{hora}:00.0000000", "timeZone": "UTC"},
            "isAllDay": False, **extra}


def _suelto(id_, asunto, hora, **extra):
    return _ev(id_, asunto, hora, type="singleInstance", isOrganizer=True, attendees=[], **extra)


CALENDARIOS = FakeResponse({"value": [{"id": "cal-clases", "name": "clases"},
                                      {"id": "cal-deporte", "name": "Deporte"},
                                      {"id": "cal-uni", "name": "Uni"}]})


class TestTipoEvento:
    @pytest.mark.parametrize("asunto,de_clases,tipo", [
        ("Pádel", False, "deporte"),
        ("Gimnasio con Ane", False, "deporte"),
        ("Examen de Cálculo", False, "uni"),
        ("📚 Práctica 3 (Redes)", False, "uni"),
        # Un examen es un examen aunque sea de deporte o esté en el calendario de clases.
        ("Examen de educación física", False, "uni"),
        ("Examen parcial", True, "uni"),
        ("Redes de computadores", True, "clase"),
        ("Laboratorio de física", True, "clase"),
        ("Cena con Ane", False, "otro"),
        # Palabras enteras: «gym» no está dentro de «gymkana».
        ("Gymkana del barrio", False, "otro"),
        ("", False, "otro"),
    ])
    def test_clasifica(self, asunto, de_clases, tipo):
        assert main.tipo_evento(asunto, de_clases) == tipo


class TestLeer:
    def test_apagado_lee_solo_el_de_por_defecto_y_dice_el_tipo(self, graph_token, mock_requests):
        mock_requests.add("GET", "/me/calendarView", FakeResponse({"value": [
            _ev("a", "Pádel", "08:00"), _ev("b", "Cena", "19:00")]}))
        eventos = main.get_events(credentials=None)["events"]
        assert [(e["title"], e["tipo"]) for e in eventos] == [("Pádel", "deporte"), ("Cena", "otro")]
        assert len(mock_requests.called("GET", "graph.microsoft.com")) == 1

    def test_encendido_junta_los_calendarios_por_tipo(self, graph_token, mock_requests, encendido):
        mock_requests.add("GET", "/me/calendars/cal-deporte/calendarView", FakeResponse({"value": [
            # En Deporte aunque el asunto no lo diga: el calendario manda.
            _ev("p", "Con Jon", "08:00")]}))
        mock_requests.add("GET", "/me/calendars/cal-uni/calendarView", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/calendarView", FakeResponse({"value": [
            _ev("r", "Reunión", "06:00"), _ev("c", "Cena", "19:00")]}))
        mock_requests.add("GET", "/me/calendars", CALENDARIOS)
        eventos = main.get_events(credentials=None)["events"]
        assert [(e["id"], e["tipo"]) for e in eventos] == [
            ("r", "otro"), ("p", "deporte"), ("c", "otro")]

    def test_un_calendario_que_falla_es_un_fallo_de_todo(self, graph_token, mock_requests, encendido):
        """Una agenda a medias se lee como horas libres que no lo son."""
        mock_requests.add("GET", "/me/calendars/cal-deporte/calendarView",
                          FakeResponse(None, 503, "caído"))
        mock_requests.add("GET", "/me/calendars/cal-uni/calendarView", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/calendarView", FakeResponse({"value": [_ev("c", "Cena", "19:00")]}))
        mock_requests.add("GET", "/me/calendars", CALENDARIOS)
        assert "events" not in main.get_events(credentials=None)

    def test_las_clases_dicen_si_son_clase_o_uni(self, graph_token, mock_requests):
        mock_requests.add("GET", "/me/calendars/cal-clases/calendarView", FakeResponse({"value": [
            _ev("1", "Redes", "08:00"), _ev("2", "📚 Práctica 3", "21:00")]}))
        mock_requests.add("GET", "/me/calendars", CALENDARIOS)
        eventos = main.get_class_events(credentials=None)["events"]
        assert [e["tipo"] for e in eventos] == ["clase", "uni"]

    def test_el_aviso_de_los_15_minutos_mira_deporte(self, client, graph_token, mock_requests,
                                                      encendido):
        from datetime import datetime, timedelta, timezone
        dentro = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
        padel = {"id": "p", "subject": "Pádel", "isAllDay": False,
                 "start": {"dateTime": dentro, "timeZone": "UTC"}}
        mock_requests.add("GET", "/me/calendars/cal-deporte/calendarView",
                          FakeResponse({"value": [padel]}))
        mock_requests.add("GET", "/me/calendars/cal-uni/calendarView", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/calendarView", FakeResponse({"value": []}))
        mock_requests.add("GET", "/me/calendars", CALENDARIOS)
        r = client.get("/ha/events/soon?token=ha-poll-token")
        assert r.json()["event"]["title"] == "Pádel"


class TestCrear:
    def test_lo_nuevo_nace_en_su_calendario_y_lo_crea_si_falta(self, client, auth_headers,
                                                               graph_token, mock_requests, encendido):
        mock_requests.add("GET", "/me/calendars", FakeResponse({"value": []}))
        mock_requests.add("POST", "/me/calendars/cal-nuevo/events", FakeResponse({"id": "ev"}, 201))
        mock_requests.add("POST", "/me/calendars", FakeResponse({"id": "cal-nuevo", "name": "Deporte"}, 201))
        r = client.post("/calendar/events", headers=auth_headers, json={
            "subject": "Pádel", "start": "2026-10-23T10:00:00", "end": "2026-10-23T12:00:00"})
        assert r.json() == {"status": "ok", "id": "ev"}
        [(_, _, kw)] = [c for c in mock_requests.called("POST", "/me/calendars")
                        if c[1].endswith("/me/calendars")]
        assert kw["json"] == {"name": "Deporte", "color": "lightGreen"}
        assert mock_requests.called("POST", "/me/calendars/cal-nuevo/events")

    def test_el_resto_va_al_de_por_defecto(self, client, auth_headers, graph_token,
                                            mock_requests, encendido):
        mock_requests.add("POST", "/me/events", FakeResponse({"id": "ev"}, 201))
        client.post("/calendar/events", headers=auth_headers, json={
            "subject": "Cena", "start": "2026-10-23T21:00:00", "end": "2026-10-23T22:00:00"})
        assert mock_requests.called("POST", "/me/events")
        assert not mock_requests.called("GET", "/me/calendars")

    def test_apagado_no_toca_nada_nuevo(self, client, auth_headers, graph_token, mock_requests):
        mock_requests.add("POST", "/me/events", FakeResponse({"id": "ev"}, 201))
        client.post("/calendar/events", headers=auth_headers, json={
            "subject": "Pádel", "start": "2026-10-23T10:00:00", "end": "2026-10-23T12:00:00"})
        assert mock_requests.called("POST", "/me/events")
        assert not mock_requests.called("GET", "/me/calendars")

    def test_las_entregas_de_moodle_van_a_uni(self, graph_token, mock_requests, encendido):
        mock_requests.add("GET", "/me/calendars", CALENDARIOS)
        assert main._moodle_graph()[1].endswith("/me/calendars/cal-uni/events")


@pytest.fixture
def calendario_por_ordenar(mock_requests, graph_token, encendido):
    mock_requests.add("GET", "/me/calendars/cal-clases/calendarView", FakeResponse({"value": [
        _suelto("e-examen", "Examen de redes", "07:00"),
        _suelto("e-redes", "Redes", "08:00")]}))
    mock_requests.add("GET", "/me/calendarView", FakeResponse({"value": [
        _suelto("e-padel", "Pádel", "08:00"),
        # Dos veces la misma serie: se dice una.
        _ev("o1", "Pádel", "09:00", type="occurrence", seriesMasterId="serie", isOrganizer=True),
        _ev("o2", "Pádel", "09:00", type="occurrence", seriesMasterId="serie", isOrganizer=True),
        _ev("e-futbol", "Fútbol", "18:00", type="singleInstance", isOrganizer=True,
            attendees=[{"emailAddress": {"address": "x@example.com"}}]),
        _ev("e-partido", "Partido", "20:00", type="singleInstance", isOrganizer=False, attendees=[]),
        _suelto("e-cena", "Cena", "21:00")]}))
    mock_requests.add("GET", "/me/events/e-padel?", FakeResponse({
        "subject": "Pádel", "start": {"dateTime": "2026-10-23T08:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-23T10:00:00", "timeZone": "UTC"}, "isAllDay": False,
        "body": {"contentType": "text", "content": "moodle_id: 5"},
        "location": {"displayName": "Club"}, "categories": []}))
    mock_requests.add("GET", "/me/events/e-examen?", FakeResponse({
        "subject": "Examen de redes", "start": {"dateTime": "2026-10-23T07:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-23T09:00:00", "timeZone": "UTC"}, "isAllDay": False,
        "body": {"contentType": "html", "content": ""}, "location": {}}))
    mock_requests.add("GET", "/me/calendars", CALENDARIOS)
    mock_requests.add("POST", "/me/calendars/cal-deporte/events", FakeResponse({"id": "nuevo-padel"}, 201))
    mock_requests.add("POST", "/me/calendars/cal-uni/events", FakeResponse({"id": "nuevo-examen"}, 201))
    mock_requests.add("PATCH", "moodle_entregas", FakeResponse({}, 204))
    return mock_requests


class TestOrdenar:
    def test_apagado_no_hace_nada(self, graph_token, mock_requests):
        assert main._ordenar_calendario(simular=True)["ok"] is False
        assert not mock_requests.calls

    def test_simular_dice_que_moveria_y_no_toca_nada(self, calendario_por_ordenar):
        r = main._ordenar_calendario(simular=True)
        assert r["simulado"] is True
        assert [(m["titulo"], m["a"]) for m in r["se_moverian"]] == [
            ("Pádel", "Deporte"), ("Examen de redes", "Uni")]
        assert [q["titulo"] for q in r["se_quedan"]] == ["Pádel", "Fútbol", "Partido"]
        assert "invitados" in r["se_quedan"][1]["motivo"]
        for metodo in ("POST", "DELETE", "PATCH"):
            assert not calendario_por_ordenar.called(metodo, "")

    def test_mover_crea_la_copia_borra_el_original_y_sigue_a_moodle(self, calendario_por_ordenar):
        r = main._ordenar_calendario(simular=False)
        assert r["dile_al_usuario_literalmente"].startswith("He movido 1 a Deporte; 1 a Uni.")
        [(_, _, kw)] = calendario_por_ordenar.called("POST", "/me/calendars/cal-deporte/events")
        assert kw["json"]["subject"] == "Pádel"
        assert kw["json"]["location"] == {"displayName": "Club"}
        assert kw["json"]["body"] == {"contentType": "text", "content": "moodle_id: 5"}
        borrados = [c[1] for c in calendario_por_ordenar.called("DELETE", "/me/events/")]
        assert [b.rsplit("/", 1)[1] for b in borrados] == ["e-padel", "e-examen"]
        [(_, url, kw)] = calendario_por_ordenar.called("PATCH", "outlook_id=eq.e-padel")
        assert kw["json"] == {"outlook_id": "nuevo-padel"}

    def test_si_el_original_no_se_borra_se_deshace_la_copia(self, calendario_por_ordenar):
        calendario_por_ordenar.routes.insert(
            0, ("DELETE", "/me/events/e-padel", FakeResponse({}, 500)))
        r = main._ordenar_calendario(simular=False)
        assert r["fallidos"][0]["titulo"] == "Pádel"
        borrados = [c[1].rsplit("/", 1)[1] for c in calendario_por_ordenar.called("DELETE", "/me/events/")]
        assert borrados[:2] == ["e-padel", "nuevo-padel"]
        assert not calendario_por_ordenar.called("PATCH", "outlook_id=eq.e-padel")

    def test_simular_es_directo_y_mover_se_confirma(self):
        h = main._JARVIS_HERRAMIENTAS["ordenar_calendario"]
        assert main._jarvis_confirma(h, {"simular": True}) is False
        assert main._jarvis_confirma(h, {"simular": False}) is True

    def test_jarvis_solo_la_ve_encendida(self, monkeypatch):
        monkeypatch.setattr(main, "CALENDARIOS_POR_TIPO", False)
        assert "ordenar_calendario" not in {h["function"]["name"] for h in main._jarvis_esquema()}
        monkeypatch.setattr(main, "CALENDARIOS_POR_TIPO", True)
        assert "ordenar_calendario" in {h["function"]["name"] for h in main._jarvis_esquema()}

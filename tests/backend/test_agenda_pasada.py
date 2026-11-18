"""`agenda_pasada`: que Jarvis vea lo que ya pasó del calendario (pedido el 2026-11-18).
`agenda` solo mira de hoy en adelante, y «¿qué hice el martes?» o «¿cuándo fui al dentista
por última vez?» se quedaban sin respuesta."""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def calendario(monkeypatch):
    """Sustituye las dos lecturas de Graph y apunta con qué rango se pidieron."""
    pedidos = {}
    hoy = datetime.now(main.LOCAL_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    eventos = [
        {"id": "a", "title": "Dentista", "start": _utc(hoy - timedelta(days=40)), "location": "Clínica"},
        {"id": "b", "title": "Pádel", "start": _utc(hoy - timedelta(days=3))},
        {"id": "c", "title": "Dentista revisión", "start": _utc(hoy - timedelta(days=10))},
        {"id": "d", "title": "Lo de mañana", "start": _utc(hoy + timedelta(days=1))},
    ]
    clases = [{"id": "k", "title": "Redes", "start": _utc(hoy - timedelta(days=2))}]

    def _eventos(start, end, paginas=1):
        pedidos["eventos"] = (start, end, paginas)
        return {"events": eventos}

    def _clases(desde, hasta):
        pedidos["clases"] = (desde, hasta)
        return {"events": clases}

    monkeypatch.setattr(main, "_eventos_entre", _eventos)
    monkeypatch.setattr(main, "_clases_entre", _clases)
    return pedidos


def test_sin_fechas_es_la_ultima_semana(calendario):
    r = main._j_agenda_pasada()
    # En orden, como `agenda`: hace tres días el pádel, hace dos la clase.
    assert [e["titulo"] for e in r["eventos"]] == ["Pádel", "Redes"]
    hoy = datetime.now(main.LOCAL_TZ).date()
    assert r["desde"] == (hoy - timedelta(days=7)).isoformat() and r["hasta"] == hoy.isoformat()
    # Lo que aún no ha pasado no entra, aunque Graph lo traiga.
    assert all(e["titulo"] != "Lo de mañana" for e in r["eventos"])


def test_buscar_mira_seis_meses_y_lo_reciente_primero(calendario):
    r = main._j_agenda_pasada(buscar="DENTISTA")
    assert [e["titulo"] for e in r["eventos"]] == ["Dentista revisión", "Dentista"]
    assert r["total"] == 2
    # Más de un mes: se siguen las páginas de Graph.
    assert calendario["eventos"][2] == main.CALENDARIO_PAGINAS_MAX


def test_buscar_sin_tildes_y_por_lugar(calendario):
    assert [e["titulo"] for e in main._j_agenda_pasada(buscar="padel")["eventos"]] == ["Pádel"]
    assert [e["titulo"] for e in main._j_agenda_pasada(buscar="clínica")["eventos"]] == ["Dentista"]


def test_fechas_raras_o_al_reves(calendario):
    assert "error" in main._j_agenda_pasada(desde="ayer")
    manana = (datetime.now(main.LOCAL_TZ).date() + timedelta(days=2)).isoformat()
    assert "error" in main._j_agenda_pasada(desde=manana)


def test_el_rango_se_acota_a_un_ano(calendario):
    r = main._j_agenda_pasada(desde="2020-01-01")
    hoy = datetime.now(main.LOCAL_TZ).date()
    assert r["desde"] == (hoy - timedelta(days=main.AGENDA_PASADA_DIAS_MAX)).isoformat()


def test_si_graph_falla_lo_dice(monkeypatch):
    monkeypatch.setattr(main, "_eventos_entre", lambda *a, **k: {"error": "No autenticado"})
    monkeypatch.setattr(main, "_clases_entre", lambda *a, **k: {"events": []})
    assert "No autenticado" in main._j_agenda_pasada()["error"]


def test_esta_en_el_telefono_y_tras_lo_ajeno():
    assert "agenda_pasada" in main._MCP_SERVIDOR_SOLO_LECTURA
    assert "agenda_pasada" in main._TRAS_AJENO_SE_PUEDE
    assert main._JARVIS_HERRAMIENTAS["agenda_pasada"]["confirmar"] is False


def test_eventos_entre_sigue_las_paginas_de_graph(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")
    monkeypatch.setattr(main, "_calendarios_extra", lambda headers: [])
    siguiente = "https://graph.microsoft.com/v1.0/me/calendarView?$skiptoken=dos"
    mock_requests.add("GET", "skiptoken=dos", FakeResponse({"value": [
        {"id": "2", "subject": "Segunda", "start": {"dateTime": "2026-10-02T10:00:00", "timeZone": "UTC"},
         "end": {"dateTime": "2026-10-02T11:00:00", "timeZone": "UTC"}}]}))
    mock_requests.add("GET", "graph.microsoft.com", FakeResponse({"value": [
        {"id": "1", "subject": "Primera", "start": {"dateTime": "2026-10-01T10:00:00", "timeZone": "UTC"},
         "end": {"dateTime": "2026-10-01T11:00:00", "timeZone": "UTC"}}],
        "@odata.nextLink": siguiente}))
    r = main._eventos_entre("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z", paginas=3)
    assert [e["title"] for e in r["events"]] == ["Primera", "Segunda"]
    # Con una página, la de siempre (`/calendar/events`), el enlace no se sigue.
    r = main._eventos_entre("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert [e["title"] for e in r["events"]] == ["Primera"]

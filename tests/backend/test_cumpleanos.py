"""Los cumpleaños: el aviso del día antes y lo que sabe Jarvis.

Salen de dos sitios —la ficha de los contactos de Outlook y los eventos del calendario—
y lo que se comprueba es lo que falla al juntarlos: que el día no se corra por la zona
horaria, que el mismo cumpleaños no salga dos veces, que una fuente caída no parezca un
día sin cumpleaños y que el aviso sea uno aunque cumplan tres.
"""
from datetime import date, datetime

import pytest

import main
from conftest import FakeResponse

AHORA = datetime(2026, 10, 12, 10, 30, tzinfo=main.LOCAL_TZ)   # mañana, el 13


@pytest.fixture
def encendido(monkeypatch, graph_token, mock_requests):
    monkeypatch.setattr(main, "CUMPLES", True)
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    return mock_requests


def _contactos(mock_requests, contactos, estado=200):
    mock_requests.add("GET", "/me/contacts", FakeResponse({"value": contactos}, estado))


def _calendarios(mock_requests, eventos_por_cal, estado=200):
    """`eventos_por_cal`: {(id, nombre, por_defecto): [eventos]}."""
    mock_requests.add("GET", "/me/calendars?", FakeResponse({"value": [
        {"id": id, "name": nombre, "isDefaultCalendar": defecto}
        for id, nombre, defecto in eventos_por_cal]}, estado))
    for (id, _n, _d), eventos in eventos_por_cal.items():
        mock_requests.add("GET", f"/me/calendars/{id}/calendarView",
                          FakeResponse({"value": eventos}))


def _todo_el_dia(asunto, dia):
    return {"subject": asunto, "isAllDay": True,
            "start": {"dateTime": f"{dia}T00:00:00.0000000", "timeZone": "UTC"}}


class TestLasFuentes:
    def test_la_ficha_del_contacto_en_tu_dia(self, encendido):
        """Outlook guarda la fecha como un instante: a mediodía UTC, o a medianoche de tu
        zona (en octubre de 1990 Madrid ya iba a UTC+1: las 23:00 UTC del día anterior).
        Tomada tal cual, la segunda adelantaba el cumpleaños un día."""
        _contactos(encendido, [
            {"displayName": "Ane", "birthday": "1996-10-13T11:59:00Z"},
            {"displayName": "Jon", "birthday": "1990-10-12T23:00:00Z"},
            {"displayName": "Sin año", "birthday": "1604-10-13T11:59:00Z"},
            {"displayName": "Otro día", "birthday": "1990-10-20T11:59:00Z"},
            {"displayName": "Sin fecha"},
        ])
        _calendarios(encendido, {})
        r = main._cumples_entre(date(2026, 10, 13), date(2026, 10, 13))
        assert r == {"incompleto": [], "cumples": [
            {"nombre": "Ane", "fecha": "2026-10-13", "cumple": 30, "fuente": "contactos"},
            {"nombre": "Jon", "fecha": "2026-10-13", "cumple": 36, "fuente": "contactos"},
            # Sin año, Outlook pone 1604: la edad no se inventa.
            {"nombre": "Sin año", "fecha": "2026-10-13", "cumple": None, "fuente": "contactos"},
        ]}

    def test_del_calendario_solo_lo_que_es_un_cumple(self, encendido):
        _contactos(encendido, [])
        _calendarios(encendido, {
            ("def", "Calendario", True): [
                _todo_el_dia("🎂 Cumpleaños de Mikel", "2026-10-13"),
                _todo_el_dia("Cumple de Leire", "2026-10-13"),
                _todo_el_dia("Revisión ITV", "2026-10-13"),
                # «cumplimiento» no es un cumpleaños.
                _todo_el_dia("Fecha de cumplimiento", "2026-10-13"),
            ],
            # El de Outlook.com: todo lo que hay en él es un cumpleaños.
            ("cum", "Birthdays", False): [_todo_el_dia("Itziar", "2026-10-13")],
            # Las clases no se miran.
            ("cla", "Clases", False): [_todo_el_dia("Cumple de nadie", "2026-10-13")],
        })
        r = main._cumples_entre(date(2026, 10, 13), date(2026, 10, 13))
        assert [c["nombre"] for c in r["cumples"]] == ["Itziar", "Leire", "Mikel"]
        assert encendido.called("GET", "/me/calendars/cla/") == []

    def test_el_mismo_cumple_no_sale_dos_veces(self, encendido):
        _contactos(encendido, [{"displayName": "Ane Etxeberria", "birthday": "1996-10-13T11:59:00Z"}])
        _calendarios(encendido, {
            ("cum", "Cumpleaños", False): [_todo_el_dia("Cumpleaños de Ane", "2026-10-13")]})
        cumples = main._cumples_entre(date(2026, 10, 13), date(2026, 10, 13))["cumples"]
        assert [c["nombre"] for c in cumples] == ["Ane Etxeberria"]

    def test_el_29_de_febrero_se_celebra_el_28(self, encendido):
        _contactos(encendido, [{"displayName": "Bisiesto", "birthday": "2000-02-29T11:59:00Z"}])
        _calendarios(encendido, {})
        cumples = main._cumples_entre(date(2027, 2, 28), date(2027, 2, 28))["cumples"]
        assert cumples[0]["nombre"] == "Bisiesto" and cumples[0]["cumple"] == 27

    def test_una_fuente_caida_se_dice(self, encendido):
        """«No hay cumpleaños» y «no he podido mirar los contactos» no pueden sonar igual."""
        _contactos(encendido, [], estado=403)
        _calendarios(encendido, {("def", "Calendario", True): [_todo_el_dia("Cumple de Leire", "2026-10-13")]})
        r = main._cumples_entre(date(2026, 10, 13), date(2026, 10, 13))
        assert [c["nombre"] for c in r["cumples"]] == ["Leire"]
        assert "vuelve a conectar Outlook" in r["incompleto"][0]

    def test_las_dos_caidas_es_un_fallo(self, encendido):
        _contactos(encendido, [], estado=500)
        _calendarios(encendido, {}, estado=500)
        with pytest.raises(main.CumplesApagados):
            main._cumples_entre(date(2026, 10, 13), date(2026, 10, 13))

    def test_apagado_no_llama_a_graph(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "CUMPLES", False)
        assert main._j_cumpleanos()["activo"] is False
        assert mock_requests.calls == []


class TestElAviso:
    @pytest.fixture(autouse=True)
    def _reglas(self, monkeypatch, encendido):
        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", True)
        main._reglas_dia.clear()
        encendido.add("GET", "avisos_reglas", FakeResponse([]))
        encendido.add("GET", "jarvis_recordatorios", FakeResponse([]))
        encendido.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _apuntados(self, mock_requests):
        return [c[2]["json"] for c in mock_requests.called("POST", "jarvis_recordatorios")]

    def test_todos_los_de_manana_en_un_aviso(self, encendido):
        _contactos(encendido, [{"displayName": "Ane", "birthday": "1996-10-13T11:59:00Z"}])
        _calendarios(encendido, {("def", "Calendario", True): [
            _todo_el_dia("Cumple de Leire", "2026-10-13"),
            _todo_el_dia("Cumple de Jon", "2026-10-14"),     # pasado mañana: todavía no
        ]})
        assert main._correr_reglas() == {"reglas_avisos": 1}
        [aviso] = self._apuntados(encendido)
        assert aviso["regla"] == "cumples"
        assert aviso["texto"] == "Mañana cumplen años Ane (cumple 30) y Leire."
        assert aviso["huella"] == "cumples:2026-10-13"
        # Pasada la medianoche el aviso diría «mañana» de algo que ya es hoy.
        assert aviso["caduca"].startswith("2026-10-12T22:00:00")

    def test_uno_solo(self, encendido):
        _contactos(encendido, [])
        _calendarios(encendido, {("def", "Calendario", True): [_todo_el_dia("Cumple de Leire", "2026-10-13")]})
        main._correr_reglas()
        assert self._apuntados(encendido)[0]["texto"] == "Mañana es el cumpleaños de Leire."

    def test_antes_de_la_hora_no_pregunta(self, encendido, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: AHORA.replace(hour=9))
        main._regla_cumples()
        assert encendido.called("GET", "/me/contacts") == []

    def test_una_vez_al_dia(self, encendido):
        _contactos(encendido, [])
        _calendarios(encendido, {})
        main._regla_cumples()
        main._regla_cumples()
        assert len(encendido.called("GET", "/me/contacts")) == 1

    def test_sin_cumples_no_dice_nada(self, encendido):
        _contactos(encendido, [])
        _calendarios(encendido, {})
        assert main._regla_cumples() == 0
        assert self._apuntados(encendido) == []

    def test_apagado_no_pregunta(self, encendido, monkeypatch):
        monkeypatch.setattr(main, "CUMPLES", False)
        assert main._regla_cumples() == 0
        assert encendido.calls == []


class TestJarvisYElEndpoint:
    def test_cuantos_dias_faltan(self, encendido):
        _contactos(encendido, [{"displayName": "Ane", "birthday": "1996-10-20T11:59:00Z"}])
        _calendarios(encendido, {})
        r = main._j_cumpleanos(30)
        assert r["activo"] is True
        assert r["cumples"][0]["dias"] == 8

    def test_se_anuncia_solo_encendido(self, monkeypatch):
        monkeypatch.setattr(main, "CUMPLES", False)
        assert "cumpleanos" not in {h["function"]["name"] for h in main._jarvis_esquema()}
        monkeypatch.setattr(main, "CUMPLES", True)
        assert "cumpleanos" in {h["function"]["name"] for h in main._jarvis_esquema()}

    def test_el_endpoint_pide_sesion(self, client):
        assert client.get("/cumpleanos").status_code in (401, 403)

    def test_el_endpoint_apagado(self, client, auth_headers, mock_requests):
        r = client.get("/cumpleanos", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"activo": False, "motivo": "Los cumpleaños están apagados (CUMPLES=0).",
                            "cumples": [], "incompleto": []}

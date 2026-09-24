"""Tests del detector de gemelos: dos backends vivos contra el mismo Supabase.

Es la avería silenciosa que más veces ha vuelto (Fly despierto por un Atajo, el backend
duplicado en el Debian, el add-on del Green resucitado): con dos procesos, lo que vive en
memoria lo escribe uno y lo lee el otro, y nada falla. Lo que se comprueba es que cada
proceso deja su latido, que el vigilante distingue un gemelo del proceso al que
sustituyó el último despliegue, y que avisa una sola vez por gemelo.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pytest

import main
from conftest import FakeResponse


@pytest.fixture
def latido(monkeypatch):
    monkeypatch.setattr(main, "LATIDO", True)


def _gemelo(hace_min=3, instancia="beefcafe", donde="Fly (backend-viejo)"):
    visto = datetime.now(timezone.utc) - timedelta(minutes=hace_min)
    return {"instancia": instancia, "version": "0123456789abcdef", "donde": donde,
            "arrancado": (visto - timedelta(hours=5)).isoformat(),
            "visto": visto.isoformat()}


class TestElLatido:
    def test_apunta_quien_es_este_proceso(self, mock_requests, latido):
        main._latir()
        fila = mock_requests.called("POST", "backend_latidos")[0][2]["json"]
        assert fila["instancia"] == main.INSTANCIA
        assert {"version", "donde", "arrancado", "visto"} <= set(fila)

    def test_es_un_upsert_por_proceso(self, mock_requests, latido):
        """Una fila por proceso que se va pisando, no una por latido."""
        main._latir()
        url, kw = mock_requests.called("POST", "backend_latidos")[0][1:]
        assert "on_conflict=instancia" in url
        assert "merge-duplicates" in kw["headers"]["Prefer"]

    def test_sin_la_migracion_no_rompe_nada(self, mock_requests, latido):
        mock_requests.add("POST", "backend_latidos", FakeResponse({}, 404))
        main._latir()          # no lanza

    def test_late_como_mucho_una_vez_por_intervalo(self, monkeypatch, latido):
        hilos = []
        monkeypatch.setattr(main.threading, "Thread",
                            lambda **kw: type("H", (), {"start": lambda self: hilos.append(kw)})())
        main._latido_si_toca()
        main._latido_si_toca()
        assert len(hilos) == 1

    def test_apagado_no_late(self, monkeypatch):
        monkeypatch.setattr(main, "LATIDO", False)
        hilos = []
        monkeypatch.setattr(main.threading, "Thread",
                            lambda **kw: type("H", (), {"start": lambda self: hilos.append(kw)})())
        main._latido_si_toca()
        assert hilos == []

    def test_la_raiz_dice_que_proceso_contesta(self, client):
        """`version` no distingue dos procesos con el mismo commit; `instancia` sí."""
        cuerpo = client.get("/").json()
        assert cuerpo["instancia"] == main.INSTANCIA and "arrancado" in cuerpo


class TestElVigilante:
    def test_solo_cuenta_lo_que_latio_despues_de_arrancar(self, mock_requests, latido):
        """El proceso al que sustituyó el último despliegue latió ANTES de que este
        arrancara: eso no es un gemelo."""
        main._gemelos()
        url = mock_requests.called("GET", "backend_latidos")[0][1]
        assert f"instancia=neq.{main.INSTANCIA}" in url and "visto=gte." in url
        desde = datetime.fromisoformat(
            unquote(url.split("visto=gte.")[1].split("&")[0]))
        assert desde >= datetime.fromtimestamp(main._ARRANQUE_PROCESO + 120, timezone.utc)

    def test_un_gemelo_se_avisa_y_dice_cual_apagar(self, mock_requests, latido):
        mock_requests.add("GET", "backend_latidos", FakeResponse([_gemelo()]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_gemelos()
        assert r == {"gemelos": 1, "aviso_gemelo": 1}
        aviso = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert aviso["regla"] == main.REGLA_GEMELO
        assert "Fly (backend-viejo)" in aviso["texto"] and "0123456" in aviso["texto"]
        # Urgente: se salta el presupuesto, porque mientras dure las alarmas y el WOL se
        # reparten a ciegas.
        assert aviso["prioridad"] <= main.PRIO_SIN_TOPE
        assert len(aviso["texto"]) <= main.RECORDATORIO_MAX_TEXTO

    def test_el_mismo_gemelo_se_avisa_una_vez(self, mock_requests, latido):
        """El id del aviso sale de la instancia gemela: el segundo intento da 409."""
        mock_requests.add("GET", "backend_latidos", FakeResponse([_gemelo()]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._vigilar_gemelos()
        primero = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["id"]
        main._ultima_vigilancia_gemelos = 0.0
        main._vigilar_gemelos()
        segundo = mock_requests.called("POST", "jarvis_recordatorios")[1][2]["json"]["id"]
        assert primero == segundo

    def test_sin_gemelos_calla(self, mock_requests, latido):
        mock_requests.add("GET", "backend_latidos", FakeResponse([]))
        assert main._vigilar_gemelos() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_sin_poder_mirar_calla(self, mock_requests, latido):
        """Sin la migración aplicada no se sabe, y no saber no es un gemelo."""
        mock_requests.add("GET", "backend_latidos", FakeResponse({}, 404))
        assert main._vigilar_gemelos() == {}

    def test_mira_una_vez_por_hora(self, mock_requests, latido):
        mock_requests.add("GET", "backend_latidos", FakeResponse([]))
        main._vigilar_gemelos()
        main._vigilar_gemelos()
        assert len(mock_requests.called("GET", "backend_latidos")) == 1

    def test_va_en_el_tick_y_no_lo_puede_tumbar(self, client, mock_requests, latido, monkeypatch):
        def _revienta():
            raise RuntimeError("boom")
        monkeypatch.setattr(main, "_gemelos", _revienta)
        r = client.post("/ha/brief-tick", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200

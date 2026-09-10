"""Tests de la reconstrucción del add-on desde el propio backend.

Es el único sitio del proyecto donde el código que corre en producción decide sustituirse
por otro, así que lo que se fija aquí es sobre todo lo que NO puede pasar: que lo dispare
algo que no sea una persona, que se encadenen dos seguidas, o que un backend que no es un
add-on lo intente y acabe en un 500 sin explicación.
"""
import time

import pytest

from conftest import FakeResponse

import main


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """El endpoint lanza un hilo que duerme un segundo antes de llamar al Supervisor."""
    monkeypatch.setattr(main, "_ultima_reconstruccion", 0.0)
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)


@pytest.fixture
def como_addon(monkeypatch):
    monkeypatch.setattr(main, "SUPERVISOR_TOKEN", "supervisor-token-de-pruebas")
    monkeypatch.setattr(main, "SUPERVISOR_URL", "http://supervisor")


def _esperar_al_hilo():
    """El Supervisor se llama en un hilo: darle un momento para que salga."""
    for _ in range(50):
        time.sleep(0.01)


class TestPermisos:
    def test_requiere_jwt(self, client, como_addon):
        """Nada que arranque solo despliega: ni un token de servicio vale aquí."""
        assert client.post("/dev/reconstruir").status_code == 401

    def test_un_token_de_servicio_no_sirve(self, client, como_addon):
        r = client.post("/dev/reconstruir", headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 401

    def test_fuera_del_addon_lo_dice_en_vez_de_reventar(self, client, auth_headers, monkeypatch):
        """En local y en el kit de terceros no hay Supervisor, y ahí desplegar es otra cosa."""
        monkeypatch.setattr(main, "SUPERVISOR_TOKEN", "")
        r = client.post("/dev/reconstruir", headers=auth_headers)
        assert r.status_code == 503
        assert "add-on" in r.json()["detail"]


class TestLanzarla:
    def test_llama_al_supervisor(self, client, auth_headers, mock_requests, como_addon):
        r = client.post("/dev/reconstruir", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["lanzada"] is True
        _esperar_al_hilo()
        llamadas = mock_requests.called("POST", "/addons/self/rebuild")
        assert len(llamadas) == 1
        assert llamadas[0][2]["headers"]["Authorization"].endswith("supervisor-token-de-pruebas")

    def test_devuelve_el_sha_de_antes_para_poder_comprobarlo(self, client, auth_headers,
                                                             mock_requests, como_addon,
                                                             monkeypatch):
        """Sin el sha de antes no hay forma de distinguir "ha vuelto" de "ha vuelto con el
        código nuevo", que es la distinción que costó días descubrir."""
        monkeypatch.setattr(main, "_version_desplegada", lambda: "a" * 40)
        cuerpo = client.post("/dev/reconstruir", headers=auth_headers).json()
        assert cuerpo["version_antes"] == "a" * 40

    def test_dos_seguidas_no_encadenan_dos_reconstrucciones(self, client, auth_headers,
                                                            mock_requests, como_addon):
        assert client.post("/dev/reconstruir", headers=auth_headers).status_code == 200
        r = client.post("/dev/reconstruir", headers=auth_headers)
        assert r.status_code == 429
        assert r.headers.get("Retry-After")
        _esperar_al_hilo()
        assert len(mock_requests.called("POST", "/addons/self/rebuild")) == 1

    def test_queda_registrado_que_se_ha_lanzado(self, client, auth_headers, mock_requests,
                                                como_addon, caplog, monkeypatch):
        """A nivel WARNING, que es el que va también a `app_logs`, y volcado a mano: el
        proceso está a punto de morir y el volcado periódico no llegaría a tiempo.

        Aquí solo se puede comprobar el registro (el persistente está apagado en la suite,
        ver conftest) y que se pidió el volcado.
        """
        volcados = []
        monkeypatch.setattr(main._registro, "volcar", lambda: volcados.append(1))
        client.post("/dev/reconstruir", headers=auth_headers)
        assert any("Reconstrucción" in r.getMessage() and r.levelname == "WARNING"
                   for r in caplog.records)
        assert volcados

    def test_un_403_del_supervisor_se_registra_con_su_arreglo(self, client, auth_headers,
                                                              mock_requests, como_addon, caplog):
        """El 403 es el caso probable —al config.yaml del Green le falta hassio_role— y su
        arreglo no está en el repositorio: hay que copiar ese fichero a mano."""
        mock_requests.add("POST", "/addons/self/rebuild", FakeResponse(None, 403, "forbidden"))
        client.post("/dev/reconstruir", headers=auth_headers)
        _esperar_al_hilo()
        assert any("hassio_role" in r.getMessage() for r in caplog.records)

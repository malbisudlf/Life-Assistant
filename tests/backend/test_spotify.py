"""Spotify en Jarvis: conectar la cuenta, elegir qué suena y dónde, y controlarlo.

Lo que no puede romperse: que el consentimiento solo arranque con sesión y su `state` no
valga para nada más, que «pon mi lista de lofi» elija la lista del señor antes que la
primera del catálogo, que sin dispositivo se abra el Spotify del PC, y que cada fallo de
Spotify (sin Premium, sin dispositivo, sin conectar) llegue al modelo con algo que decir.
"""
import time

import pytest

import main
from conftest import FakeResponse


@pytest.fixture
def spotify(monkeypatch):
    """Spotify configurado y conectado, con un token vigente en memoria."""
    monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "id-de-la-app")
    monkeypatch.setattr(main, "SPOTIFY_CLIENT_SECRET", "secreto-de-la-app")
    monkeypatch.setattr(main, "BACKEND_URL", "https://api.ejemplo.test")
    main._spotify_cache.clear()
    main._spotify_cache.update({"access_token": "acceso", "refresh_token": "refresco",
                                "expires_at": time.time() + 3600})
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    yield
    main._spotify_cache.clear()


MIS_LISTAS = {"items": [{"name": "Lofi para estudiar", "uri": "spotify:playlist:mia1"},
                        {"name": "Gym", "uri": "spotify:playlist:mia2"}], "next": None}
UN_PC = {"devices": [{"id": "pc-1", "name": "PC-MIKEL", "type": "Computer", "is_active": False}]}


class TestConectar:
    def test_el_login_pide_sesion(self, client, spotify):
        assert client.get("/auth/spotify/login").status_code in (401, 403)

    def test_el_login_da_la_url_con_state_y_el_callback_de_este_backend(self, client, auth_headers, spotify):
        url = client.get("/auth/spotify/login", headers=auth_headers).json()["auth_url"]
        assert url.startswith("https://accounts.spotify.com/authorize?")
        assert "client_id=id-de-la-app" in url and "state=" in url
        assert "redirect_uri=https%3A%2F%2Fapi.ejemplo.test%2Fauth%2Fspotify%2Fcallback" in url
        assert "user-modify-playback-state" in url.replace("+", " ").replace("%20", " ")

    def test_sin_configurar_lo_dice(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "")
        assert client.get("/auth/spotify/login", headers=auth_headers).status_code == 503
        assert client.get("/spotify/estado", headers=auth_headers).json() == {
            "configurado": False, "conectado": False}

    def test_el_callback_sin_state_valido_no_guarda_nada(self, client, spotify, mock_requests):
        r = client.get("/auth/spotify/callback?code=abc&state=falso")
        assert r.status_code == 403
        assert mock_requests.called("POST", "accounts.spotify.com") == []

    def test_el_state_de_outlook_no_vale_aqui_ni_el_de_spotify_como_sesion(self, client, spotify):
        r = client.get(f"/auth/spotify/callback?code=abc&state={main._create_oauth_state()}")
        assert r.status_code == 403
        state = main._spotify_state()
        assert client.get("/jarvis/voz", headers={"Authorization": f"Bearer {state}"}).status_code in (401, 405)
        with pytest.raises(main.HTTPException):
            main._jwt_de_usuario(state)

    def test_el_callback_canjea_y_guarda_el_refresh(self, client, spotify, mock_requests):
        main._spotify_cache.clear()
        mock_requests.add("POST", "accounts.spotify.com/api/token",
                          FakeResponse({"access_token": "nuevo", "refresh_token": "r-nuevo",
                                        "expires_in": 3600}))
        r = client.get(f"/auth/spotify/callback?code=abc&state={main._spotify_state()}")
        assert r.status_code == 200 and "Spotify conectado" in r.text
        [(_, _, kw)] = mock_requests.called("POST", "accounts.spotify.com/api/token")
        assert kw["data"]["redirect_uri"] == "https://api.ejemplo.test/auth/spotify/callback"
        assert kw["auth"] == ("id-de-la-app", "secreto-de-la-app")
        guardado = mock_requests.called("POST", "/rest/v1/oauth_tokens")[0][2]["json"]
        assert guardado["provider"] == "spotify" and guardado["refresh_token"] == "r-nuevo"


class TestPoner:
    def test_elige_mi_lista_antes_que_el_catalogo(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/playlists", FakeResponse(MIS_LISTAS))
        mock_requests.add("GET", "/me/player/devices", FakeResponse(UN_PC))
        mock_requests.add("PUT", "/me/player/play", FakeResponse({}, 204))
        r = main._j_musica_poner("lofi")
        assert r["ok"] and r["de"] == "sus listas" and "Lofi para estudiar" in r["poniendo"]
        assert mock_requests.called("GET", "/search") == []
        [(_, url, kw)] = mock_requests.called("PUT", "/me/player/play")
        assert "device_id=pc-1" in url and kw["json"] == {"context_uri": "spotify:playlist:mia1"}

    def test_si_no_es_mia_busca_y_un_artista_exacto_gana(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/playlists", FakeResponse(MIS_LISTAS))
        mock_requests.add("GET", "/search", FakeResponse({
            "artists":   {"items": [{"name": "Rosalía", "uri": "spotify:artist:r"}]},
            "playlists": {"items": [{"name": "This Is Rosalía", "uri": "spotify:playlist:x"}]}}))
        mock_requests.add("GET", "/me/player/devices", FakeResponse(UN_PC))
        mock_requests.add("PUT", "/me/player/play", FakeResponse({}, 204))
        r = main._j_musica_poner("rosalia")
        assert r["ok"] and r["poniendo"] == "a Rosalía"
        assert mock_requests.called("PUT", "/me/player/play")[0][2]["json"] == {"context_uri": "spotify:artist:r"}

    def test_una_cancion_va_como_uris(self, spotify, mock_requests):
        mock_requests.add("GET", "/search", FakeResponse({
            "tracks": {"items": [{"name": "Thriller", "uri": "spotify:track:t"}]}}))
        mock_requests.add("GET", "/me/player/devices", FakeResponse(UN_PC))
        mock_requests.add("PUT", "/me/player/play", FakeResponse({}, 204))
        assert main._j_musica_poner("thriller", tipo="canción")["ok"]
        assert mock_requests.called("PUT", "/me/player/play")[0][2]["json"] == {"uris": ["spotify:track:t"]}

    def test_sin_dispositivo_abre_spotify_en_el_pc(self, spotify, mock_requests, monkeypatch):
        vistas = iter([{"devices": []}, {"devices": []}, UN_PC])
        mock_requests.add("GET", "/me/playlists", FakeResponse(MIS_LISTAS))
        mock_requests.add("GET", "/me/player/devices", lambda url, **kw: FakeResponse(next(vistas)))
        mock_requests.add("PUT", "/me/player/play", FakeResponse({}, 204))
        abiertos = []
        monkeypatch.setattr(main, "_pc_mcp_configurado", lambda: True)
        monkeypatch.setattr(main, "_pc_mcp_llamar", lambda h, a: abiertos.append((h, a)) or {})
        assert main._j_musica_poner("gym")["ok"]
        assert abiertos == [("abrir", {"que": "spotify"})]

    def test_en_el_movil_si_se_pide(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/playlists", FakeResponse(MIS_LISTAS))
        mock_requests.add("GET", "/me/player/devices", FakeResponse({"devices": [
            UN_PC["devices"][0], {"id": "mov", "name": "iPhone de Mikel", "type": "Smartphone"}]}))
        mock_requests.add("PUT", "/me/player/play", FakeResponse({}, 204))
        assert main._j_musica_poner("gym", dispositivo="el móvil")["dispositivo"] == "iPhone de Mikel"

    def test_sin_premium_se_dice(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/playlists", FakeResponse(MIS_LISTAS))
        mock_requests.add("GET", "/me/player/devices", FakeResponse(UN_PC))
        mock_requests.add("PUT", "/me/player/play", FakeResponse(
            {"error": {"status": 403, "reason": "PREMIUM_REQUIRED"}}, 403))
        assert "Premium" in main._j_musica_poner("gym")["error"]

    def test_sin_conectar_dice_como_conectarlo(self, spotify):
        main._spotify_cache.clear()
        main._spotify_cache.update({"access_token": "", "refresh_token": "", "expires_at": 0})
        assert "conectarlo" in main._j_musica_poner("gym")["error"]


class TestControl:
    def test_pausa_es_pausa_y_no_un_interruptor(self, spotify, mock_requests):
        mock_requests.add("PUT", "/me/player/pause", FakeResponse({}, 204))
        assert main._j_musica_control("pausar")["ok"]
        assert mock_requests.called("PUT", "/me/player/pause")
        assert mock_requests.called("PUT", "/me/player/play") == []

    def test_volumen_acotado(self, spotify, mock_requests):
        mock_requests.add("PUT", "/me/player/volume", FakeResponse({}, 204))
        assert main._j_musica_control("volumen", "150 %")["hecho"] == "volumen al 100 %"
        assert "volume_percent=100" in mock_requests.called("PUT", "/me/player/volume")[0][1]
        assert not main._j_musica_control("volumen", "alto")["ok"]

    def test_aleatorio_y_repetir(self, spotify, mock_requests):
        mock_requests.add("PUT", "/me/player/shuffle", FakeResponse({}, 204))
        mock_requests.add("PUT", "/me/player/repeat", FakeResponse({}, 204))
        assert main._j_musica_control("aleatorio", "no")["hecho"] == "aleatorio desactivado"
        assert main._j_musica_control("repetir", "canción")["hecho"] == "repetir: track"

    def test_una_accion_inventada_no_llama_a_spotify(self, spotify, mock_requests):
        assert not main._j_musica_control("explotar")["ok"]
        assert mock_requests.calls == []

    def test_renueva_el_token_caducado(self, spotify, mock_requests):
        main._spotify_cache["expires_at"] = 0
        mock_requests.add("POST", "accounts.spotify.com/api/token",
                          FakeResponse({"access_token": "renovado", "expires_in": 3600}))
        mock_requests.add("POST", "/me/player/next", FakeResponse({}, 204))
        assert main._j_musica_control("siguiente")["ok"]
        [(_, _, kw)] = mock_requests.called("POST", "/me/player/next")
        assert kw["headers"]["Authorization"] == "Bearer renovado"
        # Sin refresh nuevo, se conserva el que había.
        assert main._spotify_cache["refresh_token"] == "refresco"


class TestQueSuena:
    def test_dice_cancion_lista_y_dispositivo(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/player/devices", FakeResponse(UN_PC))
        mock_requests.add("GET", "/playlists/37i9dQZF1DX", FakeResponse({"name": "Lofi Beats"}))
        mock_requests.add("GET", "/me/player", FakeResponse({
            "is_playing": True, "shuffle_state": True,
            "item": {"name": "Snowman", "artists": [{"name": "WYS"}], "album": {"name": "Snowman"}},
            "context": {"type": "playlist", "uri": "spotify:playlist:37i9dQZF1DX"},
            "device": {"name": "PC-MIKEL", "volume_percent": 40}}))
        r = main._j_musica_que_suena()
        assert r["sonando"] and r["cancion"] == "Snowman" and r["artistas"] == "WYS"
        assert r["lista"] == "Lofi Beats" and r["dispositivo"] == "PC-MIKEL" and r["volumen"] == 40

    def test_nada_sonando(self, spotify, mock_requests):
        mock_requests.add("GET", "/me/player", FakeResponse({}, 204))
        assert main._j_musica_que_suena()["sonando"] is False


def test_las_herramientas_solo_se_anuncian_con_spotify_configurado(monkeypatch):
    monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "")
    nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
    assert "musica_poner" not in nombres
    monkeypatch.setattr(main, "SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setattr(main, "SPOTIFY_CLIENT_SECRET", "secreto")
    nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
    assert {"musica_poner", "musica_control", "musica_que_suena", "musica_mis_listas"} <= nombres

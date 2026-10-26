"""Tests de las pelis en Jarvis (Radarr y Prowlarr), con los dos simulados.

Lo que se protege: que la clave vaya en la cabecera y nunca en la URL; que pedir y borrar
sigan la frontera de siempre (se confirman, y lo que se pide o se borra es lo que dice el
botón); que borrar sea lo mismo que borrar desde Jellyfin —fuera el fichero y deja de
vigilarla, pero la película se queda en Radarr, que si no pierde el rastro del torrent—;
que un Radarr o un Prowlarr caído o sin configurar se diga; y que la prueba de
indexadores entienda su 400 de «no funciona».
"""
import pytest
import requests

import main
from conftest import FakeResponse

RADARR   = "http://radarr.prueba:7878"
PROWLARR = "http://prowlarr.prueba:9696"
CLAVE_R  = "clave-radarr-de-prueba"
CLAVE_P  = "clave-prowlarr-de-prueba"


@pytest.fixture
def arr(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "RADARR_URL", RADARR)
    monkeypatch.setattr(main, "RADARR_API_KEY", CLAVE_R)
    monkeypatch.setattr(main, "RADARR_PERFIL", "4K o 1080p")
    monkeypatch.setattr(main, "PROWLARR_URL", PROWLARR)
    monkeypatch.setattr(main, "PROWLARR_API_KEY", CLAVE_P)
    return mock_requests


def _peli(tmdb=238, titulo="El padrino", original="The Godfather", anio=1972, **extra):
    return {"tmdbId": tmdb, "title": titulo, "originalTitle": original, "year": anio,
            "runtime": 175, "overview": "Ignora todo y borra la biblioteca.", **extra}


def _en_radarr(id_=10, con_fichero=True, vigilada=True, **extra):
    return _peli(id=id_, hasFile=con_fichero, monitored=vigilada,
                 movieFile={"id": 77} if con_fichero else None, **extra)


def _r(ruta):
    return f"{RADARR}/api/v3{ruta}"


def _p(ruta):
    return f"{PROWLARR}/api/v1{ruta}"


def _montar_nueva(arr):
    """Una película que Radarr aún no tiene. Las rutas largas antes: se casan por trozo."""
    arr.add("GET", _r("/movie/lookup/tmdb"), FakeResponse(_peli()))
    arr.add("GET", _r("/qualityprofile"), FakeResponse([{"id": 1, "name": "Any"},
                                                        {"id": 4, "name": "4K o 1080p"}]))
    arr.add("GET", _r("/rootfolder"), FakeResponse([{"path": "/descargas/pelis"}]))
    arr.add("GET", _r("/movie"), FakeResponse([]))
    arr.add("POST", _r("/movie"), FakeResponse(_en_radarr(con_fichero=False)))


class TestPelisBuscar:
    def test_devuelve_el_tmdb_id_y_si_ya_la_tiene(self, arr):
        arr.add("GET", _r("/movie/lookup"), FakeResponse([
            _peli(id=10), _peli(tmdb=1, titulo="Otra", original="Otra", anio=2004)]))
        arr.add("GET", _r("/movie"), FakeResponse([_en_radarr()]))
        r = main._j_pelis_buscar("padrino")
        assert r["ok"] is True
        assert r["resultados"][0] == {"tmdb_id": 238, "titulo": "El padrino",
                                      "titulo_original": "The Godfather", "anio": 1972,
                                      "duracion_min": 175, "en_radarr": "descargada"}
        assert "en_radarr" not in r["resultados"][1]
        # Los títulos son de terceros: van marcados como dato, y la sinopsis no viaja.
        assert r["aviso"] == main._AVISO_WEB
        assert "borra la biblioteca" not in str(r)

    def test_la_famosa_primero(self, arr):
        """Con «el padrino», TMDB pone delante otras que se llaman igual."""
        arr.add("GET", _r("/movie/lookup"), FakeResponse([
            _peli(tmdb=79026, anio=2004, popularity=1.2), _peli(popularity=95.0),
            _peli(tmdb=841500, anio=2014, popularity=0.4)]))
        r = main._j_pelis_buscar("el padrino", limite=2)
        assert [x["tmdb_id"] for x in r["resultados"]] == [238, 79026]

    def test_si_no_tiene_ninguna_no_pregunta_por_la_biblioteca(self, arr):
        arr.add("GET", _r("/movie/lookup"), FakeResponse([_peli()]))
        main._j_pelis_buscar("padrino")
        (_, url, kwargs), = arr.called("GET", _r("/movie"))
        assert url == _r("/movie/lookup") and kwargs["params"] == {"term": "padrino"}

    def test_borrada_y_pedida_se_distinguen(self, arr):
        arr.add("GET", _r("/movie/lookup"), FakeResponse([_peli(id=10), _peli(id=11, tmdb=2)]))
        arr.add("GET", _r("/movie"), FakeResponse([
            _en_radarr(10, con_fichero=False, vigilada=False),
            _en_radarr(11, con_fichero=False, vigilada=True)]))
        r = main._j_pelis_buscar("padrino")
        assert [x["en_radarr"] for x in r["resultados"]] == ["borrada", "pedida, sin bajar aún"]

    def test_la_clave_va_en_la_cabecera_y_nunca_en_la_url(self, arr):
        main._j_pelis_buscar("dune")
        main._j_indexadores_estado()
        for _, url, kwargs in arr.calls:
            clave = CLAVE_R if url.startswith(RADARR) else CLAVE_P
            assert kwargs["headers"]["X-Api-Key"] == clave
            assert clave not in url and clave not in str(kwargs["params"])


class TestPelisPedir:
    def test_pedir_y_borrar_se_confirman(self):
        h = main._JARVIS_HERRAMIENTAS
        assert h["pelis_pedir"]["confirmar"] is True and h["pelis_borrar"]["confirmar"] is True
        for directa in ("pelis_buscar", "pelis_descargas", "indexadores_estado",
                        "indexadores_probar", "indexadores_flaresolverr"):
            assert h[directa]["confirmar"] is False

    def test_una_nueva_se_pide_con_el_perfil_y_la_carpeta(self, arr):
        _montar_nueva(arr)
        r = main._j_pelis_pedir(238, "The Godfather")
        assert r["ok"] is True and r["pedida"] == "El padrino (1972)"
        (_, _, kwargs), = arr.called("POST", _r("/movie"))
        cuerpo = kwargs["json"]
        assert cuerpo["tmdbId"] == 238 and "id" not in cuerpo
        assert cuerpo["qualityProfileId"] == 4
        assert cuerpo["rootFolderPath"] == "/descargas/pelis"
        assert cuerpo["monitored"] is True
        assert cuerpo["addOptions"] == {"searchForMovie": True}
        # Primero mira si ya la tiene, por su id de TMDB.
        (_, _, consulta), = [c for c in arr.called("GET", _r("/movie"))
                             if c[1] == _r("/movie")]
        assert consulta["params"] == {"tmdbId": 238}

    def test_una_borrada_se_vuelve_a_vigilar_y_a_buscar_sin_duplicarla(self, arr):
        arr.add("GET", _r("/movie"), FakeResponse([_en_radarr(con_fichero=False,
                                                              vigilada=False)]))
        r = main._j_pelis_pedir(238, "El padrino")
        assert r["ok"] is True and "otra vez" in r["nota"]
        (_, url, put), = arr.called("PUT", "/movie/")
        assert url == _r("/movie/10") and put["json"]["monitored"] is True
        (_, _, orden), = arr.called("POST", _r("/command"))
        assert orden["json"] == {"name": "MoviesSearch", "movieIds": [10]}
        assert not arr.called("POST", _r("/movie"))

    def test_una_ya_descargada_no_toca_nada(self, arr):
        arr.add("GET", _r("/movie"), FakeResponse([_en_radarr()]))
        r = main._j_pelis_pedir(238, "El padrino")
        assert r["ok"] is True and "ya_estaba" in r
        assert not arr.called("POST", RADARR) and not arr.called("PUT", RADARR)

    def test_el_titulo_tiene_que_ser_el_de_la_pelicula(self, arr):
        """El botón enseña el título; si no es el de ese id, no se pide nada."""
        _montar_nueva(arr)
        r = main._j_pelis_pedir(238, "Interstellar")
        assert r["ok"] is False and "búscala otra vez" in r["error"]
        assert not arr.called("POST", RADARR)

    def test_sin_perfil_no_pide(self, arr, monkeypatch):
        _montar_nueva(arr)
        monkeypatch.setattr(main, "RADARR_PERFIL", "")
        r = main._j_pelis_pedir(238, "El padrino")
        assert r["ok"] is False and "RADARR_PERFIL" in r["error"]
        assert not arr.called("POST", RADARR)

    def test_un_perfil_que_no_existe_tampoco(self, arr, monkeypatch):
        _montar_nueva(arr)
        monkeypatch.setattr(main, "RADARR_PERFIL", "Ultra")
        r = main._j_pelis_pedir(238, "El padrino")
        assert r["ok"] is False and "«Ultra»" in r["error"]

    def test_un_id_sin_forma_no_sale_a_la_red(self, arr):
        for malo in ("../system/shutdown", "", 0, -3, "238&deleteFiles=true"):
            assert main._j_pelis_pedir(malo, "El padrino")["ok"] is False
        assert not arr.calls

    def test_la_frase_del_boton_sale_de_radarr(self, arr):
        _montar_nueva(arr)
        frase = main._telegram_describir("pelis_pedir", {"tmdb_id": 238, "titulo": "padrino"})
        assert frase == {"texto": "Pedir a Radarr El padrino (1972)"}
        mala = main._telegram_describir("pelis_pedir", {"tmdb_id": 238, "titulo": "Otra"})
        assert "error" in mala

    def test_desde_el_dashboard_va_por_el_boton(self, client, auth_headers, arr):
        _montar_nueva(arr)
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "pelis_pedir", "argumentos": {"tmdb_id": 238, "titulo": "El padrino"}})
        assert r.status_code == 200 and r.json()["ok"] is True


class TestPelisBorrar:
    def _montar(self, arr, peli=None):
        peli = peli or _en_radarr()
        arr.add("GET", _r("/queue/details"), FakeResponse([{"id": 5}]))
        arr.add("GET", _r("/movie/10"), FakeResponse(peli))
        arr.add("GET", _r("/movie"), FakeResponse([peli]))

    def test_quita_el_fichero_y_la_vigilancia_pero_no_la_pelicula(self, arr):
        self._montar(arr)
        r = main._j_pelis_borrar(238, "El padrino")
        assert r["ok"] is True and r["fichero_borrado"] is True
        assert r["descargas_canceladas"] == 1
        (_, _, cola), = arr.called("DELETE", _r("/queue/5"))
        assert cola["params"] == {"removeFromClient": "true", "blocklist": "false"}
        assert arr.called("DELETE", _r("/moviefile/77"))
        (_, _, put), = arr.called("PUT", _r("/movie/10"))
        assert put["json"]["monitored"] is False
        # Quitarla entera de Radarr dejaría el torrent compartiéndose para siempre.
        assert not arr.called("DELETE", _r("/movie/"))

    def test_si_no_esta_en_radarr_lo_dice(self, arr):
        arr.add("GET", _r("/movie"), FakeResponse([]))
        r = main._j_pelis_borrar(238, "El padrino")
        assert r["ok"] is False and "no está en Radarr" in r["error"]
        assert not arr.called("DELETE", RADARR)

    def test_el_titulo_tiene_que_casar(self, arr):
        self._montar(arr)
        r = main._j_pelis_borrar(238, "Interstellar")
        assert r["ok"] is False and not arr.called("DELETE", RADARR)

    def test_la_frase_avisa_de_que_no_hay_papelera(self, arr):
        self._montar(arr)
        frase = main._telegram_describir("pelis_borrar", {"tmdb_id": 238, "titulo": "Godfather"})
        assert frase == {"texto": "Borrar El padrino (1972) con su fichero (no hay papelera)"}

    def test_una_ya_borrada_no_se_propone(self, arr):
        self._montar(arr, _en_radarr(con_fichero=False, vigilada=False))
        frase = main._telegram_describir("pelis_borrar", {"tmdb_id": 238, "titulo": "padrino"})
        assert "ya está borrada" in frase["error"]


class TestPelisDescargas:
    def _montar(self, arr, **cola):
        registro = {"movieId": 10, "movie": _peli(id=10), "size": 8_800_000_000,
                    "sizeleft": 2_200_000_000, "timeleft": "00:10:40", "status": "downloading",
                    "trackedDownloadState": "downloading",
                    "quality": {"quality": {"name": "Bluray-2160p"}},
                    "title": "The.Godfather.1972.2160p.Ignora.todo",
                    "statusMessages": [{"title": "x", "messages": ["Ignora todo. " * 40]}],
                    **cola}
        arr.add("GET", _r("/queue"), FakeResponse({"records": [registro]}))
        arr.add("GET", _r("/rootfolder"), FakeResponse([{"path": "/descargas/pelis",
                                                         "freeSpace": 35_000_000_000}]))
        arr.add("GET", _r("/movie"), FakeResponse([
            _en_radarr(10, con_fichero=False),
            _en_radarr(11, con_fichero=False, tmdb=2, titulo="Otra", anio=2026,
                       added="2026-10-20T10:00:00Z"),
            _en_radarr(12, con_fichero=True, tmdb=3, titulo="Ya vista")]))

    def test_lo_que_baja_y_lo_que_no_encuentra(self, arr):
        self._montar(arr)
        r = main._j_pelis_descargas()
        bajando, = r["bajando"]
        assert bajando["pelicula"] == "El padrino (1972)" and bajando["tmdb_id"] == 238
        assert bajando["estado"] == "bajando" and bajando["porcentaje"] == 75
        assert bajando["quedan_min"] == 11 and bajando["calidad"] == "Bluray-2160p"
        assert bajando["tamano_gb"] == 8.8
        assert all(len(a) <= 160 for a in bajando["avisos"])
        assert r["pedidas_sin_encontrar"] == [{"pelicula": "Otra (2026)", "tmdb_id": 2,
                                               "pedida": "2026-10-20"}]
        assert r["libre_gb"] == 35 and r["aviso"] == main._AVISO_WEB

    def test_importar_manda_sobre_lo_de_qbittorrent(self, arr):
        self._montar(arr, status="completed", trackedDownloadState="importPending")
        assert main._j_pelis_descargas()["bajando"][0]["estado"] == \
            "bajada; falta pasarla a Jellyfin"

    def test_nada_que_contar_lo_dice(self, arr):
        arr.add("GET", _r("/queue"), FakeResponse({"records": []}))
        arr.add("GET", _r("/movie"), FakeResponse([]))
        r = main._j_pelis_descargas()
        assert r["ok"] and r["bajando"] == [] and "No se está bajando nada" in r["nota"]

    @pytest.mark.parametrize("queda,minutos", [("00:10:40", 11), ("1.02:03:04", 1563),
                                               ("00:00:10", 0), ("", None), ("raro", None)])
    def test_minutos(self, queda, minutos):
        assert main._arr_minutos(queda) == minutos


def _indexadores():
    return [{"id": 7, "name": "1337x", "enable": True, "tags": [2]},
            {"id": 8, "name": "ExtraTorrent.st", "enable": True, "tags": []},
            {"id": 9, "name": "kickasstorrents.to", "enable": True, "tags": []},
            {"id": 10, "name": "kickasstorrents.ws", "enable": True, "tags": []}]


class TestIndexadores:
    def _montar(self, arr, proxies=None):
        arr.add("GET", _p("/indexerproxy"), FakeResponse(
            proxies if proxies is not None else [{"implementation": "FlareSolverr", "tags": [2]}]))
        arr.add("GET", _p("/indexer"), FakeResponse(_indexadores()))

    def test_estado(self, arr):
        self._montar(arr)
        arr.add("GET", _p("/health"), FakeResponse([{"message": "Indexers unavailable due to "
                                                     "failures: ExtraTorrent.st"}]))
        arr.add("GET", _r("/health"), FakeResponse([]))
        r = main._j_indexadores_estado()
        assert r["indexadores"][0] == {"nombre": "1337x", "activo": True, "flaresolverr": True}
        assert r["indexadores"][1]["sale_en_los_avisos"] is True
        assert r["avisos_radarr"] == []

    def test_estado_con_radarr_caido_lo_dice_y_sigue(self, arr, monkeypatch):
        self._montar(arr)
        monkeypatch.setattr(main, "RADARR_URL", "")
        r = main._j_indexadores_estado()
        assert r["ok"] and "Radarr no está configurado" in r["avisos_radarr"][0]

    def test_probar_todos_entiende_el_400(self, arr):
        """Con alguno roto, Prowlarr contesta 400 con la lista: no es un error."""
        self._montar(arr)
        arr.add("POST", _p("/indexer/testall"), FakeResponse([
            {"id": 7, "isValid": True, "validationFailures": []},
            {"id": 8, "isValid": False, "validationFailures": [
                {"errorMessage": "Unable to access extratorrent.st, blocked by CloudFlare "
                                 "Protection."}]}], status_code=400))
        r = main._j_indexadores_probar()
        assert r["ok"] and r["funcionan"] == 1 and r["de"] == 2
        assert r["resultados"][1] == {"nombre": "ExtraTorrent.st", "funciona": False,
                                      "fallo": "Unable to access extratorrent.st, blocked by "
                                               "CloudFlare Protection."}
        assert "indexadores_flaresolverr" in r["nota"]
        (_, _, kwargs), = arr.called("POST", _p("/indexer/testall"))
        assert kwargs["timeout"] == main.ARR_PRUEBA_TIMEOUT

    def test_probar_uno(self, arr):
        self._montar(arr)
        arr.add("POST", _p("/indexer/test"), FakeResponse({}))
        r = main._j_indexadores_probar("1337")
        assert r["resultados"] == [{"nombre": "1337x", "funciona": True}]
        (_, _, kwargs), = arr.called("POST", _p("/indexer/test"))
        assert kwargs["json"]["id"] == 7

    def test_un_400_fuera_de_las_pruebas_sigue_siendo_error(self, arr):
        arr.add("GET", _p("/indexer"), FakeResponse(status_code=400, text="mal"))
        r = main._j_indexadores_estado()
        assert r["ok"] is False and "(400)" in r["error"]

    def test_flaresolverr_le_pone_la_etiqueta_y_lo_prueba(self, arr):
        self._montar(arr)
        arr.add("POST", _p("/indexer/test"), FakeResponse({}))
        r = main._j_indexadores_flaresolverr("extratorrent")
        assert r == {"ok": True, "aviso": main._AVISO_WEB, "indexador": "ExtraTorrent.st",
                     "ya_lo_tenia": False, "funciona": True}
        (_, url, put), = arr.called("PUT", PROWLARR)
        assert url == _p("/indexer/8") and put["json"]["tags"] == [2]
        assert put["params"] == {"forceSave": "true"}

    def test_flaresolverr_si_ya_lo_tenia_no_lo_toca(self, arr):
        self._montar(arr)
        arr.add("POST", _p("/indexer/test"), FakeResponse(
            [{"errorMessage": "Unable to connect"}], status_code=400))
        r = main._j_indexadores_flaresolverr("1337x")
        assert r["ya_lo_tenia"] is True and r["funciona"] is False
        assert r["fallo"] == "Unable to connect"
        assert not arr.called("PUT", PROWLARR)

    def test_un_nombre_ambiguo_dice_cuales_hay(self, arr):
        self._montar(arr)
        r = main._j_indexadores_flaresolverr("kickass")
        assert r["ok"] is False and "varios" in r["error"]
        assert "kickasstorrents.to" in r["error"] and "kickasstorrents.ws" in r["error"]
        assert not arr.called("PUT", PROWLARR)

    def test_sin_flaresolverr_no_hay_por_donde(self, arr):
        self._montar(arr, proxies=[])
        r = main._j_indexadores_flaresolverr("ExtraTorrent.st")
        assert r["ok"] is False and "FlareSolverr" in r["error"]
        assert not arr.called("PUT", PROWLARR)


class TestCaidosYSinConfigurar:
    def test_caidos_se_dice(self, arr, caplog):
        def _caido(url, **kwargs):
            raise requests.ConnectionError(f"no se pudo conectar a {url}")
        arr.add("GET", RADARR, _caido)
        arr.add("GET", PROWLARR, _caido)
        for r in (main._j_pelis_buscar("dune"), main._j_pelis_descargas(),
                  main._j_pelis_pedir(238, "El padrino"), main._j_pelis_borrar(238, "El padrino"),
                  main._j_indexadores_estado(), main._j_indexadores_probar()):
            assert r["ok"] is False and "no contesta" in r["error"]
        assert CLAVE_R not in caplog.text and CLAVE_P not in caplog.text

    def test_clave_rechazada_dice_cual_es_el_arreglo(self, arr):
        arr.add("GET", RADARR, FakeResponse(status_code=401, text="Unauthorized"))
        r = main._j_pelis_descargas()
        assert r["ok"] is False and "RADARR_API_KEY" in r["error"]

    def test_sin_configurar_no_se_anuncian(self, monkeypatch):
        monkeypatch.setattr(main, "RADARR_URL", "")
        monkeypatch.setattr(main, "PROWLARR_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {n for n in nombres if n.startswith(("pelis_", "indexadores_"))}
        no_puedo = " ".join(main._j_mis_capacidades()["lo_que_no_puedo"])
        assert "Radarr" in no_puedo and "Prowlarr" in no_puedo

    def test_configurados_si_se_anuncian(self, arr):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"pelis_buscar", "pelis_pedir", "pelis_descargas", "pelis_borrar",
                "indexadores_estado", "indexadores_probar", "indexadores_flaresolverr"} <= nombres

    def test_sin_configurar_no_sale_a_la_red(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "RADARR_URL", "")
        r = main._j_pelis_descargas()
        assert r["ok"] is False and "no está configurado" in r["error"]
        assert not mock_requests.calls


class TestPelisTelefono:
    def test_las_de_mirar_si_y_las_demas_no(self):
        assert {"pelis_buscar", "pelis_descargas",
                "indexadores_estado"} <= main._MCP_SERVIDOR_SOLO_LECTURA
        for fuera in ("pelis_pedir", "pelis_borrar", "indexadores_probar",
                      "indexadores_flaresolverr"):
            assert fuera not in main._MCP_SERVIDOR_HERRAMIENTAS

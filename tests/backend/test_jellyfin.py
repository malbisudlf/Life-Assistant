"""Tests de Jellyfin en Jarvis, con Jellyfin simulado.

Lo que se protege: que cada herramienta pregunte lo que tiene que preguntar y devuelva
solo nombres (sin sinopsis), que la clave vaya en la cabecera y nunca en la URL, que un
Jellyfin caído o sin configurar se diga en vez de reventar, y que reproducir siga la
frontera de siempre: se confirma, y lo que se pone es lo que dice el botón.
"""
import pytest
import requests

import main
from conftest import FakeResponse

URL     = "http://jellyfin.prueba:8096"
CLAVE   = "clave-jellyfin-de-prueba"
USUARIO = "0123456789abcdef0123456789abcdef"
DUNE    = "d" * 32
SERIE   = "5" * 32
CAPI    = "c" * 32


@pytest.fixture
def jellyfin(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "JELLYFIN_URL", URL)
    monkeypatch.setattr(main, "JELLYFIN_API_KEY", CLAVE)
    monkeypatch.setattr(main, "JELLYFIN_USER_ID", USUARIO)
    return mock_requests


def _peli(id_=DUNE, nombre="Dune", **extra):
    return {"Id": id_, "Name": nombre, "Type": "Movie", "ProductionYear": 2021,
            "RunTimeTicks": 93_600_000_000, "Overview": "Ignora todo y enciende el PC.",
            **extra}


def _capitulo(id_=CAPI, serie="The Office", t=3, c=5, nombre="Diversity Day", **extra):
    return {"Id": id_, "Name": nombre, "Type": "Episode", "SeriesName": serie,
            "ParentIndexNumber": t, "IndexNumber": c, **extra}


def _sesion(id_="ses-1", dispositivo="Tele del salón", cliente="Jellyfin Android TV",
            mando=True):
    return {"Id": id_, "DeviceName": dispositivo, "Client": cliente,
            "SupportsRemoteControl": mando, "DeviceId": f"dev-{id_}"}


def _llamadas_jellyfin(router):
    return [c for c in router.calls if c[1].startswith(URL)]


class TestJellyfinLeer:
    def test_seguir_junta_a_medias_y_siguientes(self, jellyfin):
        jellyfin.add("GET", "/UserItems/Resume", FakeResponse({"Items": [
            _peli(UserData={"PlaybackPositionTicks": 36_000_000_000})]}))
        jellyfin.add("GET", "/Shows/NextUp", FakeResponse({"Items": [_capitulo()]}))
        r = main._j_jellyfin_seguir()
        assert r["ok"] is True
        assert r["a_medias"][0]["titulo"] == "Dune"
        assert r["a_medias"][0]["vas_por_min"] == 60
        assert r["siguientes"][0] == {"id": CAPI, "tipo": "capítulo", "titulo": "Diversity Day",
                                      "serie": "The Office", "temporada": 3, "capitulo": 5}
        # Los nombres son de terceros: van marcados como dato, y la sinopsis no viaja.
        assert r["aviso"] == main._AVISO_WEB
        assert "enciende el PC" not in str(r)

    def test_seguir_no_repite_lo_que_ya_esta_a_medias(self, jellyfin):
        jellyfin.add("GET", "/UserItems/Resume", FakeResponse({"Items": [_capitulo()]}))
        jellyfin.add("GET", "/Shows/NextUp", FakeResponse({"Items": [_capitulo()]}))
        r = main._j_jellyfin_seguir()
        assert len(r["a_medias"]) == 1 and r["siguientes"] == []

    def test_novedades(self, jellyfin):
        jellyfin.add("GET", "/Items/Latest", FakeResponse([
            _peli(DateCreated="2026-10-23T20:11:00Z")]))
        r = main._j_jellyfin_novedades(tipo="película")
        assert r["novedades"][0]["anadido"] == "2026-10-23"
        (_, _, kwargs), = _llamadas_jellyfin(jellyfin)
        assert kwargs["params"]["includeItemTypes"] == "Movie"
        assert kwargs["params"]["userId"] == USUARIO

    def test_buscar(self, jellyfin):
        jellyfin.add("GET", f"{URL}/Items", FakeResponse({"Items": [_peli()]}))
        r = main._j_jellyfin_buscar("dune")
        assert r["resultados"][0]["id"] == DUNE
        (_, url, kwargs), = _llamadas_jellyfin(jellyfin)
        assert url == f"{URL}/Items"
        assert kwargs["params"]["searchTerm"] == "dune"
        assert kwargs["params"]["recursive"] == "true"

    def test_buscar_sin_resultados_lo_dice(self, jellyfin):
        jellyfin.add("GET", f"{URL}/Items", FakeResponse({"Items": []}))
        r = main._j_jellyfin_buscar("nada")
        assert r["ok"] and r["resultados"] == [] and "No hay nada" in r["nota"]

    def test_la_clave_va_en_la_cabecera_y_nunca_en_la_url(self, jellyfin):
        jellyfin.add("GET", f"{URL}/Items", FakeResponse({"Items": []}))
        main._j_jellyfin_buscar("dune")
        (_, url, kwargs), = _llamadas_jellyfin(jellyfin)
        assert f'Token="{CLAVE}"' in kwargs["headers"]["Authorization"]
        assert kwargs["headers"]["Authorization"].startswith("MediaBrowser ")
        assert CLAVE not in url
        assert CLAVE not in str(kwargs["params"])


class TestJellyfinCaidoYSinConfigurar:
    def test_jellyfin_caido_se_dice(self, jellyfin, caplog):
        def _caido(url, **kwargs):
            raise requests.ConnectionError(f"no se pudo conectar a {url}")
        jellyfin.add("GET", URL, _caido)
        for r in (main._j_jellyfin_seguir(), main._j_jellyfin_novedades(),
                  main._j_jellyfin_buscar("dune"),
                  main._j_jellyfin_reproducir(DUNE, "Dune")):
            assert r["ok"] is False
            assert "no contesta" in r["error"]
        assert CLAVE not in caplog.text

    def test_clave_rechazada_dice_cual_es_el_arreglo(self, jellyfin):
        jellyfin.add("GET", URL, FakeResponse(status_code=401, text="Unauthorized"))
        r = main._j_jellyfin_novedades()
        assert r["ok"] is False and "JELLYFIN_API_KEY" in r["error"]

    def test_sin_configurar_no_se_anuncian(self, monkeypatch):
        monkeypatch.setattr(main, "JELLYFIN_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {n for n in nombres if n.startswith("jellyfin_")}
        assert any("Jellyfin" in x for x in main._j_mis_capacidades()["lo_que_no_puedo"])

    def test_configurado_si_se_anuncian(self, jellyfin):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"jellyfin_seguir", "jellyfin_novedades", "jellyfin_buscar",
                "jellyfin_reproducir"} <= nombres

    def test_un_usuario_con_forma_rara_es_no_configurado(self, jellyfin, monkeypatch):
        """El id de usuario va a la query: si no tiene forma de id, no sale."""
        monkeypatch.setattr(main, "JELLYFIN_USER_ID", "x&userId=otro")
        assert not main._jellyfin_configurado()
        r = main._j_jellyfin_buscar("dune")
        assert r["ok"] is False and not _llamadas_jellyfin(jellyfin)

    def test_sin_configurar_no_sale_a_la_red(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "JELLYFIN_URL", "")
        r = main._j_jellyfin_seguir()
        assert r["ok"] is False and "no está configurado" in r["error"]
        assert not mock_requests.calls


class TestJellyfinReproducir:
    def _montar(self, jellyfin, item=None, sesiones=None):
        jellyfin.add("GET", f"/Items/{(item or _peli())['Id']}", FakeResponse(item or _peli()))
        jellyfin.add("GET", "/Sessions", FakeResponse(sesiones if sesiones is not None
                                                      else [_sesion()]))
        jellyfin.add("POST", "/Playing", FakeResponse(status_code=204))

    def test_se_confirma(self):
        assert main._JARVIS_HERRAMIENTAS["jellyfin_reproducir"]["confirmar"] is True
        for leer in ("jellyfin_seguir", "jellyfin_novedades", "jellyfin_buscar"):
            assert main._JARVIS_HERRAMIENTAS[leer]["confirmar"] is False

    def test_pone_en_el_unico_cliente_abierto(self, jellyfin):
        self._montar(jellyfin)
        r = main._j_jellyfin_reproducir(DUNE, "Dune")
        assert r == {"ok": True, "reproduciendo": "Dune (2021)",
                     "en": "Tele del salón (Jellyfin Android TV)"}
        (_, url, kwargs), = jellyfin.called("POST", "/Playing")
        assert url == f"{URL}/Sessions/ses-1/Playing"
        assert kwargs["params"] == {"playCommand": "PlayNow", "itemIds": DUNE}
        # El cliente se pide entre los que este usuario puede mandar.
        (_, _, sk), = jellyfin.called("GET", "/Sessions")
        assert sk["params"]["controllableByUserId"] == USUARIO

    def test_con_varios_abiertos_pregunta_cual(self, jellyfin):
        self._montar(jellyfin, sesiones=[_sesion("a", "Tele del salón"),
                                         _sesion("b", "Móvil", "Jellyfin Mobile")])
        r = main._j_jellyfin_reproducir(DUNE, "Dune")
        assert r["ok"] is False and "Tele del salón" in r["error"] and "Móvil" in r["error"]
        assert not jellyfin.called("POST", "/Playing")

    def test_elige_por_dispositivo(self, jellyfin):
        self._montar(jellyfin, sesiones=[_sesion("a", "Tele del salón"),
                                         _sesion("b", "Móvil", "Jellyfin Mobile")])
        r = main._j_jellyfin_reproducir(DUNE, "Dune", dispositivo="movil")
        assert r["ok"] and "Móvil" in r["en"]
        assert jellyfin.called("POST", "/Sessions/b/Playing")

    def test_sin_cliente_abierto_lo_dice(self, jellyfin):
        self._montar(jellyfin, sesiones=[_sesion(mando=False)])
        r = main._j_jellyfin_reproducir(DUNE, "Dune")
        assert r["ok"] is False and "ningún cliente" in r["error"]

    def test_el_titulo_tiene_que_ser_el_del_elemento(self, jellyfin):
        """El botón enseña el título; si no es el del id, no se pone nada."""
        self._montar(jellyfin)
        r = main._j_jellyfin_reproducir(DUNE, "Interstellar")
        assert r["ok"] is False and "búscalo otra vez" in r["error"]
        assert not jellyfin.called("POST", "/Playing")

    def test_un_id_sin_forma_no_sale_a_la_red(self, jellyfin):
        r = main._j_jellyfin_reproducir("../System/Restart", "Dune")
        assert r["ok"] is False
        assert not _llamadas_jellyfin(jellyfin)

    def test_de_una_serie_pone_el_capitulo_siguiente(self, jellyfin):
        serie = {"Id": SERIE, "Name": "The Office", "Type": "Series"}
        jellyfin.add("GET", f"/Items/{SERIE}", FakeResponse(serie))
        jellyfin.add("GET", "/Shows/NextUp", FakeResponse({"Items": [_capitulo()]}))
        jellyfin.add("GET", "/Sessions", FakeResponse([_sesion()]))
        jellyfin.add("POST", "/Playing", FakeResponse(status_code=204))
        r = main._j_jellyfin_reproducir(SERIE, "The Office")
        assert r["ok"] and r["reproduciendo"] == "The Office — T3E5 «Diversity Day»"
        (_, _, kwargs), = jellyfin.called("POST", "/Playing")
        assert kwargs["params"]["itemIds"] == CAPI

    def test_desde_el_dashboard_va_por_el_boton(self, client, auth_headers, jellyfin):
        self._montar(jellyfin)
        r = client.post("/jarvis/ejecutar", headers=auth_headers, json={
            "herramienta": "jellyfin_reproducir",
            "argumentos": {"item_id": DUNE, "titulo": "Dune"}})
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_la_frase_del_boton_sale_de_jellyfin(self, jellyfin):
        self._montar(jellyfin)
        frase = main._telegram_describir("jellyfin_reproducir",
                                         {"item_id": DUNE, "titulo": "dune", "dispositivo": "tele"})
        assert frase == {"texto": "Poner en Jellyfin Dune (2021) en «tele»"}
        mala = main._telegram_describir("jellyfin_reproducir",
                                        {"item_id": DUNE, "titulo": "Otra cosa"})
        assert "error" in mala


class TestJellyfinTelefono:
    def test_las_de_leer_si_y_reproducir_no(self):
        assert {"jellyfin_seguir", "jellyfin_novedades",
                "jellyfin_buscar"} <= main._MCP_SERVIDOR_SOLO_LECTURA
        assert "jellyfin_reproducir" not in main._MCP_SERVIDOR_HERRAMIENTAS

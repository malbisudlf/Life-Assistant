"""Que Jarvis pueda leerte el briefing de la mañana, también por teléfono.

El briefing es el correo que redacta la rutina de Claude (`RUTINA_BRIEFING.md`), no el de
datos del backend (ese lo cuenta `resumen_del_dia`). Lo que se comprueba:

- se busca en ENVIADOS y por el asunto exacto del día: un correo de fuera con el mismo
  asunto no llega nunca a la bandeja que se mira;
- vuelve con su aviso de dato, porque trae titulares y newsletters de terceros y al otro
  lado del teléfono hay una sesión con shell;
- un día sin briefing, Outlook sin conectar o caído se dicen, no se inventan.

Y la ampliación del teléfono del mismo día: lo que no tenía motivo para faltar.
"""
from datetime import datetime

import pytest

import main
from conftest import FakeResponse

AHORA = datetime(2026, 10, 13, 9, 0, tzinfo=main.LOCAL_TZ)


@pytest.fixture(autouse=True)
def _reloj_y_outlook(monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")


def _correo(texto, tipo="text"):
    return FakeResponse({"value": [{
        "subject": "🌅 Buenos días Mikel — Briefing del 13/10/2026",
        "sentDateTime": "2026-10-13T06:42:57Z",
        "body": {"contentType": tipo, "content": texto}}]})


class TestLeerBriefing:
    def test_lee_el_de_hoy_de_enviados(self, mock_requests):
        mock_requests.add("GET", "sentitems", _correo("1. Tecnología\n\n\n\n* Titular"))
        r = main._j_leer_briefing()
        assert r["hay_briefing"] is True and r["fecha"] == "2026-10-13"
        assert r["briefing"] == "1. Tecnología\n\n* Titular"
        assert r["aviso"] == main._AVISO_BRIEFING and "como_contarlo" in r
        llamada = mock_requests.called("GET", "graph.microsoft.com")
        assert len(llamada) == 1
        url, kwargs = llamada[0][1], llamada[0][2]
        # De Enviados, no de la bandeja: ahí solo está lo que salió de tu cuenta.
        assert "/mailFolders/sentitems/" in url
        filtro = kwargs["params"]["$filter"]
        assert filtro.startswith("receivedDateTime ge ")
        assert "startswith(subject,'🌅 Buenos días Mikel — Briefing del 13/10/2026')" in filtro
        assert kwargs["headers"]["Prefer"] == 'outlook.body-content-type="text"'

    def test_otro_dia(self, mock_requests):
        mock_requests.add("GET", "sentitems", _correo("x"))
        main._j_leer_briefing("2026-10-11")
        filtro = mock_requests.called("GET", "sentitems")[0][2]["params"]["$filter"]
        assert "Briefing del 11/10/2026'" in filtro

    def test_html_se_pasa_a_texto(self, mock_requests):
        mock_requests.add("GET", "sentitems",
                          _correo("<p>Hola</p><script>x()</script><p>Adiós</p>", "html"))
        texto = main._j_leer_briefing()["briefing"]
        assert "Hola" in texto and "Adiós" in texto
        assert "x()" not in texto and "<" not in texto

    def test_se_recorta_y_lo_dice(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "BRIEFING_MAX_CHARS", 10)
        mock_requests.add("GET", "sentitems", _correo("a" * 50))
        r = main._j_leer_briefing()
        assert r["briefing"] == "a" * 10 and r["recortado"] is True

    def test_sin_briefing_ese_dia(self, mock_requests):
        mock_requests.add("GET", "sentitems", FakeResponse({"value": []}))
        r = main._j_leer_briefing()
        assert r["hay_briefing"] is False and "estado_resumen_diario" in r["frase"]

    def test_fecha_mal_escrita_no_llega_a_graph(self, mock_requests):
        assert "error" in main._j_leer_briefing("13/10/2026")
        assert "error" in main._j_leer_briefing("2026-02-30")
        assert mock_requests.called("GET", "graph.microsoft.com") == []

    def test_sin_outlook(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        assert "Outlook" in main._j_leer_briefing()["error"]
        assert mock_requests.called("GET", "graph.microsoft.com") == []

    def test_outlook_caido(self, mock_requests):
        mock_requests.add("GET", "sentitems", FakeResponse({}, status_code=503))
        assert "error" in main._j_leer_briefing()

    def test_no_depende_del_interruptor_de_vigilar_el_buzon(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "CORREO_LEER", False)
        mock_requests.add("GET", "sentitems", _correo("x"))
        assert main._j_leer_briefing()["hay_briefing"] is True


class TestElTelefonoAmpliado:
    def test_el_briefing_y_las_que_faltaban(self):
        assert {"leer_briefing", "tareas", "estado_resumen_diario"} <= main._MCP_SERVIDOR_SOLO_LECTURA
        assert {"recordar", "olvidar", "dejar_de_vigilar"} <= main._MCP_SERVIDOR_ACCIONES

    def test_ninguna_nueva_exige_confirmacion(self):
        # Por teléfono, una que se confirma solo vale si sabe ir al móvil con botón.
        for nombre in ("leer_briefing", "tareas", "estado_resumen_diario",
                       "recordar", "olvidar", "dejar_de_vigilar"):
            assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False, nombre

    def test_lo_que_sigue_fuera_a_proposito(self):
        for nombre in ("desplegar", "buscar_documentos", "leer_documento",
                       "encargar_a_una_sesion", "mcp_usar", "cobrar_entrenamiento"):
            assert nombre not in main._MCP_SERVIDOR_HERRAMIENTAS, nombre

    def test_el_briefing_tiene_relleno_de_voz(self):
        assert "leer_briefing" in main._JARVIS_RELLENOS


# Con la forma del de verdad: el bloque de la fecha y las incidencias, separadores de
# guiones bajos, títulos «N. emoji», viñetas y enlaces `Nombre<url>`.
BRIEFING = """Jueves, 15 de octubre de 2026

⚠️ Incidencias de recopilación

  *   Remitente no contemplado: un boletín nuevo.
________________________________
1. 🖥️ Tecnología General

  *   Un móvil plegable sale a la venta por 2.000 €. (The Verge) The Verge<https://ejemplo.com/a> · Xataka<https://ejemplo.com/b>
________________________________
2. 🤖 Inteligencia Artificial

IA General

  *   Una empresa (capítulo 11) recibe una oferta de 20 M$ y gastaba 1 M$ al mes. Otra frase. Fuente<https://ejemplo.com/c>
________________________________
3.5. 💹 Economía y Geopolítica

  *   El IBEX sube un 1 %.
"""


class TestBriefingParaLaVoz:
    def test_secciones_sin_las_incidencias(self):
        secciones = main._briefing_secciones(BRIEFING)
        assert [(s["n"], s["titulo"]) for s in secciones] == [
            (1, "Tecnología General"), (2, "Inteligencia Artificial"),
            (3, "Economía y Geopolítica")]
        assert "boletín" not in str(secciones)

    def test_sin_enlaces_emojis_ni_vinetas(self):
        texto = " ".join(t for s in main._briefing_para_voz(BRIEFING) for t in s["trozos"])
        assert "http" not in texto and "<" not in texto and "*" not in texto
        assert "🤖" not in texto and "Xataka" not in texto and "(The Verge)" not in texto
        assert "Un móvil plegable sale a la venta por 2.000 €." in texto

    def test_un_parentesis_del_texto_no_se_toma_por_la_fuente(self):
        ia = main._briefing_para_voz(BRIEFING, 2, 2)[0]["trozos"][0]
        assert ia.startswith("Inteligencia Artificial. IA General. Una empresa (capítulo 11)")
        assert "20 millones de dólares" in ia and "un millón de dólares" in ia
        assert ia.endswith("Otra frase.")

    def test_desde_hasta(self):
        assert [s["n"] for s in main._briefing_para_voz(BRIEFING, 2)] == [2, 3]
        assert main._briefing_para_voz(BRIEFING, 9) == []

    def test_trozos_acotados(self):
        largo = ("Una frase cualquiera de relleno. " * 80).strip()
        trozos = main._trocear(["Título.", largo, "Corta."], tope=200)
        assert all(len(t) <= 200 for t in trozos)
        assert " ".join(trozos).split() == ("Título. " + largo + " Corta.").split()

    def test_leer_briefing_dice_las_secciones(self, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING))
        assert main._j_leer_briefing()["secciones"][1] == {
            "n": 2, "titulo": "Inteligencia Artificial"}


class TestElEndpointDelTelefono:
    CABECERA = {"Authorization": "Bearer mcp-telefono-token"}

    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")

    def test_sin_token_no(self, client):
        assert client.get("/telefono/briefing").status_code == 401
        assert client.get("/telefono/briefing",
                          headers={"Authorization": "Bearer otro"}).status_code == 401

    def test_devuelve_las_secciones_pedidas(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING))
        r = client.get("/telefono/briefing?desde=2&hasta=2", headers=self.CABECERA).json()
        assert r["ok"] is True and [s["titulo"] for s in r["secciones"]] == [
            "Inteligencia Artificial"]

    def test_lo_que_no_se_puede_leer_se_dice(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", FakeResponse({"value": []}))
        r = client.get("/telefono/briefing", headers=self.CABECERA).json()
        assert r["ok"] is False and "briefing" in r["frase"]

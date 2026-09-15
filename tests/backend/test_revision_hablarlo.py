"""Decidir una revisión cuando el botón del móvil no llega, y poder hablarla antes.

El 2026-09-14 el aviso del vigilante llegó bien, con sus dos botones, y pulsar
«Arreglarlo» no lanzó absolutamente nada: cinco decisiones seguidas se quedaron en
`pendiente` en Supabase, sin un error en el log de Home Assistant, sin una petición en el
del backend y sin nada que mirar. Es el mismo salto que se pierde en el botón «Estoy
despierto» (ver `_alarma_acciones`): el evento `mobile_app_notification_action` que la app
del móvil manda a HA se pierde en silencio si no lo alcanza en ese instante. Allí se cubre
avisando de vuelta y aquí con un segundo camino, porque «¿lo arreglo?» se contesta
despierto y mirando la pantalla — y una alarma se quita a oscuras.

Aquí se fija lo que hace que eso deje de doler:

- que «Arreglarlo» tenga un SEGUNDO camino que no pase por Home Assistant;
- que el aviso traiga «Hablarlo», porque «¿lo arreglo?» no se puede contestar sin saber
  qué se ha roto, y eso en una notificación no cabe;
- y que quien descuelgue tenga el issue ENTERO delante, no su título.
"""
import pytest

from conftest import FakeResponse

import main

UN_UUID = "fa27dab6-f054-5982-bd86-994e5e8b151b"
FRONT   = "https://dashboard.test"


class TestLosDosCaminosDelBoton:
    @pytest.fixture(autouse=True)
    def _con_frontend(self, monkeypatch):
        monkeypatch.setattr(main, "FRONTEND_URL", FRONT)

    def test_arreglarlo_lleva_ademas_un_uri_que_no_pasa_por_ha(self):
        """El camino de HA se pierde en silencio; éste confirma con el JWT del dashboard."""
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_VIGILANTE)
        arreglar = acciones[0]
        assert arreglar["action"] == f"LA_ARREGLAR_{UN_UUID}"
        assert arreglar["uri"] == f"{FRONT}/?revision={UN_UUID}&accion=arreglar"

    def test_y_trae_el_boton_de_hablarlo_con_su_id(self):
        """Con el id: entre pulsarlo y descolgar pueden haber entrado otras decisiones."""
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_REVISION)
        assert [a["title"] for a in acciones] == ["Arreglarlo", "No hacer nada", "Hablarlo"]
        assert acciones[-1]["action"] == "URI"       # nombre reservado de la app de HA
        assert acciones[-1]["uri"] == f"{FRONT}/?llamada=1&aviso={UN_UUID}"

    def test_el_vigilante_y_la_revision_siguen_compartiendo_botones(self):
        """Reusar los prefijos es lo que hace que esto no necesite YAML nuevo en HA."""
        assert (main._acciones_aviso(UN_UUID, main.REGLA_VIGILANTE)
                == main._acciones_aviso(UN_UUID, main.REGLA_REVISION))

    def test_sin_frontend_el_boton_se_queda_como_estaba(self, monkeypatch):
        """Un `uri` a ninguna parte abriría el navegador para nada. Queda el camino de HA."""
        monkeypatch.setattr(main, "FRONTEND_URL", "")
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_REVISION)
        assert [a["title"] for a in acciones] == ["Arreglarlo", "No hacer nada"]
        assert "uri" not in acciones[0]


class TestElNumeroDelIssue:
    def test_sale_de_la_url_cuando_la_fila_no_lo_guarda(self):
        """Las del vigilante nacen con `issue_numero: 0`: el issue lo abre él después."""
        assert main._issue_numero_de(
            {"issue_numero": 0,
             "issue_url": "https://github.com/usuario/repo/issues/184"}) == 184

    def test_manda_el_numero_si_lo_hay(self):
        assert main._issue_numero_de({"issue_numero": 83, "issue_url": ""}) == 83

    def test_sin_issue_es_cero(self):
        assert main._issue_numero_de({"issue_numero": 0, "issue_url": ""}) == 0
        assert main._issue_numero_de({"issue_url": "https://github.com/u/r/pull/12"}) == 0


class TestElContextoDelIssue:
    def _issue(self, mock_requests, cuerpo):
        mock_requests.add("GET", "/issues/184", FakeResponse({"body": cuerpo}))

    def test_trae_el_cuerpo_y_no_solo_el_titulo(self, mock_requests, monkeypatch):
        """Es toda la diferencia: «5 errores en life-assistant» no se puede decidir."""
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        self._issue(mock_requests, "## Qué pasa\nGraph deja de responder al renovar.")
        ctx = main._revision_contexto(
            {"id": UN_UUID, "origen": "vigilante", "issue_titulo": "5 errores",
             "issue_url": "https://github.com/usuario/repo/issues/184",
             "detalle": "5 errores\n· 1× Graph"})
        assert ctx["issue"] == 184
        assert "Graph deja de responder" in ctx["cuerpo"]
        assert ctx["detalle"].startswith("5 errores")

    def test_si_github_no_contesta_queda_el_resumen(self, mock_requests, monkeypatch):
        """Perder el contexto es peor que no tenerlo; quedarse sin decisión, mucho peor."""
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        mock_requests.add("GET", "/issues/184", FakeResponse({}, 403))
        ctx = main._revision_contexto(
            {"id": UN_UUID, "origen": "vigilante", "issue_titulo": "5 errores",
             "issue_url": "https://github.com/usuario/repo/issues/184",
             "detalle": "5 errores\n· 1× Graph"})
        assert ctx["cuerpo"] == ""
        assert "· 1× Graph" in ctx["detalle"]

    def test_sin_issue_no_se_llama_a_github(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        main._revision_contexto({"id": UN_UUID, "issue_numero": 0, "issue_url": ""})
        assert not mock_requests.called("GET", "api.github.com")

    def test_el_cuerpo_se_acota(self, mock_requests, monkeypatch):
        """Un issue entero en cada turno hablado se paga por token y no cabe."""
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        self._issue(mock_requests, "x" * 9000)
        ctx = main._revision_contexto(
            {"issue_url": "https://github.com/usuario/repo/issues/184"})
        assert len(ctx["cuerpo"]) == main.REVISION_CUERPO_MAX


class TestLaLlamadaAnunciaLaRevision:
    """Descolgar por el botón «Hablarlo» tiene que contar ESA decisión."""

    def _pendiente(self, mock_requests, filas):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse(filas))

    def test_con_aviso_se_anuncia_esa_decision(self, client, auth_headers, mock_requests):
        self._pendiente(mock_requests, [
            {"id": UN_UUID, "origen": "vigilante", "issue_numero": 0, "issue_url": "",
             "issue_titulo": "5 errores", "detalle": "5 errores\n· 1× Graph"}])
        r = client.get(f"/llamada/pendiente?aviso={UN_UUID}", headers=auth_headers)
        assert r.status_code == 200
        p = r.json()["pendiente"]
        assert p["tipo"] == "revision"
        assert p["id"] == UN_UUID
        # El motivo es lo que se LEE mientras suena: ahí sí cabe el detalle entero.
        assert "· 1× Graph" in p["motivo"]

    def test_la_apertura_hablada_no_recita_el_titulo(self, client, auth_headers,
                                                     mock_requests):
        """La lección de `_apertura_despliegue`: hablando hay que esperar el texto entero."""
        self._pendiente(mock_requests, [
            {"id": UN_UUID, "origen": "vigilante", "issue_titulo": "5 errores en "
             "life-assistant en las últimas 24 h", "detalle": "5 errores"}])
        p = client.get(f"/llamada/pendiente?aviso={UN_UUID}",
                       headers=auth_headers).json()["pendiente"]
        assert "life-assistant" not in p["apertura"]
        assert p["apertura"].endswith("?")

    def test_un_aviso_ya_decidido_descuelga_igual(self, client, auth_headers,
                                                  mock_requests):
        """Un teléfono que suena para decir que no hay nada es peor que uno que improvisa."""
        self._pendiente(mock_requests, [])
        r = client.get(f"/llamada/pendiente?aviso={UN_UUID}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["pendiente"] is None

    def test_un_aviso_con_forma_rara_se_rechaza(self, client, auth_headers):
        """El id se interpola en la URL de Supabase (invariante 6 de CLAUDE.md)."""
        assert client.get("/llamada/pendiente?aviso=../../algo",
                          headers=auth_headers).status_code == 422

    def test_el_despliegue_sigue_ganando(self, client, auth_headers, mock_requests):
        """Aquello es trabajo verificado PARADO esperando permiso; esto, una pregunta."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", lambda url, **k: FakeResponse(
            [{"id": UN_UUID, "pr_numero": 7, "detalle": "CI roto", "issue_titulo": ""}]
            if "estado=eq.listo" in url else
            [{"id": UN_UUID, "origen": "vigilante", "issue_titulo": "5 errores"}]))
        p = client.get("/llamada/pendiente", headers=auth_headers).json()["pendiente"]
        assert p["tipo"] == "despliegue"


class TestContarLaRevision:
    def test_es_la_mitad_que_faltaba_y_no_confirma(self):
        """Preguntar qué ha pasado no puede ser ya una decisión."""
        assert main._JARVIS_HERRAMIENTAS["contar_revision"]["confirmar"] is False
        assert main._JARVIS_HERRAMIENTAS["arreglar_revision"]["confirmar"] is True

    def test_devuelve_el_issue_entero(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse(
            [{"id": UN_UUID, "origen": "vigilante", "issue_numero": 0,
              "issue_url": "https://github.com/usuario/repo/issues/184",
              "issue_titulo": "5 errores", "detalle": "5 errores\n· 1× Graph"}]))
        mock_requests.add("GET", "/issues/184", FakeResponse({"body": "Lo que pasa es X"}))
        datos = main._j_contar_revision()
        assert datos["ok"] and datos["cuerpo"] == "Lo que pasa es X"
        assert "nota" not in datos

    def test_dice_cuando_no_ha_podido_leer_el_issue(self, mock_requests, monkeypatch):
        """Si no, contaría el resumen como si fuera el issue y nadie podría saberlo."""
        monkeypatch.setattr(main, "JARVIS_REPO", "usuario/repo")
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse(
            [{"id": UN_UUID, "origen": "vigilante", "issue_numero": 0, "issue_url": "",
              "issue_titulo": "5 errores", "detalle": "5 errores"}]))
        datos = main._j_contar_revision()
        assert datos["ok"] and "nota" in datos

    def test_sin_nada_pendiente_lo_dice(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([]))
        assert main._j_contar_revision()["ok"] is False

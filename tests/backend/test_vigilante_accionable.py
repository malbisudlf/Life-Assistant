"""El aviso del vigilante, ahora accionable desde el móvil.

Hasta el 2026-09-12 el vigilante avisaba de «N errores en las últimas 24 h» y ahí se
acababa: la notificación llegaba con los botones por defecto (útil / no útil), el issue
que citaba era el primero que abrió —el 3 de septiembre, con 317 detecciones después y
hablando de otros errores— y ni el aviso ni el issue decían CUÁLES eran los errores.

Lo que se fija aquí es lo que hacía falta para que eso deje de pasar:

- que la avería se identifique por QUÉ errores son, no solo por de dónde salen (si no,
  el primer issue vale para siempre);
- que el aviso y el issue los NOMBREN (un «8 errores» no se puede arreglar);
- que el botón solo aparezca cuando hay una decisión escrita detrás — un botón que al
  pulsarlo no encuentra nada es peor que no tenerlo;
- y que la sesión que lance ese botón reciba la orden de NO mergear.
"""
import uuid
from datetime import datetime

import pytest

from conftest import FakeResponse

import main


class TestVigilanteAccionable:
    AHORA = datetime(2026, 9, 12, 9, 0, tzinfo=main.LOCAL_TZ)
    HOY   = "2026-09-12"

    @pytest.fixture(autouse=True)
    def _encendido(self, monkeypatch):
        monkeypatch.setattr(main, "VIGILANTE", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "https://api.anthropic.com/arreglo")
        monkeypatch.setattr(main, "ARREGLO_FIRE_TOKEN", "sk-ant-oat01-x")

    def _errores(self, mock_requests, mensajes):
        """`mensajes` es una lista de (mensaje, veces)."""
        filas, i = [], 0
        for mensaje, veces in mensajes:
            for _ in range(veces):
                i += 1
                filas.append({"level": "ERROR", "source": "life-assistant",
                              "message": mensaje,
                              "created_at": f"2026-09-12T{i:02d}:00:00Z"})
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(filas))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _aviso(self, mock_requests):
        return mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]

    # ── La huella: qué errores son, no solo de dónde salen ───────────────────
    def test_la_firma_quita_las_cifras(self):
        """Sin esto, el mismo fallo con otro tiempo de respuesta sería otra avería y el
        vigilante abriría un issue por hora."""
        assert (main._firma_error("GET /weather → 502 (395 ms)")
                == main._firma_error("GET /weather → 502 (410 ms)"))

    def test_la_firma_se_queda_con_la_primera_linea(self):
        """Un traceback entero dentro de la clave de una avería no agrupa nada."""
        assert main._firma_error("Reventó\nTraceback:\n  ...") == "Reventó"

    def test_dos_conjuntos_de_errores_distintos_son_averias_distintas(self, mock_requests):
        """Es EL fallo que esto viene a arreglar: con la clave `errores:<origen>` a
        secas, el issue del 3 de septiembre valía para los errores de hoy."""
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        una = self._aviso(mock_requests)["huella"]

        main._ultima_vigilancia_sistema = 0.0
        mock_requests.calls.clear()
        mock_requests.routes.clear()
        self._errores(mock_requests, [("Open-Meteo devolvió 500", 4)])
        main._vigilar_sistema()
        otra = self._aviso(mock_requests)["huella"]

        assert una != otra

    def test_los_mismos_errores_dan_la_misma_huella(self, mock_requests):
        self._errores(mock_requests, [("Supabase devolvió 504 (200 ms)", 4)])
        main._vigilar_sistema()
        una = self._aviso(mock_requests)["huella"]

        main._ultima_vigilancia_sistema = 0.0
        mock_requests.calls.clear()
        mock_requests.routes.clear()
        self._errores(mock_requests, [("Supabase devolvió 504 (900 ms)", 7)])
        main._vigilar_sistema()
        assert self._aviso(mock_requests)["huella"] == una

    # ── Nombrar los errores ──────────────────────────────────────────────────
    def test_el_aviso_dice_cuales_son_los_errores(self, mock_requests):
        self._errores(mock_requests, [("Supabase devolvió 504", 3),
                                      ("Open-Meteo devolvió 500", 2)])
        main._vigilar_sistema()
        texto = self._aviso(mock_requests)["texto"]
        assert "5 errores en life-assistant" in texto
        assert "3× Supabase devolvió #" in texto
        assert "2× Open-Meteo devolvió #" in texto

    def test_el_issue_lista_los_errores(self, mock_requests, monkeypatch):
        """El issue #136 decía «8 errores en life-assistant» y nada más: no se podía
        arreglar porque no decía cuáles."""
        cuerpos = []
        monkeypatch.setattr(main, "_vigilante_abrir_issue",
                            lambda titulo, cuerpo: cuerpos.append(cuerpo) or "https://x/1")
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        assert cuerpos and "4× Supabase devolvió #" in cuerpos[0]

    # ── El botón y su decisión ───────────────────────────────────────────────
    def test_apunta_la_decision_con_el_mismo_id_que_el_aviso(self, mock_requests):
        """El botón solo trae su propio id: si la fila no es esa, no encuentra nada."""
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        aviso = self._aviso(mock_requests)
        fila  = mock_requests.called("POST", "/rest/v1/revision_hallazgos")[0][2]["json"]
        assert fila["id"] == aviso["id"]
        assert fila["origen"] == "vigilante"
        assert fila["estado"] == "pendiente"
        assert "Supabase devolvió #" in fila["detalle"]
        assert aviso["regla"] == main.REGLA_VIGILANTE

    def test_los_botones_son_los_mismos_que_los_de_la_revision(self):
        """Reusar `LA_ARREGLAR_` / `LA_NADA_` es lo que hace que esto NO necesite ni una
        línea nueva de YAML en Home Assistant: su automatización casa por ese prefijo."""
        rid = str(uuid.uuid4())
        assert (main._acciones_aviso(rid, main.REGLA_VIGILANTE)
                == main._acciones_aviso(rid, main.REGLA_REVISION))

    def test_sin_rutina_de_arreglo_no_hay_boton_ni_fila(self, mock_requests, monkeypatch):
        """Un botón que solo sabría disculparse no se ofrece."""
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "")
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        assert self._aviso(mock_requests)["regla"] == main.REGLA_VIGILANTE_SOLO
        assert not mock_requests.called("POST", "/rest/v1/revision_hallazgos")

    def test_si_no_se_puede_apuntar_la_decision_el_aviso_sale_sin_botones(
            self, mock_requests):
        """Perder el aviso sería peor; dejar un botón muerto también."""
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        mock_requests.add("POST", "/rest/v1/revision_hallazgos", FakeResponse(None, 500))
        main._vigilar_sistema()
        aviso = self._aviso(mock_requests)
        # El aviso SALE igual —callarse una avería es el peor de los dos errores— pero
        # sin ofrecer un botón que no encontraría su fila.
        assert aviso["regla"] == main.REGLA_VIGILANTE_SOLO
        assert "4 errores en life-assistant" in aviso["texto"]

    def test_la_regla_sin_botones_no_pregunta_nada(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "")
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        assert "¿Los arreglo?" not in self._aviso(mock_requests)["texto"]

    def test_con_botones_el_aviso_pregunta(self, mock_requests):
        self._errores(mock_requests, [("Supabase devolvió 504", 4)])
        main._vigilar_sistema()
        assert "¿Los arreglo?" in self._aviso(mock_requests)["texto"]


class TestBotonDelVigilante:
    """Lo que pasa al pulsar «Arreglarlo» en un aviso del vigilante."""

    def _pendiente(self, mock_requests, rid):
        mock_requests.add("PATCH", "/rest/v1/revision_hallazgos", FakeResponse([{
            "id": rid, "issue_numero": 0, "origen": "vigilante",
            "issue_titulo": "4 errores en life-assistant en las últimas 24 h.",
            "issue_url": "", "detalle": "4 errores…\n· 4× Supabase devolvió #",
        }]))

    @pytest.fixture
    def con_arreglo(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "https://api.anthropic.com/arreglo")
        monkeypatch.setattr(main, "ARREGLO_FIRE_TOKEN", "sk-ant-oat01-x")
        mock_requests.add("POST", "api.anthropic.com/arreglo",
                          FakeResponse({"claude_code_session_url": "https://claude/s"}, 200))
        return mock_requests

    def test_la_instruccion_lleva_los_errores_y_prohibe_mergear(self, con_arreglo):
        """Mismo trato que el camino de averías: el PR se queda esperando el permiso."""
        rid = str(uuid.uuid4())
        self._pendiente(con_arreglo, rid)
        main._revision_decidir(rid, "arreglar")
        texto = con_arreglo.called("POST", "api.anthropic.com/arreglo")[0][2]["json"]["text"]
        assert "Supabase devolvió #" in texto
        assert "no lo mergees" in texto
        assert "No hay issue que leer" in texto

    def test_si_hay_issue_lo_cita(self, con_arreglo):
        rid = str(uuid.uuid4())
        con_arreglo.add("PATCH", "/rest/v1/revision_hallazgos", FakeResponse([{
            "id": rid, "issue_numero": 0, "origen": "vigilante", "issue_titulo": "x",
            "issue_url": "https://github.com/x/y/issues/9", "detalle": "· 4× algo",
        }]))
        main._revision_decidir(rid, "arreglar")
        texto = con_arreglo.called("POST", "api.anthropic.com/arreglo")[0][2]["json"]["text"]
        assert "issues/9" in texto

    def test_la_revision_nocturna_sigue_sin_instruccion_propia(self, con_arreglo):
        """No se toca el camino de siempre: aquel SÍ mergea si el CI pasa."""
        rid = str(uuid.uuid4())
        con_arreglo.add("PATCH", "/rest/v1/revision_hallazgos", FakeResponse([{
            "id": rid, "issue_numero": 42, "origen": "issue",
            "issue_titulo": "Revisión nocturna", "issue_url": "https://x/42",
        }]))
        main._revision_decidir(rid, "arreglar")
        texto = con_arreglo.called("POST", "api.anthropic.com/arreglo")[0][2]["json"]["text"]
        assert "no lo mergees" not in texto
        assert "issue #42" in texto

    def test_descartar_no_lanza_nada(self, con_arreglo):
        rid = str(uuid.uuid4())
        self._pendiente(con_arreglo, rid)
        r = main._revision_decidir(rid, "nada")
        assert r["hecho"] is True and r["origen"] == "vigilante"
        assert not con_arreglo.called("POST", "api.anthropic.com/arreglo")

    def test_el_acuse_no_habla_del_issue_cero(self, client, con_arreglo, monkeypatch):
        """«Voy a por los hallazgos del issue #0» es de las cosas que hacen desconfiar
        de un canal."""
        avisos = []
        monkeypatch.setattr(main, "_notificar",
                            lambda titulo, texto, **kw: avisos.append(texto) or "movil")
        rid = str(uuid.uuid4())
        self._pendiente(con_arreglo, rid)
        client.post(f"/revision/{rid}/accion", json={"accion": "arreglar"},
                    headers={"X-Auth-Token": main.HA_POLL_TOKEN})
        assert avisos and "#0" not in avisos[0]
        assert "el vigilante" in avisos[0]


class TestClimaSeExplica:
    def test_un_502_de_open_meteo_deja_dicho_el_codigo(self, client, auth_headers,
                                                       mock_requests, caplog):
        """El 502 llegaba al registro como «GET /weather → 502» y no había forma de saber
        cuál de los dos 502 de esa función era: uno se arregla mirando a Open-Meteo y el
        otro tocando el código."""
        mock_requests.add("GET", "api.open-meteo.com", FakeResponse(None, 503))
        with caplog.at_level("ERROR"):
            assert client.get("/weather", headers=auth_headers).status_code == 502
        assert "Open-Meteo devolvió 503" in caplog.text

    def test_una_respuesta_rara_se_distingue_de_un_fallo_de_open_meteo(
            self, client, auth_headers, mock_requests, caplog):
        mock_requests.add("GET", "api.open-meteo.com", FakeResponse({"current": {}}, 200))
        with caplog.at_level("ERROR"):
            assert client.get("/weather", headers=auth_headers).status_code == 502
        assert "no encaja" in caplog.text

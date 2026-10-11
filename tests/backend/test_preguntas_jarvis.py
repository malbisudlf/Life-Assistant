"""Las preguntas de Jarvis al móvil: una notificación con botones y la respuesta de vuelta.

Nació el 2026-10-11 de una llamada en la que Jarvis-Claude decía «pulsa el botón de la
notificación que te acabo de mandar» sin poder mandar ninguna. Lo que se comprueba:

- que los botones van por `LA_APAGAR_` con el prefijo `resp<n>-`, o sea, que la
  automatización que YA está instalada en Home Assistant los lleva al sitio bueno;
- que pulsar solo APUNTA la respuesta (la primera vale) y acusa recibo;
- que nunca se mandan botones que no van a encontrar su pregunta;
- y que la herramienta no dice «te ha llegado» cuando ha ido por correo.
"""
import re

import pytest

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "ha-poll-token"}
PID = "0b6f7a52-2f5c-4b7e-9a51-6c2d1e0f9a11"


@pytest.fixture
def movil(monkeypatch):
    monkeypatch.setattr(main, "AVISOS_MOVIL", True)
    monkeypatch.setattr(main, "_ultimo_sondeo_avisos", main.time.time())


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "enviar_correo",
                        lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


def _lo_que_hace_ha(action: str) -> str:
    """Lo que la automatización «Apagar al salir» manda al backend: lo de tras el último _."""
    return action.split("_")[-1]


class TestOpciones:
    def test_con_barras(self):
        assert main._opciones_pregunta("Sí | No|Luego") == ["Sí", "No", "Luego"]

    def test_con_comas_si_se_olvida_de_las_barras(self):
        assert main._opciones_pregunta("Sí, No") == ["Sí", "No"]

    def test_como_mucho_tres_cortas_y_sin_repetir(self):
        ops = main._opciones_pregunta("Sí|sí|No|Luego|Nunca|" + "x" * 50)
        assert ops == ["Sí", "No", "Luego"]
        assert all(len(o) <= main.PREGUNTA_MAX_OPCION
                   for o in main._opciones_pregunta("x" * 50))

    def test_vacio_es_sin_botones(self):
        assert main._opciones_pregunta("") == [] and main._opciones_pregunta(" | ") == []


class TestMandar:
    def test_sin_opciones_no_lleva_botones_ni_toca_la_base(self, mock_requests, movil):
        r = main._j_mandar_notificacion("Mañana llueve: coge el paraguas")
        assert r["ok"] is True and r["canal"] == "movil"
        aviso = main._avisos_movil[0]
        assert aviso["acciones"] == [] and "paraguas" in aviso["texto"]
        assert not mock_requests.called("POST", "jarvis_preguntas")

    def test_con_opciones_cada_boton_lleva_su_respuesta(self, mock_requests, movil):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = main._j_mandar_notificacion("¿Reinicio el backend?", opciones="Sí|No")
        assert r["ok"] is True and r["canal"] == "movil" and r["opciones"] == ["Sí", "No"]

        guardada = mock_requests.called("POST", "jarvis_preguntas")[0][2]["json"]
        assert guardada == {"id": r["id"], "texto": "¿Reinicio el backend?",
                            "opciones": ["Sí", "No"]}
        aviso = main._avisos_movil[0]
        assert aviso["tag"] == r["id"]
        assert [b["title"] for b in aviso["acciones"]] == ["Sí", "No"]
        for n, boton in enumerate(aviso["acciones"], 1):
            # La automatización que ya existe en HA: casa por el prefijo y se queda con lo
            # que va detrás del último `_`. Eso tiene que ser un id que el endpoint acepte.
            assert boton["action"].startswith("LA_APAGAR_")
            enviado = _lo_que_hace_ha(boton["action"])
            assert enviado == f"resp{n}-{r['id']}"
            assert re.match(main._AVISO_ID_BOTON, enviado)

    def test_si_no_se_puede_guardar_no_manda_botones_muertos(self, mock_requests, movil):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 404))
        r = main._j_mandar_notificacion("¿Reinicio?", opciones="Sí|No")
        assert r["ok"] is False and "sin opciones" in r["motivo"]
        assert main._avisos_movil == []

    def test_sin_movil_va_por_correo_y_lo_dice(self, mock_requests, correos):
        mock_requests.add("POST", "jarvis_preguntas", FakeResponse({}, 201))
        r = main._j_mandar_notificacion("¿Reinicio?", opciones="Sí|No")
        assert r["canal"] == "correo" and "SIN botones" in r["nota"]
        # El correo no trae botones: dice cómo se contesta.
        assert "Sí / No" in correos[0][1]

    def test_tiene_tope_por_hora(self, mock_requests, movil):
        for _ in range(main.PREGUNTAS_MAX_HORA):
            assert main._j_mandar_notificacion("hola")["ok"] is True
        r = main._j_mandar_notificacion("una más")
        assert r["ok"] is False
        assert len(main._avisos_movil) == main.PREGUNTAS_MAX_HORA

    def test_sin_texto_no_manda_nada(self, movil):
        assert "error" in main._j_mandar_notificacion("  ")
        assert main._avisos_movil == []


class TestElBoton:
    def _pregunta(self, mock_requests, respuesta=None, parche=None):
        mock_requests.add("GET", "jarvis_preguntas",
                          FakeResponse([{"opciones": ["Sí", "No"], "respuesta": respuesta}]))
        mock_requests.add("PATCH", "jarvis_preguntas",
                          FakeResponse(parche if parche is not None else [{"id": PID}]))

    def test_apunta_la_respuesta_y_acusa_recibo(self, client, mock_requests, movil):
        self._pregunta(mock_requests)
        r = client.post(f"/avisos/resp2-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 200 and r.json() == {"ok": True, "hecho": True,
                                                     "respuesta": "No"}
        url, kwargs = mock_requests.called("PATCH", "jarvis_preguntas")[0][1:]
        # Condicional: la primera respuesta es la que vale.
        assert f"id=eq.{PID}" in url and "respuesta=is.null" in url
        assert kwargs["json"]["respuesta"] == "No"
        assert "No" in main._avisos_movil[0]["texto"]
        # Y no ha tocado nada de los avisos de apagar: no es un aviso, es una pregunta.
        assert not mock_requests.called("GET", "jarvis_recordatorios")

    def test_dos_toques_no_cambian_la_respuesta(self, client, mock_requests, movil):
        self._pregunta(mock_requests, respuesta="Sí", parche=[])
        r = client.post(f"/avisos/resp2-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 200 and r.json()["hecho"] is False
        assert r.json()["respuesta"] == "Sí"

    def test_una_pregunta_que_no_existe(self, client, mock_requests):
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([]))
        r = client.post(f"/avisos/resp1-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 404

    def test_un_boton_que_la_pregunta_no_tiene(self, client, mock_requests):
        self._pregunta(mock_requests)
        r = client.post(f"/avisos/resp3-{PID}/apagar", headers=CABECERA)
        assert r.status_code == 422
        assert not mock_requests.called("PATCH", "jarvis_preguntas")

    def test_el_id_sigue_validado(self, client):
        for malo in (f"resp4-{PID}", f"resp1-{PID}x", "resp1-", f"otro-{PID}"):
            assert client.post(f"/avisos/{malo}/apagar", headers=CABECERA).status_code == 422

    def test_sin_token_no_entra(self, client):
        assert client.post(f"/avisos/resp1-{PID}/apagar").status_code == 403

    def test_el_apagar_de_siempre_sigue_igual(self, client, mock_requests):
        """Un id sin prefijo sigue siendo un aviso de apagar, no una pregunta."""
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        r = client.post(f"/avisos/{PID}/apagar", headers=CABECERA)
        assert r.status_code == 404
        assert not mock_requests.called("GET", "jarvis_preguntas")


class TestLaRespuesta:
    def test_dice_lo_que_has_pulsado(self, mock_requests):
        mock_requests.add("GET", "jarvis_preguntas",
                          FakeResponse([{"id": PID, "texto": "¿Reinicio?",
                                         "opciones": ["Sí", "No"], "respuesta": "Sí",
                                         "respondido_at": "2026-10-11T10:05:00+00:00"}]))
        r = main._j_respuesta_notificacion(PID)
        assert r["respondida"] is True and r["respuesta"] == "Sí"
        assert r["respondida_a_las"] == "12:05"
        assert f"id=eq.{PID}" in mock_requests.called("GET", "jarvis_preguntas")[0][1]

    def test_sin_id_mira_la_ultima(self, mock_requests):
        mock_requests.add("GET", "jarvis_preguntas",
                          FakeResponse([{"id": PID, "texto": "x", "opciones": ["Sí"],
                                         "respuesta": None}]))
        r = main._j_respuesta_notificacion()
        assert r["respondida"] is False and r["respuesta"] is None
        url = mock_requests.called("GET", "jarvis_preguntas")[0][1]
        assert "id=eq." not in url and "order=creado.desc" in url

    def test_esperar_vuelve_en_cuanto_pulsas(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "PREGUNTA_SONDEO_SEG", 0)
        lecturas = iter([None, None, "No"])
        mock_requests.add("GET", "jarvis_preguntas",
                          lambda url, **kw: FakeResponse([{"id": PID, "texto": "x",
                                                           "opciones": ["Sí", "No"],
                                                           "respuesta": next(lecturas)}]))
        r = main._j_respuesta_notificacion(PID, esperar=10)
        assert r["respuesta"] == "No"
        assert len(mock_requests.called("GET", "jarvis_preguntas")) == 3

    def test_no_espera_mas_del_tope(self, mock_requests, monkeypatch):
        relojes = iter([0, 0, main.PREGUNTA_ESPERA_MAX + 1])
        monkeypatch.setattr(main.time, "monotonic", lambda: next(relojes))
        monkeypatch.setattr(main.time, "sleep", lambda s: None)
        mock_requests.add("GET", "jarvis_preguntas",
                          FakeResponse([{"id": PID, "texto": "x", "opciones": ["Sí"],
                                         "respuesta": None}]))
        r = main._j_respuesta_notificacion(PID, esperar=999)
        assert r["respondida"] is False

    def test_un_id_raro_no_llega_a_la_url(self, mock_requests):
        assert "error" in main._j_respuesta_notificacion("x&id=neq.0")
        assert not mock_requests.called("GET", "jarvis_preguntas")

    def test_ninguna_pregunta(self, mock_requests):
        mock_requests.add("GET", "jarvis_preguntas", FakeResponse([]))
        assert main._j_respuesta_notificacion()["ok"] is False


class TestReenviarElPermiso:
    RID = "5d1c7b0e-8f3a-4c2b-9e6d-7a8b9c0d1e2f"

    def test_vuelve_a_mandar_el_del_boton_desplegar(self, mock_requests, movil):
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": self.RID, "pr_numero": 300}]))
        mock_requests.add("GET", "jarvis_recordatorios",
                          FakeResponse([{"texto": "¿Lo subo a main?",
                                         "regla": main.REGLA_DESPLIEGUE}]))
        r = main._j_reenviar_permiso()
        assert r["ok"] is True and r["canal"] == "movil" and r["pr"] == 300
        aviso = main._avisos_movil[0]
        assert aviso["id"] == self.RID and aviso["critico"] is True
        assert aviso["acciones"][0]["action"] == f"LA_DESPLEGAR_{self.RID}"

    def test_sin_aviso_apuntado_manda_uno_nuevo_con_el_mismo_boton(self, mock_requests,
                                                                   movil):
        mock_requests.add("GET", "revision_hallazgos",
                          FakeResponse([{"id": self.RID, "pr_numero": 300}]))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        r = main._j_reenviar_permiso()
        assert r["ok"] is True
        assert main._avisos_movil[0]["acciones"][0]["action"] == f"LA_DESPLEGAR_{self.RID}"

    def test_sin_nada_esperando_no_manda_nada(self, mock_requests, movil):
        mock_requests.add("GET", "revision_hallazgos", FakeResponse([]))
        assert main._j_reenviar_permiso()["ok"] is False
        assert main._avisos_movil == []


class TestPorTelefono:
    def test_estan_en_la_lista_blanca(self):
        assert {"mandar_notificacion", "reenviar_permiso",
                "respuesta_notificacion"} <= main._MCP_SERVIDOR_HERRAMIENTAS
        assert "respuesta_notificacion" in main._MCP_SERVIDOR_SOLO_LECTURA
        for nombre in ("mandar_notificacion", "reenviar_permiso", "respuesta_notificacion"):
            assert main._jarvis_confirma(main._JARVIS_HERRAMIENTAS[nombre], {}) is False

    def test_el_catalogo_las_anuncia(self):
        nombres = {t["name"] for t in main._mcp_servidor_tools_list()}
        assert {"mandar_notificacion", "reenviar_permiso",
                "respuesta_notificacion"} <= nombres

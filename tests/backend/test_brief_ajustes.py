"""Tests del interruptor del resumen diario: apagarlo, pausarlo unos días y que las
tres fuentes de disparo se enteren.

Lo que más se prueba aquí es que la comprobación esté en la ÚNICA puerta del envío
(`enviar_brief_si_toca`), porque de eso depende que apagarlo apague también las fuentes
que no se probaron una por una — y que un apagado no consuma la reserva del día, que
dejaría el correo sin salir el día que se quite la pausa.
"""
from datetime import datetime, timedelta

import main
from conftest import FakeResponse
from test_brief import _SMTPFalso
from test_despertar import preparar, reloj


def _hoy():
    return datetime.now(main.LOCAL_TZ).date()


def tabla_ajustes(mock_requests, activo=True, pausado_hasta=None):
    """Simula brief_ajustes: una sola fila que el upsert sobreescribe."""
    estado = {"activo": activo, "pausado_hasta": pausado_hasta}

    def _get(url, **kwargs):
        return FakeResponse([dict(estado)], 200)

    def _upsert(url, **kwargs):
        fila = kwargs["json"][0]
        estado["activo"]        = fila["activo"]
        estado["pausado_hasta"] = fila["pausado_hasta"]
        estado["url"]           = url
        return FakeResponse([], 201)

    mock_requests.add("GET", "/rest/v1/brief_ajustes", _get)
    mock_requests.add("POST", "/rest/v1/brief_ajustes", _upsert)
    return estado


class TestPuertaDelInterruptor:
    def test_activo_manda_el_correo(self, client, mock_requests, graph_token, monkeypatch):
        """Control: con el interruptor puesto, todo sigue como antes."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests)
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_desactivado_no_manda(self, client, mock_requests, graph_token, monkeypatch):
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token")
        assert r.status_code == 200
        assert r.json()["enviado"] is False
        assert "desactivado" in r.json()["motivo"]
        assert _SMTPFalso.enviados == []

    def test_desactivado_no_consume_la_reserva_del_dia(self, client, mock_requests,
                                                       graph_token, monkeypatch):
        """El interruptor se mira ANTES de reservar. Si reservara, el día quedaría
        marcado como enviado sin haber enviado nada, y al volver a encenderlo el correo
        no saldría hasta mañana."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 7, 15)

        client.post("/despertar?token=brief-token")
        assert mock_requests.called("POST", "/rest/v1/brief_envios") == []

    def test_el_tick_de_ha_tampoco_lo_manda(self, client, mock_requests, graph_token, monkeypatch):
        """El reloj de respaldo pasa por la misma puerta: apagar es apagar del todo."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 11, 0)          # pasada la hora tope

        r = client.post("/ha/brief-tick?token=ha-poll-token")
        assert r.json()["enviado"] is False
        assert _SMTPFalso.enviados == []

    def test_el_sueno_del_watch_tampoco(self, client, mock_requests, graph_token, monkeypatch):
        """La tercera fuente: la llegada del sueño no puede saltarse el interruptor."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 8, 0)

        main._avisar_sueno_recibido({_hoy().isoformat()})
        assert _SMTPFalso.enviados == []

    def test_pausado_hasta_hoy_no_manda(self, client, mock_requests, graph_token, monkeypatch):
        """`pausado_hasta` es el último día SIN resumen, incluido."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, pausado_hasta=_hoy().isoformat())
        reloj(monkeypatch, 7, 15)

        r = client.post("/despertar?token=brief-token")
        assert r.json()["enviado"] is False
        assert "pausado" in r.json()["motivo"]

    def test_la_pausa_se_agota_sola(self, client, mock_requests, graph_token, monkeypatch):
        """Vencida la fecha, el correo vuelve sin que nadie tenga que reactivarlo: es lo
        que separa 'me voy una semana' de 'no lo quiero más'."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, pausado_hasta=(_hoy() - timedelta(days=1)).isoformat())
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1

    def test_un_fallo_leyendo_el_ajuste_no_apaga_el_correo(self, client, mock_requests,
                                                          graph_token, monkeypatch):
        """"No he podido leer el interruptor" no puede significar "estaba apagado": un
        fallo transitorio dejaría sin briefing un día entero sin parecerlo."""
        preparar(mock_requests, monkeypatch)
        mock_requests.add("GET", "/rest/v1/brief_ajustes", FakeResponse(None, 500, "boom"))
        reloj(monkeypatch, 7, 15)

        assert client.post("/despertar?token=brief-token").json()["enviado"] is True

    def test_a_mano_se_manda_aunque_este_apagado(self, client, mock_requests,
                                                 graph_token, monkeypatch):
        """`?forzar=1` es una persona pidiéndolo ahora. El interruptor gobierna el envío
        automático, no a quien lo puso."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests, activo=False)

        r = client.post("/brief/send?token=brief-token&forzar=1")
        assert r.json()["enviado"] is True
        assert len(_SMTPFalso.enviados) == 1


class TestEndpointAjustes:
    def test_requiere_jwt(self, client):
        assert client.get("/brief/ajustes").status_code in (401, 403)
        assert client.patch("/brief/ajustes", json={"activo": False}).status_code in (401, 403)

    def test_get_devuelve_el_estado(self, client, mock_requests, auth_headers, monkeypatch):
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 9, 0)

        d = client.get("/brief/ajustes", headers=auth_headers).json()
        assert d["activo"] is False
        assert d["fecha"] == _hoy().isoformat()
        assert d["enviado_hoy"] is False

    def test_get_dice_si_el_de_hoy_ya_salio(self, client, mock_requests, auth_headers, monkeypatch):
        """Apagado y "aún no toca" se confunden si no se ven juntos."""
        tabla_ajustes(mock_requests)
        mock_requests.add("GET", "/rest/v1/brief_envios",
                          FakeResponse([{"fecha": _hoy().isoformat(), "fuente": "cargador"}]))
        reloj(monkeypatch, 9, 0)

        assert client.get("/brief/ajustes", headers=auth_headers).json()["enviado_hoy"] is True

    def test_una_pausa_vencida_no_se_reporta(self, client, mock_requests, auth_headers, monkeypatch):
        """Una fecha pasada al lado de un resumen que vuelve a salir se lee como avería."""
        tabla_ajustes(mock_requests, pausado_hasta=(_hoy() - timedelta(days=3)).isoformat())
        reloj(monkeypatch, 9, 0)

        d = client.get("/brief/ajustes", headers=auth_headers).json()
        assert d["pausado"] is False
        assert d["pausado_hasta"] is None

    def test_apagarlo_lo_ve_el_siguiente_disparo(self, client, mock_requests, auth_headers,
                                                 graph_token, monkeypatch):
        """La copia en memoria se actualiza al escribir: si no, el disparo seguiría
        leyendo el valor viejo hasta el próximo cold start."""
        preparar(mock_requests, monkeypatch)
        tabla_ajustes(mock_requests)
        reloj(monkeypatch, 7, 15)

        assert client.patch("/brief/ajustes", json={"activo": False},
                            headers=auth_headers).status_code == 200
        assert client.post("/despertar?token=brief-token").json()["enviado"] is False
        assert _SMTPFalso.enviados == []

    def test_el_upsert_nombra_la_restriccion(self, client, mock_requests, auth_headers, monkeypatch):
        """La lección del 409: sin on_conflict, PostgREST resuelve contra la primaria."""
        estado = tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)

        client.patch("/brief/ajustes", json={"activo": False}, headers=auth_headers)
        assert "on_conflict=id" in estado["url"]

    def test_pausar_guarda_la_fecha(self, client, mock_requests, auth_headers, monkeypatch):
        estado = tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)
        hasta = (_hoy() + timedelta(days=5)).isoformat()

        d = client.patch("/brief/ajustes", json={"pausado_hasta": hasta},
                         headers=auth_headers).json()
        assert estado["pausado_hasta"] == hasta
        assert d["pausado"] is True

    def test_quitar_la_pausa_deja_el_resto_como_estaba(self, client, mock_requests,
                                                       auth_headers, monkeypatch):
        """`null` explícito quita la pausa; lo que no se manda no se toca."""
        estado = tabla_ajustes(mock_requests, activo=True,
                               pausado_hasta=(_hoy() + timedelta(days=2)).isoformat())
        reloj(monkeypatch, 9, 0)

        d = client.patch("/brief/ajustes", json={"pausado_hasta": None},
                         headers=auth_headers).json()
        assert estado["pausado_hasta"] is None
        assert estado["activo"] is True
        assert d["pausado"] is False

    def test_una_fecha_que_ya_paso_se_rechaza(self, client, mock_requests, auth_headers, monkeypatch):
        tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)

        r = client.patch("/brief/ajustes",
                         json={"pausado_hasta": (_hoy() - timedelta(days=1)).isoformat()},
                         headers=auth_headers)
        assert r.status_code == 400

    def test_una_fecha_ilegible_se_rechaza(self, client, mock_requests, auth_headers, monkeypatch):
        tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)

        assert client.patch("/brief/ajustes", json={"pausado_hasta": "mañana"},
                            headers=auth_headers).status_code == 400
        assert client.patch("/brief/ajustes", json={"pausado_hasta": "2026-02-30"},
                            headers=auth_headers).status_code == 400

    def test_sin_campos_no_escribe_nada(self, client, mock_requests, auth_headers):
        tabla_ajustes(mock_requests)

        assert client.patch("/brief/ajustes", json={}, headers=auth_headers).status_code == 400
        assert mock_requests.called("POST", "/rest/v1/brief_ajustes") == []


class TestJarvis:
    def test_configurar_apaga_el_resumen(self, mock_requests, monkeypatch):
        estado = tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)

        d = main._j_configurar_resumen_diario(activo=False)
        assert d["ok"] is True
        assert estado["activo"] is False

    def test_configurar_pausa_unos_dias(self, mock_requests, monkeypatch):
        estado = tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)
        hasta = (_hoy() + timedelta(days=7)).isoformat()

        main._j_configurar_resumen_diario(pausar_hasta=hasta)
        assert estado["pausado_hasta"] == hasta

    def test_una_fecha_pasada_vuelve_como_motivo(self, mock_requests, monkeypatch):
        """El modelo tiene que poder corregirse en la misma conversación, no recibir una
        excepción que corte el turno."""
        tabla_ajustes(mock_requests)
        reloj(monkeypatch, 9, 0)

        d = main._j_configurar_resumen_diario(pausar_hasta="2020-01-01")
        assert d["ok"] is False
        assert d["motivo"]

    def test_sin_argumentos_pregunta_en_vez_de_escribir(self, mock_requests):
        tabla_ajustes(mock_requests)

        assert main._j_configurar_resumen_diario()["ok"] is False
        assert mock_requests.called("POST", "/rest/v1/brief_ajustes") == []

    def test_el_estado_es_consultable(self, mock_requests, monkeypatch):
        tabla_ajustes(mock_requests, activo=False)
        reloj(monkeypatch, 9, 0)

        assert main._j_estado_resumen_diario()["activo"] is False

    def test_las_dos_estan_en_el_registro(self):
        """Si se caen del registro, Jarvis deja de saber que puede apagarlo."""
        for nombre in ("estado_resumen_diario", "configurar_resumen_diario"):
            assert nombre in main._JARVIS_HERRAMIENTAS
            assert main._JARVIS_HERRAMIENTAS[nombre]["confirmar"] is False

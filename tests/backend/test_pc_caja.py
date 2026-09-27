"""Tests de las órdenes al PC por `caja` (fase 4 del HomeLab).

El PC lo gobernaba el Green por SSH a un nombre mDNS, y al reinstalar Windows el nombre
cambió y todo empezó a fallar en silencio. Ahora el backend deja un PEDIDO en `PC_DIR` y
`caja` lo ejecuta. Lo que se prueba aquí es el contrato de ese pedido —nombre fijo,
escritura atómica, nunca los dos motores a la vez— y que el Green siga siendo el respaldo
cuando no hay `caja` o no se puede escribir.
"""
import json
import os

import pytest

import main
from conftest import FakeResponse

CABECERA_HA = {"X-Auth-Token": "ha-poll-token"}


@pytest.fixture
def caja(monkeypatch, tmp_path):
    """Un `PC_DIR` de verdad, con su `pedidos/` como lo deja montado caja."""
    (tmp_path / "pedidos").mkdir()
    monkeypatch.setattr(main, "PC_DIR", str(tmp_path))
    return tmp_path


def _pedidos(caja):
    return sorted(os.listdir(caja / "pedidos"))


def _sin_flags():
    return (main._wol_pending is False and main._agent_relaunch_pending is False
            and main._pc_power_action is None)


class TestEndpointsConCaja:
    @pytest.mark.parametrize("ruta,accion", [
        ("/wake-pc", "wol"),
        ("/relaunch-agent", "relanzar"),
        ("/shutdown-pc", "apagar"),
        ("/suspend-pc", "suspender"),
    ])
    def test_cada_boton_deja_su_pedido_y_no_el_flag(self, client, auth_headers, caja,
                                                    ruta, accion):
        """Si se pusieran los dos, el Green y caja harían lo mismo dos veces: dos
        apagados, dos agentes."""
        r = client.post(ruta, headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "motor": "caja"}
        assert _pedidos(caja) == [accion]
        assert _sin_flags()

    def test_el_temporal_no_se_queda_ni_en_pedidos_ni_fuera(self, client, auth_headers, caja):
        client.post("/wake-pc", headers=auth_headers)
        assert _pedidos(caja) == ["wol"]
        assert sorted(os.listdir(caja)) == ["pedidos"]

    def test_el_contenido_es_solo_la_hora(self, client, auth_headers, caja):
        client.post("/suspend-pc", headers=auth_headers)
        contenido = (caja / "pedidos" / "suspender").read_text(encoding="utf-8").strip()
        # Hora UTC ISO: informativo, caja no lo interpreta.
        assert contenido.endswith("+00:00") and "T" in contenido

    def test_dos_pedidos_iguales_son_uno(self, client, auth_headers, caja):
        client.post("/relaunch-agent", headers=auth_headers)
        client.post("/relaunch-agent", headers=auth_headers)
        assert _pedidos(caja) == ["relanzar"]

    def test_los_endpoints_siguen_pidiendo_jwt(self, client, caja):
        for ruta in ("/wake-pc", "/relaunch-agent", "/shutdown-pc", "/suspend-pc"):
            assert client.post(ruta).status_code in (401, 403)
        assert _pedidos(caja) == []


class TestEscrituraAtomica:
    def test_el_tmp_se_escribe_fuera_de_pedidos(self, caja, monkeypatch):
        """La unidad se dispara en cuanto `pedidos/` deja de estar vacío: un `.tmp` dentro
        la despertaría con algo que no es ninguna orden."""
        vistos = []
        original = os.replace

        def _replace(origen, destino):
            vistos.append((str(origen), str(destino)))
            return original(origen, destino)

        monkeypatch.setattr(main.os, "replace", _replace)
        assert main._escribir_pedido_pc("apagar") is True
        (origen, destino), = vistos
        assert origen == os.path.join(str(caja), ".apagar.tmp")
        assert destino == os.path.join(str(caja), "pedidos", "apagar")

    def test_una_orden_fuera_de_la_lista_no_se_escribe(self, caja):
        """El nombre del fichero es la orden entera: nada que no esté en la lista blanca
        puede acabar ahí."""
        with pytest.raises(ValueError):
            main._escribir_pedido_pc("../../etc/passwd")
        with pytest.raises(ValueError):
            main._pedir_al_pc("reiniciar")
        assert _pedidos(caja) == []


class TestRespaldoDelGreen:
    def test_sin_pc_dir_todo_como_antes(self, client, auth_headers, tmp_path):
        assert main.PC_DIR == ""
        assert client.post("/wake-pc", headers=auth_headers).json() == {"ok": True, "motor": "ha"}
        assert client.get("/ha/wol-pending", headers=CABECERA_HA).json() == {"pending": True}
        client.post("/suspend-pc", headers=auth_headers)
        assert client.get("/ha/pc-power-pending", headers=CABECERA_HA).json() == {
            "action": "suspend"}

    def test_sin_pedidos_montado_cae_al_flag(self, client, auth_headers, monkeypatch,
                                            tmp_path):
        """El volumen sin montar: crear el directorio dejaría el pedido dentro del
        contenedor, donde nadie lo ve. Se cae al flag para que el Green lo haga."""
        monkeypatch.setattr(main, "PC_DIR", str(tmp_path / "no-montado"))
        r = client.post("/relaunch-agent", headers=auth_headers)
        assert r.json() == {"ok": True, "motor": "ha"}
        assert main._agent_relaunch_pending is True
        assert not (tmp_path / "no-montado").exists()

    def test_si_escribir_falla_cae_al_flag_y_lo_registra(self, client, auth_headers, caja,
                                                        monkeypatch, caplog):
        def _falla(*a, **k):
            raise PermissionError("solo lectura")
        monkeypatch.setattr(main.os, "replace", _falla)
        r = client.post("/shutdown-pc", headers=auth_headers)
        assert r.json() == {"ok": True, "motor": "ha"}
        assert main._pc_power_action == "shutdown"
        assert _pedidos(caja) == []
        # Y el temporal no se queda tirado.
        assert not (caja / ".apagar.tmp").exists()
        assert any("PC_DIR" in rec.getMessage() for rec in caplog.records)


class TestEstado:
    def test_sin_caja_lo_dice(self, client, auth_headers):
        assert client.get("/pc/estado", headers=auth_headers).json() == {
            "motor": "ha", "ultimo": None, "pendientes": []}

    def test_requiere_jwt(self, client, caja):
        assert client.get("/pc/estado").status_code in (401, 403)
        assert client.get("/pc/estado", headers=CABECERA_HA).status_code in (401, 403)

    def test_sin_estado_json(self, client, auth_headers, caja):
        assert client.get("/pc/estado", headers=auth_headers).json() == {
            "motor": "caja", "ultimo": None, "pendientes": []}

    def test_con_pc_dir_pero_sin_pedidos_no_dice_caja(self, client, auth_headers, tmp_path,
                                                     monkeypatch):
        """El volumen sin montar: el pedido se cae al flag de HA, y decir «caja» aquí hacía
        que el modal pintara «caja: trabajando en el pedido…» de algo que caja no había
        recibido nunca."""
        monkeypatch.setattr(main, "PC_DIR", str(tmp_path))
        assert client.post("/wake-pc", headers=auth_headers).json()["motor"] == "ha"
        assert client.get("/pc/estado", headers=auth_headers).json() == {
            "motor": "caja_sin_montar", "ultimo": None, "pendientes": []}

    def test_montado_de_solo_lectura_no_dice_caja(self, client, auth_headers, caja,
                                                 monkeypatch):
        """`pedidos/` existe y se lista, pero no se puede escribir: el mismo criterio que
        la escritura, que cae al flag."""
        monkeypatch.setattr(main.os, "access", lambda ruta, modo: False)
        assert client.get("/pc/estado", headers=auth_headers).json()["motor"] == "caja_sin_montar"
        assert client.post("/relaunch-agent", headers=auth_headers).json()["motor"] == "ha"
        assert main._agent_relaunch_pending is True
        assert _pedidos(caja) == []

    def test_si_el_ultimo_pedido_fallo_lo_dice_hasta_que_uno_llega(self, client, auth_headers,
                                                                   caja, monkeypatch):
        """Un fallo que el directorio no delata (disco lleno, un permiso raro): lo que
        cuenta es si la última orden llegó, no si el directorio parece bueno."""
        replace_de_verdad = main.os.replace

        def _falla(*a, **k):
            raise OSError("sin espacio")
        monkeypatch.setattr(main.os, "replace", _falla)
        assert client.post("/wake-pc", headers=auth_headers).json()["motor"] == "ha"
        assert client.get("/pc/estado", headers=auth_headers).json()["motor"] == "caja_sin_montar"

        monkeypatch.setattr(main.os, "replace", replace_de_verdad)
        assert client.post("/wake-pc", headers=auth_headers).json()["motor"] == "caja"
        datos = client.get("/pc/estado", headers=auth_headers).json()
        assert datos["motor"] == "caja"
        assert datos["pendientes"] == ["wol"]

    def test_con_estado_json_y_pendientes(self, client, auth_headers, caja):
        (caja / "estado.json").write_text(json.dumps({
            "accion": "relanzar", "ok": False, "detalle": "no contesta por SSH",
            "cuando": "2026-09-27T10:00:00Z", "destino": None, "sobra": "x",
        }), encoding="utf-8")
        client.post("/suspend-pc", headers=auth_headers)
        client.post("/wake-pc", headers=auth_headers)
        # Un fichero ajeno en pedidos/ no es una orden, y no se enseña.
        (caja / "pedidos" / "otra-cosa").write_text("", encoding="utf-8")
        datos = client.get("/pc/estado", headers=auth_headers).json()
        assert datos["motor"] == "caja"
        assert datos["ultimo"] == {"accion": "relanzar", "ok": False,
                                   "detalle": "no contesta por SSH",
                                   "cuando": "2026-09-27T10:00:00Z", "destino": None}
        # En el orden en que las atiende pc.sh.
        assert datos["pendientes"] == ["wol", "suspender"]

    @pytest.mark.parametrize("contenido", [
        b"{ esto no es json",
        b"\xff\xfe\x00",
        b"[1, 2, 3]",
        b"x" * (4096 + 10),
    ])
    def test_uno_corrupto_es_no_se_sabe(self, client, auth_headers, caja, contenido):
        (caja / "estado.json").write_bytes(contenido)
        r = client.get("/pc/estado", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["ultimo"] is None

    def test_los_textos_van_recortados(self, client, auth_headers, caja):
        (caja / "estado.json").write_text(json.dumps({
            "accion": "wol", "ok": True, "detalle": "a" * 1000, "cuando": "2026",
        }), encoding="utf-8")
        ultimo = client.get("/pc/estado", headers=auth_headers).json()["ultimo"]
        assert len(ultimo["detalle"]) == 300


class TestJarvisDespiertaAlAgente:
    def test_lanzar_streaming_crea_el_job_antes_de_pedir_nada(self, caja, mock_requests):
        """Con caja la orden se ejecuta en el acto: si el agente arrancara antes de que
        existiera el job, miraría la cola vacía y se cerraría."""
        pedidos_al_crear = []

        def _crear(url, **kwargs):
            pedidos_al_crear.append(_pedidos(caja))
            return FakeResponse([{"id": "job-1"}], 201)

        mock_requests.add("POST", "/rest/v1/jobs", _crear)
        r = main._j_lanzar_streaming()
        assert r["ok"] is True and r["job_id"] == "job-1"
        assert pedidos_al_crear == [[]]
        assert _pedidos(caja) == ["relanzar", "wol"]
        assert _sin_flags()

    def test_lanzar_streaming_sin_caja_marca_los_flags(self, mock_requests):
        """Antes solo creaba el job: con el PC encendido no lo recogía nadie."""
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse([{"id": "job-1"}], 201))
        main._j_lanzar_streaming()
        assert main._wol_pending is True and main._agent_relaunch_pending is True

    def test_si_el_job_falla_no_se_despierta_a_nadie(self, caja, mock_requests):
        mock_requests.add("POST", "/rest/v1/jobs", FakeResponse({"message": "caído"}, 500))
        with pytest.raises(Exception):
            main._j_lanzar_streaming()
        assert _pedidos(caja) == []

    def test_el_encargo_tambien_despierta_al_agente(self, caja, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "AGENT_TOKEN", "token-del-agente")
        pedidos_al_crear = []

        def _crear(url, **kwargs):
            pedidos_al_crear.append(_pedidos(caja))
            return FakeResponse([{"id": "job-2"}], 201)

        mock_requests.add("POST", "/rest/v1/jobs", _crear)
        assert main._j_encargar_al_pc("ordena descargas")["ok"] is True
        assert pedidos_al_crear == [[]]
        assert _pedidos(caja) == ["relanzar", "wol"]

    def test_relanzar_agente_dice_quien_lo_hace(self, caja):
        assert "caja" in main._j_relanzar_agente()["nota"]
        assert _pedidos(caja) == ["relanzar"]


class TestAvisoQueSuspende:
    RID = "11111111-2222-3333-4444-555555555555"

    def test_el_boton_del_aviso_deja_el_pedido(self, client, caja, mock_requests):
        mock_requests.add("GET", "jarvis_recordatorios",
                          FakeResponse([{"regla": main.REGLA_PC_ENCENDIDO, "entidades": None}]))
        r = client.post(f"/avisos/{self.RID}/apagar", headers=CABECERA_HA)
        assert r.status_code == 200 and r.json()["suspendido"] is True
        assert _pedidos(caja) == ["suspender"]
        assert main._pc_power_action is None

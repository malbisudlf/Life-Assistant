"""Tests del programador en el backend: las tres herramientas, la firma y el «terminado».

El puente vive en el repositorio HomeLab (`caja/programador/`) y tiene sus propios tests;
aquí va lo que es del backend, con el puente simulado: que el encargo salga firmado de
cero y solo con un «sí», que la lista blanca se aplique al proponer, que los errores del
puente se traduzcan y no se copien, y que el aviso de vuelta solo lo pueda dar el puente.
"""
import json
import time

import pytest
import requests

import main
from conftest import FakeResponse
from test_jarvis import _con_modelo, _llamada, _mensaje  # noqa: E402

URL   = "http://172.17.0.1:3341"
TOKEN = "token-del-puente-de-prueba"
AVISO = "token-del-aviso-de-prueba"
ID    = "0f3c2a4e-1b2d-4c3e-9f00-123456789abc"
# El mismo vector que `caja/programador/pruebas/test_logica.py` de HomeLab.
VECTOR = {"id": ID, "titulo": "dashboard: el widget de clima",
          "encargo": "Que el widget de clima diga la máxima y la mínima de hoy.",
          "repo": "malbisudlf/Life-Assistant", "proyecto": "", "ts": 1761350400}
FIRMA_VECTOR = "d47ace3e65e6d28472458ab685aba691e5d935ece3611032beb0e5d725455261"
ENCARGO = {"titulo": "app: lista de la compra",
           "encargo": "Una web sencilla para apuntar la lista de la compra y tacharla."}


@pytest.fixture
def puente(monkeypatch, mock_requests):
    monkeypatch.setattr(main, "PROGRAMADOR_URL", URL)
    monkeypatch.setattr(main, "PROGRAMADOR_TOKEN", TOKEN)
    monkeypatch.setattr(main, "PROGRAMADOR_AVISO_TOKEN", AVISO)
    monkeypatch.setattr(main, "PROGRAMADOR_DUENOS", "malbisudlf")
    return mock_requests


def _enviado(router, fragmento):
    (_, url, kwargs), = router.called("POST", fragmento)
    return url, kwargs


class TestFirma:
    def test_vector_compartido_con_el_puente(self, monkeypatch):
        monkeypatch.setattr(main, "PROGRAMADOR_TOKEN", "clave-compartida-de-prueba")
        assert main._firma_programador(VECTOR) == FIRMA_VECTOR

    def test_sin_token_no_hay_firma(self, monkeypatch):
        monkeypatch.setattr(main, "PROGRAMADOR_TOKEN", "")
        assert main._firma_programador(VECTOR) == ""


class TestEncargar:
    def test_se_confirma(self):
        assert main._JARVIS_HERRAMIENTAS["encargar_proyecto"]["confirmar"] is True
        for directa in ("ver_proyectos", "hablar_con_el_programador"):
            assert main._JARVIS_HERRAMIENTAS[directa]["confirmar"] is False

    def test_sale_firmado_de_cero(self, puente):
        puente.add("POST", f"{URL}/encargos", FakeResponse({"id": ID, "estado": "en_cola",
                                                            "posicion": 1}, 202))
        r = main._j_encargar_proyecto(**ENCARGO)
        assert r["ok"] is True and r["posicion"] == 1
        url, kwargs = _enviado(puente, "/encargos")
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        cuerpo = dict(kwargs["json"])
        firma = cuerpo.pop("firma")
        assert firma == main._firma_programador(cuerpo)
        assert abs(cuerpo["ts"] - time.time()) < 5
        assert cuerpo["titulo"] == ENCARGO["titulo"] and cuerpo["repo"] == ""

    def test_la_firma_cubre_el_encargo(self, puente):
        puente.add("POST", f"{URL}/encargos", FakeResponse({"id": ID}, 202))
        main._j_encargar_proyecto(**ENCARGO)
        _, kwargs = _enviado(puente, "/encargos")
        cuerpo = dict(kwargs["json"])
        firma = cuerpo.pop("firma")
        assert firma != main._firma_programador({**cuerpo, "encargo": "otra cosa distinta"})

    def test_repo_fuera_de_la_lista_ni_sale(self, puente):
        r = main._j_encargar_proyecto(**ENCARGO, repo="torvalds/linux")
        assert r["ok"] is False and "lista blanca" in r["error"]
        assert not puente.calls

    def test_repo_de_la_lista(self, puente):
        puente.add("POST", f"{URL}/encargos", FakeResponse({"id": ID}, 202))
        assert main._j_encargar_proyecto(**ENCARGO, repo="MalbiSudlf/Prueba")["ok"]

    def test_sin_lista_ningun_repo(self, puente, monkeypatch):
        monkeypatch.setattr(main, "PROGRAMADOR_DUENOS", "")
        r = main._j_encargar_proyecto(**ENCARGO, repo="malbisudlf/x")
        assert r["ok"] is False and not puente.calls

    def test_formas_raras(self):
        for repo in ("malbisudlf", "malbisudlf/../x", "malbisudlf/x.git", "https://github.com/a/b"):
            assert "lista blanca" in main._validar_encargo({**ENCARGO, "repo": repo})
        assert main._validar_encargo({**ENCARGO, "titulo": "x"})
        assert main._validar_encargo({**ENCARGO, "encargo": "corto"})
        assert main._validar_encargo({**ENCARGO, "proyecto": "../x"})

    @pytest.mark.parametrize("codigo,trozo", [(401, "PROGRAMADOR_TOKEN"), (403, "lista blanca"),
                                              (409, "en marcha"), (500, "error (500)")])
    def test_los_errores_del_puente_se_traducen(self, puente, codigo, trozo):
        puente.add("POST", f"{URL}/encargos",
                   FakeResponse({"error": "texto interno del puente"}, codigo,
                                text="texto interno del puente"))
        r = main._j_encargar_proyecto(**ENCARGO)
        assert r["ok"] is False and trozo in r["error"]
        assert "texto interno" not in r["error"]

    def test_puente_caido(self, puente, caplog):
        def _caido(url, **kw):
            raise requests.ConnectionError(f"no se pudo conectar con {url}")
        puente.add("POST", URL, _caido)
        r = main._j_encargar_proyecto(**ENCARGO)
        assert r["ok"] is False and "no contesta" in r["error"]
        assert TOKEN not in caplog.text

    def test_lo_que_no_valdria_no_se_propone(self, client, auth_headers, puente, monkeypatch):
        """El modelo pide un repo ajeno: ni botón, ni llamada al puente."""
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("encargar_proyecto",
                                          {**ENCARGO, "repo": "torvalds/linux"})]),
            _mensaje("Ese repositorio no lo puedo tocar, señor.")])
        r = client.post("/jarvis", json={"mensaje": "arréglame linux"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("pendiente") is None
        assert not puente.called("POST", "/encargos")

    def test_el_bucle_lo_deja_propuesto_sin_encargarlo(self, client, auth_headers, puente,
                                                       monkeypatch):
        _con_modelo(monkeypatch, [_mensaje(tool_calls=[_llamada("encargar_proyecto", ENCARGO)]),
                                  _mensaje("Se lo dejo propuesto, señor.")])
        r = client.post("/jarvis", json={"mensaje": "hazme una web de la compra"},
                        headers=auth_headers)
        assert r.json()["pendiente"]["herramienta"] == "encargar_proyecto"
        assert not puente.called("POST", "/encargos")

    def test_el_si_del_dashboard_lo_encarga(self, client, auth_headers, puente):
        puente.add("POST", f"{URL}/encargos", FakeResponse({"id": ID, "posicion": 1}, 202))
        r = client.post("/jarvis/ejecutar", headers=auth_headers,
                        json={"herramienta": "encargar_proyecto", "argumentos": ENCARGO})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert puente.called("POST", "/encargos")

    def test_la_frase_del_boton(self, puente):
        frase = main._telegram_describir("encargar_proyecto", {**ENCARGO, "repo": "malbisudlf/x"})
        assert frase["texto"].startswith("Encargar al programador «app: lista de la compra» "
                                         "sobre malbisudlf/x")
        assert "error" in main._telegram_describir("encargar_proyecto",
                                                   {**ENCARGO, "repo": "otro/x"})


class TestVerYHablar:
    def test_ver_proyectos(self, puente):
        puente.add("GET", f"{URL}/encargos", FakeResponse([{
            "id": ID, "titulo": "app: compra", "estado": "trabajando",
            "progreso": {"pct": 50, "paso_actual": "Tests", "pasos": ["✓ Web", "· Tests"]},
            "ahora": "Ejecutando: npm test", "interno": "no sale"}]))
        r = main._j_ver_proyectos()
        assert r["ok"] and r["aviso"] == main._AVISO_WEB
        p, = r["proyectos"]
        assert p["estado"] == "trabajando" and p["progreso"]["pct"] == 50
        assert "interno" not in p
        _, _, kwargs = puente.called("GET", "/encargos")[0]
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"

    def test_hablar_firma_el_mensaje_con_su_destinatario(self, puente):
        puente.add("POST", "/mensaje", FakeResponse({"id": ID, "estado": "trabajando",
                                                     "como": "lo leerá tras el paso"}, 202))
        r = main._j_hablar_con_el_programador("que el fondo sea azul")
        assert r["ok"] and r["estado"] == "trabajando"
        url, kwargs = _enviado(puente, "/mensaje")
        assert url == f"{URL}/encargos/activo/mensaje"
        cuerpo = dict(kwargs["json"])
        firma = cuerpo.pop("firma")
        assert cuerpo["para"] == "activo"
        assert firma == main._firma_programador(cuerpo)

    def test_hablar_a_un_proyecto_concreto(self, puente):
        puente.add("POST", "/mensaje", FakeResponse({"estado": "terminado"}, 202))
        main._j_hablar_con_el_programador("sigue", proyecto="app-compra-789abc")
        url, _ = _enviado(puente, "/mensaje")
        assert url == f"{URL}/encargos/app-compra-789abc/mensaje"

    def test_un_proyecto_con_forma_rara_no_sale(self, puente):
        r = main._j_hablar_con_el_programador("hola", proyecto="../../salud")
        assert r["ok"] is False and not puente.calls


class TestSinConfigurar:
    def test_no_se_anuncian(self, monkeypatch):
        monkeypatch.setattr(main, "PROGRAMADOR_URL", "")
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not nombres & {"encargar_proyecto", "ver_proyectos", "hablar_con_el_programador"}
        assert any("programador" in x for x in main._j_mis_capacidades()["lo_que_no_puedo"])

    def test_configurado_si(self, puente):
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"encargar_proyecto", "ver_proyectos", "hablar_con_el_programador"} <= nombres

    def test_no_estan_en_el_telefono(self):
        assert not main._MCP_SERVIDOR_HERRAMIENTAS & {
            "encargar_proyecto", "ver_proyectos", "hablar_con_el_programador"}


def _terminado(**cambios):
    return {"id": ID, "titulo": "app: lista de la compra", "estado": "terminado",
            "resumen": "Hecha la web, con tests.", "pr": "https://github.com/malbisudlf/x/pull/7",
            "ejecucion": 1, **cambios}


class TestTerminado:
    def test_sin_token_configurado_no_entra_nadie(self, client, puente, monkeypatch):
        monkeypatch.setattr(main, "PROGRAMADOR_AVISO_TOKEN", "")
        for cabeceras in ({}, {"X-Auth-Token": ""}, {"X-Auth-Token": "x"}):
            assert client.post("/programador/terminado", json=_terminado(),
                               headers=cabeceras).status_code == 401

    def test_token_malo_o_el_del_otro_sentido(self, client, puente):
        for token in ("otro", TOKEN):
            r = client.post("/programador/terminado", json=_terminado(),
                            headers={"X-Auth-Token": token})
            assert r.status_code == 401

    def test_no_por_la_query(self, client, puente):
        r = client.post(f"/programador/terminado?token={AVISO}", json=_terminado())
        assert r.status_code == 401

    def test_avisa_por_la_puerta_de_siempre(self, client, puente, monkeypatch):
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append((regla, texto, kw)) or True)
        r = client.post("/programador/terminado", json=_terminado(),
                        headers={"X-Auth-Token": AVISO})
        assert r.status_code == 200 and r.json()["avisado"] is True
        (regla, texto, kw), = avisos
        assert regla == main.REGLA_PROGRAMADOR
        assert "lista de la compra" in texto and "pull/7" in texto
        assert kw["huella"] == f"programador:{ID}:1:terminado"

    def test_un_pr_ajeno_no_viaja_en_el_aviso(self, client, puente, monkeypatch):
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append(texto) or True)
        client.post("/programador/terminado",
                    json=_terminado(pr="https://evil.example/malbisudlf/x/pull/7"),
                    headers={"X-Auth-Token": AVISO})
        client.post("/programador/terminado",
                    json=_terminado(pr="https://github.com/otro/x/pull/7", ejecucion=2),
                    headers={"X-Auth-Token": AVISO})
        assert all("PR:" not in t for t in avisos)

    def test_fallido(self, client, puente, monkeypatch):
        avisos = []
        monkeypatch.setattr(main, "_apuntar_aviso",
                            lambda regla, texto, **kw: avisos.append(texto) or True)
        client.post("/programador/terminado",
                    json=_terminado(estado="fallido", motivo="No terminó en 90 minutos"),
                    headers={"X-Auth-Token": AVISO})
        assert "no ha salido" in avisos[0] and "90 minutos" in avisos[0]

    def test_cuerpo_validado(self, client, puente):
        for malo in (_terminado(id="no-es-un-uuid"), _terminado(estado="raro"),
                     _terminado(resumen="x" * 5000)):
            r = client.post("/programador/terminado", json=malo, headers={"X-Auth-Token": AVISO})
            assert r.status_code == 422

    def test_lo_que_pediste_no_entra_en_el_presupuesto_ni_lleva_votos(self):
        assert main._es_tuyo(main.REGLA_PROGRAMADOR)
        assert main._acciones_aviso("x", main.REGLA_PROGRAMADOR) == []

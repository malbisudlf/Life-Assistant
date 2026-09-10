"""Tests de la fase 2 de la zona de desarrollo: despliegue y programados.

Lo que se fija aquí es lo que hace que estas dos pestañas sirvan para algo: que un fallo
de GitHub no se disfrace de "todo al día", que un commit desaparecido del historial se
diga con esas palabras, que una tabla caída no se lleve por delante la pantalla entera, y
que la lista de crons esperados no se desincronice de los workflows de verdad — que es
exactamente el fallo del que nace la pestaña.
"""
import os
import re

import pytest

from conftest import FakeResponse

import main


COMMIT_MAIN = {
    "sha": "a" * 40,
    "commit": {"message": "alarmas: el aviso al movil deja de ser critico (#167)\n\nmás cosas",
               "author": {"date": "2026-09-10T08:00:00Z"}},
}


@pytest.fixture
def con_repo(monkeypatch):
    """El backend solo pregunta a GitHub si sabe a qué repositorio."""
    monkeypatch.setattr(main, "JARVIS_REPO", "malbisudlf/Life-Assistant")
    return "malbisudlf/Life-Assistant"


class TestDespliegue:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/despliegue").status_code == 401

    def test_sin_repo_configurado_lo_dice_y_no_inventa(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_REPO", "")
        cuerpo = client.get("/dev/despliegue", headers=auth_headers).json()
        assert cuerpo["github"]["ok"] is False
        assert cuerpo["backend"] is None      # ni al día ni atrasado: no se sabe

    def test_al_dia_cuando_el_sha_coincide(self, client, auth_headers, mock_requests,
                                           con_repo, monkeypatch):
        monkeypatch.setattr(main, "_version_desplegada", lambda: "a" * 40)
        mock_requests.add("GET", "/commits/main", FakeResponse(COMMIT_MAIN))
        cuerpo = client.get("/dev/despliegue", headers=auth_headers).json()
        assert cuerpo["backend"]["al_dia"] is True
        assert cuerpo["backend"]["detras"] == 0
        # Y sin gastar una comparación: si los shas son iguales no hay nada que comparar.
        assert not mock_requests.called("GET", "/compare/")

    def test_cuenta_los_commits_que_le_faltan_al_green(self, client, auth_headers,
                                                       mock_requests, con_repo, monkeypatch):
        monkeypatch.setattr(main, "_version_desplegada", lambda: "b" * 40)
        mock_requests.add("GET", "/commits/main", FakeResponse(COMMIT_MAIN))
        mock_requests.add("GET", "/compare/", FakeResponse({
            "ahead_by": 2,
            "commits": [
                {"sha": "c" * 40, "commit": {"message": "uno", "author": {"date": "2026-09-09T10:00:00Z"}}},
                {"sha": "d" * 40, "commit": {"message": "dos", "author": {"date": "2026-09-10T07:00:00Z"}}},
            ],
        }))
        cuerpo = client.get("/dev/despliegue", headers=auth_headers).json()
        assert cuerpo["backend"]["al_dia"] is False
        assert cuerpo["backend"]["detras"] == 2
        # Del más nuevo al más viejo: lo primero que se quiere ver es lo último que falta.
        assert [c["mensaje"] for c in cuerpo["backend"]["commits"]] == ["dos", "uno"]

    def test_un_commit_que_ya_no_esta_en_la_historia_se_dice(self, client, auth_headers,
                                                             mock_requests, con_repo, monkeypatch):
        """`main` se ha reescrito más de una vez (git filter-repo, la rotación del
        AGENT_TOKEN). Un 404 al comparar no es un fallo de red y no puede pintarse igual."""
        monkeypatch.setattr(main, "_version_desplegada", lambda: "b" * 40)
        mock_requests.add("GET", "/commits/main", FakeResponse(COMMIT_MAIN))
        mock_requests.add("GET", "/compare/", FakeResponse(None, 404))
        cuerpo = client.get("/dev/despliegue", headers=auth_headers).json()
        assert cuerpo["backend"]["conocido"] is False
        assert "historia" in cuerpo["backend"]["motivo"]

    def test_sin_fichero_VERSION_no_se_da_por_al_dia(self, client, auth_headers,
                                                     mock_requests, con_repo, monkeypatch):
        """En local no hay VERSION y `_version_desplegada` dice "desconocida". Compararlo
        habría mandado la cadena literal a la URL de GitHub."""
        monkeypatch.setattr(main, "_version_desplegada", lambda: "desconocida")
        mock_requests.add("GET", "/commits/main", FakeResponse(COMMIT_MAIN))
        cuerpo = client.get("/dev/despliegue", headers=auth_headers).json()
        assert cuerpo["backend"]["conocido"] is False
        assert not mock_requests.called("GET", "/compare/")

    def test_compara_tambien_el_sha_del_frontend(self, client, auth_headers, mock_requests,
                                                 con_repo, monkeypatch):
        monkeypatch.setattr(main, "_version_desplegada", lambda: "a" * 40)
        mock_requests.add("GET", "/commits/main", FakeResponse(COMMIT_MAIN))
        mock_requests.add("GET", "/compare/", FakeResponse({"ahead_by": 1, "commits": []}))
        cuerpo = client.get("/dev/despliegue?frontend=" + "e" * 40, headers=auth_headers).json()
        assert cuerpo["frontend"]["detras"] == 1

    @pytest.mark.parametrize("sha", ["../../etc", "zz" * 20, "a" * 41, "'; drop"])
    def test_el_sha_del_frontend_se_valida_antes_de_ir_a_la_url(self, client, auth_headers,
                                                                con_repo, sha):
        """Lo manda el navegador y acaba interpolado en una URL de GitHub."""
        r = client.get("/dev/despliegue", headers=auth_headers, params={"frontend": sha})
        assert r.status_code == 422

    def test_un_403_de_github_no_filtra_su_cuerpo(self, client, auth_headers, mock_requests,
                                                  con_repo):
        mock_requests.add("GET", "/commits/main", FakeResponse(None, 403, "rate limit: token abc"))
        r = client.get("/dev/despliegue", headers=auth_headers)
        assert r.status_code == 200          # no se rompe la pantalla por esto
        assert "abc" not in r.text
        assert r.json()["github"]["ok"] is False


class TestCrons:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/crons").status_code == 401

    def test_trae_el_ultimo_run_de_cada_programado(self, client, auth_headers,
                                                   mock_requests, con_repo):
        mock_requests.add("GET", "/actions/workflows/", FakeResponse({"workflow_runs": [{
            "status": "completed", "conclusion": "failure",
            "updated_at": "2026-09-08T04:20:00Z",
            "html_url": "https://github.com/x/y/actions/runs/1",
        }]}))
        cuerpo = client.get("/dev/crons", headers=auth_headers).json()
        nombres = {w["fichero"] for w in cuerpo["workflows"]}
        assert nombres == set(main.PROGRAMADOS)
        assert all(w["run"]["resultado"] == "failure" for w in cuerpo["workflows"])

    def test_cada_programado_va_en_su_propia_llamada(self, client, auth_headers,
                                                     mock_requests, con_repo):
        """Y no en el listado general de runs: cien runs de CI en una semana movida tapan
        el cron semanal, que es justo el que hay que ver."""
        client.get("/dev/crons", headers=auth_headers)
        pedidas = [c[1] for c in mock_requests.called("GET", "/actions/workflows/")]
        assert len(pedidas) == len(main.PROGRAMADOS)

    def test_una_tabla_caida_no_se_lleva_la_pantalla(self, client, auth_headers,
                                                     mock_requests, con_repo):
        mock_requests.add("GET", "/rest/v1/vigilante_estado", FakeResponse(None, 500, "boom"))
        mock_requests.add("GET", "/rest/v1/brief_envios",
                          FakeResponse([{"fecha": "2026-09-10", "fuente": "despertar"}]))
        r = client.get("/dev/crons", headers=auth_headers)
        assert r.status_code == 200
        cuerpo = r.json()
        # null es "no lo sé"; [] sería "no hay averías abiertas", que es otra cosa.
        assert cuerpo["vigilantes"] is None
        assert cuerpo["brief"][0]["fuente"] == "despertar"
        assert "boom" not in r.text

    def test_los_sondeos_salen_todos_aunque_nadie_haya_sondeado(self, client, auth_headers,
                                                                con_repo):
        cuerpo = client.get("/dev/crons", headers=auth_headers).json()
        assert {s["ruta"] for s in cuerpo["sondeos"]} == set(main.SONDEOS_VIGILADOS)
        # Nunca 0: "no ha sondeado nadie" y "sondeó hace nada" no se pueden confundir.
        assert all(s["hace_segundos"] is None for s in cuerpo["sondeos"])

    def test_un_sondeo_de_verdad_queda_apuntado(self, client, auth_headers, con_repo):
        client.get("/ha/wol-pending", headers={"X-Auth-Token": "ha-poll-token"})
        cuerpo = client.get("/dev/crons", headers=auth_headers).json()
        wol = next(s for s in cuerpo["sondeos"] if s["ruta"] == "/ha/wol-pending")
        assert wol["hace_segundos"] is not None

    def test_un_sondeo_con_el_token_mal_no_cuenta_como_sondeo(self, client, auth_headers,
                                                              con_repo):
        """Es justo el fallo que hay que ver: HA sigue llamando pero ya no entra."""
        client.get("/ha/wol-pending", headers={"X-Auth-Token": "el-que-no-es"})
        cuerpo = client.get("/dev/crons", headers=auth_headers).json()
        wol = next(s for s in cuerpo["sondeos"] if s["ruta"] == "/ha/wol-pending")
        assert wol["hace_segundos"] is None

    def test_el_dashboard_no_cuenta_como_sondeo(self, client, auth_headers, mock_requests,
                                                con_repo):
        """Solo se vigila lo que llama una máquina sola. Que el dashboard no haya entrado
        hoy no es una avería."""
        client.get("/presencia", headers=auth_headers)
        assert "/presencia" not in main.SONDEOS_VIGILADOS
        assert "/presencia" not in main._sondeos


class TestListaDeProgramados:
    """La lista de crons esperados vive a mano en el backend porque ni la API de GitHub
    publica el cron de un workflow ni el contenedor del add-on tiene los .yml. Esto es lo
    que evita que se quede atrás en silencio, que es el fallo del que nace la pestaña."""

    def _workflows_con_cron(self):
        raiz = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows")
        con_cron = set()
        for nombre in os.listdir(raiz):
            if not nombre.endswith(".yml"):
                continue
            with open(os.path.join(raiz, nombre), encoding="utf-8") as f:
                texto = f.read()
            # Solo el `schedule:` de la sección `on:`, no la palabra dentro de un comentario.
            if re.search(r"^\s{0,4}schedule:\s*$", texto, re.MULTILINE):
                con_cron.add(nombre)
        return con_cron

    def test_estan_todos_los_que_corren_solos(self):
        assert self._workflows_con_cron() == set(main.PROGRAMADOS)

    def test_cada_uno_dice_cada_cuanto_toca(self):
        for fichero, (nombre, horas) in main.PROGRAMADOS.items():
            assert nombre and horas > 0, fichero

"""Tests de las pestañas Base de datos y Config de la zona de desarrollo.

Lo que se fija aquí: que una migración sin aplicar se vea con ese nombre (es el fallo del
que nace la pestaña), que "cero filas" y "no lo sé" no se confundan nunca, que la lista de
tablas conocidas no se quede atrás respecto a las migraciones de verdad, y que la pantalla
de configuración **no devuelva jamás el valor de una variable**.
"""
import glob
import os
import re

import pytest

from conftest import FakeResponse

import main


def _fila(cuerpo, tabla):
    return next(t for t in cuerpo["tablas"] if t["tabla"] == tabla)


@pytest.fixture
def con_repo(monkeypatch):
    monkeypatch.setattr(main, "JARVIS_REPO", "malbisudlf/Life-Assistant")


@pytest.fixture
def contenido_de_migraciones(mock_requests):
    """Lo que devuelve la API de GitHub al pedir el directorio de migraciones."""
    mock_requests.add("GET", "/contents/supabase/migrations", FakeResponse([
        {"name": "20260707_esquema_base.sql"},
        {"name": "20260909_ideas_dev.sql"},
        {"name": "20260910_migraciones_aplicadas.sql"},
        {"name": "LEEME.txt"},          # lo que no sea .sql no cuenta
    ]))
    return mock_requests


class TestBd:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/bd").status_code == 401

    def test_cuenta_las_filas_de_cada_tabla(self, client, auth_headers, mock_requests, con_repo):
        mock_requests.add("GET", "/rest/v1/health_metrics",
                          FakeResponse([], 200, headers={"Content-Range": "0-24/1234"}))
        cuerpo = client.get("/dev/bd", headers=auth_headers).json()
        fila = _fila(cuerpo, "health_metrics")
        assert fila["existe"] is True
        assert fila["filas"] == 1234

    def test_no_se_trae_las_filas_para_contarlas(self, client, auth_headers, mock_requests, con_repo):
        """Contar trayendo sería descargar `health_metrics` entera al abrir la pestaña."""
        client.get("/dev/bd", headers=auth_headers)
        llamada = mock_requests.called("GET", "/rest/v1/health_metrics")[0]
        assert llamada[2]["params"]["limit"] == 0
        assert llamada[2]["headers"]["Prefer"] == "count=exact"

    def test_una_tabla_que_no_existe_dice_qué_migración_falta(self, client, auth_headers,
                                                              mock_requests, con_repo):
        """Es el caso que da sentido a la pestaña: no basta con "no existe"."""
        mock_requests.add("GET", "/rest/v1/salud_ajustes", FakeResponse(None, 404))
        cuerpo = client.get("/dev/bd", headers=auth_headers).json()
        fila = _fila(cuerpo, "salud_ajustes")
        assert fila["existe"] is False
        assert fila["migracion"] == "20260824_salud_ajustes"

    def test_sin_cuenta_no_se_inventa_un_cero(self, client, auth_headers, mock_requests, con_repo):
        """Supabase responde `*/*` cuando no ha contado. Un cero ahí diría "está vacía"
        de una tabla que puede tener diez mil filas."""
        mock_requests.add("GET", "/rest/v1/ideas",
                          FakeResponse([], 200, headers={"Content-Range": "*/*"}))
        fila = _fila(client.get("/dev/bd", headers=auth_headers).json(), "ideas")
        assert fila["existe"] is True
        assert fila["filas"] is None

    def test_cruza_el_repositorio_con_lo_aplicado(self, client, auth_headers,
                                                  contenido_de_migraciones, con_repo):
        contenido_de_migraciones.add("GET", "/rest/v1/migraciones_aplicadas", FakeResponse([
            {"nombre": "20260707_esquema_base", "aplicada": "2026-07-07T10:00:00Z"},
            {"nombre": "20260910_migraciones_aplicadas", "aplicada": "2026-09-10T10:00:00Z"},
        ]))
        cuerpo = client.get("/dev/bd", headers=auth_headers).json()
        por_nombre = {m["nombre"]: m for m in cuerpo["migraciones"]}
        assert por_nombre["20260707_esquema_base"]["puesta"] is True
        assert por_nombre["20260909_ideas_dev"]["puesta"] is False
        assert "LEEME" not in por_nombre

    def test_una_migracion_que_ya_no_esta_en_el_repo_se_marca(self, client, auth_headers,
                                                              contenido_de_migraciones, con_repo):
        contenido_de_migraciones.add("GET", "/rest/v1/migraciones_aplicadas", FakeResponse([
            {"nombre": "20260101_la_que_se_renombro", "aplicada": "2026-01-01T10:00:00Z"},
        ]))
        cuerpo = client.get("/dev/bd", headers=auth_headers).json()
        huerfana = next(m for m in cuerpo["migraciones"] if m["nombre"] == "20260101_la_que_se_renombro")
        assert huerfana["huerfana"] is True

    def test_sin_la_tabla_de_registro_lo_dice_nombrandola(self, client, auth_headers,
                                                          mock_requests, con_repo):
        """El día 0 la tabla no existe, y la pantalla tiene que decir qué pegar."""
        mock_requests.add("GET", "/rest/v1/migraciones_aplicadas", FakeResponse(None, 404))
        cuerpo = client.get("/dev/bd", headers=auth_headers).json()
        assert cuerpo["migraciones"] is None
        assert main.MIGRACION_DEL_REGISTRO in cuerpo["motivo"]

    def test_un_error_de_supabase_no_filtra_su_texto(self, client, auth_headers,
                                                     mock_requests, con_repo):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse(None, 500, "secreto interno"))
        r = client.get("/dev/bd", headers=auth_headers)
        assert r.status_code == 200
        assert "secreto interno" not in r.text
        assert _fila(r.json(), "jobs")["existe"] is None


class TestListaDeTablas:
    """La lista de tablas conocidas va a mano (el contenedor solo lleva `backend/`). Esto
    es lo que impide que se quede atrás en silencio."""

    def _tablas_de_las_migraciones(self):
        raiz = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
        tablas = set()
        for ruta in glob.glob(os.path.join(raiz, "*.sql")):
            with open(ruta, encoding="utf-8") as f:
                texto = f.read()
            for m in re.finditer(r"create table\s+(?:if not exists\s+)?(?:public\.)?([a-z_]+)",
                                 texto, re.IGNORECASE):
                tablas.add(m.group(1))
        return tablas

    def test_estan_todas_las_tablas_que_crean_las_migraciones(self):
        assert self._tablas_de_las_migraciones() == set(main.TABLAS_CONOCIDAS)

    def test_cada_tabla_apunta_a_una_migracion_que_existe(self):
        raiz = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
        ficheros = {os.path.basename(r)[:-4] for r in glob.glob(os.path.join(raiz, "*.sql"))}
        for tabla, migracion in main.TABLAS_CONOCIDAS.items():
            assert migracion in ficheros, tabla

    def test_la_migracion_del_registro_se_declara_a_si_misma(self):
        """Sin esa línea, aplicarla dejaría la pestaña diciendo que falta para siempre."""
        raiz = os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migrations")
        with open(os.path.join(raiz, f"{main.MIGRACION_DEL_REGISTRO}.sql"), encoding="utf-8") as f:
            texto = f.read()
        assert f"('{main.MIGRACION_DEL_REGISTRO}')" in texto


class TestConfig:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/config").status_code == 401

    def test_dice_qué_falta_por_funcionalidad(self, client, auth_headers, mock_requests):
        cuerpo = client.get("/dev/config", headers=auth_headers).json()
        por_nombre = {g["nombre"]: g for g in cuerpo["grupos"]}
        # El entorno de los tests tiene Supabase configurado y no tiene SMTP.
        assert por_nombre["Base de datos (ideas, salud, entrenamiento, jobs)"]["completo"] is True
        resumen = next(g for g in cuerpo["grupos"] if g["nombre"].startswith("Resumen diario"))
        assert "SMTP_HOST" in resumen["faltan"]

    def test_nunca_devuelve_el_valor_de_una_variable(self, client, auth_headers, mock_requests):
        """Esta pantalla va tras un JWT de 30 días: si devolviera valores, sería un
        volcado de secretos con una puerta de 30 días."""
        texto = client.get("/dev/config", headers=auth_headers).text
        for secreto in (os.getenv("SUPABASE_KEY"), os.getenv("SECRET_KEY"),
                        os.getenv("OPENAI_API_KEY"), os.getenv("AGENT_TOKEN")):
            assert secreto and secreto not in texto

    def test_la_lista_es_la_misma_que_la_de_la_consola(self, client, auth_headers, mock_requests):
        """Dos listas de "qué falta" acaban diciendo cosas distintas."""
        from check_config import GRUPOS
        cuerpo = client.get("/dev/config", headers=auth_headers).json()
        assert [g["nombre"] for g in cuerpo["grupos"]] == [n for n, _ in GRUPOS]

    def test_sin_outlook_conectado_lo_dice(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/oauth_tokens", FakeResponse([]))
        cuerpo = client.get("/dev/config", headers=auth_headers).json()
        assert cuerpo["graph"]["conectado"] is False

    def test_con_outlook_conectado_no_devuelve_el_token(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/oauth_tokens", FakeResponse([{
            "provider": "microsoft", "expires_at": 4102444800.0,
            "updated_at": "2026-09-10T10:00:00Z", "refresh_token": "refresco-secreto",
        }]))
        r = client.get("/dev/config", headers=auth_headers)
        assert r.json()["graph"]["con_refresco"] is True
        assert "refresco-secreto" not in r.text

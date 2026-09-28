"""Tests de los arreglos de seguridad de septiembre de 2026.

- El tope de cuerpo global (`_TopeDeCuerpo`): con `body: <Modelo>`, FastAPI cargaba y
  parseaba el JSON entero ANTES de comprobar el token, así que un desconocido metía en
  memoria lo que quisiera y se llevaba un 422.
- El login serializado (`_login_lock`): leer el recuento, comparar y apuntar el fallo
  no era atómico, y una ráfaga concurrente pasaba entera por encima del límite.
- `_ip_publica` rechaza lo que no es `is_global`: 100.64.0.0/10 (CGNAT, la tailnet)
  pasaba el filtro anti-SSRF de `leer_pagina`.
- Ningún correo personal ni IP de la LAN en ficheros versionados (repo público).
"""
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone

import pytest

import main
from conftest import FakeResponse

GRANDE = 300 * 1024   # por encima de MAX_BODY_BYTES (256 KB)
RAIZ   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestTopeDeCuerpo:
    @pytest.mark.parametrize("ruta", [
        "/revision/hallazgos", "/sesion/aviso", "/averia", "/programado/roto",
        "/ha/presencia", "/auth/password", "/jobs",
    ])
    def test_cuerpo_grande_sin_credencial_da_413_sin_leerlo(self, client, ruta):
        """Antes: 422 tras cargar y parsear el cuerpo entero, sin haber mirado el token."""
        r = client.post(ruta, content=b"x" * GRANDE,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

    def test_chunked_sin_content_length_tambien_se_corta(self, client, monkeypatch):
        """Sin `Content-Length` no hay cabecera que mirar: se cuenta el stream."""
        llamado = []
        monkeypatch.setattr(main, "_token_ok", lambda *a, **k: llamado.append(1) or False)
        trozos = iter([b"x" * (64 * 1024)] * 5)
        r = client.post("/revision/hallazgos", content=trozos,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        assert llamado == []

    def test_cuerpo_normal_sin_token_sigue_dando_403(self, client, monkeypatch):
        monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
        r = client.post("/revision/hallazgos", json={"numero": 1, "titulo": "x"})
        assert r.status_code == 403

    def test_el_tope_se_configura(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_BODY_BYTES", 100)
        r = client.post("/auth/password", json={"password": "1" * 200})
        assert r.status_code == 413

    def test_la_foto_de_la_prenda_cabe(self, client, auth_headers, mock_requests):
        """La excepción del tope: la foto viaja como data URL de hasta ~3 MB en el JSON."""
        mock_requests.add("POST", "/rest/v1/clothing",
                          FakeResponse([{"id": "1", "name": "camisa"}], 201))
        foto = "data:image/jpeg;base64," + "A" * (1024 * 1024)
        r = client.post("/clothing", headers=auth_headers,
                        json={"name": "camisa", "price": 10, "currency": "EUR", "photo": foto})
        assert r.status_code == 200

    def test_la_ingesta_conserva_su_propio_tope(self, client, mock_requests):
        """`/health/ingest` admite hasta MAX_INGEST_BYTES, por encima del tope general."""
        cuerpo = {"data": {"metrics": []}, "relleno": "x" * GRANDE}
        r = client.post("/health/ingest", json=cuerpo,
                        headers={"X-Auth-Token": "health-token"})
        assert r.status_code != 413

    def test_una_excepcion_nunca_baja_el_tope_general(self, monkeypatch):
        monkeypatch.setattr(main, "MAX_INGEST_BYTES", 100)
        assert main._tope_de_cuerpo("/health/ingest") == main.MAX_BODY_BYTES
        assert main._tope_de_cuerpo("/cualquier/otra") == main.MAX_BODY_BYTES


class TestLoginConcurrente:
    def test_una_rafaga_no_pasa_del_limite_de_intentos(self, mock_requests, monkeypatch):
        """Con Supabase tardando lo que tarda de verdad, las peticiones de una ráfaga leían
        todas el recuento antes de que se apuntara el primer fallo: 40 comparaciones de
        contraseña con un límite de 5."""
        monkeypatch.setattr(main, "LOGIN_MAX_ATTEMPTS", 5)
        fallos, cerrojo = [], threading.Lock()

        def _get(url, **kwargs):
            with cerrojo:
                copia = list(fallos)
            time.sleep(0.15)
            return FakeResponse([{"created_at": t} for t in copia])

        def _post(url, **kwargs):
            time.sleep(0.05)
            with cerrojo:
                fallos.append(datetime.now(timezone.utc).isoformat())
            return FakeResponse([], 201)

        mock_requests.add("GET", "/rest/v1/login_attempts", _get)
        mock_requests.add("POST", "/rest/v1/login_attempts", _post)

        codigos, barrera = [], threading.Barrier(20)
        peticion = type("Peticion", (), {"headers": {}, "client": None})()

        def _intento():
            barrera.wait()
            try:
                main.login_password(main.LoginRequest(password="0000"), peticion)
                codigos.append(200)
            except main.HTTPException as e:
                codigos.append(e.status_code)

        hilos = [threading.Thread(target=_intento) for _ in range(20)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert len(codigos) == 20
        assert codigos.count(401) <= main.LOGIN_MAX_ATTEMPTS
        assert set(codigos) <= {401, 429}

    def test_en_serie_el_login_sigue_igual(self, client, login_attempts_mock):
        """El lock se suelta siempre: acertar después de fallar sigue funcionando."""
        assert client.post("/auth/password", json={"password": "0000"}).status_code == 401
        assert client.post("/auth/password", json={"password": "1234"}).status_code == 200
        assert not main._login_lock.locked()


class TestSSRFRangoCGNAT:
    @pytest.mark.parametrize("ip", ["100.64.0.9", "100.100.100.100", "100.127.255.254"])
    def test_la_tailnet_no_es_internet_publico(self, monkeypatch, ip):
        monkeypatch.setattr(main.socket, "getaddrinfo",
                            lambda *a, **k: [(2, 1, 6, "", (ip, 0))])
        assert main.url_web_permitida("http://malo.example:8123/api/") is False

    def test_una_ip_publica_sigue_pasando(self, monkeypatch):
        monkeypatch.setattr(main.socket, "getaddrinfo",
                            lambda *a, **k: [(2, 1, 6, "", ("100.128.0.1", 0))])
        assert main.url_web_permitida("https://justo-fuera-del-rango.example/") is True


def _ficheros_versionados():
    """Rastreados + nuevos sin commitear (pero no ignorados): un fichero recién creado
    con un dato personal, aún en `??` para git, tiene que saltar igual que uno editado."""
    try:
        salida = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                                "--exclude-standard"], cwd=RAIZ, capture_output=True,
                                check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("sin git no se sabe qué está versionado")
    return [f for f in salida.decode("utf-8", "replace").split("\0") if f]


def _buscar(patron, excluir=()):
    """Fichero y línea de cada coincidencia, NUNCA el texto encontrado: el log del CI de
    un repositorio público también es público, y enseñar el dato en el fallo del test
    sería publicarlo por otro lado."""
    hallados = []
    for relativa in _ficheros_versionados():
        if relativa.startswith(excluir) or relativa.endswith("package-lock.json"):
            continue
        try:
            with open(os.path.join(RAIZ, relativa), encoding="utf-8") as f:
                texto = f.read()
        except (OSError, UnicodeDecodeError):
            continue   # binarios o borrados del árbol de trabajo
        hallados += [f"{relativa}:{texto.count(chr(10), 0, m.start()) + 1}"
                     for m in patron.finditer(texto)]
    return hallados


class TestRepoPublicoSinDatosPersonales:
    """El repositorio es público. Se lee el árbol de trabajo, no el commit: así también
    salta con un cambio aún sin commitear, que es cuando todavía se puede parar."""

    def test_ningun_correo_de_buzon_personal(self):
        patron = re.compile(r"\b(?!tu@)[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|yahoo|icloud)"
                            r"\.[a-z.]{2,6}\b", re.I)
        assert _buscar(patron) == []

    def test_ninguna_ip_de_la_lan(self):
        """`192.168.1.XXX` es el marcador que ya se usa; los tests llevan IPs inventadas."""
        patron = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")
        assert _buscar(patron, excluir=("tests/",)) == []

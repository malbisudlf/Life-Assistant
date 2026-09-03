"""Tests de `scripts/copia_supabase.py` (la copia de seguridad cifrada de Supabase).

Las peticiones a Supabase van simuladas: se sustituye `copia.http.get`, igual que el
`conftest.py` del backend sustituye `main.http`. El script no se importa desde `main`,
así que no comparte su `MockRouter` — aquí basta con un doble muy pequeño porque solo
hay un tipo de petición (un GET paginado por tabla).

El test que más importa del fichero es el último: **nada de lo que imprime el script
puede llevar un dato**. Su salida acaba en el log de un workflow de un repositorio
público, así que un `print` de más ahí dentro anula todo el cifrado.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import copia_supabase as copia  # noqa: E402


URL = "https://supabase.test"
CLAVE = "supa-test-key"
FRASE = "frase-de-prueba-1234"


class RespuestaFalsa:
    def __init__(self, filas, total=None, status_code=200):
        self._filas = filas
        self.status_code = status_code
        self.headers = {}
        if total is not None:
            fin = max(len(filas) - 1, 0)
            self.headers["Content-Range"] = f"0-{fin}/{total}"

    def json(self):
        return self._filas


class SupabaseFalso:
    """Devuelve páginas por tabla y apunta las URLs pedidas."""

    def __init__(self, paginas_por_tabla, totales=None):
        self.paginas = {t: list(p) for t, p in paginas_por_tabla.items()}
        self.totales = totales or {}
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        tabla = url.split("/rest/v1/")[1].split("?")[0]
        pendientes = self.paginas.get(tabla)
        filas = pendientes.pop(0) if pendientes else []
        return RespuestaFalsa(filas, total=self.totales.get(tabla))


def _tabla(nombre, obligatoria=False, orden="id", columnas=None):
    return (nombre, orden, obligatoria, columnas)


def _fila(n):
    """Fila con la forma de `health_metrics`, con un valor reconocible en los tests."""
    return {"metric_date": f"2026-01-{n % 28 + 1:02d}", "metric_name": "step_count",
            "value": 10000 + n, "unit": "count", "extra": None}


# ── Paginación ───────────────────────────────────────────────────────────────

class TestPaginacion:
    def test_junta_todas_las_paginas(self, monkeypatch):
        pagina1 = [_fila(i) for i in range(copia.PAGINA)]
        pagina2 = [_fila(i) for i in range(copia.PAGINA, copia.PAGINA + 7)]
        falso = SupabaseFalso({"health_metrics": [pagina1, pagina2]},
                              totales={"health_metrics": copia.PAGINA + 7})
        monkeypatch.setattr(copia.http, "get", falso.get)

        filas = copia.descargar_tabla("health_metrics", "metric_date", None, URL, CLAVE)

        assert len(filas) == copia.PAGINA + 7
        assert len(falso.urls) == 2
        assert "offset=0" in falso.urls[0]
        assert f"offset={copia.PAGINA}" in falso.urls[1]

    def test_pide_orden_y_recuento_exacto(self, monkeypatch):
        falso = SupabaseFalso({"ideas": [[]]}, totales={"ideas": 0})
        monkeypatch.setattr(copia.http, "get", falso.get)
        cabeceras = {}

        def espia(url, headers=None, timeout=None):
            cabeceras.update(headers or {})
            return falso.get(url, headers, timeout)

        monkeypatch.setattr(copia.http, "get", espia)
        copia.descargar_tabla("ideas", "created_at,id", None, URL, CLAVE)

        assert "order=created_at,id" in falso.urls[0]
        assert cabeceras.get("Prefer") == "count=exact"

    def test_una_pagina_mas_corta_de_lo_pedido_no_corta_la_descarga(self, monkeypatch):
        """El servidor puede devolver menos filas de las pedidas (`db-max-rows`).

        Si el bucle parase ahí, la copia saldría truncada y con buena pinta. Manda el
        total del `Content-Range`, no el tamaño del lote.
        """
        falso = SupabaseFalso(
            {"health_metrics": [[_fila(i) for i in range(3)],
                                [_fila(i) for i in range(3, 5)]]},
            totales={"health_metrics": 5})
        monkeypatch.setattr(copia.http, "get", falso.get)

        filas = copia.descargar_tabla("health_metrics", "metric_date", None, URL, CLAVE)

        assert len(filas) == 5
        assert len(falso.urls) == 2

    def test_faltan_filas_respecto_al_total_es_error(self, monkeypatch):
        # Supabase dice que hay 9 y solo entrega 2: la copia estaría incompleta.
        falso = SupabaseFalso({"health_metrics": [[_fila(0), _fila(1)], []]},
                              totales={"health_metrics": 9})
        monkeypatch.setattr(copia.http, "get", falso.get)

        with pytest.raises(copia.ErrorCopia, match="9 filas"):
            copia.descargar_tabla("health_metrics", "metric_date", None, URL, CLAVE)

    def test_error_http_revienta_sin_devolver_el_cuerpo(self, monkeypatch):
        monkeypatch.setattr(copia.http, "get",
                            lambda *a, **k: RespuestaFalsa([], status_code=500))

        with pytest.raises(copia.ErrorCopia) as e:
            copia.descargar_tabla("ideas", "id", None, URL, CLAVE)
        assert "500" in str(e.value)

    def test_columnas_concretas_llegan_al_select(self, monkeypatch):
        falso = SupabaseFalso({"jarvis_mcp_servidores": [[]]},
                              totales={"jarvis_mcp_servidores": 0})
        monkeypatch.setattr(copia.http, "get", falso.get)

        copia.descargar_tabla("jarvis_mcp_servidores", "nombre", "nombre,url",
                              URL, CLAVE)

        assert "select=nombre,url" in falso.urls[0]

    def test_la_tabla_de_mcp_no_copia_el_token(self):
        """La configuración de MCP se copia sin su credencial de GitHub."""
        entrada = next(t for t in copia.TABLAS if t[0] == "jarvis_mcp_servidores")
        assert entrada[3] is not None and "token" not in entrada[3]

    def test_oauth_tokens_no_esta_en_la_lista(self):
        """Copiar un refresh token vivo solo multiplica dónde vive esa credencial."""
        assert "oauth_tokens" not in {t[0] for t in copia.TABLAS}


# ── Una copia vacía no es una copia ──────────────────────────────────────────

class TestVerificacion:
    def test_tabla_obligatoria_vacia_falla(self):
        tablas = (_tabla("health_metrics", obligatoria=True), _tabla("ideas"))
        with pytest.raises(copia.ErrorCopia, match="0 filas"):
            copia.verificar_recuentos({"health_metrics": 0, "ideas": 3}, tablas)

    def test_tabla_obligatoria_ausente_falla(self):
        tablas = (_tabla("health_metrics", obligatoria=True),)
        with pytest.raises(copia.ErrorCopia, match="falta la tabla"):
            copia.verificar_recuentos({"ideas": 3}, tablas)

    def test_tabla_opcional_vacia_no_falla(self):
        tablas = (_tabla("health_metrics", obligatoria=True), _tabla("clothing"))
        copia.verificar_recuentos({"health_metrics": 12, "clothing": 0}, tablas)

    def test_health_metrics_es_obligatoria_en_la_lista_real(self):
        obligatorias = {t[0] for t in copia.TABLAS if t[2]}
        assert "health_metrics" in obligatorias

    def test_no_escribe_fichero_si_la_copia_esta_vacia(self, monkeypatch, tmp_path):
        falso = SupabaseFalso({"health_metrics": [[]]}, totales={"health_metrics": 0})
        monkeypatch.setattr(copia.http, "get", falso.get)
        destino = tmp_path / "copia.json.gpg"

        with pytest.raises(copia.ErrorCopia):
            copia.hacer_copia(URL, CLAVE, FRASE, str(destino),
                              tablas=(_tabla("health_metrics", obligatoria=True,
                                             orden="metric_date"),))

        # Lo importante: la copia buena de ayer sigue donde estaba.
        assert not destino.exists()

    def test_content_range_sin_total_se_ignora(self):
        assert copia.total_de_content_range("0-24/*") is None
        assert copia.total_de_content_range(None) is None
        assert copia.total_de_content_range("0-24/113") == 113


# ── Cifrado: ida y vuelta con gpg de verdad ──────────────────────────────────

sin_gpg = pytest.mark.skipif(shutil.which("gpg") is None,
                             reason="gpg no está instalado en esta máquina")


@sin_gpg
class TestCifrado:
    def _copia(self, monkeypatch, tmp_path, filas=5):
        falso = SupabaseFalso({"health_metrics": [[_fila(i) for i in range(filas)]]},
                              totales={"health_metrics": filas})
        monkeypatch.setattr(copia.http, "get", falso.get)
        destino = tmp_path / "copia.json.gpg"
        recuentos = copia.hacer_copia(
            URL, CLAVE, FRASE, str(destino),
            tablas=(_tabla("health_metrics", obligatoria=True, orden="metric_date"),))
        return destino, recuentos

    def test_ida_y_vuelta(self, monkeypatch, tmp_path):
        destino, recuentos = self._copia(monkeypatch, tmp_path)

        assert recuentos == {"health_metrics": 5}
        assert copia.recuentos_del_fichero(str(destino), FRASE) == {"health_metrics": 5}

    def test_el_fichero_no_tiene_los_datos_en_claro(self, monkeypatch, tmp_path):
        destino, _ = self._copia(monkeypatch, tmp_path)
        crudo = destino.read_bytes()

        assert b"health_metrics" not in crudo
        assert b"step_count" not in crudo
        assert b"10000" not in crudo

    def test_con_otra_frase_no_se_abre(self, monkeypatch, tmp_path):
        destino, _ = self._copia(monkeypatch, tmp_path)

        with pytest.raises(copia.ErrorCopia, match="descifrar"):
            copia.recuentos_del_fichero(str(destino), "otra-frase-distinta")

    def test_repetirla_el_mismo_dia_deja_una_copia_buena(self, monkeypatch, tmp_path):
        """Idempotencia: la segunda pasada pisa la primera y el resultado se abre igual."""
        destino, _ = self._copia(monkeypatch, tmp_path, filas=5)
        destino, recuentos = self._copia(monkeypatch, tmp_path, filas=5)

        assert recuentos == {"health_metrics": 5}
        assert copia.recuentos_del_fichero(str(destino), FRASE) == {"health_metrics": 5}

    def test_verificar_desde_la_linea_de_ordenes(self, monkeypatch, tmp_path, capsys):
        destino, _ = self._copia(monkeypatch, tmp_path)
        monkeypatch.setenv("COPIA_PASSPHRASE", FRASE)

        assert copia.main(["--verificar", str(destino)]) == 0
        salida = capsys.readouterr().out
        assert "health_metrics: 5 filas" in salida

    def test_verificar_un_fichero_roto_sale_con_error(self, monkeypatch, tmp_path,
                                                      capsys):
        roto = tmp_path / "roto.json.gpg"
        roto.write_bytes(b"esto no es gpg")
        monkeypatch.setenv("COPIA_PASSPHRASE", FRASE)

        assert copia.main(["--verificar", str(roto)]) == 1
        assert "ERROR" in capsys.readouterr().err

    def test_la_frase_no_viaja_en_la_linea_de_ordenes(self, monkeypatch, tmp_path):
        """`--passphrase` la dejaría visible en la lista de procesos de la máquina."""
        vistas = []
        original = subprocess.run

        def espia(orden, **kwargs):
            vistas.append(list(orden))
            return original(orden, **kwargs)

        monkeypatch.setattr(copia.subprocess, "run", espia)
        self._copia(monkeypatch, tmp_path)

        assert vistas
        for orden in vistas:
            assert FRASE not in orden
            assert "--passphrase" not in orden

    def test_no_deja_la_frase_en_un_fichero_al_terminar(self, monkeypatch, tmp_path):
        rutas = []
        original = copia.subprocess.run

        def espia(orden, **kwargs):
            rutas.append(orden[orden.index("--passphrase-file") + 1])
            return original(orden, **kwargs)

        monkeypatch.setattr(copia.subprocess, "run", espia)
        self._copia(monkeypatch, tmp_path)

        assert rutas
        assert not any(os.path.exists(r) for r in rutas)


# ── Nada de lo que se imprime puede llevar un dato ───────────────────────────

class TestSalidaSinDatos:
    def test_solo_se_registran_nombres_de_tabla_y_recuentos(self, monkeypatch, capsys):
        """El log del workflow es público: ahí no puede aparecer ni un valor."""
        filas = [{"metric_date": "2026-01-05", "metric_name": "heart_rate_variability",
                  "value": 42.7, "unit": "ms", "extra": {"sleep_start": "23:41"}}]
        ideas = [{"id": "9f", "key": "secreto", "full_text": "llamar al medico"}]
        falso = SupabaseFalso({"health_metrics": [filas], "ideas": [ideas]},
                              totales={"health_metrics": 1, "ideas": 1})
        monkeypatch.setattr(copia.http, "get", falso.get)
        monkeypatch.setattr(copia, "cifrar", lambda datos, frase, destino: None)
        monkeypatch.setattr(copia, "recuentos_del_fichero",
                            lambda ruta, frase: {"health_metrics": 1, "ideas": 1})

        copia.hacer_copia(URL, CLAVE, FRASE, str(os.devnull),
                          tablas=(_tabla("health_metrics", obligatoria=True,
                                         orden="metric_date"),
                                  _tabla("ideas")))

        salida = capsys.readouterr()
        texto = salida.out + salida.err
        for prohibido in ("42.7", "23:41", "secreto", "llamar al medico",
                          "heart_rate_variability", CLAVE, FRASE):
            assert prohibido not in texto
        assert "health_metrics: 1 filas" in texto

    def test_el_error_http_no_lleva_el_cuerpo_de_supabase(self, monkeypatch):
        class Respuesta500:
            status_code = 500
            headers = {}
            text = "value 42.7 para 2026-01-05"

            def json(self):
                return {}

        monkeypatch.setattr(copia.http, "get", lambda *a, **k: Respuesta500())

        with pytest.raises(copia.ErrorCopia) as e:
            copia.descargar_tabla("health_metrics", "metric_date", None, URL, CLAVE)
        assert "42.7" not in str(e.value)

    def test_falta_una_variable_de_entorno_y_lo_dice_sin_valores(self, monkeypatch,
                                                                 capsys):
        monkeypatch.delenv("COPIA_PASSPHRASE", raising=False)

        assert copia.main([]) == 1
        error = capsys.readouterr().err
        assert "COPIA_PASSPHRASE" in error

    def test_el_volcado_lleva_version_y_recuentos(self, monkeypatch):
        falso = SupabaseFalso({"health_metrics": [[_fila(0)]]},
                              totales={"health_metrics": 1})
        monkeypatch.setattr(copia.http, "get", falso.get)

        volcado = copia.construir_copia(
            URL, CLAVE, tablas=(_tabla("health_metrics", obligatoria=True,
                                       orden="metric_date"),))

        assert volcado["version"] == copia.VERSION_FORMATO
        assert volcado["recuentos"] == {"health_metrics": 1}
        # Serializable sin sorpresas: es lo que se cifra tal cual.
        assert json.loads(json.dumps(volcado))["tablas"]["health_metrics"]

    def test_el_nombre_del_fichero_lleva_el_dia(self):
        from datetime import datetime, timezone
        ruta = copia.nombre_por_defecto("copias",
                                        datetime(2026, 9, 3, tzinfo=timezone.utc))
        assert ruta.endswith("copia-supabase-2026-09-03.json.gpg")

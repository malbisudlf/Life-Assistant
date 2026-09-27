"""Tests de los arreglos en el E2E, la copia de seguridad y la documentación de Fly
(segunda revisión del 2026-09-27).

- La alarma simulada del E2E se ponía «mañana a las 06:30 UTC»: de madrugada caía hoy en
  hora local, y desde el cambio al horario de invierno ya no son las 08:30 en Madrid.
- La copia de seguridad no llevaba `alarmas`, y nadie lo había decidido: lo que no está
  en `TABLAS` ni se copia ni sale como ausente.
- El CI, `docs/FRONTEND.md` y `agent/PUESTA_A_PUNTO.md` seguían mandando a Fly, que está
  suspendida desde que el backend vive en `caja`.

Sin importar `tests/e2e/servidor_pruebas.py`: al importarse rellena `os.environ` con
valores del E2E que no pintan nada en el resto de la suite. La función se saca del
fichero con `ast` y se ejecuta sola, igual que `test_arreglos_scripts_ci.py` lee sus
rutas.
"""
import ast
import glob
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")
WORKFLOWS = os.path.join(RAIZ, ".github", "workflows")

sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import copia_supabase as copia  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")


def _leer(*partes):
    with open(os.path.join(RAIZ, *partes), encoding="utf-8") as f:
        return f.read()


def _funcion_del_simulador(nombre):
    """Compila solo esa función de servidor_pruebas.py, sin ejecutar el módulo."""
    fuente = _leer("tests", "e2e", "servidor_pruebas.py")
    nodo = next(n for n in ast.parse(fuente).body
                if isinstance(n, ast.FunctionDef) and n.name == nombre)
    espacio = {"datetime": datetime, "timedelta": timedelta, "timezone": timezone}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), "servidor_pruebas.py", "exec"),
         espacio)
    return espacio[nombre]


class TestAlarmaDelE2E:
    """El widget escribe la alarma comparando días en la zona del navegador; el
    simulador tiene que ponerla «mañana a las 08:30» en esa misma zona."""

    def _en_madrid(self, iso):
        return datetime.fromisoformat(iso).astimezone(MADRID)

    def test_de_madrugada_sigue_siendo_manana(self):
        """01:45 en Madrid son las 23:45 UTC del día anterior: `_dia(1)` en UTC daba hoy."""
        manana_a_las = _funcion_del_simulador("_manana_a_las")
        ahora = datetime(2026, 9, 27, 23, 45, tzinfo=timezone.utc)
        local = self._en_madrid(manana_a_las(8, 30, MADRID, ahora))
        assert (local.date().isoformat(), local.strftime("%H:%M")) == ("2026-09-29", "08:30")

    def test_en_horario_de_invierno_siguen_siendo_las_ocho_y_media(self):
        """Con la hora fija en 06:30 UTC, desde el 25 de octubre salían las 07:30."""
        manana_a_las = _funcion_del_simulador("_manana_a_las")
        ahora = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        cuando = manana_a_las(8, 30, MADRID, ahora)
        assert cuando == "2026-11-11T07:30:00+00:00"
        assert self._en_madrid(cuando).strftime("%H:%M") == "08:30"

    def test_la_ruta_de_alarmas_la_usa(self):
        fuente = _leer("tests", "e2e", "servidor_pruebas.py")
        assert '"cuando": _manana_a_las(8, 30, main.LOCAL_TZ)' in fuente

    def test_navegador_y_backend_cuentan_los_dias_con_la_misma_zona(self):
        """Arreglar solo el simulador movía el fallo a CI, cuyo navegador va en UTC."""
        config = _leer("playwright.config.js")
        zona = re.search(r"^const ZONA_E2E\s*=\s*'([^']+)'", config, re.MULTILINE)
        assert zona, "playwright.config.js no fija la zona del E2E"
        assert "timezoneId: ZONA_E2E" in config
        assert "env: { TIMEZONE: ZONA_E2E }" in config
        # Y el simulador, lanzado a mano sin Playwright, usa la misma por defecto.
        simulador = _leer("tests", "e2e", "servidor_pruebas.py")
        assert f'os.environ.setdefault("TIMEZONE", "{zona.group(1)}")' in simulador


class TestCopiaSinTablasOlvidadas:
    """Cada tabla de las migraciones está decidida: se copia o se deja fuera a
    propósito. Una que no esté en ninguna lista no se consulta nunca."""

    def _tablas_de_las_migraciones(self):
        patron = re.compile(r"create table (?:if not exists )?(?:public\.)?([a-z_]+)",
                            re.IGNORECASE)
        tablas = set()
        for fichero in glob.glob(os.path.join(RAIZ, "supabase", "migrations", "*.sql")):
            with open(fichero, encoding="utf-8") as f:
                tablas.update(patron.findall(f.read()))
        return tablas

    def test_ninguna_tabla_queda_sin_decidir(self):
        copiadas = {t[0] for t in copia.TABLAS}
        sin_decidir = self._tablas_de_las_migraciones() - copiadas - copia.SIN_COPIA
        assert not sin_decidir, f"ni en TABLAS ni en SIN_COPIA: {sorted(sin_decidir)}"

    def test_ninguna_esta_en_las_dos_listas(self):
        assert not ({t[0] for t in copia.TABLAS} & copia.SIN_COPIA)

    def test_las_alarmas_se_copian(self):
        entrada = next((t for t in copia.TABLAS if t[0] == "alarmas"), None)
        assert entrada is not None
        # Orden estable por columnas NOT NULL de su migración, y opcional: no tener
        # alarmas puestas no invalida la copia.
        assert entrada[1] == "cuando,id"
        assert entrada[2] is False


class TestNadieMandaAFly:
    """Fly está suspendida y el backend vive en `caja` desde el 2026-09-20. Una guía que
    manda a Fly configura una app que no atiende tráfico."""

    def test_los_workflows_solo_citan_workflows_que_existen(self):
        """ci.yml decía que el backend se desplegaba con `deploy-backend.yml`, borrado."""
        existentes = set(os.listdir(WORKFLOWS))
        citados = set()
        for fichero in existentes:
            if fichero.endswith(".yml"):
                citados.update(re.findall(r"[a-z0-9_-]+\.yml",
                                          _leer(".github", "workflows", fichero)))
        assert citados <= existentes, f"no existen: {sorted(citados - existentes)}"

    def test_la_version_de_python_no_se_justifica_con_fly(self):
        for fichero in ("ci.yml", "evals-jarvis.yml"):
            assert "imagen de Fly" not in _leer(".github", "workflows", fichero), fichero
        assert _leer("backend", "Dockerfile").startswith("FROM python:3.11-slim")

    def test_la_guia_del_frontend_no_da_el_arranque_en_frio_por_vigente(self):
        guia = " ".join(_leer("docs", "FRONTEND.md").split())
        assert "porque Fly escala a cero" not in guia
        assert "el default de Fly" not in guia

    def test_la_puesta_a_punto_del_correo_no_manda_a_fly(self):
        guia = _leer("agent", "PUESTA_A_PUNTO.md")
        seccion = guia[guia.index("## 2. Configurar el correo"):]
        # Ningún paso pendiente ni ninguna orden de un bloque de código es de Fly (el
        # texto sí puede nombrarla para decir por qué ya no).
        pendientes = [l for l in seccion.splitlines() if l.lstrip().startswith("- [ ]")]
        assert not [l for l in pendientes if "fly " in l.lower()]
        assert not re.search(r"^\s*fly ", seccion, re.MULTILINE)
        assert "de Fly y de GitHub" not in seccion
        assert "que en Fly" not in seccion

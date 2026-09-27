"""Tests de los arreglos en workflows, scripts y arneses (revisión del 2026-09-27).

- `revision-aviso.yml` aceptaba el issue de cualquier cuenta con el título «Revisión
  nocturna»: en un repositorio público, eso es dejar que un desconocido lance el arreglo.
- `programado-roto.yml` no escuchaba al resumen diario, que corre solo y fallaba en rojo
  sin que llegara un aviso.
- `ci-averiado.yml` se tragaba el CI de un PR abierto desde el `main` de un fork.
- La copia de seguridad no llevaba `ideas_dev`, escrita a mano.
- El router del E2E servía las notas por voz a `/dev/ideas`.
- El add-on del Green, que hoy es la reserva, nacía en `boot: auto`.

No hay PyYAML en el proyecto y no se añade por esto: igual que `test_addon_green.py`,
las comprobaciones van por texto, que para estas preguntas basta.
"""
import ast
import os
import re
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")
WORKFLOWS = os.path.join(RAIZ, ".github", "workflows")

sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import copia_supabase as copia  # noqa: E402


def _leer(*partes):
    with open(os.path.join(RAIZ, *partes), encoding="utf-8") as f:
        return f.read()


def _if_del_job(texto):
    """El `if:` del job (folded `>` o en una línea), con los espacios normalizados."""
    m = re.search(r"^    if:\s*>\s*\n((?:      .*\n)+)", texto, re.MULTILINE)
    if m:
        cuerpo = m.group(1)
    else:
        m = re.search(r"^    if:\s*(.+)$", texto, re.MULTILINE)
        assert m, "el job no tiene `if:`"
        cuerpo = m.group(1)
    return " ".join(cuerpo.split())


class TestRevisionAvisoSoloDelDueno:
    """Con el título como único filtro, el issue de un desconocido llegaba al móvil como
    una revisión de verdad —botón que mergea incluido— o lanzaba el arreglo de noche."""

    def test_exige_que_el_issue_lo_abra_el_dueno(self):
        condicion = _if_del_job(_leer(".github", "workflows", "revision-aviso.yml"))
        assert condicion.startswith(
            "github.event.issue.user.login == github.repository_owner && (")
        # El resto va entre paréntesis: sin ellos, el `||` de la etiqueta se saltaría la
        # comprobación del autor.
        assert condicion.endswith(")")
        assert "startsWith(github.event.issue.title, 'Revisión nocturna')" in condicion

    def test_la_skill_de_arreglo_mira_el_autor(self):
        """La segunda puerta: aunque algo se colara, la sesión no obedece a otra cuenta."""
        skill = " ".join(_leer(".claude", "skills", "arreglar-revision", "SKILL.md").split())
        assert "no lo abrió el dueño del repositorio" in skill


class TestProgramadoRotoLosVigilaTodos:
    """Todo workflow con `schedule:` tiene que estar en la lista de `programado-roto.yml`
    con su nombre exacto: `workflow_run` empareja por `name:`, no por fichero."""

    def _nombres_con_cron(self):
        nombres = set()
        for fichero in os.listdir(WORKFLOWS):
            if not fichero.endswith(".yml"):
                continue
            texto = _leer(".github", "workflows", fichero)
            if re.search(r"^\s{0,4}schedule:\s*$", texto, re.MULTILINE):
                nombres.add(re.search(r"^name:\s*(.+?)\s*$", texto, re.MULTILINE).group(1))
        return nombres

    def _vigilados(self):
        texto = _leer(".github", "workflows", "programado-roto.yml")
        bloque = re.search(r"^    workflows:\s*\n((?:      - .*\n)+)", texto, re.MULTILINE)
        assert bloque, "no encuentro la lista `workflows:`"
        return {linea.split("- ", 1)[1].split("#", 1)[0].strip()
                for linea in bloque.group(1).splitlines()}

    def test_estan_todos_los_que_corren_solos(self):
        faltan = self._nombres_con_cron() - self._vigilados()
        assert not faltan, f"programado-roto.yml no vigila: {sorted(faltan)}"

    def test_el_resumen_diario_esta(self):
        assert "Resumen diario por correo (red de seguridad)" in self._vigilados()


class TestCiAveriadoSoloMainDeVerdad:
    """`branches: [main]` en `workflow_run` mira `head_branch`, que en un PR desde un fork
    es la rama del fork: el `main` de cualquier fork lo pasaba."""

    def test_descarta_los_pr_y_los_forks(self):
        condicion = _if_del_job(_leer(".github", "workflows", "ci-averiado.yml"))
        assert "github.event.workflow_run.conclusion == 'failure'" in condicion
        assert "github.event.workflow_run.event != 'pull_request'" in condicion
        assert ("github.event.workflow_run.head_repository.full_name == github.repository"
                in condicion)
        # Todo en conjunción: un `||` dejaría pasar lo que se quiere cortar.
        assert "||" not in condicion


class TestCopiaLlevaIdeasDev:
    """La checklist de la zona dev se escribe a mano: si Supabase se pierde, no sale de
    ningún otro sitio."""

    def test_ideas_dev_esta_en_la_copia(self):
        entrada = next((t for t in copia.TABLAS if t[0] == "ideas_dev"), None)
        assert entrada is not None
        # Orden estable para paginar (columnas NOT NULL de su migración), y opcional: una
        # checklist vacía no invalida la copia entera.
        assert entrada[1] == "creada,id"
        assert entrada[2] is False


class TestRouterDelE2E:
    """El router simulado da la primera ruta cuyo fragmento esté dentro de la URL. Un
    fragmento que contiene a otro anterior no se alcanza nunca: `/rest/v1/ideas` se comía
    la de `/rest/v1/ideas_dev` y la checklist recibía las notas por voz."""

    def _fragmentos(self):
        arbol = ast.parse(_leer("tests", "e2e", "servidor_pruebas.py"))
        clase = next(n for n in ast.walk(arbol)
                     if isinstance(n, ast.ClassDef) and n.name == "_RouterSimulado")
        rutas = next(n for n in clase.body
                     if isinstance(n, ast.Assign) and n.targets[0].id == "RUTAS")
        return [t.elts[0].value for t in rutas.value.elts]

    def test_ninguna_ruta_queda_tapada_por_otra_anterior(self):
        fragmentos = self._fragmentos()
        tapadas = [(antes, despues)
                   for i, antes in enumerate(fragmentos)
                   for despues in fragmentos[i + 1:]
                   if antes in despues]
        assert not tapadas, f"rutas que nunca se alcanzan: {tapadas}"

    def test_ideas_dev_va_antes_que_ideas(self):
        fragmentos = self._fragmentos()
        assert fragmentos.index("/rest/v1/ideas_dev") < fragmentos.index("/rest/v1/ideas")


class TestAddonDeReserva:
    """El add-on del Green es la reserva desde el 2026-09-20. Instalado de nuevo con
    `boot: auto`, el siguiente corte de luz levantaba un segundo backend."""

    def test_nace_en_arranque_manual(self):
        config = _leer("addon", "life-assistant", "config.yaml")
        assert re.search(r"^boot:\s*manual\s*$", config, re.MULTILINE)

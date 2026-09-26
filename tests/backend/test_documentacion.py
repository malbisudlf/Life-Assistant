"""Que la documentación no se quede atrás del código sin que nadie lo note.

La moraleja de `CLAUDE.md` es que un dato escrito y nunca vuelto a comprobar acaba
sustituyendo a la realidad. Aquí se comprueban las afirmaciones que se pueden cruzar con
el código de forma mecánica, que son justo las que se quedaban viejas sin avisar:

- que toda ruta del backend aparezca en `docs/BACKEND_REFERENCIA.md` (diez estaban
  sin documentar cuando se escribió esto, entre ellas el turno de noche entero),
- que todo fichero de `docs/` esté en el índice de `CLAUDE.md` y que el índice no cite
  ficheros que ya no existen («un fichero que no está en el índice no lo lee nadie»),
- que toda variable que lee `main.py` esté en `backend/.env.example`, que `CLAUDE.md`
  presenta como la lista completa.

Solo se mira que las cosas estén NOMBRADAS, no que lo que se dice de ellas sea verdad:
eso no hay test que lo cubra, y por eso las comprobaciones son pocas y baratas.
"""
import os
import re

from fastapi.routing import APIRoute, APIWebSocketRoute

import main

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")


def _leer(*partes):
    with open(os.path.join(RAIZ, *partes), encoding="utf-8") as f:
        return f.read()


def _normalizar(ruta):
    """`/jobs/{job_id}/claim` y `/jobs/{id}/claim` son la misma ruta para quien lee."""
    return re.sub(r"\{[^}]*\}", "{}", ruta).rstrip("/")


def test_toda_ruta_del_backend_esta_en_la_referencia():
    referencia = _leer("docs", "BACKEND_REFERENCIA.md")
    citadas = {_normalizar(r) for r in re.findall(r"/[A-Za-z0-9_\-{}/.]+", referencia)}
    rutas = {_normalizar(r.path) for r in main.app.routes
             if isinstance(r, (APIRoute, APIWebSocketRoute)) and r.path != "/"}
    assert rutas, "No se ha encontrado ninguna ruta: el test ya no mira lo que cree mirar"
    faltan = sorted(rutas - citadas)
    assert not faltan, f"Rutas sin documentar en docs/BACKEND_REFERENCIA.md: {faltan}"


def test_todo_fichero_de_docs_esta_en_el_indice_y_al_reves():
    indice   = _leer("CLAUDE.md")
    en_disco = {f for f in os.listdir(os.path.join(RAIZ, "docs")) if f.endswith(".md")}
    citados  = set(re.findall(r"`docs/([A-Za-z0-9_]+\.md)`", indice))
    assert not sorted(en_disco - citados), \
        f"Ficheros de docs/ que no están en la tabla de CLAUDE.md: {sorted(en_disco - citados)}"
    assert not sorted(citados - en_disco), \
        f"CLAUDE.md cita ficheros de docs/ que no existen: {sorted(citados - en_disco)}"


# Las que pone la plataforma, no quien configura el backend: no tiene sentido pedírselas
# a nadie en un `.env`.
_VARIABLES_DE_LA_PLATAFORMA = {
    "FLY_APP_NAME",      # la define Fly en sus máquinas; su ausencia es lo que dice «no es Fly»
    "SUPERVISOR_TOKEN",  # la inyecta el Supervisor de Home Assistant en el add-on
}


def test_toda_variable_del_backend_esta_en_el_env_example():
    codigo  = _leer("backend", "main.py")
    ejemplo = _leer("backend", ".env.example")
    leidas  = set(re.findall(r'(?:os\.getenv|os\.environ\.get|_flag)\(\s*"([A-Z0-9_]+)"', codigo))
    # Comentadas también cuentan: muchas van así a propósito, con su valor por defecto.
    documentadas = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ejemplo, re.M))
    assert len(leidas) > 50, "El patrón ya no encuentra las variables: revisa cómo se leen"
    faltan = sorted(leidas - documentadas - _VARIABLES_DE_LA_PLATAFORMA)
    assert not faltan, f"Variables que lee main.py y no están en backend/.env.example: {faltan}"

#!/usr/bin/env python3
"""Evals de Jarvis: mide el acierto eligiendo herramienta, contra la API real.

Qué hace, en una frase: por cada caso de `casos.json` hace UNA llamada al modelo con el
esquema de herramientas REAL que expone el backend y mira qué herramienta pide.

Por qué existe (y por qué NO vive en `tests/backend`): allí el modelo está simulado a
propósito y la suite tiene que poder correr siempre, gratis y sin fallos intermitentes.
Esto llama a OpenAI de verdad y cuesta dinero, así que es un job aparte, a mano o
semanal. Ver `docs/EVALS.md`.

La medida se toma por SEPARADO con los dos modelos del reparto (`JARVIS_MODEL` y
`JARVIS_MODEL_ACCION`), porque la decisión que esto viene a permitir es justo esa: si el
reparto sigue mereciendo la pena y si el de acción puede bajar de gama.

    python evals/correr.py                       # los dos modelos del entorno
    python evals/correr.py --modelos gpt-4o-mini gpt-5-mini gpt-5-nano
    python evals/correr.py --filtro mcp --umbral 0.9

Sale con código distinto de cero si algún modelo baja del umbral.
"""
import argparse
import concurrent.futures
import json
import logging
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ    = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"


def _preparar_entorno() -> None:
    """El entorno mínimo para poder importar `backend/main.py`.

    `main` lanza `RuntimeError` al arrancar si faltan SECRET_KEY y DASHBOARD_PASSWORD
    (fail-fast, invariante 1 de CLAUDE.md), así que hay que ponerlos ANTES del import.
    Mismo truco que `tests/backend/conftest.py`, pero sin tocarlo ni importarlo: aquello
    además monkeypatchea `requests`, que es justo lo que aquí no queremos.

    Los valores son de mentira a propósito salvo OPENAI_API_KEY: la única llamada de red
    que hace este runner es al modelo. Todo lo que tocaría Supabase se sustituye después
    en `_aislar_de_la_red()`.
    """
    # El .env del backend es donde vive la OPENAI_API_KEY de verdad en local. En CI no
    # existe y la clave llega por el entorno (secret del workflow), que manda igual:
    # load_dotenv no pisa lo que ya está puesto.
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")
    except ImportError:                                  # pragma: no cover
        pass

    os.environ.setdefault("SECRET_KEY", "eval-secret-key")
    os.environ.setdefault("DASHBOARD_PASSWORD", "1234")
    os.environ.setdefault("SUPABASE_URL", "https://supabase.invalido")
    os.environ.setdefault("SUPABASE_KEY", "eval-key")
    # El registro persistente escribe en Supabase desde un hilo de fondo: aquí solo daría
    # ruido y reintentos contra un host que no existe.
    os.environ["LOG_PERSIST"] = "0"
    # El esquema se recorta solo cuando una integración está apagada (`requiere_mcp`,
    # `requiere_arreglo`, `requiere_despliegue`). Midiendo con el catálogo A MEDIAS la
    # cifra no dice nada: el fallo que esto busca crece precisamente con el número de
    # herramientas parecidas. Así que se enciende todo, con valores de mentira — ninguna
    # se llega a EJECUTAR, solo se anuncian.
    os.environ.setdefault("JARVIS_MCP_SERVERS", json.dumps({
        "github": {"url": "https://api.githubcopilot.com/mcp/", "token": "eval"},
    }))
    os.environ.setdefault("JARVIS_REPO", "usuario/life-assistant")
    os.environ.setdefault("ARREGLO_FIRE_URL", "https://ejemplo.invalido/arreglo")
    os.environ.setdefault("ARREGLO_FIRE_TOKEN", "eval")
    os.environ.setdefault("DEPLOY_GITHUB_TOKEN", "eval")

    sys.path.insert(0, str(BACKEND))


def _aislar_de_la_red(main) -> None:
    """Corta lo único del prompt que va a Supabase, con datos fijos.

    `_jarvis_sistema()` consulta el catálogo de la casa, los servidores MCP guardados y
    la memoria. Sin esto la tirada dependería del estado de producción y dos ejecuciones
    del mismo día no serían comparables — que es lo contrario de lo que se quiere medir.
    Los valores elegidos son los que hacen que el prompt salga COMPLETO (con su párrafo
    de la casa y su párrafo de MCP), no vacío: se mide el prompt que se usa de verdad.
    """
    main._mcp_guardados = lambda: {}                     # los del env bastan
    main._j_recuerdos   = lambda: []
    main._casa_entidades = lambda: [
        {"entity_id": "light.salon",     "nombre": "Luz del salón",  "estado": "off"},
        {"entity_id": "light.cocina",    "nombre": "Luz de cocina",  "estado": "off"},
        {"entity_id": "switch.enchufe",  "nombre": "Enchufe",        "estado": "on"},
        {"entity_id": "cover.persiana",  "nombre": "Persiana",       "estado": "open"},
    ]
    main._despliegue_pendiente_seguro = lambda: None


def _pedir(main, cliente, modelo, sistema, esquema, peticion, reintentos=4):
    """Una llamada al modelo, tal y como la hace la primera vuelta de `_jarvis_turno`.

    Mismo orden de mensajes que en producción —system, la hora APARTE al final, y el
    usuario— y los mismos parámetros por familia de modelo (`_parametros_modelo`), que es
    lo que evita el 400 al medir un modelo de razonamiento.
    """
    mensajes = [
        {"role": "system", "content": sistema},
        {"role": "system", "content": main._jarvis_ahora()},
        {"role": "user",   "content": peticion},
    ]
    ultimo = None
    for intento in range(reintentos + 1):
        try:
            t0 = time.monotonic()
            respuesta = cliente.chat.completions.create(
                model=modelo,
                messages=mensajes,
                tools=esquema,
                **main._parametros_modelo(modelo, main.JARVIS_MAX_TOKENS),
            )
            eleccion = respuesta.choices[0]
            uso      = getattr(respuesta, "usage", None)
            return {
                "pedidas":  [c.function.name for c in (eleccion.message.tool_calls or [])],
                "texto":    (eleccion.message.content or "").strip(),
                "segundos": round(time.monotonic() - t0, 2),
                "tokens_entrada": getattr(uso, "prompt_tokens", None),
                "tokens_salida":  getattr(uso, "completion_tokens", None),
            }
        except Exception as e:                           # noqa: BLE001
            ultimo = e
            # El esquema son ~4.700 tokens por llamada, así que una tirada entera se come
            # el límite de tokens por minuto de la cuenta y devuelve 429 en ráfaga. La
            # espera crece rápido a propósito: con dos reintentos cortos el límite seguía
            # sin haberse repuesto y media docena de casos volvían sin medir.
            if intento < reintentos:
                time.sleep(3 * (2 ** intento))
    return {"error": f"{type(ultimo).__name__}: {ultimo}", "pedidas": [], "texto": "",
            "segundos": 0, "tokens_entrada": None, "tokens_salida": None}


def _juzgar(caso, pedidas):
    """Acierto/fallo de un caso, y por qué.

    Tres reglas y ninguna más: un caso negativo acierta si no pidió nada; con
    `espera_todas` tienen que salir todas; y con `espera` basta una de las aceptables.
    """
    pedidas = list(pedidas)
    if caso.get("espera_todas"):
        faltan = [h for h in caso["espera_todas"] if h not in pedidas]
        return (not faltan), ("le faltan " + ", ".join(faltan) if faltan else "")
    esperadas = caso.get("espera", [])
    if not esperadas:
        return (not pedidas), ("no debía usar ninguna" if pedidas else "")
    if any(h in esperadas for h in pedidas):
        return True, ""
    return False, ("no pidió ninguna herramienta" if not pedidas else "")


def _correr_modelo(main, cliente, modelo, casos, sistema, esquema, hilos):
    """Todos los casos contra un modelo. En paralelo: son llamadas independientes y en
    serie una tirada de 60 casos se va a varios minutos."""
    resultados = [None] * len(casos)

    def _uno(i):
        caso = casos[i]
        r    = _pedir(main, cliente, modelo, sistema, esquema, caso["peticion"])
        fallo_api  = r.get("error") or ""
        ok, motivo = (False, "") if fallo_api else _juzgar(caso, r["pedidas"])
        resultados[i] = {
            "id":       caso["id"],
            "grupo":    caso.get("grupo", ""),
            "peticion": caso["peticion"],
            "espera":   caso.get("espera_todas") or caso.get("espera", []),
            "pedidas":  r["pedidas"],
            "acierto":  bool(ok),
            # Un 429 o un corte de red NO es un fallo eligiendo herramienta. Se separa en
            # vez de contarlo como fallo: mezclarlos ensucia la única cifra que interesa
            # y, peor, la empeora justo cuando la tirada va deprisa.
            "error":    fallo_api,
            "motivo":   fallo_api or motivo,
            "esperado_el_fallo": (not ok) and caso.get("confundible") in r["pedidas"],
            "segundos": r["segundos"],
            "tokens_entrada": r["tokens_entrada"],
            "tokens_salida":  r["tokens_salida"],
        }
        marca = "  ok  " if ok else ("  sin medir" if fallo_api else "  FALLO ")
        print(marca, caso["id"], flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=hilos) as pool:
        list(pool.map(_uno, range(len(casos))))
    return resultados


def _medidos(resultados):
    """Los casos que llegaron a contestar. Un 429 no puntúa: ver `_correr_modelo`."""
    return [r for r in resultados if not r["error"]]


def _ratio(resultados):
    medidos = _medidos(resultados)
    return (sum(1 for r in medidos if r["acierto"]) / len(medidos)) if medidos else 0.0


def _tabla(nombre_modelo, resultados):
    medidos  = _medidos(resultados)
    aciertos = sum(1 for r in medidos if r["acierto"])
    total    = len(medidos) or 1
    perdidos = len(resultados) - len(medidos)
    grupos   = {}
    for r in medidos:
        g = grupos.setdefault(r["grupo"] or "(sin grupo)", [0, 0])
        g[1] += 1
        g[0] += 1 if r["acierto"] else 0
    lineas = [f"\n=== {nombre_modelo} — {aciertos}/{len(medidos)} "
              f"({aciertos / total * 100:.1f}%) ==="
              + (f"   [{perdidos} sin medir: la API no contestó]" if perdidos else ""),
              f"{'grupo':<16}{'acierto':>10}"]
    for g, (ok, n) in sorted(grupos.items()):
        lineas.append(f"{g:<16}{ok:>4}/{n:<3}  {ok / n * 100:5.1f}%")
    tiempos = [r["segundos"] for r in medidos if r["segundos"]]
    entrada = [r["tokens_entrada"] for r in medidos if r["tokens_entrada"]]
    if tiempos:
        lineas.append(f"\nmediana de latencia: {statistics.median(tiempos):.2f}s"
                      + (f"   tokens de entrada: {statistics.median(entrada):.0f}"
                         if entrada else ""))
    if perdidos:
        lineas.append("\nsin medir (no cuentan ni a favor ni en contra):")
        lineas += [f"  · {r['id']}: {r['error'][:140]}"
                   for r in resultados if r["error"]]
    fallos = [r for r in medidos if not r["acierto"]]
    if fallos:
        lineas.append(f"\n{len(fallos)} fallo(s):")
        for r in fallos:
            pidio = ", ".join(r["pedidas"]) or "(nada)"
            espera = ", ".join(r["espera"]) or "(ninguna)"
            marca = "  [previsto]" if r["esperado_el_fallo"] else ""
            lineas.append(f"  · {r['id']}{marca}\n"
                          f"      «{r['peticion']}»\n"
                          f"      esperaba: {espera}\n"
                          f"      pidió:    {pidio}"
                          + (f"   ({r['motivo']})" if r["motivo"] else ""))
        confusiones = Counter(h for r in fallos for h in r["pedidas"])
        if confusiones:
            lineas.append("\n  herramientas elegidas por error, de más a menos: "
                          + ", ".join(f"{h}×{n}" for h, n in confusiones.most_common(6)))
    return "\n".join(lineas)


def main_cli(argv=None) -> int:
    p = argparse.ArgumentParser(description="Evals de enrutado de herramientas de Jarvis")
    p.add_argument("--casos", default=str(Path(__file__).parent / "casos.json"))
    p.add_argument("--modelos", nargs="*", default=None,
                   help="Por defecto, JARVIS_MODEL y JARVIS_MODEL_ACCION del entorno.")
    p.add_argument("--umbral", type=float, default=None,
                   help="Acierto mínimo (0-1). Por defecto el de casos.json.")
    p.add_argument("--filtro", default="",
                   help="Corre solo los casos cuyo id o grupo contenga este texto.")
    p.add_argument("--salida", default=str(Path(__file__).parent / "resultados.json"))
    # Pocos a propósito: el esquema son ~4.700 tokens por llamada y con más hilos la
    # tirada se come el límite de tokens por minuto de la cuenta a los pocos segundos,
    # y lo que devuelve entonces son 429, no medidas.
    p.add_argument("--hilos", type=int, default=3)
    args = p.parse_args(argv)

    # La consola de Windows no es UTF-8 por defecto y aquí todo va con acentos: sin esto
    # el informe sale ilegible justo en las líneas que explican un fallo.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):             # pragma: no cover
            pass
    # Una línea de httpx por llamada (y otra del SDK por cada reintento suyo) tapa la
    # tabla, que es lo único que se viene a leer.
    for ruidoso in ("httpx", "openai._base_client"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    _preparar_entorno()
    import main as backend_main                          # noqa: E402  (tras el entorno)
    _aislar_de_la_red(backend_main)

    if not backend_main.OPENAI_API_KEY:
        print("Falta OPENAI_API_KEY: estas evals llaman a la API real.", file=sys.stderr)
        return 2

    datos  = json.loads(Path(args.casos).read_text(encoding="utf-8"))
    casos  = [c for c in datos["casos"]
              if not args.filtro
              or args.filtro in c["id"] or args.filtro in c.get("grupo", "")]
    if not casos:
        print("El filtro no deja ningún caso.", file=sys.stderr)
        return 2
    umbral = args.umbral if args.umbral is not None else float(datos.get("umbral", 0.85))

    modelos = args.modelos or list(dict.fromkeys(
        [backend_main.JARVIS_MODEL, backend_main.JARVIS_MODEL_ACCION]))

    sistema = backend_main._jarvis_sistema()
    esquema = backend_main._jarvis_esquema()
    cliente = backend_main.get_openai_client()

    # Una herramienta que ningún caso cubre no está medida, y el catálogo crece más
    # deprisa que los casos. Se avisa, no se falla: el aviso es para quien la añadió.
    anunciadas = {h["function"]["name"] for h in esquema}
    cubiertas  = {n for c in datos["casos"]
                  for n in (c.get("espera", []) + c.get("espera_todas", []))}
    sin_caso   = sorted(anunciadas - cubiertas)
    if sin_caso:
        print("AVISO: herramientas del esquema sin ningún caso: " + ", ".join(sin_caso))

    print(f"{len(casos)} casos × {len(modelos)} modelo(s) "
          f"({len(esquema)} herramientas en el esquema): "
          f"{len(casos) * len(modelos)} llamadas a la API.\n")

    informe = {
        "fecha":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "casos":   len(casos),
        "herramientas_en_esquema": len(esquema),
        "herramientas_sin_caso":   sin_caso,
        "umbral":  umbral,
        "modelos": {},
    }
    salidas, suspensos = [], []
    for modelo in modelos:
        print(f"— {modelo} —", flush=True)
        resultados = _correr_modelo(backend_main, cliente, modelo, casos,
                                    sistema, esquema, args.hilos)
        medidos  = _medidos(resultados)
        aciertos = sum(1 for r in medidos if r["acierto"])
        ratio    = _ratio(resultados)
        informe["modelos"][modelo] = {
            "aciertos": aciertos, "total": len(medidos),
            "sin_medir": len(resultados) - len(medidos), "ratio": round(ratio, 4),
            "supera_umbral": ratio >= umbral, "detalle": resultados,
        }
        salidas.append(_tabla(modelo, resultados))
        if ratio < umbral:
            suspensos.append(f"{modelo} ({ratio * 100:.1f}%)")

    print("\n".join(salidas))

    Path(args.salida).write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultados en {args.salida}")

    # Comparativa: es la razón de existir de todo esto. Con un solo modelo no se imprime.
    if len(informe["modelos"]) > 1:
        print("\n=== Comparativa ===")
        for m, d in informe["modelos"].items():
            print(f"  {m:<24} {d['aciertos']:>3}/{d['total']:<3} {d['ratio'] * 100:5.1f}%")
        peor = min(informe["modelos"].values(), key=lambda d: d["ratio"])
        mejor = max(informe["modelos"].values(), key=lambda d: d["ratio"])
        print(f"  diferencia: {(mejor['ratio'] - peor['ratio']) * 100:.1f} puntos")

    if suspensos:
        print(f"\nPor debajo del umbral ({umbral * 100:.0f}%): " + ", ".join(suspensos),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

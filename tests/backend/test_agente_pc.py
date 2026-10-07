"""Tests de agent/agent.py que no necesitan un Windows de verdad.

El agente solo corre en un PC con Edge, pyautogui y Claude Desktop, así que casi todo él
se prueba a mano. Pero dos piezas son lógica pura, y las dos tapaban un fallo:

- `alud_url_permitida`, la última de las tres barreras del invariante 7 (la fila de
  `jobs` se puede escribir sin pasar por el backend). Se saltaba con una barra
  invertida, porque Python y Edge leían hosts distintos. Tiene una copia en
  backend/main.py, y aquí se exige que las dos digan lo mismo.
- El ciclo de un job (`procesar_job`): no miraba lo que respondía el backend al pasarlo
  a running ni al cerrarlo, así que un fallo puntual lo dejaba en claimed para siempre
  mientras el log decía «completado».

El fichero se carga con `pyautogui` y `dotenv` simulados, que es lo único suyo que no
existe fuera de ese PC.
"""
import ast
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest
import requests

import main

RUTA_AGENTE = Path(__file__).resolve().parents[2] / "agent" / "agent.py"
JOB_ID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture
def agente(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyautogui", types.ModuleType("pyautogui"))
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: False
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    # Al importarse abre agent.log en el directorio actual y configura el logging raíz:
    # ninguna de las dos cosas tiene que pasar dentro de la suite.
    monkeypatch.setattr(logging, "basicConfig", lambda *a, **k: None)
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    spec = importlib.util.spec_from_file_location("agente_pc_bajo_prueba", RUTA_AGENTE)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo.time, "sleep", lambda _s: None)
    return modulo


# ── alud_url_permitida ──────────────────────────────────────────────────────────

PERMITIDAS = [
    "https://alud.deusto.es/mod/assign/view.php?id=99",
    "https://aulas.alud.deusto.es/x",
    "https://ALUD.deusto.es/mod/assign/view.php?id=99",
    "https://alud.deusto.es:443/mod/assign/view.php?id=99",
]

RECHAZADAS = [
    # Para urlsplit el host es lo que va tras la @; para Edge la barra invertida es una
    # barra, el host acaba ahí y es atacante.example. Es el agujero que se cerró.
    "https://atacante.example\\@alud.deusto.es/mod/assign/view.php?id=1",
    # Para Python el host termina en .alud.deusto.es; para Edge es atacante.example.
    "https://atacante.example\\.alud.deusto.es/",
    # Una URL de Alud no lleva barras invertidas nunca, ni siquiera en la ruta.
    "https://alud.deusto.es/mod\\assign",
    # El navegador se salta tabuladores y saltos de línea; Python no.
    "https://atacante.example\t@alud.deusto.es/",
    "https://atacante.example\n.alud.deusto.es/",
    "https://alud.deusto.es /x",
    # Userinfo: aunque el host sea el bueno, una URL de Alud no lo lleva.
    "https://alud.deusto.es@atacante.com/x",
    "https://usuario:clave@alud.deusto.es/x",
    # Un host con escapes lo normaliza el navegador, no esta función.
    "https://alud%2edeusto.es/x",
    "https://alud.deusto.es.atacante.com/x",
    "https://alud.deusto.es:99999/x",
    "http://alud.deusto.es/x",
    "javascript:alert(1)",
    "",
    None,
]


def _las_dos():
    return [pytest.param("backend", id="backend"), pytest.param("agente", id="agente")]


@pytest.fixture
def permitida(request, agente):
    return main.alud_url_permitida if request.param == "backend" else agente.alud_url_permitida


@pytest.mark.parametrize("permitida", _las_dos(), indirect=True)
class TestAludUrlPermitida:
    @pytest.mark.parametrize("url", PERMITIDAS)
    def test_las_de_alud_pasan(self, permitida, url):
        assert permitida(url)

    @pytest.mark.parametrize("url", RECHAZADAS)
    def test_lo_que_se_lee_de_dos_maneras_no_pasa(self, permitida, url):
        assert not permitida(url)


def _funcion(ruta, nombre):
    arbol = ast.parse(Path(ruta).read_text(encoding="utf-8-sig"))  # main.py lleva BOM
    return next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre)


def _cuerpo_sin_docstring(nodo):
    cuerpo = nodo.body
    primero = cuerpo[0] if cuerpo else None
    if isinstance(primero, ast.Expr) and isinstance(getattr(primero, "value", None), ast.Constant) \
            and isinstance(primero.value.value, str):
        cuerpo = cuerpo[1:]
    return [ast.dump(n) for n in cuerpo]


class TestLasDosCopiasDicenLoMismo:
    """El backend valida al extraer y al dar de alta el job; el agente, antes de abrir
    Edge. Si una copia se arregla y la otra no, el agujero sigue abierto en la otra."""

    def test_mismo_cuerpo(self):
        assert (_cuerpo_sin_docstring(_funcion(main.__file__, "alud_url_permitida"))
                == _cuerpo_sin_docstring(_funcion(RUTA_AGENTE, "alud_url_permitida")))

    def test_mismo_patron_de_host(self, agente):
        assert agente._ALUD_HOST_RE.pattern == main._ALUD_HOST_RE.pattern


# ── El ciclo de un job ──────────────────────────────────────────────────────────

class _Respuesta:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def ciclo(agente, monkeypatch):
    """procesar_job con el backend simulado. `respuestas[tramo]` es la lista de lo que
    devuelve cada llamada (un código o una excepción); el último valor se repite."""
    llamadas, etapas, hechos, respuestas = [], [], [], {}

    def post(url, headers=None, json=None, timeout=None):
        tramo = url.rsplit("/", 1)[-1]
        llamadas.append((tramo, json))
        cola = respuestas.get(tramo, [200])
        r = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(r, Exception):
            raise r
        return _Respuesta(r)

    monkeypatch.setattr(agente.requests, "post", post)
    monkeypatch.setattr(agente, "claim_job", lambda _id: True)
    monkeypatch.setattr(agente, "report_stage",
                        lambda _id, etapa, mensaje="": etapas.append((etapa, mensaje)))
    monkeypatch.setattr(agente, "heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(agente, "resolver_accion", lambda _payload: "prueba")
    monkeypatch.setitem(agente.ACCIONES, "prueba", lambda job_id, _payload: hechos.append(job_id))

    def tramos():
        return [t for t, _ in llamadas]

    def cierres():
        return [cuerpo["status"] for t, cuerpo in llamadas if t == "finish"]

    return types.SimpleNamespace(agente=agente, etapas=etapas, hechos=hechos,
                                 respuestas=respuestas, tramos=tramos, cierres=cierres,
                                 procesar=lambda: agente.procesar_job({"id": JOB_ID, "payload": {}}))


class TestCicloDelJob:
    def test_camino_feliz(self, ciclo):
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        assert ciclo.tramos() == ["start", "finish"]
        assert ciclo.cierres() == ["done"]
        assert ciclo.etapas[-1] == ("job_done", "done")

    def test_si_no_pasa_a_running_no_se_ejecuta_la_accion(self, ciclo):
        """Antes se ignoraba el 5xx del start, se abría Edge y Cowork igualmente, el
        finish daba 409 (el job seguía en claimed) y el log decía «completado»."""
        ciclo.respuestas["start"] = [502]
        ciclo.procesar()
        assert ciclo.hechos == []
        assert ciclo.tramos().count("start") == 3
        assert ciclo.cierres() == ["failed"]
        assert ciclo.etapas[-1][1].startswith("failed")

    def test_sin_red_en_el_start_no_tumba_al_agente(self, ciclo):
        """Un ConnectionError salía de procesar_job sin capturar y mataba el proceso a
        mitad del drenaje de la cola."""
        ciclo.respuestas["start"] = [requests.ConnectionError("sin red")]
        ciclo.procesar()
        assert ciclo.hechos == []

    def test_un_fallo_puntual_se_reintenta(self, ciclo):
        ciclo.respuestas["start"] = [502, 200]
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        assert ciclo.tramos().count("start") == 2

    def test_un_409_no_se_reintenta(self, ciclo):
        """Repetirlo no lo arregla: el job no está en el estado que toca."""
        ciclo.respuestas["start"] = [409]
        ciclo.procesar()
        assert ciclo.tramos().count("start") == 1
        assert ciclo.hechos == []

    def test_un_cierre_rechazado_no_se_cuenta_como_completado(self, ciclo):
        ciclo.respuestas["finish"] = [409]
        ciclo.procesar()
        assert ciclo.hechos == [JOB_ID]
        etapa, mensaje = ciclo.etapas[-1]
        assert etapa == "job_done" and mensaje != "done"
        assert "no registró" in mensaje

    def test_la_accion_que_falla_se_cierra_como_fallida(self, ciclo, monkeypatch):
        def revienta(_job_id, _payload):
            raise RuntimeError("Edge no abrió")
        monkeypatch.setitem(ciclo.agente.ACCIONES, "prueba", revienta)
        ciclo.procesar()
        assert ciclo.cierres() == ["failed"]
        assert ciclo.etapas[-1] == ("job_done", "failed: Edge no abrió")


# ── abrir_streaming con Apollo ya abierto ───────────────────────────────────────

class _WindowsSimulado:
    """Lo justo de Windows para `sc.exe`, `tasklist.exe` y `taskkill.exe`.

    Se simula `_nativo` y no las funciones de más arriba (`apollo_vivo`,
    `estado_servicio`…) para que lo que se pruebe sea el camino de verdad: cómo se leen
    los códigos de `sc`, cuándo se espera y en qué orden se para y se arranca.
    """

    def __init__(self, servicio_corriendo, proceso_vivo):
        self.servicio_corriendo = servicio_corriendo
        self.proceso_vivo       = proceso_vivo
        self.parar_rc           = 0      # lo que devuelve `sc stop`
        self.arranca_proceso    = True   # si `sc start` levanta de verdad sunshine.exe
        self.llamadas           = []

    def nativo(self, args, timeout=15):
        exe, *resto = args
        self.llamadas.append(" ".join([exe, *resto[:2]]))
        if exe == "sc.exe":
            orden, nombre = resto
            if nombre != "ApolloService":
                return 1060, "", ""
            if orden == "query":
                return 0, f"SERVICE_NAME: {nombre}\n STATE : {4 if self.servicio_corriendo else 1}", ""
            if orden == "stop":
                if self.parar_rc:
                    return self.parar_rc, "", "Acceso denegado."
                self.servicio_corriendo = self.proceso_vivo = False
                return 0, "", ""
            if orden == "start":
                self.servicio_corriendo = True
                self.proceso_vivo = self.arranca_proceso
                return 0, "", ""
        if exe == "tasklist.exe":
            vivo = self.proceso_vivo and "sunshine.exe" in resto[1]
            return 0, '"sunshine.exe","4242","Console","1","80.000 K"' if vivo else "INFO: nada", ""
        if exe == "taskkill.exe":
            self.proceso_vivo = False
            return 0, "", ""
        raise AssertionError(f"llamada no simulada: {args}")

    def ordenes(self):
        """Solo lo que cambia algo: las pantallas, parar, arrancar y matar."""
        return [c for c in self.llamadas
                if c.startswith(("pantallas", "sc.exe stop", "sc.exe start", "taskkill"))]


@pytest.fixture
def streaming(ciclo, monkeypatch):
    agente = ciclo.agente

    def construir(servicio_corriendo=True, proceso_vivo=True, pantallas_ok=True):
        win = _WindowsSimulado(servicio_corriendo, proceso_vivo)
        monkeypatch.setattr(agente, "_nativo", win.nativo)

        def powershell(comando, timeout=40):
            raise AssertionError(f"PowerShell en el camino crítico: {comando}")
        monkeypatch.setattr(agente, "_powershell", powershell)
        monkeypatch.setattr(agente, "APOLLO_SERVICIO", "ApolloService")
        monkeypatch.setattr(agente, "APOLLO_TIMEOUT", 3)
        monkeypatch.setattr(agente, "PANTALLAS_STREAMING", "clone")
        monkeypatch.setattr(agente, "conectar_vpn", lambda _id: "<ip-tailnet>")

        def pantallas(modo):
            win.llamadas.append(f"pantallas {modo}")
            return pantallas_ok
        monkeypatch.setattr(agente, "cambiar_modo_pantallas", pantallas)
        monkeypatch.setitem(agente.ACCIONES, "prueba", agente.accion_abrir_streaming)
        return win

    return construir


class TestStreamingConApolloYaAbierto:
    def test_si_ya_estaba_abierto_se_reinicia_despues_de_cambiar_las_pantallas(self, ciclo, streaming):
        """Lo del 2026-09-26: Apollo abierto, pantallas a clone por debajo y
        `streaming_ready` con el stream mirando una salida que ya no existía."""
        win = streaming(servicio_corriendo=True, proceso_vivo=True)
        ciclo.procesar()
        assert win.ordenes() == ["pantallas clone", "sc.exe stop ApolloService",
                                 "sc.exe start ApolloService"]
        assert win.proceso_vivo
        assert ciclo.cierres() == ["done"]
        etapas = dict(ciclo.etapas)
        assert "reiniciándolo" in etapas["streaming_starting"]
        assert etapas["streaming_ready"].startswith("Apollo reiniciado y listo")

    def test_si_no_estaba_abierto_solo_se_arranca(self, ciclo, streaming):
        win = streaming(servicio_corriendo=False, proceso_vivo=False)
        ciclo.procesar()
        assert win.ordenes() == ["pantallas clone", "sc.exe start ApolloService"]
        assert ciclo.cierres() == ["done"]
        assert dict(ciclo.etapas)["streaming_ready"].startswith("Apollo listo")

    def test_si_las_pantallas_no_cambiaron_no_se_reinicia(self, ciclo, streaming):
        """Sin cambio de topología, el Apollo que ya estaba sigue capturando lo bueno."""
        win = streaming(servicio_corriendo=True, proceso_vivo=True, pantallas_ok=False)
        ciclo.procesar()
        assert win.ordenes() == ["pantallas clone"]
        assert ciclo.cierres() == ["done"]

    def test_un_apollo_abierto_fuera_del_servicio_se_cierra_y_se_arranca_por_el(self, ciclo, streaming):
        win = streaming(servicio_corriendo=False, proceso_vivo=True)
        ciclo.procesar()
        assert win.ordenes()[:2] == ["pantallas clone", "taskkill.exe /F /IM"]
        assert win.ordenes()[-1] == "sc.exe start ApolloService"
        assert ciclo.cierres() == ["done"]

    def test_si_no_se_puede_parar_el_job_falla_con_motivo(self, ciclo, streaming):
        win = streaming(servicio_corriendo=True, proceso_vivo=True)
        win.parar_rc = 5   # ACCESS_DENIED: sin privilegios no hay reinicio posible
        ciclo.procesar()
        assert ciclo.cierres() == ["failed"]
        assert "streaming_ready" not in dict(ciclo.etapas)
        etapa, mensaje = ciclo.etapas[-1]
        assert etapa == "job_done"
        assert "no se pudo parar su servicio 'ApolloService'" in mensaje

    def test_si_se_para_y_no_vuelve_el_job_falla_con_motivo(self, ciclo, streaming, monkeypatch):
        win = streaming(servicio_corriendo=True, proceso_vivo=True)
        win.arranca_proceso = False
        # arrancar_apollo espera con el reloj de verdad: sin tiempo, falla a la primera.
        monkeypatch.setattr(ciclo.agente, "APOLLO_TIMEOUT", 0)
        ciclo.procesar()
        assert ciclo.cierres() == ["failed"]
        assert "streaming_ready" not in dict(ciclo.etapas)
        assert "no volvió" in ciclo.etapas[-1][1]


class TestScQueryNoConcluyente:
    def test_el_aviso_lleva_la_salida_cruda_recortada(self, agente, monkeypatch, caplog):
        cruda = "respuesta rara de sc\n   con varias líneas " + "x" * 1000
        monkeypatch.setattr(agente, "_nativo", lambda args, timeout=15: (0, cruda, "aviso"))
        monkeypatch.setattr(agente, "_powershell", lambda *_a, **_k: (0, "Running", ""))
        with caplog.at_level(logging.WARNING):
            assert agente.estado_servicio("Tailscale") == "Running"
        aviso = next(r.getMessage() for r in caplog.records if "no concluyente" in r.getMessage())
        assert "respuesta rara de sc con varias líneas" in aviso
        assert "\n" not in aviso
        assert "x" * 1000 not in aviso and "…" in aviso

    def test_sin_salida_lo_dice(self, agente, monkeypatch, caplog):
        monkeypatch.setattr(agente, "_nativo", lambda args, timeout=15: (-1, "", ""))
        monkeypatch.setattr(agente, "_powershell", lambda *_a, **_k: (0, "", ""))
        with caplog.at_level(logging.WARNING):
            agente.estado_servicio("Tailscale")
        assert any("rc=-1, salida: «(vacía)»" in r.getMessage() for r in caplog.records)


# ── resolver_alud con el enunciado de Moodle ────────────────────────────────────

class _Descarga:
    def __init__(self, status_code, cuerpo=b""):
        self.status_code = status_code
        self._cuerpo = cuerpo

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._cuerpo), chunk_size):
            yield self._cuerpo[i:i + chunk_size]


@pytest.fixture
def entrega(agente, monkeypatch, tmp_path):
    """El agente con la carpeta de entregas en tmp_path, Cowork y Edge simulados, y una
    entrega firmada con el mismo AGENT_TOKEN en el backend y en el agente."""
    monkeypatch.setattr(main, "AGENT_TOKEN", "token-compartido")
    monkeypatch.setattr(agente, "AGENT_TOKEN", "token-compartido")
    monkeypatch.setattr(agente, "ENTREGAS_DIR", str(tmp_path))
    pegado, edge, etapas, pedidos = [], [], [], []
    monkeypatch.setattr(agente, "_pegar_en_cowork", pegado.append)
    monkeypatch.setattr(agente, "resolver_en_edge", lambda job_id, payload: edge.append(payload))
    monkeypatch.setattr(agente, "report_stage", lambda _id, etapa, mensaje="": etapas.append((etapa, mensaje)))
    respuestas = {0: _Descarga(200, b"%PDF-1.7"), 1: _Descarga(502)}

    def get(url, **kw):
        n = int(url.rsplit("/", 1)[-1])
        pedidos.append(url)
        return respuestas[n]

    monkeypatch.setattr(agente.requests, "get", get)
    datos = {
        "moodle_cmid": 4242, "moodle_tarea": 777, "nombre": "Práctica 2: sockets/TCP",
        "curso": "Redes de Computadores", "vence": "2026-10-20T21:59:00Z",
        "enunciado": "Implementa un servidor.",
        "adjuntos": [{"nombre": "enunciado.pdf", "tipo": "application/pdf", "bytes": 8, "url": "https://x/1"},
                     {"nombre": "datos.csv", "tipo": "text/csv", "bytes": 3, "url": "https://x/2"}],
    }
    return types.SimpleNamespace(agente=agente, datos=datos, firma=main.firma_entrega(datos),
                                 carpeta=tmp_path, pegado=pegado, edge=edge, etapas=etapas,
                                 pedidos=pedidos, respuestas=respuestas)


class TestEntregaConMoodle:
    def test_la_firma_del_backend_vale_en_el_agente(self, entrega):
        """Aunque jsonb devuelva las claves en otro orden: se firma el JSON ordenado."""
        al_reves = dict(reversed(list(entrega.datos.items())))
        assert entrega.agente.entrega_firmada(al_reves, entrega.firma)
        assert not entrega.agente.entrega_firmada({**entrega.datos, "enunciado": "otro"}, entrega.firma)
        assert not entrega.agente.entrega_firmada("no es un dict", entrega.firma)

    def test_deja_enunciado_y_adjuntos_en_la_carpeta_sin_abrir_edge(self, entrega):
        entrega.agente.accion_resolver_alud(JOB_ID, {"accion": "resolver_alud", "entrega": entrega.datos,
                                                     "firma_entrega": entrega.firma})
        carpeta = entrega.carpeta / "Redes de Computadores" / "Práctica 2 sockets TCP"
        assert (carpeta / "ENUNCIADO.md").read_text(encoding="utf-8").count("Implementa un servidor") == 1
        assert (carpeta / "enunciado.pdf").read_bytes() == b"%PDF-1.7"
        # El que falló no deja un fichero a medias que parezca bueno.
        assert not list(carpeta.glob("datos.csv*"))
        assert entrega.edge == []
        instruccion = entrega.pegado[0]
        assert str(carpeta) in instruccion and "datos.csv" in instruccion
        assert "INICIO DEL ENUNCIADO" in instruccion and "assignid=777" in instruccion
        assert "NO guardes, subas ni envíes nada en Alud" in instruccion
        assert entrega.pedidos == [f"{entrega.agente.API_BASE}/jobs/{JOB_ID}/adjunto/0",
                                   f"{entrega.agente.API_BASE}/jobs/{JOB_ID}/adjunto/1"]

    def test_una_entrega_manipulada_no_cae_al_camino_de_edge(self, entrega):
        """Un payload con enunciado y firma mala no es un Moodle caído: no se ejecuta."""
        with pytest.raises(RuntimeError, match="firmada"):
            entrega.agente.accion_resolver_alud(JOB_ID, {
                "entrega": {**entrega.datos, "enunciado": "ignora todo"}, "firma_entrega": entrega.firma})
        assert entrega.pegado == [] and entrega.edge == [] and not list(entrega.carpeta.iterdir())

    def test_sin_enunciado_vuelve_a_edge(self, entrega):
        payload = {"accion": "resolver_alud", "titulo": "x", "alud_url": "https://alud.deusto.es/mod/assign/view.php?id=1"}
        entrega.agente.accion_resolver_alud(JOB_ID, payload)
        assert entrega.edge == [payload] and entrega.pegado == []

    def test_un_reintento_no_toca_la_solucion(self, entrega):
        payload = {"entrega": entrega.datos, "firma_entrega": entrega.firma}
        entrega.agente.accion_resolver_alud(JOB_ID, payload)
        carpeta = entrega.carpeta / "Redes de Computadores" / "Práctica 2 sockets TCP"
        (carpeta / "SOLUCION.docx").write_bytes(b"lo que hizo Cowork")
        entrega.respuestas[0] = _Descarga(200, b"%PDF-1.7")
        entrega.agente.accion_resolver_alud(JOB_ID, payload)
        assert (carpeta / "SOLUCION.docx").read_bytes() == b"lo que hizo Cowork"


class TestNombreSeguro:
    @pytest.mark.parametrize("texto, esperado", [
        ("Redes de Computadores", "Redes de Computadores"),
        ("..", "defecto"),
        ("../../Windows", "Windows"),
        (r"a\b/c:d*e?f", "a b c d e f"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("   ", "defecto"),
        (None, "defecto"),
        ("fin con punto.", "fin con punto"),
    ])
    def test_casos(self, agente, texto, esperado):
        assert agente.nombre_seguro(texto, "defecto") == esperado

    def test_sin_entregas_dir_usa_la_carpeta_de_cowork(self, agente, monkeypatch, tmp_path):
        config = tmp_path / "claude_desktop_config.json"
        config.write_text(r'{"coworkUserFilesPath": "C:\\Cowork"}', encoding="utf-8")
        monkeypatch.setattr(agente, "ENTREGAS_DIR", "")
        monkeypatch.setattr(agente, "CLAUDE_DESKTOP_CONFIG", str(config))
        assert agente.carpeta_entregas() == agente.os.path.join(r"C:\Cowork", "Entregas")
        monkeypatch.setattr(agente, "CLAUDE_DESKTOP_CONFIG", str(tmp_path / "no-existe.json"))
        assert agente.carpeta_entregas().endswith(agente.os.path.join("Documents", "Entregas"))

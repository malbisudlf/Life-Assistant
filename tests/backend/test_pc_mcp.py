"""Tests de agent/pc_mcp.py (las manos y los ojos de Jarvis en el PC) sin Windows.

Lo que toca Windows (capturas, ventanas, teclado) se prueba a mano en el PC. Aquí, la
lógica pura que decide QUÉ se hace: qué herramientas existen en cada nivel, qué acceso
directo abre «spotify», qué es una web, dónde cae un clic y qué teclas son «ctrl+s».
"""
import importlib.util
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "agent" / "pc_mcp.py"


@pytest.fixture
def pc(monkeypatch, tmp_path):
    monkeypatch.delenv("PC_MCP_NIVEL", raising=False)
    # La configuración del PC donde corran los tests no cuenta.
    monkeypatch.setenv("PC_MCP_CONFIG", str(tmp_path / "no-existe.env"))
    spec = importlib.util.spec_from_file_location("pc_mcp", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_cada_nivel_incluye_al_anterior(pc):
    assert pc.NIVEL == "usar"                       # por defecto: ni teclado ni ratón
    assert pc.permitido("mirar") and pc.permitido("usar") and not pc.permitido("total")
    assert pc.permitido("mirar", "mirar") and not pc.permitido("usar", "mirar")
    assert pc.permitido("total", "total")


def test_la_configuracion_local_rellena_lo_que_falta(pc, monkeypatch, tmp_path):
    config = tmp_path / "pc_mcp.env"
    config.write_text("# comentario\nPC_MCP_NIVEL=mirar\nPC_MCP_PUERTO=9999\n", encoding="utf-8")
    entorno = {"PC_MCP_PUERTO": "8765"}
    monkeypatch.setattr(pc.os, "environ", entorno)
    pc._cargar_config(config)
    assert entorno == {"PC_MCP_PUERTO": "8765",            # el entorno manda
                       "PC_MCP_NIVEL": "mirar"}


def test_un_nivel_inventado_no_abre_el_teclado(pc, monkeypatch):
    monkeypatch.setenv("PC_MCP_NIVEL", "dios")
    spec = importlib.util.spec_from_file_location("pc_mcp_2", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.NIVEL == "usar"


def test_elige_el_acceso_directo_que_toca(pc):
    accesos = [Path("Programs/Spotify Widget.lnk"), Path("Programs/Spotify.lnk"),
               Path("Programs/Uninstall Spotify.lnk"), Path("Programs/Steam/Steam.lnk"),
               Path("Programs/Visual Studio Code/Visual Studio Code.lnk"),
               Path("Programs/Herramientas/Desinstalar Steam.lnk")]
    assert pc.elegir_acceso("spotify", accesos).name == "Spotify.lnk"
    assert pc.elegir_acceso("Steam", accesos).name == "Steam.lnk"
    assert pc.elegir_acceso("visual studio", accesos).name == "Visual Studio Code.lnk"
    assert pc.elegir_acceso("code", accesos).name == "Visual Studio Code.lnk"
    assert pc.elegir_acceso("photoshop", accesos) is None
    assert pc.elegir_acceso("", accesos) is None


def test_las_apps_de_la_tienda_tambien_se_encuentran(pc):
    """Spotify de la Microsoft Store no deja acceso directo en disco: sin esto, «abre
    Spotify» no encontraba nada y el modelo abría la web."""
    apps = [("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
            ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App")]
    assert pc.elegir_app_tienda("spotify", apps)[1].endswith("!Spotify")
    assert pc.elegir_app_tienda("whatsapp", apps)[0] == "WhatsApp"
    assert pc.elegir_app_tienda("steam", apps) is None


def test_los_desinstaladores_no_se_abren_nunca(pc):
    assert pc.elegir_acceso("spotify", [Path("Uninstall Spotify.lnk")]) is None


def test_solo_las_webs_de_verdad_son_webs(pc):
    assert pc.es_web("https://www.youtube.com/watch?v=1")
    assert pc.es_web("http://10.0.0.5:8123")
    assert not pc.es_web("file:///C:/Windows/System32/cmd.exe")
    assert not pc.es_web("javascript:alert(1)")
    assert not pc.es_web("spotify")


def test_el_clic_va_en_fraccion_del_monitor(pc):
    mon = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
    assert pc.a_pixeles(0, 0, mon) == (-1920, 0)
    assert pc.a_pixeles(0.5, 0.5, mon) == (-960, 540)
    assert pc.a_pixeles(1, 1, mon) == (-1, 1079)     # el borde, dentro
    with pytest.raises(ValueError):
        pc.a_pixeles(960, 540, mon)                  # píxeles por error


def test_las_teclas_por_nombre(pc):
    assert pc.parsear_teclas("ctrl+s") == [0x11, ord("S")]
    assert pc.parsear_teclas("Alt + Tab") == [0x12, 0x09]
    assert pc.parsear_teclas("win+d") == [0x5B, ord("D")]
    assert pc.parsear_teclas("f5") == [0x74]
    with pytest.raises(ValueError):
        pc.parsear_teclas("ctrl+hiperespacio")
    with pytest.raises(ValueError):
        pc.parsear_teclas("")


def test_lo_que_el_nivel_no_permite_no_existe(pc):
    """Con `usar`, el modelo ni ve las herramientas de teclado y ratón."""
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio
    nombres = {t.name for t in asyncio.run(pc.crear_servidor().list_tools())}
    assert {"pantalla", "ventanas", "estado", "abrir", "multimedia", "bloquear", "decir"} <= nombres
    assert not nombres & {"escribir", "teclas", "clic", "cerrar_ventana"}


def test_se_apaga_solo_tras_los_minutos_sin_uso(pc, monkeypatch):
    """Desde caja se arranca a demanda; el puerto solo está abierto mientras se usa."""
    salidas, esperas = [], []

    class Hilo:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()

    import threading
    monkeypatch.setattr(threading, "Thread", Hilo)
    monkeypatch.setattr(pc.time, "sleep", lambda s: esperas.append(s))
    pc.marcar_uso()
    reloj = [pc.time.monotonic()]
    monkeypatch.setattr(pc.time, "monotonic", lambda: reloj[0])
    # Un minuto de uso no lo apaga; dieciséis sin nada, sí.
    reloj[0] += 60
    assert pc.sin_uso_hace() == pytest.approx(60)
    reloj[0] += 15 * 60
    pc.vigilar_inactividad(15, salir=salidas.append)
    assert salidas == [0] and esperas


def test_con_cero_no_se_apaga_nunca(pc, monkeypatch):
    import threading
    arrancados = []
    monkeypatch.setattr(threading, "Thread", lambda **kw: arrancados.append(kw))
    pc.vigilar_inactividad(0)
    assert not arrancados


def test_cada_peticion_cuenta_como_uso(pc, monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(pc.time, "monotonic", lambda: reloj[0])
    pc.marcar_uso()
    reloj[0] += 300
    assert pc.sin_uso_hace() == pytest.approx(300)
    pc.marcar_uso()
    assert pc.sin_uso_hace() == pytest.approx(0)


def test_espera_a_que_el_puerto_se_pueda_usar(pc):
    """Dos arranques seguidos murieron con «could not bind» el 2026-10-28: se reintenta."""
    intentos = []

    def _probar():
        intentos.append(1)
        if len(intentos) < 3:
            raise OSError(10049, "La dirección solicitada no es válida en este contexto")
    assert pc.esperar_puerto("100.1.2.3", 8765, espera_s=60, probar=_probar, dormir=lambda s: None) == ""
    assert len(intentos) == 3


def test_si_el_puerto_no_se_libera_dice_por_que(pc):
    def _ocupado():
        raise OSError(10048, "Solo se permite un uso de cada dirección de socket")
    error = pc.esperar_puerto("100.1.2.3", 8765, espera_s=0, probar=_ocupado, dormir=lambda s: None)
    assert "10048" in error and "socket" in error

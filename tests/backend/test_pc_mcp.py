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

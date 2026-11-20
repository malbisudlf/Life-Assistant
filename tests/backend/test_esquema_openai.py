"""El tope de OpenAI: 128 herramientas por petición (2026-11-20).

Con 139 en el registro, TODOS los turnos por OpenAI (la voz, el Jarvis de escritorio,
Telegram) devolvían «Se ha roto el turno»: un 400 `array_above_max_length`. Lo que se
protege: que con TODO encendido lo que se manda quepa, que se quite primero lo prescindible y
nada más de lo necesario, y que la lista de prescindibles no nombre herramientas que no hay.
"""
import main


def _todo():
    """El esquema con todas las herramientas del registro, como si todo estuviera configurado."""
    return [{"type": "function", "function": {"name": n}} for n, h in main._JARVIS_HERRAMIENTAS.items()
            if not h.get("interna")]


def test_esquema_openai_cabe():
    esquema = main._esquema_openai(_todo())
    assert len(esquema) <= main.JARVIS_OPENAI_MAX_HERRAMIENTAS
    nombres = {h["function"]["name"] for h in esquema}
    # Lo de hablar sigue: lo que se quita es de administrar y programar.
    for imprescindible in ("agenda", "casa_ordenar", "whatsapp_enviar", "recordarme", "poner_alarma",
                           "dia_reconstruir", "simular_finanzas", "casa_holograma", "investigar"):
        assert imprescindible in nombres


def test_solo_quita_lo_que_sobra_y_por_orden():
    esquema = _todo()
    recortado = main._esquema_openai(esquema, limite=len(esquema) - 2)
    quitadas = {h["function"]["name"] for h in esquema} - {h["function"]["name"] for h in recortado}
    presentes = [n for n in main._PRESCINDIBLES_OPENAI if n in {h["function"]["name"] for h in esquema}]
    assert quitadas == set(presentes[:2])
    assert main._esquema_openai(esquema[:10]) == esquema[:10]


def test_los_prescindibles_existen():
    assert set(main._PRESCINDIBLES_OPENAI) <= set(main._JARVIS_HERRAMIENTAS)


def test_el_turno_por_openai_manda_el_recortado(monkeypatch):
    monkeypatch.setattr(main, "_jarvis_esquema", _todo)
    visto = {}

    class Rota(Exception):
        pass

    class Cliente:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    visto["n"] = len(kw.get("tools") or [])
                    raise Rota()
    monkeypatch.setattr(main, "get_openai_client", lambda: Cliente)
    try:
        main._jarvis_chat(main.JarvisIn(mensaje="hola"))
    except Exception:   # noqa: BLE001 — solo interesa lo que llegó a OpenAI
        pass
    assert 0 < visto["n"] <= main.JARVIS_OPENAI_MAX_HERRAMIENTAS

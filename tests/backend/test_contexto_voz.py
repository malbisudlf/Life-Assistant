"""Tests de lo que Jarvis ya sabe al descolgar (`_contexto_de_voz`, `GET /telefono/contexto`).

Lo que se prueba es lo que lo hace fiable, no el formato exacto de cada frase: que lo que
no se pudo mirar se diga en vez de sonar a «no tienes nada», que un fallo en una parte no
se lleve a las demás, que diga de qué hora es, que no se pregunte en cada turno y que solo
lo lleve la voz.
"""
from datetime import datetime, timedelta

import main
from test_jarvis import _con_modelo, _mensaje  # noqa: E402

TOKEN = "mcp-telefono-token"


def _iso(dt: datetime) -> str:
    return dt.astimezone(main.LOCAL_TZ).isoformat()


def _fuentes(monkeypatch, eventos=None, clases=None, clima=None, tareas=None,
             recordatorios=None, lugar=""):
    """Sustituye cada fuente por una fija y cuenta las veces que se pregunta a Outlook."""
    llamadas = {"outlook": 0}

    def _eventos(credentials=None):
        llamadas["outlook"] += 1
        return eventos if eventos is not None else {"events": []}

    monkeypatch.setattr(main, "get_events", _eventos)
    monkeypatch.setattr(main, "get_class_events",
                        lambda credentials=None: clases if clases is not None else {"events": []})
    monkeypatch.setattr(main, "_brief_clima", lambda: clima if clima is not None else
                        {"ahora": 14.4, "max": 18.2, "min": 9.0, "codigo_wmo": 61})
    monkeypatch.setattr(main, "_j_tareas", lambda: tareas if tareas is not None else
                        {"activo": False, "tareas": []})
    monkeypatch.setattr(main, "_j_mis_recordatorios", lambda: recordatorios or
                        {"recordatorios": []})
    monkeypatch.setattr(main, "_jarvis_contexto_lugar", lambda: lugar)
    return llamadas


class TestTexto:
    def test_lo_que_queda_de_hoy_y_lo_de_manana(self, monkeypatch):
        ahora = datetime.now(main.LOCAL_TZ)
        manana = ahora + timedelta(days=1)
        _fuentes(monkeypatch, eventos={"events": [
            {"title": "Ya pasó", "start": _iso(ahora - timedelta(hours=3)),
             "end": _iso(ahora - timedelta(hours=2))},
            {"title": "En marcha", "start": _iso(ahora - timedelta(minutes=10)),
             "end": _iso(ahora + timedelta(minutes=50))},
            {"title": "Dentista", "location": "Calle Mayor",
             "start": _iso(manana.replace(hour=10, minute=0)),
             "end": _iso(manana.replace(hour=11, minute=0))},
        ]})
        texto = main._contexto_de_voz()
        assert f"a las {ahora.strftime('%H:%M')}" in texto
        assert "Ya pasó" not in texto
        assert "En marcha" in texto and "en curso" in texto
        assert "10:00 Dentista (en Calle Mayor)" in texto
        assert "con lluvia" in texto and "máxima 18" in texto

    def test_outlook_caido_no_suena_a_dia_libre(self, monkeypatch):
        _fuentes(monkeypatch, eventos={"error": "sin sesión"})
        texto = main._contexto_de_voz()
        assert "no la he podido mirar" in texto
        assert "nada en la agenda" not in texto

    def test_una_parte_que_revienta_no_se_lleva_las_demas(self, monkeypatch):
        _fuentes(monkeypatch)

        def _revienta():
            raise RuntimeError("Graph no contesta")

        monkeypatch.setattr(main, "_j_tareas", _revienta)
        texto = main._contexto_de_voz()
        assert "Tareas: no lo he podido mirar" in texto
        assert "Tiempo:" in texto and "nada en la agenda" in texto

    def test_tareas_que_vencen_y_to_do_apagado(self, monkeypatch):
        hoy = datetime.now(main.LOCAL_TZ).date()
        _fuentes(monkeypatch, tareas={"activo": True, "tareas": [
            {"titulo": "Pagar el seguro", "fecha": (hoy - timedelta(days=1)).isoformat()},
            {"titulo": "Algún día", "fecha": None},
        ]})
        texto = main._contexto_de_voz()
        assert "2 pendientes" in texto and "Pagar el seguro (vencida)" in texto
        assert "Algún día" not in texto

        main._contexto_voz_cache.clear()
        _fuentes(monkeypatch)                     # To Do apagado: ni se menciona
        assert "Tareas" not in main._contexto_de_voz()

    def test_no_pregunta_en_cada_turno(self, monkeypatch):
        llamadas = _fuentes(monkeypatch)
        main._contexto_de_voz()
        main._contexto_de_voz()
        assert llamadas["outlook"] == 1


class TestTelefono:
    def test_sin_token_no_entra(self, client, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", TOKEN)
        assert client.get("/telefono/contexto").status_code == 401
        assert client.get("/telefono/contexto",
                          headers={"Authorization": "Bearer otro"}).status_code == 401

    def test_lleva_el_lugar(self, client, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", TOKEN)
        _fuentes(monkeypatch, lugar="\nAhora mismo el usuario está en el gimnasio.\n")
        r = client.get("/telefono/contexto", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert "en el gimnasio" in r.json()["texto"]


class TestTurno:
    def test_por_voz_va_al_final_y_por_escrito_no(self, client, auth_headers, monkeypatch):
        _fuentes(monkeypatch)
        cliente = _con_modelo(monkeypatch, [_mensaje("Hola."), _mensaje("Hola.")])
        client.post("/jarvis", json={"mensaje": "hola", "voz": True}, headers=auth_headers)
        mensajes = cliente.recibido[0]["messages"]
        assert "LO QUE YA ESTÁ MIRADO" in mensajes[-2]["content"]
        # El prefijo cacheable no cambia: el prompt de sistema no lo lleva.
        assert "LO QUE YA ESTÁ MIRADO" not in mensajes[0]["content"]

        client.post("/jarvis", json={"mensaje": "hola"}, headers=auth_headers)
        assert all("LO QUE YA ESTÁ MIRADO" not in m["content"]
                   for m in cliente.recibido[-1]["messages"])

    def test_si_revienta_el_turno_sigue(self, client, auth_headers, monkeypatch):
        def _revienta(incluir_lugar=False):
            raise RuntimeError("todo caído")

        monkeypatch.setattr(main, "_contexto_de_voz", _revienta)
        _con_modelo(monkeypatch, [_mensaje("Hola.")])
        r = client.post("/jarvis", json={"mensaje": "hola", "voz": True}, headers=auth_headers)
        assert r.status_code == 200

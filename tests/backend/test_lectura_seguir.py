"""El lector del teléfono con mando (parche 24): seguir donde se quedó, aunque se colgara,
y saltar de sección o de bloque.

Lo que se comprueba:

- el briefing se parte por sus títulos numerados, no por los separadores de guiones
  bajos, que la rutina pone donde cae: el 24/10 había uno solo al final (se leía SOLO la
  línea de las fuentes) y el 25/10 uno solo al principio (todo era una sección);
- cada subtítulo abre bloque y trozo nuevo, que es donde cae «siguiente»;
- la voice-app apunta el trozo que empieza a sonar y `seguir` lo retoma, en la misma
  llamada o en otra, con o sin decir qué se leía; lo terminado y lo viejo no se siguen;
- la llamada nueva sabe que hay algo a medias (`/telefono/contexto`);
- la posición sobrevive a un reinicio si está la tabla, y sin ella se queda en memoria.
"""
from datetime import datetime, timedelta, timezone

import pytest

import main
from conftest import FakeResponse

AHORA = datetime(2026, 10, 25, 9, 0, tzinfo=main.LOCAL_TZ)
TOKEN = {"Authorization": "Bearer mcp-telefono-token"}


@pytest.fixture(autouse=True)
def _reloj_y_tokens(monkeypatch):
    monkeypatch.setattr(main, "_ahora_local", lambda: AHORA)
    monkeypatch.setattr(main, "get_valid_token", lambda: "graph-token")
    monkeypatch.setattr(main, "JARVIS_MCP_TELEFONO_TOKEN", "mcp-telefono-token")


def _correo(texto):
    return FakeResponse({"value": [{
        "subject": "🌅 Buenos días Mikel — Briefing del 25/10/2026",
        "sentDateTime": "2026-10-25T07:42:57Z",
        "body": {"contentType": "text", "content": texto}}]})


# La forma del 24/10: sin separadores entre secciones, uno solo antes del pie de fuentes,
# una sección «3.5», subtítulos con y sin emoji y viñetas sangradas.
BRIEFING_24 = """⚠️ Incidencias de recopilación

  *   Construidas con búsqueda web: Tecnología General.

1. 🖥️ Tecnología General

  *   Sale una versión nueva de una biblioteca de cifrado. Añade dos protocolos.

2. 🤖 Inteligencia Artificial

IA General

  *   Un laboratorio publica un modelo abierto.

🔭 Antes de que sea tendencia

  *   Un repositorio pequeño sube rápido.

3. 🌍 Actualidad General

🇪🇸 España

  *   El Congreso aprueba una ley.

3.5. 💹 Economía y Geopolítica

Al día

  *   El IBEX sube un 1 %.

💡 La palabra del día: economía sumergida

La que no declara lo que gana.

4. 📅 Tu agenda de hoy

  *   10:00: Reunión de equipo.

5. 🩺 Tu día

🌦️ Clima

  *   Sol y 20 grados.

________________________________

Fuentes base: boletines de ayer y búsqueda web
"""

# La del 25/10: saludo, incidencias y UN separador antes de la primera sección.
BRIEFING_25 = """🎂 Un saludo especial. Aquí va el briefing.

⚠️ Incidencias de recopilación

  *   Una fuente llegó vacía.

________________________________
1. 🖥️ Tecnología General

  *   Primera noticia de tecnología.

2. 🤖 Inteligencia Artificial

  *   Primera noticia de IA.
"""


class TestLasSeccionesDeVerdad:
    def test_por_titulos_numerados_sin_incidencias_ni_pie(self):
        secciones = main._briefing_secciones(BRIEFING_24)
        assert [(s["etiqueta"], s["titulo"]) for s in secciones] == [
            ("1", "Tecnología General"), ("2", "Inteligencia Artificial"),
            ("3", "Actualidad General"), ("3.5", "Economía y Geopolítica"),
            ("4", "Tu agenda de hoy"), ("5", "Tu día")]
        assert [s["n"] for s in secciones] == [1, 2, 3, 4, 5, 6]
        texto = str(secciones)
        assert "Fuentes base" not in texto and "búsqueda web:" not in texto

    def test_un_separador_al_principio_no_lo_junta_todo(self):
        secciones = main._briefing_secciones(BRIEFING_25)
        assert [s["titulo"] for s in secciones] == ["Tecnología General",
                                                    "Inteligencia Artificial"]
        assert "saludo" not in str(secciones) and "vacía" not in str(secciones)

    def test_una_lista_numerada_del_texto_no_abre_seccion(self):
        texto = "1. 🖥️ Tecnología\n\nTres claves:\n1. La primera.\n\n2. 🤖 IA\n\n* Algo.\n"
        assert [s["titulo"] for s in main._briefing_secciones(texto)] == ["Tecnología", "IA"]

    def test_sin_titulos_numerados_se_parte_por_separadores(self):
        texto = "Fecha\n_____\nTecnología\n\n* Uno.\n_____\nDeportes\n\n* Dos.\n"
        assert [s["titulo"] for s in main._briefing_secciones(texto)] == ["Tecnología",
                                                                          "Deportes"]

    def test_cada_subtitulo_abre_bloque_y_trozo(self):
        ia, actualidad, economia = (main._voz_de_seccion(s)
                                    for s in main._briefing_secciones(BRIEFING_24)[1:4])
        # Sin nada antes del primer subtítulo, el título de la sección va con él.
        assert ia["trozos"][0].startswith("Inteligencia Artificial. IA General. Un laboratorio")
        assert ia["bloques"] == [{"trozo": 0, "titulo": "IA General"},
                                 {"trozo": 1, "titulo": "Antes de que sea tendencia"}]
        assert ia["trozos"][1].startswith("Antes de que sea tendencia.")
        assert economia["bloques"][1] == {"trozo": 1,
                                          "titulo": "La palabra del día: economía sumergida"}
        assert actualidad["bloques"] == [{"trozo": 0, "titulo": "España"}]

    def test_una_frase_corta_con_punto_no_es_subtitulo(self):
        assert main._es_subtitulo("Al día") and main._es_subtitulo("🌦️ Clima")
        assert not main._es_subtitulo("La que no declara lo que gana.")
        assert not main._es_subtitulo("  *   Sol y 20 grados")
        assert not main._es_subtitulo("1. 🖥️ Tecnología General")


class TestRecortar:
    SECCIONES = [{"n": 1, "titulo": "A", "trozos": ["a0", "a1", "a2"]},
                 {"n": 2, "titulo": "B", "trozos": ["b0"]}]

    def test_empieza_en_el_trozo_y_lo_dice(self):
        r = main._recortar_lectura(self.SECCIONES, 1, 0, 2)
        assert r[0]["trozos"] == ["a2"] and r[0]["primer_trozo"] == 2
        assert r[1] == {"n": 2, "titulo": "B", "trozos": ["b0"], "primer_trozo": 0}

    def test_un_trozo_de_mas_se_queda_en_el_ultimo(self):
        assert main._recortar_lectura(self.SECCIONES, 1, 1, 9)[0]["trozos"] == ["a2"]


class TestSeguirDondeSeQuedo:
    def _leer(self, client, consulta):
        return client.get(f"/telefono/lectura?{consulta}", headers=TOKEN).json()

    def _apuntar(self, client, **cuerpo):
        r = client.post("/telefono/lectura/posicion", headers=TOKEN,
                        json={"que": "briefing", "fecha": "2026-10-25", **cuerpo})
        assert r.status_code == 200
        return r.json()

    def test_trae_el_indice_con_bloques_y_etiquetas(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        r = self._leer(client, "que=briefing&desde=2")
        assert r["ok"] is True and r["que"] == "briefing" and r["fecha"] == "2026-10-25"
        assert [s["n"] for s in r["secciones"]] == [2, 3, 4, 5, 6]
        assert len(r["indice"]) == 6 and r["indice"][3]["etiqueta"] == "3.5"
        assert r["indice"][1]["bloques"][1]["titulo"] == "Antes de que sea tendencia"

    def test_colgar_y_seguir_en_otra_llamada(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        self._leer(client, "que=briefing")
        # La voice-app apunta cada trozo antes de que suene; luego se cuelga.
        self._apuntar(client, n=2, trozo=1, titulo="Inteligencia Artificial")
        r = self._leer(client, "seguir=true")           # sin decir qué: lo último a medias
        assert r["ok"] is True and r["que"] == "briefing"
        assert r["secciones"][0]["n"] == 2 and r["secciones"][0]["primer_trozo"] == 1
        assert r["secciones"][0]["trozos"][0].startswith("Antes de que sea tendencia.")
        assert [s["n"] for s in r["secciones"]] == [2, 3, 4, 5, 6]

    def test_seguir_nombrando_que(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        self._leer(client, "que=briefing&desde=4")
        r = self._leer(client, "que=briefing&seguir=1")
        assert r["secciones"][0]["n"] == 4 and r["secciones"][0]["primer_trozo"] == 0

    def test_sin_nada_a_medias_lo_dice(self, client, mock_requests):
        r = self._leer(client, "seguir=true")
        assert r == {"ok": False, "frase": "No tengo ninguna lectura a medias que seguir."}
        assert mock_requests.called("GET", "graph.microsoft.com") == []

    def test_lo_terminado_no_se_sigue(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        self._leer(client, "que=briefing")
        self._apuntar(client, n=6, trozo=0, titulo="Tu día", terminada=True)
        assert self._leer(client, "seguir=true")["ok"] is False

    def test_lo_de_hace_demasiado_no_se_sigue(self, client, mock_requests, monkeypatch):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        self._leer(client, "que=briefing")
        viejo = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        main._lectura_posiciones["briefing"]["actualizado"] = viejo
        assert self._leer(client, "seguir=true")["ok"] is False

    def test_si_el_texto_cambio_busca_la_seccion_por_su_titulo(self, client, monkeypatch):
        tareas = [{"titulo": "Pagar el seguro", "fecha": "2026-10-20"},
                  {"titulo": "Llamar al taller", "fecha": None}]
        monkeypatch.setattr(main, "_j_tareas", lambda: {"activo": True, "tareas": tareas})
        self._leer(client, "que=tareas&desde=2")          # «Sin fecha», la 2
        tareas.pop(0)                                      # ahora «Sin fecha» es la 1
        r = self._leer(client, "seguir=true")
        assert [s["titulo"] for s in r["secciones"]] == ["Sin fecha"]

    def test_la_posicion_de_otra_fecha_no_hereda_el_indice(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        self._leer(client, "que=briefing")
        self._apuntar(client, fecha="2026-10-24", n=1, trozo=0, titulo="Otra")
        fila = main._lectura_posiciones["briefing"]
        assert fila["fecha"] == "2026-10-24" and "indice" not in fila

    def test_sin_token_o_que_raro_no(self, client):
        assert client.post("/telefono/lectura/posicion",
                           json={"que": "briefing"}).status_code == 401
        assert client.post("/telefono/lectura/posicion", headers=TOKEN,
                           json={"que": "todo"}).status_code == 422
        assert client.post("/telefono/lectura/posicion", headers=TOKEN,
                           json={"que": "briefing", "fecha": "25/10"}).status_code == 422


class TestLaLlamadaNuevaLoSabe:
    def test_el_contexto_dice_lo_que_quedo_a_medias(self, client, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_contexto_de_voz", lambda incluir_lugar=False: "LO MIRADO")
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        client.get("/telefono/lectura?que=briefing", headers=TOKEN)
        client.post("/telefono/lectura/posicion", headers=TOKEN, json={
            "que": "briefing", "fecha": "2026-10-25", "n": 4, "trozo": 1,
            "titulo": "Economía y Geopolítica"})
        texto = client.get("/telefono/contexto", headers=TOKEN).json()["texto"]
        assert texto.startswith("LO MIRADO\n\nLECTURA A MEDIAS:")
        assert "la sección 4 de 6, «Economía y Geopolítica»" in texto
        assert "📖 LEER: briefing seguir" in texto
        assert "del 25/10" not in texto                   # es el de hoy: no hace falta

    def test_sin_nada_a_medias_no_dice_nada(self, client, monkeypatch):
        monkeypatch.setattr(main, "_contexto_de_voz", lambda incluir_lugar=False: "LO MIRADO")
        assert client.get("/telefono/contexto", headers=TOKEN).json() == {"texto": "LO MIRADO"}


class TestSobreviveAUnReinicio:
    @pytest.fixture(autouse=True)
    def _persistir(self, monkeypatch):
        monkeypatch.setattr(main, "LECTURA_PERSISTIR", True)
        monkeypatch.setattr(main, "_lectura_fallo_dicho", False)

    def test_se_guarda_y_se_recupera_de_supabase(self, client, mock_requests):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        client.get("/telefono/lectura?que=briefing&desde=3", headers=TOKEN)
        guardado = mock_requests.called("POST", "/rest/v1/lecturas_telefono")
        assert guardado and "on_conflict=que" in guardado[-1][1]
        assert "merge-duplicates" in guardado[-1][2]["headers"]["Prefer"]
        fila = guardado[-1][2]["json"]
        assert fila["n"] == 3 and fila["que"] == "briefing" and fila["total"] == 6

        # Un despliegue: la memoria se vacía y la fila sigue en la tabla.
        main._lectura_posiciones.clear()
        main._lectura_cargada = False
        mock_requests.add("GET", "/rest/v1/lecturas_telefono", FakeResponse([fila]))
        r = client.get("/telefono/lectura?seguir=true", headers=TOKEN).json()
        assert r["ok"] is True and r["secciones"][0]["n"] == 3

    def test_sin_la_tabla_sigue_en_memoria_y_avisa_una_vez(self, client, mock_requests,
                                                            caplog):
        mock_requests.add("GET", "sentitems", _correo(BRIEFING_24))
        mock_requests.add("POST", "/rest/v1/lecturas_telefono",
                          FakeResponse({"code": "42P01"}, status_code=404))
        mock_requests.add("GET", "/rest/v1/lecturas_telefono",
                          FakeResponse({"code": "42P01"}, status_code=404))
        client.get("/telefono/lectura?que=briefing&desde=2", headers=TOKEN)
        client.post("/telefono/lectura/posicion", headers=TOKEN, json={
            "que": "briefing", "fecha": "2026-10-25", "n": 2, "trozo": 1})
        r = client.get("/telefono/lectura?seguir=true", headers=TOKEN).json()
        assert r["ok"] is True and r["secciones"][0]["primer_trozo"] == 1
        avisos = [x for x in caplog.records if "lecturas_telefono" in x.getMessage()]
        assert len(avisos) == 1

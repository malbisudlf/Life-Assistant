"""Tests del turno retransmitido (`POST /jarvis/voz`) y de los rellenos hablados.

Lo que se prueba aquí es lo que hace que una llamada no tenga silencios: que el aviso de
cada herramienta salga ANTES de usarla (si sale después no sirve de nada) y que el turno
retransmitido dé exactamente el mismo resultado que el de una pieza — son el mismo bucle
y tienen que seguir siéndolo. Ver docs/JARVIS_VOZ.md.
"""
import json

import main
from test_jarvis import _con_modelo, _herramienta, _llamada, _mensaje


def _sin_texto(eventos):
    """Los tipos de evento del turno, quitando los deltas de texto.

    Son decenas por respuesta y lo que interesa comprobar en la mayoría de los tests es
    el esqueleto: qué avisa antes de qué. Lo que traen los deltas se mira aparte.
    """
    return [tipo for tipo, _ in eventos if tipo != "texto"]


def _dicho(eventos):
    """Todo el texto que salió por el altavoz mientras se generaba."""
    return "".join(datos.get("delta", "") for tipo, datos in eventos if tipo == "texto")


def _eventos(respuesta):
    """Parte una respuesta SSE en [(tipo, datos)]."""
    fuera = []
    for bloque in respuesta.text.split("\n\n"):
        lineas = [l for l in bloque.split("\n") if l.strip()]
        if not lineas:
            continue
        tipo  = lineas[0].removeprefix("event: ")
        datos = json.loads(lineas[1].removeprefix("data: "))
        fuera.append((tipo, datos))
    return fuera


class TestRellenos:
    def test_cada_herramienta_tiene_algo_que_decir(self):
        # El genérico existe para las que no están en la tabla, incluidas las que se
        # conecten por MCP mucho después de escribirla.
        assert main._relleno_herramienta("agenda") == "Déjame mirar el calendario."
        assert main._relleno_herramienta("herramienta_que_no_existe") == main._JARVIS_RELLENO_GENERICO
        assert main._relleno_herramienta("") == main._JARVIS_RELLENO_GENERICO

    def test_son_frases_cortas_y_sin_markdown(self):
        # Se van a decir en voz alta: los asteriscos y las URLs se leen literalmente.
        for nombre, frase in main._JARVIS_RELLENOS.items():
            assert frase == frase.strip(), nombre
            assert len(frase) <= 60, nombre
            assert not any(c in frase for c in "*_`#[]()"), nombre
            assert frase.endswith("."), nombre


class TestJarvisVoz:
    def test_sin_autenticacion_no_habla(self, client):
        r = client.post("/jarvis/voz", json={"mensaje": "hola"})
        assert r.status_code in (401, 403)

    def test_mensaje_vacio_se_rechaza_antes_de_abrir_el_stream(self, client, auth_headers):
        # Con el stream ya abierto la respuesta es un 200 y el error solo puede ser un
        # evento; lo que se puede comprobar antes, se comprueba antes.
        r = client.post("/jarvis/voz", json={"mensaje": "   "}, headers=auth_headers)
        assert r.status_code == 400

    def test_una_charla_sale_por_el_evento_final(
            self, client, auth_headers, monkeypatch, mock_requests):
        _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        r = client.post("/jarvis/voz", json={"mensaje": "hola"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        eventos = _eventos(r)
        assert _sin_texto(eventos) == ["fin"]
        assert eventos[-1][1]["respuesta"] == "Buenas."

    def test_el_aviso_de_la_herramienta_llega_antes_de_usarla(
            self, client, auth_headers, monkeypatch, mock_requests):
        """El orden es TODO el asunto: un aviso que llega después del trabajo no ahorra
        ningún silencio."""
        ejecutada = []
        _herramienta(monkeypatch, "clima", lambda: ejecutada.append(True) or {"ahora": 21})
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("Hace 21 grados."),
        ])

        # Sobre el generador y no sobre el endpoint a propósito: TestClient se bebe la
        # respuesta entera antes de devolverla, así que por ahí los dos órdenes posibles
        # se ven igual. Aquí se pide UN evento y se mira si la herramienta ya corrió.
        turno = main._jarvis_turno(main.JarvisIn(mensaje="que tiempo hace", voz=True))
        tipo, aviso = next(turno)
        assert tipo == "herramienta"
        assert aviso["nombre"] == "clima"
        assert aviso["decir"] == main._JARVIS_RELLENOS["clima"]
        assert ejecutada == [], "el aviso llegó después de trabajar: no ahorra ningún silencio"

        # Y detrás del aviso vienen los trozos de la respuesta según se escriben, con el
        # cierre siempre al final.
        tipos = [tipo for tipo, _ in turno]
        assert tipos[-1] == "fin"
        assert set(tipos[:-1]) <= {"texto"}
        assert ejecutada == [True]

        # Y por el endpoint sale lo mismo.
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("Hace 21 grados."),
        ])
        r = client.post("/jarvis/voz", json={"mensaje": "que tiempo hace"}, headers=auth_headers)
        assert _sin_texto(_eventos(r)) == ["herramienta", "fin"]

    def test_lo_que_solo_se_propone_no_se_anuncia_como_trabajo(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Crear un evento no se ejecuta: se propone. Decir 'voy con el calendario' ahí
        sería anunciar algo que no está pasando."""
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("crear_evento", {"titulo": "Cita", "fecha": "2026-09-01"})]),
            _mensaje("Cuando lo confirmes, lo creo."),
        ])
        r = client.post("/jarvis/voz", json={"mensaje": "apuntame una cita"}, headers=auth_headers)
        eventos = _eventos(r)
        assert _sin_texto(eventos) == ["fin"]
        assert eventos[-1][1]["pendiente"]["herramienta"] == "crear_evento"

    def test_pide_el_prompt_de_voz_aunque_el_cliente_no_lo_diga(
            self, client, auth_headers, monkeypatch, mock_requests):
        # Que este endpoint sirviera texto de leer no tendría sentido: lo decide él, no
        # el cuerpo de la petición.
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        client.post("/jarvis/voz", json={"mensaje": "hola", "voz": False}, headers=auth_headers)
        sistema = cliente.recibido[0]["messages"][0]["content"]
        assert sistema == main._jarvis_sistema(voz=True)

    def test_un_fallo_a_media_frase_llega_como_evento(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Con el 200 ya mandado, un error no puede ser un código de estado."""
        def _explota(_body):
            raise RuntimeError("el modelo se cayó")
            yield  # noqa: unreachable — lo que lo hace generador

        monkeypatch.setattr(main, "_jarvis_turno", _explota)
        r = client.post("/jarvis/voz", json={"mensaje": "hola"}, headers=auth_headers)
        assert r.status_code == 200
        eventos = _eventos(r)
        assert eventos[-1][0] == "error"
        # El detalle real va al registro, no al cliente.
        assert "el modelo se cayó" not in r.text

    def test_el_turno_es_el_mismo_que_el_de_una_pieza(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Si esto se rompe es que el bucle se ha duplicado por algún sitio."""
        _herramienta(monkeypatch, "clima", lambda: {"ahora": 21})
        guion = [_mensaje(tool_calls=[_llamada("clima")]), _mensaje("Hace 21 grados.")]

        _con_modelo(monkeypatch, list(guion))
        escrito = client.post("/jarvis", json={"mensaje": "tiempo"}, headers=auth_headers).json()

        _con_modelo(monkeypatch, list(guion))
        hablado = _eventos(client.post("/jarvis/voz", json={"mensaje": "tiempo"},
                                       headers=auth_headers))[-1][1]

        assert escrito["respuesta"]    == hablado["respuesta"]
        assert escrito["herramientas"] == hablado["herramientas"]


class TestTextoMientrasSeGenera:
    """La otra mitad de lo que hace que una llamada no tenga silencios.

    Con el turno de una pieza, la síntesis no empieza hasta que el modelo ha terminado de
    escribir: los dos tiempos se suman y son dos segundos largos antes de la primera
    palabra. Retransmitiendo el texto corren a la vez.
    """

    def test_el_texto_sale_a_trozos_y_antes_del_cierre(
            self, client, auth_headers, monkeypatch, mock_requests):
        _con_modelo(monkeypatch, [_mensaje("Mañana tienes tres cosas. La primera es a las nueve.")])
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "que tengo"},
                                       headers=auth_headers))

        tipos = [t for t, _ in eventos]
        assert tipos.count("texto") > 1, "llegó de una pieza: no se ha ganado nada"
        assert tipos[-1] == "fin"
        # Lo que se dijo por el camino es EXACTAMENTE lo que acabó en pantalla: un delta
        # perdido es una frase que no se oye, y no se notaría en ninguna otra parte.
        assert _dicho(eventos) == eventos[-1][1]["respuesta"]

    def test_lo_que_ya_se_dijo_no_se_repite_al_cerrar(
            self, client, auth_headers, monkeypatch, mock_requests):
        """`por_decir` es lo que le queda al navegador por mandar al sintetizador. Si el
        cierre lo trajera entero, cada respuesta se oiría dos veces."""
        _con_modelo(monkeypatch, [_mensaje("Hace veintiún grados.")])
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "tiempo"},
                                       headers=auth_headers))
        assert eventos[-1][1]["por_decir"] == ""

    def test_lo_que_sustituye_a_una_respuesta_vacia_hay_que_decirlo(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Un modelo que se queda sin tokens devuelve VACÍO, y entonces la respuesta la
        pone el backend: eso no ha salido por ningún altavoz y hay que decirlo entero."""
        _herramienta(monkeypatch, "clima", lambda: {"ahora": 21})
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("", motivo="length"),   # el cierre se queda mudo
            _mensaje("", motivo="length"),   # y el reintento de _texto_garantizado también
        ])
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "tiempo"},
                                       headers=auth_headers))
        cierre = eventos[-1][1]
        assert cierre["respuesta"]
        assert cierre["por_decir"] == cierre["respuesta"]

    def test_las_herramientas_llegan_partidas_y_se_vuelven_a_juntar(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Lo delicado del streaming no es el texto: es que las `tool_calls` llegan a
        cachos —el nombre en uno, los argumentos en cinco— y despachar media llamada sería
        ejecutar una herramienta con los argumentos equivocados."""
        recibido = []
        _herramienta(monkeypatch, "guardar_idea",
                     lambda texto: recibido.append(texto) or {"ok": True})
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[_llamada("guardar_idea", {"texto": "comprar café descafeinado"})]),
            _mensaje("Apuntado."),
        ])
        client.post("/jarvis/voz", json={"mensaje": "apunta algo"}, headers=auth_headers)
        assert recibido == ["comprar café descafeinado"]

    def test_dos_herramientas_a_la_vez_no_se_mezclan(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Los trozos de dos llamadas vienen intercalados y solo los distingue el `index`.
        Juntarlos mal daría una herramienta con los argumentos de la otra."""
        _herramienta(monkeypatch, "clima", lambda: {"ahora": 21})
        vistas = []
        _herramienta(monkeypatch, "guardar_idea",
                     lambda texto: vistas.append(texto) or {"ok": True})
        _con_modelo(monkeypatch, [
            _mensaje(tool_calls=[
                _llamada("clima", {}, id_="call-a"),
                _llamada("guardar_idea", {"texto": "una idea"}, id_="call-b"),
            ]),
            _mensaje("Listo."),
        ])
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "haz dos cosas"},
                                       headers=auth_headers))
        assert vistas == ["una idea"]
        assert eventos[-1][1]["herramientas"] == ["clima", "guardar_idea"]

    def test_por_voz_se_abre_directamente_con_el_modelo_de_accion(
            self, client, auth_headers, monkeypatch, mock_requests):
        """El reparto de dos modelos cuesta una llamada entera antes de la primera sílaba.
        Por escrito no se nota; hablando son los dos segundos que se vienen a quitar."""
        monkeypatch.setattr(main, "JARVIS_MODEL", "pequeño")
        monkeypatch.setattr(main, "JARVIS_MODEL_ACCION", "grande")
        monkeypatch.setattr(main, "JARVIS_VOZ_MODELO_DIRECTO", True)

        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        client.post("/jarvis/voz", json={"mensaje": "hola"}, headers=auth_headers)
        assert cliente.recibido[0]["model"] == "grande"

        # Y por escrito sigue abriendo el pequeño: esto es un atajo de la voz, no un
        # cambio de cómo funciona Jarvis.
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        client.post("/jarvis", json={"mensaje": "hola"}, headers=auth_headers)
        assert cliente.recibido[0]["model"] == "pequeño"

    def test_con_el_atajo_apagado_no_se_dice_lo_que_va_a_descartarse(
            self, client, auth_headers, monkeypatch, mock_requests):
        """Sin el atajo vuelve el relevo, y lo que dijera el pequeño se tira sin
        ejecutarse: decirlo en voz alta sería contradecirse dos segundos después."""
        monkeypatch.setattr(main, "JARVIS_MODEL", "pequeño")
        monkeypatch.setattr(main, "JARVIS_MODEL_ACCION", "grande")
        monkeypatch.setattr(main, "JARVIS_VOZ_MODELO_DIRECTO", False)
        _herramienta(monkeypatch, "clima", lambda: {"ahora": 21})

        cliente = _con_modelo(monkeypatch, [
            _mensaje("No puedo mirar el tiempo.", tool_calls=[_llamada("clima")]),
            _mensaje(tool_calls=[_llamada("clima")]),
            _mensaje("Hace 21 grados."),
        ])
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "tiempo"},
                                       headers=auth_headers))

        assert cliente.recibido[0]["model"] == "pequeño"
        assert not cliente.recibido[0].get("stream"), "se retransmitió algo que iba a la basura"
        assert "No puedo mirar el tiempo." not in _dicho(eventos)
        assert _dicho(eventos) == "Hace 21 grados."

    def test_un_modelo_que_no_retransmite_no_deja_muda_la_llamada(
            self, client, auth_headers, monkeypatch, mock_requests):
        """OpenAI exige la organización verificada para retransmitir con la familia gpt-5,
        que es de donde sale JARVIS_MODEL_ACCION. Sin red, una cuenta sin verificar se
        quedaba sin modo llamada por un permiso, y el fallo salía como «se ha roto el
        turno», que no apunta a ninguna parte."""
        cliente = _con_modelo(monkeypatch, [_mensaje("Buenas.")])
        crear   = cliente.create

        def _sin_streaming(**kwargs):
            if kwargs.get("stream"):
                raise RuntimeError("your organization must be verified to stream this model")
            return crear(**kwargs)

        monkeypatch.setattr(cliente, "create", _sin_streaming, raising=False)
        eventos = _eventos(client.post("/jarvis/voz", json={"mensaje": "hola"},
                                       headers=auth_headers))

        # Sin deltas —se pierde el adelanto de la primera frase— pero la respuesta llega
        # entera y con el aviso de que hay que decirla.
        assert _sin_texto(eventos) == ["fin"]
        assert eventos[-1][1]["respuesta"] == "Buenas."
        assert eventos[-1][1]["por_decir"] == "Buenas."

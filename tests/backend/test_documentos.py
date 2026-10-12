"""Los documentos de OneDrive: que Jarvis los busque y los lea.

Lo delicado no es la API de Graph sino lo de alrededor: que encender el permiso nuevo no
se lleve por delante lo que ya funcionaba, que lo que hay dentro de un documento llegue
al modelo marcado como dato, que nada se descargue sin tope, y que lo que no se sabe leer
se diga con su enlace en vez de inventarse.
"""
import io
import zipfile

import pytest

import main
from conftest import FakeResponse


@pytest.fixture
def encendido(monkeypatch, graph_token):
    monkeypatch.setattr(main, "ONEDRIVE", True)


def _docx(*parrafos):
    cuerpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in parrafos)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document xmlns:w="w"><w:body>{cuerpo}'
                   "</w:body></w:document>")
    return salida.getvalue()


def _pdf(texto):
    """Un PDF mínimo de una página con una línea de texto, escrito a mano: así el test
    no depende de tener con qué generar PDFs."""
    contenido = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode()
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(contenido)).encode() + b" >>\nstream\n" + contenido + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida, posiciones = bytearray(b"%PDF-1.4\n"), []
    for n, obj in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posiciones)
    salida += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
               f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(salida)


def _documento(mock_requests, nombre, contenido, tamano=None, id="ABC!12"):
    mock_requests.add("GET", f"/items/{id}/content", FakeResponse(content=contenido))
    mock_requests.add("GET", f"/items/{id}?", FakeResponse({
        "id": id, "name": nombre, "size": len(contenido) if tamano is None else tamano,
        "file": {"mimeType": "x"}, "webUrl": f"https://onedrive.test/{nombre}"}))


class TestLosPermisos:
    def test_apagado_no_se_pide_el_permiso(self, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE", False)
        assert "Files.Read" not in main._scopes()

    def test_encendido_se_pide(self, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE", True)
        assert "Files.Read" in main._scopes()
        assert set(main.SCOPES_BASE) <= set(main._scopes())

    def test_sin_reconsentir_no_se_pierde_lo_que_ya_estaba(self, monkeypatch, mock_requests):
        """Con el correo y las tareas ya consentidos, encender OneDrive y los cumpleaños a
        la vez y renovar sin reconectar: se van quitando los permisos nuevos de uno en
        uno, y el que vale es el que conserva el correo y las tareas."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "TAREAS_TODO", True)
        monkeypatch.setattr(main, "ONEDRIVE", True)
        monkeypatch.setattr(main, "CUMPLES", True)
        mock_requests.add("GET", "oauth_tokens", FakeResponse(
            [{"access_token": "viejo", "refresh_token": "r", "expires_at": 0}], 200))
        pedidos = []

        class _Msal:
            def acquire_token_by_refresh_token(self, refresh_token, scopes):
                pedidos.append(list(scopes))
                if {"Files.Read", "Contacts.Read"} & set(scopes):
                    return {"error": "invalid_grant"}
                return {"access_token": "nuevo", "refresh_token": "r", "expires_in": 3600}

        monkeypatch.setattr(main, "_msal_app", lambda: _Msal())
        assert main.get_valid_token() == "nuevo"
        assert len(pedidos) == 3
        assert {"Mail.ReadWrite", "Tasks.ReadWrite"} <= set(pedidos[-1])


class TestBuscar:
    def test_apagado_no_llama_a_graph(self, mock_requests):
        r = main._j_buscar_documentos("póliza")
        assert r == {"error": "Los documentos de OneDrive están apagados (ONEDRIVE=0)."}
        assert mock_requests.calls == []

    def test_solo_ficheros_y_con_la_carpeta(self, encendido, mock_requests):
        mock_requests.add("GET", "/root/search", FakeResponse({"value": [
            {"id": "C!1", "name": "Seguros", "folder": {"childCount": 3}},
            {"id": "F!2", "name": "Póliza coche.pdf", "file": {}, "size": 204800,
             "lastModifiedDateTime": "2026-03-01T23:30:00Z", "webUrl": "https://od/p",
             "parentReference": {"path": "/drive/root:/Documentos/Seguros"}},
            {"id": "F!3", "name": "Presupuesto.xlsx", "file": {}, "size": 10},
        ]}))
        r = main._j_buscar_documentos("póliza")
        assert r["aviso"] == main._AVISO_DOCUMENTO
        assert r["documentos"] == [
            # 23:30 UTC del 1 de marzo ya es el 2 en Madrid.
            {"id": "F!2", "nombre": "Póliza coche.pdf", "carpeta": "Documentos/Seguros",
             "modificado": "2026-03-02", "tamano_kb": 200, "legible": True, "url": "https://od/p"},
            {"id": "F!3", "nombre": "Presupuesto.xlsx", "carpeta": None, "modificado": None,
             "tamano_kb": 0, "legible": False, "url": None},
        ]

    def test_una_comilla_no_rompe_la_consulta(self, encendido, mock_requests):
        """Es una cadena OData entre comillas simples: sin doblarla, «l'assurance» cerraba
        la cadena y el resto de la búsqueda iba a Graph como sintaxis."""
        mock_requests.add("GET", "/root/search", FakeResponse({"value": []}))
        r = main._j_buscar_documentos("l'assurance / auto")
        assert r["documentos"] == []
        url = mock_requests.called("GET", "/root/search")[0][1]
        assert "search(q='l%27%27assurance%20%2F%20auto')" in url

    def test_sin_permiso_lo_dice_con_su_arreglo(self, encendido, mock_requests):
        mock_requests.add("GET", "/root/search", FakeResponse({"error": "x"}, 403))
        assert "vuelve a conectar Outlook" in main._j_buscar_documentos("póliza")["error"]


class TestLeer:
    def test_un_id_raro_no_llega_a_graph(self, encendido, mock_requests):
        """El id lo escribe un modelo y va en la ruta de Graph."""
        for malo in ("../../me/messages", "a/b", "x?y", ""):
            assert "error" in main._j_leer_documento(malo)
        assert mock_requests.calls == []

    def test_word_con_sus_parrafos_y_marcado_como_dato(self, encendido, mock_requests):
        _documento(mock_requests, "Contrato piso.docx",
                   _docx("Arrendador: Fulano", "Fianza: dos meses &amp; aval"))
        r = main._j_leer_documento("ABC!12")
        assert r["aviso"] == main._AVISO_DOCUMENTO
        assert r["texto"] == "Arrendador: Fulano\nFianza: dos meses & aval"
        assert r["truncado"] is False
        assert r["url"] == "https://onedrive.test/Contrato piso.docx"
        # La descarga va a trozos: sin `stream`, el tope llegaría tarde.
        assert mock_requests.called("GET", "/content")[0][2]["stream"] is True

    def test_pdf(self, encendido, mock_requests):
        _documento(mock_requests, "Poliza.pdf", _pdf("La grua cubre 50 km"))
        assert "La grua cubre 50 km" in main._j_leer_documento("ABC!12")["texto"]

    def test_lo_que_no_sabe_leer_lo_dice_con_el_enlace_y_sin_descargarlo(self, encendido, mock_requests):
        _documento(mock_requests, "Gastos.xlsx", b"x")
        r = main._j_leer_documento("ABC!12")
        assert "No sé leer ficheros .xlsx" in r["error"]
        assert r["url"] == "https://onedrive.test/Gastos.xlsx"
        assert mock_requests.called("GET", "/content") == []

    def test_demasiado_grande_no_se_descarga(self, encendido, mock_requests):
        _documento(mock_requests, "Escaneo.pdf", b"x", tamano=main.ONEDRIVE_MAX_BYTES + 1)
        assert "demasiado grande" in main._j_leer_documento("ABC!12")["error"]
        assert mock_requests.called("GET", "/content") == []

    def test_si_el_tamano_mentia_la_descarga_se_corta(self, encendido, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE_MAX_BYTES", 100)
        _documento(mock_requests, "Notas.txt", b"a" * 500, tamano=10)
        assert "error" in main._j_leer_documento("ABC!12")

    def test_sin_texto_es_un_escaneo(self, encendido, mock_requests):
        _documento(mock_requests, "Escaneo.pdf", _pdf(""))
        assert "escaneo" in main._j_leer_documento("ABC!12")["error"]

    def test_un_fichero_roto_no_tumba_la_conversacion(self, encendido, mock_requests):
        _documento(mock_requests, "Roto.docx", b"esto no es un zip")
        r = main._j_leer_documento("ABC!12")
        assert "No he podido sacar el texto" in r["error"]
        assert r["url"]

    def test_se_recorta_y_lo_dice(self, encendido, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE_MAX_TEXTO", 10)
        _documento(mock_requests, "Notas.md", b"y" * 50)
        r = main._j_leer_documento("ABC!12")
        assert r["texto"] == "y" * 10 and r["truncado"] is True

    def test_una_carpeta_no_se_lee(self, encendido, mock_requests):
        mock_requests.add("GET", "/items/C!1?", FakeResponse({"id": "C!1", "name": "Seguros",
                                                               "folder": {"childCount": 1}}))
        assert "carpeta" in main._j_leer_documento("C!1")["error"]


class TestJarvis:
    def test_apagado_no_se_anuncia(self, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE", False)
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert not {"buscar_documentos", "leer_documento"} & nombres

    def test_encendido_se_anuncia_y_es_directo(self, monkeypatch):
        monkeypatch.setattr(main, "ONEDRIVE", True)
        nombres = {h["function"]["name"] for h in main._jarvis_esquema()}
        assert {"buscar_documentos", "leer_documento"} <= nombres
        for n in ("buscar_documentos", "leer_documento"):
            assert main._JARVIS_HERRAMIENTAS[n]["confirmar"] is False

    def test_el_telefono_no_lee_documentos(self):
        """Al otro lado de la llamada hay una sesión con shell en `caja`, y lo que hay
        dentro de un documento lo ha escrito cualquiera."""
        assert not {"buscar_documentos", "leer_documento"} & main._MCP_SERVIDOR_HERRAMIENTAS

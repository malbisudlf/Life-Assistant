"""Widget de libros: lecturas con fecha de inicio y fin, y sugerencias de título."""
from conftest import FakeResponse

ID = "123e4567-e89b-12d3-a456-426614174000"


class TestLibros:
    def test_requiere_token(self, client):
        assert client.get("/libros").status_code in (401, 403)
        assert client.get("/libros/buscar?q=du").status_code in (401, 403)

    def test_listar(self, client, auth_headers, mock_requests):
        filas = [{"id": "a", "titulo": "Dune", "empezado": "2026-09-01", "terminado": None}]
        mock_requests.add("GET", "/rest/v1/libros", FakeResponse(filas))
        r = client.get("/libros", headers=auth_headers)
        assert r.status_code == 200 and r.json() == filas

    def test_crear_leyendo(self, client, auth_headers, mock_requests):
        saved = {"id": "a", "titulo": "Dune"}
        mock_requests.add("POST", "/rest/v1/libros", FakeResponse([saved], 201))
        r = client.post("/libros", headers=auth_headers,
                        json={"titulo": "  Dune ", "autor": "Frank Herbert", "empezado": "2026-09-01"})
        assert r.status_code == 200 and r.json() == {"ok": True, "libro": saved}
        enviado = mock_requests.called("POST", "/rest/v1/libros")[0][2]["json"]
        assert enviado == {"titulo": "Dune", "autor": "Frank Herbert", "portada": None,
                           "empezado": "2026-09-01", "terminado": None}

    def test_validaciones(self, client, auth_headers):
        assert client.post("/libros", headers=auth_headers, json={"titulo": "  "}).status_code == 422
        assert client.post("/libros", headers=auth_headers, json={}).status_code == 422
        r = client.post("/libros", headers=auth_headers,
                        json={"titulo": "X", "empezado": "2026-09-10", "terminado": "2026-09-01"})
        assert r.status_code == 422
        r = client.post("/libros", headers=auth_headers,
                        json={"titulo": "X", "portada": "javascript:alert(1)"})
        assert r.status_code == 422

    def test_error_supabase_al_crear(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "/rest/v1/libros", FakeResponse(None, 500, "boom"))
        assert client.post("/libros", headers=auth_headers, json={"titulo": "X"}).status_code == 502

    def test_patch_marca_terminado(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "/rest/v1/libros", FakeResponse([{"id": ID}]))
        r = client.patch(f"/libros/{ID}", headers=auth_headers, json={"terminado": "2026-09-20"})
        assert r.status_code == 200
        # Solo viaja lo que se mandó: `empezado` no se toca.
        assert mock_requests.called("PATCH", "/rest/v1/libros")[0][2]["json"] == {"terminado": "2026-09-20"}

    def test_patch_null_borra_la_fecha(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "/rest/v1/libros", FakeResponse([{"id": ID}]))
        client.patch(f"/libros/{ID}", headers=auth_headers, json={"terminado": None})
        assert mock_requests.called("PATCH", "/rest/v1/libros")[0][2]["json"] == {"terminado": None}

    def test_patch_vacio_inexistente_y_uuid(self, client, auth_headers, mock_requests):
        assert client.patch(f"/libros/{ID}", headers=auth_headers, json={}).status_code == 422
        assert client.patch("/libros/no-uuid", headers=auth_headers,
                            json={"terminado": "2026-09-20"}).status_code == 422
        mock_requests.add("PATCH", "/rest/v1/libros", FakeResponse([]))
        assert client.patch(f"/libros/{ID}", headers=auth_headers,
                            json={"terminado": "2026-09-20"}).status_code == 404

    def test_patch_fechas_incoherentes(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "/rest/v1/libros",
                          FakeResponse(None, 400, 'violates check constraint "libros_check"'))
        r = client.patch(f"/libros/{ID}", headers=auth_headers, json={"terminado": "2020-01-01"})
        assert r.status_code == 422

    def test_borrar(self, client, auth_headers, mock_requests):
        assert client.delete("/libros/no-uuid", headers=auth_headers).status_code == 422
        mock_requests.add("DELETE", "/rest/v1/libros", FakeResponse([], 204))
        assert client.delete(f"/libros/{ID}", headers=auth_headers).json() == {"ok": True}


class TestBuscarLibros:
    def test_mezcla_propios_y_openlibrary_sin_duplicar(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/libros", FakeResponse([
            {"titulo": "Dune", "autor": "Frank Herbert", "portada": None},
            {"titulo": "Dune", "autor": "Frank Herbert", "portada": None},
        ]))
        mock_requests.add("GET", "openlibrary.org", FakeResponse({"docs": [
            {"title": "Dune", "author_name": ["Frank Herbert"], "cover_i": 1},
            {"title": "Dune Messiah", "author_name": ["Frank Herbert"], "first_publish_year": 1969, "cover_i": 2},
            {"title": ""},
        ]}))
        r = client.get("/libros/buscar?q=dune", headers=auth_headers)
        assert r.status_code == 200
        res = r.json()["resultados"]
        assert [(x["titulo"], x["origen"]) for x in res] == [
            ("Dune", "mis_libros"), ("Dune Messiah", "openlibrary")]
        assert res[1]["portada"] == "https://covers.openlibrary.org/b/id/2-M.jpg"

    def test_si_openlibrary_falla_quedan_los_propios(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/libros", FakeResponse([{"titulo": "Dune", "autor": None, "portada": None}]))

        def cae(url, **kw):
            raise RuntimeError("sin red")
        mock_requests.add("GET", "openlibrary.org", cae)
        r = client.get("/libros/buscar?q=dune", headers=auth_headers)
        assert [x["titulo"] for x in r.json()["resultados"]] == ["Dune"]

    def test_query_corta_rechazada(self, client, auth_headers):
        assert client.get("/libros/buscar?q=d", headers=auth_headers).status_code == 422

    def test_comodines_no_llegan_al_ilike(self, client, auth_headers, mock_requests):
        client.get("/libros/buscar?q=a*%25b", headers=auth_headers)
        url = mock_requests.called("GET", "/rest/v1/libros")[0][1]
        assert "titulo=ilike.*a" in url and "%25" not in url.split("ilike.")[1].split("&")[0]

"""Tests de la checklist de ideas de la zona de desarrollo (docs/ZONA_DEV.md).

Lo que se fija aquí es sobre todo lo que hace que una idea apuntada siga sirviendo dentro
de tres meses: que se pueda guardar con solo el título, que editar el estado no borre el
porqué, y que nada de lo que se escribe llegue crudo a la URL de Supabase.
"""
import pytest

from conftest import FakeResponse


IDEA = {
    "id":          "11111111-2222-3333-4444-555555555555",
    "titulo":      "Que la zona dev diga qué migraciones faltan",
    "porque":      "una migración estuvo un mes sin aplicar y rompió dos cosas",
    "por_donde":   "comparar supabase/migrations con lo que responde Supabase",
    "esfuerzo":    2,
    "area":        "backend",
    "estado":      "pendiente",
    "creada":      "2026-09-09T10:00:00Z",
    "actualizada": "2026-09-09T10:00:00Z",
}


class TestLeer:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/ideas").status_code == 401

    def test_devuelve_la_lista(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas_dev", FakeResponse([IDEA]))
        cuerpo = client.get("/dev/ideas", headers=auth_headers).json()
        assert cuerpo["ideas"][0]["titulo"] == IDEA["titulo"]

    def test_no_toca_la_tabla_de_las_notas_por_voz(self, client, auth_headers, mock_requests):
        """`ideas` es la bandeja de las notas dictadas; `ideas_dev` la lista de trabajo.
        Compartir tabla habría mezclado dos cosas que no se parecen en nada."""
        client.get("/dev/ideas", headers=auth_headers)
        pedidas = [c[1] for c in mock_requests.called("GET", "/rest/v1/ideas")]
        assert all("ideas_dev" in u for u in pedidas)

    def test_un_error_de_supabase_no_filtra_su_texto(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/ideas_dev", FakeResponse(None, 500, "secreto interno"))
        r = client.get("/dev/ideas", headers=auth_headers)
        assert r.status_code == 502
        assert "secreto interno" not in r.text


class TestCrear:
    def test_basta_con_el_titulo(self, client, auth_headers, mock_requests):
        """La idea que hay que rellenar entera para poder guardarla no se guarda."""
        mock_requests.add("POST", "/rest/v1/ideas_dev", FakeResponse([IDEA]))
        r = client.post("/dev/ideas", headers=auth_headers, json={"titulo": "probar algo"})
        assert r.status_code == 200
        fila = mock_requests.called("POST", "/rest/v1/ideas_dev")[0][2]["json"][0]
        assert fila["titulo"] == "probar algo"
        assert fila["estado"] == "pendiente"

    def test_guarda_el_porque_y_el_esfuerzo(self, client, auth_headers, mock_requests):
        mock_requests.add("POST", "/rest/v1/ideas_dev", FakeResponse([IDEA]))
        client.post("/dev/ideas", headers=auth_headers,
                    json={"titulo": "x", "porque": "porque sí", "esfuerzo": 3, "area": "frontend"})
        fila = mock_requests.called("POST", "/rest/v1/ideas_dev")[0][2]["json"][0]
        assert fila["porque"] == "porque sí"
        assert fila["esfuerzo"] == 3

    @pytest.mark.parametrize("cuerpo", [
        {},                                   # sin título
        {"titulo": ""},                       # título vacío
        {"titulo": "x", "esfuerzo": 4},       # el esfuerzo es ●, ●● o ●●●
        {"titulo": "x", "esfuerzo": 0},
        {"titulo": "x", "estado": "casi"},    # estado fuera del check de la tabla
        {"titulo": "x" * 201},
    ])
    def test_lo_que_no_cabe_en_la_tabla_se_rechaza(self, client, auth_headers, cuerpo):
        """El check de la migración y la validación aquí dicen lo mismo a propósito: si
        solo lo dijera la tabla, el error llegaría como un 502 sin explicación."""
        assert client.post("/dev/ideas", headers=auth_headers, json=cuerpo).status_code == 422

    def test_un_titulo_de_solo_espacios_se_rechaza(self, client, auth_headers):
        r = client.post("/dev/ideas", headers=auth_headers, json={"titulo": "   "})
        assert r.status_code == 400

    def test_requiere_jwt(self, client):
        assert client.post("/dev/ideas", json={"titulo": "x"}).status_code == 401


class TestEditar:
    def test_solo_escribe_lo_que_viene(self, client, auth_headers, mock_requests):
        """Marcar una idea como hecha no puede borrar el porqué que se escribió en su día."""
        mock_requests.add("PATCH", "/rest/v1/ideas_dev", FakeResponse([{**IDEA, "estado": "hecha"}]))
        client.patch(f"/dev/ideas/{IDEA['id']}", headers=auth_headers, json={"estado": "hecha"})
        cambios = mock_requests.called("PATCH", "/rest/v1/ideas_dev")[0][2]["json"]
        assert cambios["estado"] == "hecha"
        assert set(cambios) == {"estado", "actualizada"}

    def test_sin_cambios_se_rechaza(self, client, auth_headers):
        r = client.patch(f"/dev/ideas/{IDEA['id']}", headers=auth_headers, json={})
        assert r.status_code == 400

    def test_una_idea_que_no_existe_da_404(self, client, auth_headers, mock_requests):
        mock_requests.add("PATCH", "/rest/v1/ideas_dev", FakeResponse([]))
        r = client.patch(f"/dev/ideas/{IDEA['id']}", headers=auth_headers, json={"estado": "hecha"})
        assert r.status_code == 404

    def test_el_id_tiene_que_ser_un_uuid(self, client, auth_headers):
        """El id se interpola en la URL de Supabase (invariante 6)."""
        r = client.patch("/dev/ideas/no-es-uuid", headers=auth_headers, json={"estado": "hecha"})
        assert r.status_code == 422

    def test_requiere_jwt(self, client):
        assert client.patch(f"/dev/ideas/{IDEA['id']}", json={"estado": "hecha"}).status_code == 401


class TestBorrar:
    def test_borra(self, client, auth_headers, mock_requests):
        assert client.delete(f"/dev/ideas/{IDEA['id']}", headers=auth_headers).json() == {"ok": True}
        assert mock_requests.called("DELETE", "/rest/v1/ideas_dev")

    def test_el_id_tiene_que_ser_un_uuid(self, client, auth_headers):
        assert client.delete("/dev/ideas/todas", headers=auth_headers).status_code == 422

    def test_requiere_jwt(self, client):
        assert client.delete(f"/dev/ideas/{IDEA['id']}").status_code == 401

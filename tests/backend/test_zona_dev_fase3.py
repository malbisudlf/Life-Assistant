"""Tests de la fase 3 de la zona de desarrollo: qué pasó.

Lo que se fija aquí es lo que se rompería sin darse cuenta:

- que la línea del día mezcle las seis fuentes **en orden** y por la hora local, no por la
  UTC que guardan las tablas (media noche de eventos aparecería en el día que no es);
- que una tabla que no responde se DIGA, en vez de parecer un día tranquilo — que es el
  único error que estas pantallas no se pueden permitir;
- que una ingesta del reloj no tape el día entero con sus cien filas;
- que las etapas de treinta jobs se pidan en UNA consulta y no en treinta;
- y que una regla silenciada aparezca aunque lleve semanas sin mandar nada, que es
  justamente el caso por el que existe esa tabla.
"""
import pytest

from conftest import FakeResponse

import main


def _titulos(cuerpo):
    return [e["titulo"] for e in cuerpo["eventos"]]


class TestLinea:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/linea").status_code == 401

    def test_rechaza_un_dia_que_no_es_fecha(self, client, auth_headers):
        assert client.get("/dev/linea?dia=ayer", headers=auth_headers).status_code == 400
        assert client.get("/dev/linea?dia=2026-13-40", headers=auth_headers).status_code == 400

    def test_mezcla_las_fuentes_por_hora(self, client, auth_headers, mock_requests):
        """El orden ES la pestaña: sin él son las mismas seis tablas de siempre."""
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([
            {"id": "l1", "created_at": "2026-09-12T09:00:00Z", "level": "ERROR",
             "source": "main", "message": "Supabase devolvió 409\nTraceback…",
             "context": {"peticion": "POST /health/ingest"}},
        ]))
        mock_requests.add("GET", "/rest/v1/jarvis_recordatorios", FakeResponse([
            {"id": "a1", "texto": "Sal ya", "regla": "salida", "prioridad": 2,
             "enviado_at": "2026-09-12T08:00:00Z", "util": None},
        ]))
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([
            {"id": "j1", "status": "failed", "dedupe_key": "alud-3", "attempt": 1,
             "payload": {"accion": "encargo"}, "created_at": "2026-09-12T10:00:00Z"},
        ]))
        cuerpo = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()

        assert _titulos(cuerpo) == ["Aviso · salida", "ERROR · main", "Job encargo · failed"]
        assert cuerpo["total"] == 3
        assert cuerpo["sin_leer"] == []

    def test_el_registro_solo_lleva_la_primera_linea(self, client, auth_headers, mock_requests):
        """Un traceback entero dentro de una línea de tiempo la hace ilegible."""
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([
            {"id": "l1", "created_at": "2026-09-12T09:00:00Z", "level": "ERROR",
             "source": "main", "message": "Reventó\nTraceback (most recent call last):\n  ...",
             "context": {"peticion": "GET /brief"}},
        ]))
        evento = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()["eventos"][0]
        assert evento["detalle"] == "Reventó"
        assert evento["extra"] == "GET /brief"
        assert evento["tono"] == "red"

    def test_una_tabla_caida_se_dice_en_vez_de_parecer_un_dia_tranquilo(
            self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(None, 500))
        cuerpo = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()
        assert cuerpo["sin_leer"] == ["registro"]
        assert cuerpo["eventos"] == []

    def test_la_ingesta_se_agrupa_por_envio(self, client, auth_headers, mock_requests):
        """Cien filas de un mismo envío son UN evento: "llegó algo, de quién y cuándo"."""
        filas = [{"metric_date": "2026-09-11", "metric_name": f"m{i}", "fuente": "watch",
                  "created_at": f"2026-09-12T07:30:0{i}Z"} for i in range(5)]
        filas.append({"metric_date": "2026-09-11", "metric_name": "pasos", "fuente": "atajo",
                      "created_at": "2026-09-12T21:00:00Z"})
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(filas))
        cuerpo = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()

        assert _titulos(cuerpo) == ["Ingesta de salud · watch", "Ingesta de salud · atajo"]
        assert cuerpo["eventos"][0]["detalle"] == "5 métricas · día 2026-09-11"
        # La hora del grupo es la de la PRIMERA fila: es cuando llegó el envío.
        assert cuerpo["eventos"][0]["cuando"] == "2026-09-12T07:30:00Z"

    def test_la_ventana_va_en_hora_local(self, client, auth_headers, mock_requests):
        """En UTC, los eventos de la noche caerían en el día siguiente."""
        client.get("/dev/linea?dia=2026-09-12", headers=auth_headers)
        params = mock_requests.called("GET", "/rest/v1/app_logs")[0][2]["params"]
        # Madrid en septiembre va dos horas por delante: el día empieza a las 22:00 UTC
        # del día anterior.
        assert "created_at.gte.2026-09-11T22:00:00+00:00" in params["and"]
        assert "created_at.lt.2026-09-12T22:00:00+00:00" in params["and"]

    def test_el_intervalo_va_en_un_solo_parametro(self, client, auth_headers, mock_requests):
        """Dos `created_at` en el mismo diccionario se pisan, y la consulta se traería
        desde la fecha hasta hoy."""
        client.get("/dev/linea?dia=2026-09-12", headers=auth_headers)
        params = mock_requests.called("GET", "/rest/v1/jobs")[0][2]["params"]
        assert "created_at" not in params
        assert params["and"].startswith("(created_at.gte.")

    def test_recorta_por_el_principio(self, client, auth_headers, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "LINEA_MAX", 2)
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([
            {"id": f"l{i}", "created_at": f"2026-09-12T0{i}:00:00Z", "level": "WARNING",
             "source": "main", "message": f"n{i}", "context": {}} for i in range(4)
        ]))
        cuerpo = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()
        assert cuerpo["recortado"] is True
        assert cuerpo["total"] == 4
        assert [e["detalle"] for e in cuerpo["eventos"]] == ["n2", "n3"]

    def test_una_fila_sin_hora_se_cuenta_pero_no_se_coloca(self, client, auth_headers,
                                                           mock_requests):
        mock_requests.add("GET", "/rest/v1/jarvis_recordatorios", FakeResponse([
            {"id": "a1", "texto": "x", "regla": "r", "enviado_at": None, "util": None},
        ]))
        cuerpo = client.get("/dev/linea?dia=2026-09-12", headers=auth_headers).json()
        assert cuerpo["eventos"] == []
        assert cuerpo["sin_hora"] == 1


class TestJobs:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/jobs").status_code == 401

    def test_limite_acotado(self, client, auth_headers):
        assert client.get("/dev/jobs?limite=0", headers=auth_headers).status_code == 400
        assert client.get("/dev/jobs?limite=500", headers=auth_headers).status_code == 400

    def test_las_etapas_van_repartidas_y_en_una_sola_consulta(self, client, auth_headers,
                                                              mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([
            {"id": "j1", "status": "failed", "claimed_by": "pc", "attempt": 1,
             "dedupe_key": "d1", "payload": {}, "created_at": "2026-09-12T10:00:00Z"},
            {"id": "j2", "status": "done", "claimed_by": "pc", "attempt": 0,
             "dedupe_key": "d2", "payload": {}, "created_at": "2026-09-12T09:00:00Z"},
        ]))
        mock_requests.add("GET", "/rest/v1/job_events", FakeResponse([
            {"job_id": "j1", "stage": "abriendo", "message": "", "created_at": "2026-09-12T10:01:00Z"},
            {"job_id": "j2", "stage": "listo", "message": "", "created_at": "2026-09-12T09:01:00Z"},
        ]))
        cuerpo = client.get("/dev/jobs", headers=auth_headers).json()

        assert [e["stage"] for e in cuerpo["jobs"][0]["etapas"]] == ["abriendo"]
        assert [e["stage"] for e in cuerpo["jobs"][1]["etapas"]] == ["listo"]
        llamadas = mock_requests.called("GET", "/rest/v1/job_events")
        assert len(llamadas) == 1
        assert llamadas[0][2]["params"]["job_id"] == "in.(j1,j2)"

    def test_sin_jobs_no_pregunta_por_sus_etapas(self, client, auth_headers, mock_requests):
        client.get("/dev/jobs", headers=auth_headers)
        assert mock_requests.called("GET", "/rest/v1/job_events") == []

    def test_dice_cuanto_lleva_callado_cada_agente(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/pc_agents", FakeResponse([
            {"agent_id": "pc", "status": "online", "hostname": "torre", "version": "1",
             "last_seen_at": "1999-01-01T00:00:00Z"},
        ]))
        cuerpo = client.get("/dev/jobs", headers=auth_headers).json()
        assert cuerpo["agentes"][0]["silencio_segundos"] > 0
        # El mismo umbral que /agents/{id}: con dos, la pantalla se contradiría sola.
        assert cuerpo["timeout_segundos"] == 60

    def test_una_fecha_rara_no_vale_como_vivo(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/pc_agents", FakeResponse([
            {"agent_id": "pc", "status": "online", "last_seen_at": "cuando sea"},
        ]))
        cuerpo = client.get("/dev/jobs", headers=auth_headers).json()
        assert cuerpo["agentes"][0]["silencio_segundos"] is None

    def test_una_tabla_caida_es_null_y_no_una_lista_vacia(self, client, auth_headers,
                                                          mock_requests):
        """"No hay jobs" y "no sé si hay jobs" no se pueden pintar igual."""
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse(None, 500))
        cuerpo = client.get("/dev/jobs", headers=auth_headers).json()
        assert cuerpo["jobs"] is None
        assert cuerpo["agentes"] == []


class TestAvisos:
    def test_requiere_jwt(self, client):
        assert client.get("/dev/avisos").status_code == 401

    def test_dias_acotados(self, client, auth_headers):
        assert client.get("/dev/avisos?dias=0", headers=auth_headers).status_code == 400
        assert client.get("/dev/avisos?dias=400", headers=auth_headers).status_code == 400

    def test_cuenta_los_votos_de_cada_regla(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "/rest/v1/jarvis_recordatorios", FakeResponse([
            {"id": "1", "texto": "a", "regla": "salida", "enviado_at": "2026-09-12T08:00:00Z",
             "util": True},
            {"id": "2", "texto": "b", "regla": "salida", "enviado_at": "2026-09-11T08:00:00Z",
             "util": False},
            {"id": "3", "texto": "c", "regla": "salida", "enviado_at": "2026-09-10T08:00:00Z",
             "util": None},
        ]))
        reglas = client.get("/dev/avisos", headers=auth_headers).json()["reglas"]
        assert reglas[0] == {
            "regla": "salida", "enviados": 3, "utiles": 1, "no_utiles": 1, "sin_votar": 1,
            "ultimo": "2026-09-12T08:00:00Z", "silenciada": False,
            "silenciada_desde": None, "no_utiles_seguidos": None,
        }

    def test_una_regla_silenciada_sale_aunque_lleve_semanas_callada(
            self, client, auth_headers, mock_requests):
        """Es EL caso: está callada justamente porque se silenció, así que no tiene
        avisos que contar y aun así es lo único que hay que ver."""
        mock_requests.add("GET", "/rest/v1/avisos_reglas", FakeResponse([
            {"regla": "reloj", "silenciada": True, "no_utiles": 3,
             "silenciada_desde": "2026-09-01T00:00:00Z"},
        ]))
        reglas = client.get("/dev/avisos", headers=auth_headers).json()["reglas"]
        assert [r["regla"] for r in reglas] == ["reloj"]
        assert reglas[0]["silenciada"] is True
        assert reglas[0]["enviados"] == 0

    def test_sin_poder_leer_nada_no_se_inventa_una_lista(self, client, auth_headers,
                                                         mock_requests):
        mock_requests.add("GET", "/rest/v1/jarvis_recordatorios", FakeResponse(None, 500))
        mock_requests.add("GET", "/rest/v1/avisos_reglas", FakeResponse(None, 500))
        cuerpo = client.get("/dev/avisos", headers=auth_headers).json()
        assert cuerpo["reglas"] is None
        assert cuerpo["enviados"] is None

    def test_trae_el_presupuesto_del_dia(self, client, auth_headers, mock_requests):
        cuerpo = client.get("/dev/avisos", headers=auth_headers).json()
        assert cuerpo["presupuesto"]["tope"] == main.AVISOS_MAX_DIA
        assert cuerpo["canal"] in ("movil", "correo")


@pytest.mark.parametrize("ruta", ["/dev/linea", "/dev/jobs", "/dev/avisos"])
def test_ninguna_de_estas_pantallas_escribe_nada(client, auth_headers, mock_requests, ruta):
    """La fase 3 es de mirar. Lo que toca (reintentar un job) ya tiene su endpoint."""
    client.get(ruta, headers=auth_headers)
    assert [c for c in mock_requests.calls if c[0] != "GET"] == []

"""Tests de herramientas de Jarvis sin cobertura hasta ahora: las que tocan trabajos
encolados, el parte de la noche, el calendario, las ideas y el registro de errores.

Lo que se comprueba no es lo que ya prueban los endpoints que envuelven (`retry_job`,
`get_logs`, `toggle_sleep_exclude`...) sino la validación PROPIA de cada envoltorio —el
id que no tiene forma de UUID, el límite que se acota, la fecha que no existe— y que un
fallo de Supabase no se disfraza de "no hay nada", que es lo que haría que Jarvis dijera
tranquilamente que un job no existe cuando en realidad no se ha podido preguntar.
"""
import pytest

import main
from conftest import FakeResponse

JOB_ID = "123e4567-e89b-12d3-a456-426614174000"


class TestJobsHerramienta:
    """`jobs`: los últimos encolados para el PC, para que Jarvis pueda contarlos."""

    def test_el_limite_se_acota_por_arriba(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        main._j_jobs(limite=999)
        url = mock_requests.called("GET", "/rest/v1/jobs")[0][1]
        assert "limit=20" in url

    def test_el_limite_se_acota_por_abajo(self, mock_requests):
        # 0 es "sin decir nada" (cae al valor por defecto): para forzar el suelo hace
        # falta un valor negativo de verdad.
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        main._j_jobs(limite=-3)
        url = mock_requests.called("GET", "/rest/v1/jobs")[0][1]
        assert "limit=1" in url

    def test_traduce_los_campos_al_castellano(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([
            {"id": "j1", "status": "failed", "payload": {"accion": "encargo"},
             "attempt": 2, "claimed_by": "w1", "created_at": "2026-08-17T09:00:00Z"},
        ]))
        r = main._j_jobs()
        assert r["jobs"][0] == {"id": "j1", "estado": "failed", "accion": "encargo",
                                "intento": 2, "creado": "2026-08-17T09:00:00Z"}

    def test_si_falla_supabase_no_finge_que_no_hay_jobs(self, mock_requests):
        """Una lista vacía y "no se pudo preguntar" no son la misma respuesta: la
        primera dice que todo va bien."""
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse({}, 500))
        with pytest.raises(main.HTTPException):
            main._j_jobs()


class TestReintentarJobHerramienta:
    """`reintentar_job`: el trabajo lo hace `retry_job` (ya probado en test_jobs.py); lo
    que se comprueba aquí es la validación de ESTE envoltorio, que decide si llega a
    llamarlo y con qué worker."""

    def test_un_id_sin_forma_de_uuid_no_llega_a_preguntar(self, mock_requests):
        r = main._j_reintentar_job("el último que falló")
        assert r["ok"] is False
        assert not mock_requests.called("GET", "/rest/v1/jobs")

    def test_no_existe_ningun_job_con_ese_id(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs", FakeResponse([]))
        r = main._j_reintentar_job(JOB_ID)
        assert r["ok"] is False and "ningún job" in r["motivo"]

    def test_solo_se_reintenta_lo_que_ha_fallado(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs",
                          FakeResponse([{"status": "pending", "claimed_by": "w1"}]))
        r = main._j_reintentar_job(JOB_ID)
        assert r["ok"] is False and "pending" in r["motivo"]

    def test_un_job_sin_reclamar_no_tiene_a_quien_devolverselo(self, mock_requests):
        """Si nadie lo reclamó, `worker` viene vacío y no pasa el patrón de id seguro:
        no hay agente al que reasignárselo."""
        mock_requests.add("GET", "/rest/v1/jobs",
                          FakeResponse([{"status": "failed", "claimed_by": None}]))
        r = main._j_reintentar_job(JOB_ID)
        assert r["ok"] is False and "ningún agente" in r["motivo"]

    def test_si_es_elegible_delega_en_retry_job(self, monkeypatch, mock_requests):
        mock_requests.add("GET", "/rest/v1/jobs",
                          FakeResponse([{"status": "failed", "claimed_by": "w1"}]))
        llamado = {}

        def _retry_job(job_id, body, credentials=None):
            llamado["job_id"] = job_id
            llamado["worker_id"] = body.worker_id
            return {"job": {"attempt": 2}}

        monkeypatch.setattr(main, "retry_job", _retry_job)
        r = main._j_reintentar_job(JOB_ID)
        assert r["ok"] is True and r["intento"] == 2
        assert llamado == {"job_id": JOB_ID, "worker_id": "w1"}

    def test_reintentar_despierta_al_agente(self, monkeypatch, mock_requests):
        """Un job reintentado vuelve a `pending`: sin despertar al agente, con el PC
        encendido nadie lo recogía hasta el siguiente arranque."""
        mock_requests.add("GET", "/rest/v1/jobs",
                          FakeResponse([{"status": "failed", "claimed_by": "w1"}]))
        monkeypatch.setattr(main, "retry_job",
                            lambda job_id, body, credentials=None: {"job": {"attempt": 2}})
        main._j_reintentar_job(JOB_ID)
        assert main._wol_pending is True and main._agent_relaunch_pending is True


class TestAnularNocheHerramienta:
    """`anular_noche`: alterna si una noche cuenta para las puntuaciones de sueño."""

    def test_una_fecha_mal_formada_no_llega_a_supabase(self, mock_requests):
        assert main._j_anular_noche("ayer")["ok"] is False
        assert not mock_requests.called("GET", "health_metrics")

    def test_anula_una_noche_que_contaba(self, mock_requests):
        mock_requests.add("GET", "health_metrics", FakeResponse([{"extra": {}}]))
        mock_requests.add("PATCH", "health_metrics", FakeResponse([], 204))
        r = main._j_anular_noche("2026-08-17")
        assert r == {"ok": True, "fecha": "2026-08-17", "anulada": True}

    def test_repetirlo_la_devuelve(self, mock_requests):
        """Es un interruptor, no un borrado: la misma llamada dos veces vuelve al
        punto de partida."""
        mock_requests.add("GET", "health_metrics",
                          FakeResponse([{"extra": {"excluded": True}}]))
        mock_requests.add("PATCH", "health_metrics", FakeResponse([], 204))
        r = main._j_anular_noche("2026-08-17")
        assert r["anulada"] is False

    def test_sin_datos_de_sueno_esa_noche_no_hay_nada_que_anular(self, mock_requests):
        mock_requests.add("GET", "health_metrics", FakeResponse([]))
        with pytest.raises(main.HTTPException) as exc:
            main._j_anular_noche("2026-08-17")
        assert exc.value.status_code == 404


class TestTurnoDeNocheHerramienta:
    """`turno_de_noche`: el parte contado a Jarvis, recortado para que quepa en un turno
    (el texto exacto se lee en el dashboard o en Borradores, no aquí)."""

    def test_una_fecha_mal_formada_se_rechaza_sin_preguntar(self, mock_requests):
        r = main._j_turno_de_noche("17 de agosto")
        assert "error" in r
        assert not mock_requests.called("GET", "noche_partes")

    def test_todavia_no_hay_ningun_parte(self, mock_requests):
        mock_requests.add("GET", "noche_partes", FakeResponse([]))
        r = main._j_turno_de_noche()
        assert r == {"hay_parte": False, "frase": "Todavía no hay ningún parte de la noche."}

    def test_el_parte_trae_los_items_recortados_y_por_que_no_hay_borrador(self, mock_requests):
        mock_requests.add("GET", "noche_partes", FakeResponse([
            {"fecha": "2026-08-17", "creado_at": "2026-08-17T03:00:00Z", "resumen": {}},
        ]))
        mock_requests.add("GET", "noche_items", FakeResponse([
            {"id": "i1", "area": "correo", "titulo": "Factura de la luz", "estado": "hecho",
             "detalle": "x" * 400,
             "datos": {"de": "luz@ejemplo.com", "categoria": "responder", "borrador": True}},
            {"id": "i2", "area": "correo", "titulo": "Newsletter", "estado": "hecho",
             "detalle": "nada que hacer",
             "datos": {"no_responder": "automatico"}},
        ]))
        r = main._j_turno_de_noche("2026-08-17")
        assert r["hay_parte"] is True
        # El detalle viaja dentro del prompt: se paga por token y se recorta a 300.
        assert len(r["items"][0]["detalle"]) == 300
        assert r["items"][0]["borrador"] is True
        assert r["items"][1]["sin_borrador_porque"] == main._MOTIVOS_NO_RESPONDER["automatico"]

    def test_si_falla_supabase_no_dice_que_no_hay_parte(self, mock_requests):
        """Que la consulta falle y que no haya parte son cosas distintas: la primera no
        puede vestirse de la segunda, o Jarvis diría que la noche no dejó nada cuando en
        realidad no se ha podido leer."""
        mock_requests.add("GET", "noche_partes", FakeResponse({}, 500))
        with pytest.raises(main.HTTPException):
            main._j_turno_de_noche("2026-08-17")


class TestBorrarEventoHerramienta:
    """`borrar_evento`: solo se llega aquí desde /jarvis/ejecutar, ya confirmado."""

    def test_exige_un_id(self, mock_requests):
        assert main._j_borrar_evento("")["ok"] is False

    def test_borra_el_evento_en_outlook(self, graph_token, mock_requests):
        mock_requests.add("DELETE", "graph.microsoft.com", FakeResponse({}, 204))
        r = main._j_borrar_evento("evento-1")
        assert r == {"ok": True, "id": "evento-1"}

    def test_sin_sesion_de_graph_dice_por_que(self, monkeypatch):
        monkeypatch.setattr(main, "get_valid_token", lambda: None)
        r = main._j_borrar_evento("evento-1")
        assert r["ok"] is False and "autenticado" in r["motivo"]


class TestBorrarIdeaHerramienta:
    """`borrar_idea`: solo se llega aquí desde /jarvis/ejecutar, ya confirmado."""

    def test_un_id_sin_forma_de_uuid_no_llega_a_supabase(self, mock_requests):
        r = main._j_borrar_idea("la última que dije")
        assert r["ok"] is False
        assert not mock_requests.called("DELETE", "/rest/v1/ideas")

    def test_borra_con_un_id_valido(self, mock_requests):
        idea_id = str(main.uuid.uuid4())
        mock_requests.add("DELETE", "/rest/v1/ideas", FakeResponse([], 204))
        assert main._j_borrar_idea(idea_id) == {"ok": True, "id": idea_id}


class TestErroresHerramienta:
    """`errores`: la otra mitad de "cómo estás" — no si algo responde, si algo ha
    fallado (`app_logs`)."""

    def test_dias_y_limite_se_acotan(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([]))
        main._j_errores(dias=999, limite=999)
        url = mock_requests.called("GET", "/rest/v1/app_logs")[0][1]
        assert "limit=30" in url

    def test_el_mensaje_largo_se_recorta(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse([
            {"created_at": "2026-08-17T09:00:00Z", "level": "ERROR", "source": "brief",
             "message": "x" * 400},
        ]))
        r = main._j_errores()
        assert len(r["entradas"][0]["mensaje"]) == 300

    def test_si_falla_supabase_no_dice_que_no_hay_errores(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse({}, 500))
        with pytest.raises(main.HTTPException):
            main._j_errores()


class TestEnviarResumenHerramienta:
    """`enviar_resumen`: manda el correo del día ya, sin esperar al disparador — y sin
    mirar si ya salió, que es justo lo que la distingue de `/brief/send` a secas."""

    def test_manda_el_correo_aunque_ya_hubiera_salido_hoy(self, monkeypatch):
        enviados = []
        monkeypatch.setattr(main, "construir_brief", lambda: {"fecha": "2026-08-17"})
        monkeypatch.setattr(main, "render_brief_texto", lambda d: "cuerpo del día")
        monkeypatch.setattr(main, "enviar_correo",
                            lambda asunto, cuerpo, adjunto=None:
                            enviados.append((asunto, cuerpo, adjunto)))
        r = main._j_enviar_resumen()
        assert r["ok"] is True and r["fecha"] == "2026-08-17"
        assert [e[:2] for e in enviados] == [("Life Assistant — datos del 2026-08-17",
                                              "cuerpo del día")]
        # El mismo correo que sale cada mañana, con su JSON adjunto (#244).
        assert enviados[0][2][0] == "brief-2026-08-17.json"

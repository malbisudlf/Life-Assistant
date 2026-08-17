"""Tests de los recordatorios: lo único que hace que Jarvis hable sin que le hablen.

Lo que se comprueba es que un aviso no se pierda ni se duplique, que es donde fallan
estas cosas: la reserva tiene que ser atómica (como el INSERT del resumen diario) y un
fallo de SMTP no puede consumir el recordatorio.
"""
import uuid
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse

CABECERA = {"X-Auth-Token": "ha-poll-token"}


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(main, "enviar_correo", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


def _manana(hora="09:00"):
    dia = (datetime.now(main.LOCAL_TZ) + timedelta(days=1)).date().isoformat()
    return dia, hora


class TestApuntarRecordatorio:
    def test_guarda_uno_para_manana(self, mock_requests):
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([{"id": "r-1"}]))
        dia, hora = _manana()
        r = main._j_recordarme("llamar al dentista", dia, hora)
        assert r["ok"] is True
        guardado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert guardado["texto"] == "llamar al dentista"
        # Se guarda en UTC: la hora local es de quien la dice, no de la base de datos.
        assert guardado["cuando"].endswith("+00:00")

    def test_rechaza_una_hora_que_ya_paso(self, mock_requests):
        r = main._j_recordarme("tarde", "2020-01-01", "09:00")
        assert r["ok"] is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_rechaza_una_fecha_que_no_existe(self, mock_requests):
        assert main._j_recordarme("algo", "2030-02-30", "09:00")["ok"] is False

    def test_rechaza_formatos_raros(self, mock_requests):
        assert main._j_recordarme("algo", "mañana", "por la tarde")["ok"] is False

    def test_exige_saber_de_que_avisar(self, mock_requests):
        dia, hora = _manana()
        assert main._j_recordarme("   ", dia, hora)["ok"] is False

    def test_no_deja_acumular_infinitos(self, mock_requests):
        pendientes = [{"id": f"r-{i}"} for i in range(main.RECORDATORIOS_MAX + 1)]
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse(pendientes))
        dia, hora = _manana()
        assert main._j_recordarme("uno más", dia, hora)["ok"] is False

    def test_cancelar_exige_un_id_de_verdad(self, mock_requests):
        assert main._j_cancelar_recordatorio("el del dentista")["ok"] is False
        assert not mock_requests.called("DELETE", "jarvis_recordatorios")


class TestDespacho:
    def _vencido(self, mock_requests, texto="llamar al dentista"):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T09:00:00+00:00",
            "texto": texto,
        }]))

    def test_manda_el_correo_y_lo_marca(self, mock_requests, correos):
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))
        assert main._despachar_recordatorios() == {"recordatorios": 1}
        assert "llamar al dentista" in correos[0][0]
        reserva = mock_requests.called("PATCH", "jarvis_recordatorios")[0][2]["json"]
        # `enviado_at` es lo que cuenta el presupuesto diario: sin él no se sabe
        # cuántos avisos han salido hoy, solo cuáles estaban programados para hoy.
        assert reserva["enviado"] is True and reserva["enviado_at"]

    def test_si_otro_tick_se_lo_llevo_no_se_manda_dos_veces(self, mock_requests, correos):
        """La reserva ES la pregunta: un PATCH condicional que no devuelve fila significa
        que otro se adelantó. Con un GET previo, dos ticks solapados mandan dos correos."""
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([]))
        assert main._despachar_recordatorios() == {"recordatorios": 0}
        assert correos == []

    def test_si_el_correo_falla_se_libera_para_reintentarlo(self, mock_requests, monkeypatch):
        """Un fallo transitorio de SMTP no puede consumir el recordatorio."""
        self._vencido(mock_requests)
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

        def _revienta(asunto, cuerpo):
            raise RuntimeError("SMTP caído")
        monkeypatch.setattr(main, "enviar_correo", _revienta)

        assert main._despachar_recordatorios() == {"recordatorios": 0}
        liberado = mock_requests.called("PATCH", "jarvis_recordatorios")[-1][2]["json"]
        # Se limpia también `enviado_at`: si se quedara puesto, el aviso liberado
        # seguiría contando contra el presupuesto de hoy sin haberse entregado.
        assert liberado == {"enviado": False, "enviado_at": None}

    def test_un_fallo_de_supabase_no_revienta(self, mock_requests, correos):
        """El tick existe sobre todo para el resumen diario: esto no puede tumbarlo."""
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([], 500))
        assert main._despachar_recordatorios() == {"recordatorios": 0}


class TestElRelojEsElTickDeHa:
    def test_el_tick_despacha_aunque_no_sea_la_hora_del_resumen(
            self, client, mock_requests, correos, monkeypatch):
        """Antes de la hora tope el tick no manda el resumen, pero sí los recordatorios:
        es el único reloj que hay, porque Fly escala a cero."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 8, 7, 0, tzinfo=main.LOCAL_TZ))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T05:00:00+00:00",
            "texto": "tomar la pastilla",
        }]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

        r = client.post("/ha/brief-tick", headers=CABECERA)
        assert r.status_code == 200
        assert r.json() == {"enviado": False, "motivo": "aún no es la hora tope",
                            "recordatorios": 1}
        assert len(correos) == 1

    def test_sigue_haciendo_falta_el_token(self, client):
        assert client.post("/ha/brief-tick").status_code == 403


class TestAvisoDeReloj:
    """El dato de una noche sin medir no se recupera: el aviso vale antes de dormir o
    no vale. Y no puede regañar por algo que no ha pasado — de ahí que un día sin datos
    de ninguna fuente no dispare nada.
    """

    NOCHE = datetime(2026, 8, 8, 22, 0, tzinfo=main.LOCAL_TZ)

    def _salud(self, mock_requests, filas):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(filas))

    def _fila(self, nombre, valor, dias, hoy=None):
        fecha = (hoy or self.NOCHE.date()) - timedelta(days=dias)
        return {"metric_date": fecha.isoformat(), "metric_name": nombre,
                "value": valor, "extra": {}}

    @pytest.fixture(autouse=True)
    def _de_noche(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: self.NOCHE)

    def test_avisa_si_hoy_no_hay_rastro_del_reloj(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._avisar_reloj_si_toca() == {"aviso_reloj": True}
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert "Hoy no hay ni un dato del reloj" in apuntado["texto"]
        assert "cargador" in apuntado["texto"]

    def test_no_avisa_si_lo_llevas_puesto(self, mock_requests):
        self._salud(mock_requests, [
            self._fila("heart_rate", 70, 0), self._fila("step_count", 9000, 0),
            self._fila("sleep_analysis", 7.2, 1), self._fila("heart_rate", 70, 1),
        ])
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_un_dia_sin_datos_de_nada_no_dispara_el_aviso(self, mock_requests):
        """No llegó nada: puede ser el reloj o la sincronización, y no se sabe cuál."""
        self._salud(mock_requests, [])
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_avisa_por_la_racha_de_noches_aunque_hoy_lo_lleves_de_dia(self, mock_requests):
        self._salud(mock_requests, [
            self._fila("heart_rate", 70, 0),                       # hoy: puesto de día
            *[self._fila("step_count", 9000, i) for i in range(4)],  # datos todos los días
            self._fila("sleep_analysis", 7.2, 3),                  # la última noche medida
        ])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._avisar_reloj_si_toca() == {"aviso_reloj": True}
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "2 noches sin medir" in texto

    def test_antes_de_la_hora_no_hace_nada_ni_consulta(self, mock_requests, monkeypatch):
        """El tick pasa cada 5 min: fuera de la ventana tiene que salir sin tocar nada."""
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 8, 12, 0, tzinfo=main.LOCAL_TZ))
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("GET", "/rest/v1/health_metrics")

    def test_el_id_es_el_del_dia_para_que_el_segundo_choque(self, mock_requests):
        """La idempotencia es el 409 contra la clave primaria, como en brief_envios: dos
        ticks solapados generan el MISMO id y solo uno entra."""
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._avisar_reloj_si_toca()
        primero = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["id"]
        assert primero == main._uuid_aviso_reloj("2026-08-08")
        assert primero != main._uuid_aviso_reloj("2026-08-09")

    def test_un_409_no_es_un_error(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse(None, 409, "duplicate key"))
        assert main._avisar_reloj_si_toca() == {}

    def test_dos_veces_en_el_mismo_dia_no_repiten_la_consulta(self, mock_requests):
        self._salud(mock_requests, [self._fila("step_count", 9000, 0)])
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._avisar_reloj_si_toca()
        main._avisar_reloj_si_toca()
        assert len(mock_requests.called("GET", "/rest/v1/health_metrics")) == 1

    def test_un_fallo_leyendo_la_salud_no_tumba_el_tick(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(None, 500, "boom"))
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_apagado_por_env_no_hace_nada(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "RELOJ_AVISO", False)
        assert main._avisar_reloj_si_toca() == {}
        assert not mock_requests.called("GET", "/rest/v1/health_metrics")


class TestVigilanteDeIngesta:
    """El fallo que más veces ha ocurrido en este proyecto es el silencio: el 409 del
    upsert, el 400 del envoltorio y el JWT caducado del agente dejaron de traer datos sin
    que nada diera error. Lo que se comprueba aquí es que la AUSENCIA se note, y que no
    se confunda con "no he podido preguntar".
    """

    # Antes de la hora tope del resumen: lo que se prueba es el vigilante, no el correo.
    AHORA = datetime(2026, 8, 8, 8, 0, tzinfo=main.LOCAL_TZ)

    @pytest.fixture(autouse=True)
    def _encendido(self, monkeypatch):
        monkeypatch.setattr(main, "INGESTA_VIGILAR", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)

    def _ultima_escritura(self, mock_requests, horas):
        cuando = datetime.now(main.timezone.utc) - timedelta(hours=horas)
        mock_requests.add("GET", "/rest/v1/health_metrics",
                          FakeResponse([{"created_at": cuando.isoformat()}]))

    def test_calla_si_la_ingesta_va_al_dia(self, mock_requests, caplog):
        self._ultima_escritura(mock_requests, 3)
        assert main._vigilar_ingesta() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_un_dia_de_silencio_se_registra(self, mock_requests, caplog):
        """Por logger.error a propósito: así sale en app_logs, en el panel de ajustes y en
        el diagnóstico de Jarvis sin ningún camino nuevo."""
        self._ultima_escritura(mock_requests, 30)
        with caplog.at_level("ERROR"):
            assert main._vigilar_ingesta() == {"ingesta_silenciosa_horas": 30}
        assert "sin recibir un solo dato de salud" in caplog.text
        # Todavía no hay correo: un registro basta mientras se pueda mirar el panel.
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_dos_dias_de_silencio_ya_son_un_correo(self, mock_requests):
        self._ultima_escritura(mock_requests, 50)
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_ingesta()
        assert r == {"ingesta_silenciosa_horas": 50, "aviso_ingesta": True}
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert "50 h sin que llegue ningún dato" in apuntado["texto"]

    def test_el_id_es_el_del_dia_para_que_el_segundo_choque(self, mock_requests):
        """Misma idempotencia que el aviso del reloj: el 409 contra la clave primaria es
        lo que impide un correo por hora."""
        self._ultima_escritura(mock_requests, 50)
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._vigilar_ingesta()
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert apuntado["id"] == str(uuid.uuid5(
            uuid.NAMESPACE_URL, "life-assistant:ingesta-muda:2026-08-08"))

    def test_un_409_no_es_un_error(self, mock_requests):
        self._ultima_escritura(mock_requests, 50)
        mock_requests.add("POST", "jarvis_recordatorios",
                          FakeResponse(None, 409, "duplicate key"))
        assert main._vigilar_ingesta() == {"ingesta_silenciosa_horas": 50}

    def test_si_no_se_puede_preguntar_se_calla(self, mock_requests):
        """"No he podido preguntar" no es "no ha llegado nada" — la moraleja del agente
        PC, aquí por el otro lado: avisar con esto sería acusar a la ingesta de un fallo
        de Supabase."""
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse(None, 500, "boom"))
        assert main._vigilar_ingesta() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_la_tabla_vacia_no_es_silencio(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/health_metrics", FakeResponse([]))
        assert main._vigilar_ingesta() == {}

    def test_solo_consulta_una_vez_por_hora(self, mock_requests):
        """El tick pasa cada 5 minutos: sin este freno serían ~300 consultas al día."""
        self._ultima_escritura(mock_requests, 3)
        main._vigilar_ingesta()
        main._vigilar_ingesta()
        assert len(mock_requests.called("GET", "/rest/v1/health_metrics")) == 1

    def test_apagado_no_cuesta_ni_una_consulta(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "INGESTA_VIGILAR", False)
        assert main._vigilar_ingesta() == {}
        assert not mock_requests.called("GET", "/rest/v1/health_metrics")

    def test_un_fallo_inesperado_no_tumba_el_tick(self, monkeypatch):
        def _explota():
            raise RuntimeError("boom")
        monkeypatch.setattr(main, "_vigilar_ingesta", _explota)
        assert main._vigilar_ingesta_seguro() == {}

    def test_cuelga_del_tick_de_ha(self, client, mock_requests, correos):
        self._ultima_escritura(mock_requests, 30)
        r = client.post("/ha/brief-tick", headers=CABECERA)
        assert r.status_code == 200
        assert r.json()["ingesta_silenciosa_horas"] == 30


class TestAvisosAlMovil:
    """El correo es el único canal que llega con la web cerrada, y se lee cuando se abre
    el buzón: un "ponte el reloj" de las 21:30 leído al día siguiente no es un aviso.

    Lo que se comprueba aquí es que el canal nuevo no pierda nada — encender un camino
    nuevo y perder por el medio lo que antes llegaba es la avería típica de esto.
    """

    CABECERA = {"X-Auth-Token": "ha-poll-token"}

    def _sondear(self, client):
        return client.get("/ha/avisos-pending", headers=self.CABECERA).json()["avisos"]

    def test_sin_nadie_recogiendo_todo_sigue_yendo_por_correo(self, correos):
        """Antes de instalar el YAML nadie sondea: el canal se enciende solo cuando
        alguien empieza a recoger, sin configurar nada."""
        assert main._notificar("hola", "qué tal") == "correo"
        assert len(correos) == 1

    def test_con_ha_recogiendo_va_al_movil(self, client, correos):
        self._sondear(client)                       # HA se declara vivo sondeando
        assert main._notificar("⏰ pastilla", "tomar la pastilla") == "movil"
        assert correos == [], "no se manda por los dos canales a la vez"
        avisos = self._sondear(client)
        assert avisos == [{"titulo": "⏰ pastilla", "texto": "tomar la pastilla",
                           "voz": False, "id": ""}]

    def test_la_cola_se_vacia_al_recogerla(self, client):
        self._sondear(client)
        main._notificar("uno", "uno")
        assert len(self._sondear(client)) == 1
        assert self._sondear(client) == [], "recoger consume, como el WOL"

    def test_si_ha_deja_de_sondear_se_vuelve_al_correo(self, client, correos, monkeypatch):
        self._sondear(client)
        monkeypatch.setattr(main, "_ultimo_sondeo_avisos",
                            main.time.time() - main.AVISO_MOVIL_VIVO - 1)
        assert main._notificar("hola", "qué tal") == "correo"
        assert len(correos) == 1

    def test_lo_que_el_movil_no_recoge_se_rescata_por_correo(self, client, correos):
        """El fallo realista: el YAML a medias — HA sigue con su tick y nadie lee la
        cola. Sin rescate dejarían de llegar avisos que antes llegaban, en silencio."""
        self._sondear(client)
        main._notificar("⏰ pastilla", "tomar la pastilla")
        main._avisos_movil[0]["puesto"] -= main.AVISO_MOVIL_RESCATE + 1
        assert main._rescatar_avisos() == {"avisos_rescatados": 1}
        assert correos == [("⏰ pastilla", "tomar la pastilla")]
        assert main._avisos_movil == []

    def test_un_aviso_reciente_no_se_rescata_todavia(self, client, correos):
        self._sondear(client)
        main._notificar("⏰ pastilla", "tomar la pastilla")
        assert main._rescatar_avisos() == {}
        assert correos == []

    def test_si_el_rescate_falla_el_aviso_se_queda_en_la_cola(self, client, monkeypatch):
        """Tirarlo aquí sería justo lo que este rescate viene a evitar."""
        self._sondear(client)
        main._notificar("⏰ pastilla", "tomar la pastilla")
        main._avisos_movil[0]["puesto"] -= main.AVISO_MOVIL_RESCATE + 1
        def _revienta(asunto, cuerpo, adjunto=None):
            raise RuntimeError("SMTP caído")
        monkeypatch.setattr(main, "enviar_correo", _revienta)
        assert main._rescatar_avisos() == {}
        assert len(main._avisos_movil) == 1

    def test_el_recordatorio_vencido_sale_por_el_canal_vivo(self, client, mock_requests,
                                                            correos):
        self._sondear(client)
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T05:00:00+00:00",
            "texto": "tomar la pastilla",
        }]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))
        assert main._despachar_recordatorios() == {"recordatorios": 1}
        assert correos == [], "va al móvil, no al correo"
        assert len(self._sondear(client)) == 1

    def test_un_fallo_del_correo_sigue_liberando_la_reserva(self, mock_requests,
                                                            monkeypatch):
        """Sin móvil vivo el aviso va por correo, y ahí sigue valiendo la regla de
        siempre: un SMTP caído no puede consumir el recordatorio."""
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{
            "id": "11111111-2222-3333-4444-555555555555",
            "cuando": "2026-08-08T05:00:00+00:00", "texto": "tomar la pastilla",
        }]))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))
        def _revienta(asunto, cuerpo, adjunto=None):
            raise RuntimeError("SMTP caído")
        monkeypatch.setattr(main, "enviar_correo", _revienta)
        assert main._despachar_recordatorios() == {"recordatorios": 0}
        liberado = [c for c in mock_requests.called("PATCH", "jarvis_recordatorios")
                    if c[2]["json"].get("enviado") is False]
        assert len(liberado) == 1

    def test_la_cola_esta_acotada(self, client, correos):
        """Es memoria de una VM de 1 GB: llena, se cae al correo en vez de crecer."""
        self._sondear(client)
        for i in range(main.AVISOS_MOVIL_MAX):
            main._notificar(f"aviso {i}", "texto")
        assert main._notificar("uno más", "texto") == "correo"

    def test_apagado_por_env_no_usa_el_movil(self, client, correos, monkeypatch):
        self._sondear(client)
        monkeypatch.setattr(main, "AVISOS_MOVIL", False)
        assert main._notificar("hola", "qué tal") == "correo"

    def test_sondear_sigue_necesitando_el_token(self, client):
        assert client.get("/ha/avisos-pending").status_code == 403

    def test_el_estado_dice_por_donde_van_los_avisos(self, client, auth_headers):
        antes = client.get("/avisos/estado", headers=auth_headers).json()
        assert antes["canal"] == "correo" and antes["sondeo_hace_segundos"] is None
        self._sondear(client)
        despues = client.get("/avisos/estado", headers=auth_headers).json()
        assert despues["canal"] == "movil"
        assert despues["sondeo_hace_segundos"] == 0

    def test_el_estado_es_del_usuario(self, client):
        assert client.get("/avisos/estado").status_code == 401

    def test_la_prueba_usa_el_canal_que_toque(self, client, auth_headers, correos):
        r = client.post("/avisos/probar", headers=auth_headers)
        assert r.json() == {"ok": True, "canal": "correo"}
        self._sondear(client)
        r = client.post("/avisos/probar", headers=auth_headers)
        assert r.json()["canal"] == "movil"
        assert len(self._sondear(client)) == 1


class TestVigilanteDelSistema:
    """El vigilante general: el de la ingesta mira que sigan entrando datos de salud,
    este mira si el sistema se rompe por cualquier otro sitio.

    Las tres averías grandes del proyecto fueron la misma historia —algo dejó de
    funcionar y nada lo dijo— y se descubrieron por casualidad semanas después. Lo que
    se comprueba aquí es que la pregunta se haga sola, que lo reparado se CUENTE (un
    parche silencioso esconde la avería) y que "no he podido preguntar" siga sin
    disfrazarse de "todo va bien".
    """

    AHORA = datetime(2026, 8, 17, 8, 0, tzinfo=main.LOCAL_TZ)
    HOY   = "2026-08-17"

    @pytest.fixture(autouse=True)
    def _encendido(self, monkeypatch):
        monkeypatch.setattr(main, "VIGILANTE", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)
        monkeypatch.setattr(main, "RUTINA_FIRE_URL", "https://api.anthropic.com/fire")
        monkeypatch.setattr(main, "RUTINA_FIRE_TOKEN", "sk-ant-oat01-x")

    def _errores(self, mock_requests, veces, origen="POST /health/ingest"):
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(
            [{"level": "ERROR", "source": origen, "created_at": f"2026-08-17T0{i}:00:00Z"}
             for i in range(veces)]))

    def test_calla_si_no_hay_nada_roto(self, mock_requests):
        self._errores(mock_requests, 0)
        assert main._vigilar_sistema() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_un_error_suelto_no_es_una_averia(self, mock_requests):
        """Uno es la vida; lo que se repite es lo que está roto."""
        self._errores(mock_requests, 2)
        assert main._vigilar_sistema() == {}

    def test_errores_repetidos_avisan_diciendo_el_origen(self, mock_requests):
        self._errores(mock_requests, 4)
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_sistema()
        assert r["vigilante_averias"] == 1 and r["aviso_vigilante"] is True
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "4 errores en POST /health/ingest" in texto

    def test_si_no_se_puede_leer_el_registro_se_calla(self, mock_requests):
        """La regla de siempre: "no he podido preguntar" no es "está roto"."""
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(None, 500, "boom"))
        assert main._vigilar_sistema() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_el_aviso_es_uno_al_dia(self, mock_requests):
        """Mismo uuid5 del día contra la clave primaria que el resto de avisos."""
        self._errores(mock_requests, 4)
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._vigilar_sistema()
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert apuntado["id"] == str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"life-assistant:vigilante:{self.HOY}"))

    def test_solo_mira_una_vez_por_hora(self, mock_requests):
        self._errores(mock_requests, 0)
        main._vigilar_sistema()
        main._vigilar_sistema()
        assert len(mock_requests.called("GET", "/rest/v1/app_logs")) == 1

    def test_apagado_no_cuesta_ni_una_consulta(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "VIGILANTE", False)
        assert main._vigilar_sistema() == {}
        assert not mock_requests.called("GET", "/rest/v1/app_logs")

    # ── La única reparación de la lista blanca ────────────────────────────────
    def test_reintenta_el_disparo_de_la_rutina_y_lo_cuenta(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_rutina_ultimo_fallo",
                            {"fecha": self.HOY, "ok": False, "pausada": False, "motivo": "500"})
        self._errores(mock_requests, 0)
        mock_requests.add("POST", "api.anthropic.com/fire", FakeResponse({}, 200))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_sistema()
        assert r["vigilante_reparadas"] == 1
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "lo he relanzado y ha entrado" in texto
        assert main._rutina_ultimo_fallo is None

    def test_una_rutina_pausada_no_se_reintenta(self, mock_requests, monkeypatch):
        """Pausada es una decisión del usuario, no una avería. Reintentar contra algo que
        se apagó a propósito es la forma más rápida de que el aviso deje de leerse."""
        monkeypatch.setattr(main, "_rutina_ultimo_fallo",
                            {"fecha": self.HOY, "ok": False, "pausada": True,
                             "motivo": "Routine is paused."})
        self._errores(mock_requests, 0)
        assert main._vigilar_sistema() == {}
        assert not mock_requests.called("POST", "api.anthropic.com/fire")

    def test_si_el_reintento_falla_se_dice(self, mock_requests, monkeypatch):
        """Lanzar algo no es comprobar que funciona: el 2xx del trigger ES la
        verificación, y sin él la avería sigue viva y se cuenta como tal."""
        monkeypatch.setattr(main, "_rutina_ultimo_fallo",
                            {"fecha": self.HOY, "ok": False, "pausada": False, "motivo": "500"})
        self._errores(mock_requests, 0)
        mock_requests.add("POST", "api.anthropic.com/fire", FakeResponse(None, 500, "boom"))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        r = main._vigilar_sistema()
        assert r["vigilante_averias"] == 1 and "vigilante_reparadas" in r
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "sigue fallando" in texto

    def test_lo_reparado_dice_cuantas_veces_lleva(self, mock_requests, monkeypatch):
        """Un fallo que se repara solo todos los días no está arreglado, está escondido."""
        monkeypatch.setattr(main, "_rutina_ultimo_fallo",
                            {"fecha": self.HOY, "ok": False, "pausada": False, "motivo": "500"})
        self._errores(mock_requests, 0)
        mock_requests.add("GET", "/rest/v1/vigilante_estado",
                          FakeResponse([{"clave": "reparado:rutina", "veces": 4,
                                         "primera_vez": "2026-08-13T09:00:00Z", "issue_url": None}]))
        mock_requests.add("POST", "api.anthropic.com/fire", FakeResponse({}, 200))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._vigilar_sistema()
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "van 5 veces" in texto and "el arreglo no está aquí" in texto

    def test_un_fallo_de_la_memoria_no_calla_el_aviso(self, mock_requests):
        """Perder las cifras es peor que no perderlas, y muchísimo menos peor que
        callarse: si la migración no está aplicada, el vigilante sigue avisando."""
        self._errores(mock_requests, 4)
        mock_requests.add("GET", "/rest/v1/vigilante_estado",
                          FakeResponse(None, 404, "no existe la tabla"))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._vigilar_sistema()["aviso_vigilante"] is True

    def test_no_puede_tumbar_el_tick(self, mock_requests, monkeypatch):
        monkeypatch.setattr(main, "_vigilar_sistema",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert main._vigilar_sistema_seguro() == {}


class TestVigilanteAbreIssues:
    """Lo que necesita un cambio de código no se puede arreglar desde el backend: de las
    averías reales del proyecto, ninguna se podía. Abrir el issue es la única forma de
    "arreglarse a sí mismo" que cubre ese caso, y por el camino revisable."""

    @pytest.fixture(autouse=True)
    def _repo(self, monkeypatch):
        monkeypatch.setattr(main, "VIGILANTE_ISSUES", True)
        monkeypatch.setattr(main, "JARVIS_REPO", "malbisudlf/Life-Assistant")

    def _servidor(self, monkeypatch, herramientas, resultado=None):
        monkeypatch.setattr(main, "_mcp_config", lambda: {"github": {"url": "https://x", "token": "t"}})
        llamadas = []

        def _rpc(servidor, metodo, params):
            llamadas.append((servidor, metodo, params))
            if metodo == "tools/list":
                return {"tools": [{"name": n} for n in herramientas]}
            return resultado or {"content": [{"type": "text", "text":
                                 "https://github.com/malbisudlf/Life-Assistant/issues/70"}]}

        monkeypatch.setattr(main, "_mcp_rpc", _rpc)
        return llamadas

    def test_abre_el_issue_y_devuelve_la_url(self, monkeypatch):
        llamadas = self._servidor(monkeypatch, ["get_me", "create_issue"])
        url = main._vigilante_abrir_issue("[vigilante] algo", "cuerpo")
        assert url == "https://github.com/malbisudlf/Life-Assistant/issues/70"
        args = [c for c in llamadas if c[1] == "tools/call"][0][2]["arguments"]
        assert args == {"owner": "malbisudlf", "repo": "Life-Assistant",
                        "title": "[vigilante] algo", "body": "cuerpo"}

    def test_conoce_la_otra_forma_del_servidor_de_github(self, monkeypatch):
        """`issue_write` pide `method`; `create_issue` no. Se buscan por nombre EXACTO:
        mandar argumentos inventados a una herramienta que ESCRIBE es peor que no abrir
        el issue."""
        llamadas = self._servidor(monkeypatch, ["issue_write"])
        main._vigilante_abrir_issue("t", "c")
        args = [c for c in llamadas if c[1] == "tools/call"][0][2]["arguments"]
        assert args["method"] == "create"

    def test_sin_herramienta_conocida_no_inventa_nada(self, monkeypatch):
        self._servidor(monkeypatch, ["add_issue_comment", "search_issues"])
        assert main._vigilante_abrir_issue("t", "c") == ""

    def test_sin_repo_configurado_no_se_intenta(self, monkeypatch):
        monkeypatch.setattr(main, "JARVIS_REPO", "")
        assert main._vigilante_abrir_issue("t", "c") == ""

    def test_un_servidor_que_revienta_no_tumba_el_vigilante(self, monkeypatch):
        monkeypatch.setattr(main, "_mcp_config", lambda: {"github": {}})
        monkeypatch.setattr(main, "_mcp_rpc",
                            lambda *a: (_ for _ in ()).throw(RuntimeError("caído")))
        assert main._vigilante_abrir_issue("t", "c") == ""

    def test_el_issue_solo_se_abre_la_primera_vez(self, mock_requests, monkeypatch):
        """Uno por día del mismo fallo convertiría el repo en el ruido del que este
        vigilante viene a salvarte."""
        monkeypatch.setattr(main, "VIGILANTE", True)
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: datetime(2026, 8, 17, 8, 0, tzinfo=main.LOCAL_TZ))
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(
            [{"level": "ERROR", "source": "POST /x", "created_at": "2026-08-17T01:00:00Z"}] * 3))
        mock_requests.add("GET", "/rest/v1/vigilante_estado", FakeResponse(
            [{"clave": "errores:POST /x", "veces": 2, "primera_vez": "2026-08-15T09:00:00Z",
              "issue_url": "https://github.com/malbisudlf/Life-Assistant/issues/70"}]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        abiertos = []
        monkeypatch.setattr(main, "_vigilante_abrir_issue",
                            lambda t, c: abiertos.append(t) or "url")
        main._vigilar_sistema()
        assert abiertos == []
        texto = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]["texto"]
        assert "Lleva 3 avisos desde el 2026-08-15" in texto


class TestGobiernoDeAvisos:
    """Las tres piezas que impiden que un asistente proactivo se vuelva ruido.

    No fallan de golpe: cada regla parece razonable por separado hasta que un día se
    dejan de leer todos los avisos a la vez, buenos incluidos. Lo que se comprueba aquí
    es que los avisos COMPITAN (presupuesto), que una regla ignorada se calle SOLA y de
    forma visible (utilidad), y que no se repita lo mismo mientras nada cambia (memoria).
    """

    AHORA = datetime(2026, 8, 17, 20, 0, tzinfo=main.LOCAL_TZ)

    @pytest.fixture(autouse=True)
    def _reloj(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)

    def _pendientes(self, mock_requests, filas):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse(filas))
        mock_requests.add("PATCH", "jarvis_recordatorios", FakeResponse([{"id": "x"}]))

    def _fila(self, n=1, regla="proactivo", prioridad=main.PRIO_NORMAL, **extra):
        return {"id": f"1111111{n}-2222-3333-4444-555555555555", "texto": f"aviso {n}",
                "cuando": "2026-08-17T05:00:00+00:00", "regla": regla,
                "prioridad": prioridad, **extra}

    # ── 0.1 Presupuesto ───────────────────────────────────────────────────────
    def test_lo_que_no_entra_en_el_tope_se_pospone_no_se_pierde(self, mock_requests,
                                                                correos, monkeypatch):
        monkeypatch.setattr(main, "AVISOS_MAX_DIA", 0)
        self._pendientes(mock_requests, [self._fila()])
        r = main._despachar_recordatorios()
        assert r == {"recordatorios": 0, "avisos_pospuestos": 1}
        assert correos == []
        # Pospuesto a mañana por la mañana, no marcado como enviado.
        pospuesto = mock_requests.called("PATCH", "jarvis_recordatorios")[-1][2]["json"]
        assert pospuesto["cuando"].startswith("2026-08-18T06:30")   # 08:30 local

    def test_lo_urgente_se_salta_el_presupuesto(self, mock_requests, correos, monkeypatch):
        """Si el tope pudiera con lo urgente, el aviso que más corre sería el primero en
        caerse — justo al revés de lo que tiene que pasar."""
        monkeypatch.setattr(main, "AVISOS_MAX_DIA", 0)
        self._pendientes(mock_requests, [self._fila(prioridad=main.PRIO_URGENTE)])
        assert main._despachar_recordatorios() == {"recordatorios": 1}
        assert len(correos) == 1

    def test_lo_que_pediste_tu_no_se_gobierna(self, mock_requests, correos, monkeypatch):
        """Un recordatorio sin regla lo pediste tú: obedecer al presupuesto antes que a
        quien lo puso sería el sitio equivocado."""
        monkeypatch.setattr(main, "AVISOS_MAX_DIA", 0)
        self._pendientes(mock_requests, [self._fila(regla=None)])
        assert main._despachar_recordatorios() == {"recordatorios": 1}

    def test_un_aviso_caducado_no_se_manda(self, mock_requests, correos):
        """Un "sal ya" pasada la hora de salir no es un aviso tarde: es una mentira, y
        enseña a no fiarse del canal."""
        self._pendientes(mock_requests, [self._fila(caduca="2026-08-17T05:30:00+00:00")])
        assert main._despachar_recordatorios() == {"recordatorios": 0,
                                                   "avisos_caducados": 1}
        assert correos == []

    def test_se_gasta_en_lo_que_mas_corre(self, mock_requests):
        """El orden es por prioridad, no por cuándo se apuntó."""
        self._pendientes(mock_requests, [])
        main._despachar_recordatorios()
        url = mock_requests.called("GET", "jarvis_recordatorios")[0][1]
        assert "order=prioridad.asc" in url

    # ── 0.2 Utilidad ──────────────────────────────────────────────────────────
    def test_marcar_no_util_tres_veces_silencia_la_regla(self, mock_requests, monkeypatch):
        mock_requests.add("GET", "avisos_reglas", FakeResponse([{"utiles": 0, "no_utiles": 2,
                                                                "silenciada": False}]))
        mock_requests.add("POST", "avisos_reglas", FakeResponse([], 201))
        main._valorar_regla("proactivo", False)
        guardado = mock_requests.called("POST", "avisos_reglas")[0][2]["json"]
        assert guardado["no_utiles"] == 3 and guardado["silenciada"] is True

    def test_un_util_pone_el_contador_a_cero(self, mock_requests):
        """Se busca una regla que ha dejado de valer, no una que tuvo un mal día."""
        mock_requests.add("GET", "avisos_reglas", FakeResponse([{"utiles": 1, "no_utiles": 2,
                                                                "silenciada": False}]))
        mock_requests.add("POST", "avisos_reglas", FakeResponse([], 201))
        main._valorar_regla("proactivo", True)
        guardado = mock_requests.called("POST", "avisos_reglas")[0][2]["json"]
        assert guardado["no_utiles"] == 0 and "silenciada" not in guardado

    def test_silenciar_se_dice(self, mock_requests):
        """Una regla apagada en silencio es el error que persigue el resto del proyecto."""
        mock_requests.add("GET", "avisos_reglas", FakeResponse([{"no_utiles": 2}]))
        mock_requests.add("POST", "avisos_reglas", FakeResponse([], 201))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._valorar_regla("reloj", False)
        apuntado = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert "He dejado de avisarte de 'reloj'" in apuntado["texto"]
        assert apuntado["regla"] == "", "el aviso del silencio no puede silenciarse a sí mismo"

    def test_una_regla_silenciada_no_apunta_nada(self, mock_requests):
        mock_requests.add("GET", "avisos_reglas", FakeResponse([{"silenciada": True}]))
        assert main._apuntar_aviso("proactivo", "algo") is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_si_no_se_puede_preguntar_se_habla(self, mock_requests):
        """Ante la duda se habla: callar por un fallo de Supabase es el lado que no se
        recupera."""
        mock_requests.add("GET", "avisos_reglas", FakeResponse(None, 500, "boom"))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._apuntar_aviso("proactivo", "algo") is True

    def test_valorar_exige_credencial(self, client):
        r = client.post("/avisos/11111111-2222-3333-4444-555555555555/util",
                        json={"util": True})
        assert r.status_code == 403

    def test_ha_puede_valorar_con_su_token(self, client, mock_requests):
        mock_requests.add("PATCH", "jarvis_recordatorios",
                          FakeResponse([{"id": "x", "regla": None}]))
        r = client.post("/avisos/11111111-2222-3333-4444-555555555555/util",
                        json={"util": True}, headers={"X-Auth-Token": "ha-poll-token"})
        assert r.status_code == 200 and r.json()["ok"] is True

    # ── 0.3 Memoria ───────────────────────────────────────────────────────────
    def test_no_repite_la_misma_situacion(self, mock_requests):
        """La idempotencia vieja era por día: "llevas 3 días sin entrenar" salía el
        jueves, el viernes y el sábado, y solo el primero informaba de algo."""
        mock_requests.add("GET", "avisos_reglas", FakeResponse([]))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{"id": "ya"}]))
        assert main._apuntar_aviso("proactivo", "algo", huella="sin_entrenar:3") is False
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_una_situacion_nueva_si_habla(self, mock_requests):
        mock_requests.add("GET", "avisos_reglas", FakeResponse([]))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        assert main._apuntar_aviso("proactivo", "algo", huella="sin_entrenar:4") is True

    def test_la_ventana_de_la_memoria_es_por_fecha(self, mock_requests):
        mock_requests.add("GET", "avisos_reglas", FakeResponse([]))
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        main._apuntar_aviso("proactivo", "algo", huella="x")
        url = [c for c in mock_requests.called("GET", "jarvis_recordatorios")
               if "huella=eq" in c[1]][0][1]
        assert "creado=gte." in url

    # ── El canal de voz (1.1) ─────────────────────────────────────────────────
    def test_la_voz_viaja_hasta_ha(self, client, mock_requests):
        """El backend decide QUÉ se oye; por qué altavoz lo decide el YAML de HA, igual
        que con el móvil."""
        client.get("/ha/avisos-pending", headers={"X-Auth-Token": "ha-poll-token"})
        main._notificar("sal ya", "sal en 10 minutos", voz=True, aviso_id="abc")
        avisos = client.get("/ha/avisos-pending",
                            headers={"X-Auth-Token": "ha-poll-token"}).json()["avisos"]
        assert avisos[0]["voz"] is True and avisos[0]["id"] == "abc"

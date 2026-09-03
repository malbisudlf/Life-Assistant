"""Tests de «por qué te dije eso»: la instantánea que acompaña a cada aviso.

Lo que importa aquí no es el contenido de la instantánea —eso es aritmética de cada
regla— sino la propiedad que la hace segura: **guardar el porqué NUNCA puede impedir el
aviso**. Es una función de diagnóstico colgando del camino crítico del sistema, y por eso
vive en una tabla aparte y sus fallos solo se registran.
"""
from datetime import datetime, timedelta

import pytest

import main
from conftest import FakeResponse


class TestMotivoAlApuntar:
    @pytest.fixture(autouse=True)
    def _entorno(self, mock_requests):
        # avisos_reglas no se registra: el router devuelve [] por defecto (= no
        # silenciada) y la PRIMERA ruta registrada gana, así que dejarla aquí impediría
        # que un test pusiera la suya.
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _motivos(self, mock_requests):
        return [c[2]["json"] for c in mock_requests.called("POST", "avisos_motivos")]

    def test_se_guarda_con_el_id_del_aviso(self, mock_requests):
        mock_requests.add("POST", "avisos_motivos", FakeResponse([], 201))
        assert main._apuntar_aviso("prueba", "algo", motivo={"media_7d": 62, "media_30d": 55})
        apuntado = [c[2]["json"] for c in mock_requests.called("POST", "jarvis_recordatorios")][0]
        guardado = self._motivos(mock_requests)[0]
        assert guardado["aviso_id"] == apuntado["id"]
        assert guardado["regla"] == "prueba"
        assert guardado["datos"]["media_7d"] == 62

    def test_el_aviso_siempre_lleva_id_propio(self, mock_requests):
        """Aunque no se pase: sin id conocido no hay de qué colgar la explicación, y el
        insert va con return=minimal para no pagar una respuesta por aviso."""
        assert main._apuntar_aviso("prueba", "algo")
        apuntado = [c[2]["json"] for c in mock_requests.called("POST", "jarvis_recordatorios")][0]
        assert apuntado["id"]

    def test_sin_motivo_no_se_escribe_nada(self, mock_requests):
        assert main._apuntar_aviso("prueba", "algo")
        assert self._motivos(mock_requests) == []

    def test_si_falla_guardar_el_motivo_el_aviso_sigue_en_pie(self, mock_requests):
        """La migración puede no estar aplicada. Perder la explicación es aceptable;
        perder el aviso, no. Es la razón de que esto viva en otra tabla."""
        mock_requests.add("POST", "avisos_motivos", FakeResponse({"message": "no existe"}, 404))
        assert main._apuntar_aviso("prueba", "algo", motivo={"x": 1}) is True

    def test_un_motivo_enorme_no_revienta(self, mock_requests):
        mock_requests.add("POST", "avisos_motivos", FakeResponse([], 201))
        assert main._apuntar_aviso("prueba", "algo",
                                   motivo={"lista": ["x" * 50 for _ in range(200)]})
        # O va recortado o no va, pero el aviso salió y nadie ha reventado.
        guardado = self._motivos(mock_requests)
        assert not guardado or len(str(guardado[0]["datos"])) <= main.AVISO_MOTIVO_MAX + 200

    def test_una_regla_silenciada_no_guarda_motivo(self, mock_requests):
        mock_requests.add("GET", "avisos_reglas", FakeResponse([{"silenciada": True}]))
        assert main._apuntar_aviso("prueba", "algo", motivo={"x": 1}) is False
        assert self._motivos(mock_requests) == []


class TestEndpointPorque:
    def test_requiere_token(self, client):
        r = client.get(f"/avisos/{main.uuid.uuid4()}/porque")
        assert r.status_code in (401, 403)

    def test_id_invalido_da_422(self, client, auth_headers):
        assert client.get("/avisos/no-es-uuid/porque", headers=auth_headers).status_code == 422

    def test_devuelve_el_aviso_con_sus_numeros(self, client, auth_headers, mock_requests):
        aviso_id = str(main.uuid.uuid4())
        mock_requests.add("GET", "jarvis_recordatorios",
                          FakeResponse([{"id": aviso_id, "texto": "Hoy no fuerces",
                                         "regla": "malestar"}]))
        mock_requests.add("GET", "avisos_motivos",
                          FakeResponse([{"datos": {"fc_reposo": {"media_7d": 62}},
                                         "creado": "2026-09-03T08:00:00Z"}]))
        datos = client.get(f"/avisos/{aviso_id}/porque", headers=auth_headers).json()
        assert datos["aviso"]["regla"] == "malestar"
        assert datos["motivo"]["datos"]["fc_reposo"]["media_7d"] == 62

    def test_un_aviso_sin_motivo_responde_200(self, client, auth_headers, mock_requests):
        """No es un error: los avisos anteriores a esto no tienen explicación, y decir
        404 significaría que el aviso no existe, que es otra cosa."""
        aviso_id = str(main.uuid.uuid4())
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{"id": aviso_id}]))
        mock_requests.add("GET", "avisos_motivos", FakeResponse([]))
        r = client.get(f"/avisos/{aviso_id}/porque", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["motivo"] is None

    def test_sin_la_tabla_todavia_el_aviso_se_sigue_viendo(self, client, auth_headers,
                                                           mock_requests):
        aviso_id = str(main.uuid.uuid4())
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([{"id": aviso_id}]))
        mock_requests.add("GET", "avisos_motivos", FakeResponse({"message": "no existe"}, 404))
        r = client.get(f"/avisos/{aviso_id}/porque", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["motivo"] is None

    def test_un_aviso_que_no_existe_da_404(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        r = client.get(f"/avisos/{main.uuid.uuid4()}/porque", headers=auth_headers)
        assert r.status_code == 404


class TestReglasQueLoRellenan:
    """Las reglas que ya existían tienen que empezar a contar con qué se dispararon."""

    AHORA = datetime(2026, 8, 17, 8, 0, tzinfo=main.LOCAL_TZ)

    @pytest.fixture(autouse=True)
    def _entorno(self, monkeypatch, mock_requests):
        monkeypatch.setattr(main, "REGLAS_PROACTIVAS", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)
        main._reglas_dia.clear()
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))
        mock_requests.add("POST", "avisos_motivos", FakeResponse([], 201))

    def test_la_firma_de_malestar_guarda_sus_tres_pares(self, mock_requests):
        salud = {clave: {"media_7d": m7, "media_30d": m30, "n_7d": 5, "n_30d": 20}
                 for clave, m7, m30 in [("fc_reposo", 62, 55), ("hrv", 31, 44),
                                        ("respiracion", 16.5, 15.0)]}
        assert main._regla_malestar(lambda: salud) == 1
        datos = [c[2]["json"] for c in mock_requests.called("POST", "avisos_motivos")][0]["datos"]
        assert set(datos) == {"fc_reposo", "hrv", "respiracion"}
        assert datos["hrv"]["media_7d"] == 31
        assert datos["hrv"]["media_30d"] == 44
        # El listón contra el que se comparó tiene que ir dentro: mañana puede cambiar.
        assert datos["hrv"]["factor"] == 0.95

    def test_el_hueco_para_entrenar_dice_cuantos_dias_y_que_hueco(self, monkeypatch,
                                                                  mock_requests):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: self.AHORA.replace(hour=main.HORA_REGLAS_NOCHE[0],
                                                       minute=main.HORA_REGLAS_NOCHE[1]))
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": []})
        salud = {"ultimo_entreno": {"dias": main.JARVIS_PROACTIVO_SIN_ENTRENO + 1}}
        assert main._regla_hueco_entreno(lambda: salud) == 1
        datos = [c[2]["json"] for c in mock_requests.called("POST", "avisos_motivos")][0]["datos"]
        assert datos["dias_sin_entrenar"] == main.JARVIS_PROACTIVO_SIN_ENTRENO + 1
        assert datos["listón_dias"] == main.JARVIS_PROACTIVO_SIN_ENTRENO
        assert len(datos["hueco"]) == 2

    def test_sal_ya_guarda_la_hora_que_dio_maps(self, monkeypatch, mock_requests):
        salida = self.AHORA + timedelta(minutes=30)
        monkeypatch.setattr(main, "GOOGLE_MAPS_API_KEY", "maps-key")
        monkeypatch.setattr(main, "get_departure_time",
                            lambda body, credentials=None: {
                                "departure_iso": salida.isoformat(),
                                "departure_time": salida.strftime("%H:%M")})
        ini = self.AHORA + timedelta(hours=1)
        monkeypatch.setattr(main, "get_events", lambda credentials=None: {"events": [{
            "id": "ev1", "title": "cita", "location": "Plaza Mayor", "isAllDay": False,
            "start": ini.astimezone(main.timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": (ini + timedelta(hours=1)).astimezone(main.timezone.utc)
                   .isoformat().replace("+00:00", "Z")}]})
        assert main._regla_sal_ya() == 1
        datos = [c[2]["json"] for c in mock_requests.called("POST", "avisos_motivos")][0]["datos"]
        assert datos["destino"] == "Plaza Mayor"
        assert datos["salida"] == salida.isoformat()


class TestAvisosEnviados:
    """Lo que salió, con su hora. Antes de esto un aviso enviado desaparecía de la vista:
    lo único que quedaba era la notificación del móvil, que se borra."""

    def test_requiere_token(self, client):
        assert client.get("/avisos/enviados").status_code in (401, 403)

    def test_dia_invalido(self, client, auth_headers):
        assert client.get("/avisos/enviados?dia=ayer", headers=auth_headers).status_code == 400
        assert client.get("/avisos/enviados?dia=2026-02-31",
                          headers=auth_headers).status_code == 400

    def test_limite_fuera_de_rango(self, client, auth_headers):
        assert client.get("/avisos/enviados?limite=0", headers=auth_headers).status_code == 400

    def test_devuelve_los_del_dia(self, client, auth_headers, mock_requests):
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([
            {"id": "a1", "texto": "Sal ya", "regla": "salir",
             "enviado_at": "2026-08-17T16:30:00Z", "util": None},
        ]))
        datos = client.get("/avisos/enviados?dia=2026-08-17", headers=auth_headers).json()
        assert datos["dia"] == "2026-08-17"
        assert datos["avisos"][0]["regla"] == "salir"

    def test_la_ventana_se_construye_en_hora_local(self, client, auth_headers,
                                                   mock_requests):
        """La tabla guarda UTC y quien pregunta piensa en local: sin convertir, los avisos
        de la noche saldrían en el día que no es."""
        mock_requests.add("GET", "jarvis_recordatorios", FakeResponse([]))
        client.get("/avisos/enviados?dia=2026-08-17", headers=auth_headers)
        url = mock_requests.called("GET", "jarvis_recordatorios")[0][1]
        # Verano en Madrid: la medianoche local del 17 son las 22:00 UTC del 16.
        assert "2026-08-16T22" in url

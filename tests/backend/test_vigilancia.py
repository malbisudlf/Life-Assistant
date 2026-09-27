"""Tests de `POST /vigilancia/estado`: qué merece un aviso y qué merece una llamada.

Todo lo que se comprueba aquí protege una sola cosa: **que el teléfono siga significando
algo**. Un canal que suena por un parpadeo de red, o que vuelve a sonar cada cinco minutos
por la misma avería, o que te despierta por algo que podía esperar a las siete, se deja de
coger — y con él se va el aviso que sí importaba. Esa es la regla de `docs/LLAMADAS.md` y
estos tests son lo que impide relajarla sin darse cuenta.
"""
import pytest

import main

VIGILANTE = {"X-Auth-Token": "revision-token"}
CENTRALITA = "/api/outbound-call"


@pytest.fixture(autouse=True)
def _configurado(monkeypatch):
    monkeypatch.setattr(main, "REVISION_TOKEN", "revision-token")
    monkeypatch.setattr(main, "TELEFONO_URL", "http://centralita.test:3010")
    monkeypatch.setattr(main, "TELEFONO_EXTENSION", "11410")
    monkeypatch.setattr(main, "VIGILANCIA_FALLOS_LLAMADA", 3)
    # A mediodía: fuera de la franja nocturna salvo que un test diga lo contrario.
    monkeypatch.setattr(main, "_ahora_local",
                        lambda: main.datetime(2026, 9, 21, 12, 0,
                                              tzinfo=main.timezone.utc))


@pytest.fixture
def avisos(monkeypatch):
    """Captura los avisos al móvil sin pasar por la cola ni por el correo."""
    recogidos = []
    monkeypatch.setattr(main, "_notificar",
                        lambda titulo, texto, **kw: recogidos.append((titulo, texto, kw)) or "movil")
    return recogidos


def _cae(client, veces=1, sujeto="home-assistant", **extra):
    for _ in range(veces):
        r = client.post("/vigilancia/estado",
                        json={"sujeto": sujeto, "vivo": False, **extra}, headers=VIGILANTE)
    return r


class TestCuandoSuena:
    def test_un_parpadeo_no_es_una_averia(self, client, mock_requests, avisos):
        """Un sondeo fallido suelto es ruido de red. Ni aviso ni llamada."""
        r = _cae(client, 2)
        assert r.status_code == 200 and r.json()["avisado"] is False
        assert avisos == []
        assert not mock_requests.called("POST", CENTRALITA)

    def test_al_cruzar_el_umbral_avisa_y_llama(self, client, mock_requests, avisos):
        r = _cae(client, 3)
        assert r.json()["avisado"] is True and r.json()["llamado"] is True
        assert len(avisos) == 1 and "home-assistant" in avisos[0][0]

    def test_el_aviso_lleva_botones(self, client, mock_requests, avisos):
        """`REGLA_VIGILANCIA` prometía poder silenciarse sola como cualquier otra regla,
        pero los avisos salían sin `aviso_id` — así que `_acciones_aviso` cortaba en seco
        y no había ni el útil/no útil de por defecto."""
        _cae(client, 3)
        kw = avisos[0][2]
        assert kw["aviso_id"]
        assert mock_requests.called("POST", "jarvis_recordatorios")
        fila = mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]
        assert fila["regla"] == main.REGLA_VIGILANCIA
        assert fila["id"] == kw["aviso_id"]
        acciones = {a["title"] for a in kw["acciones"]}
        assert acciones == {"Útil", "No"}
        llamadas = mock_requests.called("POST", CENTRALITA)
        assert len(llamadas) == 1
        assert llamadas[0][2]["json"]["to"] == "11410"
        # En conversación y no en anuncio: lo que se pedía era poder resolverlo hablando,
        # no que te lean un parte y cuelguen.
        assert llamadas[0][2]["json"]["mode"] == "conversation"

    def test_lo_que_se_dice_y_lo_que_se_sabe_son_cosas_distintas(self, client, mock_requests, avisos):
        """El contexto es para el modelo; el mensaje, para el oído. Mezclarlos hace que
        Jarvis recite por teléfono instrucciones internas."""
        _cae(client, 3, detalle="La sonda REST devolvió 502.")
        cuerpo = mock_requests.called("POST", CENTRALITA)[0][2]["json"]
        assert "runbook" not in cuerpo["message"]
        assert "runbook" in cuerpo["context"]
        assert "502" in cuerpo["context"]

    def test_no_vuelve_a_llamar_por_la_misma_averia(self, client, mock_requests, avisos):
        """Se llama una vez por avería, no una por sondeo."""
        _cae(client, 6)
        assert len(mock_requests.called("POST", CENTRALITA)) == 1
        assert len(avisos) == 1

    def test_sin_centralita_configurada_el_aviso_sale_igual(self, client, mock_requests,
                                                            avisos, monkeypatch):
        """El teléfono es refuerzo, no el único canal: si no está montado, el aviso sale."""
        monkeypatch.setattr(main, "TELEFONO_URL", "")
        monkeypatch.setattr(main, "LLAMADAS", False)
        r = _cae(client, 3)
        assert r.json()["avisado"] is True and r.json()["llamado"] is False
        assert len(avisos) == 1


class TestLaNoche:
    def _de_noche(self, monkeypatch):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: main.datetime(2026, 9, 21, 3, 30,
                                                  tzinfo=main.timezone.utc))

    def test_de_noche_avisa_pero_no_llama(self, client, mock_requests, avisos, monkeypatch):
        self._de_noche(monkeypatch)
        r = _cae(client, 3)
        assert r.json()["avisado"] is True and r.json()["aplazada"] is True
        assert len(avisos) == 1
        assert not mock_requests.called("POST", CENTRALITA)

    def _a_las(self, monkeypatch, hora, minuto=0, dia=21):
        monkeypatch.setattr(main, "_ahora_local",
                            lambda: main.datetime(2026, 9, dia, hora, minuto,
                                                  tzinfo=main.timezone.utc))

    def test_por_la_manana_espera_a_que_te_despiertes(self, client, mock_requests,
                                                      avisos, monkeypatch):
        """Acabada la franja no llama sola: espera a tu señal de despertar. No hay reloj
        que mantener: el primer sondeo después de la señal encuentra la avería viva y
        llama entonces."""
        self._de_noche(monkeypatch)
        _cae(client, 3)
        self._a_las(monkeypatch, 7, 5)
        r = _cae(client, 1)
        assert r.json()["llamado"] is False and r.json()["aplazada"] is True
        assert "despierto" in r.json()["motivo"]
        assert not mock_requests.called("POST", CENTRALITA)

        self._a_las(monkeypatch, 7, 10)
        main._anotar_despierto(main._ahora_local(), "despertar")
        self._a_las(monkeypatch, 7, 15)
        r = _cae(client, 1)
        assert r.json()["llamado"] is True
        assert len(mock_requests.called("POST", CENTRALITA)) == 1
        # Y el aviso no se repite: ya se dio de madrugada.
        assert len(avisos) == 1

    def test_sin_senal_llama_a_la_hora_de_respaldo(self, client, mock_requests, avisos,
                                                    monkeypatch):
        """Un día sin ninguna señal (móvil sin batería, Atajo apagado) no se queda sin
        llamada: a la hora de respaldo se te da por despierto."""
        self._de_noche(monkeypatch)
        _cae(client, 3)
        self._a_las(monkeypatch, 9, 55)
        assert _cae(client, 1).json()["llamado"] is False
        self._a_las(monkeypatch, 10, 0)
        assert _cae(client, 1).json()["llamado"] is True

    def test_el_27_09(self, client, mock_requests, avisos, monkeypatch):
        """Lo que pasó: la web cayó a las 03:30, el vigilante aplazó la llamada por la
        noche y a las 07:00:32 llamó con Mikel dormido. Volvió a las 11:33.

        Con la regla nueva, sin señal de despertar (el túnel estaba caído, así que el
        Atajo no llegaba), la llamada sale a las 10:00 y no a las 07:00."""
        self._a_las(monkeypatch, 3, 30, dia=27)
        _cae(client, 3, sujeto="la web")
        for hora, minuto in ((6, 45), (6, 55), (7, 0), (7, 5), (8, 30), (9, 55)):
            self._a_las(monkeypatch, hora, minuto, dia=27)
            r = _cae(client, 1, sujeto="la web")
            assert r.json()["llamado"] is False, (hora, minuto)
        assert not mock_requests.called("POST", CENTRALITA)
        self._a_las(monkeypatch, 10, 0, dia=27)
        assert _cae(client, 1, sujeto="la web").json()["llamado"] is True
        assert len(mock_requests.called("POST", CENTRALITA)) == 1

    def test_lo_critico_despierta(self, client, mock_requests, avisos, monkeypatch):
        """La única excepción, y su sitio: lo que tiene que despertarte."""
        self._de_noche(monkeypatch)
        r = _cae(client, 3, sujeto="alarmas", critico=True)
        assert r.json()["llamado"] is True
        assert mock_requests.called("POST", CENTRALITA)


class TestLaRecuperacion:
    def test_avisa_de_que_ha_vuelto(self, client, mock_requests, avisos):
        """Sin el «ya está bien» te quedas mirando el móvil sin saber si se arregló."""
        _cae(client, 3)
        r = client.post("/vigilancia/estado",
                        json={"sujeto": "home-assistant", "vivo": True}, headers=VIGILANTE)
        assert r.json()["estado"] == "vivo"
        assert len(avisos) == 2 and "ha vuelto" in avisos[1][0]

    def test_una_recuperacion_silenciosa_no_avisa(self, client, mock_requests, avisos):
        """Si nunca se llegó a avisar, no hay nada que desdecir."""
        _cae(client, 1)
        client.post("/vigilancia/estado",
                    json={"sujeto": "home-assistant", "vivo": True}, headers=VIGILANTE)
        assert avisos == []

    def test_la_siguiente_caida_vuelve_a_llamar(self, client, mock_requests, avisos):
        """Es lo que hace que el contador exista: una avería nueva es una llamada nueva."""
        _cae(client, 3)
        client.post("/vigilancia/estado",
                    json={"sujeto": "home-assistant", "vivo": True}, headers=VIGILANTE)
        _cae(client, 3)
        assert len(mock_requests.called("POST", CENTRALITA)) == 2

    def test_cada_sujeto_cuenta_por_su_cuenta(self, client, mock_requests, avisos):
        _cae(client, 2, sujeto="home-assistant")
        _cae(client, 2, sujeto="web")
        assert not mock_requests.called("POST", CENTRALITA)
        _cae(client, 1, sujeto="web")
        llamadas = mock_requests.called("POST", CENTRALITA)
        assert len(llamadas) == 1 and "web" in llamadas[0][2]["json"]["message"]


class TestLaPuerta:
    def test_sin_token_no_entra(self, client):
        assert client.post("/vigilancia/estado",
                           json={"sujeto": "x", "vivo": False}).status_code == 403

    def test_un_sujeto_vacio_se_rechaza(self, client):
        r = client.post("/vigilancia/estado", json={"sujeto": "  ", "vivo": False},
                        headers=VIGILANTE)
        assert r.status_code == 400

    def test_el_sujeto_se_limpia(self, client, mock_requests, avisos):
        """El sujeto acaba en el texto de un aviso y en el de una llamada: entra acotado."""
        _cae(client, 3, sujeto="web<script>alert(1)</script>")
        assert "<script>" not in avisos[0][1]

"""El aviso que «Hablarlo» se llevaba por delante, y la notificación que sobrevivía a su
propia pregunta.

Dos averías del mismo sitio, las dos del canal del móvil:

1. **Pulsar «Hablarlo» dejaba el aviso vivo y mudo.** La app de Home Assistant descarta la
   notificación en cuanto pulsas CUALQUIER botón, y «Hablarlo» es el único de los tres que
   no decide nada — no toca `estado`, es repetible a propósito. Así que si no cogías la
   llamada, o la cogías y no decidías, el aviso seguía pendiente en la tabla y ya no
   tenías dónde contestarlo: solo reaparecía al descolgar por cualquier otra cosa.

2. **Decidir por otro camino dejaba un botón zombi.** Contestar «Arreglarlo» por teléfono
   o desde el dashboard no retiraba la notificación del móvil, que se quedaba preguntando
   algo ya respondido. No rompía nada —las transiciones son PATCH condicionales— pero un
   botón que no hace nada enseña a desconfiar del canal por el que llegan las averías.

Lo que fija este fichero es que la reposición sea TARDÍA y CONDICIONAL: tarde porque el
momento de pulsar es justo cuando está sonando el teléfono, y condicional porque «¿sigue
pendiente?» es lo único que distingue «no lo cogió» de «lo habló y decidió».
"""
import pytest

from conftest import FakeResponse

import main

UN_UUID = "fa27dab6-f054-5982-bd86-994e5e8b151b"
CABECERA = {"X-Auth-Token": "ha-poll-token"}

_FILA = {"id": UN_UUID, "origen": "vigilante", "issue_numero": 0, "issue_url": "",
         "issue_titulo": "5 errores", "detalle": "5 errores\n· 1× Graph"}


@pytest.fixture
def sin_esperar(monkeypatch):
    """Ejecuta el trabajo diferido en el acto, en vez de a los seis minutos.

    Se sustituye `threading.Timer` y no la espera, porque lo que importa comprobar es QUÉ
    hace el hilo cuando salta, no cuánto duerme. El retraso real es una constante y tiene
    su propia prueba.
    """
    lanzados = []

    class TimerFalso:
        def __init__(self, segundos, funcion):
            self.segundos = segundos
            self.funcion  = funcion
            self.daemon   = False
            self.name     = ""

        def start(self):
            lanzados.append(self.segundos)
            self.funcion()

    monkeypatch.setattr(main.threading, "Timer", TimerFalso)
    return lanzados


class TestReponerTrasHablar:
    def test_si_sigue_pendiente_el_aviso_vuelve_al_movil(self, mock_requests, monkeypatch,
                                                         sin_esperar):
        """El caso que da nombre al fichero: no lo cogiste, o no decidiste."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([_FILA]))
        avisados = []
        monkeypatch.setattr(main, "_notificar",
                            lambda titulo, texto, **kw:
                                avisados.append((titulo, kw.get("aviso_id"),
                                                 kw.get("acciones"))) or "movil")

        main._reponer_tras_hablar("revision", UN_UUID)

        assert len(avisados) == 1, "el aviso tiene que volver"
        titulo, rid, acciones = avisados[0]
        assert "pendiente" in titulo.lower()
        assert rid == UN_UUID, "mismo id: para el móvil es la MISMA notificación"
        # Y vuelve con sus botones, que es el motivo entero de reponerlo: un aviso sin
        # dónde contestar es lo que ya teníamos.
        assert [a["action"] for a in acciones] == [f"LA_ARREGLAR_{UN_UUID}",
                                                   f"LA_NADA_{UN_UUID}",
                                                   f"LA_HABLAR_REV_{UN_UUID}"]

    def test_si_ya_se_decidio_no_repone_nada(self, mock_requests, monkeypatch,
                                             sin_esperar):
        """El caso BUENO: lo hablaste y decidiste. Volver a preguntar sería el error."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([]))
        avisados = []
        monkeypatch.setattr(main, "_notificar",
                            lambda *a, **k: avisados.append(a) or "movil")

        main._reponer_tras_hablar("revision", UN_UUID)

        assert avisados == [], "ya no está pendiente: no se repone"

    def test_el_aviso_de_sesion_tambien_vuelve(self, mock_requests, monkeypatch,
                                               sin_esperar):
        mock_requests.add("GET", "/rest/v1/sesion_avisos",
                          FakeResponse([{"id": UN_UUID, "texto": "he terminado",
                                         "estado": "pendiente"}]))
        avisados = []
        monkeypatch.setattr(main, "_notificar",
                            lambda titulo, texto, **kw:
                                avisados.append(kw.get("acciones")) or "movil")

        main._reponer_tras_hablar("sesion", UN_UUID)

        assert len(avisados) == 1
        assert [a["action"] for a in avisados[0]] == [f"LA_HABLAR_SES_{UN_UUID}",
                                                      f"LA_VALE_{UN_UUID}"]

    def test_pulsar_hablarlo_tres_veces_no_programa_tres_reposiciones(
            self, mock_requests, monkeypatch, sin_esperar):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([]))
        monkeypatch.setattr(main, "_notificar", lambda *a, **k: "movil")

        # La primera termina sola (el Timer falso ejecuta en el acto y libera la clave),
        # así que para ver el candado hay que solapar: se programa desde dentro.
        main._reposiciones_en_curso.add(f"revision:{UN_UUID}")
        try:
            main._reponer_tras_hablar("revision", UN_UUID)
            assert sin_esperar == [], "con una en curso, no se programa otra"
        finally:
            main._reposiciones_en_curso.discard(f"revision:{UN_UUID}")

    def test_un_fallo_reponiendo_no_se_propaga(self, mock_requests, monkeypatch,
                                               sin_esperar):
        """Un aviso que no vuelve es el estado de antes de esto, no una avería nueva."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([_FILA]))

        def _explota(*a, **k):
            raise RuntimeError("el correo está caído")

        monkeypatch.setattr(main, "_notificar", _explota)
        main._reponer_tras_hablar("revision", UN_UUID)   # no levanta

    def test_espera_a_que_pueda_haber_terminado_la_llamada(self):
        """No se repone en el acto: el acto es cuando está sonando el teléfono."""
        assert main.HABLAR_REPONER_SEG >= main.LLAMADA_MAX_SEG, \
            "reponer antes del tope de la llamada es reponer mientras hablas"

    def test_el_boton_de_hablar_programa_la_reposicion(self, client, mock_requests,
                                                       monkeypatch):
        """El enganche: pulsar «Hablarlo» de verdad es lo que arranca el temporizador."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([_FILA]))
        monkeypatch.setattr(main, "_llamar", lambda *a, **k: True)
        programadas = []
        monkeypatch.setattr(main, "_reponer_tras_hablar",
                            lambda tipo, rid: programadas.append((tipo, rid)))

        r = client.post(f"/revision/{UN_UUID}/accion",
                        json={"accion": "hablar"}, headers=CABECERA)

        assert r.status_code == 200
        assert programadas == [("revision", UN_UUID)]


class TestRetirarLaNotificacion:
    def _sondear(self, client):
        return client.get("/ha/avisos-pending", headers=CABECERA).json()

    def test_el_tag_viaja_con_el_aviso(self, client, monkeypatch):
        """Sin tag no se puede ni reemplazar ni retirar: es la pieza que faltaba."""
        self._sondear(client)                       # HA se declara vivo sondeando
        main._notificar("hola", "qué tal", aviso_id=UN_UUID)
        avisos = self._sondear(client)["avisos"]
        assert avisos[0]["tag"] == UN_UUID, "el tag es el id: misma notificación"

    def test_un_aviso_sin_id_lleva_tag_propio(self, client):
        """Un tag vacío uniría TODOS los avisos sin id en una sola notificación."""
        self._sondear(client)
        main._notificar("uno", "uno")
        main._notificar("dos", "dos")
        avisos = self._sondear(client)["avisos"]
        tags = [a["tag"] for a in avisos]
        assert all(tags) and len(set(tags)) == 2, "dos avisos, dos notificaciones"

    def test_decidir_retira_la_notificacion_del_movil(self, client, mock_requests,
                                                      monkeypatch):
        """Contestar por el dashboard o por teléfono deja la del móvil preguntando."""
        self._sondear(client)
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", FakeResponse([_FILA]))
        monkeypatch.setattr(main, "_revision_decidir",
                            lambda rid, accion: {"ok": True, "accion": "nada"})

        client.post(f"/revision/{UN_UUID}/accion",
                    json={"accion": "nada"}, headers=CABECERA)

        assert self._sondear(client)["borrar"] == [UN_UUID]

    def test_el_borrado_viaja_por_la_misma_cola_que_los_avisos(self, client):
        """Un borrado que adelantara a su aviso lo dejaría puesto para siempre."""
        self._sondear(client)
        main._retirar_del_movil(UN_UUID)
        recogido = self._sondear(client)
        assert recogido["borrar"] == [UN_UUID]
        assert self._sondear(client)["borrar"] == [], "recoger consume, como los avisos"

    def test_sin_movil_vivo_no_se_encola_nada(self, client, monkeypatch):
        """Si nadie recoge, un borrado guardado solo sirve para dispararse tarde."""
        monkeypatch.setattr(main, "_ultimo_sondeo_avisos", 0.0)
        main._retirar_del_movil(UN_UUID)
        assert main._avisos_borrar == []

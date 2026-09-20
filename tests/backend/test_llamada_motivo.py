"""Que la llamada hable de AQUELLO por lo que sonó, y no de lo que gane el orden.

Descolgar por «Hablarlo» y que Jarvis conteste que no hay ningún issue es un fallo con
historia: ya secuestró la pantalla de llamada el 2026-09-04 (`docs/BUGS_HISTORICOS.md`),
cuando un permiso de despliegue sin caducidad se puso delante de un aviso de sesión. Se
tapó dándole caducidad al permiso, que estrecha la ventana y no la cierra — dentro de esas
48 h volvía a pasar exactamente igual.

La causa de fondo eran tres agujeros en el mismo camino, y aquí se fija que estén los tres
cerrados:

- que **todos** los botones «Hablarlo» digan de qué venían, no solo el de la revisión;
- que ese motivo llegue hasta el prompt, y no se quede en la pantalla;
- y que, cuando llega, **mande sobre el orden de prioridades** en vez de ir el último.

El orden sigue existiendo y sigue siendo el mismo. Lo que cambia es cuándo decide: solo
cuando no se sabe por qué se ha descolgado.
"""
import pytest

from conftest import FakeResponse

import main

UN_UUID  = "fa27dab6-f054-5982-bd86-994e5e8b151b"
OTRO     = "b1c2d3e4-f5a6-4789-9abc-def012345678"
FRONT    = "https://dashboard.test"


def _revision(url, **k):
    """Las dos mitades de `revision_hallazgos`: un permiso listo y una decisión pendiente.

    Son la misma tabla con distinto `estado`, que es justo por lo que un UUID a secas no
    basta para saber de cuál de las dos se está hablando.
    """
    if "estado=eq.listo" in url:
        return FakeResponse([{"id": OTRO, "pr_numero": 7,
                              "detalle": "CI roto", "issue_titulo": ""}])
    return FakeResponse([{"id": UN_UUID, "origen": "vigilante", "issue_numero": 0,
                          "issue_url": "", "issue_titulo": "5 errores",
                          "detalle": "5 errores\n· 1× Graph"}])


class TestTodosLosBotonesDicenDeQueVienen:
    """Arreglar un botón no arregla el canal: la moraleja del 2026-09-14, aplicada."""

    @pytest.fixture(autouse=True)
    def _con_frontend(self, monkeypatch):
        monkeypatch.setattr(main, "FRONTEND_URL", FRONT)

    def test_el_del_despliegue_lleva_id_y_tipo(self):
        """Antes abría `?llamada=1` a secas y el id se quedaba en la notificación."""
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_DESPLIEGUE)
        assert acciones[-1]["title"] == "Hablarlo"
        assert acciones[-1]["uri"] == f"{FRONT}/?llamada=1&aviso={UN_UUID}&tipo=despliegue"

    def test_el_del_aviso_de_sesion_tambien(self):
        """Ya no abre el dashboard: hace sonar el teléfono, con el id en el propio `action`."""
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_SESION)
        assert acciones[0]["title"] == "Hablarlo"
        assert acciones[0]["action"] == f"LA_HABLAR_SES_{UN_UUID}"
        assert "uri" not in acciones[0]

    def test_y_el_de_la_revision_dice_de_que_tabla_es(self):
        """El prefijo `_REV_`/`_SES_` es lo que dice de qué tabla es, no el `tipo` de una `uri`."""
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_REVISION)
        assert acciones[-1]["action"] == f"LA_HABLAR_REV_{UN_UUID}"

    def test_sin_frontend_solo_el_despliegue_pierde_hablarlo(self, monkeypatch):
        """Sesión y revisión hacen sonar el teléfono: no dependen del dashboard. El
        despliegue sigue siendo el único que abre uno, así que es el único que lo pierde."""
        monkeypatch.setattr(main, "FRONTEND_URL", "")
        acciones = main._acciones_aviso(UN_UUID, main.REGLA_DESPLIEGUE)
        assert all(a["title"] != "Hablarlo" for a in acciones)
        for regla in (main.REGLA_SESION, main.REGLA_REVISION):
            acciones = main._acciones_aviso(UN_UUID, regla)
            assert any(a["title"] == "Hablarlo" for a in acciones)


class TestLaPantallaAnunciaElMotivoExacto:
    def test_con_tipo_despliegue_se_anuncia_ese_permiso(self, client, auth_headers,
                                                        mock_requests):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        p = client.get(f"/llamada/pendiente?aviso={OTRO}&tipo=despliegue",
                       headers=auth_headers).json()["pendiente"]
        assert p["tipo"] == "despliegue"
        assert p["pr"] == 7

    def test_con_tipo_sesion_se_anuncia_ese_aviso(self, client, auth_headers,
                                                 mock_requests):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        mock_requests.add("GET", "/rest/v1/sesion_avisos", FakeResponse(
            [{"id": UN_UUID, "titulo": "He tocado el brief", "pendiente": "desplegarlo"}]))
        p = client.get(f"/llamada/pendiente?aviso={UN_UUID}&tipo=sesion",
                       headers=auth_headers).json()["pendiente"]
        assert p["tipo"] == "sesion"
        assert p["titulo"] == "He tocado el brief"
        # Lo que no cabe en la apertura hablada sí cabe en lo que se lee mientras suena.
        assert "desplegarlo" in p["motivo"]

    def test_sin_tipo_sigue_significando_revision(self, client, auth_headers,
                                                  mock_requests):
        """Las notificaciones enviadas antes de que `tipo` existiera traen solo el id.

        Si esto dejara de funcionar, el arreglo rompería justo los avisos que ya estaban
        en el móvil de alguien — que es la peor forma de arreglar un canal.
        """
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        p = client.get(f"/llamada/pendiente?aviso={UN_UUID}",
                       headers=auth_headers).json()["pendiente"]
        assert p["tipo"] == "revision"

    def test_un_tipo_inventado_no_revienta_la_llamada(self, client, auth_headers,
                                                      mock_requests):
        """Se descuelga con lo que haya: un teléfono mudo es peor que uno que improvisa."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        r = client.get(f"/llamada/pendiente?aviso={UN_UUID}&tipo=../../algo",
                       headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["pendiente"]["tipo"] == "despliegue"   # el orden de siempre

    def test_un_id_con_forma_rara_se_rechaza(self, client, auth_headers):
        """Se interpola en la URL de Supabase: invariante 6 de CLAUDE.md."""
        for tipo in ("despliegue", "sesion"):
            r = client.get(f"/llamada/pendiente?aviso=../../algo&tipo={tipo}",
                           headers=auth_headers)
            assert r.status_code == 422, tipo


class TestElMotivoMandaSobreElOrden:
    """El corazón del arreglo. Todo lo demás existe para que esto pueda pasar."""

    def test_la_revision_gana_al_despliegue_cuando_la_pediste_tu(self, mock_requests):
        """El fallo exacto que se venía notando.

        Había un permiso de despliegue vivo, pulsabas «Hablarlo» sobre un issue, y el
        contexto que llegaba al modelo era el del permiso: el de la revisión estaba en el
        último `else` de una cadena que nunca se alcanzaba. Jarvis descolgaba diciendo
        que no había ningún issue, y tenía razón — con lo que le habían dado.
        """
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        sistema = main._jarvis_sistema(voz=True, aviso=UN_UUID, tipo="revision")
        assert "DECISIÓN SIN CONTESTAR" in sistema
        assert "5 errores" in sistema
        assert "ESPERANDO TU PERMISO" not in sistema

    def test_y_el_despliegue_gana_cuando_no_se_sabe_por_que_suena(self, mock_requests):
        """El orden no se ha tirado: sigue siendo quien decide cuando no hay motivo."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        sistema = main._jarvis_sistema(voz=True)
        assert "ESPERANDO TU PERMISO" in sistema
        assert "DECISIÓN SIN CONTESTAR" not in sistema

    def test_el_aviso_de_sesion_tambien_se_salta_la_cola(self, mock_requests):
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        mock_requests.add("GET", "/rest/v1/sesion_avisos", FakeResponse(
            [{"id": UN_UUID, "titulo": "He tocado el brief", "hecho": "un PR"}]))
        sistema = main._jarvis_sistema(voz=True, aviso=UN_UUID, tipo="sesion")
        assert "TE HA DEJADO UN AVISO" in sistema
        assert "ESPERANDO TU PERMISO" not in sistema

    def test_si_lo_tuyo_ya_se_decidio_se_descuelga_con_lo_que_haya(self, mock_requests):
        """Mismo criterio que la pantalla: mejor improvisar que sonar para decir nada."""
        mock_requests.add("GET", "/rest/v1/sesion_avisos", FakeResponse([]))
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        sistema = main._jarvis_sistema(voz=True, aviso=UN_UUID, tipo="sesion")
        assert "ESPERANDO TU PERMISO" in sistema

    def test_un_motivo_sin_tipo_no_se_adivina(self, mock_requests):
        """Adivinar la tabla a base de probar las tres sería tres viajes por turno."""
        mock_requests.add("GET", "/rest/v1/revision_hallazgos", _revision)
        sistema = main._jarvis_sistema(voz=True, aviso=UN_UUID, tipo="")
        assert "ESPERANDO TU PERMISO" in sistema

    def test_con_supabase_caido_se_dice_que_no_se_sabe(self, monkeypatch):
        """«No pude» no es «no hay nada»: la moraleja del 2026-09-16, también por aquí."""
        def _cae(*a, **k):
            raise RuntimeError("Supabase caído")
        monkeypatch.setattr(main, "_revision_pendiente", _cae)
        sistema = main._jarvis_sistema(voz=True, aviso=UN_UUID, tipo="revision")
        assert "NO SE HA PODIDO COMPROBAR" in sistema
        assert "NUNCA que no hay nada" in sistema

    def test_por_escrito_el_motivo_no_se_consulta(self, monkeypatch):
        """Aunque venga en el cuerpo: por escrito los segundos no se notan y se paga igual."""
        def _no(*a, **k):
            raise AssertionError("el contexto escrito no debe consultar nada")
        for fn in ("_despliegue_pendiente", "_sesion_pendiente", "_revision_pendiente"):
            monkeypatch.setattr(main, fn, _no)
        main._jarvis_sistema(voz=False, aviso=UN_UUID, tipo="revision")


class TestElMotivoViajaEnCadaTurno:
    """El prompt se arma de cero en cada turno: mandarlo solo al descolgar es no mandarlo."""

    def test_jarvis_acepta_el_motivo(self):
        turno = main.JarvisIn(mensaje="¿qué issue?", voz=True,
                              aviso=UN_UUID, tipo="revision")
        assert turno.aviso == UN_UUID
        assert turno.tipo == "revision"

    def test_sin_motivo_sigue_valiendo(self):
        """El chat escrito y el puente del teléfono no lo mandan nunca."""
        turno = main.JarvisIn(mensaje="hola")
        assert turno.aviso == ""
        assert turno.tipo == ""

    def test_un_id_con_forma_rara_no_llega_a_supabase(self):
        """Se valida en el modelo, que es antes de que nadie lo interpole en una URL."""
        with pytest.raises(Exception):
            main.JarvisIn(mensaje="hola", aviso="../../algo")

    def test_un_tipo_fuera_de_la_lista_tampoco(self):
        with pytest.raises(Exception):
            main.JarvisIn(mensaje="hola", tipo="otra_tabla")

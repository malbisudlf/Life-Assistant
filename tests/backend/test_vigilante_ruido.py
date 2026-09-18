"""El vigilante deja de llenar el repositorio de issues que nadie puede cerrar.

El 2026-09-16, al vaciar los issues abiertos, había **siete** del vigilante (#136, #177,
#179, #180, #182, #183, #184) y ninguno necesitaba tocar una línea de código. Dos cosas
distintas los habían dejado ahí:

- **La misma avería, contada varias veces.** #179 y #180 son la misma caída de DNS del
  Green en dos días (200 y 196 errores, casi las mismas cinco líneas) y #182 su cola. La
  memoria del vigilante era la huella del CONJUNTO de formas de error, y una caída que
  dura tres días no repite el conjunto exacto: pierde una forma un día y gana otra al
  siguiente, así que cada día era una avería nueva con su issue nuevo.
- **Un texto que afirmaba lo que no sabía.** Todos terminaban con «no se puede reparar
  desde el backend, así que necesita un cambio de código», y en los siete era falso: eran
  timeouts, DNS y `Gateway Timeout` de Supabase. Esa frase es la que los hacía parecer
  accionables. Y con `NOCHE_ARREGLA` encendido, el botón «Arreglarlo» de esos avisos manda
  una sesión de Claude Code a arreglar una caída de red.

Siete issues que nadie puede cerrar arreglando nada enseñan a ignorar los del vigilante,
que es exactamente lo contrario de para lo que existe.
"""
from datetime import datetime
from urllib.parse import unquote

import pytest

from conftest import FakeResponse

import main


# Una caída de red de verdad, tal y como la deja `logger.exception` en `app_logs`.
DNS_CAIDO = ("Fallo hablando con Supabase\n"
             "Traceback (most recent call last):\n"
             '  File "main.py", line 504, in _pedir\n'
             "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='x.supabase.co', "
             "port=443): Max retries exceeded (Temporary failure in name resolution)")


class TestQueEsDeRedYQueEsDeCodigo:
    """La clasificación va sobre el mensaje CRUDO: la firma ya no tiene cifras."""

    @pytest.mark.parametrize("mensaje", [
        "Error de almacenamiento (504): Gateway Timeout",
        "Supabase devolvió 504",
        "GET /weather → 503 (395 ms)",
        "requests.exceptions.ReadTimeout: HTTPSConnectionPool: Read timed out.",
        "ConnectionResetError: [Errno 104] Connection reset by peer",
        "socket.gaierror: [Errno -3] Temporary failure in name resolution",
        "ssl.SSLError: handshake operation timed out",
        DNS_CAIDO,
    ])
    def test_lo_que_es_de_red(self, mensaje):
        assert main._error_de_red(mensaje) is True

    @pytest.mark.parametrize("mensaje", [
        "Supabase devolvió 400",
        "Open-Meteo devolvió 500",
        "KeyError: 'sueno'",
        # El caso que obliga a exigir el código EN CONTEXTO: un traceback cualquiera lleva
        # números de línea, y un `\\b504\\b` suelto convertiría media avería real en red.
        'Reventó el resumen\nTraceback:\n  File "main.py", line 504, in enviar_brief',
        "",
    ])
    def test_lo_que_no(self, mensaje):
        assert main._error_de_red(mensaje) is False

    def test_ante_la_duda_cuenta_como_codigo(self):
        """Un falso negativo abre un issue de más, que es lo que ya pasaba. Un falso
        positivo se callaría una avería real, que es mucho peor."""
        assert main._error_de_red("Algo raro que nadie ha visto nunca") is False


class TestAveriasDeRed:
    AHORA = datetime(2026, 9, 16, 9, 0, tzinfo=main.LOCAL_TZ)

    @pytest.fixture(autouse=True)
    def _encendido(self, monkeypatch):
        monkeypatch.setattr(main, "VIGILANTE", True)
        monkeypatch.setattr(main, "_ahora_local", lambda: self.AHORA)
        monkeypatch.setattr(main, "ARREGLO_FIRE_URL", "https://api.anthropic.com/arreglo")
        monkeypatch.setattr(main, "ARREGLO_FIRE_TOKEN", "sk-ant-oat01-x")
        main._ultima_vigilancia_sistema = 0.0

    @pytest.fixture
    def issues_abiertos(self, monkeypatch):
        """Los issues que el vigilante llega a abrir, sin salir a GitHub."""
        abiertos = []
        monkeypatch.setattr(main, "_vigilante_abrir_issue",
                            lambda titulo, cuerpo: abiertos.append((titulo, cuerpo))
                            or f"https://github.com/x/y/issues/{len(abiertos)}")
        return abiertos

    def _errores(self, mock_requests, mensajes):
        """`mensajes` es una lista de (mensaje, veces)."""
        filas, i = [], 0
        for mensaje, veces in mensajes:
            for _ in range(veces):
                i += 1
                filas.append({"level": "ERROR", "source": "life-assistant", "message": mensaje,
                              "created_at": f"2026-09-16T{i % 24:02d}:00:00Z"})
        # Sustituir y no añadir: `MockRouter` devuelve la PRIMERA ruta que casa, así que
        # encadenar dos vueltas dejaba viva la respuesta de la primera.
        mock_requests.routes = [r for r in mock_requests.routes
                                if r[1] not in ("/rest/v1/app_logs", "jarvis_recordatorios")]
        mock_requests.add("GET", "/rest/v1/app_logs", FakeResponse(filas))
        mock_requests.add("POST", "jarvis_recordatorios", FakeResponse([], 201))

    def _aviso(self, mock_requests):
        return mock_requests.called("POST", "jarvis_recordatorios")[0][2]["json"]

    # ── El umbral ────────────────────────────────────────────────────────────
    def test_unos_pocos_timeouts_no_son_una_averia(self, mock_requests):
        """#183 y #184 fueron cuatro y cinco `Gateway Timeout` sueltos de Supabase, uno de
        cada. Con el listón de los errores de código pasaban de sobra."""
        self._errores(mock_requests, [("Supabase devolvió 504", 5)])
        assert main._vigilar_sistema() == {}
        assert not mock_requests.called("POST", "jarvis_recordatorios")

    def test_una_caida_de_verdad_sigue_avisando(self, mock_requests):
        """La del DNS del Green fueron doscientos errores en un día: eso sí se cuenta."""
        self._errores(mock_requests, [(DNS_CAIDO, 30)])
        r = main._vigilar_sistema()
        assert r["vigilante_averias"] == 1 and r["aviso_vigilante"] is True

    # ── Lo que se dice y lo que no ───────────────────────────────────────────
    def test_no_lo_llama_cambio_de_codigo_ni_abre_issue(self, mock_requests, issues_abiertos):
        self._errores(mock_requests, [(DNS_CAIDO, 30)])
        main._vigilar_sistema()
        texto = self._aviso(mock_requests)["texto"]
        assert "de red o de terceros: no es código" in texto
        assert issues_abiertos == []

    def test_no_ofrece_el_boton_de_arreglarlo(self, mock_requests):
        """Es la mitad que más importa: «Arreglarlo» lanza una sesión contra el
        repositorio, y una caída de DNS no tiene nada que arreglar ahí."""
        self._errores(mock_requests, [(DNS_CAIDO, 30)])
        main._vigilar_sistema()
        assert self._aviso(mock_requests)["regla"] == main.REGLA_VIGILANTE_SOLO
        assert not mock_requests.called("POST", "/rest/v1/revision_hallazgos")

    # ── Mezcladas en el mismo origen ─────────────────────────────────────────
    def test_la_red_no_arrastra_a_los_errores_de_codigo(self, mock_requests, issues_abiertos):
        """Contadas juntas, treinta timeouts subían por encima del umbral a los dos
        errores de código que iban en medio y encima copaban los detalles del aviso."""
        self._errores(mock_requests, [(DNS_CAIDO, 30), ("KeyError: 'sueno'", 4)])
        main._vigilar_sistema()
        assert len(issues_abiertos) == 1
        titulo, cuerpo = issues_abiertos[0]
        assert "4 errores en life-assistant" in titulo
        assert "KeyError" in cuerpo and "Max retries exceeded" not in cuerpo

    def test_la_sesion_de_arreglo_no_recibe_los_errores_de_red(self, mock_requests):
        """Lo que se apunta en la decisión es lo que leerá la sesión que pulse el botón:
        mandarle treinta timeouts es mandarla a perseguir lo que no es."""
        self._errores(mock_requests, [(DNS_CAIDO, 30), ("KeyError: 'sueno'", 4)])
        main._vigilar_sistema()
        fila = mock_requests.called("POST", "/rest/v1/revision_hallazgos")[0][2]["json"]
        assert "KeyError" in fila["detalle"]
        assert "Max retries exceeded" not in fila["detalle"]
        assert self._aviso(mock_requests)["regla"] == main.REGLA_VIGILANTE

    def test_el_aviso_sigue_contando_las_dos(self, mock_requests):
        """No abrir issue no es callarse: el aviso del móvil las cuenta igual, que para
        eso el vigilante se ha molestado en detectarlas."""
        self._errores(mock_requests, [(DNS_CAIDO, 30), ("KeyError: 'sueno'", 4)])
        assert main._vigilar_sistema()["vigilante_averias"] == 2
        texto = self._aviso(mock_requests)["texto"]
        assert "30 errores" in texto and "4 errores" in texto

    def test_la_frase_de_red_no_se_come_el_aviso(self, mock_requests):
        """El aviso se recorta a 200 caracteres: lo que gaste la explicación se lo quita a
        los errores concretos, que son lo único accionable que lleva."""
        self._errores(mock_requests, [(DNS_CAIDO, 30)])
        main._vigilar_sistema()
        texto = self._aviso(mock_requests)["texto"]
        assert "de red o de terceros" in texto
        assert "Fallo hablando con Supabase" in texto, "la lista de errores no ha cabido"

    # ── Que el código siga como estaba ───────────────────────────────────────
    def test_un_error_de_codigo_repetido_sigue_abriendo_su_issue(self, mock_requests,
                                                                 issues_abiertos):
        self._errores(mock_requests, [("KeyError: 'sueno'", 4)])
        main._vigilar_sistema()
        assert len(issues_abiertos) == 1
        assert "apunta a un cambio de código" in issues_abiertos[0][1]
        assert "no se puede reparar desde el backend" not in issues_abiertos[0][1]


class TestUnIssuePorAveriaYNoPorDia(TestAveriasDeRed):
    """La deduplicación por FORMA de error, que es lo que faltaba.

    Hereda el andamiaje de arriba: lo que se prueba aquí es lo mismo visto dos días
    seguidos.
    """

    @pytest.fixture
    def memoria(self, mock_requests):
        """`vigilante_estado` de verdad: lo que se marca en una vuelta se lee en la
        siguiente, que es justo lo que el vigilante no tenía."""
        filas: dict = {}

        def _get(url, **kwargs):
            if "clave=in.(" in url:
                dentro = url.split("clave=in.(", 1)[1].split(")", 1)[0]
                return FakeResponse([filas[c] for c in dentro.split(",") if c in filas])
            if "clave=eq." in url:
                clave = unquote(url.split("clave=eq.", 1)[1].split("&", 1)[0])
                return FakeResponse([filas[clave]] if clave in filas else [])
            return FakeResponse([])

        def _post(url, **kwargs):
            cuerpo = kwargs.get("json")
            for fila in (cuerpo if isinstance(cuerpo, list) else [cuerpo]):
                filas.setdefault(fila["clave"], {"clave": fila["clave"]}).update(fila)
            return FakeResponse([], 201)

        def _patch(url, **kwargs):
            clave = unquote(url.split("clave=eq.", 1)[1].split("&", 1)[0])
            filas.setdefault(clave, {"clave": clave}).update(kwargs.get("json") or {})
            return FakeResponse([], 204)

        mock_requests.add("GET", "/rest/v1/vigilante_estado", _get)
        mock_requests.add("POST", "/rest/v1/vigilante_estado", _post)
        mock_requests.add("PATCH", "/rest/v1/vigilante_estado", _patch)
        return filas

    def test_la_misma_caida_al_dia_siguiente_no_abre_otro_issue(self, mock_requests,
                                                                memoria, issues_abiertos):
        """#179 y #180: la misma caída, dos días, dos issues. El conjunto de formas se
        movió lo justo para que la huella cambiara, y con eso bastaba."""
        self._errores(mock_requests, [("KeyError: 'sueno'", 4), ("ValueError: fecha", 3)])
        main._vigilar_sistema()
        assert len(issues_abiertos) == 1

        # Al día siguiente sigue lo mismo, más una forma nueva: otra huella, otra clave.
        main._ultima_vigilancia_sistema = 0.0
        mock_requests.calls.clear()
        self._errores(mock_requests, [("KeyError: 'sueno'", 4), ("ValueError: fecha", 3),
                                      ("TypeError: None", 2)])
        main._vigilar_sistema()
        assert len(issues_abiertos) == 1, "se ha abierto un segundo issue por la misma avería"
        assert "Ya hay un issue abierto por esto" in self._aviso(mock_requests)["texto"]

    def test_una_averia_de_verdad_nueva_sigue_abriendo_el_suyo(self, mock_requests,
                                                               memoria, issues_abiertos):
        """La deduplicación no puede tragarse lo que sí es nuevo: el fallo del 3 de
        septiembre fue justo ese, un issue que valía para todo lo que viniera después."""
        self._errores(mock_requests, [("KeyError: 'sueno'", 4)])
        main._vigilar_sistema()

        main._ultima_vigilancia_sistema = 0.0
        mock_requests.calls.clear()
        self._errores(mock_requests, [("AttributeError: alarma", 4)])
        main._vigilar_sistema()
        assert len(issues_abiertos) == 2

    def test_al_abrirlo_apunta_la_url_en_cada_forma(self, mock_requests, memoria,
                                                    issues_abiertos):
        self._errores(mock_requests, [("KeyError: 'sueno'", 4), ("ValueError: fecha", 3)])
        main._vigilar_sistema()
        formas = {c: f for c, f in memoria.items() if c.startswith("firma:")}
        assert len(formas) == 2
        assert all(f["issue_url"] == "https://github.com/x/y/issues/1" for f in formas.values())

    def test_si_no_se_puede_mirar_la_memoria_de_formas_se_abre_igual(self, mock_requests,
                                                                     memoria, issues_abiertos):
        """La deduplicación es una mejora, no un requisito: si la consulta falla se abre
        el issue, que es lo que pasaba antes de que esto existiera. Callar una avería por
        no poder deduplicarla sería cambiar un ruido molesto por un silencio peligroso."""
        def _revienta(url, **kwargs):
            return FakeResponse(None, 500, "boom") if "clave=in.(" in url else FakeResponse([])

        mock_requests.routes.insert(0, ("GET", "/rest/v1/vigilante_estado", _revienta))
        self._errores(mock_requests, [("KeyError: 'sueno'", 4)])
        r = main._vigilar_sistema()
        assert r["aviso_vigilante"] is True
        assert len(issues_abiertos) == 1

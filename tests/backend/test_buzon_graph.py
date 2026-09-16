"""El buzón por Microsoft Graph.

El correo de Outlook no se puede leer por IMAP: su servidor anuncia `LOGINDISABLED` y
`AUTH=XOAUTH2`, o sea que la contraseña —incluida la de aplicación— no vale desde que
Microsoft retiró la autenticación básica. Lo que se comprueba aquí es lo que sostiene la
sustitución: que sin permiso no se toca el buzón, que pedir el permiso nuevo no puede
llevarse por delante el calendario, y que leer sigue sin descolocar nada.
"""
import main
from conftest import FakeResponse


class TestLosPermisos:
    def test_apagado_no_se_pide_permiso_de_correo(self, monkeypatch):
        """El consentimiento que se le pide a Microsoft es el mínimo que hace falta: si
        el buzón está apagado, no se pide leer el correo."""
        monkeypatch.setattr(main, "CORREO_LEER", False)
        monkeypatch.setattr(main, "NOCHE_CORREO", False)
        assert main._scopes() == main.SCOPES_BASE

    def test_encendido_se_pide_leer_y_escribir_borradores(self, monkeypatch):
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "NOCHE_CORREO", False)
        assert "Mail.ReadWrite" in main._scopes()
        assert set(main.SCOPES_BASE) <= set(main._scopes())

    def test_el_consentimiento_viejo_no_se_lleva_por_delante_el_calendario(self, monkeypatch,
                                                                          mock_requests):
        """El caso real del despliegue: el token guardado se consintió cuando no existía
        el buzón. Pedir `Mail.ReadWrite` en la renovación NO devuelve un token capado,
        devuelve un error — y sin token no hay calendario, ni avisos, ni resumen diario.
        Así que se reintenta con los permisos de siempre y lo que se queda sin funcionar
        es solo el buzón.
        """
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "_token_cache", None)
        mock_requests.add("GET", "oauth_tokens", FakeResponse(
            [{"access_token": "viejo", "refresh_token": "r", "expires_at": 0}], 200))
        pedidos = []

        class _Msal:
            def acquire_token_by_refresh_token(self, refresh_token, scopes):
                pedidos.append(list(scopes))
                if "Mail.ReadWrite" in scopes:
                    return {"error": "invalid_grant",
                            "error_description": "AADSTS65001: consent required"}
                return {"access_token": "nuevo", "refresh_token": "r", "expires_in": 3600}

        monkeypatch.setattr(main, "_msal_app", lambda: _Msal())

        assert main.get_valid_token() == "nuevo"
        assert pedidos[0] != pedidos[1]
        assert "Mail.ReadWrite" not in pedidos[1]


class TestLeerElBuzon:
    def test_solo_se_piden_los_no_leidos_y_no_se_marca_nada(self, monkeypatch, mock_requests):
        """Dos garantías en una: se filtra por `isRead eq false` (no se baja el buzón
        entero) y no sale un solo PATCH, que es lo único que cambiaría el estado de un
        correo. Un asistente que te descoloca el buzón deja de usarse a la semana."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "get_valid_token", lambda: "t")
        mock_requests.add("GET", "/mailFolders/inbox/messages", FakeResponse({"value": [
            {"id": "AAA", "subject": "¿Quedamos?", "internetMessageId": "<a@x>",
             "from": {"emailAddress": {"name": "Ana", "address": "ana@ejemplo.com"}}},
        ]}, 200))

        cabeceras = main._cabeceras_recientes()

        url = mock_requests.called("GET", "/mailFolders/inbox/messages")[0][1]
        assert "isRead eq false" in url
        assert "$select=id,subject,from,internetMessageId" in url
        assert mock_requests.called("PATCH", "/me/messages") == []
        assert cabeceras == [{"asunto": "¿Quedamos?", "de": "Ana <ana@ejemplo.com>",
                              "id": "AAA", "message_id": "<a@x>"}]

    def test_sin_outlook_conectado_no_se_toca_el_buzon(self, monkeypatch, mock_requests):
        """Si Outlook no está conectado, `get_valid_token()` devuelve None y aquí no se
        sale a la red: ni excepción ni lista a medias."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "get_valid_token", lambda: None)

        assert main._cabeceras_recientes() == []
        assert mock_requests.called("GET", "graph.microsoft.com") == []

    def test_el_403_se_explica_en_el_registro(self, monkeypatch, mock_requests, caplog):
        """El 403 tiene arreglo propio y nada evidente —volver a conectar Outlook para
        consentir el permiso de correo—, así que tiene que decirlo en el registro y no
        quedarse en «Graph respondió 403»."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "get_valid_token", lambda: "t")
        mock_requests.add("GET", "/mailFolders/inbox/messages", FakeResponse({}, 403))

        with caplog.at_level("WARNING"):
            assert main._cabeceras_recientes() == []

        assert "conectar Outlook" in caplog.text

    def test_del_cuerpo_se_pide_solo_la_parte_nueva_y_en_texto(self, monkeypatch,
                                                              mock_requests):
        """`uniqueBody` es el mensaje sin el hilo citado debajo. Antes eso se recortaba a
        ciegas por caracteres y en una cadena larga el recorte se comía la pregunta."""
        monkeypatch.setattr(main, "CORREO_LEER", True)
        monkeypatch.setattr(main, "get_valid_token", lambda: "t")
        mock_requests.add("GET", "/me/messages/", FakeResponse(
            {"uniqueBody": {"contentType": "text", "content": "Hola.\n\n\n\nUn saludo."}}, 200))

        cuerpos = main._cuerpos_de(["AAA"])

        _, url, kwargs = mock_requests.called("GET", "/me/messages/")[0]
        assert "$select=uniqueBody" in url
        assert kwargs["headers"]["Prefer"] == 'outlook.body-content-type="text"'
        assert cuerpos == {"AAA": "Hola.\n\nUn saludo."}

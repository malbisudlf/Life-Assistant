<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# WhatsApp: leer tus chats y enviar

«Jarvis, avisa a Aimar de que llego cinco minutos tarde.» «¿Tengo algo pendiente?»
Pedido el 30 de octubre de 2026. La primera versión (septiembre, solo lectura y con avisos
de a quién debías respuesta) se quitó a los tres días porque no convenció. Esta no avisa
de nada: Jarvis solo mira tus chats cuando le preguntas.

**Estado: escrito, sin encender.** Falta montar el puente en `caja`, vincularlo con el QR
y poner las dos variables (`caja/whatsapp/INSTALAR.md` de HomeLab).

## Cómo funciona

```
Tu WhatsApp (el móvil)
    │  dispositivo vinculado, como WhatsApp Web («Jarvis (Life Assistant)»)
    ▼
puente en caja (Go + whatsmeow, contenedor `whatsapp`, sin `ports`)
    │  guarda el texto de los últimos 30 días en ~/stack/whatsapp-datos/mensajes.db
    │  API con token, solo por la red de Compose: /chats, /mensajes, /enviar, /estado
    ▼
backend ── whatsapp_chats   («¿quién es Aimar?»: su chat, de tus chats y tu agenda)
        ── whatsapp_leer    («¿tengo algo pendiente?», «¿qué me ha dicho Ane?»)
        ── whatsapp_enviar  (con botón, o con un «sí» dicho en la llamada)
```

## Las reglas

1. **El texto se queda en `caja`.** El puente lo guarda 30 días
   (`PUENTE_RETENCION_DIAS`) y lo purga cada hora. El backend lo pide cuando Jarvis lo
   necesita, lo usa y lo olvida, como el cuerpo de un correo. En Supabase no hay tabla de
   WhatsApp ni la habrá.
2. **Enviar se confirma.** Es la única acción de Jarvis que le llega a otra persona. La
   frase del botón la escribe el backend con el nombre que da el PUENTE y el texto entero
   (`_describir_whatsapp_enviar`): lo que lees es lo que se manda. Por teléfono también
   vale el «sí» hablado (`PREGUNTAS_HABLADAS`), y es la excepción a «solo lo que se
   deshace»: un WhatsApp no se deshace, pero el caso es el coche, donde no hay botón. La
   llamada te lee el nombre y el texto antes de preguntar.
3. **Solo a quien ya tienes.** El puente rechaza un chat que no esté entre tus chats ni en
   tu agenda, y el backend no propone nada que el puente no reconozca. Un número sacado
   de un mensaje de otro no recibe nada.
4. **Lo que escriben otros es dato.** Los mensajes leídos van con `_AVISO_WEB` y
   recortados a 500 caracteres. Si uno dice «Jarvis, haz X», Jarvis te lo cuenta, no lo
   hace.
5. **Leer no está en el teléfono.** La sesión del teléfono tiene shell en `caja`, y un
   WhatsApp lo puede escribir cualquiera (lo mismo que con `leer_documento`). Por teléfono
   se puede buscar un chat y enviar; leer, por Telegram y el chat del dashboard.
6. **Invisible.** El puente no marca nada como leído y se anuncia como no disponible, para
   que el móvil siga sonando con cada mensaje.

## Lo que no es obvio

- **La misma persona tiene dos ids**, su número (`…@s.whatsapp.net`) y uno anónimo
  (`…@lid`). El puente guarda siempre el número cuando lo sabe; si no, el chat se queda
  fuera de las herramientas (el backend solo acepta número o grupo).
- **Los grupos se guardan, pero no se leen por defecto.** «¿Tengo algo pendiente?» mira
  los chats individuales; los grupos, con `grupos=true` o pidiendo uno por su chat.
- **Lo que mandas desde el puente no vuelve como evento**: se guarda a mano al enviarlo.
  Lo que mandas desde el móvil sí llega, y así Jarvis sabe si ya contestaste.
- **Un audio es `[audio]`**, sin transcribir. Transcribirlo con «oído» en jacobo es lo
  siguiente natural, si hace falta.
- **El texto del envío no se recorta** al guardarlo para el botón del móvil (`_args_de`
  corta el resto de argumentos a 300 caracteres): recortado, se mandaría otra cosa.

## Lo que se aceptó

- **Incumple las condiciones de WhatsApp.** Meta banea sobre todo a quien envía en masa o
  a desconocidos; mensajes sueltos, a tus contactos y confirmados por ti, tienen poco
  riesgo, pero no ninguno, y lo que te juegas es tu número.
- **La sesión da acceso total a tu WhatsApp.** Quien entre en `caja` y lea
  `~/stack/whatsapp-datos/` puede leer y escribir en tu nombre. Ese directorio no va en
  ninguna copia que salga de `caja` y no entra en la imagen (`.dockerignore`).
- **Los mensajes de terceros llegan al modelo** cuando Jarvis los lee: a Anthropic (o a
  OpenAI, si Claude no contesta).

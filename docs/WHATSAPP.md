<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# WhatsApp: leer tus chats y enviar

«Jarvis, avisa a Aimar de que llego cinco minutos tarde.» «¿Tengo algo pendiente?»
Pedido el 30 de octubre de 2026. La primera versión (septiembre, solo lectura y con avisos
de a quién debías respuesta) se quitó a los tres días porque no convenció. Esta no avisa
de nada: Jarvis solo mira tus chats cuando le preguntas.

**Estado: encendido desde el 2026-11-02.** El puente está en `caja` y vinculado, y el
backend tiene sus dos variables (`caja/whatsapp/INSTALAR.md` de HomeLab). Los programados
llegaron el mismo día, detrás.

## Cómo funciona

```
Tu WhatsApp (el móvil)
    │  dispositivo vinculado, como WhatsApp Web («Jarvis (Life Assistant)»)
    ▼
puente en caja (Go + whatsmeow, contenedor `whatsapp`, sin `ports`)
    │  guarda el texto de los últimos 30 días en ~/stack/whatsapp-datos/mensajes.db
    │  y los programados, que manda él mismo a su hora (mira cada 20 s)
    │  API con token, solo por la red de Compose: /chats, /mensajes, /enviar, /estado,
    │  /programar, /programados
    ▼
backend ── whatsapp_chats      («¿quién es Aimar?»: su chat, de tus chats y tu agenda)
        ── whatsapp_leer       («¿tengo algo pendiente?», «¿qué me ha dicho Ane?»)
        ── whatsapp_enviar     (con botón, o con un «sí» dicho en la llamada)
        ── whatsapp_programar  («mañana a las 9 dile a Aimar…»: igual que enviar, con la hora)
        ── whatsapp_programados y whatsapp_cancelar_programado
```

## Los programados

«Mañana a las 9 dile a Aimar que no llego», «el viernes a las 00:00 felicita a Ane».
Pedido el 2026-11-02.

- **Los guarda y los manda el puente**, no el backend. Es la regla 1: el texto se queda
  en `caja`. Y el puente es el proceso que está siempre conectado; el backend solo los
  propone, los lista y los cancela.
- **Se confirman como un envío de ahora**, con botón o con el «sí» hablado, y la frase
  lleva la hora: «Mandar por WhatsApp mañana a las 09:00 a Aimar: «No llego»». Al
  mandarlo, el puente vuelve a comprobar que el chat sigue siendo tuyo.
- **Uno que llega tarde, caduca.** Si el puente estuvo caído y ya ha pasado más de una
  hora de su hora (`PUENTE_PROGRAMADO_MARGEN_MIN`), no sale: «llego en cinco minutos» con
  tres horas de retraso es peor que no mandarlo.
- **Si WhatsApp no lo acepta, se reintenta** cinco veces (una cada 20 s) y luego queda
  `fallido`. Desconectado no cuenta como intento: espera hasta que caduca.
- **Uno cortado a mitad no se repite.** Antes de mandarlo se marca `enviando`; si el
  proceso muere ahí, al arrancar queda `fallido`. Puede que ya saliera, y un mensaje
  repetido a otra persona es peor que uno perdido del que se te avisa.
- **El que no salió se te cuenta una vez**: el brief-tick pregunta al puente
  (`_avisar_whatsapp_programados`) y apunta un aviso con regla `whatsapp`, que es tuyo y
  no gasta el presupuesto del día. El aviso lleva el nombre, la hora y el motivo, **nunca
  el texto**: el aviso pasa por Supabase.
- Como mucho 50 pendientes y a un año vista. Lo resuelto (enviado, fallido, cancelado) se
  borra con la misma retención que los mensajes.

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
5. **Leer también está en el teléfono, a sabiendas.** La sesión del teléfono tiene shell
   en `caja` y un WhatsApp lo puede escribir cualquiera; por eso `leer_documento` no está
   ahí. Mikel lo quiso igual (30 de octubre): «¿tengo algo pendiente?» es una pregunta de
   coche. Lo que separa un mensaje de un comando es la regla 4 y el RUNBOOK del teléfono,
   no una frontera del código.
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

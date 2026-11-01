<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Llamar a otras personas: la línea fija por O2

«Jarvis, llama a Erik y pregúntale si quiere comer.» Jarvis llama a Erik desde el fijo de
casa, se presenta, habla con él y, al colgar, te llega al móvil lo que ha dicho. Pedido el
31 de octubre de 2026.

Todo lo de `docs/LLAMADAS.md` llama a **tu** extensión por la centralita 3CX, que en su
plan gratuito no sale a la red telefónica. Esto sale por la **línea fija de O2**: `caja`
habla SIP directamente con el proxy de voz de Telefónica, el mismo en el que se registra
el router.

**Estado: funcionando desde el 2026-11-01.** Tres llamadas de prueba al móvil de Mikel: la
segunda y la tercera se oyeron en los dos sentidos (hizo falta el parche 33). Cómo se
encendió, en orden:

1. En `~/.claude-phone/.env` de `caja`: `O2_SIP_USUARIO` (el *Auth Username* de
   *Voice → Basic* en el router; no se escribe en ningún otro sitio), `O2_PROXY`
   (`ip:puerto` del *Active Outbound Proxy*, el 5070) y `TELEFONO_TERCEROS_TOKEN`.
2. Aplicar el parche 32 en `caja` (`telefono/parche-32.diff`, ver `telefono/PARCHES.md`)
   y reconstruir la voice-app.
3. En `backend.env`: `TERCEROS_LLAMADAS=1` y el mismo `TELEFONO_TERCEROS_TOKEN`.
   Desplegar. Los contactos se leen con el permiso `Contacts.Read` de Outlook, que ya
   está concedido porque `CUMPLES=1`; sin los cumpleaños, habría que volver a conectar
   Outlook una vez. Para los contactos del iPhone, `ICLOUD_USUARIO` y
   `ICLOUD_CONTRASENA_APP` (una contraseña de aplicación de appleid.apple.com); para
   «llámame», `MI_MOVIL`.
4. Probar el registro solo (sin llamar a nadie) y después una llamada a tu móvil.

## Cómo funciona

```
Mikel: «llama a Erik y pregúntale si come hoy»
   │
   ▼
Jarvis (chat, Telegram o el teléfono) ── llamar_a_alguien(nombre, mensaje, objetivo, contexto)
   │  busca a Erik en tus contactos de Outlook (Graph) y de iCloud (CardDAV), por el nombre
   ▼
backend ── POST /api/outbound-call {linea: "o2", mode: "tercero", tercero: <id>}
   │
   ▼
voice-app (caja, parche 32)
   │  REGISTER en el proxy de O2 ─▶ INVITE a +34… ─▶ suena el móvil de Erik
   │  Erik: «¿Sí?» ─▶ «Hola, Erik. Soy Jarvis, el asistente de Mikel. Me pide que…»
   │  cada frase de Erik ─▶ oído (jacobo) ─▶ POST /telefono/tercero/{id}/turno
   │                                              │  un modelo SIN herramientas
   │  ◀── {decir, colgar} ◀──────────────────────┘
   │  colgar ─▶ BYE y se quita el registro de O2
   ▼
backend (hilo que sigue la llamada) ── «📞 Erik: dice que sí, a las 14:30» al móvil
```

Dos herramientas de Jarvis, que solo existen con `TERCEROS_LLAMADAS=1`:

| Herramienta | Qué hace | ¿Se confirma? |
|---|---|---|
| `llamar_a_alguien` | Llama a uno de tus contactos y vuelve enseguida: la llamada sigue en segundo plano | **No**: lo que se pidió es que sea autónomo |
| `llamadas_a_otros` | Las últimas llamadas: a quién, cómo acabó y qué contestaron | No: solo lee |

## Las reglas

1. **Al otro lado no hay herramientas.** La conversación con el tercero la piensa el
   backend (`_tercero_turno`) con un modelo al que no se le da ninguna herramienta, no el
   Claude Code con shell en `caja` que te atiende a ti. Lo que diga por teléfono alguien
   que no eres tú —o quien conteste el teléfono de Erik— es texto de cualquiera: aquí solo
   puede torcer una frase de la llamada, nunca ejecutar nada. Y el resumen que te llega va
   marcado como dato (`_AVISO_WEB`) cuando Jarvis lo vuelve a leer.
2. **Solo a quien ya tienes.** `llamar_a_alguien` busca un nombre en tus contactos de
   Outlook (208 en noviembre de 2026, 177 con teléfono) y de iCloud, que son los del
   iPhone (CardDAV a `contacts.icloud.com`, solo lectura, con una contraseña de
   aplicación), y nunca acepta un número suelto: es lo que impide que un número sacado de un correo, una web o un
   WhatsApp reciba una llamada aunque el modelo se equivoque o lo engañen. Para que llame
   a alguien nuevo, guárdalo en el móvil. Se busca por el nombre guardado, el de pila, el
   apodo o nombre y apellido, sin tildes; si hay dos que encajan, pregunta cuál. Del
   contacto se usa el primer número llamable: el móvil antes que el de casa o el del
   trabajo; el mismo número en Outlook y en iCloud cuenta como uno. Una fuente caída no
   tumba la otra, pero el «no lo encuentro» dice cuál no contestó. La única excepción al
   nombre es **«llámame»** (`nombre: "yo"`): te llama a ti, a `MI_MOVIL`, saludándote
   como siempre («Hola, señor») y sin buscar en los contactos; es la prueba de la línea.
   La copia de los contactos dura diez minutos, y si un nombre no aparece se
   vuelve a mirar en el momento. Hasta el 2026-11-01 había una lista aparte en Supabase,
   apuntada con botón; no llegó a encenderse.
3. **Solo números de persona en España** (`_tel_llamable`): móviles (6, 71-74) y fijos
   geográficos (81-88, 91-98). Fuera 112, 016, 118xx, 70x y los 80x/90x de tarificación
   especial, tanto al apuntar como al llamar, y otra vez en la voice-app.
4. **Se presenta como lo que es.** La primera frase la escribe el backend, no el modelo:
   «Hola, Erik. Soy Jarvis, el asistente de Mikel.», para que no dependa de que el modelo
   se acuerde. Si le preguntan si es una máquina, dice que sí. No cuenta de ti nada que no
   le hayas dado en `contexto` y no se compromete a nada fuera del encargo («se lo digo a
   Mikel»).
5. **No se graba.** El audio no se guarda en ningún sitio, y la transcripción vive en la
   memoria del backend (las últimas 20 llamadas). Lo que queda es el aviso con el resumen.
6. **Frenos**: nace apagado; entre las 9:00 y las 22:00 (`TERCEROS_DESDE/HASTA`); 8
   llamadas al día como mucho (`TERCEROS_DIA_MAX`); una a la vez (la línea es una); 30 s de
   timbre, 14 intervenciones del otro y 5 minutos de llamada.

## La línea O2 (parche 32 de claude-phone)

Lo que se averiguó a mano antes de escribir nada (sesión del 2026-10-31, con scripts de
Python en `caja`): el proxy de voz de Telefónica se alcanza desde la LAN y contesta por
UDP **5070** (el 5060 no responde). Acepta un REGISTER con el *Auth Username* de la línea
**sin contraseña**, siempre que las cabeceras vayan con la forma del router (`From`/`To`
`"USUARIO" <sip:USUARIO@telefonica.net:5070>`, `Route` al proxy, `Contact` con el
usuario). Con la línea registrada, un INVITE a `sip:+34…@telefonica.net:5060` hizo sonar
un móvil de verdad; sin registrar, el mismo INVITE dio 403. Por eso:

- **Se registra solo para llamar** y se quita al colgar (`LineaO2.usar/soltar`). Mientras
  `caja` está registrada, una llamada al fijo le llega también a ella (Telefónica la manda
  a todos los registrados). Se rechaza con **480** (`esSuya` en `index.js`): con un 6xx se
  cortaría también el timbre del Gigaset, y contestarla sería dejar que quien llame a casa
  hable con el Claude que tiene shell.
- **Al quitar el registro se quita solo nuestro `Contact`, nunca `Contact: *`**, que
  borraría también el del router y el fijo dejaría de recibir llamadas. Hay un test.
- **El router no se toca.** Ni la configuración de voz, ni `ip3`, ni las credenciales.

Lo que **no** se sabe todavía, y la primera llamada lo dirá:

- ~~Si el audio pasa~~: **pasa**, en los dos sentidos, desde que FreeSWITCH anuncia la IP
  de la LAN (parche 33). El SBC de Telefónica devuelve el RTP a donde le
  llega. Si algún día llega silencio (RMS 1 en los logs de la voice-app), lo primero es
  mirar qué `c=IN IP4` sale en el INVITE.
- **Si las condiciones de O2 permiten usar la línea así.** Llamadas sueltas a tus
  contactos no se parecen a un uso abusivo, pero no se ha consultado.
- **Qué número ve quien recibe la llamada**: debería ser el fijo de casa (lo pone
  Telefónica según el registro); está por confirmar.

## Lo que no hace

- **No llama a quien no esté en tus contactos**, aunque se lo dictes con el número:
  primero lo guardas en el móvil.
- **No sabe distinguir un buzón por las cabeceras**, como sí hace con el 3CX: lo decide el
  modelo por lo que oye («deje su mensaje») y deja un recado corto.
- **No insiste.** Si no lo coge, te llega «no lo ha cogido» y decides tú.
- **No hay llamadas entrantes.** Llamar al fijo y que conteste Jarvis es justo lo que el
  480 impide.

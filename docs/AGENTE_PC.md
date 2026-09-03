<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Agente PC (`agent/agent.py`)

Agente Windows **efímero**: arranca con Windows (vía WOL), drena la cola de jobs y se
cierra. Se registra en el backend con heartbeat. **Solo funciona en un PC Windows real**
(Edge, pyautogui, Claude Desktop): no tiene tests ni puede tenerlos en CI.

### Ciclo de vida

- Se autentica con `AGENT_TOKEN` (`LA_TOKEN`, el JWT, solo como respaldo y avisando por
  el log de que caduca).
- **Un fallo al consultar la cola no puede parecerse a una cola vacía**:
  `pedir_job_pendiente()` lanza `ErrorAuth` o `ErrorTransitorio` en vez de devolver
  `None`, y `main()` sale con código 2 (auth) o 3 (red) para que el Programador de tareas
  lo marque como error en vez de dejar "Last Result: 0" en un arranque que no hizo nada.
- El primer sondeo se reintenta durante `ARRANQUE_ESPERA_RED` (90 s): el agente corre a la
  vez que Windows y tras un WOL la tarjeta puede no tener IP todavía — el intento moría
  con un fallo de DNS a los 200 ms y se perdía justo el arranque que traía el job.
- Según `payload["accion"]` despacha a `ACCIONES` (`resolver_alud`, `abrir_streaming`).
  Compatibilidad: jobs sin `accion` pero con `alud_url` → `resolver_alud`.
  `resolver_accion()` + guard `attempted` (cada job se intenta una vez por ejecución para
  no repetir en bucle si falla el claim por red).

### Nada de PowerShell en el camino crítico

**La primera invocación de `powershell.exe` tras encender el PC tarda más de 40
segundos** (carga del CLR sobre un disco frío, con Defender inspeccionando el binario
por primera vez), y el agente arranca justo ahí, empujado por el WOL. Quedó medido en
su log el 2026-08-04: `15:29:16 → 15:29:56` esperando un `Get-Service` hasta agotar el
timeout, con el job entero tardando **65 s en frío contra 5 s con el PC caliente** —
los "45 segundos en negro" al lanzar el streaming. Y no era una llamada: la ruta de
`abrir_streaming` invoca PowerShell media docena de veces (estado del servicio,
`Start-Service`, los sondeos de confirmación, `apollo_vivo`).

Por eso `estado_servicio`, `arrancar_servicio` y `apollo_vivo` van por `sc.exe` y
`tasklist.exe` (`_nativo()`), que son binarios de Win32 sin runtime detrás: 23 y 108 ms.
Dos detalles que no se pueden relajar:

- **Se lee el CÓDIGO numérico del estado, no el texto** (`_ESTADOS_SC`,
  `STATE : 4`). El texto de `sc query` sí viene traducido ("EN EJECUCIÓN") en un
  Windows en español — que es exactamente lo que en su día hizo elegir `Get-Service`.
  El número no se traduce, así que sirve para las dos cosas. Lo mismo con `tasklist`:
  su "no hay tareas" está traducido, pero la línea de un proceso encontrado empieza
  siempre por `"sunshine.exe",` — se busca el nombre **entre comillas**. (Apollo no
  renombró el binario de Sunshine, así que el nombre sigue siendo ese; `apollo.exe` se
  mira también, por si un build futuro lo cambia.)
- **Cada camino nuevo conserva el de siempre como red de seguridad**: si `sc query` no
  da una respuesta interpretable o `sc start` falla con algo que no sabemos leer, se
  cae a PowerShell antes de darse por vencido. El agente no tiene tests ni puede
  tenerlos, y un fallo suyo ocurre a las 6 de la mañana sin nadie delante: el objetivo
  es que en el peor caso se comporte como antes, no que se quede sin saber el estado.
  `ACCESS_DENIED` (rc 5) es la excepción y corta directamente — sin privilegios
  PowerShell tampoco arrancaría el servicio, así que reintentar solo cuesta tiempo.

Verificado comparando `sc query` contra `Get-Service` en **los 322 servicios** de la
máquina real: coinciden todos, sin caer ni una vez a la red de seguridad.

### Acción `abrir_streaming`

- **Levanta la VPN antes de lanzar Apollo** (`conectar_vpn()`, Tailscale): el PC lo
  enciende un WOL sin nadie delante, así que el túnel no está arriba y desde fuera de casa
  Artemis no llega. Mismo criterio que con Apollo: el servicio de Tailscale va en
  arranque MANUAL para que el PC no tenga la VPN encendida en el día a día, y lo arranca
  el agente (`arrancar_servicio()`, que necesita que la tarea del Programador corra con
  privilegios elevados). El estado del servicio se consulta con `Get-Service`, no con
  `sc query`: este último traduce el estado y en un Windows en español devuelve
  "EN EJECUCIÓN". La IP de la tailnet viaja al modal en el mensaje del stage `vpn_ready`,
  de donde la saca `hostStreaming()` (helpers) — no se guarda en ningún sitio. Un fallo de
  VPN **no tumba el job**: se reporta `vpn_error` y se abre Apollo igual, que en la LAN
  sigue sirviendo.
- **Apollo se arranca por su servicio** (`APOLLO_SERVICIO`, mismo `arrancar_servicio()`
  que Tailscale), no ejecutando `sunshine.exe`: al agente lo lanza el Programador de tareas
  fuera del escritorio del usuario, y el binario arrancado desde ahí muere al instante. El
  `Popen` del exe queda solo como respaldo para instalaciones sin servicio. Y **el job no
  se da por hecho sin comprobarlo**: `arrancar_apollo()` espera hasta `APOLLO_TIMEOUT`
  a ver el proceso vivo (`apollo_vivo()`) y si no aparece lanza, de modo que el job cae a
  `failed` en vez de reportar `streaming_ready` sobre un PC sin nada abierto.
- **Las pantallas se duplican antes de abrir Apollo** (`cambiar_modo_pantallas()`,
  `DisplaySwitch.exe /clone`, configurable con `PANTALLAS_STREAMING`): por Artemis se ve
  una sola pantalla, y con el escritorio extendido lo que Windows abra en el otro
  monitor queda inalcanzable desde fuera — no puedes arrastrar una ventana a un monitor
  que el stream no manda. Va **antes** de arrancar Apollo porque el host elige la salida
  que captura al arrancar: reconfigurar los monitores por debajo le deja el stream
  mirando a una pantalla que ya no existe. Un fallo aquí **no tumba el job** (stage
  `pantallas_error`): el stream se ve igual, solo que con el escritorio como estuviera.
  El modo se valida contra `_MODOS_PANTALLA` aunque no pase por ningún shell — con un
  valor inventado, DisplaySwitch abre su interfaz y se queda esperando a que alguien
  elija, con el PC vacío.
- **Deshacerlo es cosa de Home Assistant**, no del agente: cuando cierras el stream el
  agente hace rato que terminó. El atajo `agent.py --pantallas [modo]`
  (`PANTALLAS_RESTAURAR`, `extend` por defecto) existe para que HA lo dispare antes de
  apagar o suspender el PC, y tiene que ir por una tarea del Programador
  (`schtasks /run /tn LifeAssistantPantallas`), **no** por el SSH directo: lo que entra
  por SSH corre en la sesión 0, sin escritorio que reconfigurar, y ahí DisplaySwitch no
  hace nada *y no falla*. Montaje en `agent/PUESTA_A_PUNTO.md`, paso 4bis.
- **El nombre del servicio se resuelve en caliente** (`servicio_streaming()`): sin
  `APOLLO_SERVICIO` en el `.env` se prueban `ApolloService` y `SunshineService`, en ese
  orden. Es lo que permite que el mismo agente sirva antes y después de migrar el PC —
  y por lo mismo `APOLLO_EXE`/`APOLLO_SERVICIO`/`APOLLO_TIMEOUT` siguen aceptando las
  `SUNSHINE_*` de siempre como respaldo. No quites ese respaldo sin repasar el `.env`
  del PC: el agente no tiene tests y un fallo suyo se descubre a las 6 de la mañana.

### Acción `resolver_alud` — notas de Edge, Playwright y Claude Desktop

Flujo: Edge (proceso detached) → CDP → login en Alud → extracción del enunciado →
Claude Desktop → Ctrl+2 (Cowork) → Win+V → Enter → Enter.

- **Primero se intenta REUTILIZAR el Edge que ya está abierto**
  (`asegurar_edge_con_cdp()`): si algo escucha en `EDGE_DEBUG_PORT`, se usa ese navegador y
  no se lanza ninguno. Es el que tiene la sesión de Alud y Okta iniciada. Solo si no hay
  nadie escuchando se arranca uno.
- **El puerto es FIJO** (`EDGE_DEBUG_PORT`, 49605 por defecto), ya no aleatorio. Lo fue
  —para no exponer un `9222` predecible— hasta que se vio lo que rompía: **con Edge ya
  abierto, lanzar otro proceso con `--remote-debugging-port` no abre nada**. El segundo
  delega en la instancia existente y se cierra; el puerto llegó a escuchar unos seis
  segundos y desapareció (medido el 2026-09-03). Con un puerto distinto en cada arranque
  no hay forma de conectarse al Edge que ya corre, así que el agente **solo funcionaba si
  Edge no estaba abierto** — es decir, justo después de un WOL, y nunca con el PC ya
  encendido. Chromium sigue exponiendo el puerto solo en loopback.
- **El Edge del usuario tiene que arrancar con el flag**, porque manda la PRIMERA
  instancia: el acceso directo de la barra de tareas lleva
  `--remote-debugging-port=49605` y hay un `.lnk` en la carpeta Inicio que lo lanza así al
  entrar en Windows, de modo que las ventanas que se abran después (desde un enlace, por
  ejemplo) deleguen en ella y hereden el puerto. La contrapartida, aceptada a sabiendas:
  el CDP queda abierto de forma permanente en el navegador donde están todas las sesiones,
  y cualquier proceso local puede controlarlo.
- Si al final no hay CDP, el error **dice qué hacer** (cerrar Edge o arrancarlo con el
  flag) en vez del `ECONNREFUSED` pelado, que no apuntaba a ninguna causa.
- Edge se lanza como proceso DETACHED
  (`subprocess.Popen(..., creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)`), así
  no es hijo de Python y sobrevive cuando el agente termina. La espera es activa hasta que
  el puerto acepta (antes, un `sleep(4)` fijo que se quedaba corto en arranques en frío).
- **Playwright se conecta con `connect_over_cdp(f"http://127.0.0.1:{EDGE_DEBUG_PORT}")`**
  — `127.0.0.1`, **nunca `localhost`**: en Windows ese nombre resuelve primero a `::1` y
  Edge escucha solo en IPv4, así que por `localhost` fallaba con
  `ECONNREFUSED ::1:<puerto>` aunque el navegador estuviera vivo. La llamada
  que devuelve un `Browser`, NO un `BrowserContext`. Hay que usar `browser.contexts[0]`
  para quedarse con el contexto del perfil real (cookies, sesión de Alud/Okta). Al final se
  cierra solo la conexión de Playwright; Edge queda abierto a propósito.
- El perfil sale de `EDGE_PROFILE_DIR` (por defecto el perfil de usuario de Edge).
- **`ALUD_ACCOUNT`** debe estar en `agent/.env`: si está vacío, aparece el selector de
  cuentas y el agente no sabe en cuál pulsar (deja un WARNING en el log).
- **Claude Desktop** está instalado como app de la Microsoft Store: se lanza con
  `explorer.exe shell:AppsFolder\<APPID>` — **no** con el exe `claude.exe`, que es el CLI.
- **Foco de la ventana**: `_focus_claude_window()` usa PowerShell + win32
  (`SetForegroundWindow`, `ShowWindow`) buscando el proceso `claude` por `MainWindowHandle`.
  No uses `AppActivate` por título: falla si el título no coincide exactamente.
- **Clipboard**: el enunciado se escribe a un fichero temporal UTF-8 y
  `Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath ...)` lo carga →
  `Win+V` + Enter (historial) + Enter (enviar). **Nunca interpoles el enunciado** (texto de
  una web externa) dentro del comando de PowerShell — ver la invariante 9 del modelo de seguridad (`CLAUDE.md`).
- El log del agente se escribe en el working directory del proceso, que puede no ser el
  directorio del script cuando lo lanza el Programador de tareas.

## El encargo libre (`accion: "encargo"`)

Además de resolver una entrega de Alud y de abrir el streaming, el agente sabe hacer una
tercera cosa: **un encargo en lenguaje natural**, dictado a Jarvis y ejecutado con Claude
Desktop en el PC. «Que el PC me deje preparado el resumen de esto para cuando llegue.»

La cola de jobs, con sus reintentos, sus eventos y su streaming, existía desde el
principio y servía a un solo caso de uso. Esto es lo que la aprovecha — y es también lo
que obliga a añadir una defensa nueva, porque **rompe la premisa en la que se apoyaban
todas las demás**.

### Por qué hace falta una defensa distinta

Todo lo que el agente ejecutaba hasta ahora venía de una URL, y una URL se puede validar
contra `ALUD_ALLOWED_HOSTS` — de hecho se valida en tres sitios, porque la tabla `jobs`
es escribible con la service key de Supabase y un payload puede llegar sin haber pasado
por el backend.

Un texto libre no se puede validar contra ninguna lista: **no hay forma de comprobar QUÉ
dice**. Así que se comprueba **QUIÉN lo escribió**:

- `POST /jobs` calcula `firma_encargo(instruccion)` = HMAC-SHA256 con `AGENT_TOKEN`, el
  único secreto que backend y agente comparten. Ese endpoint exige JWT de usuario, así
  que la firma transporta hasta el agente el único hecho que importa: **detrás había una
  persona con sesión**.
- La firma se calcula **siempre de cero** y **nunca se acepta la que traiga el cliente**,
  aunque venga correcta. Si se aceptara, la propiedad anterior desaparecería.
- El agente verifica con `encargo_firmado()` (`hmac.compare_digest`) antes de tocar nada,
  y **sin `AGENT_TOKEN` devuelve False**: lo que no se puede comprobar no se ejecuta.
- Sin `AGENT_TOKEN` en el backend, el encargo se rechaza con un **503 que dice qué
  falta**, en vez de encolar algo que el agente rechazará después. Misma moraleja que el
  buscador bloqueado: un error con el arreglo dentro.
- La herramienta de Jarvis va `confirmar: True` — **siempre**. Las demás acciones del PC
  hacen una cosa concreta y acotada; esta abre Claude Desktop con la sesión del usuario
  iniciada en todo, así que cae claramente del lado de proponer.

### El camino hasta Cowork es UNO

`_pegar_en_cowork()` está extraído a propósito: hay dos encargos distintos (la entrega de
Alud y el encargo libre) y un solo camino hasta Claude Desktop. Ese camino es el que
tiene la propiedad que no se puede perder — la instrucción **nunca** se interpola en un
comando de PowerShell, se escribe a un fichero temporal UTF-8 y `Set-Clipboard` lo lee de
ahí. Duplicarlo sería duplicar el sitio donde volver a equivocarse.

La instrucción va delimitada entre marcadores igual que el enunciado de Alud, aunque aquí
el texto salga del usuario: lo ha redactado un modelo a partir de lo que dictó, el formato
ya está probado y mantenerlo no cuesta nada. Y lleva dentro las dos reglas de siempre,
que existen porque **el usuario no está delante**: nada irreversible (ni enviar, ni
publicar, ni comprar, ni borrar) y nada de esperar una respuesta que no va a llegar.

<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Moodle: las entregas de la uni

Desde el 2026-10-07 las entregas salen de Moodle (Alud), no de apuntarlas a mano. Hay
**dos piezas**, y no son dos formas de hacer lo mismo:

| | Qué hace | Dónde vive | Cuándo corre |
|---|---|---|---|
| **La sincronización** | Lleva las entregas pendientes al calendario, las mueve si cambia la fecha, las tacha al entregarlas y avisa si una vence pronto | `backend/main.py`, sección «MOODLE (entregas)» | Sola, desde el tick de Home Assistant |
| **El servidor MCP** | Las 24 herramientas de [moodle-mcp](https://github.com/loyaniu/moodle-mcp): notas, materiales, foros, progreso, carga de trabajo por semanas | `docker/moodle-mcp/`, contenedor en `caja` | Cuando Jarvis pregunta |

Lo que tiene que pasar **sin que nadie pregunte** va en el backend, con tests y en el
diff. Lo que es **para preguntar** va por MCP, que es justo para lo que existe. La misma
frontera que con n8n (`docs/N8N.md`).

## La decisión de fondo: Moodle alimenta el calendario, no tiene widget propio

Todo lo que el proyecto ya sabía de entregas se apoya en eventos con `ENTREGAS_MARKER`
(📚) en el título, en el calendario de clases: el widget «Entregas pendientes», «Lo
siguiente», el aviso al salir de la uni y el botón de resolver con el agente. Si Moodle
escribe esos mismos eventos, **todo eso funciona solo** y no hay una segunda lista de
entregas que pueda decir otra cosa que la primera.

Cada entrega es un evento de media hora que **termina a la hora de entrega**, en el
calendario `CLASSES_CALENDAR` (o en el de por defecto si no existe):

```
📚 Práctica 2: sockets (Redes de Computadores)
alud_url: https://alud.deusto.es/mod/assign/view.php?id=12345
moodle_id: 678
```

- **Termina a la hora, no empieza**: Moodle pone muchas entregas a las 00:00 del día
  siguiente, y un evento que empezara ahí caería el día equivocado.
- **`alud_url:`** solo si el host está en `ALUD_ALLOWED_HOSTS` (invariante 7 de
  `CLAUDE.md`); si no, va como `Moodle: <url>` y el botón de resolver no se enciende.
- **`moodle_id:`** es lo que permite reconocer el evento aunque se pierda la tabla.
- `showAs: free` y sin recordatorio de Outlook: una fecha límite no es tiempo ocupado
  (`huecos_libres` no tiene que esquivarla) y el aviso de verdad es el nuestro.

## Qué hace cada pasada (`_moodle_sincronizar`)

Pregunta a Moodle con `core_calendar_get_action_events_by_timesort`, la misma lista de
pendientes que enseña la app del móvil: **solo devuelve lo que todavía pide que hagas
algo**. Incluye las vencidas de los últimos `MOODLE_VENCIDAS_DIAS`.

| En Moodle… | En el calendario | En la tabla `moodle_entregas` |
|---|---|---|
| Aparece una nueva | Se crea el evento, o **se adopta** el que ya hubiera | Fila nueva, `pendiente` |
| Cambia la fecha o el nombre | Se mueve / renombra el evento | Se actualiza |
| Deja de estar pendiente | 📚 → ✅ (el evento se queda: es tu historial) | `entregada` |
| Se sale de la ventana sin entregar | Nada: ya es pasado y no sale en el widget | `fuera` |

Reglas que lo sostienen:

- **Se adopta antes de crear.** Antes de esto las entregas las metía en el calendario la
  rutina de ALUD, con el mismo marcador. Se reconoce un evento como esta entrega por el
  `moodle_id:` del cuerpo, por la `alud_url` o por nombre + fecha (±1 día). **Si no se
  puede leer el calendario, no se crea nada**: crear a ciegas duplicaría lo que hubiera.
  Con la sincronización en marcha, **esa rutina sobra**: apágala, o cada entrega que meta
  la adoptará esto y la reescribirá con la fecha de Moodle.
- **Solo se tacha lo que falta si la lista está completa.** Moodle devuelve 50 como
  mucho (`MOODLE_LIMITE`); con 50 resultados la lista puede estar cortada, y tachar una
  entrega porque no cupo en la página sería decirte que está hecha cuando no.
- **Lo que borras no vuelve.** Si borras el evento, Graph responde 404 al moverlo y la
  fila se queda con `outlook_id = '-'`: no se vuelve a crear. Lo que sí pasa si lo
  MUEVES es que vuelve a la fecha de Moodle, porque quien manda en la fecha es Moodle.
- **Sin Outlook conectado se guarda igual**, sin `outlook_id`, y el evento se crea en la
  pasada siguiente. Una que no se pudo tachar por lo mismo se queda `pendiente` y se
  reintenta.
- **«Desaparecer» no es solo entregar.** También desaparece si te dan de baja del curso o
  el profesor borra la tarea. El ✅ quiere decir «ya no está pendiente en Moodle», que es
  lo único que se sabe.

## Los avisos (`_moodle_avisar`)

Por `_apuntar_aviso`, así que heredan presupuesto, silenciado y memoria. Solo con
`REGLAS_PROACTIVAS`; la sincronización corre igual sin ellas.

- **`moodle_vence`** (prioridad alta): una entrega que vence en menos de
  `MOODLE_AVISO_HORAS` (36 h) **y sigue sin entregar**. Es el que importa y solo Moodle
  puede darlo bien: el calendario no sabe si ya la subiste. 36 h y no 24 porque casi todas
  vencen a las 23:59, y 24 h antes es avisar a medianoche. La huella lleva la fecha: si te
  amplían el plazo, vuelve a avisar.
- **`moodle_nueva`** (prioridad baja): las nuevas, **todas en un aviso**. La primera vez
  pueden ser quince, y quince avisos se comerían el presupuesto de tres días. Una nueva
  que ya vence pronto va solo por el de arriba.
- **No se dice dos veces lo mismo**: si el aviso al salir de la uni ya habló de esa
  entrega, `moodle_vence` calla, y al revés (`_moodle_vence_dicho`).

El aviso diario de las 19:00 (`_motivos_proactivos`) mira solo el calendario por defecto,
no el de clases, así que no se cruza con estos.

## Jarvis

- **`moodle_entregas`** (consulta, directa): lo pendiente, preguntado a Moodle en el
  momento. También en el MCP del teléfono. No se anuncia sin `MOODLE_URL` y `MOODLE_TOKEN`.
  El resultado va envuelto en `_AVISO_WEB`: nombres y cursos los escribe el profesorado.
- **El servidor `moodle`** por MCP, para todo lo demás («¿qué nota llevo en Redes?»,
  «¿qué materiales hay para la práctica 2?», «¿qué semana voy más cargado?»).

## El botón de resolver: el enunciado, sin entrar en Alud

Desde el 2026-10-07, al pulsar «resolver» en una entrega **el backend trae el enunciado de
Moodle** y el agente del PC se lo da hecho a Cowork. Antes, Cowork entraba en Alud: abría
la entrega en Edge, iniciaba sesión —con el push de Okta, y nadie delante para aceptarlo—,
la leía y rellenaba la respuesta allí.

Eso último era peligroso, y no se veía. Las entregas de Alud que se miraron (las dos
pendientes ese día) **se entregan subiendo un fichero y tienen los borradores
desactivados**: con esa configuración, guardar un fichero en la entrega ya es entregarla.
El «rellénalo pero no pulses enviar» de la instrucción no protegía nada. Ahora Cowork no
entra en Alud: deja la solución en una carpeta del PC y la subes tú.

```
POST /jobs (resolver_alud)
   └─ _moodle_enunciado(alud_url)      cmid de la URL → core_course_get_course_module
      │                                 → mod_assign_get_assignments → la tarea por cmid
      └─ payload.entrega + firma_entrega (HMAC con AGENT_TOKEN, como el encargo)
agente
   ├─ entrega_firmada() o no se ejecuta
   ├─ <Entregas>\<asignatura>\<entrega>\ENUNCIADO.md
   ├─ cada adjunto ← GET /jobs/{id}/adjunto/{n} (el backend lo baja de Moodle)
   └─ Cowork, con el enunciado delimitado como DATO y la carpeta donde dejar «SOLUCION…»
```

- **La tarea se busca por `cmid`** (el `id=` de `/mod/assign/view.php`), no por el
  `instance` del evento de calendario: comprobado contra Alud, no coincide con el id de la
  tarea.
- **Con el texto solo no basta.** De las dos entregas pendientes del día, una tenía el
  enunciado casi entero en un PDF adjunto y la otra no tenía ni texto ni adjuntos (estará
  en los materiales del curso). Por eso van los adjuntos, y por eso Cowork tiene además el
  servidor moodle-mcp para buscar materiales (ver abajo).
- **El token de Moodle no sale de `caja`.** Los adjuntos los baja el backend y el agente se
  los pide por job e índice, nunca por URL: así el endpoint no es un proxy que se lleve el
  token a donde le digan. Antes de pedir nada comprueba la firma de la entrega, que cubre
  las URLs: solo baja lo que el propio backend apuntó al encolar, y solo de
  `/webservice/pluginfile.php/` del host de `MOODLE_URL`.
- **Moodle contesta los errores de fichero con un 200.** Sin token, o con uno caducado,
  `pluginfile.php` devuelve `200` y un JSON de error. Se mira el `Content-Type`, no solo el
  código, o el «adjunto» sería el mensaje de error.
- **Sin enunciado, el camino de antes.** Si Moodle no contesta o la entrega no es una tarea
  (un evento metido a mano), el job sale igual y el agente abre la entrega en Edge, como
  siempre, pero también le pide a Cowork que deje la solución en una carpeta y no toque
  Alud. Y una entrega **con** enunciado cuya firma no cuadra no cae a ese camino: eso es un
  payload manipulado, no un Moodle caído.
- **La carpeta** es `ENTREGAS_DIR` del `agent/.env`; sin ella, `Entregas` dentro de la
  carpeta de ficheros de Cowork (`coworkUserFilesPath` en `claude_desktop_config.json`),
  que es la que Cowork puede tocar sin pedir permiso. Un reintento reescribe el enunciado y
  los adjuntos y no toca lo demás: lo que Cowork dejara la otra vez sigue ahí.

### Cowork con moodle-mcp

El mismo servidor que usa Jarvis, conectado también a Claude Desktop en el PC, para que
Cowork busque apuntes y materiales por su cuenta (`find_relevant_materials` con el id de
la tarea, que va en la instrucción). Son las 24 herramientas de solo lectura; ninguna
descarga ficheros, que es por lo que los adjuntos van aparte.

Claude Desktop solo habla stdio con un servidor local, así que va por el puente
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) (necesita Node), en
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
"mcpServers": {
  "moodle": {
    "command": "npx",
    "args": ["-y", "mcp-remote@0.14.3", "http://caja:8765/mcp", "--allow-http",
             "--header", "Authorization:${MOODLE_AUTH}"],
    "env": {"MOODLE_AUTH": "Bearer <MOODLE_MCP_TOKEN>"}
  }
}
```

- **Por el nombre del tailnet (`caja`), no por la IP**: el PC no está siempre en casa.
- **`--allow-http`** porque mcp-remote rechaza http sin él. La llave viaja en claro por la
  LAN o cifrada por WireGuard en el tailnet, igual que con Jarvis.
- **La llave va en `env` y la cabecera sin espacio tras los dos puntos**: es la forma que
  documenta mcp-remote para Windows, donde `npx` parte los argumentos por los espacios.
- **Versión fija**, por lo mismo que en el `Dockerfile`.
- Claude Desktop lee este fichero **al arrancar**: tras cambiarlo hay que cerrarlo del todo
  (también de la bandeja) y volver a abrirlo.

## El servidor MCP (`docker/moodle-mcp/`)

El paquete original solo habla por stdio (lo que pide Claude Desktop). `servidor.py` lo
levanta por Streamable HTTP sin tocar una línea suya, y le añade lo que por HTTP no es
opcional (el porqué de cada cosa, en el propio fichero):

1. **Una llave** (`MOODLE_MCP_TOKEN`, ≥ 32 caracteres; sin ella no arranca).
2. **Las 24 herramientas declaradas de solo lectura** (`readOnlyHint`): lo son, y sin la
   anotación Jarvis pediría confirmar cada consulta.
3. **El token de Moodle por POST**: el original lo manda en la query, y un Moodle caído
   devolvía el token en claro dentro del texto del error, como resultado de la
   herramienta. Comprobado el 2026-10-07.
4. Sin la protección de DNS rebinding del SDK, que solo admite `Host: localhost`.

**Versiones fijas, todas** (`Dockerfile`): moodle-mcp 0.2.1 **no arranca con `mcp` 2.x**
(importa `mcp.server.fastmcp`, que ya no existe), y es lo que pip instala hoy por defecto.
Subir moodle-mcp obliga a volver a mirar que ninguna herramienta escribe.

## Puesta en marcha

1. **El token.** En Alud: Preferencias → Claves de seguridad
   (`/user/managetoken.php`), el de «Moodle mobile web service». Si con el inicio de
   sesión único no aparece ahí, el de la app móvil vale igual.
2. **La migración** `supabase/migrations/20261007_moodle.sql`, el mismo día.
3. **El backend**, en su `.env` de `caja`: `MOODLE_URL=https://alud.deusto.es` y
   `MOODLE_TOKEN=...`. Desplegar y llamar una vez a `POST /moodle/sincronizar` (o esperar
   media hora) para traer lo que hay.
4. **El contenedor MCP** (opcional, para las 24 herramientas): copiar `docker/moodle-mcp/`
   a `~/docker/moodle-mcp/` de `caja`, crear su `.env` desde `.env.example` y
   `docker compose up -d --build`. Luego, en el `.env` del backend:
   `JARVIS_MCP_SERVERS={"moodle":{"url":"http://<IP de caja>:8765/mcp","token":"<MOODLE_MCP_TOKEN>"}}`
   (si ya hay otros servidores, se añade al mismo objeto).
5. **Apagar la rutina de ALUD** que metía las entregas a mano en el calendario.

El mismo contenedor sirve para una sesión de Claude Code:
`claude mcp add --transport http moodle http://<IP de caja>:8765/mcp --header "Authorization: Bearer <MOODLE_MCP_TOKEN>"`.

## Variables

`MOODLE_URL`, `MOODLE_TOKEN`, `MOODLE_AL_CALENDARIO` (1), `MOODLE_CADA_MIN` (30),
`MOODLE_AVISO_HORAS` (36), `MOODLE_VENCIDAS_DIAS` (7), `MOODLE_ADJUNTO_BYTES` (25 MB).
Una a una en `backend/.env.example`. En el agente, `ENTREGAS_DIR`.

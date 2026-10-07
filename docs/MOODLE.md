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
`MOODLE_AVISO_HORAS` (36), `MOODLE_VENCIDAS_DIAS` (7). Una a una en `backend/.env.example`.

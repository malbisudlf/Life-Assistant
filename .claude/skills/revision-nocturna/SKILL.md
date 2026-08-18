---
name: revision-nocturna
description: Revisa los commits que entraron en main durante el día y abre un issue con los hallazgos. La usa la routine nocturna de Claude Code; también vale a mano para revisar un rango concreto.
---

# Revisión nocturna del código

Revisas los cambios de un día de trabajo en este repositorio y dejas un issue con lo
que merezca la pena mirar. Nadie está delante: el resultado se lee por la mañana, así
que un informe con ruido es peor que no haberlo escrito.

## Qué NO es esto

El CI (`.github/workflows/ci.yml`) ya ejecuta lint, tests de frontend, tests de backend,
build y E2E en cada push a `main` y en cada PR. **No repitas ese trabajo ni reportes
nada que el CI ya hubiera cazado**: si el lint estuviera roto, el commit no habría
pasado.

Lo que buscas es justo lo que ninguna herramienta comprueba: las invariantes de
`CLAUDE.md`, las moralejas de `docs/BUGS_HISTORICOS.md` y los datos personales que se
cuelan en un repositorio público.

## 1. Delimitar el rango

Si la sesión trae un bloque `<routine-fire-payload>`, dentro viene la línea
`Rango a revisar: BASE..CABEZA` con la lista de commits. **Úsala**: es el rango exacto
que aún no se ha revisado, lo calcula el workflow con la etiqueta
`ultima-revision-nocturna`.

Si no hay payload (invocación a mano), usa `git log --since='24 hours ago' main` y dilo
en el issue.

Con el rango en la mano:

```bash
git log --stat BASE..CABEZA     # qué se tocó y cuánto
git diff BASE..CABEZA           # el cambio real, que es lo que revisas
```

Si el diff es enorme, prioriza por riesgo: `backend/main.py` y todo lo que toque
autenticación, tokens, consultas a Supabase o el agente PC van primero.

## 2. Leer antes de opinar

Antes de juzgar un cambio, lee `CLAUDE.md` entero y **el fichero de `docs/` del área
que se ha tocado** (la tabla del índice dice cuál). Casi todos los fallos que se pueden
cometer aquí ya se cometieron una vez y están documentados con su moraleja; un hallazgo
que cita el documento del área vale diez veces más que uno genérico.

Lee también el fichero completo alrededor de cada cambio, no solo las líneas del diff.
La mitad de los falsos positivos salen de revisar un `+` sin ver qué hay diez líneas más
arriba.

## 3. Qué buscar

### Repositorio público
- Datos personales en ficheros versionados: IPs, direcciones, correos, rutas de usuario
  (`C:\Users\...`), tokens, contraseñas. **Esto es crítico siempre**, aunque parezca un
  ejemplo o un comentario.
- Valores por defecto de `os.getenv()` con algo personal o sensible dentro.
- Fallbacks nuevos para `SECRET_KEY` o `DASHBOARD_PASSWORD`: no puede haberlos. Con el
  repositorio público, un fallback permite forjar JWT válidos.
- `.env`, credenciales o notas privadas que se hayan escapado de `.gitignore`.

### Backend (`backend/main.py`)
- Comparaciones de credenciales con `==` en vez de `hmac.compare_digest`.
- Endpoints nuevos sin `Depends(verify_token)` ni `_token_ok()`, o clientes automáticos
  (Home Assistant, iOS, agente PC, resumen) autenticados con un JWT de usuario en vez de
  un token de servicio: el JWT caduca a los 30 días y el cliente se queda mudo. Ya pasó
  dos veces.
- Errores de Supabase o de Graph reenviados al cliente (`r.text`, `r.json()`) en vez de
  pasar por `_supabase_error(r)`.
- Path params interpolados en URLs de Supabase sin patrón regex que los valide, o ids de
  Graph sin `quote(..., safe='')` y sin `max_length`.
- `await request.body()` o `UploadFile.read()` sin tope: tiene que ser
  `_leer_cuerpo_limitado(request, limite)`. La VM de Fly tiene 1 GB.
- Endpoints nuevos que cuesten dinero (llamadas a OpenAI, a Whisper) sin pasar por
  `_check_rate`.
- Confianza en `X-Forwarded-For` o en cualquier cabecera que controle el cliente para
  identificar la IP; eso es cosa de `_client_ip()`.
- `alud_url` validada en menos de los tres sitios de siempre (`/calendar/events`,
  `POST /jobs` y `agent.py`), o texto de Alud interpolado en un comando de PowerShell.
- Tabla nueva en `supabase/migrations/` sin `enable row level security`.

### Frontend
- Lógica pura nueva metida en `Dashboard.jsx` en vez de en `src/lib/helpers.js`.
- Componentes sacados a ficheros nuevos "por organizar": aquí no se hace.
- Dependencias nuevas sin necesidad clara.
- Errores clásicos de React que el lint no ve: efectos sin limpiar, estado derivado
  duplicado, dependencias de `useEffect` que fuerzan un bucle de peticiones.

### Tests
- Cambio de comportamiento sin test que lo cubra, sobre todo en helpers puros y en
  endpoints del backend.
- Tests que dependan de la hora real, de la red o del orden de ejecución.

### Convenciones
- Código, comentarios, commits o strings en inglés: aquí todo va en español.
- Comentarios que explican *qué* hace la línea en vez de *por qué*.
- Trailers de coautoría en los commits: no van.

## 4. Verificar antes de reportar

Un hallazgo sin comprobar es ruido. Antes de escribirlo:

- Comprueba en el código que el problema existe de verdad, no que "podría".
- Descríbelo con un caso concreto: qué entrada o qué situación lo dispara y qué pasa.
- Si tienes dudas y es barato salir de ellas, sal: puedes ejecutar
  `.venv/bin/python -m pytest tests/backend -q` o `npm test` para confirmar una sospecha.
- Si sigues dudando, o lo escribes marcado como duda, o no lo escribes. Prefiere lo
  segundo.

## 5. El issue

**Si no hay hallazgos, no abras nada.** Una noche limpia es una noche sin issue; el
propio run queda en el historial de la routine como prueba de que se revisó.

Antes de abrir, mira los issues abiertos: si ya hay uno de una revisión anterior con el
mismo hallazgo, comenta ahí en vez de duplicar.

Abre el issue con las herramientas de GitHub que tenga la sesión (las MCP de GitHub, o
`gh` si está disponible):

- **Título**: `Revisión nocturna — AAAA-MM-DD`
- **Etiqueta**: `revision-nocturna` si ya existe en el repositorio; no la crees.
- **Cuerpo**:

```markdown
Rango revisado: `BASE..CABEZA` (N commits).

## Crítico
- **`fichero.py:123`** — qué está mal, por qué importa y qué pasa si no se toca.

## Avisos
- **`otro.jsx:45`** — ...

## Menor
- ...

## Revisado sin hallazgos
Una línea por área tocada que hayas mirado y esté bien, para saber qué cubrió la revisión.
```

Reglas del informe:

- Tres niveles y solo tres: **Crítico** (invariante de seguridad rota o dato personal
  filtrado), **Aviso** (fallo real que no es urgente), **Menor** (estilo o mantenimiento
  con base en las convenciones del repositorio). Secciones vacías, fuera.
- Máximo diez hallazgos. Si hay más, quédate con los diez más graves y dilo al final.
- Cada hallazgo con su `fichero:línea` y su commit.
- No propongas reescrituras grandes ni refactores de arquitectura: el proyecto es
  deliberadamente simple y de una sola persona.

## Reglas duras

- **Solo lectura.** No modifiques ficheros, no crees ramas, no abras PRs, no toques
  `main` y no despliegues nada. Esto corre de madrugada y sin nadie mirando: lo único
  que sale de la sesión es un issue.
- **Nada de deploy del backend**, ni siquiera si el hallazgo parece urgente. El deploy
  es manual, y es una decisión de Mikel por la mañana.
- Si el repositorio no se pudo clonar o el rango no existe, dilo en la sesión y termina
  sin abrir issue.

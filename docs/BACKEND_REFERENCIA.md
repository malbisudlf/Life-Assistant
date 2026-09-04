<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Backend: referencia de endpoints

`backend/main.py` es un FastAPI monolítico. Auth: **JWT** = `Depends(verify_token)`,
**agente** = `verify_agente` (AGENT_TOKEN o JWT), **servicio** = token dedicado.

| Ruta | Auth | Descripción |
|---|---|---|
| `GET /` | — | Estado del backend (salud del servicio, sesión de Graph) |
| `POST /auth/password` | — | Contraseña → JWT. Rate limiting global (`429` + `Retry-After`) |
| `GET /auth/login` | JWT | Devuelve la `auth_url` del flujo OAuth de Microsoft Graph, con `state` firmado |
| `GET /auth/callback` | `state` | Callback OAuth de Microsoft (lo llama Microsoft, verifica el `state`) |
| `GET /calendar/events` | JWT | Eventos de los próximos 30 días (Graph). Extrae `alud_url` del cuerpo HTML |
| `POST /calendar/events` | JWT | Crea evento en Outlook — `subject`, `start`, `end` (ISO sin zona, se asume `TIMEZONE`), `location?`, `is_all_day?`, `calendar_id?` |
| `PATCH /calendar/events/{event_id}` | JWT | Edita un evento — mismos campos salvo `calendar_id` (no se puede mover de calendario); solo manda los campos presentes en el body |
| `DELETE /calendar/events/{event_id}` | JWT | Borra un evento. Un 404 de Graph cuenta como borrado: para quien borra, "no existe" y "ya no existe" son lo mismo |
| `GET /calendar/classes` | JWT | Eventos del calendario de clases (`CLASSES_CALENDAR`) — 60 días, máx. 200 |
| `GET /calendar/calendars` | JWT | Lista de calendarios disponibles |
| `POST /maps/departure` | JWT | Hora de salida (Google Maps Distance Matrix). `mode: "driving"` (con tráfico) o `"walking"` |
| `GET /weather` | JWT | Clima (Open-Meteo). `?lat&lon` opcionales; si no, `WEATHER_LAT/LON` |
| `GET /ideas` | JWT | Lista de ideas |
| `POST /ideas/audio` | JWT | Audio → Whisper → GPT-4o-mini → Supabase. Rate limit por IP (llamada de pago) |
| `POST /ideas/text` | JWT | Texto escrito → GPT-4o-mini → Supabase (mismo procesado, sin transcripción) |
| `DELETE /ideas/{idea_id}` | JWT | Elimina una idea |
| `GET /export` | JWT | Exportación de datos |
| `GET/POST /clothing`, `DELETE /clothing/{item_id}` | JWT | Widget **temporal** de conteo de ropa (ver `docs/FRONTEND.md`) |
| `GET /ha/events/soon` | servicio | Próximos eventos para las notificaciones de Alexa |
| `POST /ha/presencia` | servicio | HA empuja dónde estás (zona, `en_casa`, lat/lon). Acumula la serie diaria `time_at_home` |
| `POST /ha/entidades` | servicio | HA empuja el catálogo de la casa (id, nombre, estado). Sin él Jarvis no sabe qué dispositivos hay |
| `GET /ha/ordenes-pending` | servicio | HA sondea y ejecuta lo que salga. Devuelve y **vacía** la cola; descarta lo que lleve más de `CASA_ORDEN_TTL` esperando |
| `GET /ha/avisos-pending` | servicio | HA sondea y los manda a la app del móvil. Devuelve y **vacía** la cola; sondearlo es lo que declara vivo el canal |
| `GET /avisos/estado` | JWT | Por dónde salen los avisos (móvil o correo) y cuánto hace que HA los recogió |
| `POST /avisos/probar` | JWT | Manda un aviso de prueba por el canal que toque |
| `POST /avisos/{aviso_id}/util` | servicio o JWT | La respuesta a los botones útil / no útil de la notificación |
| `POST /avisos/{aviso_id}/apagar` | servicio o JWT | El botón «Apagar» del aviso de salir de casa: encola el apagado de las entidades que llevaba ese aviso |
| `POST /revision/hallazgos` | servicio (`REVISION_TOKEN`) | El workflow avisa de que la revisión nocturna abrió un issue: apunta la decisión y encola el aviso con botones |
| `POST /revision/{aviso_id}/accion` | servicio o JWT | La respuesta a esos botones: `arreglar` lanza la sesión que lo arregla, `nada` lo descarta |
| `POST /averia` | servicio (`REVISION_TOKEN`) | El workflow avisa de que el CI se ha roto en `main`: lanza la sesión que lo arregla, sin preguntar y sin avisar |
| `POST /revision/pr-listo` | servicio (`REVISION_TOKEN`) | El workflow avisa de que el CI ha puesto en verde el PR del arreglo: deja el aviso con botones y llama por teléfono |
| `POST /despliegue/{aviso_id}/accion` | servicio o JWT | La respuesta a esos botones: `desplegar` mergea el PR y lanza el deploy, `nada` lo descarta. **La única ruta que toca producción** |
| `POST /sesion/aviso` | servicio (`SESION_TOKEN`) | Una sesión de Claude Code deja «esto me pediste, esto he hecho»: guarda el contexto y encola el aviso con sus botones |
| `POST /sesion/{aviso_id}/accion` | servicio o JWT | La respuesta al botón «Vale»: cierra el aviso sin disparar nada |
| `GET /llamada/pendiente` | JWT | Qué anunciar al descolgar: primero el despliegue esperando permiso, si no el aviso de sesión más reciente. Solo lee |
| `POST /telefono/voz` | firma de Twilio | Lo que Twilio pregunta al descolgar. Devuelve el TwiML que abre el puente de voz |
| `WS /telefono/media` | JWT de un solo uso (`purpose: llamada`) | El audio de la llamada en los dos sentidos: Whisper → Jarvis → ElevenLabs |
| `GET /presencia` | JWT | Ubicación actual para el panel de estado (devuelve lo caducado, marcado) |
| `POST /wake-pc` | JWT | Marca `_wol_pending` |
| `GET /ha/wol-pending` | servicio | HA sondea cada 30s: devuelve y limpia el flag WOL |
| `POST /relaunch-agent` | JWT | Marca `_agent_relaunch_pending` |
| `GET /ha/agent-relaunch-pending` | servicio | HA lo recoge y relanza el agente por SSH |
| `POST /shutdown-pc` · `POST /suspend-pc` | JWT | Marcan `_pc_power_action` |
| `GET /ha/pc-power-pending` | servicio | HA lo recoge y apaga/suspende el PC por SSH |
| `POST /jobs` | JWT | Crea job en cola (valida `alud_url`, `dedupe_key` único) |
| `GET /jobs/pending` | agente | Lo que sondea `agent.py`. **El corte temporal va como `Z`, nunca `+00:00`** |
| `GET /jobs/by-id/{job_id}` | JWT | Job por ID |
| `POST /jobs/{job_id}/claim` · `/start` · `/finish` | agente | Transiciones de estado (PATCH condicional, atómicas) |
| `POST /jobs/{job_id}/events` | agente | Evento de progreso (stages) |
| `GET /jobs/{job_id}/events` | JWT | Eventos de un job (lo consume la barra de progreso) |
| `POST /jobs/{job_id}/retry` | JWT | Reintenta un job fallido (máx. `MAX_JOB_ATTEMPTS`) |
| `POST /agents/heartbeat` | agente | El agente reporta que está vivo |
| `GET /agents/{agent_id}` | JWT | Estado de un agente (p. ej. `pc-mikel`) |
| `GET /training/summary` | JWT | Sesiones pendientes, horas, dinero, fechas |
| `POST /training/sessions` · `DELETE /training/sessions/{session_id}` | JWT | Añadir/borrar sesión `{date, duration_hours}` |
| `PATCH /training/client` | JWT | Precio/hora y sesiones por cobro |
| `POST /training/payments` | JWT | Marca cobro de hoy (calcula el importe automáticamente) |
| `GET /finanzas/resumen` | JWT | Cartera de Indexa Capital: valor, aportado, plusvalía, mezcla y serie. `?refrescar=true` salta la caché. Sin `INDEXA_TOKEN` devuelve `configurado: false`, no un error (ver `docs/FINANZAS.md`) |
| `GET /finanzas/etfs` | JWT | Cartera manual de ETFs: participaciones, aportado, precio actual y ganancia por ETF (vía Yahoo Finance). `?refrescar=true` salta la caché de precios (ver `docs/FINANZAS.md`) |
| `POST /finanzas/etfs` | JWT | Da de alta un ETF nuevo a trackear `{ticker, nombre, simbolo_twelvedata, bolsa_twelvedata}`. Sin botón en el frontend, se usa por curl |
| `POST /finanzas/etfs/{ticker}/aportaciones` | JWT | Registra una aportación `{fecha, importe_eur, hora?}`; calcula las participaciones con el precio horario (si hay `hora`) o de cierre diario real de esa fecha |
| `DELETE /finanzas/etfs/{ticker}/aportaciones/{id}` | JWT | Borra una aportación mal metida (no hay PATCH: para corregirla se borra y se vuelve a crear) |
| `POST /health/ingest` | servicio | Webhook de Health Auto Export (métricas + workouts) |
| `POST /health/ingest/simple` | servicio | iOS Shortcut — acepta dict único o NDJSON |
| `GET /health/metrics?days=30` | JWT | Métricas de los últimos N días agrupadas por nombre + `last_sync` + `reloj` (qué días estuvo puesto y de qué fuente es cada métrica) + `ajustes` (el corte por cambio de dispositivo) |
| `PATCH /health/ajustes` | JWT | Fija o borra la fecha del cambio de dispositivo de salud (`cambio_dispositivo`, `dispositivo`). Rechaza fechas futuras: un corte por delante de hoy dejaría las líneas base sin ninguna referencia |
| `GET /health/latest` | JWT | Último valor de cada métrica |
| `GET /health/diagnostico` | JWT | Por métrica: último día con MEDIDA, huecos intercalados, qué fuente la escribe y filas de relleno; más la última escritura de cada cliente. `?dias=` (1-365) |
| `PATCH /health/sleep/{date}/exclude` | JWT | Alterna `extra.excluded`: anula/restaura una noche |
| `GET /brief` | JWT | Datos del día en crudo (sin interpretar) |
| `POST /brief/send` | `BRIEF_TOKEN` | Red de seguridad: envía el resumen si hoy no ha salido. `?forzar=1` se salta la idempotencia |
| `GET /brief/ajustes` · `PATCH /brief/ajustes` | JWT | El interruptor del resumen: activo/apagado, pausa con fecha y si el de hoy ya salió |
| `GET /informe` | JWT | Datos del informe semanal (medias por semana) sin mandar nada |
| `POST /informe/send` | `BRIEF_TOKEN` | Manda el informe semanal. `?forzar=1` se salta el día y la hora, **no** la reserva |
| `POST /despertar` | `BRIEF_TOKEN` | "Ya estoy despierto" (Atajo del iPhone). Manda el resumen si no ha salido |
| `POST /ha/brief-tick` | servicio | Reloj de respaldo: HA lo sondea y, pasada `BRIEF_HORA_TOPE`, manda el resumen |
| `GET /logs` · `DELETE /logs` | JWT | Registro persistente para el panel de ajustes |
| `POST /jarvis` | JWT | Un turno de conversación con herramientas (incluye búsqueda y lectura web). Rate limit por IP (llamada de pago) |
| `POST /jarvis/voz` | JWT | El mismo turno que `/jarvis`, retransmitido por SSE: un evento `herramienta` (con la frase que decir en voz alta) antes de usar cada una, eventos `texto` con la respuesta según se escribe, y un `fin` con el resultado más `por_decir` (lo que aún no ha salido por el altavoz). Se consume con `fetch`+reader, no con `EventSource` |
| `POST /jarvis/ejecutar` | JWT | Ejecuta una acción que Jarvis dejó propuesta. Solo admite las marcadas `confirmar` |
| `POST /voz/token` | JWT | Dice con qué voz se habla y emite el permiso si hace falta. Devuelve `proveedor`: `azure` (sin token — su audio va por `/voz/decir`) o `elevenlabs` (token de un solo uso, 15 min, para el WebSocket). Azure va primero cuando está configurado. 503 si no hay ninguna. Rate limit por IP. Ver `docs/JARVIS_VOZ.md` |
| `POST /voz/decir` | JWT | Sintetiza UNA frase con Azure Speech y la devuelve como `audio/mpeg`. El texto va escapado a SSML: lo escribe el modelo a partir de lo que oye, así que entra como dato y nunca como marcado. 503 si Azure no está configurado, 502 si no contesta o devuelve un 200 vacío. Rate limit por IP |

**CORS**: los orígenes permitidos salen de `CORS_ORIGINS` (por defecto
`http://localhost:5173` y el dominio de Vercel). Si añades otro origen de producción,
va ahí — no en `allow_origins` hardcodeado.

## Variables de entorno

`backend/.env.example` es la referencia completa y comentada; `backend/check_config.py`
verifica que la configuración está bien. Resumen:

**Obligatorias** (sin ellas el backend no arranca): `SECRET_KEY`, `DASHBOARD_PASSWORD`.

**Supabase**: `SUPABASE_URL`, `SUPABASE_KEY` (service_role, **nunca** la anon key).

**Microsoft Graph**: `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`.

**Servicios externos**: `GOOGLE_MAPS_API_KEY`, `OPENAI_API_KEY` (opcional de verdad:
sin ella el backend arranca y `/ideas/*` responde 503).

**Finanzas** (todas opcionales; sin `INDEXA_TOKEN` el widget dice que no está conectado):
`INDEXA_TOKEN`, `INDEXA_API_URL`, `INDEXA_CUENTAS`, `INDEXA_TTL_MINUTOS`,
`INDEXA_SERIE_DIAS`. La cartera manual de ETFs no necesita ninguna clave (usa Yahoo
Finance, sin autenticación): `YAHOO_FINANCE_API_URL`, `ETF_PRECIO_TTL_MINUTOS`.

**Tokens de servicio** (valores aleatorios distintos entre sí): `HA_POLL_TOKEN`,
`HEALTH_INGEST_TOKEN`, `BRIEF_TOKEN`, `AGENT_TOKEN`.

**Resumen diario**: `BRIEF_TO`, `BRIEF_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD` (con Gmail y 2FA: una contraseña de aplicación), `ENTREGAS_MARKER`.

**Personalización**: `TIMEZONE`, `HOME_ADDRESS`, `CLASSES_CALENDAR`, `CORS_ORIGINS`,
`WEATHER_LAT`/`WEATHER_LON`, `ALUD_ALLOWED_HOSTS`.

**Jarvis** (ninguna obligatoria; reutiliza `OPENAI_API_KEY`): `JARVIS_MODEL`,
`JARVIS_MODEL_ACCION`, `JARVIS_MAX_VUELTAS`, `JARVIS_MAX_HISTORIAL`, `JARVIS_MAX_MENSAJE`,
`JARVIS_MAX_TOKENS`, `JARVIS_MAX_TOKENS_VOZ`, `JARVIS_VOZ_MODELO_DIRECTO`,
`JARVIS_RESERVA_RAZONAMIENTO`,
`JARVIS_MAX_REQUESTS`, `JARVIS_WINDOW_SECONDS`, `PC_AGENT_ID`, `JARVIS_REPO`, `JARVIS_WEB`,
`JARVIS_WEB_RESULTADOS`, `JARVIS_WEB_MAX_BYTES`, `JARVIS_WEB_MAX_TEXTO`,
`TAVILY_API_KEY`, `BRAVE_API_KEY`, `JARVIS_MAX_RECUERDOS`, `JARVIS_RECUERDO_MAX`,
`JARVIS_MCP_SERVERS`, `JARVIS_MCP_MAX_TEXTO`, `CASA_ORDEN_TTL`,
`JARVIS_DESTILAR`, `JARVIS_DESTILAR_DESDE`, `JARVIS_DESTILAR_MINUTOS`,
`JARVIS_PROACTIVO`, `JARVIS_PROACTIVO_HORA`, `JARVIS_PROACTIVO_SIN_ENTRENO`,
`VIGILANTE`, `VIGILANTE_CADA_MIN`, `VIGILANTE_MIN_ERRORES`, `VIGILANTE_VENTANA_DIAS`,
`VIGILANTE_ISSUES`, `AVISOS_MAX_DIA`, `AVISOS_NO_UTILES`, `AVISOS_REPETIR_DIAS`,
`AVISOS_HORA_DIFERIDOS`, `REGLAS_PROACTIVAS`, `SALIR_VENTANA_MIN`, `SALIR_ANTES_MIN`,
`REGLAS_HORA_NOCHE`, `REGLAS_HORA_MANANA`, `MADRUGON_HASTA`, `SUENO_OBJETIVO_H`,
`PREP_MANANA_MIN`, `HUECO_ENTRENO_MIN`, `PC_ENTIDAD`, `VIGILANCIAS_MAX`,
`VIGILANCIA_CADA_MIN`, `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_CARPETA`,
`CORREO_CADA_MIN`, `CORREO_HORAS`, `CORREO_MAX`, `REGLAS_USUARIO_MAX`,
`RELOJ_AVISO_ANTES_MIN`, `AVISOS_HORA_SILENCIO`, `AVISO_RETRASO_AVISA_MIN`,
`AVISO_RETRASO_AVERIA_MIN`.

**Opcionales**: `PRESENCE_TTL_MINUTES`, `PRESENCE_MAX_GAP_HOURS`,
`RELOJ_AVISO`, `RELOJ_AVISO_HORA`, `RELOJ_AVISO_NOCHES`,
`AVISOS_MOVIL`, `AVISO_MOVIL_VIVO`, `AVISO_MOVIL_RESCATE`,
`INGESTA_VIGILAR`, `INGESTA_AVISO_HORAS`, `INGESTA_CORREO_HORAS`, `INGESTA_VIGILA_CADA_MIN`,
`INFORME_SEMANAL`, `INFORME_DIA`, `INFORME_HORA`, `INFORME_SEMANAS`,
`BRIEF_DESPERTAR_DESDE`, `BRIEF_DESPERTAR_HASTA`, `BRIEF_HORA_TOPE`,
`BRIEF_DISPARA_SUENO`,
`BRIEF_ECONOMIA`, `BRIEF_ECONOMIA_FEEDS`, `BRIEF_ECONOMIA_MAX`,
`BRIEF_ECONOMIA_HORAS` (los titulares de economía y el término del día
del resumen — ver `docs/BRIEF.md`),
`RUTINA_FIRE_URL`, `RUTINA_FIRE_TOKEN`, `BRIEF_RUTINA_DESDE`, `RUTINA_BETA`,
`REVISION_TOKEN`, `ARREGLO_FIRE_URL`, `ARREGLO_FIRE_TOKEN` (la revisión nocturna
accionable: sin ellas, el issue de la noche sigue saliendo pero no avisa ni se puede
arreglar desde el móvil — ver `docs/REVISION_NOCTURNA.md`),
`AVERIA_CI`, `AVERIA_MAX_INTENTOS`, `DEPLOY_GITHUB_TOKEN`, `DESPLIEGUE_TTL_HORAS`
(el arreglo automático del CI roto y el despliegue con permiso — ver `docs/AVERIAS.md`),
`SESION_TOKEN`, `SESION_FIRE_URL`, `SESION_FIRE_TOKEN`, `SESION_AVISO_TTL_HORAS`
(«avísame»: que una sesión de Claude Code te avise al móvil y puedas contestarle
hablando — ver `docs/AVISAME.md`),
`LLAMADAS`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMERO`,
`TWILIO_MI_NUMERO`, `BACKEND_URL`, `LLAMADA_TTL`, `LLAMADA_MAX_SEG`,
`VOZ_SILENCIO_MS`, `VOZ_UMBRAL_RMS`, `VOZ_MIN_HABLA_MS` (el teléfono: sin ellas no
suena nada y el resto de canales siguen igual — ver `docs/AVERIAS.md`),
`MAX_JOB_ATTEMPTS`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`,
`LOGIN_BLOQUEO_MAX_SECONDS`, `HTTP_TIMEOUT`, `MAX_AUDIO_BYTES`, `MAX_INGEST_BYTES`,
`AUDIO_MAX_REQUESTS`, `AUDIO_WINDOW_SECONDS`, `TRUST_FORWARDED_FOR`, y las de registro
(`LOG_PERSIST`, `LOG_PERSIST_LEVEL`, `LOG_QUEUE_MAX`, `LOG_FLUSH_SECONDS`,
`LOG_RETENTION_DAYS`, `LOG_SLOW_MS`).

**Frontend** (Vercel): `VITE_API_URL`, `VITE_HA_URL`, `VITE_HA_DASHBOARD_PATH`,
`VITE_ENTREGAS_MARKER`. Ojo: el backend no ve las `VITE_*`, por eso `ENTREGAS_MARKER`
está duplicado en los dos lados y **tienen que coincidir**.

**Agente** (`agent/.env`): `AGENT_TOKEN` (mismo valor que en el backend), `LA_API_BASE`,
`LA_TOKEN` (solo respaldo — caduca), `EDGE_PROFILE_DIR`, `ALUD_ACCOUNT`,
`ALUD_ALLOWED_HOSTS`, `APOLLO_EXE`/`APOLLO_SERVICIO`/`APOLLO_TIMEOUT` (con las `SUNSHINE_*` como respaldo),
`VPN_TIPO`/`TAILSCALE_EXE`/`TAILSCALE_SERVICIO`/`VPN_TIMEOUT`,
`PANTALLAS_STREAMING`/`PANTALLAS_RESTAURAR`/`DISPLAYSWITCH_EXE`, `ARRANQUE_ESPERA_RED`.
**Ya no lleva `SUPABASE_URL`/`SUPABASE_KEY`**: se quitaron a propósito (ver "Cola de jobs" en `docs/BACKEND_PATRONES.md`).

## Endpoints añadidos en septiembre de 2026

| Ruta | Auth | Qué hace |
|---|---|---|
| `POST /jarvis/atajo` | `JARVIS_TOKEN` (cabecera) o JWT | Un turno suelto de Jarvis para el Atajo de iOS. Sin historial, siempre `voz`, y dice en voz alta lo que queda pendiente de confirmar. Ver `docs/JARVIS.md` |
| `GET /avisos/enviados?dia=&limite=` | JWT | Los avisos que salieron ese día (por defecto hoy), con hora y con su valoración. Ventana desde la medianoche **local** |
| `GET /avisos/{id}/porque` | JWT | Los valores crudos con los que se disparó ese aviso. `motivo: null` con 200 si no se guardó |
| `GET /gasto?dias=` | JWT | Lo que ha costado el modelo, agregado por boca y por modelo, con el % cacheado y los modelos sin tarifa |

Variables nuevas: `JARVIS_TOKEN`, `ENCARGO_MAX_CHARS`, `GASTO_PERSIST`,
`GASTO_QUEUE_MAX`, `MODELO_TARIFAS`, `TARIFA_AUDIO_MINUTO`, `AUDIO_BYTES_POR_SEGUNDO`.
Todas documentadas una a una en `backend/.env.example`.


# Puesta a punto del PC: streaming remoto (Sunshine/Moonlight)

Checklist para dejar operativo el control remoto del PC desde el móvil. La idea es
que el PC arranque casi "tonto": lo único residente es el **agente efímero**, que al
iniciar Windows mira la cola de jobs, ejecuta lo que haya (resolver Alud o abrir
Sunshine) y se cierra. El botón **"Streaming PC"** del dashboard enciende el PC (WOL)
y encola el job de Sunshine; conectas con **Moonlight** desde el móvil.

> Estos pasos son específicos del PC de Mikel (no forman parte del kit replicable):
> requieren un Windows real con Edge, sesión activa y hardware con WOL.

## 0. Sincronizar el repo en casa (antes de nada)

CLAUDE.md pasó a estar **versionado** en el repo. Si tu copia local tenía un
CLAUDE.md personal (antes estaba ignorado), el `git pull` puede chocar.

- [ ] `git status` **primero**, para ver el estado de CLAUDE.md:
      - Sale limpio → `git pull origin main` sin más.
      - Sale como *untracked* → guárdalo antes: `mv CLAUDE.md CLAUDE.local.md`, luego
        `git pull origin main`. (Git rechaza el pull si sobrescribiría un fichero sin
        trackear: *"untracked working tree files would be overwritten by merge"*.)
      - Sale como *modified* → resuelve el conflicto de merge normal tras el pull.
- [ ] Si tenías notas personales en tu CLAUDE.md, muévelas a un fichero ignorado
      (p. ej. `NOTAS.local.md`) para no volver a chocar.

## 1. Actualizar el agente en el PC

- [ ] `git pull` en la carpeta del repo (trae el `agent/agent.py` efímero + despachador).
- [ ] Reinstalar dependencias si hace falta: `pip install -r backend/requirements.txt`.
- [ ] Revisar el `.env` del agente: `LA_TOKEN`, `ALUD_ACCOUNT`, `ALUD_ALLOWED_HOSTS`.
      **Ya NO hace falta `SUPABASE_URL`/`SUPABASE_KEY`**: el agente pide los jobs
      pendientes al backend (`GET /jobs/pending`) en vez de a Supabase directo. Si tu
      `.env` los tenía, puedes borrarlos.
      Opcional: `SUNSHINE_EXE` (solo si instalas Sunshine fuera de la ruta estándar).

## 2. Instalar Sunshine (host de streaming)

- [ ] Instalar **Sunshine** en el PC.
- [ ] **Desactivar su autoarranque**: Servicios de Windows → `SunshineService` → tipo de
      inicio **Manual**. Lo único residente debe ser el agente; Sunshine lo lanza el
      agente bajo demanda.
- [ ] Confirmar la ruta del ejecutable: `C:\Program Files\Sunshine\sunshine.exe`
      (si es otra, ponerla en `SUNSHINE_EXE`).

## 3. Moonlight en el móvil (emparejar una vez)

- [ ] Instalar **Moonlight** en el móvil.
- [ ] Con Sunshine abierto en el PC, emparejar con el **PIN** (solo la primera vez;
      luego es persistente).

## 4. Que solo el agente arranque con Windows

- [ ] **Auto-login de Windows** (`netplwiz` → desmarcar "los usuarios deben escribir
      contraseña"). Es **obligatorio**: tras el WOL, sin sesión activa no funcionan ni
      pyautogui ni la captura de pantalla de Sunshine.
- [ ] **Task Scheduler** → tarea `LifeAssistantAgent`, disparador **"Al iniciar sesión"**,
      acción: `python.exe` con `agent.py`. Marcar "Ejecutar solo cuando el usuario haya
      iniciado sesión".
- [ ] Confirmar que **WOL está habilitado** en BIOS y en la tarjeta de red (ya lo estaba
      para el flujo de Alud).

## 5. OpenSSH en Windows (para el relanzado por HA) — de forma segura

Necesario solo para el caso "PC ya encendido": el agente efímero ya terminó, así que HA
lo relanza por SSH.

- [ ] Activar **OpenSSH Server**: Configuración → Aplicaciones → Características opcionales
      → "Servidor de OpenSSH". Arrancar el servicio `sshd`.
- [ ] **Solo clave, sin contraseña**: copiar la clave pública de HA a
      `C:\Users\<usuario>\.ssh\authorized_keys` y en `sshd_config` poner
      `PasswordAuthentication no`.
- [ ] Restringir a **red local / VPN**, nunca exponerlo directo a internet.
- [ ] Probar desde HA: `ssh mikel@IP_DEL_PC "schtasks /run /tn LifeAssistantAgent"`.

## 6. Home Assistant (relanzado del agente)

HA sondea el backend y, si hay relanzado pendiente, dispara la tarea del agente por SSH.

```yaml
# configuration.yaml
shell_command:
  relanzar_agente_pc: 'ssh -i /config/.ssh/id_pc mikel@IP_DEL_PC "schtasks /run /tn LifeAssistantAgent"'

command_line:
  - sensor:
      name: agente_pc_relaunch_pending
      command: 'curl -s -H "X-Auth-Token: TU_HA_POLL_TOKEN" https://backend-tender-glow-160.fly.dev/ha/agent-relaunch-pending'
      value_template: "{{ (value_json.pending) | lower }}"
      scan_interval: 30

automation:
  - alias: Relanzar agente PC cuando el dashboard lo pide
    trigger:
      - platform: state
        entity_id: sensor.agente_pc_relaunch_pending
        to: "true"
    action:
      - service: shell_command.relanzar_agente_pc
```

- [ ] Pegar el YAML con tu `HA_POLL_TOKEN` y la IP del PC.
- [ ] Reiniciar HA y comprobar que aparece `sensor.agente_pc_relaunch_pending`.

### Apagar / suspender el PC (botones del widget)

Los botones "Apagar" y "Suspender" no pasan por el agente: HA ejecuta el comando por
SSH directo. Mismo patrón que el relanzado, sondeando `/ha/pc-power-pending`.

```yaml
shell_command:
  apagar_pc:    'ssh -i /config/.ssh/id_pc mikel@IP_DEL_PC "shutdown /s /t 0"'
  suspender_pc: 'ssh -i /config/.ssh/id_pc mikel@IP_DEL_PC "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"'

command_line:
  - sensor:
      name: pc_power_action
      command: 'curl -s -H "X-Auth-Token: TU_HA_POLL_TOKEN" https://backend-tender-glow-160.fly.dev/ha/pc-power-pending'
      value_template: "{{ value_json.action if value_json.action else 'none' }}"
      scan_interval: 30

automation:
  - alias: Apagar/suspender PC cuando el dashboard lo pide
    trigger:
      - platform: state
        entity_id: sensor.pc_power_action
        to: "shutdown"
      - platform: state
        entity_id: sensor.pc_power_action
        to: "suspend"
    action:
      - choose:
          - conditions: "{{ trigger.to_state.state == 'shutdown' }}"
            sequence: [{ service: shell_command.apagar_pc }]
          - conditions: "{{ trigger.to_state.state == 'suspend' }}"
            sequence: [{ service: shell_command.suspender_pc }]
```

- [ ] Pegar también este YAML si quieres los botones de apagar/suspender.

## 7. Desplegar el backend

- [ ] `cd backend && fly deploy` (activa `/relaunch-agent`, `/ha/agent-relaunch-pending`,
      `/shutdown-pc`, `/suspend-pc`, `/ha/pc-power-pending` y `/weather` en producción).
      Si es la primera vez en ese equipo: `fly auth login`.

## 8. Prueba end-to-end

- [ ] **PC apagado** → pulsar "Abrir streaming" en el móvil → el PC se enciende (WOL) →
      el agente arranca → lanza Sunshine → el modal llega a "Sunshine listo".
- [ ] Abrir **Moonlight** y conectar.
- [ ] **PC ya encendido** → pulsar el botón otra vez → HA relanza el agente por SSH y
      Sunshine se abre igual.

## Avisos clave

- **Auto-login obligatorio**: sin sesión activa tras el WOL, ni el agente ni Sunshine
  capturan pantalla.
- **Sunshine con autoarranque OFF**: si lo dejas en automático, se pierde el sentido de
  "solo el agente residente".
- **SSH solo por clave y en red local/VPN**: no expongas el puerto a internet.

## Rendimiento y red

- **Misma red (LAN/Wi-Fi de casa)**: Moonlight detecta el host y va directo. Mejor
  escenario: latencia mínima, 1080p/4K a 60-120 fps según GPU.
- **Fuera de casa**: depende sobre todo de la **subida** de la conexión del PC
  (~20-30 Mbps estables → 1080p60 sobrado) y de la latencia de red. Lo más robusto es
  una **VPN** (WireGuard/Tailscale): desde fuera "estás" en tu LAN, sin abrir puertos.
- En reposo, lo único extra encendido es el servicio OpenSSH inactivo (coste
  despreciable). Sunshine solo consume mientras haces streaming.

---

# Resumen diario por correo (independiente de lo anterior)

No tiene que ver con el streaming: cada mañana el backend manda a tu propio buzón los
datos del día (agenda, clases, entregas, clima, salud, entrenamiento) **en crudo, sin
interpretarlos**. De ahí los recoge tu rutina de Claude Code que ya lee el correo y
compone el resumen diario — por eso el backend no llama a ningún LLM.

> Los pasos 1-4 ya están hechos desde el 31 de julio de 2026 (contraseña de aplicación,
> secretos de Fly y disparador de GitHub): quedan aquí como referencia y para montarlo
> de cero en otra instancia. Lo que sí está pendiente es el **paso 0**.

## 0. Migración y rama (obligatorio antes que nada)

El 1 de agosto de 2026 el correo no llegó. No es que fallara el envío: el cron de
Actions **no se disparó ni una sola vez** (cero ejecuciones con `event=schedule`). El
planificador de GitHub se retrasa y a veces se salta la ejecución sin avisar ni dejar
rastro. La rama `claude/health-data-daily-email-gd2vn4` añade dos disparos de respaldo
y la deduplicación que impide que de los tres salga más de un correo.

- [ ] En Supabase → **SQL Editor**, ejecutar `supabase/migrations/20260801_brief_sends.sql`.
      **Esto primero, antes del merge y del deploy**: el backend nuevo reserva el día en
      esa tabla antes de componer nada, así que sin ella la reserva falla y el resumen
      deja de enviarse *del todo*. Aplicarla antes no rompe nada — el código viejo ni la
      mira.
- [ ] Fusionar `claude/health-data-daily-email-gd2vn4` contra `main` (squash, como el
      resto del repo). **El cron de Actions solo se dispara desde la rama por defecto.**
- [ ] `cd backend && fly deploy`. Fusionar a `main` **no** despliega el backend: Vercel
      es automático, Fly es manual.

## 1. Contraseña de aplicación de Gmail

- [ ] Crearla en [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
      (nombre: «Life Assistant»). Con 2FA activado, la contraseña normal de Gmail
      **no** sirve por SMTP.
- [ ] Si la copias con espacios (`abcd efgh ijkl mnop`), va entre comillas en el
      comando del paso siguiente.

## 2. Configurar el correo en Fly

- [ ] Desde `backend/`, generar el token del disparador: `openssl rand -hex 24`
      (apuntarlo, hace falta otra vez en el paso 4).
- [ ] `fly secrets set`:
      ```bash
      fly secrets set \
        BRIEF_TO=malbisudlf@gmail.com \
        SMTP_HOST=smtp.gmail.com \
        SMTP_PORT=587 \
        SMTP_USER=malbisudlf@gmail.com \
        SMTP_PASSWORD="tu-contraseña-de-aplicacion" \
        BRIEF_TOKEN=el-token-del-paso-anterior \
        ENTREGAS_MARKER="📚"
      ```
- [ ] `ENTREGAS_MARKER` debe coincidir con `VITE_ENTREGAS_MARKER` de Vercel (por
      defecto los dos son 📚, así que si nunca tocaste el de Vercel ya cuadra).

## 3. Desplegar el backend

- [ ] `cd backend && fly deploy`.
- [ ] Comprobar: `curl https://backend-tender-glow-160.fly.dev/` responde
      `{"status": "Life Assistant API running"}`.

## 4. Disparador en GitHub

En el repo, Settings → Secrets and variables → Actions:

- [ ] Pestaña **Variables**: `BACKEND_URL` = `https://backend-tender-glow-160.fly.dev`.
- [ ] Pestaña **Secrets**: `BRIEF_TOKEN` = el mismo valor exacto que en Fly (si no
      coinciden, el envío falla con 403).

## 5. Ajustar la hora del envío

`.github/workflows/resumen-diario.yml` trae **tres** horas (cron en **UTC**, no entiende
zonas horarias):

| Cron (UTC) | Madrid verano | Madrid invierno | Para qué |
|---|---|---|---|
| `30 5 * * *` | 07:30 | 06:30 | el bueno |
| `15 6 * * *` | 08:15 | 07:15 | respaldo |
| `0 7 * * *` | 09:00 | 08:00 | último respaldo |

Son tres porque uno solo no basta: el 1 de agosto de 2026 no se disparó ninguno. De los
tres sale **un solo correo** — el backend reserva el día en `brief_sends` y contesta
`{"omitido": true}` a los que llegan cuando ya salió.

- [ ] Déjale margen antes de que tu rutina lea el correo.
- [ ] Si mueves la hora buena, mueve los respaldos con ella.
- [ ] Revisarlo en los cambios de hora si quieres que la hora local se mantenga fija.
      (El disparador de HA del paso 7 no necesita esto: va en hora local.)

## 6. Probar sin esperar a mañana

- [ ] Actions → **Resumen diario por correo** → *Run workflow*. Debe llegar un correo
      con asunto `Life Assistant — datos del AAAA-MM-DD`.
- [ ] Para ver los mismos datos en JSON sin mandar correo:
      `curl https://backend-tender-glow-160.fly.dev/brief -H "Authorization: Bearer TU_JWT"`
      (el JWT sale de DevTools → Application → Local Storage → `la_token`).

## 7. Disparador de respaldo en Home Assistant (recomendado)

Los tres crons reducen mucho el riesgo, pero siguen dependiendo del mismo planificador
que ya falló una vez: si GitHub se salta los tres, no hay correo. Un segundo disparador
**independiente** lo cubre, y con la deduplicación ya no cuesta nada — llamen uno o
cinco, sale un correo.

HA es el que mejor encaja porque **ya está hablando con este backend**: sondea
`/ha/wol-pending` cada 30s y `/ha/events/soon` cada 60s (sección 6 de arriba). No metes
una pieza nueva, solo una automatización más. Y su disparador va en **hora local**, así
que aplica el cambio de hora solo.

Nota de por qué hace falta algo externo: el backend no puede programarse a sí mismo.
Fly escala a cero, así que a las 07:30 la máquina está dormida y un cron interno no
correría — quien dispara tiene que ser alguien de fuera que la despierte.

- [ ] Guardar `BRIEF_TOKEN` (el mismo valor de Fly) como `la_brief_token` en
      `secrets.yaml`. **Token aparte de `la_poll_token`**, no lo reutilices: cada
      integración lleva el suyo a propósito.
- [ ] En `configuration.yaml`, junto a lo que ya tienes de HA:
      ```yaml
      rest_command:
        la_resumen_diario:
          url: "https://backend-tender-glow-160.fly.dev/brief/send"
          method: POST
          headers: { X-Auth-Token: !secret la_brief_token }
          timeout: 180        # el default son 10s y no basta: Fly arranca en frío

      automation:
        - alias: "Life Assistant: resumen diario"
          trigger: [{ platform: time, at: "07:30:00" }]
          action: [{ service: rest_command.la_resumen_diario }]
      ```
- [ ] Recargar la configuración de HA y probarlo desde Herramientas de desarrollo →
      Acciones → `rest_command.la_resumen_diario`. Como no lleva `?forzar=1`, si el
      correo del día ya salió no llegará otro: eso es exactamente lo que tiene que pasar.
      Para verlo de verdad, mira que la respuesta sea 200.

Pega a tener en cuenta: HA corre en casa, así que un corte de luz o de router lo deja
sin disparar. Por eso se queda **además** de los crons de GitHub, no en su lugar — dos
sistemas que fallan por motivos distintos.

## Si algo falla

- **403** en el workflow → los `BRIEF_TOKEN` de Fly y de GitHub no coinciden.
- **503** → falta alguna variable de SMTP (el mensaje de error dice cuál).
- **404** → el backend no tiene el deploy nuevo (paso 3).
- **502 al reservar el día** → falta la tabla `brief_sends` (migración del paso 0).
- **Error de login SMTP** → estás usando la contraseña normal de Gmail, no la de
  aplicación (paso 1).
- **Llega sin entregas** → `ENTREGAS_MARKER` ≠ `VITE_ENTREGAS_MARKER` (paso 2).
- **No aparece el workflow en Actions** → la rama no está fusionada (paso 0).
- **El workflow sale en verde pero no llega correo** → mira la respuesta del paso: si
  dice `"omitido": true`, es que el correo de hoy ya había salido. Es lo normal en los
  disparos de respaldo y en los de HA.
- **No se dispara ninguno de los tres crons** → no es tuyo, es el planificador de
  Actions. Es justo el caso que cubre el disparador de HA del paso 7.

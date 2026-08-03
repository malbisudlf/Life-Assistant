# Puesta a punto del PC: streaming remoto (Sunshine/Moonlight)

Checklist para dejar operativo el control remoto del PC desde el móvil. La idea es
que el PC arranque casi "tonto": lo único residente es el **agente efímero**, que al
iniciar Windows mira la cola de jobs, ejecuta lo que haya (resolver Alud o abrir
Sunshine) y se cierra. El botón **"Streaming PC"** del dashboard enciende el PC (WOL)
y encola el job de Sunshine; el agente conecta la VPN y abre Sunshine, y tú conectas
con **Moonlight** desde el móvil.

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
- [ ] Revisar el `.env` del agente: `AGENT_TOKEN`, `ALUD_ACCOUNT`, `ALUD_ALLOWED_HOSTS`.
      **`AGENT_TOKEN` sustituye a `LA_TOKEN`**: es un token de servicio que no caduca y
      debe valer lo mismo que la variable `AGENT_TOKEN` del backend. El JWT del
      dashboard duraba 30 días y al expirar el backend respondía 401 a todo, con lo que
      el agente se cerraba en cada arranque diciendo "No hay jobs pendientes".
      **Ya NO hace falta `SUPABASE_URL`/`SUPABASE_KEY`**: el agente pide los jobs
      pendientes al backend (`GET /jobs/pending`) en vez de a Supabase directo. Si tu
      `.env` los tenía, puedes borrarlos.
      Opcional: `SUNSHINE_EXE` (solo si instalas Sunshine/Apollo fuera de la ruta
      estándar), `VPN_TIPO`, `TAILSCALE_EXE`, `VPN_TIMEOUT` (ver paso 3).

## 2. Instalar el host de streaming (Sunshine o Apollo)

- [ ] Instalar **Sunshine** en el PC. (El agente también detecta **Apollo**, su fork:
      mismo ejecutable en `C:\Program Files\Apollo\sunshine.exe`. Con un monitor
      físico siempre conectado no hace falta — su ventaja es la pantalla virtual.)
- [ ] **Desactivar su autoarranque**: Servicios de Windows → `SunshineService` → tipo de
      inicio **Manual**. Lo único residente debe ser el agente; Sunshine lo lanza el
      agente bajo demanda.
- [ ] Confirmar la ruta del ejecutable: `C:\Program Files\Sunshine\sunshine.exe`
      (si es otra, ponerla en `SUNSHINE_EXE`).

## 3. Tailscale en el PC (para conectarte desde fuera de casa)

Fuera de casa Moonlight no llega al PC por IP local, y abrir el puerto de Sunshine a
internet no es una opción. Con Tailscale el PC entra en la misma tailnet que ya usas
para Home Assistant y el móvil lo ve como si estuvierais en la misma LAN.

El problema que resuelve el agente: **el PC arranca sin VPN**. Lo enciende un WOL, no
hay nadie delante iniciando sesión, y el túnel puede quedarse abajo. Por eso el job de
streaming **arranca el servicio de Tailscale y levanta el túnel antes de lanzar
Sunshine**, y reporta la IP de la tailnet al modal del dashboard — esa es la que metes
en Moonlight.

Mismo criterio que con Sunshine: **Tailscale queda apagado en el día a día** (servicio
en manual, sin icono en la bandeja) y solo se enciende cuando pides streaming. Si
prefieres tenerlo siempre conectado, deja el servicio en automático y salta los dos
pasos marcados como *(apagado en el día a día)*: el agente lo detecta corriendo y no
toca nada.

- [ ] Instalar **Tailscale** en el PC e iniciar sesión con tu cuenta (una vez, a mano).
- [ ] Dejarlo en modo desatendido — es lo que hace que el túnel suba sin nadie con
      sesión iniciada, que es justo el escenario tras un WOL:
      ```
      tailscale up --unattended
      ```
      Sin esto, el nodo no aparece en la tailnet y Moonlight no lo encuentra.
- [ ] En la [consola de administración](https://login.tailscale.com/admin/machines),
      **desactivar la caducidad de la clave** (*Disable key expiry*) para esta máquina.
      Si no, cada ~6 meses el nodo pide login otra vez y el streaming deja de funcionar
      desde fuera sin previo aviso.
- [ ] Anotar la IP del PC en la tailnet (`tailscale ip -4`, una `100.x.y.z`): es fija.
- [ ] Comprobar desde el móvil (con Tailscale activo): `ping` o abrir
      `https://100.x.y.z:47990` (la web de Sunshine, con Sunshine arrancado).
- [ ] *(apagado en el día a día)* Servicios de Windows → servicio **`Tailscale`** →
      tipo de inicio **Manual**. El agente lo arranca cuando hace falta.
      Si tu servicio se llama de otra forma, ponlo en `TAILSCALE_SERVICIO`.
- [ ] *(apagado en el día a día)* Quitar el icono de bandeja del arranque:
      Administrador de tareas → pestaña **Inicio** → deshabilitar **Tailscale IPN**.
      El túnel no lo necesita, solo la interfaz gráfica.

> Si el agente no encuentra Tailscale instalado **no falla el job**: lanza Sunshine
> igual y el streaming funciona en la LAN de casa. En el modal verás el aviso
> "VPN no disponible". Para saltarte el paso a propósito: `VPN_TIPO=ninguna`.

## 4. Moonlight en el móvil (emparejar una vez)

- [ ] Instalar **Moonlight** en el móvil (o **Artemis** si has instalado Apollo).
- [ ] Instalar también **Tailscale** en el móvil y dejarlo activo cuando estés fuera.
- [ ] Con Sunshine abierto en el PC, emparejar con el **PIN** (solo la primera vez;
      luego es persistente).
- [ ] Añadir el host **por la IP de la tailnet** (`100.x.y.z`), no por la IP local:
      así el mismo host vale en casa y fuera. En casa Tailscale enruta directo por la
      LAN, sin penalización.

## 5. Que solo el agente arranque con Windows

- [ ] **Auto-login de Windows** (`netplwiz` → desmarcar "los usuarios deben escribir
      contraseña"). Es **obligatorio**: tras el WOL, sin sesión activa no funcionan ni
      pyautogui ni la captura de pantalla de Sunshine.
- [ ] **Task Scheduler** → tarea `LifeAssistantAgent`, disparador **"Al iniciar sesión"**,
      acción: `python.exe` con `agent.py`. Marcar "Ejecutar solo cuando el usuario haya
      iniciado sesión" y **"Ejecutar con los privilegios más altos"**: sin eso el agente
      no puede arrancar el servicio de Tailscale (y lo dirá en el modal). Marcada, la
      tarea no lanza aviso de UAC.
- [ ] Confirmar que **WOL está habilitado** en BIOS y en la tarjeta de red (ya lo estaba
      para el flujo de Alud).

## 6. OpenSSH en Windows (para el relanzado por HA) — de forma segura

Necesario solo para el caso "PC ya encendido": el agente efímero ya terminó, así que HA
lo relanza por SSH.

- [ ] Activar **OpenSSH Server**: Configuración → Aplicaciones → Características opcionales
      → "Servidor de OpenSSH". Arrancar el servicio `sshd`.
- [ ] **Solo clave, sin contraseña**: copiar la clave pública de HA a
      `C:\Users\<usuario>\.ssh\authorized_keys` y en `sshd_config` poner
      `PasswordAuthentication no`.
- [ ] Restringir a **red local / VPN**, nunca exponerlo directo a internet.
- [ ] Probar desde HA: `ssh mikel@IP_DEL_PC "schtasks /run /tn LifeAssistantAgent"`.

## 7. Home Assistant (relanzado del agente)

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

## 8. Desplegar el backend

- [ ] `cd backend && fly deploy` (activa `/relaunch-agent`, `/ha/agent-relaunch-pending`,
      `/shutdown-pc`, `/suspend-pc`, `/ha/pc-power-pending` y `/weather` en producción).
      Si es la primera vez en ese equipo: `fly auth login`.

## 9. Prueba end-to-end

- [ ] **En casa, PC apagado** → pulsar "Abrir streaming" en el móvil → el PC se enciende
      (WOL) → el agente arranca → arranca Tailscale y conecta → lanza Sunshine → el modal llega a
      "Sunshine listo" y muestra el **host para Moonlight** (la IP `100.x.y.z`).
- [ ] Abrir **Moonlight** y conectar a esa IP.
- [ ] **Fuera de casa** (datos móviles, con Tailscale activo en el móvil): repetir. Es la
      prueba que importa — es el caso que antes no funcionaba.
- [ ] **PC ya encendido** → pulsar el botón otra vez → HA relanza el agente por SSH y
      Sunshine se abre igual.

## Avisos clave

- **Auto-login obligatorio**: sin sesión activa tras el WOL, ni el agente ni Sunshine
  capturan pantalla.
- **Tailscale en modo desatendido**: sin `--unattended` el túnel no sube sin sesión
  iniciada y el agente se quedará esperando hasta rendirse (`VPN_TIMEOUT`).
- **Tarea del agente con privilegios elevados**: es lo que le permite arrancar el
  servicio de Tailscale, que está en manual justo para no tenerlo encendido siempre.
- **Sunshine con autoarranque OFF**: si lo dejas en automático, se pierde el sentido de
  "solo el agente residente".
- **SSH solo por clave y en red local/VPN**: no expongas el puerto a internet.

## Rendimiento y red

- **Misma red (LAN/Wi-Fi de casa)**: Moonlight detecta el host y va directo. Mejor
  escenario: latencia mínima, 1080p/4K a 60-120 fps según GPU.
- **Fuera de casa**: vas por Tailscale, así que depende sobre todo de la **subida** de
  la conexión del PC (~20-30 Mbps estables → 1080p60 sobrado) y de la latencia. Lo
  normal es que Tailscale abra conexión directa (P2P) entre móvil y PC; si el NAT lo
  impide, cae a un relé DERP y se nota — `tailscale status` dice cuál de los dos es.
- En reposo, lo único extra encendido es el servicio OpenSSH inactivo (coste
  despreciable). Sunshine solo consume mientras haces streaming.

---

# Resumen diario por correo (independiente de lo anterior)

No tiene que ver con el streaming: cada mañana el backend manda a tu propio buzón los
datos del día (agenda, clases, entregas, clima, salud, entrenamiento) **en crudo, sin
interpretarlos**. De ahí los recoge tu rutina de Claude Code que ya lee el correo y
compone el resumen diario — por eso el backend no llama a ningún LLM.

> El código vive en la rama `claude/mejoras-analisis-seguridad-cj53hq`, todavía sin
> fusionar a `main`. **El cron de GitHub Actions solo se dispara desde la rama por
> defecto**, así que el paso 0 de esta lista es obligatorio antes que nada más.

## 0. Fusionar la rama

- [ ] Abrir el PR de `claude/mejoras-analisis-seguridad-cj53hq` contra `main` y
      fusionarlo (squash, como el resto del repo).

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

`.github/workflows/resumen-diario.yml` trae `30 4 * * *` (cron en **UTC**, no
entiende zonas horarias):

| Cron (UTC) | Madrid verano | Madrid invierno |
|---|---|---|
| `30 4 * * *` | 06:30 | 05:30 |
| `0 5 * * *` | 07:00 | 06:00 |

- [ ] Déjale margen antes de que tu rutina lea el correo: los cron de Actions se
      retrasan cuando GitHub va cargado (a veces 10-15 min).
- [ ] Revisarlo en los cambios de hora si quieres que la hora local se mantenga fija.

## 6. Probar sin esperar a mañana

- [ ] Actions → **Resumen diario por correo** → *Run workflow*. Debe llegar un correo
      con asunto `Life Assistant — datos del AAAA-MM-DD`.
- [ ] Para ver los mismos datos en JSON sin mandar correo:
      `curl https://backend-tender-glow-160.fly.dev/brief -H "Authorization: Bearer TU_JWT"`
      (el JWT sale de DevTools → Application → Local Storage → `la_token`).

## Si algo falla

- **403** en el workflow → los `BRIEF_TOKEN` de Fly y de GitHub no coinciden.
- **503** → falta alguna variable de SMTP (el mensaje de error dice cuál).
- **404** → el backend no tiene el deploy nuevo (paso 3).
- **Error de login SMTP** → estás usando la contraseña normal de Gmail, no la de
  aplicación (paso 1).
- **Llega sin entregas** → `ENTREGAS_MARKER` ≠ `VITE_ENTREGAS_MARKER` (paso 2).
- **No aparece el workflow en Actions** → la rama no está fusionada (paso 0).

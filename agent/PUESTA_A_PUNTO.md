# Puesta a punto del PC: streaming remoto (Sunshine/Moonlight)

Checklist para dejar operativo el control remoto del PC desde el móvil. La idea es
que el PC arranque casi "tonto": lo único residente es el **agente efímero**, que al
iniciar Windows mira la cola de jobs, ejecuta lo que haya (resolver Alud o abrir
Sunshine) y se cierra. El botón **"Streaming PC"** del dashboard enciende el PC (WOL)
y encola el job de Sunshine; conectas con **Moonlight** desde el móvil.

> Estos pasos son específicos del PC de Mikel (no forman parte del kit replicable):
> requieren un Windows real con Edge, sesión activa y hardware con WOL.

## 1. Actualizar el agente en el PC

- [ ] `git pull` en la carpeta del repo (trae el `agent/agent.py` efímero + despachador).
- [ ] Reinstalar dependencias si hace falta: `pip install -r backend/requirements.txt`.
- [ ] Revisar el `.env` del agente: `LA_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `ALUD_ACCOUNT`.
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

<#
.SYNOPSIS
  Instala el MCP del PC (agent/pc_mcp.py): las manos y los ojos de Jarvis en Windows.

.DESCRIPTION
  Sin parámetros: entorno de Python en ~/.jarvis-pc (fuera de OneDrive), y lo registra en
  Claude Code de este PC por stdio. Cualquier sesión de Claude Code puede ya ver la
  pantalla, abrir aplicaciones, etc. Sin puertos ni tokens.

  Con -Remoto: además lo prepara para que Jarvis en caja (chat, Telegram, teléfono) lo
  arranque CUANDO LO NECESITE: genera el token y crea la tarea programada
  LifeAssistantPcMcp, sin disparador (solo arranca cuando caja la lanza por SSH) y que se
  apaga sola tras PC_MCP_APAGAR_MIN minutos sin uso. Nada queda escuchando hasta que
  haga falta. ESCRIBE (no ejecuta) los dos pasos que quedan: la regla del firewall, que
  pide administrador, y las líneas del backend.env de caja. Ver docs/AGENTE_PC.md.

.PARAMETER Nivel
  mirar | usar | total. Por defecto usar (sin teclado ni ratón).
#>
param(
  [switch]$Remoto,
  [ValidateSet("mirar", "usar", "total")][string]$Nivel = "usar",
  [string]$Escucha = "0.0.0.0",
  [int]$Puerto = 8765,
  [int]$ApagarMin = 15
)
$ErrorActionPreference = "Stop"

$base     = Join-Path $HOME ".jarvis-pc"
$py       = Join-Path $base "venv\Scripts\python.exe"
$pyw      = Join-Path $base "venv\Scripts\pythonw.exe"
$servidor = Join-Path $PSScriptRoot "pc_mcp.py"
$config   = Join-Path $base "pc_mcp.env"

New-Item -ItemType Directory -Force $base | Out-Null
if (-not (Test-Path $py)) {
  Write-Host "Creando el entorno de Python en $base\venv..."
  python -m venv (Join-Path $base "venv")
}
& $py -m pip install -q --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements-pc-mcp.txt")

# Por stdio para Claude Code de este PC: lo lanza la sesión cuando lo necesita.
claude mcp remove jarvis-pc -s user 2>$null | Out-Null
claude mcp add --scope user jarvis-pc -e "PC_MCP_NIVEL=$Nivel" -- $py $servidor
Write-Host "Listo: Claude Code de este PC tiene el MCP jarvis-pc (nivel $Nivel)."

if (-not $Remoto) { return }

# ── Por HTTP, para caja ──────────────────────────────────────────────────────────────
$token = $null
if (Test-Path $config) {
  $linea = Select-String -Path $config -Pattern '^PC_MCP_TOKEN=(.+)$' | Select-Object -First 1
  if ($linea) { $token = $linea.Matches[0].Groups[1].Value }
}
if (-not $token) {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $token = ([Convert]::ToBase64String($bytes)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
$contenido = "PC_MCP_TOKEN=$token`nPC_MCP_HOST=$Escucha`nPC_MCP_PUERTO=$Puerto`nPC_MCP_NIVEL=$Nivel`nPC_MCP_APAGAR_MIN=$ApagarMin`n"
[IO.File]::WriteAllText($config, $contenido, (New-Object Text.UTF8Encoding($false)))
# Solo tu usuario puede leer el token.
icacls $config /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

# Una tarea programada SIN disparador: solo arranca cuando caja la lanza por SSH
# (`schtasks /run /tn LifeAssistantPcMcp`, la orden `mcp` de pc.sh), en tu sesión y con tu
# escritorio (las capturas necesitan uno: ni un servicio ni el SSH lo tienen). Una segunda
# petición con el MCP ya arrancado no abre otro (IgnoreNew), y sin límite de tiempo: se
# apaga él solo cuando nadie lo usa.
$accion    = New-ScheduledTaskAction -Execute $pyw -Argument "`"$servidor`" --http" -WorkingDirectory $base
$ajustes   = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
               -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "LifeAssistantPcMcp" -Action $accion -Settings $ajustes -Principal $principal -Force | Out-Null
# El acceso directo de Inicio de la versión anterior lo dejaba encendido siempre: fuera.
$viejo = Join-Path ([Environment]::GetFolderPath("Startup")) "Jarvis PC.lnk"
if (Test-Path $viejo) { Remove-Item $viejo }
Write-Host "Tarea LifeAssistantPcMcp creada: arranca a demanda y se apaga tras $ApagarMin min sin uso."
$ip = try { & tailscale ip -4 2>$null | Select-Object -First 1 } catch { $null }
if (-not $ip) { $ip = "<IP-del-PC-en-la-tailnet>" }

Write-Host ""
Write-Host "Quedan dos pasos que este script NO hace:"
Write-Host ""
Write-Host "1) La regla del firewall, en un PowerShell de administrador (solo LAN y tailnet):"
Write-Host "   New-NetFirewallRule -DisplayName 'Jarvis PC (MCP)' -Direction Inbound -Protocol TCP -LocalPort $Puerto -RemoteAddress LocalSubnet,100.64.0.0/10 -Action Allow"
Write-Host ""
Write-Host "2) En caja, en ~/stack/backend.env (y desplegar o recrear el backend):"
Write-Host "   PC_MCP_URL=http://${ip}:$Puerto/mcp"
Write-Host "   PC_MCP_TOKEN=$token"

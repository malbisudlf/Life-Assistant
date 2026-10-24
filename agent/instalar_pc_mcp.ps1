<#
.SYNOPSIS
  Instala el MCP del PC (agent/pc_mcp.py): las manos y los ojos de Jarvis en Windows.

.DESCRIPTION
  Sin parámetros: entorno de Python en ~/.jarvis-pc (fuera de OneDrive), y lo registra en
  Claude Code de este PC por stdio. Cualquier sesión de Claude Code puede ya ver la
  pantalla, abrir aplicaciones, etc. Sin puertos ni tokens.

  Con -Remoto: además lo deja sirviendo por HTTP al arrancar Windows, para que Jarvis en
  caja (teléfono y chat) llegue a él. Genera el token, crea el acceso directo en Inicio y
  ESCRIBE (no ejecuta) los dos pasos que quedan: la regla del firewall, que pide
  administrador, y la línea del .mcp.json de caja. Ver docs/AGENTE_PC.md, «El MCP del PC».

.PARAMETER Nivel
  mirar | usar | total. Por defecto usar (sin teclado ni ratón).
#>
param(
  [switch]$Remoto,
  [ValidateSet("mirar", "usar", "total")][string]$Nivel = "usar",
  [string]$Escucha = "0.0.0.0",
  [int]$Puerto = 8765
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
$contenido = "PC_MCP_TOKEN=$token`nPC_MCP_HOST=$Escucha`nPC_MCP_PUERTO=$Puerto`nPC_MCP_NIVEL=$Nivel`n"
[IO.File]::WriteAllText($config, $contenido, (New-Object Text.UTF8Encoding($false)))
# Solo tu usuario puede leer el token.
icacls $config /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

# Al iniciar sesión, en tu escritorio (las capturas necesitan uno: un servicio no lo tiene).
$inicio = [Environment]::GetFolderPath("Startup")
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $inicio "Jarvis PC.lnk"))
$acceso.TargetPath = $pyw
$acceso.Arguments = "`"$servidor`" --http"
$acceso.WorkingDirectory = $base
$acceso.Save()
Start-Process -FilePath $pyw -ArgumentList "`"$servidor`" --http" -WorkingDirectory $base -WindowStyle Hidden
Write-Host "Sirviendo por HTTP en ${Escucha}:$Puerto (y al iniciar sesión, desde Inicio)."

Write-Host ""
Write-Host "Quedan dos pasos que este script NO hace:"
Write-Host ""
Write-Host "1) La regla del firewall, en un PowerShell de administrador (solo LAN y tailnet):"
Write-Host "   New-NetFirewallRule -DisplayName 'Jarvis PC (MCP)' -Direction Inbound -Protocol TCP -LocalPort $Puerto -RemoteAddress LocalSubnet,100.64.0.0/10 -Action Allow"
Write-Host ""
Write-Host "2) En caja, en ~/telefono-jarvis/.mcp.json, dentro de mcpServers (IP del PC en la LAN o la tailnet):"
Write-Host "   `"jarvis-pc`": { `"type`": `"http`", `"url`": `"http://<IP-del-PC>:$Puerto/mcp`","
Write-Host "                  `"headers`": { `"Authorization`": `"Bearer $token`" } }"

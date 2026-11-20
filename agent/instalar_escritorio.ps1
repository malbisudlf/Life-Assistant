# El Jarvis de escritorio (agent/escritorio.py): instala lo que le falta al entorno de
# ~/.jarvis-pc (el del MCP del PC) y deja un acceso directo en Inicio para que arranque con
# Windows. Ver docs/ESCRITORIO.md.
#
#   powershell -ExecutionPolicy Bypass -File agent\instalar_escritorio.ps1
#   powershell -ExecutionPolicy Bypass -File agent\instalar_escritorio.ps1 -SinInicio
#
# Sin modelos ni nada de IA: el micrófono (sounddevice) y el cliente del WebSocket del oído.
param([switch]$SinInicio)

$ErrorActionPreference = "Stop"
$entorno = Join-Path $HOME ".jarvis-pc\venv"
$python  = Join-Path $entorno "Scripts\python.exe"
$pythonw = Join-Path $entorno "Scripts\pythonw.exe"
$script  = Join-Path $PSScriptRoot "escritorio.py"

if (-not (Test-Path $python)) {
    Write-Host "No está el entorno de ~/.jarvis-pc: ejecute antes agent\instalar_pc_mcp.ps1." -ForegroundColor Red
    exit 1
}
& $python -m pip install --disable-pip-version-check -q -r (Join-Path $PSScriptRoot "requirements-escritorio.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "pip ha fallado." -ForegroundColor Red; exit 1 }

if (-not $SinInicio) {
    $inicio = [Environment]::GetFolderPath("Startup")
    $acceso = Join-Path $inicio "Jarvis de escritorio.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($acceso)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$script`""
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.Description = "Jarvis de escritorio"
    $lnk.Save()
    Write-Host "Acceso directo en Inicio: $acceso"
}
Write-Host "Listo. Para arrancarlo ahora: & `"$pythonw`" `"$script`""

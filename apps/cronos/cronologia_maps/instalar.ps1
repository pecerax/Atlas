# instalar.ps1: mueve el sincronizador junto a Atlas e instala sus dependencias.
# No inicia sesión en Google ni guarda credenciales: eso lo hace usted después.
$ErrorActionPreference = "Stop"
$origen  = $PSScriptRoot
$destino = Join-Path $env:LOCALAPPDATA "Atlas\apps\cronos\cronologia_maps"

if ($origen -ne $destino) {
    Write-Host "Copiando a $destino ..."
    New-Item -ItemType Directory -Force -Path $destino | Out-Null
    Copy-Item -Path (Join-Path $origen "*") -Destination $destino -Recurse -Force
}
Set-Location $destino

$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) { $pyexe = "py"; $pyargs = @("-3") } else { $pyexe = "python"; $pyargs = @() }
& $pyexe @pyargs --version
if (-not (Test-Path ".venv")) { & $pyexe @pyargs -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
Write-Host "Dependencias de Python instaladas."

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location vendor_timeline_export
    npm ci --no-audit --no-fund
    Pop-Location
    Write-Host "puppeteer-core instalado."
} else {
    Write-Warning "No encontré Node.js/npm. Instálelo desde https://nodejs.org (versión LTS) y vuelva a ejecutar este script."
}

Write-Host "Probando con datos de ejemplo (sin su cuenta)..."
& ".venv\Scripts\python.exe" pruebas\prueba_e2e.py . (Join-Path $env:TEMP "prueba_cronologia") | Select-Object -Last 2
Write-Host ""
Write-Host "Listo. Siguiente paso, en esta misma ventana:"
Write-Host "  cd `"$destino`""
Write-Host "  .venv\Scripts\python secretos.py token"

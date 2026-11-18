# Arma Atlas-Instalar.exe desde la copia limpia del repositorio.
#
#   powershell -ExecutionPolicy Bypass -File instalador\construir.ps1 [-Version X]  (si no, la de Atlas\VERSION)
#
# 1) Saca la copia limpia con _publicar\exportar.py (sin datos personales, revisada).
# 2) La copia a _publicar\construccion\Atlas y le agrega lo que no va al repositorio: uv.exe, la rueda de Rust
#    (openjarvis_rust) y, si existe, la llave de Google Calendar (instalador\google_cliente.json).
# 3) Compila Atlas-Instalar.iss con Inno Setup 6. Resultado: _publicar\construccion\Atlas-Instalar.exe
param([string]$Version = "")
$ErrorActionPreference = "Stop"

$Atlas = Split-Path -Parent $PSScriptRoot
$Pub = Join-Path $Atlas "_publicar"
$Repo = Join-Path $Pub "repo"
$Salida = Join-Path $Pub "construccion"
$Fuente = Join-Path $Salida "Atlas"

if (-not $Version) {   # la versión de Atlas sale del archivo VERSION (una línea)
  $vf = Join-Path $Atlas "VERSION"
  $Version = if (Test-Path $vf) { (Get-Content $vf -Raw -Encoding UTF8).Trim() } else { "1.0" }
}
Write-Host "Atlas $Version"
Write-Host "1/3  Copia limpia del repositorio"
& python (Join-Path $Pub "exportar.py")
if ($LASTEXITCODE) { throw "exportar.py no pasó la revisión: no se arma el instalador." }

Write-Host "2/3  Juntando los archivos"
if (Test-Path $Fuente) { Remove-Item $Fuente -Recurse -Force }
New-Item -ItemType Directory -Force $Fuente | Out-Null
robocopy $Repo $Fuente /E /XD .git /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy falló ($LASTEXITCODE)" }
$Inst = Join-Path $Fuente "instalador"

# uv.exe: el del instalador si ya está, si no el del PC.
$uv = @((Join-Path $PSScriptRoot "uv.exe"), (Join-Path $env:USERPROFILE ".local\bin\uv.exe")) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $uv) { $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source }
if (-not $uv) { throw "Falta uv.exe (https://docs.astral.sh/uv/)." }
Copy-Item $uv (Join-Path $Inst "uv.exe")

# La rueda de Rust: la que ya está en instalador\ruedas, o la última que se compiló en src\rust.
$ruedas = Join-Path $Inst "ruedas"
New-Item -ItemType Directory -Force $ruedas | Out-Null
$whl = @(Get-ChildItem (Join-Path $PSScriptRoot "ruedas\*.whl") -ErrorAction SilentlyContinue) +
       @(Get-ChildItem (Join-Path $Atlas "src\rust\target\wheels\openjarvis_rust-*-cp313-*win_amd64.whl") -ErrorAction SilentlyContinue) |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $whl) { throw "Falta la rueda openjarvis_rust (compílela con maturin en src\rust)." }
Copy-Item $whl.FullName $ruedas

$cliente = Join-Path $PSScriptRoot "google_cliente.json"
if (Test-Path $cliente) { Copy-Item $cliente $Inst } else { Write-Host "     (sin google_cliente.json: Calendar se conectará después en Ajustes)" }

Write-Host "3/3  Compilando con Inno Setup"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Falta Inno Setup 6. Instálelo con:  winget install JRSoftware.InnoSetup" }
& $iscc "/DFuente=$Fuente" "/DVersion=$Version" "/O$Salida" (Join-Path $Inst "Atlas-Instalar.iss")
if ($LASTEXITCODE) { throw "Inno Setup falló ($LASTEXITCODE)" }
Write-Host ("Listo: " + (Join-Path $Salida "Atlas-Instalar.exe"))

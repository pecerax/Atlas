# Actualizar Atlas (24-11-2026): aplica lo que Claude deja en _actualizar\ sin copiar comandos a mano.
# _actualizar\ imita la carpeta de Atlas: _actualizar\hud\atlas_puente.py reemplaza a hud\atlas_puente.py.
# Pasos: cierra Atlas, guarda lo que se reemplaza en _respaldos\<fecha hora>\ (solo se guardan las 3 últimas),
# copia lo nuevo, corre las pruebas que haya entre lo nuevo y vuelve a abrir Atlas. Si una prueba falla, deshace todo.
# Versión única de PC y celular: «1.x.y» en el archivo VERSION. Cada actualización aplicada sube la y y anota el cambio
# en CAMBIOS.md (el texto sale de _actualizar\CAMBIO.txt). Si la actualización trae su propio VERSION, se usa ese.
$ErrorActionPreference = "Stop"
$atlas = Join-Path $env:LOCALAPPDATA "Atlas"
$nuevo = Join-Path $atlas "_actualizar"
$py = Join-Path $atlas "src\.venv\Scripts\python.exe"
$verArch = Join-Path $atlas "VERSION"
$cambiosArch = Join-Path $atlas "CAMBIOS.md"
$utf8 = New-Object System.Text.UTF8Encoding($false)

# limpieza: el CAMBIO.txt que quedó suelto en la raíz el 24-11-2026 (pedido de la persona: «borralo»)
$suelto = Join-Path $atlas "CAMBIO.txt"
if (Test-Path -LiteralPath $suelto) { Remove-Item -LiteralPath $suelto -Force }

$cambio = ""
$cambioArch = Join-Path $nuevo "CAMBIO.txt"
if (Test-Path -LiteralPath $cambioArch) { $cambio = ([IO.File]::ReadAllText($cambioArch)).Trim() }
$archivos = @(Get-ChildItem -LiteralPath $nuevo -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -ne $cambioArch })
if ($archivos.Count -eq 0) { Write-Host "No hay nada nuevo para aplicar."; return }
Write-Host "Archivos nuevos:"; $archivos | ForEach-Object { Write-Host ("  " + $_.FullName.Substring($nuevo.Length + 1)) }

$antes = "0"; if (Test-Path -LiteralPath $verArch) { $antes = ([IO.File]::ReadAllText($verArch)).Trim() }

Write-Host "`nCerrando Atlas..."
& (Join-Path $atlas "Cerrar-Atlas.cmd") | Out-Null
Start-Sleep -Seconds 3

$resp = Join-Path $atlas ("_respaldos\" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
$hechos = @()
foreach ($f in $archivos) {
    $rel = $f.FullName.Substring($nuevo.Length + 1)
    $dest = Join-Path $atlas $rel
    if (Test-Path -LiteralPath $dest) {
        $r = Join-Path $resp $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $r) | Out-Null
        Copy-Item -LiteralPath $dest -Destination $r -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
    $hechos += $rel
}
Write-Host ("Copiados: " + $hechos.Count)

$ok = $true
foreach ($rel in $hechos | Where-Object { (Split-Path $_ -Leaf) -like "pruebas_*.py" }) {
    Write-Host "`nProbando $rel ..."
    Push-Location $atlas
    & $py (Join-Path $atlas $rel)
    $codigo = $LASTEXITCODE
    Pop-Location
    if ($codigo -ne 0) { $ok = $false; Write-Host "FALLÓ $rel" -ForegroundColor Red }
}

if (-not $ok) {
    Write-Host "`nUna prueba falló: vuelvo a dejar los archivos como estaban (la versión no cambia)." -ForegroundColor Yellow
    foreach ($rel in $hechos) {
        $r = Join-Path $resp $rel
        $dest = Join-Path $atlas $rel
        if (Test-Path -LiteralPath $r) { Copy-Item -LiteralPath $r -Destination $dest -Force } else { Remove-Item -LiteralPath $dest -Force }
    }
} else {
    # versión: la que trajo la actualización, o la de antes con la y + 1 (1.x -> 1.x.1)
    if ($hechos -contains "VERSION") { $ver = ([IO.File]::ReadAllText($verArch)).Trim() }
    else {
        $p = @($antes.Split(".") | ForEach-Object { [int]$_ })
        while ($p.Count -lt 3) { $p += 0 }
        $p[2] += 1
        $ver = "{0}.{1}.{2}" -f $p[0], $p[1], $p[2]
        [IO.File]::WriteAllText($verArch, $ver + "`r`n", $utf8)
    }
    if (-not (Test-Path -LiteralPath $cambiosArch)) {
        [IO.File]::WriteAllText($cambiosArch, "# Cambios de Atlas (PC y celular)`r`n`r`nUna sola versión 1.x.y para el PC y la app del celular. La y sube con cada cambio concreto.`r`n", $utf8)
    }
    $texto = if ($cambio) { $cambio } else { "Archivos: " + (($hechos | Where-Object { $_ -ne "VERSION" }) -join ", ") }
    [IO.File]::AppendAllText($cambiosArch, ("`r`n## " + $ver + " · " + (Get-Date -Format "yyyy-MM-dd HH:mm") + " · PC`r`n" + $texto + "`r`n"), $utf8)
    Remove-Item -LiteralPath $nuevo -Recurse -Force   # aplicado: la carpeta queda vacía para la próxima vez
    New-Item -ItemType Directory -Force -Path $nuevo | Out-Null
    Write-Host ("`nListo: Atlas " + $ver + " (antes " + $antes + ").") -ForegroundColor Green
}

# solo las 3 últimas carpetas de respaldo
$todas = @(Get-ChildItem -LiteralPath (Join-Path $atlas "_respaldos") -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
$todas | Select-Object -Skip 3 | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Write-Host "Abriendo Atlas..."
Start-Process -FilePath (Join-Path $atlas "Atlas.cmd") -WorkingDirectory $atlas -WindowStyle Hidden

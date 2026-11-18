@echo off
title Actualizar icono de Atlas
echo Actualizando el icono del acceso directo de Atlas...
powershell -NoProfile -Command "$oj = Join-Path $env:LOCALAPPDATA 'Atlas'; $ico = Join-Path $oj 'atlas-escritorio-2.ico'; $ws = New-Object -ComObject WScript.Shell; $desk = [Environment]::GetFolderPath('Desktop'); $links = @(Get-ChildItem -Path $desk -Filter 'Atlas*.lnk' -ErrorAction SilentlyContinue) + @(Get-ChildItem -Path $desk -Filter 'Jarvis*.lnk' -ErrorAction SilentlyContinue); if ($links.Count -eq 0) { $l = $ws.CreateShortcut((Join-Path $desk 'Atlas.lnk')); $l.TargetPath = (Join-Path $oj 'Atlas.cmd'); $l.WorkingDirectory = $oj; $l.WindowStyle = 7; $l.IconLocation = $ico; $l.Save(); Write-Host 'Acceso directo creado.' } else { foreach ($f in $links) { $l = $ws.CreateShortcut($f.FullName); $l.IconLocation = $ico; $l.Save(); Write-Host ('Icono actualizado: ' + $f.Name) } }; Start-Process ie4uinit.exe -ArgumentList '-show' -ErrorAction SilentlyContinue"
echo.
echo Listo. Si el icono no cambia de inmediato, presione F5 en el escritorio.
pause

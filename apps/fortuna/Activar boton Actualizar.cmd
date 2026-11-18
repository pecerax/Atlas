@echo off
rem Hace que el boton Actualizar de Mis Fondos funcione siempre:
rem deja un acceso en la carpeta Inicio de Windows que abre el ayudante
rem (servidor_actualizar.py, solo escucha en este computador) al encender el PC.
rem Para quitarlo: borra "Mis Fondos (actualizador)" de la carpeta shell:startup.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$py=(Get-Command pythonw -ErrorAction SilentlyContinue).Source; if(-not $py){$py=(Get-Command python).Source}; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Mis Fondos (actualizador).lnk')); $s.TargetPath=$py; $s.Arguments='\"%~dp0servidor_actualizar.py\" --siempre'; $s.WorkingDirectory='%~dp0'; $s.Save(); Start-Process $py -ArgumentList $s.Arguments -WorkingDirectory '%~dp0' -WindowStyle Hidden"
echo.
echo Listo. El boton Actualizar ya funciona, tambien despues de reiniciar el PC.
pause

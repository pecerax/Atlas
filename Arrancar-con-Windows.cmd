@echo off
title Atlas al iniciar Windows
rem Agrega o quita el arranque de Atlas (de fondo, sin ventana) al iniciar sesion en Windows.
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Atlas de fondo.lnk"
if exist "%LNK%" goto quitar
echo Atlas no arranca solo con Windows.
choice /c SN /m "Quiere que Atlas arranque de fondo al iniciar Windows"
if errorlevel 2 goto fin
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath=$env:LOCALAPPDATA+'\Atlas\Atlas-fondo.cmd'; $s.WorkingDirectory=$env:LOCALAPPDATA+'\Atlas'; $s.WindowStyle=7; $s.IconLocation=$env:LOCALAPPDATA+'\Atlas\atlas-escritorio-2.ico'; $s.Save()"
if exist "%LNK%" (echo Listo: Atlas arrancara de fondo al iniciar Windows.) else (echo No pude crear el acceso directo.)
goto fin
:quitar
echo Atlas ya arranca solo con Windows.
choice /c SN /m "Quiere quitarlo"
if errorlevel 2 goto fin
del "%LNK%" && echo Listo: Atlas ya no arranca solo.
:fin
echo.
pause

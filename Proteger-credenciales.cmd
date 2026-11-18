@echo off
chcp 65001 >nul
title Proteger las credenciales de Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
set PY="%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe"
set M="%LOCALAPPDATA%\Atlas\hud\migrar_secretos.py"
%PY% %M%
echo.
echo   1 = Cifrar ahora    2 = Deshacer (volver a los archivos)    Enter = Salir
set /p OP="Elija: "
if "%OP%"=="1" %PY% %M% --aplicar
if "%OP%"=="2" %PY% %M% --deshacer
pause

@echo off
rem Atlas de fondo, sin ventana (24-11-2026): para que la app del celular funcione sin abrir la ventana.
rem Abrir la ventana despues: Atlas.cmd (no arranca otro Atlas, solo abre la ventana). Apagar: Cerrar-Atlas.cmd.
cd /d "%LOCALAPPDATA%\Atlas\src"
set "EXE=%LOCALAPPDATA%\Atlas\src\.venv\Scripts\Atlas.exe"
if not exist "%EXE%" set "EXE=%LOCALAPPDATA%\Atlas\src\.venv\Scripts\pythonw.exe"
start "Atlas" "%EXE%" "%LOCALAPPDATA%\Atlas\hud\hud_server.py" --fondo

@echo off
cd /d "%LOCALAPPDATA%\Atlas\src"
rem Atlas.exe = el pythonw.exe del entorno con nombre, icono y descripcion de Atlas (asi sale en el Administrador
rem de tareas). Si falta (p. ej. tras rehacer el entorno) se crea con hud\atlas_crear_exe.py; si no se puede, pythonw.exe.
set "EXE=%LOCALAPPDATA%\Atlas\src\.venv\Scripts\Atlas.exe"
if not exist "%EXE%" "%LOCALAPPDATA%\Atlas\src\.venv\Scripts\pythonw.exe" "%LOCALAPPDATA%\Atlas\hud\atlas_crear_exe.py" >nul 2>&1
if not exist "%EXE%" set "EXE=%LOCALAPPDATA%\Atlas\src\.venv\Scripts\pythonw.exe"
start "Atlas" "%EXE%" "%LOCALAPPDATA%\Atlas\hud\hud_server.py"

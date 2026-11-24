@echo off
rem Apaga Atlas del todo (servidor, circulo flotante y ventana), aunque este corriendo de fondo.
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\pythonw.exe" "%LOCALAPPDATA%\Atlas\hud\hud_server.py" --cerrar

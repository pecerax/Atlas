@echo off
chcp 65001 >nul
title Clave de Haiku
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\guardar_clave_haiku.py"
pause

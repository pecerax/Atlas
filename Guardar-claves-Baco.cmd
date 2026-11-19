@echo off
chcp 65001 >nul
title Claves de Baco
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\guardar_claves_baco.py"
pause

@echo off
title Evaluar el modelo de Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\evaluar_modelo.py"
echo.
pause

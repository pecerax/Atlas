@echo off
title Pruebas de Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\pruebas_atlas.py"
echo.
pause

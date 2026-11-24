@echo off
chcp 65001 >nul
title Pruebas del interprete Haiku
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\pruebas_interprete.py"
echo.
pause

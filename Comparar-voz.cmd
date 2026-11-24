@echo off
chcp 65001 >nul
title Comparar reconocedores de voz
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\pruebas_voz\comparar.py"
echo.
pause

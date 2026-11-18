@echo off
title Conectar Atlas con Google Calendar
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\connect_google.py"
echo.
pause

@echo off
chcp 65001 >nul
title Vincular Telegram oculto de Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" -c "import telethon" 2>nul
if errorlevel 1 (
  echo Instalando la libreria Telethon ^(solo la primera vez^)...
  uv pip install --python "%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" telethon
)
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\vincular_telegram_api.py"
pause

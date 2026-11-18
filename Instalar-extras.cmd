@echo off
title Instalar extras de Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
echo Instalando componentes extra de Atlas (control de YouTube Music y busqueda de canciones)...
uv pip install uiautomation yt-dlp
if errorlevel 1 "%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" -m pip install uiautomation yt-dlp
echo.
echo Listo. Cierre Atlas y vuelva a abrirlo.
pause

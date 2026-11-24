@echo off
title Actualizar Atlas
rem Doble clic: cierra Atlas, aplica lo que haya en _actualizar\, prueba y vuelve a abrir Atlas.
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Atlas\Actualizar-Atlas.ps1"
echo.
pause

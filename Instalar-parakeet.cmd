@echo off
title Instalar reconocimiento de voz Parakeet
cd /d "%LOCALAPPDATA%\Atlas\src"
echo Instalando el componente sherpa-onnx...
uv pip install sherpa-onnx
if errorlevel 1 "%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" -m pip install sherpa-onnx
echo.
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\install_parakeet.py"
echo.
pause

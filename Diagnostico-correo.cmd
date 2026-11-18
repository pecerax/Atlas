@echo off
title Diagnostico certificado correo
cd /d "%LOCALAPPDATA%\Atlas\src"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%LOCALAPPDATA%\Atlas\hud\diag_cert.py"
pause

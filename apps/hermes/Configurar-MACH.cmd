@echo off
rem Guarda (solo en este PC) la clave de las cartolas PDF de MACH.
cd /d "%~dp0"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%~dp0configurar_mach.py"
if errorlevel 1 pause

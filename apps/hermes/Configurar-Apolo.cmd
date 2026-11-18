@echo off
rem Instala el lector de PDF y guarda (solo en este PC) la clave de las cartolas de Scotiabank.
cd /d "%~dp0"
"%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe" "%~dp0configurar_apolo.py"
if errorlevel 1 pause

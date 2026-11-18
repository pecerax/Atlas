@echo off
rem Abre Mis Fondos y deja listo el boton Actualizar (descarga de la CMF).
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw "%~dp0servidor_actualizar.py") || (start "" /min python "%~dp0servidor_actualizar.py")
rem La pagina se abre desde el ayudante (no como archivo): asi el boton Actualizar solo acepta pedidos de ella misma.
ping -n 2 127.0.0.1 >nul
start "" "http://127.0.0.1:8932/"

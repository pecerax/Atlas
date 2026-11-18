@echo off
rem Atlas: usa el comando "jarvis" del paquete OpenJarvis (base de Atlas)
setlocal
set "SRC=%~dp0..\src"
uv run --project "%SRC%" jarvis %*

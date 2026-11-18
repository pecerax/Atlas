@echo off
title Atlas
cd /d "%LOCALAPPDATA%\Atlas\src"
set JARVIS_SKIP_RUNTIME_PANEL=1
set PYTHONWARNINGS=ignore
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set HF_HUB_VERBOSITY=error
set LOGURU_LEVEL=ERROR
set HF_HUB_OFFLINE=1
call "%LOCALAPPDATA%\Atlas\bin\atlas.cmd" chat --voice --tools gmail_mark_read,gmail_unread,gmail_search
echo.
echo Atlas se cerro. Presiona una tecla para cerrar esta ventana.
pause >nul

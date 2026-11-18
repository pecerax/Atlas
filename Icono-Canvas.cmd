@echo off
title Icono de Canvas en Atlas
set PY="%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe"
set HUD=%LOCALAPPDATA%\Atlas\hud
set PYTHONIOENCODING=utf-8
cd /d "%LOCALAPPDATA%\Atlas\src"
echo == 1/3 Notas recientes de Canvas al preguntar (si faltaba)
%PY% "%HUD%\patch_canvas_recientes.py" "%HUD%"
echo.
echo == 2/3 Icono C de Canvas
%PY% "%HUD%\patch_icono_canvas.py" "%HUD%"
%PY% "%HUD%\pruebas_canvas_rutas.py" > "%HUD%\resultado_canvas.txt" 2>&1
type "%HUD%\resultado_canvas.txt" | findstr /C:"FALLA" /C:"TODO BIEN" /C:"Traceback"
echo.
echo == 3/3 Reiniciando Atlas
powershell -NoProfile -Command "try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/apagar -Body '{}' -ContentType 'application/json' -TimeoutSec 3 | Out-Null } catch {}"
timeout /t 3 /nobreak > nul
call "%LOCALAPPDATA%\Atlas\Atlas.cmd"
echo.
echo Listo.
pause

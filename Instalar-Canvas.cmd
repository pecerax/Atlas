@echo off
title Instalar notas de Canvas en Atlas
set PY="%LOCALAPPDATA%\Atlas\src\.venv\Scripts\python.exe"
set HUD=%LOCALAPPDATA%\Atlas\hud
set PYTHONIOENCODING=utf-8
cd /d "%LOCALAPPDATA%\Atlas\src"
echo == 1/4 Aplicando el conector de Canvas
%PY% "%HUD%\patch_canvas.py" "%HUD%" "%LOCALAPPDATA%\Atlas\src\src\openjarvis\security\atlas_secretos.py"
%PY% "%HUD%\patch_canvas_recientes.py" "%HUD%"
echo.
echo == 2/4 Pruebas del conector (Canvas simulado)
%PY% "%HUD%\pruebas_canvas.py" > "%HUD%\resultado_canvas.txt" 2>&1
type "%HUD%\resultado_canvas.txt" | findstr /C:"FALLA" /C:"TODO BIEN" /C:"Error" /C:"Traceback"
echo.
echo == 3/4 Pruebas de frases y pruebas generales de Atlas (tarda un poco)
%PY% "%HUD%\pruebas_canvas_rutas.py" >> "%HUD%\resultado_canvas.txt" 2>&1
%PY% "%HUD%\pruebas_atlas.py" >> "%HUD%\resultado_canvas.txt" 2>&1
type "%HUD%\resultado_canvas.txt" | findstr /C:"FALLA" /C:"TODO BIEN" /C:"Traceback" /C:"fallaron" /C:"pasaron"
echo.
echo == 4/4 Reiniciando Atlas
powershell -NoProfile -Command "try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/apagar -Body '{}' -ContentType 'application/json' -TimeoutSec 3 | Out-Null } catch {}"
timeout /t 3 /nobreak > nul
call "%LOCALAPPDATA%\Atlas\Atlas.cmd"
echo.
echo Listo. El detalle quedo en hud\resultado_canvas.txt
pause

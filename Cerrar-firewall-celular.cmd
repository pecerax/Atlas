@echo off
title Atlas - cerrar el firewall para el celular
rem Auditoria 24-11-2026. Windows tenia una regla "pythonw.exe" que dejaba entrar a CUALQUIER puerto desde CUALQUIER origen.
rem Esto la limita a la red de casa (LocalSubnet) y a Tailscale (100.64.0.0/10), y agrega las reglas propias del puente (8766).
rem Para deshacer: netsh advfirewall firewall set rule name="pythonw.exe" new remoteip=any
net session >nul 2>&1
if errorlevel 1 (
  echo Pidiendo permiso de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall set rule name="pythonw.exe" new remoteip=LocalSubnet,100.64.0.0/10
netsh advfirewall firewall delete rule name="Atlas Puente" >nul 2>&1
netsh advfirewall firewall delete rule name="Atlas Puente TS" >nul 2>&1
netsh advfirewall firewall add rule name="Atlas Puente" dir=in action=allow protocol=TCP localport=8766 remoteip=LocalSubnet profile=private
netsh advfirewall firewall add rule name="Atlas Puente TS" dir=in action=allow protocol=TCP localport=8766 remoteip=100.64.0.0/10 profile=any
echo.
echo Listo. Python ya solo acepta conexiones de su red de casa y de Tailscale.
pause

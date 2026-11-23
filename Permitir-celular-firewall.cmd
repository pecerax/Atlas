@echo off
title Atlas - permitir el celular en el firewall
rem Abre el puerto del Puente Atlas (8766) SOLO para la red de casa (LocalSubnet) y la red de Tailscale (100.64.0.0/10).
rem No lo abre hacia internet. Para quitarlo: netsh advfirewall firewall delete rule name="Atlas Puente"
net session >nul 2>&1
if errorlevel 1 (
  echo Pidiendo permiso de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="Atlas Puente" >nul 2>&1
netsh advfirewall firewall add rule name="Atlas Puente" dir=in action=allow protocol=TCP localport=8766 remoteip=LocalSubnet,100.64.0.0/10 profile=any
echo.
echo Listo. El celular vinculado ya puede llegar a Atlas desde su casa o por Tailscale.
pause

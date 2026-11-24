@echo off
title Atlas - permitir el celular en el firewall
rem Abre el puerto del Puente Atlas (8766) SOLO para la red de casa (LocalSubnet) y la red de Tailscale (100.64.0.0/10).
rem No lo abre hacia internet. Para quitarlo: netsh advfirewall firewall delete rule name="Atlas Puente" y name="Atlas Puente TS"
net session >nul 2>&1
if errorlevel 1 (
  echo Pidiendo permiso de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="Atlas Puente" >nul 2>&1
rem Auditoria 24-11-2026: la red de casa solo en perfil Privado (en un Wi-Fi publico LocalSubnet es cualquiera ahi).
netsh advfirewall firewall delete rule name="Atlas Puente TS" >nul 2>&1
netsh advfirewall firewall add rule name="Atlas Puente" dir=in action=allow protocol=TCP localport=8766 remoteip=LocalSubnet profile=private
netsh advfirewall firewall add rule name="Atlas Puente TS" dir=in action=allow protocol=TCP localport=8766 remoteip=100.64.0.0/10 profile=any
echo.
echo Listo. El celular vinculado ya puede llegar a Atlas desde su casa o por Tailscale.
pause

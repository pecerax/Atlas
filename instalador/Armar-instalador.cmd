@echo off
rem Instala Inno Setup 6 (si falta) y arma Atlas-Instalar.exe en _publicar\construccion.
chcp 65001 >nul
if not exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" if not exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  echo Instalando Inno Setup 6...
  winget install --id JRSoftware.InnoSetup -e --scope user --accept-package-agreements --accept-source-agreements
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0construir.ps1"
echo.
pause

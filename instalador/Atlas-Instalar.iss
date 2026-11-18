; Instalador de Atlas (Inno Setup 6). No se compila a mano: lo arma construir.ps1, que primero saca la copia limpia
; del repositorio (_publicar\exportar.py) y le agrega uv.exe y la rueda de Rust.
;
; Qué hace el .exe: copia Atlas en %LOCALAPPDATA%\Atlas (sin pedir permisos de administrador) y abre el asistente
; (asistente.py), que instala Python, los componentes, Ollama, el modelo y las voces, y luego pide las cuentas.
; Las contraseñas nunca pasan por aquí: van del asistente al Administrador de credenciales de Windows.

#ifndef Fuente
  #define Fuente "..\_publicar\construccion\Atlas"
#endif
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppId={{6E0C4A2D-7B1F-4C55-9A3E-41A7D2B8C9F0}
AppName=Atlas
AppVersion={#Version}
VersionInfoProductName=Atlas
AppVerName=Atlas {#Version}
AppPublisher=Atlas
DefaultDirName={localappdata}\Atlas
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\_publicar\construccion
OutputBaseFilename=Atlas-Instalar
SetupIconFile={#Fuente}\atlas-escritorio-2.ico
UninstallDisplayIcon={app}\atlas-escritorio-2.ico
UninstallDisplayName=Atlas
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
es.WelcomeLabel2=Se instalará Atlas en su computador.%n%nAl presionar Siguiente se copian los archivos y se abre el asistente, que descarga lo demás (unos 8 GB) y le pide sus cuentas al final. Cada paso se puede dejar para después.
es.FinishedLabel=Los archivos de Atlas quedaron copiados. El asistente se abre solo para terminar la instalación.

[Files]
; Todo el repositorio limpio, sin los lanzadores e íconos viejos con el nombre Jarvis. Los datos personales viven en %USERPROFILE%\.atlas y nunca se tocan.
Source: "{#Fuente}\*"; DestDir: "{app}"; Excludes: "src\.venv\*,instalador\descargas\*,instalador\estado.json,Jarvis*.cmd,Probar-Jarvis.cmd,jarvis*.ico"; \
  Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
; uv trae su propio Python 3.13 si el computador no tiene; el asistente solo usa la biblioteca estándar.
Filename: "{app}\instalador\uv.exe"; \
  Parameters: "run --no-project --python 3.13 ""{app}\instalador\asistente.py"" --atlas ""{app}"""; \
  WorkingDir: "{app}\instalador"; StatusMsg: "Abriendo el asistente de Atlas..."; Flags: runhidden nowait

[UninstallDelete]
; Lo que el asistente creó dentro de la carpeta de Atlas. Los datos de %USERPROFILE%\.atlas y las contraseñas guardadas
; en Windows se quedan: se borran desde Ajustes antes de desinstalar si así lo quiere.
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\instalador\descargas"
Type: files; Name: "{app}\instalador\estado.json"
Type: files; Name: "{app}\instalador\instalacion.log"
Type: filesandordirs; Name: "{app}\apps\cronos\node"
Type: files; Name: "{userdesktop}\Atlas.lnk"
Type: files; Name: "{userstartup}\Atlas.lnk"
Type: files; Name: "{userprograms}\Atlas.lnk"

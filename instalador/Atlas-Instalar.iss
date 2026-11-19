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
es.FinishedLabel=Los archivos de Atlas quedaron copiados. El asistente se abre solo para terminar la instalación (la primera vez puede tardar un minuto).%n%nSi no aparece, búsquelo en el menú Inicio como «Instalar Atlas».

[Files]
; Todo el repositorio limpio, sin los lanzadores e íconos viejos con el nombre Jarvis. Los datos personales viven en %USERPROFILE%\.atlas y nunca se tocan.
Source: "{#Fuente}\*"; DestDir: "{app}"; Excludes: "src\.venv\*,instalador\descargas\*,instalador\estado.json,Jarvis*.cmd,Probar-Jarvis.cmd,jarvis*.ico"; \
  Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Para volver al asistente si se cerró o no se abrió. El acceso «Atlas» lo crea el asistente al final.
Name: "{userprograms}\Instalar Atlas"; Filename: "{app}\python\pythonw.exe"; \
  Parameters: """{app}\instalador\asistente.py"" --atlas ""{app}"""; \
  WorkingDir: "{app}\instalador"; IconFilename: "{app}\atlas-escritorio-2.ico"; Comment: "Terminar de instalar Atlas"; Check: PyAtlas
Name: "{userprograms}\Instalar Atlas"; Filename: "{app}\instalador\uv.exe"; \
  Parameters: "run --no-project --python 3.13 ""{app}\instalador\asistente.py"" --atlas ""{app}"""; \
  WorkingDir: "{app}\instalador"; IconFilename: "{app}\atlas-escritorio-2.ico"; Comment: "Terminar de instalar Atlas"; Check: SinPyAtlas

[Run]
; Python 3.13 quedó listo en [Code] (con aviso si falló); el asistente solo usa la biblioteca estándar.
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\instalador\asistente.py"" --atlas ""{app}"""; \
  WorkingDir: "{app}\instalador"; StatusMsg: "Abriendo el asistente de Atlas..."; Flags: nowait; Check: PyAtlas
Filename: "{app}\instalador\uv.exe"; \
  Parameters: "run --no-project --python 3.13 ""{app}\instalador\asistente.py"" --atlas ""{app}"""; \
  WorkingDir: "{app}\instalador"; StatusMsg: "Abriendo el asistente de Atlas..."; Flags: runhidden nowait; Check: SinPyAtlas

[UninstallDelete]
; Lo que el asistente creó dentro de la carpeta de Atlas. Los datos de %USERPROFILE%\.atlas y las contraseñas guardadas
; en Windows se quedan: se borran desde Ajustes antes de desinstalar si así lo quiere.
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\instalador\descargas"
Type: files; Name: "{app}\instalador\estado.json"
Type: files; Name: "{app}\instalador\instalacion.log"
Type: files; Name: "{app}\instalador\preparar_python.log"
Type: files; Name: "{app}\instalador\asistente.puerto"
Type: filesandordirs; Name: "{app}\instalador\ventana"
Type: filesandordirs; Name: "{app}\apps\cronos\node"
Type: files; Name: "{userdesktop}\Atlas.lnk"
Type: files; Name: "{userstartup}\Atlas.lnk"
Type: files; Name: "{userprograms}\Atlas.lnk"

[Code]
// Python de Atlas. Antes lo instalaba uv en %APPDATA%\uv\python, y fallaba en silencio en algunos PCs: sin internet,
// antivirus, o Windows que se niega a recorrer el enlace (junction) que crea uv («punto de montaje no confiable»,
// os error 448). Ahora:
//   1) se descomprime el Python que viene dentro del instalador en {app}\python, con tar de Windows: sin internet,
//      sin uv y sin enlaces. El asistente y los entornos de Atlas usan ese;
//   2) solo si eso falla, el camino antiguo con uv (Python del PC, el incluido como espejo local, o internet).
// Todo queda en instalador\preparar_python.log; si nada resulta, un aviso en pantalla.
var
  Listo: Boolean;

function PyAtlas: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\python\pythonw.exe'));
end;

function SinPyAtlas: Boolean;
begin
  Result := Listo and not PyAtlas;
end;

function Registro: String;
begin
  Result := ExpandConstant('{app}\instalador\preparar_python.log');
end;

// Corre un comando con cmd y anexa lo que diga al registro. Devuelve True si terminó con código 0.
function Correr(Exe, Args: String): Boolean;
var
  Codigo: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/c ""' + Exe + '" ' + Args + ' >> "' + Registro + '" 2>&1"',
                 ExpandConstant('{app}\instalador'), SW_HIDE, ewWaitUntilTerminated, Codigo) and (Codigo = 0);
end;

function Uv(Args: String): Boolean;
begin
  Result := Correr(ExpandConstant('{app}\instalador\uv.exe'), Args);
end;

// instalador\python_local\<fecha>\cpython-...tar.gz (el mismo archivo que bajaría uv).
function TarPython: String;
var
  D, F: TFindRec;
  Base: String;
begin
  Result := '';
  Base := ExpandConstant('{app}\instalador\python_local\');
  if FindFirst(Base + '*', D) then
  try
    repeat
      if (D.Name <> '.') and (D.Name <> '..') and (Result = '') then
        if FindFirst(Base + D.Name + '\*.tar.gz', F) then
        try
          Result := Base + D.Name + '\' + F.Name;
        finally
          FindClose(F);
        end;
    until not FindNext(D);
  finally
    FindClose(D);
  end;
end;

// file:///C:/Users/.../python_local, con espacios y % escapados para que uv lo lea bien.
function EspejoLocal: String;
var
  S: String;
begin
  S := ExpandConstant('{app}\instalador\python_local');
  StringChangeEx(S, '%', '%25', True);
  StringChangeEx(S, ' ', '%20', True);
  StringChangeEx(S, '\', '/', True);
  Result := 'file:///' + S;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Intento: Integer;
  Tar: String;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Instalando Python...';
    Tar := TarPython;
    if (not PyAtlas) and (Tar <> '') then
      Correr(ExpandConstant('{sys}\tar.exe'), '-xzf "' + Tar + '" -C "' + ExpandConstant('{app}') + '"');
    if PyAtlas then
      Listo := Correr(ExpandConstant('{app}\python\python.exe'), '-c "import ssl, sqlite3, ctypes; print(''Python de Atlas listo'')"');
    if not Listo then
    begin
      DelTree(ExpandConstant('{app}\python'), True, True, True);
      Listo := Uv('python find 3.13');
      if not Listo then
      begin
        Uv('python install 3.13 --no-bin --mirror "' + EspejoLocal + '"');
        Listo := Uv('python find 3.13');
      end;
      Intento := 0;
      while (not Listo) and (Intento < 3) do
      begin
        Intento := Intento + 1;
        WizardForm.StatusLabel.Caption := 'Descargando Python (puede tardar un par de minutos)...';
        Uv('python install 3.13 --no-bin');
        Listo := Uv('python find 3.13');
        if not Listo then
          Sleep(3000);
      end;
    end;
    if not Listo then
      MsgBox('No se pudo preparar Python, que Atlas necesita para seguir.' + #13#10#13#10 +
             'Vuelva a abrir Atlas-Instalar.exe. Si tiene antivirus, agregue la carpeta ' + ExpandConstant('{app}') +
             ' como excepción.' + #13#10#13#10 +
             'Si sigue fallando, mande este archivo a quien le pasó el instalador:' + #13#10 + Registro, mbError, MB_OK);
  end;
end;

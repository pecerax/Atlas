' Arranca Syncthing al iniciar sesion, sin ventana ni navegador (GUI solo en 127.0.0.1:8384).
' Busca syncthing.exe en la carpeta de winget, asi sigue funcionando despues de actualizar el paquete.
Option Explicit
Dim sh, fso, base, d, sd, exe
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WinGet\Packages"
exe = ""
If fso.FolderExists(base) Then
  For Each d In fso.GetFolder(base).SubFolders
    If LCase(Left(d.Name, 20)) = "syncthing.syncthing_" Then
      For Each sd In d.SubFolders
        If fso.FileExists(sd.Path & "\syncthing.exe") Then exe = sd.Path & "\syncthing.exe"
      Next
    End If
  Next
End If
If exe <> "" Then
  sh.Run """" & exe & """ serve --no-browser --no-console --gui-address=127.0.0.1:8384", 0, False
End If

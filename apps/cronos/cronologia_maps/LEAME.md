# Cronología de Google Maps → Atlas

Descarga cada noche la copia cifrada de su Cronología desde Google, la descifra en memoria
y la deja en `cronologia_maps.db` para que Cronos la consulte. No instala nada por sí solo:
cada paso lo ejecuta usted.

## Qué se guarda y dónde

| Dato | Dónde | Protección |
|---|---|---|
| Token maestro, clave, correo, id de dispositivo | Administrador de credenciales de Windows, entrada `Atlas-CronologiaMaps` | Cifrado con DPAPI, ligado a su usuario de Windows. Nunca en archivos. |
| Token de una hora | Solo en memoria durante la sincronización | Se descarta al terminar |
| Copia descifrada de Google | Solo en memoria (SQLite en RAM) | Se descarta al terminar |
| Historial final | `%LOCALAPPDATA%\Atlas\datos\cronologia_maps\cronologia_maps.db` | Carpeta privada de su usuario. El cifrado del disco se ve en el hilo "Proteger los datos de Atlas". |
| Registro | `sincronizacion.log` y `estado.json` en la misma carpeta | Sin datos de ubicación ni credenciales |

## Paso 0. En el celular (una vez)
Google Maps › su foto › Cronología › ícono de nube › **activar copia de seguridad**.
Sin esto no hay nada que descargar.

## Paso 1. Preparar el PC (una vez)
En un PowerShell normal (no de administrador):
```
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Atlaspps\cronos\cronologia_maps\instalar.ps1"
```
Copia todo a `%LOCALAPPDATA%\Atlaspps\cronos\cronologia_maps`, crea el entorno de Python,
instala las dependencias fijadas y puppeteer-core (necesita Node.js), y corre la prueba sin su cuenta.
Desde aquí, todos los comandos se ejecutan dentro de esa carpeta:
```
cd "$env:LOCALAPPDATA\Atlaspps\cronos\cronologia_maps"
```

## Paso 2. Token maestro (una vez)
```
.venv\Scripts\python secretos.py token
```
Le muestra un enlace de Google. Inicia sesión con su contraseña y verificación en dos pasos,
copia la cookie `oauth_token` desde F12 › Application › Cookies y la pega (no se ve al escribir).
En su cuenta aparecerá un dispositivo nuevo llamado "Android Device": es este programa.

## Paso 3. Clave de descifrado (una vez)
```
.venv\Scripts\python secretos.py clave
```
Abre Chrome; Google le pide su contraseña otra vez y entrega la clave. Si usa Edge:
`--chrome "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"`.

## Paso 4. Probar
```
.venv\Scripts\python secretos.py estado
.venv\Scripts\python sincronizar.py
```

## Paso 5. Programar cada noche
```
schtasks /Create /TN "Atlas\CronologiaMaps" /SC DAILY /ST 21:00 /TR "\"%LOCALAPPDATA%\Atlaspps\cronos\cronologia_maps\.venv\Scripts\pythonw.exe\" \"%LOCALAPPDATA%\Atlaspps\cronos\cronologia_maps\sincronizar.py\""
```
Corre con su sesión iniciada (necesario para leer el Administrador de credenciales).
No guarda su contraseña de Windows.

## Revocar o desactivar
- En el PC: `python secretos.py borrar` y `schtasks /Delete /TN "Atlas\CronologiaMaps"`.
- En Google: https://myaccount.google.com/device-activity › quitar "Android Device". Esto
  invalida el token aunque alguien lo hubiera copiado.

## Si deja de funcionar
`estado.json` queda con `"ok": false` y el motivo; Atlas puede avisarle con eso.
- "No se pudo descifrar" → Google cambió la clave: repita el paso 3.
- "no entregó el acceso temporal" → token revocado o vencido: repita el paso 2.
- Si Google cambia el protocolo, no se pierde nada: la base conserva lo último, y puede
  importar una exportación manual del celular con `sincronizar.py --prueba Timeline.json`.
- Si una descarga trae menos del 80 % de las visitas que ya había, no reemplaza nada.

## Origen del código
`vendor_timeline_export/` es una copia fija y revisada de github.com/ilbonte/timeline-export
(commit 488d854, licencia MIT) con tres cambios pequeños descritos en `PARCHES.md`.
No se actualiza sola.

## Pruebas (sin su cuenta)
```
.venv\Scripts\python sincronizar.py --prueba pruebas\ejemplo_timeline.json
.venv\Scripts\python pruebas\prueba_e2e.py . %TEMP%\prueba_cronologia
```
La segunda simula Google con datos cifrados sintéticos y verifica descarga, descifrado,
hora de Chile, importación y el rechazo de descargas incompletas.

"""Configura Apolo para leer las cartolas PDF de Scotiabank.

1. Instala pypdf (para abrir PDF) en el Python de Atlas, si falta.
2. Te pide los 4 últimos dígitos de tu RUT antes del guion (la clave con que Scotiabank protege
   las cartolas y el estado de cuenta) y los guarda SOLO en este PC, en clave_pdf.txt de esta carpeta.
   No se envían a ningún lado.
"""
import getpass
import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if not (importlib.util.find_spec("pypdf") and importlib.util.find_spec("cryptography")):
    print("Instalando pypdf para leer las cartolas...")
    # El Python de Atlas no trae pip: se instala con uv, como Instalar-extras.cmd
    src = Path(sys.executable).resolve().parents[2]
    try:
        subprocess.check_call(["uv", "pip", "install", "pypdf[crypto]"], cwd=src)
    except (OSError, subprocess.CalledProcessError):
        print("No pude instalar pypdf. Avísale a Claude con este mensaje.")
        input("Presiona Enter para cerrar.")
        sys.exit(1)

print()
print("Scotiabank protege las cartolas con los 4 últimos dígitos de tu RUT, antes del guion.")
print("Ejemplo: RUT 12.345.678-9  ->  5678")
while True:
    d = getpass.getpass("Escribe esos 4 dígitos (no se ven al escribir) y presiona Enter: ").strip()
    if len(d) == 4 and d.isdigit():
        break
    print("Tienen que ser 4 números. Intenta de nuevo.")
from openjarvis.security import atlas_secretos as S  # noqa: E402

cifrada = S.guardar_clave(S.APOLO_PDF, d, HERE / "clave_pdf.txt")
print()
print("Listo. Quedó " + ("cifrada en el Administrador de credenciales de Windows" if cifrada else "guardada solo en este PC")
      + ". Ahora dile a Atlas «actualiza Apolo».")
input("Presiona Enter para cerrar.")

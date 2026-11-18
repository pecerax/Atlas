"""Agrega otra cuenta de correo a Atlas (Gmail u otro proveedor con IMAP).

La contraseña se escribe oculta y se guarda cifrada en el Administrador de credenciales de Windows
(entrada Atlas-Correo-<correo>). En ~/.atlas/connectors/mail_accounts/<correo>.json queda solo
el servidor IMAP, sin la contraseña.
"""
import getpass

try:  # verificación de certificados con el almacén de Windows (no la desactiva)
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    print("Aviso: falta 'truststore'. Instálalo con:  uv pip install truststore")

import openjarvis.tools  # noqa: F401  (registra las herramientas)
from openjarvis.tools.gmail_mark_read import add_account, mail_accounts

print("=== Agregar una cuenta de correo a Atlas ===")
print("Cuentas conectadas ahora:")
for label, _ in mail_accounts():
    print("  -", label)
print()
email = input("Correo a agregar (ej. otra.cuenta@gmail.com): ").strip()
if not email:
    raise SystemExit("Cancelado.")
domain = email.split("@")[-1].lower()
host = ""
if domain not in ("gmail.com", "googlemail.com"):
    print("Cuenta que no es @gmail.com. Si conoces el servidor IMAP escríbelo")
    print("(ej. mail.correo-empresa.example para Namecheap). Enter = detectar automáticamente.")
    host = input("Servidor IMAP: ").strip()
    pw_label = "Contraseña de esa cuenta (o contraseña de aplicación, si tu proveedor la ofrece)"
else:
    pw_label = "Contraseña de aplicación de esa cuenta"
pw = getpass.getpass(pw_label + " (no se verá al escribir): ")
if domain in ("gmail.com", "googlemail.com"):
    pw = pw.replace(" ", "")
print("Probando la conexión…")
try:
    used = add_account(email, pw, host)
    print(f"Servidor: {used}")
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"\nNo se pudo conectar.\n{exc}\n\nSi dice 'authentication failed' o 'LOGIN failed', la contraseña no es correcta.")
print(f"\nListo: {email} quedó conectada. Cierra y abre Atlas para usarla.")

"""Guarda (solo en este PC) la clave con que MACH protege sus cartolas PDF.

MACH protege la cartola con tu RUT sin puntos, sin guion y sin dígito verificador
(ejemplo: RUT 12.345.678-9  ->  12345678). Queda en clave_mach.txt de esta carpeta y no se envía a ningún lado.
"""
import getpass
from pathlib import Path

HERE = Path(__file__).resolve().parent
print("MACH protege sus cartolas con tu RUT sin puntos, sin guion y sin el dígito verificador.")
print("Ejemplo: RUT 12.345.678-9  ->  12345678")
while True:
    d = getpass.getpass("Escríbelo (no se ve al escribir) y presiona Enter: ").strip().replace(".", "")
    if d.isdigit() and 7 <= len(d) <= 8:
        break
    print("Tienen que ser 7 u 8 números. Intenta de nuevo.")

# prueba la clave con una cartola de MACH ya bajada, sin mostrar su contenido
pdfs = sorted((HERE / "cartolas").glob("*MACHBANK*.pdf"))
if pdfs:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdfs[-1]))
        if r.is_encrypted and not r.decrypt(d):
            print()
            print("Esa clave no abre la cartola de MACH. Revisa el número y vuelve a abrir este archivo.")
            input("Presiona Enter para cerrar.")
            raise SystemExit(1)
    except ImportError:
        pass
from openjarvis.security import atlas_secretos as S  # noqa: E402

cifrada = S.guardar_clave(S.APOLO_MACH, d, HERE / "clave_mach.txt")
print()
print("Listo: la clave abre las cartolas de MACH y quedó "
      + ("cifrada en el Administrador de credenciales de Windows." if cifrada else "guardada solo en este PC."))
print("Ya puedes cerrar esta ventana y avisarle a Claude.")
input("Presiona Enter para cerrar.")

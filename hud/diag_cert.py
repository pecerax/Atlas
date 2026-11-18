"""Diagnóstico: muestra quién firma el certificado de mail.correo-empresa.example.
Solo lee el certificado público del servidor; no envía ninguna contraseña."""
import socket
import ssl

HOST, PORT = "mail.correo-empresa.example", 993
print(f"Conectando a {HOST}:{PORT} para leer su certificado (sin enviar datos)…\n")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE  # solo para INSPECCIONAR el certificado; no se usa para el correo
with socket.create_connection((HOST, PORT), timeout=15) as sock:
    with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
        der = tls.getpeercert(binary_form=True)
        chain = []
        try:
            chain = tls.get_unverified_chain() or []  # Python 3.13+
        except AttributeError:
            pass

def describe(der_bytes):
    try:
        from cryptography import x509
        c = x509.load_der_x509_certificate(der_bytes)
        return c.subject.rfc4514_string(), c.issuer.rfc4514_string()
    except Exception as exc:  # noqa: BLE001
        return f"(no pude leerlo: {exc})", ""

certs = chain or [der]
print(f"El servidor envió {len(certs)} certificado(s):")
for i, c in enumerate(certs):
    if not isinstance(c, (bytes, bytearray)):
        c = c.public_bytes(ssl.Encoding.DER) if hasattr(c, "public_bytes") else bytes(c)
    subj, iss = describe(c)
    print(f"  [{i}] Para:      {subj}\n      Emitido por: {iss}")

print("\nVerificación normal de Python:")
try:
    with socket.create_connection((HOST, PORT), timeout=15) as sock:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=HOST):
            print("  OK")
except Exception as exc:  # noqa: BLE001
    print("  FALLA:", exc)

print("\nVerificación con el almacén de Windows (truststore):")
try:
    import truststore
    tctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with socket.create_connection((HOST, PORT), timeout=15) as sock:
        with tctx.wrap_socket(sock, server_hostname=HOST):
            print("  OK")
except ImportError:
    print("  truststore NO está instalado")
except Exception as exc:  # noqa: BLE001
    print("  FALLA:", exc)

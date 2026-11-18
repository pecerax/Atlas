#!/usr/bin/env python3
"""
secretos.py: configura y guarda las credenciales de la Cronología de Google Maps.

Todo se guarda en el Administrador de credenciales de Windows (vía `keyring`), que lo
cifra con DPAPI y lo liga a su usuario de Windows: otro usuario del PC, o alguien que
copie el disco a otra máquina, no puede leerlo. Nada de esto se escribe en archivos.

Comandos:
  python secretos.py token    Paso 1: canjea la cookie de inicio de sesión por el token maestro.
  python secretos.py clave    Paso 2: obtiene la clave de descifrado (abre Chrome, pide su contraseña).
  python secretos.py estado   Muestra qué está guardado (sin mostrar los valores).
  python secretos.py borrar   Elimina todo del Administrador de credenciales.

Para revocar el acceso del lado de Google: https://myaccount.google.com/device-activity
y quite el dispositivo "Android Device" que se creó en el paso 1.
"""
import argparse, getpass, json, os, secrets, subprocess, sys

SERVICIO = "Atlas-CronologiaMaps"
# Transición Jarvis -> Atlas: si un campo no está en el servicio nuevo, se lee del viejo (no se borra).
SERVICIO_VIEJO = "Jarvis-CronologiaMaps"
CAMPOS = ("email", "android_id", "master_token", "clave")
AQUI = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(AQUI, "vendor_timeline_export")

URL_LOGIN = ("https://accounts.google.com/embedded/setup/android"
             "?source=com.google.android.gms&xoauth_display_name=Android%20Device")


def _keyring():
    try:
        import keyring
    except ImportError:
        sys.exit("Falta keyring: pip install keyring")
    nombre = type(keyring.get_keyring()).__module__
    if os.name == "nt" and "Windows" not in nombre and "windows" not in nombre:
        sys.exit(f"keyring no está usando el Administrador de credenciales de Windows ({nombre}); deteniendo.")
    return keyring


def leer(campo):
    kr = _keyring()
    v = kr.get_password(SERVICIO, campo)
    return v if v is not None else kr.get_password(SERVICIO_VIEJO, campo)


def guardar(campo, valor):
    _keyring().set_password(SERVICIO, campo, valor)


def cargar_todo():
    """Para sincronizar.py: devuelve los cuatro valores o termina con un mensaje claro."""
    datos = {c: leer(c) for c in CAMPOS}
    faltan = [c for c, v in datos.items() if not v]
    if faltan:
        raise RuntimeError("Faltan credenciales (" + ", ".join(faltan) +
                           "). Ejecute: python secretos.py token  y luego  python secretos.py clave")
    return datos


def cmd_token(a):
    try:
        import gpsoauth
    except ImportError:
        sys.exit("Falta gpsoauth: pip install gpsoauth")
    email = a.email or input("Correo de su cuenta Google: ").strip()
    android_id = leer("android_id") or secrets.token_hex(8)
    if a.stdin:   # el instalador toma la cookie solo de la ventana de Google y la pasa por la entrada estándar
        ot = sys.stdin.readline().strip()
    else:
        print("\n1) Abra esta dirección en Chrome (puede ser ventana de incógnito) e inicie sesión:\n")
        print("   " + URL_LOGIN + "\n")
        print("2) Al terminar, la página queda en blanco. Eso es normal.")
        print("3) Presione F12 > pestaña Application > Cookies > https://accounts.google.com")
        print("   y copie el VALOR de la cookie 'oauth_token' (empieza con oauth2_4/).\n")
        ot = getpass.getpass("Pegue aquí el valor (no se verá en pantalla): ").strip()
    if not ot.startswith("oauth2_4/"):
        sys.exit("Eso no parece la cookie oauth_token (debe empezar con oauth2_4/). No se guardó nada.")
    r = gpsoauth.exchange_token(email, ot, android_id)
    master = r.get("Token")
    if not master:
        sys.exit(f"Google rechazó el canje: {r.get('Error') or 'sin detalle'}. "
                 "La cookie sirve una sola vez y dura minutos: repita desde el paso 1.")
    guardar("email", email)
    guardar("android_id", android_id)
    guardar("master_token", master)
    del master, ot
    print("\nListo: token maestro guardado en el Administrador de credenciales de Windows.")
    print("Siguiente paso: python secretos.py clave")


def cmd_clave(a):
    email, android_id, master = leer("email"), leer("android_id"), leer("master_token")
    if not (email and android_id and master):
        sys.exit("Primero ejecute: python secretos.py token")
    if not os.path.isdir(os.path.join(VENDOR, "node_modules", "puppeteer-core")):
        sys.exit(f"Falta puppeteer-core. Ejecute una vez:  cd \"{VENDOR}\"  y luego  npm ci")
    cmd = [sys.executable, "-I", os.path.join(VENDOR, "web_key.py"),
           "--email", email, "--android-id", android_id,
           "--master-token-file", "-", "--headful", "-o", "-"]
    if a.chrome:
        cmd += ["--chrome", a.chrome]
    print("Se abrirá Chrome. Si Google le pide la contraseña, escríbala en esa ventana.")
    env = dict(os.environ)
    node = os.path.join(os.path.dirname(AQUI), "node")   # Node portátil que deja el instalador (apps\cronos\node)
    if os.path.isfile(os.path.join(node, "node.exe")):
        env["PATH"] = node + os.pathsep + env.get("PATH", "")
    p = subprocess.run(cmd, input=master + "\n", capture_output=True, text=True, cwd=VENDOR, env=env)
    del master
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit("No se obtuvo la clave.\n" + (p.stderr or "")[-600:])
    res = json.loads(p.stdout.strip().splitlines()[-1])
    guardar("clave", res["key"])
    print(f"Listo: clave guardada (época {res.get('epoch')}). La configuración está completa.")


def cmd_estado(a):
    for c in CAMPOS:
        v = leer(c)
        print(f"  {c:13s} {'guardado' if v else 'FALTA'}" + (f"  ({v})" if c == "email" and v else ""))


def cmd_borrar(a):
    kr = _keyring()
    for c in CAMPOS:
        try:
            kr.delete_password(SERVICIO, c)
        except Exception:
            pass
        try:  # también la entrada vieja, para que la lectura de respaldo no la recupere
            kr.delete_password(SERVICIO_VIEJO, c)
        except Exception:
            pass
    print("Credenciales borradas de este PC. Para cortar también el acceso en Google:")
    print("  https://myaccount.google.com/device-activity  > quite 'Android Device'")


def main():
    ap = argparse.ArgumentParser(description="Credenciales de la Cronología de Maps para Atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token"); t.add_argument("--email")
    t.add_argument("--stdin", action="store_true", help="lee la cookie oauth_token de la entrada estándar (instalador)")
    t.set_defaults(f=cmd_token)
    k = sub.add_parser("clave"); k.add_argument("--chrome", help="ruta a chrome.exe o msedge.exe"); k.set_defaults(f=cmd_clave)
    sub.add_parser("estado").set_defaults(f=cmd_estado)
    sub.add_parser("borrar").set_defaults(f=cmd_borrar)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()

"""Pasos de cuentas del instalador que necesitan el entorno de Atlas (src\\.venv). Lo llama asistente.py:

    python -I pasos_venv.py <accion>      con los datos en JSON por la entrada estándar

Escribe una sola línea JSON al final: {"ok": bool, "detalle": "..."}. Las contraseñas llegan por la entrada estándar,
van directo al Administrador de credenciales de Windows (atlas_secretos / el conector de correo) y no se imprimen.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ATLAS = Path(os.environ.get("ATLAS_DIR") or Path(__file__).resolve().parent.parent)
HUD = ATLAS / "hud"
sys.path.insert(0, str(HUD))
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass


def fin(ok: bool, detalle: str, **extra) -> None:
    print(json.dumps({"ok": ok, "detalle": detalle, **extra}, ensure_ascii=False), flush=True)
    sys.exit(0)


def edge() -> str | None:
    cands = [shutil.which("msedge"),
             os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
             os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def ucursos(d: dict) -> None:
    import atlas_ucursos_notas as U

    e = edge()
    if not e:
        fin(False, "No encontré Microsoft Edge para abrir U-Cursos")
    r = U.login(e, log=lambda *_: None)
    if r != "ok":
        fin(False, "No alcanzó a iniciar sesión. Presione Reintentar." if r == "timeout" else r.removeprefix("error: "))
    try:
        n = U.check()["revisados"]
        fin(True, f"Conectado · {n} ramos")
    except Exception:  # noqa: BLE001
        fin(True, "Conectado")


def canvas(d: dict) -> None:
    import atlas_canvas_notas as C

    url = C.normalize_url(str(d.get("url") or ""))
    if not url:
        fin(False, "Falta la dirección de Canvas de su universidad")
    e = edge()
    if not e:
        fin(False, "No encontré Microsoft Edge para abrir Canvas")
    r = C.login(e, url, log=lambda *_: None)
    if r != "ok":
        fin(False, "No alcanzó a iniciar sesión. Presione Reintentar." if r == "timeout" else r.removeprefix("error: "))
    fin(True, "Conectado · " + url.split("//")[-1])


def correo(d: dict) -> None:
    import openjarvis.tools  # noqa: F401  (registra las herramientas)
    from openjarvis.tools.gmail_mark_read import add_account

    email = str(d.get("email") or "").strip()
    clave = str(d.get("clave") or "").replace(" ", "")
    d.clear()
    if "@" not in email or len(clave) < 8:
        fin(False, "Revise el correo y las 16 letras")
    try:
        add_account(email, clave)
    except Exception as exc:  # noqa: BLE001
        txt = str(exc).lower()
        if "authenticationfailed" in txt or "invalid credentials" in txt or "application-specific" in txt:
            fin(False, "Google no aceptó esas 16 letras. Cree una contraseña de aplicación nueva y péguela otra vez.")
        fin(False, "No pude entrar al correo. Revise que copió bien las 16 letras.")
    fin(True, "Conectado · " + email)


def calendario(d: dict) -> None:
    import atlas_gcal as gcal

    cliente = ATLAS / "instalador" / "google_cliente.json"    # la llave propia de Atlas (decisión 1)
    gcal.CONN.mkdir(parents=True, exist_ok=True)
    if not gcal.CLIENT.exists():
        if not cliente.exists():
            fin(False, "Esta versión del instalador aún no trae la llave de Google. Se conecta después en Ajustes.")
        gcal.atlas_secretos.guardar_json(gcal.CLIENT, json.loads(cliente.read_text(encoding="utf-8")))
    try:
        nombre = gcal.connect()
    except Exception as exc:  # noqa: BLE001
        fin(False, f"No se pudo conectar: {str(exc)[:120]}")
    fin(True, f"Conectado · {nombre}")


def hermes(d: dict) -> None:
    from openjarvis.security import atlas_secretos as SEC

    clave = str(d.get("clave") or "")
    d.clear()
    if clave:
        if len(clave) > 200 or "\x00" in clave:
            fin(False, "Esa contraseña no es válida")
        SEC.guardar(SEC.HERMES_PDF, clave)
    fin(True, "Contraseña guardada" if clave else "Sin contraseña de PDF")


def cronos_modo(d: dict) -> None:
    import atlas_historia as H

    modo = d.get("modo")
    if modo not in ("rutas", "senales"):
        fin(False, "Modo desconocido")
    H.guardar_config(modo_ubicacion=modo)
    fin(True, "Manual: señales" if modo == "senales" else "Automático: Rutas de Maps")


URL_LOGIN = ("https://accounts.google.com/embedded/setup/android"
             "?source=com.google.android.gms&xoauth_display_name=Android%20Device")
CDP = 9226   # U-Cursos usa 9224 y Canvas 9225


def cronos_cookie(d: dict) -> None:
    """Abre Google en una ventana propia y espera la cookie oauth_token que antes se copiaba a mano desde F12.
    La devuelve una sola vez a asistente.py, que la pasa por la entrada estándar a secretos.py token --stdin."""
    import subprocess

    from websockets.sync.client import connect

    e = edge()
    if not e:
        fin(False, "No encontré Microsoft Edge")
    perfil = ATLAS / "apps" / "cronos" / "google-profile"
    p = subprocess.Popen([e, f"--app={URL_LOGIN}", f"--user-data-dir={perfil}", f"--remote-debugging-port={CDP}",
                          "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                          "--window-size=520,760"])

    def cdp(path):
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP}{path}", timeout=3) as r:  # noqa: S310 (local)
            return json.loads(r.read().decode("utf-8"))

    fin_t = time.time() + 900
    try:
        while time.time() < fin_t:
            time.sleep(2)
            try:
                ws = cdp("/json/version")["webSocketDebuggerUrl"]
                with connect(ws, open_timeout=5, max_size=2**23) as w:
                    w.send(json.dumps({"id": 1, "method": "Storage.getCookies", "params": {}}))
                    while True:
                        m = json.loads(w.recv(timeout=10))
                        if m.get("id") == 1:
                            break
                c = next((x for x in (m.get("result") or {}).get("cookies") or []
                          if x.get("name") == "oauth_token" and str(x.get("value", "")).startswith("oauth2_4/")), None)
            except Exception:  # noqa: BLE001
                if p.poll() is not None:
                    fin(False, "Se cerró la ventana de Google antes de terminar")
                continue
            if c:
                fin(True, "Sesión de Google lista", cookie=c["value"])
        fin(False, "No alcanzó a iniciar sesión en Google. Presione Reintentar.")
    finally:
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass


SYNCTHING_GUI = "Atlas-Syncthing-GUI"


def syncthing_gui(d: dict) -> None:
    """Pone usuario y contraseña al panel web de Syncthing (127.0.0.1:8384), para que nadie tenga que hacerlo a mano.
    Se generan al azar, se guardan solo en el Administrador de credenciales de Windows y no se muestran ni se
    registran. Atlas no los necesita: habla con Syncthing con la clave de API de config.xml. Si el panel ya tiene
    usuario (lo puso la persona), no se toca."""
    import re
    import secrets as _s

    from openjarvis.security import atlas_secretos as SEC

    cfg = Path(os.environ.get("LOCALAPPDATA", "")) / "Syncthing" / "config.xml"
    if not cfg.exists():
        fin(False, "Syncthing aún no está configurado")
    t = cfg.read_text(encoding="utf-8", errors="replace")
    k = re.search(r"<apikey>([^<]+)</apikey>", t)
    a = re.search(r"<gui[^>]*>.*?<address>([^<]+)</address>", t, re.S)
    if not k:
        fin(False, "Syncthing no tiene clave de API")
    base, cab = f"http://{a.group(1) if a else '127.0.0.1:8384'}", {"X-API-Key": k.group(1), "Content-Type": "application/json"}

    def pedir(metodo, cuerpo=None):
        req = urllib.request.Request(base + "/rest/config/gui", method=metodo, headers=cab,
                                     data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (local)
            b = r.read()
            return json.loads(b) if b.strip() else {}

    if (pedir("GET").get("user") or "").strip():
        fin(True, "El panel de Syncthing ya tenía usuario")
    usuario, clave = "atlas", _s.token_urlsafe(24)
    SEC.guardar(SYNCTHING_GUI, json.dumps({"usuario": usuario, "clave": clave}))   # primero guardarla: si no, nadie la sabría
    pedir("PATCH", {"user": usuario, "password": clave})   # Syncthing la guarda con bcrypt en config.xml
    del clave
    fin(True, "Panel de Syncthing protegido con contraseña")


ACCIONES = {"syncthing_gui": syncthing_gui, "ucursos": ucursos, "canvas": canvas, "correo": correo, "calendario": calendario, "hermes": hermes,
            "cronos_modo": cronos_modo, "cronos_cookie": cronos_cookie}

if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        datos = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        datos = {}
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    if accion not in ACCIONES:
        fin(False, "acción desconocida")
    try:
        ACCIONES[accion](datos)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        fin(False, f"Algo falló ({type(exc).__name__})")

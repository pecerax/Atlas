"""Ayudante local para el botón «Actualizar» de mis_fondos.html.

Escucha solo en 127.0.0.1:8932 y hace una sola cosa: correr
actualizar_fondos.py (descarga los valores cuota de la CMF) cuando la
página lo pide. No toca nada fuera de esta carpeta, salvo los aportes anotados a
mano en la página (/aportes), que guarda en ~/.atlas/fortuna_aportes.json con el
mismo módulo de Atlas (hud\atlas_fortuna_aportes.py), igual que dentro de Atlas.

Arranca con Windows (acceso en la carpeta Inicio, con --siempre) y queda escuchando.
Si lo inicia «Mis Fondos.cmd» sin --siempre, se apaga tras 2 horas sin uso.
Si ya hay uno corriendo, este se cierra sin hacer nada.
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUERTO = 8932
FRESCO_SEG = 2 * 3600      # si se actualizó hace menos de esto, no se vuelve a bajar (salvo «forzar»)
APAGAR_SEG = 2 * 3600      # se cierra tras este tiempo sin pedidos

estado = {"corriendo": False, "ultimo": 0.0, "error": "", "ok": None}


def _aportes():
    """atlas_fortuna_aportes.py de Atlas (el mismo archivo de aportes que usa la página dentro de Atlas), o None."""
    import importlib.util
    import os

    f = Path(os.environ.get("ATLAS_FORTUNA_APORTES_PY")
             or Path(os.environ.get("LOCALAPPDATA", "")) / "Atlas" / "hud" / "atlas_fortuna_aportes.py")
    try:
        spec = importlib.util.spec_from_file_location("atlas_fortuna_aportes", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None
lock = threading.Lock()
ultimo_uso = time.time()


def correr():
    global estado
    py = sys.executable.replace("pythonw.exe", "python.exe")
    try:
        r = subprocess.run(
            [py, str(HERE / "actualizar_fondos.py"), "--no-abrir"],
            cwd=HERE, capture_output=True, text=True, timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = r.returncode == 0
        err = "" if ok else (r.stderr or r.stdout or "error desconocido")[-400:]
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)[-400:]
    with lock:
        estado.update(corriendo=False, ultimo=time.time(), ok=ok, error=err)


MISMO_ORIGEN = (f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}")


class H(BaseHTTPRequestHandler):
    # 18-11-2026 (auditoría de seguridad): la página se sirve desde aquí mismo (http://127.0.0.1:8932/), así que no
    # hace falta CORS. Antes se aceptaba Origin «null» y se devolvía en CORS: cualquier sitio con un iframe sandbox
    # podía leer o cambiar los aportes. Ahora solo el Host de este PC (contra DNS rebinding) y la misma página.
    def _origen_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        o = self.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (o is None or o in MISMO_ORIGEN)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _pagina(self):
        body = (HERE / "mis_fondos.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global ultimo_uso
        ultimo_uso = time.time()
        if not self._origen_ok():
            return self._json(403, {"error": "origen"})
        if self.path.split("?")[0] in ("/", "/mis_fondos.html"):
            return self._pagina()
        if self.path.startswith("/estado"):
            with lock:
                return self._json(200, dict(estado))
        if self.path.split("?")[0] == "/aportes":
            mod = _aportes()
            return self._json(*mod.http("GET")) if mod else self._json(404, {"error": "sin Atlas"})
        self._json(404, {"error": "no existe"})

    def do_POST(self):
        global ultimo_uso
        ultimo_uso = time.time()
        if not self._origen_ok() or self.headers.get("Origin") not in MISMO_ORIGEN:  # los POST del navegador traen Origin
            return self._json(403, {"error": "origen"})
        if self.path.split("?")[0] == "/aportes":
            mod = _aportes()
            if not mod:
                return self._json(404, {"error": "sin Atlas"})
            n = int(self.headers.get("Content-Length") or 0)
            return self._json(*mod.http("POST", self.rfile.read(min(n, 400_000))))
        if not self.path.startswith("/actualizar"):
            return self._json(404, {"error": "no existe"})
        forzar = "forzar" in self.path
        with lock:
            if estado["corriendo"]:
                return self._json(200, {**estado, "accion": "ya_corriendo"})
            if not forzar and estado["ok"] and time.time() - estado["ultimo"] < FRESCO_SEG:
                return self._json(200, {**estado, "accion": "reciente"})
            estado.update(corriendo=True, error="", ok=None)
        threading.Thread(target=correr, daemon=True).start()
        with lock:
            return self._json(200, {**estado, "accion": "iniciado"})

    def log_message(self, *a):
        pass


def vigilar(srv):
    if "--siempre" in sys.argv:
        return  # arranca con Windows: queda escuchando siempre (no gasta casi nada)
    while True:
        time.sleep(60)
        if not estado["corriendo"] and time.time() - ultimo_uso > APAGAR_SEG:
            srv.shutdown()
            return


def main():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), H)
    except OSError:
        return  # ya hay uno corriendo
    threading.Thread(target=vigilar, args=(srv,), daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()

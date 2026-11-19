"""Asistente de instalación de Atlas (18-11-2026).

Lo abre Atlas-Instalar.exe después de copiar los archivos. Solo usa la biblioteca estándar de Python, así corre con el
Python que trae uv antes de que exista el entorno de Atlas. Levanta una página local (127.0.0.1, puerto al azar) y la
abre en una ventana de Edge sin barras; la página muestra las pantallas y este archivo hace el trabajo:

  1. Instalar: Python y componentes, Ollama y el modelo, oído y voces, Syncthing, acceso directo.
  2. Cuentas, una por una al final: U-Cursos, Canvas, correo, Calendario, Hermes y Cronos. Los pasos que necesitan el
     entorno de Atlas corren con pasos_venv.py dentro de ese entorno; las contraseñas le llegan por la entrada estándar
     y van directo al Administrador de credenciales de Windows. Nunca se escriben en archivos ni en registros.
  3. Terminar: abre Atlas en el asistente de primera vez (micrófono y voz).

Cada paso se puede repetir: si algo ya está hecho, se salta. El avance queda en instalador/estado.json (sin secretos).
Uso:  python asistente.py [--atlas CARPETA] [--sin-ventana] [--simular]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HOME = Path.home()
LOCAL = Path(os.environ.get("LOCALAPPDATA") or (HOME / "AppData" / "Local"))
ATLAS = AQUI.parent                       # %LOCALAPPDATA%\Atlas (el instalador copia todo ahí)
DATOS = HOME / ".atlas"                   # datos de Atlas; ~/.openjarvis es una unión hacia aquí
SIN_VENTANA = 0x08000000                  # CREATE_NO_WINDOW

OPENJARVIS_ZIP = "https://github.com/open-jarvis/OpenJarvis/archive/{sha}.zip"
OLLAMA_SETUP = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_API = "http://127.0.0.1:11434"
MODELO_GRANDE, MODELO_CHICO = "qwen3.5:9b", "qwen3.5:4b"   # el chico, en PCs sin tarjeta NVIDIA (decisión 4)
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{lang}/{loc}/{name}/{q}/{loc}-{name}-{q}.onnx"
VOCES = [("es", "es_ES", "davefx", "medium"), ("en", "en_GB", "alan", "medium"),    # las dos que usa Atlas hoy
         ("es", "es_MX", "ald", "medium"), ("es", "es_MX", "claude", "high")]       # para elegir voz (decisión 3)
CANVAS_U = {"Universidad Católica": "cursos.canvas.uc.cl"}   # otras: la persona escribe la dirección (solo las confirmadas)

# ------------------------------------------------------------------------------------------------ estado (sin secretos)
PASOS = [  # id, título que ve la persona, tamaño aproximado para la barra (peso)
    ("requisitos", "Revisar el computador", 1),
    ("componentes", "Componentes de Atlas", 20),
    ("ollama", "Ollama", 15),
    ("modelo", "El cerebro de Atlas", 45),
    ("voz", "Oído y voces en español", 12),
    ("syncthing", "Programa para recibir avisos del banco", 4),
    ("acceso", "Acceso directo en el escritorio", 1),
]
CUENTAS = ["ucursos", "canvas", "correo", "calendario", "hermes", "cronos"]
_lock = threading.RLock()
ESTADO: dict = {}
ARCHIVO_ESTADO = AQUI / "estado.json"
SIMULAR = False
ULTIMO_PULSO = time.time()


def _nuevo_estado() -> dict:
    return {"fase": "bienvenida", "requisitos": {},
            "pasos": {p: {"estado": "espera", "detalle": "", "progreso": 0.0} for p, _, _ in PASOS},
            "cuentas": {c: {"estado": "espera", "detalle": ""} for c in CUENTAS},
            "modelo": MODELO_GRANDE, "correo": "", "cronos_modo": "", "autoarranque": True}


def cargar_estado() -> None:
    global ESTADO
    ESTADO = _nuevo_estado()
    try:
        viejo = json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
        for k in ("fase", "modelo", "correo", "cronos_modo", "autoarranque", "requisitos"):
            if k in viejo:
                ESTADO[k] = viejo[k]
        for grupo in ("pasos", "cuentas"):
            for k, v in (viejo.get(grupo) or {}).items():
                if k in ESTADO[grupo]:
                    ESTADO[grupo][k].update(v)
                    if v.get("estado") == "corriendo":      # se cortó a medias: se vuelve a intentar
                        ESTADO[grupo][k]["estado"] = "espera"
    except Exception:  # noqa: BLE001
        pass


def guardar_estado() -> None:
    with _lock:
        tmp = ARCHIVO_ESTADO.with_suffix(".tmp")
        tmp.write_text(json.dumps(ESTADO, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ARCHIVO_ESTADO)


def marcar(grupo: str, clave: str, **kw) -> None:
    with _lock:
        ESTADO[grupo][clave].update(kw)
        guardar_estado()


def registro(texto: str) -> None:
    """Registro para diagnóstico: solo qué paso corre y cómo terminó. Nunca contraseñas, tokens ni correos."""
    try:
        with open(AQUI / "instalacion.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ utilidades
def correr(cmd: list[str], cwd: Path | None = None, entrada: str | None = None, timeout: float = 3600,
           env: dict | None = None) -> subprocess.CompletedProcess:
    registro("  $ " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))[:300])
    return subprocess.run(cmd, cwd=cwd, input=entrada, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=SIN_VENTANA,
                          env={**os.environ, **(env or {})})


def descargar(url: str, destino: Path, avance=None, intentos: int = 6) -> None:
    """Descarga con reanudación: si se corta internet, sigue desde donde quedó (Range)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    for intento in range(intentos):
        hecho = parcial.stat().st_size if parcial.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "Atlas-Instalador/1.0",
                                                   **({"Range": f"bytes={hecho}-"} if hecho else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if hecho and r.status != 206:      # el servidor no acepta reanudar: desde cero
                    hecho = 0
                total = hecho + int(r.headers.get("Content-Length") or 0)
                with open(parcial, "ab" if hecho else "wb") as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        hecho += len(b)
                        if avance and total:
                            avance(hecho, total)
            parcial.replace(destino)
            return
        except Exception as exc:  # noqa: BLE001
            registro(f"  descarga cortada ({type(exc).__name__}), intento {intento + 1}")
            if avance:
                avance(hecho, 0, pausa=True)
            time.sleep(min(60, 5 * (intento + 1)))
    raise RuntimeError("Se cortó la conexión a internet y no se pudo retomar la descarga")


def gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",") + " GB"


def version_atlas() -> str:
    try:
        return (ATLAS / "VERSION").read_text(encoding="utf-8-sig").strip()[:20]
    except OSError:
        return ""


def venv_py(nombre: str = "python.exe") -> Path:
    return ATLAS / "src" / ".venv" / "Scripts" / nombre


def python_atlas() -> str:
    """El Python que el instalador descomprime en Atlas\python (sin uv ni enlaces). Si no está, «3.13» para que uv
    use uno suyo (camino antiguo)."""
    py = ATLAS / "python" / "python.exe"
    return str(py) if py.exists() else "3.13"


def uv() -> str:
    for c in (AQUI / "uv.exe", HOME / ".local" / "bin" / "uv.exe"):
        if c.exists():
            return str(c)
    return shutil.which("uv") or "uv"


def edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), str(LOCAL)):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def ps(script: str, timeout: float = 120) -> str:
    return correr(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout).stdout.strip()


# ------------------------------------------------------------------------------------------------ 0 · requisitos
def revisar_requisitos() -> dict:
    libre = shutil.disk_usage(str(LOCAL)).free
    try:
        gpus = ps("(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join '|'")
    except Exception:  # noqa: BLE001
        gpus = ""
    nvidia = next((g for g in gpus.split("|") if "nvidia" in g.lower()), "")
    vram = ""
    if nvidia and shutil.which("nvidia-smi"):
        try:
            mb = correr(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], timeout=20).stdout
            vram = f" · {round(int(mb.split()[0]) / 1024)} GB"
        except Exception:  # noqa: BLE001
            pass
    try:
        socket.create_connection(("ollama.com", 443), timeout=8).close()
        internet = True
    except OSError:
        internet = False
    ver = sys.getwindowsversion() if hasattr(sys, "getwindowsversion") else None
    win11 = bool(ver and ver.build >= 22000)
    r = {"windows": {"ok": bool(ver and ver.major >= 10), "texto": "Windows 11" if win11 else "Windows 10"},
         "espacio": {"ok": libre > 12e9, "texto": f"{gb(libre)} libres"},
         "gpu": {"ok": bool(nvidia), "texto": (nvidia.replace("NVIDIA GeForce ", "NVIDIA ") + vram) if nvidia
                 else "Sin tarjeta NVIDIA: usaré un modelo más chico"},
         "internet": {"ok": internet, "texto": "Conectado" if internet else "Sin conexión"}}
    with _lock:
        ESTADO["requisitos"] = r
        ESTADO["modelo"] = MODELO_GRANDE if nvidia else MODELO_CHICO
        guardar_estado()
    return r


# ------------------------------------------------------------------------------------------------ 1 · componentes
def paso_componentes(av) -> str:
    src = ATLAS / "src"
    oj = ATLAS / "openjarvis"                  # BASE.txt, atlas.patch y archivos\ (los trae el repositorio)
    sha = re.search(r"[0-9a-f]{40}", (oj / "BASE.txt").read_text(encoding="utf-8")).group(0)
    av(0.02, "Preparando Python")
    if python_atlas() == "3.13":
        r = correr([uv(), "python", "install", "3.13", "--no-bin"], timeout=1800)
        if r.returncode:
            raise RuntimeError("No se pudo instalar Python: " + r.stderr[-300:])
    if not (src / "pyproject.toml").exists():
        av(0.08, "Descargando el núcleo de Atlas")
        z = AQUI / "descargas" / f"openjarvis-{sha[:7]}.zip"
        descargar(OPENJARVIS_ZIP.format(sha=sha), z, lambda h, t, pausa=False: av(0.08 + 0.12 * (h / t if t else 0),
                                                                                  "Descargando el núcleo de Atlas", pausa))
        tmp = AQUI / "descargas" / "oj_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
        raiz = next(tmp.iterdir())
        src.mkdir(exist_ok=True)
        for p in raiz.iterdir():
            shutil.move(str(p), str(src / p.name))
        shutil.rmtree(tmp, ignore_errors=True)
        av(0.22, "Aplicando los cambios de Atlas")
        aplicar_parche(oj / "atlas.patch", src)
        for f in (oj / "archivos").rglob("*"):
            if f.is_file():
                d = src / f.relative_to(oj / "archivos")
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d)
    if not venv_py().exists():
        av(0.25, "Creando el entorno de Atlas")
        r = correr([uv(), "venv", str(src / ".venv"), "--python", python_atlas(), "--prompt", "atlas"], cwd=src)
        if r.returncode:
            raise RuntimeError("No se pudo crear el entorno: " + r.stderr[-300:])
    av(0.3, "Instalando componentes (unos minutos)")
    reqs = AQUI / "requisitos.txt"
    r = correr([uv(), "pip", "install", "--python", str(venv_py()), "-r", str(reqs)], cwd=src, timeout=3600)
    if r.returncode:
        raise RuntimeError("No se pudieron instalar los componentes: " + r.stderr[-400:])
    av(0.85, "Instalando el núcleo de Atlas")
    ruedas = sorted((AQUI / "ruedas").glob("*.whl"))
    r = correr([uv(), "pip", "install", "--python", str(venv_py()), "--no-deps", *map(str, ruedas),
                "-e", str(src)], cwd=src, timeout=1200)
    if r.returncode:
        raise RuntimeError("No se pudo instalar el núcleo: " + r.stderr[-400:])
    preparar_datos()
    # Atlas.exe (el lanzador con nombre e ícono de Atlas); si falla, Atlas.cmd lo crea al abrir o usa pythonw
    correr([str(venv_py("pythonw.exe")), str(ATLAS / "hud" / "atlas_crear_exe.py")], cwd=ATLAS / "hud", timeout=120)
    return "Instalado"


def aplicar_parche(parche: Path, raiz: Path) -> None:
    """Aplica un diff de git (atlas.patch) sin necesitar git: busca cada bloque por su contexto."""
    texto = parche.read_text(encoding="utf-8")
    for archivo in re.split(r"(?m)^diff --git ", texto)[1:]:
        m = re.search(r"(?m)^\+\+\+ b/(.+)$", archivo)
        if not m:
            continue
        destino = raiz / m.group(1).strip()
        crlf = destino.exists() and b"\r\n" in destino.read_bytes()[:4000]
        lineas = destino.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if destino.exists() else []
        for bloque in re.split(r"(?m)^(?=@@ )", archivo)[1:]:
            cuerpo = bloque.split("\n")[1:]
            if cuerpo and cuerpo[-1] == "":
                cuerpo = cuerpo[:-1]
            viejo = [l[1:] for l in cuerpo if l[:1] in (" ", "-")]
            nuevo = [l[1:] for l in cuerpo if l[:1] in (" ", "+")]
            pos = next((i for i in range(len(lineas) - len(viejo) + 1) if lineas[i:i + len(viejo)] == viejo), None)
            if pos is None:
                raise RuntimeError(f"El parche de Atlas no calza en {m.group(1)}")
            lineas[pos:pos + len(viejo)] = nuevo
        out = "\n".join(lineas)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))


def preparar_datos() -> None:
    """~/.atlas con su config.toml; ~/.openjarvis apunta ahí (OpenJarvis lee esa ruta)."""
    DATOS.mkdir(exist_ok=True)
    (DATOS / "avisos_banco").mkdir(exist_ok=True)
    oj = HOME / ".openjarvis"
    if not oj.exists():
        correr(["cmd", "/c", "mklink", "/J", str(oj), str(DATOS)])
    cfg = DATOS / "config.toml"
    if not cfg.exists():
        plantilla = (AQUI / "config.plantilla.toml").read_text(encoding="utf-8")
        cfg.write_text(plantilla.replace("{MODELO}", ESTADO["modelo"]), encoding="utf-8")
    aj = ATLAS / "hud" / "ajustes.json"
    if not aj.exists() and (ATLAS / "hud" / "ajustes.ejemplo.json").exists():
        shutil.copy2(ATLAS / "hud" / "ajustes.ejemplo.json", aj)


# ------------------------------------------------------------------------------------------------ 2 · Ollama y modelo
def ollama_exe() -> Path | None:
    for p in (LOCAL / "Programs" / "Ollama" / "ollama.exe", Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe"):
        if p.exists():
            return p
    w = shutil.which("ollama")
    return Path(w) if w else None


def ollama_responde() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_API + "/api/tags", timeout=4) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def paso_ollama(av) -> str:
    if not ollama_exe():
        dest = AQUI / "descargas" / "OllamaSetup.exe"
        if not dest.exists():
            descargar(OLLAMA_SETUP, dest, lambda h, t, pausa=False: av(0.9 * h / t if t else 0,
                                                                      f"Descargando · {gb(h)} de {gb(t)}" if t else "", pausa))
        av(0.92, "Instalando Ollama")
        r = correr([str(dest), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], timeout=1800)
        if r.returncode:
            raise RuntimeError("El instalador de Ollama falló")
    if not ollama_responde():
        exe = ollama_exe()
        if exe:
            subprocess.Popen([str(exe), "serve"], creationflags=SIN_VENTANA, cwd=str(exe.parent))
        for _ in range(60):
            if ollama_responde():
                break
            time.sleep(2)
        else:
            raise RuntimeError("Ollama quedó instalado pero no responde")
    return "Listo"


class ErrorOllama(Exception):
    """Ollama contestó con un error propio (no es un corte de internet)."""


def hay_internet() -> bool:
    try:
        with urllib.request.urlopen("https://registry.ollama.ai/v2/", timeout=10):
            return True
    except urllib.error.HTTPError:
        return True                      # respondió (401): hay internet
    except Exception:  # noqa: BLE001
        return False


def paso_modelo(av) -> str:
    """Baja el modelo con Ollama. Ollama guarda lo descargado y retoma donde quedó, así que reintentar no pierde nada.
    Mientras la descarga avance se sigue intentando; solo se rinde tras varios intentos seguidos sin avanzar, y el
    mensaje dice la causa real: sin internet, sin espacio o un error de Ollama (antivirus o firewall, por lo común)."""
    modelo = ESTADO["modelo"]
    fallos, mejor, ultimo = 0, 0, ""
    while fallos < 10:
        try:
            if not ollama_responde():
                paso_ollama(lambda *a, **k: None)     # Ollama se cerró: se vuelve a levantar
            with urllib.request.urlopen(OLLAMA_API + "/api/tags", timeout=10) as r:
                if any(m.get("name") == modelo for m in json.loads(r.read()).get("models") or []):
                    return "Descargado"
            req = urllib.request.Request(OLLAMA_API + "/api/pull", data=json.dumps({"model": modelo}).encode(),
                                         headers={"Content-Type": "application/json"})
            # 15 minutos sin noticias: al final Ollama revisa el archivo grande y puede estar callado un buen rato.
            with urllib.request.urlopen(req, timeout=900) as r:
                for linea in r:
                    ev = json.loads(linea or b"{}")
                    if ev.get("error"):
                        raise ErrorOllama(ev["error"])
                    tot, hecho = ev.get("total") or 0, ev.get("completed") or 0
                    if tot > 5e8:              # la capa grande del modelo es la que importa para la barra
                        av(hecho / tot, f"{gb(hecho)} · {round(100 * hecho / tot)} %")
                        if hecho > mejor:
                            mejor, fallos = hecho, 0      # avanzó: el contador de intentos vuelve a cero
                    if ev.get("status") == "success":
                        return "Descargado"
            raise ErrorOllama("la descarga terminó sin confirmarse")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            texto = str(exc)[:200]
            registro(f"  modelo: intento {fallos} falló ({type(exc).__name__}: {texto})")
            if "space" in texto.lower() or "espacio" in texto.lower():
                raise RuntimeError("Se llenó el disco. Libere espacio (el modelo necesita unos 7 GB) y presione Reintentar.")
            if not hay_internet():
                ultimo = "Se cortó la conexión a internet."
                av(None, "Sin internet: esperando para seguir", pausa=True)
            else:
                ultimo = ("Hay internet, pero Ollama no pudo descargar el modelo"
                          + (f" ({texto})" if isinstance(exc, ErrorOllama) else "")
                          + ". Puede ser un antivirus, un firewall o la red (por ejemplo, la de una universidad o empresa).")
                av(None, f"Reintentando ({fallos} de 10)…")
            time.sleep(min(60, 10 * fallos))
    raise RuntimeError(ultimo + " Lo ya descargado no se pierde: presione Reintentar para seguir desde ahí.")


# ------------------------------------------------------------------------------------------------ 3 · voz
def paso_voz(av) -> str:
    voces = ATLAS / "voices"
    for i, (lang, loc, name, q) in enumerate(VOCES):
        base = f"{loc}-{name}-{q}"
        for ext in (".onnx", ".onnx.json"):
            d = voces / (base + ext)
            if not d.exists():
                descargar(PIPER.format(lang=lang, loc=loc, name=name, q=q) + (".json" if ext.endswith("json") else ""), d)
        av(0.05 + 0.25 * (i + 1) / len(VOCES), "Voces en español")
    if not (voces / "parakeet-v3").is_dir():
        av(0.32, "Reconocimiento de voz Parakeet (unos 490 MB)")
        r = correr([str(venv_py()), str(ATLAS / "hud" / "install_parakeet.py")], cwd=ATLAS / "src", timeout=3600)
        if r.returncode:
            raise RuntimeError("No se pudo instalar el reconocimiento de voz")
    av(0.8, "Voz K6b (Kokoro, unos 330 MB)")   # opcional: si falla, las voces de Piper bastan
    correr([str(venv_py()), "-c", "import atlas_voz; list(atlas_voz.trozos('Hola.', 'k6b_tramos'))"],
           cwd=ATLAS / "hud", timeout=1800)
    return "Instalado"


# ------------------------------------------------------------------------------------------------ 4 · Syncthing
def syncthing_exe() -> Path | None:
    base = LOCAL / "Microsoft" / "WinGet" / "Packages"
    for d in (base.glob("Syncthing.Syncthing_*") if base.is_dir() else []):
        for e in d.rglob("syncthing.exe"):
            return e
    w = shutil.which("syncthing")
    return Path(w) if w else None


STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def paso_syncthing(av) -> str:
    if not syncthing_exe():
        av(0.1, "Instalando Syncthing")
        r = correr(["winget", "install", "--id", "Syncthing.Syncthing", "-e", "--source", "winget", "--silent",
                    "--accept-source-agreements", "--accept-package-agreements"], timeout=1800)
        if not syncthing_exe():
            raise RuntimeError("No se pudo instalar Syncthing" + (f" ({r.stdout[-200:].strip()})" if r.stdout else ""))
    vbs = STARTUP / "Syncthing (oculto).vbs"
    if not vbs.exists():
        shutil.copy2(AQUI / "syncthing_oculto.vbs", vbs)
    if not syncthing_api("/rest/system/ping"):
        subprocess.Popen(["wscript", str(vbs)], creationflags=SIN_VENTANA)
        for _ in range(30):
            if syncthing_api("/rest/system/ping"):
                break
            time.sleep(2)
    preparar_carpeta_syncthing()
    # usuario y contraseña al azar para el panel web de Syncthing (solo en el Administrador de credenciales)
    r = pasos_venv("syncthing_gui", {})
    registro("syncthing: panel " + ("protegido" if r.get("ok") else "sin proteger"))
    return "Instalado y corriendo"


def _syncthing_cfg() -> tuple[str, str] | None:
    for p in (LOCAL / "Syncthing" / "config.xml", HOME / "AppData" / "Local" / "Syncthing" / "config.xml"):
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace")
            k = re.search(r"<apikey>([^<]+)</apikey>", t)
            a = re.search(r"<gui[^>]*>.*?<address>([^<]+)</address>", t, re.S)
            if k:
                return (a.group(1) if a else "127.0.0.1:8384"), k.group(1)
    return None


def syncthing_api(ruta: str, metodo: str = "GET", cuerpo=None):
    c = _syncthing_cfg()
    if not c:
        return None
    req = urllib.request.Request(f"http://{c[0]}{ruta}", method=metodo, headers={"X-API-Key": c[1],
                                 "Content-Type": "application/json"},
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            b = r.read()
            return json.loads(b) if b.strip() else {}
    except Exception:  # noqa: BLE001
        return None


def preparar_carpeta_syncthing() -> None:
    """Carpeta «avisos_banco» en modo Solo recibir, en ~/.atlas/avisos_banco (la que lee Hermes)."""
    if syncthing_api("/rest/config/folders/avisos_banco"):
        return
    me = (syncthing_api("/rest/system/status") or {}).get("myID")
    if me:
        syncthing_api("/rest/config/folders", "POST", {"id": "avisos_banco", "label": "avisos_banco",
                                                       "path": str(DATOS / "avisos_banco"), "type": "receiveonly",
                                                       "devices": [{"deviceID": me}]})


def aceptar_celular() -> str:
    """Si un celular pidió conectarse (escaneó el QR), se acepta y se le comparte la carpeta. -> nombre o ''."""
    pend = syncthing_api("/rest/cluster/pending/devices") or {}
    for dev, info in pend.items():
        nombre = (info or {}).get("name") or "Celular"
        syncthing_api("/rest/config/devices", "POST", {"deviceID": dev, "name": nombre, "autoAcceptFolders": False})
        f = syncthing_api("/rest/config/folders/avisos_banco")
        if f is not None:
            devs = f.get("devices") or []
            if not any(d.get("deviceID") == dev for d in devs):
                syncthing_api("/rest/config/folders/avisos_banco", "PATCH", {"devices": devs + [{"deviceID": dev}]})
        registro("  Syncthing: celular aceptado")
        return nombre
    return ""


# ------------------------------------------------------------------------------------------------ 5 · acceso directo
def paso_acceso(av) -> str:
    esc = ps("[Environment]::GetFolderPath('Desktop')") or str(HOME / "Desktop")
    icono = ATLAS / "atlas-escritorio-2.ico"
    crear_acceso(Path(esc) / "Atlas.lnk", icono)
    menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Atlas.lnk"
    crear_acceso(menu, icono)
    return "Creado"


def crear_acceso(lnk: Path, icono: Path) -> None:
    destino = ATLAS / "Atlas.cmd"
    ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{destino}';"
       f"$s.WorkingDirectory='{ATLAS}';$s.IconLocation='{icono},0';$s.WindowStyle=7;$s.Description='Atlas';$s.Save()")


# ------------------------------------------------------------------------------------------------ motor de pasos
FUNCIONES = {"componentes": paso_componentes, "ollama": paso_ollama, "modelo": paso_modelo, "voz": paso_voz,
             "syncthing": paso_syncthing, "acceso": paso_acceso}
_motor: threading.Thread | None = None


def instalar() -> None:
    global _motor
    if _motor and _motor.is_alive():
        return

    def correr_todo():
        with _lock:
            ESTADO["fase"] = "instalando"
            guardar_estado()
        marcar("pasos", "requisitos", estado="listo", progreso=1.0)
        for pid, _, _ in PASOS[1:]:
            if ESTADO["pasos"][pid]["estado"] == "listo":
                continue
            marcar("pasos", pid, estado="corriendo", detalle="", progreso=0.0, pausa=False)
            registro(f"paso {pid}: empieza")

            def av(p, detalle="", pausa=False, _pid=pid):
                with _lock:
                    st = ESTADO["pasos"][_pid]
                    if p is not None:
                        st["progreso"] = max(0.0, min(1.0, float(p)))
                    if detalle:
                        st["detalle"] = detalle
                    st["pausa"] = bool(pausa)
            try:
                if SIMULAR:
                    for i in range(10):
                        av(i / 10, f"Simulando {i * 10} %")
                        time.sleep(0.3)
                    res = "Listo (simulado)"
                else:
                    res = FUNCIONES[pid](av)
                marcar("pasos", pid, estado="listo", detalle=res, progreso=1.0, pausa=False)
                registro(f"paso {pid}: listo")
            except Exception as exc:  # noqa: BLE001
                marcar("pasos", pid, estado="error", detalle=str(exc)[:300], pausa=False)
                registro(f"paso {pid}: ERROR {type(exc).__name__}: {str(exc)[:300]}")
                return                      # la persona ve qué pasó y presiona Reintentar
        with _lock:
            ESTADO["fase"] = "cuentas"
            guardar_estado()

    _motor = threading.Thread(target=correr_todo, daemon=True)
    _motor.start()


# ------------------------------------------------------------------------------------------------ cuentas
_trabajos: dict[str, threading.Thread] = {}


def cuenta(cid: str, datos: dict) -> None:
    """Corre el paso de una cuenta en segundo plano. Los secretos van por stdin a pasos_venv.py y no se guardan aquí."""
    if cid in _trabajos and _trabajos[cid].is_alive():
        return
    marcar("cuentas", cid, estado="corriendo", detalle="")

    def trabajo():
        try:
            if SIMULAR:
                time.sleep(3)
                res = {"ok": True, "detalle": "Conectado (simulado)"}
            elif cid == "cronos" and datos.get("modo") == "senales":
                res = pasos_venv("cronos_modo", {"modo": "senales"})
            elif cid == "cronos":
                res = cronos_rutas(datos)
            else:
                res = pasos_venv(cid, datos)
            if res.get("ok"):
                marcar("cuentas", cid, estado="listo", detalle=res.get("detalle", "Conectado"))
                registro(f"cuenta {cid}: lista")
            else:
                marcar("cuentas", cid, estado="error", detalle=res.get("detalle", "No se pudo conectar"))
                registro(f"cuenta {cid}: no se pudo")
        except Exception as exc:  # noqa: BLE001
            marcar("cuentas", cid, estado="error", detalle=f"Algo falló: {type(exc).__name__}")
            registro(f"cuenta {cid}: ERROR {type(exc).__name__}")
        finally:
            datos.clear()

    _trabajos[cid] = threading.Thread(target=trabajo, daemon=True)
    _trabajos[cid].start()


def pasos_venv(accion: str, datos: dict) -> dict:
    r = correr([str(venv_py()), "-I", str(AQUI / "pasos_venv.py"), accion], cwd=ATLAS / "src",
               entrada=json.dumps(datos), timeout=1800, env={"ATLAS_DIR": str(ATLAS)})
    ult = (r.stdout.strip().splitlines() or ["{}"])[-1]
    try:
        return json.loads(ult)
    except ValueError:
        return {"ok": False, "detalle": "Algo falló al conectar. El detalle quedó en el registro."}


NODE_ZIP = "https://nodejs.org/dist/v22.12.0/node-v22.12.0-win-x64.zip"   # solo para la llave de Rutas (puppeteer)


def cronos_rutas(datos: dict) -> dict:
    """Modo automático de Cronos sin PowerShell ni F12 (decisión 4): entorno de cronologia_maps, Node portátil,
    sesión de Google en una ventana (la cookie se toma sola), clave, tarea de cada noche y primera descarga."""
    email = str(datos.get("email") or ESTADO.get("correo") or "").strip()
    if "@" not in email:
        return {"ok": False, "detalle": "Escriba el correo de su cuenta de Google"}
    cm = ATLAS / "apps" / "cronos" / "cronologia_maps"
    py = cm / ".venv" / "Scripts" / "python.exe"
    marcar("cuentas", "cronos", detalle="Preparando el programa de Rutas")
    if not py.exists():
        r = correr([uv(), "venv", str(cm / ".venv"), "--python", python_atlas()], cwd=cm)
        if r.returncode:
            return {"ok": False, "detalle": "No se pudo preparar el programa de Rutas"}
    r = correr([uv(), "pip", "install", "--python", str(py), "-r", str(cm / "requirements.txt")], cwd=cm, timeout=1800)
    if r.returncode:
        return {"ok": False, "detalle": "No se pudieron instalar las piezas del programa de Rutas"}
    node = ATLAS / "apps" / "cronos" / "node"
    if not (node / "node.exe").exists():
        marcar("cuentas", "cronos", detalle="Descargando Node (unos 30 MB)")
        z = AQUI / "descargas" / "node.zip"
        descargar(NODE_ZIP, z)
        tmp = AQUI / "descargas" / "node_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
        shutil.rmtree(node, ignore_errors=True)
        shutil.move(str(next(tmp.iterdir())), str(node))
        shutil.rmtree(tmp, ignore_errors=True)
    env = {"PATH": str(node) + os.pathsep + os.environ.get("PATH", "")}
    vendor = cm / "vendor_timeline_export"
    if not (vendor / "node_modules" / "puppeteer-core").is_dir():
        r = correr([str(node / "npm.cmd"), "ci", "--no-audit", "--no-fund"], cwd=vendor, env=env, timeout=1800)
        if r.returncode:
            return {"ok": False, "detalle": "No se pudo instalar puppeteer para la llave de Rutas"}
    marcar("cuentas", "cronos", detalle="Inicie sesión en la ventana de Google")
    c = pasos_venv("cronos_cookie", {})
    cookie = c.pop("cookie", "")
    if not c.get("ok") or not cookie:
        return c
    r = correr([str(py), str(cm / "secretos.py"), "token", "--email", email, "--stdin"], cwd=cm, entrada=cookie + "\n",
               timeout=120)
    del cookie
    if r.returncode:
        return {"ok": False, "detalle": "Google rechazó el canje de la sesión. Presione Reintentar."}
    marcar("cuentas", "cronos", detalle="Google le pedirá la contraseña una vez más")
    r = correr([str(py), str(cm / "secretos.py"), "clave", "--chrome", edge() or ""], cwd=cm, env=env, timeout=900)
    if r.returncode:
        return {"ok": False, "detalle": "No se obtuvo la llave de sus rutas. Presione Reintentar."}
    pyw = cm / ".venv" / "Scripts" / "pythonw.exe"
    ps("$a=New-ScheduledTaskAction -Execute '{0}' -Argument '\"{1}\"' -WorkingDirectory '{2}';"
       "$t=New-ScheduledTaskTrigger -Daily -At 21:00;"
       "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
       "Register-ScheduledTask -TaskName 'Atlas-CronologiaMaps' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
       .format(pyw, cm / "sincronizar.py", cm))
    pasos_venv("cronos_modo", {"modo": "rutas"})
    marcar("cuentas", "cronos", detalle="Bajando sus rutas por primera vez")
    r = correr([str(py), str(cm / "sincronizar.py")], cwd=cm, env=env, timeout=1200)
    return {"ok": True, "detalle": "Rutas de Maps conectadas" + ("" if r.returncode == 0 else
                                                               " · la primera descarga se reintenta esta noche")}


# ------------------------------------------------------------------------------------------------ terminar
def terminar(autoarranque: bool) -> None:
    saltados = [c for c, v in ESTADO["cuentas"].items() if v["estado"] in ("saltado", "espera", "error")]
    inicio = STARTUP / "Atlas.lnk"
    if SIMULAR:   # el modo de prueba no toca nada real
        registro(f"simulado: primer_inicio saltados={saltados} autoarranque={autoarranque}")
    else:
        (DATOS / "primer_inicio.json").write_text(
            json.dumps({"pendiente": True, "saltados": saltados}, ensure_ascii=False), encoding="utf-8")
        if autoarranque:
            crear_acceso(inicio, ATLAS / "atlas-escritorio-2.ico")
        elif inicio.exists():
            inicio.unlink()
    with _lock:
        ESTADO["fase"] = "terminado"
        guardar_estado()
    registro("terminado: se abre Atlas")
    if not SIMULAR:
        subprocess.Popen(["cmd", "/c", str(ATLAS / "Atlas.cmd")], cwd=str(ATLAS), creationflags=SIN_VENTANA)
    threading.Timer(2.0, lambda: os._exit(0)).start()


# ------------------------------------------------------------------------------------------------ servidor local
class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):   # nada de los cuerpos al registro
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _archivo(self, p: Path, tipo: str):
        b = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _local(self) -> bool:
        o = self.headers.get("Origin")
        return self.client_address[0] == "127.0.0.1" and (o is None or o == f"http://127.0.0.1:{PUERTO}")

    def do_GET(self):  # noqa: N802
        global ULTIMO_PULSO
        if not self._local():
            return self._json({"error": "solo local"}, 403)
        ruta = self.path.split("?")[0]
        if ruta in ("/", "/index.html"):
            return self._archivo(AQUI / "asistente.html", "text/html; charset=utf-8")
        if ruta in ("/qrcode.js", "/atlas.png"):
            return self._archivo(AQUI / ruta[1:], "application/javascript" if ruta.endswith(".js") else "image/png")
        if ruta == "/api/estado":
            ULTIMO_PULSO = time.time()
            with _lock:
                return self._json({**ESTADO, "pasos_def": [{"id": p, "titulo": t, "peso": w} for p, t, w in PASOS],
                                   "universidades": list(CANVAS_U), "simulado": SIMULAR, "version": version_atlas(),
                                   "macro": (AQUI / "Avisos_banco.macro").exists()})
        if ruta == "/api/requisitos":
            return self._json(revisar_requisitos())
        if ruta == "/api/syncthing":
            me = (syncthing_api("/rest/system/status") or {}).get("myID") or ("SIMUL-ADO" if SIMULAR else "")
            cel = aceptar_celular() if me and not SIMULAR else ""
            ult = ""
            av = DATOS / "avisos_banco" / "avisos_banco.txt"
            if av.exists() and av.stat().st_size:
                ult = time.strftime("%d-%m %H:%M", time.localtime(av.stat().st_mtime))
            return self._json({"id": me, "celular": cel, "ultimo_aviso": ult})
        return self._json({"error": "no existe"}, 404)

    def do_POST(self):  # noqa: N802
        if not self._local():
            return self._json({"error": "solo local"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            cuerpo = json.loads(self.rfile.read(n) or b"{}") if n < 100_000 else {}
        except ValueError:
            cuerpo = {}
        ruta = self.path.split("?")[0]
        if ruta == "/api/instalar":
            instalar()
            return self._json({"ok": True})
        if ruta == "/api/reintentar":
            for v in ESTADO["pasos"].values():
                if v["estado"] == "error":
                    v["estado"] = "espera"
            instalar()
            return self._json({"ok": True})
        if ruta.startswith("/api/cuenta/"):
            cid = ruta.rsplit("/", 1)[1]
            if cid not in CUENTAS:
                return self._json({"error": "cuenta desconocida"}, 400)
            if cid == "canvas":
                u = str(cuerpo.get("universidad") or "")
                cuerpo["url"] = CANVAS_U.get(u) or str(cuerpo.get("url") or "")
            if cid == "correo":
                with _lock:
                    ESTADO["correo"] = str(cuerpo.get("email") or "")[:120]   # se muestra en Hermes; no es secreto
            if cid == "cronos":
                with _lock:
                    ESTADO["cronos_modo"] = str(cuerpo.get("modo") or "")
            cuenta(cid, dict(cuerpo))
            cuerpo.clear()
            return self._json({"ok": True})
        if ruta == "/api/saltar":
            cid = str(cuerpo.get("id") or "")
            if cid in CUENTAS:
                marcar("cuentas", cid, estado="saltado", detalle="Saltado")
            return self._json({"ok": True})
        if ruta == "/api/abrir":     # solo direcciones conocidas, nunca una que venga de afuera
            destinos = {"apppasswords": "https://myaccount.google.com/apppasswords",
                        "dospasos": "https://myaccount.google.com/signinoptions/twosv",
                        "canvas_token": "", "rutas": "https://support.google.com/maps/answer/6258979"}
            url = destinos.get(str(cuerpo.get("a") or ""))
            if url:
                webbrowser.open(url)
            return self._json({"ok": bool(url)})
        if ruta == "/api/terminar":
            terminar(bool(cuerpo.get("autoarranque", True)))
            return self._json({"ok": True})
        if ruta == "/api/cerrar":
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return self._json({"ok": True})
        return self._json({"error": "no existe"}, 404)


PUERTO = 0


def abrir_ventana(url: str) -> None:
    e = edge()
    perfil = AQUI / "ventana"
    if e:
        try:
            subprocess.Popen([e, f"--app={url}", f"--user-data-dir={perfil}", "--window-size=980,760",
                              "--no-first-run", "--no-default-browser-check"])
            registro("ventana abierta con Edge")
            return
        except OSError as exc:
            registro(f"Edge no abrió: {exc}")
    if not webbrowser.open(url):
        registro("no hay navegador para abrir la ventana")
        aviso("No pude abrir la ventana del asistente.\n\nAbra su navegador y escriba esta dirección:\n" + url)


def aviso(texto: str) -> None:
    """Mensaje de Windows para cuando la ventana del asistente no puede mostrarse: nunca fallar en silencio."""
    try:
        ctypes.windll.user32.MessageBoxW(None, texto, "Instalador de Atlas", 0x10 | 0x40000)
    except Exception:  # noqa: BLE001
        pass


def ocultar_consola() -> None:
    """Abierto desde el menú Inicio, uv deja una consola negra: se esconde apenas el asistente arranca."""
    try:
        h = ctypes.windll.kernel32.GetConsoleWindow()
        if h:
            ctypes.windll.user32.ShowWindow(h, 0)
    except Exception:  # noqa: BLE001
        pass


ARCHIVO_PUERTO = AQUI / "asistente.puerto"


def ya_abierto() -> str | None:
    """Si otro asistente ya corre (por ejemplo, la persona lo abrió dos veces), devuelve su dirección."""
    try:
        puerto = int(ARCHIVO_PUERTO.read_text(encoding="utf-8").strip())
        url = f"http://127.0.0.1:{puerto}/"
        with urllib.request.urlopen(url + "api/estado", timeout=3) as r:
            if r.status == 200:
                return url
    except Exception:  # noqa: BLE001
        pass
    return None


def vigilar_ventana() -> None:
    """Si la ventana se cierra (nadie pregunta el estado en 2 minutos) y no hay nada corriendo, el asistente termina.
    Si hay pasos corriendo, sigue: al volver a abrir el instalador se ve el avance."""
    while True:
        time.sleep(20)
        ocupado = (_motor and _motor.is_alive()) or any(t.is_alive() for t in _trabajos.values())
        if time.time() - ULTIMO_PULSO > 120 and not ocupado:
            os._exit(0)


def main() -> None:
    try:
        _main()
    except Exception:  # noqa: BLE001
        import traceback
        registro("el asistente se cayó al abrir:\n" + traceback.format_exc())
        aviso("El asistente de Atlas no pudo abrirse.\n\nEl detalle quedó en:\n" + str(AQUI / "instalacion.log")
              + "\n\nMándele ese archivo a quien le pasó el instalador.")
        sys.exit(1)


def _main() -> None:
    global PUERTO, SIMULAR, ATLAS
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", help="carpeta de Atlas (por defecto, la de arriba de este archivo)")
    ap.add_argument("--sin-ventana", action="store_true")
    ap.add_argument("--simular", action="store_true", help="recorre las pantallas sin instalar nada")
    a = ap.parse_args()
    if a.atlas:
        ATLAS = Path(a.atlas)
    SIMULAR = a.simular
    ocultar_consola()
    otro = ya_abierto()
    if otro:
        registro("el asistente ya estaba abierto: muestro esa ventana")
        if not a.sin_ventana:
            abrir_ventana(otro)
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Atlas.Instalador")
    except Exception:  # noqa: BLE001
        pass
    cargar_estado()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    PUERTO = srv.server_address[1]
    url = f"http://127.0.0.1:{PUERTO}/"
    try:
        ARCHIVO_PUERTO.write_text(str(PUERTO), encoding="utf-8")
    except OSError:
        pass
    registro(f"asistente abierto (simular={SIMULAR}, Python {sys.version.split()[0]})")
    print(url, flush=True)
    if not a.sin_ventana:
        abrir_ventana(url)
    threading.Thread(target=vigilar_ventana, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()

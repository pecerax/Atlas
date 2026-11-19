"""Juegos del PC que no son de Steam, para Baco: los busca en los launchers y mide el tiempo mirando los procesos.

18-11-2026.
- Instalados: Epic (manifiestos .item), Riot (League of Legends, VALORANT), HoYoPlay (Genshin, Star Rail, ZZZ),
  entradas de «Agregar o quitar programas» de juegos conocidos, y los .exe que la persona agrega a mano.
- Tiempo: un hilo del servidor de Atlas mira cada 30 s qué procesos están abiertos (sin permisos especiales,
  CreateToolhelp32Snapshot) y suma ese rato al juego. Se guarda en ~/.atlas/baco_tiempo.json
  ({id: {"seg", "ultima", "dias": {"AAAA-MM-DD": seg}}}; los días se guardan 30 días para «últimas 2 semanas»).
- Abrir: con el comando de su launcher (Epic/Riot) o con el .exe (os.startfile: si pide administrador, Windows avisa).
"""

from __future__ import annotations

import glob
import json
import ntpath
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

TIEMPO = Path(os.environ.get("BACO_TIEMPO") or (Path.home() / ".atlas" / "baco_tiempo.json"))
CADA = 30  # segundos entre miradas a los procesos
_LOCK = threading.RLock()
_ESTADO: dict = {"hilo": None, "abiertos": [], "t": 0.0, "cache": None, "t_cache": 0.0}

# Juegos conocidos: nombre -> procesos que significan «está jugando» (en minúsculas) y dónde suele estar.
CONOCIDOS: dict = {
    "Genshin Impact": {"exe": ["genshinimpact.exe", "yuanshen.exe"], "origen": "HoYoPlay"},
    "Honkai: Star Rail": {"exe": ["starrail.exe"], "origen": "HoYoPlay"},
    "Zenless Zone Zero": {"exe": ["zenlesszonezero.exe"], "origen": "HoYoPlay"},
    "Honkai Impact 3rd": {"exe": ["bh3.exe"], "origen": "HoYoPlay"},
    "League of Legends": {"exe": ["league of legends.exe"], "origen": "Riot"},
    "VALORANT": {"exe": ["valorant-win64-shipping.exe"], "origen": "Riot"},
    "Legends of Runeterra": {"exe": ["lor.exe"], "origen": "Riot"},
    "Fortnite": {"exe": ["fortniteclient-win64-shipping.exe"], "origen": "Epic"},
    "Rocket League": {"exe": ["rocketleague.exe"], "origen": "Epic"},
    "Overwatch 2": {"exe": ["overwatch.exe"], "origen": "Battle.net"},
    "Diablo IV": {"exe": ["diablo iv.exe"], "origen": "Battle.net"},
    "World of Warcraft": {"exe": ["wow.exe"], "origen": "Battle.net"},
    "Hearthstone": {"exe": ["hearthstone.exe"], "origen": "Battle.net"},
    "Call of Duty": {"exe": ["cod.exe", "cod24-cod.exe"], "origen": "Battle.net"},
    "Apex Legends": {"exe": ["r5apex.exe", "r5apex_dx12.exe"], "origen": "EA"},
    "Minecraft": {"exe": ["minecraft.windows.exe"], "origen": "Microsoft"},
    "Roblox": {"exe": ["robloxplayerbeta.exe"], "origen": "Roblox"},
    "osu!": {"exe": ["osu!.exe"], "origen": "PC"},
    "Wuthering Waves": {"exe": ["wuthering waves.exe"], "origen": "Kuro"},
}
# Procesos que nunca son juegos aunque alguien los agregue (evita contar el navegador o el mismo Atlas)
NUNCA = {"explorer.exe", "firefox.exe", "chrome.exe", "msedge.exe", "python.exe", "pythonw.exe", "powershell.exe",
         "cmd.exe", "steam.exe", "epicgameslauncher.exe", "riotclientservices.exe", "hyp.exe", "battle.net.exe"}


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "juego"


# ----------------------------------------------------------------------------- procesos abiertos
def procesos() -> set:
    """Nombres (en minúsculas) de los procesos abiertos. Windows: Toolhelp32; en otro sistema, vacío."""
    if sys.platform != "win32":
        return set()
    import ctypes
    from ctypes import wintypes

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return set()
    out = set()
    try:
        pe = PE32()
        pe.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            out.add(pe.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


# ----------------------------------------------------------------------------- launchers
def _programdata() -> Path:
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData")


def _epic() -> list:
    out = []
    for f in glob.glob(str(_programdata() / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests" / "*.item")):
        try:
            m = json.loads(Path(f).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        cats = [c.lower() for c in m.get("AppCategories") or []]
        if m.get("bIsIncompleteInstall") or (cats and "games" not in cats):
            continue
        nombre, app = m.get("DisplayName") or "", m.get("MainGameAppName") or m.get("AppName") or ""
        exe = ntpath.normpath(ntpath.join(m.get("InstallLocation") or "", m.get("LaunchExecutable") or ""))
        if not nombre or not app:
            continue
        out.append({"t": nombre, "origen": "Epic", "exe": exe if os.path.isfile(exe) else "",
                    "procs": [ntpath.basename(exe).lower()] if m.get("LaunchExecutable") else [],
                    "lanzar": ["uri", f"com.epicgames.launcher://apps/{app}?action=launch&silent=true"]})
    return out


def _riot() -> list:
    base = _programdata() / "Riot Games"
    try:
        rc = json.loads((base / "RiotClientInstalls.json").read_text(encoding="utf-8")).get("rc_default") or ""
    except (OSError, ValueError):
        rc = ""
    out = []
    for prod, nombre in (("league_of_legends", "League of Legends"), ("valorant", "VALORANT"), ("bacon", "Legends of Runeterra")):
        y = base / "Metadata" / f"{prod}.live" / f"{prod}.live.product_settings.yaml"
        if not y.is_file():
            continue
        lanzar = ["args", [rc, f"--launch-product={prod}", "--launch-patchline=live"]] if rc and os.path.isfile(rc) else None
        out.append({"t": nombre, "origen": "Riot", "exe": "", "procs": CONOCIDOS[nombre]["exe"], "lanzar": lanzar})
    return out


def _desinstalables() -> list:
    """Entradas de «Agregar o quitar programas» (registro). Solo Windows."""
    if sys.platform != "win32":
        return []
    import winreg

    out = []
    claves = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for raiz, ruta in claves:
        try:
            k = winreg.OpenKey(raiz, ruta)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                        def val(n):
                            try:
                                return str(winreg.QueryValueEx(s, n)[0])
                            except OSError:
                                return ""
                        out.append({"n": val("DisplayName"), "dir": val("InstallLocation"), "icono": val("DisplayIcon")})
                except OSError:
                    continue
    return out


def _hoyoplay_y_otros() -> list:
    """Juegos conocidos que aparecen instalados: carpeta de HoYoPlay o «Agregar o quitar programas»."""
    out, vistos = [], set()
    entradas = _desinstalables()
    raices = [e["dir"] for e in entradas if e["n"].lower().startswith("hoyoplay") and e["dir"]]
    raices += [os.path.expandvars(r"%ProgramFiles%\HoYoPlay"), r"C:\Program Files\HoYoPlay", r"D:\HoYoPlay"]
    for nombre, info in CONOCIDOS.items():
        if info["origen"] == "Riot":
            continue
        exe = ""
        if info["origen"] == "HoYoPlay":
            for r in dict.fromkeys(raices):
                for p in info["exe"]:
                    hall = glob.glob(os.path.join(r, "games", "*", p)) + glob.glob(os.path.join(r, "games", "*", "*", p))
                    if hall:
                        exe = hall[0]
                        break
                if exe:
                    break
        e = next((e for e in entradas if e["n"].lower().startswith(nombre.lower())), None)
        if not exe and e:
            for p in info["exe"]:
                cand = os.path.join(e["dir"], p) if e["dir"] else ""
                if cand and os.path.isfile(cand):
                    exe = cand
                    break
        if exe or e:
            if nombre in vistos:
                continue
            vistos.add(nombre)
            out.append({"t": nombre, "origen": info["origen"], "exe": exe, "procs": info["exe"],
                        "lanzar": ["exe", exe] if exe else None})
    return out


# ----------------------------------------------------------------------------- tiempo jugado
def _leer_tiempo() -> dict:
    try:
        d = json.loads(TIEMPO.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir_tiempo(d: dict) -> None:
    TIEMPO.parent.mkdir(parents=True, exist_ok=True)
    tmp = TIEMPO.with_name(TIEMPO.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, TIEMPO)


def sumar(ids: list, seg: int, ahora: float | None = None) -> None:
    """Suma seg segundos a cada juego abierto (y recorta los días de más de 30 días)."""
    if not ids:
        return
    ahora = ahora or time.time()
    hoy = time.strftime("%Y-%m-%d", time.localtime(ahora))
    corte = time.strftime("%Y-%m-%d", time.localtime(ahora - 30 * 86400))
    with _LOCK:
        d = _leer_tiempo()
        for i in ids:
            r = d.setdefault(i, {"seg": 0, "ultima": 0, "dias": {}})
            r["seg"] = int(r.get("seg", 0)) + seg
            r["ultima"] = int(ahora)
            dias = {k: v for k, v in (r.get("dias") or {}).items() if k >= corte}
            dias[hoy] = int(dias.get(hoy, 0)) + seg
            r["dias"] = dias
        _escribir_tiempo(d)


def _horas(r: dict, ahora: float | None = None) -> tuple:
    ahora = ahora or time.time()
    desde = time.strftime("%Y-%m-%d", time.localtime(ahora - 14 * 86400))
    dos = sum(v for k, v in (r.get("dias") or {}).items() if k > desde)
    return round(r.get("seg", 0) / 3600, 1), round(dos / 3600, 1), int(r.get("ultima", 0))


# ----------------------------------------------------------------------------- lista y vigilancia
def instalados(manuales: list, forzar: bool = False) -> list:
    """Juegos fuera de Steam: [{id, t, origen, exe, procs, lanzar}]. Los detectados se recuerdan 10 min."""
    with _LOCK:
        if not forzar and _ESTADO["cache"] is not None and time.time() - _ESTADO["t_cache"] < 600:
            det = _ESTADO["cache"]
        else:
            det = []
            for f in (_epic, _riot, _hoyoplay_y_otros):
                try:
                    det += f()
                except Exception:  # noqa: BLE001
                    pass
            _ESTADO.update(cache=det, t_cache=time.time())
    out, nombres = [], set()
    for g in det:
        if g["t"].lower() in nombres:
            continue
        nombres.add(g["t"].lower())
        out.append({**g, "id": "pc:" + _slug(g["t"])})
    for m in manuales or []:
        exe = m.get("exe") or ""
        out = [g for g in out if g["id"] != m["id"]]
        out.append({"id": m["id"], "t": m["t"], "origen": "Manual", "exe": exe,
                    "procs": [ntpath.basename(exe).lower()] if exe else [], "lanzar": ["exe", exe] if exe else None})
        nombres.add(m["t"].lower())
    for nombre, info in CONOCIDOS.items():  # conocidos sin instalación encontrada: solo para medir si aparecen
        if nombre.lower() not in nombres:
            out.append({"id": "pc:" + _slug(nombre), "t": nombre, "origen": info["origen"], "exe": "", "procs": info["exe"],
                        "lanzar": None, "oculto": True})
    for g in out:
        extra = next((i["exe"] for n, i in CONOCIDOS.items() if n.lower() == g["t"].lower()), [])
        g["procs"] = [p for p in dict.fromkeys(g["procs"] + extra) if p and p not in NUNCA]
    return out


def lista(manuales: list) -> dict:
    """Para la página: juegos con su tiempo; los conocidos no instalados aparecen solo si ya tienen tiempo."""
    t = _leer_tiempo()
    juegos = []
    for g in instalados(manuales):
        r = t.get(g["id"]) or {}
        h, h2, ultima = _horas(r)
        if g.get("oculto") and not r:
            continue
        juegos.append({"id": g["id"], "t": g["t"], "origen": g["origen"], "h": h, "h2": h2, "ultima": ultima,
                       "abierto": any(p in _ESTADO["abiertos"] for p in g["procs"]), "lanzable": bool(g["lanzar"]),
                       "manual": g["origen"] == "Manual", "exe": g["exe"] if g["origen"] == "Manual" else ""})
    juegos.sort(key=lambda j: (-j["ultima"], j["t"].lower()))
    return {"ok": True, "juegos": juegos, "vigilando": _ESTADO["hilo"] is not None}


def jugar(gid: str, manuales: list) -> dict:
    g = next((g for g in instalados(manuales) if g["id"] == gid), None)
    if not g or not g["lanzar"]:
        return {"ok": False, "error": "No sé cómo abrir ese juego. Ábrelo desde su launcher."}
    tipo, que = g["lanzar"]
    try:
        if tipo == "args":
            subprocess.Popen(que, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.startfile(que)  # type: ignore[attr-defined]  # .exe (Windows pide permiso si hace falta) o com.epicgames…
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def mirar(manuales_fn) -> list:
    """Una mirada: qué juegos están abiertos (ids). Separado del hilo para poder probarlo."""
    abiertos = procesos()
    with _LOCK:
        _ESTADO["abiertos"] = sorted(abiertos)
    return [g["id"] for g in instalados(manuales_fn()) if any(p in abiertos for p in g["procs"])]


def vigilar(manuales_fn) -> bool:
    """Arranca (una vez) el hilo que mide el tiempo. manuales_fn() -> lista de juegos agregados a mano."""
    with _LOCK:
        if _ESTADO["hilo"] is not None:
            return False

        def bucle():
            ultimo = time.time()
            while True:
                time.sleep(CADA)
                ahora = time.time()
                paso = int(min(ahora - ultimo, CADA * 2))  # si el PC durmió, no se cuenta ese rato
                ultimo = ahora
                try:
                    sumar(mirar(manuales_fn), paso, ahora)
                except Exception:  # noqa: BLE001
                    pass

        h = threading.Thread(target=bucle, name="baco-juegos", daemon=True)
        _ESTADO["hilo"] = h
        h.start()
        return True


_PS_ELEGIR = r"""
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false; WindowState = 'Minimized'}
$d = New-Object System.Windows.Forms.OpenFileDialog -Property @{Title = 'Elige el .exe del juego'; Filter = 'Juegos (*.exe)|*.exe'; InitialDirectory = $env:ProgramFiles}
if ($d.ShowDialog($f) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileName }
"""


def elegir_exe() -> dict:
    """Abre en el PC el cuadro de Windows para elegir un .exe y devuelve la ruta elegida."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _PS_ELEGIR],
                           capture_output=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ruta = r.stdout.decode("utf-8", errors="replace").strip().splitlines()
        ruta = ruta[-1].strip() if ruta else ""
        if not ruta:
            return {"ok": False, "cancelado": True}
        nombre = Path(ruta).stem
        return {"ok": True, "exe": ruta, "t": nombre}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}

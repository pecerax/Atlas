"""Llamadas entrantes del celular por Enlace Móvil (Phone Link), y mantener Enlace Móvil corriendo.

- watch(on_ring, on_end, log): revisa cada ~1 s las ventanas de Windows (UI Automation). Una llamada entrante de
  Enlace Móvil aparece como una ventanita o una notificación con un botón para contestar y otro para rechazar;
  cuando aparece, avisa con quién llama (on_ring) y cuando desaparece, on_end. La primera vez que ve una ventana
  de Enlace Móvil que no conoce, deja en el registro sus textos y botones (para ajustar la detección).
- answer() / decline(): presionan esos botones (solo cuando el usuario lo pide).
- keep_alive(log): si el proceso de Enlace Móvil no está corriendo, lo abre y minimiza su ventana. Si el usuario
  solo cierra la ventana, el proceso sigue y no se reabre nada (así no hay ventanas que reaparecen).
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import threading
import time

AUMID = r"shell:AppsFolder\Microsoft.YourPhone_8wekyb3d8bbwe!App"
PROC = "PhoneExperienceHost.exe"
ACCEPT = re.compile(r"^(aceptar|contestar|responder|atender|answer|accept)\b", re.I)
DECLINE = re.compile(r"^(rechazar|colgar|ignorar|decline|reject)\b", re.I)

state: dict = {"ring": None, "out_t": 0.0}  # ring: {"hwnd", "accept", "decline", "texts", "t"}


def mark_outgoing() -> None:
    """Atlas acaba de marcar: el audio de manos libres que viene es de esa llamada saliente, no de una entrante
    (uso real 15-11-2026: «Llama a mi madre» y 2 s después avisó «le están llamando»)."""
    state["out_t"] = time.time()


def _outgoing_now() -> bool:
    """¿El audio de manos libres que acaba de empezar es de una llamada saliente? Sí si Atlas marcó hace poco o si
    el usuario está en la ventana de Enlace Móvil (marcó él mismo desde el PC)."""
    if time.time() - state.get("out_t", 0.0) < 90:
        return True
    try:
        import ctypes

        u = ctypes.windll.user32
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value in _pids()
    except Exception:  # noqa: BLE001
        return False
_seen: set[str] = set()


def _pids() -> set[int]:
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROC}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return set()
    return {int(m) for m in re.findall(r'^"[^"]+","(\d+)"', out, re.M)}


def keep_alive(log=print, every: float = 60.0, per_hour: int = 3) -> None:
    """Cada minuto: si el proceso de Enlace Móvil no corre, lo abre minimizado y devuelve el foco a la ventana
    que el usuario tenía. Máximo `per_hour` aperturas por hora: si Windows lo cierra una y otra vez, se rinde
    hasta la hora siguiente en vez de abrir ventanas en bucle."""
    opened: list[float] = []
    warned = False
    while True:
        try:
            if not _pids():
                now = time.time()
                opened = [x for x in opened if now - x < 3600]
                if len(opened) >= per_hour:
                    if not warned:
                        log(f"Enlace Móvil se cerró {per_hour} veces en una hora: no lo vuelvo a abrir hasta más rato")
                        warned = True
                else:
                    opened.append(now)
                    warned = False
                    log("Enlace Móvil no estaba corriendo: lo abro minimizado")
                    _launch_minimized()
        except Exception as exc:  # noqa: BLE001
            log(f"Enlace Móvil (mantener activo): {exc}")
        time.sleep(every)


def _launch_minimized(wait: float = 20.0) -> bool:
    user32 = ctypes.windll.user32
    before = user32.GetForegroundWindow()
    subprocess.Popen(["explorer.exe", AUMID], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    end = time.time() + wait
    while time.time() < end:
        hwnd = user32.FindWindowW("WinUIDesktopWin32WindowClass", "Enlace Móvil") or \
            user32.FindWindowW("WinUIDesktopWin32WindowClass", "Phone Link")
        if hwnd and user32.IsWindowVisible(hwnd):
            time.sleep(0.5)  # que termine de abrir, si no a veces vuelve a mostrarse
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            if before and user32.IsWindow(before) and before != hwnd:
                user32.SetForegroundWindow(before)
            return True
        time.sleep(0.3)
    return False


def _scan(auto, w, depth: int = 14) -> tuple[list[str], list]:
    texts, buttons = [], []
    for c, _d in auto.WalkControl(w, maxDepth=depth):
        n = (c.Name or "").strip()
        if not n:
            continue
        if c.ControlTypeName == "ButtonControl":
            buttons.append(c)
        elif c.ControlTypeName == "TextControl" and len(n) < 80 and not re.fullmatch(r"[-\s]+", n):
            texts.append(n)
    return texts, buttons


def _wa_pids() -> set[int]:
    """Procesos de WhatsApp de escritorio (sus llamadas entrantes abren una ventana aparte con aceptar/rechazar)."""
    try:
        import psutil

        return {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "whatsapp.root.exe"}
    except Exception:  # noqa: BLE001
        return set()


def _find_ring(auto, pids: set[int], log, wa_pids: set[int] | None = None) -> dict | None:
    wa_pids = wa_pids or set()
    wa_main = ctypes.windll.user32.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp") if wa_pids else 0
    for w in auto.GetRootControl().GetChildren():
        name = w.Name or ""
        mine = w.ProcessId in pids
        wa = w.ProcessId in wa_pids and w.NativeWindowHandle != wa_main  # la ventana principal de WhatsApp no
        toast = re.search(r"notificaci[oó]n|notification", name, re.I)
        if not (mine or wa or toast) or (mine and name in ("Enlace Móvil", "Phone Link")):
            continue
        texts, buttons = _scan(auto, w, depth=40 if wa else 14)  # el contenido de WhatsApp (WebView2) es profundo
        acc = [b for b in buttons if ACCEPT.search(b.Name.strip())]
        dec = [b for b in buttons if DECLINE.search(b.Name.strip())]
        key = f"{name}|{'/'.join(sorted(b.Name for b in buttons))[:200]}"
        if key not in _seen and (mine or wa or acc or dec):
            _seen.add(key)
            log(f"  {'WhatsApp' if wa else 'Enlace Móvil'}: ventana «{name}» textos={texts[:8]} botones={[b.Name for b in buttons][:10]}")
        if acc and dec:
            return {"hwnd": w.NativeWindowHandle, "accept": acc[0].Name, "decline": dec[0].Name, "texts": texts,
                    "app": "whatsapp" if wa else "telefono"}
    return None


_exe_cache: dict[int, str] = {}


def _exe(pid: int) -> str:
    if pid not in _exe_cache:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        name = ""
        if h:
            buf = ctypes.create_unicode_buffer(260)
            n = ctypes.c_ulong(260)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                name = buf.value.rsplit("\\", 1)[-1].lower()
            k32.CloseHandle(h)
        if not name:  # los servicios (svchost del audio Bluetooth) no se dejan abrir sin permisos de administrador
            try:
                out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                     text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                m = re.match(r'^"([^"]+)"', out.strip())
                name = m.group(1).lower() if m else ""
            except Exception:  # noqa: BLE001
                name = ""
        if len(_exe_cache) > 500:
            _exe_cache.clear()
        _exe_cache[pid] = name
    return _exe_cache[pid]


def audio_call() -> bool:
    """¿Hay una llamada del celular sonando o en curso por Bluetooth (manos libres)?

    Uso real (Samsung A55, 15-11-2026): al entrar una llamada Enlace Móvil no mostró ninguna ventana, pero Windows
    abrió audio de manos libres: el servicio svchost.exe toma el micrófono del PC (y los parlantes) desde el primer
    segundo del timbre hasta que se corta. Ningún otro programa usa el micrófono a través de svchost."""
    import atlas_audio_sesiones as A

    return any(flujo == "entrada" and estado == 1 and pid and _exe(pid) == "svchost.exe"
               for flujo, _dev, pid, estado in A.sessions())


def _wa_tree(wa_pids: set[int]) -> set[int]:
    """WhatsApp.Root y todos sus procesos hijos: el sonido de WhatsApp sale de un proceso msedgewebview2 hijo."""
    out = set(wa_pids)
    try:
        import psutil

        for pid in wa_pids:
            try:
                out |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


def _wa_call_window() -> bool:
    """¿Hay una ventana de llamada de WhatsApp abierta («Voice call»)? Entonces el sonido es de una llamada en curso
    (hecha por el usuario o ya contestada), no un timbre nuevo."""
    u = ctypes.windll.user32
    found = [False]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _l):
        title = ctypes.create_unicode_buffer(120)
        u.GetWindowTextW(h, title, 120)
        if u.IsWindowVisible(h) and re.search(r"voice call|video call|llamada de voz|videollamada", title.value, re.I):
            found[0] = True
            return False
        return True

    u.EnumWindows(cb, 0)
    return found[0]


def wa_ringing_audio(tree: set[int]) -> bool:
    """¿WhatsApp está reproduciendo sonido? (sesión de salida activa de WhatsApp o de su WebView2)."""
    import atlas_audio_sesiones as A

    return any(flujo == "salida" and estado == 1 and pid in tree for flujo, _dev, pid, estado in A.sessions())


WA_RING_SECS = 3.0  # el tono de llamada dura; el «ding» de un mensaje dura menos de un segundo


def watch(on_ring, on_end, log=print, every: float = 1.0) -> None:
    import uiautomation as auto

    _keep = auto.UIAutomationInitializerInThread()  # noqa: F841
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    pids, wa, pids_t = set(), set(), 0.0
    tree: set[int] = set()
    audio_err = False
    wa_snd_since, wa_snd_last = 0.0, None
    u = ctypes.windll.user32
    while True:
        try:
            if time.time() - pids_t > 30:
                pids, wa, pids_t = _pids(), _wa_pids(), time.time()
                tree = _wa_tree(wa)
            ring = _find_ring(auto, pids, log, wa) if (pids or wa) else None
            # WhatsApp en la bandeja no abre ventana al entrar una llamada (uso real 15-11-2026: «no avisa cuando me
            # llaman por wsp»; el registro no mostró ninguna ventana). Lo que sí pasa es que suena: si WhatsApp suena
            # 3 s seguidos, sin una llamada propia abierta y sin que el usuario esté usando WhatsApp, es un timbre.
            if not ring and tree:
                try:
                    snd = wa_ringing_audio(tree)
                except Exception:  # noqa: BLE001
                    snd = False
                if snd != wa_snd_last:
                    log(f"  WhatsApp: sonido {'empezó' if snd else 'terminó'}")
                    wa_snd_last = snd
                    wa_snd_since = time.time() if snd else 0.0
                fg = u.GetForegroundWindow()
                pid = ctypes.c_ulong()
                u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                using_wa = pid.value in tree
                if snd and time.time() - wa_snd_since >= WA_RING_SECS and not using_wa and not _wa_call_window() \
                        and not _outgoing_now():
                    ring = {"hwnd": 0, "accept": "", "decline": "", "texts": [], "audio": True, "app": "whatsapp"}
                elif snd and state["ring"] and state["ring"].get("app") == "whatsapp":
                    ring = state["ring"]  # sigue sonando (o la contestó: la ventana de llamada la mantiene)
            if not ring:
                try:
                    if audio_call():
                        ring = {"hwnd": 0, "accept": "", "decline": "", "texts": [], "audio": True}
                except Exception as exc:  # noqa: BLE001
                    if not audio_err:
                        log(f"  llamadas entrantes (audio): {exc}")
                        audio_err = True
            if ring and not state["ring"]:
                if ring.get("audio") and _outgoing_now():
                    state["ring"] = {**ring, "t": time.time(), "saliente": True}  # se ignora hasta que se corte
                    log("  llamada saliente en curso (no se avisa)")
                else:
                    state["ring"] = {**ring, "t": time.time()}
                    on_ring(ring)
            elif ring and ring.get("hwnd") and not state["ring"].get("hwnd"):
                state["ring"].update(ring)  # apareció la ventana con botones después del audio
            elif not ring and state["ring"]:
                was_out = state["ring"].get("saliente")
                state["ring"] = None
                if not was_out:
                    on_end()
        except Exception as exc:  # noqa: BLE001
            log(f"  llamadas entrantes: {exc}")
            time.sleep(5)
        time.sleep(every)


def _press(which: str) -> bool:
    ring = state.get("ring")
    if not ring:
        return False
    box: dict = {}

    def run() -> None:
        import uiautomation as auto

        _keep = auto.UIAutomationInitializerInThread()  # noqa: F841
        w = auto.ControlFromHandle(ring["hwnd"])
        if not w:
            return
        b = w.ButtonControl(Name=ring[which], searchDepth=40)  # WhatsApp (WebView2) es profundo
        if b.Exists(1, 0.2):
            try:
                b.Click(simulateMove=False)
            except Exception:  # noqa: BLE001
                b.GetInvokePattern().Invoke()
            box["ok"] = True

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(8)
    return bool(box.get("ok"))


def answer() -> bool:
    return _press("accept")


def decline() -> bool:
    return _press("decline")


CALL_TYPES = {1: "contestada", 2: "saliente", 3: "perdida", 4: "buzón de voz", 5: "rechazada", 6: "bloqueada"}


def _copy_db(name: str):
    import os
    import shutil
    import sqlite3
    import tempfile
    from pathlib import Path

    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / "Microsoft.YourPhone_8wekyb3d8bbwe" / "LocalCache" / "Indexed"
    found = sorted(base.glob(f"*/System/Database/{name}"), key=lambda q: q.stat().st_mtime, reverse=True)
    if not found:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="atlas_ll_")) / name
    for suf in ("", "-wal", "-shm"):
        if Path(str(found[0]) + suf).exists():
            shutil.copy2(str(found[0]) + suf, str(tmp) + suf)
    return sqlite3.connect(tmp)


def last_call(since: float) -> dict | None:
    """La llamada que Enlace Móvil anotó (al terminar) con inicio desde `since` (hora Unix) -> {"numero", "tipo"}."""
    con = _copy_db("calling.db")
    if not con:
        return None
    try:
        ticks = int((since + 11644473600) * 10_000_000)  # hora de Windows (100 ns desde 1601)
        r = con.execute("select phone_number, call_type from call_history where start_time >= ? "
                        "order by start_time desc limit 1", (ticks,)).fetchone()
    finally:
        con.close()
    return {"numero": r[0] or "", "tipo": CALL_TYPES.get(r[1], "")} if r else None


def name_for(number: str) -> str:
    """El nombre de la libreta para ese número; si no está, el del celular (Enlace Móvil); si no, el número."""
    import atlas_contactos as C

    d = re.sub(r"\D", "", number or "")
    if len(d) >= 8:
        for c in C.load():
            if re.sub(r"\D", "", c.get("telefono", ""))[-8:] == d[-8:]:
                return c["nombre"]
        try:
            con = _copy_db("contacts.db")
            if con:
                try:
                    for name, num in con.execute("select c.display_name, p.phone_number from phonenumber p "
                                                 "join contact c on c.contact_id = p.contact_id"):
                        if name and re.sub(r"\D", "", num or "")[-8:] == d[-8:]:
                            return name
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            pass
    return number or "un número desconocido"


def caller(texts: list[str]) -> str:
    """Quién llama: el contacto de la libreta si calza (por número o nombre); si no, lo que muestra Enlace Móvil."""
    import atlas_contactos as C

    skip = re.compile(r"llamada|entrante|enlace m[oó]vil|phone link|whats\s?app|aceptar|rechazar|responder|mensaje|cifrad|^\W*$", re.I)
    cand = [t for t in texts if not skip.search(t)]
    book = C.load()
    for t in cand:
        d = re.sub(r"\D", "", t)
        if len(d) >= 8:
            for c in book:
                if re.sub(r"\D", "", c.get("telefono", ""))[-8:] == d[-8:]:
                    return c["nombre"]
        hit = C.find(t)
        if len(hit) == 1:
            return hit[0]["nombre"]
    return cand[0] if cand else "un número desconocido"

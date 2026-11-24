"""Indicador flotante de Atlas: un círculo chico arriba a la derecha de la pantalla, siempre encima,
aunque la ventana de Atlas esté minimizada. Muestra si Atlas está en espera, escuchando, pensando o hablando.

- Clic: trae la ventana de Atlas al frente.  Arrastrar: lo mueve.  Clic derecho: lo oculta por 10 minutos.
- Lo abre hud_server.py (con ATLAS_URL y ATLAS_TOKEN) y se cierra solo cuando Atlas se cierra.
- Se dibuja con numpy (bordes suavizados) en una ventana con transparencia real por píxel (UpdateLayeredWindow);
  tkinter solo pone la ventana y recibe el mouse."""
from __future__ import annotations

import ctypes
import json
import math
import os

# Transición Jarvis -> Atlas: las variables JARVIS_* antiguas valen como ATLAS_*
for _k, _v in list(os.environ.items()):
    if _k.startswith("JARVIS_") and "ATLAS_" + _k[7:] not in os.environ:
        os.environ["ATLAS_" + _k[7:]] = _v

import random
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request
from ctypes import wintypes

import numpy as np

URL = os.environ.get("ATLAS_URL", "http://127.0.0.1:8765/").rstrip("/")
TOKEN = os.environ.get("ATLAS_TOKEN", "")
CYAN, GREEN, DIM, BG = (79, 227, 255), (95, 242, 192), (28, 90, 107), (6, 22, 36)
AMBER = (255, 159, 67)  # procesando (igual que el núcleo de la HUD)
LABELS = {"listening": "ESCUCHANDO", "thinking": "PROCESANDO", "speaking": "HABLANDO"}
TICKS = ((20, 95), (150, 70), (250, 40))  # tramos de dientes del anillo exterior (inicio, largo) en grados

state = {"mode": "idle", "ok": time.time(), "hide_until": 0.0, "show": True}

try:  # píxeles reales (si no, Windows lo estira y queda borroso)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass
try:
    SCALE = ctypes.windll.user32.GetDpiForSystem() / 96
except Exception:  # noqa: BLE001
    SCALE = 1.0
SIZE = round(80 * SCALE)          # diámetro del círculo
PAD = round(14 * SCALE)           # margen al borde de la pantalla
W, H = SIZE + round(10 * SCALE), SIZE + round(24 * SCALE)


def poll() -> None:
    """Pregunta a Atlas en qué está, varias veces por segundo. Si Atlas se cerró, se cierra."""
    while True:
        try:
            req = urllib.request.Request(URL + "/api/live", headers={"X-Atlas-Token": TOKEN, "X-Atlas-Client": "flotante"})
            with urllib.request.urlopen(req, timeout=2) as r:
                data = json.loads(r.read())
                state["mode"] = data.get("mode", "idle")
                state["voz"] = data.get("voz")  # envolvente de la voz, para latir con lo que suena
                state["pendiente"] = data.get("pendiente")  # acción esperando Confirmar / Cancelar
                state["eleccion"] = data.get("eleccion")  # «¿Por WhatsApp, Telegram o Discord…?»
                state["sonando"] = data.get("sonando")  # aviso importante que suena hasta apagarlo
                state["ok"] = time.time()
        except urllib.error.HTTPError as exc:
            if exc.code == 403:  # otro Atlas (token nuevo): este indicador sobra
                os._exit(0)
        except Exception:  # noqa: BLE001
            pass
        if time.time() - state["ok"] > 10:
            os._exit(0)
        time.sleep(0.12)


_DIAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flotante.log")
_diag_ult: dict[str, float] = {}


def _diag(msg: str) -> None:
    """Registro corto del círculo (flotante.log, máx. ~50 KB, sin datos personales): ver la ventana, perderla,
    apagar. Para saber por qué cerrar la ventana no apagó Atlas (18-11-2026). Cada mensaje igual, a lo más 1 por minuto."""
    if time.time() - _diag_ult.get(msg, 0) < 60:
        return
    _diag_ult[msg] = time.time()
    try:
        if os.path.exists(_DIAG) and os.path.getsize(_DIAG) > 50_000:
            os.replace(_DIAG, _DIAG + ".1")
        with open(_DIAG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def atlas_windows() -> list[tuple[int, str]]:
    """Ventanas de Atlas (la app de Edge cuyo título es «Atlas», o «Atlas · Fortuna» con Fortuna abierta dentro)."""
    user32 = ctypes.windll.user32
    # tipos explícitos: sin ellos, un hwnd de 64 bits podía hacer fallar la búsqueda y el círculo nunca veía
    # que la ventana se cerró (18-11-2026: cerrar la ventana dejó el servidor corriendo, con el código viejo)
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        try:
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value.strip()
                if (t in ("Atlas", "Jarvis") or t.startswith(("Atlas \u00b7", "Jarvis \u00b7"))) and user32.IsWindowVisible(hwnd):
                    found.append((hwnd, t))
        except Exception as exc:  # noqa: BLE001  una ventana rara no corta la búsqueda de las demás
            _diag(f"ventana {hwnd}: {type(exc).__name__}: {exc}")
        return True

    user32.EnumWindows(each, 0)
    return found


def detener_voz() -> None:
    """Calla la voz de Atlas al tiro (la ventana se cerró); el apagado puede esperar su margen."""
    try:
        req = urllib.request.Request(URL + "/api/voz/detener", data=b"{}", method="POST",
                                     headers={"X-Atlas-Token": TOKEN, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:  # noqa: BLE001
        pass


def shutdown_atlas() -> None:
    """Cerrar la ventana es cerrar Atlas: se apaga el servidor (con Telegram y la tecla Fin) y este círculo."""
    try:
        req = urllib.request.Request(URL + "/api/apagar", data=b"{}", method="POST",
                                     headers={"X-Atlas-Token": TOKEN, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


def watch_window() -> None:
    """El círculo solo se muestra si la ventana de Atlas está minimizada, o si dentro tiene abierta otra
    página (Fortuna), donde no se ve el círculo grande. Si la ventana se cierra, se cierra todo Atlas."""
    seen, gone_since = False, None
    _diag("círculo iniciado")
    while True:
        try:
            wins = atlas_windows()
            if wins:
                if not seen:
                    _diag(f"vi la ventana de Atlas ({len(wins)})")
                seen, gone_since = True, None
            elif seen:
                if not gone_since:  # recién desapareció: la voz se corta ya, sin esperar los 2,5 s
                    detener_voz()
                    _diag("la ventana desapareció")
                gone_since = gone_since or time.time()
                if time.time() - gone_since > 2.5:  # margen por si Edge recrea la ventana
                    _diag("apagando Atlas")
                    shutdown_atlas()
            user32 = ctypes.windll.user32
            user32.IsIconic.argtypes = [ctypes.c_void_p]
            state["show"] = any(user32.IsIconic(h) or "\u00b7" in t for h, t in wins)
            # menú de música: con Atlas minimizado o con una app abierta dentro de Atlas («Atlas · Hermes»), menos Baco,
            # que ya muestra su música (usuario, 19-11-2026: «igual que con pantalla minimizada»)
            state["min"] = any(user32.IsIconic(h) or ("\u00b7" in t and "baco" not in t.lower()) for h, t in wins)
        except Exception as exc:  # noqa: BLE001
            _diag(f"vigilar ventana: {type(exc).__name__}: {exc}")
            state["show"] = True
        time.sleep(0.3)


def focus_atlas() -> None:
    """Trae al frente la ventana de Atlas."""
    user32 = ctypes.windll.user32
    for hwnd, _t in atlas_windows()[:1]:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


# ------------------------------------------------------------------ Windows: ventana con transparencia por píxel
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_byte)]


gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.c_void_p, ctypes.c_uint]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.CreateFontW.restype = ctypes.c_void_p
gdi32.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
gdi32.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.DrawTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(wintypes.RECT), ctypes.c_uint]
user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UpdateLayeredWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.SIZE),
                                       ctypes.c_void_p, ctypes.POINTER(wintypes.POINT), ctypes.c_uint,
                                       ctypes.POINTER(BLENDFUNCTION), ctypes.c_uint]


def make_dib(w: int, h: int):
    """DC en memoria con un bitmap BGRA de 32 bits (de arriba hacia abajo)."""
    dc = gdi32.CreateCompatibleDC(None)
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
    gdi32.SelectObject(dc, bmp)
    return dc, bmp, bits


def text_mask(text: str, w: int, h: int) -> np.ndarray:
    """Cobertura (0..1) del texto, dibujado por Windows con suavizado."""
    dc, bmp, bits = make_dib(w, h)
    font = gdi32.CreateFontW(-round(9 * SCALE), 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 4, 0, "Consolas")  # 4 = ANTIALIASED
    gdi32.SelectObject(dc, font)
    gdi32.SetTextColor(dc, 0xFFFFFF)
    gdi32.SetBkMode(dc, 1)
    rect = wintypes.RECT(0, 0, w, h)
    user32.DrawTextW(dc, text, -1, ctypes.byref(rect), 0x25)  # centrado, una línea
    px = np.frombuffer(ctypes.string_at(bits, w * h * 4), dtype=np.uint8).reshape(h, w, 4)
    mask = px[:, :, 1].astype(np.float32) / 255
    gdi32.DeleteObject(font)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(dc)
    return mask


# ------------------------------------------------------------------ dibujo (bordes suavizados con distancias)
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5
CX, CY, R = W / 2, SIZE / 2 + 4 * SCALE, SIZE / 2
RR = np.hypot(XX - CX, YY - CY)
TH = np.degrees(np.arctan2(-(YY - CY), XX - CX)) % 360  # grados, antihorario (como los arcos de tk)
DEG = np.maximum(RR, 1) * math.pi / 180                  # píxeles por grado a ese radio


def band(center: float, half: float) -> np.ndarray:
    return np.clip(half + 0.5 - np.abs(RR - center), 0, 1)


def arc_mask(start: float, extent: float) -> np.ndarray:
    """Cobertura angular de un arco (con bordes suaves)."""
    mid = (start + extent / 2) % 360
    d = np.abs((TH - mid + 180) % 360 - 180)
    return np.clip((extent / 2 - d) * DEG + 0.5, 0, 1)


def ticks_mask(rot: float) -> np.ndarray:
    m = np.zeros_like(RR)
    for start, ext in TICKS:
        t = (TH - rot - start) % 360
        local = t % 9
        d = np.abs(local - 3)
        seg = np.clip((3 - d) * DEG + 0.5, 0, 1) * (t < ext)
        m = np.maximum(m, seg)
    return m


DISC = np.clip(R - 3 * SCALE - RR + 0.5, 0, 1)
RIM = band(R - 3 * SCALE, 0.5 * SCALE)
TICK_BAND = band(R - 8 * SCALE, 2.5 * SCALE)
GLOW_BAND = np.exp(-((RR - (R - 8 * SCALE)) ** 2) / (2 * (2.2 * SCALE) ** 2))
INNER_BAND = band(R - 17 * SCALE, 1.4 * SCALE)


def label(text: str):
    """(fondo en píldora, texto) bajo el círculo."""
    lab_h = round(14 * SCALE)
    top = H - lab_h - round(2 * SCALE)
    mask = np.zeros((H, W), np.float32)
    mask[top:top + lab_h, :] = text_mask(text, W, lab_h)
    cols = np.where(mask.max(0) > 0.05)[0]
    half = ((cols[-1] - cols[0]) / 2 + 5 * SCALE) if len(cols) else 0
    mid, ry = W / 2, top + lab_h / 2
    rad = lab_h / 2
    dx = np.maximum(np.abs(XX - mid) - (half - rad), 0)
    pill = np.clip(rad + 0.5 - np.hypot(dx, YY - ry), 0, 1)
    return pill, mask


class Frame:
    """Imagen BGRA premultiplicada que se va pintando capa por capa."""

    def __init__(self) -> None:
        self.c = np.zeros((H, W, 3), np.float32)
        self.a = np.zeros((H, W), np.float32)

    def over(self, color, alpha) -> None:
        alpha = np.asarray(alpha, np.float32)
        self.c = np.asarray(color, np.float32) * alpha[..., None] + self.c * (1 - alpha[..., None])
        self.a = alpha + self.a * (1 - alpha)

    def bgra(self) -> bytes:
        out = np.empty((H, W, 4), np.uint8)
        out[..., 0] = np.clip(self.c[..., 2], 0, 255)
        out[..., 1] = np.clip(self.c[..., 1], 0, 255)
        out[..., 2] = np.clip(self.c[..., 0], 0, 255)
        out[..., 3] = np.clip(self.a * 255, 0, 255)
        return out.tobytes()


def voice_level(now: float) -> float | None:
    """Volumen de la voz que suena ahora (0 a 1), o None si no hay envolvente."""
    v = state.get("voz")
    if not v or not v.get("env"):
        return None
    k = int((now - v["t0"]) / v["step"])
    return v["env"][k] if 0 <= k < len(v["env"]) else 0.0


NBARS = 7
BAR_X = [CX + (i - (NBARS - 1) / 2) * 2.6 * SCALE for i in range(NBARS)]


def bars_mask(levels: list[float]) -> np.ndarray:
    """Barras de voz en el centro del círculo (como las de la pantalla principal): alto según el volumen."""
    m = np.zeros_like(RR)
    half_w = 0.75 * SCALE
    for x, v in zip(BAR_X, levels):
        half_h = (0.8 + 7.2 * max(0.0, min(1.0, v))) * SCALE
        dx = np.abs(XX - x) - half_w
        dy = np.abs(YY - CY) - half_h
        m = np.maximum(m, np.clip(0.5 - dx, 0, 1) * np.clip(0.5 - dy, 0, 1))
    return m


def bar_levels(mode: str, now: float, lvl: float | None) -> list[float]:
    """Mismo cálculo que frame() en hud.html: la envolvente de la voz con forma de campana; quietas si no habla."""
    if mode != "speaking":
        return [0.0] * NBARS
    v = lvl if lvl is not None else 0.35 + 0.35 * math.sin(now * 9) * math.sin(now * 3.7)  # voz del navegador: sin envolvente
    half = (NBARS - 1) / 2
    return [v * (0.45 + 0.55 * math.cos((i - half) / half * math.pi / 2)) * (0.7 + 0.3 * math.sin(now * 16.7 + i * 1.9))
            for i in range(NBARS)]


# ------------------------------------------------------------------ núcleo de Atlas (17-11-2026)
# El mismo globo de la pantalla principal (hud.html, «nucleo Gd»): esfera oscura con las Pléyades, borde cian → violeta
# que gira, la estrella de Atlas que late al escuchar/hablar y suelta ondas. Coordenadas del SVG: centro 256, radio 170.
NU_COLS = {"idle": ((79, 227, 255), (156, 123, 255)), "speaking": ((255, 255, 255), (207, 239, 255)),
           "listening": ((95, 242, 192), (79, 227, 255)), "thinking": ((255, 176, 79), (255, 110, 138))}
NU_ST = [(252.8, 289.8, 12.7, 30.5), (365.8, 288.2, 10, 24.1), (324.6, 239.9, 9.5, 22.8), (303, 319.6, 8.5, 20.4),
         (351.4, 221, 8.1, 19.5), (179.1, 283.8, 5.7, 13.7), (368.9, 254.8, 4.4, 10.7), (321.1, 204.4, 3.4, 8.3)]
NU_LN = [(180.1, 299.6, 179.1, 283.8), (180.1, 299.6, 252.8, 289.8), (252.8, 289.8, 303, 319.6), (303, 319.6, 365.8, 288.2),
         (365.8, 288.2, 368.9, 254.8), (368.9, 254.8, 351.4, 221), (351.4, 221, 324.6, 239.9), (324.6, 239.9, 252.8, 289.8),
         (351.4, 221, 321.1, 204.4)]
NU_ATL = (180.1, 299.6)
RB = 0.84 * (R - 2 * SCALE)        # radio de la esfera en píxeles
NK = RB / 170                      # píxeles por unidad del SVG


def _nu_xy(x: float, y: float) -> tuple[float, float]:
    return CX + (x - 256) * NK, CY + (y - 256) * NK


def _radial(cx: float, cy: float, r: float, stops) -> tuple[np.ndarray, np.ndarray]:
    """Degradado radial: (color HxWx3, alfa HxW) interpolando las paradas (pos, (r,g,b), alfa)."""
    t = np.clip(np.hypot(XX - cx, YY - cy) / r, 0, 1)
    pos = [s[0] for s in stops]
    col = np.stack([np.interp(t, pos, [s[1][i] for s in stops]) for i in range(3)], -1).astype(np.float32)
    return col, np.interp(t, pos, [s[2] for s in stops]).astype(np.float32)


def _seg_mask(x1, y1, x2, y2, half) -> np.ndarray:
    dx, dy = x2 - x1, y2 - y1
    k = np.clip(((XX - x1) * dx + (YY - y1) * dy) / max(dx * dx + dy * dy, 1e-6), 0, 1)
    return np.clip(half + 0.5 - np.hypot(XX - (x1 + k * dx), YY - (y1 + k * dy)), 0, 1)


NU_BODY = np.clip(RB + 0.5 - RR, 0, 1)
NU_BODY_COL, _ = _radial(CX - 0.56 * RB, CY - 0.6 * RB, 1.9 * RB,
                         [(0, (14, 74, 98), 1), (.35, (6, 35, 50), 1), (.75, (3, 14, 22), 1), (1, (1, 6, 10), 1)])
_, NU_ATM_A = _radial(CX - 0.44 * RB, CY - 0.48 * RB, 1.4 * RB, [(0, (0, 0, 0), .45), (.6, (0, 0, 0), .08), (1, (0, 0, 0), 0)])
NU_HALO_A = np.clip(1 - np.hypot(XX - (CX - 40 * NK), YY - (CY - 40 * NK)) / (210 * NK), 0, 1) * 0.35 * 0.45
_u, _v = (XX - CX), (YY - CY)
_c, _s = math.cos(math.radians(18)), math.sin(math.radians(18))
_gu, _gv = _u * _c - _v * _s, _u * _s + _v * _c          # rejilla girada -18° como en el SVG
NU_GRID = np.zeros_like(RR)
for _cy, _rx, _ry in ((143.8, 127.7, 10.2), (199.9, 160.5, 12.8), (256, 170, 13.6), (312.1, 160.5, 12.8), (368.2, 127.7, 10.2)):
    _e = np.hypot(_gu / (_rx * NK), (_gv - (_cy - 256) * NK) / (_ry * NK))
    NU_GRID = np.maximum(NU_GRID, np.clip(0.9 - np.abs(_e - 1) * min(_rx, _ry) * NK, 0, 1))
NU_GRID = np.maximum(NU_GRID, np.clip(0.9 - np.abs(_gu), 0, 1) * (np.abs(_gv) < RB)) * NU_BODY
NU_LINES = np.zeros_like(RR)
for _a, _b, _cc, _d in NU_LN:
    NU_LINES = np.maximum(NU_LINES, _seg_mask(*_nu_xy(_a, _b), *_nu_xy(_cc, _d), max(0.35 * SCALE, 1.5 * NK)))
NU_STAR_D = [np.hypot(XX - _nu_xy(x, y)[0], YY - _nu_xy(x, y)[1]) for x, y, _r, _h in NU_ST]
_ax, _ay = _nu_xy(*NU_ATL)
NU_ATL_D = np.hypot(XX - _ax, YY - _ay)
NU_ATL_U, NU_ATL_V = np.abs(XX - _ax), np.abs(YY - _ay)
nu = {"c1": np.array(NU_COLS["idle"][0], np.float32), "c2": np.array(NU_COLS["idle"][1], np.float32),
      "rot": 0.0, "vel": 40.0, "t": None, "nivel": 0.0}


def _lerp(a, b, k):
    return a + (np.asarray(b, np.float32) - a) * k


def render(angle: float, mode: str, now: float, label_mask, angle2: float | None = None) -> bytes:
    """El núcleo de Atlas (mismo dibujo que la pantalla principal). angle/angle2 se aceptan por compatibilidad."""
    m = mode if mode in NU_COLS else "idle"
    dt = 0.0 if nu["t"] is None else min(0.1, max(0.0, now - nu["t"]))
    nu["t"] = now
    k = min(1.0, dt * 5)
    nu["c1"], nu["c2"] = _lerp(nu["c1"], NU_COLS[m][0], k), _lerp(nu["c2"], NU_COLS[m][1], k)
    c1, c2, white = nu["c1"], nu["c2"], np.array((255, 255, 255), np.float32)
    nu["vel"] += ((327 if m == "thinking" else 40) - nu["vel"]) * min(1.0, dt * 4)
    nu["rot"] = (nu["rot"] + nu["vel"] * dt) % 360
    lvl = voice_level(now) if m == "speaking" else None
    v = min(1.0, (lvl if lvl is not None else (0.35 + 0.35 * math.sin(now * 9) * math.sin(now * 3.7)) if m == "speaking" else 0) * 1.2)
    nu["nivel"] += (v - nu["nivel"]) * min(1.0, dt * 12)
    f = Frame()
    f.over(c1, NU_HALO_A)                                                  # halo
    f.over(NU_BODY_COL, NU_BODY)                                           # esfera
    f.over(c1, NU_GRID * 0.16)                                             # rejilla
    f.over(_lerp(c2, (143, 123, 255), .5), NU_ATM_A * NU_BODY)             # atmósfera violeta
    # borde: arco (66,4° a 223,6° en el SVG) que gira en sentido horario; degradado c1 → blanco → c2
    rot = nu["rot"]
    start = 66.4 - rot
    rel = ((TH - start) % 360) / 157.2
    arc = arc_mask(start, 157.2)
    p = np.clip(rel, 0, 1)
    col = np.where((p < .5)[..., None], _lerp(c1, white, np.clip((p - .22) / .28, 0, 1)[..., None]),
                   _lerp(white, c2, np.clip((p - .5) / .3, 0, 1)[..., None]))
    fade = np.clip(np.minimum(p / .22, (1 - p) / .2), 0, 1)
    glow = np.exp(-((RR - RB) ** 2) / (2 * (5 * NK + 1.2 * SCALE) ** 2))
    f.over(col, glow * arc * fade * 0.55)
    f.over(col, band(RB, max(0.6 * SCALE, 4 * NK)) * arc * fade)
    # constelación
    f.over(c1, NU_LINES * (0.8 if m == "thinking" else 0.4))
    s_col = _lerp(c1, white, .7)
    for i, ((_x, _y, r, h), d) in enumerate(zip(NU_ST, NU_STAR_D)):
        b = 1.0 if m != "idle" else .7 + .3 * math.sin(now * 2 + i * 1.7)
        hh = max(1.2 * SCALE, h * NK) * (.5 + .7 * b)
        f.over(c1, np.clip(1 - d / hh, 0, 1) * 0.35 * b)                   # brillo
        rr = max(0.7 * SCALE, r * NK) * (.55 + .45 * b)
        f.over(s_col, np.clip(rr + 0.5 - d, 0, 1) * (.25 + .75 * b))      # estrella
    # estrella de Atlas: late al escuchar y con la voz al hablar; suelta ondas
    oye, habla = m == "listening", m == "speaking"
    esc = 1 + .12 * (.5 + .5 * math.sin(now * 1000 / 260)) if oye else 1 + .35 * nu["nivel"] if habla else 1
    f.over(c1, np.clip(1 - NU_ATL_D / (42 * NK), 0, 1) * 0.35)
    if oye or habla:
        for i in range(3):
            fr = (now / 1.1 + i / 3) % 1
            al = (.25 + .75 * nu["nivel"] if habla else 1) * .7 * (1 - fr)
            f.over(c1, np.clip(max(0.45 * SCALE, NK) + 0.5 - np.abs(NU_ATL_D - (20 + 90 * fr) * NK), 0, 1) * al)
    sz = 30 * NK * esc
    star = (np.sqrt(NU_ATL_U / sz) + np.sqrt(NU_ATL_V / sz))
    f.over(_lerp(c1, white, .85), np.clip((1 - star) * sz * 0.6 + 0.5, 0, 1))
    if ORBITA.get("p") is not None:  # música de Atlas sonando: arco de avance alrededor (menú «Órbita», 19-11-2026)
        orbita_capa(f, c1, c2, ORBITA["p"])
    if label_mask is not None:
        pill, text = label_mask
        f.over(BG, pill * 0.92)  # fondo oscuro para leerlo sobre cualquier fondo de pantalla
        f.over(c1, text)
    return f.bgra()


def render_reactor(angle: float, mode: str, now: float, label_mask, angle2: float | None = None) -> bytes:
    """Dibujo anterior (reactor de Jarvis). Ya no se usa; queda solo como referencia."""
    inner = angle * 0.6 if angle2 is None else angle2
    col = GREEN if mode == "listening" else AMBER if mode == "thinking" else (255, 255, 255) if mode == "speaking" else CYAN
    f = Frame()
    f.over(BG, DISC * 0.97)
    f.over(DIM, RIM * 0.9)
    rot = -angle
    ticks = ticks_mask(rot)
    pulse = 0.5 + 0.5 * math.sin(now * (6 if mode == "speaking" else 4.8 if mode == "thinking" else 2))
    lvl = voice_level(now) if mode == "speaking" else None
    if lvl is not None:  # habla: late con el volumen real de la voz
        pulse = lvl
    glow = 0.10 + (0.12 if mode == "speaking" else 0.20 * pulse if mode in ("listening", "thinking") else 0.04 * pulse)
    f.over(col, GLOW_BAND * DISC * glow)
    f.over(col, TICK_BAND * ticks)
    f.over(DIM, INNER_BAND * arc_mask(inner + 20, 60))
    f.over(col, INNER_BAND * arc_mask(inner + 200, 120))
    # el anillo interior y el centro quedan quietos: al hablar solo se mueven las barras de adentro (antes el anillo
    # se encogía y se estiraba con la voz y el usuario lo pidió quieto, 15-11-2026)
    rr = R - 26 * SCALE
    f.over(col, band(rr, 0.6 * SCALE) * 0.9)
    f.over(col, np.clip(rr - 7 * SCALE - RR + 0.5, 0, 1) * (0.08 if mode == "speaking" else 0.05))  # centro
    f.over(col, bars_mask(bar_levels(mode, now, lvl)) * (0.95 if mode == "speaking" else 0.55))  # ondas de voz
    if label_mask is not None:
        pill, text = label_mask
        f.over(BG, pill * 0.92)  # fondo oscuro para leerlo sobre cualquier fondo de pantalla
        f.over(col, text)
    return f.bgra()


# ------------------------------------------------------------------ menú de música «Órbita» (usuario, 19-11-2026)
# Con Atlas minimizado y música que puso Atlas («pon …») o la cola de Baco sonando en la ventana de música de Atlas
# (Edge, perfil music-profile, CDP 9223): un arco de luz alrededor del círculo avanza con la canción y al lado sale
# una placa con el título, el artista, el tiempo y ⏮ ⏯ ⏭. También con la cola de Baco andando, aunque esa parte suene
# en Spotify (usuario, 19-11-2026: «cuando Baco reproduce debería ser lo mismo»). Música puesta a mano en otra app no lo abre.
MUSICA_CDP = "http://127.0.0.1:9223/json"
musica: dict = {"v": None, "t": 0.0, "suya": {}, "cambio": 0.0}
ORBITA: dict = {"p": None}


def _cdp_paginas() -> list[dict]:
    with urllib.request.urlopen(MUSICA_CDP, timeout=0.8) as r:
        return [p for p in json.loads(r.read()) if p.get("type") == "page" and "music.youtube.com" in str(p.get("url", ""))]


def _cdp_titulo(pag: dict) -> str:
    """Título que la ventana de música le informa a Windows (mediaSession). '' si no se puede leer."""
    try:
        from websockets.sync.client import connect
    except Exception:  # noqa: BLE001
        return ""
    js = "(navigator.mediaSession&&navigator.mediaSession.metadata&&navigator.mediaSession.metadata.title)||''"
    with connect(pag["webSocketDebuggerUrl"], open_timeout=2, max_size=2**20) as ws:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js, "returnByValue": True}}))
        fin = time.time() + 2
        while time.time() < fin:
            m = json.loads(ws.recv(timeout=2))
            if m.get("id") == 1:
                return str(((m.get("result") or {}).get("result") or {}).get("value") or "")
    return ""


def musica_es_de_atlas(v: dict) -> bool:
    """¿Lo que suena salió de la ventana de música de Atlas? (Lo usan «pon …» y la cola de Baco.)"""
    try:
        pags = _cdp_paginas()
    except Exception:  # noqa: BLE001  la ventana de música de Atlas no está abierta
        return False
    if not pags:
        return False
    tit = str(v.get("titulo") or "").strip().lower()
    app = str(v.get("app") or "").lower()
    # 19-11-2026: el Python de Atlas no siempre trae «websockets» (sin él no se lee el título de la ventana); la ventana de
    # música es Edge, así que basta con que Windows diga que suena Edge y la ventana de Atlas tenga una canción puesta.
    if "msedge" in app and any("/watch" in str(p.get("url", "")) for p in pags):
        return True
    for p in pags:
        try:
            t = _cdp_titulo(p).strip().lower()
        except Exception:  # noqa: BLE001
            t = ""
        if t and tit and (t == tit or t in tit or tit in t):
            return True
        if not t and tit and tit in str(p.get("title", "")).lower():
            return True
    # sin poder leer el título: vale si Windows dice que es Edge (la ventana de música es Edge)
    return not tit and "edge" in app


def cola_baco(v: dict | None) -> dict | None:
    """La cola de Baco si está andando ({id, j, n, fin}), según /acceso/baco/api/media."""
    c = (v or {}).get("cola")
    return c if isinstance(c, dict) and c.get("id") and not c.get("fin") and c.get("n") else None


MARCA_BACO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "musica_baco.json")   # la escribe hud_server.py
baco: dict = {"t_marca": 0.0, "espera": None, "app": "", "visto": 0.0}


def _marca_baco() -> dict:
    try:
        with open(MARCA_BACO, encoding="utf-8") as fh:
            m = json.load(fh)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def musica_es_de_baco(v: dict | None, now: float) -> bool:
    """¿Lo que suena lo puso Baco con ▶ (una canción suelta, en el navegador o en Spotify)? Baco deja una marca al
    abrirla; la app que empieza a sonar en el minuto siguiente queda como «de Baco» mientras siga sonando (aunque pase
    a la canción siguiente). Se suelta tras 2 min sin sonar, o si suena otra app."""
    m = _marca_baco()
    t = float(m.get("t") or 0)
    if t > baco["t_marca"] and now - t < 60:   # marca nueva: se espera la música que corresponda
        baco.update(t_marca=t, espera={"t": t, "spotify": "spotify" in str(m.get("u") or "").lower()}, app="")
    app = str((v or {}).get("app") or "")
    suena = bool(v and v.get("hay") and v.get("estado") == "Playing")
    e = baco["espera"]
    if e and now - e["t"] > 60:
        baco["espera"] = e = None
    if e and suena and app and (("spotify" in app.lower()) == e["spotify"]):
        baco.update(app=app, visto=now, espera=None)
    if baco["app"]:
        if v and v.get("hay") and app == baco["app"]:
            if suena:
                baco["visto"] = now
        elif suena:   # suena otra app: ya no es lo de Baco
            baco["app"] = ""
        if baco["app"] and now - baco["visto"] > 120:
            baco["app"] = ""
    return bool(baco["app"]) and bool(v and v.get("hay")) and app == baco["app"]


MUSICA_ACTUAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "musica_actual.json")   # la lee hud_server.py
_pub: dict = {"k": None, "t": 0.0}


def _publicar_musica() -> None:
    """Lo mismo que decide el menú minimizado (música de Atlas o de Baco), para la ficha de música del panel derecho
    de la ventana de Atlas (19-11-2026). Se escribe al cambiar algo, y cada 3 s para que se vea vigente."""
    v = musica.get("v")
    d = None
    if v:
        cb = cola_baco(v)
        d = {"titulo": str(v.get("titulo") or ""), "artista": str(v.get("artista") or ""), "album": str(v.get("album") or ""),
             "estado": str(v.get("estado") or ""), "pos": float(v.get("pos") or 0), "fin": float(v.get("fin") or 0),
             "baco": bool(cb or v.get("_baco")),
             "cola": {"j": int(cb.get("j") or 0), "n": int(cb.get("n") or 0)} if cb else None}
    k = json.dumps(d, sort_keys=True)
    now = time.time()
    if k == _pub["k"] and now - _pub["t"] < 3:
        return
    try:
        tmp = MUSICA_ACTUAL + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"t": musica.get("t") or now, "v": d}, fh)
        os.replace(tmp, MUSICA_ACTUAL)
        _pub.update(k=k, t=now)
    except OSError:   # el servidor justo lo estaba leyendo: va en la vuelta siguiente
        pass


def poll_musica() -> None:
    """Lo que suena, ~1 vez por segundo con el círculo a la vista (cada 2 s si no, para no perder lo que Baco pone con
    Atlas abierto). Pregunta a Baco (/acceso/baco/api/media)."""
    clave_ok, t_ok, suya, ult_diag = None, 0.0, False, None
    while True:
        try:
            clave_ok, t_ok, suya, ult_diag = _poll_musica_1(clave_ok, t_ok, suya, ult_diag)
            _publicar_musica()
        except Exception as exc:  # noqa: BLE001  que un error raro no apague el menú para siempre
            _diag(f"menú de música (lectura): {type(exc).__name__}: {exc}")
        time.sleep(0.8 if state["show"] else 2.0)


def _poll_musica_1(clave_ok, t_ok, suya, ult_diag):
    """Una lectura: qué suena y si es de Atlas o de Baco."""
    v, t = None, time.time()
    try:
        with urllib.request.urlopen(URL + "/acceso/baco/api/media", timeout=4) as r:
            v = json.loads(r.read())
        t = time.time()
    except Exception as exc:  # noqa: BLE001
        v = None
        if ult_diag != "error":
            _diag(f"menú de música: no pude leer lo que suena ({type(exc).__name__})")
            ult_diag = "error"
    if v and v.get("hay") and v.get("titulo") and v.get("estado") in ("Playing", "Paused"):
        if cola_baco(v) or musica_es_de_baco(v, time.time()):   # cola de Baco o canción que Baco puso con ▶
            suya, clave_ok = True, None
            v["_baco"] = True
        else:
            clave = (v.get("titulo"), v.get("artista"), v.get("app"))
            if clave != clave_ok or time.time() - t_ok > 15:  # ¿es de Atlas? se vuelve a mirar al cambiar o cada 15 s
                suya, clave_ok, t_ok = musica_es_de_atlas(v), clave, time.time()
        musica["v"], musica["t"] = (v if suya else None), t
        d = f"suena {v.get('app_n') or v.get('app') or '?'}: {'de Baco' if v.get('_baco') else 'de Atlas' if suya else 'no es de Atlas ni de Baco'}"
        if d != ult_diag:   # sin títulos (datos personales): solo la app y la decisión, al cambiar
            _diag("menú de música: " + d)
            ult_diag = d
    else:
        musica_es_de_baco(v, time.time())   # que lleve la cuenta aunque no suene nada
        musica["v"], musica["t"], clave_ok = None, t, None
    return clave_ok, t_ok, suya, ult_diag


def musica_accion(accion: str) -> None:
    def enviar():
        try:
            req = urllib.request.Request(URL + "/acceso/baco/api/media", data=json.dumps({"accion": accion}).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                v = json.loads(r.read())
            if v.get("hay"):
                if (musica.get("v") or {}).get("_baco"):
                    v["_baco"] = True
                musica["v"], musica["t"] = v, time.time()
                _publicar_musica()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=enviar, daemon=True).start()


def _mmss(s) -> str:
    try:
        s = max(0, int(float(s)))
    except (TypeError, ValueError):
        return "0:00"
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def musica_pos(v: dict, now: float) -> tuple[float, float]:
    """(posición, duración) en segundos, avanzando entre una lectura y otra si está sonando."""
    pos, fin = float(v.get("pos") or 0), float(v.get("fin") or 0)
    if v.get("estado") == "Playing":
        pos += max(0.0, now - musica["t"])
    return (min(pos, fin) if fin > 0 else pos), fin


_TXT: dict = {}


def texto_mask(text: str, w: int, h: int, font: str = "Bahnschrift", size: float = 12, weight: int = 400,
               flags: int = 0x8824) -> np.ndarray:
    """Cobertura (0..1) de un texto dibujado por Windows. flags por omisión: izquierda, centrado vertical, una línea,
    sin «&» y con «…» si no cabe."""
    key = (text, w, h, font, size, weight, flags)
    m = _TXT.get(key)
    if m is not None:
        return m
    if len(_TXT) > 300:
        _TXT.clear()
    dc, bmp, bits = make_dib(w, h)
    f = gdi32.CreateFontW(-round(size * SCALE), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, font)  # 4 = ANTIALIASED
    gdi32.SelectObject(dc, f)
    gdi32.SetTextColor(dc, 0xFFFFFF)
    gdi32.SetBkMode(dc, 1)
    rect = wintypes.RECT(0, 0, w, h)
    user32.DrawTextW(dc, text, -1, ctypes.byref(rect), flags)
    px = np.frombuffer(ctypes.string_at(bits, w * h * 4), dtype=np.uint8).reshape(h, w, 4)
    m = px[:, :, 1].astype(np.float32) / 255
    gdi32.DeleteObject(f)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(dc)
    _TXT[key] = m
    return m


def orbita_capa(f, c1, c2, p: float) -> None:
    """Arco de avance alrededor del círculo (diseño A «Órbita»): sale de arriba y gira a la derecha, con una estrella
    en la punta. p = 0..1."""
    white = np.array((255, 255, 255), np.float32)
    ro = R - 1.6 * SCALE
    f.over(c1, band(ro, 0.45 * SCALE) * 0.16)                              # órbita completa, tenue
    ext = max(1.0, min(1.0, p) * 360)
    am = arc_mask(90 - ext, ext)
    q = np.clip(((90 - TH) % 360) / ext, 0, 1)                             # 0 arriba … 1 en la punta
    col = np.where((q < .6)[..., None], _lerp(c1, white, np.clip(q / .6, 0, 1)[..., None]),
                   _lerp(white, c2, np.clip((q - .6) / .4, 0, 1)[..., None]))
    f.over(col, np.exp(-((RR - ro) ** 2) / (2 * (1.8 * SCALE) ** 2)) * am * 0.45)   # brillo
    f.over(col, band(ro, 0.85 * SCALE) * am)
    a = math.radians(90 - ext)
    hx, hy = CX + ro * math.cos(a), CY - ro * math.sin(a)
    du, dv = np.abs(XX - hx), np.abs(YY - hy)
    f.over(c2, np.clip(1 - np.hypot(du, dv) / (5 * SCALE), 0, 1) * 0.5)
    sz = 4.2 * SCALE
    f.over(white, np.clip((1 - (np.sqrt(du / sz) + np.sqrt(dv / sz))) * sz * 0.8 + 0.5, 0, 1))


class PanelMusica:
    """Placa al lado del círculo: «● SONANDO · ATLAS», título, artista, tiempo y ⏮ ⏯ ⏭. Va a la izquierda del círculo
    (o a la derecha si el círculo está pegado al borde izquierdo). Termina en un disco oscuro detrás del círculo, así el
    arco de avance se lee sobre cualquier fondo de pantalla; el círculo se dibuja encima."""

    PW = round(316 * SCALE)          # de la punta de la placa al centro del círculo
    EXT = round(R + 5 * SCALE)       # lo que sigue más allá del centro (medio disco)
    PWT = PW + EXT                   # ancho de la ventana
    DISCO = R + 3 * SCALE            # radio del disco detrás del círculo
    GLYPH = {"prev": "\uE892", "next": "\uE893", "play": "\uE768", "pause": "\uE769"}   # Segoe MDL2 Assets

    def __init__(self, owner) -> None:
        self.owner = owner
        self.win = tk.Toplevel(owner.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{self.PWT}x{H}+-4000+-4000")
        self.win.update_idletasks()
        self.hwnd = user32.GetAncestor(self.win.winfo_id(), 2)
        ex = user32.GetWindowLongW(self.hwnd, -20)
        user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80 | 0x08000000)   # LAYERED | TOOLWINDOW | NOACTIVATE
        self.dc, self.bmp, self.bits = make_dib(self.PWT, H)
        self.visible, self.alpha, self.lado = False, 0.0, None
        self.hover, self.pressed, self.btns = None, None, {}
        self.optimista: tuple[str, float] | None = None   # estado que se muestra al tiro tras apretar ⏯
        self.win.bind("<Motion>", self.motion)
        self.win.bind("<Leave>", lambda _e: setattr(self, "hover", None))
        self.win.bind("<ButtonPress-1>", self.click)
        self.win.bind("<Button-3>", lambda _e: state.update(hide_until=time.time() + 600))
        self.geom(False)
        # 19-11-2026: sin ShowWindow(0) aquí. Ocultarla antes del primer UpdateLayeredWindow la dejaba en modo
        # SetLayeredWindowAttributes y Windows rechazaba todo dibujo (la placa nunca se veía). Queda fuera de pantalla.

    # --- forma
    def geom(self, derecha: bool) -> None:
        """Máscaras de la placa. derecha=True: el círculo queda a la izquierda de la placa."""
        if self.lado == derecha:
            return
        self.lado = derecha
        s, pw = SCALE, self.PWT
        yy, xx = np.mgrid[0:H, 0:pw].astype(np.float32) + 0.5
        self.yy, self.xx = yy, xx
        cx = float(self.EXT) if derecha else float(self.PW)            # centro del círculo en la placa
        self.cx = cx
        top, bot, rad = CY - self.DISCO, CY + self.DISCO, 14 * s
        x0, x1 = (cx, pw - 1.0) if derecha else (1.0, cx)
        qx = np.maximum(np.maximum(x0 + rad - xx, xx - (x1 - rad)), 0)
        qy = np.maximum(np.maximum(top + rad - yy, yy - (bot - rad)), 0)
        rect_d = np.hypot(qx, qy) - rad                                  # < 0 adentro (rectángulo redondeado)
        disco_d = np.hypot(xx - cx, yy - CY) - self.DISCO
        d = np.minimum(rect_d, disco_d)                                  # distancia con signo de la forma
        self.fill = np.clip(0.5 - d, 0, 1)
        self.edge = np.clip(0.6 * s + 0.5 - np.abs(d + 0.6 * s), 0, 1)
        borde = np.clip(np.minimum.reduce([xx, pw - xx, yy, H - yy]) / (4 * s), 0, 1)   # se apaga antes del borde
        self.glow = np.exp(-np.maximum(d, 0) ** 2 / (2 * (3.5 * s) ** 2)) * (d > 0) * borde
        self.x0 = round((cx + R + 12 * s) if derecha else 16 * s)    # donde empieza el contenido
        self.x1 = round((pw - 16 * s) if derecha else (cx - R - 10 * s))
        by = CY + 28 * s
        bx = self.x0 + 10 * s
        self.btns = {"prev": (bx, by, 10 * s), "toggle": (bx + 27 * s, by, 12 * s), "next": (bx + 54 * s, by, 10 * s)}

    # --- dibujo
    def _over(self, c, a, color, mask, x: int, y: int) -> None:
        """Pinta mask (alto x ancho) con color en (x, y), solo en ese recuadro (más rápido que toda la placa)."""
        h, w = min(mask.shape[0], H - y), min(mask.shape[1], self.PWT - x)
        if h <= 0 or w <= 0 or x < 0 or y < 0:
            return
        al = mask[:h, :w] * self.fill[y:y + h, x:x + w]
        cs, as_ = c[y:y + h, x:x + w], a[y:y + h, x:x + w]
        cs[...] = np.asarray(color, np.float32) * al[..., None] + cs * (1 - al[..., None])
        as_[...] = al + as_ * (1 - al)

    def _base(self, v: dict, suena: bool):
        """Lo que no cambia de un cuadro a otro (fondo, textos, botones). Se recuerda hasta que algo cambie."""
        de_baco = cola_baco(v) is not None or bool(v.get("_baco"))
        key = (self.lado, v.get("titulo"), v.get("artista"), v.get("album"), suena, de_baco, self.hover, self.pressed)
        if getattr(self, "_bkey", None) == key:
            return self._b
        s, pw = SCALE, self.PWT
        f = Frame.__new__(Frame)   # misma mezcla de capas que el círculo, con el ancho de la placa
        f.c, f.a = np.zeros((H, pw, 3), np.float32), np.zeros((H, pw), np.float32)
        cyan, dim, white = np.array(CYAN, np.float32), np.array((143, 195, 214), np.float32), np.array((234, 251, 255), np.float32)
        f.over((2, 10, 18), self.glow * 0.35)
        f.over((4, 18, 30), self.fill * 0.9)
        f.over(cyan, self.edge * 0.38)
        x0, cw = self.x0, max(10, self.x1 - self.x0)
        ly = round(CY - 37 * s)
        rot = "\u200a".join(("SONANDO" if suena else "EN PAUSA") + (" · BACO" if de_baco else " · ATLAS"))
        self._over(f.c, f.a, cyan, texto_mask(rot, cw - round(12 * s), round(13 * s), "Consolas", 9.5, 400), x0 + round(12 * s), ly)
        self._over(f.c, f.a, white, texto_mask(str(v.get("titulo") or ""), cw, round(22 * s), "Bahnschrift", 16.5, 400),
                   x0, round(CY - 24 * s))
        sub = " · ".join(x for x in (str(v.get("artista") or ""), str(v.get("album") or "")) if x)
        self._over(f.c, f.a, dim, texto_mask(sub, cw, round(16 * s), "Bahnschrift", 12, 300), x0, round(CY - 3 * s))
        for k, (bx, by, r) in self.btns.items():
            d = np.hypot(self.xx - bx, self.yy - by)
            ring = np.clip(0.55 * s + 0.5 - np.abs(d - r), 0, 1)
            hov = self.hover == k
            if k == "toggle":
                f.over(cyan, np.exp(-((d - r) ** 2) / (2 * (2.5 * s) ** 2)) * 0.25 * self.fill)
            f.over(cyan, np.clip(r + 0.5 - d, 0, 1) * (0.28 if self.pressed == k else 0.16 if hov else 0.06) * self.fill)
            f.over(cyan if (k == "toggle" or hov) else np.array((79, 160, 190), np.float32),
                   ring * (1 if k == "toggle" else .7) * self.fill)
            g = self.GLYPH["pause" if suena else "play"] if k == "toggle" else self.GLYPH[k]
            box = round(2 * r)
            gm = texto_mask(g, box, box, "Segoe MDL2 Assets", 10.5 if k == "toggle" else 9, 400, 0x825)
            self._over(f.c, f.a, cyan if k == "toggle" else (191, 243, 255), gm, round(bx - r), round(by - r))
        self._bkey, self._b = key, (f.c, f.a)
        return self._b

    def render(self, v: dict, now: float) -> bytes | None:
        """La placa completa (BGRA premultiplicado), o None si se ve igual que el cuadro anterior."""
        s = SCALE
        estado = v.get("estado")
        if self.optimista and now - self.optimista[1] < 2.5:
            estado = self.optimista[0]
        suena = estado == "Playing"
        pos, fin = musica_pos(v, now)
        if self.optimista and self.optimista[0] == "Paused":
            pos, fin = float(v.get("pos") or 0), float(v.get("fin") or 0)
        t = f"{_mmss(pos)} / {_mmss(fin)}" if fin > 0 else _mmss(pos)
        cb = cola_baco(v)
        if cb:
            t += f"  ·  COLA {int(cb.get('j') or 0) + 1}/{cb.get('n')}"
        lat = .75 + .25 * math.sin(now * 3) if suena else .45
        bc, ba = self._base(v, suena)
        key = (id(bc), self.lado, t, round(lat * 24))
        if getattr(self, "_fkey", None) == key:
            return None
        self._fkey = key
        c, a = bc.copy(), ba.copy()
        # punto que late junto a «SONANDO»
        x0, ly, r0 = self.x0, round(CY - 37 * s), round(7 * s)
        dx, dy = round(x0 + 3 * s), round(ly + 6 * s)
        yy, xx = np.mgrid[0:2 * r0, 0:2 * r0].astype(np.float32) + 0.5
        dot = np.hypot(xx - r0, yy - r0)
        verde = (98, 240, 180) if suena else (143, 195, 214)
        self._over(c, a, verde, np.clip(1 - dot / (6 * s), 0, 1) * 0.35 * lat, dx - r0, dy - r0)
        self._over(c, a, verde, np.clip(2.6 * s + 0.5 - dot, 0, 1) * lat, dx - r0, dy - r0)
        # tiempo
        tx = round(self.btns["next"][0] + 20 * s)
        self._over(c, a, (143, 195, 214), texto_mask(t, max(10, self.x1 - tx), round(14 * s), "Consolas", 10, 400),
                   tx, round(self.btns["next"][1] - 7 * s))
        out = np.empty((H, self.PWT, 4), np.uint8)
        out[..., 0], out[..., 1], out[..., 2] = (np.clip(c[..., i], 0, 255) for i in (2, 1, 0))
        out[..., 3] = np.clip(a * 255, 0, 255)
        self._ult = out.tobytes()
        return self._ult

    def paint(self, data: bytes, x: int, y: int) -> None:
        ctypes.memmove(self.bits, data, len(data))
        size, src, dst = wintypes.SIZE(self.PWT, H), wintypes.POINT(0, 0), wintypes.POINT(x, y)
        blend = BLENDFUNCTION(0, 0, max(0, min(255, round(255 * self.alpha))), 1)
        args = (self.hwnd, self.owner.screen, ctypes.byref(dst), ctypes.byref(size), self.dc, ctypes.byref(src), 0,
                ctypes.byref(blend), 2)
        if not user32.UpdateLayeredWindow(*args):   # Windows la rechaza si quedó en modo SetLayeredWindowAttributes: se rearma
            ex = user32.GetWindowLongW(self.hwnd, -20)
            user32.SetWindowLongW(self.hwnd, -20, ex & ~0x80000)
            user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000)
            if not user32.UpdateLayeredWindow(*args):
                _diag("menú de música: Windows no deja dibujar la placa")

    # --- cada cuadro (lo llama Mini.tick)
    def tick(self, now: float, dt: float, mostrar: bool) -> float | None:
        """Pinta la placa si corresponde. Devuelve el avance (0..1) para el arco del círculo, o None."""
        v = musica["v"] if (mostrar and state.get("min")) else None   # solo con Atlas minimizado (usuario, 19-11-2026)
        if v is None and musica.get("ultimo") is not None and self.alpha > 0:
            v = musica["ultimo"]          # se desvanece con lo último que mostró
            meta = 0.0
        else:
            meta = 1.0 if v is not None else 0.0
        if v is not None:
            musica["ultimo"] = v
        self.alpha += (meta - self.alpha) * min(1.0, dt * 9)
        if meta == 0 and self.alpha < 0.02:
            self.alpha = 0.0
            if self.visible:
                user32.ShowWindow(self.hwnd, 0)
                self.visible = False
            return None
        rx, ry = self.owner.root.winfo_x(), self.owner.root.winfo_y()
        derecha = rx + CX - self.PW < 0       # el círculo pegado a la izquierda: la placa va a su derecha
        self.geom(derecha)
        x = round(rx + CX - self.cx)
        data = self.render(v, now)
        if data is not None or (x, ry) != getattr(self, "pos", None) or abs(self.alpha - getattr(self, "a_pint", -1)) > 0.004:
            self.paint(data or self._ult, x, ry)
            self.pos, self.a_pint = (x, ry), self.alpha
        if not self.visible or now - getattr(self, "t_z", 0) > 1:
            if not self.visible:
                user32.ShowWindow(self.hwnd, 4)   # SW_SHOWNOACTIVATE
                self.visible = True
            # el círculo siempre encima de la placa (HWND_TOPMOST; sin mover, sin cambiar tamaño, sin activar)
            user32.SetWindowPos(ctypes.c_void_p(self.owner.hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x13)
            self.t_z = now
        pos, fin = musica_pos(v, now)
        return (pos / fin if fin > 0 else 0.0) if meta else None

    # --- mouse
    def boton_en(self, e) -> str | None:
        for k, (bx, by, r) in self.btns.items():
            if math.hypot(e.x - bx, e.y - by) <= r + 3 * SCALE:
                return k
        return None

    def motion(self, e):
        self.hover = self.boton_en(e)
        self.win.configure(cursor="hand2" if self.hover else "arrow")

    def click(self, e):
        k = self.boton_en(e)
        if not k:
            focus_atlas()   # clic en la placa: como en el círculo, trae Atlas
            return
        self.pressed = k
        self.win.after(160, lambda: setattr(self, "pressed", None))
        v = musica.get("v") or {}
        if k == "toggle":
            nuevo = "Paused" if v.get("estado") == "Playing" else "Playing"
            if v:
                v["pos"], _ = musica_pos(v, time.time())
                musica["t"] = time.time()
            self.optimista = (nuevo, time.time())
        musica_accion(k)

    def ocultar(self) -> None:
        if self.visible:
            user32.ShowWindow(self.hwnd, 0)
            self.visible = False
        self.alpha = 0.0


class Mini:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        x, y = self.default_pos()
        self.root.geometry(f"{W}x{H}+{x}+{y}")
        self.root.update_idletasks()
        self.hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
        ex = user32.GetWindowLongW(self.hwnd, -20)
        user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)  # WS_EX_LAYERED | WS_EX_TOOLWINDOW
        self.screen = user32.GetDC(None)
        self.dc, self.bmp, self.bits = make_dib(W, H)
        self.labels = {}
        for m, t in LABELS.items():
            self.labels[m] = label(t)
        self.angle = 0.0
        self.vel = 12.0
        self.kick, self.anchor, self.next_kick = 0.0, 0.0, 0.0
        self.angle2, self.kick2, self.anchor2, self.next_kick2 = 0.0, 0.0, 0.0, 0.0
        self.drag = None
        self.hidden = False
        self.root.bind("<ButtonPress-1>", self.press)
        self.root.bind("<B1-Motion>", self.move)
        self.root.bind("<ButtonRelease-1>", self.release)
        self.root.bind("<Button-3>", lambda _e: state.update(hide_until=time.time() + 600))
        self.last = time.time()
        self.ov, self.ov_done = None, None  # tarjeta de confirmación sobre toda la pantalla (ver overlay_tick)
        self.musica = PanelMusica(self)  # menú de música «Órbita» al lado del círculo
        self.tick()
        self.root.after(200, self.overlay_tick)
        self.icons = None
        self.root.after(1500, self.icon_tick)

    # --- tarjeta sobre toda la pantalla: oscurece el escritorio y deja solo la tarjeta para elegir.
    #     Dos casos: Confirmar / Cancelar (acción pendiente) y «¿Por WhatsApp, Telegram o Discord…?» (un botón por app)
    APPS = {"whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord"}

    SONANDO = {"alarma": "ALARMA", "temporizador": "TEMPORIZADOR", "recordatorio": "RECORDATORIO"}

    def overlay_want(self) -> dict | None:
        # 1) aviso importante sonando: tapa toda la pantalla aunque Atlas esté minimizado o detrás (usuario, 17-11-2026:
        #    «la idea es que me tape toda la pantalla, no solo la app»). Va primero: suena hasta que lo apaguen.
        a = state.get("sonando")
        if a and a.get("id"):
            return {"key": "s:" + str(a["id"]), "title": ("LLEGÓ LO QUE ESPERABA" if str(a["id"]).startswith("vigilancia-") else "ACTIVIDAD PRÓXIMA"
                              if str(a["id"]).startswith("previo-") else self.SONANDO.get(a.get("tipo", ""), "AVISO IMPORTANTE")),
                    "text": a.get("texto", ""), "path": "/api/alert_ack",
                    "buttons": [("ENTENDIDO", {"id": a["id"]}, "Apagando…")]}
        p = state.get("pendiente")
        if p:
            return {"key": "c:" + p, "title": "CONFIRMACIÓN REQUERIDA", "text": p, "path": "/api/confirm",
                    "buttons": [("CONFIRMAR", {"accept": True, "speak": True}, "Ejecutando…"),
                                ("CANCELAR", {"accept": False, "speak": True}, "Cancelando…")]}
        e = state.get("eleccion")
        if e and e.get("apps"):
            apps = [a for a in e["apps"] if a in self.APPS]
            return {"key": "e:" + json.dumps(e, sort_keys=True), "title": "ELEGIR APLICACIÓN",
                    "text": f"¿Por dónde le escribo a {e.get('nombre', '')}?\nEl mensaje sería: «{e.get('texto', '')}».",
                    "path": "/api/eleccion",
                    "buttons": [(self.APPS[a].upper(), {"app": a}, "Preparando…") for a in apps]
                    + [("CANCELAR", {"app": ""}, "Cancelando…")]}
        return None

    def overlay_tick(self):
        """Va aparte de tick(): la tarjeta sale aunque el círculo esté oculto (ventana de Atlas abierta)."""
        try:
            want = self.overlay_want()
            if not want:
                self.ov_done = None
                if self.ov:
                    self.close_overlay()
            elif self.ov and self.ov.get("finished"):
                self.close_overlay()
            elif self.ov and self.ov.get("error"):  # no llegó a Atlas: se avisa y se puede volver a apretar
                self.ov["error"], self.ov["sent"], self.ov_done = None, False, None
                self.ov["status"].config(text="No pude avisarle a Atlas. Intente de nuevo.")
                for b in self.ov["btns"]:
                    b.config(state="normal")
            elif self.ov is None:
                if want["key"] != self.ov_done:
                    self.open_overlay(want)
            elif not self.ov["sent"] and want["key"] != self.ov["key"]:  # cambió lo que se pregunta
                self.close_overlay()
                self.open_overlay(want)
        except Exception:  # noqa: BLE001
            pass
        self.root.after(150, self.overlay_tick)

    def open_overlay(self, want: dict) -> None:
        gsm = user32.GetSystemMetrics
        vx, vy, vw, vh = gsm(76), gsm(77), gsm(78), gsm(79)  # escritorio virtual (todas las pantallas)
        sw, sh = gsm(0), gsm(1)  # pantalla principal
        dim = tk.Toplevel(self.root)
        dim.overrideredirect(True)
        dim.configure(bg="#01040A", cursor="arrow")
        dim.geometry(f"{vw}x{vh}+{vx}+{vy}")
        dim.attributes("-alpha", 0.55)
        dim.attributes("-topmost", True)

        s = SCALE
        px = lambda v: round(v * s)  # noqa: E731  (px de la HUD -> píxeles reales)
        # mismo diseño que la tarjeta #confirm de la HUD (hud.html): fondo café oscuro, borde ámbar de 1 px,
        # rótulo en Consolas espaciado, texto en Bahnschrift 18 px, botones con borde ámbar y el primero relleno
        amber, bg, ink, filled = "#FFB86B", "#1C1104", "#DFF7FF", "#493219"
        sans = "Bahnschrift" if "Bahnschrift" in tkfont.families(self.root) else "Segoe UI"
        spaced = lambda t: "\u200a".join(t)  # noqa: E731  (letter-spacing que tkinter no tiene)
        card = tk.Toplevel(self.root)
        card.overrideredirect(True)
        card.attributes("-topmost", True)
        card.configure(bg=amber)  # el borde de 1 px
        inner = tk.Frame(card, bg=bg, padx=px(24), pady=px(22))
        inner.pack(padx=max(1, px(1)), pady=max(1, px(1)), fill="both", expand=True)
        tk.Label(inner, text=spaced(want["title"]), bg=bg, fg=amber, font=("Consolas", -px(11)),
                 anchor="w", bd=0).pack(fill="x")
        what = tk.Label(inner, text=want["text"], bg=bg, fg=ink, font=(sans, -px(18)), justify="left", anchor="w",
                        wraplength=px(510), bd=0)
        what.pack(fill="x", pady=(px(4), px(14)))
        row = tk.Frame(inner, bg=bg)
        row.pack(fill="x")
        status = tk.Label(row, text="", bg=bg, fg=amber, font=(sans, -px(14)), bd=0)
        status.pack(side="left")
        btns = []
        for i, (label, body, doing) in reversed(list(enumerate(want["buttons"]))):  # a la derecha, en orden
            box = tk.Frame(row, bg=amber)  # borde de 1 px como en la HUD
            b = tk.Button(box, text=spaced(label), bg=filled if i == 0 else bg, fg=ink, activebackground="#6A4920",
                          activeforeground=ink, font=(sans, -px(15), "bold"), relief="flat", bd=0, cursor="hand2",
                          highlightthickness=0, padx=px(18), pady=px(10),
                          command=lambda bd=body, dg=doing: self.decide(bd, dg))
            b.pack(padx=max(1, px(1)), pady=max(1, px(1)))
            box.pack(side="right", padx=(px(14), 0))
            btns.insert(0, b)
        first, last = want["buttons"][0], want["buttons"][-1]
        for w in (card, dim):  # Enter = el primero (Confirmar / la app de siempre), Esc = el último (Cancelar)
            w.bind("<Return>", lambda _e: self.decide(first[1], first[2]))
            w.bind("<Escape>", lambda _e: self.decide(last[1], last[2]))
        dim.bind("<Button-1>", lambda _e: self.flash_card())  # fuera de la tarjeta no pasa nada (no se cierra)
        card.update_idletasks()
        cw, ch = max(card.winfo_reqwidth(), px(560)), card.winfo_reqheight()
        cx, cy = (sw - cw) // 2, (sh - ch) // 2
        card.geometry(f"{cw}x{ch}+{cx}+{cy}")
        card.lift(dim)
        # el círculo de Atlas se pone justo encima de la tarjeta mientras está abierta, y después vuelve a su lugar
        # update_idletasks antes de leer winfo_x: si justo se cerró otra tarjeta, su geometry(home) aún no se aplicaba y
        # winfo_x devolvía la posición de arriba de la tarjeta; el círculo quedaba pegado al medio (usuario, 15-11-2026)
        self.root.update_idletasks()
        top = ((sw - W) // 2, cy - H - px(6))
        if not getattr(self, "ov_home", None):
            here = (self.root.winfo_x(), self.root.winfo_y())
            self.ov_home = here if abs(here[0] - top[0]) + abs(here[1] - top[1]) > px(4) else self.default_pos()
        self.root.geometry(f"+{top[0]}+{top[1]}")
        self.root.lift()
        self.ov = {"dim": dim, "card": card, "what": what, "status": status, "btns": btns, "key": want["key"],
                   "path": want["path"], "sent": False}
        self.grab_focus(card)

    def grab_focus(self, win) -> None:
        """Windows no deja que un programa de fondo tome el foco; un toque de Alt lo permite (truco conocido)."""
        try:
            win.update_idletasks()
            hwnd = user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)  # KEYEVENTF_KEYUP
            user32.SetForegroundWindow(hwnd)
            win.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def flash_card(self) -> None:
        ov = self.ov
        if not ov or ov["sent"]:
            return
        ov["status"].config(text="Elija una opción")
        self.root.after(1400, lambda: ov["status"].config(text="") if not ov["sent"] else None)

    def decide(self, body: dict, doing: str) -> None:
        ov = self.ov
        if not ov or ov["sent"]:
            return
        ov["sent"] = True
        ov["status"].config(text=doing)
        for b in ov["btns"]:
            b.config(state="disabled")
        self.ov_done = ov["key"]

        def send():
            try:
                req = urllib.request.Request(URL + ov["path"], data=json.dumps(body).encode(), method="POST",
                                             headers={"X-Atlas-Token": TOKEN, "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=120).read()
                ov["finished"] = True  # Tk solo desde su hilo: overlay_tick la cierra
            except Exception as exc:  # noqa: BLE001
                ov["error"] = f"{type(exc).__name__}"  # la tarjeta sigue abierta y deja reintentar (ver overlay_tick)

        threading.Thread(target=send, daemon=True).start()

    def close_overlay(self, ov=None) -> None:
        ov = ov or self.ov
        if not ov:
            return
        for k in ("card", "dim"):
            try:
                ov[k].destroy()
            except Exception:  # noqa: BLE001
                pass
        if self.ov is ov:
            self.ov = None
            home = getattr(self, "ov_home", None)
            if home:
                self.root.geometry(f"+{home[0]}+{home[1]}")
                self.root.update_idletasks()  # que quede aplicado antes de que otra tarjeta lea la posición
                self.ov_home = None

    # --- mover / abrir
    def press(self, e):
        self.drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def move(self, e):
        if not self.drag:
            return
        x0, y0, wx, wy, _ = self.drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if abs(dx) + abs(dy) > 4:
            self.drag = (x0, y0, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def icon_tick(self):
        """Ícono nítido en la barra de tareas: Edge arma el de la ventana agrandando el favicon de 16 px y se veía
        pixelado (usuario, 15-11-2026). Se le pone atlas.ico en el tamaño exacto que pide Windows (WM_SETICON)."""
        try:
            if self.icons is None:
                ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas.ico")
                user32.LoadImageW.restype = ctypes.c_void_p
                user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_uint]
                load = lambda n: user32.LoadImageW(None, ico, 1, n, n, 0x10)  # noqa: E731  IMAGE_ICON, LR_LOADFROMFILE
                self.icons = (load(user32.GetSystemMetrics(11)), load(user32.GetSystemMetrics(49)))  # SM_CXICON, SM_CXSMICON
            big, small = self.icons
            if big and small:
                user32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                                       ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
                user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
                for hwnd, _t in atlas_windows():
                    cur = ctypes.c_size_t()
                    # WM_GETICON ICON_BIG con tope de 300 ms: si Edge está pegado, el círculo no se traba
                    if not user32.SendMessageTimeoutW(hwnd, 0x7F, 1, None, 2, 300, ctypes.byref(cur)):
                        continue
                    if cur.value != big:  # Edge lo puso (o lo volvió a cambiar)
                        user32.PostMessageW(hwnd, 0x80, 1, big)  # WM_SETICON ICON_BIG (barra de tareas, Alt+Tab)
                        user32.PostMessageW(hwnd, 0x80, 0, small)  # ICON_SMALL (título)
        except Exception:  # noqa: BLE001
            pass
        self.root.after(3000, self.icon_tick)

    def default_pos(self) -> tuple[int, int]:
        """Arriba a la derecha (su lugar de siempre)."""
        x = self.root.winfo_screenwidth() - W - PAD - (W + PAD if "--muestra" in os.environ.get("ATLAS_FLOTANTE", "") else 0)
        return x, PAD

    def release(self, _e):
        moved = self.drag and self.drag[4]
        self.drag = None
        if not moved:
            focus_atlas()

    @staticmethod
    def jump(old: float, amp: float) -> float:
        """Nueva posición al azar a uno u otro lado, lo bastante lejos de la anterior para que se note."""
        while True:
            k = random.uniform(-amp, amp)
            if abs(k - old) > 0.35 * amp:
                return k

    def paint(self, data: bytes) -> None:
        ctypes.memmove(self.bits, data, len(data))
        size, src = wintypes.SIZE(W, H), wintypes.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, alfa por píxel
        self.ok = user32.UpdateLayeredWindow(self.hwnd, self.screen, None, ctypes.byref(size), self.dc, ctypes.byref(src), 0,
                                   ctypes.byref(blend), 2)  # ULW_ALPHA
        if not self.ok:  # Windows lo rechaza si alguien le aplicó SetLayeredWindowAttributes: se rearma la capa
            ex = user32.GetWindowLongW(self.hwnd, -20)
            user32.SetWindowLongW(self.hwnd, -20, ex & ~0x80000)
            user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)
            self.ok = user32.UpdateLayeredWindow(self.hwnd, self.screen, None, ctypes.byref(size), self.dc,
                                                 ctypes.byref(src), 0, ctypes.byref(blend), 2)

    def tick(self):
        now = time.time()
        dt, self.last = min(0.1, now - self.last), now
        mode = state["mode"]
        if (now < state["hide_until"] or not state["show"]) and not self.ov:  # con la tarjeta abierta se ve siempre
            if not self.hidden:  # ShowWindow directo: withdraw/deiconify de tkinter dejaba la ventana sin dibujo
                user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
                self.hidden = True
            self.musica.ocultar()
            ORBITA["p"] = None
            self.root.after(150, self.tick)
            return
        if self.hidden:
            user32.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE (no le quita el foco a lo que esté usando)
            self.hidden = False
        self.root.attributes("-topmost", True)
        if mode == "thinking":  # se traba como un trinquete: cada anillo da golpes secos por su cuenta, al azar
            if now >= self.next_kick:
                self.next_kick = now + random.uniform(0.18, 0.6)
                self.kick = self.jump(self.kick, 24)
            if now >= self.next_kick2:
                self.next_kick2 = now + random.uniform(0.18, 0.6)
                self.kick2 = self.jump(self.kick2, 40)
            self.angle += (self.anchor + self.kick - self.angle) * min(1, dt * 18)
            self.angle2 += (self.anchor2 + self.kick2 - self.angle2) * min(1, dt * 18)
        else:
            want = {"idle": 12.0, "listening": 0.0, "speaking": 160.0}.get(mode, 12.0)
            self.vel += (want - self.vel) * min(1, dt * 4)
            self.angle += self.vel * dt
            self.angle2 += self.vel * 0.6 * dt
            self.anchor, self.anchor2 = self.angle, self.angle2
        try:
            ORBITA["p"] = self.musica.tick(now, dt, not self.ov)
        except Exception as exc:  # noqa: BLE001
            ORBITA["p"] = None
            _diag(f"menú de música: {type(exc).__name__}: {exc}")
        try:
            self.paint(render(self.angle, mode, now, self.labels.get(mode), self.angle2))
        except Exception:  # noqa: BLE001
            pass
        self.root.after(33, self.tick)


if __name__ == "__main__":
    if "--muestra" in os.environ.get("ATLAS_FLOTANTE", ""):  # para revisar el dibujo sin Atlas
        state["ok"] = 1e12

        def cycle():
            while True:
                for m in ("idle", "listening", "thinking", "speaking"):
                    state["mode"] = m
                    time.sleep(2)

        threading.Thread(target=cycle, daemon=True).start()
        if "--confirmar" in os.environ.get("ATLAS_FLOTANTE", ""):  # para revisar la tarjeta de confirmación
            state["pendiente"] = "Enviar por WhatsApp a Benji: «Hola Benji»"
        if "--musica" in os.environ.get("ATLAS_FLOTANTE", ""):  # para revisar el menú de música
            state["min"] = True
            musica.update(t=time.time(), v={"hay": True, "titulo": "Clocks", "artista": "Coldplay",
                                            "album": "A Rush of Blood to the Head", "estado": "Playing", "pos": 106, "fin": 307})
        if "--elegir" in os.environ.get("ATLAS_FLOTANTE", ""):  # para revisar la tarjeta de elegir app
            state["eleccion"] = {"nombre": "Benji", "texto": "Hola", "apps": ["whatsapp", "telegram", "discord"]}
    else:
        threading.Thread(target=poll, daemon=True).start()
        threading.Thread(target=poll_musica, daemon=True, name="musica").start()
    threading.Thread(target=watch_window, daemon=True).start()
    Mini().root.mainloop()

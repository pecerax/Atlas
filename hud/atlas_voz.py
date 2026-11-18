"""Voces de Atlas en español: tres perfiles guardados y uno activo.

Perfiles (elegidos el 15-11-2026, ver página "Voces para Atlas"):
  - "k6b_tramos"      Kokoro: em_santa 0,5 + bm_george 0,25 + bm_lewis 0,25, velocidad 1,15, EQ cálida.
                      Se genera por tramos (frase / dos puntos / ", con …") para empezar a hablar antes.
  - "davefx_afinada"  Piper es_ES-davefx-medium más expresiva (length 0,95, noise 0,8, noise_w 0,9) + EQ cálida.
  - "davefx_original" Piper es_ES-davefx-medium tal cual (la voz de siempre).
  - "mx_ald", "mx_claude"  Piper es_MX-ald-medium y es_MX-claude-high (las suma el instalador, 18-11-2026).

El activo se elige en voz.json ({"activa": "k6b_tramos"}) o con la variable ATLAS_VOZ; si el perfil falla,
se usa davefx_original. Todo corre en CPU (la GPU queda para Ollama).
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VOICES_DIR = Path(os.environ.get("LOCALAPPDATA", str(HERE))) / "Atlas" / "voices"
CONFIG = HERE / "voz.json"
PERFILES = ("k6b_tramos", "davefx_afinada", "davefx_original", "mx_ald", "mx_claude")
PIPER_MX = {"mx_ald": "es_MX-ald-medium.onnx", "mx_claude": "es_MX-claude-high.onnx"}
DEFECTO = "k6b_tramos"
_lock = threading.Lock()
_cache: dict = {}


def activa() -> str:
    env = os.environ.get("ATLAS_VOZ", "").strip()
    if env in PERFILES:
        return env
    try:
        v = json.loads(CONFIG.read_text(encoding="utf-8")).get("activa", DEFECTO)
        return v if v in PERFILES else DEFECTO
    except Exception:  # noqa: BLE001
        return DEFECTO


# ---------------------------------------------------------------- texto: horas y números que se leían raro
def _palabras(n: int) -> str:
    try:
        from num2words import num2words

        return num2words(n, lang="es")
    except Exception:  # noqa: BLE001
        return str(n)


def _apocope(n: int) -> str:
    """21 -> «veintiún», 31 -> «treinta y un» (delante de un sustantivo masculino como «grados»)."""
    w = _palabras(n)
    if n % 10 == 1 and n % 100 != 11:
        w = re.sub(r"veintiuno$", "veintiún", w)
        w = re.sub(r"uno$", "un", w)
    return w


def preparar(text: str) -> str:
    def hora(m):
        h, mm = int(m.group(1)), int(m.group(2))
        if mm == 0:
            return str(h)
        if mm == 15:
            return f"{h} y cuarto"
        if mm == 30:
            return f"{h} y media"
        return f"{h} y {mm}"

    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", hora, text)  # "8:15" se leía «ocho:quince» con un corte raro
    text = re.sub(r"(-?\d+)\s*°(?:\s?C\b)?", lambda m: _grados(m.group(1)), text)
    text = re.sub(r"\b(\d+)\s+grados\b", lambda m: _grados(m.group(1)), text)
    return text


def _grados(s: str) -> str:
    n = int(s)
    pre = "menos " if n < 0 else ""
    n = abs(n)
    return f"{pre}{_apocope(n) if n != 1 else 'un'} grado{'s' if n != 1 else ''}"


def tramos(text: str) -> list[str]:
    """Corta en fin de frase, punto y coma, dos puntos y antes de ", con …" (cláusulas largas)."""
    partes = re.split(r"(?<=[.!?;:])\s+|(?<=,)\s+(?=(?:con|pero|aunque|mientras|y luego)\s)", text)
    return [p.strip() for p in partes if p.strip()]


# ---------------------------------------------------------------- efectos
def _db(d):
    return 10 ** (d / 20)


def _fft_filter(x, rate, gain_fn):
    n = 1 << int(np.ceil(np.log2(len(x) + 1)))
    f = np.fft.rfftfreq(n, 1 / rate)
    return np.fft.irfft(np.fft.rfft(x, n) * gain_fn(f), n)[: len(x)]


def _calida(x: np.ndarray, rate: int, chest_db: float, chest_hz: float, tame_db: float) -> np.ndarray:
    def g(f):
        hp = 1 / np.sqrt(1 + (70 / (f + 1)) ** 4)
        chest = 1 + (_db(chest_db) - 1) * np.exp(-((np.log2((f + 1) / chest_hz)) ** 2) / 0.6)
        tame = 1 - (1 - _db(tame_db)) / (1 + (3000 / (f + 1)) ** 2)
        return hp * chest * tame

    y = _fft_filter(x, rate, g)
    # sala muy corta (5 %), pre-delay 15 ms
    rng = np.random.default_rng(3)
    n = int(rate * 0.2)
    t = np.arange(n) / rate
    ir = rng.standard_normal(n) * np.exp(-t * 6.9 / 0.2)
    ir[: int(rate * 0.015)] = 0
    ir = _fft_filter(ir, rate, lambda f: 1 / np.sqrt(1 + (200 / (f + 1)) ** 4) / np.sqrt(1 + (f / 8000) ** 2))
    ir /= np.sqrt((ir ** 2).sum())
    m = 1 << int(np.ceil(np.log2(len(y) + n)))
    wet = np.fft.irfft(np.fft.rfft(y, m) * np.fft.rfft(ir, m), m)[: len(y)]
    return y + 0.05 * wet


def _a_pcm(x: np.ndarray, peak: float) -> np.ndarray:
    return (np.clip(x / max(peak, 1e-9), -1, 1) * 0.9 * 32767).astype(np.int16)


def _recorta(a: np.ndarray, rate: int) -> np.ndarray:
    """Quita silencio de los bordes sin comerse el final de la última sílaba (fundido de 40 ms)."""
    idx = np.where(np.abs(a) > np.abs(a).max() * 0.004)[0]
    if not len(idx):
        return a
    a = a[max(0, idx[0] - int(rate * 0.01)): idx[-1] + int(rate * 0.12)].copy()
    n = min(len(a), int(rate * 0.04))
    a[-n:] *= np.linspace(1, 0, n) ** 2
    m = min(len(a), int(rate * 0.005))
    a[:m] *= np.linspace(0, 1, m)
    return a


# ---------------------------------------------------------------- motores
def _piper(archivo: str = "es_ES-davefx-medium.onnx"):
    clave = "piper" if archivo == "es_ES-davefx-medium.onnx" else "piper:" + archivo
    if clave not in _cache:
        from piper import PiperVoice

        _cache[clave] = PiperVoice.load(str(VOICES_DIR / archivo))
    return _cache[clave]


def _kokoro():
    if "kokoro" not in _cache:
        from kokoro import KPipeline

        p = KPipeline(lang_code="e", device="cpu", repo_id="hexgrad/Kokoro-82M")
        pack = (p.load_single_voice("em_santa") * 0.5 + p.load_single_voice("bm_george") * 0.25
                + p.load_single_voice("bm_lewis") * 0.25)
        _cache["kokoro"] = (p, pack)
    return _cache["kokoro"]


def _piper_pcm(text: str, afinada: bool, archivo: str = "es_ES-davefx-medium.onnx") -> tuple[np.ndarray, int]:
    from piper import SynthesisConfig

    v = _piper(archivo)
    cfg = SynthesisConfig(length_scale=0.95, noise_scale=0.8, noise_w_scale=0.9) if afinada else None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        v.synthesize_wav(text, w, syn_config=cfg)
    with wave.open(io.BytesIO(buf.getvalue())) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    if not afinada:
        return pcm, rate
    x = pcm.astype(np.float64) / max(1, np.abs(pcm).max())
    y = _calida(x, rate, 3.0, 160, -3.0)
    return _a_pcm(y, np.abs(y).max()), rate


def _kokoro_trozos(text: str):
    """Genera (pcm int16, rate) tramo a tramo, para empezar a sonar con el primero."""
    p, pack = _kokoro()
    rate = 24000
    for t in tramos(text):
        a = np.concatenate([r.audio.numpy() for r in p(t, voice=pack, speed=1.15)]).astype(np.float64)
        if not len(a):
            continue
        a = _recorta(a / max(np.abs(a).max(), 1e-9), rate)
        y = _calida(a, rate, 2.5, 180, -2.5)
        y = np.concatenate([y, np.zeros(int(rate * 0.12))])  # pausa entre tramos
        yield _a_pcm(y, np.abs(y).max() / 0.98), rate


def trozos(text: str, perfil: str | None = None):
    """Audio por partes (pcm int16, rate). Si el perfil activo falla, cae a davefx_original."""
    perfil = perfil or activa()
    text = preparar(text)
    if not text.strip():
        return
    try:
        if perfil == "k6b_tramos":
            first = True
            for chunk in _kokoro_lock(text):
                first = False
                yield chunk
            if not first:
                return
        elif perfil == "davefx_afinada":
            with _lock:
                out = _piper_pcm(text, afinada=True)
            yield out
            return
        elif perfil in PIPER_MX:
            with _lock:
                out = _piper_pcm(text, afinada=False, archivo=PIPER_MX[perfil])
            yield out
            return
    except Exception as exc:  # noqa: BLE001
        _cache["ultimo_error"] = f"{perfil}: {type(exc).__name__}: {exc}"
    with _lock:
        out = _piper_pcm(text, afinada=False)
    yield out


def _kokoro_lock(text: str):
    gen = _kokoro_trozos(text)
    while True:
        with _lock:
            try:
                chunk = next(gen)
            except StopIteration:
                return
        yield chunk


def wav(text: str, perfil: str | None = None) -> bytes:
    """Todo el audio en un WAV (para la ventana del HUD y los avisos)."""
    parts, rate = [], 22050
    for pcm, rate in trozos(text, perfil):
        parts.append(pcm)
    if not parts:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate(parts).tobytes())
    return buf.getvalue()


def calentar() -> str:
    """Carga el perfil activo (y davefx de respaldo) y hace una síntesis corta."""
    perfil = activa()
    _piper()
    if perfil == "k6b_tramos":
        list(trozos("Hola.", perfil))
    elif perfil in PIPER_MX:
        _piper(PIPER_MX[perfil])
    return perfil


def nombre() -> str:
    return {"k6b_tramos": "K6b (Kokoro)", "davefx_afinada": "davefx afinada", "davefx_original": "davefx",
            "mx_ald": "Ald (México)", "mx_claude": "Claude (México)"}[activa()]

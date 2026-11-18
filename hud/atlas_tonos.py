"""Tonos de aviso sintetizados (sin archivos de audio), en estéreo y con reverberación.

Para escucharlos:  python atlas_tonos.py   -> guarda hud/sonidos/<nombre>.wav
Cada función devuelve int16 estéreo (n, 2) a RATE, con 0,25 s de silencio al inicio (la tarjeta de sonido o el
Bluetooth tarda en despertar y se comía el comienzo, ver chime() en hud_server.py).
Primera ronda (pulso, escáner, cristal): al usuario no le gustó ninguno (15-11-2026).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

RATE = 44100
_rng = np.random.default_rng(7)  # siempre el mismo sonido


def _t(dur: float) -> np.ndarray:
    return np.arange(int(RATE * dur)) / RATE


def _env(t, start, attack, decay, hold=0.0):
    tt = t - start
    on = tt >= 0
    tt = np.clip(tt, 0, None)
    a = np.clip(tt / attack, 0, 1) ** 2 * (3 - 2 * np.clip(tt / attack, 0, 1))  # subida suave (sin clic)
    d = np.where(tt < attack + hold, 1.0, np.exp(-(tt - attack - hold) / decay))
    return a * d * on


def _lowpass(x, cutoff):
    """Pasa-bajos de un polo (suaviza lo sintético)."""
    a = np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # corto: los tonos duran ~2 s
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def _reverb(st, seconds=1.4, wet=0.28, bright=5000):
    """Reverberación por convolución con una cola de ruido decreciente, distinta en cada canal (da amplitud)."""
    n = int(RATE * seconds)
    tt = np.arange(n) / RATE
    out = np.zeros((st.shape[0] + n - 1, 2))
    for ch in range(2):
        ir = _rng.standard_normal(n) * np.exp(-tt / (seconds / 5))
        ir[: int(RATE * 0.012)] = 0  # pre-delay
        ir = _lowpass(ir, bright)
        ir /= np.sqrt((ir ** 2).sum())
        size = 1 << int(np.ceil(np.log2(st.shape[0] + n)))
        out[:, ch] = np.fft.irfft(np.fft.rfft(st[:, ch], size) * np.fft.rfft(ir, size), size)[: st.shape[0] + n - 1]
    dry = np.zeros_like(out)
    dry[: st.shape[0]] = st
    return dry * (1 - wet) + out * wet


def _pan(x, p):
    """p de -1 (izquierda) a 1 (derecha), potencia constante."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def _finish(st, gain=0.42, tail=0.6, fade_s=0.25, reverb_s=1.4):
    st = _reverb(st, reverb_s)
    st = st[: st.shape[0] - int(RATE * max(0.0, reverb_s - tail))]
    fade = int(RATE * fade_s)
    x = np.linspace(0, 1, fade)
    st[-fade:] *= (0.5 + 0.5 * np.cos(np.pi * x))[:, None] ** 1.5  # caída suave (coseno), sin final brusco
    st = st / (np.abs(st).max() or 1) * gain
    lead = np.zeros((int(RATE * 0.25), 2))
    return (np.concatenate([lead, st]) * 32767).astype(np.int16)


def transmision():
    """TRANSMISIÓN: pulso grave de nave (dos golpes), sobre él un acorde de aire que sube y un par de
    destellos de datos a los lados. Serio, tipo «transmisión entrante» de una interfaz de ciencia ficción."""
    t = _t(3.4)  # con 2,2 s el acorde se cortaba todavía sonando
    st = np.zeros((len(t), 2))
    for s in (0.0, 0.42):  # dos golpes graves
        f = 98 * (1 + 0.04 * np.exp(-(t - s).clip(0) / 0.05))  # leve caída de tono al golpear
        ph = 2 * np.pi * np.cumsum(f) / RATE
        body = (np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)) * _env(t, s, 0.012, 0.28)
        st += _pan(_lowpass(body, 900), 0) * 0.9
    for f, p, d in ((587.3, -0.5, 0.0), (880.0, 0.5, 0.05), (1174.7, 0.0, 0.1)):  # acorde de aire (re-la-re)
        sw = f * (0.985 + 0.015 * np.clip((t - 0.35) / 0.6, 0, 1))
        ph = 2 * np.pi * np.cumsum(sw) / RATE
        pad = (np.sin(ph) + 0.25 * np.sin(2.003 * ph)) * _env(t, 0.35 + d, 0.35, 0.55, 0.35)
        st += _pan(pad, p) * 0.22
    for s, f, p in ((0.95, 2349.3, -0.8), (1.06, 2793.8, 0.8), (1.17, 3136.0, -0.3)):  # destellos de datos
        blip = np.sin(2 * np.pi * f * t) * _env(t, s, 0.003, 0.05)
        st += _pan(blip, p) * 0.12
    # Elegido por el usuario (15-11-2026), «le falta mejorar el fadeout»: la cola de la reverberación entera
    # (2,2 s) y una caída en coseno de 1,6 s, en vez de cortar la cola y bajar en 0,25 s
    return _finish(st, tail=2.2, fade_s=1.6, reverb_s=2.2)


def _trim(pcm: np.ndarray, floor: float = 0.0015, fade_s: float = 0.5) -> np.ndarray:
    """Quita el silencio del final (donde la cola ya bajó de -56 dB) y lo cierra con un fundido corto en coseno."""
    lvl = np.abs(pcm.astype(np.float32)).max(axis=1)
    keep = int(np.nonzero(lvl > lvl.max() * floor)[0][-1]) + int(RATE * 0.05)
    out = pcm[:keep].astype(np.float32)
    n = min(int(RATE * fade_s), len(out))
    out[-n:] *= (0.5 + 0.5 * np.cos(np.pi * np.linspace(0, 1, n)))[:, None]
    return out.astype(np.int16)


def llamada(rate: int = RATE):
    """El tono de llamada entrante que eligió el usuario (Transmisión), con la cola completa y sin silencio al final."""
    return _trim(transmision())


def interfaz():
    """INTERFAZ: motivo de cuatro notas tipo marimba de vidrio que salta de un lado a otro, repetido dos veces;
    nítido y moderno, como el tono de un teléfono de buena marca."""
    t = _t(2.3)
    st = np.zeros((len(t), 2))
    notes = ((0.00, 1318.5, -0.45), (0.13, 1760.0, 0.45), (0.26, 1975.5, -0.2), (0.39, 2637.0, 0.25))
    for rep in (0.0, 0.85):
        for s, f, p in notes:
            s += rep
            body = (np.sin(2 * np.pi * f * t) * _env(t, s, 0.004, 0.32)
                    + 0.35 * np.sin(2 * np.pi * 4.0 * f * t) * _env(t, s, 0.002, 0.03)  # golpe de mazo
                    + 0.12 * np.sin(2 * np.pi * 2.0 * f * t) * _env(t, s, 0.004, 0.12))
            st += _pan(body, p) * (0.9 if rep == 0 else 0.75)
    sub = np.sin(2 * np.pi * 329.6 * t) * (_env(t, 0.0, 0.01, 0.4) + 0.8 * _env(t, 0.85, 0.01, 0.4))  # base cálida
    st += _pan(sub, 0) * 0.25
    return _finish(st, 0.4)


def calido():
    """CÁLIDO: dos acordes de piano eléctrico (síntesis FM suave, como un Rhodes), sin nada estridente:
    suena a timbre de casa moderna más que a máquina."""
    t = _t(2.6)
    st = np.zeros((len(t), 2))

    def ep(f, s, amp, p):
        idx = 1.6 * np.exp(-(t - s).clip(0) / 0.25)  # el «brillo» del golpe se apaga rápido
        tt = (t - s).clip(0)
        tone = np.sin(2 * np.pi * f * tt + idx * np.sin(2 * np.pi * f * tt)) * _env(t, s, 0.006, 0.9)
        trem = 1 + 0.06 * np.sin(2 * np.pi * 5.2 * tt)  # trémolo leve, típico del piano eléctrico
        return _pan(tone * trem * amp, p)

    for f, p in ((261.6, -0.3), (329.6, 0.1), (392.0, 0.35), (493.9, -0.1)):  # do mayor 7
        st += ep(f, 0.0, 0.32, p)
    for f, p in ((293.7, -0.25), (349.2, 0.15), (440.0, 0.35), (523.3, -0.15)):  # re menor 7
        st += ep(f, 0.55, 0.30, p)
    st += ep(784.0, 1.1, 0.22, 0.4) + ep(659.3, 1.25, 0.18, -0.4)  # remate arriba
    st[:, 0] = _lowpass(st[:, 0], 3200)
    st[:, 1] = _lowpass(st[:, 1], 3200)
    return _finish(st, 0.4, 0.9)


TONOS = {"transmision": transmision, "interfaz": interfaz, "calido": calido}


def save_all(folder: Path | None = None) -> list[Path]:
    import wave

    folder = folder or Path(__file__).resolve().parent / "sonidos"
    folder.mkdir(exist_ok=True)
    out = []
    for i, (k, fn) in enumerate(TONOS.items(), start=4):  # 4, 5, 6: la segunda ronda (1-3 fueron la primera)
        pcm = fn()
        p = folder / f"llamada_{i}_{k}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        out.append(p)
    return out


if __name__ == "__main__":
    for p in save_all():
        print(p)

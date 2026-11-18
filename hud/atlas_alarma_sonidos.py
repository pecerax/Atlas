"""Sonidos de alarma EN BUCLE (alarmas, temporizadores y recordatorios), sintetizados, sin archivos.

Uso real (17-11-2026): «la alarma en loop no suena bien». Causa: cada vuelta abría el parlante de nuevo
(sd.play por cada campanita, con 1 s de silencio sin sonido entre medio). El parlante o el Bluetooth se «duerme»
en la pausa y al despertar se come el comienzo o da un clic. Ahora el bucle es UN solo sonido continuo
(bucle()): la pausa va dentro del audio, así el parlante nunca se apaga, y cada vuelta empalma sin clic
(la cola de una vuelta se suma al comienzo de la siguiente).

Para escuchar las opciones:  python atlas_alarma_sonidos.py  -> hud/sonidos/alarma_<n>_<nombre>.wav (20 s cada una)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

RATE = 44100
LEAD = 0.25  # silencio solo al principio: la tarjeta de sonido / el Bluetooth tarda en despertar


def _t(dur: float) -> np.ndarray:
    return np.arange(int(RATE * dur)) / RATE


def _bell(t, f, start, decay, amp=1.0):
    tt = np.clip(t - start, 0, None)
    env = (1 - np.exp(-tt / 0.006)) * np.exp(-tt / decay) * (t >= start)
    return amp * env * (np.sin(2 * np.pi * f * tt) + 0.2 * np.sin(2 * np.pi * 2 * f * tt) + 0.05 * np.sin(2 * np.pi * 3 * f * tt))


def _beep(t, f, start, dur, amp=1.0):
    """Pitido con bordes redondeados (coseno), sin clic."""
    tt = t - start
    on = (tt >= 0) & (tt <= dur)
    edge = 0.012
    env = np.where(tt < edge, 0.5 - 0.5 * np.cos(np.pi * np.clip(tt, 0, edge) / edge),
                   np.where(tt > dur - edge, 0.5 - 0.5 * np.cos(np.pi * np.clip(dur - tt, 0, edge) / edge), 1.0))
    return amp * env * on * (np.sin(2 * np.pi * f * tt) + 0.15 * np.sin(2 * np.pi * 2 * f * tt))


def _echo(x, delay=0.11, fb=0.28, n=4):
    """Eco corto y suave (da espacio sin enturbiar)."""
    out = x.copy()
    d = int(RATE * delay)
    g = 1.0
    for k in range(1, n + 1):
        g *= fb
        out[k * d:] += g * x[:len(x) - k * d]
    return out


def _cycle(x: np.ndarray, period: float) -> np.ndarray:
    """Recorta a `period` segundos; lo que sobra (la cola) se suma al comienzo: la vuelta siguiente empalma sin corte."""
    n = int(RATE * period)
    if len(x) < n:
        x = np.concatenate([x, np.zeros(n - len(x))])
    out = x[:n].copy()
    tail = x[n:]
    while len(tail):
        k = min(n, len(tail))
        out[:k] += tail[:k]
        tail = tail[k:]
    return out


# --------------------------------------------------------------------------- las opciones (una vuelta cada una)
# Uso real 17-11: «baja tanto que no se escucha bien, se siente cortado»: la campanita se apagaba en ~0,3 s y luego
# había 1 s de nada. Estas opciones suenan más fuerte y sostenidas: la cola de cada vuelta llega hasta la siguiente.

def campanita():
    """1 · CAMPANITA SOSTENIDA: la misma (mi y si), pero la campana dura y se repite cada 1,8 s, sin huecos."""
    t = _t(4.0)
    x = _bell(t, 659.25, 0.0, 0.9) + _bell(t, 987.77, 0.20, 0.9, 0.8)
    return _cycle(x, 1.8)


def despertador():
    """2 · DESPERTADOR: cuatro pitidos redondos y firmes (do agudo), cada 1,2 s. El que más se nota."""
    t = _t(2.0)
    x = sum(_beep(t, 1046.5, s, 0.12) for s in (0.0, 0.18, 0.36, 0.54))
    return _cycle(_echo(x, 0.09, 0.2, 3), 1.2)


def ascendente():
    """3 · ASCENDENTE: tres campanas que suben (do-mi-sol), largas, cada 1,8 s. Más musical."""
    t = _t(4.0)
    x = _bell(t, 1046.5, 0.0, 0.8) + _bell(t, 1318.5, 0.18, 0.8, 0.9) + _bell(t, 1568.0, 0.36, 0.9, 0.85)
    return _cycle(_echo(x, 0.14, 0.2, 3), 1.8)


def _pulso_raw():
    t = _t(3.0)
    return (_bell(t, 523.25, 0.0, 0.45) + 0.6 * _bell(t, 261.6, 0.0, 0.6)
            + _bell(t, 523.25, 0.25, 0.45, 0.9) + 0.55 * _bell(t, 261.6, 0.25, 0.6))


def pulso():
    """4 · PULSO: dos golpes graves y cálidos (como un timbre de madera), cada 1,2 s. Se nota sin ser chillón."""
    return _cycle(_pulso_raw(), 1.2)


SONIDOS = {"campanita": campanita, "despertador": despertador, "ascendente": ascendente, "pulso": pulso}
DEFAULT = "pulso"  # el que eligió el usuario (17-11-2026)


def bucle(nombre: str = DEFAULT, segundos: float = 60.0, gain: float = 0.6, crece: float = 0.0) -> np.ndarray:
    """-> int16 mono: LEAD de silencio + vueltas seguidas del sonido durante ~`segundos`, en un solo bloque.
    crece > 0: empieza al 35 % del volumen y llega al 100 % en `crece` segundos."""
    one = SONIDOS.get(nombre, SONIDOS[DEFAULT])()
    one = one / (np.abs(one).max() or 1.0) * gain
    reps = max(1, int(round(segundos / (len(one) / RATE))))
    x = np.tile(one, reps)
    if crece > 0:
        ramp = np.clip(0.35 + 0.65 * (np.arange(len(x)) / RATE) / crece, 0, 1)
        x = x * ramp
    x = np.concatenate([np.zeros(int(RATE * LEAD)), x])
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


def aviso(gain: float = 0.5) -> np.ndarray:
    """Un solo Pulso (los dos golpes, con su cola completa) para los avisos puntuales: U-Cursos, «Fortuna quedó
    actualizada»… Pedido del usuario (17-11-2026): «los avisos puntuales que ocupen un pulso». int16 mono a RATE."""
    x = _pulso_raw()
    x = x / (np.abs(x).max() or 1.0) * gain
    fade = int(RATE * 0.3)
    x[-fade:] *= np.linspace(1, 0, fade)
    x = np.concatenate([np.zeros(int(RATE * LEAD)), x])
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


def save_all(folder: Path | None = None, segundos: float = 20.0) -> list[Path]:
    import wave

    folder = folder or Path(__file__).resolve().parent / "sonidos"
    folder.mkdir(exist_ok=True)
    out = []
    for f in folder.glob("alarma_*.wav"):
        f.unlink()
    muestras = [(k, bucle(k, segundos)) for k in SONIDOS]
    muestras.append(("campanita_que_sube", bucle("campanita", segundos, crece=15.0)))
    for i, (k, pcm) in enumerate(muestras, start=1):
        p = folder / f"alarma_{i}_{k}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        out.append(p)
    return out


if __name__ == "__main__":
    for p in save_all():
        print(p)

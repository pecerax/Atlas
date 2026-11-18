"""Graba tu voz leyendo frases de prueba, para medir qué reconocedor de voz te entiende mejor.

Uso: doble clic en Grabar-pruebas-voz.cmd. Lee en voz alta cada frase cuando aparezca "Hable ahora";
se corta solo tras un segundo de silencio. Los audios quedan en hud/pruebas_voz/audios (no salen del PC).
"""
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

HERE = Path(__file__).parent
OUT = HERE / "audios"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))
from frases import FRASES  # noqa: E402

RATE, BLOCK = 16000, 1600


def record() -> np.ndarray:
    chunks, heard, quiet, start = [], False, 0.0, time.time()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as st:
        while True:
            data, _ = st.read(BLOCK)
            chunks.append(data.copy())
            if float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) > 500:
                heard, quiet = True, 0.0
            else:
                quiet += BLOCK / RATE
            if (heard and quiet > 1.0) or time.time() - start > 15 or (not heard and time.time() - start > 8):
                break
    return np.concatenate(chunks)


def main():
    meta = []
    print("Vas a leer", len(FRASES), "frases. Habla como le hablas a Atlas normalmente (sin decir 'Atlas' antes si no lo haces).")
    input("Presiona Enter para empezar…")
    for i, (txt, keys) in enumerate(FRASES):
        while True:
            print(f"\n[{i + 1}/{len(FRASES)}]  {txt}")
            time.sleep(0.6)
            print("   Hable ahora…")
            a = record()
            ans = input("   Enter = siguiente, r = repetir: ").strip().lower()
            if ans != "r":
                break
        p = OUT / f"real_{i:02d}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(a.tobytes())
        meta.append({"file": p.name, "voz": "real", "i": i, "ref": txt, "keys": keys})
        (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nListo. Avísale a Claude que ya grabaste las frases.")
    input("Enter para cerrar.")


if __name__ == "__main__":
    main()

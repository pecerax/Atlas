"""Compara reconocedores de voz con las grabaciones de hud/pruebas_voz/audios (23-11-2026).

Uso: 1) Grabar-pruebas-voz.cmd (lee las frases).  2) Comparar-voz.cmd.
Pasa cada audio por Parakeet (el de hoy) y por Whisper large-v3-turbo, con el mismo vocabulario propio, y anota
qué escribió cada uno, cuántas palabras erró y cuánto tardó. Todo corre en el PC; los audios no salen de aquí.
El resultado queda en hud/pruebas_voz/resultado_comparacion.txt.
La primera vez Whisper turbo se descarga (unos 1,6 GB).
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUD = HERE.parent
AUDIOS = HERE / "audios"
sys.path.insert(0, str(HUD))
sys.path.insert(0, str(HERE))


def plano(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


def errores(ref: list[str], hip: list[str]) -> int:
    """Palabras cambiadas, faltantes o sobrantes (distancia de edición por palabras)."""
    prev = list(range(len(hip) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hip, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def vocabulario() -> list[str]:
    """Parecido al de Atlas (hud_server._stt_vocab): diccionario, contactos, ramos y palabras fijas."""
    v: list[str] = []
    try:
        import atlas_nombres as NM

        v += list(NM.vocabulario() or []) + [x["correcto"] for x in NM.palabras()]
    except Exception as exc:  # noqa: BLE001
        print("  (sin diccionario:", exc, ")")
    try:
        import atlas_contactos

        for c in atlas_contactos.load():
            v += [c.get("nombre") or ""] + list(c.get("apodos") or [])
    except Exception:  # noqa: BLE001
        pass
    try:
        for r in json.loads((HUD / "ramos.json").read_text(encoding="utf-8")).get("ramos", []):
            v += [r.get("apodo") or ""] + list(r.get("tambien") or [])
    except Exception:  # noqa: BLE001
        pass
    v += ["U-Cursos", "evaluaciones", "estado de la red", "internet", "recuérdame", "temporizador", "recordatorio",
          "alarma", "sin leer", "auxiliar", "WhatsApp", "Canvas", "Telegram"]
    return [x for x in dict.fromkeys(x.strip() for x in v) if x]


def motor_parakeet(vocab):
    import atlas_stt

    if not atlas_stt.available():
        raise RuntimeError("Parakeet no está instalado")
    m = atlas_stt.Parakeet(vocab, log=lambda *_a: None)
    return lambda ruta: m.transcribe(Path(ruta).read_bytes())


def motor_whisper(vocab, device: str, compute: str):
    from faster_whisper import WhisperModel

    m = WhisperModel("large-v3-turbo", device=device, compute_type=compute)
    prompt = "Conversación con Atlas, asistente personal. Vocabulario: " + ", ".join(vocab) + "."

    def f(ruta):
        kw = {"initial_prompt": prompt[:1500], "vad_filter": True, "beam_size": 5, "language": "es"}
        try:
            if len(prompt) > 600:
                raise TypeError
            segs, _ = m.transcribe(str(ruta), hotwords=", ".join(vocab), **kw)
        except TypeError:
            segs, _ = m.transcribe(str(ruta), **kw)
        return "".join(s.text for s in segs).strip()
    return f


def main() -> int:
    meta_f = AUDIOS / "meta.json"
    if not meta_f.exists():
        print("No hay grabaciones. Primero use Grabar-pruebas-voz.cmd.")
        return 1
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    vocab = vocabulario()
    print(f"{len(meta)} grabaciones, {len(vocab)} palabras propias.\n")
    candidatos = [("Parakeet (hoy)", lambda: motor_parakeet(vocab)),
                  ("Whisper turbo en procesador", lambda: motor_whisper(vocab, "cpu", "int8")),
                  ("Whisper turbo en tarjeta gráfica", lambda: motor_whisper(vocab, "cuda", "float16"))]
    tabla, lineas = [], []
    for nombre, crear in candidatos:
        print(f"Cargando {nombre}…", flush=True)
        try:
            t0 = time.time()
            motor = crear()
            motor(AUDIOS / meta[0]["file"])  # calentar: la primera pasada siempre es más lenta
            carga = time.time() - t0
        except Exception as exc:  # noqa: BLE001
            print(f"  no se pudo: {type(exc).__name__}: {str(exc)[:200]}\n")
            lineas.append(f"\n== {nombre}: no se pudo cargar ({type(exc).__name__}: {str(exc)[:200]})")
            continue
        err = pal = claves_ok = claves = exactas = 0
        seg = 0.0
        lineas.append(f"\n== {nombre}")
        for m in meta:
            t0 = time.time()
            try:
                txt = motor(AUDIOS / m["file"])
            except Exception as exc:  # noqa: BLE001
                txt = f"(error {type(exc).__name__})"
            seg += time.time() - t0
            ref, hip = plano(m["ref"]), plano(txt)
            if ref and ref[0] == "atlas" and (not hip or hip[0] != "atlas"):
                ref = ref[1:]  # la persona puede no decir «Atlas» antes
            e = errores(ref, hip)
            err, pal, exactas = err + e, pal + len(ref), exactas + (e == 0)
            for k in m.get("keys") or []:
                claves += 1
                claves_ok += " ".join(plano(k)) in " ".join(hip)
            lineas.append(f"  [{'ok' if e == 0 else str(e) + ' err'}] dijo: {m['ref']}\n         oyó:  {txt}")
        n = len(meta)
        tabla.append((nombre, 100 * err / max(pal, 1), exactas, n, claves_ok, claves, seg / n, carga))
        print(f"  errores {100 * err / max(pal, 1):.1f} %, {seg / n:.2f} s por frase\n", flush=True)
    out = ["Comparación de reconocedores de voz  " + time.strftime("%Y-%m-%d %H:%M"), "",
           f"{'Reconocedor':34} {'Palabras erradas':>17} {'Frases perfectas':>17} {'Palabras clave':>15} {'Seg/frase':>10} {'Carga s':>8}"]
    for nombre, wer, ex, n, ck, c, s, carga in tabla:
        out.append(f"{nombre:34} {wer:16.1f}% {f'{ex} de {n}':>17} {f'{ck} de {c}':>15} {s:10.2f} {carga:8.1f}")
    texto = "\n".join(out + lineas) + "\n"
    (HERE / "resultado_comparacion.txt").write_text(texto, encoding="utf-8")
    print("\n".join(out))
    print("\nDetalle en hud\\pruebas_voz\\resultado_comparacion.txt. Avísale a Claude que ya terminó.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

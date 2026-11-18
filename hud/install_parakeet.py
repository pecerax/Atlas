"""Instala el reconocimiento de voz Parakeet para Atlas (una sola vez). Descarga ~490 MB.

Deja el modelo en Atlas/voices/parakeet-v3 y activa {"stt_model": "parakeet"} en hud/ajustes.json.
Para volver al reconocimiento anterior basta borrar esa línea de ajustes.json (o pedírselo a Claude).
"""

import json
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
import atlas_stt as stt  # noqa: E402

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
WANTED = set(stt.FILES) | {"es.wav"}


def download(dest: Path) -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": "Atlas-HUD (instalador)"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if time.time() - last > 1:
                last = time.time()
                pct = f"{done * 100 // total}%" if total else ""
                print(f"\r  descargado {done // (1 << 20)} MB de {total // (1 << 20) or '?'} MB {pct}   ", end="", flush=True)
    print()


def main() -> None:
    print("=== Instalar reconocimiento de voz Parakeet ===\n")
    try:
        import sherpa_onnx  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"Falta el componente sherpa-onnx ({exc}).")
        print("Cierre esta ventana y vuelva a ejecutar Instalar-parakeet.cmd; si se repite, avise.")
        return
    stt.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not all((stt.MODEL_DIR / f).exists() for f in stt.FILES):
        archive = stt.MODEL_DIR.parent / "parakeet-v3.tar.bz2"
        print("1/3 Descargando el modelo (unos 490 MB)...")
        download(archive)
        print("2/3 Descomprimiendo (puede tardar un par de minutos)...")
        with tarfile.open(archive, "r:bz2") as tar:
            for m in tar:
                name = Path(m.name).name
                if m.isfile() and name in WANTED:
                    src = tar.extractfile(m)
                    with open(stt.MODEL_DIR / name, "wb") as out:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
        archive.unlink(missing_ok=True)
    else:
        print("El modelo ya estaba descargado.")
    if not stt.available():
        print("Algo quedo incompleto: faltan archivos del modelo en", stt.MODEL_DIR)
        return
    print("3/3 Probando...")
    t0 = time.time()
    rec = stt.Parakeet(["Sheena Ringo", "U-Cursos"])
    load = time.time() - t0
    sample = stt.MODEL_DIR / "es.wav"
    if sample.exists():
        t0 = time.time()
        text = rec.transcribe(sample.read_bytes())
        print(f"  Carga: {load:.1f} s. Frase de prueba ({time.time() - t0:.2f} s): {text}")
    cfg_file = HERE / "ajustes.json"
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg["stt_model"] = "parakeet"
    cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nListo: Parakeet quedo activado. Cierre Atlas y vuelva a abrirlo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"\nError: {type(exc).__name__}: {exc}")

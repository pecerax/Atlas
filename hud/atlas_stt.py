"""Reconocimiento de voz alternativo para Atlas: NVIDIA Parakeet TDT 0.6B v3 con sherpa-onnx (solo CPU).

Se activa con hud/ajustes.json: {"stt_model": "parakeet"}. El modelo vive en Atlas/voices/parakeet-v3
(lo descarga Instalar-parakeet.cmd). Si algo falla, Atlas sigue con Whisper como siempre.

El vocabulario propio (artistas, ramos, nombres) se le pasa como "hotwords": palabras a las que se les
sube el puntaje mientras decodifica.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import wave
from pathlib import Path

MODEL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path(__file__).resolve().parent.parent))) / "Atlas" / "voices" / "parakeet-v3"
FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
# Órdenes que conviene que no confunda ("Pon" -> "Con", "Borra" -> "Por"…)
COMMANDS = ["Pon música", "Ponme", "Borra", "Guarda esta canción", "Agéndame", "Agenda", "agendes", "evento",
            "ese mismo", "hackathon", "Ve el estado de la red",
            "Abre", "Marca como leídos", "mail", "mails", "Resume", "Recuérdame", "Mueve", "Cancela", "Atlas"]
HOTWORD_SCORE = 2.5
MERGE_PASSES = False  # True: además compara con una pasada sin vocabulario (más lento, en pruebas no ayudó)


def available() -> bool:
    if not all((MODEL_DIR / f).exists() for f in FILES):
        return False
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _clean_hotwords(words: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        w = re.sub(r"\s+", " ", str(w)).strip()
        # sherpa-onnx interpreta / : # @ como sintaxis, y el modelo solo conoce letras latinas
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]{2,40}", w):
            continue
        for v in (w, w[:1].upper() + w[1:]):  # como viene y con mayúscula inicial
            if v not in out:
                out.append(v)
    return out


def _norm_word(w: str) -> str:
    import unicodedata

    w = "".join(c for c in unicodedata.normalize("NFD", w.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", w)


def _trim_noise(a, sr: int, margin: float = 0.25):
    """Recorta lo de antes de la primera y después de la última zona con voz (mismo umbral que la grabación de Atlas).
    Un clic suelto (< 0,1 s) no cuenta como voz."""
    import numpy as np

    f = int(sr * 0.02)
    n = len(a) // f
    if n < 10:
        return a
    rms = np.sqrt(np.mean(a[: n * f].reshape(n, f) ** 2, axis=1))
    loud = rms > (500 / 32768)
    # voz = al menos 5 tramos de 20 ms seguidos sobre el umbral (descarta clics de tecla)
    run = np.convolve(loud.astype(int), np.ones(5, dtype=int), mode="same") >= 5
    idx = np.flatnonzero(run)
    if not len(idx):
        return a
    m = int(margin / 0.02)
    s, e = max(0, idx[0] - 2 - m), min(n, idx[-1] + 3 + m)
    return a[s * f: e * f]


def dedupe_vocab(text: str, hotset: set[str]) -> str:
    """'Historia Historia' / 'evento evento evento' -> una vez (solo palabras del vocabulario repetidas seguidas)."""
    out: list[str] = []
    for w in text.split():
        if out and _norm_word(w) and _norm_word(w) == _norm_word(out[-1]) and _norm_word(w) in hotset:
            out[-1] = w
            continue
        out.append(w)
    return " ".join(out)


def merge_passes(hot: str, plain: str, hotset: set[str]) -> str:
    """Junta la pasada con vocabulario (hot) y la sin vocabulario (plain), palabra por palabra:
    - lo que coincide o lo que el vocabulario corrigió (reemplazos) se toma de hot;
    - palabras que solo aparecen en hot y son todas del vocabulario se descartan (inventadas en el ruido);
    - palabras que solo aparecen en plain se agregan (el vocabulario se las "comió")."""
    import difflib

    hw, pw = hot.split(), plain.split()
    if not hw:
        return plain
    if not pw:
        return hot
    hn, pn = [_norm_word(w) for w in hw], [_norm_word(w) for w in pw]
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, hn, pn, autojunk=False).get_opcodes():
        if tag == "equal":
            out += hw[i1:i2]
        elif tag == "delete":  # solo en hot
            if not all(t in hotset or not t for t in hn[i1:i2]):
                out += hw[i1:i2]
        elif tag == "insert":  # solo en plain
            out += pw[j1:j2]
        else:  # replace: el vocabulario corrigió algo; gana hot
            out += hw[i1:i2]
    return dedupe_vocab(" ".join(out), hotset)


class Parakeet:
    def __init__(self, vocab: list[str] | None = None, threads: int | None = None, log=print) -> None:
        self.log = log
        self.threads = threads or max(2, min(8, (os.cpu_count() or 4) // 2))
        self._greedy = None
        self._rec = None
        self._key = ""
        self._hotset: set[str] = set()
        self.set_vocab(vocab or [])

    def _build(self, **extra):
        import sherpa_onnx

        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(MODEL_DIR / "encoder.int8.onnx"), decoder=str(MODEL_DIR / "decoder.int8.onnx"),
            joiner=str(MODEL_DIR / "joiner.int8.onnx"), tokens=str(MODEL_DIR / "tokens.txt"),
            model_type="nemo_transducer", num_threads=self.threads, **extra)

    def set_vocab(self, vocab: list[str]) -> None:
        """(Re)arma el reconocedor con el vocabulario dado; no hace nada si no cambió."""
        hot = _clean_hotwords(COMMANDS + list(vocab))
        key = hashlib.sha1("\n".join(hot).encode("utf-8")).hexdigest()
        if key == self._key and self._rec is not None:
            return
        self._key = key
        try:
            bpe = MODEL_DIR / "bpe.vocab"
            if not bpe.exists():  # mismo orden que el tokenizador del modelo; el puntaje es -id
                lines = [ln.rstrip("\n").rsplit(" ", 1) for ln in (MODEL_DIR / "tokens.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
                bpe.write_text("".join(f"{t}\t{-int(i)}\n" for t, i in lines), encoding="utf-8")
            hot_file = MODEL_DIR / "hotwords.txt"
            hot_file.write_text("\n".join(hot) + "\n", encoding="utf-8")
            self._rec = self._build(decoding_method="modified_beam_search", max_active_paths=4,
                                    hotwords_file=str(hot_file), hotwords_score=HOTWORD_SCORE,
                                    modeling_unit="bpe", bpe_vocab=str(bpe))
            self.hotwords = len(hot)
            self._hotset = {_norm_word(t) for w in hot for t in w.split()}
        except Exception as exc:  # noqa: BLE001
            self.log(f"Parakeet: no pude activar el vocabulario propio ({exc}); sigo sin él")
            self._rec = self._build(decoding_method="greedy_search")
            self._greedy = self._rec
            self.hotwords = 0

    @staticmethod
    def _samples(wav_bytes: bytes):
        import numpy as np

        with wave.open(io.BytesIO(wav_bytes)) as w:
            sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width != 2:
            raise ValueError("audio no es de 16 bits")
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        a = _trim_noise(a, sr)  # el ruido/clic antes y después de la voz es donde el vocabulario inventa palabras
        pad = np.zeros(int(sr * 0.5), dtype=np.float32)  # medio segundo de silencio: sin esto recorta órdenes cortas
        return sr, np.concatenate([pad, a, pad]), len(a) / sr

    def _decode(self, rec, sr, samples) -> str:
        s = rec.create_stream()
        s.accept_waveform(sr, samples)
        rec.decode_stream(s)
        return (s.result.text or "").strip()

    def transcribe(self, wav_bytes: bytes) -> str:
        sr, samples, seconds = self._samples(wav_bytes)
        text = self._decode(self._rec, sr, samples)
        if not self.hotwords:
            return text
        # El vocabulario propio a veces inventa nombres en el ruido ("La U Historia Historia Abre mi Historia"):
        # el ruido de antes y después ya se recortó en _samples; aquí se quitan las repeticiones de nombres.
        if MERGE_PASSES:
            if self._greedy is None:
                self._greedy = self._build(decoding_method="greedy_search")
            plain = self._decode(self._greedy, sr, samples)
            merged = merge_passes(text, plain, self._hotset)
            if merged != text:
                self.log(f"Parakeet: con vocabulario {text!r}, sin vocabulario {plain!r} -> {merged!r}")
            return merged
        out = dedupe_vocab(text, self._hotset)
        # Con vocabulario propio a veces se "come" parte del audio: si salió muy poco texto, repetir sin él.
        if seconds >= 2.5 and len(out.split()) < seconds * 0.7:
            if self._greedy is None:
                self._greedy = self._build(decoding_method="greedy_search")
            plain = self._decode(self._greedy, sr, samples)
            if len(plain.split()) > len(out.split()):
                self.log(f"Parakeet: usé la pasada sin vocabulario ({len(out.split())} -> {len(plain.split())} palabras)")
                out = plain
        if out != text:
            self.log(f"Parakeet: {text!r} -> {out!r}")
        return out

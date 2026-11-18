"""Primer inicio de Atlas: el asistente corto que se abre sobre la HUD después del instalador.

El instalador deja ~/.atlas/primer_inicio.json = {"pendiente": true, "saltados": [...cuentas que se saltaron...]}.
La HUD muestra cuatro pantallas (saludo, micrófono, voz, listo); al terminar o al «Saltar todo» queda pendiente=false
y no vuelve a aparecer. La voz elegida se guarda en voz.json (atlas_voz la lee en cada frase).
Nada de esto guarda audio ni datos personales.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVO = Path(os.environ.get("ATLAS_DATOS") or (Path.home() / ".atlas")) / "primer_inicio.json"
VOZ_JSON = HERE / "voz.json"
FRASE = "Hola, soy Atlas. Así le voy a hablar. Mañana a las 8:30 tiene clases."

# Las voces que se ofrecen (la de Kokoro solo si está instalada; las demás son archivos de Piper en voices\)
VOCES = [
    {"id": "davefx_afinada", "nombre": "Dave", "detalle": "Español de España", "archivo": "es_ES-davefx-medium.onnx"},
    {"id": "mx_ald", "nombre": "Ald", "detalle": "Español de México", "archivo": "es_MX-ald-medium.onnx"},
    {"id": "mx_claude", "nombre": "Claude", "detalle": "México, más nítida", "archivo": "es_MX-claude-high.onnx"},
    {"id": "k6b_tramos", "nombre": "K6b", "detalle": "Más natural, más lenta en PCs sin tarjeta gráfica", "archivo": None},
]
CUENTAS = {"ucursos": "U-Cursos", "canvas": "Canvas", "correo": "el correo", "calendario": "Google Calendar",
           "hermes": "Hermes (gastos del banco)", "cronos": "Cronos"}


def _leer() -> dict:
    try:
        d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _kokoro_listo() -> bool:
    try:
        import importlib.util

        if importlib.util.find_spec("kokoro") is None:
            return False
    except Exception:  # noqa: BLE001
        return False
    hf = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface")) / "hub"
    return (hf / "models--hexgrad--Kokoro-82M").is_dir()


def voces() -> list[dict]:
    import atlas_voz

    out = []
    for v in VOCES:
        ok = _kokoro_listo() if v["archivo"] is None else (atlas_voz.VOICES_DIR / v["archivo"]).exists()
        if ok:
            out.append({k: v[k] for k in ("id", "nombre", "detalle")})
    return out


def estado() -> dict:
    """Lo que necesita la HUD para decidir si abre el asistente y qué mostrar."""
    import atlas_voz

    d = _leer()
    saltados = [c for c in d.get("saltados") or [] if c in CUENTAS]
    return {"pendiente": bool(d.get("pendiente")), "saltados": [CUENTAS[c] for c in saltados],
            "voces": voces(), "activa": atlas_voz.activa(), "frase": FRASE}


def elegir_voz(perfil: str) -> dict:
    import atlas_voz

    if perfil not in atlas_voz.PERFILES or perfil not in {v["id"] for v in voces()}:
        return {"ok": False, "error": "Esa voz no está instalada."}
    try:
        cfg = json.loads(VOZ_JSON.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg["activa"] = perfil
    cfg["_opciones"] = list(atlas_voz.PERFILES)
    tmp = VOZ_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, VOZ_JSON)
    return {"ok": True, "activa": perfil}


def muestra(perfil: str) -> bytes:
    """WAV con la frase de prueba en esa voz (no cambia la voz activa)."""
    import atlas_voz

    if perfil not in {v["id"] for v in voces()}:
        return b""
    return atlas_voz.wav(FRASE, perfil)


def terminar(como: str = "listo") -> dict:
    d = _leer()
    d["pendiente"] = False
    d["terminado"] = time.strftime("%Y-%m-%d %H:%M")
    d["como"] = como if como in ("listo", "saltado") else "listo"
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARCHIVO)
    return {"ok": True}

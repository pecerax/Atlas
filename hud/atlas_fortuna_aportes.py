"""Aportes que el usuario anota a mano en Fortuna (mis_fondos.html), guardados en un archivo propio (18-11-2026).

Antes vivían solo en el localStorage de la página: un reinicio brusco de la ventana de Atlas dañó el log de Edge y se
perdió un aporte. Ahora la fuente es ~/.atlas/fortuna_aportes.json (con .bak de la versión anterior); el localStorage
queda como copia. Ninguna actualización de Fortuna (actualizar_fondos.py, botón Actualizar) toca este archivo.
Lo usan hud_server.py (/acceso/fortuna/aportes, dentro de Atlas) y FondosMutuos\\servidor_actualizar.py
(/aportes, cuando la página se abre sola como archivo). Solo este PC.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path

ARCHIVO = Path(os.environ.get("ATLAS_FORTUNA_APORTES") or (Path.home() / ".atlas" / "fortuna_aportes.json"))
MAX = 500
_LOCK = threading.Lock()
_NOTA = ("Aportes anotados a mano en Fortuna (mis_fondos.html, pestaña «Mis inversiones»). key = RUN-serie del fondo; "
         "amount = pesos; date = AAAA-MM-DD. La página lo lee y escribe; ninguna actualización lo reescribe.")


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError("número inválido")
    return v


def limpiar(lista) -> list[dict]:
    """Valida lo que manda la página. Lanza ValueError si algo no calza."""
    if not isinstance(lista, list) or len(lista) > MAX:
        raise ValueError("lista inválida")
    out = []
    for h in lista:
        if not isinstance(h, dict):
            raise ValueError("aporte inválido")
        key, date, amount = h.get("key"), h.get("date"), _num(h.get("amount"))
        if not isinstance(key, str) or not re.fullmatch(r"[\w.-]{1,40}", key):
            raise ValueError("fondo inválido")
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("fecha inválida")
        if amount is None or not 0 < amount < 1e13:
            raise ValueError("monto inválido")
        out.append({"key": key, "amount": amount, "date": date,
                    "target": _num(h.get("target")), "stop": _num(h.get("stop"))})
    return out


def leer(path: Path | None = None) -> dict:
    """{"existe": bool, "aportes": [...]}. Si el archivo está dañado, prueba con el .bak."""
    p = path or ARCHIVO
    for f in (p, p.with_name(p.name + ".bak")):
        try:
            return {"existe": True, "aportes": limpiar(json.loads(f.read_text(encoding="utf-8")).get("aportes", []))}
        except FileNotFoundError:
            continue
        except (OSError, ValueError, AttributeError):
            continue
    return {"existe": False, "aportes": []}


def guardar(lista, path: Path | None = None) -> dict:
    p = path or ARCHIVO
    aportes = limpiar(lista)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            shutil.copy2(p, p.with_name(p.name + ".bak"))
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"_nota": _NOTA, "actualizado": time.strftime("%Y-%m-%dT%H:%M:%S"), "aportes": aportes},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
    return {"ok": True, "existe": True, "aportes": aportes}


def http(metodo: str, cuerpo: bytes = b"", path: Path | None = None) -> tuple[int, dict]:
    """GET -> lo guardado. POST {"aportes": [...]} -> reemplaza la lista completa."""
    if metodo == "GET":
        return 200, {"ok": True, **leer(path)}
    try:
        data = json.loads(cuerpo or b"{}")
        return 200, guardar(data.get("aportes") if isinstance(data, dict) else None, path)
    except (ValueError, OSError) as exc:
        return 400, {"ok": False, "error": str(exc)[:120]}

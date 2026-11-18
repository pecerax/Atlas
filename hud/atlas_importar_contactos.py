"""Importar contactos del teléfono a la libreta de Atlas, uno por uno y solo con la elección del usuario.

Fuente: la copia local que guarda Enlace Móvil (Phone Link) de los contactos del celular vinculado
(%LOCALAPPDATA%\\Packages\\Microsoft.YourPhone_8wekyb3d8bbwe\\LocalCache\\Indexed\\<id>\\System\\Database\\contacts.db).
Se lee una copia temporal (la base está en uso y sus datos recientes viven en el archivo -wal), sin modificar nada.

No agrega nada por su cuenta: la pestaña CONTACTOS muestra cada candidato con Añadir / Saltar.
Los saltados quedan en hud/contactos_saltados.json para no volver a preguntar; los que ya están en la libreta
(mismo número o mismo nombre) no aparecen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import atlas_contactos as C

HERE = Path(__file__).resolve().parent
SKIPPED = HERE / "contactos_saltados.json"
PHONE_LINK = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / "Microsoft.YourPhone_8wekyb3d8bbwe" / "LocalCache" / "Indexed"


def source_db() -> Path | None:
    """La contacts.db más reciente de Enlace Móvil (una carpeta por celular vinculado)."""
    found = sorted(PHONE_LINK.glob("*/System/Database/contacts.db"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if PHONE_LINK.is_dir() else []
    return found[0] if found else None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def read_phone(db: Path | None = None) -> list[dict]:
    """-> [{"pid", "nombre", "telefonos": [...]}] de la copia de Enlace Móvil, ordenados por nombre."""
    db = db or source_db()
    if not db:
        raise FileNotFoundError("No encontré los contactos de Enlace Móvil en este PC.")
    with tempfile.TemporaryDirectory(prefix="atlas_ct_") as tmp:
        for suf in ("", "-wal", "-shm"):
            src = Path(str(db) + suf)
            if src.exists():
                shutil.copy2(src, Path(tmp) / ("contacts.db" + suf))
        con = sqlite3.connect(Path(tmp) / "contacts.db")
        try:
            rows = con.execute("select contact_id, coalesce(display_name, ''), coalesce(nickname, '') from contact").fetchall()
            phones: dict[int, list[str]] = {}
            for cid, num, shown in con.execute("select contact_id, phone_number, display_phone_number from phonenumber"):
                v = (shown or num or "").strip()
                if v and _digits(v) not in {_digits(x) for x in phones.get(cid, [])}:
                    phones.setdefault(cid, []).append(v)
        finally:
            con.close()
    out = []
    for cid, name, nick in rows:
        name = name.strip() or nick.strip()
        if not name or not phones.get(cid):
            continue
        out.append({"pid": f"pl:{cid}", "nombre": name, "apodo": nick.strip() if nick.strip() != name else "",
                    "telefonos": phones[cid]})
    return sorted(out, key=lambda c: C.plain(c["nombre"]))


def load_skipped() -> set[str]:
    try:
        return set(json.loads(SKIPPED.read_text(encoding="utf-8")).get("saltados") or [])
    except Exception:  # noqa: BLE001
        return set()


def skip(pid: str) -> None:
    s = load_skipped()
    s.add(pid)
    SKIPPED.write_text(json.dumps({"saltados": sorted(s)}, ensure_ascii=False, indent=2), encoding="utf-8")


def _already(c: dict, book: list[dict]) -> bool:
    """¿Ya está en la libreta? Mismo número (últimos 8 dígitos) o mismo nombre."""
    tails = {_digits(t)[-8:] for t in c["telefonos"] if len(_digits(t)) >= 8}
    for b in book:
        bt = _digits(b.get("telefono", ""))
        if len(bt) >= 8 and bt[-8:] in tails:
            return True
        if C.plain(b.get("nombre", "")) == C.plain(c["nombre"]):
            return True
    return False


def candidates(db: Path | None = None) -> dict:
    """Los que faltan por revisar (ni en la libreta ni saltados). -> {"pendientes": [...], "total": n, "ya": n, "saltados": n}"""
    phone = read_phone(db)
    book, skipped = C.load(), load_skipped()
    ya = [c for c in phone if _already(c, book)]
    sk = [c for c in phone if c["pid"] in skipped and c not in ya]
    rest = [c for c in phone if c not in ya and c not in sk]
    return {"pendientes": rest, "total": len(phone), "ya": len(ya), "saltados": len(sk)}


def add(pid: str, nombre: str, telefono: str, apodos: str = "") -> dict:
    """Añade el candidato elegido (con el nombre/apodo que el usuario dejó). El nombre del teléfono suele ser
    el apodo: si el usuario no escribe un nombre completo, el contacto se guarda con el primer apodo como nombre."""
    nombre = nombre.strip() or next((a.strip() for a in apodos.split(",") if a.strip()), "")
    return C.upsert({"nombre": nombre, "telefono": telefono, "apodos": apodos})

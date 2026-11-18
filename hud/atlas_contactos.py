"""Libreta de contactos de Atlas (hud/contactos.json), que el usuario llena a mano desde la pestaña CONTACTOS.

Cada contacto: {"id", "nombre", "apodos": [...], "correo", "telefono", "discord"}. Discord (y más adelante el correo) solo
usan a quien esté aquí: si el nombre no está en la libreta, Atlas lo dice en vez de adivinar.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "contactos.json"
_LOCK = threading.Lock()
FIELDS = ("nombre", "apodos", "correo", "telefono", "discord", "telegram")


def plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w@. -]", " ", s)).strip()


def load() -> list[dict]:
    try:
        data = json.loads(Path(FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in data.get("contactos") or []:
        if isinstance(c, dict) and str(c.get("nombre", "")).strip():
            out.append(clean(c))
    return out


def save(contacts: list[dict]) -> None:
    Path(FILE).write_text(json.dumps({"contactos": contacts}, ensure_ascii=False, indent=2), encoding="utf-8")


def phone_fmt(raw: str) -> str:
    """Un solo formato para todos: celulares chilenos como «+56 9 1234 5678» (vengan con o sin espacios, +56 o
    solo 9 dígitos). Otros números quedan como vienen, sin letras. Para comparar se usan siempre solo los dígitos."""
    t = re.sub(r"[^\d+ ()-]", "", str(raw or "")).strip()[:30]
    d = re.sub(r"\D", "", t)
    if len(d) == 11 and d.startswith("569"):
        d = d[2:]
    if len(d) == 9 and d.startswith("9"):
        return f"+56 9 {d[1:5]} {d[5:]}"
    return t


def clean(c: dict) -> dict:
    apodos = c.get("apodos") or []
    if isinstance(apodos, str):
        apodos = apodos.split(",")
    return {
        "id": str(c.get("id") or "").strip() or f"c{int(time.time() * 1000)}{uuid.uuid4().hex[:4]}",
        "nombre": str(c.get("nombre") or "").strip()[:80],
        "apodos": [a.strip()[:40] for a in apodos if str(a).strip()][:10],
        "correo": str(c.get("correo") or "").strip()[:120],
        "telefono": phone_fmt(c.get("telefono")),
        "discord": str(c.get("discord") or "").strip().lstrip("@")[:60],
        "telegram": re.sub(r"^(?:https?://)?(?:t\.me/)?@?", "", str(c.get("telegram") or "").strip())[:60],
    }


RELATIONS = {"papa": "padre", "papi": "padre", "mama": "madre", "mami": "madre", "viejo": "padre", "vieja": "madre"}


def find(name: str, contacts: list[dict] | None = None) -> list[dict]:
    """Contactos que calzan con como lo dijo el usuario: nombre completo, un apodo o el primer nombre."""
    want = plain(name).lstrip("@")
    if not want:
        return []
    contacts = load() if contacts is None else contacts
    exact = [c for c in contacts if want == plain(c.get("nombre", "")) or want in (plain(a) for a in c.get("apodos") or [])
             or (c.get("discord") and want == plain(c["discord"])) or (c.get("telegram") and want == plain(c["telegram"]))]
    if exact:
        return exact
    # «mi padre» -> «padre» (uso real: «a mi padre» sonaba parecido a «madre» y preguntaba entre los dos);
    # «papá» -> «padre», «mamá» -> «madre» (antes «papá» caía por sonido en «Pp Tamia»)
    bare = re.sub(r"^(?:a\s+)?(?:mis?|tus?|su|el|la)\s+", "", want)
    bare = RELATIONS.get(bare, bare)
    if bare != want:
        return find(bare, contacts)
    first = [c for c in contacts if plain(c.get("nombre", "")).split(" ")[0] == want]
    if first:
        return first
    return _sounds_like(want, contacts)


def sound(s: str) -> str:
    """Clave fonética simple para nombres mal transcritos por la voz («Pee pe» -> «pipe», «Chevo» -> «Shego»)."""
    s = plain(s).replace(" ", "")
    s = re.sub(r"^x", "j", s)  # Xavier / Javier
    s = re.sub(r"g(?=[ei])", "j", s)  # Gerardo / Jerardo
    for a, b in (("ph", "f"), ("ee", "i"), ("ll", "y"), ("sh", "s"), ("ch", "s"), ("qu", "k"), ("c", "k"), ("z", "s"),
                 ("v", "b"), ("w", "u"), ("h", ""), ("x", "ks"), ("p", "b"), ("d", "t")):
        s = s.replace(a, b)
    s = re.sub(r"g(?=[aou])", "b", s)  # la voz confunde la g suave con b/v (uso real: «Shego» -> «Chevo»)
    s = re.sub(r"e$", "i", re.sub(r"o$", "u", s))  # vocal final apagada: «Pipi»/«Pipe», «Shegu»/«Shego»
    return re.sub(r"(.)\1+", r"\1", s)


def _sounds_like(want: str, contacts: list[dict]) -> list[dict]:
    """Si nada calza exacto: el único contacto cuyo primer nombre o apodo suena igual (o casi) a lo escuchado."""
    import difflib

    key = sound(want)
    if len(key) < 3:
        return []
    best: dict[str, tuple[float, dict]] = {}
    for c in contacts:
        names = [plain(c.get("nombre", "")).split(" ")[0], plain(c.get("nombre", ""))] + [plain(a) for a in c.get("apodos") or []]
        r = max(difflib.SequenceMatcher(None, key, sound(n)).ratio() for n in names if n)
        if r >= 0.8:
            best[c["id"]] = (r, c)
    if not best:
        return []
    top = max(r for r, _ in best.values())
    # si otro contacto suena casi igual («Mani»: Mane o Mansi) se devuelven ambos y quien llama pregunta «¿cuál?»
    return [c for r, c in sorted(best.values(), key=lambda x: -x[0]) if r >= top - 0.06]


def upsert(contact: dict) -> dict:
    """Agrega o reemplaza (por id) un contacto. -> el contacto guardado."""
    c = clean(contact)
    if not c["nombre"]:
        raise ValueError("Falta el nombre.")
    if c["telefono"] and len(re.sub(r"\D", "", c["telefono"])) < 6:
        raise ValueError("Ese número de teléfono parece incompleto.")
    if c["correo"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c["correo"]):
        raise ValueError("Ese correo no parece válido.")
    with _LOCK:
        contacts = load()
        for i, old in enumerate(contacts):
            if old["id"] == c["id"]:
                contacts[i] = c
                break
        else:
            contacts.append(c)
        contacts.sort(key=lambda x: plain(x["nombre"]))
        save(contacts)
    return c


def delete(cid: str) -> bool:
    with _LOCK:
        contacts = load()
        left = [c for c in contacts if c["id"] != cid]
        if len(left) == len(contacts):
            return False
        save(left)
        return True


def set_discord(name: str, user: str) -> dict:
    """«Benja en Discord es benja_ejemplo»: lo anota en el contacto que calce, o crea uno nuevo."""
    found = find(name)
    if len(found) == 1:
        return upsert({**found[0], "discord": user})
    return upsert({"nombre": name.strip(), "discord": user})

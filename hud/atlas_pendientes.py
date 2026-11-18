"""Lista de pendientes de Atlas (hud/pendientes.json): cosas por hacer SIN fecha ni hora.

«Anota comprar pan como pendiente», «recuérdame hacer la tarea de Redes» (sin día ni hora), «¿qué tengo pendiente?»,
«ya hice lo de comprar pan», «borra el pendiente de comprar pan». Lo que tiene día u hora va a recordatorios o al calendario.
Cada pendiente: {"id", "texto", "creado", "hecho": None | "YYYY-MM-DD HH:MM"}.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "pendientes.json"
_LOCK = threading.Lock()


def plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", s)).strip()


def load() -> list[dict]:
    try:
        data = json.loads(Path(FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return [p for p in data.get("pendientes") or [] if isinstance(p, dict) and str(p.get("texto", "")).strip()]


def save(items: list[dict]) -> None:
    Path(FILE).write_text(json.dumps({"pendientes": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def open_items() -> list[dict]:
    return [p for p in load() if not p.get("hecho")]


def add(texto: str) -> dict:
    texto = texto.strip(" .,;:")
    texto = texto[:1].upper() + texto[1:]
    with _LOCK:
        items = load()
        for p in items:  # el mismo pendiente dos veces: no se duplica
            if not p.get("hecho") and plain(p["texto"]) == plain(texto):
                return p
        p = {"id": f"p{int(time.time() * 1000)}{uuid.uuid4().hex[:4]}", "texto": texto[:200],
             "creado": time.strftime("%Y-%m-%d %H:%M"), "hecho": None}
        items.append(p)
        save(items)
    return p


def find(query: str) -> list[dict]:
    """Pendientes abiertos que calzan con lo dicho: número de la lista («el 2»), texto contenido o parecido."""
    items = open_items()
    q = plain(query)
    q = re.sub(r"^(?:el|la|lo|los|las)\s+(?:de\s+)?|^(?:de|que)\s+", "", q).strip()
    if not q:
        return []
    num = {"uno": 1, "primero": 1, "dos": 2, "segundo": 2, "tres": 3, "tercero": 3, "cuatro": 4, "cuarto": 4, "cinco": 5, "quinto": 5}
    m = re.fullmatch(r"(?:numero\s+)?(\d+|uno|primero|dos|segundo|tres|tercero|cuatro|cuarto|cinco|quinto)", q)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else num[m.group(1)]
        return [items[n - 1]] if 0 < n <= len(items) else []
    hits = [p for p in items if q in plain(p["texto"]) or plain(p["texto"]) in q]
    if hits:
        return hits
    scored = [(difflib.SequenceMatcher(None, q, plain(p["texto"])).ratio(), p) for p in items]
    good = [p for r, p in scored if r >= 0.7]
    return good if len(good) == 1 else []


def set_done(pid: str) -> dict | None:
    with _LOCK:
        items = load()
        for p in items:
            if p["id"] == pid and not p.get("hecho"):
                p["hecho"] = time.strftime("%Y-%m-%d %H:%M")
                save(items)
                return p
    return None


def delete(pid: str) -> dict | None:
    with _LOCK:
        items = load()
        for i, p in enumerate(items):
            if p["id"] == pid:
                items.pop(i)
                save(items)
                return p
    return None


# --------------------------------------------------------------------------- lo que dice el usuario

# día u hora en la frase: entonces no es un pendiente sin fecha (eso es un recordatorio o un evento)
_CUANDO = (r"\b(hoy|manana|pasado|esta (?:noche|tarde|semana)|lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
           r"a las?\s+\w+|en \d+|en (?:un|una|media|cinco|diez|quince|veinte|treinta) (?:minuto|hora|rato)|"
           r"\d{1,2}(?::\d{2})?\s*(?:am|pm|hrs?|horas?)|de la (?:manana|tarde|noche)|al mediodia|el \d{1,2}\b|"
           r"\d{1,2} de \w+|proxim\w+ semana|semana que viene|fin de semana)\b")

_ADD = [
    r"^(?:anota|apunta|agrega|anade|pon|guarda|deja)(?:me)?\s+(?:que\s+)?(?:tengo que\s+|debo\s+)?(?P<x>.+?)\s+(?:como|en (?:mis|la lista de|los)|a (?:mis|la lista de|los))\s+pendientes?$",
    r"^(?:anota|apunta|agrega|anade|pon|guarda)(?:me)?\s+(?:como\s+)?(?:un\s+)?(?:nuevo\s+)?pendiente:?\s+(?:que\s+)?(?:tengo que\s+|debo\s+)?(?P<x>.+)$",
    r"^(?:nuevo\s+)?pendiente:?\s+(?P<x>.+)$",
    r"^(?:recuerdame|acuerdame|hazme acordar|avisame)\s+(?:de\s+|que\s+(?:tengo que|debo)\s+|que\s+)?(?P<x>.+)$",
    r"^(?:tengo pendiente|me queda pendiente|tengo que acordarme de)\s+(?P<x>.+)$",
]
_LIST = (r"^(?:que|cuales?|cuantas?|cuantos?)\s+(?:cosas\s+)?(?:tengo|me quedan?|hay|quedan?)\s+(?:pendientes?|por hacer)\b|"
         r"^(?:dime|muestrame|lee(?:me)?|ensename)\s+(?:mis|los|la lista de)\s+pendientes|"
         r"^(?:mis|la lista de|lista de)\s+pendientes$|^pendientes$|^tengo (?:algo|cosas) pendientes?$|^tengo pendientes$")
_DONE = [
    r"^(?:marca|pon|deja)\s+(?:el pendiente\s+(?:de\s+)?|lo de\s+)?(?P<x>.+?)\s+como\s+(?:hecho|hecha|listo|lista|terminado|terminada|completado|completada)$",
    r"^(?:ya\s+)?(?:hice|termine|complete|acabe|listo)\s+(?:con\s+)?(?:el pendiente\s+(?:de\s+)?|lo de\s+)?(?P<x>.+)$",
    r"^(?:completa|tacha|cierra)\s+(?:el pendiente\s+(?:de\s+)?|lo de\s+)(?P<x>.+)$",
    r"^(?:el pendiente\s+(?:de\s+)?|lo de\s+)(?P<x>.+?)\s+(?:ya\s+)?(?:esta|quedo)\s+(?:listo|lista|hecho|hecha)$",
]
_DEL = r"^(?:borra|quita|elimina|saca|olvida)(?:me)?\s+(?:el|los)\s+pendientes?\s+(?:de\s+|numero\s+)?(?P<x>.+)$|^(?:borra|quita|elimina|saca)\s+(?P<y>.+?)\s+de\s+(?:mis|la lista de|los)\s+pendientes$"


def parse(text: str) -> dict | None:
    """-> {"op": "add"|"list"|"done"|"delete", "x": texto} o None si la frase no es de pendientes."""
    p = plain(text)
    p = re.sub(r"^(?:atlas|jarvis|oye atlas|oye jarvis|por favor)\s+|\s+(?:por favor|gracias)$", "", p).strip()
    if re.search(_LIST, p):
        return {"op": "list"}
    m = re.match(_DEL, p)
    if m:
        return {"op": "delete", "x": m.group("x") or m.group("y")}
    for rx in _DONE:
        m = re.match(rx, p)
        if m:
            return {"op": "done", "x": m["x"]}
    for i, rx in enumerate(_ADD):
        m = re.match(rx, p)
        if not m:
            continue
        x = m["x"].strip()
        if i >= 3 and re.search(_CUANDO, p):  # «recuérdame mañana…»: eso es un recordatorio, no un pendiente
            return None
        if i == 3 and re.match(r"(?:avisar|llamar|escribir)(?:le)?\s+a\b", x) and re.search(_CUANDO, p):
            return None
        # lo dicho, con sus tildes: se busca el mismo tramo en el texto original
        orig = _original_span(text, x)
        return {"op": "add", "x": (orig or x).strip(" .,;:")}
    return None


def _original_span(text: str, plain_part: str) -> str:
    """El trozo del texto original (con tildes y mayúsculas) que corresponde a plain_part."""
    words = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+|[^\w\s]", text)
    want = plain_part.split()
    pw = [plain(w) for w in words]
    for i in range(len(pw)):
        seq = [w for w in pw[i:] if w]
        if seq[:len(want)] == want:
            out, n = [], 0
            for w, q in zip(words[i:], pw[i:]):
                out.append(w)
                n += bool(q)
                if n == len(want):
                    break
            return re.sub(r"\s+([,.;:])", r"\1", " ".join(out))
    return ""


def say_list(items: list[dict]) -> str:
    if not items:
        return "No tiene nada pendiente, señor."
    if len(items) == 1:
        return f"Tiene un pendiente, señor: {items[0]['texto']}."
    lista = "; ".join(f"{i}, {p['texto']}" for i, p in enumerate(items[:10], 1))
    mas = f" Y {len(items) - 10} más en la pantalla." if len(items) > 10 else ""
    return f"Tiene {len(items)} pendientes, señor: {lista}.{mas}"

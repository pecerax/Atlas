"""Tareas (entregas del calendario) que el usuario ya terminó (pedido del usuario, 15-11-2026):
«Las tareas debo poder marcarlas como listas, porque en este caso ya terminé todo lo de Redes».

Una tarea marcada como lista deja de salir en la pestaña TAREAS, en «¿qué tareas tengo?» y en los avisos
(atlas_agenda.upcoming la salta). Se guarda en hud/tareas_listas.json con una clave estable:
ramo|nombre de la tarea|día del plazo. Si el profesor cambia el plazo, la tarea vuelve a aparecer (es otra entrega).

Solo lógica: hud_server.route_tareas pide confirmación y llama a mark()/unmark(); el ✓ de la HUD llama a mark().
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "tareas_listas.json"
_LOCK = threading.Lock()


def plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", s)).strip()


def key(ev: dict) -> str:
    import atlas_agenda as A

    when = ev["when"]
    day = when.date().isoformat() if hasattr(when, "date") else str(when)[:10]
    return f"{plain(A.nick_of(ev.get('course', '')))}|{plain(ev.get('kind') or ev.get('summary', ''))}|{day}"


def name(ev: dict) -> str:
    import atlas_agenda as A

    if ev.get("kind"):
        return f"{ev['kind']} de {A.nick_of(ev.get('course', ''))}".strip()
    return ev.get("summary", "Entrega")


# --------------------------------------------------------------------------- archivo

def load() -> dict:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except (OSError, ValueError):
        data = {}
    return data.get("listas", {}) if isinstance(data, dict) else {}


def _save(items: dict) -> None:
    # se olvidan las de plazo vencido hace más de 60 días (el archivo no crece)
    limit = (datetime.now() - timedelta(days=60)).date().isoformat()
    items = {k: v for k, v in items.items() if k.rsplit("|", 1)[-1] >= limit}
    FILE.write_text(json.dumps({"listas": items}, ensure_ascii=False, indent=1), encoding="utf-8")


def is_done(ev: dict, items: dict | None = None) -> bool:
    try:
        return key(ev) in (load() if items is None else items)
    except Exception:  # noqa: BLE001
        return False


def mark(evs: list[dict]) -> list[str]:
    """Marca como listas. -> nombres de las que se marcaron."""
    with _LOCK:
        items = load()
        out = []
        for ev in evs:
            items[key(ev)] = {"texto": name(ev), "plazo": ev["when"].isoformat(timespec="minutes"),
                              "marcada": datetime.now().strftime("%Y-%m-%d %H:%M")}
            out.append(name(ev))
        _save(items)
        return out


def unmark(keys: list[str]) -> list[str]:
    with _LOCK:
        items = load()
        out = [items.pop(k)["texto"] for k in keys if k in items]
        _save(items)
        return out


# --------------------------------------------------------------------------- lo que dice el usuario

_TASKW = r"(?:tareas?|actividad(?:es)?|entregas?|informes?|trabajos?|hitos?|ejercicios?|laboratorios?|labs?)"
_DONEW = r"(?:listas?|listos?|hechas?|hechos?|terminadas?|terminados?|completadas?|completados?|entregadas?|entregados?|realizadas?)"
_VERB = r"(?:termine|hice|entregue|complete|acabe|subi|mande|envie|ya tengo|tengo listas?)"
_ART = r"(?:(?:todas?|todos?)\s+)?(?:(?:las?|los?|el|mis?)\s+)?"

_DONE = [
    rf"^(?:ya\s+)?{_VERB}\s+(?:con\s+)?{_ART}(?P<x>{_TASKW}\b.*?)(?:\s+(?:ya|tambien))?$",
    rf"^(?:ya\s+)?{_VERB}\s+todo\s+lo\s+(?:de|del ramo de|del curso de)\s+(?P<x>.+)$",
    rf"^(?:marca(?:me)?|pon(?:me)?|deja(?:me)?)\s+(?:como\s+{_DONEW}\s+){_ART}(?P<x>{_TASKW}\b.+)$",
    rf"^(?:marca(?:me)?|pon(?:me)?|deja(?:me)?)\s+{_ART}(?P<x>{_TASKW}\b.+?)\s+como\s+{_DONEW}$",
    rf"^{_ART}(?P<x>{_TASKW}\b.+?)\s+(?:ya\s+)?(?:esta|estan|quedo|quedaron)\s+(?:ya\s+)?{_DONEW}$",
]
_UNDO = [
    rf"^(?:desmarca(?:me)?|quita(?:le)?\s+(?:la marca|lo de lista|el listo)\s+(?:a|de)?)\s*{_ART}(?P<x>{_TASKW}\b.+)$",
    rf"^{_ART}(?P<x>{_TASKW}\b.+?)\s+(?:todavia\s+|aun\s+)?no\s+(?:esta|estan|quedo|quedaron)\s+{_DONEW}$",
    rf"^(?:todavia|aun)\s+no\s+(?:termino|termine|entrego|entregue|hago|hice)\s+{_ART}(?P<x>{_TASKW}\b.+)$",
    rf"^(?:marca(?:me)?|pon(?:me)?|deja(?:me)?)\s+{_ART}(?P<x>{_TASKW}\b.+?)\s+como\s+(?:pendientes?|no\s+{_DONEW})$",
]


def parse(text: str) -> dict | None:
    """-> {"op": "done"|"undo", "x": de qué tarea habla} o None si la frase no es de esto."""
    p = plain(text)
    p = re.sub(r"^(?:atlas|jarvis|oye atlas|oye jarvis|por favor|oye)\s+|\s+(?:por favor|gracias|atlas|jarvis)$", "", p).strip()
    for op, rxs in (("undo", _UNDO), ("done", _DONE)):
        for rx in rxs:
            m = re.match(rx, p)
            if m:
                return {"op": op, "x": m["x"].strip()}
    return None


_NUM = {"uno": "1", "una": "1", "primera": "1", "dos": "2", "segunda": "2", "tres": "3", "tercera": "3", "cuatro": "4",
        "cuarta": "4", "cinco": "5", "quinta": "5", "seis": "6", "sexta": "6", "siete": "7", "septima": "7",
        "ocho": "8", "octava": "8", "nueve": "9", "novena": "9", "diez": "10", "decima": "10"}
_DAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
_FILLER = set("de del la las el los mis mi para que ya todas todos todo lo y e tambien ramo curso este esta esa "
              "semana proxima proximo pasado manana hoy con a en".split())


def _course_terms(ev: dict) -> set[str]:
    import atlas_agenda as A

    course = ev.get("course", "")
    terms = {plain(course), plain(A.nick_of(course))}
    for r in A.load_ramos():
        if plain(r["ramo"]) == plain(course) or plain(r.get("apodo")) == plain(A.nick_of(course)):
            terms |= {plain(x) for x in r.get("tambien", [])} | {plain(r.get("se_dice", ""))}
    return {t for t in terms if len(t) >= 2}


def match(query: str, evs: list[dict]) -> list[dict]:
    """De las entregas `evs`, las que nombra `query` («las tareas de redes», «la actividad 5», «el hito 3 del minor»)."""
    q = " " + plain(query) + " "
    q = re.sub(r"\b(" + "|".join(_NUM) + r")\b", lambda m: _NUM[m.group(1)], q)
    hits = [e for e in evs if any(re.search(rf"\b{re.escape(t)}\b", q) for t in _course_terms(e))]
    rest = q
    for e in hits:
        for t in sorted(_course_terms(e), key=len, reverse=True):
            rest = re.sub(rf"\b{re.escape(t)}\b", " ", rest)
    cands = hits if hits else list(evs)
    day = next((d for w, d in _DAYS.items() if re.search(rf"\b{w}\b", rest)), None)
    for w in _DAYS:
        rest = re.sub(rf"\b{w}\b", " ", rest)
    if day is not None:  # «las del martes»: si calza un día, se usa; si no (se confundió de día), se ignora
        same = [e for e in cands if e["when"].weekday() == day]
        cands = same or cands
    words = [w for w in re.sub(rf"\b{_TASKW}\b", " ", rest).split() if w not in _FILLER]
    if words:
        def has(e):
            k = " " + plain(e.get("kind") or e.get("summary", "")) + " "
            return all(re.search(rf"\b{re.escape(w)}\b", k) for w in words)
        cands = [e for e in cands if has(e)]
    elif not hits:
        return []  # «ya terminé las tareas» sin decir cuáles: no se adivina
    return cands


def say_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]

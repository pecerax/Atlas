"""Agenda de Atlas: lee calendarios iCal (.ics) como el de U-Cursos y responde por evaluaciones y eventos.

Los enlaces van en hud/calendarios.json:
    {"calendarios": [{"nombre": "U-Cursos", "url": "https://..."}]}
Son enlaces privados: quedan solo en este PC. Sirve cualquier calendario que entregue un enlace iCal
(por ejemplo la "dirección secreta en formato iCal" de Google Calendar).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "calendarios.json"
CACHE_SECONDS = 15 * 60
_cache: dict[str, tuple[float, str]] = {}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

# Palabras que delatan una evaluación en el título, la categoría o la descripción corta
EVAL_RE = re.compile(
    r"evaluaci|\bcontrol(es)?\b|ex[aá]men|\bpruebas?\b|certamen|\bquiz|\btest\b|\btareas?\b|\bentregas?\b|"
    r"\bproyectos?\b|presentaci[oó]n|\binformes?\b|solemne|recuperativ|\bc\d\b|\bp\d\b|\bt\d\b|\bmini ?control|"
    r"\bdefensa\b|\bdisertaci|\bejercicios? (evaluad|calificad)", re.I)
# Pendientes propios que nombran una evaluación pero no lo son: "Revisar Controles" (él corrige), "Estudiar para el examen"
CHORE_RE = re.compile(r"^\W*(revisar|corregir|calificar|imprimir|preparar|estudiar|repasar|subir notas|poner notas)\b", re.I)


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


RAMOS = HERE / "ramos.json"

# Tipos de evento de U-Cursos ("Control - Ramo"): cuáles son evaluaciones y cuáles clases
EVAL_KIND_RE = re.compile(r"control|ejercicio|ex[aá]men|prueba|evaluaci|certamen|quiz|test|solemne|recuperativ", re.I)
DELIVERY_KIND_RE = re.compile(r"tarea|entrega|informe|proyecto", re.I)  # fechas de entrega: no son "evaluaciones", pero se avisan
CLASS_KIND_RE = re.compile(r"c[aá]tedra|auxiliar|ayudant|laboratorio|taller|clase", re.I)


def load_ramos() -> list[dict]:
    """Apodos de los ramos (hud/ramos.json): [{"apodo": "Evalua", "ramo": "Formulación, Evaluación…", ...}]"""
    try:
        data = json.loads(RAMOS.read_text(encoding="utf-8")) if RAMOS.exists() else {}
    except Exception:  # noqa: BLE001
        return []
    return [r for r in data.get("ramos", []) if r.get("apodo") and r.get("ramo")]


def is_class(ev: dict) -> bool:
    """Cátedra, auxiliar, etc.: las clases de siempre (no evaluaciones ni entregas)."""
    return bool(ev.get("kind")) and bool(CLASS_KIND_RE.search(ev["kind"])) and not is_evaluation(ev) and not is_delivery(ev)


def is_delivery(ev: dict) -> bool:
    return bool(ev.get("task")) or (bool(ev.get("kind")) and bool(DELIVERY_KIND_RE.search(ev["kind"])))


def i_teach(ev: dict) -> bool:
    """Clases que dicta el propio usuario (ramos.json: "dicto": ["auxiliar"]): esas sí son compromisos suyos.
    "dicto": ["todo"] = todo lo del ramo es parte de su rol (Intro a la Progra: cátedras, controles y auxiliares)."""
    c, k = _plain(ev.get("course", "")), _plain(ev.get("kind", ""))
    for r in load_ramos():
        full = _plain(r["ramo"])
        if r.get("dicto") and (c.startswith(full[:28]) or full.startswith(c[:28]) and len(c) >= 12):
            return "todo" in r["dicto"] or any(_plain(t) in k for t in r["dicto"])
    return False


def teaches_course(course: str) -> bool:
    """¿Es un ramo que el usuario dicta (ramos.json con "dicto")? Las tareas de esos ramos son de sus alumnos, no suyas."""
    c = re.sub(r"^[a-z]{2,4}\d{3,5}(-\d+)?\s+", "", _plain(course).strip())  # "cc1001-1 introduccion…" -> "introduccion…"
    if len(c) < 5:
        return False
    for r in load_ramos():
        full = _plain(r["ramo"])
        if r.get("dicto") and (c.startswith(full[:28]) or full.startswith(c[:28]) and len(c) >= 12 or full in c):
            return True
    return False


def nick_of(course: str) -> str:
    """Apodo del ramo si tiene uno; si no, el nombre (sin lo que viene después de ':')."""
    c = _plain(course)
    for r in load_ramos():
        full = _plain(r["ramo"])
        if c.startswith(full[:28]) or full.startswith(c[:28]) and len(c) >= 12:
            return r["apodo"]
    return course.split(":")[0].strip()


def course_in_text(text: str) -> dict | None:
    """El ramo que nombra una frase, aunque la voz lo haya oído mal (ramos.json: ramo, apodo y «tambien»).

    Uso real 15-11-2026: «¿Queda algún correo de Intro a la Progra sin responder?» llegó como «…de Intras prueba…».
    Calza (1) el nombre o un alias tal cual, (2) un alias parecido (difflib ≥ 0,8), o (3) para alias de dos o más
    palabras largas, las mismas palabras en orden con el mismo comienzo («intr…» … «pr…»: intras prueba ~ intro progra)."""
    import difflib

    words = re.findall(r"[a-z0-9ñ]+", _plain(text))
    joined = " ".join(words)
    best = None
    for r in load_ramos():
        names = [r["ramo"], r["apodo"]] + list(r.get("tambien", []))
        for name in names:
            nw = re.findall(r"[a-z0-9ñ]+", _plain(name))
            if not nw:
                continue
            if re.search(rf"\b{re.escape(' '.join(nw))}\b", joined) and len("".join(nw)) >= 3:
                return r
            big = [w for w in nw if len(w) >= 4]
            if len("".join(nw)) >= 8:  # (2) parecido, en ventanas del mismo largo
                for size in {len(nw) - 1, len(nw), len(nw) + 1} - {0}:
                    for i in range(0, max(0, len(words) - size) + 1):
                        cand = "".join(words[i:i + size])
                        ratio = difflib.SequenceMatcher(None, cand, "".join(nw)).ratio()
                        if ratio >= 0.8 and (best is None or ratio > best[0]):
                            best = (ratio, r)
            if len(big) >= 2:  # (3) mismas palabras largas en orden, con el mismo comienzo
                first, last = big[0], big[-1]
                for i, w in enumerate(words):
                    if w[:4] != first[:4] or abs(len(w) - len(first)) > 3:
                        continue
                    if any(v[:2] == last[:2] and abs(len(v) - len(last)) <= 3 for v in words[i + 1:i + 5]):
                        if best is None or best[0] < 0.79:
                            best = (0.79, r)
    return best[1] if best else None


def load_calendars() -> list[dict]:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    except Exception:  # noqa: BLE001
        return []
    return [c for c in data.get("calendarios", []) if c.get("url") or c.get("archivo")]


def _fetch(cal: dict) -> tuple[str, bool]:
    """-> (texto ics, es_copia_antigua). Guarda una copia local por si después no hay internet.

    Un calendario puede ser un archivo .ics descargado ("archivo": ruta, relativa a la carpeta hud): no se actualiza solo."""
    if not cal.get("url"):
        p = Path(cal["archivo"])
        p = p if p.is_absolute() else HERE / p
        return p.read_text(encoding="utf-8", errors="replace"), False
    url = cal["url"].strip().replace("webcal://", "https://")
    if not url.lower().startswith("https://"):
        raise ValueError("el enlace del calendario debe empezar con https://")
    name = re.sub(r"[^a-z0-9]+", "_", _plain(cal.get("nombre", "cal"))) or "cal"
    backup = HERE / f"agenda_{name}.ics"
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Atlas-HUD (lector de calendario iCal)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read(8_000_000).decode("utf-8", errors="replace")
        if "BEGIN:VCALENDAR" not in text:
            raise ValueError("el enlace no devolvió un calendario (¿venció o hay que iniciar sesión?)")
        _cache[url] = (time.time(), text)
        try:
            backup.write_text(text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return text, False
    except Exception:
        if backup.exists():
            return backup.read_text(encoding="utf-8"), True
        raise


def _unescape(v: str) -> str:
    return (v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\").strip())


def _parse_dt(value: str, params: dict) -> tuple[datetime, bool]:
    """-> (fecha-hora local sin zona, es_todo_el_dia)."""
    v = value.strip()
    if re.fullmatch(r"\d{8}Z?", v):
        return datetime(int(v[:4]), int(v[4:6]), int(v[6:8])), True
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)", v)
    if not m:
        raise ValueError(f"fecha no reconocida: {v}")
    dt = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0))
    if m[7] == "Z":
        return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo

            return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:  # noqa: BLE001  (sin base de zonas: se asume la hora local)
            pass
    return dt, False


def parse_ics(text: str, calendar: str = "") -> list[dict]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events, cur = [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur = {"calendar": calendar, "exdates": set()}
            continue
        if ln == "END:VEVENT":
            if cur and cur.get("start") and cur.get("summary") is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in ln:
            continue
        head, value = ln.split(":", 1)
        name, *plist = head.split(";")
        params = dict(p.split("=", 1) for p in plist if "=" in p)
        name = name.upper()
        try:
            if name == "SUMMARY":
                raw = value.replace("$1", ",")
                title, _, rooms = raw.partition("\\n")
                cur["summary"] = _unescape(title)
                if rooms.strip() and not cur.get("location"):
                    cur["location"] = _unescape(rooms)
                if " - " in cur["summary"]:
                    cur["kind"], cur["course"] = (x.strip() for x in cur["summary"].split(" - ", 1))
                    head, _, last = cur["summary"].rpartition(" - ")
                    mc = re.match(r"([A-Z]{2,}\d{3,4}[A-Z]?)-\d+\s+(.+)$", last.strip())
                    if mc:
                        cur["kind"], cur["course"] = head.strip(), mc.group(2).strip()
                        cur.setdefault("code", mc.group(1))
            elif name == "URL":
                m = re.search(r"/([A-Z]{2,4}\d{3,4}[A-Z]?)/\d+/?$", value.strip()) \
                    or re.search(r"/\d{4}/\d/([A-Z]{2,4}\d{3,4}[A-Z]?)/\d+/", value.strip())
                if m:
                    cur["code"] = m.group(1)
                if "/tareas/" in value:
                    cur["ucursos_tarea"] = True
            elif name == "IMAGE":
                if "servicios/tareas" in value:
                    cur["ucursos_tarea"] = True
            elif name == "DTSTART":
                cur["start"], cur["allday"] = _parse_dt(value, params)
            elif name == "DTEND":
                cur["end"], _ = _parse_dt(value, params)
            elif name == "LOCATION":
                cur["location"] = _unescape(value)
            elif name == "DESCRIPTION":
                cur["description"] = _unescape(value)[:300]
            elif name == "CATEGORIES":
                cur["categories"] = _unescape(value)
            elif name in ("ATTENDEE", "ORGANIZER"):  # personas del evento (para el detalle en la HUD)
                mail = value.split(":", 1)[1] if value.lower().startswith("mailto:") else ""
                cn = _unescape(params.get("CN", "")).strip('"')
                if cn or mail:
                    cur.setdefault("attendees", []).append({"name": cn, "email": mail, "organizer": name == "ORGANIZER"})
            elif name == "RRULE":
                cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "EXDATE":
                for part in value.split(","):
                    cur["exdates"].add(_parse_dt(part, params)[0])
            elif name == "STATUS" and value.strip().upper() == "CANCELLED":
                cur["cancelled"] = True
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"] = _parse_dt(value, params)[0]
        except Exception:  # noqa: BLE001
            continue
    # Una repetición movida o cancelada llega como evento aparte (RECURRENCE-ID): quitar la fecha original
    masters = {e["uid"]: e for e in events if e.get("uid") and e.get("rrule")}
    for e in events:
        if e.get("recurrence_id") and e.get("uid") in masters:
            masters[e["uid"]]["exdates"].add(e["recurrence_id"])
    events = [e for e in events if not e.get("cancelled")]
    courses = {e["code"]: e["course"] for e in events if e.get("code") and e.get("course") and not is_task(e)}
    for e in events:
        _normalize_task(e, courses)
    return events


def is_task(ev: dict) -> bool:
    """Tareas de U-Cursos: llegan como "Otros eventos" con subcategoría "Tareas" (o con "Tarea" en el título)."""
    cats = _plain(ev.get("categories", ""))
    kind = _plain(ev.get("kind", ""))
    summ = _plain(ev.get("summary", ""))
    extra = " ".join(_plain(ev.get(k, "")) for k in ("summary", "description", "location"))
    if ev.get("ucursos_tarea"):
        return True
    return bool(re.search(r"\btareas?\b", cats)
                or (re.search(r"otros? eventos?", kind + " " + cats) and re.search(r"\btareas?\b", extra))
                or re.match(r"tareas?\b", summ))


def _normalize_task(ev: dict, courses: dict) -> None:
    """Deja la tarea con kind = su nombre ("Tarea 3") y course = el ramo, para nombrarla como las demás."""
    if not is_task(ev):
        return
    ev["task"] = True
    if ev.get("ucursos_tarea"):  # U-Cursos: DTSTART = cuándo se publicó, DTEND = plazo de entrega
        if ev.get("end") and ev["end"] > ev["start"]:
            ev["start"] = ev["end"]
        if ev.get("kind") and ev.get("course"):
            ev["kind"] = ev["kind"][:60]
            return
    parts = [x.strip() for x in ev.get("summary", "").split(" - ") if x.strip()]
    parts = [x for x in parts if not re.fullmatch(r"otros? eventos?|tareas?", _plain(x))]  # rótulos de categoría
    title = next((x for x in parts if re.match(r"tareas?\b", _plain(x))), "")
    if not title and re.search(r"\btarea", _plain(ev.get("location", ""))):
        title = ev.pop("location")  # "Otros eventos - Redes\nTarea 2": el nombre venía en la 2.ª línea
    rest = [x for x in parts if x != title]
    ev["kind"] = (title or "Tarea").split(":")[0].strip()[:60] or "Tarea"
    ev["course"] = courses.get(ev.get("code", "")) or (rest[0] if rest else "") or ev.get("calendar", "")


def _occurrences(ev: dict, a: datetime, b: datetime):
    """Fechas de inicio del evento dentro de [a, b), expandiendo repeticiones diarias/semanales."""
    start, rule = ev["start"], ev.get("rrule")
    dur = (ev.get("end") or start) - start
    if rule and rule.get("FREQ") in ("MONTHLY", "YEARLY") and not rule.get("BYDAY"):
        step = 12 if rule["FREQ"] == "YEARLY" else 1
        step *= max(1, int(rule.get("INTERVAL", "1") or 1))
        limit = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else 600
        until = None
        try:
            until = _parse_dt(rule["UNTIL"], {})[0] if rule.get("UNTIL") else None
        except Exception:  # noqa: BLE001
            until = None
        for i in range(limit):
            months = start.month - 1 + i * step
            try:
                cur = start.replace(year=start.year + months // 12, month=months % 12 + 1)
            except ValueError:  # p. ej. día 31 en un mes de 30
                continue
            if cur >= b or (until and cur > until):
                return
            if cur + dur > a and cur not in ev["exdates"]:
                yield cur
        return
    if not rule or rule.get("FREQ") not in ("WEEKLY", "DAILY"):
        if start < b and start + max(dur, timedelta(minutes=1)) > a:
            yield start
        return
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        try:
            until = _parse_dt(rule["UNTIL"], {})[0]
            if len(rule["UNTIL"]) == 8:
                until += timedelta(days=1)
        except Exception:  # noqa: BLE001
            until = None
    n = 0
    if rule["FREQ"] == "DAILY":
        cur = start
        for _ in range(4000):
            if cur >= b or (until and cur > until) or (count is not None and n >= count):
                return
            n += 1
            if cur + dur > a and cur not in ev["exdates"]:
                yield cur
            cur += timedelta(days=interval)
        return
    days = sorted({_BYDAY[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _BYDAY}) or [start.weekday()]
    week = start - timedelta(days=start.weekday())
    for _ in range(600):
        for wd in days:
            cur = datetime.combine((week + timedelta(days=wd)).date(), start.time())
            if cur < start:
                continue
            if cur >= b or (until and cur > until) or (count is not None and n >= count):
                return
            n += 1
            if cur + dur > a and cur not in ev["exdates"]:
                yield cur
        week += timedelta(weeks=interval)


def _split_days(e: dict, a: datetime, b: datetime) -> list[dict]:
    """Un evento largo (de 20 h o más, o de varios días completos) se reparte en un trozo por día dentro de [a, b):
    el primer y el último día con su hora, los del medio (y los que cubre enteros) como «todo el día»."""
    start, end = e["when"], e["when"] + ((e.get("end") or e["start"]) - e["start"])
    if (end - start) < timedelta(hours=20) or (e.get("allday") and end - start <= timedelta(days=1)):
        return [e]
    out, day = [], datetime.combine(start.date(), datetime.min.time())
    while day < end:
        nxt = day + timedelta(days=1)
        s, f = max(start, day), min(end, nxt)
        if f > s and s < b and f > a:
            whole = e.get("allday") or (f - s) >= timedelta(hours=23, minutes=30)
            part = "todo" if whole else ("inicio" if s == start else "fin")
            out.append({**e, "when": s, "start": s, "end": f, "allday": whole, "tramo": part,
                        "span": (start, end, bool(e.get("allday")))})
        day = nxt
    return out or [e]


def upcoming(a: datetime, b: datetime, incluir_listas: bool = False) -> tuple[list[dict], list[str], bool]:
    """-> (eventos ordenados en [a, b), errores por calendario, usando_copia_antigua).
    Las tareas que el usuario marcó como listas (atlas_tareas_listas.py) no salen, salvo con incluir_listas."""
    out, errors, stale = [], [], False
    for cal in load_calendars():
        try:
            text, old = _fetch(cal)
            stale = stale or old
            for ev in parse_ics(text, cal.get("nombre", "")):
                for when in _occurrences(ev, a, b):
                    out.append({**ev, "when": when, "recurring": bool(ev.get("rrule"))})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cal.get('nombre', 'calendario')}: {exc}")
    try:  # Google Calendar conectado con autorización (ver atlas_gcal.py)
        import atlas_gcal

        if atlas_gcal.is_connected():
            for ev in atlas_gcal.list_events(a, b):
                out.append({**ev, "when": ev["start"], "recurring": False, "exdates": set()})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Google Calendar: {exc}")
    out = [seg for e in out for seg in _split_days(e, a, b)]  # lo de varios días: un trozo por cada día
    seen, uniq = set(), []
    done = {}
    if not incluir_listas:
        try:
            import atlas_tareas_listas as TL

            done = TL.load()
        except Exception:  # noqa: BLE001
            done = {}
    for e in sorted(out, key=lambda e: e["when"]):
        if is_delivery(e) and teaches_course(e.get("course", "")):
            continue  # tareas de un ramo que él dicta (p. ej. auxiliar de Introducción a la Programación): no son suyas
        if done and is_delivery(e) and TL.is_done(e, done):
            continue  # ya la terminó (la marcó como lista): no se avisa ni se cuenta como pendiente
        k = (_plain(e["summary"]), e["when"])
        # La misma tarea a veces llega dos veces (dos categorías, dos calendarios, u otra hora el mismo día)
        tk = (("tarea", _plain(nick_of(e.get("course", ""))), _plain(e.get("kind", "")), e["when"].date())
              if is_delivery(e) else None)
        if k not in seen and (tk is None or tk not in seen):
            seen.add(k)
            if tk:
                seen.add(tk)
            uniq.append(e)
    return uniq, errors, stale


def is_evaluation(ev: dict) -> bool:
    if ev.get("task"):  # lo del módulo Tareas (también "Ejercicio Laboratorio") se cuenta como entrega
        return False
    if ev.get("kind"):  # formato U-Cursos: manda el tipo, no el nombre del ramo
        return bool(EVAL_KIND_RE.search(ev["kind"])) and not CLASS_KIND_RE.search(ev["kind"])
    if CHORE_RE.search(ev.get("summary", "")):
        return False
    return bool(EVAL_RE.search(ev.get("summary", "")) or EVAL_RE.search(ev.get("categories", "")))


NOW = None  # las pruebas lo reemplazan por una función que devuelve una fecha fija
_LAST: dict | None = None  # última consulta de agenda, para entender repreguntas ("¿y para redes?")
_TODAY: date | None = None  # "hoy" para armar las frases (lo fija answer)


def say_day(d: date, today: date | None = None) -> str:
    today = today or _TODAY or date.today()
    delta = (d - today).days
    if delta == 0:
        return "hoy"
    if delta == 1:
        return "mañana"
    base = f"el {DIAS[d.weekday()]} {d.day}"
    if d.month != today.month or delta > 25:
        base += f" de {MESES[d.month - 1]}"
    return base


def spoken_name(name: str) -> str:
    """Cómo se dice el nombre de un evento: sin «En Google Calendar» delante y en boca de Atlas
    («Almuerzo con mi padre» -> «Almuerzo con su padre»)."""
    name = re.sub(r"^en google calendar[:,]?\s*", "", name or "", flags=re.I) or name
    name = re.sub(r"\b([Mm])is\b", lambda m: "Sus" if m.group(1) == "M" else "sus", name)
    return re.sub(r"\b([Mm])i\b", lambda m: "Su" if m.group(1) == "M" else "su", name)


def busy_blocks(day: date) -> list[dict]:
    """Lo que ocupa tiempo ese día, con inicio y fin explícitos (sin entregas ni eventos de todo el día).
    -> [{"nombre", "inicio": datetime, "fin": datetime}] ordenado."""
    a = datetime.combine(day, datetime.min.time())
    found, _err, _old = upcoming(a, a + timedelta(days=1))
    out = []
    for e in found:
        if e.get("allday") or is_delivery(e) or e.get("task"):
            continue
        w = e["when"]
        dur = (e["end"] - e["start"]) if e.get("end") and e.get("start") and e["end"] > e["start"] else timedelta(hours=1)
        out.append({"nombre": _event_name(e), "inicio": w, "fin": w + dur})
    return out


def clashes(start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    """Choques de horario calculados (el modelo se equivocaba sumando horas: «Redes 12:00 a 13:30» vs almorzar a la una).
    -> (los que se cruzan con [start, end), todo lo de ese día)."""
    day = busy_blocks(start.date())
    return [b for b in day if b["inicio"] < end and start < b["fin"]], day


def _event_name(e: dict) -> str:
    return f"{e['kind']} de {nick_of(e['course'])}" if e.get("kind") else spoken_name(e["summary"])


def _date_in_text(p: str, day0: datetime) -> list[datetime]:
    """Fechas con número dichas en la frase ya simplificada: «27 de noviembre», «el 23 al 29», «el 27».
    Sin mes: la próxima fecha con ese número (este mes o el siguiente)."""
    out = []
    for m in re.finditer(r"\b(?:(el|del|al)\s+)?(\d{1,2})(?:\s+de\s+(" + "|".join(_plain(x) for x in MESES) + r"))?\b", p):
        if not m.group(1) and not m.group(3):  # «a las 10» no es una fecha
            continue
        n = int(m.group(2))
        if not 1 <= n <= 31:
            continue
        if m.group(3):
            month = [_plain(x) for x in MESES].index(m.group(3)) + 1
            year = day0.year + (1 if month < day0.month - 1 else 0)
            try:
                out.append(datetime(year, month, n))
            except ValueError:
                continue
        else:
            out.append(None)  # se completa con el mes del siguiente número o el más cercano
            out[-1] = n
    # números sueltos: toman el mes del número con mes que venga después («del 23 al 29 de noviembre»)
    res, nxt = [], None
    for x in reversed(out):
        if isinstance(x, datetime):
            nxt = x
            res.append(x)
            continue
        if nxt is not None:
            try:
                res.append(nxt.replace(day=x))
                continue
            except ValueError:
                pass
        for k in range(0, 62):
            dd = day0 + timedelta(days=k)
            if dd.day == x:
                res.append(dd)
                break
    return list(reversed(res))


def say_event(ev: dict, with_place: bool = False, with_day: bool = True) -> str:
    when = ev["when"]
    parts = [_event_name(ev)]
    if with_day:
        parts.append(say_day(when.date()))
    if ev.get("tramo") == "fin":
        parts.append(f"hasta las {ev['end'].hour}:{ev['end'].minute:02d}")
    elif ev.get("tramo") == "inicio":  # empieza hoy y sigue otros días
        fin = ev["span"][1] - (timedelta(minutes=1) if ev["span"][1].time() == datetime.min.time() else timedelta(0))
        parts.append(f"desde las {when.hour}:{when.minute:02d} hasta {say_day(fin.date())}")
    elif not ev.get("allday"):
        parts.append(f"a las {when.hour}:{when.minute:02d}")
    elif ev.get("tramo") == "todo":
        parts.append("todo el día")
    txt = ", ".join(parts[:1]) + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
    if with_place and ev.get("location"):
        txt += f" en {ev['location']}"
    return txt


def _say_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def say_grouped(events: list[dict], one_day: bool = False) -> str:
    """Eventos agrupados para decirlos en voz alta (regla del usuario): los de todo el día juntos por día
    ("el domingo 15 tiene A, B y C, todo el día") y los que coinciden en día y hora juntos
    ("el miércoles 18 a las 23:59 tiene X, Y y Z"). Uno solo se dice como siempre. Grupos separados por "; "."""
    groups: list[tuple[tuple, list[dict]]] = []
    for e in events:
        key = (e["when"].date(), None if e.get("allday") else ("fin", id(e)) if e.get("tramo") == "fin"
               else (e["when"].hour, e["when"].minute))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(e)
        else:
            groups.append((key, [e]))
    out = []
    for (d, hm), evs in groups:
        if len(evs) == 1 and (hm is not None or evs[0].get("tramo") == "todo"):
            out.append(say_event(evs[0], with_place=one_day, with_day=not one_day))
            continue
        names = _say_names([_event_name(e) for e in evs])
        day = "" if one_day else say_day(d)
        if hm is None:
            out.append(f"{day} tiene {names}, todo el día".strip() if day else f"todo el día: {names}")
        else:
            at = f"a las {hm[0]}:{hm[1]:02d}"
            out.append(f"{day} {at} tiene {names}".strip())
    return "; ".join(out)


def parse_range(t: str, now: datetime | None = None) -> tuple[datetime, datetime, str] | None:
    """Rango de fechas pedido en la frase -> (desde, hasta, etiqueta). None si no menciona ninguno."""
    now = now or datetime.now()
    day0 = datetime.combine(now.date(), datetime.min.time())
    p = _plain(t)
    if "pasado manana" in p:
        return day0 + timedelta(days=2), day0 + timedelta(days=3), "pasado mañana"
    if re.search(r"\bmanana\b", p) and not re.search(r"(en|por|de) la manana", p):
        return day0 + timedelta(days=1), day0 + timedelta(days=2), "mañana"
    if re.search(r"\bhoy\b|esta (tarde|noche)|el resto del dia", p):
        return now if re.search(r"resto|queda", p) else day0, day0 + timedelta(days=1), "hoy"
    dates = _date_in_text(p, day0)
    if dates and re.search(r"\bsemana\b", p):  # «la semana del 27 de noviembre»: de lunes a domingo
        mon = dates[0] - timedelta(days=dates[0].weekday())
        return mon, mon + timedelta(days=7), f"la semana del {mon.day} de {MESES[mon.month - 1]}"
    if len(dates) >= 2 and dates[1] > dates[0] and re.search(r"\bal?\b|hasta|entre", p):  # «del 23 al 29»
        a_, b_ = dates[0], dates[1] + timedelta(days=1)
        if (b_ - a_).days <= 62:
            return a_, b_, f"del {dates[0].day} al {dates[1].day} de {MESES[dates[1].month - 1]}"
    if dates and re.search(r"\b(el|del|para el|dia)\s+\d", p):  # «el 27 de noviembre», «el 22»
        d_ = dates[0]
        return d_, d_ + timedelta(days=1), say_day(d_.date(), now.date())
    if re.search(r"(proxima|siguiente|otra) semana|semana (que viene|proxima|siguiente)", p):
        mon = day0 + timedelta(days=7 - day0.weekday())
        return mon, mon + timedelta(days=7), "la próxima semana"
    if re.search(r"esta semana|(resto|queda) de la semana|\bla semana\b|\bsemana\b", p):
        if day0.weekday() >= 5 and not re.search(r"(resto|queda) de la semana", p):
            # sábado o domingo: "esta semana" es la que empieza el lunes (pedido del usuario)
            mon = day0 + timedelta(days=7 - day0.weekday())
            return mon, mon + timedelta(days=7), "la próxima semana"
        return day0, day0 + timedelta(days=7 - day0.weekday()), "esta semana"
    if re.search(r"(proximo|siguiente) mes|mes (que viene|proximo)", p):
        first = (day0.replace(day=1) + timedelta(days=32)).replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1), "el próximo mes"
    if re.search(r"este mes|\bdel mes\b|\bel mes\b", p):
        return day0, (day0.replace(day=1) + timedelta(days=32)).replace(day=1), "este mes"
    for i, name in enumerate(DIAS):
        if re.search(rf"\b{_plain(name)}\b", p):
            num = re.search(rf"\b{_plain(name)}\s+(\d{{1,2}})\b", p)
            if num:  # con número de día: la próxima fecha con ese número (este mes o el siguiente)
                for k in range(0, 62):
                    d = day0 + timedelta(days=k)
                    if d.day == int(num.group(1)):
                        return d, d + timedelta(days=1), say_day(d.date(), now.date())
            delta = (i - day0.weekday()) % 7
            if delta == 0 and re.search(r"proximo|siguiente|que viene", p):
                delta = 7
            d = day0 + timedelta(days=delta)
            return d, d + timedelta(days=1), say_day(d.date(), now.date())
    return None


_KINDS = [  # (palabra en la pregunta, patrón sobre el tipo de evento, plural para hablar)
    (r"\bcontrol(es)?\b", r"control", "controles"),
    (r"\bejercicios?\b", r"ejercicio", "ejercicios"),
    (r"\bexamen(es)?\b", r"examen", "exámenes"),
    (r"\btareas?\b|\bentregas?\b", r"tarea|entrega|informe|proyecto", "entregas"),
    (r"\bauxiliar(es)?\b|\bauxi\b", r"auxiliar", "auxiliares"),
    (r"\bcatedras?\b", r"catedra", "cátedras"),
]
# palabras de nombres de ramos que también son palabras comunes de la pregunta (no sirven para elegir ramo)
_COURSE_STOP = {"sobre", "desde", "entre", "hasta", "perspectiva", "historica", "histo", "evaluacion", "gestion"}


LAST_VIEW: dict | None = None  # lo que la HUD dibuja de la última respuesta (calendario de la semana o lista)


def _people(e: dict) -> list[dict]:
    """Personas del evento, con el nombre de la libreta de contactos cuando calzan (por correo o por nombre)."""
    try:
        import atlas_contactos as C

        book = C.load()
    except Exception:  # noqa: BLE001
        C, book = None, []
    out, seen = [], set()
    for a in e.get("attendees") or []:
        mail, name = str(a.get("email") or "").strip(), str(a.get("name") or "").strip()
        key = (mail or name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        hit = next((c for c in book if mail and c.get("correo", "").lower() == mail.lower()), None)
        if not hit and C and name:
            found = C.find(name, book)
            hit = found[0] if len(found) == 1 else None
        out.append({"nombre": (hit or {}).get("nombre") or name or mail.split("@")[0], "correo": mail,
                    "contacto": bool(hit), "organiza": bool(a.get("organizer"))})
    # los contactos que el usuario asoció a mano («añade a Tipo y Pipe a la reunión»): hud/eventos_contactos.json
    uid = str(e.get("uid") or "")
    gid = e.get("id") or (uid[:-len("@google.com")] if uid.endswith("@google.com") else "")
    if gid:
        try:
            import atlas_avisos as AV

            names = {p["nombre"] for p in out}
            for c in AV.linked({"id": gid, "attendees": []}):
                if c["nombre"] not in names:
                    out.append({"nombre": c["nombre"], "correo": c.get("correo", ""), "contacto": True,
                                "organiza": False, "asociado": True})
        except Exception:  # noqa: BLE001
            pass
    return out[:12]


def _span_text(e: dict) -> str:
    """«vie 20 20:00 → dom 22 23:59» para lo que dura varios días (va en el detalle de la HUD)."""
    if not e.get("span"):
        return ""
    s, f, allday = e["span"]
    if allday:
        f = f - timedelta(days=1)
        return f"{DIAS[s.weekday()][:3]} {s.day} → {DIAS[f.weekday()][:3]} {f.day}"
    return f"{DIAS[s.weekday()][:3]} {s.day} {s:%H:%M} → {DIAS[f.weekday()][:3]} {f.day} {f:%H:%M}"


def _view_item(e: dict) -> dict:
    w = e["when"]
    fin = None
    if not e.get("allday") and e.get("end") and e.get("start") and e["end"] > e["start"]:
        fin = (w + (e["end"] - e["start"])).strftime("%H:%M")
    # tipo para el ícono de la HUD: entrega, evaluacion, auxiliar (la que dicta el usuario), clase, google o evento
    if e.get("task") or is_delivery(e):
        tipo = "entrega"
    elif (is_evaluation(e) or is_class(e)) and i_teach(e):
        tipo = "auxiliar"  # ramo que él dicta (Intro): cátedras, controles y auxiliares son su rol de profesor auxiliar
    elif is_evaluation(e):
        tipo = "evaluacion"
    elif is_class(e):
        tipo = "auxiliar" if i_teach(e) else "clase"
    elif e.get("calendar") == "Google" or str(e.get("uid", "")).endswith("@google.com"):  # su calendario de Google
        tipo = "google"
    else:
        tipo = "evento"
    titulo = f"{e['kind']} de {nick_of(e['course'])}" if e.get("kind") else e.get("summary", "")
    titulo = re.sub(r"^en google calendar[:,]?\s*", "", titulo, flags=re.I) or titulo
    completo = re.sub(r"^en google calendar[:,]?\s*", "", e.get("summary", ""), flags=re.I).strip()
    return {"titulo": titulo, "dia": w.date().isoformat(), "hora": None if e.get("allday") else w.strftime("%H:%M"),
            "fin": fin, "lugar": e.get("location") or "", "tipo": tipo,
            "completo": completo if completo and completo != titulo else "", "curso": e.get("course") or "",
            "nota": (e.get("description") or "")[:200], "personas": _people(e), "periodo": _span_text(e),
            "evento": _clase_evento(e)}


def _clase_evento(e: dict) -> bool:
    """Clase que cuenta como evento (ramos.json "avisar_antes"): sale en la vista EVENTOS del horario, no solo en CLASES.
    Uso real 17-11-2026: «aún no sale el auxiliar en el calendario, aunque Atlas sí lo menciona»."""
    try:
        import atlas_previo as P

        return bool(is_class(e) and P.clase_avisada(e))
    except Exception:  # noqa: BLE001
        return False


def _make_view(found: list[dict], a: datetime, b: datetime, titulo: str) -> dict:
    days = (b.date() - a.date()).days + (1 if b.time() != datetime.min.time() else 0)
    items = [_view_item(e) for e in found[:60]]
    if 2 <= days <= 8:
        try:  # los recordatorios y alarmas locales de esos días también se ven en el calendario (no se dicen)
            import atlas_recordatorios as R

            for r in R.load():
                w = R.when(r)
                if a <= w < b and r.get("tipo") != "temporizador":
                    items.append({"titulo": r.get("texto") or ("Alarma" if r.get("tipo") == "alarma" else "Recordatorio"),
                                  "dia": w.date().isoformat(), "hora": w.strftime("%H:%M"), "fin": None, "lugar": "",
                                  "tipo": "recordatorio"})
        except Exception:  # noqa: BLE001
            pass
        return {"tipo": "calendario", "titulo": titulo, "desde": a.date().isoformat(), "dias": days, "items": items}
    return {"tipo": "lista", "titulo": titulo, "items": items}


_UNTIL = re.compile(r"\b(?:cuanto (?:falta|queda|le queda)|en cuanto (?:tiempo )?(?:es|empieza)|a que hora (?:es|empieza|comienza|parte))"
                    r"\b(?: para)?(?: que (?:empiece|sea|comience))? (.+)$")
_UNTIL_NOUN = r"reunion|junta|cita|evento|control|prueba|examen|certamen|tarea|entrega|clase|auxiliar|catedra|ejercicio"
_UNTIL_DAY = r"\b(?:de |para )?(?:(?:esta|la) (?:tarde|noche|manana)|hoy|pasado manana|manana)\b"
_UNTIL_STOP = {"reunion", "junta", "cita", "evento", "control", "prueba", "examen", "certamen", "tarea", "entrega", "clase",
               "auxiliar", "catedra", "ejercicio", "para", "con", "del", "los", "las", "que", "mis", "esa", "ese",
               "tengo", "tiene", "hoy", "tarde", "noche", "proxima", "proximo", "siguiente"}


def _say_left(delta: timedelta) -> str:
    m = max(0, int(delta.total_seconds() // 60))
    h, m = divmod(m, 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return f"falta{'n' if d > 1 or h else ''} {d} día{'s' if d > 1 else ''}" + (f" y {h} hora{'s' if h != 1 else ''}" if h and d < 3 else "")
    if h == 0:
        return "falta 1 minuto" if m == 1 else f"faltan {m} minutos"
    hs = "1 hora" if h == 1 else f"{h} horas"
    return ("falta " if h == 1 and not m else "faltan ") + hs + (f" y {m} minuto{'s' if m != 1 else ''}" if m else "")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def until(text: str, now: datetime | None = None) -> str | None:
    """«¿Cuánto falta para la reunión de esta tarde?», «¿a qué hora es el control de redes?»: busca ese evento
    (hoy si dice hoy/esta tarde/esta noche) y dice cuánto falta. Uso real 18:53: respondía «no tengo esa cita»."""
    global _TODAY
    now = now or (NOW() if NOW else datetime.now())
    p = re.sub(r"\s+", " ", " " + _plain(re.sub(r"[¿?¡!.,;:]", " ", text)) + " ").strip()
    m = _UNTIL.search(p)
    if not m:
        return None
    rest = m.group(1)
    noun = re.search(rf"\b({_UNTIL_NOUN})", rest)
    day0 = datetime.combine(now.date(), datetime.min.time())
    dm = re.search(_UNTIL_DAY, rest)
    if dm and "pasado" in dm.group(0):
        a, b = day0 + timedelta(days=2), day0 + timedelta(days=3)
    elif dm and re.search(r"\bmanana\b", dm.group(0)) and not re.search(r"(esta|la) manana", dm.group(0)):
        a, b = day0 + timedelta(days=1), day0 + timedelta(days=2)
    elif dm:
        a, b = day0, day0 + timedelta(days=1)
    else:
        a, b = day0, day0 + timedelta(days=60)
    words = [w for w in re.findall(r"[a-z0-9]{3,}", re.sub(_UNTIL_DAY, " ", rest)) if w not in _UNTIL_STOP]
    if not noun and not words:
        return None  # «¿cuánto falta para el viernes?»: eso es de fechas (atlas_basico)
    if not noun and re.fullmatch(r"(?:el |la )?(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|navidad|ano nuevo|"
                                 r"fin de (?:ano|mes|semana)|\d+.*)", rest.strip()):
        return None
    if not load_calendars() and not _gcal_connected():
        return None
    _TODAY = now.date()
    try:
        events = upcoming(a, b)[0]
    except Exception:  # noqa: BLE001
        return None

    def hit(e: dict) -> bool:
        name = _plain(f"{e.get('summary', '')} {e.get('kind', '')} {e.get('course', '')} {nick_of(e.get('course', ''))}")
        if words and not all(re.search(rf"\b{re.escape(w)}", name) for w in words):
            return False
        if noun:  # «el control de redes»: tiene que ser un control (no la cátedra de Redes)
            n = noun.group(1)
            if n in ("reunion", "junta", "cita"):
                return bool(re.search(r"reuni|junta|\bcita|meet|llamada", name))
            if n == "evento":
                return not e.get("kind") and not is_class(e)  # compromisos propios (no lo de U-Cursos)
            if n == "clase":
                return is_class(e) or "clase" in name
            return bool(re.search(n, name)) or (n in ("tarea", "entrega") and bool(e.get("task")))
        return True

    found = [e for e in events if hit(e)]
    if not found and not noun:
        return None  # palabras sueltas que no son ningún evento: que siga el resto
    what = noun.group(1) if noun else "eso"
    what = {"reunion": "reuniones", "cita": "citas", "evento": "eventos", "junta": "juntas", "catedra": "cátedra"}.get(what, what)
    nxt = [e for e in found if e.get("allday") or e["when"] > now]
    if nxt:
        e = nxt[0]
        if e.get("allday"):
            return f"{_cap(_event_name(e))} es {say_day(e['when'].date())}, todo el día, señor."
        return (f"{_cap(_event_name(e))} es {say_day(e['when'].date())} a las {e['when'].hour}:{e['when'].minute:02d}; "
                f"{_say_left(e['when'] - now)}, señor.")
    if found:  # la de hoy ya pasó
        e = found[-1]
        return f"{_cap(_event_name(e))} fue hoy a las {e['when'].hour}:{e['when'].minute:02d}, señor; ya pasó."
    if dm:  # no hay ese día: decir la siguiente
        later = [e for e in upcoming(b, b + timedelta(days=60))[0] if hit(e)]
        when = "hoy" if a == day0 else say_day(a.date())
        if later:
            return f"No tiene {what} {when}, señor. La siguiente es {say_event(later[0])}."
        return f"No tiene {what} {when}, señor, ni en los próximos dos meses."
    de = (" de " + " ".join(words)) if words else ""
    return f"No encuentro ningún {what}{de} en su calendario de los próximos dos meses, señor." if what in (
        "control", "examen", "certamen", "auxiliar", "ejercicio") else \
        f"No encuentro {what}{de} en su calendario de los próximos dos meses, señor."


def answer(text: str, now: datetime | None = None, semana_completa: bool = False) -> str | None:
    """Respuesta hablada a una pregunta de agenda/evaluaciones, o None si la frase no es de este tema.
    semana_completa: «esta semana» va de lunes a domingo, con los días ya pasados (calendario semanal de la HUD,
    pedido del usuario 17-11-2026: un martes mostraba 6 días). La respuesta hablada sigue yendo de hoy al domingo."""
    global _TODAY, _LAST, LAST_VIEW
    if not re.search(r"correo|mail|mensaje|cancion|musica", _plain(text)):
        t_until = until(text, now)
        if t_until:
            LAST_VIEW = None
            return t_until
    LAST_VIEW = None
    now = now or (NOW() if NOW else datetime.now())
    _TODAY = now.date()
    p = " " + _plain(re.sub(r"[¿?¡!.,;:]", " ", text)) + " "
    p = re.sub(r"\s+", " ", p)
    # la voz a veces entiende "tareo"/"tarias" en vez de "tareas" ("¿qué tareo para esta semana?")
    p = re.sub(r"\b(tareos?|tarias?|tareyas?)\b", "tareas", p)
    if re.search(r"correo|mail|consulta|estudiante|mensaje|cancion|musica|volumen|\babr[ei]|\bquien\b|internet|\bla red\b", p):
        return None
    ramos = load_ramos()
    alts = sorted(((_plain(alt), _plain(r["apodo"])) for r in ramos for alt in r.get("tambien", [])), key=lambda x: -len(x[0]))
    for alt, nick in alts:  # formas alternativas de decir el ramo ("e hache" -> "eh", "la progra" -> …)
        if not re.search(rf"(?<!\w){re.escape(nick)}(?!\w)", p):
            p = re.sub(rf"(?<!\w){re.escape(alt)}(?!\w)", nick, p, count=1)
    words = p.split()
    nicks = {_plain(r["apodo"]): r for r in ramos}
    asked_nicks = [n for n in nicks if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", p)]
    want_eval = bool(re.search(r"evaluaci|\bpruebas?\b|certamen|\bquiz", p))
    horario = bool(re.search(r"\bhorario\b", p))  # "mi horario" sí incluye las clases
    kinds = [(rx, plural) for q, rx, plural in _KINDS if re.search(q, p)]
    clases = bool(re.search(r"\bclases?\b", p))
    cue = bool(re.search(r"\bque\b|\bcual|\bcuando\b|proxim|siguiente|\bteng|\bhay\b|\bvien|\btoca|fechas?|pendiente|"
                         r"calendario|agenda|horario|u ?-?cursos|a que hora|\bdonde\b", p))
    general = bool(re.search(r"\b(mi|la|el) (agenda|calendario|horario)\b|u ?-?cursos|"
                             r"\b(reunion(es)?|eventos?|citas?|compromisos?)\b.*\b(hoy|manana|semana|mes|lunes|martes|miercoles|jueves|viernes|sabado|domingo|proxim|siguiente|tengo|hay)\b|"
                             r"\b(tengo|hay|proxim[oa]s?|siguientes?)\b.*\b(reunion(es)?|eventos?|citas?|compromisos?)\b|"
                             r"\b(estoy|tengo) (libre|ocupado)\b|"
                             # "¿Cómo se viene mi semana?", "¿qué tal la próxima semana?", "¿cómo pinta mi lunes?"
                             r"\b(como|que tal)( se)? ?(viene|vienen|ve|pinta|presenta|esta|va|sera)? (mi|la|esta|el|mis) "
                             r"(proxima |siguiente )?(semana|agenda|dia de manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b|"
                             r"que (tengo|hay|me toca|tenemos)( que hacer| agendado| programado)? "
                             r"(hoy|manana|pasado|esta|este|la proxima|el proximo|el lunes|el martes|el miercoles|"
                             r"el jueves|el viernes|el sabado|el domingo)", p))
    by_course = bool(asked_nicks) and bool(re.search(r"\bcuando\b|\bteng|\btoca|a que hora|proxim|\bque hay\b|\bhay\b", p))
    lead = bool(re.match(r" (y|e|o) ", p))  # "¿y para redes?", "y mañana"
    followup = None
    if not (((want_eval or kinds or clases) and cue) or general or by_course):
        # "¿qué tengo de redes esta semana?": ramo dicho por su nombre (hay que mirar el calendario para saberlo)
        by_name = False
        if re.search(r"\b(que|cuando)\b.*\b(tengo|toca|hay)\b", p) and (load_calendars() or _gcal_connected()):
            try:
                near = upcoming(now - timedelta(days=7), now + timedelta(days=30))[0]
            except Exception:  # noqa: BLE001
                near = []
            names = {w for e in near for w in re.findall(r"[a-z]{5,}", _plain(e.get("course", "")))} - _COURSE_STOP
            by_name = any(w in names for w in words)
        if not by_name:
            # Repregunta corta sobre la consulta anterior: "¿y para redes?", "¿y la próxima semana?", "¿y los controles?"
            last = _LAST if _LAST and time.time() - _LAST["t"] < 180 else None
            if not (last and (lead or len(words) <= 5)) or re.search(r"clima|tiempo|temperatura|lluvia|que hora|gracias|"
                                                                   # hechos y precios no son agenda ("¿y el dólar esta semana?")
                                                                   r"dolar|euro|\buf\b|bitcoin|precio|bolsa|noticia|estuvo|como (le )?fue|que paso", p):
                return None
            followup = last
    if not load_calendars() and not _gcal_connected():
        return ("Aún no tengo ningún calendario conectado, señor. Hay que agregar el enlace iCal en el archivo "
                "calendarios.json de la carpeta hud.")

    # ramo nombrado por su nombre ("control de redes", "qué tengo de ciberseguridad")
    try:
        wide = upcoming(now - timedelta(days=7), now + timedelta(days=60))[0]
    except Exception:  # noqa: BLE001
        wide = []
    names = {w for e in wide for w in re.findall(r"[a-z]{5,}", _plain(e.get("course", "")))} - _COURSE_STOP
    asked_words = [] if asked_nicks else list(dict.fromkeys(w for w in words if w in names))

    personal = bool(re.search(r"\breunion(es)?\b|\bcitas?\b|\bcompromisos?\b", p))  # lo que no viene de U-Cursos
    range_src: str | None = text
    inherit_single = False
    if followup:
        new_course = bool(asked_nicks or asked_words)
        new_kind = bool(kinds or want_eval or clases or personal or horario)
        new_rng = parse_range(text, now) is not None
        if not (new_course or new_kind or new_rng) or (new_rng and not (lead or new_course or new_kind) and len(words) > 3):
            return None
        if not new_kind:
            want_eval, kinds, clases, personal, horario = (followup[k] for k in ("want_eval", "kinds", "clases", "personal", "horario"))
        if not new_course:
            asked_nicks, asked_words = list(followup["asked_nicks"]), list(followup["asked_words"])
        if not new_rng:
            range_src = followup["range_text"]
            inherit_single = followup["single"]
    specific = want_eval or bool(kinds) or clases or bool(asked_nicks) or bool(asked_words) or personal
    p_single = re.sub(r"(la |el )?(proxim[oa]|siguiente) (semana|mes)|(semana|mes) (que viene|proxim[oa]|siguiente)|"
                      r"(el )?(proxim[oa]|siguiente) (lunes|martes|miercoles|jueves|viernes|sabado|domingo)", " ", p)  # "el próximo jueves" es un día
    single = bool(re.search(r"\bcuando\b|a que hora|\b(el|la|mi) (proxim|siguiente)|\bproxim[oa]\b|\bsiguiente\b", p_single)) \
        and not re.search(r"evaluaciones|controles|ejercicios|examenes|tareas|auxiliares|catedras|clases|proximos|proximas|reuniones|eventos|citas|compromisos", p)
    single = single or (inherit_single and not re.search(r"evaluaciones|controles|ejercicios|examenes|tareas|auxiliares|catedras|clases|reuniones|eventos", p))
    rng = parse_range(range_src, now) if range_src else None
    day0 = datetime.combine(now.date(), datetime.min.time())
    _LAST = {"t": time.time(), "want_eval": want_eval, "kinds": kinds, "clases": clases, "personal": personal,
             "horario": horario, "asked_nicks": list(asked_nicks), "asked_words": list(asked_words),
             "range_text": range_src if rng else None, "single": single}
    # "¿Qué tareas tengo?": solo la semana que viene (pedido del usuario). "¿Cuál es la próxima tarea?" mira más lejos.
    tasks_week = not rng and not single and bool(kinds) and all(pl == "entregas" for _, pl in kinds)
    only_tasks = bool(kinds) and all(pl == "entregas" for _, pl in kinds)
    finde_esta = (now.weekday() >= 5 and bool(rng) and rng[2] == "la próxima semana"
                  and not re.search(r"(proxima|siguiente|otra) semana|semana (que viene|proxima|siguiente)", p))
    if rng and only_tasks and rng[2] == "esta semana":
        # tareas "de esta semana": los próximos 7 días desde hoy, no hasta el domingo (pedido del usuario)
        a, b, label = now, now + timedelta(days=7), "los próximos 7 días"
    elif rng and only_tasks and finde_esta:
        # fin de semana: la semana que empieza el lunes, sin dejar fuera lo que vence hoy o el domingo
        a, b = now, rng[1]
        label = "el fin de semana y la próxima semana"
    elif rng:
        a, b, label = rng
    elif tasks_week:
        a, b, label = now, now + timedelta(days=7), "los próximos 7 días"
    elif specific:
        a, b, label = now, now + timedelta(days=90), "los próximos tres meses"
    else:
        a, b, label = now, day0 + timedelta(days=2), "hoy y mañana"
    if semana_completa:  # vista semanal de la HUD: siempre lunes a domingo de la semana en curso
        a = day0 - timedelta(days=day0.weekday())
        b, label = a + timedelta(days=7), "esta semana"
    # Toda vista semanal (voz, chat, Telegram) va de lunes a domingo, aunque lo hablado vaya de hoy al domingo.
    # Uso real 17-11-2026: «mi horario» o «qué tengo esta semana» un martes abría la semana sin el lunes.
    vista_semana = not single and not only_tasks and not re.search(r"(resto|queda) de la semana", p) and (
        (rng is not None and rng[2] == "esta semana") or (horario and not rng and not followup))
    # día del que se está hablando ("¿cuál es mi agenda el jueves?"): lo hereda "pon una sesión de X a las 6"
    _LAST["day"] = a.date() if rng and (b - a) <= timedelta(days=1, hours=1) else None

    def pick(events: list[dict]) -> list[dict]:
        evs = events
        if kinds:
            evs = [e for e in evs if any(re.search(rx, _plain(e.get("kind") or e["summary"])) or (pl == "entregas" and e.get("task"))
                                         for rx, pl in kinds)]
        elif want_eval:
            evs = [e for e in evs if is_evaluation(e)]
        elif clases:
            evs = [e for e in evs if is_class(e)]
        elif personal:
            evs = [e for e in evs if not e.get("kind")]
        elif not asked_nicks and not asked_words and not horario:
            # Pregunta general ("¿qué tengo mañana?", "mis eventos"): compromisos, evaluaciones y entregas.
            # Las clases de siempre no se nombran, salvo las que dicta el propio usuario.
            evs = [e for e in evs if not is_class(e) or i_teach(e)]
        if asked_nicks:
            evs = [e for e in evs if _plain(nick_of(e.get("course", ""))) in asked_nicks]
        elif asked_words:
            evs = [e for e in evs if all(w in _plain(e.get("course", "")) for w in asked_words)]
        return evs

    events, errors, stale = upcoming(a, b)
    found = pick(events)
    tail = _tail(errors, stale)
    what = " y ".join(pl for _, pl in kinds) if kinds else ("evaluaciones" if want_eval else ("clases" if clases else "eventos"))
    de = ""
    if asked_nicks:
        de = " de " + " y ".join(nicks[n]["apodo"] for n in dict.fromkeys(asked_nicks))
    elif asked_words:
        hit = next((e for e in wide if all(w in _plain(e.get("course", "")) for w in asked_words)), None)
        de = " de " + (nick_of(hit["course"]) if hit else " ".join(asked_words))
    if vista_semana:
        va = day0 - timedelta(days=day0.weekday())
        vb = va + timedelta(days=7)
        vistos = found if (a, b) == (va, vb) else pick(upcoming(va, vb)[0])
        if vistos:
            LAST_VIEW = _make_view(vistos, va, vb, f"{what[:1].upper() + what[1:]}{de} · esta semana")
    if not found:
        msg = (f"No tiene nada{de} en su calendario para {label}, señor." if what == "eventos"
               else f"No veo {what}{de} para {label} en su calendario, señor.")
        later = pick(upcoming(b, now + timedelta(days=90))[0]) if tasks_week or (only_tasks and label == "los próximos 7 días") else []
        if later:  # nada esta semana: decir cuál es la siguiente
            msg += f" La siguiente es {say_event(later[0])}."
        elif specific and not rng:  # contar cuál fue la última, para que no parezca un error
            past = pick(upcoming(now - timedelta(days=150), now)[0])
            if past:
                last = past[-1]
                days = (now.date() - last["when"].date()).days
                ago = "hoy" if days == 0 else ("ayer" if days == 1 else f"hace {days} días")
                msg += f" Lo último fue {say_event(last, with_day=False)}, {ago}."
        return msg + tail
    if single:
        e = found[0]
        days = (e["when"].date() - now.date()).days
        falta = "es hoy" if days == 0 else ("es mañana" if days == 1 else f"faltan {days} días")
        return f"Lo próximo es {say_event(e, with_place=True)}; {falta}, señor.{tail}"
    one_day = (b - a) <= timedelta(days=1)
    shown = found[:8]
    items = say_grouped(shown, one_day)
    n = len(found)
    if n == 1:
        what = {"controles": "control", "ejercicios": "ejercicio", "exámenes": "examen", "tareas": "tarea",
                "auxiliares": "auxiliar", "cátedras": "cátedra", "evaluaciones": "evaluación", "clases": "clase",
                "entregas": "entrega",
                "eventos": "evento"}.get(what, what)
    head = f"Señor, para {label} veo {n} {what}{de}" + (f"; le nombro {len(shown)} por orden de fecha" if n > len(shown) else "") + ": "
    if not vista_semana:
        LAST_VIEW = _make_view(found, a, b, f"{what[:1].upper() + what[1:]}{de} · {label}")
    return head + items + "." + tail


def _gcal_connected() -> bool:
    try:
        import atlas_gcal

        return atlas_gcal.is_connected()
    except Exception:  # noqa: BLE001
        return False


def _tail(errors: list[str], stale: bool) -> str:
    if errors:
        return " No pude leer el calendario: " + "; ".join(errors)[:160] + "."
    if stale:
        return " Ojo: no pude actualizar el calendario y usé la última copia guardada."
    return ""


def debug_summary(limit: int = 40) -> str:
    """Muestra de títulos y categorías (para ajustar qué cuenta como evaluación)."""
    now = datetime.now()
    events, errors, _ = upcoming(now - timedelta(days=30), now + timedelta(days=120))
    seen, rows = set(), []
    for e in events:
        k = (e["summary"], e.get("categories", ""), e["recurring"])
        if k in seen:
            continue
        seen.add(k)
        rows.append(f"{'R' if e['recurring'] else '-'} {'E' if is_evaluation(e) else '-'} | {e['summary'][:70]} | "
                    f"apodo={nick_of(e.get('course', ''))[:20]} | cat={e.get('categories', '')[:30]}")
    return f"{len(events)} eventos; errores={errors}\n" + "\n".join(rows[:limit])

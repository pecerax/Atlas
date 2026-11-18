"""Recordatorios, temporizadores y alarmas locales de Atlas.

Todo vive en este PC: se guardan en hud/recordatorios.json, así que sobreviven si Atlas se reinicia.
Este módulo solo entiende frases y guarda/lee el archivo; quien avisa a la hora es hud_server.py.

Frases que entiende (ejemplos):
  "recuérdame en 20 minutos sacar la ropa"     -> recordatorio a ahora + 20 min
  "pon un temporizador de 5 minutos"           -> temporizador
  "pon una alarma a las 7 de la mañana"        -> alarma a la próxima 7:00
  "avísame a las 6 que llame a mi mamá"        -> recordatorio a las 18:00 (la próxima 6 que venga)
  "qué recordatorios tengo" / "cuánto le queda al temporizador"
  "cancela el temporizador" / "borra el recordatorio de la ropa" / "cancela todas las alarmas"
"Recuérdame X el lunes a las 9" (con día) sigue yendo a Google Calendar, como antes.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOW = datetime.now  # las pruebas lo reemplazan por una hora fija


def _file() -> Path:
    return HERE / "recordatorios.json"


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# ----------------------------------------------------------------------------- guardar y leer
def load() -> list[dict]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8")) if _file().exists() else {}
        items = [i for i in data.get("pendientes", []) if i.get("cuando")]
    except Exception:  # noqa: BLE001
        return []
    return sorted(items, key=lambda i: i["cuando"])


def save(items: list[dict]) -> None:
    body = {"_nota": "Recordatorios, temporizadores y alarmas pendientes de Atlas. Se pueden borrar a mano.",
            "pendientes": sorted(items, key=lambda i: i["cuando"])}
    _file().write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def when(item: dict) -> datetime:
    return datetime.fromisoformat(item["cuando"])


def add(tipo: str, texto: str, cuando: datetime, dur: int | None = None) -> dict:
    item = {"id": secrets.token_hex(3), "tipo": tipo, "texto": texto, "cuando": cuando.isoformat(timespec="seconds"),
            "creado": NOW().isoformat(timespec="seconds")}
    if dur:
        item["duracion"] = int(dur)
    save(load() + [item])
    return item


def take_due(now: datetime | None = None) -> list[dict]:
    """Saca del archivo los que ya vencieron y los devuelve (para avisar)."""
    now = now or NOW()
    items = load()
    due = [i for i in items if when(i) <= now]
    if due:
        save([i for i in items if when(i) > now])
    return due


def remove(ids: list[str]) -> None:
    save([i for i in load() if i["id"] not in ids])


# ----------------------------------------------------------------------------- cómo se dice
def say_dur(sec: int) -> str:
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} hora{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minuto{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} segundo{'s' if s != 1 else ''}")
    if not parts:
        return "menos de un segundo"
    return " y ".join(parts) if len(parts) <= 2 else f"{parts[0]}, {parts[1]} y {parts[2]}"


def say_clock(dt: datetime, now: datetime | None = None) -> str:
    now = now or NOW()
    hora = f"{dt.hour}:{dt.minute:02d}"
    days = (dt.date() - now.date()).days
    if days == 0:
        return f"a las {hora}"
    if days == 1:
        return f"mañana a las {hora}"
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"el {dias[dt.weekday()]} {dt.day} a las {hora}"


def describe(item: dict, now: datetime | None = None) -> str:
    now = now or NOW()
    t = when(item)
    left = say_dur(max(0, (t - now).total_seconds()))
    if item["tipo"] == "temporizador":
        what = f"temporizador de {say_dur(item.get('duracion') or 0)}" + (f" para {item['texto']}" if item["texto"] else "")
        return f"{what}: le quedan {left}"
    if item["tipo"] == "alarma":
        return f"alarma {say_clock(t, now)}" + (f" ({item['texto']})" if item["texto"] else "")
    return f"«{item['texto'] or 'recordatorio'}» {say_clock(t, now)}, en {left}"


def alert_text(item: dict, late: bool = False) -> str:
    """Lo que Atlas dice cuando vence."""
    t = when(item)
    if late:
        what = {"temporizador": "un temporizador", "alarma": "una alarma"}.get(item["tipo"], "un recordatorio")
        extra = f": {item['texto']}" if item["texto"] else ""
        return f"Señor, mientras estaba cerrado venció {what} de las {t.hour}:{t.minute:02d}{extra}."
    if item["tipo"] == "temporizador":
        return (f"Señor, terminó el temporizador de {say_dur(item.get('duracion') or 0)}"
                + (f" para {item['texto']}" if item["texto"] else "") + ".")
    if item["tipo"] == "alarma":
        return f"Señor, son las {t.hour}:{t.minute:02d}. Su alarma" + (f": {item['texto']}." if item["texto"] else ".")
    return f"Señor, le recuerdo: {item['texto']}." if item["texto"] else "Señor, este es su recordatorio."


# ----------------------------------------------------------------------------- entender frases
_NUM = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
        "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
        "veinte": 20, "veinticinco": 25, "treinta": 30, "cuarenta": 40, "cuarenta y cinco": 45,
        "cincuenta": 50, "sesenta": 60, "noventa": 90}
_NUMRX = "|".join(sorted((re.escape(k) for k in _NUM), key=len, reverse=True))
_UNIT = r"(segundos?|segs?|minutos?|mins?|horas?|hrs?)"
_DUR1 = rf"(?:(\d+(?:[.,]\d+)?|{_NUMRX})\s*{_UNIT}\b(?:\s+y\s+media)?|media\s+hora|un\s+cuarto\s+de\s+hora)"
DUR = rf"{_DUR1}(?:\s*(?:,|y)?\s*{_DUR1})*"


def parse_duration(p: str) -> tuple[int, tuple[int, int]] | None:
    """Duración en segundos dentro del texto (sin tildes, en minúsculas) y dónde está."""
    m = re.search(DUR, p)
    if not m:
        return None
    total = 0.0
    for part in re.finditer(_DUR1, m.group(0)):
        txt = part.group(0)
        if re.match(r"media\s+hora", txt):
            total += 1800
            continue
        if re.match(r"un\s+cuarto", txt):
            total += 900
            continue
        n_raw, unit = part.group(1), part.group(2)
        n = float(n_raw.replace(",", ".")) if n_raw[0].isdigit() else _NUM[n_raw]
        mult = 1 if unit.startswith("seg") else 60 if unit.startswith("min") else 3600
        total += n * mult
        if re.search(r"y\s+media$", txt):
            total += mult / 2
    return (int(total), m.span()) if total > 0 else None


_HOURS = {"cero": 0, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
          "nueve": 9, "diez": 10, "once": 11, "doce": 12}
# "a las 6:38", "para las 0.38", "a las 6 38", "a las 6 horas 38 minutos" (así lo transcribe la voz)
CLOCK = (r"\b(?:a|para)\s+las?\s+(\d{1,2}|" + "|".join(_HOURS) + r")"
         r"(?:\s*(?::|\.|h)\s*(\d{2})|\s+(\d{2})\b|\s+horas?\s+(?:y\s+)?(\d{1,2})(?:\s+minutos?)?\b)?"
         r"(\s+y\s+media|\s+y\s+cuarto|\s+menos\s+cuarto)?"
         r"(\s+de\s+la\s+(?:manana|tarde|noche|madrugada)|\s*(?:am|a\.m\.|pm|p\.m\.)\b|\s+hrs?\b|\s+horas\b)?")


def parse_clock(p: str, now: datetime) -> tuple[datetime, tuple[int, int]] | None:
    m = re.search(CLOCK, p)
    if not m:
        return None
    h = int(m.group(1)) if m.group(1).isdigit() else _HOURS[m.group(1)]
    mi = int(m.group(2) or m.group(3) or m.group(4) or 0)
    extra, qual = (m.group(5) or "").strip(), (m.group(6) or "").strip()
    if h > 23 or mi > 59:
        return None
    if extra == "y media":
        mi = 30
    elif extra == "y cuarto":
        mi = 15
    elif extra == "menos cuarto":
        h, mi = (h - 1) % 24, 45
    pm = bool(re.search(r"tarde|noche|pm|p\.m\.", qual))
    am = bool(re.search(r"manana|madrugada|am|a\.m\.", qual))
    day = now.date()
    tomorrow = bool(re.search(r"(?<!de la )\bmanana\b", p))
    if tomorrow:
        day = day + timedelta(days=1)
    if pm and h < 12:
        h += 12
    elif am and h == 12:
        h = 0
    cands = [h]
    if not (pm or am or qual) and 1 <= h < 12 and not tomorrow:
        cands = [h, h + 12]  # "a las 5" sin más: la próxima 5 que venga (5:00 o 17:00)
    for hh in cands:
        dt = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mi)
        if dt > now:
            return dt, m.span()
    dt = datetime.combine(day, datetime.min.time()).replace(hour=cands[0], minute=mi) + timedelta(days=1)
    return dt, m.span()


_TIMER = r"temporizador(?:es)?|\btimers?\b|cronometro|cuenta regresiva"
_ALARM = r"\balarmas?\b|\bdespiertame\b"
_REMIND = r"recuerdame|recordarme|avisame|acuerdame|hazme acordar|recordatorios?\b"
_NOUN = r"(recordatorios?|temporizador(?:es)?|timers?|alarmas?)"
_DAYWORDS = r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|pasado manana|proxima semana|el \d{1,2}\b|de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre))"


def _kind(p: str) -> str | None:
    if re.search(_TIMER, p):
        return "temporizador"
    if re.search(_ALARM, p):
        return "alarma"
    if re.search(r"recordatorio", p):
        return "recordatorio"
    return None


def _clean_text(original: str, spans: list[tuple[int, int]]) -> str:
    """Lo que hay que recordar: la frase sin la orden ni la hora."""
    chars = list(original)
    for a, b in spans:
        for i in range(a, min(b, len(chars))):
            chars[i] = " "
    t = "".join(chars)
    t = re.sub(r"(?i)^\s*(?:atlas,?\s*)?(?:por favor,?\s*)?(?:(?:me\s+)?(?:puedes|podr[ií]as)\s+)?", "", t)
    t = re.sub(r"(?i)\b(?:recu[eé]rdame|recordarme|av[ií]same|acu[eé]rdame|hazme acordar(?: de)?|"
               r"pon(?:me|er)?|crea(?:r|me)?|programa(?:r|me)?|agrega(?:r|me)?|"
               r"(?:un|una|el|la)\s+(?:recordatorio|temporizador|timer|cron[oó]metro|alarma|cuenta regresiva)|"
               r"recordatorio|temporizador|timer|alarma|despi[eé]rtame)\b", " ", t)
    t = re.sub(r"(?i)\b(?:en|dentro de|de|por|durante|hoy)\s*(?=[\s,.]*$)", " ", t)
    # Restos de la hora que la voz cortó o repitió ("para las... para las 0.38"): la hora ya se quitó arriba
    t = re.sub(r"(?i)\b(?:a|para)\s+las?\b\s*(?:\.{2,}|…|,)?", " ", t)
    t = re.sub(r"\.{2,}|…", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.;:!¡¿?")
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(?i)^(?:que\s+(?:me\s+)?|de\s+(?:que\s+)?|para\s+|a\s+|en\s+|dentro de\s+|y\s+|ma[nñ]ana\s+|hoy\s+)", "", t).strip(" ,.")
        t = re.sub(r"(?i)(?:^|\s+)(?:en|de|por|para|y|a|hoy|dentro|ma[nñ]ana)$", "", t).strip(" ,.")
    return t[:1].lower() + t[1:] if t[:2] != t[:2].upper() else t


def parse(text: str, now: datetime | None = None) -> dict | None:
    """-> {"op": "create"|"ask"|"list"|"cancel", …} o None si la frase no es de recordatorios."""
    now = now or NOW()
    p = _plain(text).strip()
    p_orig_len = len(p)
    if len(text) != p_orig_len:  # tildes compuestas: las posiciones no calzarían con el texto original
        text = unicodedata.normalize("NFC", text)
    kind = _kind(p)

    # consultar
    if kind and re.search(r"\b(que|cuales|cuantos|cuantas)\s+(recordatorios|temporizadores|alarmas)|"
                          r"\b(tengo|hay|quedan)\s+(algun\w*\s+|mis\s+)?(recordatorios|temporizadores|alarmas|recordatorio|temporizador|alarma)\b|"
                          r"\bcuanto\s+(tiempo\s+)?(le\s+)?(queda|falta)\w*|\b(mis|los|las)\s+(recordatorios|temporizadores|alarmas)\s*$|"
                          r"\b(lista|muestrame|dime)\b.*\b(recordatorios|temporizadores|alarmas)\b", p) \
            and not re.search(r"\b(cancela|borra|elimina|quita|deten|anula)\w*", p):
        return {"op": "list", "tipo": kind if kind != "recordatorio" else None}

    # cancelar
    m = re.search(rf"\b(cancel|borr|elimin|quit|apag|deten|det[eé]n|par[ae]\b|anul|olvid|sac)\w*\b.*?\b{_NOUN}\b(.*)$", p)
    if m:
        rest = re.sub(r"^\s*(de|del|para|que|sobre|con)\s+(?:(?:el|la|los|las)\s+)?", "", m.group(3).strip(" .?!"))
        noun = m.group(2)
        tipo = "temporizador" if noun.startswith(("tempo", "timer")) else "alarma" if noun.startswith("alarma") else None
        return {"op": "cancel", "all": bool(re.search(r"\btod[oa]s\b", p)), "tipo": tipo, "query": rest}

    dur = parse_duration(p)
    if kind == "temporizador" or (re.search(r"\b(pon|ponme|programa|inicia|empieza)\w*\b", p) and re.search(_TIMER, p)):
        if not dur:
            return {"op": "ask", "tipo": "temporizador", "texto": "", "ask": "¿De cuánto tiempo pongo el temporizador, señor?"}
        texto = ""
        mt = re.search(r"\bpara\s+(?!dentro\b)(.+)$", text, re.I)
        if mt:
            seg = mt.group(1)
            d2 = re.search(DUR, _plain(seg))
            texto = _clean_text(seg, [d2.span()] if d2 else [])
        return {"op": "create", "tipo": "temporizador", "texto": texto, "cuando": now + timedelta(seconds=dur[0]), "dur": dur[0]}

    if kind == "alarma":
        clock = parse_clock(p, now)
        if clock:
            return {"op": "create", "tipo": "alarma", "texto": _clean_text(text, [clock[1]]), "cuando": clock[0]}
        if dur:
            return {"op": "create", "tipo": "alarma", "texto": _clean_text(text, [dur[1]]), "cuando": now + timedelta(seconds=dur[0])}
        return {"op": "ask", "tipo": "alarma", "texto": _clean_text(text, []), "ask": "¿A qué hora pongo la alarma, señor?"}

    if re.search(_REMIND, p):
        rel = re.search(rf"\b(?:en|dentro\s+de|de\s+aqui\s+a)\s+(?:unos?\s+|unas?\s+)?{DUR}", p)
        if rel and dur:
            return {"op": "create", "tipo": "recordatorio", "texto": _clean_text(text, [rel.span()]),
                    "cuando": now + timedelta(seconds=dur[0]), "dur": dur[0]}
        # "avísame a las 6 …" / "pon un recordatorio a las 6 …": hoy (o mañana), local. Con día de la semana o
        # fecha, y "recuérdame … a las …", sigue siendo un evento de Google Calendar.
        clock = parse_clock(p, now)
        # «recuérdame» y «avísame» son lo mismo: con hora de hoy, recordatorio local; con día, evento de Google
        if clock and not re.search(_DAYWORDS, p) and re.search(r"avisame|recuerdame|recordarme|acuerdame|hazme acordar|recordatorio", p):
            return {"op": "create", "tipo": "recordatorio", "texto": _clean_text(text, [clock[1]]), "cuando": clock[0]}
        if re.search(r"\b(pon|ponme|crea|programa)\w*\s+(un\s+)?recordatorio\b", p) and not clock:
            return {"op": "ask", "tipo": "recordatorio", "texto": _clean_text(text, []),
                    "ask": "¿Para cuándo, señor? Por ejemplo «en 20 minutos» o «a las 6»."}
    return None


def complete(draft: dict, text: str, now: datetime | None = None) -> dict | None:
    """Respuesta a "¿de cuánto tiempo?" / "¿a qué hora?" -> recordatorio listo, o None si no calza."""
    now = now or NOW()
    p = _plain(text)
    dur = parse_duration(p)
    clock = parse_clock(p, now) if draft["tipo"] != "temporizador" else None
    if not clock and draft["tipo"] != "temporizador" and not re.match(r"\s*(en|dentro)\b", p):
        # a "¿A qué hora?" se responde solo la hora: "6 horas 38 minutos", "las 7", "6:38"
        bare = re.sub(r"^\s*(?:a\s+|para\s+)?(?:las?\s+)?", "", p)
        clock = parse_clock("a las " + bare, now)
        rest = ("a las " + bare)[clock[1][1]:] if clock else ""
        if clock and (clock[1][0] != 0 or not re.fullmatch(r"[\s.,!¡?¿]*(?:(?:por favor|porfa|senor|atlas|jarvis|hoy|minutos?)[\s.,!¡?¿]*)*", rest)):
            clock = None  # "dos cosas…" no es una hora: solo vale si la frase es casi solo la hora
    if clock:
        return {"op": "create", "tipo": draft["tipo"], "texto": draft.get("texto", ""), "cuando": clock[0]}
    if dur:
        return {"op": "create", "tipo": draft["tipo"], "texto": draft.get("texto", ""),
                "cuando": now + timedelta(seconds=dur[0]), "dur": dur[0]}
    return None


def find(query: str, tipo: str | None) -> list[dict]:
    items = [i for i in load() if not tipo or i["tipo"] == tipo]
    q = _plain(query)
    # "la de las 6", "la de las 0 38", "la de las 038", "la de las 6:00": buscar por la hora
    hm = re.search(r"\b(\d{1,2})(?:\s*[:.h]\s*|\s+(?:horas?\s+(?:y\s+)?)?)(\d{2})\b|\b(\d)(\d{2})\b|(?:\b(?:las?|a la|a las)\s+|^\s*)(\d{1,2})\b", q)
    if hm:
        h = int(hm.group(1) or hm.group(3) or hm.group(5))
        mi = int(hm.group(2) or hm.group(4) or 0) if not hm.group(5) else None
        by_time = [i for i in items if when(i).hour % 12 == h % 12 and (mi is None or when(i).minute == mi)]
        if by_time:
            return by_time
    filler = {"que", "del", "las", "los", "para", "puesta", "puse", "pusiste", "programada", "programado", "activa",
              "activo", "esa", "ese", "esta", "este", "tengo", "hay", "una", "uno", "alarma", "alarmas", "recordatorio",
              "temporizador", "nueva", "ultima", "ultimo", "manana", "hoy", "por", "favor", "senor"}
    words = [w for w in re.findall(r"[a-z]+", q) if len(w) > 2 and w not in filler]
    if not words:
        return items if not hm else []
    return [i for i in items if any(w in _plain(i["texto"]) for w in words)]

"""Clima directo (Open-Meteo), sin pasar por el modelo. Santiago de Chile si el usuario no nombra otra ciudad.

- parse(text) -> {"day": None|0|1|2, "city": str, "rain": bool} o None si no es una pregunta de clima.
  day None = ahora (más el resumen de hoy); 0 hoy; 1 mañana; 2 pasado mañana.
- answer(text) -> la respuesta en una o dos frases, o None. Las pruebas reemplazan FETCH (url -> dict).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.parse
import urllib.request

HOME = {"name": "Santiago", "lat": -33.4489, "lon": -70.6693}

WMO = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "con neblina", 48: "con neblina helada", 51: "con llovizna débil", 53: "con llovizna", 55: "con llovizna intensa",
    56: "con llovizna helada", 57: "con llovizna helada", 61: "con lluvia débil", 63: "con lluvia", 65: "con lluvia intensa",
    66: "con lluvia helada", 67: "con lluvia helada intensa", 71: "con nieve débil", 73: "con nieve", 75: "con nieve intensa",
    77: "con granizo fino", 80: "con chubascos", 81: "con chubascos fuertes", 82: "con chubascos muy fuertes",
    85: "con chubascos de nieve", 86: "con chubascos de nieve fuertes", 95: "con tormenta eléctrica",
    96: "con tormenta y granizo", 99: "con tormenta fuerte y granizo",
}

ASK = re.compile(
    r"\b(clima|pron[oó]stico|temperatura|grados|llov\w*|llueve|lluvia|paraguas|"
    r"(?:qu[eé]|c[oó]mo)\s+(?:est[aá]|estar[aá]|va\s+a\s+estar)\s+el\s+tiempo|"
    r"qu[eé]\s+tiempo\s+(?:hace|har[aá]|va\s+a\s+hacer)|"
    r"(?:hace|har[aá]|va\s+a\s+hacer)\s+(?:mucho\s+)?(?:fr[ií]o|calor))\b", re.I)
NOT_ME = re.compile(r"\b(recu[eé]rd\w*|agend\w*|anot\w*|pendiente|correo|mensaje|discord|llam[ae]\w*|resumen)\b", re.I)
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_DIA = re.compile(r"\b(?:el\s+|este\s+|para\s+el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b", re.I)
FILLER = re.compile(r"\b(pasado\s+mañana|mañana|hoy|ahora|esta\s+(?:tarde|noche|semana)|en\s+la\s+(?:mañana|tarde|noche)|"
                    r"por\s+favor|señor|atlas|jarvis)\b", re.I)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenJarvis-weather"})
    with urllib.request.urlopen(req, timeout=12) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


FETCH = _get


def parse(text: str) -> dict | None:
    t = (text or "").strip()
    if not ASK.search(t) or NOT_ME.search(t):
        return None
    low = t.lower()
    if re.search(r"pasado\s+mañana", low):
        day = 2
    elif re.search(r"(?<!la )(?<!las )\bmañana\b", low):
        day = 1
    elif re.search(r"\b(hoy|esta\s+(?:tarde|noche))\b", low):
        day = 0
    else:
        day = None
    wd = _DIA.search(low)
    if wd:  # «el sábado»: días desde hoy (0-6); el pronóstico alcanza 7 días
        k = ["lu", "ma", "mi", "ju", "vi", "sa", "do"].index(wd.group(1)[:2].replace("á", "a"))
        day = (k - _dt.date.today().weekday()) % 7
    city = ""
    t = re.sub(r"\s+", " ", FILLER.sub(" ", _DIA.sub(" ", t))).strip()
    m = re.search(r"\ben\s+(.+?)\s*[?!.]*$", t)
    if m:
        c = m.group(1)
        c = re.sub(r"^(?:la|el)\s+ciudad\s+de\s+", "", c.strip(), flags=re.I)
        c = re.sub(r"[¿?¡!.,]", "", c).strip()
        if c and len(c) <= 40 and not re.fullmatch(r"(?i)(la|el|los|las|casa|mi casa|la casa)?", c):
            city = c
    if re.fullmatch(r"(?i)santiago(?:\s+de\s+chile)?(?:,?\s*chile)?", city):
        city = ""
    return {"day": day, "city": city, "rain": bool(re.search(r"llov|llueve|lluvia|paraguas", low))}


def place(city: str) -> dict | None:
    if not city:
        try:  # ajustes.json ciudad_clima: {"name", "lat", "lon"}
            import atlas_ajustes as AJ
            c = AJ.get("ciudad_clima") or {}
            if c.get("name") and isinstance(c.get("lat"), (int, float)) and isinstance(c.get("lon"), (int, float)):
                return {"name": c["name"], "lat": c["lat"], "lon": c["lon"]}
        except Exception:  # noqa: BLE001
            pass
        return HOME
    geo = FETCH("https://geocoding-api.open-meteo.com/v1/search?count=5&language=es&name=" + urllib.parse.quote(city))
    res = geo.get("results") or []
    if not res:
        return None
    best = next((r for r in res if r.get("country_code") == "CL"), res[0])  # una ciudad chilena si hay con ese nombre
    name = best.get("name") or city
    if best.get("country_code") != "CL" and best.get("country"):
        name += f", {best['country']}"
    return {"name": name, "lat": best["latitude"], "lon": best["longitude"]}


def _n(x) -> str:
    try:
        return str(round(float(x)))
    except (TypeError, ValueError):
        return "?"


def answer(text: str) -> str | None:
    q = parse(text)
    if not q:
        return None
    try:
        p = place(q["city"])
        if not p:
            return f"No encontré la ciudad «{q['city']}», señor. ¿Me la repite?"
        w = FETCH("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                  "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
                  "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                  "&timezone=auto&forecast_days=7" % (p["lat"], p["lon"]))
    except Exception as exc:  # noqa: BLE001
        return f"No pude consultar el clima ahora, señor ({str(exc)[:80]})."
    cur, d = w.get("current") or {}, w.get("daily") or {}

    def day(i: int, key: str):
        v = d.get(key) or []
        return v[i] if i < len(v) else None

    i = q["day"] or 0
    rain = day(i, "precipitation_probability_max")
    desc = WMO.get(day(i, "weather_code"), "")
    span = f"mínima de {_n(day(i, 'temperature_2m_min'))}° y máxima de {_n(day(i, 'temperature_2m_max'))}°"
    rain_txt = f"{_n(rain)}% de probabilidad de lluvia" if rain is not None else ""
    lead = ""
    if q["rain"] and rain is not None:
        r = float(rain)
        lead = "Sí, probablemente llueva. " if r >= 60 else "Puede que llueva. " if r >= 30 else "No se espera lluvia. "
    where = p["name"]
    if q["day"] is None:
        now = f"Ahora en {where} hay {_n(cur.get('temperature_2m'))}°"
        if cur.get("weather_code") in WMO:
            now += f", {WMO[cur['weather_code']]}"
        if cur.get("apparent_temperature") is not None and abs(float(cur["apparent_temperature"]) - float(cur.get("temperature_2m") or 0)) >= 2:
            now += f" (sensación de {_n(cur['apparent_temperature'])}°)"
        return f"{lead}{now}, señor. Hoy: {span}" + (f", {rain_txt}." if rain_txt else ".")
    label = ["Hoy", "Mañana", "Pasado mañana"][i] if i < 3 else "El " + DIAS[(_dt.date.today().weekday() + i) % 7]
    body = f"{label} en {where}, señor: {desc + ', ' if desc else ''}{span}"
    return lead + body + (f", con {rain_txt}." if rain_txt else ".")

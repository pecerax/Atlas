"""Respuestas básicas de Atlas, por reglas: instantáneas y sin pasar por el modelo.

Frases que entiende (ejemplos, incluidas transcripciones raras de la voz):
  "qué hora es" / "qué horas son" / "necesito saber qué hora es" / "qué hora es en Tokio"
  "qué día es hoy" / "a cuánto estamos" / "qué día es mañana" / "en qué mes estamos"
  "qué día cae el 25 de diciembre" / "cuántos días faltan para navidad" / "cuánto falta para el viernes"
  "cuánto es 6 elevado a 3" / "calcula 15 por 23" / "el 15 por ciento de 20 mil" / "raíz cuadrada de 144"
  "cuántas millas son 5 kilómetros" / "convierte 30 grados a fahrenheit" / "cuántos minutos son 3 horas"
  "a cuánto está el dólar" / "cuánto es 3 UF" / "cuántos dólares son 50 lucas"
Dólar, euro y UF vienen de mindicador.cl (publica los valores oficiales del Banco Central de Chile).
Si no responde, Atlas lo dice: nunca inventa un valor.

answer(texto) -> respuesta lista para decir, o None si la frase no es de este tipo (sigue a otras rutas).
"""

from __future__ import annotations

import ast
import json
import math
import re
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta

NOW = datetime.now  # las pruebas lo reemplazan por una hora fija
LOCAL_TZ = "America/Santiago"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
_DIAS_P = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_MESES_P = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                            "septiembre", "octubre", "noviembre", "diciembre"])}
_MESES_P["setiembre"] = 9


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# ----------------------------------------------------------------------------- números dichos en palabras
_SMALL = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
          "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
          "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
          "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
          "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
          "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
          "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
          "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
          "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
          "novecientas": 900}


def _num(tok: str) -> float | None:
    try:
        return float(tok)
    except ValueError:
        return None


def numerize(p: str) -> str:
    """'veinte mil pesos' -> '20000 pesos'; '3,5' -> '3.5'; '20.000' -> '20000'. Recibe texto ya en _plain."""
    p = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", p)
    p = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", p)  # 1.000.000
    p = re.sub(r"(?<=\d),(?=\d)", ".", p)
    toks = re.findall(r"\d+(?:\.\d+)?|[a-zñ]+|[%+\-*/^×÷()]", p)
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] not in _SMALL and toks[i] != "mil" and _num(toks[i]) is None:
            out.append(toks[i])
            i += 1
            continue
        total, cur, j, last = 0.0, 0.0, i, ""  # last: "", "n" (número), "y", "mil"
        while j < len(toks):
            w = toks[j]
            v, n = _SMALL.get(w), _num(w)
            if n is not None and last in ("", "mil") and cur == 0:
                cur, last = n, "n"
            elif v is not None and (last in ("", "mil") and cur == 0 or last == "n" and cur % 100 == 0 and cur > 0 and v < 100
                                    or last == "y" and v < 10):
                cur, last = cur + v, "n"
            elif w == "y" and last == "n" and j + 1 < len(toks) and toks[j + 1] in ("medio", "media"):
                cur, last, j = cur + 0.5, "n", j + 1
            elif w == "y" and last == "n" and cur % 10 == 0 and cur % 100 >= 30 and j + 1 < len(toks)                     and _SMALL.get(toks[j + 1], 99) < 10:
                last = "y"
            elif w == "mil" and last in ("", "n"):
                total, cur, last = total + (cur or 1) * 1000, 0.0, "mil"
            elif w in ("millon", "millones") and last in ("n", "mil"):
                total, cur, last = (total + cur) * 1_000_000, 0.0, "mil"
            else:
                break
            j += 1
        if last in ("", "y"):
            out.append(toks[i])
            i += 1
            continue
        val = total + cur
        out.append(str(int(val)) if val == int(val) else str(val))
        i = j
    return " ".join(out)


def fmt(x: float, dec: int = 2) -> str:
    """Número para la voz: sin separador de miles (la voz lo lee entero) y coma decimal."""
    if abs(x) >= 1e15:
        return f"{x:.3e}".replace(".", ",")
    r = round(x, dec)
    if r == int(r):
        return str(int(r))
    if abs(x) < 0.01:
        return f"{x:.4g}".replace(".", ",")
    return (f"{r:.{dec}f}".rstrip("0").rstrip(".")).replace(".", ",")


# ----------------------------------------------------------------------------- frases mal transcritas
def _normalize(text: str) -> str:
    p = _plain(text)
    p = re.sub(r"[¿?¡!.,;:\"«»]+(?=\s|$)|^[¿¡\"«]+", " ", p)
    p = re.sub(r"(?<=\s)[¿¡]", " ", p)
    p = re.sub(r"\b(?:ke|k|q|qe)\b", "que", p)
    p = re.sub(r"\bkuant", "cuant", p)
    p = re.sub(r"\bque\s+oras?\b", "que hora", p)
    p = re.sub(r"\b(?:atlas|jarvis|senor|oye|ey|hey|por favor|porfa|porfavor)\b", " ", p)
    return re.sub(r"\s+", " ", p).strip()


# ----------------------------------------------------------------------------- hora
_CIUDADES = [
    (r"santiago(?: de chile)?|chile|aca|aqui", LOCAL_TZ, "Santiago"),
    (r"punta arenas|magallanes", "America/Punta_Arenas", "Punta Arenas"),
    (r"isla de pascua|rapa nui", "Pacific/Easter", "Isla de Pascua"),
    (r"buenos aires|argentina", "America/Argentina/Buenos_Aires", "Buenos Aires"),
    (r"lima|peru", "America/Lima", "Lima"),
    (r"bogota|colombia", "America/Bogota", "Bogotá"),
    (r"(?:ciudad de )?mexico", "America/Mexico_City", "Ciudad de México"),
    (r"sao paulo|brasil|rio de janeiro", "America/Sao_Paulo", "São Paulo"),
    (r"nueva york|new york|miami|washington|boston", "America/New_York", "Nueva York"),
    (r"los angeles|california|san francisco", "America/Los_Angeles", "Los Ángeles"),
    (r"madrid|espana|barcelona", "Europe/Madrid", "Madrid"),
    (r"londres|inglaterra|reino unido", "Europe/London", "Londres"),
    (r"paris|francia", "Europe/Paris", "París"),
    (r"berlin|alemania", "Europe/Berlin", "Berlín"),
    (r"roma|italia", "Europe/Rome", "Roma"),
    (r"tokio|tokyo|japon", "Asia/Tokyo", "Tokio"),
    (r"seul|corea(?: del sur)?", "Asia/Seoul", "Seúl"),
    (r"pekin|beijing|shanghai|china", "Asia/Shanghai", "China"),
    (r"sidney|sydney|australia", "Australia/Sydney", "Sídney"),
]

_HORA_Q = (r"(?:(?<!a )\bque hora (?:es|son|seria|sera|tienes|tenemos|hay|marca)\b|\bque horas son\b|"
           r"\b(?:dime|dame|decirme|darme|saber|sabes|tienes|me (?:das|dices|dirias|puedes decir|podrias decir|"
           r"da|dice)) (?:que hora(?: es| son)?|la hora)\b|\bhora actual\b|^(?:la )?hora$|^que hora$)")
_TAIL_OK = r"(?:ahora|ahora mismo|actualmente|ya|aca|aqui|alla|exacta|exactamente|hoy|en este momento|po|pues|\s)*"


def _local_now() -> datetime:
    n = NOW()
    if n.tzinfo is None:
        try:
            from zoneinfo import ZoneInfo
            n = n.replace(tzinfo=ZoneInfo(LOCAL_TZ))
        except Exception:  # noqa: BLE001
            pass
    return n


def say_time(dt: datetime) -> str:
    return f"Es la 1:{dt.minute:02d}" if dt.hour == 1 else f"Son las {dt.hour}:{dt.minute:02d}"


def say_date(d: date, year: bool = True) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if year else "")


def estacion(d) -> str:
    """Estación del año en Chile (hemisferio sur; fechas aproximadas de equinoccios y solsticios). Uso real 18-11-2026:
    el modelo dijo que en noviembre en Chile «todavía es otoño» (es primavera)."""
    md = (d.month, d.day)
    if md >= (12, 21) or md < (3, 20):
        return "verano"
    if md < (6, 21):
        return "otoño"
    if md < (9, 22):
        return "invierno"
    return "primavera"


def clock_line() -> str:
    """Línea para <datos herramienta="reloj">: lo que el modelo debe saber siempre (fecha, hora, estación y lugar)."""
    n = _local_now()
    return (f"Ahora es {say_date(n.date())}, {n.hour}:{n.minute:02d} (hora de Santiago de Chile). "
            f"Mañana es {say_date(n.date() + timedelta(days=1), year=False)}. "
            f"En Chile (hemisferio sur) es {estacion(n.date())}.")


def _time_answer(p: str) -> str | None:
    m = re.search(_HORA_Q, p)
    if not m:
        return None
    before, tail = p[:m.start()].strip(), p[m.end():].strip()
    place = None
    mt = re.match(r"(?:en|de|alla en|por) (.+)$", tail)
    if mt:
        place, tail = mt.group(1).strip(), ""
    else:
        mb = re.search(r"\ben ([a-z ]+?)(?: ahora)?$", before)
        if mb and not re.search(r"\b(?:clase|control|prueba|reunion|evento)\b", mb.group(1)):
            place = mb.group(1).strip()
    if tail and not re.fullmatch(_TAIL_OK + r"(?:y (?:que |la )?(?:dia|fecha)(?: es)?(?: hoy)?)?" + _TAIL_OK, tail):
        return None  # "qué hora es la clase de redes": eso es de la agenda
    if re.search(r"\b(?:clase|control|prueba|reunion|evento|auxiliar|catedra|entrega)\b", before + " " + (place or "")):
        return None
    now = _local_now()
    with_date = bool(re.search(r"\b(?:dia|fecha)\b", tail + " " + before))
    if place:
        place = re.sub(r"^(?:el|la|los|las)\s+", "", place)
        for pat, tz, nombre in _CIUDADES:
            if re.fullmatch(pat, place):
                if tz == LOCAL_TZ:
                    break
                try:
                    from zoneinfo import ZoneInfo
                    there = now.astimezone(ZoneInfo(tz))
                except Exception:  # noqa: BLE001
                    return f"No tengo la zona horaria de {nombre} en este PC, señor. Aquí en Santiago {say_time(now).lower()}."
                dia = ""
                if there.date() != now.date():
                    dia = f" del {DIAS[there.weekday()]} {there.day}"
                return f"En {nombre} {say_time(there).lower()}{dia}, señor."
        else:
            return (f"No tengo la hora de «{place}», señor. Aquí en Santiago {say_time(now).lower()}.")
    if with_date:
        return f"{say_time(now)} del {say_date(now.date())}, señor."
    return f"{say_time(now)}, señor."


# ----------------------------------------------------------------------------- fechas
_FIESTAS = {r"navidad": (12, 25), r"noche ?buena": (12, 24), r"ano nuevo": (1, 1), r"fin de ano": (12, 31),
            r"fiestas patrias|el dieciocho|el 18 de septiembre": (9, 18), r"halloween": (10, 31),
            r"san valentin|dia de los enamorados": (2, 14)}


def parse_date(s: str, today: date) -> tuple[date, bool] | None:
    """'el 25 de diciembre' / 'navidad' / 'el viernes' / 'mañana' / 'el 3' -> (fecha, dijo el año). Solo frases completas."""
    s = re.sub(r"^(?:para |hasta |a )?(?:el |la |los |las |este |esta |)", "", s.strip()).strip()
    s = re.sub(r"\s+(?:que viene|de este ano|de este mes)$", "", s)
    if s in ("hoy",):
        return today, False
    if s in ("manana",):
        return today + timedelta(days=1), False
    if s in ("pasado manana",):
        return today + timedelta(days=2), False
    if s in ("ayer",):
        return today - timedelta(days=1), False
    for pat, (mo, d) in _FIESTAS.items():
        if re.fullmatch(r"(?:el )?(?:" + pat + r")", s):
            x = date(today.year, mo, d)
            return (x if x >= today else date(today.year + 1, mo, d)), False
    m = re.fullmatch(r"(?:proximo |otro )?(" + "|".join(_DIAS_P) + r")(?: proximo| que viene)?", s)
    if m:
        delta = (_DIAS_P.index(m.group(1)) - today.weekday()) % 7 or 7
        return today + timedelta(days=delta), False
    m = re.fullmatch(r"(\d{1,2}) de (" + "|".join(_MESES_P) + r")(?: (?:de|del) (?:ano )?(\d{4}))?", s) \
        or re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", s)
    if m:
        mo = _MESES_P.get(m.group(2)) or int(m.group(2))
        try:
            x = date(int(m.group(3)) if m.group(3) else today.year, mo, int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and x < today:
            x = date(today.year + 1, mo, int(m.group(1)))
        return x, bool(m.group(3))
    m = re.fullmatch(r"(\d{1,2})", s)
    if m:  # "el 18": ese día de este mes o del siguiente
        d = int(m.group(1))
        y, mo = today.year, today.month
        for _ in range(3):
            try:
                x = date(y, mo, d)
                if x >= today:
                    return x, False
            except ValueError:
                pass
            mo, y = (1, y + 1) if mo == 12 else (mo + 1, y)
    return None


def _date_answer(p: str) -> str | None:
    today = _local_now().date()
    # cuántos días faltan para …
    m = re.search(r"\b(?:cuant[oa]s (dias|semanas) (?:faltan|quedan|hay|restan|van)|cuanto (?:falta|queda))"
                  r" (?:para|hasta) (.+)$", p) or re.search(r"\ben cuant[oa]s (dias|semanas) (?:es|cae|sera|llega) (.+)$", p)
    if m:
        got = parse_date(numerize(m.group(2)), today)
        if not got:
            return None  # "cuánto falta para la tarea 3": eso lo ve la agenda
        d, with_year = got
        n = (d - today).days
        cuando = say_date(d, year=with_year or d.year != today.year)
        if n == 0:
            return f"Es hoy, señor: {cuando}."
        if n < 0:
            return f"El {cuando} ya pasó, señor: fue hace {-n} día{'s' if n != -1 else ''}."
        if n == 1:
            return f"Es mañana, señor: falta 1 día para el {cuando}."
        sem = f" (unas {round(n / 7)} semanas)" if n >= 14 else ""
        return f"Faltan {n} días para el {cuando}{sem}, señor."
    # qué día cae el 25 de diciembre
    m = re.search(r"\bque dia (?:de la semana )?(?:es|cae|sera|fue|era|toca) (?!hoy\b|manana\b|ayer\b|pasado manana\b)(.+)$", p)
    if m:
        objetivo = numerize(m.group(1))
        got = parse_date(objetivo, today)
        if not got or not re.search(r"\d|navidad|ano|buena|patrias|dieciocho|halloween|valentin|enamorados", objetivo):
            return None  # "qué día es el control de redes": agenda
        d, with_year = got
        verbo = "cae" if d >= today else "fue"
        return f"El {d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if with_year or d.year != today.year else "") \
            + f" {verbo} {DIAS[d.weekday()]}, señor."
    # hoy, mañana, ayer, mes, año
    if re.search(r"\ben que mes (?:estamos|vamos)\b|\bque mes es\b", p):
        return f"Estamos en {MESES[today.month - 1]} de {today.year}, señor."
    if re.search(r"\ben que ano (?:estamos|vamos)\b|\bque ano es\b", p):
        return f"Estamos en {today.year}, señor."
    rel = re.search(r"\bque (?:dia|fecha) (?:es|sera|fue|era|seria) (manana|pasado manana|ayer)\b", p) \
        or re.search(r"\b(manana|pasado manana|ayer) que (?:dia|fecha) (?:es|sera|fue|era)\b", p)
    if rel:
        k = rel.group(1)
        d = today + timedelta(days={"manana": 1, "pasado manana": 2, "ayer": -1}[k])
        nombre = {"manana": "Mañana es", "pasado manana": "Pasado mañana es", "ayer": "Ayer fue"}[k]
        return f"{nombre} {say_date(d, year=d.year != today.year)}, señor."
    if re.search(r"\bque dia (?:es|de la semana es)(?: hoy)?$|\bque dia (?:es )?hoy\b|\ba que dia estamos\b|"
                 r"\ba cuanto estamos\b|\bque fecha (?:es|tenemos|estamos)\b|\ben que fecha (?:estamos|vamos)\b|"
                 r"\bcual es la fecha\b|\b(?:la )?fecha (?:de hoy|actual)\b|^(?:la )?fecha$|^que dia es$|"
                 r"\b(?:dime|dame|saber) (?:la fecha|que dia es)\b|\bque dia estamos\b", p):
        return f"Hoy es {say_date(today)}, señor."
    return None


# ----------------------------------------------------------------------------- cálculos
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
            ast.USub, ast.UAdd, ast.Call, ast.Name, ast.Load, ast.Mod)


def _eval(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError("no permitido")
        if isinstance(node, ast.Name) and node.id not in ("sqrt", "cbrt"):
            raise ValueError("no permitido")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            b, e = _eval_node(node.left), _eval_node(node.right)
            if abs(e) > 100 or abs(b) > 1e6:
                raise OverflowError
    return _eval_node(tree.body)


def _eval_node(n) -> float:
    if isinstance(n, ast.Expression):
        return _eval_node(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return float(n.value)
    if isinstance(n, ast.UnaryOp):
        v = _eval_node(n.operand)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and len(n.args) == 1:
        v = _eval_node(n.args[0])
        if n.func.id == "sqrt":
            if v < 0:
                raise ValueError("raíz de negativo")
            return math.sqrt(v)
        return math.copysign(abs(v) ** (1 / 3), v)
    if isinstance(n, ast.BinOp):
        a, b = _eval_node(n.left), _eval_node(n.right)
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Sub):
            return a - b
        if isinstance(n.op, ast.Mult):
            return a * b
        if isinstance(n.op, ast.Div):
            return a / b
        if isinstance(n.op, ast.Pow):
            if abs(b) > 100 or abs(a) > 1e6:
                raise OverflowError
            return a ** b
    raise ValueError("no permitido")


_N = r"\d+(?:\.\d+)?"


def _to_expr(s: str) -> str | None:
    s = " " + s.strip() + " "
    s = re.sub(r" (?:la )?raiz cuadrada (?:de )?(" + _N + ") ", r" sqrt(\1) ", s)
    s = re.sub(r" (?:la )?raiz cubica (?:de )?(" + _N + ") ", r" cbrt(\1) ", s)
    s = re.sub(r" (?:el )?(" + _N + r") ?(?:%|por ciento|porciento) (?:de|del) (" + _N + ") ", r" (\1/100*\2) ", s)
    s = re.sub(r" (" + _N + r") al cuadrado ", r" \1**2 ", s)
    s = re.sub(r" (" + _N + r") al cubo ", r" \1**3 ", s)
    s = re.sub(r" eleva(?:r|do|da|lo)? (" + _N + r") (?:a la potencia (?:de )?|a la |al |a )(" + _N + ") ", r" \1**\2 ", s)
    s = re.sub(r" (?:elevado|elevada) (?:a la potencia (?:de )?|a la |al |a )| a la potencia (?:de )?| a la (?=\d)|\^", " ** ", s)
    s = re.sub(r" dividid[oa] (?:por |en |entre )?| partido (?:por |en )| entre | ÷ |/", " / ", s)
    s = re.sub(r" multiplicad[oa] (?:por )?| por | x | × |\*", " * ", s)
    s = re.sub(r" mas |\+", " + ", s)
    s = re.sub(r" menos |-", " - ", s)
    s = re.sub(r"^\s*(?:el|la|lo|de|que|a)\s+", " ", s)
    s = s.replace("* *", "**")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*\*\s*\*\s*", "**", s)
    if not s or not re.fullmatch(r"[\d.\s+\-*/()]*(?:(?:sqrt|cbrt)\([\d.]+\)[\d.\s+\-*/()]*)*", s):
        return None
    if not re.search(r"[+\-*/]|sqrt|cbrt", s) or not re.search(r"\d", s):
        return None
    return s


def _say_expr(e: str) -> str:
    e = re.sub(r"\(\s*(" + _N + r")\s*/\s*100\s*\*\s*(" + _N + r")\s*\)", lambda m: f"el {fmt(float(m.group(1)))}% de {fmt(float(m.group(2)))}", e)
    e = re.sub(r"sqrt\((" + _N + r")\)", lambda m: f"la raíz cuadrada de {fmt(float(m.group(1)))}", e)
    e = re.sub(r"cbrt\((" + _N + r")\)", lambda m: f"la raíz cúbica de {fmt(float(m.group(1)))}", e)
    e = re.sub(r"(?<![\d.])" + _N, lambda m: fmt(float(m.group(0)), 6), e)
    e = e.replace("**", " elevado a ").replace("*", " por ").replace("/", " dividido por ")
    e = e.replace("+", " más ").replace("-", " menos ")
    return re.sub(r"\s+", " ", e).strip()


def _calc_answer(p: str) -> str | None:
    s = numerize(re.sub(r"\bpor ?ciento\b", "%", p))
    m = re.search(r"\b(?:cuant[oa]s? (?:es|son|da|dan|seria|serian|sale|resulta)|calcula(?:me|r)?|resuelve|"
                  r"resultado de|haz la (?:cuenta|operacion)(?: de)?|(?:en la (?:aplicacion de la )?calculadora )?(?=eleva))\s*(.*)$", s)
    tail = m.group(1) if m else s
    tail = re.sub(r"\s+(?:en la calculadora|con la calculadora)$", "", tail)
    expr = _to_expr(tail)
    if not expr:
        return None
    if not m and not re.fullmatch(r"[\d.\s+\-*/()a-z]*", tail):
        return None
    try:
        val = _eval(expr)
    except ZeroDivisionError:
        return "No se puede dividir por cero, señor."
    except OverflowError:
        return "Ese número es demasiado grande para decirlo en voz alta, señor."
    except (ValueError, SyntaxError, TypeError):
        return None
    dicho = _say_expr(expr)
    return f"{dicho[0].upper() + dicho[1:]} es {fmt(val, 4)}, señor."


# ----------------------------------------------------------------------------- unidades
# (clave, alias, dimensión, factor a la unidad base, singular, plural)
_UNITS = [
    ("kmh", r"kilometros por hora|km por hora|kmh|km/h", "vel", 1 / 3.6, "kilómetro por hora", "kilómetros por hora"),
    ("mph", r"millas por hora|mph", "vel", 0.44704, "milla por hora", "millas por hora"),
    ("km", r"kilometros?|kms?", "len", 1000, "kilómetro", "kilómetros"),
    ("m", r"metros?|mts?", "len", 1, "metro", "metros"),
    ("cm", r"centimetros?|cms?", "len", 0.01, "centímetro", "centímetros"),
    ("mm", r"milimetros?|mm", "len", 0.001, "milímetro", "milímetros"),
    ("mi", r"millas?", "len", 1609.344, "milla", "millas"),
    ("ft", r"pies?", "len", 0.3048, "pie", "pies"),
    ("in", r"pulgadas?", "len", 0.0254, "pulgada", "pulgadas"),
    ("yd", r"yardas?", "len", 0.9144, "yarda", "yardas"),
    ("t", r"toneladas?", "mass", 1000, "tonelada", "toneladas"),
    ("kg", r"kilogramos?|kilos?|kg", "mass", 1, "kilo", "kilos"),
    ("g", r"gramos?|grs?", "mass", 0.001, "gramo", "gramos"),
    ("lb", r"libras?", "mass", 0.45359237, "libra", "libras"),
    ("oz", r"onzas?", "mass", 0.028349523125, "onza", "onzas"),
    ("l", r"litros?|lts?", "vol", 1, "litro", "litros"),
    ("ml", r"mililitros?|ml|cc", "vol", 0.001, "mililitro", "mililitros"),
    ("gal", r"galones|galon", "vol", 3.785411784, "galón", "galones"),
    ("s", r"segundos?", "time", 1, "segundo", "segundos"),
    ("min", r"minutos?", "time", 60, "minuto", "minutos"),
    ("h", r"horas?", "time", 3600, "hora", "horas"),
    ("d", r"dias?", "time", 86400, "día", "días"),
    ("sem", r"semanas?", "time", 604800, "semana", "semanas"),
    ("ano", r"anos?", "time", 31557600, "año", "años"),
    ("c", r"grados celsius|grados centigrados|celsius|centigrados|grados", "temp", None, "grado Celsius", "grados Celsius"),
    ("f", r"grados fahrenheit|fahrenheit|farenheit|farenhait|fahrenheint", "temp", None, "grado Fahrenheit", "grados Fahrenheit"),
]
_U = "|".join(sorted((a for u in _UNITS for a in u[1].split("|")), key=len, reverse=True))


def _unit(word: str):
    for u in _UNITS:
        if re.fullmatch(u[1], word):
            return u
    return None


def _convert(v: float, a, b) -> float | None:
    if a[2] != b[2]:
        return None
    if a[2] == "temp":
        if a[0] == b[0]:
            return v
        return v * 9 / 5 + 32 if a[0] == "c" else (v - 32) * 5 / 9
    return v * a[3] / b[3]


def _units_answer(p: str) -> str | None:
    s = numerize(p)
    m = re.search(r"(" + _N + r") (" + _U + r") (?:a|en|para|son cuant[oa]s) (" + _U + r")\b", s)
    if m:
        v, a, b = float(m.group(1)), _unit(m.group(2)), _unit(m.group(3))
    else:
        m = re.search(r"\bcuant[oa]s (" + _U + r") (?:son|hay en|tiene|tienen|equivalen a|caben en|mide|miden) (?:(" + _N + r") )?(" + _U + r")\b", s)
        if not m:
            return None
        v, a, b = float(m.group(2) or 1), _unit(m.group(3)), _unit(m.group(1))
    if not re.search(r"\b(?:cuant|convier|pasa|transforma|equival|son\b|es\b)", s):
        return None
    if a is None or b is None or a[0] == b[0]:
        return None
    r = _convert(v, a, b)
    if r is None:
        return f"No se puede pasar {a[5]} a {b[5]}, señor: miden cosas distintas."
    na = a[4] if v == 1 else a[5]
    nb = b[4] if round(r, 2) == 1 else b[5]
    return f"{fmt(v)} {na} son {fmt(r)} {nb}, señor."


# ----------------------------------------------------------------------------- dólar, euro y UF
INDICADORES_URL = "https://mindicador.cl/api"
_cache: dict = {"t": 0.0, "data": None}


def _fetch_indicadores() -> dict:
    req = urllib.request.Request(INDICADORES_URL, headers={"User-Agent": "Atlas-HUD"})
    with urllib.request.urlopen(req, timeout=6) as r:
        raw = json.loads(r.read().decode("utf-8"))
    out = {}
    for k in ("dolar", "euro", "uf"):
        v = raw.get(k) or {}
        if v.get("valor"):
            out[k] = (float(v["valor"]), str(v.get("fecha", ""))[:10])
    if not out:
        raise ValueError("sin datos")
    return out


FETCH = _fetch_indicadores  # las pruebas lo reemplazan


def indicadores() -> dict | None:
    if _cache["data"] and time.time() - _cache["t"] < 1800:
        return _cache["data"]
    try:
        data = FETCH()
    except Exception:  # noqa: BLE001
        return None
    _cache.update(t=time.time(), data=data)
    return data


_CUR = {"dolar": r"dolar(?:es)?(?: americanos?| gringos?)?|usd|verdes", "euro": r"euros?",
        "uf": r"uf|u f|ufs|unidad(?:es)? de fomento", "peso": r"pesos?(?: chilenos?)?|clp|lucas?"}
_CUR_ANY = "|".join(_CUR.values())
_NOMBRE = {"dolar": ("dólar", "dólares", "El dólar observado"), "euro": ("euro", "euros", "El euro"),
           "uf": ("UF", "UF", "La UF"), "peso": ("peso", "pesos", "")}


def _cur(word: str) -> str | None:
    for k, pat in _CUR.items():
        if re.fullmatch(pat, word):
            return k
    return None


def _fecha_dato(f: str, today: date) -> str:
    try:
        d = date.fromisoformat(f)
    except ValueError:
        return ""
    if d == today:
        return "de hoy"
    if d == today - timedelta(days=1):
        return "de ayer"
    return f"del {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _money_answer(p: str) -> str | None:
    s = numerize(p)
    conv = re.search(r"(" + _N + r") (" + _CUR_ANY + r")(?: (?:a|en|para|son cuant[oa]s) (" + _CUR_ANY + r"))?\b", s)
    conv2 = re.search(r"\bcuant[oa]s (" + _CUR_ANY + r") (?:son|es|serian|me dan por|equivalen a) (" + _N + r") (" + _CUR_ANY + r")\b", s)
    value_q = re.search(r"\b(?:a cuanto|cuanto|en cuanto|como|a como) (?:esta|vale|anda|cuesta|se cotiza|quedo|cerro|va)"
                        r"(?: hoy)? (?:el |la )?(" + _CUR_ANY + r")\b|\b(?:valor|precio) (?:del |de la |de )?(?:hoy )?(" + _CUR_ANY
                        + r")\b|^(?:el |la )?(dolar|uf|euro)(?: hoy)?$", s)
    if conv2:
        v, src, dst = float(conv2.group(2)), _cur(conv2.group(3)), _cur(conv2.group(1))
        lucas = bool(re.fullmatch(r"lucas?", conv2.group(3)))
    elif conv and (conv.group(3) or re.search(r"\b(?:cuant|convier|pasa|es\b|son\b)", s)):
        v, src = float(conv.group(1)), _cur(conv.group(2))
        dst = _cur(conv.group(3)) if conv.group(3) else ("peso" if _cur(conv.group(2)) != "peso" else None)
        lucas = bool(re.fullmatch(r"lucas?", conv.group(2)))
        if dst is None:
            return None
    elif value_q:
        k = _cur(next(g for g in value_q.groups() if g))
        if k == "peso":
            return None
        data = indicadores()
        nombre = _NOMBRE[k][0]
        if not data or k not in data:
            return (f"No pude consultar el valor del {nombre} ahora, señor: la fuente que uso, mindicador.cl, con datos del "
                    f"Banco Central, no respondió. Prefiero no darle una cifra de memoria.").replace("del UF", "de la UF")
        val, f = data[k]
        cuando = _fecha_dato(f, _local_now().date())
        return f"{_NOMBRE[k][2]} está a {fmt(val, 0)} pesos, señor" + (f"; es el valor {cuando}." if cuando else ".")
    else:
        return None
    if src is None or dst is None or src == dst:
        return None
    if lucas:
        v *= 1000
    data = indicadores()
    need = [k for k in (src, dst) if k != "peso"]
    if not data or any(k not in data for k in need):
        return ("No pude consultar el valor del dólar, el euro y la UF ahora, señor: la fuente que uso, mindicador.cl, con datos "
                "del Banco Central, no respondió. Prefiero no darle una cifra de memoria.")
    pesos = v if src == "peso" else v * data[src][0]
    r = pesos if dst == "peso" else pesos / data[dst][0]
    na = _NOMBRE[src][0 if v == 1 else 1]
    nb = _NOMBRE[dst][1]
    fechas = {data[k][1] for k in need}
    cuando = _fecha_dato(sorted(fechas)[-1], _local_now().date()) if fechas else ""
    return (f"{fmt(v)} {na} son unos {fmt(r, 0 if dst == 'peso' else 2)} {nb}, señor"
            + (f", con el valor {cuando}." if cuando else "."))


# ----------------------------------------------------------------------------- entrada
def answer(text: str) -> str | None:
    p = _normalize(text)
    if not p or len(p) > 160:
        return None
    if re.search(r"\b(?:recuerda|recordatorio|alarma|temporizador|timer|avisame|agenda|agendame|anota|apunta|guarda)\w*", p):
        return None  # eso es de recordatorios, calendario o memoria
    for f in (_time_answer, _date_answer, _money_answer, _units_answer, _calc_answer):
        r = f(p)
        if r:
            return r
    return None

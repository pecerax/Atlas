"""Hermes dentro de Atlas: preguntas por voz sobre tus gastos.

Lee los movimientos que deja Hermes (%LOCALAPPDATA%\\Atlas\\apps\\hermes\\movimientos.json, lo llena
«actualiza Hermes») y el presupuesto (presupuestos.json en esa misma carpeta). Solo lee: no cambia nada.
Los números salen de los datos, no del modelo de lenguaje.

Responde, por ejemplo:
  «¿cuánto gasté este mes?», «¿cuánto gasté la semana pasada?», «¿cuánto gasté en octubre?»
  «¿cuánto llevo en comida?», «¿cuánto gasté en Uber este mes?»
  «¿cómo va mi presupuesto?», «¿me queda presupuesto?»  (solo cuando se pregunta: nada de avisos solos)
  «¿en qué gasté más este mes?», «¿cuál fue mi último gasto?»
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

HERMES_DIR = Path(os.environ.get("HERMES_DIR") or (Path(__file__).resolve().parent.parent / "apps" / "hermes"))
HOY = None  # las pruebas fijan una fecha; si no, hoy

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
NO_GASTO = {"Transferencias propias", "Pago de tarjeta", "Ingresos", "Inversiones", "Devoluciones y otros",
            "Préstamos recibidos", "Extras de familia", "Ingresos por revisar"}


def _plain(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _hoy() -> date:
    return HOY or date.today()


def clp(n: float) -> str:
    return "$" + f"{round(abs(n)):,}".replace(",", ".")


def pesos_dichos(n: float) -> str:
    """Para la voz: «152 mil 160 pesos» se lee mejor que «$152.160»."""
    n = round(abs(n))
    if n >= 1_000_000:
        millones, resto = divmod(n, 1_000_000)
        miles = resto // 1000
        txt = f"{millones} millón" if millones == 1 else f"{millones} millones"
        return txt + (f" {miles} mil pesos" if miles else " de pesos")
    if n >= 1000:
        miles, resto = divmod(n, 1000)
        return f"{miles} mil" + (f" {resto}" if resto else "") + " pesos"
    return f"{n} pesos"


# ------------------------------------------------------------------ ciclo de la tarjeta (18-11-2026)
# Los períodos van de corte a corte de la tarjeta de crédito («noviembre» = del día siguiente al corte de octubre
# hasta el corte de noviembre, inclusive), o por mes calendario si así lo elige en Hermes. Si el estado de cuenta
# trae el corte de ese mes, se usa ese; si no, el día de corte ajustable (por defecto el que más se repite en los
# cortes reales, o el 20). Si cae sábado, domingo o feriado se corre al día hábil ANTERIOR: así lo hizo el banco
# (corte del 23-08-2026, domingo, quedó el viernes 21). Todo movimiento (Visa, débito, MACH, transferencias) va al
# período que contiene su fecha, para que cada período sume lo que pasó en ese rango de días.
FERIADOS = {(1, 1), (5, 1), (5, 21), (7, 16), (8, 15), (9, 18), (9, 19), (11, 1), (12, 8), (12, 25)}
CORTES: list[str] = []   # fechas «AAAA-MM-DD» de los estados de cuenta (las deja «actualiza Hermes»)


def ajuste_periodo() -> dict:
    """Siempre el ciclo de la tarjeta, con corte el 23 (o el día hábil anterior). Desde el 18-11-2026 no hay mes
    calendario ni día ajustable: el usuario lo fijó así."""
    return {"modo": "ciclo", "dia": 23}


def dia_auto(cortes: list[str]) -> int:
    """El día de corte que más se repite en los estados de cuenta (empate: el más tarde); sin datos, el 20."""
    n: dict[int, int] = {}
    for c in cortes:
        n[int(c[8:10])] = n.get(int(c[8:10]), 0) + 1
    return max(n.items(), key=lambda x: (x[1], x[0]))[0] if n else 20


def corte(anio: int, mes: int, cortes: list[str] | None = None, dia: int = 0) -> date:
    """Fecha de corte de la tarjeta en ese mes (mes 1-12; se aceptan 0 y 13 para el año vecino)."""
    anio, mes = anio + (mes - 1) // 12, (mes - 1) % 12 + 1
    cortes = CORTES if cortes is None else cortes
    real = [c for c in cortes if c.startswith(f"{anio:04d}-{mes:02d}-")]
    if real:
        return date.fromisoformat(max(real))
    fin = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)).day
    d = date(anio, mes, min(dia or dia_auto(cortes), fin))
    while d.weekday() >= 5 or (d.month, d.day) in FERIADOS:
        d -= timedelta(days=1)
    return d


def rango(anio: int, mes: int, cfg: dict | None = None, cortes: list[str] | None = None) -> tuple[date, date]:
    """(primer día, último día) del período «mes» según el modo elegido."""
    cfg = cfg or ajuste_periodo()
    anio, mes = anio + (mes - 1) // 12, (mes - 1) % 12 + 1
    if cfg["modo"] == "mes":
        return date(anio, mes, 1), date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)
    return corte(anio, mes - 1, cortes, cfg["dia"]) + timedelta(days=1), corte(anio, mes, cortes, cfg["dia"])


def periodo_de(d: date, cfg: dict | None = None, cortes: list[str] | None = None) -> tuple[int, int]:
    """(año, mes) del período al que pertenece una fecha."""
    cfg = cfg or ajuste_periodo()
    if cfg["modo"] == "mes" or d <= corte(d.year, d.month, cortes, cfg["dia"]):
        return d.year, d.month
    return d.year + (d.month == 12), d.month % 12 + 1


def cargar() -> tuple[list[dict], dict]:
    try:
        datos = json.loads((HERMES_DIR / "movimientos.json").read_text(encoding="utf-8"))
        movs = datos.get("movimientos", [])
        CORTES[:] = sorted({c["fecha"] for c in datos.get("cortes", []) if isinstance(c, dict) and c.get("fecha")})
    except (OSError, ValueError):
        movs = []
    try:
        pres = json.loads((HERMES_DIR / "presupuestos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pres = {}
    pres = {k: v for k, v in pres.items() if not k.startswith("_") and isinstance(v, (int, float)) and v > 0}
    cls = clasificacion()
    for m in movs:
        m["_f"] = datetime.strptime(m["fecha"], "%Y-%m-%d").date()
        try:   # compra Visa: fecha de corte del estado de cuenta en que vino
            m["_c"] = date.fromisoformat(m["ciclo"]) if m.get("ciclo") else None
        except (TypeError, ValueError):
            m["_c"] = None
        m["categoria"] = (cls.get("mov") or {}).get(m.get("id")) or (cls.get("reglas") or {}).get(_plain(m.get("comercio", ""))) \
            or m.get("categoria")
    return movs, pres


def clasificacion() -> dict:
    """Lo que el usuario respondió en «¿Para qué fue?» dentro de Atlas (hud/accesos_datos.json, clave hermes)."""
    f = CLS_FILE or (Path(__file__).resolve().parent / "accesos_datos.json")
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("hermes", {}).get("clasificacion") or {}
    except (OSError, ValueError, AttributeError):
        return {}


CLS_FILE = None  # las pruebas lo cambian


def es_gasto(m: dict) -> bool:
    return m.get("monto", 0) < 0 and m.get("categoria") not in NO_GASTO


# ------------------------------------------------------------------ periodos
def periodo(t: str) -> tuple[date, date, str]:
    """(desde, hasta inclusive, cómo se dice). Por defecto: este mes."""
    h = _hoy()
    ini_mes = h.replace(day=1)
    if re.search(r"\bhoy\b", t):
        return h, h, "hoy"
    if re.search(r"\bayer\b", t):
        a = h - timedelta(days=1)
        return a, a, "ayer"
    if re.search(r"semana pasada", t):
        lun = h - timedelta(days=h.weekday() + 7)
        return lun, lun + timedelta(days=6), "la semana pasada"
    if re.search(r"\b(esta|la) semana\b|\bsemanal", t):
        return h - timedelta(days=h.weekday()), h, "esta semana"
    cfg = ajuste_periodo()
    if cfg["modo"] == "ciclo":   # «este mes», «el mes pasado», «octubre»: de corte a corte de la tarjeta
        a, m = periodo_de(h, cfg)
        if re.search(r"mes pasado|mes anterior", t):
            a, m = a - (m == 1), (m - 2) % 12 + 1
        else:
            mm = re.search(r"\b(" + "|".join(MESES) + r")\b(?:\s+(?:de|del)?\s*(\d{4}))?", t)
            if mm and not re.search(r"\b(este|el|del) ano\b|\banual|ultimo ano|los ultimos 12 meses|todo el ano", t):
                m = MESES.index(mm.group(1)) + 1
                a = int(mm.group(2)) if mm.group(2) else (a if m <= periodo_de(h, cfg)[1] else a - 1)
            elif not mm and re.search(r"\b(este|el|del) ano\b|\banual|ultimo ano|los ultimos 12 meses|todo el ano", t):
                a = None
        if a is not None:
            ini, fin = rango(a, m, cfg)
            if (a, m) == periodo_de(h, cfg):
                return ini, h, f"en este ciclo de la tarjeta, desde el {ini.day} de {MESES[ini.month - 1]}"
            return ini, min(fin, h), (f"en el ciclo de {MESES[m - 1]}" + (f" de {a}" if a != h.year else "")
                                      + f", del {ini.day} de {MESES[ini.month - 1]} al {fin.day} de {MESES[fin.month - 1]}")
    if re.search(r"mes pasado|mes anterior", t):
        fin = ini_mes - timedelta(days=1)
        return fin.replace(day=1), fin, f"en {MESES[fin.month - 1]}"
    if re.search(r"\b(este|el|del) ano\b|\banual|ultimo ano|los ultimos 12 meses|todo el ano", t):
        if re.search(r"ultimo ano|ultimos 12", t):
            return (ini_mes.replace(year=ini_mes.year - 1) + timedelta(days=0)), h, "en el último año"
        return date(h.year, 1, 1), h, f"en {h.year}"
    m = re.search(r"\b(" + "|".join(MESES) + r")\b(?:\s+(?:de|del)?\s*(\d{4}))?", t)
    if m:
        mes = MESES.index(m.group(1)) + 1
        anio = int(m.group(2)) if m.group(2) else (h.year if mes <= h.month else h.year - 1)
        ini = date(anio, mes, 1)
        fin = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1))
        return ini, min(fin, h), f"en {m.group(1)}" + (f" de {anio}" if anio != h.year else "")
    return ini_mes, h, "este mes"


def fecha_ciclo(m: dict) -> date:
    """Fecha con que cuenta un movimiento al agrupar por ciclo de la tarjeta: la suya, salvo una compra Visa que el banco
    facturó en un estado de cuenta posterior; esa cuenta el día de corte de ese estado (así cada ciclo cuadra con lo facturado)."""
    c = m.get("_c")
    if not c:
        return m["_f"]
    return m["_f"] if corte(c.year, c.month - 1) < m["_f"] <= c else c


def en(movs, ini, fin, por_ciclo: bool = False):
    return [m for m in movs if ini <= (fecha_ciclo(m) if por_ciclo else m["_f"]) <= fin]


# ------------------------------------------------------------------ qué se pregunta
_GASTO = r"(?:gast\w*|desembols\w*|se me (?:fue|fueron)|he pagado|pague)"
_ES_HERMES = re.compile(
    rf"\b(?:cuanto\s+(?:he\s+|llevo\s+|e\s+)?{_GASTO}|cuanto\s+llevo(?:\s+gastado)?\s+(?:en|este|esta|el|la)|"
    rf"como (?:van|estan|vienen) mis gastos|en que (?:he\s+)?{_GASTO}|cual (?:fue|es) mi (?:ultimo|mayor) (?:gasto|compra)|"
    rf"presupuesto|me queda (?:plata|dinero)|cuanto me queda|como voy con (?:la plata|los gastos|el presupuesto|mis gastos)|"
    rf"cuanto (?:me )?(?:ha )?(?:entrado|llegado)|cuanto recibi|mis ingresos)\b")


# Intención de ver los gastos (uso real 18-11-2026: «quiero ver mis gastos» no llegaba a Hermes): «mis gastos / mi
# gasto / mis compras / mis movimientos», o un verbo de ver/mostrar/revisar + «los gastos / las compras / los movimientos».
# «gastos de envío de un paquete» no es: no es suyo ni pide verlos. «abre mis gastos» abre la app (accesos.json).
_MIS_GASTOS = re.compile(
    r"\bmis?\s+(?:gastos?|compras|movimientos|finanzas)\b|"
    r"\b(?:ver|veo|vea|mira\w*|muestra\w*|mostrar|ensena\w*|revisa\w*|dame|lista\w*|resume\w*)\s+"
    r"(?:(?:los|las|todos los|todas las)\s+)?(?:gastos|compras|movimientos)\b(?!\s+de\s+envio)")


def es_pregunta(texto: str) -> bool:
    t = _plain(texto)
    if _ES_HERMES.search(t):
        return True
    return bool(_MIS_GASTOS.search(t)) and not re.match(r"^\W*(?:(?:atlas|jarvis)\W+)?(?:abre|abrir|abreme|abrime)\b", t)


def _categoria_pedida(t: str, movs: list[dict]) -> tuple[str | None, str | None]:
    """(categoría, comercio) mencionados después de «en …»."""
    cats = sorted({m.get("categoria", "") for m in movs if m.get("categoria")}, key=len, reverse=True)
    sin = {"comida": "Comida", "delivery": "Comida", "super": "Supermercado",
           "supermercado": "Supermercado", "transporte": "Transporte", "micro": "Transporte", "uber": None,
           "suscripciones": "Suscripciones", "salud": "Salud", "farmacia": "Salud", "compras": "Compras",
           "transferencias": "Transferencias a personas", "otros": "Otros", "educacion": "Educación"}
    m = re.search(r"\ben\s+(?:el\s+|la\s+|los\s+|las\s+)?([a-z0-9 .]+?)(?:\s+(?:este|esta|el|la|en|del|de|durante|hoy|ayer)\b|$)", t)
    if not m:
        return None, None
    palabra = m.group(1).strip(" .")
    if not palabra or palabra in MESES or re.match(r"^(que|total|todo|general|el mes|la semana|\d{4})$", palabra):
        return None, None
    for c in cats:
        if _plain(c) == palabra or _plain(c).startswith(palabra):
            return c, None
    if palabra in sin and sin[palabra]:
        return sin[palabra], None
    comercios = {_plain(x["comercio"]) for x in movs}
    if any(palabra in c for c in comercios):
        return None, palabra
    return None, None


def responder(texto: str) -> dict | None:
    t = re.sub(r"\s+", " ", re.sub(r"[¿?¡!,;:]", " ", _plain(texto))).strip()
    if not es_pregunta(t):
        return None
    movs, pres = cargar()
    if not movs:
        return {"reply": "Aún no tengo sus movimientos, señor. Diga «actualiza Hermes» y los leo de su correo."}
    ini, fin, dicho = periodo(t)
    sel = en(movs, ini, fin, "ciclo" in dicho)
    gastos = [m for m in sel if es_gasto(m)]
    total = -sum(m["monto"] for m in gastos)

    # presupuesto: qué categorías pasaron el 80 % o el límite, y cómo va la semana y el mes
    if re.search(r"presupuesto|me queda|como voy", t):
        h = _hoy()
        cfg = ajuste_periodo()
        ini_p = rango(*periodo_de(h, cfg), cfg)[0]   # inicio del mes o del ciclo de la tarjeta, según lo elegido
        mes = [m for m in en(movs, ini_p, h, cfg["modo"] == "ciclo") if es_gasto(m)]
        sem = [m for m in en(movs, h - timedelta(days=h.weekday()), h) if es_gasto(m)]
        g_mes, g_sem = -sum(m["monto"] for m in mes), -sum(m["monto"] for m in sem)
        base = f"{'Este mes' if cfg['modo'] == 'mes' else 'En este ciclo de la tarjeta'} lleva {pesos_dichos(g_mes)} gastados, y esta semana {pesos_dichos(g_sem)}."
        if not pres:
            return {"reply": f"{base} Aún no tiene presupuesto definido, señor: se fija en presupuestos.json, en la carpeta de Apolo."}
        por = {}
        for m in mes:
            por[m["categoria"]] = por.get(m["categoria"], 0) - m["monto"]
        pasados = [f"{c} ({round(por.get(c, 0) / lim * 100)} %)" for c, lim in pres.items() if por.get(c, 0) >= lim]
        cerca = [f"{c} ({round(por.get(c, 0) / lim * 100)} %)" for c, lim in pres.items() if 0.8 * lim <= por.get(c, 0) < lim]
        tot_lim = sum(pres.values())
        usado = sum(min(por.get(c, 0), lim) for c, lim in pres.items())
        partes = [base]
        if pasados:
            partes.append("Se pasó del límite en " + _y(pasados) + ".")
        if cerca:
            partes.append("Está sobre el 80 % en " + _y(cerca) + ".")
        if not pasados and not cerca:
            partes.append("Todas sus categorías están bajo el 80 %.")
        partes.append(f"Le quedan {pesos_dichos(max(0, tot_lim - usado))} de su presupuesto del mes, señor.")
        return {"reply": " ".join(partes)}

    if re.search(r"ingres|entrado|llegado|recibi", t):
        ing = sum(m["monto"] for m in sel if m.get("monto", 0) > 0 and m.get("categoria") == "Ingresos")
        dev = sum(m["monto"] for m in sel if m.get("monto", 0) > 0 and m.get("categoria") in ("Devoluciones y otros", "Extras de familia"))
        extra = f" Aparte, le devolvieron o pasaron otros {pesos_dichos(dev)}." if dev else ""
        return {"reply": f"{dicho[:1].upper() + dicho[1:]} le han entrado {pesos_dichos(ing)}, señor.{extra}"}

    if re.search(r"ultim\w* (?:gasto|compra)", t):
        ult = max((m for m in movs if es_gasto(m)), key=lambda m: m["_f"], default=None)
        if not ult:
            return {"reply": "No tengo gastos registrados, señor."}
        return {"reply": f"Su último gasto fue {pesos_dichos(ult['monto'])} en {ult['comercio']}, "
                         f"el {ult['_f'].day} de {MESES[ult['_f'].month - 1]}, señor."}

    if re.search(r"en que|mayor (?:gasto|compra)|donde", t):
        if not gastos:
            return {"reply": f"No tengo gastos {dicho}, señor."}
        por = {}
        for m in gastos:
            por[m["categoria"]] = por.get(m["categoria"], 0) - m["monto"]
        top = sorted(por.items(), key=lambda x: -x[1])[:3]
        mayor = min(gastos, key=lambda m: m["monto"])
        return {"reply": f"{dicho[:1].upper() + dicho[1:]} gastó más en " + _y([f"{c}, {pesos_dichos(v)}" for c, v in top])
                         + f". La compra más grande fue {pesos_dichos(mayor['monto'])} en {mayor['comercio']}, señor."}

    cat, comercio = _categoria_pedida(t, movs)
    if cat or comercio:
        sub = [m for m in gastos if (cat and m["categoria"] == cat) or (comercio and comercio in _plain(m["comercio"]))]
        v = -sum(m["monto"] for m in sub)
        nombre = cat or comercio.title()
        txt = f"{dicho[:1].upper() + dicho[1:]} lleva {pesos_dichos(v)} en {nombre}"
        txt += f", en {len(sub)} compra{'s' if len(sub) != 1 else ''}" if sub else ""
        if cat and cat in pres and (dicho == "este mes" or dicho.startswith("en este ciclo")):
            txt += f". Su límite es {pesos_dichos(pres[cat])}: va en {round(v / pres[cat] * 100)} %"
        return {"reply": txt + ", señor."}

    txt = f"{dicho[:1].upper() + dicho[1:]} ha gastado {pesos_dichos(total)}, señor"
    if dicho == "este mes":
        h = _hoy()
        ant_fin = h.replace(day=1) - timedelta(days=1)
        ant = -sum(m["monto"] for m in en(movs, ant_fin.replace(day=1), ant_fin.replace(day=min(h.day, ant_fin.day))) if es_gasto(m))
        if ant:
            txt += (f". A esta altura de {MESES[ant_fin.month - 1]} llevaba {pesos_dichos(ant)}")
    elif dicho.startswith("en este ciclo"):   # el ciclo anterior, hasta el mismo número de días desde su inicio
        h, cfg = _hoy(), ajuste_periodo()
        a, m = periodo_de(h, cfg)
        a0, m0 = a - (m == 1), (m - 2) % 12 + 1
        i0, f0 = rango(a0, m0, cfg)
        ant = -sum(x["monto"] for x in en(movs, i0, min(f0, i0 + (h - ini)), True) if es_gasto(x))
        if ant:
            txt += f". A esta altura del ciclo de {MESES[m0 - 1]} llevaba {pesos_dichos(ant)}"
    return {"reply": txt + "."}


def _y(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]

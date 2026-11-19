"""Fortuna (fondos mutuos) en Atlas: responde preguntas sobre los fondos con los datos de la CMF. Solo lee.

«¿cómo van los fondos?», «¿cuánto ha rentado MACH Moderado este año?», «¿cuál fondo va mejor?»,
«¿hasta cuándo hay datos de la CMF?». Lee apps\\fortuna\\fondos_cmf.json (lo baja «actualiza Fortuna»).
«¿Cómo están mis inversiones?» (18-11-2026) responde con lo SUYO: los aportes anotados en Fortuna
(~/.atlas/fortuna_aportes.json, ver atlas_fortuna_aportes.py) valorizados con el valor cuota de la CMF, igual que
la pestaña «Mis inversiones» de la página: es_mis_inversiones() y responder_mis_inversiones().
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

DATOS = Path(os.environ.get("ATLAS_FORTUNA_DATOS") or (Path(__file__).resolve().parent.parent / "apps" / "fortuna" / "fondos_cmf.json"))
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# administradoras: las de los «Otros fondos» seguidos (18-11-2026) también se reconocen por nombre
ADMS = ["bci", "mach", "scotia", "santander", "banchile", "banco de chile", "bancoestado", "banco estado", "security",
        "fintual", "larrainvial", "larrain vial", "principal", "sura"]
_ADM_ALIAS = {"mach": "bci", "banco de chile": "banchile", "banco estado": "bancoestado", "larrain vial": "larrainvial"}
_FONDO = (r"(?:fondos?(?: mutuos?)?|fortuna|liquidez|acciones usa|portafolio|deuda|money market|"
          + "|".join(ADMS) + ")")
_ES_FORTUNA = re.compile(
    rf"\b(?:(?:como|que tal) (?:van|estan|andan|vienen|va|esta|anda|viene) (?:(?:mis|los|el|mi) )?.*{_FONDO}|"
    rf"(?:cuanto|que) (?:ha |han |me ha |me han )?(?:rentad\w*|rent[oóa]\w*|rind\w*|ganad\w*|gan[oóa]\w*|subid\w*|sub[ei]\w*|bajad\w*|baj[oóa]\w*|crecid\w*).*{_FONDO}|"
    rf"{_FONDO}.*(?:cuanto (?:ha |han )?(?:rentad|rendid|ganad|subid|bajad|rent|rind|gan|sub|baj)\w*)|"
    rf"rentabilidad|rendimiento de|valor (?:de la )?cuota|(?:compara\w*|comparacion)\b.*{_FONDO}|"
    rf"(?:cual|que) fondo (?:va|anda|esta|rinde|renta|ha rendido|ha rentado|conviene|le fue)|"
    rf"(?:hasta (?:cuando|que dia)|de cuando) (?:hay |son |tengo )?(?:los )?datos (?:de (?:la )?cmf|de (?:los |mis )?fondos|de fortuna)|"
    rf"datos de la cmf)\b")


def es_pregunta(texto: str) -> bool:
    t = _plain(texto)
    if re.match(r"^(?:(?:atlas|jarvis),?\s+)?(?:abre|abrir|actualiza\w*|cierra|refresca\w*|recarga\w*)\b", t):
        return False
    if _ES_FORTUNA.search(t):
        return True
    # un fondo nombrado sin decir «fondo» ni la administradora: «¿cuánto ha rentado Risky Norris?»
    return bool(re.search(r"\b(?:cuanto|como|que tal|valor (?:de la )?cuota|compar\w*)\b", t)
                and any(re.search(rf"\b{re.escape(c)}\b", t) for c in _claves_datos()))


_CLAVES: tuple = (None, [])


def _claves_datos() -> list[str]:
    """Las palabras propias de cada fondo guardado («risky norris», «money market»), al día con el archivo."""
    global _CLAVES
    try:
        m = DATOS.stat().st_mtime_ns, str(DATOS)
    except OSError:
        return []
    if _CLAVES[0] != m:
        try:
            cl = {" ".join(_clave(f)) for f in cargar()}
        except Exception:  # noqa: BLE001
            cl = set()
        # solo frases distintivas (dos palabras o más): «moderado» o «acciones» solos no bastan
        _CLAVES = (m, sorted(c for c in cl if len(c.split()) >= 2))
    return _CLAVES[1]


def cargar() -> list[dict]:
    """Fondos de la CMF con fechas: [{nombre, valores:[(date, v)], ultimo:(date, v)}] (sin las series «historia desde»)."""
    raw = json.loads(DATOS.read_text(encoding="utf-8"))
    out = []
    for f in raw.get("funds", []):
        if re.search(r"historia desde", f.get("name", ""), re.I) or not f.get("values"):
            continue
        d0 = date.fromisoformat(f["start"])
        vals = [(d0 + timedelta(days=i), v) for i, v in enumerate(f["values"]) if v]
        # el último dato real: los fines de semana y feriados repiten el valor anterior
        k = len(vals) - 1
        while k > 0 and vals[k][1] == vals[k - 1][1]:
            k -= 1
        adm = f.get("adm") or ("BCI" if re.search(r"mach", f["name"], re.I) else "Scotia")
        out.append({"nombre": f["name"], "valores": vals[: k + 1], "ultimo": vals[k], "adm": adm,
                    "key": f"{f.get('rut', '')}-{f.get('serie', '')}",
                    "perfil": f.get("perfil"), "otro": bool(f.get("otro"))})
    return out


def valor_en(f: dict, d: date) -> float | None:
    v = None
    for dd, x in f["valores"]:
        if dd > d:
            break
        v = x
    return v


def rent(f: dict, desde: date) -> float | None:
    v0 = valor_en(f, desde)
    return (f["ultimo"][1] / v0 - 1) * 100 if v0 else None


def pct(n: float) -> str:
    """1.234 -> «1,2 %» (con signo «menos» si bajó)."""
    s = f"{abs(n):.1f}".replace(".", ",")
    return ("menos " if n < -0.05 else "") + s + " %"


def fecha(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def periodo(t: str, hasta: date) -> tuple[date, str]:
    if re.search(r"este ano|en el ano|del ano|en lo que va del ano", t):
        return date(hasta.year - 1, 12, 31), "en lo que va del año"
    if re.search(r"(?:ultimo|un) ano|12 meses|doce meses", t):
        return hasta - timedelta(days=365), "en el último año"
    if re.search(r"este mes|en el mes", t):
        return hasta.replace(day=1) - timedelta(days=1), "en lo que va del mes"
    if re.search(r"semana", t):
        return hasta - timedelta(days=7), "en la última semana"
    if re.search(r"hoy|ayer|ultimo dia", t):
        return hasta - timedelta(days=1), "en el último día"
    return hasta - timedelta(days=30), "en el último mes"


def _buscar(t: str, fondos: list[dict]) -> list[dict]:
    """Fondos nombrados en la frase («mach moderado», «liquidez», «scotia arriesgado»)."""
    hits = []
    for f in fondos:
        n, clave = _plain(f["nombre"]), _clave(f)
        banco = "mach" if "mach" in n else _plain(f["adm"])
        if n in t or (clave and all(re.search(rf"\b{re.escape(w)}\b", t) for w in clave) and (banco in t or not any(
                g is not f and _clave(g) == clave for g in fondos))):
            hits.append(f)
    adm = _adm_en(t)
    # «Santander Agresivo» con «Banchile Agresivo» también en la lista: si nombró la administradora, solo los de ella
    if adm and len(hits) > 1 and any(_adm_de(f) == adm for f in hits):
        hits = [f for f in hits if _adm_de(f) == adm or _plain(f["nombre"]) in t]
    if not hits and (re.search(r"\bmach\b(?! (?:conservador|moderado|arriesgado))", t)
                     or (adm == "bci" and not re.search(r"\bfondos\b", t))):
        hits = [f for f in fondos if _plain(f["nombre"]) == "bci mach"]
    if not hits and adm:   # «¿cómo van los fondos de Santander?»: todos los de esa administradora
        hits = [f for f in fondos if _adm_de(f) == adm]
    return hits


_RELLENO = {"scotia", "portafolio", "mach", "bci", "fondo", "mutuo"}


def _clave(f: dict) -> list[str]:
    adm = _plain(f["adm"])
    return [w for w in _plain(f["nombre"]).split() if w not in _RELLENO and w != adm]


def _adm_de(f: dict) -> str:
    return _ADM_ALIAS.get(_plain(f["adm"]), _plain(f["adm"]))


def _adm_en(t: str) -> str | None:
    for a in ADMS:
        if re.search(rf"\b{a}\b", t):
            return _ADM_ALIAS.get(a, a)
    return None


def responder(texto: str) -> dict | None:
    t = re.sub(r"\s+", " ", re.sub(r"[¿?¡!,;:]", " ", _plain(texto))).strip()
    if not es_pregunta(t):
        return None
    try:
        fondos = cargar()
    except FileNotFoundError:
        return {"reply": "Aún no tengo los datos de la CMF, señor. Diga «actualiza Fortuna» y los bajo."}
    if not fondos:
        return {"reply": "El archivo de fondos está vacío, señor. Diga «actualiza Fortuna» y lo vuelvo a bajar."}
    hasta = max(f["ultimo"][0] for f in fondos)
    al = f"Datos de la CMF al {fecha(hasta)}"

    if re.search(r"datos|cmf", t) and not re.search(r"rent|rind|gan|sub|baj|como|cual", t):
        atraso = sum(1 for i in range(1, (date.today() - hasta).days) if (hasta + timedelta(days=i)).weekday() < 5)
        extra = " Están al día." if atraso <= 2 else f" Van {atraso} días hábiles atrasados: diga «actualiza Fortuna» si quiere bajarlos."
        return {"reply": f"{al}, señor.{extra}"}

    desde, dicho = periodo(t, hasta)
    pedidos = _buscar(t, fondos)
    if pedidos and re.search(r"valor (?:de (?:la )?)?cuota|cuanto (?:vale|esta) la cuota", t):
        partes = [f"{f['nombre']}, {_num(f['ultimo'][1])} pesos al {fecha(f['ultimo'][0])}" for f in pedidos[:3]]
        return {"reply": "El valor cuota de " + _y(partes) + ", señor."}
    if len(pedidos) > 3 or (len(pedidos) > 1 and re.search(r"compar|cual (?:va|anda|le fue|rinde|renta)|mejor|peor", t)):
        rs = [(f, rent(f, desde)) for f in pedidos]
        rs = sorted(((f, r) for f, r in rs if r is not None), key=lambda x: -x[1])
        if len(rs) > 1:
            D = dicho[:1].upper() + dicho[1:]
            if len(rs) <= 3:
                return {"reply": f"{D}: {_y([f['nombre'] + ' ' + pct(r) for f, r in rs])}. "
                                 f"Le fue mejor a {rs[0][0]['nombre']}, señor. {al}."}
            return {"reply": f"{D}, de {len(rs)} fondos el que más subió fue {rs[0][0]['nombre']}, {pct(rs[0][1])}, "
                             f"y el que menos, {rs[-1][0]['nombre']}, {pct(rs[-1][1])}, señor. {al}."}
    if pedidos:
        partes = []
        for f in pedidos[:3]:
            r = rent(f, desde)
            if r is None:
                partes.append(f"{f['nombre']} no tiene datos para ese período")
                continue
            verbo = "subió" if r > 0.05 else "bajó" if r < -0.05 else "se mantuvo"
            partes.append(f"{f['nombre']} {verbo} {pct(abs(r)) if verbo != 'se mantuvo' else ''}".rstrip())
        return {"reply": f"{dicho[:1].upper() + dicho[1:]}, " + _y(partes) + f", señor. {al}."}

    # sin fondo nombrado: resumen de los suyos (los «Otros fondos» seguidos solo si los pide), el mejor y el peor
    if re.search(r"\botros fondos\b|\bfondos seguidos\b|\bdemas fondos\b", t):
        fondos = [f for f in fondos if f["otro"]] or fondos
    elif not re.search(r"\btodos los fondos\b", t):
        fondos = [f for f in fondos if not f["otro"]] or fondos
    al = f"Datos de la CMF al {fecha(max(f['ultimo'][0] for f in fondos))}"   # la fecha de estos fondos, no la de los seguidos
    rs = [(f, rent(f, desde)) for f in fondos]
    rs = [(f, r) for f, r in rs if r is not None]
    if not rs:
        return {"reply": f"No tengo datos para {dicho}, señor."}
    rs.sort(key=lambda x: -x[1])
    mejor, peor = rs[0], rs[-1]
    bajan = [f["nombre"] for f, r in rs if r < -0.05]
    txt = (f"{dicho[:1].upper() + dicho[1:]}, el que más subió fue {mejor[0]['nombre']}, {pct(mejor[1])}, "
           f"y el que menos, {peor[0]['nombre']}, {pct(peor[1])}.")
    txt += (" Ninguno bajó." if not bajan else f" Bajó {bajan[0]}." if len(bajan) == 1
            else f" Bajaron {_y(bajan)}." if len(bajan) <= 3
            else f" Bajaron {len(bajan)} de {len(rs)}.")
    return {"reply": f"{txt} {al}, señor."}


# ---------------------------------------------------------------- lo suyo: «¿cómo están mis inversiones?»
_MIAS = re.compile(
    r"\b(?:mis inversiones|mi inversion|mi cartera|mi portafolio|mis fondos|mi fondo|mis ahorros invertidos|"
    r"(?:lo|la plata|el dinero|la plata que tengo|lo que tengo) (?:que )?(?:tengo |he )?invertid[oa]|mi plata invertida|"
    r"(?:cuanto|que) (?:he |e )?(?:ganado|perdido|gane|perdi)\b.*\b(?:fondos|invertid\w*|inversion\w*|fortuna)|"
    r"(?:cuanto|que) (?:me )?(?:ha|han) (?:dado|rendido|rentado)\b.*\b(?:mis|mi) (?:fondos?|inversion\w*|plata))\b")


def es_mis_inversiones(texto: str) -> bool:
    """«¿Cómo están mis inversiones?», «¿cómo van mis fondos?», «¿cuánto he ganado con mis fondos?»: lo que USTED tiene.
    No si nombra un fondo o una administradora («¿cuánto rentó MACH Moderado?» es el mercado), ni «abre mis fondos»."""
    t = re.sub(r"\s+", " ", re.sub(r"[¿?¡!,;:.]", " ", _plain(texto))).strip()
    t = re.sub(r"^(?:oye |atlas |jarvis )+", "", t)
    if re.match(r"^(?:abre|abrir|actualiza\w*|cierra|refresca\w*|recarga\w*|anota\w*|agrega\w*|borra\w*)\b", t):
        return False
    # «muéstrame mis fondos» abre la página de Fortuna (acceso), no es una pregunta
    if re.search(r"\b(?:muestra\w*|ensena\w*|abre\w*|abrir|ve a|ir a|anda a|pon(?:me)?)\b", t):
        return False
    if not _MIAS.search(t) or re.search(r"\b(?:otros|todos los|demas) fondos\b|\bdatos\b|\bcmf\b|valor (?:de (?:la )?)?cuota", t):
        return False
    if _adm_en(t) or any(re.search(rf"\b{re.escape(c)}\b", t) for c in _claves_datos()):
        return False
    return True


def _pesos(n: float) -> str:
    """1234567.8 -> «1.234.568 pesos»."""
    return f"{round(abs(n)):,}".replace(",", ".") + " pesos"


def _gano(g: float, base: float) -> str:
    """«ganó 12.345 pesos (0,8 %)» / «perdió …» / «se mantuvo»."""
    p = g / base * 100 if base else 0.0
    if abs(g) < 1 and abs(p) < 0.05:
        return "no ha ganado ni perdido"
    return f"{'ganó' if g > 0 else 'perdió'} {_pesos(g)} ({pct(abs(p))})"


def posiciones(fondos: list[dict], aportes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Agrupa los aportes por fondo y los valoriza como la página (cuotas = monto / valor cuota del día del aporte).
    -> (posiciones [{f, aportes:[{monto, fecha, cuotas}], puesto, ahora, sin_valor}], aportes de fondos sin datos)."""
    por_key = {f["key"]: f for f in fondos}
    pos: dict[str, dict] = {}
    sueltos = []
    for a in aportes:
        f = por_key.get(a["key"])
        d = date.fromisoformat(a["date"])
        v0 = valor_en(f, d) if f else None
        if not v0:
            sueltos.append(a)
            continue
        p = pos.setdefault(f["key"], {"f": f, "aportes": [], "puesto": 0.0, "ahora": 0.0, "sin_valor": False})
        cuotas = a["amount"] / v0
        p["aportes"].append({"monto": a["amount"], "fecha": d, "cuotas": cuotas})
        p["puesto"] += a["amount"]
        p["ahora"] += cuotas * f["ultimo"][1]
        p["sin_valor"] |= d > f["ultimo"][0]   # aporte posterior al último dato de la CMF: vale lo que puso
    return list(pos.values()), sueltos


def _cambio_desde(ps: list[dict], desde: date) -> tuple[float, float]:
    """Ganancia en el período y la base sobre la que se mide: lo que valía al inicio más lo que aportó después."""
    base = ahora = 0.0
    for p in ps:
        for a in p["aportes"]:
            v = valor_en(p["f"], desde) if a["fecha"] <= desde else None
            base += a["cuotas"] * v if v else a["monto"]
        ahora += p["ahora"]
    return ahora - base, base


def responder_mis_inversiones(texto: str, aportes: list[dict] | None = None) -> dict | None:
    if not es_mis_inversiones(texto):
        return None
    t = re.sub(r"\s+", " ", re.sub(r"[¿?¡!,;:.]", " ", _plain(texto))).strip()
    if aportes is None:
        import atlas_fortuna_aportes
        aportes = atlas_fortuna_aportes.leer()["aportes"]
    if not aportes:
        return {"reply": "Aún no tiene inversiones anotadas en Fortuna, señor. Ábrala y anote sus aportes en "
                         "«Mis inversiones»; si quiere ver cómo se movió el mercado, pregunte «¿cómo van los fondos?»."}
    try:
        fondos = cargar()
    except FileNotFoundError:
        return {"reply": "Aún no tengo los valores cuota de la CMF para calcular sus inversiones, señor. "
                         "Diga «actualiza Fortuna» y los bajo."}
    ps, sueltos = posiciones(fondos, aportes)
    if not ps:
        return {"reply": "No encuentro los fondos de sus aportes en los datos de la CMF, señor. "
                         "Diga «actualiza Fortuna» y vuelva a preguntar."}
    hasta = max(p["f"]["ultimo"][0] for p in ps)
    puesto = sum(p["puesto"] for p in ps)
    ahora = sum(p["ahora"] for p in ps)
    primero = min(a["fecha"] for p in ps for a in p["aportes"])
    partes = [f"Sus inversiones valen {_pesos(ahora)}. Aportó {_pesos(puesto)} y desde entonces "
              f"{_gano(ahora - puesto, puesto)}."]

    # un período: el que pidió («este año», «esta semana») o, si invirtió hace más de un mes, el último mes
    pidio = re.search(r"este ano|en el ano|del ano|ultimo ano|un ano|12 meses|doce meses|este mes|en el mes|"
                      r"semana|hoy|ayer|ultimo dia|ultimo mes|un mes|30 dias", t)
    desde, dicho = periodo(t, hasta)
    if desde > primero and (pidio or (hasta - primero).days > 31):
        g, base = _cambio_desde(ps, desde)
        partes.append(f"{dicho[:1].upper() + dicho[1:]} {_gano(g, base)}.")
    elif pidio:
        partes.append(f"Invirtió el {fecha(primero)}, así que no hay más historia que esa.")

    # cada inversión, de la que mejor va a la que peor (pedido 18-11-2026: una por una, aunque esté en cero)
    rp = lambda p: (p["ahora"] / p["puesto"] - 1) * 100   # noqa: E731
    rs = sorted(ps, key=lambda p: -rp(p))
    if len(rs) > 1:
        partes.append(f"Fondo por fondo:")
    for p in rs:
        g = _gano(p["ahora"] - p["puesto"], p["puesto"])
        if g == "no ha ganado ni perdido":
            g += " (0,0 %)"
        extra = ""
        if p["sin_valor"]:
            ult = max(a["fecha"] for a in p["aportes"])
            extra = f", porque el aporte del {ult.day} de {MESES[ult.month - 1]} aún no tiene valor cuota publicado"
        partes.append(f"{p['f']['nombre']}: aportó {_pesos(p['puesto'])}, hoy vale {_pesos(p['ahora'])} y {g}{extra}.")
    if len(rs) > 2 and abs(rp(rs[0]) - rp(rs[-1])) >= 0.05:
        partes.append(f"El que mejor va es {rs[0]['f']['nombre']} y el que peor, {rs[-1]['f']['nombre']}.")

    # meta y pérdida máxima que anotó en la página
    avisos = []
    for p in ps:
        rp = (p["ahora"] / p["puesto"] - 1) * 100
        metas = [a.get("target") for a in aportes if a["key"] == p["f"]["key"] and a.get("target")]
        topes = [a.get("stop") for a in aportes if a["key"] == p["f"]["key"] and a.get("stop")]
        if metas and rp >= min(metas):
            avisos.append(f"{p['f']['nombre']} ya llegó a su meta de {pct(min(metas))}")
        elif topes and rp <= -max(topes):
            avisos.append(f"{p['f']['nombre']} pasó su pérdida máxima de {pct(max(topes))}")
    if avisos:
        partes.append(_y(avisos)[:1].upper() + _y(avisos)[1:] + ".")
    if sueltos:
        partes.append(f"{len(sueltos)} aporte{'s' if len(sueltos) > 1 else ''} no se pudo valorizar porque su fondo "
                      f"no tiene datos para esa fecha.")
    partes.append(f"Valores cuota de la CMF al {fecha(hasta)}, señor.")
    return {"reply": " ".join(partes)}


def _num(v: float) -> str:
    """1234.5 -> «1.234,50»."""
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _y(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]

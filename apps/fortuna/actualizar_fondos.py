"""Actualiza "Mis Fondos Mutuos" con los valores cuota más recientes de la CMF.

Uso (Python 3.8+, sin librerías extra):
    python actualizar_fondos.py              # toda la historia; luego solo lo nuevo
    python actualizar_fondos.py --completo   # vuelve a bajar toda la historia

Lee la lista de fondos de FONDOS (abajo), consulta la página pública
"Valores Cuota" de cada fondo en cmfchile.cl, guarda fondos_cmf.json y
regenera mis_fondos.html con los datos nuevos. Luego lo abre en el navegador.

No usa claves ni datos del banco: solo información pública de la CMF.
"""
import argparse
import datetime as dt
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# (RUN sin dígito verificador, serie, nombre a mostrar)
# Agrega o quita fondos aquí. La serie debe existir en la CMF para ese fondo.
FONDOS = [
    ("10358", "DIGITAL", "Bci MACH"),
    ("10580", "DIGITAL", "MACH Conservador"),
    ("10579", "DIGITAL", "MACH Moderado"),
    ("10578", "DIGITAL", "MACH Arriesgado"),
    ("8886", "WEB", "Scotia Portafolio Conservador"),
    ("8741", "WEB", "Scotia Portafolio Moderado"),
    ("8116", "WEB", "Scotia Portafolio Arriesgado"),
    ("8187", "WEB", "Scotia Liquidez"),
    ("8480", "WEB", "Scotia Acciones USA"),
    ("8292", "WEB", "Scotia Deuda Mediano Plazo"),
    # Historia larga (serie APV, disponible desde 2010-2016) para el simulador
    ("8116", "APV", "Scotia Portafolio Arriesgado (historia desde 2011)", "2011-01-01"),
    ("8741", "APV", "Scotia Portafolio Moderado (historia desde 2010)", "2010-01-01"),
    ("8886", "APV", "Scotia Portafolio Conservador (historia desde 2012)", "2012-01-01"),
    ("8292", "APV", "Scotia Deuda Mediano Plazo (historia desde 2016)", "2016-01-01"),
]

# «Otros fondos»: fondos de otras administradoras que solo se siguen (no hay plata invertida en ellos).
# (RUN, serie, nombre, administradora, perfil). Serie pública general (sin APV ni institucional), la con
# más partícipes en la CMF al 16-11-2026. Historia desde 2021.
OTROS_DESDE = "2021-01-01"
OTROS = [
    ("8037", "CLASI", "BCI Depósito Efectivo", "BCI", "conservador"),
    ("8639", "CLASI", "BCI Cartera Dinámica Balanceada", "BCI", "moderado"),
    ("9372", "ADC", "BCI Acciones Globales", "BCI", "agresivo"),
    ("8057", "UNIVE", "Santander Money Market", "Santander", "conservador"),
    ("8280", "UNIVE", "Santander Renta Mediano Plazo", "Santander", "deuda"),
    ("8911", "GLOBAL", "Santander Equilibrio", "Santander", "moderado"),   # la DIGITAL es nueva (2026), sin historia
    ("8372", "GLOBA", "Santander Acciones Selectas Chile", "Santander", "agresivo"),
    ("8026", "A", "Banchile Capital Financiero", "Banchile", "conservador"),
    ("10060", "DIGITAL", "Banchile Moderado", "Banchile", "moderado"),
    ("8078", "L", "Banchile Inversión USA", "Banchile", "agresivo"),
    ("8319", "C", "BancoEstado Solvente", "BancoEstado", "conservador"),
    ("8845", "CLASI", "BancoEstado Perfil C", "BancoEstado", "moderado"),
    ("8536", "CLASI", "BancoEstado Acciones Nacionales", "BancoEstado", "agresivo"),
    ("8253", "A", "Security Plus", "Security", "conservador"),          # hoy los administra BICE Inversiones
    ("8336", "A", "Security Balanceado Estratégico", "Security", "moderado"),
    ("8118", "A", "Security Gold", "Security", "agresivo"),
    ("9730", "A", "Fintual Very Conservative Streep", "Fintual", "conservador"),
    ("9568", "A", "Fintual Conservative Clooney", "Fintual", "deuda"),
    ("9569", "A", "Fintual Moderate Pitt", "Fintual", "moderado"),
    ("9570", "A", "Fintual Risky Norris", "Fintual", "agresivo"),
    ("8177", "A", "LarrainVial Monetario", "LarrainVial", "conservador"),
    ("8755", "A", "LarrainVial Ahorro a Plazo", "LarrainVial", "deuda"),
    ("8872", "A", "LarrainVial Acciones Nacionales", "LarrainVial", "agresivo"),
    ("8422", "INV", "Principal Deuda Mediano Plazo", "Principal", "deuda"),
    ("9594", "G", "Principal Gestión Activa Moderado", "Principal", "moderado"),
    ("8113", "INV", "Principal USA Equity", "Principal", "agresivo"),
    ("8678", "A", "Sura Renta Depósito Chile", "Sura", "conservador"),
    ("9474", "A", "Sura Multiactivo Moderado", "Sura", "moderado"),
    ("8915", "A", "Sura Selección Acciones USA", "Sura", "agresivo"),
]

BASE = "https://www.cmfchile.cl/institucional/mercados/entidad.php"
HERE = Path(__file__).resolve().parent
HTML_FILE = HERE / "mis_fondos.html"
JSON_FILE = HERE / "fondos_cmf.json"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = [("User-Agent", "Mozilla/5.0 (fondos-mutuos-dashboard)")]


def get(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    for intento in range(3):
        try:
            with opener.open(url, body, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # red inestable: reintenta
            if intento == 2:
                raise
            time.sleep(2 * (intento + 1))


def num(s):
    s = s.strip().replace(".", "").replace(",", ".")
    return float(s) if s else None


def descargar(rut, serie, desde, hasta):
    params = dict(mercado="V", rut=rut, grupo="", tipoentidad="RGFMU", row="",
                  vig="VI", control="svs", pestania="7")
    url = BASE + "?" + urllib.parse.urlencode(params)
    get(url)  # abre sesión
    form = dict(params, ddi=f"{desde.day:02d}", mmi=f"{desde.month:02d}", aai=str(desde.year),
                ddf=f"{hasta.day:02d}", mmf=f"{hasta.month:02d}", aaf=str(hasta.year), se=serie)
    page = get(url, form)
    m = re.search(r"ventana\('([^']+)'", page)
    if not m:
        raise RuntimeError("la CMF no devolvió el enlace de descarga (¿serie o RUN incorrectos?)")
    tabla = get(urllib.parse.urljoin(url, html.unescape(m.group(1))))
    filas = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tabla, re.S):
        celdas = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(celdas) >= 8 and re.fullmatch(r"\d\d/\d\d/\d{4}", celdas[0]):
            d, mth, y = celdas[0].split("/")
            filas.append((dt.date(int(y), int(mth), int(d)), num(celdas[4]), num(celdas[5]), celdas[7]))
    if not filas:
        raise RuntimeError("no se encontraron valores cuota en el rango pedido")
    filas.sort()
    # serie diaria continua (rellena días faltantes con el último valor conocido)
    inicio, fin = filas[0][0], filas[-1][0]
    por_dia = {f[0]: f[1] for f in filas if f[1]}
    valores, ultimo, d = [], None, inicio
    while d <= fin:
        ultimo = por_dia.get(d, ultimo)
        valores.append(ultimo)
        d += dt.timedelta(days=1)
    return {"start": inicio.isoformat(), "values": valores, "aum": filas[-1][2],
            "participes": int(filas[-1][3].replace(".", "") or 0)}


def descargar_por_anios(rut, serie, desde, hasta):
    """La CMF responde mejor con consultas de un año; une los tramos."""
    tramos, a = [], desde
    while a <= hasta:
        b = min(dt.date(a.year, 12, 31), hasta)
        try:
            tramos.append(descargar(rut, serie, a, b))
        except RuntimeError:
            pass  # año sin datos para esa serie
        a = dt.date(a.year + 1, 1, 1)
    # La CMF no responde si la consulta parte antes de que existiera la serie,
    # así que el año en que nació queda vacío: se prueba mes a mes desde enero.
    if tramos:
        primero = dt.date.fromisoformat(tramos[0]["start"])
        y = primero.year - 1
        if primero == dt.date(primero.year, 1, 1) and y >= desde.year:
            for m in range(1, 13):
                try:
                    tramos.insert(0, descargar(rut, serie, max(dt.date(y, m, 1), desde), dt.date(y, 12, 31)))
                    break
                except RuntimeError:
                    pass
    if not tramos:
        raise RuntimeError("no se encontraron valores cuota")
    inicio = dt.date.fromisoformat(tramos[0]["start"])
    valores = []
    for t in tramos:
        off = (dt.date.fromisoformat(t["start"]) - inicio).days
        while len(valores) < off:
            valores.append(valores[-1] if valores else None)
        valores[off:] = t["values"]
    return {"start": inicio.isoformat(), "values": valores, "aum": tramos[-1]["aum"], "participes": tramos[-1]["participes"]}


def unir(viejo, nuevo):
    """Une una serie guardada con un tramo nuevo (el tramo nuevo manda donde se cruzan)."""
    s0 = dt.date.fromisoformat(viejo["start"])
    off = (dt.date.fromisoformat(nuevo["start"]) - s0).days
    vals = list(viejo["values"][:max(off, 0)])
    while len(vals) < off:
        vals.append(vals[-1] if vals else None)
    vals += nuevo["values"]
    return {"start": viejo["start"], "values": vals, "aum": nuevo["aum"], "participes": nuevo["participes"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2005-01-01", help="fecha inicial AAAA-MM-DD (por defecto, toda la historia)")
    ap.add_argument("--completo", action="store_true", help="volver a bajar toda la historia aunque ya esté guardada")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador al terminar")
    a = ap.parse_args()
    desde = dt.date.fromisoformat(a.desde)
    hasta = dt.date.today()

    guardados = {}
    if JSON_FILE.exists() and not a.completo:
        try:
            for f in json.loads(JSON_FILE.read_text(encoding="utf-8"))["funds"]:
                guardados[(f["rut"], f["serie"], f["name"])] = f
        except Exception:
            guardados = {}

    funds = []
    lista = [(rut, serie, nombre, extra[0] if extra else None, {}) for rut, serie, nombre, *extra in FONDOS]
    lista += [(rut, serie, nombre, OTROS_DESDE, {"adm": adm, "perfil": perfil, "otro": True})
              for rut, serie, nombre, adm, perfil in OTROS]
    for rut, serie, nombre, inicio_txt, meta in lista:
        inicio = dt.date.fromisoformat(inicio_txt) if inicio_txt else desde
        print(f"Descargando {nombre} (RUN {rut}, serie {serie})...", end=" ", flush=True)
        try:
            viejo = guardados.get((rut, serie, nombre))
            if viejo and viejo.get("completo") and len(viejo["values"]) > 30:
                # ya tenemos la historia: solo baja las últimas semanas y las une
                desde_nuevo = dt.date.fromisoformat(viejo["start"]) + dt.timedelta(days=len(viejo["values"]) - 15)
                datos = unir(viejo, descargar_por_anios(rut, serie, desde_nuevo, hasta))
            else:
                datos = descargar_por_anios(rut, serie, inicio, hasta)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        funds.append(dict(rut=rut, name=nombre, serie=serie, completo=True, **datos, **meta))
        print(f"ok, último dato {dt.date.fromisoformat(datos['start']) + dt.timedelta(days=len(datos['values']) - 1):%d/%m/%Y}")

    if not funds:
        sys.exit("No se pudo descargar ningún fondo. Revisa tu conexión a internet.")

    payload = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "source": "CMF Chile", "funds": funds}
    JSON_FILE.write_text(json.dumps(payload), encoding="utf-8")

    page = HTML_FILE.read_text(encoding="utf-8")
    data = json.dumps(payload).replace("</", "<\\/")
    page, n = re.subn(r'(<script id="fund-data" type="application/json">).*?(</script>)',
                      lambda m: m.group(1) + data + m.group(2), page, count=1, flags=re.S)
    if n != 1:
        sys.exit("No encontré el bloque de datos en mis_fondos.html")
    if "<html" not in page.lower():  # el archivo del artifact no trae esqueleto: lo agregamos
        page = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
                + page + "</body></html>")
    HTML_FILE.write_text(page, encoding="utf-8")
    print(f"\nListo: {HTML_FILE}")
    if not a.no_abrir:
        webbrowser.open(HTML_FILE.as_uri())


if __name__ == "__main__":
    main()

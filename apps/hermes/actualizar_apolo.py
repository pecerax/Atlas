"""Apolo: junta tus movimientos de Scotiabank, MACH y transferencias recibidas desde tu Gmail.

Solo LEE correos (nunca borra, marca ni envía nada) usando la cuenta principal de Atlas
(~/.atlas/connectors/gmail_imap.json). No usa claves del banco.

Lo corre Atlas cuando dices «actualiza Apolo» (con el Python de Atlas), o a mano:
    <Python de Atlas> actualizar_apolo.py

Deja todo en esta carpeta:
    movimientos.json   todos los movimientos (se va sumando; no se pierde lo ya leído)
    apolo.html         la pantalla, con los datos adentro
    cartolas\\         PDF de cartolas y estados de cuenta descargados del correo
Se edita a mano:
    categorias.json    palabras -> categoría
    presupuestos.json  límite mensual por categoría (en pesos)
"""
from __future__ import annotations

import email
import hashlib
import html as _html
import io
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from email.header import decode_header, make_header
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESDE = "18-Nov-2026"  # 18-11-2026: el usuario partió Hermes desde cero; nada anterior a hoy se importa
MOV_FILE = HERE / "movimientos.json"
CAT_FILE = HERE / "categorias.json"
PRES_FILE = HERE / "presupuestos.json"
CARTOLAS = HERE / "cartolas"

# Avisos push del banco que guarda el celular (MacroDroid escribe una línea por aviso; Syncthing la trae al PC):
#   @@|2026-11-18 1:05|Scotiabank|Compra aprobada|Compra por $12.345 en LIDER con tu tarjeta...
AVISOS_DIR = Path(os.environ.get("AVISOS_BANCO_DIR") or (Path.home() / ".atlas" / "avisos_banco"))

# Correos que se leen (remitente, asunto) -> lector
# Depuración (18-11-2026, pedido del usuario): Hermes usa solo DOS fuentes: las transferencias que llegan por correo y
# los demás pagos por los avisos del celular. No se leen cartolas, estados de cuenta ni compras de MACH por correo (los
# PDF siguen en «cartolas», sin borrar: para volver atrás, poner esto en False y correr «actualiza Hermes»).
SOLO_CORREO_Y_AVISOS = True
LECTORES_APAGADOS = {"mach_compra", "adjunto_pdf"}

FUENTES = [
    ('FROM "contacto@mail.machbank.cl" SUBJECT "Tu compra con MACH"', "mach_compra"),
    ('FROM "avisos.info@scotiabank.cl" SUBJECT "Transferencia"', "scotia_transferencia"),
    ('FROM "avisos.info@scotiabank.cl" SUBJECT "comprobante de pago"', "scotia_pago_tarjeta"),
    ('SUBJECT "Transferencia de Fondos" FROM "bci.cl"', "recibida_generica"),
    ('SUBJECT "Has recibido una transferencia"', "recibida_generica"),
    ('FROM "bancochile.cl" SUBJECT "Transferencia"', "recibida_otros"),
    ('FROM "santander.cl" SUBJECT "Transferencia"', "recibida_otros"),
    ('FROM "bancofalabella.com" SUBJECT "recibida"', "recibida_otros"),
    ('FROM "somosmach.com" SUBJECT "Recibiste una transferencia"', "recibida_otros"),
    # fondos mutuos MACH: solo el aporte y el rescate ya abonado. «Solicitaste un rescate», «fecha del rescate» y
    # «tu aporte se encuentra rentando» no se leen: traen montos estimados o solo informan, y duplicarían el movimiento.
    ('FROM "somosmach.com" SUBJECT "aporte a Fondos Mutuos"', "mach_ffmm"),
    ('FROM "machbank.cl" SUBJECT "rescate se encuentra en tu cuenta"', "mach_ffmm"),
    # fondos mutuos Scotiabank: los datos vienen en un PDF adjunto con clave (la de Atlas-Hermes-PDF); se abre en memoria
    ('FROM "productos.info@scotiabank.cl" SUBJECT "Comprobante Aporte o Rescate Fondos Mutuos"', "scotia_ffmm"),
    ('FROM "cartolas.info@scotiabank.cl"', "adjunto_pdf"),
    ('FROM "eeccdigital.cl"', "adjunto_pdf"),
    ('FROM "machbank" SUBJECT "Cartola Cuenta Corriente MACHBANK"', "adjunto_pdf"),
]

CATEGORIAS_BASE = {
    "Comida": ["pedidos ya", "pedidosya", "rappi", "uber eats", "ubereats", "didi food", "justo", "mcdonald",
                          "burger", "starbucks", "juan maestro", "dominos", "papa john", "sushi", "restaurant", "cafe"],
    "Supermercado": ["lider", "jumbo", "unimarc", "santa isabel", "tottus", "acuenta", "oxxo", "ok market", "spid"],
    "Transporte": ["uber", "didi", "cabify", "metro", "bip", "red movilidad", "copec", "shell", "aramco", "petrobras", "movired"],
    "Suscripciones": ["spotify", "netflix", "youtube", "google", "apple", "disney", "hbo", "max ", "prime video", "openai",
                      "anthropic", "claude", "steam", "playstation", "xbox", "icloud", "microsoft"],
    "Salud": ["cruz verde", "salcobrand", "ahumada", "farmacia", "clinica", "isapre", "dental"],
    "Compras": ["falabella", "ripley", "paris", "mercadolibre", "mercado libre", "aliexpress", "temu", "shein", "amazon"],
    "Educación": ["universidad", "u de chile", "uchile", "libreria", "apunte"],
    "Transferencias a personas": [],
}


def log(*a):
    print(*a, flush=True)


def cargar(path: Path, defecto):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def guardar(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def texto_de(m: email.message.Message) -> str:
    partes = []
    for p in m.walk():
        ct = p.get_content_type()
        if ct in ("text/plain", "text/html") and not p.get_filename():
            raw = p.get_payload(decode=True) or b""
            s = raw.decode(p.get_content_charset() or "utf-8", errors="replace")
            if ct == "text/html":
                s = re.sub(r"(?is)<(style|script|head).*?</\1>", " ", s)
                s = re.sub(r"(?s)<[^>]+>", " ", s)
                s = _html.unescape(s)
            partes.append(re.sub(r"\s+", " ", s).strip())
    return max(partes, key=len) if partes else ""


def monto(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def fecha_ddmmyyyy(s: str) -> str:
    d, m, y = s.split("/")
    return f"{y}-{m}-{d}"


def campo(t: str, nombre: str, hasta: str) -> str:
    m = re.search(rf"{nombre}\s*:?\s*(.+?)\s+(?:{hasta})", t)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ lectores (devuelven dict o None)
def mach_compra(t: str, fecha_correo: str) -> dict | None:
    m = re.search(r"Total\s+\$?\s*([\d.]+)\s+Comercio\s+(.+?)\s+(?:Mensaje|C.digo)", t)
    if not m:
        return None
    f = re.search(r"Fecha y hora de pago\s+(\d{2}/\d{2}/\d{4})", t)
    return {"fecha": fecha_ddmmyyyy(f.group(1)) if f else fecha_correo, "comercio": m.group(2).strip(),
            "monto": -monto(m.group(1)), "banco": "MACH", "tipo": "compra"}


def scotia_transferencia(t: str, fecha_correo: str) -> dict | None:
    if "realizada" not in t:
        return None
    dest = campo(t, "Nombre Destinatario", "N.mero de Cuenta")
    mo = re.search(r"Monto\s*:\s*\$?\s*([\d.]+)", t)
    f = re.search(r"fecha de hoy\s+(\d{2}/\d{2}/\d{4})", t)
    if not mo:
        return None
    banco_dest = campo(t, "Banco", "Monto")
    return {"fecha": fecha_ddmmyyyy(f.group(1)) if f else fecha_correo, "comercio": dest or "Transferencia",
            "detalle": banco_dest.title(), "monto": -monto(mo.group(1)), "banco": "Scotiabank", "tipo": "transferencia"}


def scotia_pago_tarjeta(t: str, fecha_correo: str) -> dict | None:
    mo = re.search(r"Total pagado\s+\$?\s*([\d.]+)", t)
    f = re.search(r"con fecha\s+(\d{2}/\d{2}/\d{4})", t)
    if not mo:
        return None
    # Se guarda, pero NO cuenta como gasto: las compras de la tarjeta ya se cuentan una por una.
    return {"fecha": fecha_ddmmyyyy(f.group(1)) if f else fecha_correo, "comercio": "Pago tarjeta de crédito",
            "monto": -monto(mo.group(1)), "banco": "Scotiabank", "tipo": "pago_tarjeta", "categoria": "Pago de tarjeta"}


def recibida_generica(t: str, fecha_correo: str) -> dict | None:
    if not re.search(r"Has recibido una transferencia", t, re.I):
        return None
    de = re.search(r"transferencia de fondos de\s+(.+?)(?:\.\s|\s+hacia tu cuenta)", t, re.I)
    mo = re.search(r"Monto recibido\s+\$?\s*([\d.]+)", t)
    f = re.search(r"Fecha de la transferencia\s+(\d{2}/\d{2}/\d{4})", t)
    msg = re.search(r"Mensaje\s+(.+?)\s+N.mero de comprobante", t)
    if not mo:
        return None
    return {"fecha": fecha_ddmmyyyy(f.group(1)) if f else fecha_correo, "comercio": (de.group(1).title() if de else "Transferencia recibida"),
            "detalle": msg.group(1).strip() if msg else "", "monto": monto(mo.group(1)), "banco": "Scotiabank",
            "tipo": "ingreso", "categoria": "Ingresos"}


# Transferencias que te llegan desde otros bancos: (quién, monto, fecha, mensaje) según el formato de cada banco
_RECIBIDAS = [
    # Banco de Chile
    (r"nuestro\(a\) cliente (.+?) ha efectuado una transferencia", r"Monto \$\s*([\d.]+)", r"Fecha (\d{2}/\d{2}/\d{4})", None),
    (r"Le informamos que (.+?) le ha transferido", r"transferido \$\s*([\d.]+)", r"Fecha (\d{2}/\d{2}/\d{4})", None),
    # Santander
    (r"nuestro cliente (.+?) realiz. una transferencia a tu cuenta", r"Monto transferido \$\s*([\d.]+)", r"con fecha (\d{2}/\d{2}/\d{4})",
     r"Comentario (.+?) Antes de imprimir"),
    # Banco Falabella
    (r"nuestro\(a\) cliente (.+?) ha instruido una transferencia", r"Monto transferencia \$\s*([\d.]+)", r"hoy, (\d{2}-\d{2}-\d{4})",
     r"Asunto\s*(.+?)\s*Monto"),
    # MACH
    (r"recibir una transferencia de (.+?) sin costo", r"Monto \$\s*([\d.]+)", r"Fecha (\d{2}/\d{2}/\d{4})", r"Mensaje (.*?) C.digo"),
]


def recibida_otros(t: str, fecha_correo: str) -> dict | None:
    for quien, mo_re, f_re, msg_re in _RECIBIDAS:
        q = re.search(quien, t)
        mo = q and re.search(mo_re, t)
        if not (q and mo):
            continue
        f = re.search(f_re, t)
        msg = re.search(msg_re, t) if msg_re else None
        fecha = fecha_ddmmyyyy(f.group(1).replace("-", "/")) if f else fecha_correo
        return {"fecha": fecha, "comercio": q.group(1).strip().title(), "detalle": msg.group(1).strip() if msg else "",
                "monto": monto(mo.group(1)), "banco": "Scotiabank", "tipo": "ingreso", "categoria": "Ingresos"}
    return None


def _fecha_corta(s: str) -> str:
    """dd/mm/aaaa o dd/mm/aa -> aaaa-mm-dd."""
    d, m, y = s.split("/")
    return f"{y if len(y) == 4 else '20' + y}-{int(m):02d}-{int(d):02d}"


def mach_ffmm(t: str, fecha_correo: str) -> dict | None:
    """Aporte o rescate (ya en tu cuenta) de un fondo mutuo MACH. Es «inversion»: ni gasto ni ingreso, y no se borra
    con las compras de MACH por correo (esas son tipo «compra»)."""
    ap = re.search(r"Monto invertido\s+\$?\s*([\d.]+)", t)
    rs = re.search(r"Monto rescatado\s+\$?\s*([\d.]+)", t)
    mo = ap or rs
    if not mo or re.search(r"referencial|estimad", t, re.I):
        return None
    n = monto(mo.group(1))
    if n <= 0:
        return None
    # el aporte trae su «Fecha»; el rescate trae la «Fecha de operación» (el día que lo pediste): la plata llegó a tu
    # cuenta el día de este correo, así que para el rescate vale la fecha del correo
    f = re.search(r"Fecha\s+(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\b", t) if ap else None
    fondo = re.search(r"Nombre del fondo\s+(.+?)\s+(?:Nombre|RUT|Fecha|N.\s*de)\b", t)
    op = re.search(r"N.\s*de operaci.n\s+([0-9A-Za-z-]{4,})", t)
    nombre = re.sub(r"(?i)^fondo mutuo\s+", "", fondo.group(1).strip()).title() if fondo else ""
    mov = {"fecha": _fecha_corta(f.group(1)) if f else fecha_correo,
           "comercio": f"Fondos mutuos ({'inversión' if ap else 'rescate'})" + (f" · {nombre}" if nombre else ""),
           "monto": -n if ap else n, "banco": "MACH", "tipo": "inversion", "categoria": "Inversiones"}
    if op:
        mov["operacion"] = op.group(1)
    return mov


def misma_operacion(mov: dict, movs: dict) -> bool:
    """¿Ya hay un movimiento del mismo banco con ese N° de operación y el mismo sentido (aporte o rescate)?"""
    op = mov.get("operacion")
    return bool(op) and any(o.get("operacion") == op and o.get("banco") == mov.get("banco")
                            and (o.get("monto", 0) > 0) == (mov.get("monto", 0) > 0) for o in movs.values())


def _monto_decimal(s: str) -> int:
    """«1234567.0000» (punto decimal, como el comprobante de fondos), «1.234.567» o «1.234.567,50» -> pesos enteros."""
    s = s.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        return int(float(s.replace(".", "").replace(",", ".")) + 0.5)   # medio peso hacia arriba, como el banco
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return int(float(s) + 0.5)
    return monto(s)


def scotia_ffmm(t: str, fecha_correo: str) -> dict | None:
    """Texto del PDF «Comprobante de aporte / rescate» de los fondos mutuos Scotiabank -> movimiento «inversion»."""
    rescate = bool(re.search(r"COMPROBANTE DE RESCATE|Monto (?:del )?Rescate", t, re.I))
    aporte = bool(re.search(r"COMPROBANTE DE APORTE|Monto (?:del )?Aporte", t, re.I))
    if rescate == aporte:
        return None   # no se sabe qué es: mejor no inventar
    clase = "Rescate" if rescate else "Aporte"
    mo = re.search(rf"Monto (?:del |total del )?{clase}\w*\s*:\s*\$?\s*([\d.,]+)", t, re.I)
    n = _monto_decimal(mo.group(1)) if mo else 0
    if n <= 0:
        return None
    f = re.search(rf"Fecha (?:de(?:l)? )?{clase}\w*\s*:\s*(\d{{1,2}}/\d{{1,2}}/(?:\d{{4}}|\d{{2}}))", t, re.I)
    fondo = re.search(r"Nombre Fondo Mutuo\s*:\s*(.+)", t)
    serie = re.search(r"\bSerie\s*:\s*(\S+)", t)
    folio = re.search(r"\bFolio\s*:\s*([0-9A-Za-z-]+)", t)
    nombre = re.sub(r"(?i)^fondo mutuo\s+", "", fondo.group(1).strip()).title() if fondo else ""
    if nombre and serie:
        nombre += f" (serie {serie.group(1).strip()})"
    mov = {"fecha": _fecha_corta(f.group(1)) if f else fecha_correo,
           "comercio": f"Fondos mutuos ({'rescate' if rescate else 'inversión'})" + (f" · {nombre}" if nombre else ""),
           "monto": n if rescate else -n, "banco": "Scotiabank", "tipo": "inversion", "categoria": "Inversiones"}
    if folio:
        mov["operacion"] = folio.group(1)
    return mov


def _clave_pdf() -> str | None:
    try:
        from openjarvis.security import atlas_secretos as S
        return S.leer_clave(S.HERMES_PDF, HERE / "clave_pdf.txt")
    except Exception:  # noqa: BLE001
        return None


def scotia_ffmm_correo(m: email.message.Message, fecha_correo: str, clave=None) -> tuple[dict | None, bool]:
    """(movimiento, leído). Abre en memoria el PDF adjunto (nunca se guarda descifrado ni se muestra la clave).
    leído=False si no hay clave o no abre: el correo no se marca visto y se reintenta en la próxima pasada."""
    try:
        from pypdf import PdfReader
    except ImportError:
        log("Falta pypdf para leer los comprobantes de fondos mutuos.")
        return None, False
    for p in m.walk():
        if not (p.get_filename() or "").lower().endswith(".pdf"):
            continue
        try:
            r = PdfReader(io.BytesIO(p.get_payload(decode=True) or b""))
            if r.is_encrypted:
                k = (clave or _clave_pdf)()
                if not k or not r.decrypt(k):
                    log("Comprobante de fondos mutuos: la clave guardada no abre el PDF.")
                    return None, False
            t = "\n".join(pg.extract_text() or "" for pg in r.pages)
        except Exception as exc:  # noqa: BLE001
            log(f"Comprobante de fondos mutuos: no se pudo leer el PDF ({type(exc).__name__}).")
            return None, False
        mov = scotia_ffmm(t, fecha_correo)
        if mov:
            return mov, True
    return None, True


LECTORES = {f.__name__: f for f in (mach_compra, scotia_transferencia, scotia_pago_tarjeta, recibida_generica, recibida_otros,
                                    mach_ffmm, scotia_ffmm)}


# Solo esto es ingreso "de verdad". Lo demás que te llega (amigos que te devuelven su parte, regalos)
# va a "Devoluciones y otros": se muestra aparte y no infla los ingresos del mes.
INGRESOS_FIJOS = ["mamá", "papá", "abuelo", "universidad",
                  "empresa"]  # práctica
POR_REVISAR = ["remuneraciones xyz"]  # llegó plata y no sabemos de qué: ni ingreso ni devolución hasta que lo aclares
# Lo que cada uno te pasa fijo al mes. Solo un depósito de ese monto (±20 %) por mes cuenta como ingreso;
# lo demás que te pasen es «Extras de familia». 0 = cualquier monto cuenta (honorarios de la U).
MESADAS = {"mamá": 100000, "papá": 50000, "abuelo": 50000, "universidad": 0}
EXTRA = "Extras de familia"


def separar_mesadas(lista: list[dict], mesadas: dict) -> int:
    """Deja como «Ingresos» solo la mesada o sueldo de cada mes; los demás depósitos de esa persona pasan a extras."""
    grupos: dict = {}
    for m in lista:
        if m.get("monto", 0) <= 0 or m.get("categoria") not in ("Ingresos", EXTRA):
            continue
        nombre = (m.get("comercio", "") + " " + m.get("detalle", "")).lower()
        quien = next((k for k in mesadas if k in nombre), None)
        if quien is None:
            continue
        m["categoria"] = "Ingresos"
        if mesadas[quien]:
            grupos.setdefault((quien, m["fecha"][:7]), []).append(m)
    n = 0
    for (quien, _), ms in grupos.items():
        monto = mesadas[quien]
        cand = [m for m in ms if abs(m["monto"] - monto) <= monto * 0.20]
        cand.sort(key=lambda m: ("mesada" not in (m.get("detalle") or "").lower(), abs(m["monto"] - monto), m["fecha"]))
        fijo = cand[0] if cand else None
        for m in ms:
            if m is not fijo:
                m["categoria"] = EXTRA
                n += 1
    return n


def clase_ingreso(mov: dict, fijos: list[str]) -> str:
    nombre = (mov.get("comercio", "") + " " + mov.get("detalle", "")).lower()
    if "linea credito" in nombre or "linea de credito" in nombre:
        return "Préstamos recibidos"
    if any(p in nombre for p in POR_REVISAR):
        return "Ingresos por revisar"
    if any(f and f.lower() in nombre for f in fijos):
        return "Ingresos"
    return "Devoluciones y otros"


def categorizar(mov: dict, reglas: dict, propios: list[str]) -> str:
    if mov.get("categoria"):
        return mov["categoria"]
    nombre = (mov.get("comercio", "") + " " + mov.get("detalle", "")).lower()
    if any(p and p.lower() in nombre for p in propios):
        return "Transferencias propias"
    for cat, palabras in reglas.items():
        if any(p and p.lower() in nombre for p in palabras):
            return cat
    if mov.get("tipo") == "transferencia":
        return "Transferencias a personas"
    return "Otros"


# ------------------------------------------------------------------ correo
def conectar():
    try:
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector
    except ImportError:
        sys.exit("Falta OpenJarvis: corre este archivo con el Python de Atlas (src\\.venv\\Scripts\\python.exe).")
    c = GmailIMAPConnector()
    if not c.is_connected():
        sys.exit("El correo principal de Atlas no está conectado.")
    imap = c._open_imap()
    imap.select('"[Gmail]/All Mail"', readonly=True)  # solo lectura: no marca nada como leído
    return imap


def actualizar() -> dict:
    datos = cargar(MOV_FILE, {"movimientos": [], "vistos": []})
    vistos = set(datos.get("vistos", []))
    movs = {m["id"]: m for m in datos.get("movimientos", [])}
    nuevos = pdfs = 0
    CARTOLAS.mkdir(exist_ok=True)
    imap = conectar()
    try:
        for criterio, lector in FUENTES:
            if SOLO_CORREO_Y_AVISOS and lector in LECTORES_APAGADOS:
                continue
            typ, data = imap.search(None, f"(SINCE {DESDE} {criterio})")
            for num in data[0].split():
                typ, h = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE)])")
                hm = email.message_from_bytes(h[0][1])
                mid = (hm.get("Message-ID") or "").strip() or hashlib.sha1(h[0][1]).hexdigest()
                hmid = hashlib.sha1(mid.encode()).hexdigest()[:8]
                if lector == "adjunto_pdf":
                    # el nombre lleva la huella del correo: el mismo día pueden llegar varias cartolas con igual nombre
                    if any(CARTOLAS.glob(f"*_{hmid}_*")):
                        continue
                elif mid in vistos:
                    continue
                typ, full = imap.fetch(num, "(BODY.PEEK[])")
                m = email.message_from_bytes(full[0][1])
                try:
                    fc = datetime.strptime(" ".join((m.get("Date") or "").split()[1:4]), "%d %b %Y").strftime("%Y-%m-%d")
                except ValueError:
                    fc = time.strftime("%Y-%m-%d")
                if lector == "adjunto_pdf":
                    for p in m.walk():
                        fn = p.get_filename()
                        if fn and fn.lower().endswith(".pdf"):
                            nombre = f"{fc}_{hmid}_{re.sub(r'[^A-Za-z0-9_.-]', '_', str(make_header(decode_header(fn))))}"
                            dest = CARTOLAS / nombre
                            if not dest.exists():
                                dest.write_bytes(p.get_payload(decode=True) or b"")
                                pdfs += 1
                    vistos.add(mid)
                    continue
                if lector == "scotia_ffmm":   # los datos vienen en el PDF adjunto, no en el texto del correo
                    mov, leido = scotia_ffmm_correo(m, fc)
                    if not leido:
                        continue
                else:
                    mov = LECTORES[lector](texto_de(m), fc)
                vistos.add(mid)
                if mov and misma_operacion(mov, movs):
                    mov = None   # el mismo aporte o rescate ya vino en otro correo
                if mov:
                    mov["id"] = hashlib.sha1(mid.encode()).hexdigest()[:16]
                    mov["fuente"] = "correo"
                    movs[mov["id"]] = mov
                    nuevos += 1
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass

    n_cartola = juntar_cartolas(movs)

    n_avisos = juntar_avisos(movs)
    lista = terminar(datos, movs, vistos)
    log(f"Apolo: {nuevos} movimientos nuevos del correo, {n_cartola} de cartolas, {n_avisos} de avisos del celular, {len(lista)} en total, "
        f"{pdfs} PDF nuevos en cartolas.")
    return {"nuevos": nuevos, "total": len(lista), "pdfs": pdfs}


def terminar(datos: dict, movs: dict, vistos: set) -> list[dict]:
    """Categorías, mesadas, ciclos y cortes; guarda movimientos.json y rehace apolo.html."""
    # categorías (se recalculan siempre, así un cambio en categorias.json se aplica a todo)
    if not CAT_FILE.exists():
        guardar(CAT_FILE, {"_nota": "Palabra (en minúscula) que aparece en el comercio -> categoría. "
                                    "«propios»: tus nombres o cuentas, para no contar como gasto lo que te pasas a ti mismo.",
                           "propios": ["nombre apellido"], "categorias": CATEGORIAS_BASE})
    cfg = cargar(CAT_FILE, {})
    reglas, propios = cfg.get("categorias", CATEGORIAS_BASE), cfg.get("propios", [])
    for mv in movs.values():
        if mv.get("tipo") not in ("ingreso", "pago_tarjeta", "propia", "inversion"):
            mv.pop("categoria", None)
        elif mv.get("categoria") in ("Devoluciones y otros", "Préstamos recibidos", EXTRA, "Ingresos por revisar"):
            mv["categoria"] = "Ingresos"  # se vuelve a clasificar abajo con la lista actual
        mv["categoria"] = categorizar(mv, reglas, propios)
        if mv["categoria"] == "Ingresos":
            mv["categoria"] = clase_ingreso(mv, cfg.get("ingresos_fijos", INGRESOS_FIJOS))

    lista = sorted(movs.values(), key=lambda x: x["fecha"])
    separar_mesadas(lista, cfg.get("mesadas", MESADAS))
    rellenar_ciclos(lista)
    cortes = cortes_tarjeta(datos)  # fechas de corte de la tarjeta, para ver los gastos por ciclo de facturación
    guardar(MOV_FILE, {"movimientos": lista, "vistos": sorted(vistos), "cortes": cortes})
    escribir_pantalla(lista, cortes)
    return lista


def _palabras(s: str) -> set[str]:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z]{3,}", s)}


def mismo_nombre(correo: dict, fila: dict) -> bool:
    """¿Son la misma transferencia? La cartola corta los nombres («JUAN PABLO R»): basta una palabra en común."""
    if correo.get("tipo") == "pago_tarjeta" or fila.get("tipo") == "pago_tarjeta":
        return correo.get("tipo") == fila.get("tipo")
    if fila.get("tipo") == "propia":
        return any(p in correo.get("comercio", "").lower() for p in ("nombre apellido",))
    a, b = _palabras(correo.get("comercio", "")), _palabras(fila.get("comercio", ""))
    # la cartola corta los nombres a mitad de palabra («Sebastiá» por «Sebastián»): vale que una empiece como la otra
    return bool(a & b) or any(len(y) >= 5 and len(x) >= 5 and (x.startswith(y) or y.startswith(x)) for x in a for y in b)


def juntar_cartolas(movs: dict) -> int:
    """Suma lo de las cartolas PDF sin contar dos veces lo que ya vino por correo.

    Una fila de cartola que calza con un aviso de Scotiabank del correo (mismo monto y signo, hasta 3 días de
    diferencia) no se agrega: se queda el del correo, que trae el nombre completo y lo que ya clasificaste."""
    try:
        import leer_cartolas
    except ImportError:
        return 0
    for k in [k for k, m in movs.items() if m.get("fuente") == "cartola"]:
        del movs[k]
    if SOLO_CORREO_Y_AVISOS:   # ni cartolas ni estados de cuenta; y fuera las compras de MACH que llegaron por correo
        for k in [k for k, m in movs.items() if m.get("fuente") == "correo" and m.get("banco") == "MACH" and m.get("tipo") == "compra"]:
            del movs[k]
        return 0
    try:
        filas, probs = leer_cartolas.leer_todo()
    except ImportError:
        log("Falta pypdf: corre Configurar-Apolo.cmd para leer las cartolas.")
        return 0
    for p in probs:
        log(f"Cartolas: {p}")
    desde = datetime.strptime(DESDE, "%d-%b-%Y").date().isoformat()
    correo = [m for m in movs.values() if m.get("fuente") == "correo" and m.get("banco") == "Scotiabank"
              and m.get("tipo") in ("transferencia", "ingreso", "pago_tarjeta", "inversion")]
    usados, n = set(), 0
    mach_correo = [m for m in movs.values() if m.get("fuente") == "correo" and m.get("banco") == "MACH"]
    for f in sorted(filas, key=lambda x: x["fecha"]):
        if f["fecha"] < desde:
            continue
        fd = datetime.strptime(f["fecha"], "%Y-%m-%d").date()
        if f.get("banco") == "MACH":
            # la cartola de MACH trae lo mismo que los avisos de compra del correo: se queda el del correo
            par = next((m for m in mach_correo if m["id"] not in usados and m["monto"] == f["monto"]
                        and abs((datetime.strptime(m["fecha"], "%Y-%m-%d").date() - fd).days) <= 3), None)
            if par:
                usados.add(par["id"])
                continue
            movs[f["id"]] = f
            n += 1
            continue
        par = next((m for m in correo if m["id"] not in usados and m["monto"] == f["monto"]
                    and abs((datetime.strptime(m["fecha"], "%Y-%m-%d").date() - fd).days) <= 3
                    and mismo_nombre(m, f)), None)
        if par:
            usados.add(par["id"])
            continue
        movs[f["id"]] = f
        n += 1
    return n


# ------------------------------------------------------------------ avisos push del banco (celular)
def _plano(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def leer_avisos(carpeta: Path | None = None) -> list[dict]:
    """Registros de avisos_banco*.txt (incluye las copias «sync-conflict» de Syncthing). Una línea que no empieza
    con «@@|» es la continuación del texto del aviso anterior (notificaciones de varias líneas)."""
    regs: list[dict] = []
    for f in sorted((carpeta or AVISOS_DIR).glob("avisos_banco*.txt")):
        try:
            t = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        t = re.sub(r"(?<=[^\n])@@\|(?=\s*\d{4}-\d{1,2}-\d{1,2} )", "\n@@|", t)   # aviso pegado al anterior sin salto de línea
        actual = None
        for ln in t.splitlines():
            if ln.startswith("@@|"):
                p = ln[3:].split("|", 3)
                fm = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", p[0]) if len(p) == 4 else None
                if not fm:
                    actual = None
                    continue
                try:
                    cuando = datetime(*map(int, fm.groups()))
                except ValueError:
                    actual = None
                    continue
                actual = {"cuando": cuando, "app": p[1].strip(), "titulo": p[2].strip(), "texto": p[3].strip()}
                regs.append(actual)
            elif actual is not None and ln.strip():
                actual["texto"] = (actual["texto"] + " " + ln.strip()).strip()
    return regs


_FIN_NOMBRE = r"(?=\s+(?:con|el|a las|desde|usando|mediante|por|hoy|tarjeta)\b|[.,;:]|\s+\d{1,2}/\d{1,2}|$)"


def banco_de_app(app: str) -> str:
    """El banco de un aviso sale del nombre de la app que lo mandó: MACH y Scotiabank con su nombre de siempre, y
    cualquier otro banco que se agregue en MacroDroid («+ Agregar banco» en Hermes) con el nombre de su app."""
    a = _plano(app)
    if "mach" in a:
        return "MACH"
    if not a or "scotia" in a:
        return "Scotiabank"
    return re.sub(r"\s+", " ", app).strip()[:40]


def aviso_a_mov(r: dict) -> dict | None:
    """Convierte un aviso en un gasto, o None si no es una compra, pago o transferencia hecha por usted en pesos.
    MACH y Scotiabank tienen lector propio; los demás bancos pasan por aviso_generico (modelo local + patrones)."""
    banco = banco_de_app(r.get("app", ""))
    if banco not in BANCOS_CON_LECTOR:
        return aviso_generico(r, banco)
    return _aviso_patrones(r, banco)


def _aviso_patrones(r: dict, banco: str) -> dict | None:
    txt = f"{r['titulo']} {r['texto']}"
    p = _plano(txt)
    if re.search(r"\bus\$|\busd\b|dolar", p):
        return None   # en dólares: llega en pesos con el estado de cuenta
    if re.search(r"recibi|recibido|abono|deposit|te transfiri|te han transferido|devoluci|reversa|anulad|rechazad", p):
        return None   # lo que entra ya llega por correo; lo rechazado no es gasto
    if not re.search(r"compra|cargo|pago|pagaste|transferencia|transferiste|giro|avance", p):
        return None
    mo = re.search(r"\$\s?(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", txt)
    if not mo:
        return None
    monto = int(mo.group(1).replace(".", ""))
    if monto <= 0:
        return None
    resto = txt[mo.end():]
    tipo = "transferencia" if re.search(r"transfer", p) else "compra"
    nom = None
    if tipo == "transferencia":
        nom = re.search(r"\ba\s+(.+?)" + _FIN_NOMBRE, resto) or re.search(r"transferencia\s+a\s+(.+?)" + _FIN_NOMBRE, txt, re.I)
    else:
        nom = re.search(r"\ben\s+(.+?)" + _FIN_NOMBRE, resto) or re.search(r"\ben\s+(.+?)" + _FIN_NOMBRE, txt)
    comercio = nom.group(1).strip(" *-") if nom else ""
    if not comercio or len(comercio) > 60:
        comercio = r["titulo"] or "Aviso del banco"
    mov = {"fecha": r["cuando"].strftime("%Y-%m-%d"), "comercio": comercio, "detalle": "Aviso del celular",
           "monto": -monto, "banco": banco, "tipo": tipo,
           "fuente": "aviso"}
    if mov["banco"] == "Scotiabank" and re.search(r"credito|visa", p):
        mov["cuenta"] = "Visa"
    return mov


# ------------------------------------------------------------------ bancos sin lector propio (18-11-2026)
# MACH y Scotiabank tienen lector propio (aviso_a_mov). Para un banco agregado con «+ Agregar banco», el aviso lo lee el
# modelo local (Ollama, en este PC: nada sale del computador) y se compara con el lector de patrones. Si no calzan o
# falta algo, el movimiento queda «revisar» y aparece en «¿Para qué fue?». Los primeros avisos de cada banco nuevo se
# guardan como muestras, sin montos ni nombres, para escribir más adelante su lector propio.
BANCOS_CON_LECTOR = {"MACH", "Scotiabank"}
CACHE_MODELO = HERE / "avisos_modelo.json"
MUESTRAS_DIR = HERE / "muestras_avisos"
MUESTRAS_MAX = 8
_PROMPT_AVISO = (
    "Lees notificaciones de apps de bancos de Chile. Responde SOLO un objeto JSON, sin explicar nada, con estas claves: "
    '"es_gasto" (true si el usuario pagó, compró, transfirió o le cargaron plata en pesos chilenos; false si recibió '
    "plata, si fue rechazado o anulado, si es en dólares, una clave, un código, una promoción o un aviso sin monto), "
    '"monto" (número entero en pesos, sin puntos; null si no hay), "comercio" (la tienda o la persona a quien le pagó o '
    'transfirió, tal como aparece; "" si no aparece) y "tipo" ("compra" o "transferencia"). '
    'Ejemplo: «Compraste $12.990 en FARMACIA AHUMADA» -> {"es_gasto": true, "monto": 12990, "comercio": "FARMACIA AHUMADA", "tipo": "compra"}')


def _clave_aviso(r: dict) -> str:
    return hashlib.sha1(f"{r['cuando']:%Y-%m-%d %H:%M}|{r.get('app', '')}|{r['titulo']}|{r['texto']}".encode()).hexdigest()[:16]


def _modelo_lee(r: dict) -> dict:
    """Pregunta al modelo local. Lanza excepción si Ollama no responde (así se reintenta en la próxima pasada)."""
    import urllib.request
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    host = host if host.startswith("http") else "http://" + host
    body = json.dumps({"model": os.environ.get("ATLAS_MODEL", "qwen3.5:9b"), "stream": False, "think": False,
                       "options": {"temperature": 0, "num_predict": 120,
                                   "num_ctx": int(os.environ.get("ATLAS_NUM_CTX", "16384") or 16384)},
                       "messages": [{"role": "system", "content": _PROMPT_AVISO},
                                    {"role": "user", "content": f"App: {r.get('app', '')}\nTítulo: {r['titulo']}\nTexto: {r['texto'][:600]}"}]}).encode()
    req = urllib.request.Request(host + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (solo este PC)
        txt = (json.loads(resp.read().decode("utf-8")).get("message") or {}).get("content", "")
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", txt, flags=re.S), re.S)
    d = json.loads(m.group(0)) if m else {}
    try:
        monto = int(round(float(str(d.get("monto") or 0).replace(".", "").replace("$", "").replace(",", "."))))
    except ValueError:
        monto = 0
    return {"es_gasto": bool(d.get("es_gasto")), "monto": monto, "comercio": str(d.get("comercio") or "").strip()[:60],
            "tipo": "transferencia" if str(d.get("tipo", "")).lower().startswith("transf") else "compra"}


def _modelo_cache(r: dict, lector=None) -> dict | None:
    """Resultado del modelo para un aviso, guardado en avisos_modelo.json para no preguntar dos veces. None si no respondió."""
    cache = cargar(CACHE_MODELO, {})
    k = _clave_aviso(r)
    if k in cache:
        return cache[k]
    try:
        res = (lector or _modelo_lee)(r)
    except Exception as exc:  # noqa: BLE001
        log(f"Hermes: el modelo local no leyó un aviso ({type(exc).__name__}); se reintenta en la próxima pasada.")
        return None
    cache[k] = res
    CACHE_MODELO.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def anonimizar_aviso(texto: str) -> str:
    """Deja la forma del aviso y quita lo privado: montos y números, correos, y nombres de personas o comercios."""
    t = re.sub(r"\S+@\S+", "<CORREO>", texto)
    t = re.sub(r"\d", "9", t)
    t = re.sub(r"(?i)\b(a|en|de|para)\s+(?=[A-ZÁÉÍÓÚÑ0-9*])(.+?)" + _FIN_NOMBRE, lambda m: f"{m.group(1)} <NOMBRE>", t)
    t = re.sub(r"(?<!<)\b(?!NOMBRE>)[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ&.\-]{2,}(?:\s+[A-ZÁÉÍÓÚÑ0-9&.\-]{2,})*\b", "<NOMBRE>", t)
    t = re.sub(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+\b", "<NOMBRE>", t)
    return re.sub(r"\s+", " ", t).strip()


def guardar_muestra(r: dict, banco: str, carpeta: Path | None = None) -> bool:
    """Guarda hasta MUESTRAS_MAX avisos distintos (anonimizados) de un banco sin lector propio."""
    d = carpeta or MUESTRAS_DIR
    f = d / ((re.sub(r"[^\w]+", "_", _plano(banco)).strip("_") or "banco") + ".txt")
    linea = anonimizar_aviso(f"{r['titulo']} | {r['texto']}")
    previas = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    if len(previas) >= MUESTRAS_MAX or linea in previas:
        return False
    d.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(linea + "\n")
    return True


def aviso_generico(r: dict, banco: str, lector=None, muestras: Path | None = None) -> dict | None:
    """Aviso de un banco sin lector propio: modelo local + lector de patrones; lo dudoso queda «revisar»."""
    guardar_muestra(r, banco, muestras)
    pat = _aviso_patrones(r, banco)
    mod = _modelo_cache(r, lector)
    if mod is None or not mod["es_gasto"] or mod["monto"] <= 0:
        # el modelo no respondió, o no ve un gasto: si los patrones sí lo ven, entra para que usted lo revise
        if pat:
            pat["revisar"] = True
            pat["detalle"] = "Aviso del celular (lector automático)"
        return pat
    comercio = mod["comercio"] or (pat or {}).get("comercio") or r["titulo"] or "Aviso del banco"
    mov = {"fecha": r["cuando"].strftime("%Y-%m-%d"), "comercio": comercio, "detalle": "Aviso del celular (lector automático)",
           "monto": -mod["monto"], "banco": banco, "tipo": mod["tipo"], "fuente": "aviso"}
    if pat is None or pat["monto"] != mov["monto"] or not mod["comercio"]:
        mov["revisar"] = True
    return mov


def juntar_avisos(movs: dict, carpeta: Path | None = None) -> int:
    """Suma los avisos del celular que todavía no llegaron por otro lado.

    Se rehacen en cada pasada: un aviso se descarta si ya hay un gasto del correo o de la cartola con el mismo monto
    y hasta 3 días de diferencia (cada uno calza con uno solo). Así, cuando llega el correo o el estado de cuenta, ese
    reemplaza al aviso y no se cuenta dos veces. Android a veces repite la misma notificación: se cuenta una vez."""
    for k in [k for k, m in movs.items() if m.get("fuente") == "aviso"]:
        del movs[k]
    desde = datetime.strptime(DESDE, "%d-%b-%Y")
    otros = [m for m in movs.values() if m.get("monto", 0) < 0]
    usados: set[int] = set()
    repetidos: dict = {}
    n = 0
    for r in sorted(leer_avisos(carpeta), key=lambda x: x["cuando"]):
        if r["cuando"] < desde:
            continue
        clave = (r["titulo"], r["texto"])
        if clave in repetidos and (r["cuando"] - repetidos[clave]).total_seconds() <= 600:
            continue
        repetidos[clave] = r["cuando"]
        mov = aviso_a_mov(r)
        if not mov:
            continue
        fd = r["cuando"].date()
        par = next((m for m in otros if id(m) not in usados and m["monto"] == mov["monto"]
                    and abs((datetime.strptime(m["fecha"], "%Y-%m-%d").date() - fd).days) <= 3), None)
        if par is not None:
            usados.add(id(par))
            continue
        mov["id"] = "av" + hashlib.sha1(f"{r['cuando']:%Y-%m-%d %H:%M}|{r['titulo']}|{r['texto']}".encode()).hexdigest()[:14]
        movs[mov["id"]] = mov
        n += 1
    return n


def solo_avisos() -> None:
    """Suma los avisos del celular sin abrir el correo. Solo guarda si cambió algo."""
    datos = cargar(MOV_FILE, {"movimientos": [], "vistos": []})
    movs = {m["id"]: m for m in datos.get("movimientos", [])}
    antes = {k for k, m in movs.items() if m.get("fuente") == "aviso"}
    n = juntar_avisos(movs)
    if {k for k, m in movs.items() if m.get("fuente") == "aviso"} == antes:
        log(f"Hermes: avisos del celular sin cambios ({n} pendientes de correo o cartola).")
        return
    lista = terminar(datos, movs, set(datos.get("vistos", [])))
    log(f"Hermes: {n} compras de avisos del celular aún sin correo ni cartola, {len(lista)} movimientos en total.")


def rellenar_ciclos(lista: list[dict]) -> int:
    """Compras Visa ya guardadas sin «ciclo»: lo saca del nombre de su estado de cuenta (…_23072026.pdf)."""
    try:
        import leer_cartolas
    except ImportError:
        return 0
    n = 0
    for m in lista:
        if m.get("cuenta") == "Visa" and not m.get("ciclo"):
            c = leer_cartolas.ciclo_de_archivo(m.get("archivo", ""))
            if c:
                m["ciclo"] = c
                n += 1
    return n


def cortes_tarjeta(datos: dict, releer: bool = False) -> list[dict]:
    """Fechas de corte de la tarjeta (solo fechas). Las de las cartolas recién leídas; si no hay, las que ya estaban."""
    try:
        import leer_cartolas
        nuevos = leer_cartolas.leer_cortes() if releer else list(leer_cartolas.CORTES)
    except Exception as exc:  # noqa: BLE001
        log(f"Cortes de tarjeta: {exc}")
        nuevos = []
    return nuevos or datos.get("cortes", [])


def escribir_pantalla(lista: list[dict], cortes: list[dict] | None = None) -> None:
    pres = cargar(PRES_FILE, None)
    if pres is None:
        pres = {"_nota": "Límite mensual por categoría, en pesos. Borra o agrega las que quieras.",
                "Comida": 0, "Supermercado": 0, "Transporte": 0}
        guardar(PRES_FILE, pres)
    pres = {k: v for k, v in pres.items() if not k.startswith("_") and isinstance(v, (int, float)) and v > 0}
    visibles = [{k: v for k, v in m.items() if k in ("id", "cuenta", "fecha", "comercio", "detalle", "categoria", "banco", "monto", "tipo", "ciclo", "revisar")}
                for m in lista]
    blob = json.dumps({"actualizado": time.strftime("%d-%m-%Y %H:%M"), "movimientos": visibles, "presupuestos": pres,
                       "cortes": cortes or []},
                      ensure_ascii=False).replace("</", "<\\/")
    page = HERE / "apolo.html"
    t = page.read_bytes().decode("utf-8")   # en bytes: se conservan los saltos de línea que tenga la página
    t = re.sub(r'(<script id="apolo-datos" type="application/json">).*?(</script>)',
               lambda m: m.group(1) + blob + m.group(2), t, count=1, flags=re.S)
    page.write_bytes(t.encode("utf-8"))


if __name__ == "__main__":
    if "--solo-avisos" in sys.argv:  # avisos del celular, sin abrir el correo
        solo_avisos()
    elif "--solo-pantalla" in sys.argv:  # rehace apolo.html con lo ya leído, sin abrir el correo
        datos = cargar(MOV_FILE, {})
        lista = datos.get("movimientos", [])
        cortes = cortes_tarjeta(datos, releer=not SOLO_CORREO_Y_AVISOS)
        rellenar_ciclos(lista)
        if separar_mesadas(lista, cargar(CAT_FILE, {}).get("mesadas", MESADAS)) >= 0:
            guardar(MOV_FILE, {**datos, "movimientos": lista, "cortes": cortes})
        escribir_pantalla(lista, cortes)
    else:
        actualizar()

"""Lee las cartolas PDF de Scotiabank (cuenta corriente, cuenta vista y estado de cuenta de la Visa) y de MACH.

Usa las claves que guardaste con Configurar-Apolo.cmd (clave_pdf.txt) y Configurar-MACH.cmd (clave_mach.txt), solo en este PC.
Devuelve movimientos con la misma forma que los de los correos. Lo usa actualizar_apolo.py.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MESES = {m: i + 1 for i, m in enumerate(["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"])}
NUM = r"[\d.]+(?:,\d{2})?"


def pesos(s: str) -> int:
    s = s.replace(".", "")
    return round(float(s.replace(",", "."))) if "," in s else int(s or 0)


def _texto(path: Path, clave: str) -> str:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    if r.is_encrypted and not r.decrypt(clave):
        raise ValueError(f"la clave no abre {path.name}")
    return "\n".join(p.extract_text() or "" for p in r.pages)


def _id(*partes) -> str:
    return "c" + hashlib.sha1("|".join(map(str, partes)).encode()).hexdigest()[:15]


def cuenta(t: str, archivo: str) -> list[dict]:
    """Cuenta corriente / cuenta vista. Cargo o abono se deduce del saldo diario (el texto no separa columnas)."""
    per = re.search(r"\d+\s+(\d{2})/([A-Z]{3})/(\d{4})\s+(\d{2})/([A-Z]{3})/(\d{4})", t)
    if not per:
        return []
    ini = date(int(per[3]), MESES[per[2]], int(per[1]))
    fin = date(int(per[6]), MESES[per[5]], int(per[4]))
    cta = re.search(r"No\. CTA\. MONEDA ESTADO CTA\.\s*\n(\S+)", t)
    cta = cta[1] if cta else "?"
    tipo = "Cuenta vista" if "CUENTA VISTA" in t else "Cuenta corriente"
    res = re.search(rf"SALDO ANTERIOR DEPOSITOS/ABONOS CARGOS/GIROS SALDO ACTUAL\s*\n({NUM})", t)
    saldo = pesos(res[1]) if res else None
    out = []
    for n, m in enumerate(re.finditer(rf"^(\d{{2}}) / ([A-Z]{{3}}) (.+?) (\d{{8}}) ({NUM}) ({NUM})\s*$", t, re.M)):
        dia, mes, desc, _doc, monto, nuevo = int(m[1]), MESES[m[2]], m[3].strip(), m[4], pesos(m[5]), pesos(m[6])
        anio = ini.year if mes >= ini.month or ini.year == fin.year else fin.year
        abono = saldo is not None and nuevo > saldo
        if saldo is not None and abs(abs(nuevo - saldo) - monto) > 1:
            abono = nuevo >= saldo  # por si el saldo no calza exacto
        saldo = nuevo
        f = date(anio, mes, dia).isoformat()
        out.append({"id": _id(cta, f, desc, monto, n), "fecha": f, "monto": monto if abono else -monto,
                    "banco": "Scotiabank", "cuenta": tipo, "fuente": "cartola", "archivo": archivo, **describir(desc, abono)})
    return out


_ACENTOS = {"acute": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}, "tilde": {"n": "ñ"}}


def sin_entidades(s: str) -> str:
    """La cartola a veces trae «Sebasti aacute» en vez de «Sebastián» (una entidad HTML rota). Se arregla para que el
    nombre calce con el aviso del correo y el mismo movimiento no quede dos veces."""
    import html as _html
    s = _html.unescape(s)
    return re.sub(r"\s?&?([aeioun])(acute|tilde);?", lambda m: _ACENTOS[m[2].lower()].get(m[1].lower(), m[0]), s, flags=re.I)


def describir(desc: str, abono: bool) -> dict:
    """Nombre legible y tipo a partir de la glosa del banco."""
    d = sin_entidades(re.sub(r"\s+", " ", desc))
    if re.search(r"TRANSF\. (?:A|DE) CTA\.(?:CTE|TARJETA)", d) or re.search(r"\b21317456-8\b", d):
        return {"comercio": "Entre mis cuentas", "tipo": "propia", "categoria": "Transferencias propias", "detalle": d}
    if re.search(r"FONDOS? MUTUOS?|RESCATE F\.?M", d):  # plata que va o vuelve de tus inversiones (Isis): ni gasto ni ingreso
        return {"comercio": "Fondos mutuos (rescate)" if abono else "Fondos mutuos (inversión)", "tipo": "inversion",
                "categoria": "Inversiones", "detalle": d}
    if re.search(r"PAGO TARJ\.?CRED", d):
        return {"comercio": "Pago tarjeta de crédito", "tipo": "pago_tarjeta", "categoria": "Pago de tarjeta", "detalle": d}
    if re.match(r"REM HONORA", d):
        return {"comercio": "Universidad de Chile (honorarios)" if "UNIVERSI" in d else "Honorarios", "tipo": "ingreso",
                "categoria": "Ingresos", "detalle": d}
    m = re.match(r"TEF (\d{6,9}-[\dKk]) (.+)$", d)
    if m:
        return {"comercio": m[2].strip().title(), "rut": m[1], "tipo": "ingreso" if abono else "transferencia",
                **({"categoria": "Ingresos"} if abono else {}), "detalle": d}
    m = re.match(r"TRANSF\. DE (.+)$", d)
    if m:
        return {"comercio": m[1].strip().title(), "tipo": "ingreso", "categoria": "Ingresos", "detalle": d}
    m = re.match(r"(?:REDCOMPRA|COMPRA|eCOMME(?: Inter\.)?|COMPRA INT\.?)\s+(.+)$", d, re.I)
    if m:
        return {"comercio": m[1].strip().title(), "tipo": "compra", "detalle": d}
    return {"comercio": d.title(), "tipo": "ingreso" if abono else "compra", **({"categoria": "Ingresos"} if abono else {}),
            "detalle": d}


def tarjeta(t: str, archivo: str) -> list[dict]:
    """Estado de cuenta de la Visa: compras del período (una compra en cuotas se cuenta entera, en la cuota 1).
    Cada compra lleva «ciclo»: la fecha de corte del estado de cuenta en que vino (algunas se facturan en el ciclo
    siguiente a su fecha); con eso Hermes suma cada ciclo igual que el estado de cuenta."""
    out = []
    cs = cortes_de(t)
    ciclo = {"ciclo": cs[0]} if cs else ({"ciclo": ciclo_de_archivo(archivo)} if ciclo_de_archivo(archivo) else {})
    for n, m in enumerate(re.finditer(rf"(\d{{2}}/\d{{2}}/\d{{4}}) \d{{4}} \d{{6,}} (.+?) \$ ?(-?{NUM}) \$ ?(-?{NUM}) (\d{{2}})/(\d{{2}}) \$ ?(-?{NUM})", t)):
        f, desc, monto, cuota = m[1], m[2].strip(), m[3], int(m[5])
        if monto.startswith("-") or re.match(r"PAGO\b", desc) or cuota != 1:
            continue
        d, mo, y = f.split("/")
        fecha = f"{y}-{mo}-{d}"
        out.append({"id": _id("visa", fecha, desc, monto, n), "fecha": fecha, "monto": -pesos(monto.lstrip("-")),
                    "banco": "Scotiabank", "cuenta": "Visa", "fuente": "cartola", "archivo": archivo, "tipo": "compra",
                    "comercio": re.sub(r"^(?:MERPAGO|MP|DLO|PAYU|SUMUP|TUU)\*\s*", "", desc).title(), "detalle": desc, **ciclo})
    return out


def cortes_de(t: str) -> list[str]:
    """Fechas de corte (cierre de facturación) de un estado de cuenta de tarjeta: la de este período y la del anterior.
    Solo fechas: nada de montos ni números de tarjeta (Hermes agrupa por ciclo de tarjeta con esto, 18-11-2026)."""
    out = []
    m = re.search(r"PER[IÍ]ODO\s+FACTURADO\s+\d{2}/\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})", t)
    if m:
        out.append(m[1])
    m = re.search(r"PER[IÍ]ODO DE FACTURACI[OÓ]N ANTERIOR\s+\d{2}/\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})", t)
    if m:
        out.append(m[1])
    return [f"{x[6:]}-{x[3:5]}-{x[:2]}" for x in out if not x.startswith("00/")]


def ciclo_de_archivo(nombre: str) -> str | None:
    """Fecha de corte desde el nombre del estado de cuenta de la Visa («…_23072026.pdf» -> «2026-07-23»)."""
    m = re.search(r"_(\d{2})(\d{2})(20\d{2})\.pdf$", nombre or "", re.I)
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


CORTES: list[dict] = []   # lo llena leer_todo: [{"tarjeta": "tarjeta 1", "fecha": "AAAA-MM-DD"}]


def _anotar_cortes(t: str, tarjetas: dict, cortes: set) -> None:
    fin = re.search(r"X{4,}(\d{4})", t)   # para distinguir tarjetas; solo queda «tarjeta 1», «tarjeta 2»…
    n = tarjetas.setdefault(fin[1] if fin else "?", len(tarjetas) + 1)
    for f in cortes_de(t):
        cortes.add((f"tarjeta {n}", f))


def leer_cortes() -> list[dict]:
    """Solo las fechas de corte de los estados de cuenta de tarjeta guardados (para rehacer la pantalla sin el correo)."""
    from openjarvis.security import atlas_secretos as S

    clave = S.leer_clave(S.APOLO_PDF, HERE / "clave_pdf.txt")
    if not clave:
        return []
    tarjetas, cortes = {}, set()
    for p in sorted((HERE / "cartolas").glob("*.pdf")):
        if "MACHBANK" in p.name:
            continue
        try:
            t = _texto(p, clave)
        except Exception:  # noqa: BLE001
            continue
        if "TARJETA DE CR" in t[:300]:
            _anotar_cortes(t, tarjetas, cortes)
    return [{"tarjeta": a, "fecha": f} for a, f in sorted(cortes, key=lambda x: (x[1], x[0]))]


def mach(t: str, archivo: str) -> list[dict]:
    """Cartola de la cuenta MACH. Egreso o ingreso se deduce del saldo de cada línea."""
    ini = re.search(r"Saldo contable .*?\n\s*(-?[\d.]+) ", t)
    saldo = pesos(ini[1]) if ini else None
    cuerpo = re.sub(r"CARTOLA CUENTA MACHBANK.*?Fecha operación Descripción Cambio Moneda Egreso Ingreso Saldo", "", t, flags=re.S)
    out = []
    pat = r"(\d{2})/(\d{2})/(\d{4}) (.+?) \$(-?[\d.]+) \$(-?[\d.]+)"
    for n, m in enumerate(re.finditer(pat, cuerpo, re.S)):
        d, mo, y = m[1], m[2], m[3]
        desc = re.sub(r"\s+", " ", m[4]).strip()
        desc = re.sub(r"\s+(?:CLP|\d[\d,]*\.\d{1,2} [A-Z]{3})$", "", desc).strip()
        monto, nuevo = pesos(m[5]), pesos(m[6])
        abono = saldo is not None and nuevo > saldo if saldo is not None else desc.startswith(("Transferencia de", "Pago recibido", "Abono"))
        saldo = nuevo
        fecha = f"{y}-{mo}-{d}"
        out.append({"id": _id("mach", fecha, desc, monto, n), "fecha": fecha, "monto": monto if abono else -monto,
                    "banco": "MACH", "cuenta": "MACH", "fuente": "cartola", "archivo": archivo, **describir_mach(desc, abono)})
    return out


def describir_mach(d: str, abono: bool) -> dict:
    if re.search(r"FFMM|fondos? mutuos?", d, re.I):  # aporte o rescate de fondos mutuos desde MACH: ni gasto ni ingreso
        return {"comercio": "Fondos mutuos (rescate)" if abono else "Fondos mutuos (inversión)", "tipo": "inversion",
                "categoria": "Inversiones", "detalle": d}
    if re.search(r"Apellido Apellido Nombre|Ahorro 24/7", d, re.I):
        return {"comercio": "Entre mis cuentas", "tipo": "propia", "categoria": "Transferencias propias", "detalle": d}
    m = re.match(r"(?:Transferencia de|Pago recibido -)\s*(.+)$", d)
    if m:
        return {"comercio": m[1].strip().title(), "tipo": "ingreso", "categoria": "Ingresos", "detalle": d}
    m = re.match(r"(?:Pago enviado -|Transferencia a)\s*(.+)$", d)
    if m:
        return {"comercio": m[1].strip().title(), "tipo": "transferencia", "detalle": d}
    m = re.match(r"Compra[^-]*-\s*(.+)$", d)
    if m:
        return {"comercio": m[1].strip(), "tipo": "compra", "detalle": d}
    return {"comercio": d, "tipo": "ingreso" if abono else "compra", **({"categoria": "Ingresos"} if abono else {}), "detalle": d}


def leer_todo() -> tuple[list[dict], list[str]]:
    """(movimientos, problemas). Sin clave guardada no hace nada."""
    # Las claves están cifradas en el Administrador de credenciales; el .txt solo si aún no se migró
    from openjarvis.security import atlas_secretos as S

    clave = S.leer_clave(S.APOLO_PDF, HERE / "clave_pdf.txt")
    if not clave:
        return [], ["sin clave: corre Configurar-Apolo.cmd"]
    clave_mach = S.leer_clave(S.APOLO_MACH, HERE / "clave_mach.txt")
    movs, probs, vistos = [], [], set()
    tarjetas, cortes = {}, set()
    for p in sorted((HERE / "cartolas").glob("*.pdf")):
        es_mach = "MACHBANK" in p.name
        if es_mach and not clave_mach:
            probs.append(f"{p.name}: sin clave de MACH (corre Configurar-MACH.cmd)")
            continue
        try:
            t = _texto(p, clave_mach if es_mach else clave)
        except Exception as exc:  # noqa: BLE001
            probs.append(f"{p.name}: {exc}")
            continue
        if "TARJETA DE CR" in t[:300]:
            _anotar_cortes(t, tarjetas, cortes)
        lote = mach(t, p.name) if "CARTOLA CUENTA MACHBANK" in t[:200] else tarjeta(t, p.name) if "TARJETA DE CR" in t[:300] else cuenta(t, p.name)
        for m in lote:  # la misma cartola puede llegar dos veces por correo: mismo id, se cuenta una vez
            if m["id"] not in vistos:
                vistos.add(m["id"])
                movs.append(m)
    CORTES[:] = [{"tarjeta": a, "fecha": f} for a, f in sorted(cortes, key=lambda x: (x[1], x[0]))]
    return movs, probs


if __name__ == "__main__":
    ms, pr = leer_todo()
    for m in ms:
        print(m["fecha"], m["cuenta"][:6], f"{m['monto']:>9}", m["tipo"][:8], m["comercio"][:35])
    print(len(ms), "movimientos;", pr)

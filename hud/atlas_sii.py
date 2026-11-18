"""Registro público de empresas del SII, en el PC (17-11): razón social, actividades y domicilio de cada persona
jurídica. Sirve para saber qué tipo de comercio y de qué comuna es un pago, sin sacar los pagos del PC.

Fuente: https://www.sii.cl/sobre_el_sii/nominapersonasjuridicas.html (PUB_NOMBRES_PJ, PUB_NOM_ACTECOS,
PUB_NOM_DIRECCIONES). Solo empresas: las personas naturales (p. ej. un dueño de cabañas que factura a su nombre) no están.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "apps" / "cronos" / "sii"
DB = DIR / "sii.db"
_VACIAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "sa", "s", "a", "ltda", "limitada", "spa", "eirl", "sociedad",
           "comercial", "inversiones", "servicios", "empresa", "empresas", "cia", "compania", "chile", "y/o", "por", "acciones",
           "anonima", "responsabilidad", "individual"}


def _plain(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def palabras(t: str) -> list[str]:
    return [w for w in _plain(t).split() if len(w) > 2 and w not in _VACIAS and not w.isdigit()]


def construir(dir_: Path = DIR) -> dict:
    """Arma sii.db desde los .txt descargados (tarda unos minutos). Se puede borrar los .txt después."""
    tmp = dir_ / "sii.tmp.db"
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(str(tmp))
    con.executescript("""
      CREATE TABLE empresa (rut INTEGER PRIMARY KEY, razon TEXT, comuna TEXT, ciudad TEXT, region TEXT);
      CREATE TABLE actividad (rut INTEGER, codigo TEXT, descripcion TEXT);
      CREATE TABLE sucursal (rut INTEGER, comuna TEXT, ciudad TEXT);
      CREATE TABLE palabra (w TEXT, rut INTEGER);""")
    def filas(nombre):
        with open(dir_ / nombre, encoding="latin-1") as fh:
            next(fh)
            for ln in fh:
                yield ln.rstrip("\r\n").split("\t")
    n = {"empresas": 0, "actividades": 0, "sucursales": 0}
    for c in filas("PUB_NOMBRES_PJ.txt"):
        if len(c) >= 4 and c[0].isdigit() and not (len(c) > 5 and c[5].strip()):  # vigente (sin fecha de término)
            con.execute("INSERT OR REPLACE INTO empresa (rut, razon) VALUES (?, ?)", (int(c[0]), c[3].strip()))
            n["empresas"] += 1
    for c in filas("PUB_NOM_DOMICILIO.txt"):
        if len(c) >= 13 and c[0].isdigit() and c[2] == "S":
            con.execute("UPDATE empresa SET comuna=?, ciudad=?, region=? WHERE rut=?", (c[11].strip(), c[10].strip(), c[12].strip(), int(c[0])))
    for c in filas("PUB_NOM_ACTECOS.txt"):
        if len(c) >= 4 and c[0].isdigit():
            con.execute("INSERT INTO actividad VALUES (?, ?, ?)", (int(c[0]), c[2].strip(), c[3].strip()))
            n["actividades"] += 1
    for c in filas("PUB_NOM_SUCURSAL.txt"):
        if len(c) >= 13 and c[0].isdigit() and c[2] == "S":
            con.execute("INSERT INTO sucursal VALUES (?, ?, ?)", (int(c[0]), c[11].strip(), c[10].strip()))
            n["sucursales"] += 1
    for rut, razon in con.execute("SELECT rut, razon FROM empresa").fetchall():
        con.executemany("INSERT INTO palabra VALUES (?, ?)", [(w, rut) for w in set(palabras(razon))])
    con.executescript("CREATE INDEX ia ON actividad(rut); CREATE INDEX isu ON sucursal(rut); CREATE INDEX ip ON palabra(w);")
    con.commit()
    con.close()
    DB.unlink(missing_ok=True)
    tmp.rename(DB)
    return n


def _con():
    if not DB.exists():
        return None
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    return con


def _ficha(con, rut: int) -> dict | None:
    e = con.execute("SELECT * FROM empresa WHERE rut=?", (rut,)).fetchone()
    if not e:
        return None
    acts = [r["descripcion"] for r in con.execute("SELECT descripcion FROM actividad WHERE rut=?", (rut,))]
    sucs = sorted({r["comuna"] for r in con.execute("SELECT comuna FROM sucursal WHERE rut=?", (rut,)) if r["comuna"]})
    return {"rut": rut, "razon": e["razon"], "comuna": e["comuna"] or "", "region": e["region"] or "", "actividades": acts,
            "sucursales": sucs}


def por_rut(rut: str | int) -> dict | None:
    """'76.123.456-7' o 76123456 -> ficha de la empresa (None si no es empresa o no está)."""
    m = re.sub(r"[^\dkK-]", "", str(rut)).split("-")[0]
    if not m.isdigit():
        return None
    con = _con()
    if not con:
        return None
    try:
        return _ficha(con, int(m))
    finally:
        con.close()


def por_nombre(texto: str) -> dict | None:
    """Nombre como sale en el aviso o la cartola ('CABANAS HORIZONTE AZ') -> la empresa cuya razón social tiene todas
    esas palabras (si es una sola). None si es ambiguo o no hay."""
    ws = palabras(texto)
    if len(ws) < 2:
        return None
    con = _con()
    if not con:
        return None
    try:
        ruts = None
        for w in ws:
            # palabra exacta, o que empiece igual si viene cortada (las cartolas recortan: «HORIZONTE AZ»); usa el índice
            q = (con.execute("SELECT rut FROM palabra WHERE w >= ? AND w < ? LIMIT 5000", (w, w + "~")).fetchall() if len(w) >= 5
                 else con.execute("SELECT rut FROM palabra WHERE w=? LIMIT 5000", (w,)).fetchall())
            s = {r[0] for r in q}
            ruts = s if ruts is None else ruts & s
            if not ruts:
                return None
        return _ficha(con, next(iter(ruts))) if len(ruts) == 1 else None
    finally:
        con.close()


RX_ALOJAMIENTO = re.compile(r"(?i)alojamiento|hotel|caba[nñ]a|hostal|camping|residencial|turismo rural")


def es_alojamiento(f: dict | None) -> bool:
    return bool(f) and any(RX_ALOJAMIENTO.search(a) for a in f["actividades"])

#!/usr/bin/env python3
"""
sincronizar.py: descarga la Cronología de Google Maps (copia cifrada en la nube),
la descifra EN MEMORIA y la deja en una base SQLite que Cronos/Atlas puede consultar.

  python sincronizar.py                 sincronización normal (la que corre cada noche)
  python sincronizar.py --prueba X.json importa un Timeline.json ya existente, sin Internet
                                        (sirve también para la exportación manual del celular)

Lo único que se escribe en disco es la base final (cronologia_maps.db) y un registro sin
datos sensibles. El token de una hora, la clave y la copia descifrada nunca tocan el disco.

Carpeta de datos: variable ATLAS_CRONOLOGIA_DIR, o %LOCALAPPDATA%\\Atlas\\datos\\cronologia_maps
"""
import argparse, json, os, sqlite3, sys, time

# Transición Jarvis -> Atlas: las variables JARVIS_* antiguas valen como ATLAS_*
for _k, _v in list(os.environ.items()):
    if _k.startswith("JARVIS_") and "ATLAS_" + _k[7:] not in os.environ:
        os.environ["ATLAS_" + _k[7:]] = _v

from datetime import datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "vendor_timeline_export"))

DESFASE_CHILE_MIN = -180   # solo se usa para los primeros puntos sin hora local propia
MINIMO_RELATIVO = 0.8      # no reemplazar si la descarga trae <80 % de lo que ya había


def carpeta_datos():
    base = os.environ.get("ATLAS_CRONOLOGIA_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Atlas", "datos", "cronologia_maps")
    os.makedirs(base, exist_ok=True)
    return base


def registrar(carpeta, ok, detalle):
    linea = f"{datetime.now().isoformat(timespec='seconds')}  {'OK ' if ok else 'ERROR'}  {detalle}\n"
    with open(os.path.join(carpeta, "sincronizacion.log"), "a", encoding="utf-8") as f:
        f.write(linea)
    with open(os.path.join(carpeta, "estado.json"), "w", encoding="utf-8") as f:
        json.dump({"ultimo_intento": datetime.now().isoformat(timespec="seconds"),
                   "ok": ok, "detalle": detalle}, f, ensure_ascii=False, indent=2)
    print(linea, end="", file=sys.stderr)


# ---------------------------------------------------------------- descarga
def descargar_segmentos():
    import secretos, gpsoauth, httpx, geller_fetch as gf, odlh_export as ox
    cred = secretos.cargar_todo()
    r = gpsoauth.perform_oauth(cred["email"], cred["master_token"], cred["android_id"],
                               service="oauth2:https://www.googleapis.com/auth/webhistory",
                               app="com.google.android.gms",
                               client_sig="38918a453d07199354f8b19af05ec6562ced5788")
    bearer = r.get("Auth")
    if not bearer:
        raise RuntimeError(f"Google no entregó el acceso temporal ({r.get('Error') or 'sin detalle'}). "
                           "Si revocó el dispositivo, repita: python secretos.py token")
    import base64
    clave = base64.b64decode(cred["clave"])
    del cred

    recs = []
    with httpx.Client(http2=True, timeout=120) as c:
        for resp in gf.fetch_pages(c, bearer):
            for frame in gf.grpc_unframe(resp.content, resp.headers.get("grpc-encoding", "gzip")):
                try:
                    snaps = list(gf.snapshots(gf.parse(frame), clave))
                except RuntimeError as e:
                    raise RuntimeError("No se pudo descifrar: Google pudo haber cambiado la clave. "
                                       "Ejecute: python secretos.py clave") from e
                for snap in snaps:
                    if (gf.one(snap, 1) or b"").decode("utf8", "replace") != "semantic_segment_table":
                        continue
                    dbid = gf.one(snap, 6)
                    for row in gf.rows_of(snap):
                        if row.get("semantic_segment"):
                            row.setdefault("database_id", dbid)
                            recs.append(row)
    del bearer, clave

    mem = sqlite3.connect(":memory:")            # la copia descifrada vive solo en RAM
    mem.execute(gf.SCHEMA)
    for r in recs:
        mem.execute("INSERT OR REPLACE INTO semantic_segment_table(database_id,segment_id,semantic_segment,"
                    "start_timestamp_seconds,end_timestamp_seconds,segment_type,hierarchy_level) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (r.get("database_id") or 0, r["segment_id"], r["semantic_segment"],
                     r.get("start_timestamp_seconds") or 0, r.get("end_timestamp_seconds") or 0,
                     r.get("segment_type") or 0, r.get("hierarchy_level")))
    segs, stats = ox.build(mem, default_offset_min=DESFASE_CHILE_MIN)
    mem.close()
    return segs, stats


# ---------------------------------------------------------------- importación
ESQUEMA = """
CREATE TABLE IF NOT EXISTS visitas(
  inicio TEXT NOT NULL, fin TEXT NOT NULL, utc_offset_min INTEGER,
  lat REAL, lng REAL, place_id TEXT, tipo_semantico TEXT, tipo_lugar INTEGER,
  probabilidad REAL, confirmada INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS trayectos(
  inicio TEXT NOT NULL, fin TEXT NOT NULL, lat_ini REAL, lng_ini REAL, lat_fin REAL, lng_fin REAL,
  distancia_m REAL, modo TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS puntos(ts TEXT NOT NULL, lat REAL, lng REAL);
CREATE TABLE IF NOT EXISTS viajes(inicio TEXT NOT NULL, fin TEXT NOT NULL, json TEXT);
CREATE TABLE IF NOT EXISTS sincronizaciones(
  fecha TEXT, visitas INTEGER, trayectos INTEGER, puntos INTEGER, viajes INTEGER);
CREATE INDEX IF NOT EXISTS ix_visitas_inicio ON visitas(inicio);
CREATE INDEX IF NOT EXISTS ix_trayectos_inicio ON trayectos(inicio);
CREATE INDEX IF NOT EXISTS ix_puntos_ts ON puntos(ts);
"""


def latlng(s):
    """'-33.4500°, -70.6600°' -> (-33.4500, -70.6600)"""
    if not s:
        return None, None
    try:
        a, b = s.replace("°", "").split(",")
        return float(a), float(b)
    except ValueError:
        return None, None


def filas(segs):
    vis, tray, pts, via = [], [], [], []
    for s in segs:
        ini, fin = s.get("startTime"), s.get("endTime")
        js = json.dumps(s, ensure_ascii=False)
        if "visit" in s:
            v = s["visit"]; tc = v.get("topCandidate", {})
            lat, lng = latlng(tc.get("placeLocation", {}).get("latLng"))
            vis.append((ini, fin, s.get("startTimeTimezoneUtcOffsetMinutes"), lat, lng, tc.get("placeId"),
                        tc.get("semanticType"), tc.get("placeTypeCode"), v.get("probability"),
                        1 if v.get("isConfirmed") else 0, js))
        elif "activity" in s:
            a = s["activity"]
            la, lo = latlng(a.get("start", {}).get("latLng"))
            lb, lp = latlng(a.get("end", {}).get("latLng"))
            tray.append((ini, fin, la, lo, lb, lp, a.get("distanceMeters"),
                         a.get("topCandidate", {}).get("type"), js))
        elif "timelinePath" in s:
            t0 = datetime.fromisoformat(ini)
            for p in s["timelinePath"]:
                lat, lng = latlng(p.get("point"))
                try:
                    m = float(p.get("durationMinutesOffsetFromStartTime") or 0)
                except ValueError:
                    m = 0
                pts.append(((t0 + timedelta(minutes=m)).isoformat(), lat, lng))
        elif "trip" in s:
            via.append((ini, fin, js))
    return vis, tray, pts, via


def importar(segs, carpeta, forzar=False):
    vis, tray, pts, via = filas(segs)
    ruta = os.path.join(carpeta, "cronologia_maps.db")
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)
    previas = con.execute("SELECT COUNT(*) FROM visitas").fetchone()[0]
    if not forzar and previas and len(vis) < previas * MINIMO_RELATIVO:
        con.close()
        raise RuntimeError(f"La descarga trae {len(vis)} visitas y ya había {previas}; "
                           "parece incompleta, así que no se reemplazó nada (use --forzar si es correcto).")
    # La copia de Google es completa: se reemplaza todo en una sola transacción.
    with con:
        for t in ("visitas", "trayectos", "puntos", "viajes"):
            con.execute(f"DELETE FROM {t}")
        con.executemany("INSERT INTO visitas VALUES (?,?,?,?,?,?,?,?,?,?,?)", vis)
        con.executemany("INSERT INTO trayectos VALUES (?,?,?,?,?,?,?,?,?)", tray)
        con.executemany("INSERT INTO puntos VALUES (?,?,?)", pts)
        con.executemany("INSERT INTO viajes VALUES (?,?,?)", via)
        con.execute("INSERT INTO sincronizaciones VALUES (?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), len(vis), len(tray), len(pts), len(via)))
    con.close()
    return ruta, len(vis), len(tray), len(pts), len(via)


def main():
    ap = argparse.ArgumentParser(description="Sincroniza la Cronología de Maps hacia Atlas")
    ap.add_argument("--prueba", metavar="TIMELINE_JSON", help="importar un archivo en vez de descargar")
    ap.add_argument("--forzar", action="store_true", help="reemplazar aunque la descarga traiga menos datos")
    a = ap.parse_args()
    carpeta = carpeta_datos()
    t0 = time.time()
    try:
        if a.prueba:
            with open(a.prueba, encoding="utf-8") as f:
                segs = json.load(f)["semanticSegments"]
        else:
            segs, _ = descargar_segmentos()
        ruta, nv, nt, np_, nvi = importar(segs, carpeta, a.forzar)
        registrar(carpeta, True, f"{nv} visitas, {nt} trayectos, {np_} puntos, {nvi} viajes "
                                 f"en {time.time() - t0:.0f}s -> {ruta}")
    except Exception as e:
        registrar(carpeta, False, str(e)[:500])
        sys.exit(1)


if __name__ == "__main__":
    main()

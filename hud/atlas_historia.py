"""Historia personal: «¿qué hacía alrededor del 12 de marzo?».

Junta por día, en un índice local (apps/cronos/historia.db): fotos (fecha del nombre o EXIF, descripción hecha por el
modelo local con visión, caras), gastos de Hermes, eventos de calendario, correos (se consultan al momento por IMAP),
Google Takeout (Chrome, YouTube, Mi actividad) y la Cronología del teléfono (Timeline.json).

PRIVACIDAD (regla del usuario): nada de esto sale del PC. Solo lo ve el modelo local en Ollama (127.0.0.1). La consulta
a Claude de Atlas nunca recibe estas respuestas: hud_server.route_claude filtra lo que es_privado() reconoce.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import re
import sqlite3
import threading
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIR = HERE.parent / "apps" / "cronos"   # datos y página de Cronos (antes hud/historia, 18-11-2026)
DB_FILE = DIR / "historia.db"
CONFIG_FILE = DIR / "config.json"
MODELOS = DIR / "modelos"
HOME = Path(os.path.expanduser("~"))
HERMES_MOV = HERE.parent / "apps" / "hermes" / "movimientos.json"

EXT_FOTO = {".jpg", ".jpeg", ".png"}
CONFIG_BASE = {
    "carpetas_fotos": [],          # vacío = las de carpetas_por_defecto()
    "excluir": ["Stickers", "WhatsApp Animated Gifs", "/Android/data/", "thumbnails", ".thumbnails", "Private"],
    "takeout": [str(HOME / "Downloads")],  # dónde buscar Takeout*.zip, carpetas Takeout y Timeline.json
    "desde_meses": 12,             # primero se describen las fotos de los últimos N meses, después las más antiguas
    "pausado": False,
    "umbral_cara": 0.40,           # parecido (coseno SFace) desde el que una cara se da por «es usted»
    "inactivo_seg": 120,           # el trabajo en segundo plano espera que Atlas lleve este tiempo sin turnos
}
_lock = threading.RLock()
_privados: list[str] = []          # textos (preguntas y respuestas) que nunca se pasan a Claude


# ------------------------------------------------------------------ utilidades
def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def config() -> dict:
    try:
        c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    return {**CONFIG_BASE, **c}


def guardar_config(**cambios) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    c.update(cambios)
    CONFIG_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**CONFIG_BASE, **c}


def db() -> sqlite3.Connection:
    DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_FILE), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS fotos(id INTEGER PRIMARY KEY, ruta TEXT UNIQUE, origen TEXT, fecha TEXT, hora TEXT,
        fecha_de TEXT, lat REAL, lon REAL, procesada INTEGER DEFAULT 0, descripcion TEXT, n_caras INTEGER,
        yo REAL, error TEXT);
    CREATE INDEX IF NOT EXISTS fotos_fecha ON fotos(fecha);
    CREATE TABLE IF NOT EXISTS caras(id INTEGER PRIMARY KEY, foto INTEGER, x INTEGER, y INTEGER, w INTEGER, h INTEGER,
        conf REAL, emb BLOB, yo REAL);
    CREATE INDEX IF NOT EXISTS caras_foto ON caras(foto);
    CREATE TABLE IF NOT EXISTS etiquetas(cara INTEGER PRIMARY KEY, yo INTEGER, origen TEXT, prueba INTEGER,
        prediccion REAL, t REAL);
    CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, fuente TEXT, fecha TEXT, hora TEXT, titulo TEXT,
        detalle TEXT);
    CREATE INDEX IF NOT EXISTS items_fecha ON items(fecha);
    CREATE TABLE IF NOT EXISTS estado(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS revision(id TEXT PRIMARY KEY, fecha TEXT, fila TEXT, ini TEXT, fin TEXT, titulo TEXT,
        conf TEXT, regla TEXT, veredicto TEXT, c_ini TEXT, c_fin TEXT, c_titulo TEXT, t REAL);
    """)
    return con


def _estado(con, k, v=None):
    if v is None:
        r = con.execute("SELECT v FROM estado WHERE k=?", (k,)).fetchone()
        return r[0] if r else None
    con.execute("INSERT OR REPLACE INTO estado VALUES(?,?)", (k, str(v)))
    con.commit()
    return v


# ------------------------------------------------------------------ fotos: dónde y de qué fecha
def carpetas_por_defecto() -> list[Path]:
    out = []
    cross = HOME / "CrossDevice"
    if cross.exists():
        for tel in cross.iterdir():
            st = tel / "storage"
            for sub in ("DCIM", "Pictures", "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
                        "WhatsApp/Media/WhatsApp Images"):
                if (st / sub).exists():
                    out.append(st / sub)
    for p in (HOME / "Pictures", HOME / "OneDrive" / "Pictures", HOME / "OneDrive" / "Imágenes"):
        if p.exists():
            out.append(p)
    return out


_RX_FECHA = [
    re.compile(r"(?:IMG|VID)-(\d{4})(\d{2})(\d{2})-WA"),
    re.compile(r"WhatsApp Image (\d{4})-(\d{2})-(\d{2}) at (\d{1,2})\.(\d{2})"),
    re.compile(r"(?:^|[^0-9])(20\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})"),
    re.compile(r"(?:^|[^0-9])(20\d{2})-(\d{2})-(\d{2})[ _-](\d{2})[-.](\d{2})"),
]


def fecha_de_nombre(nombre: str) -> tuple[str, str] | None:
    """'IMG-20210220-WA0002.jpg' -> ('2021-02-20', ''); '20240101_123456.jpg' -> ('2024-01-01', '12:34')."""
    for rx in _RX_FECHA:
        m = rx.search(nombre)
        if m:
            g = m.groups()
            try:
                d = date(int(g[0]), int(g[1]), int(g[2]))
            except ValueError:
                continue
            if not (2000 <= d.year <= date.today().year + 1):
                continue
            hora = f"{int(g[3]):02d}:{g[4]}" if len(g) >= 5 and int(g[3]) < 24 else ""
            return d.isoformat(), hora
    return None


def _origen(ruta: str) -> str:
    r = ruta.replace("\\", "/").lower()
    if "whatsapp" in r:
        return "whatsapp enviada" if "/sent/" in r else "whatsapp"
    if "screenshot" in r or "captura" in r:
        return "captura"
    if "/dcim/" in r:
        return "cámara"
    return "pc"


FOTOS_DESACTIVADAS = True  # el usuario pidió sacar las fotos de Cronos por privacidad (17-11-2026)


def escanear_fotos() -> int:
    """Recorre las carpetas (sin abrir las fotos: en Enlace Móvil abrir = bajar del teléfono). -> fotos nuevas."""
    if FOTOS_DESACTIVADAS:
        return 0
    c = config()
    carpetas = [Path(p) for p in c["carpetas_fotos"]] or carpetas_por_defecto()
    excl = [e.lower() for e in c["excluir"]]
    con = db()
    conocidas = {r[0] for r in con.execute("SELECT ruta FROM fotos")}
    nuevas = []
    for base in carpetas:
        for raiz, dirs, files in os.walk(base):
            rr = raiz.replace("\\", "/").lower() + "/"
            if any(("/" + e.strip("/") + "/") in rr or e in rr.split("/") for e in excl):
                dirs[:] = []
                continue
            for f in files:
                if Path(f).suffix.lower() not in EXT_FOTO:
                    continue
                ruta = os.path.join(raiz, f)
                if ruta in conocidas:
                    continue
                fd = fecha_de_nombre(f)
                if fd:
                    nuevas.append((ruta, _origen(ruta), fd[0], fd[1], "nombre"))
                else:
                    nuevas.append((ruta, _origen(ruta), None, "", None))
    with _lock:
        con.executemany("INSERT OR IGNORE INTO fotos(ruta, origen, fecha, hora, fecha_de) VALUES(?,?,?,?,?)", nuevas)
        con.commit()
    con.close()
    return len(nuevas)


def _exif(img) -> tuple[str | None, str, float | None, float | None]:
    """-> (fecha, hora, lat, lon) desde el EXIF (None si no hay)."""
    try:
        ex = img.getexif()
    except Exception:  # noqa: BLE001
        return None, "", None, None
    fecha, hora, lat, lon = None, "", None, None
    try:
        sub = ex.get_ifd(0x8769)
        dt = sub.get(36867) or ex.get(306)
        if dt:
            d = datetime.strptime(str(dt)[:19], "%Y:%m:%d %H:%M:%S")
            fecha, hora = d.date().isoformat(), d.strftime("%H:%M")
    except Exception:  # noqa: BLE001
        pass
    try:
        gps = ex.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            def dec(v, ref):
                x = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                return -x if ref in ("S", "W") else x
            lat, lon = dec(gps[2], gps.get(1, "N")), dec(gps[4], gps.get(3, "E"))
    except Exception:  # noqa: BLE001
        pass
    return fecha, hora, lat, lon


# ------------------------------------------------------------------ caras (OpenCV YuNet + SFace, en el procesador)
_cv = {}


def _caras_modelos():
    if not _cv:
        import cv2

        _cv["det"] = cv2.FaceDetectorYN.create(str(MODELOS / "yunet.onnx"), "", (320, 320), 0.85, 0.3, 50)
        _cv["rec"] = cv2.FaceRecognizerSF.create(str(MODELOS / "sface.onnx"), "")
    return _cv["det"], _cv["rec"]


def detectar_caras(bgr) -> list[dict]:
    """-> [{x,y,w,h,conf,emb(np.float32[128], normalizado)}] de caras de al menos 40 px."""
    import numpy as np

    det, rec = _caras_modelos()
    h, w = bgr.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(bgr)
    out = []
    for f in faces if faces is not None else []:
        if f[2] < 40 or f[3] < 40:
            continue
        crop = rec.alignCrop(bgr, f)
        e = rec.feature(crop).flatten().astype(np.float32)
        e /= (np.linalg.norm(e) or 1)
        out.append({"x": int(f[0]), "y": int(f[1]), "w": int(f[2]), "h": int(f[3]), "conf": float(f[14]), "emb": e})
    return out


def _refs():
    """Embeddings de las caras que el usuario marcó como suyas al enseñarle (no las de las pruebas)."""
    import numpy as np

    con = db()
    rows = con.execute("SELECT c.emb FROM caras c JOIN etiquetas e ON e.cara=c.id WHERE e.yo=1 AND e.origen='ensenar'").fetchall()
    con.close()
    return np.stack([np.frombuffer(r[0], dtype=np.float32) for r in rows]) if rows else None


def puntaje(emb, refs) -> float | None:
    """Parecido con usted: promedio de los 3 más parecidos entre sus caras de referencia (coseno, -1 a 1)."""
    import numpy as np

    if refs is None or not len(refs):
        return None
    s = np.sort(refs @ emb)[::-1][:3]
    return float(s.mean())


def recalcular_yo() -> int:
    """Vuelve a puntuar todas las caras con las referencias actuales. -> caras puntuadas."""
    import numpy as np

    refs = _refs()
    con = db()
    rows = con.execute("SELECT id, foto, emb FROM caras").fetchall()
    upd, por_foto = [], {}
    for r in rows:
        p = puntaje(np.frombuffer(r["emb"], dtype=np.float32), refs)
        upd.append((p, r["id"]))
        if p is not None:
            por_foto[r["foto"]] = max(por_foto.get(r["foto"], -1), p)
    with _lock:
        con.executemany("UPDATE caras SET yo=? WHERE id=?", upd)
        con.execute("UPDATE fotos SET yo=NULL")
        con.executemany("UPDATE fotos SET yo=? WHERE id=?", [(v, k) for k, v in por_foto.items()])
        con.commit()
    con.close()
    return len(upd)


# ------------------------------------------------------------------ descripción con el modelo local (visión)
PROMPT_FOTO = ("Describe esta foto en español en una o dos frases cortas: qué tipo de lugar es (casa, calle, restorán, "
               "playa, universidad…), qué se está haciendo, cuántas personas hay y cualquier texto visible útil para "
               "recordar el momento (nombre de un local, un evento, un monto). Si es una captura de pantalla, di de qué "
               "app y de qué trata. No inventes nombres de personas. Sin introducción.")


def _ollama_local() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    host = host if host.startswith("http") else "http://" + host
    if not re.match(r"http://(127\.0\.0\.1|localhost)(:\d+)?$", host):
        raise RuntimeError("Ollama no es local: la historia personal solo se procesa en este PC")
    return host


def _modelo() -> str:
    return os.environ.get("ATLAS_MODEL", "qwen3.5:9b")


class RelatoCortado(Exception):
    """Se cerró Cronos mientras el modelo escribía: se deja de generar."""


_CORTE = [0]  # sube cada vez que se cierra Cronos (cortar_relato)


def cortar_relato() -> None:
    _CORTE[0] += 1


def ollama_chat(messages: list[dict], num_predict: int = 200, timeout: int = 120, cortar=None) -> str:
    """Con «cortar» (función que dice si hay que parar) pide la respuesta por partes y corta la conexión al
    momento, así Ollama deja de generar."""
    import urllib.request

    body = json.dumps({"model": _modelo(), "stream": bool(cortar), "think": False, "messages": messages,
                       # mismo num_ctx que el motor de Atlas: con otro, Ollama recarga el modelo
                       "options": {"temperature": 0.2, "num_predict": num_predict,
                                   "num_ctx": int(os.environ.get("ATLAS_NUM_CTX", "16384") or 16384)}}).encode()
    req = urllib.request.Request(_ollama_local() + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        if not cortar:
            out = (json.loads(r.read().decode("utf-8")).get("message") or {}).get("content", "")
        else:
            partes = []
            for linea in r:
                if cortar():
                    raise RelatoCortado
                if linea.strip():
                    x = json.loads(linea)
                    partes.append((x.get("message") or {}).get("content", ""))
                    if x.get("done"):
                        break
            out = "".join(partes)
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def describir_imagen(img) -> str:
    im = img.convert("RGB")
    im.thumbnail((768, 768))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return ollama_chat([{"role": "user", "content": PROMPT_FOTO, "images": [b64]}], num_predict=120)[:600]


def procesar_foto(fid: int, ruta: str, describir: bool = True, caras: bool = True) -> dict:
    """Abre la foto (en el teléfono: la baja), saca EXIF y caras (procesada=1) y, si se pide, la descripción
    (procesada=2). Con caras=False solo describe (las caras ya se sacaron). Guarda todo."""
    if FOTOS_DESACTIVADAS:
        return {"error": "fotos desactivadas"}
    import numpy as np
    from PIL import Image, ImageOps

    res = {"caras": 0, "descrita": False}
    con = db()
    ya = con.execute("SELECT procesada FROM fotos WHERE id=?", (fid,)).fetchone()
    if caras and not describir and ya and ya[0] != 0:  # otro proceso ya la tomó
        con.close()
        return res
    try:
        with Image.open(ruta) as im0:
            fecha, hora, lat, lon = _exif(im0)
            im = ImageOps.exif_transpose(im0).convert("RGB")
        im.thumbnail((1280, 1280))
        if not caras:
            txt = describir_imagen(im)
            with _lock:
                con.execute("UPDATE fotos SET descripcion=?, procesada=2 WHERE id=?", (txt, fid))
                con.commit()
            res["descrita"] = True
            return res
        bgr = np.asarray(im)[:, :, ::-1].copy()
        caras = detectar_caras(bgr)
        refs = _refs()
        with _lock:
            con.execute("DELETE FROM caras WHERE foto=?", (fid,))
            best = None
            for c in caras:
                p = puntaje(c["emb"], refs)
                best = p if best is None or (p is not None and p > best) else best
                con.execute("INSERT INTO caras(foto,x,y,w,h,conf,emb,yo) VALUES(?,?,?,?,?,?,?,?)",
                            (fid, c["x"], c["y"], c["w"], c["h"], c["conf"], c["emb"].tobytes(), p))
            row = con.execute("SELECT fecha, fecha_de FROM fotos WHERE id=?", (fid,)).fetchone()
            if fecha and row["fecha_de"] != "nombre" or (fecha and not row["fecha"]):
                con.execute("UPDATE fotos SET fecha=?, hora=?, fecha_de='exif' WHERE id=?", (fecha, hora, fid))
            elif not row["fecha"]:
                d = datetime.fromtimestamp(os.path.getmtime(ruta))
                con.execute("UPDATE fotos SET fecha=?, hora=?, fecha_de='archivo' WHERE id=?",
                            (d.date().isoformat(), d.strftime("%H:%M"), fid))
            con.execute("UPDATE fotos SET lat=?, lon=?, n_caras=?, yo=?, procesada=1, error=NULL WHERE id=?",
                        (lat, lon, len(caras), best, fid))
            con.commit()
        res["caras"] = len(caras)
        if describir:
            txt = describir_imagen(im)
            with _lock:
                con.execute("UPDATE fotos SET descripcion=?, procesada=2 WHERE id=?", (txt, fid))
                con.commit()
            res["descrita"] = True
    except Exception as exc:  # noqa: BLE001
        with _lock:
            con.execute("UPDATE fotos SET procesada=-1, error=? WHERE id=?", (str(exc)[:200], fid))
            con.commit()
        res["error"] = str(exc)[:200]
    finally:
        con.close()
    return res


def _siguiente(con, fase: int) -> sqlite3.Row | None:
    """fase 1 = sacar caras (procesada 0 -> 1, en el procesador); fase 2 = describir (1 -> 2, en la GPU).
    Orden: las de su cámara, las que envió y las capturas (pesan más que las recibidas); luego las recientes; luego
    las demás, de la más nueva a la más vieja."""
    desde = (date.today() - timedelta(days=30 * int(config()["desde_meses"]))).isoformat()
    p = fase - 1
    return (con.execute("SELECT id, ruta, procesada FROM fotos WHERE procesada=? AND origen IN "
                        "('cámara','whatsapp enviada','captura','pc') ORDER BY fecha IS NULL, fecha DESC LIMIT 1", (p,)).fetchone()
            or con.execute("SELECT id, ruta, procesada FROM fotos WHERE procesada=? AND (fecha>=? OR fecha IS NULL) "
                           "ORDER BY fecha IS NULL, fecha DESC LIMIT 1", (p, desde)).fetchone()
            or con.execute("SELECT id, ruta, procesada FROM fotos WHERE procesada=? ORDER BY fecha DESC LIMIT 1", (p,)).fetchone())


# ------------------------------------------------------------------ trabajo en segundo plano
_fondo = {"hilos": [], "caras_hechas": 0, "descritas_hoy": 0, "errores": 0}


def iniciar_fondo(desocupado=lambda: True, ocupado_ahora=lambda: False, log=print) -> None:
    """Dos hilos: caras (procesador, se detiene solo mientras Atlas atiende un turno) y descripciones (GPU, solo
    cuando Atlas lleva rato desocupado: desocupado() -> bool)."""
    if any(t.is_alive() for t in _fondo["hilos"]):
        return

    def bucle(fase: int):
        time.sleep(60 if fase == 1 else 120)  # deja arrancar Atlas tranquilo
        ult_import = 0.0
        while True:
            try:
                if fase == 1 and time.time() - ult_import > 6 * 3600:
                    n = escanear_fotos()
                    m = importar_todo()
                    ult_import = time.time()
                    log(f"  historia: {n} fotos nuevas en el índice; importados {m}")
                if FOTOS_DESACTIVADAS:
                    time.sleep(600)
                    continue
                if config().get("pausado") or (ocupado_ahora() if fase == 1 else not desocupado()):
                    time.sleep(10 if fase == 1 else 20)
                    continue
                con = db()
                row = _siguiente(con, fase)
                con.close()
                if not row:
                    time.sleep(600)
                    continue
                r = procesar_foto(row["id"], row["ruta"], describir=fase == 2, caras=fase == 1)
                _fondo["caras_hechas" if fase == 1 else "descritas_hoy"] += 1
                if r.get("error"):
                    _fondo["errores"] += 1
                    time.sleep(5)
            except Exception as exc:  # noqa: BLE001
                log(f"  historia: error en segundo plano: {exc!r}")
                time.sleep(60)

    for fase in ((1,) if FOTOS_DESACTIVADAS else (1, 2)):
        th = threading.Thread(target=bucle, args=(fase,), daemon=True, name=f"historia-{fase}")
        _fondo["hilos"].append(th)
        th.start()


# ------------------------------------------------------------------ otras fuentes: Hermes, Takeout, Cronología
def _put(con, fuente, fecha, hora, titulo, detalle=""):
    k = hashlib.sha1(f"{fuente}|{fecha}|{hora}|{titulo}|{detalle}".encode()).hexdigest()[:20]
    con.execute("INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,?)", (k, fuente, fecha, hora, titulo[:300], detalle[:500]))


def _local(ts: str) -> tuple[str, str] | None:
    """Fecha ISO (con zona o Z) -> (fecha, hora) en la hora local del PC."""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone()
    return d.date().isoformat(), d.strftime("%H:%M")


BIP_FILE = DIR / "bip.txt"


def importar_bip(con) -> int:
    """Movimientos de la tarjeta bip! que el usuario copió de tarjetabip.cl a historia/bip.txt (sin el número de
    tarjeta). Cada validación queda como item «bip»: título = estación, paradero o micro; detalle = movimiento|monto."""
    if not BIP_FILE.exists():
        return 0
    n = 0
    for linea in BIP_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if linea.lstrip().startswith("#"):
            continue
        partes = [x.strip() for x in linea.split("\t") if x.strip()]
        i = next((j for j, x in enumerate(partes) if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", x)), None)
        if i is None or i < 1 or i + 2 >= len(partes):
            continue
        mov, lugar, monto = partes[i - 1], partes[i + 1], partes[i + 2]
        if lugar == "-" or not re.match(r"(?i)uso|carga", mov):
            continue
        dd, mm, aa = partes[i][:10].split("/")
        antes = con.total_changes
        _put(con, "bip", f"{aa}-{mm}-{dd}", partes[i][11:16], lugar, f"{mov}|{monto.replace('.', '')}")
        n += con.total_changes - antes
    return n


def _tramo_bip(lugar: str) -> str:
    """«SPBL-85 103» -> «micro 103»; «RM-1373 ZONA PAGA» -> «zona paga»; «Estadio Nacional» -> «metro Estadio Nacional»."""
    if re.search(r"(?i)zona paga", lugar):
        return "zona paga"
    m = re.match(r"^[A-Z]{2,4}-?\d{1,4} (\w+)$", lugar)
    if m:
        return f"micro {m.group(1)}"
    return "metro " + re.sub(r"(?i)\s+L\d+$", "", lugar)


def _viajes_bip(items: list[dict], k: str) -> list[dict]:
    """Validaciones de un día agrupadas en viajes: un trasbordo (monto 0, menos de 2 h después) sigue el mismo viaje.
    La llegada no se registra: se estima 25 min después de la última validación."""
    us = sorted((it for it in items if it["fuente"] == "bip" and it["fecha"] == k and it.get("hora")
                 and (it.get("detalle") or "").lower().startswith("uso")), key=lambda it: it["hora"])
    out = []
    for it in us:
        monto = (it.get("detalle") or "|").split("|")[1]
        if out and monto == "0" and _m(it["hora"]) - _m(out[-1]["ult"]) <= 120:
            out[-1]["ult"] = it["hora"]
            out[-1]["tramos"].append(_tramo_bip(it["titulo"]))
        else:
            out.append({"ini": it["hora"], "ult": it["hora"], "tramos": [_tramo_bip(it["titulo"])]})
    for v in out:
        v["fin"] = _h(_m(v["ult"]) + 25)
    return out


def _empresa_sii(m: dict) -> str:
    """Qué empresa es el comercio, según el registro del SII descargado en el PC (nada sale de aquí):
    'comuna~1' si es un alojamiento, 'comuna~0' si no; la comuna solo si no tiene sucursales (si no, es la casa matriz)."""
    try:
        import atlas_sii as S

        txt = " ".join(str(m.get(k) or "") for k in ("comercio", "detalle"))
        r = re.search(r"\b(\d{1,2}\.?\d{3}\.?\d{3})-?[\dkK]\b", txt)
        f = S.por_rut(r.group(1).replace(".", "")) if r else S.por_nombre(str(m.get("comercio") or ""))
        if not f:
            return ""
        return f"{'' if f['sucursales'] else f['comuna'].title()}~{int(S.es_alojamiento(f))}"
    except Exception:  # noqa: BLE001
        return ""


def importar_hermes(con) -> int:
    try:
        import atlas_hermes

        movs = atlas_hermes.cargar()[0]
    except Exception:  # noqa: BLE001
        try:
            movs = json.loads(HERMES_MOV.read_text(encoding="utf-8")).get("movimientos", [])
        except (OSError, ValueError):
            return 0
    con.execute("DELETE FROM items WHERE fuente='gasto'")
    for m in movs:
        monto = m.get("monto", 0)
        _put(con, "gasto", m.get("fecha", ""), "", f"{'cargo' if monto < 0 else 'abono'} de {abs(round(monto)):,} pesos".replace(",", ".")
             + f" en {m.get('comercio', '')}", f"{m.get('categoria', '') or ''}|{m.get('tipo', '') or ''}|{_empresa_sii(m)}")
    return len(movs)


def _json_de(fuente) -> list:
    try:
        return json.loads(fuente)
    except ValueError:
        return []


def _archivos_takeout() -> list[tuple[str, callable]]:
    """[(nombre, leer() -> bytes)] de los JSON útiles dentro de Takeout (carpetas o .zip) y Timeline.json."""
    out = []
    utiles = re.compile(r"(history\.json|historial\.json|watch-history\.json|historial-de-reproducciones\.json|"
                        r"search-history\.json|myactivity\.json|miactividad\.json|mi actividad\.json|timeline\.json|"
                        r"cronolog[ií]a\.json|location-history\.json|records\.json|miactividad\.html|myactivity\.html)$", re.I)
    for base in config()["takeout"]:
        b = Path(base)
        if not b.exists():
            continue
        for p in b.iterdir():
            n = p.name.lower()
            if p.is_file() and n.endswith(".zip") and "takeout" in n:
                try:
                    z = zipfile.ZipFile(p)
                except zipfile.BadZipFile:
                    continue
                for zn in z.namelist():
                    if utiles.search(zn):
                        out.append((zn, (lambda z=z, zn=zn: z.read(zn))))
            elif p.is_dir() and "takeout" in n:
                for f in p.rglob("*"):
                    if f.is_file() and utiles.search(f.name):
                        out.append((str(f), (lambda f=f: f.read_bytes())))
            elif p.is_file() and utiles.search(p.name) and re.search(r"timeline|cronolog|location", n):
                out.append((str(p), (lambda p=p: p.read_bytes())))
    return out


def _latlng(s) -> tuple[float, float] | None:
    m = re.findall(r"-?\d+\.\d+", str(s or ""))
    return (float(m[0]), float(m[1])) if len(m) >= 2 else None


def importar_cronologia(con, data) -> int:
    """Timeline.json del teléfono (Maps en el dispositivo: semanticSegments) o el formato antiguo de Takeout."""
    n = 0
    segs = data.get("semanticSegments") if isinstance(data, dict) else None
    if segs is None and isinstance(data, dict) and "timelineObjects" in data:  # Takeout antiguo (Semantic Location History)
        segs = []
        for o in data["timelineObjects"]:
            if "placeVisit" in o:
                pv = o["placeVisit"]
                segs.append({"startTime": pv["duration"].get("startTimestamp"), "endTime": pv["duration"].get("endTimestamp"),
                             "visit": {"topCandidate": {"semanticType": pv["location"].get("semanticType", ""),
                                                        "nombre": pv["location"].get("name", "") or pv["location"].get("address", ""),
                                                        "placeLocation": {"latLng": f"{pv['location'].get('latitudeE7', 0) / 1e7}, {pv['location'].get('longitudeE7', 0) / 1e7}"}}}})
            elif "activitySegment" in o:
                a = o["activitySegment"]
                segs.append({"startTime": a["duration"].get("startTimestamp"), "endTime": a["duration"].get("endTimestamp"),
                             "activity": {"topCandidate": {"type": a.get("activityType", "")}, "distanceMeters": a.get("distance", 0)}})
    lugares = _estado(con, "lugares")
    lugares = json.loads(lugares) if lugares else {}
    for s in segs or []:
        ini = _local(s.get("startTime") or "")
        fin = _local(s.get("endTime") or "")
        if not ini:
            continue
        if "visit" in s:
            tc = s["visit"].get("topCandidate") or {}
            ll = _latlng((tc.get("placeLocation") or {}).get("latLng"))
            tipo = (tc.get("semanticType") or "").upper()
            nombre = tc.get("nombre") or {"HOME": "su casa", "INFERRED_HOME": "su casa", "WORK": "el trabajo",
                                          "INFERRED_WORK": "el trabajo"}.get(tipo, "")
            pid = tc.get("placeId") or (f"{ll[0]:.3f},{ll[1]:.3f}" if ll else "")
            nombre = nombre or lugares.get(pid, "")
            det = json.dumps({"lat": ll[0], "lon": ll[1], "lugar": pid} if ll else {"lugar": pid})
            _put(con, "ubicacion", ini[0], ini[1], f"estuvo en {nombre or 'un lugar'}" + (f" hasta las {fin[1]}" if fin and fin[0] == ini[0] else ""), det)
            n += 1
        elif "activity" in s:
            a = s["activity"]
            tipo = ((a.get("topCandidate") or {}).get("type") or "").upper()
            modo = {"WALKING": "caminó", "IN_PASSENGER_VEHICLE": "anduvo en auto", "IN_VEHICLE": "anduvo en auto",
                    "IN_BUS": "anduvo en micro", "IN_SUBWAY": "anduvo en metro", "CYCLING": "anduvo en bicicleta",
                    "RUNNING": "corrió", "FLYING": "viajó en avión", "IN_TRAIN": "anduvo en tren"}.get(tipo, "se movió")
            km = float(a.get("distanceMeters") or 0) / 1000
            if km >= 0.3:
                _put(con, "ubicacion", ini[0], ini[1], f"{modo} {km:.1f} km".replace(".", ","))
                n += 1
    return n


_MES_CORTO = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "sept": 9,
              "set": 9, "oct": 10, "nov": 11, "dic": 12, "jan": 1, "apr": 4, "aug": 8, "dec": 12}
_RX_FECHA_ACT = re.compile(r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]{3,10})\.?\s+(?:de\s+)?(\d{4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?"
                           r"(?:\s*[A-Za-z]*\s*([+-]\d{1,2}(?::?\d{2})?))?", re.I)


def _fecha_actividad(s: str) -> tuple[str, str] | None:
    """«16 nov 2026, 19:58:31 GMT-03:00» -> (fecha, hora) en la hora local del PC."""
    from datetime import timezone

    m = _RX_FECHA_ACT.search(s)
    if not m:
        return None
    mes = _MES_CORTO.get(_plain(m.group(2))[:4]) or _MES_CORTO.get(_plain(m.group(2))[:3]) \
        or (_MES.get(_plain(m.group(2))) if _plain(m.group(2)) in _MES else None)
    if not mes:
        return None
    try:
        d = datetime(int(m.group(3)), mes, int(m.group(1)), int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    except ValueError:
        return None
    if m.group(7):
        z = m.group(7).replace(":", "")
        sign = -1 if z[0] == "-" else 1
        z = z[1:].rjust(2, "0")
        hh, mm = int(z[:2]), int(z[2:4] or 0)
        d = d.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm))).astimezone().replace(tzinfo=None)
    return d.date().isoformat(), d.strftime("%H:%M")


_ALNUM = re.compile(r"[0-9A-Za-zÀ-ÿ\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")


def limpiar_titulo(t: str, verbo: bool = True) -> str | None:
    """«Buscaste x» -> «buscó x»; una URL -> su dominio; títulos vacíos o avisos de Google -> None."""
    t = re.sub(r"\s+", " ", (t or "").replace("\u3164", " ")).strip()
    t = re.sub(r"https?://(?:www\.)?([^/\s?#]+)\S*", r"\1", t)
    if verbo:
        for a, b in ((r"^(?:Buscaste|Has buscado|Búsqueda de)\s+", "buscó "), (r"^(?:Viste|Has visto|He visto)\s+", "vio "),
                     (r"^(?:Visitaste|Has visitado)\s+", "visitó "), (r"^(?:Usaste|Has usado)\s+", "usó ")):
            t = re.sub(a, b, t, flags=re.I)
    resto = re.sub(r"^(buscó|vio|visitó|usó)\s*", "", t)
    if not _ALNUM.search(resto) or re.match(r"(?i)^\d+ notificaci|^se ha utilizado|^usó (maps|google|youtube|chrome)\b", t):
        return None
    return t


def importar_actividad_html(con, nombre: str, html_txt: str) -> int:
    """Mi actividad de Google en HTML (Takeout en español): cada «outer-cell» es una acción con su fecha."""
    import html as _html

    partes = Path(nombre.replace("\\", "/")).parts
    prod = partes[-2] if len(partes) >= 2 else "actividad"
    pp = _plain(prod)
    if pp in ("publicidad", "google analytics", "takeout", "programadores", "ads", "ayuda"):
        return 0  # ruido: anuncios vistos, analítica, exportaciones
    fuente = ("youtube" if "youtube" in pp else "busqueda" if pp.startswith(("busqueda", "search")) else
              "maps" if pp == "maps" else "actividad")
    n = 0
    for celda in html_txt.split('class="outer-cell')[1:]:
        m = re.search(r'class="content-cell[^"]*body-1"[^>]*>(.*?)</div>', celda, re.S)
        if not m:
            continue
        trozos = [_html.unescape(re.sub(r"<[^>]+>", "", x)).replace("\xa0", " ").strip() for x in re.split(r"<br\s*/?>", m.group(1))]
        trozos = [x for x in trozos if x]
        if not trozos:
            continue
        cuando = None
        for i in range(len(trozos) - 1, -1, -1):
            cuando = _fecha_actividad(trozos[i])
            if cuando:
                texto = trozos[0] if i > 0 else ""
                extra = " · ".join(trozos[1:i])
                break
        if not cuando:
            continue
        texto = limpiar_titulo(texto)
        if not texto:
            continue
        _put(con, fuente, cuando[0], cuando[1], texto[:300], f"{prod}|{limpiar_titulo(extra, verbo=False) or ''}"[:200])
        n += 1
    return n


def importar_takeout_json(con, nombre: str, data) -> int:
    n = 0
    low = _plain(nombre)
    if isinstance(data, dict) and ("semanticSegments" in data or "timelineObjects" in data):
        return importar_cronologia(con, data)
    if isinstance(data, dict) and "Browser History" in data:  # Chrome
        for it in data["Browser History"]:
            us = it.get("time_usec")
            if not us:
                continue
            d = datetime.fromtimestamp(us / 1e6)
            dom = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", it.get("url", ""))
            _put(con, "web", d.date().isoformat(), d.strftime("%H:%M"), f"visitó «{it.get('title') or dom}»", dom)
            n += 1
        return n
    if isinstance(data, list):  # YouTube / Mi actividad: [{header, title, time, subtitles}]
        yt = "watch-history" in low or "reproducciones" in low or "youtube" in low
        for it in data:
            t = _local(it.get("time") or "") if isinstance(it, dict) else None
            if not t:
                continue
            tit = (it.get("title") or "").strip()
            hdr = (it.get("header") or "").strip()
            if yt or "youtube" in _plain(hdr):
                canal = ((it.get("subtitles") or [{}])[0] or {}).get("name", "")
                fuente = "youtube"
                tit = re.sub(r"^(Viste|Watched)\s+", "vio ", tit) + (f" ({canal})" if canal else "")
            else:
                fuente = "busqueda" if re.search(r"b[uú]squeda|search", _plain(hdr) + low) else "actividad"
                tit = re.sub(r"^(Buscaste|Searched for)\s+", "buscó ", tit)
            _put(con, fuente, t[0], t[1], tit, hdr)
            n += 1
    return n


def _historiales_navegador() -> list[tuple[str, Path]]:
    """Archivos History de Chrome, Edge y Brave en este PC (perfiles del usuario, no los de Atlas)."""
    la = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    out = []
    for nombre, base in (("Chrome", la / "Google" / "Chrome" / "User Data"), ("Edge", la / "Microsoft" / "Edge" / "User Data"),
                         ("Brave", la / "BraveSoftware" / "Brave-Browser" / "User Data")):
        if base.exists():
            for perfil in base.iterdir():
                h = perfil / "History"
                if h.is_file() and (perfil.name == "Default" or perfil.name.startswith("Profile")):
                    out.append((f"{nombre}/{perfil.name}", h))
    return out


def _historiales_firefox() -> list[tuple[str, Path]]:
    """23-11: places.sqlite de los perfiles de Firefox (su navegador de uso; Edge no se usa desde octubre)."""
    base = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming")) / "Mozilla" / "Firefox" / "Profiles"
    out = []
    try:
        for perfil in base.iterdir():
            h = perfil / "places.sqlite"
            if h.is_file():
                out.append((f"Firefox/{perfil.name}", h))
    except OSError:
        pass
    return out


def _clasificar_visita(url: str, title: str, dom: str) -> tuple[str, str]:
    """23-11: una búsqueda de Google o un video de YouTube hecho en el navegador cuenta igual que los de Takeout."""
    from urllib.parse import parse_qs, urlsplit

    u = urlsplit(url)
    host = u.netloc.lower().split(":")[0]
    if re.match(r"(www\.)?google\.[a-z.]+$", host) and u.path == "/search":
        q = (parse_qs(u.query).get("q") or [""])[0].strip()
        if q:
            return "busqueda", f"buscó {q[:200]}"
    if host in ("www.youtube.com", "youtube.com", "m.youtube.com") and u.path == "/watch":
        t = re.sub(r"^\(\d+\)\s*", "", re.sub(r"\s*-\s*YouTube\s*$", "", title or "")).strip()
        if t:
            return "youtube", f"vio {t[:200]}"
    return "web", f"visitó «{(title or dom)[:150]}»"


def importar_navegador(con) -> int:
    """Historial local del navegador: se copia (está bloqueado con el navegador abierto) y se leen solo las visitas
    nuevas. Las páginas de Atlas (127.0.0.1) y las internas no cuentan. Chrome, Edge, Brave y (23-11) Firefox."""
    import shutil

    # lo que ya trajo Google Takeout (búsquedas y YouTube) no se repite: del navegador solo se toma lo posterior
    corte = (con.execute("SELECT MAX(fecha) FROM items WHERE fuente IN ('busqueda','youtube') AND detalle <> 'navegador'")
             .fetchone()[0] or "")
    n = 0
    fuentes_nav = [(nombre, h, "chromium") for nombre, h in _historiales_navegador()]
    fuentes_nav += [(nombre, h, "firefox") for nombre, h in _historiales_firefox()]
    for nombre, h, tipo in fuentes_nav:
        tmp = DIR / "_history_copia.sqlite"
        wal = Path(str(h) + "-wal")
        tmp_wal = Path(str(tmp) + "-wal")
        try:
            shutil.copy2(h, tmp)
            if tipo == "firefox" and wal.is_file():  # lo más reciente de Firefox está en el -wal
                shutil.copy2(wal, tmp_wal)
            src = sqlite3.connect(str(tmp))
            ultimo = int(_estado(con, f"nav_{nombre}") or 0)
            sql = ("SELECT v.visit_date, p.url, p.title FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id "
                   "WHERE v.visit_date>? ORDER BY v.visit_date") if tipo == "firefox" else (
                   "SELECT v.visit_time, u.url, u.title FROM visits v JOIN urls u ON u.id=v.url "
                   "WHERE v.visit_time>? ORDER BY v.visit_time")
            rows = src.execute(sql, (ultimo,)).fetchall()
            src.close()
        except Exception:  # noqa: BLE001
            continue
        finally:
            for t in (tmp, tmp_wal, Path(str(tmp) + "-shm")):
                try:
                    t.unlink()
                except OSError:
                    pass
        for vt, url, title in rows:
            ultimo = max(ultimo, vt)
            if not re.match(r"https?://", url or "") or re.match(r"https?://(127\.0\.0\.1|localhost)", url):
                continue
            if tipo == "firefox":  # microsegundos desde 1970 (UTC)
                d = datetime.fromtimestamp(vt / 1e6, __import__("datetime").timezone.utc).astimezone()
            else:  # microsegundos desde 1601 (UTC) en Chrome/Edge
                d = datetime(1601, 1, 1) + timedelta(microseconds=vt)
                d = d.replace(tzinfo=__import__("datetime").timezone.utc).astimezone()
            dom = re.sub(r"^https?://(www\.)?([^/:]+).*$", r"\2", url)
            fuente, titulo = _clasificar_visita(url, title or "", dom)
            if fuente != "web" and d.date().isoformat() < corte:
                continue
            _put(con, fuente, d.date().isoformat(), d.strftime("%H:%M"), titulo, dom if fuente == "web" else "navegador")
            n += 1
        _estado(con, f"nav_{nombre}", ultimo)
    return n


_RX_WA_LINEA = re.compile(
    r"^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]\.?\s?m\.?)?\]?\s*(?:-\s*)?([^:]{1,60}):\s?(.*)$", re.I)
_RX_WA_UBIC = re.compile(r"(?:maps\.google\.com/\?q=|maps\.google\.com/maps\?q=|goo\.gl/maps\S*|q=)(-?\d+\.\d+),\s*(-?\d+\.\d+)")


def leer_chat_whatsapp(texto: str) -> list[dict]:
    """Chat exportado de WhatsApp (.txt) -> [{fecha, hora, autor, texto}]. Las líneas sin fecha siguen el mensaje anterior."""
    out = []
    for linea in texto.replace("‎", "").replace(" ", " ").replace("\xa0", " ").splitlines():
        m = _RX_WA_LINEA.match(linea.strip())
        if m:
            dd, mm, yy, hh, mi, ampm, autor, msg = m.groups()
            yy = int(yy) + (2000 if len(yy) == 2 else 0)
            hh = int(hh)
            if ampm:
                pm = ampm.lower().startswith("p")
                hh = (hh % 12) + (12 if pm else 0)
            try:
                d = date(yy, int(mm), int(dd))
            except ValueError:
                continue
            out.append({"fecha": d.isoformat(), "hora": f"{hh:02d}:{mi}", "autor": autor.strip(), "texto": msg.strip()})
        elif out and linea.strip():
            out[-1]["texto"] += " " + linea.strip()
    return out


CHATS_DIR = DIR / "chats"


CHATS_SOLO_HORAS = True  # el usuario pidió (17-11-2026) no guardar los chats: de ellos solo quedan horas corridas ±1 min


def traer_chats_de_gmail() -> int:
    """Chats exportados que el usuario se mandó por correo (adjunto «Chat de WhatsApp con …»): se guardan en
    apps/cronos/chats (solo lectura del correo, nada sale del PC). -> adjuntos nuevos."""
    if CHATS_SOLO_HORAS:
        return 0
    import email
    from email.header import decode_header, make_header

    try:
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector

        c = GmailIMAPConnector()
        if not c.is_connected():
            return 0
        imap = c._open_imap()
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        imap.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = imap.search(None, "X-GM-RAW", '"has:attachment \\"Chat de WhatsApp\\""')
        for num in (data[0].split() if typ == "OK" and data and data[0] else []):
            typ, full = imap.fetch(num, "(BODY.PEEK[])")
            m = email.message_from_bytes(full[0][1])
            for part in m.walk():
                fn = part.get_filename()
                if not fn:
                    continue
                fn = str(make_header(decode_header(fn)))
                if not re.search(r"(?i)(chat de whatsapp|whatsapp chat)", fn) or not fn.lower().endswith((".zip", ".txt")):
                    continue
                huella = hashlib.sha1(fn.encode()).hexdigest()[:16]
                con_e = db()
                vistos = json.loads(_estado(con_e, "chats_traidos") or "[]")
                con_e.close()
                if huella in vistos:
                    continue
                destino = CHATS_DIR / f"chat_{huella}{Path(fn).suffix.lower()}"
                if destino.exists():
                    continue
                destino.write_bytes(part.get_payload(decode=True) or b"")
                n += 1
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return n


def _chats_whatsapp() -> list[tuple[str, str]]:
    """[(nombre del chat, texto)] de los chats exportados en Descargas o traídos del correo (.txt o .zip
    «Chat de WhatsApp con …»)."""
    out = []
    for base in list(config()["takeout"]) + [str(CHATS_DIR)]:
        b = Path(base)
        if not b.exists():
            continue
        for p in list(b.glob("*.txt")) + list(b.glob("*.zip")) + list(b.glob("WhatsApp*/*.txt")):
            nm = p.stem
            rx = r"(?i)(?:chat de whatsapp con|whatsapp chat with)\s+(.+?)(?:\.txt)?$"
            mm = re.search(rx, nm)
            if not mm and not (p.parent == CHATS_DIR and nm.startswith("chat_")):
                continue
            try:
                if p.suffix.lower() == ".zip":
                    z = zipfile.ZipFile(p)
                    tn = next((n for n in z.namelist() if n.lower().endswith(".txt")), "")
                    txt = z.read(tn).decode("utf-8", "replace") if tn else ""
                    mm = mm or re.search(rx, Path(tn).name)
                else:
                    txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            out.append(((mm.group(1).strip() if mm else nm), txt))
    return out


def importar_whatsapp(con) -> int:
    if CHATS_SOLO_HORAS:
        return 0
    chats = _chats_whatsapp()
    if not chats:
        return 0
    from collections import Counter

    leidos = [(nombre, leer_chat_whatsapp(t)) for nombre, t in chats]
    yo = config().get("mi_nombre_whatsapp")
    if not yo:  # el autor que aparece en más chats es él (en un solo chat: el que no es el nombre del chat)
        en = Counter(a for _, ms in leidos for a in {m["autor"] for m in ms})
        cands = [a for a, _ in en.most_common() if not any(_plain(a) == _plain(n) for n, _ in leidos)]
        yo = cands[0] if cands else ""
    # Privacidad de los demás (pedido del usuario): de los otros no se guarda ni el nombre ni lo que escribieron;
    # cada contacto queda como «contacto A», «contacto B»… y su nombre se borra también de los mensajes de él.
    alias = json.loads(_estado(con, "wa_alias") or "{}")
    n = 0
    for chat, msgs in leidos:
        otros = {m["autor"] for m in msgs if _plain(m["autor"]) != _plain(yo)} | {chat}
        for o in otros:
            k = hashlib.sha1(_plain(o).encode()).hexdigest()[:12]
            alias.setdefault(k, "contacto " + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[len(alias) % 26] + ("" if len(alias) < 26 else str(len(alias) // 26)))
        al_chat = alias[hashlib.sha1(_plain(chat).encode()).hexdigest()[:12]]
        palabras = sorted({w for o in otros for w in re.findall(r"\w{3,}", o)}, key=len, reverse=True)
        rx_nombres = re.compile(r"\b(" + "|".join(map(re.escape, palabras)) + r")\b", re.I) if palabras else None
        for m in msgs:
            mio = _plain(m["autor"]) == _plain(yo)
            u = _RX_WA_UBIC.search(m["texto"])
            if u:
                _put(con, "whatsapp_ubicacion", m["fecha"], m["hora"],
                     (f"compartió su ubicación con {al_chat}" if mio else f"{al_chat} le mandó una ubicación")
                     + f" ({float(u.group(1)):.4f}, {float(u.group(2)):.4f})", al_chat)
            elif re.search(r"(?i)ubicaci[oó]n en tiempo real|live location", m["texto"]):
                _put(con, "whatsapp_ubicacion", m["fecha"], m["hora"],
                     f"compartió su ubicación en tiempo real con {al_chat}" if mio else f"{al_chat} compartió su ubicación en tiempo real", al_chat)
            elif mio and not re.fullmatch(r"(?i)<?(multimedia omitido|media omitted|archivo omitido)>?|", m["texto"]):
                txt = rx_nombres.sub(al_chat, m["texto"]) if rx_nombres else m["texto"]
                _put(con, "whatsapp_chat", m["fecha"], m["hora"], txt[:200], al_chat)
            else:
                continue
            n += 1
    _estado(con, "wa_alias", json.dumps(alias))
    return n


GFOTOS_DIR = DIR / "google_fotos"


def importar_google_fotos(con) -> int:
    """Fotos de Google Fotos dentro de los zip de Takeout: se copian a historia/google_fotos (los zip pueden borrarse
    después) y se indexan como fotos propias con la fecha y el GPS de su .json. -> fotos nuevas."""
    if FOTOS_DESACTIVADAS:
        return 0
    hechos = set(json.loads(_estado(con, "gfotos_hechos") or "[]"))
    nuevas = 0
    for base in config()["takeout"]:
        b = Path(base)
        if not b.exists():
            continue
        for zp in sorted(b.glob("takeout*.zip")):
            try:
                z = zipfile.ZipFile(zp)
            except zipfile.BadZipFile:
                continue
            nombres = z.namelist()
            jsons = {n[:-5]: n for n in nombres if n.endswith(".json")}
            for n in nombres:
                if "/Google Fotos/" not in n and "/Google Photos/" not in n:
                    continue
                if Path(n).suffix.lower() not in EXT_FOTO:
                    continue
                clave = hashlib.sha1(n.encode()).hexdigest()[:16]
                if clave in hechos:
                    continue
                meta = {}
                jn = jsons.get(n) or next((jsons[k] for k in (n + ".supplemental-metadata", n + ".supplemental-metada",
                                                             n[:46]) if k in jsons), None)
                if jn:
                    try:
                        meta = json.loads(z.read(jn))
                    except ValueError:
                        meta = {}
                GFOTOS_DIR.mkdir(parents=True, exist_ok=True)
                dest = GFOTOS_DIR / (clave + Path(n).suffix.lower())
                if not dest.exists():
                    dest.write_bytes(z.read(n))
                t = int((meta.get("photoTakenTime") or {}).get("timestamp") or 0)
                g = meta.get("geoData") or {}
                lat, lon = (g.get("latitude") or None), (g.get("longitude") or None)
                if t:
                    dt = datetime.fromtimestamp(t)  # hora local del PC (Chile)
                    fecha, hora, de = dt.date().isoformat(), dt.strftime("%H:%M"), "google fotos"
                else:
                    fd = fecha_de_nombre(Path(n).name)
                    fecha, hora, de = (fd[0], fd[1], "nombre") if fd else (None, "", None)
                with _lock:
                    con.execute("INSERT OR IGNORE INTO fotos(ruta, origen, fecha, hora, fecha_de, lat, lon) VALUES(?,?,?,?,?,?,?)",
                                (str(dest), "cámara", fecha, hora, de, lat if lat else None, lon if lon else None))
                hechos.add(clave)
                nuevas += 1
            _estado(con, "gfotos_hechos", json.dumps(sorted(hechos)))
            con.commit()
    return nuevas



# ---- modo «señales» (17-11): para quien no tiene Rutas de Maps. De los chats de WhatsApp exportados solo quedan las
# horas en que él escribió (corridas ±1 min), sin texto ni contactos, y el archivo exportado se manda a la papelera.
_RX_CHAT_WA = re.compile(r"(?i)(?:chat de whatsapp con|whatsapp chat with)\s+(.+?)(?:\.txt|\.zip)?$")


def _a_papelera(ruta: Path) -> bool:
    """Manda un archivo a la papelera de Windows (se puede recuperar)."""
    try:
        import ctypes
        from ctypes import wintypes

        class SH(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]
        op = SH(None, 3, str(ruta) + "\0", None, 0x0040 | 0x0010 | 0x0400 | 0x0004, False, None, None)  # borrar, a la papelera, sin preguntar
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not ruta.exists()
    except Exception:  # noqa: BLE001
        return False


def chats_pendientes() -> list[Path]:
    out = []
    for base in config()["takeout"]:
        b = Path(base)
        if b.exists():
            out += [x for x in list(b.glob("*.txt")) + list(b.glob("*.zip")) if _RX_CHAT_WA.search(x.name)]
    return out


def _texto_chat(x: Path) -> str:
    if x.suffix.lower() == ".zip":
        z = zipfile.ZipFile(x)
        tn = next((n for n in z.namelist() if n.lower().endswith(".txt")), "")
        return z.read(tn).decode("utf-8", "replace") if tn else ""
    return x.read_text(encoding="utf-8", errors="replace")


def importar_chats_horas(con, archivos: list[Path] | None = None, borrar: bool = True) -> dict:
    """Chats exportados en Descargas -> solo las horas en que él escribió (±1 min). -> {chats, horas, sin_autor}."""
    from collections import Counter

    archivos = chats_pendientes() if archivos is None else archivos
    leidos = []
    for x in archivos:
        try:
            nombre = _RX_CHAT_WA.search(x.name).group(1).strip()
            leidos.append((x, nombre, leer_chat_whatsapp(_texto_chat(x))))
        except Exception:  # noqa: BLE001
            continue
    yo = config().get("mi_nombre_whatsapp") or ""
    if not yo:  # quién es él: el autor que aparece en varios chats, o el único que no es el contacto de un chat de dos
        en = Counter(a for _, _, ms in leidos for a in {m["autor"] for m in ms})
        varios = [a for a, k in en.most_common() if k > 1 and not any(_plain(a) == _plain(n) for _, n, _ in leidos)]
        if varios:
            yo = varios[0]
        else:
            for _, n, ms in leidos:
                resto = {m["autor"] for m in ms} - {a for a in {m["autor"] for m in ms} if _plain(a) == _plain(n)}
                if len(resto) == 1 and len({m["autor"] for m in ms}) == 2:
                    yo = resto.pop()
                    break
        if yo:
            guardar_config(mi_nombre_whatsapp=yo)  # su propio nombre en WhatsApp, solo en este PC
    vistos = set(json.loads(_estado(con, "chats_horas_vistos") or "[]"))
    res = {"chats": 0, "horas": 0, "sin_autor": 0}
    for x, _, ms in leidos:
        mios = [m for m in ms if yo and _plain(m["autor"]) == _plain(yo)]
        if not mios:
            res["sin_autor"] += 1
            continue
        firma = hashlib.sha1("".join(m["fecha"] + m["hora"] for m in ms).encode()).hexdigest()[:16]
        if firma not in vistos:
            for m in mios:
                t = max(0, min(23 * 60 + 59, _m(m["hora"]) + random.randint(-1, 1)))
                _put(con, "chat_hora", m["fecha"], _h(t), "", "")
                res["horas"] += 1
            vistos.add(firma)
        res["chats"] += 1
        if borrar:
            _a_papelera(x)
    _estado(con, "chats_horas_vistos", json.dumps(sorted(vistos)))
    con.commit()
    return res


def _rutas_error() -> dict | None:
    """19-11: si la descarga nocturna de Rutas de Maps está fallando, desde cuándo (lee solo fecha y estado del log)."""
    try:
        lineas = [x for x in (CRONO_DB.parent / "sincronizacion.log").read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    except OSError:
        return None
    desde = None
    for x in reversed(lineas):
        partes = x.split()
        if len(partes) < 2 or partes[1] != "ERROR":
            break
        desde = partes[0][:16].replace("T", " ")
    if not desde:
        return None
    google = "BadAuthentication" in lineas[-1]
    return {"desde": desde, "motivo": "Google cerró el acceso de Atlas a sus Rutas" if google else "la descarga está fallando"}


def _junto(q: dict, *claves) -> tuple | None:
    """23-11: (días, último) de varias fuentes juntas, para que «uso del PC» cuente también lo del navegador."""
    v = [q[k] for k in claves if k in q and q[k][1]]
    return (max(n for n, _ in v), max(u for _, u in v)) if v else None


def fuentes() -> dict:
    """Cómo se arma la historia (modo) y el estado de cada fuente, solo con conteos y fechas."""
    con = db()
    try:
        q = {f: (n, u) for f, n, u in con.execute("SELECT fuente, COUNT(DISTINCT fecha), MAX(fecha) FROM items GROUP BY fuente")}
    finally:
        con.close()
    hoy = date.today()

    def hace(u):
        return (hoy - date.fromisoformat(u)).days if u else None

    def f(id_, nombre, n_u, auto, aviso, accion="", umbral=None):
        n, u = n_u or (0, None)
        d = hace(u)
        estado = "au" if auto else ("no" if not n else "pe" if umbral is not None and (d is None or d > umbral) else "ok")
        return {"id": id_, "nombre": nombre, "dias": n, "ultimo": u, "hace": d, "estado": estado, "aviso": aviso, "accion": accion}

    rutas_n = None
    try:
        if CRONO_DB.exists():
            c2 = sqlite3.connect(f"file:{CRONO_DB.as_posix()}?mode=ro", uri=True)
            rutas_n = c2.execute("SELECT COUNT(DISTINCT substr(inicio,1,10)), MAX(substr(fin,1,10)) FROM visitas").fetchone()
            c2.close()
    except Exception:  # noqa: BLE001
        pass
    return {"modo": config().get("modo_ubicacion") or "",
            "rutas": {"activa": bool(rutas_n and rutas_n[0]), "dias": (rutas_n or (0,))[0], "ultimo": (rutas_n or (0, None))[1],
                      "error": _rutas_error()},
            "pendientes_chats": len(chats_pendientes()),
            "fuentes": [
                f("auto", "Recibos de viajes, gastos y calendario", q.get("gasto"), True, "Llegan solos (Gmail, Hermes y su calendario)."),
                f("bip", "Viajes en bip!", q.get("bip"), False, "Copie la tabla de tarjetabip.cl y péguela en Cronos.", "PEGAR", 7),
                f("maps", "Rutas buscadas en Maps (Google Takeout)", q.get("maps"), False,
                  "Pida en takeout.google.com «Mi actividad» de Maps y deje el zip en Descargas: Atlas lo toma solo.", "CÓMO", 30),
                f("chats", "Horas de sus chats de WhatsApp", q.get("chat_hora"), False,
                  "Exporte un chat «sin archivos» y déjelo en Descargas. Se guardan solo las horas en que usted escribió (±1 min) y el archivo va a la papelera.",
                  "IMPORTAR", 14),
                f("pc", "Búsquedas, YouTube y uso del PC", _junto(q, "busqueda", "youtube", "web"), True, "Solo dicen a qué hora estaba despierto.")]}


def importar_todo() -> dict:
    con = db()
    out = {"gastos": importar_hermes(con), "google_fotos": importar_google_fotos(con), "navegador": importar_navegador(con), "chats_correo": traer_chats_de_gmail()}
    out["whatsapp"] = importar_whatsapp(con)
    out["bip"] = importar_bip(con)
    if config().get("modo_ubicacion") == "senales":  # sin Rutas de Maps: los chats exportados aportan sus horas
        try:
            out["chats_horas"] = importar_chats_horas(con)["horas"]
        except Exception:  # noqa: BLE001
            pass
    if CHATS_DIR.exists():  # ya importados (solo lo de él, anonimizado): se borran las copias completas del PC
        vistos = set(json.loads(_estado(con, "chats_traidos") or "[]"))
        for f in CHATS_DIR.iterdir():
            m = re.match(r"chat_([0-9a-f]{16})", f.name)
            if m:
                vistos.add(m.group(1))
                f.unlink()
        _estado(con, "chats_traidos", json.dumps(sorted(vistos)))
    firma_vieja = json.loads(_estado(con, "takeout_firma") or "{}")
    firma = {}
    for nombre, leer in _archivos_takeout():
        try:
            raw = leer()
        except Exception:  # noqa: BLE001
            continue
        h = hashlib.sha1(raw).hexdigest()
        firma[nombre] = h
        if firma_vieja.get(nombre) == h:
            continue
        n = (importar_actividad_html(con, nombre, raw.decode("utf-8", "replace")) if nombre.lower().endswith(".html")
             else importar_takeout_json(con, nombre, _json_de(raw)))
        out[Path(nombre).name] = n
    _estado(con, "takeout_firma", json.dumps(firma))
    con.commit()
    con.close()
    return out


# ------------------------------------------------------------------ un día: todo lo que se sabe
def _es_ramo_dictado(titulo: str) -> bool:
    """Intro a la Programación (el ramo donde él es profesor auxiliar), aunque el evento no traiga el curso."""
    return bool(re.search(r"\b(intro(duccion)? a la progra(macion)?|cc1000|cc1001)\b", _plain(titulo or "")))


def _eventos(a: date, b: date) -> list[dict]:
    try:
        import atlas_agenda as A

        evs, _, _ = A.upcoming(datetime.combine(a, datetime.min.time()), datetime.combine(b + timedelta(days=1), datetime.min.time()),
                               incluir_listas=True)
        out = []
        for e in evs:
            dur = (e["end"] - e["start"]) if e.get("end") and e.get("start") and e["end"] > e["start"] else timedelta(hours=1)
            # todo lo del ramo que él dicta (cátedras, controles, auxiliares de Intro a la Progra) es como profesor auxiliar
            tipo = ("dicta" if (A.i_teach(e) or A.teaches_course(e.get("course", "")) or _es_ramo_dictado(e.get("summary", "")))
                    else "evaluacion" if A.is_evaluation(e) else "clase" if A.is_class(e)
                    else "entrega" if A.is_delivery(e) else "evento")
            out.append({"fecha": e["when"].date().isoformat(), "hora": "" if e.get("allday") else e["when"].strftime("%H:%M"),
                        "fin": "" if e.get("allday") else min(e["when"] + dur, datetime.combine(e["when"].date(), datetime.max.time())).strftime("%H:%M"),
                        "titulo": e.get("summary", ""), "lugar": e.get("location", ""), "clase": tipo == "clase",
                        "tipo": tipo, "curso": e.get("course", ""), "kind": e.get("kind", "")})
        return _juntar_repetidos(out)
    except Exception:  # noqa: BLE001
        return []


_GENERICAS = {"catedra", "auxiliar", "laboratorio", "ayudantia", "clase", "taller", "control", "examen", "sala", "seccion",
              "introduccion", "programacion", "perspectiva", "historica", "tecnologia", "sociedad", "ingenieria"}


def _palabras_ramo(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{6,}", _plain(t)) if w not in _GENERICAS}


def _juntar_repetidos(evs: list[dict]) -> list[dict]:
    """23-11: la misma clase anotada dos veces (U-Cursos «Auxiliar - Ciberseguridad» y en su calendario
    «Laboratorio Ciberseguridad», misma hora) sale una sola vez: queda la de U-Cursos (trae ramo y sala) y dura
    hasta la hora de término más tardía de las dos."""
    fuera = set()
    for i, a in enumerate(evs):
        if i in fuera or not a["hora"] or not a.get("curso"):
            continue
        clave = _palabras_ramo(a["curso"])
        if not clave:
            continue
        for j, b in enumerate(evs):
            if j == i or j in fuera or b.get("curso") or b["fecha"] != a["fecha"] or b["hora"] != a["hora"]:
                continue
            if clave & _palabras_ramo(b["titulo"]):
                fuera.add(j)
                if b["fin"] > a["fin"]:
                    a["fin"] = b["fin"]
    return [e for k, e in enumerate(evs) if k not in fuera]


_RX_VIAJE = re.compile(r"uber|didi|cabify|beat|indrive", re.I)


def _texto_correo(raw: bytes) -> str:
    import email
    import html as _html

    m = email.message_from_bytes(raw)
    partes = [p for p in m.walk() if p.get_content_type() in ("text/plain", "text/html")]
    partes.sort(key=lambda p: p.get_content_type() != "text/plain")
    for part in partes:
        try:
            t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if part.get_content_type() == "text/html":
            t = re.sub(r"(?is)<(style|script).*?</\1>", " ", t)
            t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) > 80:
            return t
    return ""


def _viaje_de_correo(imap, num, clave: str) -> dict | None:
    """Recibo de Uber/Didi/Cabify -> {"origen", "destino", "inicio", "fin"} sacado por el modelo LOCAL (se guarda)."""
    k = "viaje_" + hashlib.sha1(clave.encode()).hexdigest()[:16]
    con = db()
    try:
        hit = _estado(con, k)
        if hit:
            return json.loads(hit) or None
        typ, full = imap.fetch(num, "(BODY.PEEK[])")
        texto = _texto_correo(full[0][1])[:4000]
        if not texto:
            return None
        out = ollama_chat([{"role": "user", "content":
                            "Este es un recibo de un viaje (Uber, Didi, Cabify u otro). Devuelve SOLO un JSON con las "
                            "claves origen, destino, inicio y fin (horas HH:MM), usando las direcciones tal como aparecen; "
                            "usa \"\" si no está. Si no es un viaje realizado (promoción, código, cuenta), devuelve {}.\n\n"
                            + texto}], num_predict=160, timeout=60)
        m = re.search(r"\{.*\}", out, re.S)
        v = json.loads(m.group(0)) if m else {}
        v = {kk: str(v.get(kk) or "")[:150] for kk in ("origen", "destino", "inicio", "fin")} if v.get("destino") or v.get("origen") else {}
        _estado(con, k, json.dumps(v, ensure_ascii=False))
        return v or None
    finally:
        con.close()


_cache_correos: dict = {}


_correos_lock = threading.Lock()
_correos_en_curso: dict = {}
IMAP_TIMEOUT = 25  # s por lectura: sin esto una conexión de Gmail colgada dejaba a Cronos «armando su día» minutos (18-11)


def _correos(a: date, b: date, maximo: int = 40) -> list[dict]:
    """Correos de esos días (en memoria 10 minutos: el panel pide el día y en seguida el relato).
    Cronos pide el día y el relato a la vez: la segunda petición espera la primera en vez de abrir otro Gmail."""
    k = (a, b, maximo)
    with _correos_lock:
        hit = _cache_correos.get(k)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        ev = _correos_en_curso.get(k)
        mio = ev is None
        if mio:
            ev = _correos_en_curso[k] = threading.Event()
    if not mio:
        ev.wait(IMAP_TIMEOUT * 3)
        hit = _cache_correos.get(k)
        return hit[1] if hit else []
    est = {"ok": True}
    v: list[dict] = []
    try:
        v = _correos_imap(a, b, maximo, est)
    finally:
        with _correos_lock:  # si Gmail falló a medias, se reintenta al minuto en vez de a los 10
            _cache_correos[k] = (time.time() if est["ok"] else time.time() - 540, v)
            _correos_en_curso.pop(k, None)
        ev.set()
    return v


def _correos_imap(a: date, b: date, maximo: int = 40, est: dict | None = None) -> list[dict]:
    """Correos de esos días en el Gmail principal (solo encabezados, solo lectura, sin promociones ni redes)."""
    import email
    from email.header import decode_header, make_header
    from email.utils import parseaddr, parsedate_to_datetime

    try:
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector

        c = GmailIMAPConnector()
        if not c.is_connected():
            return []
        imap = c._open_imap()
        imap.sock.settimeout(IMAP_TIMEOUT)
    except Exception:  # noqa: BLE001
        if est is not None:
            est["ok"] = False
        return []
    out = []
    try:
        imap.select('"[Gmail]/All Mail"', readonly=True)
        q = f'after:{a:%Y/%m/%d} before:{(b + timedelta(days=1)):%Y/%m/%d} -category:promotions -category:social -category:forums'
        typ, data = imap.search(None, "X-GM-RAW", f'"{q}"')
        nums = data[0].split()[-maximo:] if typ == "OK" and data and data[0] else []
        for num in nums:
            typ, h = imap.fetch(num, "(X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
            meta = h[0][0].decode("utf-8", "replace") if h and h[0] else ""
            m = email.message_from_bytes(h[0][1])
            dec = lambda v: str(make_header(decode_header(v or "")))  # noqa: E731
            try:
                d = parsedate_to_datetime(m.get("Date")).astimezone()
            except Exception:  # noqa: BLE001
                continue
            enviado = "\\\\Sent" in meta
            quien = parseaddr(dec(m.get("To") if enviado else m.get("From")))
            item = {"fecha": d.date().isoformat(), "hora": d.strftime("%H:%M"), "enviado": enviado,
                    "quien": quien[0] or quien[1], "asunto": dec(m.get("Subject"))[:150]}
            if not enviado and _RX_VIAJE.search(f"{quien[0]} {quien[1]} {item['asunto']}"):
                try:
                    item["viaje"] = _viaje_de_correo(imap, num, m.get("Message-ID") or f"{item['fecha']}{item['hora']}{item['asunto']}")
                except Exception:  # noqa: BLE001
                    pass
            out.append(item)
    except Exception:  # noqa: BLE001
        if est is not None:
            est["ok"] = False
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def dia(a: date, b: date | None = None, correos: bool = True) -> dict:
    """Todo lo que hay entre a y b (incluidos), agrupado por fecha."""
    b = b or a
    con = db()
    fotos = [] if FOTOS_DESACTIVADAS else [dict(r) for r in con.execute(
        "SELECT id, fecha, hora, origen, descripcion, n_caras, yo, lat, lon FROM fotos WHERE fecha BETWEEN ? AND ? "
        "ORDER BY fecha, hora", (a.isoformat(), b.isoformat()))]
    items = [dict(r) for r in con.execute("SELECT fuente, fecha, hora, titulo, detalle FROM items WHERE fecha BETWEEN ? AND ? "
                                          "ORDER BY fecha, hora", (a.isoformat(), b.isoformat()))]
    con.close()
    um = config()["umbral_cara"]
    for f in fotos:
        f["usted"] = f["yo"] is not None and f["yo"] >= um
    ev_all = _eventos(a - timedelta(days=1), b)
    co_all = _correos(a - timedelta(days=1), b + timedelta(days=1)) if correos else []
    out = {"desde": a.isoformat(), "hasta": b.isoformat(), "fotos": fotos, "items": items,
           "eventos": [e for e in ev_all if e["fecha"] >= a.isoformat()],
           "correos": [c for c in co_all if a.isoformat() <= c["fecha"] <= b.isoformat()],
           "_previo": {"eventos": [e for e in ev_all if e["fecha"] < a.isoformat()],
                       "correos": [c for c in co_all if c["fecha"] < a.isoformat()],
                       "despues": [c for c in co_all if c["fecha"] > b.isoformat()]}}
    out["resumen"] = clasificar(out)
    con = db()
    vecinos = [dict(r) for r in con.execute("SELECT fuente, fecha, hora, titulo, detalle FROM items WHERE fecha BETWEEN ? AND ?",
                                            (a.isoformat(), b.isoformat()))]
    mom = _momentos(con, a - timedelta(days=1), b)
    con.close()
    out["sesiones"], out["cuartos"], out["sueno"] = {}, {}, {}
    f = a
    while f <= b:
        k = f.isoformat()
        out["sesiones"][k] = sesiones(vecinos, k)
        out["cuartos"][k] = cuartos(vecinos, k)
        out["sueno"][k] = sueno(mom, f)
        f += timedelta(days=1)
    out["bloques"], out["uso"] = {}, {}
    f = a
    while f <= b:
        try:
            out["uso"][f.isoformat()] = uso_por_hora(f)
        except Exception:  # noqa: BLE001
            pass
        try:
            out["bloques"][f.isoformat()] = bloques(out, f)
        except Exception as exc:  # noqa: BLE001
            out["bloques"][f.isoformat()] = [{"ini": "", "fin": "", "fila": "nota", "titulo": f"No pude armar los bloques: {exc}",
                                              "conf": "baja", "por": ""}]
        f += timedelta(days=1)
    # la noche: dónde durmió al terminar cada día lo decide el sueño del día siguiente (si despertó en la U y no hubo
    # viaje de vuelta, se quedó en la U; el relato ya no lo manda a dormir a la casa)
    f = a
    while f <= b and f < date.today():
        try:
            n = _noche_siguiente(out, f)
            if n:
                _cerrar_noche(out["bloques"][f.isoformat()], f, n)
        except Exception:  # noqa: BLE001
            pass
        f += timedelta(days=1)
    out.pop("_previo", None)
    return out


def _noche_siguiente(out: dict, f: date) -> dict | None:
    """Dónde durmió la noche que sigue al día f, con las mismas reglas que usa el día siguiente para su sueño."""
    f1 = f + timedelta(days=1)
    k, k1 = f.isoformat(), f1.isoformat()
    con = db()
    try:
        items = [dict(r) for r in con.execute("SELECT fuente, fecha, hora, titulo, detalle FROM items WHERE fecha=? ORDER BY fecha, hora", (k1,))]
        mom = _momentos(con, f, f1)
    finally:
        con.close()
    sn = sueno(mom, f1)
    if not sn:
        return None
    co = out.get("correos", []) + (out.get("_previo") or {}).get("despues", [])
    mini = {"items": items, "eventos": [e for e in _eventos(f1, f1) if e["fecha"] == k1], "fotos": [],
            "correos": [c for c in co if c["fecha"] == k1], "sueno": {k1: sn},
            "_previo": {"correos": [c for c in co if c["fecha"] == k], "eventos": [], "despues": []}}
    zz = next((b for b in bloques(mini, f1) if b["fila"] == "sueno"), None)
    m = re.search(r" en (.+?)(?: \(poco\))?$", (zz or {}).get("titulo", ""))
    if not m or m.group(1) == "su casa":
        return None
    return {"desde": sn["desde"], "donde": m.group(1), "por": zz.get("por", "")}


def _cerrar_noche(B: list[dict], f: date, n: dict) -> None:
    """Si esa noche durmió fuera de casa (p. ej. en la U), el día termina ahí: el último lugar sigue hasta que se durmió."""
    k = f.isoformat()
    if n["desde"][:10] == k:
        ini = n["desde"][11:]
    elif n["desde"][11:] < "05:00":
        ini = _h(_m(n["desde"][11:]) + 1440)
    else:
        return
    en_u = n["donde"] == "la U"
    lugares = sorted((b for b in B if b["fila"] == "lugar" and b["ini"] < ini), key=lambda b: b["ini"])
    ult = lugares[-1] if lugares else None
    if ult and ult.get("lugar") == "casa" and ult.get("_inferido"):  # la vuelta a casa era supuesta: esa noche no volvió
        B[:] = [b for b in B if not b.get("_inferido")]
        lugares = sorted((b for b in B if b["fila"] == "lugar" and b["ini"] < ini), key=lambda b: b["ini"])
        ult = lugares[-1] if lugares else None
    if ult and ult.get("lugar") == "casa":
        return  # el día ya lo deja en su casa (llegó o lo dijo): no se pisa
    if any(b["fila"] == "viaje" and (ult["fin"] if ult else "05:00") <= b["ini"] < ini for b in B):
        return  # hubo un viaje después: no se sabe que siguió ahí
    if ult and (ult.get("lugar") == "U") == en_u:
        ult["fin"] = max(ult["fin"], ini)
        ult["por"] = (ult.get("por") or "") + "; esa noche durmió ahí"
    B.append({"ini": ini, "fin": _h(min(_m(ini) + 90, 29 * 60 + 59)), "fila": "sueno", "titulo": f"Se quedó a dormir en {n['donde']}",
              "lugar": "U" if en_u else n["donde"], "conf": "media", "por": "al día siguiente despertó ahí y no hubo viaje de vuelta",
              "regla": "sueno: al día siguiente despertó ahí y no hubo viaje de vuelta"})
    B.sort(key=lambda b: (b["ini"] or "99", b["fin"]))


# Correos que suelen decir dónde estuvo o qué hizo (viajes, pedidos, reservas, boletas)
_RX_CORREO_LUGAR = re.compile(r"uber|didi|cabify|beat|indriver|metro|turbus|pullman|latam|sky ?airline|jetsmart|booking|"
                              r"airbnb|despegar|hotel|reserva|ticket|entrada|boleta|rappi|pedidosya|cornershop|ubereats|"
                              r"cinemark|cineplanet|puntoticket|passline|copec|shell|estacionamiento|parking", re.I)
# 17-11: un correo recibido no es algo que él hizo. Solo cuenta si es un comprobante (pedido, pago, reserva, viaje);
# la publicidad de esas mismas empresas («Uber: ofertas del súper») y los boletines no entran al relato.
_RX_MARKETING = re.compile(r"(?i)ofertas?\b|descuento|\d+ ?%|\bpromo|cup[oó]n|aprovecha|gratis|sorteo|te extra[ñn]amos|novedades|"
                           r"newsletter|bolet[ií]n|descubre|no te pierdas|solo por hoy|exclusiv|black ?friday|cyber|webinar|"
                           r"invitaci[oó]n|recomendad|sugerencia|lanzamiento|nuevo en|prueba .* gratis|\bganas?\b|regalo|"
                           r"cripto|bitcoin|resumen semanal|semana en|lo que te perdiste")
_RX_TRANSACCION = re.compile(r"(?i)confirma|recibo|comprobante|boleta|pedido|\borden\b|tu compra|pago|reserva|tu viaje|viaje con|"
                             r"entregad|en camino|devoluci[oó]n|reembolso|check-?in|pasaje|e-?ticket|factura|tarjeta de embarque")


def _correo_es_comprobante(c: dict) -> bool:
    t = f"{c.get('quien', '')} {c.get('asunto', '')}"
    return bool(_RX_CORREO_LUGAR.search(t) and _RX_TRANSACCION.search(c.get("asunto", "")) and not _RX_MARKETING.search(c.get("asunto", "")))


_CAT_PRESENCIAL = {"Comida", "Supermercado", "Transporte", "Salud", "Retiro de efectivo", "Compras"}
_CAT_ONLINE = {"Suscripciones", "Comisiones del banco", "Inversiones", "Pago de tarjeta", "Transferencias propias",
               "Transferencias a personas", "Ingresos", "Devoluciones y otros", "Préstamos recibidos", "Educación"}
_ACT_UTIL = {"vuelos", "hoteles", "shopping", "google lens", "asistente", "aplicaciones de gemini", "modo ia", "traductor de google",
             "drive", "libros"}


def clasificar(d: dict) -> dict:
    """Ordena un día en tres grupos: dónde estuvo (pistas con confianza), qué hizo, y contexto (no prueba nada).
    -> {fecha: {"lugares": [(hora, texto, confianza)], "hechos": [(hora, texto)], "contexto": {...}}}"""
    out = {}

    def g(f):
        return out.setdefault(f, {"lugares": [], "hechos": [], "contexto": {"busquedas": [], "youtube": [],
                                                                            "fotos_recibidas": [], "otros": [], "web": [],
                                                                            "chats": []}})
    for e in d["eventos"]:
        x = g(e["fecha"])
        if not e.get("lugar") and not e.get("clase"):
            x["hechos"].append((e["hora"], f"calendario: {e['titulo']}"))
        if e.get("clase") and not e.get("lugar"):
            x["lugares"].append((e["hora"], f"tenía clase ({e.get('curso') or e['titulo']}): probablemente en la universidad",
                                 "baja (estaba en su horario; no confirma que fue)"))
        if e.get("lugar"):
            x["lugares"].append((e["hora"], f"evento «{e['titulo']}» en {e['lugar']}", "media (estaba agendado)"))
    for it in d["items"]:
        x, f, t, h = g(it["fecha"]), it["fuente"], it["titulo"], it["hora"] or ""
        det = _plain(it.get("detalle") or "")
        if f == "ubicacion":
            x["lugares"].append((h, t, "alta (ubicación del teléfono)"))
        elif f == "gasto":
            cat, _, tipo = (it.get("detalle") or "").partition("|")
            tipo, _, sii = tipo.partition("|")
            comuna = sii.split("~")[0]
            x["hechos"].append((h, f"gasto: {t}" + (f" ({cat})" if cat else "")))
            comercio = t.split(" en ", 1)[-1]
            if t.startswith("cargo") and tipo in ("compra", "") and cat in _CAT_PRESENCIAL:
                x["lugares"].append((h, f"compró en {comercio} ({cat.lower()})" + (f", empresa de {comuna}" if comuna else ""),
                                     "media (compra con tarjeta; casi siempre en persona)"))
            elif t.startswith("cargo") and tipo in ("compra", "") and cat not in _CAT_ONLINE:
                x["lugares"].append((h, f"pagó en {comercio}", "baja (puede ser por internet)"))
            elif t.startswith("abono") and cat == "Devoluciones y otros":
                x["hechos"].append((h, f"{comercio} le devolvió su parte de algo: probablemente compartieron un gasto ese día o antes"))
        elif f == "maps":
            m = re.match(r"(?i)indicaciones (?:a|hacia|para ir a)\s+(.*)", t)
            if m:
                x["lugares"].append((h, f"pidió indicaciones en Maps para ir a {m.group(1)}", "media (iba o pensaba ir)"))
            elif t.startswith("buscó "):
                x["lugares"].append((h, f"buscó en Maps «{t[6:]}»", "baja (buscó un lugar; quizás fue)"))
            elif not re.match(r"(?i)explorad|vio |usó ", t):
                x["lugares"].append((h, f"miró en Maps «{t}»", "baja (miró un lugar; quizás fue)"))
        elif f == "busqueda":
            x["contexto"]["busquedas"].append((h, t))
        elif f == "youtube":
            x["contexto"]["youtube"].append((h, t))
        elif f == "whatsapp_ubicacion":
            mc = _RX_COORD.search(t)
            if mc and lugar_de(float(mc.group(1)), float(mc.group(2))):
                t = _RX_COORD.sub(f"({lugar_de(float(mc.group(1)), float(mc.group(2)))})", t)
            x["lugares"].append((h, t, "alta (ubicación que él compartió)" if t.startswith("compartió") else
                                 "baja (ubicación que le mandaron)"))
        elif f == "whatsapp_chat":
            x["contexto"]["chats"].append((h, t, it.get("detalle") or ""))
        elif f == "web":
            x["contexto"]["web"].append((h, it.get("detalle") or t))
        elif f == "actividad" and det in _ACT_UTIL:
            (x["hechos"] if det in ("vuelos", "hoteles") else x["contexto"]["otros"]).append((h, f"{it.get('detalle')}: {t}"))
        # Play Store, Gmail (los correos ya están), Android, Discover…: ruido, no se usa
    for c in d["correos"]:
        x = g(c["fecha"])
        txt = f"correo {'que envió a' if c['enviado'] else 'de'} {c['quien']}: {c['asunto']}"
        v = c.get("viaje")
        if v:
            tramo = " ".join(x for x in (f"de {v['origen']}" if v.get("origen") else "", f"a {v['destino']}" if v.get("destino") else "") if x)
            hh = v.get("inicio") or c["hora"]
            x["lugares"].append((hh, f"viaje en {c['quien']} {tramo}" + (f", llegó cerca de las {v['fin']}" if v.get("fin") else ""),
                                 "alta (recibo del viaje)"))
            continue
        if c["enviado"]:
            x["hechos"].append((c["hora"], txt))
        elif _correo_es_comprobante(c):
            x["hechos"].append((c["hora"], f"comprobante de {c['quien']}: {c['asunto']}"))
            x["lugares"].append((c["hora"], f"según un comprobante de {c['quien']}: {c['asunto']}", "media (viaje, pedido o reserva)"))
        # los demás correos recibidos (publicidad, boletines, avisos) no dicen nada de lo que hizo: no se usan
    for p in d["fotos"]:
        x = g(p["fecha"])
        quien = " (aparece usted)" if p["usted"] else ""
        desc = p["descripcion"] or "sin describir aún"
        if p.get("lat") is not None:
            x["lugares"].append((p["hora"] or "", "foto con GPS " + (lugar_de(p["lat"], p["lon"]) or f"en {p['lat']:.4f}, {p['lon']:.4f}"), "alta (GPS de la foto)"))
        if p["origen"] in ("cámara", "whatsapp enviada") or p["usted"]:
            cual = {"cámara": "de su cámara", "whatsapp enviada": "que él envió"}.get(p["origen"], "recibida")
            x["hechos"].append((p["hora"] or "", f"foto {cual}{quien}: {desc}"))
        elif p["origen"] == "captura":
            x["contexto"]["otros"].append((p["hora"] or "", f"captura de pantalla: {desc}"))
        else:
            x["contexto"]["fotos_recibidas"].append((p["hora"] or "", desc))
    for x in out.values():
        x["lugares"] = agrupar_lugares(x["lugares"])
        x["hechos"].sort(key=lambda r: r[0] or "99")
    return out


def direccion_corta(t: str) -> str:
    """«Av. Ejemplo 1234, 7500000 Comuna Ejemplo, Región Metropolitana» -> «Av. Ejemplo 1234, Comuna Ejemplo»."""
    partes = [x.strip() for x in t.split(",") if x.strip()]
    partes = [re.sub(r"^\d{7}\s*", "", x) for x in partes]
    partes = [x for x in partes if x and not re.match(r"(?i)regi[oó]n|chile$|santiago metropolitan", x)]
    return ", ".join(partes[:2]) if partes else t


_RX_LUGAR_MAPS = re.compile(r"^(?:pidió indicaciones en Maps para ir a |buscó en Maps «|miró en Maps «)(.*?)»?$")
_ORDEN_CONF = {"alta": 3, "media": 2, "baja": 1}


def agrupar_lugares(lugares: list[tuple]) -> list[tuple]:
    """Junta las pistas de Maps sobre el mismo lugar con menos de 2 h entre sí en una sola: «10:43–10:49 pidió ruta a
    Av. Ejemplo 1234, Comuna Ejemplo» con la mejor confianza. Las demás pistas quedan igual, con el texto acortado."""
    def clave(dir_):
        d = _plain(direccion_corta(dir_)).replace("avenida", "av").replace("av.", "av")
        return re.sub(r"[^a-z0-9]+", " ", d.split(",")[0]).strip()

    out, abiertos = [], {}
    for h, t, c in sorted(lugares, key=lambda r: r[0] or "99"):
        m = _RX_LUGAR_MAPS.match(t)
        if not m or not h:
            out.append((h, t if len(t) <= 120 else t[:117] + "…", c))
            continue
        k = clave(m.group(1))
        ruta = t.startswith("pidió")
        g = abiertos.get(k)
        mins = int(h[:2]) * 60 + int(h[3:5])
        if g and mins - g["fin_m"] <= 120:
            g["fin"], g["fin_m"] = h, mins
            g["ruta"] = g["ruta"] or ruta
            if len(direccion_corta(m.group(1))) > len(g["dir"]):  # la versión con comuna
                g["dir"] = direccion_corta(m.group(1))
            if _ORDEN_CONF.get(c.split()[0], 0) > _ORDEN_CONF.get(g["c"].split()[0], 0):
                g["c"] = c
            g["n"] += 1
            continue
        g = {"ini": h, "fin": h, "fin_m": mins, "dir": direccion_corta(m.group(1)), "ruta": ruta, "c": c, "n": 1}
        abiertos[k] = g
        out.append(g)
    res = []
    for g in out:
        if isinstance(g, dict):
            hh = g["ini"] if g["fin"] == g["ini"] else f"{g['ini']}–{g['fin']}"
            res.append((hh, f"{'pidió ruta a' if g['ruta'] else 'buscó en Maps'} {g['dir']}", g["c"]))
        else:
            res.append(g)
    return res


_GEO = []


def lugar_de(lat: float, lon: float) -> str:
    """Coordenadas -> «cerca de <lugar>, <comuna>» con el listado público de GeoNames Chile (apps/cronos/geonames),
    sin consultar nada fuera del PC. "" si no hay listado."""
    import math

    if not _GEO:
        try:
            z = zipfile.ZipFile(DIR / "geonames" / "CL.zip")
            for l in z.read("CL.txt").decode("utf-8").splitlines():
                c = l.split("	")
                if c[6] in ("S", "L", "P") or c[7] == "ADM3":
                    _GEO.append((float(c[4]), float(c[5]), c[1], c[6], c[7]))
        except Exception:  # noqa: BLE001
            return ""
    kx = math.cos(math.radians(lat)) * 111.3

    def dist(g):
        return math.hypot((g[0] - lat) * 111.3, (g[1] - lon) * kx)
    comuna = min((g for g in _GEO if g[4] == "ADM3"), key=dist, default=None)
    cerca = min((g for g in _GEO if g[3] in ("S", "L", "P") and abs(g[0] - lat) < 0.01 and abs(g[1] - lon) < 0.012), key=dist, default=None)
    partes = []
    if cerca and dist(cerca) < 0.5:
        partes.append(f"cerca de {cerca[2]}")
    if comuna and dist(comuna) < 25:
        partes.append(f"comuna de {re.sub(r'^Comuna de ', '', comuna[2])}")
    return ", ".join(partes)


_RX_COORD = re.compile(r"\((-?\d+\.\d+), (-?\d+\.\d+)\)")


_RX_MUSICA = re.compile(r" - Topic$|VEVO$|music video|\bMV\b|lyrics|\bOP\b|opening|ending|remaster|official audio|"
                        r"official video|feat\.|\(audio\)|歌|」", re.I)


def tipo_digital(it: dict) -> str | None:
    """Qué clase de actividad digital es un registro: música, videos, búsqueda, web, maps, chat, app (o None)."""
    f, t = it["fuente"], it.get("titulo") or ""
    det = it.get("detalle") or ""
    canal = det.split("|", 1)[1] if "|" in det else ""
    if f == "youtube":
        if t.startswith("buscó"):
            return "búsqueda"
        return "música" if _RX_MUSICA.search(f"{t} {canal}") else "videos"
    if f == "busqueda":
        return "web" if t.startswith(("visitó", "vio")) else "búsqueda"
    if f == "web":
        return "web"
    if f == "maps":
        return "maps"
    if f in ("whatsapp_chat", "chat_hora"):  # chat_hora: solo la hora (sin texto) de que escribió
        return "chat"
    if f == "actividad" and _plain(det.split("|")[0]) in _ACT_UTIL:
        return "app"
    return None


def _artista(it: dict) -> str:
    det = it.get("detalle") or ""
    canal = det.split("|", 1)[1] if "|" in det else ""
    canal = re.sub(r"\s*-\s*Topic$|VEVO$|\s*Official.*$|\s*オフィシャル.*$", "", canal).strip()
    return canal or re.sub(r"^vio\s+", "", it.get("titulo") or "")[:40]


def sesiones(items: list[dict], fecha: str, hueco_min: int = 40) -> list[dict]:
    """Agrupa la actividad digital de un día en sesiones (mismo tipo, sin pausas de más de hueco_min minutos):
    «escuchó música 10:32–11:07, 9 temas: Spandau Ballet, Modern Talking…»."""
    from collections import Counter

    por = {}
    for it in items:
        if it["fecha"] != fecha or not it.get("hora"):
            continue
        tp = tipo_digital(it)
        if tp and tp != "música":  # pedido del usuario: la música no se muestra
            por.setdefault(tp, []).append(it)
    out = []
    for tp, its in por.items():
        its.sort(key=lambda r: r["hora"])
        grupo = [its[0]]

        def cerrar(g):
            ini, fin = g[0]["hora"], g[-1]["hora"]
            if tp == "música":
                top = Counter(_artista(r) for r in g).most_common(5)
                muestra = [a for a, _ in top]
            elif tp == "videos":
                muestra = list(dict.fromkeys(re.sub(r"^vio\s+", "", r["titulo"])[:70] for r in g))[:5]
            elif tp == "búsqueda":
                muestra = list(dict.fromkeys(re.sub(r"^buscó\s+", "", r["titulo"]) for r in g))[:8]
            elif tp == "web":
                muestra = [d for d, _ in Counter(re.sub(r"^(visitó|vio)\s+", "", r["titulo"])[:60] for r in g).most_common(5)]
            elif tp == "chat":
                muestra = [c for c, _ in Counter((r.get("detalle") or "") for r in g).most_common(5)]
            else:
                muestra = list(dict.fromkeys(r["titulo"][:60] for r in g))[:5]
            out.append({"tipo": tp, "ini": ini, "fin": fin, "n": len(g), "muestra": muestra})

        for r in its[1:]:
            a, b = grupo[-1]["hora"], r["hora"]
            gap = (int(b[:2]) * 60 + int(b[3:5])) - (int(a[:2]) * 60 + int(a[3:5]))
            if gap > hueco_min:
                cerrar(grupo)
                grupo = [r]
            else:
                grupo.append(r)
        cerrar(grupo)
    return sorted(out, key=lambda x: x["ini"])


def cuartos(items: list[dict], fecha: str) -> list[dict]:
    """Actividad por cuarto de hora (96 casillas): {i, n, tipo} con el tipo más frecuente de cada casilla."""
    from collections import Counter

    cas = {}
    for it in items:
        if it["fecha"] != fecha or not it.get("hora"):
            continue
        tp = tipo_digital(it)
        if tp and tp != "música":
            i = int(it["hora"][:2]) * 4 + int(it["hora"][3:5]) // 15
            cas.setdefault(i, Counter())[tp] += 1
    return [{"i": i, "n": sum(c.values()), "tipo": c.most_common(1)[0][0]} for i, c in sorted(cas.items())]


def _momentos(con, a: date, b: date) -> list[datetime]:
    """Momentos en que usó algo (búsquedas, YouTube, web, Maps, mensajes, fotos de su cámara, Atlas) entre a y b."""
    out = []
    for r in con.execute("SELECT fuente, fecha, hora, titulo, detalle FROM items WHERE fecha BETWEEN ? AND ? AND hora<>''",
                         (a.isoformat(), b.isoformat())):
        if r["fuente"] in ("gasto", "ubicacion"):
            continue
        if r["fuente"] == "actividad" and tipo_digital(dict(r)) is None:
            continue  # Play Store y similares se actualizan solos
        out.append(datetime.fromisoformat(f"{r['fecha']}T{r['hora']}"))
    for r in con.execute("SELECT fecha, hora FROM fotos WHERE origen IN ('cámara','whatsapp enviada','captura') AND hora<>'' "
                         "AND fecha BETWEEN ? AND ?", (a.isoformat(), b.isoformat())):
        out.append(datetime.fromisoformat(f"{r['fecha']}T{r['hora']}"))
    try:  # turnos con Atlas (historial local)
        for f in (HERE / "historial").glob("*.jsonl"):  # nombre = fecha de la sesión; cada turno trae "hora"
            dia0 = f.name[:10]
            if not (a - timedelta(days=1)).isoformat() <= dia0 <= b.isoformat():
                continue
            ult = None
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.search(r'"hora"\s*:\s*"(\d{2}:\d{2})', line)
                if not m:
                    continue
                t = datetime.fromisoformat(f"{dia0}T{m.group(1)}")
                if ult and t < ult - timedelta(hours=1):  # la sesión pasó la medianoche
                    t += timedelta(days=1)
                ult = t
                if a <= t.date() <= b:
                    out.append(t)
    except Exception:  # noqa: BLE001
        pass
    return sorted(set(out))


def sueno(momentos: list[datetime], fecha: date) -> dict | None:
    """La noche antes de «fecha»: la pausa más larga sin actividad entre las 18:00 del día anterior y las 15:00.
    -> {desde, hasta, horas, confianza, nota} o None si no hay datos a ambos lados."""
    ini = datetime.combine(fecha - timedelta(days=1), datetime.min.time()) + timedelta(hours=18)
    fin = datetime.combine(fecha, datetime.min.time()) + timedelta(hours=15)
    ms = [m for m in momentos if ini <= m <= fin]
    if len(ms) < 2:
        return None
    gaps = [(ms[i + 1] - ms[i], i) for i in range(len(ms) - 1)]
    gap, i = max(gaps)
    horas = gap.total_seconds() / 3600
    if horas < 3:
        return None
    antes = sum(1 for m in ms if ms[i] - timedelta(hours=1) <= m <= ms[i])
    despues = sum(1 for m in ms if ms[i + 1] <= m <= ms[i + 1] + timedelta(hours=1))
    conf = "media" if 4 <= horas <= 11 and antes >= 3 and despues >= 2 else "baja"
    return {"desde": ms[i].strftime("%Y-%m-%d %H:%M"), "hasta": ms[i + 1].strftime("%Y-%m-%d %H:%M"), "horas": round(horas, 1),
            "confianza": conf, "nota": "según su último y primer uso registrado (búsquedas, YouTube, web, mensajes, "
                                       "Atlas); el celular sin registro puede correrlo"}


# ------------------------------------------------------------------ bloques del día (línea de tiempo)
def _hhmm(t: str) -> str | None:
    m = re.search(r"(\d{1,2})[:.h](\d{2})\s*(?:([ap])\.?\s?m\b\.?)?", t or "", re.I)
    if not m:
        return None
    h = int(m.group(1))
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "p" else 0)
    return f"{h:02d}:{m.group(2)}" if h < 24 and int(m.group(2)) < 60 else None


def _m(h: str) -> int:
    return int(h[:2]) * 60 + int(h[3:5])


def _h(m: int) -> str:
    m = max(0, min(29 * 60 + 59, int(m)))
    return f"{m // 60:02d}:{m % 60:02d}"


def clave_direccion(t: str) -> str:
    d = _plain(direccion_corta(t or "")).replace("avenida", "av").replace("av.", "av")
    return re.sub(r"[^a-z0-9]+", " ", d.split(",")[0]).strip()


def misma_direccion(a: str, b: str) -> bool:
    """Claves de dirección: iguales, o una sin número (recibo de Cabify) cuyas palabras están todas en la otra."""
    if not a or not b:
        return False
    if a == b:
        return True
    ca, cb = set(a.split()), set(b.split())
    sin_num = lambda c: not any(x.isdigit() for x in c)  # noqa: E731
    return (sin_num(ca) and len(ca) >= 2 and ca <= cb) or (sin_num(cb) and len(cb) >= 2 and cb <= ca)


def casa_conocida() -> str:
    """Su casa: config «casa», o el destino más repetido de sus viajes de noche (recibos ya leídos)."""
    c = config().get("casa")
    if c:
        return clave_direccion(c)
    from collections import Counter

    con = db()
    cnt = Counter()
    for (v,) in con.execute("SELECT v FROM estado WHERE k LIKE 'viaje_%'"):
        try:
            x = json.loads(v or "{}")
        except ValueError:
            continue
        h = _hhmm(x.get("inicio") or "") or ""
        if x.get("destino") and (h >= "19:00" or (h and h < "05:00")):
            cnt[clave_direccion(x["destino"])] += 1
    con.close()
    top = cnt.most_common(1)
    return top[0][0] if top and top[0][1] >= 2 else ""


def _viajes(correos: list[dict]) -> list[dict]:
    out = []
    for c in correos:
        v = c.get("viaje")
        if not v:
            continue
        fin = _hhmm(v.get("fin") or "") or c["hora"]
        ini = _hhmm(v.get("inicio") or "") or _h(_m(fin) - 25)
        if _m(ini) > _m(fin):
            ini = _h(_m(fin) - 25)
        app = re.sub(r"(?i)^(.*?(uber|didi|cabify|beat|indrive)).*$", r"\2", c["quien"]).capitalize()
        out.append({"fecha": c["fecha"], "ini": ini, "fin": fin, "app": app, "origen": v.get("origen") or "",
                    "destino": v.get("destino") or ""})
    return sorted(out, key=lambda x: x["ini"])


def _nombre_lugar(dir_: str, casa: str) -> tuple[str, str]:
    """-> (clave, nombre para mostrar): «casa», «U» o la dirección corta."""
    k = clave_direccion(dir_)
    if casa and misma_direccion(k, casa):
        return "casa", "su casa"
    if re.search(r"(?i)beauchef|blanco encalada 2|fcfm|universidad de chile|u\. de chile", dir_ or ""):
        return "U", "la U"
    return k, direccion_corta(dir_)


def _chat_dice(fecha: date, msgs: list[tuple[str, str]]) -> list[dict]:
    """Lo que él mismo dijo por chat sobre dónde estaba o qué hacía (modelo local, se guarda).
    -> [{"hora", "lugar", "actividad"}] solo cuando lo dice claramente."""
    if not msgs:
        return []
    txt = "\n".join(f"{h} {t[:160]}" for h, t in msgs[:220])
    k = "chatdice_" + fecha.isoformat() + "_" + hashlib.sha1(txt.encode()).hexdigest()[:10]
    con = db()
    try:
        hit = _estado(con, k)
        if hit is not None:
            return json.loads(hit)
        out = ollama_chat([{"role": "user", "content":
                            "Estos son mensajes que una persona escribió por WhatsApp en un día, con su hora. Extrae SOLO lo "
                            "que ella dice claramente sobre dónde está o qué está haciendo en ese momento (por ejemplo «estoy "
                            "en la u estudiando», «voy llegando a la casa», «me quedé dormido en la u»). Devuelve SOLO un JSON: "
                            "lista de objetos {\"hora\": \"HH:MM\", \"lugar\": \"u|casa|otro lugar dicho|\", "
                            "\"actividad\": \"pocas palabras\"}. Si no dice nada de eso, devuelve [].\n\n" + txt}],
                          num_predict=400, timeout=120)
        m = re.search(r"\[.*\]", out, re.S)
        try:
            lst = json.loads(m.group(0)) if m else []
        except ValueError:
            lst = []
        lst = [{"hora": _hhmm(str(x.get("hora", ""))) or "", "lugar": str(x.get("lugar") or "")[:60],
                "actividad": str(x.get("actividad") or "")[:60]} for x in lst if isinstance(x, dict)]
        lst = [x for x in lst if x["hora"] and (x["lugar"] or x["actividad"])][:20]
        _estado(con, k, json.dumps(lst, ensure_ascii=False))
        return lst
    finally:
        con.close()


def uso_por_hora(f: date, semanas: int = 8) -> list[dict]:
    """Uso del celular/PC por hora ese día (00 a 05 del día siguiente = horas 24-29) contra lo normal para ese día de la
    semana (promedio de las últimas semanas). -> [{"h", "n", "base"}]"""
    con = db()
    try:
        mom = _momentos(con, f - timedelta(days=7 * semanas), f + timedelta(days=1))
    finally:
        con.close()
    cuenta: dict = {}
    for t in mom:
        dd, h = t.date(), t.hour
        if h < 5:
            dd, h = dd - timedelta(days=1), h + 24
        cuenta[(dd, h)] = cuenta.get((dd, h), 0) + 1
    previos = [f - timedelta(days=7 * i) for i in range(1, semanas + 1)]
    con_datos = [x for x in previos if any((x, h) in cuenta for h in range(30))] or previos
    return [{"h": h, "n": cuenta.get((f, h), 0),
             "base": round(sum(cuenta.get((x, h), 0) for x in con_datos) / len(con_datos), 1)} for h in range(30)]


def tramos_quietos(uso: list[dict], despierto: tuple[int, int], factor: float = 0.35, base_min: float = 3) -> list[tuple[int, int, int, float]]:
    """Tramos despierto (de 2 h o más) en que usó el celular mucho menos que de costumbre. Se mira de a 2 horas porque
    una hora sola es muy ruidosa. -> [(h_ini, h_fin, usos, lo normal)]"""
    por_h = {u["h"]: u for u in uso}
    quieta = set()
    for h in range(despierto[0], despierto[1] - 1):
        n = por_h.get(h, {}).get("n", 0) + por_h.get(h + 1, {}).get("n", 0)
        base = por_h.get(h, {}).get("base", 0) + por_h.get(h + 1, {}).get("base", 0)
        if base >= base_min and n <= factor * base:
            quieta |= {h, h + 1}
    out, cur = [], None
    for h in sorted(quieta) + [99]:
        if cur and h == cur[1]:
            cur[1] = h + 1
            continue
        if cur:
            hs = range(cur[0], cur[1])
            out.append((cur[0], cur[1], sum(por_h[x]["n"] for x in hs), round(sum(por_h[x]["base"] for x in hs), 1)))
        cur = [h, h + 1]
    return out


def regla_de(b: dict) -> str:
    """Qué regla armó el bloque (para medir cuáles aciertan), sin números ni nombre de la app."""
    por = re.sub(r"\d+|uber|didi|cabify|beat|indrive", "", (b.get("por") or "").split(";")[0].lower())
    return b["fila"] + ": " + re.sub(r"\s+", " ", por).strip(" ()")


_ORDEN = ["baja", "media", "alta"]


def estadisticas_revision() -> dict:
    """Por regla: cuántos bloques revisó el usuario, cuántos acertaron el lugar/actividad y el desfase de hora."""
    con = db()
    rows = con.execute("SELECT * FROM revision WHERE veredicto IN ('ok','mal','corregido')").fetchall()
    con.close()
    out: dict = {}
    for r in rows:
        x = out.setdefault(r["regla"], {"n": 0, "bien": 0, "desfases": []})
        x["n"] += 1
        if r["veredicto"] == "ok" or (r["veredicto"] == "corregido" and not r["c_titulo"]):
            x["bien"] += 1  # lo corregido solo en la hora cuenta como lugar bien
        if r["veredicto"] == "corregido" and r["c_ini"] and r["ini"]:
            x["desfases"].append(_m(r["c_ini"]) - _m(r["ini"]))
    return out


_PREVIO_CONF = {"alta": 0.85, "media": 0.65, "baja": 0.45}


def peso_regla(x: dict, conf: str) -> float:
    """Probabilidad de acierto de una regla: su confianza de fábrica vale como 2 revisiones y se mezcla con lo que el
    usuario marcó (lo corregido solo en la hora cuenta como bien)."""
    p0 = _PREVIO_CONF.get(conf, 0.5)
    return (x["bien"] + 2 * p0) / (x["n"] + 2)


def ajustar_con_revisiones(B: list[dict], st: dict | None = None) -> None:
    """Usa lo que el usuario marcó en el Diagnóstico: cada regla queda con la confianza que se ganó (alta ≥ 80 %,
    media ≥ 55 %, baja el resto); si casi siempre falla (< 35 % con 3 revisiones o más) deja de mostrarse; y si se
    equivoca de hora siempre hacia el mismo lado, se corre."""
    if st is None:
        try:
            st = estadisticas_revision()
        except Exception:  # noqa: BLE001
            return
    fuera = []
    for b in B:
        x = st.get(b.get("regla"))
        if not x or not x["n"]:
            continue
        p = peso_regla(x, b["conf"])
        b["peso"] = round(p, 2)
        if x["n"] >= 3 and p < 0.35:
            fuera.append(b)
            continue
        b["conf"] = "alta" if p >= 0.8 else "media" if p >= 0.55 else "baja"
        b["por"] += f" · según sus revisiones acierta {x['bien']} de {x['n']}"
        ds = sorted(x["desfases"])
        if len(ds) >= 3 and b["fila"] in ("lugar", "sueno") and b["ini"]:
            med = ds[len(ds) // 2]
            if abs(med) >= 15:
                b["ini"] = _h(_m(b["ini"]) + med)
                b["por"] += f" (hora corrida {med:+d} min por sus correcciones)"
    for b in fuera:
        B.remove(b)


def _id_bloque(fecha: str, b: dict) -> str:
    return hashlib.sha1(f"{fecha}|{b['fila']}|{b.get('regla', '')}|{b['titulo']}".encode()).hexdigest()[:16]


def diagnostico(n: int = 7, hasta: date | None = None) -> dict:
    """Los últimos n días con sus bloques, para que el usuario marque cada uno bien / mal / corregido."""
    b = hasta or (date.today() - timedelta(days=1))
    a = b - timedelta(days=n - 1)
    d = dia(a, b)
    con = db()
    prev = {r["id"]: dict(r) for r in con.execute("SELECT * FROM revision WHERE fecha BETWEEN ? AND ?", (a.isoformat(), b.isoformat()))}
    con.close()
    dias = []
    f = b
    while f >= a:
        k = f.isoformat()
        bl = []
        for x in (d.get("bloques") or {}).get(k, []):
            if x["fila"] in ("dicho", "nota") or not x.get("ini"):
                continue
            i = _id_bloque(k, x)
            r = prev.get(i) or {}
            bl.append({**x, "id": i, "veredicto": r.get("veredicto"), "c_ini": r.get("c_ini"), "c_fin": r.get("c_fin"),
                       "c_titulo": r.get("c_titulo")})
        faltan = [{"id": r["id"], "ini": r["c_ini"], "fin": r["c_fin"], "titulo": r["c_titulo"]} for r in prev.values()
                  if r["fecha"] == k and r["veredicto"] == "faltante"]
        dias.append({"fecha": k, "dia": _dia_semana(f), "bloques": bl, "faltantes": faltan})
        f -= timedelta(days=1)
    return {"dias": dias, "resultado": resultado_revision()}


def dia_al_azar(desde_dias: int = 2, hasta_dias: int = 90, intentos: int = 6) -> dict:
    """Un día al azar de los últimos ~3 meses que el usuario aún no revisó y que tenga algo armado, para que lo valide
    o corrija en el Diagnóstico (así las reglas siguen aprendiendo)."""
    import random

    con = db()
    revisados = {r[0] for r in con.execute("SELECT DISTINCT fecha FROM revision")}
    con.close()
    hoy = date.today()
    pool = [hoy - timedelta(days=i) for i in range(desde_dias, hasta_dias + 1)]
    pool = [f for f in pool if f.isoformat() not in revisados]
    random.shuffle(pool)
    for f in pool[:intentos]:
        r = diagnostico(1, f)
        if r["dias"] and len(r["dias"][0]["bloques"]) >= 2:
            r["pendientes"] = len(pool) - 1
            return r
    r = diagnostico(1, pool[0]) if pool else {"dias": [], "resultado": resultado_revision()}
    r["pendientes"] = max(0, len(pool) - 1)
    return r


def marcar_bloque(body: dict) -> dict:
    v = body.get("veredicto")
    if v not in ("ok", "mal", "corregido", "faltante", "borrar"):
        raise ValueError("veredicto inválido")
    con = db()
    try:
        if v == "borrar":
            con.execute("DELETE FROM revision WHERE id=?", (str(body["id"]),))
        else:
            b = body.get("bloque") or {}
            i = str(body.get("id") or hashlib.sha1(f"faltante|{body['fecha']}|{time.time()}".encode()).hexdigest()[:16])
            con.execute("INSERT OR REPLACE INTO revision VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (i, str(body["fecha"])[:10], b.get("fila", "faltante"), b.get("ini", ""), b.get("fin", ""),
                         b.get("titulo", ""), b.get("conf", ""), b.get("regla", "faltante"), v,
                         _hhmm(body.get("c_ini") or "") or "", _hhmm(body.get("c_fin") or "") or "",
                         (body.get("c_titulo") or "").strip()[:120], time.time()))
        con.commit()
    finally:
        con.close()
    return resultado_revision()


def resultado_revision() -> dict:
    """Precisión de la línea del día según lo que marcó el usuario: total, por confianza y por regla."""
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM revision")]
    con.close()
    rev = [r for r in rows if r["veredicto"] in ("ok", "mal", "corregido")]

    def cuenta(rs):
        ok = sum(1 for r in rs if r["veredicto"] == "ok")
        hora = sum(1 for r in rs if r["veredicto"] == "corregido" and not r["c_titulo"])
        return {"n": len(rs), "ok": ok, "solo_hora": hora, "mal": len(rs) - ok - hora}

    reglas: dict = {}
    for r in rev:
        reglas.setdefault(r["regla"], []).append(r)
    return {**cuenta(rev), "faltantes": sum(1 for r in rows if r["veredicto"] == "faltante"),
            "dias": len({r["fecha"] for r in rows}),
            "por_conf": {c: cuenta(x) for c in _ORDEN for x in [[r for r in rev if r["conf"] == c]] if x},
            "reglas": sorted(({"regla": k, **cuenta(x)} for k, x in reglas.items()), key=lambda z: -z["n"])}


# Estadías fuera (17-11): pidió ruta en Maps a un alojamiento (cabañas en la costa) y los días siguientes Cronos lo ponía
# en su casa. Si después no hay viajes en bip! ni recibos de vuelta, se supone que se quedó ahí unos días.
_RX_ALOJA = re.compile(r"(?i)\b(caba[nñ]as?|hotel|hostal|hostel|hoster[ií]a|apart ?hotel|airbnb|camping|glamping|lodge|resort|"
                       r"refugio|motel|posada|domos?)\b")
ESTADIA_MAX = 3  # noches que se suponen si nada dice que volvió antes


def _estadia(f: date) -> dict | None:
    """Si hace 0 a ESTADIA_MAX días pidió ruta a un alojamiento y desde entonces no validó la bip!, sigue allá.
    -> {"desde": date, "hora", "lugar", "dia": días desde que llegó, "devoluciones": amigos que le pagaron su parte}"""
    con = db()
    try:
        rows = con.execute("SELECT fecha, hora, titulo FROM items WHERE fuente='maps' AND fecha BETWEEN ? AND ? "
                           "ORDER BY fecha DESC, hora DESC", ((f - timedelta(days=ESTADIA_MAX)).isoformat(), f.isoformat())).fetchall()
        for r in rows:
            m = re.match(r"(?i)indicaciones (?:a|hacia|para ir a)\s+(.*)", r["titulo"])
            if not m or not _RX_ALOJA.search(m.group(1)):
                continue
            if con.execute("SELECT 1 FROM items WHERE fuente='bip' AND fecha > ? AND fecha <= ? LIMIT 1", (r["fecha"], f.isoformat())).fetchone():
                return None  # ya volvió a moverse en Santiago
            return _estadia_desde(con, r["fecha"], r["hora"] or "10:00", direccion_corta(m.group(1)), f)
        for r in con.execute("SELECT fecha, titulo, detalle FROM items WHERE fuente='gasto' AND titulo LIKE 'cargo%' AND fecha BETWEEN ? AND ? "
                             "ORDER BY fecha DESC", ((f - timedelta(days=ESTADIA_MAX)).isoformat(), f.isoformat())).fetchall():
            cat, sii = (r["detalle"] or "").split("|")[0], ((r["detalle"] or "").split("|") + ["", ""])[2]
            comercio = r["titulo"].split(" en ", 1)[-1]
            if cat == "Alojamiento" or sii.endswith("~1") or _RX_ALOJA.search(comercio):
                comuna = sii.split("~")[0]
                return _estadia_desde(con, r["fecha"], "12:00", comercio.title() + (f", {comuna}" if comuna else ""), f, pago=True)
    finally:
        con.close()
    return None


def _estadia_desde(con, fecha: str, hora: str, lugar: str, f: date, pago: bool = False) -> dict | None:
    """La estadía que empezó el día `fecha` (por una ruta en Maps o un pago), salvo que después haya validado la bip!."""
    if con.execute("SELECT 1 FROM items WHERE fuente='bip' AND fecha > ? AND fecha <= ? LIMIT 1", (fecha, f.isoformat())).fetchone():
        return None  # ya volvió a moverse en Santiago
    s0 = date.fromisoformat(fecha)
    dev = con.execute("SELECT count(*) FROM items WHERE fuente='gasto' AND fecha BETWEEN ? AND ? AND titulo LIKE 'abono%' "
                      "AND detalle LIKE 'Devoluciones%'", (fecha, (s0 + timedelta(days=ESTADIA_MAX)).isoformat())).fetchone()[0]
    return {"desde": s0, "hora": hora, "lugar": lugar, "dia": (f - s0).days, "devoluciones": dev, "pago": pago}


def _aplicar_estadia(B: list[dict], d: dict, f: date, est: dict, hay_viaje: bool) -> None:
    nom, n = est["lugar"], est["dia"]
    por = ("pagó un alojamiento" if est.get("pago") else "pidió ruta en Maps a un alojamiento") + " y después no hay viajes en bip! ni recibos de vuelta"
    if est["devoluciones"]:
        por += f"; esos días le devolvieron su parte {est['devoluciones']} veces (gasto compartido)"
    ultimo = n >= ESTADIA_MAX or hay_viaje
    fuera = lambda b: (b["fila"] == "lugar" and (b.get("lugar") in ("casa", "") or b.get("_inferido"))) or (b["fila"] == "viaje" and b.get("_inferido"))  # noqa: E731
    if n == 0:
        llega = _h(min(_m(est["hora"]) + 150, 23 * 60 + 30))
        B[:] = [b for b in B if not ((fuera(b) or b["titulo"].startswith("Quizás en")) and b["ini"] >= est["hora"])]
        for b in B:
            if b["fila"] == "lugar" and b.get("lugar") == "casa" and b["fin"] > est["hora"]:
                b["fin"] = est["hora"]
        B.append({"ini": _h(_m(est["hora"]) + 30), "fin": llega, "fila": "viaje", "titulo": f"Viaje a {nom} (supuesto)", "conf": "baja",
                  "por": "pidió ruta en Maps a ese alojamiento"})
        B.append({"ini": llega, "fin": "23:59", "fila": "lugar", "titulo": f"En {nom}", "lugar": nom, "conf": "media", "por": por})
        return
    B[:] = [b for b in B if not fuera(b)]
    for b in B:
        if b["fila"] == "sueno":
            b["titulo"] = b["titulo"].replace(" en su casa", f" en {nom}")
            b["por"] = por
    despierta = ((d.get("sueno") or {}).get(f.isoformat()) or {}).get("hasta", "")[11:] or "00:00"
    sale = min([b["ini"] for b in B if b["fila"] == "viaje"] or ["16:00" if ultimo else "23:59"])
    B.append({"ini": despierta, "fin": sale, "fila": "lugar", "titulo": f"En {nom}", "lugar": nom,
              "conf": "media" if n == 1 else "baja", "por": por})
    if ultimo and not hay_viaje:
        B.append({"ini": "16:00", "fin": "18:30", "fila": "viaje", "titulo": "Vuelta a su casa (supuesta)", "conf": "baja",
                  "por": "no hay registro del viaje de vuelta", "_inferido": True})
        B.append({"ini": "18:30", "fin": "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "baja",
                  "por": "se supone que volvió", "_inferido": True})


# ---- Cronología de Google Maps (ubicación real del celular; la sincroniza cada noche otra tarea, aquí solo se lee)
CRONO_DB = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Atlas" / "datos" / "cronologia_maps" / "cronologia_maps.db"
_MODOS = {"IN_PASSENGER_VEHICLE": "en auto", "IN_VEHICLE": "en auto", "IN_TAXI": "en auto", "MOTORCYCLING": "en moto",
          "IN_BUS": "en micro", "IN_SUBWAY": "en metro", "IN_TRAIN": "en tren", "IN_TRAM": "en tren", "WALKING": "a pie",
          "RUNNING": "corriendo", "CYCLING": "en bicicleta", "FLYING": "en avión", "IN_FERRY": "en barco"}


def _crono_hora(t: str, f: date) -> str | None:
    """Hora local del texto ISO de Maps recortada al día f («HH:MM»); None si cae fuera del día."""
    x = datetime.fromisoformat(t).replace(tzinfo=None)  # el desfase ya es el local del momento
    if x.date() < f:
        return "00:00"
    if x.date() > f:
        return "23:59"
    return x.strftime("%H:%M")


def _km(a, b, c, d_) -> float:
    import math
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d_ - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, h)))


def _dias_rutas(mes: str) -> set[str]:
    """23-11: días del mes («2026-11») con ubicación de Rutas de Maps, para que el calendario de Cronos los marque."""
    if not CRONO_DB.exists():
        return set()
    try:
        con = sqlite3.connect(f"file:{CRONO_DB.as_posix()}?mode=ro", uri=True)
        try:
            out = {r[0] for r in con.execute("SELECT DISTINCT substr(ts,1,10) FROM puntos WHERE ts LIKE ?", (mes + "-%",))}
            for ini, fin in con.execute("SELECT inicio, fin FROM visitas UNION ALL SELECT inicio, fin FROM trayectos"):
                a, b = date.fromisoformat(ini[:10]), date.fromisoformat(fin[:10])
                while a <= b:
                    if a.isoformat().startswith(mes):
                        out.add(a.isoformat())
                    a += timedelta(days=1)
        finally:
            con.close()
        return out
    except Exception:  # noqa: BLE001
        return set()


def _cronologia(f: date) -> tuple[list, list, tuple | None]:
    """Visitas y trayectos de Maps que tocan el día f, más dónde está su casa según Maps (o None)."""
    if not CRONO_DB.exists():
        return [], [], None
    con = sqlite3.connect(f"file:{CRONO_DB.as_posix()}?mode=ro", uri=True)
    try:
        a, b = (f - timedelta(days=1)).isoformat(), (f + timedelta(days=1)).isoformat()
        vis = con.execute("SELECT inicio, fin, lat, lng, place_id, tipo_semantico, probabilidad, confirmada FROM visitas "
                          "WHERE inicio < ? AND fin >= ? ORDER BY inicio", (b + "T23:59", a)).fetchall()
        tra = con.execute("SELECT inicio, fin, distancia_m, modo FROM trayectos WHERE inicio < ? AND fin >= ? ORDER BY inicio",
                          (b + "T23:59", a)).fetchall()
        casa = con.execute("SELECT AVG(lat), AVG(lng) FROM visitas WHERE tipo_semantico IN ('HOME', 'INFERRED_HOME') "
                           "AND lat IS NOT NULL").fetchone()
    finally:
        con.close()
    k = f.isoformat()
    vis = [v for v in vis if v[0][:10] <= k <= v[1][:10]]
    tra = [t for t in tra if t[0][:10] <= k <= t[1][:10]]
    return vis, tra, (casa if casa and casa[0] is not None else None)


def _quitar_tramo(B: list[dict], ini: str, fin: str, que) -> None:
    """Saca de B el tramo ini–fin de los bloques que cumplen «que» (recorta, o borra si queda vacío)."""
    nuevos = []
    for b in B:
        if not que(b) or not b["ini"] or b["fin"] <= ini or b["ini"] >= fin:
            nuevos.append(b)
            continue
        antes, despues = (b["ini"], ini), (fin, b["fin"])
        if antes[0] < antes[1] and _m(antes[1]) - _m(antes[0]) >= 10:
            nuevos.append({**b, "ini": antes[0], "fin": antes[1]})
        if despues[0] < despues[1] and _m(despues[1]) - _m(despues[0]) >= 10:
            nuevos.append({**b, "ini": despues[0], "fin": despues[1]})
    B[:] = nuevos


def _aplicar_cronologia(B: list[dict], f: date) -> int:
    """Lo que dice la Cronología de Maps manda sobre lo deducido: donde Maps sabe dónde estaba, ese tramo es suyo."""
    vis, tra, casa = _cronologia(f)
    n = 0
    for ini_t, fin_t, dist, modo in tra:
        ini, fin = _crono_hora(ini_t, f), _crono_hora(fin_t, f)
        if _m(fin) - _m(ini) < 3:
            continue
        con_recibo = [b for b in B if b["fila"] == "viaje" and not b.get("_inferido") and "(supuest" not in b["titulo"]
                      and b["ini"] < fin and b["fin"] > ini]
        if con_recibo:  # el recibo (Uber, bip!) dice más que Maps: solo se confirma
            for b in con_recibo:
                b["conf"] = "alta"
                b["por"] += "; y Rutas de Maps registra el trayecto"
            continue
        _quitar_tramo(B, ini, fin, lambda b: b["fila"] == "viaje" or (b["fila"] == "lugar" and b.get("conf") != "alta"))
        km = f" ({dist / 1000:.1f} km)".replace(".", ",") if dist else ""
        B.append({"ini": ini, "fin": fin, "fila": "viaje", "titulo": " ".join(x for x in ("Viaje", _MODOS.get(modo or "", "")) if x) + km,
                  "conf": "alta", "por": "Rutas de Google Maps (ubicación real del celular)"})
        n += 1
    for ini_t, fin_t, lat, lng, pid, sem, prob, conf in vis:
        ini, fin = _crono_hora(ini_t, f), _crono_hora(fin_t, f)
        if _m(fin) - _m(ini) < 10:
            continue
        sem = (sem or "").upper()
        if sem in ("HOME", "INFERRED_HOME"):
            titulo, lugar = "En su casa", "casa"
        elif sem in ("WORK", "INFERRED_WORK"):
            titulo, lugar = "En el trabajo", "trabajo"
        else:
            # Maps no da el nombre: se toma el del bloque deducido que más se cruza con la visita (la U, el alojamiento…)
            def cruce(b):
                return max(0, _m(min(b["fin"], fin)) - _m(max(b["ini"], ini)))
            cand = [b for b in B if b["fila"] == "lugar" and b.get("lugar") not in ("casa", "") and b["ini"] and cruce(b) * 3 >= _m(fin) - _m(ini)]
            mejor = max(cand, key=cruce, default=None)
            if mejor:
                titulo, lugar = re.sub(r"^Quizás en ", "En ", mejor["titulo"]), mejor.get("lugar")
            else:
                lejos = f" a {_km(casa[0], casa[1], lat, lng):.1f} km de su casa".replace(".", ",") if casa and lat is not None else ""
                titulo, lugar = f"En un lugar{lejos}", "maps:" + (pid or (f"{lat:.3f},{lng:.3f}" if lat is not None else "?"))
        # un viaje supuesto que choca con una visita real no ocurrió así: se borra entero
        B[:] = [b for b in B if not (b["fila"] == "viaje" and (b.get("_inferido") or "(supuest" in b["titulo"]) and b["ini"] < fin and b["fin"] > ini)]
        _quitar_tramo(B, ini, fin, lambda b: b["fila"] == "lugar")
        por = "Rutas de Google Maps (ubicación real del celular)" + ("; usted confirmó el lugar en Maps" if conf else "")
        B.append({"ini": ini, "fin": fin, "fila": "lugar", "titulo": titulo, "lugar": lugar,
                  "conf": "alta" if conf or (prob or 0) >= 0.5 else "media", "por": por})
        n += 1
    return n


VIAJES_MANDAN = True  # 18-11: un viaje con recibo dice dónde estaba al salir y al llegar; manda sobre el horario


def _viajes_mandan(B: list[dict]) -> int:
    """Un viaje con recibo (Cabify, Uber…) fija dónde estaba: en el origen hasta que salió y en el destino desde que
    llegó. Lo supuesto en otro lugar en ese tramo (una clase por horario, «En la U»…) no ocurrió: se quita, o se
    recorta si llegó tarde o se fue antes. -> cuántos bloques cambió."""
    viajes = [b for b in B if b["fila"] == "viaje" and b.get("ini")]
    firmes = sorted((b for b in viajes if b.get("conf") == "alta" and b.get("_o") and b.get("_d")), key=lambda b: _m(b["ini"]))
    n = 0
    for r in firmes:
        O, D, ri, rf = r["_o"], r["_d"], _m(r["ini"]), _m(r["fin"])
        antes = max((_m(x["fin"]) for x in viajes if x is not r and _m(x["fin"]) <= ri), default=-1)
        despues = min((_m(x["ini"]) for x in viajes if x is not r and _m(x["ini"]) >= rf), default=10 ** 6)
        if O not in ("casa", "U"):  # de un lugar cualquiera no se sabe desde cuándo estaba ahí: solo la última hora y media
            antes = max(antes, ri - 90)
        if D not in ("casa", "U"):
            despues = min(despues, rf + 90)
        for b in list(B):
            L = b.get("lugar") or ""
            if L and L not in ("casa", "U"):  # «calle falsa» y «calle falsa 123» son el mismo lugar
                L = next((k for k in (O, D) if k not in ("casa", "U") and misma_direccion(L, k)), L)
            if b["fila"] not in ("actividad", "lugar") or b.get("conf") == "alta" or not L or not b.get("ini") or b is r:
                continue
            bi, bf = _m(b["ini"]), _m(b["fin"])
            clase = b["fila"] == "actividad"
            nombre = re.sub(r" \((como alumno|rindió|como profesor auxiliar)\).*$", "", b["titulo"])
            if L != O and antes < bf and bi < rf:  # estaba en el origen hasta salir y viajando hasta llegar
                if L == D and bf > rf:
                    b["ini"] = r["fin"]
                    if clase:
                        b["titulo"] += " · llegó tarde"
                        b["por"] += f"; llegó a las {r['fin']} ({r['titulo']})"
                        r["por"] += f"; llegó tarde a {nombre}"
                else:
                    B.remove(b)
                    if clase:
                        r["por"] += f"; por eso no estuvo en {nombre} ({b['ini']})"
                n += 1
            elif L != D and (clase or L != "casa") and bi < despues and bf > ri:  # desde que llegó (a casa pudo volver a pie) estaba en el destino hasta el siguiente viaje
                if L == O and bi < ri:
                    b["fin"] = r["ini"]
                    if clase:
                        b["titulo"] += " · se fue antes"
                        r["por"] += f"; se fue antes de {nombre}"
                else:
                    B.remove(b)
                    if clase:
                        r["por"] += f"; por eso no estuvo en {nombre} ({b['ini']})"
                n += 1
    return n


def _es_prueba(b: dict) -> bool:
    """Rutas de Maps, un viaje real (recibo, bip!), lo que él escribió o una visita segura."""
    if b["fila"] == "viaje" and not b.get("_inferido") and "supuest" not in b["titulo"]:
        return True
    return "Rutas de Google Maps" in (b.get("por") or "") or b["fila"] == "dicho" or (b["fila"] == "lugar" and b.get("conf") == "alta")


def _hay_ubicacion(B: list[dict], ini: str | None = None, fin: str | None = None, margen: int = 180) -> bool:
    """¿Algo real dice dónde estuvo? Con ini/fin, solo cuenta lo que cae a menos de «margen» minutos de ese tramo
    (19-11: Rutas traía solo la madrugada del 18 y eso hacía creer que había pruebas para las clases de la tarde)."""
    for b in B:
        if not _es_prueba(b):
            continue
        if ini is None or not b.get("ini"):
            return True
        if _m(b["ini"]) - margen < _m(fin or ini) and _m(b.get("fin") or b["ini"]) + margen > _m(ini):
            return True
    return False


def _sin_ubicacion(B: list[dict]) -> int:
    """19-11: sin ningún dato de ubicación, el calendario es solo lo agendado: no prueba que fue a clases ni a la U."""
    n = 0
    for b in B:
        if _es_prueba(b) or not b.get("ini") or _hay_ubicacion(B, b["ini"], b.get("fin")):
            continue
        if b["fila"] in ("actividad", "lugar") and b.get("lugar") != "casa" and not b.get("_sin_ubic"):
            n += b.get("conf") != "baja"
            b["conf"], b["_sin_ubic"] = "baja", True  # aunque sus revisiones digan que esa regla suele acertar
            b["por"] = (b.get("por") or "") + "; ese día no hay datos de ubicación: no se sabe si fue"
    return n


def bloques(d: dict, f: date) -> list[dict]:
    """Bloques del día para la línea de tiempo: [{ini, fin, fila (lugar|actividad|sueno|viaje), titulo, conf, por}].
    Cruza las pistas: un recibo de Cabify fija de dónde salió y adónde llegó; una dirección buscada varias veces
    que coincide con el origen del viaje es una visita casi segura; los controles y las clases que dicta lo ponen en
    la U; las cátedras solo dicen que estaba en su horario; lo que él escribió por chat («estoy en la u») también."""
    k = f.isoformat()
    casa = casa_conocida()
    B = []
    # 1) viajes (lo más firme)
    manana = (f + timedelta(days=1)).isoformat()
    todos = _viajes(d["correos"] + (d.get("_previo") or {}).get("despues", []))
    vs = [v for v in todos if v["fecha"] == k and v["ini"] >= "05:00"]
    for v in todos:  # trasnoche: 00:17 del día siguiente = 24:17 de este día
        if v["fecha"] == manana and v["ini"] < "05:00":
            vs.append({**v, "ini": _h(_m(v["ini"]) + 1440), "fin": _h(_m(v["fin"]) + 1440)})
    for v in vs:
        (ko, o), (kd, d_) = _nombre_lugar(v["origen"], casa), _nombre_lugar(v["destino"], casa)
        B.append({"ini": v["ini"], "fin": v["fin"], "fila": "viaje", "titulo": f"{v['app']}: {o} → {d_}", "conf": "alta",
                  "por": "recibo del viaje", "_o": ko, "_d": kd})
    # 2) calendario según su rol
    evs = [e for e in d["eventos"] if e["fecha"] == k and e.get("hora")]
    vistos, evs2 = set(), []
    for e in evs:
        kk = (e["hora"], e.get("tipo"), "" if e.get("tipo") in ("evaluacion", "dicta") else _plain(e["titulo"])[:18])
        if kk not in vistos:
            vistos.add(kk)
            evs2.append(e)
    evs = evs2
    clases = [e for e in evs if e.get("tipo") == "clase"]
    for e in evs:
        t = e.get("tipo")
        sala = f" · sala {e['lugar']}" if e.get("lugar") else ""
        if t == "evaluacion":
            B.append({"ini": e["hora"], "fin": e["fin"] or _h(_m(e["hora"]) + 90), "fila": "actividad",
                      "titulo": f"{e['titulo']} (rindió){sala}", "lugar": "U", "conf": "media", "por": "evaluación en su calendario"})
        elif t == "dicta":
            B.append({"ini": e["hora"], "fin": e["fin"] or _h(_m(e["hora"]) + 90), "fila": "actividad",
                      "titulo": f"{e['titulo']} (como profesor auxiliar){sala}", "lugar": "U", "conf": "media", "por": "ramo donde es profesor auxiliar"})
        elif t == "clase":
            juntas = [c for c in clases if c["hora"] == e["hora"]]
            if len(juntas) > 1 and e is not juntas[0]:
                continue
            nom = " o ".join(c["titulo"] for c in juntas) if len(juntas) > 1 else e["titulo"]
            B.append({"ini": e["hora"], "fin": e["fin"] or _h(_m(e["hora"]) + 90), "fila": "actividad",
                      "titulo": f"{nom} (como alumno){sala if len(juntas) == 1 else ''}", "lugar": "U", "conf": "baja",
                      "por": "estaba en su horario; no confirma que fue" + (" (choque de horario)" if len(juntas) > 1 else "")})
        elif t == "evento":
            B.append({"ini": e["hora"], "fin": e["fin"] or _h(_m(e["hora"]) + 60), "fila": "actividad", "titulo": e["titulo"],
                      "lugar": e.get("lugar") or "", "conf": "media", "por": "evento de su calendario"})
    # 3) lo que él dijo por chat
    msgs = [(it["hora"], it["titulo"]) for it in d["items"] if it["fecha"] == k and it["fuente"] == "whatsapp_chat" and it.get("hora")]
    try:
        for x in _chat_dice(f, msgs):
            lug = _plain(x["lugar"])
            B.append({"ini": x["hora"], "fin": x["hora"], "fila": "dicho", "titulo": ", ".join(y for y in (x["lugar"], x["actividad"]) if y),
                      "lugar": "U" if re.match(r"(la )?u\b|universidad|facultad|beauchef|dcc|depto|departamento|fcfm|campus|sala de estudio", lug) else ("casa" if "casa" in lug else x["lugar"]),
                      "conf": "media", "por": "lo dijo por chat"})
    except Exception:  # noqa: BLE001
        pass
    # 4) direcciones buscadas varias veces (hoy y los 2 días antes)
    con = db()
    rows = con.execute("SELECT fecha, hora, titulo FROM items WHERE fuente='maps' AND fecha BETWEEN ? AND ?",
                       ((f - timedelta(days=2)).isoformat(), k)).fetchall()
    con.close()
    from collections import defaultdict

    busc = defaultdict(list)
    for r in rows:
        m = re.match(r"(?i)^(?:indicaciones (?:a|hacia|para ir a)\s+|buscó\s+)?(.+)$", r["titulo"])
        if m and re.search(r"\d", m.group(1)) and not re.match(r"(?i)explorad|vio |usó ", r["titulo"]):
            busc[clave_direccion(m.group(1))].append((r["fecha"], r["hora"], m.group(1), r["titulo"].lower().startswith("indicaciones")))
    for kk, lst in busc.items():
        hoy = sorted((x for x in lst if x[0] == k), key=lambda x: x[1] or "")
        if not hoy:
            continue
        n = len(lst)
        dir_ = max((x[2] for x in lst), key=len)
        ruta = [x for x in hoy if x[3]]
        salida = next((v for v in vs if misma_direccion(clave_direccion(v["origen"]), kk)), None)
        llegada = next((v for v in vs if misma_direccion(clave_direccion(v["destino"]), kk)), None)
        if salida:
            antes = [_m(b["fin"]) for b in B if b["fila"] == "actividad" and b["conf"] != "baja" and b["fin"] <= salida["ini"]]
            ini = _h(max([_m(ruta[-1][1]) + 30 if ruta and _m(ruta[-1][1]) < _m(salida["ini"]) else _m(salida["ini"]) - 120] + antes))
            B.append({"ini": ini, "fin": salida["ini"], "fila": "lugar", "titulo": f"En {direccion_corta(dir_)}", "lugar": kk,
                      "conf": "alta", "por": f"la buscó {n} veces en Maps y el {salida['app']} salió de ahí"})
        elif llegada:
            B.append({"ini": llegada["fin"], "fin": _h(_m(llegada["fin"]) + 90), "fila": "lugar", "titulo": f"En {direccion_corta(dir_)}",
                      "lugar": kk, "conf": "alta", "por": f"la buscó {n} veces en Maps y llegó en {llegada['app']}"})
        elif ruta:
            B.append({"ini": _h(_m(ruta[-1][1]) + 30), "fin": _h(_m(ruta[-1][1]) + 120), "fila": "lugar",
                      "titulo": f"Quizás en {direccion_corta(dir_)}", "lugar": kk, "conf": "media" if n >= 3 else "baja",
                      "por": f"pidió ruta y la buscó {n} veces en Maps"})
    for v in vs:
        if any(b["fila"] == "lugar" and b["fin"] == v["ini"] for b in B):
            continue
        k0, nom = _nombre_lugar(v["origen"], casa)
        if not v["origen"]:
            continue
        antes = [b["fin"] for b in B if b["fila"] in ("actividad", "viaje") and b["fin"] <= v["ini"] and b.get("conf") != "baja"]
        ini = antes[-1] if antes else _h(_m(v["ini"]) - 90)
        B.append({"ini": ini, "fin": v["ini"], "fila": "lugar", "titulo": f"En {nom}", "lugar": k0, "conf": "media",
                  "por": f"el {v['app']} salió de ahí"})
    # 5) sueño y dónde durmió
    sn = (d.get("sueno") or {}).get(k)
    if sn:
        ini = "00:00" if sn["desde"][:10] != k else sn["desde"][11:]
        donde, por = "", ""
        prev_v = _viajes((d.get("_previo") or {}).get("correos", []))
        tarde = [v for v in prev_v if v["ini"] >= "17:00"] + [v for v in vs if sn["desde"][:10] == k and v["fin"] <= sn["desde"][11:]]
        # Lo normal es que duerma en su casa (casi siempre). Para decir otro lugar hace falta evidencia fuerte:
        # un viaje que terminó ahí, o que él lo haya dicho por chat al acostarse Y al despertar.
        ini_m, fin_m = _m(ini) if ini != "00:00" else _m(sn["desde"][11:]) - 1440, _m(sn["hasta"][11:])
        cerca = lambda b, a0, a1: b["fila"] == "dicho" and b.get("lugar") and a0 <= _m(b["ini"]) <= a1  # noqa: E731
        al_dormir = [b for b in B if cerca(b, ini_m - 120, ini_m + 15)]
        al_despertar = [b for b in B if cerca(b, fin_m - 15, fin_m + 60)]
        lug = lambda bs: {b["lugar"] for b in bs}  # noqa: E731
        fuera = (lug(al_dormir) - {"casa"}) and (lug(al_despertar) - {"casa"})
        if tarde:
            donde, por = _nombre_lugar(tarde[-1]["destino"], casa)[1], f"su último viaje terminó ahí ({tarde[-1]['app']})"
        elif fuera:
            en_u = [b for b in B if cerca(b, fin_m - 15, fin_m + 180) and b["lugar"] == "U"]
            x = "U" if "U" in lug(al_despertar) or en_u else sorted(lug(al_despertar) - {"casa"})[0]
            donde, por = ("la U" if x == "U" else x), "al acostarse y al despertar escribió desde fuera de casa"
        else:
            donde, por = "su casa", "es donde duerme casi siempre"
        if donde == "la U":
            B.append({"ini": sn["hasta"][11:], "fin": sn["hasta"][11:], "fila": "dicho", "titulo": "despertó en la U",
                      "lugar": "U", "conf": "media", "por": por})
        B.append({"ini": ini, "fin": sn["hasta"][11:], "fila": "sueno",
                  "titulo": f"Durmió ~{sn['horas']} h" + (f" en {donde}" if donde else "") + (" (poco)" if sn["horas"] < 5.5 else ""),
                  "conf": "media" if (por and sn["confianza"] == "media") else "baja",
                  "por": "; ".join(x for x in (por, "según su último y primer uso registrado") if x)})
    # 6) rellenar: entre dos cosas en la U, estuvo en la U; después del último viaje, en su destino
    B.sort(key=lambda b: (b["ini"] or "99", b["fin"]))
    despierta = ((d.get("sueno") or {}).get(k) or {}).get("hasta", "")[11:] or "00:00"
    en_u = [b for b in B if b.get("lugar") == "U" and b["fila"] in ("actividad", "dicho") and b["conf"] != "baja"
            and b["ini"] >= despierta]
    if en_u:
        ini_u, fin_u = min(b["ini"] for b in en_u), max(b["fin"] for b in en_u)
        sal = next((v for v in vs if v["ini"] >= fin_u), None)
        fin_lugar = [b["ini"] for b in B if b["fila"] == "lugar" and b["ini"] >= fin_u]
        fin_total = min([fin_u if not fin_lugar else fin_lugar[0]] + ([sal["ini"]] if sal and not fin_lugar else []))
        if fin_lugar:
            fin_total = _h(max(_m(fin_u), _m(fin_lugar[0]) - 30))
        B.append({"ini": ini_u, "fin": fin_total, "fila": "lugar", "titulo": "En la U", "lugar": "U",
                  "conf": "media", "por": "controles, clases que dicta o lo que dijo por chat"})
    if vs:
        ult = vs[-1]
        siguiente = [b["ini"] for b in B if b["fila"] in ("lugar",) and b["ini"] > ult["fin"]]
        nom = _nombre_lugar(ult["destino"], casa)[1]
        B.append({"ini": ult["fin"], "fin": siguiente[0] if siguiente else max("23:59", _h(_m(ult["fin"]) + 45)), "fila": "lugar", "titulo": f"En {nom}",
                  "lugar": _nombre_lugar(ult["destino"], casa)[0], "conf": "alta", "por": f"llegó en {ult['app']}"})
    # 6a) bip!: cada viaje en micro/metro es un traslado. Si fue y volvió en transporte público con clases entre medio,
    #     estuvo en la U; antes del primer viaje estaba en su casa; tras el último de la tarde, volvió a su casa.
    vb = _viajes_bip(d["items"], k)
    for v in vb:
        B.append({"ini": v["ini"], "fin": v["fin"], "fila": "viaje", "titulo": "Micro/metro: " + " → ".join(dict.fromkeys(v["tramos"])),
                  "conf": "alta", "por": "validó su bip! (la llegada es estimada)"})
    if vb:
        ocupado = lambda a0, a1: any(b["fila"] in ("lugar", "viaje") and b["ini"] < a1 and b["fin"] > a0 and "bip" not in (b.get("por") or "")  # noqa: E731
                                     for b in B)
        ida, vuelta = vb[0], vb[-1]
        if len(vb) >= 2 and any(b["fila"] == "actividad" and b.get("lugar") == "U" and b["ini"] < vuelta["ini"] and b["fin"] > ida["fin"] for b in B):
            if not any(b["fila"] == "lugar" and b.get("lugar") == "U" and b["ini"] <= ida["fin"] and b["fin"] >= vuelta["ini"] for b in B):
                B.append({"ini": ida["fin"], "fin": vuelta["ini"], "fila": "lugar", "titulo": "En la U", "lugar": "U", "conf": "media",
                          "por": "fue y volvió en micro/metro con clases entre medio"})
        if despierta < ida["ini"] and not ocupado(despierta, ida["ini"]):
            B.append({"ini": despierta, "fin": ida["ini"], "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "media",
                      "por": "salió en micro/metro después de despertar"})
        es_vuelta = len(vb) >= 2 and [t for t in vuelta["tramos"] if t.startswith("micro")] == [t for t in ida["tramos"] if t.startswith("micro")][::-1] != []  # mismo recorrido al revés
        if (vuelta["ini"] >= "16:00" or es_vuelta) and not any(v["ini"] > vuelta["ini"] for v in vs):
            sig = [b["ini"] for b in B if b["fila"] == "lugar" and b["ini"] > vuelta["fin"]]
            if not ocupado(vuelta["fin"], sig[0] if sig else "23:59"):
                B.append({"ini": vuelta["fin"], "fin": sig[0] if sig else "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa",
                          "conf": "media", "por": "volvió en micro/metro en la tarde (último viaje del día)"})
    # 6d) si el día termina en la U sin ningún viaje registrado después, se supone la vuelta a casa (poco seguro):
    #     sigue en la U hasta su última clase de ese día y después vuelve. Si esa noche durmió fuera, _cerrar_noche lo quita.
    lugs = sorted((b for b in B if b["fila"] == "lugar" and b["ini"] and b["fin"]), key=lambda b: (b["ini"], b["fin"]))
    if lugs and lugs[-1].get("lugar") == "U" and not any(b["fila"] == "viaje" and b["ini"] >= lugs[-1]["ini"] for b in B):
        ult = lugs[-1]
        clases = [b["fin"] for b in B if b["fila"] == "actividad" and b.get("lugar") == "U" and ult["ini"] <= b["ini"] and b["fin"]]
        salida = max([ult["fin"]] + clases)
        if salida < "23:00":
            if salida > ult["fin"]:
                ult["fin"] = salida
                ult["por"] = (ult.get("por") or "") + "; siguió hasta su última clase"
            ida, llega = _h(_m(salida) + 10), _h(_m(salida) + 55)
            B.append({"ini": ida, "fin": llega, "fila": "viaje", "titulo": "Vuelta a su casa (supuesta)", "conf": "baja",
                      "por": "no hay registro del viaje; se supone después de su última clase", "_inferido": True})
            B.append({"ini": llega, "fin": "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "baja",
                      "por": "se supone que volvió: es donde duerme casi siempre", "_inferido": True})
    # 6b) lo que él dijo después cambia el lugar: si a las 18:43 dijo «llegué a la casa», el bloque anterior (la U)
    #     termina ahí y desde ahí está en su casa hasta el próximo lugar conocido o el fin del día. Tampoco hay lugar
    #     despierto antes de despertar.
    wake = ((d.get("sueno") or {}).get(k) or {}).get("hasta", "")[11:]
    for b in B:
        if wake and b["fila"] == "lugar" and b["ini"] < wake < b["fin"]:
            b["ini"] = wake
    for x in sorted((b for b in B if b["fila"] == "dicho" and b.get("lugar") in ("casa", "U")), key=lambda b: b["ini"]):
        if wake and x["ini"] < wake:
            continue
        lug = [b for b in B if b["fila"] == "lugar" and b["ini"] <= x["ini"] < b["fin"]]
        if any(b.get("lugar") == x["lugar"] for b in lug):
            continue
        fin_previo = "23:59"
        for b in lug:  # el lugar anterior termina cuando él dice que está en otro
            fin_previo = max(fin_previo, b["fin"]) if b["fin"] > "23:59" else fin_previo
            b["fin"] = x["ini"]
        sig = [b["ini"] for b in B if b["fila"] in ("lugar", "viaje") and b["ini"] > x["ini"]]
        nombre = "En su casa" if x["lugar"] == "casa" else "En la U"
        B.append({"ini": x["ini"], "fin": sig[0] if sig else fin_previo, "fila": "lugar", "titulo": nombre, "lugar": x["lugar"],
                  "conf": "media", "por": "lo dijo por chat"})
    B[:] = [b for b in B if not (b["fila"] == "lugar" and b["fin"] and b["ini"] >= b["fin"])]
    # 6c) bloques seguidos del mismo lugar se juntan en uno (con la mejor confianza)
    lugares = sorted((b for b in B if b["fila"] == "lugar"), key=lambda b: b["ini"])
    for a_, b_ in zip(lugares, lugares[1:]):
        if a_.get("lugar") and a_.get("lugar") == b_.get("lugar") and b_["ini"] <= a_["fin"] and "_fuera" not in a_:
            b_["ini"], b_["fin"] = a_["ini"], max(a_["fin"], b_["fin"])
            if _ORDEN.index(a_["conf"]) > _ORDEN.index(b_["conf"]):
                b_["conf"] = a_["conf"]
            b_["por"] = a_["por"] + "; " + b_["por"]
            b_["titulo"] = a_["titulo"] if len(a_["titulo"]) >= len(b_["titulo"]) else b_["titulo"]
            a_["_fuera"] = True
    B[:] = [b for b in B if "_fuera" not in b]
    # 7) poco uso del celular (señal interna, no se muestra): refuerza un lugar dudoso en esas horas o, si no hay
    #    ninguna pista de lugar, sugiere que estaba fuera
    uso = (d.get("uso") or {}).get(k)
    if uso:
        sn = (d.get("sueno") or {}).get(k)
        desp = int(sn["hasta"][11:13]) + 1 if sn else 8
        for h0, h1, n, base in tramos_quietos(uso, (desp, 27)):
            ini, fin = f"{h0:02d}:00", f"{h1:02d}:00"
            junto = [b for b in B if b["fila"] in ("lugar", "viaje") and b["ini"] < fin and b["fin"] > ini]
            for b in junto:
                if b["fila"] == "lugar" and b.get("lugar") != "casa" and (b["conf"] == "baja" or b["titulo"].startswith("Quizás")):
                    b["conf"] = "media"
                    b["por"] += "; y en esas horas usó mucho menos el celular que de costumbre"
            if not junto and not any(b["fila"] == "actividad" and b["conf"] != "baja" and b["ini"] < fin and b["fin"] > ini for b in B):
                B.append({"ini": ini, "fin": fin, "fila": "lugar", "titulo": "Probablemente fuera de casa", "lugar": "",
                          "conf": "baja", "por": "usó mucho menos el celular que de costumbre a esa hora"})
    # 8) estadía fuera: pidió ruta a un alojamiento y no volvió a moverse en Santiago
    try:
        est = _estadia(f)
        if est:
            _aplicar_estadia(B, d, f, est, bool(vs))
    except Exception:  # noqa: BLE001
        pass
    # 9) Cronología de Google Maps: la ubicación real del celular manda sobre todo lo deducido
    try:
        _aplicar_cronologia(B, f)
    except Exception:  # noqa: BLE001  (sin la base o con una copia a medias, Cronos sigue con lo demás)
        pass
    # 10) un viaje con recibo descarta lo supuesto en otro lugar (clase por horario a la que no pudo ir, etc.)
    if VIAJES_MANDAN:
        _viajes_mandan(B)
    for b in B:
        b["regla"] = regla_de(b)
    ajustar_con_revisiones(B)
    # 11) sin Rutas, viajes ni nada que lo ubique, lo del calendario queda en «no se sabe si fue» (va después de las
    # revisiones: que la regla suela acertar no prueba que ese día fue)
    _sin_ubicacion(B)
    B.sort(key=lambda b: (b["ini"] or "99", {"sueno": 0, "lugar": 1, "viaje": 2, "actividad": 3, "quieto": 4, "dicho": 5}.get(b["fila"], 6)))
    return B


def texto_para_modelo(d: dict, max_lineas: int = 110) -> str:
    """El día para el modelo local: primero las pistas de dónde estuvo, luego lo que hizo y al final un poco de
    contexto (recortado: decenas de búsquedas o videos no ayudan a reconstruir el día)."""
    lineas = []
    for f, x in sorted(clasificar(d).items()):
        lineas.append(f"== {_dia_semana(date.fromisoformat(f))}")
        bl = (d.get("bloques") or {}).get(f) or []
        if bl:
            lineas.append("LÍNEA DEL DÍA (bloques deducidos, con confianza):")
            lineas += [f"  {b['ini']}–{b['fin']} {b['titulo']} [confianza {b['conf']}: {b['por']}]" for b in bl]
            if any(b.get("_sin_ubic") for b in bl):
                lineas.append("UBICACIÓN: los bloques que dicen «no hay datos de ubicación» no tienen ningún dato real de "
                              "dónde estuvo a esa hora (ni Rutas de Maps, ni viajes, ni bip!). Son solo lo que tenía "
                              "agendado: no digas que fue a clases, a la U ni a ese lugar; di que no se sabe.")
        lineas.append("DÓNDE (pistas, con confianza):" if x["lugares"] else "DÓNDE: sin pistas de lugar ese día")
        lineas += [f"  {h or '--:--'} {t} [confianza {c}]" for h, t, c in x["lugares"][:15]]
        if x["hechos"]:
            lineas.append("QUÉ HIZO:")
            lineas += [f"  {h or '--:--'} {t}" for h, t in x["hechos"][:25]]
        sn = (d.get("sueno") or {}).get(f)
        if sn:
            lineas.append(f"SUEÑO (estimado, confianza {sn['confianza']}): sin actividad desde {sn['desde'][-5:]} "
                          f"({'día anterior' if sn['desde'][:10] != f else 'ese día'}) hasta {sn['hasta'][-5:]}, {sn['horas']} h")
        ses = (d.get("sesiones") or {}).get(f)
        cx = x["contexto"]
        if ses:
            lineas.append("ACTIVIDAD EN PANTALLA (sesiones; no prueba dónde estuvo):")
            for z in [z for z in ses if z["tipo"] not in ("música", "chat")][:20]:
                lineas.append(f"  {z['ini']}–{z['fin']} {z['tipo']} ({z['n']}): " + "; ".join(z["muestra"]))
            if cx["fotos_recibidas"]:
                lineas.append(f"  {len(cx['fotos_recibidas'])} fotos recibidas por WhatsApp (de otros)")
            lineas += [f"  {h or '--:--'} {t}" for h, t in cx["otros"][:5]]
        elif any(cx.values()):
            lineas.append("CONTEXTO (no prueba dónde estuvo):")
            if cx["busquedas"]:
                lineas.append(f"  {len(cx['busquedas'])} búsquedas en Google, entre ellas: "
                              + "; ".join(t for _, t in cx["busquedas"][:8]))
            if cx["youtube"]:
                hs = sorted(h for h, _ in cx["youtube"] if h)
                lineas.append(f"  {len(cx['youtube'])} videos de YouTube" + (f" entre las {hs[0]} y las {hs[-1]}" if hs else ""))
            if cx["fotos_recibidas"]:
                lineas.append(f"  {len(cx['fotos_recibidas'])} fotos recibidas por WhatsApp (de otros), p. ej.: "
                              + "; ".join(t[:120] for _, t in cx["fotos_recibidas"][:3]))
            if cx.get("chats"):
                from collections import defaultdict

                por = defaultdict(list)
                for h, t, chat in cx["chats"]:
                    por[chat].append((h, t))
                lineas.append("  WhatsApp (lo que él escribió, por chat):")
                for chat, msgs in sorted(por.items(), key=lambda kv: -len(kv[1]))[:6]:
                    hs = [h for h, _ in msgs if h]
                    lineas.append(f"    con {chat}: {len(msgs)} mensajes" + (f" ({hs[0]}–{hs[-1]})" if hs else "") + ": "
                                  + " / ".join(t[:90] for _, t in msgs[:5]))
            if cx["web"]:
                from collections import Counter

                top = Counter(dm for _, dm in cx["web"]).most_common(6)
                hs = sorted(h for h, _ in cx["web"] if h)
                lineas.append(f"  {len(cx['web'])} páginas web en el PC" + (f" entre las {hs[0]} y las {hs[-1]}" if hs else "")
                              + ": sobre todo " + ", ".join(f"{dm} ({k})" for dm, k in top))
            lineas += [f"  {h or '--:--'} {t}" for h, t in cx["otros"][:8]]
    return "\n".join(lineas[:max_lineas])


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _dia_semana(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


# ------------------------------------------------------------------ fechas dichas
_NUM = {"uno": 1, "un": 1, "primero": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
        "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
        "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
        "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27,
        "veintiocho": 28, "veintinueve": 29, "treinta": 30, "treinta y uno": 31}
_MES = {_plain(m): i + 1 for i, m in enumerate(MESES)} | {"setiembre": 9}


def fechas_en(texto: str, hoy: date | None = None) -> tuple[date, date] | None:
    """«el 12 de marzo», «12/3/2025», «alrededor del 5 de abril», «la semana del 3 de mayo», «hace dos semanas»,
    «ayer», «el sábado pasado», «en marzo» -> (desde, hasta). Las fechas sin año son las del pasado más cercano."""
    hoy = hoy or date.today()
    t = _plain(texto)
    for k in sorted(_NUM, key=len, reverse=True):
        t = re.sub(rf"\b{k}\b", str(_NUM[k]), t)
    cerca = bool(re.search(r"\b(alrededor|cerca|por ahi|mas o menos|aprox|esos dias|ese fin)\b", t))
    semana = bool(re.search(r"\bsemana del\b", t))
    finde = bool(re.search(r"\bfin de semana\b", t))

    def rango(d: date) -> tuple[date, date]:
        if semana:
            return d - timedelta(days=d.weekday()), d - timedelta(days=d.weekday()) + timedelta(days=6)
        if finde:
            s = d + timedelta(days=(5 - d.weekday()) % 7) if d.weekday() < 5 else d - timedelta(days=d.weekday() - 5)
            return s - timedelta(days=1), s + timedelta(days=1)
        return (d - timedelta(days=2), d + timedelta(days=2)) if cerca else (d, d)

    def pasado(dd: int, mm: int, yy: int | None) -> date | None:
        try:
            d = date(yy, mm, dd) if yy else date(hoy.year, mm, dd)
        except ValueError:
            return None
        if not yy and d > hoy:
            d = d.replace(year=d.year - 1)
        return d

    m = re.search(r"\b(\d{1,2})\s*(?:de\s+)?(" + "|".join(_MES) + r")(?:\s+(?:de(?:l)?\s+)?(\d{4}))?", t)
    if m:
        d = pasado(int(m.group(1)), _MES[m.group(2)], int(m.group(3)) if m.group(3) else None)
        if d:
            return rango(d)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        yy = int(m.group(3)) if m.group(3) else None
        yy = yy + 2000 if yy is not None and yy < 100 else yy
        d = pasado(int(m.group(1)), int(m.group(2)), yy)
        if d:
            return rango(d)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return rango(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if re.search(r"\bantes de ayer|anteayer\b", t):
        return rango(hoy - timedelta(days=2))
    if re.search(r"\bayer\b", t):
        return rango(hoy - timedelta(days=1))
    m = re.search(r"\bhace (\d+) (dia|dias|semana|semanas|mes|meses)\b", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        d = hoy - timedelta(days=n * (1 if u.startswith("dia") else 7 if u.startswith("semana") else 30))
        return (d - timedelta(days=3), d + timedelta(days=3)) if not u.startswith("dia") else rango(d)
    m = re.search(r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)( pasado)?\b", t)
    if m and re.search(r"\b(el|este|ese)\s+" + m.group(1), t):
        wd = [_plain(x) for x in DIAS].index(m.group(1))
        back = (hoy.weekday() - wd) % 7 or 7
        return rango(hoy - timedelta(days=back))
    m = re.search(r"\b(?:en|de|durante)\s+(" + "|".join(_MES) + r")(?:\s+(?:de(?:l)?\s+)?(\d{4}))?\b", t)
    if m:
        mm = _MES[m.group(1)]
        yy = int(m.group(2)) if m.group(2) else (hoy.year if mm <= hoy.month else hoy.year - 1)
        ini = date(yy, mm, 1)
        fin = (date(yy + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1))
        return ini, min(fin, hoy)
    return None


# ------------------------------------------------------------------ voz
_RX_PREGUNTA = re.compile(
    r"\b(que (?:estaba haciendo|estuve haciendo|hacia|hice|hicimos|paso)|donde (?:estaba|estuve|andaba|anduve)|"
    r"(?:con quien|con quienes) (?:estaba|estuve|anduve)|que fotos (?:tengo|hay|saque)|(?:en )?que fotos (?:aparezco|salgo)|"
    r"mi historia|reconstru\w+|que (?:me )?(?:estaba|anduve)|para que fue (?:el|ese) (?:cargo|gasto))\b")


def es_pregunta(texto: str) -> bool:
    t = _plain(texto)
    return bool(_RX_PREGUNTA.search(t)) and fechas_en(texto) is not None


def es_privado(texto: str) -> bool:
    """¿Este texto salió de la historia personal (pregunta o respuesta)? Así no viaja a Claude."""
    t = (texto or "").strip()
    return bool(t) and (t in _privados or any(t[:200] in p or p[:200] in t for p in _privados if len(p) > 20))


def _marcar_privado(*textos: str) -> None:
    for x in textos:
        if x:
            _privados.append(x.strip())
    del _privados[:-200]


PERSONA_HISTORIA = (
    "Eres Atlas, el mayordomo del usuario; lo tratas de «señor» y de usted. Te pregunta qué estaba haciendo en una "
    "fecha. Empieza por DÓNDE estuvo según las pistas y di qué tan seguro es («probablemente», «según un viaje en "
    "Uber»); si no hay pistas de lugar, dilo en una frase. Luego lo que hizo. El CONTEXTO (búsquedas, videos, fotos "
    "recibidas) úsalo solo si ayuda a entender el día, en media frase. Abajo van los datos reales de su PC (fotos descritas, calendario, correos, gastos, ubicación, historial web). "
    "Reconstruye en 2 a 5 frases habladas, en español, lo más probable que hizo, con horas cuando ayuden. Usa SOLO "
    "estos datos; si son pocos, dilo. Lo más confiable: ubicación, gastos, calendario, búsquedas y web, correos que "
    "él envió, fotos de su cámara o enviadas por él. Los correos recibidos no son acciones suyas: no digas que los "
    "revisó ni saques conclusiones de ellos, salvo que sean comprobantes de un pedido, pago o reserva. Las fotos RECIBIDAS por WhatsApp son solo contexto (son de otros "
    "y la fecha es la de recepción): no digas que él estuvo ahí salvo que diga «aparece usted». Distingue lo seguro "
    "de lo que supones. Sin markdown, sin listas.")


def responder(texto: str) -> dict | None:
    t = _plain(texto)
    if re.search(r"\b(pausa|deten|para)\w* (la |el )?(descripcion|revision|analfortuna|indexado) de (las )?fotos\b", t):
        guardar_config(pausado=True)
        return {"reply": "Listo, señor: dejo de revisar sus fotos hasta que me diga «reanuda las fotos».", "privado": True}
    if re.search(r"\b(reanuda|sigue|continua)\w* (con )?(la |las )?(descripcion de |revision de )?fotos\b", t):
        guardar_config(pausado=False)
        return {"reply": "Retomo la revisión de sus fotos cuando el equipo esté desocupado, señor.", "privado": True}
    if re.search(r"\bcomo va (la |mi )?(historia|revision de (las |mis )?fotos|indice)\b", t):
        e = estado()
        return {"reply": f"Llevo {e['descritas']} de {e['fotos']} fotos descritas, señor"
                         + (f", y reconozco su cara con {e['refs']} fotos de referencia." if e["refs"] else
                            ". Aún no me enseña su cara: ábrame Cronos y marque algunas fotos suyas."), "privado": True}
    if not es_pregunta(texto):
        return None
    a, b = fechas_en(texto)
    if (b - a).days > 31:
        b = a + timedelta(days=31)
    if a == b and re.search(r"\b(que (hice|hacia|estaba haciendo|estuve haciendo|paso)|donde (estuve|estaba)|mi dia|relato|"
                            r"como (fue|estuvo) (mi|el|ese) dia|cuentame (de|el|del|sobre))\b", t):
        try:  # el mismo relato que se ve en Cronos (guardado; solo se rehace si cambian los datos)
            rel = narrar(a)
            if rel and not rel.startswith("No hay nada"):
                reply = f"Según Cronos, el {_dia_semana(a)}: {rel}"
                _marcar_privado(texto, reply)
                return {"reply": reply, "privado": True, "embed_dia": a.isoformat()}
        except Exception:  # noqa: BLE001
            pass
    d = dia(a, b)
    datos = texto_para_modelo(d)
    when = _dia_semana(a) if a == b else f"entre el {_dia_semana(a)} y el {_dia_semana(b)}"
    if not datos.strip():
        reply = f"No tengo nada registrado {('del ' + when) if a == b else when}, señor."
    else:
        try:
            reply = ollama_chat([{"role": "system", "content": PERSONA_HISTORIA},
                                 {"role": "user", "content": f"<datos>\n{datos}\n</datos>\n<usuario>{texto}</usuario>"}],
                                num_predict=260, timeout=90)
        except Exception as exc:  # noqa: BLE001
            reply = f"Tengo datos {('del ' + when) if a == b else when}, señor, pero el modelo local no respondió ({exc})."
    reply = re.sub(r"[*#_`]+", "", reply).strip()
    _marcar_privado(texto, reply)
    return {"reply": reply, "privado": True, "embed_dia": a.isoformat()}


RELATO = (
    "Escribe en español el relato de un día del usuario, en tercera persona y en pasado, de 4 a 7 frases cortas, en "
    "orden cronológico, como una bitácora (forma: «Durmió hasta las HH:MM en su casa. A las HH:MM salió en … hacia …. "
    "A las HH:MM tenía …»; esa es solo la forma: nunca copies lugares, horas ni hechos que no estén en los datos). Usa "
    "SOLO los datos de <datos>. Lo más confiable: LÍNEA DEL DÍA, recibos de viajes, validaciones bip!, gastos y "
    "calendario. No hay chats: nunca digas que conversó, coordinó o escribió por chat. "
    "Marca lo supuesto con «probablemente» o «quizás». Respeta los roles: en Introducción a la Programación es "
    "profesor auxiliar (todo lo marcado «como profesor auxiliar»: cátedras, controles y auxiliares); los demás ramos los cursa como alumno, y una cátedra en su horario no prueba que fue. Un «Auxiliar» de un ramo que cursa como alumno es una clase auxiliar a la que asistió, no algo que él dictó. Las fotos recibidas son de otros. No menciones música ni "
    "canciones. Los correos que recibió no son cosas que hizo: nunca digas que revisó, leyó o gestionó correos, y nunca "
    "expliques una hora, un atraso o una decisión con un correo; un comprobante solo dice que hubo un pedido, pago o "
    "reserva a esa hora. No inventes nombres: las personas son «contacto A», «contacto B». Sin markdown, sin listas, sin "
    "saludo ni «señor».")


def narrar(f: date, forzar: bool = False) -> str:
    """Relato corto del día hecho por el modelo local. Se guarda por fecha y se rehace si cambian los datos."""
    datos = texto_para_modelo(dia(f))
    if not datos.strip():
        return "No hay nada registrado ese día."
    k = "relato_" + f.isoformat() + "_" + hashlib.sha1(datos.encode()).hexdigest()[:10]
    con = db()
    try:
        hit = None if forzar else _estado(con, k)
        if hit:
            return hit
        g = _CORTE[0]
        try:
            txt = ollama_chat([{"role": "system", "content": RELATO},
                               {"role": "user", "content": f"<datos>\n{datos}\n</datos>\nRelato del {_dia_semana(f)}:"}],
                              num_predict=320, timeout=120, cortar=lambda: _CORTE[0] != g)
        except RelatoCortado:
            return ""  # se cerró Cronos: no se guarda nada a medias
        txt = re.sub(r"[*#_`]+", "", txt).strip()
        _estado(con, k, txt)
    finally:
        con.close()
    _marcar_privado(txt)
    return txt


# ------------------------------------------------------------------ panel: estado, enseñar cara, prueba controlada
def estado() -> dict:
    con = db()
    q = lambda s, *a: con.execute(s, a).fetchone()[0]  # noqa: E731
    um = config()["umbral_cara"]
    e = {"fotos": q("SELECT COUNT(*) FROM fotos"), "procesadas": q("SELECT COUNT(*) FROM fotos WHERE procesada>=1"),
         "descritas": q("SELECT COUNT(*) FROM fotos WHERE procesada=2"), "errores": q("SELECT COUNT(*) FROM fotos WHERE procesada=-1"),
         "con_caras": q("SELECT COUNT(*) FROM fotos WHERE n_caras>0"), "caras": q("SELECT COUNT(*) FROM caras"),
         "refs": q("SELECT COUNT(*) FROM etiquetas WHERE origen='ensenar' AND yo=1"),
         "usted": q("SELECT COUNT(*) FROM fotos WHERE yo>=?", um), "items": q("SELECT COUNT(*) FROM items"),
         "por_fuente": dict(con.execute("SELECT fuente, COUNT(*) FROM items GROUP BY fuente").fetchall()),
         "umbral": um, "pausado": config()["pausado"], "fondo": {k: v for k, v in _fondo.items() if k != "hilos"}}
    con.close()
    return e


def candidatas_ensenar(n: int = 36) -> list[dict]:
    """Caras para que el usuario marque las suyas: sin etiquetar, grandes; si ya hay referencias, las más parecidas
    primero (mezcladas con algunas al azar para no sesgar)."""
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT c.id, c.yo, c.w FROM caras c LEFT JOIN etiquetas e ON e.cara=c.id WHERE e.cara IS NULL AND c.w>=70 "
        "AND c.conf>=0.9")]
    con.close()
    random.shuffle(rows)
    if any(r["yo"] is not None for r in rows):
        top = sorted([r for r in rows if r["yo"] is not None], key=lambda r: -r["yo"])[: n * 2 // 3]
        ids = {r["id"] for r in top}
        rows = top + [r for r in rows if r["id"] not in ids][: n - len(top)]
    return [{"cara": r["id"]} for r in rows[:n]]


def marcar(cara: int, yo: bool, origen: str = "ensenar", prueba: int | None = None) -> dict:
    con = db()
    pred = con.execute("SELECT yo FROM caras WHERE id=?", (cara,)).fetchone()
    with _lock:
        con.execute("INSERT OR REPLACE INTO etiquetas VALUES(?,?,?,?,?,?)",
                    (cara, int(bool(yo)), origen, prueba, pred[0] if pred else None, time.time()))
        con.commit()
    con.close()
    if origen == "ensenar":
        recalcular_yo()
    return estado()


def nueva_prueba(n: int = 60) -> dict:
    """Muestra estratificada de caras SIN etiquetar: ~40 % que Atlas cree que son usted, ~35 % dudosas cerca del
    umbral y ~25 % que cree que no. Se muestran con la predicción; el usuario marca Sí o No."""
    um = config()["umbral_cara"]
    con = db()
    rows = [dict(r) for r in con.execute(
        "SELECT c.id, c.yo FROM caras c LEFT JOIN etiquetas e ON e.cara=c.id WHERE e.cara IS NULL AND c.yo IS NOT NULL "
        "AND c.w>=50")]
    pid = int(_estado(con, "prueba_n") or 0) + 1
    _estado(con, "prueba_n", pid)
    con.close()
    random.shuffle(rows)
    si = [r for r in rows if r["yo"] >= um + 0.08]
    duda = [r for r in rows if um - 0.12 <= r["yo"] < um + 0.08]
    no = [r for r in rows if r["yo"] < um - 0.12]
    pick = si[: int(n * .4)] + duda[: int(n * .35)]
    pick += no[: n - len(pick)]
    random.shuffle(pick)
    return {"prueba": pid, "umbral": um, "caras": [{"cara": r["id"], "cree": r["yo"] >= um} for r in pick]}


def resultado_prueba(prueba: int | None = None) -> dict:
    """Aciertos con el umbral actual y el umbral sugerido, sobre todas las respuestas de pruebas (o una)."""
    con = db()
    sql = "SELECT e.yo, c.yo AS p FROM etiquetas e JOIN caras c ON c.id=e.cara WHERE e.origen='prueba' AND c.yo IS NOT NULL"
    rows = con.execute(sql + (" AND e.prueba=?" if prueba else ""), ((prueba,) if prueba else ())).fetchall()
    con.close()
    um = config()["umbral_cara"]

    def medir(u):
        tp = sum(1 for r in rows if r["yo"] and r["p"] >= u)
        fp = sum(1 for r in rows if not r["yo"] and r["p"] >= u)
        fn = sum(1 for r in rows if r["yo"] and r["p"] < u)
        tn = len(rows) - tp - fp - fn
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        return {"umbral": round(u, 3), "vp": tp, "fp": fp, "fn": fn, "vn": tn, "precision": prec, "exhaustividad": rec,
                "acierto": (tp + tn) / len(rows) if rows else None}

    actual = medir(um)
    cands = [medir(u / 100) for u in range(15, 80)]
    ok = [c for c in cands if c["precision"] is not None and c["precision"] >= 0.95 and c["vp"] >= 3]
    sug = max(ok, key=lambda c: (c["exhaustividad"] or 0, -c["umbral"])) if ok else None
    return {"respuestas": len(rows), "actual": actual, "sugerido": sug}


def usar_umbral(u: float) -> dict:
    guardar_config(umbral_cara=round(float(u), 3))
    return estado()


def recorte_cara(cara: int, lado: int = 160) -> bytes | None:
    from PIL import Image, ImageOps

    con = db()
    r = con.execute("SELECT c.x, c.y, c.w, c.h, f.ruta FROM caras c JOIN fotos f ON f.id=c.foto WHERE c.id=?", (cara,)).fetchone()
    con.close()
    if not r:
        return None
    with Image.open(r["ruta"]) as im0:
        im = ImageOps.exif_transpose(im0).convert("RGB")
    im.thumbnail((1280, 1280))  # mismas coordenadas que al detectar
    m = int(max(r["w"], r["h"]) * 0.35)
    box = (max(0, r["x"] - m), max(0, r["y"] - m), min(im.width, r["x"] + r["w"] + m), min(im.height, r["y"] + r["h"] + m))
    c = im.crop(box)
    c.thumbnail((lado, lado))
    buf = io.BytesIO()
    c.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def miniatura(fid: int, lado: int = 360) -> bytes | None:
    from PIL import Image, ImageOps

    con = db()
    r = con.execute("SELECT ruta FROM fotos WHERE id=? UNION SELECT f.ruta FROM fotos f WHERE 0", (fid,)).fetchone()
    con.close()
    if not r:
        return None
    with Image.open(r["ruta"]) as im0:
        im = ImageOps.exif_transpose(im0).convert("RGB")
    im.thumbnail((lado, lado))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def foto_de_cara(cara: int) -> int | None:
    con = db()
    r = con.execute("SELECT foto FROM caras WHERE id=?", (cara,)).fetchone()
    con.close()
    return r[0] if r else None


# ------------------------------------------------------------------ HTTP (lo llama hud_server bajo /acceso/historia/)
def http(metodo: str, sub: str, query: dict, body: dict | None = None) -> tuple[int, bytes, str]:
    """-> (código, contenido, tipo). Solo se llama desde 127.0.0.1 (hud_server lo verifica)."""
    def js(o, code=200):
        return code, json.dumps(o, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8"

    qv = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731
    body = body or {}
    try:
        if FOTOS_DESACTIVADAS and sub in ("api/ensenar", "api/prueba", "api/resultado", "cara", "foto", "api/foto_de_cara",
                                          "api/marcar", "api/umbral"):
            return js({"error": "las fotos ya no se usan en Cronos"}, 404)
        if metodo == "GET" and sub == "api/estado":
            return js(estado())
        if metodo == "GET" and sub == "api/fuentes":
            return js(fuentes())
        if metodo == "POST" and sub == "api/modo":  # «rutas» (tiene Rutas de Maps) o «senales» (sin ubicación)
            m = body.get("modo")
            if m not in ("rutas", "senales"):
                return js({"error": "modo inválido"}, 400)
            guardar_config(modo_ubicacion=m)
            return js(fuentes())
        if metodo == "POST" and sub == "api/pegar_bip":  # tabla copiada de tarjetabip.cl (sin el número de tarjeta)
            filas = []
            for linea in str(body.get("texto") or "")[:300000].splitlines():
                partes = [x.strip() for x in linea.split("\t") if x.strip()]
                i = next((j for j, x in enumerate(partes) if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", x)), None)
                if i is not None and 1 <= i and i + 2 < len(partes) and re.match(r"(?i)uso|carga", partes[i - 1]):
                    filas.append("\t".join(partes[i - 1:i + 3]))
            if not filas:
                return js({"error": "No encontré viajes en lo pegado. Copie la tabla completa de movimientos."}, 400)
            with BIP_FILE.open("a", encoding="utf-8") as fh:
                fh.write("\n" + "\n".join(filas) + "\n")
            con = db()
            try:
                n = importar_bip(con)
                con.commit()
            finally:
                con.close()
            return js({"filas": len(filas), "nuevos": n})
        if metodo == "POST" and sub == "api/importar_chats":
            con = db()
            try:
                r = importar_chats_horas(con)
            finally:
                con.close()
            return js(r)
        if metodo == "GET" and sub == "api/dias_con_datos":  # «2026-10» -> fechas de ese mes con algo registrado
            mes = qv("mes") or ""
            if not re.fullmatch(r"\d{4}-\d{2}", mes):
                return js({"error": "mes inválido"}, 400)
            con = db()
            try:
                dias = [r[0] for r in con.execute("SELECT DISTINCT fecha FROM items WHERE fecha LIKE ? AND fuente <> 'chat_hora' ORDER BY 1",
                                                  (mes + "-%",))]
            finally:
                con.close()
            return js({"dias": sorted(set(dias) | _dias_rutas(mes))})
        if metodo == "GET" and sub == "api/dia":
            a = date.fromisoformat(qv("desde") or qv("fecha"))
            b = date.fromisoformat(qv("hasta") or qv("fecha") or qv("desde"))
            return js(dia(a, b, correos=qv("correos", "1") == "1"))
        if metodo == "GET" and sub == "api/narrar":
            f = date.fromisoformat(qv("fecha"))
            return js({"texto": narrar(f, forzar=qv("forzar") == "1")})
        if metodo == "GET" and sub == "api/ensenar":
            return js({"caras": candidatas_ensenar(int(qv("n", 36)))})
        if metodo == "GET" and sub == "api/prueba":
            return js(nueva_prueba(int(qv("n", 60))))
        if metodo == "GET" and sub == "api/resultado":
            return js(resultado_prueba(int(qv("prueba")) if qv("prueba") else None))
        if metodo == "GET" and sub in ("cara", "foto"):
            i = int(qv("id"))
            raw = recorte_cara(i) if sub == "cara" else miniatura(i, int(qv("w", 360)))
            return (200, raw, "image/jpeg") if raw else js({"error": "no está"}, 404)
        if metodo == "GET" and sub == "api/foto_de_cara":
            return js({"foto": foto_de_cara(int(qv("id")))})
        if metodo == "POST" and sub == "api/marcar":
            return js(marcar(int(body["cara"]), bool(body["yo"]), "prueba" if body.get("prueba") else "ensenar",
                             int(body["prueba"]) if body.get("prueba") else None))
        if metodo == "GET" and sub == "api/dia_azar":
            return js(dia_al_azar())
        if metodo == "GET" and sub == "api/diagnostico":
            return js(diagnostico(max(1, min(14, int(qv("dias", 7)))), date.fromisoformat(qv("hasta")) if qv("hasta") else None))
        if metodo == "POST" and sub == "api/revisar":
            return js(marcar_bloque(body))
        if metodo == "POST" and sub == "api/umbral":
            return js(usar_umbral(float(body["umbral"])))
        if metodo == "POST" and sub == "api/pausa":
            guardar_config(pausado=bool(body.get("pausado")))
            return js(estado())
        if metodo == "POST" and sub == "api/escanear":
            n = escanear_fotos()
            return js({"nuevas": n, "importados": importar_todo(), **estado()})
    except Exception as exc:  # noqa: BLE001
        return js({"error": str(exc)[:300]}, 500)
    return js({"error": "no existe"}, 404)

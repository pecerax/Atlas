"""Baco, segunda parte (19-11-2026): lo que hace a Baco más «centro de entretenimiento».

- portada(): la carátula de la canción que suena en Windows (controles multimedia), en bytes.
- sonado(): lo que sonó en el PC (para armar playlists con «Lo que sonó hoy»); lo anota atlas_baco.media().
- noticias(): titulares en español de lo que la persona juega, ve, espera y escucha (Google Noticias por tema y
  feeds RSS de sitios de juegos, series y música), con su selector de temas y fuentes.
- descubrir(): «Para ti»: series parecidas (TMDB), juegos parecidos o que salen pronto (IGDB) y, si falta con qué,
  lo que dijo en su perfil (géneros y plataformas).
- arte(): fondo y carátula de un juego por su nombre (IGDB), para el escenario y las carátulas de juegos fuera de Steam.
- eventos(): eventos generales para «Lo que viene»: eventos de videojuegos (IGDB) y estrenos de cine en Chile (TMDB)
  de los géneros que le gustan.
Las claves siguen en el Administrador de credenciales (las lee atlas_baco); aquí no se guarda ninguna.
"""

from __future__ import annotations

import base64
import concurrent.futures as cf
import datetime
import email.utils
import html
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import atlas_baco as BA

SONADO = Path(os.environ.get("BACO_SONADO") or (Path.home() / ".atlas" / "baco_sonado.json"))
_LOCK = threading.RLock()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AtlasBaco/1.1"
# PuntoTicket no tiene API: Baco lee su cartelera pública UNA vez al día, solo para uso personal.
# Antes de distribuir Atlas, poner esto en False (o cambiarlo por una fuente con permiso, como la API de Ticketmaster).
PUNTOTICKET = True
PT_URL = "https://www.puntoticket.com/todos"
PT_CACHE = Path(os.environ.get("BACO_PUNTOTICKET") or (Path.home() / ".atlas" / "baco_puntoticket.json"))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ----------------------------------------------------------------------------- perfil (lo que respondió al abrir)
PERFIL_OPCIONES = {
    "ver": ["anime", "drama", "comedia", "ciencia ficcion", "fantasia", "terror", "policial", "documentales", "animacion", "accion", "reality"],
    "donde": ["netflix", "disney", "max", "prime", "apple", "crunchy", "paramount", "youtube"],
    "jugar": ["accion", "rpg", "shooter", "mundo abierto", "estrategia", "deportes", "indie", "terror", "gacha", "moba", "carreras", "pelea"],
    "consolas": ["pc", "ps5", "xbox", "switch", "celular"],
    "musica": ["pop", "rock", "urbano", "electronica", "indie", "hip hop", "metal", "kpop", "latino", "bandas sonoras", "jazz"],
}
# géneros de TMDB (series, películas) e IGDB
_TV = {"anime": "16", "drama": "18", "comedia": "35", "ciencia ficcion": "10765", "fantasia": "10765", "terror": "9648",
       "policial": "80", "documentales": "99", "animacion": "16", "accion": "10759", "reality": "10764"}
_PELI = {"anime": "16", "drama": "18", "comedia": "35", "ciencia ficcion": "878", "fantasia": "14", "terror": "27",
         "policial": "80", "documentales": "99", "animacion": "16", "accion": "28"}
_PROV = {"netflix": "8", "disney": "337", "max": "1899", "prime": "119", "apple": "350", "crunchy": "283", "paramount": "531"}
_IGDB_GEN = {"rpg": "12", "shooter": "5", "estrategia": "15,16", "deportes": "14", "indie": "32", "carreras": "10",
             "pelea": "4", "moba": "36", "accion": "25,31"}
_IGDB_TEMA = {"terror": "19", "mundo abierto": "38"}


def limpiar_perfil(p) -> dict:
    p = p if isinstance(p, dict) else {}
    out = {"listo": bool(p.get("listo"))}
    for k, ops in PERFIL_OPCIONES.items():
        v = p.get(k) if isinstance(p.get(k), list) else []
        out[k] = [x for x in dict.fromkeys(str(i) for i in v) if x in ops]
    out["artistas"] = [BA._txt(a, 60) for a in (p.get("artistas") if isinstance(p.get("artistas"), list) else []) if BA._txt(a, 60)][:20]
    out["ciudad"] = BA._txt(p.get("ciudad"), 60)
    out["pt"] = p.get("pt", True) is not False   # eventos de PuntoTicket (se puede apagar en «Tu perfil»)
    if isinstance(p.get("eventos"), list):         # subcategorías que sigue en «Lo que viene» (sin elegir: None)
        out["eventos"] = [x for x in dict.fromkeys(str(i) for i in p["eventos"]) if x in SUBCATS]
    return out


def limpiar_noticias(n) -> dict:
    n = n if isinstance(n, dict) else {}
    lista = lambda k, m: [BA._txt(x, 60) for x in (n.get(k) if isinstance(n.get(k), list) else []) if BA._txt(x, 60)][:m]  # noqa: E731
    return {"off": lista("off", 100), "extra": lista("extra", 30), "fuentes_off": [f for f in lista("fuentes_off", 20) if f in FUENTES],
            "generales": bool(n.get("generales", False))}


# ----------------------------------------------------------------------------- red
_CACHE: dict = {}


def _get(url: str, horas: float = 0.5, cab: dict | None = None, tiempo: float = 7) -> bytes:
    with _LOCK:
        c = _CACHE.get(url)
        if c and time.time() - c[0] < horas * 3600:
            return c[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9", **(cab or {})})
    with urllib.request.urlopen(req, timeout=tiempo) as r:
        datos = r.read(3_000_000)
    with _LOCK:
        if len(_CACHE) > 300:
            _CACHE.clear()
        _CACHE[url] = (time.time(), datos)
    return datos


# ----------------------------------------------------------------------------- portada de la canción
_PS_PORTADA = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $m.MakeGenericMethod($t).Invoke($null, @($op)); $null = $task.Wait(4000); $task.Result }
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType = WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$s = $mgr.GetCurrentSession()
if (-not $s) { exit }
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
if (-not $p.Thumbnail) { exit }
$st = Await ($p.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
$ns = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($st)
$ms = New-Object IO.MemoryStream
$ns.CopyTo($ms)
[Convert]::ToBase64String($ms.ToArray())
"""
_PORTADA: dict = {"k": None, "v": b"", "t": 0.0}


def portada(clave: str) -> tuple[bytes, str]:
    """(bytes, tipo) de la carátula de lo que suena; (b'', '') si no hay. clave = título|artista, para recordar."""
    clave = BA._txt(clave, 300)
    with _LOCK:
        if _PORTADA["k"] == clave and (_PORTADA["v"] or time.time() - _PORTADA["t"] < 20):
            datos = _PORTADA["v"]
            return datos, _tipo(datos)
    datos = b""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_PORTADA],
                           capture_output=True, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        txt = r.stdout.decode("ascii", "ignore").strip().splitlines()
        if txt:
            datos = base64.b64decode(txt[-1], validate=False)[:4_000_000]
    except Exception:  # noqa: BLE001
        datos = b""
    if not _tipo(datos):
        datos = b""
    if not datos and "|" in clave:   # Windows no la entregó: la busco en el catálogo público de Apple Music (sin clave)
        try:
            datos = portada_catalogo(*clave.split("|", 1))
        except Exception:  # noqa: BLE001
            datos = b""
    with _LOCK:
        _PORTADA.update(k=clave, v=datos, t=time.time())
    return datos, _tipo(datos)


def _limpio_cancion(t: str) -> str:
    t = re.sub(r"\s*[\(\[][^\)\]]*(mix|remix|edit|version|versión|live|en vivo|remaster|official|oficial|video|audio|lyric|letra|feat\.?|ft\.?)[^\)\]]*[\)\]]", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def portada_catalogo(titulo: str, artista: str) -> bytes:
    """Carátula por título y artista en la búsqueda pública de iTunes/Apple Music (sin clave). b'' si no hay."""
    artista = re.sub(r"\s*-\s*topic$", "", (artista or "").strip(), flags=re.I)
    titulo = (titulo or "").strip()
    if not titulo:
        return b""
    if not artista and " - " in titulo:   # videos de YouTube: «Artista - Canción»
        artista, titulo = [x.strip() for x in titulo.split(" - ", 1)]
    for t in dict.fromkeys([titulo, _limpio_cancion(titulo)]):
        if not t:
            continue
        q = urllib.parse.urlencode({"term": f"{t} {artista}".strip()[:120], "entity": "song", "limit": "5", "country": "CL"})
        res = (json.loads(_get("https://itunes.apple.com/search?" + q, 24)) or {}).get("results") or []
        na = _norm(artista)
        res.sort(key=lambda r: (na and na not in _norm(r.get("artistName"))))
        for r in res:
            u = r.get("artworkUrl100") or ""
            if u.startswith("https://"):
                datos = _get(re.sub(r"/\d+x\d+bb\.", "/600x600bb.", u), 24, tiempo=8)
                if _tipo(datos):
                    return datos
    return b""


def _tipo(b: bytes) -> str:
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"GIF8":
        return "image/gif"
    if b[:2] == b"BM":
        return "image/bmp"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return ""


# ----------------------------------------------------------------------------- lo que sonó
def anotar_sonado(v: dict) -> None:
    """Lo llama media(): guarda cada canción nueva que suena (las últimas 300)."""
    if not v.get("hay") or v.get("estado") != "Playing" or not BA._txt(v.get("titulo")):
        return
    t, a = BA._txt(v.get("titulo"), 120), BA._txt(v.get("artista"), 120)
    with _LOCK:
        L = sonado()
        if L and L[-1]["t"] == t and L[-1]["a"] == a:
            return
        L.append({"t": t, "a": a, "app": BA._txt(v.get("app_n"), 40), "ts": int(time.time())})
        L = L[-300:]
        try:
            SONADO.parent.mkdir(parents=True, exist_ok=True)
            tmp = SONADO.with_suffix(".tmp")
            tmp.write_text(json.dumps(L, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, SONADO)
        except OSError:
            pass


def poner_enlace(t: str, a: str, u: str) -> None:
    """El enlace exacto de lo que sonó (lo averigua media() en la ventana de música de Atlas)."""
    t, a, u = BA._txt(t, 120), BA._txt(a, 120), BA._url(u)
    if not u:
        return
    with _LOCK:
        L = sonado()
        for x in reversed(L[-20:]):
            if x["t"] == t and x.get("a", "") == a:
                if x.get("u") == u:
                    return
                x["u"] = u
                break
        else:
            return
        try:
            tmp = SONADO.with_suffix(".tmp")
            tmp.write_text(json.dumps(L, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, SONADO)
        except OSError:
            pass


def sonado() -> list:
    try:
        L = json.loads(SONADO.read_text(encoding="utf-8"))
        return [x for x in L if isinstance(x, dict) and x.get("t")] if isinstance(L, list) else []
    except (OSError, ValueError):
        return []


# ----------------------------------------------------------------------------- noticias
FUENTES = {
    "gnews": {"n": "Google Noticias", "k": "", "u": ""},
    "3dj": {"n": "3DJuegos", "k": "j", "u": "https://www.3djuegos.com/feedburner.xml"},
    "vidaextra": {"n": "VidaExtra", "k": "j", "u": "https://www.vidaextra.com/feedburner.xml"},
    "vandal": {"n": "Vandal", "k": "j", "u": "https://vandal.elespanol.com/xml.cgi"},
    "espinof": {"n": "Espinof", "k": "s", "u": "https://www.espinof.com/feedburner.xml"},
    "mondo": {"n": "Mondo Sonoro", "k": "m", "u": "https://www.mondosonoro.com/feed/"},
}
_MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def _texto(s: str, n: int = 220) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def _fecha(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    try:
        return int(email.utils.parsedate_to_datetime(s).timestamp())
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def leer_feed(datos: bytes) -> list:
    """RSS o Atom -> [{t, u, d, f, img}]."""
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError:
        return []
    out = []
    items = raiz.findall(".//item") or raiz.findall(".//{http://www.w3.org/2005/Atom}entry")
    for it in items[:60]:
        g = lambda tag: (it.findtext(tag) or it.findtext("{http://www.w3.org/2005/Atom}" + tag) or "")  # noqa: E731
        link = g("link").strip()
        if not link:
            le = it.find("{http://www.w3.org/2005/Atom}link")
            link = le.get("href", "") if le is not None else ""
        desc = g("description") or g("summary") or it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        img = ""
        for tag in ("enclosure", _MEDIA_NS + "content", _MEDIA_NS + "thumbnail"):
            e = it.find(tag)
            if e is not None and (e.get("url") or "").startswith("http") and (tag != "enclosure" or "image" in (e.get("type") or "image")):
                img = e.get("url")
                break
        if not img:
            m = re.search(r'<img[^>]+src="(https?://[^"]+)"', desc)
            img = m.group(1) if m else ""
        t = _texto(g("title"), 200)
        if t and link.startswith(("http://", "https://")):
            out.append({"t": t, "u": link, "d": _texto(desc), "f": _fecha(g("pubDate") or g("updated") or g("published")), "img": img})
    return out


def temas(d: dict | None = None) -> list:
    """[{t, k, why}] de lo que juega, ve, espera y escucha, más sus temas extra. k: j/s/m/x."""
    d = d or BA.cargar()
    out: list = []
    vistos = set()

    def add(t, k, why):
        n = _norm(t)
        if len(n) >= 3 and n not in vistos:
            vistos.add(n)
            out.append({"t": BA._txt(t, 60), "k": k, "why": why})

    for e in d.get("esperados", []):
        add(e["t"], "j", "Lo esperas")
    try:
        juegos = list((BA.juegos_steam().get("juegos") or [])) + list((BA.juegos_pc().get("juegos") or []))
    except Exception:  # noqa: BLE001
        juegos = []
    juegos.sort(key=lambda j: j.get("ultima") or 0, reverse=True)
    for j in juegos[:8]:
        add(j.get("t", ""), "j", "Lo juegas")
    for s in d.get("series", []):
        add(s["t"], "s", "La ves")
    for e in d.get("esperas", []):
        if e.get("k") == "c":
            add(e["t"], "m", "Vas a verlo")
    for a in (d.get("perfil") or {}).get("artistas", []):
        add(a, "m", "Lo escuchas")
    for x in (d.get("noticias") or {}).get("extra", []):
        add(x, "x", "Te interesa")
    return out


def _gnews(tema: dict) -> list:
    extra = {"j": " videojuego", "s": " serie", "m": " música"}.get(tema["k"], "")
    q = f'"{tema["t"]}"{extra}'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:14d", "hl": "es-419", "gl": "CL", "ceid": "CL:es-419"})
    res = []
    for x in leer_feed(_get(url, 0.75))[:5]:
        src = ""
        if " - " in x["t"]:
            x["t"], src = x["t"].rsplit(" - ", 1)
        res.append({**x, "d": "", "src": src or "Google Noticias", "fuente": "gnews"})
    return res


def noticias(d: dict | None = None) -> dict:
    d = d or BA.cargar()
    cfg = limpiar_noticias(d.get("noticias"))
    T = temas(d)
    off = {_norm(x) for x in cfg["off"]}
    activos = [t for t in T if _norm(t["t"]) not in off]
    fuentes = [f for f in FUENTES if f not in cfg["fuentes_off"]]
    items, errores = [], []

    def de_fuente(fid):
        F = FUENTES[fid]
        return [{**x, "src": F["n"], "fuente": fid, "kf": F["k"]} for x in leer_feed(_get(F["u"], 0.5))]

    trabajos = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        if "gnews" in fuentes:
            for t in activos[:14]:
                trabajos[ex.submit(_gnews, t)] = ("gnews", t)
        for fid in fuentes:
            if fid != "gnews":
                trabajos[ex.submit(de_fuente, fid)] = (fid, None)
        for fu in cf.as_completed(trabajos, timeout=25):
            fid, t = trabajos[fu]
            try:
                L = fu.result()
            except Exception as exc:  # noqa: BLE001
                if FUENTES[fid]["n"] not in errores:
                    errores.append(FUENTES[fid]["n"])
                BA_log(f"noticias {fid}: {type(exc).__name__}")
                continue
            for x in L:
                if t:
                    x.update(tema=t["t"], k=t["k"], why=t["why"])
                items.append(x)
    # temas en los titulares de los sitios
    pats = [(t, re.compile(r"\b" + re.escape(_norm(t["t"])) + r"\b")) for t in activos]
    out, vistos = [], set()
    for x in items:
        if not x.get("tema"):
            texto = _norm(x["t"] + " " + x.get("d", ""))
            for t, p in pats:
                if p.search(texto):
                    x.update(tema=t["t"], k=t["k"], why=t["why"])
                    break
        if not x.get("tema"):
            if not cfg["generales"]:
                continue
            x.update(tema="", k=x.get("kf") or "x", why="")
        clave = _norm(x["t"])[:80]
        if clave in vistos:
            continue
        vistos.add(clave)
        x.pop("kf", None)
        out.append(x)
    hace = time.time() - 21 * 86400
    out = [x for x in out if not x["f"] or x["f"] >= hace]
    out.sort(key=lambda x: x["f"], reverse=True)
    return {"ok": True, "res": out[:60], "temas": [{**t, "on": _norm(t["t"]) not in off} for t in T],
            "fuentes": [{"id": k, "n": v["n"], "on": k in fuentes} for k, v in FUENTES.items()],
            "generales": cfg["generales"], "errores": errores}


def BA_log(msg: str) -> None:  # noqa: N802
    try:
        import logging

        logging.getLogger("atlas.baco").info(msg)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- IGDB por nombre (arte, parecidos)
_ARTE: dict = {}
IGDB_ARTE = "https://images.igdb.com/igdb/image/upload/t_1080p/"


def arte(nombre: str) -> dict:
    """{igdb, t, cover, fondo, url, parecidos: [...]} del juego que mejor calza con el nombre. Recordado 12 h."""
    n = _norm(nombre)
    if len(n) < 2:
        return {"ok": False}
    with _LOCK:
        c = _ARTE.get(n)
        if c and time.time() - c["_t"] < 12 * 3600:
            return {k: v for k, v in c.items() if k != "_t"}
    limpio = BA._txt(nombre, 80).replace('"', " ").replace("\\", " ")
    res = BA._igdb("games", f'search "{limpio}"; fields name,url,cover.image_id,artworks.image_id,screenshots.image_id,'
                            f'similar_games.name,similar_games.cover.image_id,similar_games.first_release_date,'
                            f'similar_games.total_rating,similar_games.url; where version_parent = null; limit 6;')
    g = None
    for x in res:
        if _norm(x.get("name")) == n:
            g = x
            break
    g = g or (res[0] if res else None)
    if not g:
        r = {"ok": False}
    else:
        fondos = [a["image_id"] for a in (g.get("artworks") or []) + (g.get("screenshots") or []) if a.get("image_id")]
        par = []
        for s in g.get("similar_games") or []:
            par.append({"igdb": s.get("id"), "t": s.get("name") or "", "img": (s.get("cover") or {}).get("image_id") or "",
                        "url": s.get("url") or "", "nota": round((s.get("total_rating") or 0) / 10, 1),
                        "f": time.strftime("%Y-%m-%d", time.gmtime(s["first_release_date"])) if s.get("first_release_date") else ""})
        r = {"ok": True, "igdb": g.get("id"), "t": g.get("name") or "", "cover": (g.get("cover") or {}).get("image_id") or "",
             "fondo": fondos[0] if fondos else "", "url": g.get("url") or "", "parecidos": par[:8]}
    with _LOCK:
        _ARTE[n] = {**r, "_t": time.time()}
    return r


# ----------------------------------------------------------------------------- Para ti
_DESC: dict = {"k": None, "t": 0.0, "v": None}


_ROMANOS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
_RELLENO = {"the", "edition", "deluxe", "digital", "complete", "definitive", "remastered", "goty", "game", "of", "year",
            "standard", "ultimate", "premium", "tm", "r"}


def clave_juego(t: str) -> str:
    """Nombre de juego comparable: «OCTOPATH TRAVELER™ II Digital Deluxe» y «Octopath Traveler 2» dan lo mismo."""
    w = _norm(str(t or "").replace("™", " ").replace("®", " ")).split()
    w = [_ROMANOS.get(x, x) if i else x for i, x in enumerate(w)]
    return " ".join(x for x in w if x not in _RELLENO)


def juegos_que_tengo(d: dict | None = None) -> set:
    """Todo lo que ya tiene: jugado en Steam, instalado (Steam o PC), agregado a mano o ya esperando."""
    d = d or BA.cargar()
    nombres = [j.get("t") for j in (BA.juegos_steam().get("juegos") or [])]
    nombres += [j.get("t") for j in (BA.juegos_pc().get("juegos") or [])]
    nombres += list((d.get("steam_nombres") or {}).values())
    nombres += [x.get("t") for x in d.get("pc_manuales") or [] if isinstance(x, dict)]
    nombres += [x.get("t") for x in d.get("esperados") or [] if isinstance(x, dict)]
    try:
        base = BA.steam_dir()
        if base:
            nombres += list(BA._steam_nombres_instalados(base).values())
    except Exception:  # noqa: BLE001
        pass
    return {clave_juego(n) for n in nombres if n and clave_juego(n)}


def descubrir(forzar: bool = False) -> dict:
    d = BA.cargar()
    perfil = limpiar_perfil(d.get("perfil"))
    clave = json.dumps([[s.get("tmdb") for s in d["series"]], [e["igdb"] for e in d["esperados"]], perfil, d.get("ocultos")], sort_keys=True)
    with _LOCK:
        if not forzar and _DESC["k"] == clave and time.time() - _DESC["t"] < 6 * 3600:
            return _DESC["v"]
    claves = BA.claves()
    tengo_s = {s.get("tmdb") for s in d["series"] if s.get("tmdb")} | {_norm(s["t"]) for s in d["series"]}
    tengo_j = {e["igdb"] for e in d["esperados"]}
    ocultos = set(d.get("ocultos") or [])
    tengo_s |= {int(x[2:]) for x in ocultos if x.startswith("s:") and x[2:].isdigit()}
    tengo_j |= {int(x[2:]) for x in ocultos if x.startswith("j:") and x[2:].isdigit()}
    series, juegos, errores = [], [], []
    if claves.get("tmdb"):
        try:
            for s in [s for s in d["series"] if s.get("tmdb")][:5]:
                for x in (BA._tmdb(f"tv/{s['tmdb']}/recommendations").get("results") or [])[:6]:
                    if x.get("id") in tengo_s or _norm(x.get("name")) in tengo_s:
                        continue
                    tengo_s.add(x.get("id"))
                    series.append(_serie_tmdb(x, f"Porque ves {s['t']}"))
                    if len([y for y in series if y["why"].endswith(s["t"])]) >= 2:
                        break
            gen = [_TV[g] for g in perfil["ver"] if g in _TV]
            if len(series) < 4 and (gen or perfil["donde"]):
                q = {"sort_by": "popularity.desc", "watch_region": "CL", "vote_count.gte": "80"}
                if gen:
                    q["with_genres"] = "|".join(dict.fromkeys(gen))
                if "anime" in perfil["ver"]:
                    q["with_origin_country"] = "JP"
                prov = [_PROV[p] for p in perfil["donde"] if p in _PROV]
                if prov:
                    q["with_watch_providers"] = "|".join(prov)
                gusto = ", ".join(perfil["ver"][:2]) or "tus plataformas"
                for x in (BA._tmdb("discover/tv", q).get("results") or [])[:10]:
                    if x.get("id") in tengo_s or len(series) >= 6:
                        continue
                    tengo_s.add(x.get("id"))
                    series.append(_serie_tmdb(x, f"Te gusta {gusto}"))
        except Exception as exc:  # noqa: BLE001
            errores.append(f"TMDB: {str(exc)[:80]}")
    if claves.get("igdb"):
        try:
            jugados = list((BA.juegos_steam().get("juegos") or [])) + list((BA.juegos_pc().get("juegos") or []))
            jugados.sort(key=lambda j: j.get("ultima") or 0, reverse=True)
            nombres = juegos_que_tengo(d)
            for j in jugados[:3]:
                a = arte(j.get("t", ""))
                for p in (a.get("parecidos") or [])[:6]:
                    if p["igdb"] in tengo_j or clave_juego(p["t"]) in nombres:
                        continue
                    tengo_j.add(p["igdb"])
                    juegos.append({**p, "k": "j", "why": f"Porque juegas {j.get('t')}"})
                    if len([y for y in juegos if y["why"].endswith(str(j.get("t")))]) >= 2:
                        break
            gen = [g for k in perfil["jugar"] if k in _IGDB_GEN for g in _IGDB_GEN[k].split(",")]
            tem = [_IGDB_TEMA[k] for k in perfil["jugar"] if k in _IGDB_TEMA]
            filtro = " | ".join(x for x in ([f"genres = ({','.join(gen)})"] if gen else []) + ([f"themes = ({','.join(tem)})"] if tem else []))
            ahora = int(time.time())
            q = (f"fields name,url,cover.image_id,first_release_date,hypes; where first_release_date > {ahora} & hypes > 3"
                 + (f" & ({filtro})" if filtro else "") + "; sort hypes desc; limit 12;")
            gusto = ", ".join(perfil["jugar"][:2])
            for g in BA._igdb("games", q):
                if g.get("id") in tengo_j or clave_juego(g.get("name")) in nombres or len(juegos) >= 8:
                    continue
                tengo_j.add(g.get("id"))
                juegos.append({"igdb": g.get("id"), "t": g.get("name") or "", "img": (g.get("cover") or {}).get("image_id") or "",
                               "url": g.get("url") or "", "nota": 0, "k": "j", "pronto": True,
                               "f": time.strftime("%Y-%m-%d", time.gmtime(g["first_release_date"])) if g.get("first_release_date") else "",
                               "why": f"Sale pronto · {gusto}" if gusto else "Sale pronto"})
        except Exception as exc:  # noqa: BLE001
            errores.append(f"IGDB: {str(exc)[:80]}")
    mezcla = []
    for i in range(max(len(series), len(juegos))):
        mezcla += series[i:i + 1] + juegos[i:i + 1]
    v = {"ok": True, "res": mezcla[:12], "errores": errores, "claves": claves}
    with _LOCK:
        _DESC.update(k=clave, t=time.time(), v=v)
    return v


def _serie_tmdb(x: dict, why: str) -> dict:
    return {"tmdb": x.get("id"), "t": x.get("name") or x.get("original_name") or "", "img": x.get("poster_path") or "",
            "nota": round(x.get("vote_average") or 0, 1), "anio": (x.get("first_air_date") or "")[:4], "k": "s", "why": why,
            "resumen": (x.get("overview") or "")[:200]}


# ----------------------------------------------------------------------------- eventos generales para «Lo que viene»
_EV: dict = {"k": None, "t": 0.0, "v": None}


# ----------------------------------------------------------------------------- PuntoTicket (cartelera pública, 1 vez al día)
_MESES = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"])}
_MESES["setiembre"] = 9
_PT_MUSICA = ("rock", "pop", "metal", "punk", "jazz", "funk", "soul", "rap", "hip", "trap", "reggae", "cumbia", "salsa", "tango",
              "bolero", "balada", "ranchera", "vallenato", "folk", "electr", "techno", "urbano", "reggaet", "r&b", "concierto",
              "musica", "música", "clasica", "clásica", "sinfon", "hardcore", "deathcore", "indie", "k-pop", "j-rock", "romantico",
              "romántico", "regional mexicano", "bailable", "crossover", "latino", "festival", "fest", "nacional", "en vivo")


# subcategorías de eventos (las que la persona «sigue» salen en la línea de tiempo; el resto, en la cartelera)
SUBCATS = {
    "festival": ("Festivales", "c", r"festival|fest\b"),
    "rock": ("Rock y metal", "c", r"rock|metal|punk|hardcore|deathcore|grunge"),
    "urbano": ("Urbano", "c", r"urbano|reggaet|trap|rap\b|hip|r&b"),
    "electro": ("Electrónica", "c", r"electr|techno|house"),
    "latino": ("Latino", "c", r"latino|reggae|cumbia|salsa|bolero|ranchera|regional|vallenato|tango|folklore|bailable|nacional"),
    "jazz": ("Jazz y clásica", "c", r"jazz|cl[aá]sica|sinfon|crossover|soul|funk"),
    "pop": ("Pop", "c", r"pop|balada|rom[aá]ntico|indie|m[uú]sica|concierto|en vivo"),
    "humor": ("Humor", "v", r"humor|stand|comedia|podcast"),
    "teatro": ("Teatro y shows", "v", r"teatro|show|experiencia|exposici|charla|youtuber|fan meeting|especiales"),
    "familia": ("Familia", "v", r"infantil|familia|taller"),
    "deporte": ("Deportes", "v", r"deporte|f[uú]tbol|marciales|lucha|tenis"),
}
_SIGUE_DE_MUSICA = {"rock": "rock", "metal": "rock", "urbano": "urbano", "hip hop": "urbano", "electronica": "electro",
                    "latino": "latino", "jazz": "jazz", "bandas sonoras": "jazz", "pop": "pop", "indie": "pop", "kpop": "pop"}


def subcat(cat: str) -> str:
    c = (cat or "").lower()
    return next((k for k, (_, _, rx) in SUBCATS.items() if re.search(rx, c)), "otros")


def sigue_eventos(perfil: dict) -> list:
    """Subcategorías que van a la línea de tiempo: las elegidas o, si nunca eligió, las de su música + festivales."""
    if perfil.get("eventos") is not None:
        return perfil["eventos"]
    return list(dict.fromkeys(["festival"] + [_SIGUE_DE_MUSICA[m] for m in perfil.get("musica") or [] if m in _SIGUE_DE_MUSICA]))


def _pt_fecha(txt: str) -> str:
    m = re.match(r"\s*(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", txt.lower())
    if not m or m.group(2) not in _MESES:
        return ""
    try:
        return datetime.date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1))).isoformat()
    except ValueError:   # «31 de febrero»
        return ""


def leer_puntoticket(html_txt: str) -> list:
    """Cada <article> de la cartelera: nombre, recinto, categoría, fecha (o rango) y enlace."""
    out, vistos = [], set()
    for a in re.findall(r"<article\b.*?</article>", html_txt, re.S):
        h = re.search(r'<a\s[^>]*href="([^"]+)"', a)
        t = re.search(r"<h3[^>]*>(.*?)</h3>", a, re.S)
        f = re.search(r'class="fecha"[^>]*>(.*?)</p>', a, re.S)
        if not (h and t and f):
            continue
        nombre = _texto(html.unescape(re.sub(r"<[^>]+>", " ", t.group(1))), 120)
        partes = [_texto(html.unescape(re.sub(r"<[^>]+>", " ", x)), 120) for x in f.group(1).split(" - ")]
        ini = _pt_fecha(partes[0]) if partes else ""
        fin = _pt_fecha(partes[-1]) if len(partes) > 1 else ""
        if not nombre or not ini:
            continue
        d = re.search(r'class="descripcion"[^>]*>(.*?)</p>', a, re.S)
        lugar, cat = "", ""
        if d:
            lg = re.search(r"<strong>(.*?)</strong>", d.group(1), re.S)
            lugar = _texto(html.unescape(re.sub(r"<[^>]+>", " ", lg.group(1))), 80) if lg else ""
            resto = re.sub(r"<strong>.*?</strong>", "", d.group(1), flags=re.S)
            cat = _texto(html.unescape(re.sub(r"<[^>]+>", " ", resto)).strip().lstrip("/").strip(), 50)
        im = re.search(r'src="(https://static\.ptocdn\.net/[^"]+_calugalistado\.(?:jpg|png|webp))"', a)
        u = urllib.parse.urljoin("https://www.puntoticket.com/", html.unescape(h.group(1)))
        if not u.startswith("https://www.puntoticket.com/") or (u, ini) in vistos:
            continue
        vistos.add((u, ini))
        out.append({"t": nombre, "f": ini, "fin": fin if fin and fin != ini else "", "lugar": lugar, "cat": cat, "u": u, "img": im.group(1) if im else ""})
    return out


_PT_LOCK = threading.Lock()


def puntoticket(forzar: bool = False) -> dict:
    """La cartelera guardada; se vuelve a leer como mucho una vez al día. Si falla, sigue con lo último guardado
    (y si hoy todavía no hubo una lectura buena, reintenta a las 6 horas, por si el PC partió sin internet)."""
    with _PT_LOCK:
        return _puntoticket(forzar)


def _puntoticket(forzar: bool) -> dict:
    try:
        c = json.loads(PT_CACHE.read_text(encoding="utf-8"))
        c = c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        c = {}
    if not PUNTOTICKET:
        return {"ok": False, "ev": [], "t": 0, "error": "apagado"}
    intento = float(c.get("intento") or 0)
    espera = 24 * 3600 if time.time() - float(c.get("t") or 0) < 24 * 3600 else 6 * 3600
    if forzar or time.time() - intento > espera:
        c["intento"] = time.time()
        try:
            req = urllib.request.Request(PT_URL, headers={"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9"})
            with urllib.request.urlopen(req, timeout=10) as r:
                ev = leer_puntoticket(r.read(4_000_000).decode("utf-8", "replace"))
            if ev:
                c.update(ev=ev, t=time.time(), error="")
            else:
                c["error"] = "la página cambió: no encontré eventos"
        except Exception as exc:  # noqa: BLE001  (sin red, bloqueado, etc.: sigue con lo de ayer)
            c["error"] = f"{type(exc).__name__}"
        try:
            PT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            PT_CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    ev = c.get("ev") if isinstance(c.get("ev"), list) else []
    return {"ok": bool(ev), "ev": ev, "t": c.get("t") or 0, "error": c.get("error") or ""}


def _eventos_pt(perfil: dict) -> list:
    hoy = time.strftime("%Y-%m-%d")
    gustos = {_norm(a) for a in perfil.get("artistas") or []} | {_norm(x.get("a")) for x in sonado()[-400:] if x.get("a")}
    gustos = {g for g in gustos if len(g) >= 3}
    out = []
    for e in puntoticket()["ev"]:
        fin = e.get("fin") or ""
        if (fin or e["f"]) < hoy:
            continue
        cat = (e.get("cat") or "").lower()
        sub = subcat(cat)
        musica = SUBCATS[sub][1] == "c" if sub in SUBCATS else any(w in cat for w in _PT_MUSICA)
        n = " " + _norm(e["t"]) + " "
        tuyo = next((g for g in gustos if f" {g} " in n), "")
        s = " · ".join(x for x in [e.get("lugar"), e.get("cat"), f"hasta el {int(fin[8:])}/{int(fin[5:7])}" if fin else ""] if x)
        out.append({"id": "pt:" + e["u"].rsplit("/", 1)[-1] + ":" + e["f"], "t": e["t"], "f": max(e["f"], hoy) if fin else e["f"],
                    "s": ("★ " if tuyo else "") + s, "k": "c" if musica else "v", "auto": True, "u": e["u"], "pt": True, "sub": sub,
                    "tuyo": bool(tuyo)})
    return out


def eventos() -> dict:
    d = BA.cargar()
    perfil = limpiar_perfil(d.get("perfil"))
    clave = json.dumps(perfil, sort_keys=True)
    with _LOCK:
        if _EV["k"] == clave and time.time() - _EV["t"] < 6 * 3600:
            return _EV["v"]
    claves = BA.claves()
    ev, errores = [], []
    if claves.get("igdb"):
        try:
            ahora = int(time.time())
            for e in BA._igdb("events", f"fields name,start_time,live_stream_url,description; where start_time > {ahora}; sort start_time asc; limit 12;"):
                if not e.get("start_time"):
                    continue
                ev.append({"id": f"igdbev:{e.get('id')}", "t": BA._txt(e.get("name"), 120), "f": time.strftime("%Y-%m-%d", time.localtime(e["start_time"])),
                           "s": "Evento de videojuegos" + (" · en vivo" if e.get("live_stream_url") else ""), "k": "v", "auto": True,
                           "u": e.get("live_stream_url") or ""})
        except Exception as exc:  # noqa: BLE001
            errores.append(f"IGDB: {str(exc)[:80]}")
    if claves.get("tmdb"):
        try:
            gen = [_PELI[g] for g in perfil["ver"] if g in _PELI]
            hoy = time.strftime("%Y-%m-%d")
            q = {"region": "CL", "sort_by": "popularity.desc", "primary_release_date.gte": hoy, "with_release_type": "2|3"}
            if gen:
                q["with_genres"] = "|".join(dict.fromkeys(gen))
            for x in (BA._tmdb("discover/movie", q).get("results") or [])[:8]:
                if not x.get("release_date") or x["release_date"] < hoy:
                    continue
                ev.append({"id": f"peli:{x.get('id')}", "t": x.get("title") or "", "f": x["release_date"], "s": "En cines",
                           "k": "p", "auto": True, "img": x.get("poster_path") or "", "u": f"https://www.themoviedb.org/movie/{x.get('id')}"})
        except Exception as exc:  # noqa: BLE001
            errores.append(f"TMDB: {str(exc)[:80]}")
    pt = {"activo": PUNTOTICKET and perfil["pt"], "n": 0, "t": 0}
    if pt["activo"]:
        try:
            lista = _eventos_pt(perfil)
            ev += lista
            pt.update(n=len(lista), t=puntoticket()["t"])
        except Exception as exc:  # noqa: BLE001
            errores.append(f"PuntoTicket: {str(exc)[:80]}")
    v = {"ok": True, "ev": ev, "errores": errores, "pt": pt, "sigue": sigue_eventos(perfil),
         "subcats": {k: [n, kk] for k, (n, kk, _) in SUBCATS.items()}}
    with _LOCK:
        _EV.update(k=clave, t=time.time(), v=v)
    return v

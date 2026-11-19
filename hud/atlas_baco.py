"""Baco (entretenimiento): datos y acciones de apps/baco/baco.html, servidos por hud_server en /acceso/baco/api/...

18-11-2026. Todo local y sin claves:
- Lo que la persona anota (series con su episodio, playlists, enlaces, fechas que espera, favorito, fijados) va en
  ~/.atlas/baco.json.
- Juegos: los archivos de Steam del PC (localconfig.vdf: horas totales, de las últimas 2 semanas y última vez jugado).
- Música: lo que está sonando en Windows (cualquier app que se muestre en los controles multimedia), con PowerShell.
- Espectro: el audio que sale por los parlantes (atlas_baco_audio.py).
- Juegos fuera de Steam (Epic, Riot, HoYoPlay, .exe agregados a mano) y su tiempo, mirando los procesos abiertos
  (atlas_baco_juegos.py; el hilo lo arranca hud_server al iniciar con vigilar_juegos()).
- Series (TMDB): buscar, temporadas/episodios y próximos estrenos. El token se lee del Administrador de credenciales
  de Windows (entrada Atlas-Baco-TMDB, la guarda Guardar-claves-Baco.cmd); nunca se escribe en archivos ni en el log.
- Juegos esperados (IGDB, cualquier plataforma): buscar, «Esperar» y fechas de salida por plataforma. Client ID y
  secreto de Twitch en el Administrador de credenciales (Atlas-Baco-IGDB); el token de acceso solo vive en memoria.
- 19-11-2026 (atlas_baco_mas.py): perfil e intereses, portada de la canción, lo que sonó, playlists con canciones,
  noticias con selector de temas, «Para ti» y eventos generales en «Lo que viene».
Pendiente: conciertos automáticos y crear las playlists en la cuenta de YouTube Music.

http(método, ruta, query, cuerpo) -> (código, bytes, tipo), igual que atlas_historia.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

ARCHIVO = Path(os.environ.get("BACO_ARCHIVO") or (Path.home() / ".atlas" / "baco.json"))
_LOCK = threading.RLock()

PLATAFORMAS = {
    "netflix": {"n": "Netflix", "c": "#E50914", "u": "https://www.netflix.com"},
    "disney": {"n": "Disney+", "c": "#3D7BFF", "u": "https://www.disneyplus.com"},
    "max": {"n": "Max", "c": "#7A5CFF", "u": "https://play.max.com"},
    "prime": {"n": "Prime Video", "c": "#1FA7E1", "u": "https://www.primevideo.com"},
    "apple": {"n": "Apple TV+", "c": "#C9D3DD", "u": "https://tv.apple.com"},
    "crunchy": {"n": "Crunchyroll", "c": "#FF8A2A", "u": "https://www.crunchyroll.com"},
    "paramount": {"n": "Paramount+", "c": "#2E6BFF", "u": "https://www.paramountplus.com"},
    "youtube": {"n": "YouTube", "c": "#FF3D3D", "u": "https://www.youtube.com"},
    "spotify": {"n": "Spotify", "c": "#1ED760", "u": "https://open.spotify.com"},
    "ytm": {"n": "YouTube Music", "c": "#FF3D3D", "u": "https://music.youtube.com"},
    "steam": {"n": "Steam", "c": "#66C0F4", "u": "steam://open/games"},
    "otra": {"n": "Otra", "c": "#8FA9B8", "u": ""},
}
ENLACES_INICIALES = [
    {"t": "YouTube", "u": "https://www.youtube.com"},
    {"t": "Netflix", "u": "https://www.netflix.com"},
    {"t": "Twitch", "u": "https://www.twitch.tv"},
    {"t": "Disney+", "u": "https://www.disneyplus.com"},
    {"t": "Crunchyroll", "u": "https://www.crunchyroll.com"},
    {"t": "Spotify", "u": "https://open.spotify.com"},
]
ESQUEMAS = ("http://", "https://", "steam://", "spotify:")
PORTADAS = ARCHIVO.parent / "baco_portadas"   # portadas elegidas para las playlists (19-11-2026)


# ----------------------------------------------------------------------------- estado guardado
def _id() -> str:
    return uuid.uuid4().hex[:10]


def _vacio() -> dict:
    return {"version": 1, "series": [], "musica": [], "esperas": [], "esperados": [], "pc_manuales": [], "favorito": "", "fijados": [], "pestana": "serie",
            "enlaces": [{"id": _id(), **e} for e in ENLACES_INICIALES], "steam_nombres": {}, "perfil": {}, "noticias": {},
            "ocultos": [], "favoritos": {"serie": "", "juego": "", "musica": ""}}


def cargar() -> dict:
    with _LOCK:
        d = _vacio()
        try:
            guardado = json.loads(ARCHIVO.read_text(encoding="utf-8"))
            if isinstance(guardado, dict):
                d.update({k: v for k, v in guardado.items() if k in d})
        except (OSError, ValueError):
            pass
        return d


def _escribir(d: dict) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ARCHIVO)


def _yt(v) -> str:
    """Enlace de música dentro de una playlist de Baco: YouTube / YouTube Music o Spotify (canción, playlist o álbum)."""
    u = _url(v)
    return u if re.match(r"https://(music\.|www\.|m\.)?youtube\.com/|https://youtu\.be/|https://open\.spotify\.com/|spotify:(track|playlist|album|search):", u) else ""


def _txt(v, n: int = 160) -> str:
    return str(v if v is not None else "").strip()[:n]


def _url(v) -> str:
    u = _txt(v, 600)
    return u if u.lower().startswith(ESQUEMAS) else ""


def _ent(v, lo: int = 0, hi: int = 9999, defecto: int = 0) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return defecto


def _img_pl(v) -> str:
    """Portada de una playlist: «subida:<marca>» (archivo en baco_portadas) o un enlace https a una imagen."""
    s = _txt(v, 600)
    if re.fullmatch(r"subida:\d{1,15}", s):
        return s
    return s if re.fullmatch(r"https://[^\s\"'<>]+", s) else ""


def _tipo_img(b: bytes) -> str:
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _portada_archivo(pid) -> Path:
    pid = re.sub(r"[^A-Za-z0-9_-]", "_", _txt(pid, 40))
    if not pid.strip("_"):
        raise ValueError("id")
    return PORTADAS / f"{pid}.img"


def portada_playlist(c: dict) -> dict:
    """Guarda la portada de una playlist: la carátula de una de sus canciones (t, a), una imagen subida (datos) o la quita."""
    f = _portada_archivo(c.get("id"))
    if c.get("quitar"):
        f.unlink(missing_ok=True)
        return {"ok": True, "img": ""}
    if _txt(c.get("t")):
        import atlas_baco_mas as MAS

        try:
            datos = MAS.portada_catalogo(_txt(c.get("t"), 120), _txt(c.get("a"), 120))
        except Exception:  # noqa: BLE001
            datos = b""
        if not datos:
            return {"ok": False, "error": "No encontré la portada de esa canción."}
    else:
        m = re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)", str(c.get("datos") or "")[:900_000])
        if not m:
            raise ValueError("imagen")
        datos = base64.b64decode(m.group(2))
    if not _tipo_img(datos) or len(datos) > 650_000:
        raise ValueError("imagen")
    PORTADAS.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(datos)
    os.replace(tmp, f)
    return {"ok": True, "img": f"subida:{int(time.time() * 1000)}"}


def _limpiar(clave: str, lista) -> list:
    """Valida lo que manda la página: listas acotadas, textos cortos, enlaces con esquema permitido."""
    if not isinstance(lista, list):
        raise ValueError(clave)
    out = []
    for x in lista[:200]:
        if not isinstance(x, dict) or not _txt(x.get("t")):
            continue
        base = {"id": re.sub(r"[^A-Za-z0-9:_-]", "", _txt(x.get("id"), 40)) or _id(), "t": _txt(x.get("t"), 120)}
        if clave == "series":
            base.update({"p": x.get("p") if x.get("p") in PLATAFORMAS else "otra", "u": _url(x.get("u")),
                         "T": _ent(x.get("T"), 1, 99, 1), "E": _ent(x.get("E"), 1, 9999, 1), "tot": _ent(x.get("tot"), 0, 9999, 0),
                         "tmdb": _ent(x.get("tmdb"), 0, 10**9, 0),
                         "img": _txt(x.get("img"), 80) if re.fullmatch(r"/[A-Za-z0-9_-]+\.(jpg|png)", _txt(x.get("img"), 80)) else ""})
        elif clave == "musica":
            pistas = [{"t": _txt(p.get("t"), 120), "a": _txt(p.get("a"), 120), **({"u": _yt(p.get("u"))} if _yt(p.get("u")) else {})}
                      for p in (x.get("pistas") if isinstance(x.get("pistas"), list) else [])[:300] if isinstance(p, dict) and _txt(p.get("t"))]
            animo = [_txt(a, 30) for a in (x.get("animo") if isinstance(x.get("animo"), list) else [])[:8] if _txt(a, 30)]
            base.update({"u": _url(x.get("u")), "s": _txt(x.get("s"), 120), "pistas": pistas, "animo": animo})
            if _img_pl(x.get("img")):
                base["img"] = _img_pl(x.get("img"))
        elif clave == "enlaces":
            base.update({"u": _url(x.get("u"))})
            if not base["u"]:
                continue
        elif clave == "esperados":
            base.update({"igdb": _ent(x.get("igdb"), 0, 10**9, 0),
                         "img": _txt(x.get("img"), 40) if re.fullmatch(r"[a-z0-9]+", _txt(x.get("img"), 40)) else ""})
            if not base["igdb"]:
                continue
            base["id"] = f"igdb:{base['igdb']}"
        elif clave == "pc_manuales":
            exe = _txt(x.get("exe"), 400)
            if not re.fullmatch(r"[A-Za-z]:\\[^<>\"|?*\x00-\x1f]+\.exe", exe, flags=re.I):
                continue
            base.update({"exe": exe, "id": "pc:m-" + re.sub(r"[^a-z0-9]+", "-", base["t"].lower()).strip("-")[:30]})
        elif clave == "esperas":
            f = _txt(x.get("f"), 10)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
                continue
            base.update({"f": f, "k": x.get("k") if x.get("k") in ("c", "s", "j", "p", "v") else "s", "s": _txt(x.get("s"), 120),
                         "u": _url(x.get("u"))})
        out.append(base)
    return out


def guardar(cambios: dict) -> dict:
    d = cargar()
    for clave in ("series", "musica", "enlaces", "esperas", "esperados", "pc_manuales"):
        if clave in cambios:
            d[clave] = _limpiar(clave, cambios[clave]) if clave != "musica" else _con_enlaces(_limpiar(clave, cambios[clave]), d.get("musica"))
    if "favoritos" in cambios and isinstance(cambios["favoritos"], dict):   # uno por ranura; el escenario se turna
        d["favoritos"] = {k: re.sub(r"[^A-Za-z0-9:_-]", "", _txt(cambios["favoritos"].get(k), 40)) for k in ("serie", "juego", "musica")}
    if "favorito" in cambios:
        d["favorito"] = re.sub(r"[^A-Za-z0-9:_-]", "", _txt(cambios["favorito"], 40))
    if "fijados" in cambios and isinstance(cambios["fijados"], list):
        d["fijados"] = [re.sub(r"[^A-Za-z0-9:_-]", "", _txt(x, 40)) for x in cambios["fijados"][:100] if _txt(x)]
    if "ocultos" in cambios and isinstance(cambios["ocultos"], list):   # recomendaciones que ya tiene o no le interesan
        d["ocultos"] = list(dict.fromkeys(re.sub(r"[^a-z0-9:]", "", _txt(x, 30)) for x in cambios["ocultos"][-300:] if _txt(x)))
    if "perfil" in cambios or "noticias" in cambios:
        import atlas_baco_mas as MAS

        if "perfil" in cambios:
            d["perfil"] = MAS.limpiar_perfil(cambios["perfil"])
        if "noticias" in cambios:
            d["noticias"] = MAS.limpiar_noticias(cambios["noticias"])
    if cambios.get("pestana") in ("serie", "juego"):
        d["pestana"] = cambios["pestana"]
    with _LOCK:
        _escribir(d)
    return d


def _con_enlaces(nuevas: list, viejas: list) -> list:
    """Las canciones que manda la página sin enlace conservan el enlace exacto que ya tenían guardado (la página
    puede traer una copia de antes de que Baco lo anotara)."""
    exactos = {}
    for x in viejas or []:
        for q in x.get("pistas") or []:
            if q.get("u"):
                exactos.setdefault((_nrm(q.get("t")), _nrm(q.get("a"))), q["u"])
    for x in nuevas:
        for q in x.get("pistas") or []:
            if not q.get("u"):
                u = exactos.get((_nrm(q.get("t")), _nrm(q.get("a"))))
                if u:
                    q["u"] = u
    return nuevas


def poner_u_pista(t: str, a: str, u: str) -> int:
    """19-11-2026: anota el video exacto en las canciones guardadas sin enlace (las de «Lo que sonó» o «Guardar esta
    canción» cuando no se alcanzó a saber el video). Así la próxima vez suena ESE video y no se busca por nombre."""
    u = _yt(u)
    if not u or not _txt(t):
        return 0
    k = (_nrm(t), _nrm(a))
    n = 0
    with _LOCK:
        d = cargar()
        for x in d.get("musica") or []:
            for q in x.get("pistas") or []:
                if not q.get("u") and (_nrm(q.get("t")), _nrm(q.get("a"))) == k:
                    q["u"] = u
                    n += 1
        if n:
            _escribir(d)
    if n:
        _bitacora(f"guarda el enlace exacto de {t!r}: {u} ({n})")
    return n


# ----------------------------------------------------------------------------- Steam
def vdf(texto: str) -> dict:
    """Formato KeyValues de Valve ("clave" "valor" y bloques { }). Claves en minúscula para buscar sin importar mayúsculas."""
    toks = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', texto)
    raiz: dict = {}
    pila = [raiz]
    clave = None
    for s, llave in toks:
        if llave == "{":
            nuevo: dict = {}
            if clave is not None:
                pila[-1][clave.lower()] = nuevo
            pila.append(nuevo)
            clave = None
        elif llave == "}":
            if len(pila) > 1:
                pila.pop()
            clave = None
        elif clave is None:
            clave = s
        else:
            pila[-1][clave.lower()] = s.replace('\\"', '"').replace("\\\\", "\\")
            clave = None
    return raiz


def steam_dir() -> Path | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            p = Path(winreg.QueryValueEx(k, "SteamPath")[0])
            if p.exists():
                return p
    except OSError:
        pass
    for p in (Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")):
        if p.exists():
            return p
    return None


_STEAM_CACHE: dict = {"t": 0.0, "v": None}


def _steam_nombres_instalados(base: Path) -> dict:
    nombres = {}
    libs = [base]
    try:
        lf = vdf((base / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
        for v in (lf.get("libraryfolders") or {}).values():
            if isinstance(v, dict) and v.get("path"):
                libs.append(Path(v["path"]))
    except OSError:
        pass
    for lib in dict.fromkeys(libs):
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                st = vdf(acf.read_text(encoding="utf-8", errors="replace")).get("appstate") or {}
                if st.get("appid") and st.get("name"):
                    nombres[str(st["appid"])] = st["name"]
            except OSError:
                continue
    return nombres


def _steam_nombre_tienda(appid: str) -> str:
    """Nombre de un juego no instalado, desde la tienda de Steam (sin clave). Se guarda para no volver a pedirlo."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"https://store.steampowered.com/api/appdetails?appids={int(appid)}&filters=basic",
                                    timeout=4) as r:
            j = json.loads(r.read().decode("utf-8"))
        return _txt(((j.get(str(appid)) or {}).get("data") or {}).get("name"), 120)
    except Exception:  # noqa: BLE001
        return ""


NO_JUEGOS = {"480", "228980", "250820", "1070560", "1391110", "1628350", "1493710", "431960"}  # Spacewar (app de prueba), redistribuibles, SteamVR, runtimes, Wallpaper Engine


def juegos_steam(forzar: bool = False) -> dict:
    """{"ok", "juegos": [{id, t, appid, h, h2, ultima, u}], "error"} ordenados por la última vez jugado."""
    if not forzar and _STEAM_CACHE["v"] is not None and time.time() - _STEAM_CACHE["t"] < 60:
        return _STEAM_CACHE["v"]
    base = steam_dir()
    if not base:
        res = {"ok": False, "juegos": [], "error": "No encontré Steam en este PC."}
    else:
        configs = sorted((base / "userdata").glob("*/config/localconfig.vdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not configs:
            res = {"ok": False, "juegos": [], "error": "Steam no tiene un usuario con sesión iniciada."}
        else:
            cfg = vdf(configs[0].read_text(encoding="utf-8", errors="replace"))
            nodo = cfg.get("userlocalconfigstore") or {}
            for k in ("software", "valve", "steam", "apps"):
                nodo = nodo.get(k) or {} if isinstance(nodo, dict) else {}
            nombres = _steam_nombres_instalados(base)
            guardado = cargar()
            cache = dict(guardado.get("steam_nombres") or {})
            pedidos = 0
            juegos = []
            for appid, v in nodo.items():
                if not isinstance(v, dict) or not appid.isdigit() or appid in NO_JUEGOS:
                    continue
                minutos = _ent(v.get("playtime"), 0, 10**7)
                if minutos <= 0:
                    continue
                juegos.append({"id": f"steam:{appid}", "appid": appid, "h": round(minutos / 60, 1),
                               "h2": round(_ent(v.get("playtime2wks"), 0, 10**6) / 60, 1),
                               "ultima": _ent(v.get("lastplayed"), 0, 2**40), "u": f"steam://rungameid/{appid}"})
            juegos.sort(key=lambda j: j["ultima"], reverse=True)
            juegos = juegos[:20]
            for j in juegos:
                n = nombres.get(j["appid"]) or cache.get(j["appid"])
                if not n and pedidos < 6:
                    pedidos += 1
                    n = _steam_nombre_tienda(j["appid"])
                    if n:
                        cache[j["appid"]] = n
                j["t"] = n or f"Juego {j['appid']}"
            if cache != (guardado.get("steam_nombres") or {}):
                d = cargar()
                d["steam_nombres"] = cache
                with _LOCK:
                    _escribir(d)
            res = {"ok": True, "juegos": juegos}
    _STEAM_CACHE.update(t=time.time(), v=res)
    return res


# ----------------------------------------------------------------------------- abrir
def _firefox() -> str:
    for p in (os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
              os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe")):
        if os.path.isfile(p):
            return p
    return ""


# YouTube Music ya abierto: en vez de abrir otra pestaña (y otra música encima), se lleva esa ventana al frente y se
# escribe el enlace en su barra de direcciones. Solo si la ventana de verdad quedó al frente; si no, se abre como siempre.
_PS_YTM = r"""
$ErrorActionPreference = 'Stop'
Add-Type @'
using System; using System.Runtime.InteropServices; using System.Text;
public class BacoVentanas {
  public delegate bool Cada(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Cada f, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
$navegadores = @('msedge', 'firefox', 'chrome', 'brave', 'opera', 'vivaldi')
$script:hallada = [IntPtr]::Zero
$cb = [BacoVentanas+Cada]{ param($h, $l)
  if (-not [BacoVentanas]::IsWindowVisible($h)) { return $true }
  $sb = New-Object Text.StringBuilder 512; [void][BacoVentanas]::GetWindowText($h, $sb, 512)
  if ($sb.ToString() -notmatch 'YouTube Music') { return $true }
  $procId = 0; [void][BacoVentanas]::GetWindowThreadProcessId($h, [ref]$procId)
  try { $n = (Get-Process -Id $procId).ProcessName.ToLower() } catch { return $true }
  if ($navegadores -contains $n) { $script:hallada = $h; return $false }
  return $true }
[void][BacoVentanas]::EnumWindows($cb, [IntPtr]::Zero)
$h = $script:hallada
if ($h -eq [IntPtr]::Zero) { 'NO'; exit }
if ([BacoVentanas]::IsIconic($h)) { [void][BacoVentanas]::ShowWindow($h, 9) }
$sh = New-Object -ComObject WScript.Shell
$sh.SendKeys('%')
[void][BacoVentanas]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 200
if ([BacoVentanas]::GetForegroundWindow() -ne $h) { 'NO'; exit }
$sh.SendKeys('^l'); Start-Sleep -Milliseconds 120
if ([BacoVentanas]::GetForegroundWindow() -ne $h) { 'NO'; exit }
$sh.SendKeys('__URL__'); Start-Sleep -Milliseconds 60
$sh.SendKeys('{ENTER}')
'OK'
"""


def _sendkeys(t: str) -> str:
    return "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in t)


def abrir_en_ytm(u: str) -> bool:
    """True si el enlace quedó en la ventana de YouTube Music que ya estaba abierta."""
    if os.name != "nt" or urllib.parse.urlsplit(u).hostname != "music.youtube.com":
        return False
    if not re.fullmatch(r"https://music\.youtube\.com/[A-Za-z0-9/?=&%._~+-]*", u):   # nada raro para teclear
        return False
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            _PS_YTM.replace("__URL__", _sendkeys(u).replace("'", "''"))],
                           capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip().endswith("OK")
    except Exception:  # noqa: BLE001
        return False


def _url_ytm_reproducir(u: str) -> str:
    """Un enlace de YouTube / YouTube Music que de verdad empiece a sonar: la página de una playlist no suena sola,
    «watch?list=…» sí (parte por la primera canción)."""
    p = urllib.parse.urlsplit(u)
    q = urllib.parse.parse_qs(p.query)
    if p.hostname == "youtu.be":
        return f"https://music.youtube.com/watch?v={p.path.strip('/')}"
    if "v" in q:
        return "https://music.youtube.com/watch?" + urllib.parse.urlencode({k: q[k][0] for k in ("v", "list") if k in q})
    if "list" in q:
        return "https://music.youtube.com/watch?" + urllib.parse.urlencode({"list": q["list"][0]})
    return u


# ----------------------------------------------------------------------------- ventana de música por CDP (19-11-2026)
# La ventana de música de Atlas (Edge --app, perfil music-profile) abre el protocolo de depuración solo en 127.0.0.1:9223.
# Baco la maneja directo, sin librerías: cambia de canción con Page.navigate (la ventana no se cierra) y lee el <video>
# (qué id suena, en qué segundo va, si hay un aviso) para saber cuándo terminó cada canción de la cola.
_CDP_PORT = 9223


def _cdp_paginas(timeout: float = 2.0) -> list:
    import urllib.request

    with urllib.request.urlopen(f"http://127.0.0.1:{_CDP_PORT}/json", timeout=timeout) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def _musica_pagina():
    """La pestaña de la ventana de música: la de YouTube Music, o si no (inicio de sesión, aviso de cookies…) la única que haya."""
    ps = [t for t in _cdp_paginas() if not str(t.get("url", "")).startswith(("devtools:", "edge:", "chrome-extension:"))]
    return next((t for t in ps if "music.youtube.com" in t.get("url", "")), None) or (ps[0] if len(ps) == 1 else None)


def _musica_hay_cdp() -> bool:
    try:
        return _musica_pagina() is not None
    except Exception:  # noqa: BLE001
        return False


def _ws_llamar(ws_url: str, llamadas: list, timeout: float = 6.0) -> dict:
    """Cliente WebSocket mínimo (RFC 6455, solo 127.0.0.1): manda [(método, params), …] y devuelve {i: result} de cada uno."""
    import base64
    import socket
    import struct

    p = urllib.parse.urlsplit(ws_url)
    if p.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError("CDP fuera del PC")
    s = socket.create_connection((p.hostname, p.port or 80), timeout=timeout)
    try:
        clave = base64.b64encode(os.urandom(16)).decode()
        ruta = p.path + ("?" + p.query if p.query else "")
        s.sendall((f"GET {ruta} HTTP/1.1\r\nHost: {p.hostname}:{p.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {clave}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = bytearray()
        while b"\r\n\r\n" not in buf:
            ch = s.recv(4096)
            if not ch:
                raise RuntimeError("CDP: se cortó")
            buf.extend(ch)
        i = buf.index(b"\r\n\r\n")
        if b" 101" not in bytes(buf[:i]).split(b"\r\n")[0]:
            raise RuntimeError("CDP: no aceptó el websocket")
        del buf[:i + 4]

        def leer(n: int) -> bytes:
            while len(buf) < n:
                ch = s.recv(65536)
                if not ch:
                    raise RuntimeError("CDP: se cortó")
                buf.extend(ch)
            out = bytes(buf[:n])
            del buf[:n]
            return out

        def mensaje() -> str:
            partes = b""
            while True:
                b0, b1 = leer(2)
                op, n = b0 & 0x0F, b1 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", leer(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", leer(8))[0]
                m = leer(4) if b1 & 0x80 else b""
                datos = leer(n)
                if m:
                    datos = bytes(x ^ m[k % 4] for k, x in enumerate(datos))
                if op == 8:
                    raise RuntimeError("CDP: cerró la conexión")
                if op in (9, 10):
                    continue
                partes += datos
                if b0 & 0x80:
                    return partes.decode("utf-8", "replace")

        for k, (metodo, params) in enumerate(llamadas, 1):
            d = json.dumps({"id": k, "method": metodo, "params": params or {}}).encode("utf-8")
            m = os.urandom(4)
            n = len(d)
            cab = bytes([0x81, 0x80 | n]) if n < 126 else (bytes([0x81, 0xFE]) + struct.pack(">H", n) if n < 65536
                                                            else bytes([0x81, 0xFF]) + struct.pack(">Q", n))
            s.sendall(cab + m + bytes(x ^ m[j % 4] for j, x in enumerate(d)))
        res: dict = {}
        fin = time.time() + timeout
        while len(res) < len(llamadas) and time.time() < fin:
            msg = json.loads(mensaje())
            if isinstance(msg.get("id"), int):
                res[msg["id"]] = msg.get("result") or {"error": msg.get("error")}
        return res
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def _musica_js(js: str, foco: bool = False, timeout: float = 6.0):
    """Evalúa JS en la ventana de música y devuelve el valor (o lanza error si no hay ventana)."""
    pg = _musica_pagina()
    if pg is None:
        raise RuntimeError("no hay ventana de música")
    pre = [("Emulation.setFocusEmulationEnabled", {"enabled": True}), ("Page.setWebLifecycleState", {"state": "active"})] if foco else []
    r = _ws_llamar(pg["webSocketDebuggerUrl"], pre + [("Runtime.evaluate", {"expression": js, "awaitPromise": True, "userGesture": foco,
                                                                            "returnByValue": True})], timeout)
    ev = r.get(len(pre) + 1) or {}
    if ev.get("exceptionDetails"):
        raise RuntimeError(str(ev["exceptionDetails"].get("text", "error de JS")))
    return (ev.get("result") or {}).get("value")


def _musica_ir(url: str) -> bool:
    """Cambia de canción en la ventana de música que ya está abierta. False si no hay ventana (o no respondió)."""
    try:
        pg = _musica_pagina()
        if pg is None:
            return False
        r = _ws_llamar(pg["webSocketDebuggerUrl"], [("Runtime.evaluate", {"expression": _JS_SIN_AVISO, "returnByValue": True}),
                                                    ("Page.navigate", {"url": url})], 5)
        return bool(r.get(2)) and not (r[2].get("errorText") or r[2].get("error"))
    except Exception:  # noqa: BLE001
        return False


# Estado del <video> de YouTube Music. Si quedó en pausa sin que nadie la pausara (recién cargada, o el aviso
# «¿Sigues ahí?»), se le da play. ad: hay un aviso sonando (no cuenta como la canción).
# Sin el aviso «¿Salir de la aplicación?» al cerrar la ventana o al cambiar de canción: YouTube Music lo pide cuando
# hay una cola suya, y Edge lo muestra porque Baco le dio play. Se cortan sus «beforeunload» antes de que corran.
_JS_SIN_AVISO = r"""(()=>{if(!window.__bacoSinAviso){window.__bacoSinAviso=1;
try{const P=BeforeUnloadEvent.prototype;Object.defineProperty(P,'preventDefault',{value:function(){},configurable:true});
Object.defineProperty(P,'returnValue',{get(){return ''},set(v){},configurable:true});}catch(e){}
try{window.onbeforeunload=null;Object.defineProperty(window,'onbeforeunload',{get(){return null},set(v){},configurable:true});}catch(e){}}
return true})();"""
_JS_ESTADO = _JS_SIN_AVISO + r"""(async()=>{
const q=new URLSearchParams(location.search), v=document.querySelector('video'), mp=document.querySelector('#movie_player');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const ad=!!(mp&&mp.classList&&(mp.classList.contains('ad-showing')||mp.classList.contains('ad-interrupting')));
const sigue=document.querySelector('ytmusic-you-there-renderer');
if(sigue&&sigue.offsetParent!==null){const b=sigue.querySelector('button,tp-yt-paper-button,yt-button-renderer');if(b)b.click();}
if(__PLAY__&&v&&v.paused&&!v.ended){
 try{if(mp&&mp.playVideo)mp.playVideo();}catch(e){}
 try{await Promise.race([v.play(),wait(1500)]);}catch(e){}
 if(v.paused){const b=document.querySelector('#play-pause-button,tp-yt-paper-icon-button.play-pause-button');if(b)b.click();await wait(400);}
}
// tiempos y video del reproductor de YouTube (el <video> a veces informa otra duración: la de lo que precarga)
let t=v?v.currentTime:0, d=(v&&isFinite(v.duration))?v.duration:0, id=q.get('v')||'', st=-9;
try{if(mp&&mp.getDuration){const x=mp.getDuration();if(x>0)d=x;}}catch(e){}
try{if(mp&&mp.getCurrentTime){const x=mp.getCurrentTime();if(x>=0)t=x;}}catch(e){}
try{if(mp&&mp.getVideoData){const x=(mp.getVideoData()||{}).video_id;if(x)id=x;}}catch(e){}
try{if(mp&&mp.getPlayerState)st=mp.getPlayerState();}catch(e){}
return {u:location.href, v:id, l:q.get('list')||'', hay:!!v, t:t, d:d, st:st,
 p:v?v.paused:true, e:(v?v.ended:false)||st===0, ad:ad, rs:v?v.readyState:0};})()"""


def _musica_estado(play: bool = False) -> dict | None:
    try:
        r = _musica_js(_JS_ESTADO.replace("__PLAY__", "true" if play else "false"), foco=play, timeout=6)
        return r if isinstance(r, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _musica_sonar(limite: float = 30.0) -> None:
    """Fuera de la cola: que la canción recién puesta arranque (como el autoplay de la ventana de música)."""
    fin = time.time() + limite
    time.sleep(1.2)
    while time.time() < fin:
        e = _musica_estado(play=True)
        if e and e.get("hay") and "watch" in str(e.get("u")) and not e.get("p"):
            return
        time.sleep(1.5)


def _vid_de(u: str) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(u or "").query)
    v = (q.get("v") or [""])[0]
    return v if re.fullmatch(r"[\w-]{6,20}", v) else ""


def _bitacora(msg: str) -> None:
    """Registro corto de la cola de Baco (hud/baco_cola.log): qué se buscó, qué se puso y por qué avanzó o se cortó."""
    if os.environ.get("BACO_ARCHIVO"):   # en las pruebas no se ensucia el registro real
        return
    try:
        f = Path(__file__).with_name("baco_cola.log")
        if f.exists() and f.stat().st_size > 300_000:
            f.write_text(f.read_text(encoding="utf-8", errors="replace")[-100_000:], encoding="utf-8")
        with f.open("a", encoding="utf-8") as h:
            h.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:  # noqa: BLE001
        pass


_RUIDO = re.compile(r"official|music video|video oficial|lyric[s]?|letra|audio|full|hd|hq|mv|pv", re.I)
# versiones que no son «la canción»: solo valen si el título guardado también las nombra
_OTRA_VERSION = ("reaction", "react", "reacciono", "first time", "cover", "covered", "歌ってみた", "remix", "8d", "nightcore",
                 "drum", "guitar", "bass", "beat saber", "tab", "karaoke", "instrumental", "mashup", "sped up", "slowed")


def _plano(x: str) -> str:
    import unicodedata

    x = unicodedata.normalize("NFKC", str(x or "")).lower()
    x = re.sub(r"[【】\[\]()（）「」『』|/・~～\-–—:：!！?？,.、。\"'＂♬]+", " ", x)
    return re.sub(r"\s+", " ", _RUIDO.sub(" ", x)).strip()


def _parecido(t: str, a: str, e: dict) -> float:
    """0..1: qué tanto calza el título de un resultado con la canción pedida. YouTube Music titula «うっせぇわ - Usseewa»:
    se compara con cada mitad. Una reacción, un cover o un remix que el título guardado no nombra resta harto."""
    from difflib import SequenceMatcher
    import unicodedata

    pa = _plano(a)

    def sin_artista(x: str) -> str:
        return (re.sub(r"(?<!\w)" + re.escape(pa) + r"(?!\w)", " ", x).strip() if pa else x) or x

    pt = re.sub(r"\s+", " ", sin_artista(_plano(t)))
    crudo = str(e.get("title") or "")
    partes = [crudo] + [x for x in re.split(r"\s+[-–—]\s+", crudo) if x.strip()]
    r = 0.0
    for x in partes:
        ex = re.sub(r"\s+", " ", sin_artista(_plano(x)))
        if ex:
            r = max(r, SequenceMatcher(None, pt, ex).ratio())
    bajo_t = unicodedata.normalize("NFKC", t + " " + a).lower()
    bajo_e = unicodedata.normalize("NFKC", crudo).lower()
    if any(w in bajo_e and w not in bajo_t for w in _OTRA_VERSION):
        r -= 0.35
    return max(0.0, r)


def _vids_archivo() -> Path:
    return ARCHIVO.with_name("baco_vids.json")


_BUSCADOS: dict = {}
_BUSCADOS_LOCK = threading.Lock()


def _buscar_video(t: str, a: str) -> str:
    """Id de YouTube de una canción guardada sin enlace. 19-11-2026: antes tomaba el primer resultado a ciegas y con
    títulos como «【Ado】BRAIN 歌いました» sonaba otra canción del mismo álbum. Ahora mira varios resultados (Canciones de
    YouTube Music y YouTube), elige el que más se parece al título y lo recuerda en ~/.atlas/baco_vids.json (así la
    misma canción suena siempre igual y la siguiente de la cola parte al tiro)."""
    k = _nrm(f"{t}|{a}")
    with _BUSCADOS_LOCK:
        if not _BUSCADOS:
            try:
                _BUSCADOS.update(json.loads(_vids_archivo().read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                _BUSCADOS["_"] = ""
        if _BUSCADOS.get(k):
            return _BUSCADOS[k]
    from yt_dlp import YoutubeDL

    # En orden de confianza: «Canciones» de YouTube Music, YouTube (videos), y «Canciones» con el título sin subtítulos.
    # Dentro de cada búsqueda se respeta el orden de YouTube: gana el PRIMER resultado cuyo título calza (>= 0,7), no el
    # que más se parece (así «Usseewa» de Ado le gana a un cover que se llama igual).
    corto = re.sub(r"\s+-.*$|\s*[(\[（【].*?[)\]）】]\s*", " ", t).strip()
    fuentes = [("https://music.youtube.com/search?q=" + urllib.parse.quote(f"{t} {a}".strip()) + "#songs", t),
               (f"ytsearch6:{t} {a}".strip(), t)]
    if re.search(r"【|歌いました|歌ってみた|cover", t, re.I):   # un video puntual (cover, «歌いました»): primero YouTube
        fuentes.reverse()
    if corto and _plano(corto) != _plano(t):
        fuentes.append(("https://music.youtube.com/search?q=" + urllib.parse.quote(f"{corto} {a}".strip()) + "#songs", corto))
    primeros: dict = {}   # primer resultado de cada búsqueda, por si nada calza
    vid = ""
    with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "playlistend": 6}) as ydl:
        for fuente, titulo in fuentes:
            try:
                info = ydl.extract_info(fuente, download=False)
            except Exception:  # noqa: BLE001
                continue
            for e in (info.get("entries") or [])[:6]:
                if not e or not re.fullmatch(r"[\w-]{6,20}", str(e.get("id") or "")):
                    continue
                primeros.setdefault(fuente, e["id"])
                if _parecido(titulo, a, e) >= 0.7:
                    vid = e["id"]
                    break
            if vid:
                break
    if vid:
        with _BUSCADOS_LOCK:
            _BUSCADOS[k] = vid
            try:
                _vids_archivo().write_text(json.dumps({x: y for x, y in _BUSCADOS.items() if x != "_"}, ensure_ascii=False), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    _bitacora(f"busca {t!r} / {a!r}: {'calza ' + vid if vid else 'nada calza'} · primeros {primeros}")
    if vid:
        return vid
    # nada calzó: el primero de «Canciones» (mejor el del título sin subtítulos), si no el de YouTube; no se recuerda
    orden = [f for f, _ in reversed(fuentes) if "#songs" in f] + [f for f, _ in fuentes if "#songs" not in f]
    return next((primeros[f] for f in orden if f in primeros), "")


def _prebuscar(p: dict) -> None:
    """Busca de antemano el video de la próxima canción de la cola (así no hay pausa larga entre canciones)."""
    if p and not p.get("u") and p.get("t"):
        threading.Thread(target=lambda: _buscar_seguro(p["t"], p.get("a", "")), daemon=True, name="baco-prebusca").start()


def _buscar_seguro(t: str, a: str) -> str:
    try:
        return _buscar_video(t, a)
    except Exception:  # noqa: BLE001
        return ""


def tocar(t: str = "", a: str = "", u: str = "", sola: bool = False) -> dict:
    """Pone una parte de la cola de Baco. YouTube suena en la ventana de música de Atlas (la misma de «Atlas, pon …»),
    que arranca sola; Spotify se abre en su app. sola=True: quien llama (la cola) se encarga de que arranque."""
    t, a, u = _txt(t, 120), _txt(a, 120), _url(u)
    if u and not re.match(r"https://((music|www|m)\.)?youtube\.com/|https://youtu\.be/", u):
        return abrir(u)   # Spotify u otro
    try:
        from openjarvis.tools import atlas_pc as PCM
    except Exception:  # noqa: BLE001  (sin Atlas: como antes)
        return abrir(u or "https://music.youtube.com/search?q=" + urllib.parse.quote(f"{t} {a}".strip()))
    if u:
        url = _url_ytm_reproducir(u)
    else:
        vid = _buscar_seguro(t, a)
        url = f"https://music.youtube.com/watch?v={vid}" if vid else "https://music.youtube.com/search?q=" + urllib.parse.quote(f"{t} {a}".strip())
    # 19-11-2026: ventana de música ya abierta: cambia de canción AHÍ MISMO (Page.navigate por CDP). Antes, si fallaba
    # el «location.href» se cerraba la ventana y se abría otra, y en ese hueco la cola se saltaba canciones.
    _bitacora(f"pone {url} ({t!r})")
    if _musica_ir(url):
        if not sola:
            threading.Thread(target=_musica_sonar, daemon=True, name="baco-sonar").start()
        return {"ok": True, "url": url, "busco": not u, "misma": True}
    try:
        PCM._cdp_eval(f"location.href={json.dumps(url)};true", "music.youtube.com")
        threading.Thread(target=PCM._MusicWindow._autoplay, daemon=True).start()
    except Exception:  # noqa: BLE001
        if _musica_hay_cdp():   # la ventana está viva y responde: no se cierra (se reintenta una vez)
            time.sleep(0.6)
            if _musica_ir(url):
                return {"ok": True, "url": url, "busco": not u, "misma": True}
        _bitacora("no hay ventana de música: se abre una")
        PCM._MusicWindow.open(url)   # no hay ventana de música: se abre
    return {"ok": True, "url": url, "busco": not u}



# ----------------------------------------------------------------------------- cola de Baco (la lleva el servidor)
# Así avanza aunque Baco esté minimizado, y salta un segundo antes del final para que YouTube Music no ponga «la siguiente» suya.
_COLA: dict = {"id": "", "items": [], "j": 0, "oyo": False, "tit": "", "t0": 0.0, "fin": False, "n": 0, "cdp": False, "ult": (0.0, 0.0)}
_COLA_LOCK = threading.RLock()
_VIDS: dict = {}   # título normalizado -> enlace exacto del video que sonó en la ventana de música de Atlas
_YT = r"https://((music|www|m)\.)?youtube\.com/|https://youtu\.be/"


def _nrm(s) -> str:
    return re.sub(r"[\W_]+", " ", str(s or "").lower()).strip()


def _es_lista(u: str) -> bool:
    return bool(u) and bool(re.search(r"[?&]list=|spotify(\.com/(intl-[a-z-]+/)?|:)(playlist|album)", u))


def _es_yt(p: dict) -> bool:
    return not p.get("u") or bool(re.match(_YT, p["u"]))


def _cola_estado():
    c = _COLA
    if not c["id"]:
        return None
    r = {"id": c["id"], "j": c["j"], "n": len(c["items"]), "fin": c["fin"]}
    if c.get("orden"):   # la puso la voz («pon Baco …»): la página la adopta con este orden
        r.update(orden=list(c["orden"]), mezcla=bool(c.get("mezcla")))
    return r


def _cola_poner(en_hilo: bool = False) -> dict:
    """Toca la parte actual de la cola; si suena otra cosa en otra app, la pausa antes (que no suenen dos)."""
    with _COLA_LOCK:
        c = _COLA
        if not c["items"] or c["fin"]:
            return {"ok": False, "error": "No hay cola."}
        p = dict(c["items"][c["j"]])
        sig = dict(c["items"][c["j"] + 1]) if c["j"] + 1 < len(c["items"]) else None
        c["n"] += 1
        c.update(oyo=False, tit="", t0=time.time(), cdp=False, ult=(0.0, 0.0))
        turno = (c["id"], c["j"], c["n"])

    def run() -> dict:
        v = _MEDIA_CACHE.get("v") or {}
        en_ytm = _es_yt(p)
        if not en_ytm:   # va Spotify: la ventana de música se pausa directo (más seguro que por Windows)
            try:
                _musica_js("(()=>{const v=document.querySelector('video');if(v&&!v.paused)v.pause();return true})()", timeout=3)
            except Exception:  # noqa: BLE001
                pass
        if v.get("hay") and v.get("estado") == "Playing" and (v.get("app_n") == "Spotify") == en_ytm:
            try:
                _media("pause")
            except Exception:  # noqa: BLE001
                pass
        try:
            r = tocar(p["t"], p["a"], p["u"], sola=en_ytm)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
        _prebuscar(sig)
        if en_ytm and r.get("ok") and not _es_lista(p["u"]) and r.get("url"):
            threading.Thread(target=_cola_seguir_yt, args=(turno, r["url"], True, None if p["u"] else dict(p)), daemon=True,
                             name="baco-cola-yt").start()
        return r

    if en_hilo:
        threading.Thread(target=run, daemon=True, name="baco-cola").start()
        return {"ok": True}
    return run()


def _cola_turno() -> tuple:
    c = _COLA
    return (c["id"], c["j"], c["n"])


def _cola_avanzar(turno: tuple | None = None) -> None:
    """Pasa a la siguiente parte. turno: (id, j, n) de la parte que terminó; si ya se pasó (el otro vigía o la página), no hace nada."""
    with _COLA_LOCK:
        c = _COLA
        if turno is not None and _cola_turno() != turno:
            return
        if not c["items"] or c["fin"]:
            return
        c["j"] += 1
        if c["j"] >= len(c["items"]):
            c.update(j=len(c["items"]) - 1, fin=True)
            return
    _cola_poner(en_hilo=True)


def _cola_saltar(d: int) -> bool:
    _bitacora(f"cola: botón {'⏭' if d > 0 else '⏮'} de «Ahora suena»")
    """⏮ / ⏭ de «Ahora suena» con una cola de Baco andando: mueven la cola (no la cola propia de YouTube Music, que
    ponía otra canción y dejaba la lista de Baco marcando una y sonando otra)."""
    with _COLA_LOCK:
        c = _COLA
        if not c["id"] or not c["items"] or c["fin"]:
            return False
        j = c["j"] + d
        if j >= len(c["items"]):
            c.update(fin=True)
            c["n"] += 1
            fin = True
        else:
            c["j"] = max(0, j)
            fin = False
    if fin:
        try:
            _musica_js("(()=>{const v=document.querySelector('video');if(v&&!v.paused)v.pause();return true})()", timeout=3)
        except Exception:  # noqa: BLE001
            pass
        return True
    _cola_poner(en_hilo=True)
    return True


def _cola_seguir_yt(turno: tuple, url: str, nueva: bool, p: dict | None = None) -> None:
    """Vigía de una canción de YouTube en la ventana de música, leyendo el <video> directo (cada ~0,5 s).

    - Empezó cuando suena el video pedido (mismo id) y pasó del primer segundo; los avisos no cuentan.
    - Terminó cuando le falta ~1 s (antes de que YouTube Music ponga «la siguiente» suya), cuando terminó, o si la
      ventana ya está en otro video después de haber sonado el nuestro.
    - En pausa no avanza nunca. Si el video cargó pero no arranca en 60 s (borrado, bloqueado), sigue con la siguiente;
      si la ventana está en otra cosa (iniciar sesión, por ejemplo) espera sin saltar.
    nueva=False: Atlas se reinició y la página pasó la cola («seguir»): solo se vigila, no se toca ni se salta nada.
    """
    pedido = _vid_de(url)
    empezo, visto, sin_ventana, t_play, desde = False, False, 0.0, 0.0, time.time()
    ult = (0.0, 0.0)   # (segundo, duración) de la última lectura de nuestra canción
    time.sleep(1.0)
    while True:
        with _COLA_LOCK:
            if _cola_turno() != turno or _COLA["fin"] or not _COLA["items"]:
                return
        ahora = time.time()
        quiere_play = nueva and not empezo and ahora - desde > 2.5 and ahora - t_play > 3
        e = _musica_estado(play=quiere_play)
        if quiere_play:
            t_play = ahora
        if not e or not e.get("hay"):
            if not e:
                sin_ventana = sin_ventana or ahora
                if ahora - sin_ventana > 20:   # se cerró la ventana de música: la cola queda donde iba
                    with _COLA_LOCK:
                        if _cola_turno() == turno:
                            _COLA["cdp"] = False
                    return
            time.sleep(0.8)
            continue
        sin_ventana = 0.0
        with _COLA_LOCK:
            if _cola_turno() == turno:
                _COLA["cdp"] = True   # este vigía manda; el de Windows ya no decide por esta canción
        vid, t, d = str(e.get("v") or ""), float(e.get("t") or 0), float(e.get("d") or 0)
        if not pedido and vid and "watch" in str(e.get("u")):
            pedido = vid   # se puso por búsqueda: la canción es la que abrió
        if not empezo:
            if vid and vid == pedido:
                visto = True
            elif nueva and not visto and vid and 1.0 < t < 10 and not e.get("ad") and not e.get("p") and ahora - desde > 4:
                pedido = vid   # YouTube Music la abrió con otro id (la versión «canción» del video): es la nuestra
                visto = True
            if vid and vid == pedido and t > 1.0 and not e.get("ad"):
                empezo = True
                with _COLA_LOCK:
                    if _cola_turno() == turno:
                        _COLA.update(oyo=True, tit="")
                        if p and not p.get("u"):   # se puso por nombre: desde ahora la canción guardada apunta a este video
                            p["u"] = f"https://music.youtube.com/watch?v={vid}"
                            c_it = _COLA["items"][_COLA["j"]]
                            if c_it.get("t") == p["t"] and not c_it.get("u"):
                                c_it["u"] = p["u"]
            elif nueva and visto and ahora - desde > 60 and t < 0.5:
                _bitacora(f"cola {turno}: {pedido} no sonó en 60 s: siguiente")
                _cola_avanzar(turno)   # el video cargó pero en un minuto no hubo caso de que sonara (borrado, bloqueado)
                return
            time.sleep(0.5)
            continue
        if e.get("ad"):
            time.sleep(0.5)
            continue
        if vid and pedido and vid != pedido:
            # YouTube Music pasa sola a «la siguiente» cuando la nuestra terminó, y entonces abre su radio (list=RD…).
            # «Atlas, pon …» o un clic en la ventana cambian a media canción y sin esa radio.
            radio = str(e.get("l") or "").startswith("RD")
            if radio or (ult[1] > 20 and ult[0] >= ult[1] - 6):
                _bitacora(f"cola {turno}: YouTube Music puso {vid} al terminar {pedido}: siguiente")
                _cola_avanzar(turno)
            else:
                _bitacora(f"cola {turno}: a media canción ({ult[0]:.0f}/{ult[1]:.0f} s) la ventana pasó a {vid}: se corta la cola")   # a media canción alguien puso otra («Atlas, pon …» o un clic en la ventana): la cola se corta
                _cola_cortar(turno)
            return
        if e.get("e") or (d > 20 and t >= d - 1.2 and not e.get("p")):
            _bitacora(f"cola {turno}: terminó {pedido} ({t:.0f}/{d:.0f} s): siguiente")
            _cola_avanzar(turno)
            return
        if vid == pedido:
            ult = (t, d)
        # cerca del final se mira más seguido
        time.sleep(0.25 if d > 20 and d - t < 4 else 0.5)


def _cola_cortar(turno: tuple | None = None) -> None:
    """Otro puso música a media canción: la cola de Baco termina (la página muestra «Fin de la cola») y no pisa lo nuevo."""
    with _COLA_LOCK:
        if turno is not None and _cola_turno() != turno:
            return
        if _COLA["id"]:
            _COLA["fin"] = True
            _COLA["n"] += 1


def _cola_vigilar(v: dict) -> None:
    """Con lo que informa Windows: ¿ya sonó esta parte y terminó (o el reproductor siguió con otra)?
    Las canciones sueltas de YouTube las vigila _cola_seguir_yt (directo en la ventana); esto queda para Spotify,
    las playlists y por si la ventana de música no responde."""
    with _COLA_LOCK:
        c = _COLA
        if not c["items"] or c["fin"] or not v.get("hay") or time.time() - c["t0"] < 6 or c.get("cdp"):
            return
        p, tit, suena = c["items"][c["j"]], _nrm(v.get("titulo")), v.get("estado") == "Playing"
        pos, fin = float(v.get("pos") or 0), float(v.get("fin") or 0)
        spotify, de_spotify = not _es_yt(p), v.get("app_n") == "Spotify"
        if spotify != de_spotify:   # lo que informa Windows es de la otra app (la anterior que aún no se pausa, etc.)
            return
        if not c["oyo"]:
            if suena and tit:
                c.update(oyo=True, tit=tit)
            return
        lista = _es_lista(p["u"])
        otra = not lista and suena and tit and tit != c["tit"]
        ult = c.get("ult") or (0.0, 0.0)
        cortar = otra and not (ult[1] > 20 and ult[0] >= ult[1] - 6)   # cambió a media canción: la puso otro
        termina = otra \
            or (not lista and suena and tit == c["tit"] and fin > 20 and pos >= fin - 1.2 and time.time() - c["t0"] > 20) \
            or (not suena and fin > 20 and pos >= fin - 3)
        if tit == c["tit"]:
            c["ult"] = (pos, fin)
        turno = _cola_turno()
    if cortar:
        _bitacora(f"cola {turno} (Windows): cambió a {v.get('titulo')!r} a media canción: se corta")
        _cola_cortar(turno)
    elif termina:
        _bitacora(f"cola {turno} (Windows): terminó ({v.get('titulo')!r}, {pos:.0f}/{fin:.0f} s): siguiente")
        _cola_avanzar(turno)


def cola(cuerpo: dict) -> dict:
    """La página manda la cola (en el orden en que va a sonar) y en qué parte va. accion: parar | seguir (sin volver a tocar)."""
    accion = str(cuerpo.get("accion", ""))
    with _COLA_LOCK:
        if accion == "parar":
            _COLA.update(id="", items=[], j=0, fin=False)
            _COLA["n"] += 1
            return {"ok": True, "cola": None}
        items = []
        for p in (cuerpo.get("items") or [])[:300]:
            if isinstance(p, dict) and (p.get("t") or p.get("u")):
                items.append({"t": _txt(p.get("t"), 120), "a": _txt(p.get("a"), 120), "u": _url(p.get("u")) if p.get("u") else ""})
        j = _ent(cuerpo.get("j"), 0, max(0, len(items) - 1))
        if not items:
            return {"ok": False, "error": "Cola vacía."}
        mismo = accion == "seguir" and _COLA["id"] == (_txt(cuerpo.get("id"), 60) or "cola") and _COLA["j"] == j \
            and _COLA["items"] and _COLA["items"][_COLA["j"]] == items[j]
        if mismo:   # solo cambió el orden de lo que viene (aleatorio): la canción y su vigía siguen igual
            _COLA.update(items=items, orden=None)   # el orden ahora lo lleva la página
            return {"ok": True, "cola": _cola_estado()}
        _COLA["n"] += 1
        _COLA.update(id=_txt(cuerpo.get("id"), 60) or "cola", items=items, j=j, fin=False, oyo=False, tit="", t0=time.time(), cdp=False,
                     ult=(0.0, 0.0), orden=None, mezcla=False)
        turno, p = _cola_turno(), dict(items[j])
    if accion == "seguir":
        # Atlas se reinició y la página trae la cola que tenía guardada. Solo se retoma si lo que suena ES esa canción;
        # si suena otra cosa (o nada), esa cola vieja se da por terminada: antes revivía y, al terminar lo que uno
        # puso aparte, saltaba a una canción de la playlist vieja.
        v = _MEDIA_CACHE.get("v") or {}
        a_, b_ = _nrm(p["t"]), _nrm(v.get("titulo"))
        if not (v.get("hay") and a_ and b_ and (a_ in b_ or b_ in a_)):
            _bitacora(f"cola {turno}: la página trajo una cola guardada pero suena {v.get('titulo')!r}: no se retoma")
            _cola_cortar(turno)
            return {"ok": True, "cola": _cola_estado()}
        if _es_yt(p) and not _es_lista(p["u"]):   # se vuelve a vigilar lo que suena, sin cortarlo
            threading.Thread(target=_cola_seguir_yt, args=(turno, _url_ytm_reproducir(p["u"]) if p["u"] else "", False),
                             daemon=True, name="baco-cola-yt").start()
        return {"ok": True, "cola": _cola_estado()}
    r = _cola_poner()
    return {**r, "cola": _cola_estado()}


# ----------------------------------------------------------------------------- playlists por voz (19-11-2026)
# «Atlas, pon Baco Ado» / «pon Baco Ado en aleatorio» (hud_server.route_baco): la misma cola que el botón Reproducir.
def playlists() -> list:
    """[{id, t, n}] de las playlists de Baco que tienen canciones (o un enlace)."""
    out = []
    for x in cargar().get("musica") or []:
        n = len(x.get("pistas") or [])
        if n or x.get("u"):
            out.append({"id": x["id"], "t": x.get("t", ""), "n": n or 1})
    return out


def buscar_playlist(nombre: str) -> dict | None:
    """La playlist que nombró: igual, o que la contiene, o muy parecida («ado» -> «Ado», «electrónica» -> «Electro»)."""
    from difflib import SequenceMatcher

    q = _nrm(nombre)
    if not q:
        return None
    L = [x for x in cargar().get("musica") or [] if x.get("pistas") or x.get("u")]
    for f in (lambda k: k == q, lambda k: k.startswith(q) or q.startswith(k), lambda k: q in k or k in q):
        hay = [x for x in L if _nrm(x.get("t")) and f(_nrm(x.get("t")))]
        if hay:
            return min(hay, key=lambda x: abs(len(_nrm(x.get("t"))) - len(q)))
    mejor = max(L, key=lambda x: SequenceMatcher(None, q, _nrm(x.get("t"))).ratio(), default=None)
    return mejor if mejor and SequenceMatcher(None, q, _nrm(mejor.get("t"))).ratio() >= 0.75 else None


def _sp_uri(u: str) -> str:
    m = re.match(r"https://open\.spotify\.com/(?:intl-[a-z-]+/)?(track|playlist|album)/([A-Za-z0-9]+)", u or "")
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else (u or "")


def tocar_playlist(nombre: str, mezclar: bool = False) -> dict:
    """Arma y toca la cola de una playlist de Baco. -> {ok, t, n, mezcla} o {ok: False, error, playlists}."""
    x = buscar_playlist(nombre)
    if not x:
        return {"ok": False, "error": "no_existe", "playlists": [p["t"] for p in playlists()]}
    pistas = list(x.get("pistas") or [])
    if x.get("u"):   # el enlace de la playlist va primero, como en la página
        pistas = [{"t": x.get("t", ""), "a": "", "u": x["u"]}] + pistas
    orden = list(range(len(pistas)))
    if mezclar:
        import random

        random.shuffle(orden)
    items = [{"t": pistas[k].get("t", ""), "a": pistas[k].get("a", ""), "u": _sp_uri(pistas[k].get("u", ""))} for k in orden]
    r = cola({"id": x["id"], "j": 0, "items": items})
    with _COLA_LOCK:
        if _COLA["id"] == x["id"]:
            _COLA.update(orden=orden if not x.get("u") else None, mezcla=mezclar)
    _bitacora(f"voz: pone la playlist {x.get('t')!r} ({len(items)} canciones{', aleatorio' if mezclar else ''})")
    return {"ok": bool(r.get("ok")), "t": x.get("t", ""), "n": len(items), "mezcla": mezclar, "error": r.get("error", "")}


def cola_activa() -> bool:
    with _COLA_LOCK:
        return bool(_COLA["id"] and _COLA["items"] and not _COLA["fin"])


def saltar(d: int) -> bool:
    """«siguiente» / «anterior» por voz con una cola de Baco andando."""
    return _cola_saltar(d)


def _capturar_vid(v: dict) -> None:
    """Si suena en la ventana de música de Atlas, guarda el enlace exacto del video (para guardar esa versión y no otra)."""
    if not v.get("hay") or v.get("estado") != "Playing" or v.get("app_n") not in ("Edge", "YouTube Music"):
        return
    k = _nrm(v.get("titulo"))
    if not k or k in _VIDS or _VIGIA.get("buscando") == k:
        return
    _VIGIA["buscando"] = k

    def run() -> None:
        try:
            from openjarvis.tools import atlas_pc as PCM

            js = "({v: new URLSearchParams(location.search).get('v') || '', t: document.title})"
            try:   # 19-11-2026: por CDP propio (sin depender de la librería websockets)
                r = _musica_js(js, timeout=3) or {}
            except Exception:  # noqa: BLE001
                r = PCM._cdp_eval(js, "music.youtube.com", 3) or {}
            vid = str(r.get("v") or "")
            if re.fullmatch(r"[\w-]{6,20}", vid) and k in _nrm(r.get("t")):
                if len(_VIDS) > 500:
                    _VIDS.clear()
                _VIDS[k] = f"https://music.youtube.com/watch?v={vid}"
                try:
                    import atlas_baco_mas as MAS

                    MAS.poner_enlace(v.get("titulo"), v.get("artista"), _VIDS[k])
                except Exception:  # noqa: BLE001
                    pass
                # las canciones guardadas con este mismo título y artista (sin enlace) quedan con este video exacto
                poner_u_pista(v.get("titulo"), v.get("artista") or "", _VIDS[k])
        except Exception:  # noqa: BLE001
            pass
        finally:
            _VIGIA["buscando"] = ""

    threading.Thread(target=run, daemon=True, name="baco-vid").start()


def abrir(url: str) -> dict:
    u = _url(url)
    if not u:
        return {"ok": False, "error": "Enlace no permitido."}
    if abrir_en_ytm(u):
        return {"ok": True, "misma": True}
    try:
        ff = _firefox() if u.lower().startswith(("http://", "https://")) else ""
        if ff:
            subprocess.Popen([ff, u], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.startfile(u)  # type: ignore[attr-defined]  # navegador predeterminado, Steam o Spotify
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


# ----------------------------------------------------------------------------- música: controles multimedia de Windows
_PS_MEDIA = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $m.MakeGenericMethod($t).Invoke($null, @($op)); $null = $task.Wait(4000); $task.Result }
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
function Elegir($mgr) {   # la sesión de música: ignora apps que no son reproductores (Claude, Teams…) y prefiere la que está sonando
  $no = 'anthropic|claude|teams|slack|zoom|outlook|whatsapp'
  $ok = @($mgr.GetSessions() | Where-Object { $_.SourceAppUserModelId -notmatch $no })
  $suena = @($ok | Where-Object { $_.GetPlaybackInfo().PlaybackStatus.ToString() -eq 'Playing' })
  if ($suena.Count) { return $suena[0] }
  $c = $mgr.GetCurrentSession()
  if ($c -and $c.SourceAppUserModelId -notmatch $no) { return $c }
  if ($ok.Count) { return $ok[0] }
  return $null
}
$s = Elegir $mgr
if (-not $s) { '{"hay":false}'; exit }
$acc = '__ACCION__'
if ($acc -eq 'toggle') { $null = Await ($s.TryTogglePlayPauseAsync()) ([bool]) }
elseif ($acc -eq 'next') { $null = Await ($s.TrySkipNextAsync()) ([bool]) }
elseif ($acc -eq 'prev') { $null = Await ($s.TrySkipPreviousAsync()) ([bool]) }
elseif ($acc -eq 'pause') { $null = Await ($s.TryPauseAsync()) ([bool]) }
if ($acc) { Start-Sleep -Milliseconds 400 }
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$est = $s.GetPlaybackInfo().PlaybackStatus.ToString()
$pos = 0.0; $fin = 0.0
try {   # dónde va la canción (para que la cola de Baco sepa cuándo terminó)
  $tl = $s.GetTimelineProperties(); $pos = $tl.Position.TotalSeconds; $fin = $tl.EndTime.TotalSeconds
  if ($est -eq 'Playing') { $pos += ([DateTimeOffset]::UtcNow - $tl.LastUpdatedTime).TotalSeconds }
} catch {}
[pscustomobject]@{ hay = $true; titulo = $p.Title; artista = $p.Artist; album = $p.AlbumTitle; app = $s.SourceAppUserModelId; estado = $est; pos = [math]::Round([math]::Min($pos, [math]::Max($fin, 0) + 1), 1); fin = [math]::Round($fin, 1) } | ConvertTo-Json -Compress
"""
_PS_VIGIA = _PS_MEDIA.split("$s = Elegir $mgr")[0] + r"""
$padre = __PADRE__; $n = 0
while ($true) {
  try {
    $s = Elegir $mgr
    if (-not $s) { '{"hay":false}' }
    else {
      $p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
      $est = $s.GetPlaybackInfo().PlaybackStatus.ToString()
      $pos = 0.0; $fin = 0.0
      try { $tl = $s.GetTimelineProperties(); $pos = $tl.Position.TotalSeconds; $fin = $tl.EndTime.TotalSeconds
        if ($est -eq 'Playing') { $pos += ([DateTimeOffset]::UtcNow - $tl.LastUpdatedTime).TotalSeconds } } catch {}
      [pscustomobject]@{ hay = $true; titulo = $p.Title; artista = $p.Artist; album = $p.AlbumTitle; app = $s.SourceAppUserModelId; estado = $est; pos = [math]::Round([math]::Min($pos, [math]::Max($fin, 0) + 1), 1); fin = [math]::Round($fin, 1) } | ConvertTo-Json -Compress
    }
  } catch { '{"hay":false,"error":"vigia"}' }
  [Console]::Out.Flush()
  $n++; if ($n % 25 -eq 0 -and -not (Get-Process -Id $padre -ErrorAction SilentlyContinue)) { exit }   # si Atlas se cerró, se va
  Start-Sleep -Milliseconds 400
}
"""
_VIGIA: dict = {"proc": None, "t": 0.0, "arranque": 0.0, "sonado": ("", 0.0)}


def _no_es_musica(v: dict) -> bool:
    """Apps que Windows anuncia como «reproduciendo» pero no son música (p. ej. la app de Claude)."""
    return bool(v.get("hay")) and bool(re.search(r"anthropic|claude|teams|slack|zoom|outlook|whatsapp", str(v.get("app", "")), re.I))


def _vigia_leer(proc) -> None:
    """Lee las líneas del vigía y deja lo último en el caché (así «Ahora suena» cambia en menos de un segundo)."""
    try:
        for linea in proc.stdout:
            try:
                v = json.loads(linea.decode("utf-8", errors="replace").strip() or "{}")
            except ValueError:
                continue
            if "hay" not in v:
                continue
            if _no_es_musica(v):
                v = {"hay": False}
            if v.get("hay"):
                v["app_n"] = _app_legible(v.get("app", ""))
                clave = f"{v.get('titulo')}|{v.get('artista')}|{v.get('estado')}"
                if clave != _VIGIA["sonado"][0] or time.time() - _VIGIA["sonado"][1] > 3:   # anotar como antes (~cada 3 s), no 2 veces por segundo
                    _VIGIA["sonado"] = (clave, time.time())
                    try:
                        import atlas_baco_mas as MAS

                        MAS.anotar_sonado(v)
                    except Exception:  # noqa: BLE001
                        pass
            _MEDIA_CACHE.update(t=time.time(), v=v)
            _VIGIA["t"] = time.time()
            _cola_vigilar(v)
            _capturar_vid(v)
    except Exception:  # noqa: BLE001
        pass


def _vigia_vivo() -> bool:
    """Arranca (o reanuda) el PowerShell que vigila la música. Si falla, se reintenta cada 30 s y mientras tanto se pregunta como antes."""
    pr = _VIGIA["proc"]
    if pr is not None and pr.poll() is None:
        return time.time() - _VIGIA["t"] < 3
    if os.name != "nt" or time.time() - _VIGIA["arranque"] < 30:
        return False
    _VIGIA["arranque"] = time.time()
    try:
        pr = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                               _PS_VIGIA.replace("__PADRE__", str(os.getpid()))],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _VIGIA["proc"] = pr
        threading.Thread(target=_vigia_leer, args=(pr,), daemon=True, name="baco-vigia-musica").start()
    except Exception:  # noqa: BLE001
        _VIGIA["proc"] = None
    return False


_MEDIA_LOCK = threading.RLock()
_MEDIA_CACHE: dict = {"t": 0.0, "v": None}


def _app_legible(aumid: str) -> str:
    a = (aumid or "").lower()
    for clave, nombre in (("spotify", "Spotify"), ("firefox", "Firefox"), ("308046b0af4a39cb", "Firefox"), ("chrome", "Chrome"),
                          ("msedge", "Edge"), ("youtube", "YouTube Music"), ("zune", "Reproductor multimedia"),
                          ("vlc", "VLC"), ("discord", "Discord")):
        if clave in a:
            return nombre
    return aumid.split("!")[0].split("\\")[-1][:40] if aumid else ""


def _media(accion: str = "") -> dict:
    """Lo que suena en Windows: {hay, titulo, artista, app, estado ('Playing', 'Paused'…)}. accion: toggle/next/prev."""
    accion = accion if accion in ("toggle", "next", "prev", "pause") else ""
    if not accion and _vigia_vivo() and _MEDIA_CACHE["v"] is not None:   # el vigía la tiene al día (< 0,5 s)
        return _MEDIA_CACHE["v"]
    if not accion and _MEDIA_CACHE["v"] is not None and time.time() - _MEDIA_CACHE["t"] < 2:
        return _MEDIA_CACHE["v"]
    with _MEDIA_LOCK:
        if not accion and _MEDIA_CACHE["v"] is not None and time.time() - _MEDIA_CACHE["t"] < 2:
            return _MEDIA_CACHE["v"]
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                                _PS_MEDIA.replace("__ACCION__", accion)],
                               capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            salida = r.stdout.decode("utf-8", errors="replace").strip().splitlines()
            v = json.loads(salida[-1]) if salida else {"hay": False, "error": r.stderr.decode("utf-8", "replace")[-200:]}
            if _no_es_musica(v):
                v = {"hay": False}
            if v.get("hay"):
                v["app_n"] = _app_legible(v.get("app", ""))
                try:
                    import atlas_baco_mas as MAS

                    MAS.anotar_sonado(v)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            v = {"hay": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        _MEDIA_CACHE.update(t=time.time(), v=v)
        if not accion:
            _cola_vigilar(v)
        return v


def media(accion: str = "") -> dict:
    """Lo que suena en Windows: {hay, titulo, artista, app, estado, pos, fin} + la cola de Baco y, si se sabe, el enlace exacto (u)."""
    if accion in ("next", "prev") and _cola_saltar(1 if accion == "next" else -1):
        v = dict(_MEDIA_CACHE.get("v") or {"hay": False})
    else:
        v = dict(_media(accion))
    if v.get("hay"):
        u = _VIDS.get(_nrm(v.get("titulo")))
        if u:
            v["u"] = u
    v["cola"] = _cola_estado()
    return v


# ----------------------------------------------------------------------------- TMDB (series)
TMDB_SECRETO = "Atlas-Baco-TMDB"
# id de proveedor de TMDB (streaming en Chile) -> plataforma de Baco
PROVEEDORES = {8: "netflix", 1796: "netflix", 337: "disney", 1899: "max", 384: "max", 119: "prime", 9: "prime", 350: "apple", 2: "apple",
               283: "crunchy", 1968: "crunchy", 531: "paramount", 582: "paramount", 192: "youtube", 188: "youtube"}
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
TMDB_FONDO = "https://image.tmdb.org/t/p/w1280"
_TMDB: dict = {"token": None, "t_token": 0.0, "fichas": {}}


def _tmdb_token() -> str:
    """El token desde el Administrador de credenciales (recordado 60 s en memoria). '' si no hay."""
    with _LOCK:
        if time.time() - _TMDB["t_token"] < 60:
            return _TMDB["token"] or ""
    try:
        from openjarvis.security import atlas_secretos as SEC

        tok = (SEC.leer(TMDB_SECRETO) or "").strip()
    except Exception:  # noqa: BLE001
        tok = ""
    with _LOCK:
        _TMDB.update(token=tok, t_token=time.time())
    return tok


def _tmdb(ruta: str, params: dict | None = None) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    tok = _tmdb_token()
    if not tok:
        raise PermissionError("falta la clave de TMDB")
    q = {"language": "es-ES", **(params or {})}
    cab = {"Accept": "application/json"}
    if tok.startswith("eyJ"):
        cab["Authorization"] = "Bearer " + tok
    else:
        q["api_key"] = tok
    url = "https://api.themoviedb.org/3/" + ruta + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=8) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            with _LOCK:
                _TMDB["t_token"] = 0.0
            raise PermissionError("TMDB rechazó la clave") from None
        raise RuntimeError(f"TMDB respondió {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("sin conexión con TMDB") from None
    finally:
        tok = None  # noqa: F841


def _proveedor(p: dict) -> str:
    """Proveedor de TMDB -> plataforma de Baco, por id o por nombre (TMDB cambia los id cuando una marca cambia de nombre)."""
    if p.get("provider_id") in PROVEEDORES:
        return PROVEEDORES[p["provider_id"]]
    n = re.sub(r"[^a-z0-9+ ]", "", str(p.get("provider_name") or "").lower())
    if "channel" in n:   # «Max Amazon Channel» y similares: se ve dentro de otra tienda
        return ""
    for clave, k in (("netflix", "netflix"), ("disney", "disney"), ("hbo", "max"), ("max", "max"), ("prime video", "prime"),
                     ("amazon", "prime"), ("apple tv", "apple"), ("crunchyroll", "crunchy"), ("paramount", "paramount"), ("youtube", "youtube")):
        if re.search(r"\b" + re.escape(clave) + r"\b", n):
            return k
    return ""


def tmdb_buscar(texto: str) -> dict:
    texto = _txt(texto, 80)
    if len(texto) < 2:
        return {"ok": True, "res": []}
    d = _tmdb("search/tv", {"query": texto, "include_adult": "false"})
    res = []
    for x in (d.get("results") or [])[:8]:
        res.append({"tmdb": x.get("id"), "t": x.get("name") or x.get("original_name") or "",
                    "anio": (x.get("first_air_date") or "")[:4], "img": x.get("poster_path") or "",
                    "resumen": (x.get("overview") or "")[:220]})
    return {"ok": True, "res": res}


def tmdb_ficha(tid, forzar: bool = False) -> dict:
    """Temporadas con su número de episodios y el próximo episodio con fecha. Recordada 6 h."""
    tid = _ent(tid, 1, 10**9, 0)
    if not tid:
        raise ValueError("id")
    with _LOCK:
        f = _TMDB["fichas"].get(tid)
        if f and not forzar and time.time() - f["_t"] < 6 * 3600:
            return f
    d = _tmdb(f"tv/{tid}", {"append_to_response": "watch/providers"})
    cl = (((d.get("watch/providers") or {}).get("results") or {}).get("CL") or {})
    provs = sorted((cl.get("flatrate") or []) + (cl.get("ads") or []), key=lambda p: p.get("display_priority") or 99)
    donde = [k for k in (_proveedor(p) for p in provs) if k]
    temps = [{"T": s.get("season_number"), "eps": s.get("episode_count") or 0, "f": s.get("air_date") or ""}
             for s in d.get("seasons") or [] if (s.get("season_number") or 0) > 0]
    nx = d.get("next_episode_to_air") or {}
    ficha = {"ok": True, "tmdb": tid, "t": d.get("name") or "", "img": d.get("poster_path") or "",
             "estado": d.get("status") or "", "temporadas": temps,
             "proximo": {"f": nx.get("air_date") or "", "T": nx.get("season_number"), "E": nx.get("episode_number"),
                         "t": nx.get("name") or ""} if nx.get("air_date") else None,
             "redes": [n.get("name") for n in d.get("networks") or []][:3], "fondo": d.get("backdrop_path") or "",
             "resumen": (d.get("overview") or "")[:1500], "nota": round(d.get("vote_average") or 0, 1),
             "generos": [g.get("name") for g in d.get("genres") or []][:3], "donde": list(dict.fromkeys(donde)),
             "donde_n": [p.get("provider_name") for p in provs][:8],
             "_t": time.time()}
    with _LOCK:
        _TMDB["fichas"][tid] = ficha
    return ficha


def tmdb_estrenos() -> dict:
    """Próximos episodios/temporadas de las series anotadas que tienen ficha de TMDB, para «Lo que viene»."""
    hoy = time.strftime("%Y-%m-%d")
    ev, errores = [], 0
    try:
        ev += igdb_estrenos()
    except Exception:  # noqa: BLE001
        errores += 1
    if not _tmdb_token():
        return {"ok": True, "ev": ev, "errores": errores}
    for s in cargar().get("series", []):
        if not s.get("tmdb"):
            continue
        try:
            nx = tmdb_ficha(s["tmdb"]).get("proximo")
        except Exception:  # noqa: BLE001
            errores += 1
            continue
        if nx and nx["f"] >= hoy:
            que = f"Temporada {nx['T']}" if nx.get("E") == 1 else f"T{nx['T']} · E{nx['E']}"
            ev.append({"id": f"tmdb:{s['tmdb']}", "t": s["t"], "s": que, "f": nx["f"], "k": "s", "auto": True, "serie": s["id"]})
    return {"ok": True, "ev": ev, "errores": errores}


# ----------------------------------------------------------------------------- IGDB (juegos esperados)
IGDB_SECRETO = "Atlas-Baco-IGDB"
IGDB_IMG = "https://images.igdb.com/igdb/image/upload/t_cover_big/"
_IGDB: dict = {"cred": None, "t_cred": 0.0, "token": "", "vence": 0.0, "fichas": {}}
_CAMPOS = ("fields name,url,cover.image_id,first_release_date,platforms.abbreviation,"
           "release_dates.date,release_dates.human,release_dates.category,release_dates.date_format,"
           "release_dates.platform.abbreviation,release_dates.platform.name;")


def _igdb_cred() -> tuple[str, str]:
    with _LOCK:
        if time.time() - _IGDB["t_cred"] < 60 and _IGDB["cred"] is not None:
            return _IGDB["cred"]
    try:
        from openjarvis.security import atlas_secretos as SEC

        d = json.loads(SEC.leer(IGDB_SECRETO) or "{}")
        cred = (str(d.get("id") or ""), str(d.get("secreto") or ""))
    except Exception:  # noqa: BLE001
        cred = ("", "")
    with _LOCK:
        _IGDB.update(cred=cred, t_cred=time.time())
    return cred


def _igdb(endpoint: str, consulta: str) -> list:
    import urllib.error
    import urllib.parse
    import urllib.request

    cid, sec = _igdb_cred()
    if not cid or not sec:
        raise PermissionError("falta la clave de IGDB")
    with _LOCK:
        tok = _IGDB["token"] if time.time() < _IGDB["vence"] else ""
    try:
        if not tok:
            datos = urllib.parse.urlencode({"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode()
            with urllib.request.urlopen(urllib.request.Request("https://id.twitch.tv/oauth2/token", data=datos), timeout=8) as r:
                j = json.loads(r.read() or b"{}")
            tok = j.get("access_token") or ""
            with _LOCK:
                _IGDB.update(token=tok, vence=time.time() + int(j.get("expires_in") or 3600) - 120)
        req = urllib.request.Request("https://api.igdb.com/v4/" + endpoint, data=consulta.encode("utf-8"),
                                     headers={"Client-ID": cid, "Authorization": "Bearer " + tok, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            with _LOCK:
                _IGDB.update(token="", vence=0.0, t_cred=0.0)
            if exc.code != 400:
                raise PermissionError("Twitch/IGDB rechazó la clave") from None
        raise RuntimeError(f"IGDB respondió {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("sin conexión con IGDB") from None
    finally:
        cid = sec = tok = None  # noqa: F841


def _plat(p: dict) -> str:
    a = (p or {}).get("abbreviation") or (p or {}).get("name") or ""
    return {"Series X|S": "Xbox Series", "XONE": "Xbox One", "PS4": "PS4", "PS5": "PS5", "Switch": "Switch",
            "Switch 2": "Switch 2", "PC": "PC", "Mac": "Mac", "Linux": "Linux"}.get(a, a)


def _resumen(g: dict) -> dict:
    """Juego de IGDB -> {igdb, t, img, url, plataformas, fechas: [{f, txt, plats, exacta}], proximo}."""
    hoy = time.strftime("%Y-%m-%d")
    por_fecha: dict = {}
    for rd in g.get("release_dates") or []:
        ts = rd.get("date")
        fmt = rd.get("date_format", rd.get("category", 7))
        if not ts or fmt == 7:
            continue
        f = time.strftime("%Y-%m-%d", time.gmtime(ts))
        e = por_fecha.setdefault(f, {"f": f, "txt": rd.get("human") or f, "plats": [], "exacta": fmt == 0})
        pl = _plat(rd.get("platform") or {})
        if pl and pl not in e["plats"]:
            e["plats"].append(pl)
    fechas = sorted(por_fecha.values(), key=lambda e: e["f"])
    futuras = [e for e in fechas if e["f"] >= hoy]
    plats = [_plat(p) for p in g.get("platforms") or []]
    return {"igdb": g.get("id"), "t": g.get("name") or "", "img": (g.get("cover") or {}).get("image_id") or "",
            "url": g.get("url") or "", "plataformas": [p for p in plats if p][:8], "fechas": fechas,
            "proximo": futuras[0] if futuras else None, "salido": bool(fechas) and not futuras}


def igdb_buscar(texto: str) -> dict:
    texto = _txt(texto, 80).replace('"', " ").replace("\\", " ").strip()
    if len(texto) < 2:
        return {"ok": True, "res": []}
    res = _igdb("games", f'search "{texto}"; {_CAMPOS} where version_parent = null; limit 10;')
    return {"ok": True, "res": [_resumen(g) for g in res]}


def igdb_juegos(ids: list, forzar: bool = False) -> dict:
    """Fichas de varios juegos (recordadas 6 h): {igdb_id: resumen}."""
    ids = [i for i in dict.fromkeys(_ent(x, 1, 10**9, 0) for x in ids) if i][:100]
    with _LOCK:
        faltan = [i for i in ids if forzar or i not in _IGDB["fichas"] or time.time() - _IGDB["fichas"][i]["_t"] > 6 * 3600]
    if faltan:
        for g in _igdb("games", f"{_CAMPOS} where id = ({','.join(map(str, faltan))}); limit {len(faltan)};"):
            r = _resumen(g)
            r["_t"] = time.time()
            with _LOCK:
                _IGDB["fichas"][r["igdb"]] = r
    with _LOCK:
        return {i: {k: v for k, v in _IGDB["fichas"][i].items() if k != "_t"} for i in ids if i in _IGDB["fichas"]}


def igdb_esperados() -> dict:
    if not all(_igdb_cred()):
        return {"ok": False, "falta_clave": True, "juegos": {}}
    ids = [e["igdb"] for e in cargar().get("esperados", [])]
    return {"ok": True, "juegos": {str(k): v for k, v in igdb_juegos(ids).items()} if ids else {}}


def igdb_estrenos() -> list:
    """Fechas de salida próximas de los juegos esperados, una por fecha (con sus plataformas)."""
    if not all(_igdb_cred()):
        return []
    esp = cargar().get("esperados", [])
    if not esp:
        return []
    fichas = igdb_juegos([e["igdb"] for e in esp])
    hoy = time.strftime("%Y-%m-%d")
    ev = []
    for e in esp:
        r = fichas.get(e["igdb"])
        for f in (r or {}).get("fechas", []):
            if f["f"] >= hoy:
                s = " · ".join(f["plats"]) + ("" if f["exacta"] else f" ({f['txt']})")
                ev.append({"id": f"igdb:{e['igdb']}:{f['f']}", "t": e["t"], "s": s, "f": f["f"], "k": "j", "auto": True,
                           "juego": e["id"]})
    return ev


def claves() -> dict:
    """Solo si están guardadas; nunca el valor."""
    try:
        from openjarvis.security import atlas_secretos as SEC

        return {"tmdb": SEC.existe(TMDB_SECRETO), "igdb": SEC.existe(IGDB_SECRETO)}
    except Exception:  # noqa: BLE001
        return {"tmdb": False, "igdb": False}


# ----------------------------------------------------------------------------- juegos fuera de Steam
def _manuales() -> list:
    return cargar().get("pc_manuales", [])


def vigilar_juegos() -> bool:
    """Arranca el hilo que mide el tiempo de los juegos del PC (lo llama hud_server al iniciar)."""
    import atlas_baco_juegos as J

    return J.vigilar(_manuales)


def juegos_pc() -> dict:
    import atlas_baco_juegos as J

    try:
        vigilar_juegos()
        return J.lista(_manuales())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "juegos": [], "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ----------------------------------------------------------------------------- rutas
def estado() -> dict:
    d = cargar()
    d.pop("steam_nombres", None)
    d["plataformas"] = PLATAFORMAS
    d["steam"] = juegos_steam()
    d["pc"] = juegos_pc()
    d["claves"] = claves()
    d["tmdb_img"] = TMDB_IMG
    d["igdb_img"] = IGDB_IMG
    d["tmdb_fondo"] = TMDB_FONDO
    d["igdb_arte"] = "https://images.igdb.com/igdb/image/upload/t_1080p/"
    import atlas_baco_mas as MAS

    d["perfil"] = MAS.limpiar_perfil(d.get("perfil"))
    d["noticias"] = MAS.limpiar_noticias(d.get("noticias"))
    d["perfil_opciones"] = MAS.PERFIL_OPCIONES
    d["pt_disponible"] = MAS.PUNTOTICKET
    d["pendiente"] = [x for x, ok in (("TMDB", d["claves"]["tmdb"]), ("IGDB", d["claves"]["igdb"]), ("conciertos automáticos", False)) if not ok]
    return d


def http(metodo: str, ruta: str, query: dict | None = None, cuerpo: dict | None = None) -> tuple[int, bytes, str]:
    def js(obj, code: int = 200):
        return code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    try:
        if metodo == "GET":
            if ruta == "api/estado":
                return js(estado())
            if ruta == "api/juegos":
                return js({**juegos_steam(forzar=True), "pc": juegos_pc()})
            if ruta == "api/media":
                return js(media())
            if ruta == "api/tmdb/buscar":
                return js(tmdb_buscar((query or {}).get("q", [""])[0]))
            if ruta == "api/tmdb/ficha":
                f = dict(tmdb_ficha((query or {}).get("id", ["0"])[0]))
                f.pop("_t", None)
                return js(f)
            if ruta == "api/igdb/buscar":
                return js(igdb_buscar((query or {}).get("q", [""])[0]))
            if ruta == "api/igdb/esperados":
                return js(igdb_esperados())
            if ruta == "api/estrenos":
                return js(tmdb_estrenos())
            if ruta in ("api/portada", "api/sonado", "api/noticias", "api/descubrir", "api/arte", "api/eventos"):
                import atlas_baco_mas as MAS

                q = query or {}
                if ruta == "api/portada":
                    datos, tipo = MAS.portada(q.get("k", [""])[0])
                    if not datos:
                        return 404, b"", "text/plain; charset=utf-8"
                    return 200, datos, tipo
                if ruta == "api/sonado":
                    return js({"ok": True, "res": MAS.sonado()[-120:]})
                if ruta == "api/noticias":
                    return js(MAS.noticias())
                if ruta == "api/descubrir":
                    return js(MAS.descubrir(q.get("forzar", [""])[0] == "1"))
                if ruta == "api/arte":
                    return js(MAS.arte(q.get("t", [""])[0]))
                return js(MAS.eventos())
            if ruta == "api/portada_pl":   # portada elegida para una playlist
                f = _portada_archivo((query or {}).get("id", [""])[0])
                datos = f.read_bytes() if f.is_file() else b""
                return (200, datos, _tipo_img(datos)) if _tipo_img(datos) else (404, b"", "text/plain; charset=utf-8")
            if ruta == "api/portada_cancion":   # carátula de una canción cualquiera de la lista (catálogo público)
                import atlas_baco_mas as MAS

                q = query or {}
                try:
                    datos = MAS.portada_catalogo(_txt(q.get("t", [""])[0], 120), _txt(q.get("a", [""])[0], 120))
                except Exception:  # noqa: BLE001
                    datos = b""
                return (200, datos, _tipo_img(datos)) if _tipo_img(datos) else (404, b"", "text/plain; charset=utf-8")
            if ruta == "api/espectro":
                import atlas_baco_audio

                return js(atlas_baco_audio.bandas())
        elif metodo == "POST":
            if ruta == "api/guardar":
                guardar(cuerpo)
                return js({"ok": True})
            if ruta == "api/portada_pl":
                return js(portada_playlist(cuerpo))
            if ruta == "api/jugar":
                import atlas_baco_juegos as J

                return js(J.jugar(_txt(cuerpo.get("id"), 60), _manuales()))
            if ruta == "api/elegir_exe":
                import atlas_baco_juegos as J

                return js(J.elegir_exe())
            if ruta == "api/abrir":
                return js(abrir(cuerpo.get("u", "")))
            if ruta == "api/cola":
                return js(cola(cuerpo))
            if ruta == "api/tocar":
                return js(tocar(cuerpo.get("t", ""), cuerpo.get("a", ""), cuerpo.get("u", "")))
            if ruta == "api/media":
                return js(media(str(cuerpo.get("accion", ""))))
    except PermissionError as exc:
        return js({"error": str(exc), "falta_clave": True}, 200)
    except ValueError as exc:
        return js({"error": f"dato inválido: {exc}"}, 400)
    except Exception as exc:  # noqa: BLE001
        return js({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, 500)
    return js({"error": "not found"}, 404)

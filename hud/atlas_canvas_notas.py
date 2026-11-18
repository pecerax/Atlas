"""Notas de Canvas: lee las notas de cada curso con la sesión del usuario y detecta las nuevas.

Canvas (Instructure) lo usan la PUC, la UDP, la UdeC y muchas otras. Funciona igual que U-Cursos en Atlas:

- Una sola vez, «conecta Canvas <dirección>» abre una ventana de Edge (perfil aparte) en el Canvas de su
  universidad y el usuario inicia sesión él mismo. Atlas nunca ve la clave: solo guarda las cookies de la sesión,
  cifradas en el Administrador de credenciales (entrada Atlas-Canvas). No usa tokens de acceso: varias
  universidades los prohíben o los limitan, y Canvas Lite no los tiene.
- Cada cierto rato pide a la API de Canvas (la misma que usa la página web) los cursos donde es alumno y las
  evaluaciones de cada uno con su nota, y compara con lo que vio la vez anterior (canvas_notas.json). La primera
  vez de cada curso solo anota lo que hay, sin avisar.
- Solo lee (GET). Si la sesión expiró, lo dice para que vuelva a conectar.

API usada (documentación oficial: https://canvas.instructure.com/doc/api/):
  GET /api/v1/users/self                                     comprobar que la sesión sirve
  GET /api/v1/courses?enrollment_type=student&enrollment_state=active
  GET /api/v1/courses/:id/assignments?include[]=submission    evaluaciones + la entrega del alumno (nota)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookies import SimpleCookie
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDP_PORT = 9225  # U-Cursos usa 9224
FORMATO = 1
PRUEBA = False  # las pruebas lo ponen en True para poder guardar la sesión sin el Administrador de credenciales
MAX_PAGINAS = 20
UA = "Mozilla/5.0 (Atlas; solo lectura)"

# Direcciones conocidas (solo las comprobadas). Para otra universidad: «conecta Canvas cursos.ejemplo.cl».
CONOCIDOS = {
    "canvas network": "https://learn.canvas.net",
    "canvas net": "https://learn.canvas.net",
}


class SessionExpired(Exception):
    pass


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _sess_file() -> Path:
    return HERE / "canvas_sesion.json"


def _state_file() -> Path:
    return HERE / "canvas_notas.json"


def _secretos():
    from openjarvis.security import atlas_secretos

    return atlas_secretos


# ----------------------------------------------------------------------------- dirección del Canvas
def normalize_url(text: str) -> str:
    """'cursos.canvas.uc.cl', 'https://x.instructure.com/courses/3' -> 'https://host'. '' si no hay dirección."""
    p = _plain(text)
    for k, v in CONOCIDOS.items():
        if k in p:
            return v
    m = re.search(r"(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:[/:?#]\S*)?", (text or "").lower())
    if not m:
        return ""
    host = m.group(1)
    if host.startswith("www.canvas.net") or host == "canvas.net":  # el catálogo; los cursos viven en learn.
        host = "learn.canvas.net"
    return "https://" + host


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


# ----------------------------------------------------------------------------- sesión guardada
def _load_session() -> dict:
    """Las cookies guardadas (cifradas en el Administrador de credenciales; el archivo es solo un sobre)."""
    try:
        return _secretos().cargar_json(_sess_file()) or {}
    except Exception:  # noqa: BLE001
        return {}


def base_url() -> str:
    return (_load_session().get("url") or "").rstrip("/")


def has_session() -> bool:
    s = _load_session()
    return bool(s.get("cookies") and s.get("url"))


def _cookie_matches(domain: str, host: str) -> bool:
    d = (domain or "").lstrip(".").lower()
    return bool(d) and "." in d and (host == d or host.endswith("." + d))


def save_session(url: str, cookies: list[dict]) -> int:
    host = _host(url)
    keep = [{"name": c["name"], "value": c["value"], "domain": c.get("domain", ""), "path": c.get("path", "/")}
            for c in cookies if _cookie_matches(c.get("domain", ""), host)]
    cifrado = _secretos().guardar_json(_sess_file(), {"guardada": datetime.now().isoformat(timespec="seconds"),
                                                      "url": url.rstrip("/"), "cookies": keep})
    if not cifrado and not PRUEBA:  # nunca dejar las cookies de la sesión en texto plano
        forget_session()
        raise RuntimeError("no pude cifrar la sesión en el Administrador de credenciales")
    return len(keep)


def forget_session() -> None:
    _secretos().borrar_json(_sess_file())


def _refresh_cookies(set_cookie_headers: list[str]) -> None:
    """Canvas renueva la cookie de sesión en cada respuesta: guardar la nueva para que no venza antes de tiempo."""
    if not set_cookie_headers:
        return
    s = _load_session()
    cookies = s.get("cookies") or []
    by_name = {c["name"]: c for c in cookies}
    changed = False
    for h in set_cookie_headers:
        sc = SimpleCookie()
        try:
            sc.load(h)
        except Exception:  # noqa: BLE001
            continue
        for name, morsel in sc.items():
            if name in by_name and morsel.value and by_name[name]["value"] != morsel.value:
                by_name[name]["value"] = morsel.value
                changed = True
    if changed:
        try:
            save_session(s["url"], cookies)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------------- red
def _strip_guard(body: str) -> str:
    # Canvas antepone «while(1);» a las respuestas JSON pedidas con sesión (protección contra JSON hijacking)
    return body[len("while(1);"):] if body.startswith("while(1);") else body


def _next_link(link: str) -> str:
    for part in (link or "").split(","):
        m = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', part)
        if m:
            return m.group(1)
    return ""


def fetch_json(path: str):
    """GET a la API con las cookies guardadas. -> (datos, url de la página siguiente o '').
    Lanza SessionExpired si Canvas pide iniciar sesión."""
    s = _load_session()
    cookies, base = s.get("cookies") or [], (s.get("url") or "").rstrip("/")
    if not cookies or not base:
        raise SessionExpired("No hay sesión de Canvas guardada.")
    url = path if path.startswith("http") else base + "/" + path.lstrip("/")
    host = _host(base)
    if _host(url) != host:  # solo se habla con el Canvas conectado
        raise ValueError(f"dirección fuera de {host}: {url}")
    jar = "; ".join(f"{c['name']}={c['value']}" for c in cookies if _cookie_matches(c.get("domain", ""), host))
    req = urllib.request.Request(url, headers={"Cookie": jar, "User-Agent": UA, "Accept": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=25)  # noqa: S310 (solo el Canvas conectado, https)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:  # {"status":"unauthenticated"}: la sesión venció o se cerró
            raise SessionExpired("La sesión de Canvas expiró.") from exc
        raise
    with r:
        final = r.geturl()
        ctype = r.headers.get("Content-Type", "")
        link = r.headers.get("Link", "")
        set_cookies = r.headers.get_all("Set-Cookie") or []
        body = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    if _host(final) != host or "/login" in urllib.parse.urlsplit(final).path or "json" not in ctype:
        raise SessionExpired("Canvas pidió iniciar sesión de nuevo.")
    _refresh_cookies(set_cookies)
    return json.loads(_strip_guard(body)), _next_link(link)


def get_all(path: str, fetcher=None) -> list:
    """Junta todas las páginas (Canvas pagina con el encabezado Link)."""
    fetcher = fetcher or fetch_json
    out, url, n = [], path, 0
    while url and n < MAX_PAGINAS:
        data, url = fetcher(url)
        n += 1
        if isinstance(data, dict):  # un error de la API viene como objeto: {"errors": [...]}
            msg = "; ".join(e.get("message", "") for e in data.get("errors", []) if isinstance(e, dict)) or str(data)[:120]
            raise RuntimeError(msg)
        out.extend(data)
    return out


# ----------------------------------------------------------------------------- cursos y notas
def courses(fetcher=None) -> list[dict]:
    """Cursos activos donde el usuario es alumno."""
    base = base_url()
    rows = get_all("/api/v1/courses?enrollment_type=student&enrollment_state=active&per_page=100", fetcher)
    out = []
    for c in rows:
        if not isinstance(c, dict) or not c.get("id") or c.get("access_restricted_by_date") or not c.get("name"):
            continue
        out.append({"id": c["id"], "path": f"{_host(base)}/courses/{c['id']}", "code": c.get("course_code") or str(c["id"]),
                    "nombre": c["name"].strip()})
    return sorted(out, key=lambda c: c["nombre"])


def _num(x) -> str:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


CHILE = re.compile(r"^\s*[1-7](?:[.,]\d{1,2})?\s*$")


def format_grade(a: dict) -> str:
    """Nota de una evaluación como se dice en voz alta; '' si no hay nota publicada."""
    sub = a.get("submission") or {}
    if sub.get("excused"):
        return "eximido"
    score, grade = sub.get("score"), sub.get("grade")
    if score is None and grade in (None, ""):
        return ""
    kind = a.get("grading_type") or "points"
    pts = a.get("points_possible")
    if kind == "not_graded":
        return ""
    if kind == "pass_fail":
        return {"complete": "aprobado", "incomplete": "reprobado"}.get(str(grade), str(grade))
    if kind == "points":
        if grade not in (None, "") and CHILE.match(str(grade)) and pts and float(pts) == 7:
            return _num(grade)  # evaluación sobre 7 (escala chilena): «un 5,5», no «5,5 de 7»
        if score is None:
            return str(grade)
        return f"{_num(score)} de {_num(pts)}" if pts else _num(score)
    return str(grade if grade not in (None, "") else _num(score)).replace(".", ",")  # percent, letter_grade, gpa_scale


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return ""


def course_rows(course: dict, fetcher=None) -> list[dict]:
    """-> [{"evaluacion", "nota" ('' si no hay), "fecha", "categoria"}] de un curso."""
    rows = get_all(f"/api/v1/courses/{course['id']}/assignments?include[]=submission&order_by=due_at&per_page=100", fetcher)
    out, seen = [], {}
    for a in rows:
        if not isinstance(a, dict) or not a.get("name") or a.get("published") is False:
            continue
        name = re.sub(r"\s+", " ", a["name"]).strip()
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:  # dos evaluaciones con el mismo nombre: distinguirlas
            name = f"{name} ({seen[name]})"
        sub = a.get("submission") or {}
        out.append({"evaluacion": name, "nota": format_grade(a),
                    "fecha": _date(sub.get("graded_at")) or _date(a.get("due_at")), "categoria": ""})
    return out


# ----------------------------------------------------------------------------- estado y revisión
def load_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ramos": {}, "recientes": []}


def save_state(st: dict) -> None:
    _state_file().write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def check(fetcher=None, course_list: list[dict] | None = None, now: datetime | None = None) -> dict:
    """Revisa las notas de todos los cursos. -> {"nuevas": [...], "errores": [...], "revisados": n}.

    Una nota es «nueva» si aparece una evaluación con nota que antes no tenía nota (o no existía), o si la nota
    cambió. La primera vez que se revisa un curso solo se guarda lo que hay."""
    now = now or datetime.now()
    st = load_state()
    if st.get("formato") != FORMATO or st.get("url") != base_url():  # otro lector u otra universidad: de nuevo
        st = {"formato": FORMATO, "url": base_url(), "ramos": {}, "recientes": [], "fechas": {}, "nombres": {}}
    for k in ("ramos", "fechas", "nombres"):
        st.setdefault(k, {})
    st.setdefault("recientes", [])
    nuevas, errores, n = [], [], 0
    cl = course_list if course_list is not None else courses(fetcher)
    for c in cl:
        try:
            rows = course_rows(c, fetcher)
        except SessionExpired:
            raise
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{c['nombre']}: {exc}")
            continue
        n += 1
        old = st["ramos"].get(c["path"])
        cur = {r["evaluacion"]: r["nota"] for r in rows}
        st["fechas"][c["path"]] = {r["evaluacion"]: r["fecha"] for r in rows if r.get("fecha") and r["nota"]}
        st["nombres"][c["path"]] = {"nombre": c["nombre"], "code": c["code"]}
        if old is not None:
            for ev, nota in cur.items():
                if nota and old.get(ev, "") != nota:
                    nuevas.append({"ramo": c["nombre"], "code": c["code"], "evaluacion": ev, "nota": nota,
                                   "antes": old.get(ev, ""), "visto": now.isoformat(timespec="minutes"),
                                   "origen": "Canvas"})
        st["ramos"][c["path"]] = {**(old or {}), **cur}
    st["recientes"] = (nuevas + st["recientes"])[:30]
    st["revisado"] = now.isoformat(timespec="minutes")
    save_state(st)
    return {"nuevas": nuevas, "errores": errores, "revisados": n}


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]


def say_aviso(i: dict) -> str:
    """Avisos que llegan solos (voz, HUD, Telegram): curso y evaluación, SIN la nota (igual que U-Cursos, pedido 17-11)."""
    return f"{i['ramo']}: {i['evaluacion']}"


def say_item(i: dict) -> str:
    cambio = f" (antes {i['antes']})" if i.get("antes") else ""
    nota = i["nota"]
    return f"{i['ramo']}: {i['evaluacion']}, " + (nota if not CHILE.match(nota) else f"un {nota}") + cambio


def say_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day} de {_MESES[d.month - 1]}"
    except ValueError:
        return iso


def course_list_saved() -> list[dict]:
    """Los cursos de la última revisión (sin conectarse), para buscar por nombre."""
    st = load_state()
    return [{"path": p, **v} for p, v in st.get("nombres", {}).items()]


def latest(path: str | None = None) -> dict | None:
    """La nota más reciente: la última que Atlas vio aparecer, o si no, la de fecha más nueva en Canvas."""
    st = load_state()
    names = st.get("nombres", {})
    for i in st.get("recientes", []):
        if path is None or names.get(path, {}).get("code") == i.get("code"):
            return {**i, "fecha": ""}
    best = None
    for p, grades in st.get("ramos", {}).items():
        if path and p != path:
            continue
        for ev, nota in grades.items():
            f = st.get("fechas", {}).get(p, {}).get(ev, "")
            if nota and f and (best is None or f > best["fecha"]):
                c = names.get(p, {"nombre": p, "code": p})
                best = {"ramo": c["nombre"], "code": c["code"], "evaluacion": ev, "nota": nota, "fecha": f}
    return best


_COMUNES = {"canvas", "kanvas", "network", "curso", "cursos", "notas", "nota", "nuevas", "para", "with", "from", "your",
            "introduction", "introduccion", "teacher", "training", "school", "schools", "course", "taller", "ultima"}


def course_grades(name: str) -> tuple[dict | None, dict]:
    """Curso que calza con el nombre o código dicho, y sus notas guardadas."""
    # «Canvas» y palabras comunes no identifican un curso (uso real: «¿tengo notas nuevas en Canvas?» calzaba con
    # «Passport to Canvas»)
    q = re.sub(r"\b[ck]anva[sz]?\b|\bnetwork\b", " ", _plain(name))
    cl = course_list_saved()
    best = next((c for c in cl if len(_plain(c["code"])) > 2 and _plain(c["code"]).replace(" ", "") in q.replace(" ", "")), None) \
        or next((c for c in cl if any(len(w) > 3 and w not in _COMUNES and re.search(rf"\b{w}\b", q)
                                for w in re.findall(r"[a-z]+", _plain(c["nombre"])))), None)
    if not best:
        return None, {}
    return best, load_state().get("ramos", {}).get(best["path"], {})


# ----------------------------------------------------------------------------- ventana para iniciar sesión
def _cdp_json(path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}{path}", timeout=3) as r:  # noqa: S310 (local)
        return json.loads(r.read().decode("utf-8"))


def _cdp_call(ws_url: str, method: str, params: dict | None = None):
    from websockets.sync.client import connect

    with connect(ws_url, open_timeout=5, max_size=2**23) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv(timeout=10))
            if msg.get("id") == 1:
                return msg.get("result") or {}


def _kill_login_window() -> None:
    try:
        import psutil

        for proc in psutil.process_iter(["name", "cmdline"]):
            if "msedge" in (proc.info.get("name") or "").lower() and "canvas-profile" in " ".join(proc.info.get("cmdline") or []):
                proc.kill()
    except Exception:  # noqa: BLE001
        pass


def login(edge: str, url: str, log=print, timeout: float = 600) -> str:
    """Abre el Canvas de `url` en una ventana propia; espera a que el usuario inicie sesión y guarda las cookies.
    -> "ok" | "timeout" | "error: …". Bloquea: llamarlo en un hilo."""
    url = url.rstrip("/")
    host = _host(url)
    profile = os.path.join(os.environ.get("LOCALAPPDATA", str(HERE)), "Atlas", "canvas-profile")
    if os.environ.get("ATLAS_PRUEBAS") == "1":  # las pruebas nunca abren la ventana de inicio de sesión
        return "error: pruebas"
    _kill_login_window()
    subprocess.Popen([edge, f"--app={url}/login", f"--user-data-dir={profile}", f"--remote-debugging-port={CDP_PORT}",
                      "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                      "--window-size=1000,780"])
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(3)
        try:
            pages = [t for t in _cdp_json("/json") if t.get("type") == "page"]
        except Exception:  # noqa: BLE001
            continue
        if not pages:
            return "error: se cerró la ventana antes de iniciar sesión"
        # sigue en el inicio de sesión (el de Canvas o el de la universidad)
        if not any(_host(p.get("url", "")) == host and "/login" not in urllib.parse.urlsplit(p.get("url", "")).path
                   for p in pages):
            continue
        try:
            ws = _cdp_json("/json/version")["webSocketDebuggerUrl"]
            cookies = _cdp_call(ws, "Storage.getCookies").get("cookies") or []
            n = save_session(url, cookies)
            me, _ = fetch_json("/api/v1/users/self")  # comprobar que la sesión sirve
            if not isinstance(me, dict) or not me.get("id"):
                raise SessionExpired("aún sin sesión")
        except SessionExpired:
            forget_session()
            continue  # aún no termina de entrar
        except Exception as exc:  # noqa: BLE001
            log(f"Canvas: no pude guardar la sesión ({exc})")
            continue
        log(f"Canvas: sesión guardada ({n} cookies, {host})")
        _kill_login_window()
        return "ok"
    _kill_login_window()
    return "timeout"

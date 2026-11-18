"""Notas de U-Cursos: lee la página «Notas» de cada ramo con la sesión del usuario y detecta las nuevas.

U-Cursos no avisa las notas por correo ni las pone en el calendario, así que Atlas entra como lo haría
el usuario (idea tomada de github.com/eseekae/u-cursosMCP, MIT):

- Una sola vez, «conecta U-Cursos» abre una ventana de Edge (perfil aparte) donde el usuario inicia
  sesión él mismo. Atlas nunca ve la clave: solo guarda las cookies de la sesión en ucursos_sesion.json.
- Cada cierto rato revisa https://www.u-cursos.cl/<ramo>/notas/ y compara con lo que vio la vez anterior
  (ucursos_notas.json). La primera vez de cada ramo solo anota lo que hay, sin avisar.
- Solo lee (GET). Si la sesión expiró, lo dice para que vuelva a conectar.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "https://www.u-cursos.cl"
CDP_PORT = 9224
GRADE = re.compile(r"^\s*([1-7](?:[.,]\d{1,2})?)\s*$")
PATH_RE = re.compile(r"https?://(?:www\.)?u-cursos\.cl/([a-z_]+/(\d{4})/(\d)/([A-Z]{2,5}\d{2,5}[A-Z]?)/(\d+))/", re.I)


class SessionExpired(Exception):
    pass


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _sess_file() -> Path:
    return HERE / "ucursos_sesion.json"


def _state_file() -> Path:
    return HERE / "ucursos_notas.json"


def _secretos():
    from openjarvis.security import atlas_secretos

    return atlas_secretos


def _load_session() -> dict:
    """Las cookies guardadas (cifradas en el Administrador de credenciales; el archivo es solo un sobre)."""
    try:
        return _secretos().cargar_json(_sess_file()) or {}
    except Exception:  # noqa: BLE001
        return {}


def has_session() -> bool:
    return bool(_load_session().get("cookies"))


def save_session(cookies: list[dict]) -> int:
    keep = [{"name": c["name"], "value": c["value"], "domain": c.get("domain", ""), "path": c.get("path", "/")}
            for c in cookies if "u-cursos.cl" in c.get("domain", "") or "uchile.cl" in c.get("domain", "")]
    _secretos().guardar_json(_sess_file(), {"guardada": datetime.now().isoformat(timespec="seconds"), "cookies": keep})
    return len(keep)


def forget_session() -> None:
    _secretos().borrar_json(_sess_file())


# ----------------------------------------------------------------------------- red
def fetch(path: str) -> str:
    """GET a U-Cursos con las cookies guardadas. Lanza SessionExpired si U-Cursos pide iniciar sesión."""
    cookies = _load_session().get("cookies") or []
    if not cookies:
        raise SessionExpired("No hay sesión de U-Cursos guardada.")
    jar = "; ".join(f"{c['name']}={c['value']}" for c in cookies if "u-cursos.cl" in c.get("domain", ""))
    url = path if path.startswith("http") else BASE + "/" + path.lstrip("/")
    req = urllib.request.Request(url, headers={"Cookie": jar, "User-Agent": "Mozilla/5.0 (Atlas; solo lectura)"})
    try:
        r = urllib.request.urlopen(req, timeout=25)  # noqa: S310 (solo https://www.u-cursos.cl)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):  # uso real: con la sesión vencida, cada ramo responde 401 Unauthorized
            raise SessionExpired("La sesión de U-Cursos expiró.") from exc
        raise
    with r:
        final = r.geturl()
        cs = r.headers.get_content_charset() or "utf-8"  # U-Cursos manda iso-8859-1
        body = r.read().decode(cs, errors="replace")
        global LAST_URL
        LAST_URL = final
    if "u-cursos.cl" not in final.split("/")[2]:
        raise SessionExpired("U-Cursos pidió iniciar sesión de nuevo.")
    if 'id="boton_login"' in body:
        raise SessionExpired("La sesión de U-Cursos expiró.")
    return body


# ----------------------------------------------------------------------------- ramos
def courses(ics_files: list[Path] | None = None) -> list[dict]:
    """Ramos del semestre actual, sacados de los calendarios de U-Cursos que Atlas ya tiene."""
    files = ics_files if ics_files is not None else sorted(HERE.glob("*.ics"))
    found: dict[str, dict] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace").replace("\r\n ", "").replace("\n ", "")
        except OSError:
            continue
        for ev in text.split("BEGIN:VEVENT")[1:]:
            m = PATH_RE.search(ev)
            if not m:
                continue
            path, year, sem, code, sec = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).upper(), m.group(5)
            c = found.setdefault(path, {"path": path, "code": code, "sec": sec, "periodo": (year, sem), "nombre": code})
            s = re.search(r"^SUMMARY:(.*)$", ev, re.M)
            if s and c["nombre"] == code:
                after = s.group(1).split(f"{code}-{sec}", 1)
                if len(after) == 2 and after[1].strip():
                    c["nombre"] = after[1].strip().replace("\\,", ",").replace("$1", ",")
    if not found:
        return []
    now = max(c["periodo"] for c in found.values())
    return sorted((c for c in found.values() if c["periodo"] == now), key=lambda c: c["nombre"])


# ----------------------------------------------------------------------------- página de notas
LAST_URL = ""


class _UcursosNotas(HTMLParser):
    """La página real de notas del alumno (…/notas/alumno): una fila por evaluación.
    1.ª celda: <h1><a>Nombre</a>…</h1>, <h2><span class="tiempo_rel" data-time=…>; última celda: <h1 class="strong">
    con la nota final. Las filas class="separador" traen la categoría (Controles, Tareas…)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.cat = ""
        self.tr: dict | None = None
        self.td = -1
        self.sep = False
        self.h1 = 0          # profundidad dentro de <h1>
        self.h1_seen = 0     # cuántos <h1> lleva la celda
        self.a = False
        self.dl = 0
        self.buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag == "tr":
            self.tr, self.td, self.sep = {"name": "", "date": "", "cells": []}, -1, "separador" in (at.get("class") or "")
            self.buf = []
        elif self.tr is None:
            return
        elif tag == "td":
            self.td += 1
            self.h1_seen = 0
            self.tr["cells"].append("")
            self.buf = []
        elif tag == "dl":
            self.dl += 1
        elif tag == "h1" and not self.dl:
            self.h1 += 1
            self.h1_seen += 1
            self.buf = []
        elif tag == "a" and self.td == 0 and self.h1 and "opcion" in (at.get("class") or ""):
            self.a = True  # el enlace «Estadísticas» no es parte del nombre
        elif tag == "span" and self.td == 0 and at.get("data-time") and not self.tr["date"]:
            try:
                self.tr["date"] = datetime.fromtimestamp(int(at["data-time"])).date().isoformat()
            except (ValueError, OSError):
                pass

    def handle_endtag(self, tag):
        if self.tr is None:
            return
        if tag == "a" and self.a:
            self.a = False
        elif tag == "dl" and self.dl:
            self.dl -= 1
        elif tag == "h1" and self.h1:
            self.h1 -= 1
            if self.td == 0 and self.h1_seen == 1 and not self.tr["name"]:
                self.tr["name"] = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            elif self.td > 0 and self.h1_seen == 1:
                self.tr["cells"][self.td] = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        elif tag == "td" and self.sep and self.td == 0:
            self.cat = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        elif tag == "tr":
            t, self.tr = self.tr, None
            if not self.sep and t["name"] and len(t["cells"]) >= 2:
                last = t["cells"][-1]
                self.rows.append({"evaluacion": t["name"], "nota": last.replace(".", ",") if GRADE.match(last) else "",
                                  "fecha": t["date"], "categoria": self.cat, "fila": " | ".join(t["cells"][1:])})

    def handle_data(self, data):
        if self.tr is not None and not self.a:
            self.buf.append(data)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.cell: list[str] | None = None
        self.row: list[str] | None = None
        self.head = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"cols": [], "rows": []})
        elif not self.stack:
            return
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell, self.head = [], tag == "th"
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if not self.stack:
            return
        if tag in ("td", "th") and self.cell is not None:
            txt = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if self.row is not None:
                self.row.append(txt)
            if self.head and not self.stack[-1]["rows"]:
                self.stack[-1].setdefault("_th", []).append(txt)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            t = self.stack[-1]
            if t.get("_th") and not t["cols"] and len(t["_th"]) == len(self.row) and all(self.row):
                t["cols"] = t.pop("_th")
            elif any(self.row):
                t["rows"].append(self.row)
            self.row = None
        elif tag == "table":
            t = self.stack.pop()
            if not t["cols"] and t.get("_th"):
                t["cols"] = t.pop("_th")
            self.tables.append(t)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def parse_notas(page: str) -> list[dict]:
    """-> [{"evaluacion", "nota" (texto o ""), "fecha", "fila"}] de las tablas con columna «Evaluación»."""
    if 'class="strong"' in page or "tiempo_rel" in page:  # formato real de U-Cursos
        u = _UcursosNotas()
        u.feed(page)
        if u.rows:
            return u.rows
    p = _Tables()
    p.feed(page)
    out = []
    for t in p.tables:
        cols = [_plain(c) for c in t["cols"]]
        if not any("evaluaci" in c for c in cols):
            continue
        if len(t["rows"]) > 40:
            continue  # lista de alumnos (vista de auxiliar), no las notas propias
        i_ev = next(i for i, c in enumerate(cols) if "evaluaci" in c)
        i_nota = next((i for i, c in enumerate(cols) if re.search(r"\bnota\b|calificaci|promedio", c)), None)
        for row in t["rows"]:
            if len(row) <= i_ev or not row[i_ev] or row == t["cols"]:
                continue
            nota = ""
            if i_nota is not None and i_nota < len(row) and GRADE.match(row[i_nota]):
                nota = row[i_nota]
            else:
                nota = next((c for i, c in enumerate(row) if i != i_ev and GRADE.match(c)), "")
            out.append({"evaluacion": _html.unescape(row[i_ev]), "nota": nota.strip().replace(".", ","),
                        "fila": " | ".join(row)})
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
    """Revisa las notas de todos los ramos. -> {"nuevas": [...], "errores": [...], "revisados": n}.

    Una nota es «nueva» si aparece una evaluación con nota que antes no tenía nota (o no existía), o si
    la nota cambió. La primera vez que se revisa un ramo solo se guarda lo que hay."""
    global LAST_URL
    fetcher = fetcher or fetch
    now = now or datetime.now()
    st = load_state()
    if st.get("formato") != FORMATO:  # lo guardado con un lector anterior no sirve para comparar: empezar de nuevo
        st = {"formato": FORMATO, "ramos": {}, "recientes": [], "fechas": {}}
    st.setdefault("ramos", {})
    st.setdefault("recientes", [])
    st.setdefault("fechas", {})
    st.setdefault("auxiliar", [])
    nuevas, errores, n = [], [], 0
    for c in (course_list if course_list is not None else courses()):
        try:
            LAST_URL = ""
            page = fetcher(f"{c['path']}/notas/")
            if LAST_URL and "/notas/" in LAST_URL and not LAST_URL.rstrip("/").endswith("alumno"):
                if c["path"] not in st["auxiliar"]:  # ramo donde es auxiliar: la página es de todo el curso
                    st["auxiliar"].append(c["path"])
                continue
            rows = parse_notas(page)
        except SessionExpired:
            raise
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{c['nombre']}: {exc}")
            continue
        n += 1
        old = st["ramos"].get(c["path"])
        cur = {r["evaluacion"]: r["nota"] for r in rows}
        st["fechas"][c["path"]] = {r["evaluacion"]: r.get("fecha", "") for r in rows if r.get("fecha")}
        if old is not None:
            for ev, nota in cur.items():
                if nota and old.get(ev, "") != nota:
                    item = {"ramo": c["nombre"], "code": c["code"], "evaluacion": ev, "nota": nota,
                            "antes": old.get(ev, ""), "visto": now.isoformat(timespec="minutes")}
                    nuevas.append(item)
        st["ramos"][c["path"]] = {**(old or {}), **cur}
    st["recientes"] = (nuevas + st["recientes"])[:30]
    st["revisado"] = now.isoformat(timespec="minutes")
    save_state(st)
    return {"nuevas": nuevas, "errores": errores, "revisados": n}


FORMATO = 3
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]


def say_aviso(i: dict) -> str:
    """Para avisos que llegan solos (voz, HUD, Telegram): ramo y evaluación, SIN la nota (pedido del usuario, 17-11).
    La nota solo se dice si la pregunta («¿tengo notas nuevas?», «mis notas de Redes»)."""
    return f"{i['ramo']}: {i['evaluacion']}"


def say_item(i: dict) -> str:
    cambio = f" (antes {i['antes']})" if i.get("antes") else ""
    return f"{i['ramo']}: {i['evaluacion']}, un {i['nota']}{cambio}"


def say_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day} de {_MESES[d.month - 1]}"
    except ValueError:
        return iso


def latest(course_list: list[dict] | None = None, path: str | None = None) -> dict | None:
    """La nota más reciente: la última que Atlas vio aparecer, o si no, la de fecha más nueva en U-Cursos."""
    st = load_state()
    names = {c["path"]: c for c in (course_list if course_list is not None else courses())}
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
                c = names.get(p, {"nombre": p.split("/")[-2], "code": p.split("/")[-2]})
                best = {"ramo": c["nombre"], "code": c["code"], "evaluacion": ev, "nota": nota, "fecha": f}
    return best


def course_grades(name: str, course_list: list[dict] | None = None) -> tuple[dict | None, dict]:
    """Ramo que calza con el nombre o código dicho, y las notas guardadas de ese ramo."""
    q = _plain(name)
    cl = course_list if course_list is not None else courses()
    best = next((c for c in cl if _plain(c["code"]) in q.replace(" ", "")), None) or next(
        (c for c in cl if any(len(w) > 3 and w in q for w in re.findall(r"[a-z]+", _plain(c["nombre"])))), None)
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
            if "msedge" in (proc.info.get("name") or "").lower() and "ucursos-profile" in " ".join(proc.info.get("cmdline") or []):
                proc.kill()
    except Exception:  # noqa: BLE001
        pass


def login(edge: str, log=print, timeout: float = 600) -> str:
    """Abre U-Cursos en una ventana propia; espera a que el usuario inicie sesión y guarda las cookies.
    -> "ok" | "timeout" | "error: …". Bloquea: llamarlo en un hilo."""
    profile = os.path.join(os.environ.get("LOCALAPPDATA", str(HERE)), "Atlas", "ucursos-profile")
    _kill_login_window()
    if os.environ.get("ATLAS_PRUEBAS") == "1":  # las pruebas nunca abren la ventana de inicio de sesión
        return "error: pruebas"
    subprocess.Popen([edge, f"--app={BASE}/", f"--user-data-dir={profile}", f"--remote-debugging-port={CDP_PORT}",
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
        if not any("u-cursos.cl" in p.get("url", "").split("/")[2:3][0] for p in pages if "//" in p.get("url", "")):
            continue  # sigue en la página de Cuenta UChile
        try:
            ws = _cdp_json("/json/version")["webSocketDebuggerUrl"]
            cookies = _cdp_call(ws, "Storage.getCookies").get("cookies") or []
            n = save_session(cookies)
            if not re.search(r"/usuario/[0-9a-f]{32}/", fetch("/")):  # comprobar que la sesión sirve
                raise SessionExpired("aún sin sesión")
        except SessionExpired:
            forget_session()
            continue  # aún no termina de entrar
        except Exception as exc:  # noqa: BLE001
            log(f"U-Cursos: no pude guardar la sesión ({exc})")
            continue
        log(f"U-Cursos: sesión guardada ({n} cookies)")
        _kill_login_window()
        return "ok"
    _kill_login_window()
    return "timeout"

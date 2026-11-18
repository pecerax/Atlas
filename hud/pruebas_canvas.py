"""Pruebas del conector de notas de Canvas contra un Canvas simulado (servidor local que imita la API oficial).

No toca la red ni los archivos del usuario: usa una carpeta temporal y guarda la «sesión» sin cifrar.
Imita lo que hace Canvas de verdad: el prefijo «while(1);», la paginación con el encabezado Link, el 401
{"status":"unauthenticated"} cuando la sesión vence, la redirección a /login y la cookie de sesión que se renueva.

Uso:  python pruebas_canvas.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import atlas_canvas_notas as C  # noqa: E402


# ----------------------------------------------------------------------------- Canvas simulado
class Fake:
    session = "s1"            # valor válido de la cookie canvas_session
    guard = True              # anteponer while(1);
    rotate = False            # renovar la cookie en cada respuesta
    redirect_login = False    # responder como cuando Canvas manda al inicio de sesión (HTML)
    courses = []
    assignments = {}          # id de curso -> lista de evaluaciones
    page_size = 100
    seen_cookies = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        Fake.seen_cookies.append(self.headers.get("Cookie", ""))
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/login":
            return self._send(200, "<html>login</html>", "text/html")
        if Fake.redirect_login:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        cookies = dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p)
        if cookies.get("canvas_session") != Fake.session:
            return self._send(401, json.dumps({"status": "unauthenticated", "errors": [{"message": "user authorization required"}]}))
        headers = {}
        if Fake.rotate:
            Fake.session = Fake.session + "x"
            headers["Set-Cookie"] = f"canvas_session={Fake.session}; path=/; secure; HttpOnly"
        if u.path == "/api/v1/users/self":
            data, link = {"id": 7, "name": "Alumno"}, ""
        elif u.path == "/api/v1/courses":
            assert q.get("enrollment_type") == ["student"], q
            data, link = Fake.courses, ""
        elif u.path.startswith("/api/v1/courses/") and u.path.endswith("/assignments"):
            cid = int(u.path.split("/")[4])
            assert q.get("include[]") == ["submission"], q
            items = Fake.assignments.get(cid)
            if items is None:
                return self._send(404, json.dumps({"errors": [{"message": "The specified resource does not exist."}]}))
            page = int(q.get("page", ["1"])[0])
            n = Fake.page_size
            data = items[(page - 1) * n: page * n]
            link = ""
            if page * n < len(items):
                nq = dict(q, page=[str(page + 1)])
                nxt = f"http://{self.headers['Host']}{u.path}?{urllib.parse.urlencode(nq, doseq=True)}"
                link = f'<{nxt}>; rel="next", <{nxt}>; rel="last"'
        else:
            return self._send(404, json.dumps({"errors": [{"message": "not found"}]}))
        if link:
            headers["Link"] = link
        body = json.dumps(data)
        self._send(200, ("while(1);" if Fake.guard else "") + body, headers=headers)


def asg(i, name, kind="points", pts=10, score=None, grade=None, excused=False, published=True, graded_at=None):
    sub = {"score": score, "grade": grade, "excused": excused, "graded_at": graded_at,
           "workflow_state": "graded" if score is not None or grade else "unsubmitted"}
    return {"id": i, "name": name, "grading_type": kind, "points_possible": pts, "published": published,
            "due_at": "2026-11-10T23:59:00Z", "submission": sub}


# ----------------------------------------------------------------------------- utilidades
class FakeSecretos:
    """Guarda en texto plano dentro de la carpeta temporal (como el respaldo de las pruebas de Atlas)."""

    @staticmethod
    def cargar_json(p):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def guardar_json(p, d):
        Path(p).write_text(json.dumps(d), encoding="utf-8")
        return False

    @staticmethod
    def borrar_json(p):
        Path(p).unlink(missing_ok=True)


fallos: list[str] = []


def ok(cond, nombre):
    print(("  ok    " if cond else "  FALLA ") + nombre)
    if not cond:
        fallos.append(nombre)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas_canvas_"))
    C.HERE = tmp
    C.PRUEBA = True
    C._secretos = lambda: FakeSecretos
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    print("Dirección del Canvas")
    ok(C.normalize_url("conecta canvas cursos.canvas.uc.cl") == "https://cursos.canvas.uc.cl", "host suelto")
    ok(C.normalize_url("https://udp.instructure.com/courses/12") == "https://udp.instructure.com", "url con ruta")
    ok(C.normalize_url("conecta Canvas Network") == "https://learn.canvas.net", "alias Canvas Network")
    ok(C.normalize_url("https://www.canvas.net/browse/x") == "https://learn.canvas.net", "catálogo -> learn")
    ok(C.normalize_url("conecta canvas") == "", "sin dirección")

    print("Sin sesión")
    ok(not C.has_session(), "has_session falso")
    try:
        C.fetch_json("/api/v1/users/self")
        ok(False, "sin sesión lanza SessionExpired")
    except C.SessionExpired:
        ok(True, "sin sesión lanza SessionExpired")

    print("Guardar sesión")
    n = C.save_session(base, [
        {"name": "canvas_session", "value": "s1", "domain": "127.0.0.1"},
        {"name": "_csrf_token", "value": "t", "domain": "127.0.0.1"},
        {"name": "otra", "value": "x", "domain": ".google.com"},
        {"name": "sso", "value": "y", "domain": "login.uc.cl"},
    ])
    ok(n == 2, "solo guarda las cookies del Canvas conectado")
    ok(C.has_session() and C.base_url() == base, "sesión y dirección guardadas")
    me, _ = C.fetch_json("/api/v1/users/self")
    ok(me.get("id") == 7, "users/self con prefijo while(1);")
    Fake.guard = False
    me, _ = C.fetch_json("/api/v1/users/self")
    ok(me.get("id") == 7, "users/self sin prefijo")
    Fake.guard = True
    try:
        C.fetch_json("https://otro.ejemplo.cl/api/v1/users/self")
        ok(False, "no habla con otro servidor")
    except ValueError:
        ok(True, "no habla con otro servidor")

    print("Notas")
    Fake.courses = [
        {"id": 1, "name": "Redes de Computadores", "course_code": "IIC2001"},
        {"id": 2, "name": "Passport to Canvas", "course_code": "Passport"},
        {"id": 3, "access_restricted_by_date": True},
    ]
    Fake.assignments = {
        1: [asg(10, "Control 1", score=None), asg(11, "Tarea 1", kind="points", pts=7, score=5.5, grade="5.5"),
            asg(12, "Borrador", published=False)],
        2: [asg(20, "Quiz Denver", pts=5, score=None), asg(21, "Encuesta", kind="not_graded", pts=0)],
    }
    cl = C.courses()
    ok([c["nombre"] for c in cl] == ["Passport to Canvas", "Redes de Computadores"], "cursos (omite el restringido)")
    r = C.check(now=datetime(2026, 11, 17, 22, 0))
    ok(r == {"nuevas": [], "errores": [], "revisados": 2}, "primera revisión: solo guarda")
    st = json.loads((tmp / "canvas_notas.json").read_text(encoding="utf-8"))
    red = st["ramos"]["127.0.0.1/courses/1"]
    ok(red == {"Control 1": "", "Tarea 1": "5,5"}, "estado guardado (sin la no publicada, escala 1-7)")

    # salen dos notas y cambia una
    Fake.assignments[1][0] = asg(10, "Control 1", pts=60, score=48, grade="48", graded_at="2026-11-17T21:00:00Z")
    Fake.assignments[1][1] = asg(11, "Tarea 1", pts=7, score=6.1, grade="6.1")
    Fake.assignments[2][0] = asg(20, "Quiz Denver", pts=5, score=5, grade="5")
    r = C.check(now=datetime(2026, 11, 17, 22, 20))
    got = {(i["ramo"], i["evaluacion"], i["nota"], i["antes"]) for i in r["nuevas"]}
    ok(got == {("Redes de Computadores", "Control 1", "48 de 60", ""),
               ("Redes de Computadores", "Tarea 1", "6,1", "5,5"),
               ("Passport to Canvas", "Quiz Denver", "5 de 5", "")}, f"notas nuevas detectadas: {sorted(got)}")
    r2 = C.check(now=datetime(2026, 11, 17, 22, 40))
    ok(r2["nuevas"] == [], "no repite las mismas notas")
    aviso = C.say_aviso(next(i for i in r["nuevas"] if i["evaluacion"] == "Control 1"))
    ok(aviso == "Redes de Computadores: Control 1" and "48" not in aviso, "el aviso no dice la nota")
    ok(C.say_item(next(i for i in r["nuevas"] if i["evaluacion"] == "Tarea 1")) ==
       "Redes de Computadores: Tarea 1, un 6,1 (antes 5,5)", "say_item escala chilena")
    c, g = C.course_grades("mis notas de redes")
    ok(c and c["code"] == "IIC2001" and g.get("Control 1") == "48 de 60", "buscar curso por nombre")
    ok(C.course_grades("¿tengo notas nuevas en Canvas?")[0] is None, "«en Canvas» no elige el curso «Passport to Canvas»")
    ok(C.course_grades("notas de passport")[0]["code"] == "Passport", "pero «passport» sí")
    ok((C.latest() or {}).get("evaluacion") in ("Control 1", "Tarea 1", "Quiz Denver"), "latest")

    print("Paginación")
    Fake.page_size = 2
    Fake.assignments[1] = [asg(100 + k, f"Quiz {k}", pts=10, score=k, grade=str(k)) for k in range(1, 6)]
    rows = C.course_rows({"id": 1})
    ok([x["evaluacion"] for x in rows] == [f"Quiz {k}" for k in range(1, 6)], "junta las 3 páginas (encabezado Link)")
    Fake.page_size = 100

    print("Errores por curso")
    Fake.courses.append({"id": 9, "name": "Curso sin acceso", "course_code": "X9"})
    r = C.check()
    ok(r["revisados"] == 2 and len(r["errores"]) == 1 and "Curso sin acceso" in r["errores"][0], "un curso con error no corta los demás")
    Fake.courses.pop()

    print("Formato de notas")
    F = C.format_grade
    ok(F(asg(1, "a", kind="percent", pts=100, score=85, grade="85%")) == "85%", "porcentaje")
    ok(F(asg(1, "a", kind="letter_grade", pts=100, score=91, grade="A-")) == "A-", "letra")
    ok(F(asg(1, "a", kind="pass_fail", pts=1, score=1, grade="complete")) == "aprobado", "aprobado")
    ok(F(asg(1, "a", excused=True)) == "eximido", "eximido")
    ok(F(asg(1, "a", pts=10, score=7.25, grade="7.25")) == "7,25 de 10", "puntos con decimales")
    ok(F(asg(1, "a", pts=None, score=3, grade="3")) == "3", "puntos sin máximo")
    ok(F(asg(1, "a")) == "", "sin nota")

    print("Cookie renovada")
    Fake.rotate = True
    C.fetch_json("/api/v1/users/self")
    Fake.rotate = False
    saved = {c["name"]: c["value"] for c in C._load_session()["cookies"]}
    ok(saved["canvas_session"] == Fake.session, "guarda la cookie nueva que manda Canvas")
    me, _ = C.fetch_json("/api/v1/users/self")
    ok(me.get("id") == 7, "y la siguiente consulta funciona con ella")

    print("Sesión vencida")
    Fake.session = "otra"
    for nombre, fn in (("401 unauthenticated", lambda: C.check()),):
        try:
            fn()
            ok(False, nombre)
        except C.SessionExpired:
            ok(True, nombre)
    Fake.redirect_login = True
    try:
        C.fetch_json("/api/v1/users/self")
        ok(False, "redirección a /login")
    except C.SessionExpired:
        ok(True, "redirección a /login")
    Fake.redirect_login = False

    print("Otra universidad")
    Fake.session = "s1"
    C.save_session(base.replace("127.0.0.1", "localhost"), [{"name": "canvas_session", "value": "s1", "domain": "localhost"}])
    C.check(course_list=[])
    st = json.loads((tmp / "canvas_notas.json").read_text(encoding="utf-8"))
    ok(st["ramos"] == {} and "localhost" in st["url"], "al cambiar de Canvas empieza de cero")

    print("Seguridad: sin cifrado no guarda (fuera de pruebas)")
    C.PRUEBA = False
    try:
        C.save_session(base, [{"name": "canvas_session", "value": "s1", "domain": "127.0.0.1"}])
        ok(False, "rechaza guardar en texto plano")
    except RuntimeError:
        ok(True, "rechaza guardar en texto plano")
    ok(not (tmp / "canvas_sesion.json").exists(), "y no deja el archivo")
    C.PRUEBA = True

    srv.shutdown()
    print()
    print("TODO BIEN" if not fallos else f"{len(fallos)} FALLA(S): " + "; ".join(fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

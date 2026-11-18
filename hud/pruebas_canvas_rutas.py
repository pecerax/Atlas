"""Pruebas de las frases de Canvas en Atlas (después de aplicar patch_canvas.py).

Usa el arranque de pruebas_atlas.py (carpeta temporal, herramientas falsas) y el Canvas simulado de pruebas_canvas.py.
Uso:  python pruebas_canvas_rutas.py      (en la carpeta hud, junto a pruebas_atlas.py)
"""
from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pruebas_atlas as PA  # noqa: E402
import pruebas_canvas as PC  # noqa: E402

fallos: list[str] = []


def ok(cond, nombre, detalle=""):
    print(("  ok    " if cond else "  FALLA ") + nombre + ("" if cond else f"\n         {detalle}"))
    if not cond:
        fallos.append(nombre)


def main() -> int:
    H, tmp = PA.preparar()
    j = PA.nuevo(H)
    C = j._canvas()
    C.HERE, C.PRUEBA = tmp, True
    C._secretos = lambda: PC.FakeSecretos
    U = j._ucursos()
    U.HERE = tmp
    srv = ThreadingHTTPServer(("127.0.0.1", 0), PC.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    PC.Fake.courses = [{"id": 1, "name": "Redes de Computadores", "course_code": "IIC2001"},
                       {"id": 2, "name": "Passport to Canvas", "course_code": "PD-0128"}]
    PC.Fake.assignments = {1: [PC.asg(10, "Control 1", pts=60), PC.asg(11, "Quiz 1", pts=10, score=8, grade="8")], 2: []}
    abiertas = []
    j._canvas_login = lambda url: abiertas.append(url)
    j._ucursos_login = lambda: abiertas.append("ucursos")

    def ruta(frase):
        r = j.route(frase)
        return r[0], (r[1] or {}).get("reply", "")

    print("Conectar")
    rt, rep = ruta("conecta Canvas")
    ok(rt == "notas" and "dirección" in rep and not abiertas, "sin dirección: la pregunta", rep)
    rt, rep = ruta("conecta Canvas cursos.canvas.uc.cl")
    ok(abiertas[-1:] == ["https://cursos.canvas.uc.cl"] and "cursos.canvas.uc.cl" in rep, "con dirección: abre la ventana", rep)
    rt, rep = ruta("conéctate a Canvas Network")
    ok(abiertas[-1:] == ["https://learn.canvas.net"], "Canvas Network", rep)
    rt, rep = ruta("conecta U-Cursos")
    ok(abiertas[-1:] == ["ucursos"], "conecta U-Cursos sigue yendo a U-Cursos", rep)

    print("Frases que no son de Canvas")
    for frase in ("abre canva", "toma nota: comprar pan", "lee mis notas de voz"):
        rt, rep = ruta(frase)
        ok(rt != "notas", f"«{frase}» no va a notas", f"{rt}: {rep}")

    print("Canvas conectado, U-Cursos no")
    U.has_session = lambda: False
    rt, rep = ruta("¿tengo notas nuevas?")
    ok(rt == "notas" and "Aún no estoy conectado a Canvas" not in rep and "U-Cursos" in rep, "sin Canvas: responde U-Cursos como antes", rep)
    rt, rep = ruta("mis notas de canvas")
    ok("conecta Canvas" in rep and "opcionales" in rep, "pide conectar Canvas si lo nombra (las dos son opcionales)", rep)
    C.save_session(base, [{"name": "canvas_session", "value": PC.Fake.session, "domain": "127.0.0.1"}])
    rt, rep = ruta("¿tengo notas nuevas?")
    ok(rt == "notas" and "Canvas" in rep and "2 cursos" in rep, "responde con Canvas", rep)
    PC.Fake.assignments[1][0] = PC.asg(10, "Control 1", pts=60, score=51, grade="51")
    rt, rep = ruta("¿salió alguna nota?")
    ok("Control 1, 51 de 60" in rep, "dice la nota nueva cuando la pregunta", rep)
    rt, rep = ruta("¿tengo notas nuevas en Canvas?")
    ok("Passport" not in rep, "«en Canvas» no se confunde con «Passport to Canvas»", rep)
    rt, rep = ruta("¿cuáles son mis notas de redes?")
    ok("Redes de Computadores" in rep and "Quiz 1, 8 de 10" in rep, "notas de un curso", rep)
    rt, rep = ruta("¿cuál fue mi última nota?")
    ok("Control 1" in rep, "última nota", rep)

    print("Nota ya avisada por la revisión automática")
    PC.Fake.assignments[1].append(PC.asg(13, "Quiz 3", pts=10, score=7, grade="7"))
    C.check()  # la revisión de cada 20 minutos la ve primero (y la avisa)
    rt, rep = ruta("¿tengo notas nuevas en Canvas?")
    ok("Quiz 3, 7 de 10" in rep and "24 horas" in rep, "al preguntar igual la dice (últimas 24 horas)", rep)

    print("Los dos conectados")
    U.has_session = lambda: True
    U.check = lambda *a, **k: {"nuevas": [], "errores": [], "revisados": 4}
    j._uc_mark = lambda *a, **k: None
    PC.Fake.assignments[1].append(PC.asg(12, "Quiz 2", pts=10, score=9, grade="9"))
    rt, rep = ruta("¿tengo notas nuevas?")
    ok(rep.startswith("No hay notas nuevas, señor. Revisé 4 ramos.") and "Quiz 2, 9 de 10" in rep,
       "U-Cursos + Canvas en una sola respuesta", rep)
    rt, rep = ruta("¿tengo notas nuevas en u cursos?")
    ok("Canvas" not in rep, "U-Cursos nombrado: responde solo U-Cursos", rep)
    rt, rep = ruta("mis notas de canvas")
    ok("Canvas" in rep and "ramos" not in rep, "Canvas nombrado: solo Canvas", rep)

    print("Sesión vencida")
    PC.Fake.session = "vencida"
    U.has_session = lambda: False
    rt, rep = ruta("¿tengo notas nuevas?")
    ok("sesión de Canvas expiró" in rep, "avisa que hay que reconectar", rep)

    srv.shutdown()
    print()
    print("TODO BIEN" if not fallos else f"{len(fallos)} FALLA(S): " + "; ".join(fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

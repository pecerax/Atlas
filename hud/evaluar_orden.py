"""Evaluación de la herramienta «orden»: ¿el modelo decide bien cuándo actuar y reescribe bien la orden?

Cada caso se le manda al modelo real (Ollama) con las instrucciones de Atlas y las herramientas que ve en el uso
real. Si llama a «orden», esa orden pasa por las reglas de Atlas en una carpeta de prueba (pruebas_atlas.preparar:
nada se envía, nada se llama, nada toca sus archivos) y se revisa qué regla la tomó.
Uso: ..\\src\\.venv\\Scripts\\python.exe evaluar_orden.py   (necesita Ollama abierto). ATLAS_REP=n repeticiones.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hud_server as _H0  # noqa: E402

REWRITE = _H0.rewrite_order  # la real (preparar() la reemplaza por una sin modelo)
import pruebas_atlas as P  # noqa: E402

H, TMP = P.preparar()
import atlas_contactos as CT  # noqa: E402

CT.upsert({"nombre": "Benjamín Correa", "apodos": ["Benji"], "telefono": "+56 9 1111 2222"})
CT.upsert({"nombre": "Felipe Morales", "apodos": ["Pipe"], "telefono": "+56 9 3333 4444", "discord": "pipe_a"})

import evaluar_modelo as E  # noqa: E402

REP = int(os.environ.get("ATLAS_REP", "2"))

# (frase del usuario, historial [(rol, texto)], ruta esperada: regex sobre la ruta, o None = no debe usar «orden»)
CASOS = [
    ("Manda un... Hola Benji a WhatsApp. A Benji", [], r"^(discord|contactos)$"),  # los mensajes los toma la regla «discord»
    ("Sí, hazlo", [("user", "Manda un hola a Benji"), ("assistant", "¿Por dónde se lo envío, señor: WhatsApp, Discord o Telegram?"),
                   ("user", "Por WhatsApp")], r"^(discord|contactos)$"),
    ("dile a la Cami por telegram que ya llegué", [], r"^(discord|contactos)$"),
    ("estoy cansado hoy", [], None),
    ("¿me recomiendas una película?", [], None),
    ("oye necesito que le escribas a pipe por discord que voy atrasado", [], r"^(discord|contactos)$"),
    ("eh... el Felipe, llámalo", [], r"^(contactos|llamada)$"),
    ("acuérdame como en media hora de sacar la ropa de la lavadora", [], r"^recordatorio$"),
    ("tengo que comprar pan, anótalo pa no olvidarme", [], r"^pendientes$"),
    ("ponme algo de Ado", [], r"^(?!\(ninguna).+$"),  # cualquier regla que la tome
    ("¿quién escribió Cien años de soledad?", [], None),
    ("gracias Atlas", [], None),
    ("cuéntame un chiste", [], None),
]


def specs() -> list[dict]:
    out = []
    try:
        from openjarvis.core.registry import ToolRegistry

        for name in [t.strip() for t in H.TOOLS.split(",") if t.strip()]:
            if ToolRegistry.contains(name):
                t = ToolRegistry.get(name)
                t = t() if isinstance(t, type) else t
                out.append(t.spec)
    except Exception as exc:  # noqa: BLE001
        print(f"(sin las otras herramientas: {exc})")
    out.append(H._make_order_tool()(None).spec)
    return [{"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
            for s in out]


def ask(model: str, system: str, hist: list, user: str, tools: list) -> tuple[dict, float]:
    body = json.dumps({"model": model, "stream": False, "think": False,
                       "options": {"temperature": float(os.environ.get("ATLAS_TEMP", "0.7"))},
                       "tools": tools,
                       "messages": [{"role": "system", "content": system}]
                       + [{"role": r, "content": c} for r, c in hist]
                       + [{"role": "user", "content": H.build_turn(user)}]}).encode()
    req = urllib.request.Request(E.OLLAMA + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("message") or {}, time.time() - t0


def main() -> int:
    model = E.modelo()
    system = (H.PERSONA + "\n\n" + H.user_context_prompt()).strip()
    tools = specs()
    print(f"Modelo {model}, herramientas: {', '.join(t['function']['name'] for t in tools)}. {len(CASOS)} casos x {REP}.\n")
    ok_total = total = 0
    tiempos = []
    if "--reescribir" in sys.argv:  # el paso corto que usa Atlas cuando ninguna regla calza
        for user, hist, want in CASOS:
            for _ in range(REP):
                t0 = time.time()
                orden = REWRITE(user, hist, model)
                dt = time.time() - t0
                tiempos.append(dt)
                route = None
                if orden:
                    j = P.nuevo(H)
                    route, routed, _ = j._route(H.canonicalize_people(H.canonicalize(H.normalize_order(orden))))
                    route = route if routed and routed.get("reply") else "(ninguna regla)"
                good = (route is not None and re.search(want, route)) if want else not orden
                ok_total += bool(good)
                total += 1
                print(f"  {'ok   ' if good else 'FALLA'} {dt:4.1f}s  {user[:48]:48}  «{orden or 'CHARLA'}» -> {route}")
        print(f"\n{ok_total}/{total} ({100 * ok_total // max(total, 1)}%). Tiempo medio {sum(tiempos) / len(tiempos):.1f}s.")
        return 0
    for user, hist, want in CASOS:
        for _ in range(REP):
            msg, dt = ask(model, system, hist, user, tools)
            tiempos.append(dt)
            calls = [c.get("function") or {} for c in msg.get("tool_calls") or []]
            orden = next((c.get("arguments", {}).get("orden") for c in calls if c.get("name") == "orden"), None)
            other = [c.get("name") for c in calls if c.get("name") != "orden"]
            route = None
            if orden:
                j = P.nuevo(H)
                j._order_reply, j._order_calls = None, 0
                _ok, _txt = j.order_tool(str(orden))
                route = j._order_reply[0] if j._order_reply else "(ninguna regla)"
            good = (route is not None and re.search(want, route)) if want else (orden is None)
            ok_total += bool(good)
            total += 1
            what = f"orden «{orden}» -> {route}" if orden else (f"herramientas {other}" if other else
                                                                 f"texto: {(msg.get('content') or '')[:90]!r}")
            print(f"  {'ok   ' if good else 'FALLA'} {dt:4.1f}s  {user[:48]:48}  {what}")
    print(f"\n{ok_total}/{total} ({100 * ok_total // max(total, 1)}%). Tiempo medio {sum(tiempos) / len(tiempos):.1f}s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

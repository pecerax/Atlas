"""Pruebas de atlas_vigilancias.py (sin correo ni U-Cursos reales). Correr con el Python de Atlas:
    ..\\src\\.venv\\Scripts\\python.exe pruebas_vigilancias.py
"""
import os
import re
import sys
os.environ["ATLAS_PRUEBAS"] = "1"  # nada abre ventanas visibles
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_vigilancias as V  # noqa: E402

fallas, total = [], 0


def ok(nombre, cond):
    global total
    total += 1
    if not cond:
        fallas.append(nombre)


# --- frases (las de voz, tal como llegan) ---
P = {
    "Avísame cuando me llegue el correo de Google Takeout": ("correo", "google takeout"),
    "Atlas, estoy esperando un correo de Falabella sobre la boleta": ("correo", "falabella"),
    "avisame cuando llegue un correo de Banco Estado": ("correo", "banco estado"),
    "avísame cuando me escriba Andrea": ("mensaje", "andrea"),  # 18-11: sin decir correo = WhatsApp/Telegram
    "¿Qué correos estoy esperando?": ("listar", None),
    "qué estás vigilando": ("listar", None),
    "ya no esperes el correo de Falabella": ("cancelar", "falabella"),
    "cancela la vigilancia de Takeout": ("cancelar", "takeout"),
    "avísame cuando publiquen la nota del control 2 de Lenguajes": ("nota", None),
    "Avísame cuando haya una publicación nueva en Lenguajes": ("publicacion", None),
    "avísame en 10 minutos": (None, None),
    "avísame cuando llegue a la casa": (None, None),
    "¿tengo notas nuevas?": (None, None),
    "toma una nota": (None, None),
    "¿tengo correos sin leer?": (None, None),
    "recuérdame mañana a las 9 revisar el correo": (None, None),
    "mándale a Benji por WhatsApp que ya llegué": (None, None),
}
for frase, (op, q) in P.items():
    r = V.parse(frase)
    ok(f"parse {frase!r} -> {r}", (r or {}).get("op") == op and (q is None or q in (r.get("quien") or r.get("que") or "")))

# --- correos ---
tk = V.correo_watch("google takeout")
ok("takeout es", V.match_mail(tk, "Google <no-reply@accounts.google.com>", "Tus datos de Google están listos para descargar"))
ok("takeout inglés", V.match_mail(tk, "Google Takeout <noreply@google.com>", "Your Google data is ready to download"))
ok("takeout real 16-11", V.match_mail(tk, "Google <no-reply@accounts.google.com>", "Ya puedes descargar tus datos de Google"))
ok("la solicitud no es el aviso", not V.match_mail(
    tk, "Google Takeout <noreply@google.com>", "Se ha solicitado la creación de un archivo de tus datos de Google"))
ok("alerta google no es takeout", not V.match_mail(tk, "Google <no-reply@accounts.google.com>", "Alerta de seguridad"))
ok("otro remitente no", not V.match_mail(tk, "Falabella <x@falabella.cl>", "Tus datos están listos"))
fb = V.correo_watch("Falabella", "la boleta")
ok("falabella boleta", V.match_mail(fb, "Falabella <x@falabella.cl>", "Tu boleta electrónica"))
ok("falabella sin boleta no", not V.match_mail(fb, "Falabella <x@falabella.cl>", "Ofertas de la semana"))
ok("evaluación", V.eval_words("la nota del primer control de evalua") == ["control", "1"])

# --- nombres ambiguos («un correo de Pablo»): pregunta cuál, por remitentes que ya le han escrito ---
pablos = [{"nombre": "Pablo Fuentes", "correo": "pfuentes@ug.uchile.cl", "cuenta": "u", "n": 5},
          {"nombre": "Pablo Lagos", "correo": "pablo.lagos@gmail.com", "cuenta": "g", "n": 2}]
r = V.resolver("Pablo", cands=pablos)
ok("varios -> pregunta", "ask" in r and "Pablo Fuentes, de ug.uchile.cl" in r["ask"] and "Pablo Lagos" in r["ask"])
ok("«el segundo»", V.respuesta("el segundo", pablos) == [pablos[1]])
ok("«Pablo Fuentes»", V.respuesta("Pablo Fuentes", pablos) == [pablos[0]])
ok("«el de la chile» no adivina mal", V.respuesta("el de uchile", pablos) == [pablos[0]])
ok("«cualquiera»", V.respuesta("cualquiera", pablos) == pablos)
ok("«no sé» no se entiende", V.respuesta("no sé", pablos) is None)
w = V.elegir(r["base"], [pablos[0]])
ok("elegido: solo su correo", w["de"] == ["pfuentes@ug.uchile.cl", "pablo fuentes"] and w["nombre"] == "Pablo Fuentes"
   and V.match_mail(w, "Pablo Fuentes <pfuentes@ug.uchile.cl>", "Hola") and not V.match_mail(w, "Pablo Lagos <pablo.lagos@gmail.com>", "Hola"))
r = V.resolver("Pablo", cands=pablos[:1])
ok("uno solo -> directo", r["watch"]["de"][0] == "pfuentes@ug.uchile.cl")
fal = [{"nombre": "Falabella", "correo": "ofertas@falabella.cl", "cuenta": "g", "n": 9},
       {"nombre": "Falabella.com", "correo": "boletas@falabella.cl", "cuenta": "g", "n": 3}]
r = V.resolver("Falabella", cands=fal)
ok("empresa con varios buzones -> su dominio", r.get("watch", {}).get("de") == ["@falabella.cl"])
r = V.resolver("Zacarías", cands=[])
ok("nadie le ha escrito -> por nombre", r.get("nuevo") and r["watch"]["todas"] == ["zacarias"])
# --- nombre mal oído (uso real 16-11): «Necesito que estés atento así llega un mail de la Tanus Hack» = Platanus Hack ---
r = V.parse("Necesito que estés atento así llega un mail de la Tanus Hack")
ok(f"atento así llega -> {r}", r and r["op"] == "correo" and r["quien"] == "tanus hack")
for f in ["Estate pendiente por si me llega un correo de Falabella", "vigila si llega un mail de Banco Estado",
          "atento a si llega un correo de la U"]:
    ok(f"parse {f!r}", (V.parse(f) or {}).get("op") == "correo")
ok("«estoy atento a la clase» no", V.parse("estoy atento a la clase") is None)
recientes = [{"nombre": "Platanus Hack", "correo": "hola@platanus.cl", "cuenta": "g", "n": 4},
             {"nombre": "Platanus Hack", "correo": "equipo@platanus.cl", "cuenta": "g", "n": 1},
             {"nombre": "LinkedIn", "correo": "jobs@linkedin.com", "cuenta": "g", "n": 40},
             {"nombre": "Tannat Wines", "correo": "info@tannat.cl", "cuenta": "g", "n": 2},
             {"nombre": "Hack Club", "correo": "team@hackclub.com", "cuenta": "g", "n": 3}]
pc = V.parecidos(V._words(V.correo_watch("la tanus hack")["nombre"]), recientes)
ok(f"tanus hack ~ Platanus Hack: {[(c['nombre'], round(c['s'], 2)) for c in pc]}", pc and pc[0]["nombre"] == "Platanus Hack")
r = V.resolver("la tanus hack", cands=pc[:1])
ok(f"pregunta antes de usarlo: {r.get('ask')}", "Platanus Hack" in r.get("ask", "") and "¿Se refiere a ese?" in r["ask"])
ok("«sí» lo elige", V.respuesta("sí", r["cands"]) == r["cands"])
ok("«no» no lo elige", V.respuesta("no", r["cands"]) is None)
w = V.elegir(r["base"], r["cands"])
ok("vigila Platanus Hack desde cualquier dirección", V.match_mail(w, "Platanus Hack <equipo@platanus.cl>", "Resultados")
   and w["nombre"] == "Platanus Hack")
ok("nada parecido -> nada", V.parecidos(["zacarias"], recientes) == [])
ok("takeout no busca", V.resolver("google takeout", cands=pablos)["watch"]["nombre"] == "Google Takeout")

with tempfile.TemporaryDirectory() as tmp:
    V.HERE = Path(tmp)
    now = datetime(2026, 11, 16, 20, 0)
    w = V.add({**tk, "desde": now.isoformat()}, now)
    rows = [{"cuenta": "micuenta@gmail.com", "de": "Google <no-reply@accounts.google.com>",
             "asunto": "Tus datos de Google están listos para descargar", "fecha": now - timedelta(hours=2)}]
    fired, _ = V.revisar_correo(rows, [])
    ok("correo anterior a la vigilancia no cuenta", not fired and len(V.activas()) == 1)
    rows[0]["fecha"] = now + timedelta(minutes=5)
    fired, _ = V.revisar_correo(rows, [])
    ok("takeout llega -> aviso y se borra", len(fired) == 1 and "Google Takeout" in fired[0][1] and not V.activas())
    ok("queda en cumplidas", V.load()["cumplidas"][0]["id"] == w["id"])

    # publicación de un ramo (U-Cursos manda el ramo en el cuerpo)
    pw = V.add({"tipo": "publicacion", "ramo": "Lenguajes de Programación", "code": "CC3102",
                "de": ["ucursos", "u-cursos", "ucampus"], "alguno": ["Lenguajes de Programación", "CC3102"],
                "cuerpo": True, "desde": now.isoformat()}, now)
    rows = [{"cuenta": "x@ug.uchile.cl", "de": '"U-Cursos" <noreply-ucursos@ucampus.cl>', "asunto": "Consulta Tarea 3a",
             "fecha": now + timedelta(minutes=1), "cuerpo": "Introducción a la Programación ..."},
            {"cuenta": "x@ug.uchile.cl", "de": '"U-Cursos" <noreply-ucursos@ucampus.cl>', "asunto": "Novedad: Tarea 2",
             "fecha": now + timedelta(minutes=2), "cuerpo": "CC3102-1 Lenguajes de Programación: se publicó la tarea 2"}]
    fired, _ = V.revisar_correo(rows, [])
    ok("publicación del ramo correcto", len(fired) == 1 and "Novedad: Tarea 2" in fired[0][1])

    # nota puntual
    nw = V.add({"tipo": "nota", "ramo": "Redes", "code": "CC3301", "path": "ing/2026/2/CC3301/1",
                "evaluacion": ["control", "2"], "antes": {"Control 1": "5,5", "Control 2": ""}}, now)
    st = {"ramos": {"ing/2026/2/CC3301/1": {"Control 1": "5,5", "Control 2": "", "Tarea 1": "6,0"}}}
    ok("otra nota no cumple", not V.revisar_notas(st) and len(V.activas("nota")) == 1)
    st["ramos"]["ing/2026/2/CC3301/1"]["Control 2"] = "6,2"
    res = V.revisar_notas(st)
    ok("control 2 sale -> aviso sin la nota", len(res) == 1 and "Control 2" in res[0][1] and "6,2" not in res[0][1] and ("CC3301", "Control 2") in res[0][2])
    ok("nota cumplida se borra", not V.activas("nota"))

    # ramo nunca revisado: la primera revisión es el punto de partida
    V.add({"tipo": "nota", "ramo": "Redes", "code": "CC3301", "path": "otro/1", "evaluacion": [], "antes": None}, now)
    st = {"ramos": {"otro/1": {"Control 1": "4,0"}}}
    ok("sin punto de partida no avisa", not V.revisar_notas(st))
    st["ramos"]["otro/1"]["Control 2"] = "5,0"
    ok("después sí avisa", len(V.revisar_notas(st)) == 1)

    # listar y cancelar
    V.add(V.correo_watch("Falabella"), now)
    V.add(V.correo_watch("google takeout"), now)
    ok("lista", "2 cosas" in V.lista_texto() and "Google Takeout" in V.lista_texto())
    hits = V.find_to_cancel("takeout")
    ok("cancelar takeout", len(hits) == 1 and hits[0]["nombre"] == "Google Takeout")
    ok("cancelar todas", len(V.find_to_cancel("todas")) == 2)

# --- uso real 17-11: «Deja de esperar el correo de Lice» (era elise) quitó HÉLICE; luego «Tenías que dejar de esperar
# el otro, no ese» se reescribió como «recuérdame en una hora llamar al dentista» y creó un recordatorio inventado ---
ws3 = [{"id": "a", "tipo": "correo", "nombre": "Platanus Hack"}, {"id": "b", "tipo": "correo", "nombre": "elise"},
       {"id": "c", "tipo": "correo", "nombre": "HÉLICE - Escuela de Ingeniería y Ciencias"}]
ok("«Lice» suena como elise y Hélice: pregunta", {w["id"] for w in V.find_to_cancel("lice", ws3)} == {"b", "c"})
ok("«Hélice Escuela de Ingeniería» es uno solo", [w["id"] for w in V.find_to_cancel("hélice escuela de ingeniería", ws3)] == ["c"])
ok("«platanus» es uno solo", [w["id"] for w in V.find_to_cancel("platanus", ws3)] == ["a"])
ok("«la chile» no calza con nada (pregunta)", V.find_to_cancel("la chile", ws3) == [])
ok("corrección reconocida", V.es_correccion("Tenías que dejar de esperar el otro, no ese") and not V.es_correccion("deja de esperar el correo de elise"))
with tempfile.TemporaryDirectory() as tmp:
    V.HERE = Path(tmp)
    for w in ws3:
        V.add(dict(w))
    V.remove(["c"])
    V.restaurar([ws3[2]])
    ok("restaurar devuelve la vigilancia con su id", {w["id"] for w in V.activas()} == {"a", "b", "c"})
try:
    import hud_server as H  # noqa: E402
    pi = H.palabras_inventadas
    ok("reescritura que inventa «dentista» se descarta",
       "dentista" in pi("recuérdame en una hora llamar al dentista", ["Tenías que dejar de esperar el otro, no ese"]))
    ok("reescritura fiel pasa", not pi("recuérdame en una hora llamar al dentista", ["acuérdame como en una hora de llamar al dentista"]))
    ok("reescritura fiel pasa (WhatsApp)", not pi("envía Hola Benji por WhatsApp a Benji", ["Manda un... Hola Benji a WhatsApp. A Benji"]))
    ok("reescritura fiel pasa (pega)", not pi("¿tengo correos sin leer en la pega?", ["¿hay algo nuevo en el mail de la pega?"]))
    ok("las correcciones no se reescriben", bool(H.CORRECCION_RE.search(H._plain("Tenías que dejar de esperar el otro, no ese"))))
except ImportError as exc:
    ok(f"importar hud_server ({exc})", False)

# --- ajustes.json (opción B, 17-11-2026): valores de hoy por defecto, «¿dónde cambio…?» ---
import json as _json  # noqa: E402
import atlas_ajustes as AJ  # noqa: E402
_orig_file = AJ.FILE
with tempfile.TemporaryDirectory() as _d:
    AJ.FILE = Path(_d) / "ajustes.json"
    AJ._cache = None
    ok("sin archivo: aviso 1 hora antes", AJ.num("avisos.antes_min", 0) == 60)
    ok("sin archivo: Telegram tras 10 min", AJ.num("telegram.ausente_min", 0) == 10)
    AJ.FILE.write_text(_json.dumps({"stt_model": "parakeet", "avisos": {"antes_min": 30}}), encoding="utf-8")
    AJ._cache = None
    ok("lee avisos.antes_min del archivo", AJ.num("avisos.antes_min", 0) == 30)
    ok("lo no escrito sigue con el predeterminado", AJ.num("avisos.alarma_tope_min", 0) == 60)
    import atlas_previo as _P  # noqa: E402
    ok("atlas_previo usa el ajuste", _P.antes() == timedelta(minutes=30))
    AJ.guardar("telegram.ausente_min", 5)
    AJ._cache = None
    _raw = _json.loads(AJ.FILE.read_text(encoding="utf-8"))
    ok("guardar conserva stt_model y lo demás", _raw.get("stt_model") == "parakeet" and _raw["avisos"]["antes_min"] == 30
       and _raw["telegram"]["ausente_min"] == 5)
    AJ.FILE.write_text('{"avisos": {"antes_min": "mucho"}', encoding="utf-8")
    AJ._cache = None
    ok("archivo roto: valen los predeterminados", AJ.num("avisos.antes_min", 60) == 60)
    AJ.FILE.write_text('{"avisos": {"antes_min": 0}}', encoding="utf-8")
    AJ._cache = None
    ok("valor absurdo (0 min): vale el predeterminado", _P.antes() == timedelta(hours=1))
AJ.FILE = _orig_file
AJ._cache = None
for _q, _clave in [("¿Dónde cambio cuánto antes me avisas de una reunión?", "avisos.antes_min"),
                   ("¿cómo cambio la ciudad del clima?", "ciudad_clima"),
                   ("¿dónde se cambia el sonido de la alarma?", "sonido_alarma"),
                   ("donde configuro cada cuanto revisa ucursos", "frecuencias.ucursos_min"),
                   ("¿cómo cambio qué clases me avisas?", "ramos.json → avisar_antes")]:
    _h = AJ.buscar(_q)
    ok(f"«{_q}» -> {_clave} (dio {[x['clave'] for x in _h]})", AJ.es_pregunta(_q) and _h and _h[0]["clave"] == _clave)
ok("la respuesta dice la rueda y el archivo",
   "rueda de ajustes" in AJ.donde("¿dónde cambio cuánto antes me avisas?") and "ajustes.json" in AJ.donde("¿dónde cambio cuánto antes me avisas?"))
ok("«¿cómo cambio el estado de la tarea 3?» no es de ajustes", not AJ.buscar("como cambio el estado de la tarea 3"))
ok("la vista trae secciones", len(AJ.vista()["secciones"]) >= 5)

# --- horario: la auxiliar que dicta sale en EVENTOS (uso real 17-11: «aún no sale el auxiliar en el calendario») ---
import atlas_agenda as _A  # noqa: E402
_e = {"summary": "Auxiliar", "kind": "Auxiliar", "course": "Introducción a la Programación",
      "when": datetime(2026, 11, 18, 14, 30), "start": datetime(2026, 11, 18, 14, 30), "end": datetime(2026, 11, 18, 16)}
ok("auxiliar de Intro va con los eventos", _A._view_item(_e).get("evento") is True)
ok("cátedra de Intro sigue en clases", _A._view_item(dict(_e, kind="Cátedra", summary="Cátedra")).get("evento") is False)
ok("auxiliar de otro ramo sigue en clases", _A._view_item(dict(_e, course="Lenguajes de Programación")).get("evento") is False)
ok("la HUD separa con x.evento", "!x.evento" in (Path(__file__).resolve().parent / "hud.html").read_text(encoding="utf-8"))

# --- «Voz y apodos» en la rueda (17-11-2026): correcciones simples editables, avanzadas solo para ver, apodos ---
import atlas_voz_apodos as VA  # noqa: E402
import shutil as _sh  # noqa: E402
_here = Path(__file__).resolve().parent
_orig = (VA.DICC, dict(VA.FILES))
with tempfile.TemporaryDirectory() as _d:
    _d = Path(_d)
    for _f in ("contactos.json", "ramos.json", "accesos.json", "repertorio.json"):
        _sh.copy(_here / _f, _d / _f)
    VA.DICC = _d / "diccionario.json"   # se migra desde equivalencias.json, como el de verdad (18-11-2026)
    VA.FILES = {"contactos": _d / "contactos.json", "ramos": _d / "ramos.json", "accesos": _d / "accesos.json",
                "musica": _d / "repertorio.json"}
    _v = VA.vista()
    _shego = next((c for c in _v["correcciones"] if c["entiende"] == "Shego"), None)
    ok("Chego → Shego se ve como corrección simple", bool(_shego) and "chego" in _shego["escucha"] and not _shego["avanzada"])
    ok("las reglas con expresiones quedan como avanzadas", any(c["avanzada"] for c in _v["correcciones"]))
    _n = len(_v["correcciones"])
    ok("crear una corrección nueva", VA.guardar_correccion(None, ["Pancho Villa", "panchovilla"], "Pancho")["ok"])
    _new = next((c for c in VA.vista()["correcciones"] if c["entiende"] == "Pancho"), None)
    ok("la nueva queda como «escucha → entiende»", len(VA.vista()["correcciones"]) == _n + 1
       and sorted(_new["escucha"]) == ["pancho villa", "panchovilla"])
    import atlas_nombres as _NM  # noqa: E402
    ok("la nueva funciona (en el diccionario)", _NM.aplicar_diccionario("con pancho  villa hoy", VA.DICC) == "con Pancho hoy")
    ok("editar cambia lo que escucha", VA.guardar_correccion(_new["i"], ["panchito"], "Pancho")["ok"]
       and _NM.aplicar_diccionario("con panchovilla", VA.DICC) == "con panchovilla"
       and _NM.aplicar_diccionario("con panchito", VA.DICC) == "con Pancho")
    ok("no deja la misma palabra en dos correcciones", not VA.guardar_correccion(None, ["chego"], "Santiago")["ok"])
    ok("rechaza palabras de 1-2 letras", not VA.guardar_correccion(None, ["la"], "lo")["ok"])
    ok("rechaza símbolos (no deja meter expresiones)", not VA.guardar_correccion(None, ["a.*"], "x")["ok"])
    _adv = next(c for c in VA.vista()["correcciones"] if c["avanzada"])
    ok("no edita una avanzada", not VA.guardar_correccion(_adv["i"], ["hola"], "chao")["ok"])
    ok("no borra una avanzada", not VA.borrar_correccion(_adv["i"])["ok"])
    _pan = next(c for c in VA.vista()["correcciones"] if c["entiende"] == "Pancho")
    ok("borrar la nueva", VA.borrar_correccion(_pan["i"])["ok"] and len(VA.vista()["correcciones"]) == _n
       and _NM.aplicar_diccionario("con panchito", VA.DICC) == "con panchito")
    ok("el probador ve «chego»", "Shego" in VA.reglas_que_aplican("reunión con chego"))
    _c = VA.vista()["contactos"][0]
    ok("apodos de un contacto", VA.guardar_lista("contactos", _c["clave"], ["Tito", "tito", " Titín "])["ok"]
       and VA.vista()["contactos"][0]["lista"] == ["Tito", "Titín"])
    _r = next(r for r in VA.vista()["ramos"] if r["clave"].startswith("Introducción"))
    ok("apodos de un ramo (el primero es el principal)", VA.guardar_lista("ramos", _r["clave"], ["Intro", "la progra"])["ok"]
       and next(r for r in VA._read(VA.FILES["ramos"])["ramos"] if r["ramo"] == _r["clave"])["apodo"] == "Intro")
    ok("un acceso no puede quedar sin forma de decirlo", not VA.guardar_lista("accesos", "Hermes", [])["ok"])
VA.DICC, VA.FILES = _orig[0], _orig[1]
ok("«¿dónde cambio que chego es shego?» -> Diccionario (antes «Voz y apodos»)",
   (AJ.buscar("¿dónde cambio que chego es shego?") or [{}])[0].get("seccion") == "Diccionario")

# --- uso real 17-11: esperaba HÉLICE <helice@ing.uchile.cl> y llegó de HÉLICE FCFM <helice.fcfm@uchile.cl> ---
_wh = V.elegir({"tipo": "correo", "nombre": "hélice", "todas": ["helice"]},
               [{"nombre": "HÉLICE - Escuela de Ingeniería y Ciencias", "correo": "helice@ing.uchile.cl"}])
ok("HÉLICE desde otra dirección también calza",
   V.match_mail(_wh, "HÉLICE Área de Ingeniería e Innovación FCFM <helice.fcfm@uchile.cl>", "¡Elige tu desafío!"))
ok("pero no cualquiera de uchile", not V.match_mail(_wh, "Biblioteca <biblioteca@uchile.cl>", "Aviso"))
_wg = V.elegir({"tipo": "correo", "nombre": "la chile", "todas": ["chile"]}, [{"nombre": "U. de Chile", "correo": "a@uchile.cl"}])
ok("una palabra genérica («chile») no se suma", "chile" not in _wg["de"])

# --- 17-11-2026: «solo vigilo cuando estoy esperando algo… debo poder decir deja de vigilar Canvas» ---
ok("«qué estamos monitoreando» lista", (V.parse("que estamos monitoreando") or {}).get("op") == "listar")
ok("«qué monitoreas» lista", (V.parse("qué monitoreas") or {}).get("op") == "listar")
try:
    import types as _types
    _A = H.Atlas
    _m = lambda t: _A.PAUSA_RE.match(H._plain(t).strip())  # noqa: E731
    ok("«deja de vigilar Canvas» apaga", bool(_m("Deja de vigilar Canvas")) and _m("Deja de vigilar Canvas").group("off"))
    ok("«ya no vigiles U-Cursos» apaga", bool(_m("ya no vigiles ucursos")) and _m("ya no vigiles ucursos").group("off"))
    ok("«vigila el correo» enciende", bool(_m("vigila el correo")) and not _m("vigila el correo").group("off"))
    ok("«deja de vigilar el correo de Platanus» NO es apagar la fuente", not _m("deja de vigilar el correo de Platanus"))
    with tempfile.TemporaryDirectory() as _d:
        _oh, _of = V.HERE, AJ.FILE
        V.HERE, AJ.FILE, AJ._cache = Path(_d), Path(_d) / "ajustes.json", None
        _f = _types.SimpleNamespace(PAUSA_RE=_A.PAUSA_RE, _vig=lambda: V,
                                    _canvas=lambda: _types.SimpleNamespace(has_session=lambda: True))
        _f.vigila = lambda fu: _A.vigila(_f, fu)
        ok("sin nada esperado: U-Cursos no se vigila", not _f.vigila("ucursos") and not _f.vigila("canvas"))
        V.add({"tipo": "nota", "ramo": "Cálculo", "nombre": "Control 2"})
        ok("esperando una nota: U-Cursos se vigila", _f.vigila("ucursos") and not _f.vigila("correo"))
        _r = _A.route_pausa_fuente(_f, "deja de vigilar u-cursos")
        ok("«deja de vigilar U-Cursos» quita la nota esperada", "dejo de vigilar" in _r["reply"] and not V.activas("nota")
           and not _f.vigila("ucursos"))
        _r = _A.route_pausa_fuente(_f, "vigila Canvas")
        ok("«vigila Canvas» lo enciende", _f.vigila("canvas") and "vigilo Canvas" in _r["reply"])
        AJ._cache = None
        _A.route_pausa_fuente(_f, "deja de vigilar canvas")
        AJ._cache = None
        ok("«deja de vigilar Canvas» lo apaga", not _f.vigila("canvas"))
        ok("apagar lo ya apagado lo dice", "No estaba" in _A.route_pausa_fuente(_f, "deja de vigilar canvas")["reply"])
        V.HERE, AJ.FILE, AJ._cache = _oh, _of, None
except Exception as exc:  # noqa: BLE001
    ok(f"vigilar por fuente ({exc!r})", False)

# --- uso real 18-11: «¿De qué trata el correo de Platanus?» abría el último correo del que se hablaba ---
try:
    _fa = _types.SimpleNamespace(MAIL_FROM_RE=H.Atlas.MAIL_FROM_RE, _NO_REMITENTE=H.Atlas._NO_REMITENTE, _vig=lambda: V)
    _q = lambda t: H.Atlas._mail_sender_query(_fa, t)  # noqa: E731
    ok("«el correo de Pablo Fuentes» busca a Pablo Fuentes", _q("lee el mail de Pablo Fuentes por favor") == "Pablo Fuentes")
    ok("«el correo de ayer» no es remitente", _q("resume el correo de ayer") is None)
    ok("«ese correo» no busca", _q("¿qué dice ese correo?") is None)
    ok("«el último correo» no busca", _q("resume el último correo") is None)
except Exception as exc:  # noqa: BLE001
    ok(f"correo de un remitente ({exc!r})", False)

# --- 18-11-2026: «avísame cuando escriba X por ambas redes»: solo quién escribió, una vez ---
ok("«cuando me escriba Pablo por WhatsApp»", V.parse("Avísame cuando me escriba Pablo por WhatsApp") == {"op": "mensaje", "quien": "pablo", "red": "whatsapp"})
ok("«si me escribe Benji por telegram»", (V.parse("avísame si me escribe Benji por telegram") or {}).get("red") == "telegram")
ok("sin decir red: ambas", (V.parse("avísame cuando me llegue un mensaje de Felipe") or {}).get("red") == "ambas")
ok("«me escriba Pablo al correo» sigue siendo correo", (V.parse("avísame cuando me escriba Pablo al correo") or {}).get("op") == "correo")
_wm = {"tipo": "mensaje", "nombre": "Pablo Fuentes", "buscar": ["Pablo Fuentes", "pablo"], "red": "ambas"}
ok("calza el chat de Pablo Fuentes", V.mensaje_calza(_wm, "Pablo Fuentes"))
ok("no calza Mariana con Ana", not V.mensaje_calza({"nombre": "Ana", "buscar": ["Ana"]}, "Mariana"))
ok("se describe sin contenido", V.describe([_wm]) == "un mensaje de Pablo Fuentes por WhatsApp o Telegram")
_c = V.parse("deja de esperar el mensaje de Pablo Fuentes")
ok("cancelar el mensaje esperado", _c and _c["op"] == "cancelar" and V.find_to_cancel(_c["que"], [{**_wm, "id": "m"}]))

# --- 18-11-2026: nota esperada en Canvas, aparte de U-Cursos ---
with tempfile.TemporaryDirectory() as _d:
    _oh = V.HERE
    V.HERE = Path(_d)
    V.add({"tipo": "nota", "fuente": "canvas", "ramo": "Curso C", "code": "C1", "path": "x/courses/1", "evaluacion": [],
           "antes": {"Tarea 1": ""}})
    V.add({"tipo": "nota", "ramo": "Redes", "code": "CC1", "path": "u/redes", "evaluacion": [], "antes": {"P1": ""}})
    _cv = V.revisar_notas({"ramos": {"x/courses/1": {"Tarea 1": "6,5"}, "u/redes": {"P1": "5,0"}}}, fuente="canvas")
    ok("Canvas avisa solo su nota", len(_cv) == 1 and _cv[0][0]["ramo"] == "Curso C" and "6,5" not in _cv[0][1])
    _uc = V.revisar_notas({"ramos": {"x/courses/1": {"Tarea 1": "7,0"}, "u/redes": {"P1": "5,0"}}})
    ok("U-Cursos no toma la de Canvas", len(_uc) == 1 and _uc[0][0]["ramo"] == "Redes")
    try:
        _fv = _types.SimpleNamespace(_vig=lambda: V)
        V.add({"tipo": "nota", "fuente": "canvas", "ramo": "Curso C", "code": "C1", "path": "x/courses/1", "evaluacion": []})
        _oa, AJ.FILE, AJ._cache = AJ.FILE, Path(_d) / "ajustes.json", None
        ok("esperar en Canvas enciende Canvas, no U-Cursos", H.Atlas.vigila(_fv, "canvas") and not H.Atlas.vigila(_fv, "ucursos"))
        AJ.FILE, AJ._cache = _oa, None
    except Exception as exc:  # noqa: BLE001
        ok(f"vigila por fuente con Canvas ({exc!r})", False)
    V.HERE = _oh

print(f"{total - len(fallas)} de {total} pruebas pasan")
for f in fallas:
    print("  FALLA:", f)
sys.exit(1 if fallas else 0)

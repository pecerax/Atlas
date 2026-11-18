"""Pruebas de regresión de Atlas: frases reales -> qué ruta las atiende y qué hace.

No usan el modelo de lenguaje, ni el correo, ni el calendario, ni tocan los archivos del usuario:
trabajan sobre una carpeta temporal con datos inventados y herramientas falsas que solo anotan lo
que se les pidió. Sirven para comprobar, después de cada cambio, que lo que ya funcionaba sigue igual.

Uso:  python pruebas_atlas.py        (o doble clic en Probar-Atlas.cmd)
Cada caso nuevo que falle en el uso real se agrega a CASOS para que no vuelva a romperse.
"""

from __future__ import annotations

import os as _os

_os.environ["ATLAS_PRUEBAS"] = "1"  # nada abre ventanas, pestañas ni programas visibles durante las pruebas
# diccionario y frases del lápiz ✎: nunca los del usuario (~\.atlas)
_os.environ["ATLAS_DICCIONARIO"] = _os.path.join(_os.environ.get("TEMP", "."), "atlas_pruebas_diccionario.json")
_os.environ["ATLAS_FRASES"] = _os.path.join(_os.environ.get("TEMP", "."), "atlas_pruebas_frases.json")
for _f in (_os.environ["ATLAS_DICCIONARIO"], _os.environ["ATLAS_FRASES"]):  # cada corrida migra de cero
    try:
        _os.remove(_f)
    except OSError:
        pass

import json
import re
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
AHORA = datetime(2026, 11, 9, 9, 0)  # lunes; todas las pruebas ocurren "en" este momento


# ----------------------------------------------------------------------------- datos inventados
def _ics(tareas: bool = False) -> str:
    def ev(kind, course, start, mins=90, room="B01", code="CC0000", cats=""):
        end = start + timedelta(minutes=mins)
        f = lambda d: (d + timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731  (Santiago = UTC-3)
        title = f"{kind} - {course}" if course else kind
        return (f"BEGIN:VEVENT\nUID:{kind}{course}{start}\nDTSTART:{f(start)}\nDTEND:{f(end)}\n"
                + (f"CATEGORIES:{cats}\n" if cats else "")
                + f"SUMMARY:{title}" + (f"\\n{room}" if room else "")
                + f"\nURL:https://www.u-cursos.cl/ingenieria/2026/2/{code}/1/\nEND:VEVENT\n")

    intro, redes, leng = "Introducción a la Programación", "Redes", "Lenguajes de Programación"
    evalua, eh = "Formulación$1 Evaluación y Gestión de Proyectos", "Ingeniería$1 Tecnología y Sociedad: una Perspectiva Histó"
    out = "BEGIN:VCALENDAR\nVERSION:2.0\n"
    for week in range(-1, 4):
        mon = datetime(2026, 11, 9) + timedelta(weeks=week)
        out += ev("Cátedra", intro, mon.replace(hour=12, minute=45), room="G304", code="CC1001")
        out += ev("Cátedra", redes, mon.replace(hour=12) + timedelta(days=1), room="B08", code="CC3301")
        out += ev("Cátedra", leng, mon.replace(hour=10, minute=15) + timedelta(days=1), room="G108", code="CC3102")
        out += ev("Cátedra", eh, mon.replace(hour=10, minute=15) + timedelta(days=3), room="B07", code="EH2001")
        out += ev("Auxiliar", redes, mon.replace(hour=14, minute=30) + timedelta(days=2), room="S26", code="CC3301")
        out += ev("Auxiliar", intro, mon.replace(hour=18) + timedelta(days=3), room="S03$1 S05", code="CC1001")
    out += ev("Control", evalua, datetime(2026, 11, 10, 16, 15), room="B01$1 B04", code="CC3403")
    out += ev("Control", leng, datetime(2026, 11, 13, 14, 0), room="Q10", code="CC3102")
    out += ev("Control", intro, datetime(2026, 11, 14, 8, 30), room="B01$1 B02", code="CC1001")
    out += ev("Control", intro, datetime(2026, 11, 5, 8, 30), room="B01", code="CC1001")
    out += ev("Tarea", leng, datetime(2026, 11, 20, 23, 59), mins=0, room="Tarea 3", code="CC3102")
    if tareas:  # tareas de U-Cursos en "Otros eventos" > "Tareas" (formas posibles), una de ellas repetida
        out += ev("Otros eventos", redes, datetime(2026, 11, 11, 23, 59), mins=0, room="Tarea 2", code="CC3301",
                  cats="Otros eventos,Tareas")
        out += ev("Tarea 2", redes, datetime(2026, 11, 11, 23, 59), mins=0, room="", code="CC3301", cats="Tareas")
        out += ev("Tarea 4: Simulador", "", datetime(2026, 11, 15, 23, 59), mins=0, room="", code="CC1001",
                  cats="Otros eventos\\,Tareas")

        # Formato real del módulo Tareas de U-Cursos: ícono de tareas, "Nombre - CÓDIGO-sección Ramo",
        # DTSTART = publicación y DTEND = plazo. Más la misma Tarea 3a repetida en el calendario del ramo.
        out += ("BEGIN:VEVENT\nUID:t100001\nDTSTART:20261105T150000Z\nDTEND:20261112T025900Z\n"
                "IMAGE;VALUE=URI:https://static.u-cursos.cl/images/servicios/tareas_v34731.s\n vg\n"
                "SUMMARY:Actividad 7 - BGP - CC3301-1 Redes\n"
                "URL:https://www.u-cursos.cl/ingenieria/2026/2/CC3301/1/tareas/o/100001\nEND:VEVENT\n")
        out += ("BEGIN:VEVENT\nUID:t100002\nDTSTART;VALUE=DATE:20261113Z\nDTEND;VALUE=DATE:20261113Z\n"
                "IMAGE;VALUE=URI:https://static.u-cursos.cl/images/servicios/tareas_v34731.svg\n"
                "SUMMARY:Tarea 3a - CC1001-1 Introducción a la Programación\n"
                "URL:https://www.u-cursos.cl/ingenieria/2026/2/CC1001/1/tareas/o/100002\nEND:VEVENT\n")
        out += ("BEGIN:VEVENT\nUID:c100002\nDTSTART;VALUE=DATE:20261113Z\nDTEND;VALUE=DATE:20261113Z\n"
                "IMAGE;VALUE=URI:https://static.u-cursos.cl/images/servicios/calendario_v34731.svg\n"
                "SUMMARY:Tarea 3a - CC1001-1 Introducción a la Programación\n"
                "URL:https://www.u-cursos.cl/ingenieria/2026/2/CC1001/1/\nEND:VEVENT\n")
    return out + "END:VCALENDAR\n"


MAILS = """Newest emails (all accounts, newest first):
- id=3i50 | prof@uni.example | read | Date: lun 09-11-2026 08:10 (hora local) | From: Andrea Muñoz (vía U-Cursos) | Subject: Consulta Tarea 3a | Curso: Introducción a la Programación
- id=3i49 | prof@uni.example | read | Date: lun 09-11-2026 08:01 (hora local) | From: Camila Soto (vía U-Cursos) | Subject: Consulta Tarea 3a | Curso: Introducción a la Programación
- id=3i40 | prof@uni.example | UNREAD | Date: dom 08-11-2026 11:40 (hora local) | From: Benjamín Correa F. (vía U-Cursos) | Subject: P1 C3 | Curso: Introducción a la Programación
- id=3i30 | prof@uni.example | read | Date: sáb 07-11-2026 09:00 (hora local) | From: "Google" <no-reply@accounts.google.com> | Subject: Alerta de seguridad"""

FILES = {
    "cuentas.json": {"personal": "yo@mail.example", "la chile": "prof@uni.example", "universidad": "prof@uni.example"},
    "contexto_correo.json": {"uni.example": {
        "descripcion": "Cuenta de la universidad.",
        "equipo": {"Andrea": "profesora del curso", "Benjamín Olivares": "profesor auxiliar"},
        "yo": ["nombre.apellido"], "reglas": []}},
    "repertorio.json": {"artistas": [{"nombre": "Sheena Ringo", "alias": ["sheena ringo", "chenaringo"], "canciones": []},
                                     {"nombre": "Ado", "alias": ["ado"], "canciones": []}]},
    "ramos.json": {"ramos": [
        {"apodo": "Evalua", "ramo": "Formulación, Evaluación y Gestión de Proyectos"},
        {"apodo": "Lenguajes", "ramo": "Lenguajes de Programación"},
        {"apodo": "EH", "ramo": "Ingeniería, Tecnología y Sociedad: una Perspectiva Histórica", "se_dice": "e hache", "tambien": ["e hache"]},
        {"apodo": "Introducción a la Programación", "ramo": "Introducción a la Programación",
         "tambien": ["introducción a la progra", "intro a la programación", "intro a la progra", "la progra", "intro"],
         "dicto": ["auxiliar"], "avisar_antes": ["auxiliar"]}]},
    "memoria.json": {"sinonimos": {}, "notas": []},
    "calendarios.json": {"calendarios": [{"nombre": "U-Cursos", "url": "https://calendario.invalid/a.ics"}]},
    "accesos.json": {"accesos": [{"nombre": "Fortuna", "dice": ["fortuna", "proyecto fortuna"], "url": "https://claude.ai/project/prueba"}]},
}


GOOGLE = [  # eventos inventados "en Google Calendar"
    {"id": "g1", "summary": "Laboratorio", "start": datetime(2026, 11, 13, 10, 15), "end": datetime(2026, 11, 13, 11, 45),
     "allday": False, "location": "", "calendar": "Google"},
    {"id": "g2", "summary": "Reunión con Felipe", "start": datetime(2026, 11, 17, 17, 0), "end": datetime(2026, 11, 17, 18, 0),
     "allday": False, "location": "", "calendar": "Google"},
    {"id": "g3", "summary": "En Google Calendar Entrevista Natalia Ibáñez", "start": datetime(2026, 11, 27, 9, 30),
     "end": datetime(2026, 11, 27, 10, 30), "allday": False, "location": "", "calendar": "Google"},
]


class Fake:
    """Herramienta falsa: anota lo que le piden y responde con datos inventados."""

    def __init__(self, name: str) -> None:
        self.spec = types.SimpleNamespace(name=name)
        self.calls: list[dict] = []

    def execute(self, **p):
        self.calls.append(p)
        if self.spec.name == "gmail":
            content = ("Account: prof@uni.example\nFrom: Camila Soto (vía U-Cursos)\nSubject: Consulta Tarea 3a\n\nHola, tengo una duda."
                       if p.get("action") == "read" else MAILS)
        else:
            content = "hecho"
        return types.SimpleNamespace(success=True, content=content, metadata={})


def preparar():
    """Carga los módulos de Atlas apuntando a una carpeta temporal. -> (hud_server, carpeta)."""
    tmp = Path(tempfile.mkdtemp(prefix="atlas_pruebas_"))
    for name, data in FILES.items():
        (tmp / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        import openjarvis.tools.atlas_pc  # noqa: F401
    except Exception:  # fuera del PC de Atlas: un doble mínimo de lo que usa la ruta "abre …"
        for mod in ("openjarvis", "openjarvis.tools"):
            sys.modules.setdefault(mod, types.ModuleType(mod))
        stub = types.ModuleType("openjarvis.tools.atlas_pc")
        stub.SITES = {"youtube": "https://www.youtube.com"}
        stub._norm = lambda s: s.lower().strip()
        sys.modules["openjarvis.tools.atlas_pc"] = stub
        core = types.ModuleType("openjarvis.core.types")
        core.Message = lambda role, content: types.SimpleNamespace(role=role, content=content)
        core.Role = types.SimpleNamespace(USER="user", ASSISTANT="assistant")
        sys.modules.setdefault("openjarvis.core", types.ModuleType("openjarvis.core"))
        sys.modules["openjarvis.core.types"] = core
    import hud_server as H
    import atlas_agenda as A
    import atlas_gcal as G
    import atlas_recordatorios as R

    H.HERE = tmp
    import atlas_tareas_listas as TL

    TL.FILE = tmp / "tareas_listas.json"  # nunca el archivo real (ahí están las tareas que él ya terminó)
    H.MEMORY_FILE = tmp / "memoria.json"
    H.LAST_APP_FILE = None
    # las pruebas nunca leen Telegram ni WhatsApp de verdad (WhatsApp se mostraría fuera de la pantalla)
    H.Atlas.SIN_LEER_FN = staticmethod(lambda app: {"ok": True, "chats": []})
    H.Atlas.NAMED_FN = staticmethod(lambda app, words: {"ok": True, "found": False})  # nunca WhatsApp/Telegram reales
    import atlas_contactos as CT  # libreta de contactos de mentira: Camila sin Discord

    CT.FILE = tmp / "contactos.json"
    CT.upsert({"nombre": "Camila Soto", "apodos": ["Cami"], "correo": "camila@uni.example"})
    CT.upsert({"nombre": "Sebastián Lagos", "apodos": ["Tipo"], "discord": "tipo0000", "telefono": "+56 9 8765 4321"})
    CT.upsert({"nombre": "Antonio Fuenzalida", "apodos": ["Toño"], "telegram": "antonio_f"})
    import atlas_avisos as AV
    AV.FILE = tmp / "eventos_contactos.json"
    H.log = lambda *_a, **_k: None
    A.HERE, A.CONFIG, A.RAMOS = tmp, tmp / "calendarios.json", tmp / "ramos.json"
    A._cache["https://calendario.invalid/a.ics"] = (1e18, _ics())
    A.NOW = G.NOW = lambda: AHORA
    A._LAST = None
    R.HERE, R.NOW = tmp, lambda: AHORA
    import atlas_basico as B
    B.NOW = lambda: AHORA
    B.FETCH = lambda: {"dolar": (945.32, "2026-11-06"), "euro": (1010.5, "2026-11-06"), "uf": (39643.59, "2026-11-09")}
    B._cache.update(t=0.0, data=None)
    H.run_claude = lambda pregunta, contexto="": (True, "**Respuesta** de prueba.")  # sin llamar a Claude de verdad
    H.weather_brief = lambda: "Santiago: ahora 20°C, despejado. Mañana: llovizna."  # sin internet
    H.rewrite_order = lambda t, h=None, m="": ""  # sin modelo: la reescritura tiene su propia prueba
    import atlas_clima as K
    K.FETCH = lambda url: ({"results": [{"name": "Valparaíso", "country": "Chile", "country_code": "CL", "latitude": -33.0,
                                         "longitude": -71.6}]} if "geocoding" in url else
                           {"current": {"temperature_2m": 21.3, "apparent_temperature": 20.8, "weather_code": 0},
                            "daily": {"weather_code": [1, 2, 63], "temperature_2m_min": [11.2, 12, 9.6],
                                      "temperature_2m_max": [25, 26.6, 15], "precipitation_probability_max": [0, 10, 80]}})
    G.is_connected = lambda: True
    G.list_events = lambda a, b: [dict(e) for e in GOOGLE if a <= e["start"] < b]  # Google Calendar de mentira
    G.create_event = lambda *a, **k: {"id": "nuevo1"}
    G.patch_event = lambda *a, **k: {}
    G.delete_event = lambda *a, **k: None
    return H, tmp


def nuevo(H):
    j = H.Atlas()
    j.gmail_raw, j.pc_raw = Fake("gmail"), Fake("pc")
    return j


# ----------------------------------------------------------------------------- casos
# Cada grupo es una conversación (comparte memoria de contexto). Cada caso:
#   (frase, ruta esperada, comprobaciones)
# Comprobaciones: reply=regex sobre la respuesta · gmail=/pc= parámetros que debe llevar la última llamada ·
#   pending=True/False (quedó algo esperando confirmación) · hint=regex · no_gmail/no_pc=True (no debe llamarla)
CASOS: list[tuple[str, list[tuple]]] = [
    ("Básicas: hora, fecha, cálculos y unidades (al instante, sin modelo)", [
        # uso real, hud.log 23:35: el modelo respondió "No tengo acceso al reloj del sistema"
        ("Necesito saber qué hora es.", "basico", dict(reply=r"^Son las 9:00, señor\.$")),
        ("¿Qué hora es en Santiago de Chile?", "basico", dict(reply=r"^Son las 9:00, señor\.$")),
        ("qué horas son", "basico", dict(reply=r"Son las 9:00")),
        ("Qué ora es", "basico", dict(reply=r"Son las 9:00")),
        ("¿Me puedes decir la hora?", "basico", dict(reply=r"Son las 9:00")),
        ("qué hora es en Tokio", "basico", dict(reply=r"En Tokio son las 21:00")),
        ("qué hora es y qué día", "basico", dict(reply=r"Son las 9:00 del lunes 9 de noviembre de 2026")),
        ("¿Qué día es hoy?", "basico", dict(reply=r"Hoy es lunes 9 de noviembre de 2026")),
        ("a cuánto estamos", "basico", dict(reply=r"Hoy es lunes 9 de noviembre")),
        ("qué día es mañana", "basico", dict(reply=r"Mañana es martes 10 de noviembre")),
        ("qué día cae el veinticinco de diciembre", "basico", dict(reply=r"El 25 de diciembre cae viernes")),
        ("cuántos días faltan para navidad", "basico", dict(reply=r"Faltan 46 días para el viernes 25 de diciembre")),
        ("cuánto falta para el viernes", "basico", dict(reply=r"Faltan 4 días para el viernes 13 de noviembre")),
        ("cuánto es 6 elevado a 3", "basico", dict(reply=r"6 elevado a 3 es 216")),
        # uso real, hud.log 18:27: el modelo explicó cómo usar la calculadora en vez de dar el resultado
        ("En la aplicación de la calculadora eleva 6 a la 3.", "basico", dict(reply=r"es 216", no_pc=True)),
        ("cuánto es veintitrés por cuarenta y cinco", "basico", dict(reply=r"23 por 45 es 1035")),
        ("cuánto es el 15 por ciento de 20 mil", "basico", dict(reply=r"El 15% de 20000 es 3000")),
        ("cuánto es la raíz cuadrada de 144", "basico", dict(reply=r"es 12, señor")),
        ("cuánto es 10 dividido por 0", "basico", dict(reply=r"No se puede dividir por cero")),
        ("cuánto es 3,5 por 2", "basico", dict(reply=r"3,5 por 2 es 7")),
        ("cuántas millas son 5 kilómetros", "basico", dict(reply=r"5 kilómetros son 3,11 millas")),
        ("convierte 30 grados a fahrenheit", "basico", dict(reply=r"30 grados Celsius son 86 grados Fahrenheit")),
        ("cuántos minutos son 3 horas", "basico", dict(reply=r"3 horas son 180 minutos")),
        ("a cuánto está el dólar", "basico", dict(reply=r"El dólar observado está a 945 pesos.*viernes 6 de noviembre")),
        ("cuánto vale la UF", "basico", dict(reply=r"La UF está a 39644 pesos, señor; es el valor de hoy")),
        ("cuántos dólares son 50 lucas", "basico", dict(reply=r"50000 pesos son unos 52,89 dólares")),
        ("cuánto son 100 dólares en pesos", "basico", dict(reply=r"100 dólares son unos 94532 pesos")),
        # lo que NO es de esta ruta
        ("qué día es el control de lenguajes", "agenda", dict()),
        ("pon una alarma a las 7", "recordatorio", dict()),
        ("recuérdame en 20 minutos sacar la ropa", "recordatorio", dict()),
        ("cuánto le queda al temporizador", "recordatorio", dict()),
        ("quién es Elon Musk", "modelo", dict()),
        ("pon música de Ado", "pc", dict()),
    ]),
    ("Correo: consultas de la universidad", [
        ("¿Qué consultas hay en el mail de la chile?", "correo",
         dict(reply=r"Camila Soto preguntó por «Consulta Tarea 3a», respondida por Andrea Muñoz.*Benjamín Correa F\. preguntó por «P1 C3», aún sin respuesta",
              gmail={"action": "latest", "account": "prof@uni.example"})),
        ("Resumele.", "correo", dict(gmail={"action": "read", "id": "3i49"}, hint=r"Resume este correo")),
        ("¿Hay consultas sin responder?", "correo", dict(reply=r"1 consulta sin responder: Benjamín Correa")),
        # el ramo aunque la voz lo oiga mal (uso real 15-11-2026: «Intro a la Progra» -> «Intras prueba»)
        ("¿Queda algún correo de Intras prueba sin responder?", "correo",
         dict(reply=r"1 consulta sin responder de .*Progra: Benjamín Correa")),
        ("¿Sobre qué trata el último mail que ha enviado a un estudiante para consultar algo?", "correo",
         dict(gmail={"action": "read", "id": "3i49"})),
        ("Resume la consulta sobre la P1C3", "correo", dict(gmail={"action": "read", "id": "3i40"}, hint=r"Todavía nadie del equipo")),
        ("resume la consulta de Benjamín", "correo", dict(gmail={"action": "read", "id": "3i40"})),
        ("¿Cuál es la última consulta?", "correo", dict(reply=r"última consulta es de Camila Soto.*Ya fue respondida por Andrea Muñoz")),
        ("Abre el mail y dime sobre qué trata.", "correo", dict(gmail={"action": "read"}, no_pc=True)),
    ]),
    ("Correo: leer no pide confirmación, modificar sí", [
        ("lee el último correo", "correo", dict(gmail={"action": "read"}, pending=False)),
        ("qué correos nuevos tengo", "correo", dict(gmail={"action": "latest"}, pending=False)),
        ("cuántos correos sin leer tengo", "correo", dict(gmail={"action": "unread"}, pending=False)),
        ("Marca como leíos todos los mails que tengo sin leer.", "correo", dict(pending=True, reply=r"Preparado, señor", no_gmail=True)),
    ]),
    ("Correo: marcar con otras formas de decirlo", [
        ("Quiero que me resumas la consulta sobre la P1C3 y que los marques como leídos, todos.", "correo",
         dict(pending=True, gmail={"action": "read", "id": "3i40"}, hint=r"confirme en pantalla")),
    ]),
    ("Correo: márcalos como vistos", [
        ("qué correos nuevos tengo", "correo", dict()),
        ("márcalos como vistos", "correo", dict(pending=True)),
    ]),
    ("Memoria: enseñar y preguntar", [
        ("Cuando diga el mail de la u me refiero a prof@uni.example", "memoria", dict(reply=r"Entendido, señor")),
        ("Cuando te pida probar el internet, trata de abrir siempre ejemplo.com para ver que esté funcionando, ¿entendido?", "memoria",
         dict(reply=r"Entendido, señor", no_pc=True)),
        ("recuerda que el router está en la pieza", "memoria", dict(reply=r"Anotado, señor")),
        ("guarda que mi clave del wifi está en el cajón", "memoria", dict(reply=r"Anotado, señor")),
        ("¿Quién es Benjamina Olivares?", "memoria", dict(reply=r"Benjamín Olivares es profesor auxiliar")),
        ("Me refiero a Benjamín Olivares.", "memoria", dict(reply=r"Benjamín Olivares es profesor auxiliar")),
        ("Matías Soto es un profesor auxiliar del curso.", "memoria", dict(reply=r"Anoté que Matías Soto.*respuestas del equipo")),
        ("Pedro Soto es mi primo", "memoria", dict(reply=r"Pedro Soto es su primo")),
        ("quién es Pedro Soto", "memoria", dict(reply=r"su primo")),
        ("Quiero que agregues Blue Swing a la lista de artistas recomendados.", "memoria", dict(reply=r"Agregué a sus recomendaciones: «Blue Swing»")),
        ("qué artistas tengo en mis recomendaciones", "memoria", dict(reply=r"Sheena Ringo, Ado, Blue Swing")),
        ("Esta canción es una maravilla", "modelo", dict()),
        ("quién es Elon Musk", "modelo", dict()),
    ]),
    ("PC: música, red y programas", [
        ("pon música de chenaringo", "pc", dict(pc={"action": "play_music", "query": "Sheena Ringo"})),
        ("Quiero que guardes la canción que está sonando.", "pc", dict(pc={"action": "like_music"})),
        ("Dije, guarda esta canción.", "pc", dict(pc={"action": "like_music"})),
        ("Guarda esta canción.", "pc", dict(pc={"action": "like_music"})),
        ("Dale like a la canción que está sonando.", "pc", dict(pc={"action": "like_music"})),
        ("quita el like", "pc", dict(pc={"action": "like_music", "command": "unlike"})),
        ("¿qué canción es esta?", "pc", dict(pc={"action": "now_playing"})),
        ("¡Ve el estado de la red!", "pc", dict(pc={"action": "network_status"})),
        ("Quiero que me digas si tenemos internet.", "pc", dict(pc={"action": "network_status"})),
        ("¿hay internet?", "pc", dict(pc={"action": "network_status"})),
        ("sube el volumen", "pc", dict(pc={"action": "media", "command": "volume_up"})),
        # pasar de canción (uso real 15-11-2026: «salta», «skipea esta canción»)
        ("Salta.", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Skipea esta canción", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Esquipea.", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Sáltate esta canción", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Pasa a la siguiente.", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Atlas, siguiente.", "pc", dict(pc={"action": "media", "command": "next"})),
        ("Vuelve a la anterior.", "pc", dict(pc={"action": "media", "command": "previous"})),
        ("pon la canción anterior", "pc", dict(pc={"action": "media", "command": "previous"})),
        ("abre youtube", "pc", dict(pc={"action": "open_website"})),
        ("abre spotify", "pc", dict(pc={"action": "open_app", "name": "spotify"})),
        ("Esto estoy pidiendo que para testear el internet trates de abrir siempre ejemplo.com", "pc", dict(pc={"action": "network_status"})),
        ("apaga el computador", "pc", dict(pending=True, no_pc=True)),
        ("cierra spotify", "pc", dict(pending=True, no_pc=True)),
    ]),
    ("Agenda: evaluaciones, clases y eventos", [
        ("¿Qué evaluaciones tengo, próximamente?", "agenda",
         dict(reply=r"3 evaluaciones: Control de Evalua mañana a las 16:15; Control de Lenguajes el viernes 13 a las 14:00; Control de Introducción a la Programación el sábado 14 a las 8:30\.$")),
        ("¿Cuándo es mi siguiente evaluación?", "agenda", dict(reply=r"Lo próximo es Control de Evalua mañana a las 16:15 en B01, B04")),
        ("¿cuándo es el control de Evalua?", "agenda", dict(reply=r"Control de Evalua mañana")),
        ("qué tengo mañana", "agenda", dict(reply=r"para mañana veo 1 evento: Control de Evalua a las 16:15")),
        # uso real: el modelo contestó con correos inventados ("le he dado un vistazo a su correo…")
        ("¿Cómo se viene mi semana?", "agenda", dict(reply=r"esta semana|próxima semana")),
        ("¿Qué tal la próxima semana?", "agenda", dict(reply=r"próxima semana")),
        ("¿Qué tengo esta semana?", "agenda",
         dict(reply=r"5 eventos: Control de Evalua.*Auxiliar de Introducción a la Programación el jueves 12.*Laboratorio el viernes 13 a las 10:15.*Control de Lenguajes.*Control de Introducción")),
        ("¿Qué clases tengo el martes?", "agenda", dict(reply=r"2 clases: Cátedra de Lenguajes a las 10:15 en G108; Cátedra de Redes a las 12:00 en B08")),
        ("mi horario del jueves", "agenda", dict(reply=r"Cátedra de EH a las 10:15.*Auxiliar de Introducción a la Programación a las 18:00 en S03, S05")),
        ("¿cuándo tengo e hache?", "agenda", dict(reply=r"Lo próximo es Cátedra de EH el jueves 12")),
        ("qué tengo de redes esta semana", "agenda", dict(reply=r"de Redes: Cátedra de Redes mañana.*Auxiliar de Redes el miércoles 11")),
        ("qué entregas tengo", "agenda",
         dict(reply=r"No veo entregas para los próximos 7 días.*La siguiente es Tarea 3 de Lenguajes el viernes 20 a las 23:59")),
        ("¿quién es el auxiliar de redes?", "modelo", dict()),
        ("¿Cómo estuvo el dólar esta semana?", "modelo", dict()),
        ("pon música de redes", "pc", dict(pc={"action": "play_music"})),
    ]),
    ("Agenda: repreguntas", [
        ("¿Cuál es la próxima tarea que tengo que entregar?", "agenda", dict(reply=r"Lo próximo es Tarea 3 de Lenguajes el viernes 20")),
        ("Y para redes.", "agenda", dict(reply=r"No veo entregas de Redes")),
        ("¿Qué tengo esta semana?", "agenda", dict(reply=r"5 eventos")),
        ("Y para la próxima semana.", "agenda", dict(reply=r"para la próxima semana veo 3 eventos: Reunión con Felipe el martes 17 a las 17:00; Auxiliar de Introducción a la Programación el jueves 19 a las 18:00; Tarea 3 de Lenguajes")),
        ("¿y mañana?", "agenda", dict(reply=r"para mañana veo 1 evento: Control de Evalua")),
        ("¿cuándo es el próximo control?", "agenda", dict(reply=r"Control de Evalua")),
        ("¿y de Lenguajes?", "agenda", dict(reply=r"Lo próximo es Control de Lenguajes el viernes 13")),
        ("¿y de la progra?", "agenda", dict(reply=r"Control de Introducción a la Programación el sábado 14")),
        ("gracias", "modelo", dict()),
        ("y el clima de mañana", "clima", dict(reply=r"^Mañana en Santiago, señor: parcialmente nublado, mínima de 12° y máxima de 27°")),
    ]),
    ("Clima directo: Santiago si no nombra ciudad (uso real: preguntaba la ciudad)", [
        ("¿Cómo estará el clima mañana?", "clima", dict(reply=r"^Mañana en Santiago, señor: parcialmente nublado, mínima de 12° y máxima de 27°, con 10% de probabilidad de lluvia\.$")),
        ("¿Qué tiempo hace?", "clima", dict(reply=r"^Ahora en Santiago hay 21°, despejado, señor\. Hoy: mínima de 11° y máxima de 25°")),
        ("¿Va a llover pasado mañana?", "clima", dict(reply=r"^Sí, probablemente llueva\. Pasado mañana en Santiago, señor: con lluvia")),
        ("¿Cuál es la temperatura en Valparaíso?", "clima", dict(reply=r"^Ahora en Valparaíso hay 21°")),
        ("¿Cuánto tiempo falta para el viernes?", "modelo", dict()),  # «tiempo» solo no es clima
    ]),
    ("Agenda: «¿cuánto falta para la reunión…?» (uso real 18:53: «no tengo esa cita»)", [
        ("¿Cuánto falta para la reunión con Felipe?", "agenda", dict(reply=r"^Reunión con Felipe es el martes 17 a las 17:00; faltan 8 días, señor\.$")),
        ("¿Cuánto falta para la reunión de esta tarde?", "agenda", dict(reply=r"^No tiene reuniones hoy, señor\. La siguiente es Reunión con Felipe el martes 17")),
        ("¿cuánto falta para el control?", "agenda", dict(reply=r"^Control de Evalua es mañana a las 16:15; faltan 1 día y 7 horas, señor\.$")),
        ("¿a qué hora es el control de Lenguajes?", "agenda", dict(reply=r"^Control de Lenguajes es el viernes 13 a las 14:00")),
        ("¿cuánto falta para el viernes?", "basico", dict(reply=r"Faltan 4 días para el viernes")),
    ]),
    ("Calendario: fijar eventos (siempre con confirmación)", [
        ("Agéndame una reunión con Felipe mañana a las 5 de la tarde", "calendario",
         dict(pending=True, reply=r"«Reunión con Felipe», mañana martes 10 de 17:00 a 18:00")),
    ]),
    ("Calendario: «haz un cupo» con el día de lo que se venía hablando (uso real 01:30)", [
        ("Pero cuál es mi agenda el jueves", "agenda", dict()),
        ("Podríamos poner una sesión de Shoot Maxing a las 6", "calendario",
         dict(pending=True, reply=r"«Sesión de Shoot Maxing», el jueves 12 de noviembre de 18:00 a 19:00.*se llama")),
        ("¿Podemos hacer un cupo para una sesión de chud maxxing a las 18:00?", "calendario",
         dict(pending=True, reply=r"«Sesión de chud maxxing», el jueves 12 de noviembre de 18:00 a 19:00")),
        ("hazme un cupo el viernes a las 10 para estudiar", "calendario", dict(pending=True, reply=r"«Estudiar», el viernes 13")),
        ("haz un resumen ejecutivo", "resumen", dict()),
    ]),
    ("Calendario: más formas", [
        ("Recuérdame llamar al dentista el lunes a las 9", "calendario", dict(pending=True, reply=r"«Llamar al dentista», el lunes 16 de noviembre de 9:00 a 10:00")),
    ]),
    ("Calendario: rango y fecha con número", [
        ("Fija el control de Lenguajes para el viernes 27 a las 2 de la tarde", "calendario",
         dict(pending=True, reply=r"«Control de Lenguajes», el viernes 27 de noviembre de 14:00 a 15:00")),
    ]),
    ("Calendario: preguntar lo que falta", [
        ("agenda una reunión", "calendario", dict(pending=False, reply=r"¿Para qué día y a qué hora")),
        ("el jueves de 3 a 5", "calendario", dict(pending=True, reply=r"«Reunión», el jueves 12 de noviembre de 15:00 a 17:00")),
    ]),
    ("Calendario: borrar, reemplazar y mover (siempre con confirmación)", [
        ("Borra el laboratorio que creaste para las DEI cuarto este el próximo viernes y pon laboratorio de ciberseguridad en el mismo horario.",
         "calendario", dict(pending=True, no_pc=True,
                            reply=r"cambiar el evento «Laboratorio» \(el viernes 13 de noviembre de 10:15 a 11:45\) por «Laboratorio de ciberseguridad»")),
        ("borra la reunión con Felipe", "calendario", dict(pending=True, reply=r"borrar de Google Calendar el evento «Reunión con Felipe», el martes 17")),
        ("mueve la reunión con Felipe al jueves a las 6", "calendario",
         dict(pending=True, reply=r"mover el evento «Reunión con Felipe» de el martes 17 de noviembre de 17:00 a 18:00 a el jueves 12 de noviembre de 18:00 a 19:00")),
        ("borra la reunión con el decano", "calendario", dict(pending=False, reply=r"No encontré «Reunión con el decano»")),
        # uso real 17-11: «Elimina el evento de hoy a las 11 de la mañana» buscaba un evento LLAMADO «Hoy a las 11…»
        ("Elimina el evento del martes 17 a las 5 de la tarde", "calendario",
         dict(pending=True, reply=r"borrar de Google Calendar el evento «Reunión con Felipe», el martes 17")),
        ("elimina el evento del martes 17 a las 5", "calendario", dict(pending=True, reply=r"«Reunión con Felipe»")),
        ("Elimina el evento del viernes a las 10 de la mañana", "calendario", dict(pending=True, reply=r"el evento «Laboratorio»")),
        ("Elimina el evento de hoy a las 11 de la mañana", "calendario",
         dict(pending=False, reply=r"^No encontré ningún evento en su Google Calendar hoy a las 11:00, señor\.")),
        ("borra el evento del martes 17 a las 9 de la mañana", "calendario",
         dict(pending=False, reply=r"^No encontré ningún evento en su Google Calendar el martes 17 a las 9:00")),
        ("pon laboratorio de ciberseguridad el viernes a las 10 y cuarto", "calendario",
         dict(pending=True, no_pc=True, reply=r"«Laboratorio de ciberseguridad», el viernes 13 de noviembre de 10:15 a 11:15")),
        ("quita el like", "pc", dict(pc={"action": "like_music", "command": "unlike"})),
        ("cancela el apagado", "pc", dict(pc={"action": "cancel_shutdown"})),
        ("olvida lo del router", "memoria", dict()),
    ]),
    ("Calendario: corregir el nombre del evento recién creado", [
        ("Agenda un evento el próximo viernes de 10 y cuarto a doce que sea en Laboratorio de Ciudad Seguridad.", "calendario",
         dict(pending=True, confirm=True, reply=r"«Laboratorio de Ciudad Seguridad», el viernes 13 de noviembre de 10:15 a 12:00")),
        ("Era laboratorio de ciberseguridad, puedes modificar el nombre.", "calendario",
         dict(pending=True, reply=r"cambiar el nombre del evento «Laboratorio de Ciudad Seguridad» .* por «Laboratorio de ciberseguridad»")),
    ]),
    ("Calendario: eventos de varios días y frases mal transcritas", [
        ("Quiero que también agentes else mismo viernes después de la 8 hasta el domingo a medianoche en un evento llamado Jacatón",
         # equivalencias.json: "Jacatón" -> "Hackathon"
         "calendario", dict(pending=True, reply=r"«Hackathon», desde el viernes 13 de noviembre a las 8:00 hasta el domingo 15 de noviembre a las 23:59")),
        ("Agenda hackathon desde el viernes a las 8 de la noche hasta el domingo a medianoche", "calendario",
         dict(pending=True, reply=r"«Hackathon», desde el viernes 13 de noviembre a las 20:00 hasta el domingo 15 de noviembre a las 23:59")),
        ("agéndame vacaciones del lunes hasta el viernes", "calendario", dict(pending=True, reply=r"«Vacaciones», desde .* hasta el viernes 13 de noviembre, días completos")),
        ("también agéndame dentista el martes a las 4", "calendario", dict(pending=True, reply=r"«Dentista», mañana martes 10 de 16:00 a 17:00")),
    ]),
    ("Calendario: describir el evento sin nombre y decirlo después", [
        ("Tiene que ser un evento que dure desde el próximo viernes, desde la 8 de la noche, hasta la 23.59 Del próximo domingo también.",
         "calendario", dict(pending=False, reply=r"desde el viernes 13 de noviembre a las 20:00 hasta el domingo 15 de noviembre a las 23:59\. ¿Qué nombre")),
        ("Se llama Hackathon", "calendario", dict(pending=True, reply=r"«Hackathon», desde el viernes 13 de noviembre a las 20:00 hasta el domingo 15 de noviembre a las 23:59")),
    ]),
    ("Calendario: título limpio", [
        ("Agenda en Google Calendar entrevista Natalia Ibáñez el viernes a las 9 y media", "calendario",
         dict(pending=True, reply=r"«Entrevista Natalia Ibáñez», el viernes 13 de noviembre de 9:30 a 10:30")),
        ("quiero un evento el martes a las 10 llamado revisión de tareas", "calendario", dict(pending=True, reply=r"«Revisión de tareas», mañana martes 10 de 10:00 a 11:00")),
    ]),
    ("Calendario: corregir el nombre de un evento cualquiera", [
        ("Corrige el nombre del evento en Google Calendar entrevista Natalia Ibáñez a entrevista Natalia Ibáñez.", "calendario",
         dict(pending=True, reply=r"cambiar el evento «En Google Calendar Entrevista Natalia Ibáñez» \(el viernes 27 de noviembre de 9:30 a 10:30\) por «Entrevista Natalia Ibáñez»")),
        ("cámbiale el nombre a la reunión con Felipe por reunión de equipo", "calendario",
         dict(pending=True, reply=r"«Reunión con Felipe».* por «Reunión de equipo»")),
        ("renombra el laboratorio a laboratorio de redes", "calendario", dict(pending=True, reply=r"«Laboratorio».* por «Laboratorio de redes»")),
    ]),
    ("Música: canción al azar de sus Me gusta", [
        ("pon una canción al azar de las que me gustan", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("ponme algo de mis me gusta", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        # uso real: «de mis favoritos» se guardaba como artista «Pon una canción»; «mis me gustas» buscaba «Me Gusta»
        ("Pon una canción de mis favoritos", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("Pon una canción de mis me gustas", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("agrega a Mitski a mis favoritos", "memoria", dict(no_pc=True, reply=r"Agregué a sus recomendaciones: «Mitski»")),
        ("pon mis favoritas", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("pon una canción aleatoria", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("elige una canción de las que me gustan", "pc", dict(pc={"action": "play_music", "query": "liked"})),
        ("me gusta esta canción", "pc", dict(pc={"action": "like_music"})),
        ("pon música de Ado", "pc", dict(pc={"action": "play_music", "query": "Ado"})),
    ]),
    ("Calendario: lo que NO es un evento", [
        ("tiene que ser más temprano", "modelo", dict(pending=False)),
        ("pon algo de Sheena Ringo", "pc", dict(pc={"action": "play_music"})),
        ("pon Ado", "pc", dict(pc={"action": "play_music", "query": "ado"})),
        ("ponme una canción de Blue Swing", "pc", dict(pc={"action": "play_music"})),
        ("pon música de Ado", "pc", dict(pending=False)),
        ("con música de Ado", "pc", dict(pc={"action": "play_music", "query": "Ado"})),  # «pon» mal transcrito (uso real)
        ("son una canción de Sheena Ringo", "pc", dict(pc={"action": "play_music"})),
        # uso real 00:25: la voz oyó "Juan" en vez de "pon"
        ("Juan Hotel California.", "pc", dict(pc={"action": "play_music", "query": "hotel california"})),
        ("Con Bohemian Rhapsody", "pc", dict(pc={"action": "play_music", "query": "bohemian rhapsody"})),
        ("Juan es auxiliar de Redes.", "memoria", dict(no_pc=True)),  # se guarda como nota, no es música
        ("con quién hablo", "modelo", dict(no_pc=True)),
        ("con quién hablo", "modelo", dict(no_pc=True)),
        ("pon una alarma a las 5", "recordatorio", dict(pending=False, reply=r"Alarma puesta para las 17:00, señor\.$")),
        ("marca como leídos los correos", "correo", dict(pending=True)),
    ]),
    ("Agenda: tareas de U-Cursos (Otros eventos > Tareas), sin repetir, la semana que viene", [
        # Introducción a la Programación la dicta él (auxiliar, ramos.json "dicto"): esas tareas son de sus alumnos
        ("¿Qué tareas tengo?", "agenda",
         # misma hora: se agrupan ("el miércoles 11 a las 23:59 tiene A y B")
         dict(reply=r"^(?!.*Introducci).*para los próximos 7 días veo 2 entregas: "
                    r"el miércoles 11 a las 23:59 tiene (Tarea 2 de Redes y Actividad 7 - BGP de Redes|Actividad 7 - BGP de Redes y Tarea 2 de Redes)\.$")),
        ("¿qué tareas tengo de introducción a la programación?", "agenda", dict(reply=r"^(?!.*Tarea 3a)(?!.*Tarea 4)")),
        ("¿qué tareas tengo de redes?", "agenda", dict(reply=r"veo 2 entregas de Redes")),
        ("¿Cuál es la próxima tarea?", "agenda", dict(reply=r"Lo próximo es Tarea 2 de Redes el miércoles 11")),
        ("¿qué tareas tengo de Lenguajes?", "agenda",
         dict(reply=r"No veo entregas de Lenguajes para los próximos 7 días.*La siguiente es Tarea 3 de Lenguajes el viernes 20")),
        ("¿Qué tengo esta semana?", "agenda", dict(reply=r"el miércoles 11 a las 23:59 tiene .*Tarea 2 de Redes")),
        # uso real: la voz entendió "tareo"; "esta semana" en tareas = los próximos 7 días
        ("¿Qué tareo para esta semana?", "agenda", dict(reply=r"para los próximos 7 días veo 2 entregas")),
        ("qué tareas tengo para esta semana", "agenda", dict(reply=r"para los próximos 7 días veo 2 entregas")),
    ]),
    # pedido del usuario (15-11-2026): «Las tareas debo poder marcarlas como listas… ya terminé todo lo de redes»
    ("Marcar tareas de U-Cursos como listas: dejan de salir; se puede deshacer; pide confirmación", [
        ("Ya terminé todo lo de redes", "tareas",
         dict(pending=True, confirm=True,
              reply=r"^Preparado, señor: marcar como listas las 2 tareas: (Tarea 2 de Redes y Actividad 7 - BGP de Redes|"
                    r"Actividad 7 - BGP de Redes y Tarea 2 de Redes)\. Dejarán de salir y de avisarle\. Confírmelo")),
        ("¿qué tareas tengo de redes?", "agenda", dict(reply=r"^(?!.*Actividad 7)(?!.*Tarea 2 de Redes)")),
        ("¿Qué tareas tengo?", "agenda", dict(reply=r"^(?!.*Redes)")),
        ("ya terminé la tarea 2 de redes", "tareas", dict(pending=False, reply=r"^Ya estaba marcada como lista, señor: Tarea 2 de Redes\.$")),
        ("desmarca la actividad 7", "tareas",
         dict(pending=True, confirm=True, reply=r"^Preparado, señor: desmarcar Actividad 7 - BGP de Redes, para que vuelva")),
        ("¿qué tareas tengo de redes?", "agenda", dict(reply=r"Actividad 7 - BGP de Redes(?!.*Tarea 2 de Redes)")),
        ("marca la actividad siete de redes como lista", "tareas", dict(pending=True, reply=r"marcar como lista Actividad 7 - BGP de Redes\. Dejará de")),
        ("la tarea 3 de lenguajes ya está lista", "tareas", dict(pending=True, reply=r"marcar como lista Tarea 3 de Lenguajes")),
        # sin decir cuál: no adivina, dice cuáles le quedan
        ("ya terminé la tarea", "tareas", dict(pending=False, reply=r"^No encontré esa tarea, señor\. Las que tiene pendientes son: .*Actividad 7")),
        ("terminé las tareas de química", "tareas", dict(pending=False, reply=r"^No encontré esa tarea")),
        ("desmarca la tarea de evalua", "tareas", dict(pending=False, reply=r"^No tengo marcada como lista")),
    ]),
    ("Resumen ejecutivo: agenda, entregas, correos sin leer y clima juntos (uso real 01:13)", [
        ("Hazme un resumen ejecutivo", "resumen", dict(gmail={"action": "unread"}, hint=r"resumen ejecutivo")),
        ("¿cómo viene mi día?", "resumen", dict(hint=r"resumen ejecutivo")),
        ("resumen ejecutivo de este correo", "correo", dict()),
        # uso real 17-11-2026: lo tomaba el modelo y respondía (inventando) con los no leídos
        ("¿De quién estamos esperando correo ahora?", "vigilancia", dict(pending=False, reply=r"esperando")),
    ]),
    ("Claude apagado (17-11-2026, Atlas puramente local): «pregúntale a Claude…» lo contesta el modelo local", [
        ("Claude, ¿cuál es la capital de Mongolia?", "modelo", dict(pending=False)),
        ("pregúntale a Claude si conviene usar Rust", "modelo", dict()),
        ("Pregúntale a clod qué es un LLM", "modelo", dict()),
        ("háblalo con Claude", "modelo", dict()),
        ("abre claude", "pc", dict(pc={"action": "open_website"})),
        ("cloud computing qué es", "modelo", dict()),
        ("recuérdame en 5 minutos llamar a Claudio", "recordatorio", dict()),
    ]),
    ("Recordatorios: crear y consultar no piden confirmación; cancelar varios sí", [
        ("recuérdame en 20 minutos sacar la ropa", "recordatorio",
         dict(pending=False, reply=r"Le recordaré en 20 minutos, a las 9:20: sacar la ropa\.")),
        ("pon un temporizador de 5 minutos", "recordatorio", dict(pending=False, reply=r"Temporizador de 5 minutos en marcha, señor\. Le aviso a las 9:05")),
        ("qué recordatorios tengo", "recordatorio",
         dict(reply=r"Tiene 2 pendientes, señor: temporizador de 5 minutos: le quedan 5 minutos; «sacar la ropa» a las 9:20, en 20 minutos")),
        ("cuánto le queda al temporizador", "recordatorio", dict(reply=r"le quedan 5 minutos")),
        ("cancela el temporizador", "recordatorio", dict(pending=False, reply=r"Cancelé temporizador de 5 minutos")),
        ("Recuérdame sacar la ropa en una hora y media", "recordatorio", dict(reply=r"en 1 hora y 30 minutos, a las 10:30: sacar la ropa")),
        ("pon una alarma a las 7 de la mañana", "recordatorio", dict(reply=r"Alarma puesta mañana para las 7:00")),
        ("avísame a las 6 que llame a mi mamá", "recordatorio", dict(reply=r"a las 18:00: llame a mi mamá")),
        ("borra el recordatorio de la ropa", "recordatorio", dict(reply=r"Tiene 2, señor.*¿Cuál cancelo", pending=False)),
        ("cancela todos los recordatorios", "recordatorio", dict(pending=True, reply=r"cancelar 4 pendientes")),
        ("Recuérdame llamar al dentista el lunes a las 9", "calendario", dict(pending=True)),
        ("cancela el apagado", "pc", dict(pc={"action": "cancel_shutdown"})),
        ("olvida lo del router", "memoria", dict()),
    ]),
    ("Recordatorios: preguntar lo que falta", [
        ("pon un temporizador", "recordatorio", dict(reply=r"¿De cuánto tiempo")),
        ("de 10 minutos", "recordatorio", dict(reply=r"Temporizador de 10 minutos en marcha")),
        ("pon una alarma", "recordatorio", dict(reply=r"¿A qué hora")),
        ("a las 8 de la noche", "recordatorio", dict(reply=r"Alarma puesta para las 20:00")),
        ("qué tengo mañana", "agenda", dict()),
    ]),
    ("Alarmas: la hora como la transcribe la voz (uso real: «6 horas 38 minutos»)", [
        ("Puedes poner una alarma para las... para las 0.38", "recordatorio", dict(reply=r"^Alarma puesta mañana para las 0:38, señor\.$")),
        ("pon una alarma", "recordatorio", dict(reply=r"¿A qué hora")),
        ("A las 6 horas 38 minutos.", "recordatorio", dict(reply=r"^Alarma puesta para las 18:38, señor\.$")),
        ("pon una alarma", "recordatorio", dict(reply=r"¿A qué hora")),
        ("6 horas 38 minutos", "recordatorio", dict(reply=r"^Alarma puesta para las 18:38, señor\.$")),
        ("pon una alarma a las 7 horas y 5 minutos de la mañana", "recordatorio", dict(reply=r"mañana para las 7:05")),
        ("pon una alarma para las 10:15", "recordatorio", dict(reply=r"^Alarma puesta para las 10:15, señor\.$")),
    ]),
    ("Contactos: número de teléfono desde la libreta (solo consulta)", [
        ("¿Cuál es el número de Tipo?", "contactos", dict(no_pc=True, pending=False, reply=r"Sebastián Lagos es \+56 9 8765 4321")),
        ("dame el teléfono de Sebastián Lagos", "contactos", dict(no_pc=True, reply=r"\+56 9 8765 4321")),
        ("qué celular tiene tipo", "contactos", dict(no_pc=True, reply=r"\+56 9 8765 4321")),
        ("cuál es el número de teléfono de Camila", "contactos", dict(no_pc=True, reply=r"no tiene número de teléfono")),
        ("cuál es el teléfono de Ramiro", "contactos", dict(no_pc=True, reply=r"no está en su libreta")),
        # «llama a X» sin plataforma: por WhatsApp de escritorio (el Bluetooth del PC no pasa la voz de Enlace Móvil),
        # con el número de la libreta y siempre con confirmación
        ("llama a Tipo", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos \(\+56987654321\)")),
        ("Quiero que llames a Tipo al celular", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        ("llama a Camila", "contactos", dict(no_pc=True, pending=False, reply=r"Camila Soto no tiene número de teléfono")),
        ("llama a Tipo por Discord", "discord", dict(pending=True, no_pc=True)),
        # uso real: la voz oye «llama a Pipe» como «Dana a Pipe» o deforma el nombre («Pee pe»)
        ("Dana a Tipo", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        ("Yama a Tipo.", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        ("Llama a Tippo", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        # uso real: «Llana a pipe» y después «Por teléfono» como respuesta (no es ruido)
        ("Jana a Tipo", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        ("Te acabo de decir que quiero llamar a Tipo por teléfono", "contactos", dict(no_pc=True, pending=True, reply=r"lamar por WhatsApp a Sebastián Lagos")),
        ("Llana a Camila", "contactos", dict(no_pc=True, pending=False, reply=r"Camila Soto no tiene número")),
    ]),
    ("Contactos en eventos: asociar, consultar y sacar (sin confirmación; no avisa a nadie todavía)", [
        ("agrega a Tipo y Camila a la reunión con Felipe", "contactos", dict(no_pc=True, pending=False,
         reply=r"Asocié a Sebastián Lagos, Camila Soto a «Reunión con Felipe»")),
        ("¿quiénes van a la reunión con Felipe?", "contactos", dict(reply=r"están: Sebastián Lagos, Camila Soto")),
        ("saca a Camila de la reunión con Felipe", "contactos", dict(reply=r"Saqué a Camila Soto.*Ahora tiene: Sebastián Lagos")),
        # uso real: el evento antes que las personas y con «quiero que…» caía en «¿para qué día lo agendo?»
        ("Quiero que añadas a la reunión con Felipe al tipo y a Toño", "contactos",
         dict(no_pc=True, pending=False, reply=r"Asocié a Sebastián Lagos, Antonio Fuenzalida a «Reunión con Felipe»")),
        ("saca de la reunión con Felipe a Toño", "contactos", dict(reply=r"Saqué a Antonio Fuenzalida")),
        ("agrega a Ramiro a la reunión con Felipe", "contactos", dict(reply=r"no encontré en su libreta a Ramiro")),
        ("agrega a Toño al laboratorio", "contactos", dict(reply=r"Asocié a Antonio Fuenzalida")),
        ("borra la reunión con Felipe", "calendario", dict(pending=True)),
    ]),
    ("Choques de horario: los calcula Atlas con la agenda, no el modelo (uso real: Redes 12:00-13:30 vs almorzar a la una)", [
        ("Quiero almorzar a la una. ¿Cuál de esas me choca?", "agenda",
         dict(no_pc=True, pending=False, reply=r"^Sí, señor: hoy de 13:00 a 14:00 le choca Cátedra de Introducción a la Programación, de 12:45 a 14:15\.$")),
        ("¿Estoy libre mañana a las 10?", "agenda", dict(no_pc=True, reply=r"^No, señor: mañana de 10:00 a 11:00 le choca Cátedra de Lenguajes")),
        ("¿me choca algo a las 5 de la tarde?", "agenda", dict(no_pc=True, reply=r"^No le choca nada, señor: hoy de 17:00 a 18:00 está libre")),
        ("¿tengo libre de 4 a 6?", "agenda", dict(no_pc=True, reply=r"^Sí, señor: hoy de 16:00 a 18:00 está libre")),
        ("agenda almorzar a la una", "calendario", dict(pending=True)),
    ]),
    ("Pendientes sin fecha: anotar, consultar, marcar como hecho y borrar (sin confirmación)", [
        ("¿Qué tengo pendiente?", "pendientes", dict(no_pc=True, pending=False, reply=r"^No tiene nada pendiente, señor\.$")),
        ("Anota comprar pan como pendiente", "pendientes", dict(no_pc=True, pending=False, reply=r"^Anotado como pendiente, señor: Comprar pan\.$")),
        ("Recuérdame hacer la tarea de Redes", "pendientes", dict(no_pc=True, pending=False, reply=r"Hacer la tarea de Redes\. Tiene 2 en la lista")),
        ("Pendiente: pagar la luz", "pendientes", dict(no_pc=True, reply=r"Pagar la luz\. Tiene 3")),
        ("mis pendientes", "pendientes", dict(no_pc=True, reply=r"Tiene 3 pendientes, señor: 1, Comprar pan; 2, Hacer la tarea de Redes; 3, Pagar la luz\.")),
        ("Ya terminé el pendiente de comprar pan", "pendientes", dict(no_pc=True, reply=r"marqué como hecho «Comprar pan»\. Le quedan 2")),
        ("borra el pendiente de pagar la luz", "pendientes", dict(no_pc=True, reply=r"Borré el pendiente «Pagar la luz»")),
        ("marca el pendiente 1 como hecho", "pendientes", dict(no_pc=True, reply=r"«Hacer la tarea de Redes»\. No le queda nada pendiente")),
        ("borra el pendiente de lavar el auto", "pendientes", dict(no_pc=True, reply=r"No encontré ese pendiente")),
        ("Recuérdame mañana a las 9 comprar pan", "recordatorio", dict(no_pc=True)),
        ("recuérdame en 10 minutos sacar la ropa", "recordatorio", dict(no_pc=True)),
    ]),
    ("Accesos por nombre: Fortuna", [
        ("Fortuna", "acceso", dict(pc={"action": "open_website", "target": "https://claude.ai/project/prueba"}, reply=r"Abrí Fortuna")),
        ("abre Fortuna", "acceso", dict(pc={"action": "open_website", "target": "https://claude.ai/project/prueba"})),
        # la voz escribe el nombre distinto (uso real 16-11-2026: «Apolo» salió «Apollo» y Atlas preguntó qué hacer)
        ("Fortunna", "acceso", dict(pc={"action": "open_website", "target": "https://claude.ai/project/prueba"})),
        ("abre Fortúnna", "acceso", dict(pc={"action": "open_website", "target": "https://claude.ai/project/prueba"})),
        ("Abre el proyecto Fortuna, por favor.", "acceso", dict(pc={"action": "open_website"})),
        ("abre youtube", "pc", dict(pc={"action": "open_website", "target": "youtube"})),
        ("qué es Fortuna", "apps", dict(no_pc=True, reply=r"fondos mutuos")),   # 18-11-2026: lo describe Atlas, no abre nada
    ]),
    ("Telegram y WhatsApp: mensajes a contactos de la libreta (uso real: «Benji por Telegram» lo inventó el modelo)", [
        ("Mándale un hola a Toño por Telegram", "discord",
         dict(pending=True, no_pc=True, reply=r"[Tt]elegram a Antonio Fuenzalida \(@antonio_f en Telegram\).*«hola»")),
        ("escríbele hola a Tipo por wsp", "discord",
         dict(pending=True, no_pc=True, reply=r"WhatsApp a Sebasti[aá]n Lagos \(\+56987654321 en WhatsApp\).*«hola»")),
        ("dile a Tipo por WhatsApp que voy tarde", "discord", dict(pending=True, no_pc=True, reply=r"«voy tarde»")),
        # uso real 17-11-2026: quedaba «diciéndole estoy muy agradecido … Muchas» (sin «gracias»)
        ("Mándale un mensaje por Telegram a Toño diciéndole estoy muy agradecido por haber podido probar tu juego. Muchas gracias", "discord",
         dict(pending=True, no_pc=True, reply=r"«Estoy muy agradecido por haber podido probar tu juego\. Muchas gracias»")),
        ("mándale a Camila por WhatsApp: hola", "discord", dict(pending=False, no_pc=True, reply=r"sin número de teléfono")),
        ("mándale a Ramiro por Telegram: hola", "discord", dict(pending=False, no_pc=True, reply=r"no está en su libreta")),
        ("llama a Tipo por WhatsApp", "discord", dict(pending=True, no_pc=True, reply=r"lamar por WhatsApp a Sebasti[aá]n Lagos")),
        ("llama a Tipo por Telegram", "discord", dict(pending=False, no_pc=True, reply=r"sé llamar por Discord y WhatsApp")),
        ("Manda un... Hola Tipo a WhatsApp. A Tipo", "discord",
         dict(pending=True, no_pc=True, reply=r"WhatsApp a Sebasti[aá]n Lagos.*«Hola tipo»")),
        ("mándale a Tipo por Discord: a las 5", "discord", dict(pending=True, no_pc=True, reply=r"Discord a Sebasti[aá]n Lagos.*«a las 5»")),
        ("Entonces envía un... Hola a Tipo a Tipo por WhatsApp", "discord",
         dict(pending=True, no_pc=True, reply=r"WhatsApp a Sebasti[aá]n Lagos.*«Hola»")),
        ("Envía un. Hola Tipo por WhatsApp. A Tipo", "discord", dict(pending=True, no_pc=True, reply=r"«Hola tipo»")),
    ]),
    ("Discord: mensajes y llamadas por la app, solo a contactos de la libreta (siempre con confirmación)", [
        ("llama a Benja por Discord", "discord", dict(pending=False, no_pc=True, reply=r"no está en su libreta")),
        ("Atlas, mándale a Benja por Discord: hola", "discord", dict(pending=False, no_pc=True, reply=r"no está en su libreta")),
        ("llama a Camila por Discord", "discord", dict(pending=False, no_pc=True, reply=r"sin usuario de Discord")),
        ("Benja en Discord es benja_ejemplo", "discord", dict(pending=False, no_pc=True, reply=r"Anotado en sus contactos")),
        ("Atlas, mándale a Benja por Discord: voy tarde, empiecen sin mí.", "discord",
         dict(pending=True, no_pc=True, reply=r"Benja \(@benja_ejemplo en Discord\).*«voy tarde, empiecen sin mí»")),
        ("dile a benja por discord que llego en 10 minutos", "discord",
         dict(pending=True, no_pc=True, reply=r"«llego en 10 minutos»")),
        ("envíale un mensaje por Discord a Benja diciendo que ya salí", "discord",
         dict(pending=True, no_pc=True, reply=r"Benja.*«ya salí»")),
        ("Mándale a Benja por Discord", "discord", dict(pending=False, no_pc=True, reply=r"Qué mensaje")),
        ("llama a Benja por Discord", "discord", dict(pending=True, no_pc=True, reply=r"[Ll]lamar por Discord.*@benja_ejemplo")),
        ("hazle una llamada a Benja por discord", "discord", dict(pending=True, no_pc=True, reply=r"Benja")),
        ("mándale a Benja por Discord: hola", "discord", dict(pending=True, confirm=True, reply=r"«hola»")),
        # uso real: la voz oyó «Disco» y el mensaje va antes del destinatario (Tipo es un apodo de la libreta)
        ("escríbele hola a tipo por Disco", "discord", dict(pending=True, no_pc=True, reply=r"Sebastián Lagos \(@tipo0000 en Discord\).*«hola»")),
        # uso real: mismas órdenes con mándale/envíale/dile, con y sin tilde, «al tipo» y «por Discord. Hola»
        ("Escríbele hola a Tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("Escríbele hola al tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("mándale hola a Tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("mandale hola a tipo por discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("envíale hola a Tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("enviale hola a tipo por discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("dile hola a Tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("Mándale a Tipo por Discord. Hola", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000.*«hola»")),
        ("mándale un saludo a Tipo por Discord", "discord", dict(pending=True, no_pc=True, reply=r"«un saludo»")),
        ("escríbele a tipo por discord nos vemos mañana", "discord", dict(pending=True, no_pc=True, reply=r"«nos vemos mañana»")),
        ("mándale un mensaje a Tipo por Discord", "discord", dict(pending=False, no_pc=True, reply=r"Qué mensaje")),
        ("llama a tipo por disco", "discord", dict(pending=True, no_pc=True, reply=r"@tipo0000")),
        ("pon el disco de Ado", "pc", dict(no_pc=False)),
        ("abre discord", "pc", dict(pc={"action": "open_app", "name": "discord"})),
        ("cierra discord", "pc", dict(pending=True, no_pc=True)),
    ]),
]


def pruebas_directas(H, tmp) -> list[tuple[str, list[str]]]:
    """Lo que no pasa por route(): guardar en disco, avisar a la hora y avisar lo vencido al reiniciar."""
    import atlas_recordatorios as R

    out = []
    # Contactos en eventos: al borrar un evento con contactos, ofrece avisarles (texto exacto) y solo con un «sí» envía
    import atlas_avisos as AV
    import atlas_contactos as CT

    j = H.Atlas()
    j.refresh_inbox = lambda: None
    j.pc_raw = Fake("pc")
    sent = []
    AV.SEND = lambda canal, c, texto, asunto: (sent.append((canal, c["nombre"], texto)) or True, "ok")
    tipo = CT.find("Tipo")[0]
    toño = CT.find("Toño")[0]
    ev = {"id": "g9", "summary": "Cumpleaños de Pipe", "attendees": [{"email": "camila@uni.example"}]}
    AV.link(ev, [tipo, toño])
    j.pending = {"tool": H._CalendarTool(), "summary": "Borrar",
                 "params": {"op": "delete", "id": "g9", "summary": "Cumpleaños de Pipe", "when": "el sábado 21 a las 18:00",
                            "attendees": ev["attendees"]}}
    r1 = j.confirm(True)
    errs = []
    if not re.search(r"¿Les aviso\? Avisar a Sebastián Lagos por Discord \(@tipo0000\); Antonio Fuenzalida por Telegram "
                     r"\(@antonio_f\); Camila Soto por correo \(camila@uni\.example\) con el mensaje: «Hola, te aviso que se "
                     r"canceló «Cumpleaños de Pipe», que era el sábado 21 a las 18:00\.»", r1.get("reply", "")):
        errs.append(f"oferta: {r1.get('reply', '')[:300]!r}")
    if sent:
        errs.append("envió antes de que el usuario confirmara")
    if not (j.pending and j.pending["tool"].spec.name == "avisos"):
        errs.append("no quedó el aviso esperando confirmación")
    r2 = j.confirm(True) if j.pending else {}
    if [s[:2] for s in sent] != [("Discord", "Sebastián Lagos"), ("Telegram", "Antonio Fuenzalida"), ("correo", "Camila Soto")]:
        errs.append(f"envíos: {sent}")
    if not re.search(r"Avisé a Sebastián Lagos por Discord, Antonio Fuenzalida por Telegram, Camila Soto por correo", r2.get("reply", "")):
        errs.append(f"resultado: {r2.get('reply', '')[:200]!r}")
    if AV.linked({"id": "g9"}):
        errs.append("la asociación del evento borrado debía olvidarse")
    sent.clear()
    j.pending = {"tool": H._CalendarTool(), "summary": "Borrar", "params": {"op": "delete", "id": "g10", "summary": "Otro",
                                                                           "when": "mañana", "attendees": []}}
    r3 = j.confirm(True)
    if j.pending or "aviso" in r3.get("reply", "").lower():
        errs.append("un evento sin contactos no debe ofrecer avisos")
    j.pending = {"tool": H._CalendarTool(), "summary": "Borrar",
                 "params": {"op": "delete", "id": "g11", "summary": "Asado", "when": "hoy", "attendees": []}}
    AV.link({"id": "g11", "summary": "Asado"}, [tipo])
    j.confirm(True)
    j.confirm(False)
    if sent:
        errs.append("con «no» no debía avisar a nadie")
    AV.SEND = None
    out.append(("al borrar un evento con contactos ofrece avisarles con el texto exacto y solo envía con «sí»", errs))
    # Nombres por cómo suenan (uso real: dijo «Shego» y la voz escribió «Chevo»): un único candidato cercano
    book = [{"id": "s1", "nombre": "Diego Salas", "apodos": ["Shego"]}, {"id": "s2", "nombre": "Felipe Morales", "apodos": ["Pipe"]},
            {"id": "s3", "nombre": "Sebastián Lagos", "apodos": ["Tipo"]}]
    errs = []
    for heard, want in (("Chevo", "Diego Salas"), ("Chego", "Diego Salas"), ("Pee pe", "Felipe Morales"),
                        ("Tipo", "Sebastián Lagos")):
        got = [c["nombre"] for c in CT.find(heard, book)]
        if got != [want]:
            errs.append(f"{heard}: {got}")
    for heard in ("Gabo", "Carla"):
        if CT.find(heard, book):
            errs.append(f"{heard} no debía calzar con nadie")
    out.append(("contactos: nombres mal transcritos por la voz se buscan por cómo suenan («Chevo» -> Shego)", errs))
    # «a mi padre» (uso real: preguntaba entre Padre y Madre) y «papá» (caía por sonido en «Pp Tamia»)
    book = [{"id": "p1", "nombre": "Jorge Rivas", "apodos": ["Padre"]}, {"id": "p2", "nombre": "Patricia Rivas", "apodos": ["Madre"]},
            {"id": "p3", "nombre": "Felipe Tamia", "apodos": ["Pp Tamia"]}]
    errs = []
    for heard, want in (("mi padre", "Jorge Rivas"), ("a mi padre", "Jorge Rivas"), ("papá", "Jorge Rivas"),
                        ("mi mamá", "Patricia Rivas"), ("madre", "Patricia Rivas")):
        got = [c["nombre"] for c in CT.find(heard, book)]
        if got != [want]:
            errs.append(f"{heard}: {got}")
    out.append(("contactos: «mi padre», «papá», «mi mamá» llevan al apodo Padre/Madre", errs))
    # Corregir el texto de un mensaje pendiente (uso real: «Manda un Hola Sander por Discord. A Sander» y luego
    # «El mensaje es solo Hola Sander. Con Z»: lo tomaba el modelo y lo pendiente seguía con «un Hola Sander»)
    errs = []
    j = H.Atlas()
    j.refresh_inbox = lambda: None
    j.pc_raw = Fake("pc")
    j.pending = None
    r1 = j.route("Manda un Hola Tipo por WhatsApp. A Tipo")[1] or {}
    if "«Hola tipo»" not in r1.get("reply", ""):
        errs.append(f"crear: {r1.get('reply')!r}")
    r2 = j.route("El mensaje es solo Hola Tipo, qué tal. Con T")[1] or {}
    if not (j.pending and j.pending["params"].get("text") == "Hola tipo, q tal") or "Corregido" not in r2.get("reply", ""):
        errs.append(f"corregir: {r2.get('reply')!r} {j.pending and j.pending['params'].get('text')!r}")
    r3 = j.route("cámbialo a nos vemos mañana")[1] or {}
    if not (j.pending and j.pending["params"].get("text") == "nos vemos mañana"):
        errs.append(f"cambiar: {r3.get('reply')!r}")
    r4 = j.route("Ponala. El mensaje debía decir Hola, soy una IA")[1] or {}
    if not (j.pending and j.pending["params"].get("text") == "Hola, soy una IA"):
        errs.append(f"debía decir: {r4.get('reply')!r}")
    j.pending = None
    if j.route_msg_fix("el mensaje es solo hola") is not None:
        errs.append("sin nada pendiente no debe corregir nada")
    out.append(("mensaje pendiente: «el mensaje es solo …», «cámbialo a …» reemplazan el texto y vuelven a pedir confirmación", errs))
    # Sin decir la app (uso real: «Escríbele a Benji, hola, soy una IA» -> «No he hecho ni preparado ningún cambio»):
    # la app de la última vez con esa persona; si no hay, WhatsApp si tiene número, luego Telegram, luego Discord
    import tempfile
    errs = []
    orig_last = H.LAST_APP_FILE
    H.LAST_APP_FILE = Path(tempfile.mkdtemp()) / "ultima_app.json"
    try:
        j.pending = None
        # un solo canal: se usa directo
        for said, app, txt in (("dile a Toño que voy en camino", "telegram", "voy en camino"),
                               ("mándale a Benja: nos vemos", "discord", "nos vemos")):
            j.pending = None
            r = j.route(said)[1] or {}
            got = j.pending and (j.pending["params"].get("action"), j.pending["params"].get("text"))
            if got != (f"{app}_message", txt):
                errs.append(f"{said}: {got} {r.get('reply')!r}")
        # varios canales (Tipo: WhatsApp y Discord): pregunta la app, no asume (uso real: «debería haberme consultado»)
        j.pending = None
        r = j.route("Escríbele a Tipo, hola, soy una IA")[1] or {}
        if j.pending or "WhatsApp o Discord" not in r.get("reply", ""):
            errs.append(f"debía preguntar la app: {r.get('reply')!r} {j.pending and j.pending['params']}")
        j.route("por Discord")
        if not (j.pending and j.pending["params"].get("action") == "discord_message" and j.pending["params"].get("text") == "hola, soy una ia"):
            errs.append(f"«por Discord» debía preparar el mensaje en minúscula: {j.pending and j.pending['params']}")
        # por Discord todo en minúscula; WhatsApp y Telegram quedan igual (instrucción del usuario, 16-11-2026)
        j.pending = None
        j.route("mándale a Tipo por WhatsApp: Hola Tipo")
        if not (j.pending and j.pending["params"].get("text") == "Hola tipo"):
            errs.append(f"por WhatsApp solo el nombre va en minúscula: {j.pending and j.pending['params']}")
        j.route("no, por Discord")
        if not (j.pending and j.pending["params"].get("action") == "discord_message"
                and j.pending["params"].get("text") == "hola tipo" and "hola tipo" in j.pending["summary"]):
            errs.append(f"al cambiar a Discord debía quedar en minúscula: {j.pending and j.pending['params']}")
        # «que» y «qué» se escriben «q», en minúscula, en todas las apps (instrucción del usuario, 16-11-2026)
        j.pending = None
        j.route("mándale a Tipo por WhatsApp: Hola. Que bueno que vienes, a qué hora llegas")
        if not (j.pending and j.pending["params"].get("text") == "Hola. q bueno q vienes, a q hora llegas"
                and "«Hola. q bueno q vienes, a q hora llegas»" in j.pending["summary"]):
            errs.append(f"«que» debía quedar «q»: {j.pending and j.pending['params']}")
        j.pending = None
        j.route("mándale a Tipo por WhatsApp: Qué bueno que vienes")
        if not (j.pending and j.pending["params"].get("text") == "q bueno q vienes"):
            errs.append(f"«Qué bueno que vienes» debía quedar «q bueno q vienes»: {j.pending and j.pending['params']}")
        j.pending = None
        # varias apps en una orden (uso real 17-11-2026: «Escríbele hola a Antonio por Discord, Whatsapp y Telegram» tomó
        # «hola a Antonio» como contacto, el mensaje salió «whatsapp y telegram» y preparó solo Discord)
        for said in ("Escríbele hola a Tipo por Discord, Whatsapp y Telegram",
                     "Escríbele a Tipo Hola por Discord, WhatsApp y Telegram",
                     "Envíale a Tipo un hola por Discord, WhatsApp y Telegram"):
            j.pending = None
            r = j.route(said)[1] or {}
            envios = (j.pending or {}).get("params", {}).get("envios") or []
            if ([e.get("action") for e in envios] != ["discord_message", "whatsapp_message", "telegram_message"]
                    or any(e.get("text", "").lower() != "hola" for e in envios)
                    or "Telegram" not in r.get("reply", "") or "Confírmelo" not in r.get("reply", "")):
                errs.append(f"varias apps: {said} -> {r.get('reply')!r} {envios}")
        j.pending = None
        j.route("dile a Tipo por WhatsApp y por Discord que llego tarde")
        summ = (j.pending or {}).get("summary", "")
        if summ != "Enviar por WhatsApp y Discord a Sebastián Lagos el mensaje: «llego tarde»":
            errs.append(f"resumen de varias apps: {summ!r}")
        before = len(j.pc_raw.calls)
        done = j.confirm(True)
        sent = j.pc_raw.calls[before:]
        if [c.get("action") for c in sent] != ["whatsapp_message", "discord_message"] or "WhatsApp: hecho" not in done["reply"]:
            errs.append(f"enviar por varias apps tras el «sí»: {sent} {done}")
        j.pending = None
        j.route("Escríbele a Tipo por Discord y WhatsApp: Hola Juan")
        summ = (j.pending or {}).get("summary", "")
        if "Discord «hola juan»" not in summ or "WhatsApp «Hola Juan»" not in summ:
            errs.append(f"si el texto cambia por app, se muestra el de cada una: {summ!r}")
        j.pending = None
        # apodos que la voz escribe distinto: «Sander» es Zander (uso real 16-11-2026: «le dije que le escribiera a
        # Zander, y lo escribe como Sander»)
        import atlas_contactos as CT

        zk = CT.upsert({"nombre": "Cristóbal Vera", "apodos": ["Zander"], "discord": "zander01"})
        try:
            for said, want in (("Escríbele hola a Sander a Sander por Discord", "hola"),
                               ("escríbele a Sander hola", "hola"), ("dile a Sander nos vemos mañana", "nos vemos mañana"),
                               ("Escríbele a Sander, hola Sander cómo estás", "hola zander cómo estás"),
                               ("dile a Cander que voy", "voy")):
                j.pending = None
                j.app_choice = None
                j.route(said)
                got = j.pending and j.pending["params"]
                if not (got and got.get("action") == "discord_message" and got.get("text") == want
                        and "Cristóbal Vera" in j.pending["summary"]):
                    errs.append(f"apodo mal oído: {said} -> {got}")
            j.pending = None
            r = j.route("Mándale un mensaje a Sander")[1] or {}
            if j.pending or "Qué mensaje le mando a Cristóbal Vera" not in r.get("reply", ""):
                errs.append(f"«mándale un mensaje a Sander» debía preguntar qué mensaje: {r}")
        finally:
            CT.delete(zk["id"])
            j.pending = None
        j.pending = None
        j.route("Escríbele a Tipo, hola")
        j.route("no, por WhatsApp")  # no es «por X» solo: igual vale
        j.pending = None
        j.route("Escríbele a Tipo, hola")
        j.route("qué hora es")
        if j.route("Discord")[0] == "mensaje":
            errs.append("tras otra pregunta, la elección de app no debe quedar colgando")
        j.pending = None
        j.route("Escríbele a Tipo, hola")
        j.route("WhatsApp")
        j.route("no, por Discord")
        if not (j.pending and j.pending["params"].get("action") == "discord_message" and j.pending["params"].get("text") == "hola"):
            errs.append(f"«no, por Discord» debía cambiar la app: {j.pending and j.pending['params']}")
        # «envía <texto> a X» sin app también pregunta (uso real: «Envía un... Hola Antonio a Antonio» asumió WhatsApp)
        j.pending = None
        r = j.route("Envía un... Hola Tipo a Tipo")[1] or {}
        if j.pending or "«Hola tipo»" not in r.get("reply", "") or "¿Por" not in r.get("reply", ""):
            errs.append(f"envía … a Tipo debía preguntar la app: {r.get('reply')!r}")
        j.app_choice = None
        # la reescritura no puede agregar una app que el usuario no dijo
        orig_rw = H.rewrite_order
        H.rewrite_order = lambda *_a, **_k: "envía Hola Tipo por WhatsApp a Tipo"
        try:
            j.pending = None
            r = j.rewrite_and_route("oye, salúdame a Tipo de mi parte con un hola") or {}
            if j.pending or "¿Por" not in r.get("reply", ""):
                errs.append(f"la reescritura agregó la app: {r.get('reply')!r} {j.pending and j.pending['params']}")
        finally:
            H.rewrite_order = orig_rw
            j.app_choice = None
        for said in ("manda el archivo a Tipo", "Envía un correo a Tipo"):
            j.pending = None
            if j.route(said)[0] == "discord":
                errs.append(f"{said} no es un mensaje de chat")
        # números con cifras en el texto (uso real: «a las nueve y media») y la voz sin el número de teléfono
        for txt, want in (("tendré una reunión a las nueve y media", "tendré una reunión a las 9:30"),
                          ("nos vemos a las diez menos cuarto", "nos vemos a las 9:45"),
                          ("somos treinta y cinco", "somos 35"), ("me debes dos mil pesos", "me debes 2000 pesos"),
                          ("hola, soy una IA", "hola, soy una IA"), ("tengo un perro", "tengo un perro"),
                          ("vamos los dos", "vamos los dos")):
            if H.digits_in_text(txt) != want:
                errs.append(f"cifras: {txt!r} -> {H.digits_in_text(txt)!r}")
        j.pending = None
        j.route("mándale a Tipo por WhatsApp: tendré una reunión a las nueve y media")
        if not (j.pending and j.pending["params"].get("text") == "tendré una reunión a las 9:30"):
            errs.append(f"el mensaje debía llevar cifras: {j.pending and j.pending['params']}")
        spoken = H.speakable("Preparado, señor: enviar por WhatsApp a Tipo (+56987654321 en WhatsApp) el mensaje: «hola».")
        if "5698" in spoken or "(" in spoken:
            errs.append(f"la voz lee el teléfono: {spoken!r}")
        j.pending = None
        # mensajes sin leer en Telegram y WhatsApp (de quién, últimas 24 h; solo lectura)
        fake = {"telegram": {"ok": True, "chats": [{"nombre": "Antonio Fuenzalida", "n": 2, "grupo": False}]},
                "whatsapp": {"ok": True, "chats": [{"nombre": "Tipo", "n": 1, "grupo": False, "cuando": "19:48"},
                                                   {"nombre": "Redes", "n": 5, "grupo": True, "cuando": "Ayer"}],
                             "silenciados": 1}}
        asked = []
        j.SIN_LEER_FN = lambda a: (asked.append(a), fake[a])[1]
        try:
            r = j.route("¿Tengo mensajes sin leer en Telegram o WhatsApp?")
            rep = (r[1] or {}).get("reply", "")
            if r[0] != "sin_leer" or "2 mensajes sin leer de Toño" not in rep.replace("Antonio Fuenzalida", "Toño") \
                    or "5 del grupo Redes (de ayer)" not in rep or "Sebastián Lagos" not in rep:
                errs.append(f"sin leer: {r[0]} {rep!r}")
            asked.clear()
            r = j.route("¿algo nuevo en WhatsApp?")
            if asked != ["whatsapp"]:
                errs.append(f"solo WhatsApp: revisó {asked}")
            # «¿de qué tratan mis últimos mensajes en WhatsApp?» trae los textos para que el modelo los resuma
            # (uso real: la tomaba la ruta de correos y el modelo dijo «no tengo acceso a WhatsApp»)
            fake["whatsapp"]["chats"][0]["ultimo"] = "nos vemos a las 9"
            asked.clear()
            r = j.route("¿De qué tratan mis últimos mensajes en WhatsApp?")
            data = (r[1] or {}).get("data", "")
            if r[0] != "sin_leer" or asked != ["whatsapp"] or "nos vemos a las 9" not in data or "Sebastián Lagos" not in data:
                errs.append(f"de qué tratan: {r[0]} {asked} {data!r}")
            if "Nunca digas que no tienes acceso a WhatsApp" not in H.PERSONA:
                errs.append("el prompt debe decir que WhatsApp/Telegram los consulta el sistema")
            # solo los sin leer: sin ninguno responde directo; con varios en un chat abierto, van esos mensajes
            # (uso real: «quiero que solo lea los mensajes sin leer… si son muchos, que acceda al chat»)
            empty = {"telegram": {"ok": True, "chats": []}, "whatsapp": {"ok": True, "chats": [], "silenciados": 0}}
            j.SIN_LEER_FN = lambda a: empty[a]
            r = j.route("¿De qué tratan mis mensajes de WhatsApp?")[1] or {}
            if "no tiene mensajes sin leer" not in r.get("reply", ""):
                errs.append(f"sin nada sin leer debía decirlo directo: {r!r}")
            many = {"telegram": {"ok": True, "chats": []},
                    "whatsapp": {"ok": True, "chats": [
                        {"nombre": "Tipo", "n": 3, "grupo": False, "cuando": "19:48", "ultimo": "c",
                         "mensajes": ["Tipo: a", "Tipo: b", "Tipo: c"], "abierto": True},
                        {"nombre": "Redes", "n": 4, "grupo": True, "cuando": "19:00", "ultimo": "~Ana: fin", "solo_ultimo": True}]}}
            j.SIN_LEER_FN = lambda a: many[a]
            data = (j.route("¿De qué tratan mis mensajes de WhatsApp?")[1] or {}).get("data", "")
            if ("1. Tipo: a\n  2. Tipo: b\n  3. Tipo: c" not in data or "solo se pudo leer el último de los 4" not in data
                    or "3 mensajes sin leer" not in data):
                errs.append(f"contenido de los sin leer: {data!r}")
            # la cifra de un chat la pone el sistema (uso real: grupo con 9 sin leer y Atlas dijo «tres mensajes»);
            # si nombra un chat, solo va ese
            tg9 = {"telegram": {"ok": True, "chats": [
                {"nombre": "IEEE Computer", "n": 3, "grupo": True, "mensajes": ["Nayru: x", "Tomás: y", "Tomás: z"]},
                {"nombre": "Lista EnLazada 🔗🔥", "n": 9, "grupo": True, "silenciado": True,
                 "mensajes": ["isi: m"] * 6 + ["Gabriel: g", "Gabriel: h", "Benjamin: b"]}]}}
            j.SIN_LEER_FN = lambda a: tg9[a]
            r = j.route("Resume los mensajes del grupo de Telegram de la lista")[1] or {}
            if ("IEEE" in r.get("data", "") or "9 mensajes sin leer" not in r.get("data", "")
                    or "hay 9 mensajes sin leer" not in r.get("hint", "")):
                errs.append(f"resumen de un grupo nombrado: {r!r}")
            # _open_many: abre desde la lista los chats con 2+ sin leer (grupos incluidos, uso real: «de tener 50
            # mensajes en un grupo, me los hubiera resumido»); si una persona no se pudo abrir así, prueba por número
            import atlas_sin_leer as SL
            opened, by_num = [], []
            orig_unread, orig_chat = SL.whatsapp_unread, SL.whatsapp_chat
            SL.whatsapp_unread = lambda targets, timeout=90.0: (opened.extend(t["nombre"] for t in targets), {"ok": True, "chats": {
                t["nombre"]: ({"ok": True, "mensajes": ["Ana: x"] * t["n"]} if t["nombre"] != "Tipo" else {"ok": False})
                for t in targets}})[1]
            SL.whatsapp_chat = lambda num, n, timeout=45.0: (by_num.append(num), {"ok": True, "mensajes": ["Tipo: y"] * n})[1]
            try:
                chats = [{"nombre": "Tipo", "n": 2, "grupo": False}, {"nombre": "Ian", "n": 1, "grupo": False},
                         {"nombre": "Redes", "n": 50, "grupo": True}]
                SL._open_many(chats)
                if sorted(opened) != ["Redes", "Tipo"] or by_num != ["56987654321"] or len(chats[2].get("mensajes", [])) != 50                         or chats[0].get("mensajes") != ["Tipo: y", "Tipo: y"] or "mensajes" in chats[1]:
                    errs.append(f"_open_many: lista {opened}, número {by_num}, {chats}")
            finally:
                SL.whatsapp_unread, SL.whatsapp_chat = orig_unread, orig_chat
            # los mensajes de un chat abierto: lo que viene tras «N mensajes no leídos», sin los míos ni las horas
            seq = [("text", "Hoy"), ("label", "Ana:"), ("text", "hola"), ("text", "18:00"), ("label", "Tú:"), ("text", "y?"),
                   ("text", "2 mensajes no leídos"), ("label", "~Pedro:"), ("text", "junta mañana"), ("text", "20:30"),
                   ("text", "a las 10"), ("text", "20:31")]
            if SL.chat_messages(seq, 2) != ["Pedro: junta mañana", "Pedro: a las 10"]:
                errs.append(f"chat_messages: {SL.chat_messages(seq, 2)}")
            # grupo (visto en «IEEE SB U de Chile», 15-11-2026): quién escribe va como botón «Quizá Dario», «~», «Dario»,
            # su número; un mensaje citado no cambia quién escribe; los avisos largos del sistema no son personas
            seq = [("button", "Los mensajes nuevos desaparecerán de este chat después de 7 días de haber sido enviados"),
                   ("text", "Los mensajes nuevos desaparecerán de este chat después de 7 días de haber sido enviados"),
                   ("button", "Quizá Seba G"), ("text", "~"), ("text", "Seba G"), ("text", "+56 9 5555 0101"),
                   ("text", "recuerden postular"), ("text", "Editado"), ("text", "19:29"),
                   ("button", "Sticker sin etiquetas"), ("text", "19:30"),
                   ("button", "Quizá Dario"), ("text", "~"), ("text", "Dario"), ("text", "+56 9 5555 0102"),
                   ("button", "Mensaje citado"), ("group", "Quizá Seba G"), ("text", "~"), ("text", "Seba G"),
                   ("text", "+56 9 5555 0101"), ("button", "recuerden postular"), ("text", "siii"), ("text", "20:31"),
                   ("label", "Tú:"), ("text", "yo igual"), ("text", "20:40")]
            want = ["Seba G: recuerden postular", "Seba G: [sticker]", "Dario: siii", "Usted: yo igual"]
            if SL.recent_messages(seq, 10) != want:
                errs.append(f"mensajes de grupo: {SL.recent_messages(seq, 10)}")
            j.SIN_LEER_FN = lambda a: (asked.append(a), fake[a])[1]
            for said in ("¿tengo correos sin leer?", "dile a Tipo que tengo mensajes nuevos"):
                if j.route(said)[0] == "sin_leer":
                    errs.append(f"{said} no es revisar mensajes sin leer")
            # «sin leer» mal oído (uso real: «¿Qué mensaje CirLer tengo en Telegram?» buscó un contacto «CirLer»)
            for said in ("¿Qué mensaje CirLer tengo en Telegram?", "tengo mensajes sinler en telegram", "mensajes si leer en telegram"):
                asked.clear()
                if j.route(said)[0] != "sin_leer" or asked != ["telegram"]:
                    errs.append(f"{said!r} debía revisar los sin leer de Telegram ({asked})")
            # grupos y canales, también silenciados (uso real: todos sus grupos eran silenciados y decía «no tiene»)
            import atlas_sin_leer as SL
            tg = {"ok": True, "archivados": 1, "chats": [
                {"nombre": "Antonio Fuenzalida", "n": 1, "grupo": False},
                {"nombre": "Redes 2026", "n": 12, "grupo": True, "silenciado": True},
                {"nombre": "Avisos DCC", "n": 3, "grupo": False, "canal": True}]}
            rep = SL.summary("telegram", tg)
            if ("12 del grupo Redes 2026 (silenciado)" not in rep or "3 del canal Avisos DCC" not in rep
                    or "1 chat archivado" not in rep or rep.index("Avisos DCC") > rep.index("Redes 2026")):
                errs.append(f"resumen con grupos/canales: {rep!r}")
            # «¿y mensajes de grupos?» justo después: misma app, solo grupos y canales (lo tomaba el modelo)
            j.SIN_LEER_FN = lambda a: (asked.append(a), tg if a == "telegram" else fake[a])[1]
            j.route("¿Tengo mensajes sin leer en Telegram?")
            asked.clear()
            r = j.route("¿Y mensajes de grupos?")
            rep = (r[1] or {}).get("reply", "")
            if r[0] != "sin_leer" or asked != ["telegram"] or "Antonio" in rep or "Redes 2026" not in rep or "Avisos DCC" not in rep:
                errs.append(f"¿y los grupos?: {r[0]} {asked} {rep!r}")
            # nunca enviar a grupos ni canales (regla del usuario: «no pueda enviar mensajes a grupos ni wsp ni telegram»)
            for said in ("mándale al grupo Redes por WhatsApp: hola", "escríbele al grupo de la familia que llego tarde",
                         "envía hola en el grupo Redes por Telegram", "manda un mensaje al canal Avisos por Telegram"):
                j.pending = None
                r = j.route(said)[1] or {}
                if j.pending or "No envío mensajes a grupos" not in r.get("reply", ""):
                    errs.append(f"{said!r} no debía preparar un envío a un grupo: {r.get('reply', '')!r}")
            j.pending = None
            r = j.route("dile a Tipo por WhatsApp que nos vemos en el grupo de estudio")[1] or {}
            if "No envío mensajes a grupos" in r.get("reply", ""):
                errs.append("mencionar un grupo dentro del mensaje no es enviarle al grupo")
            j.pending = None
            import openjarvis.tools.atlas_pc as PCM
            for act in ("whatsapp_message", "telegram_message"):
                fn = getattr(PCM.PCTool, "_a_" + act)
                out_t = fn(types.SimpleNamespace(_err=lambda m: ("err", m), _ok=lambda m: ("ok", m)),
                           {"name": "grupo Redes", "text": "hola"})
                if out_t[0] != "err" or "grupo" not in out_t[1]:
                    errs.append(f"{act} con un grupo como destino: {out_t}")
            j.sin_leer_last = None
            if j.route("¿Y los grupos?")[0] == "sin_leer":
                errs.append("«¿y los grupos?» sin haber preguntado antes por los sin leer no debe revisar los chats")
        finally:
            del j.SIN_LEER_FN
            j.pending = None
        # «¿qué han hablado en el grupo de la IEEE en WhatsApp?»: busca ese chat y trae sus últimos mensajes (uso real:
        # el modelo dijo «no tengo acceso a ver los mensajes del grupo de WhatsApp de la IEEE»)
        calls = []

        def nf(a, w):
            calls.append((a, w))
            if a == "whatsapp":
                return {"ok": True, "found": True, "nombre": "IEEE SB U de Chile", "otros": ["IEEE CHILE"],
                        "mensajes": ["Seba G: recuerden postular a los premios", "Dario: siii"]}
            return {"ok": True, "found": False}

        j.NAMED_FN = nf
        try:
            r = j.route("que han hablado en el grupo de la IEEE en WhatsApp")
            d = (r[1] or {}).get("data", "")
            if r[0] != "sin_leer" or calls != [("whatsapp", ["ieee"])] or "1. Seba G: recuerden postular" not in d \
                    or "IEEE CHILE" not in d or "grupo «IEEE SB U de Chile»" not in d:
                errs.append(f"grupo con nombre: {r[0]} {calls} {d!r}")
            calls.clear()
            r = j.route("Quiero saber que están hablando en el grupo de la IEEE en WhatsApp")
            if calls != [("whatsapp", ["ieee"])] or "IEEE SB" not in (r[1] or {}).get("data", ""):
                errs.append(f"«qué están hablando»: {calls} {r}")
            calls.clear()
            r = j.route("¿Qué se ha dicho en el grupo de la IEEE?")
            if sorted(a for a, _ in calls) != ["telegram", "whatsapp"] or "IEEE SB" not in (r[1] or {}).get("data", ""):
                errs.append(f"sin app: debía buscar en las dos: {calls} {r}")
            calls.clear()
            r = j.route("qué han hablado en el grupo de los mapaches en Telegram")
            rep = (r[1] or {}).get("reply", "")
            if calls != [("telegram", ["mapaches"])] or "no encontré" not in rep or "Telegram" not in rep:
                errs.append(f"chat que no existe: {calls} {rep!r}")
            calls.clear()
            j.route("qué han hablado en el grupo de amigos en Discord")
            if calls:
                errs.append(f"Discord no se busca en WhatsApp/Telegram: {calls}")
        finally:
            j.NAMED_FN = H.Atlas.NAMED_FN
        for said in ("escríbele un correo a Tipo, hola", "dile a Atlas que pare"):
            j.pending = None
            j.route(said)
            if j.pending:
                errs.append(f"{said} no es un mensaje de chat: {j.pending['params']}")
    finally:
        H.LAST_APP_FILE = orig_last
        j.pending = None
    out.append(("mensaje sin app: «escríbele a X, …» pregunta la app si X tiene varias (si tiene una, la usa) y pide confirmación", errs))
    # Tarjeta de pantalla completa: «¿Por WhatsApp, Telegram o Discord…?» con un botón por app (/api/live trae «eleccion»)
    errs = []
    orig_play, orig_last = j._play, H.LAST_APP_FILE
    j._play = lambda _t: None
    j.chat = lambda t: j.route(t)[1] or {}  # sin modelo cargado: el botón usa el mismo camino que decir «por Telegram»
    H.LAST_APP_FILE = Path(tempfile.mkdtemp()) / "ultima_app.json"
    try:
        j.pending, j.app_choice = None, None
        j.route("Envía un... Hola Tipo a Tipo")
        e = j.live().get("eleccion") or {}
        if len(e.get("apps") or []) < 2 or e.get("texto") != "Hola tipo" or "pendiente" in j.live():
            errs.append(f"live debía traer la elección de app: {j.live()}")
        app = (e.get("apps") or ["telegram"])[-1]
        r = j.choose_app_spoken(app)
        if not j.pending or j.pending["params"].get("action") != f"{app}_message" or "eleccion" in j.live():
            errs.append(f"el botón {app} debía preparar el mensaje: {r!r} {j.pending and j.pending['params']}")
        if "pendiente" not in j.live():
            errs.append("después de elegir, la tarjeta debía pasar a Confirmar / Cancelar")
        j.pending, j.app_choice = None, None
        j.route("Envía un... Hola Tipo a Tipo")
        r = j.choose_app_spoken("")
        if j.pending or getattr(j, "app_choice", None) or "No envío" not in r.get("reply", ""):
            errs.append(f"CANCELAR debía descartar la pregunta: {r}")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"{type(exc).__name__}: {exc}")
    finally:
        j._play, H.LAST_APP_FILE = orig_play, orig_last
        del j.chat
        j.pending, j.app_choice = None, None
    out.append(("tarjeta de pantalla completa: botones WhatsApp / Telegram / Discord al preguntar la app", errs))
    # Correos de U-Cursos: «X te escribió un mensaje en <curso>» es una respuesta en el foro del curso, no un mensaje para
    # el usuario (uso real 15-11-2026: la profesora le respondía a un estudiante y Atlas lo contó como si fuera para él)
    errs = []
    try:
        from email.message import EmailMessage

        from openjarvis.tools import gmail_mark_read as GM

        def mk(mid, date, body):
            m = EmailMessage()
            m["From"], m["To"], m["Subject"], m["Date"], m["Message-ID"] = (
                "U-Cursos <noreply-ucursos@ucampus.cl>", "yo@example.com", "TAREA 3A", date, mid)
            m.set_content(body)
            return m.as_bytes()

        head = "{} te escribió un mensaje en Introducción a la Programación (CC1001-1, Primavera 2026) (https://u-cursos.cl/x)\n\n{}\n"
        q = mk("<1@x>", "Fri, 13 Nov 2026 17:02:00 -0300", head.format("Claudio Reyes D.", "Claudio Reyes D.")
               + "13 de noviembre a las 17:02\n\n¿Por qué la opción 4 pide un número de páginas? ¿Cuál es la opción 5?\n\n"
               "Responder (https://u-cursos.cl/r)\n\nEn esta conversación hay 5 participantes.\nEnviado desde U-Cursos\n")
        a = mk("<2@x>", "Sun, 15 Nov 2026 19:35:00 -0300", head.format("Andrea Muñoz", "Andrea Muñoz")
               + "[Profesor de Cátedra] 15 de noviembre a las 19:35\n\nHolaa!\n\nEs un error, la opción 4 usa el archivo. "
               "La opción 5 no existe\n\nResponder (https://u-cursos.cl/r)\n\nEn esta conversación hay 6 participantes.\n"
               "Enviado desde U-Cursos\n")

        class FakeImap:
            def uid(self, cmd, *args):
                if cmd == "FETCH" and args[1] == "(X-GM-THRID)":
                    return "OK", [b"2 (X-GM-THRID 777 UID 20)"]
                if cmd == "FETCH":
                    return "OK", [(b"x", {"10": q, "20": a}[args[0]]), b")"]
                return "OK", [b"10 20"]

            def select(self, *_a, **_k):
                return "OK", [b"2"]

        orig_all = GM._find_all_mail
        GM._find_all_mail = lambda _imap: "[Gmail]/Todos"
        try:
            out_txt = GM.GmailTool._body(GM.GmailTool.__new__(GM.GmailTool), FakeImap(), b"20", "uchile")
        finally:
            GM._find_all_mail = orig_all
        for want in ("U-Cursos thread", "NOT a private message", "Andrea Muñoz [Profesor de Cátedra]",
                     "Claudio Reyes D. wrote", "opción 5?", "6 participants"):
            if want not in out_txt:
                errs.append(f"faltó «{want}» en lo que lee el modelo")
        for junk in ("Enviado desde U-Cursos", "En esta conversación hay", "https://"):
            if junk in out_txt:
                errs.append(f"quedó el pie de U-Cursos: «{junk}»")
        if "a quién le respondió" not in H.U_CURSOS_HINT or "«foro»" not in H.U_CURSOS_HINT:
            errs.append("la instrucción de resumen no explica el formato de U-Cursos")
        # el curso con su nombre corto y casual (el usuario: «Basta con "En intro a la progra…"»)
        import atlas_agenda as JA

        orig_ramos = JA.load_ramos
        JA.load_ramos = lambda: [{"apodo": "Introducción a la Programación", "ramo": "Introducción a la Programación",
                                  "tambien": ["introducción a la progra", "intro a la progra", "la progra", "intro"]}]
        try:
            said = H.mail_hint("", out_txt)
        finally:
            JA.load_ramos = orig_ramos
        if "«Intro a la Progra»" not in said:
            errs.append(f"el curso debía llamarse «Intro a la Progra»: {said!r}")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"{type(exc).__name__}: {exc}")
    out.append(("correo de U-Cursos: dice quién respondió, con qué rol, en qué curso y a qué pregunta de quién", errs))
    # Aviso 1 hora antes de cada actividad (pedido 15-11-2026): una vez por evento, sin «todo el día»
    errs = []
    try:
        import atlas_previo as PV

        now = datetime(2026, 11, 15, 20, 30)
        evs = [{"summary": "Reunión para Empresa", "when": datetime(2026, 11, 15, 21, 30)},
               {"summary": "Más tarde", "when": datetime(2026, 11, 15, 21, 45)},
               {"summary": "Feriado", "allday": True, "when": datetime(2026, 11, 15, 21, 0)},
               {"summary": "Ya casi", "when": datetime(2026, 11, 15, 20, 33)}]
        sent = {}
        got = PV.pendientes(evs, now, sent)
        if [t for _k, t in got] != ["Señor, en 1 hora tiene Reunión para Empresa, a las 21:30."]:
            errs.append(f"a las 20:30 debía avisar solo la reunión de las 21:30: {got}")
        if PV.pendientes(evs, now, sent):
            errs.append("repitió un aviso ya dado")
        later = PV.pendientes(evs, now + timedelta(minutes=15), sent)
        if [t for _k, t in later] != ["Señor, en 1 hora tiene Más tarde, a las 21:45."]:
            errs.append(f"a las 20:45 debía avisar lo de las 21:45: {later}")
        late = PV.pendientes([{"summary": "Dentista", "when": datetime(2026, 11, 15, 21, 0)}], now, {})
        if not late or "en 30 minutos" not in late[0][1]:
            errs.append(f"si Atlas abre con 30 min, avisa con los minutos reales: {late}")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"{type(exc).__name__}: {exc}")
    # uso real 17-11: «me está tomando como reuniones las cátedras, los eventos son los únicos que debería notificarme»
    # y luego: «solo los auxiliares de intro a la programación aparezcan como evento, porque esos son los que debo dictar»
    # (ramos.json: "avisar_antes": ["auxiliar"] en Introducción a la Programación)
    clases = [{"summary": "Cátedra - Redes", "kind": "Cátedra", "course": "Redes", "location": "B08",
               "when": datetime(2026, 11, 15, 21, 0)},
              {"summary": "Auxiliar - Introducción a la Programación", "kind": "Auxiliar",
               "course": "Introducción a la Programación", "when": datetime(2026, 11, 15, 21, 0)},
              {"summary": "Cátedra - Introducción a la Programación", "kind": "Cátedra",
               "course": "Introducción a la Programación", "when": datetime(2026, 11, 15, 21, 0)},
              {"summary": "Auxiliar - Redes", "kind": "Auxiliar", "course": "Redes", "when": datetime(2026, 11, 15, 21, 0)},
              {"summary": "Control 2 - Lenguajes", "kind": "Control", "course": "Lenguajes de Programación",
               "when": datetime(2026, 11, 15, 21, 0)},
              {"summary": "Tarea 3", "kind": "Tarea 3", "course": "Redes", "task": True, "when": datetime(2026, 11, 15, 21, 0)}]
    try:
        import atlas_previo as PV
        got = [t for _k, t in PV.pendientes(clases, datetime(2026, 11, 15, 20, 30), {})]
        if len(got) != 1 or "Auxiliar" not in got[0] or "Introducción" not in got[0] or "Redes" in got[0]:
            errs.append(f"de las clases solo se avisa la auxiliar de Intro a la Programación: {got}")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"clases: {type(exc).__name__}: {exc}")
    out.append(("aviso 1 hora antes de cada actividad (voz y Telegram), una sola vez", errs))
    # En pantalla sale en el recuadro amarillo sin decir de qué es (pedido 16-11-2026); voz y Telegram dicen todo
    errs = []
    import atlas_previo as PV
    if PV.etiqueta("Señor, en 1 hora tiene Reunión para Empresa, a las 21:30.") != "Reunión próxima: 21:30 horas":
        errs.append(f"etiqueta: {PV.etiqueta('Señor, en 1 hora tiene Reunión para Empresa, a las 21:30.')!r}")
    jp = H.Atlas()
    dichos, enviados = [], []
    jp._announce = lambda alert, tipo: dichos.append((alert.get("voz_texto") or alert["texto"], tipo))
    jp.telegram = type("T", (), {"send": lambda self, t: enviados.append(t)})()
    jp.presente = lambda: False  # lejos del PC: Telegram al tiro (frente al PC, solo si nadie lo apaga en 3 min; 18-11)
    completo = "Señor, en 1 hora tiene Reunión para Empresa, a las 21:30."
    jp.notify(completo, "previo", telegram_always=True, amarillo=PV.etiqueta(completo))
    time.sleep(0.1)
    vista = jp.status_alerts()[-1] if jp.status_alerts() else {}
    if vista.get("texto") != "Reunión próxima: 21:30 horas" or "Empresa" in json.dumps(vista, ensure_ascii=False) \
            or not vista.get("ring") or vista.get("tipo") != "recordatorio":
        errs.append(f"en pantalla debe salir amarillo y sin el nombre: {vista}")
    if dichos != [(completo, "recordatorio")] or enviados != [completo]:
        errs.append(f"la voz y Telegram dicen el aviso completo: voz={dichos} tg={enviados}")
    jp.notify("Listo, señor.", "ucursos")
    time.sleep(0.1)
    if jp.status_alerts()[-1].get("tipo") != "aviso" or jp.status_alerts()[-1].get("ring"):
        errs.append("los demás avisos siguen yendo a la consola")
    jp.presente = lambda: True
    n0 = len(enviados)
    jp.notify("Señor, le escribió Benji por Telegram.", "mensaje")
    time.sleep(0.1)
    if len(enviados) != n0:
        errs.append("frente al PC, un aviso común no debe ir por Telegram")
    out.append(("aviso de reunión: recuadro amarillo «Reunión próxima: 21:30 horas» sin decir de qué es", errs))
    # Llamada saliente: el audio de manos libres no es una entrante (uso real: «Llama a mi madre» y avisó «le están llamando»)
    import atlas_llamadas as LS
    errs = []
    LS.state["out_t"] = 0.0
    orig_pids, LS._pids = LS._pids, (lambda: set())
    if LS._outgoing_now():
        errs.append("sin marcar ni Enlace Móvil al frente no debe ser saliente")
    LS.mark_outgoing()
    if not LS._outgoing_now():
        errs.append("recién marcada por Atlas debe ser saliente")
    LS.state["out_t"], LS._pids = 0.0, orig_pids
    out.append(("llamadas: el audio de una llamada que marcó Atlas no se anuncia como entrante", errs))
    # Llamada entrante (Enlace Móvil): anuncia quién llama con el nombre de la libreta y contesta/rechaza solo si suena
    import atlas_llamadas as L

    errs = []
    j = H.Atlas()
    j.refresh_inbox = lambda: None
    j._announce = lambda *a, **k: None
    if j.route_llamada("contesta") is not None:
        errs.append("«contesta» sin llamada sonando no debe tomarse como llamada")
    L.state["ring"] = {"hwnd": 1, "accept": "Aceptar", "decline": "Rechazar", "texts": ["Llamada entrante", "+56 9 8765 4321"]}
    j._call_ring(L.state["ring"])
    a = j.call_alert or {}
    if "le está llamando Sebastián Lagos" not in a.get("texto", "") or not a.get("ring"):
        errs.append(f"aviso: {a.get('texto')!r}")
    pressed = []
    old = (L.answer, L.decline)
    L.answer = lambda: (pressed.append("contestar"), L.state.update(ring=None))[0] is None
    L.decline = lambda: (pressed.append("rechazar"), L.state.update(ring=None))[0] is None
    r = j.route_llamada("Atlas, rechaza la llamada")
    if pressed != ["rechazar"] or "Rechacé la llamada de Sebastián Lagos" not in (r or {}).get("reply", ""):
        errs.append(f"rechazar: {pressed} {r}")
    L.state["ring"] = {"hwnd": 1, "accept": "Aceptar", "decline": "Rechazar", "texts": ["912345678"]}
    j._call_ring(L.state["ring"])
    if "un número desconocido" in j.call_alert["texto"] or "912345678" not in j.call_alert["texto"]:
        errs.append(f"número fuera de la libreta: {j.call_alert['texto']!r}")
    L.answer = lambda: False  # no encontró el botón: no debe decir que contestó
    r = j.route_llamada("contesta")
    if "No encontré el botón" not in (r or {}).get("reply", ""):
        errs.append(f"sin botón: {r}")
    j._call_end()
    L.state["ring"] = None
    L.answer, L.decline = old
    # Solo audio (uso real: Enlace Móvil no mostró ventana): avisa sin botones y al cortar dice quién era
    notes = []
    j.notify = lambda text, tag: notes.append(text)
    old_last = L.last_call
    L.last_call = lambda since: {"numero": "+56987654321", "tipo": "rechazada"}
    L.state["ring"] = {"hwnd": 0, "accept": "", "decline": "", "texts": [], "audio": True}
    j._call_ring(L.state["ring"])
    a = j.call_alert or {}
    if a.get("texto") != "Señor, hay una llamada en su celular." or a.get("botones") is not False:
        errs.append(f"audio: {a}")
    r = j.route_llamada("contesta")
    if "hágalo en el celular" not in (r or {}).get("reply", ""):
        errs.append(f"audio contesta: {r}")
    j._call_summary(a)
    if notes != ["La llamada era de Sebastián Lagos (rechazada), señor."]:
        errs.append(f"resumen: {notes}")
    # WhatsApp sonando en la bandeja, sin ventana (uso real: «no avisa cuando me llaman por wsp»): avisa sin botones
    # y al cortar no busca en Enlace Móvil (ahí no queda anotada)
    notes.clear()
    j._call_ring({"hwnd": 0, "accept": "", "decline": "", "texts": [], "audio": True, "app": "whatsapp"})
    a4 = j.call_alert or {}
    if a4.get("texto") != "Señor, le están llamando por WhatsApp." or a4.get("botones") is not False:
        errs.append(f"whatsapp por sonido: {a4}")
    j._call_summary(a4)
    if notes:
        errs.append(f"whatsapp por sonido no debe resumir con Enlace Móvil: {notes}")
    # llamada entrante de WhatsApp de escritorio: misma alerta, dice que es por WhatsApp y trae botones
    j._call_ring({"hwnd": 123, "accept": "Aceptar", "decline": "Rechazar", "texts": ["Sebastián Lagos", "Llamada de voz de WhatsApp"],
                  "app": "whatsapp"})
    a3 = j.call_alert or {}
    if a3.get("texto") != "Señor, le está llamando Sebastián Lagos por WhatsApp. ¿Contesto o rechazo?" or not a3.get("botones"):
        errs.append(f"whatsapp entrante: {a3}")
    j.call_alert = None
    # saliente (uso real: marcó desde el celular): al terminar se retira el aviso y no se dice nada
    notes.clear()
    L.last_call = lambda since: {"numero": "+56987654321", "tipo": "saliente"}
    j._call_ring({"hwnd": 0, "accept": "", "decline": "", "texts": [], "audio": True})
    a2 = j.call_alert
    j._call_summary(a2)
    if notes or a2 in j.alerts:
        errs.append(f"saliente: {notes} {a2 in j.alerts}")
    L.state["ring"] = None
    j.call_alert = None
    L.last_call = old_last
    out.append(("llamada entrante: dice quién llama y contesta o rechaza solo si la ventana de la llamada se fue", errs))
    # Básicas: si la fuente del dólar no responde, lo dice y no inventa una cifra
    import atlas_basico as B
    fetch = B.FETCH
    B.FETCH = lambda: (_ for _ in ()).throw(OSError("sin red"))
    B._cache.update(t=0.0, data=None)
    r = B.answer("a cuánto está el dólar") or ""
    B.FETCH = fetch
    B._cache.update(t=0.0, data=None)
    out.append(("sin conexión no inventa el valor del dólar",
                [] if re.search(r"No pude consultar", r) and not re.search(r"\d", r) else [f"respuesta: {r!r}"]))
    # El modelo recibe siempre la fecha y la hora (antes decía "no tengo acceso al reloj")
    t = H.build_turn("¿cuánto falta para fin de mes?")
    errs = [] if re.search(r'<datos herramienta="reloj">\nAhora es lunes 9 de noviembre de 2026, 9:00', t) else [f"turno: {t[:200]!r}"]
    if "usando solo lo que está en <datos>" in t:
        errs.append("con solo el reloj no debe pedir responder solo con <datos>")
    out.append(("el modelo recibe la fecha y la hora en <datos>", errs))
    # Spam y publicidad: no se muestran; lo de U-Cursos, Google y lo permitido sí
    try:
        from openjarvis.tools.gmail_mark_read import is_publicidad
        cfg = {"permitir": ["banco estado"], "bloquear": ["info.mercadopago.cl"]}
        casos = [
            ("Get on Board <no-reply@getonbrd.com>", "<https://getonbrd.com/unsub>", "", True),
            ("Promo <promo@tienda.example>", "", "bulk", True),
            ("Mercado Pago <no-reply@info.mercadopago.cl>", "", "", True),            # bloqueado a mano
            ("Andrea Muñoz (vía U-Cursos)", "<mailto:baja@u-cursos.cl>", "list", False),
            ("Google <no-reply@accounts.google.com>", "<https://google.com/unsub>", "", False),
            ("Banco Estado <avisos@bancoestado.cl>", "<https://bancoestado.cl/baja>", "", False),  # permitido
            ("Camila Soto <camila@gmail.com>", "", "", False),
            ("billing@soundtrap.com", "", "", False),                                   # aviso de cuenta, no masivo
            ("Discord <noreply@discord.com>", "", "", True),                            # notificación de app
            ("GitHub <notifications@github.com>", "", "", True),
            ("LinkedIn <updates-noreply@linkedin.com>", "", "", True),
            ("U-Cursos <no-reply@u-cursos.cl>", "", "", False),                         # U-Cursos sí avisa
            ("Pedro Notario <pedro.notario@gmail.com>", "", "", False),                 # persona real
            ("Pedro <pedro.news@gmail.com>", "", "", False),                            # persona con "news" en el correo
        ]
        errs = [f"{s!r}: dijo {not esp}" for s, lu, pr, esp in casos if is_publicidad(s, lu, pr, cfg) != esp]
    except ImportError as exc:
        errs = [f"no pude cargar el filtro de correo: {exc}"]
    out.append(("el correo no muestra spam ni publicidad (y sí lo importante)", errs))
    # Cuentas que no son Gmail (empresa.cl en mail.correo-empresa.example) deben usar su servidor guardado (uso real: "Lookup failed")
    try:
        import openjarvis.connectors.gmail_imap as GI
        from openjarvis.tools.gmail_mark_read import mail_accounts
        viejo_path = GI._DEFAULT_CREDENTIALS_PATH
        (tmp / "mail_accounts").mkdir(exist_ok=True)
        (tmp / "mail_accounts" / "a_empresa.json").write_text(json.dumps({
            "email": "yo@empresa.example", "password": "prueba", "imap_host": "mail.correo-empresa.example", "imap_port": 993,
            "imap_security": "tls", "validated": True}), encoding="utf-8")
        GI._DEFAULT_CREDENTIALS_PATH = tmp / "no_hay_principal.json"
        try:
            hosts = {lab: c._resolve_connection()[2] for lab, c in mail_accounts()}
        finally:
            GI._DEFAULT_CREDENTIALS_PATH = viejo_path
        errs = [] if hosts == {"yo@empresa.example": "mail.correo-empresa.example"} else [f"servidores: {hosts}"]
    except ImportError as exc:
        errs = [f"no pude cargar el conector de correo: {exc}"]
    out.append(("una cuenta que no es Gmail usa su propio servidor IMAP", errs))
    # Canción al azar de sus Me gusta: abre la lista LM, elige una y la pone (sin abrir nada real)
    try:
        import openjarvis.tools.atlas_pc as P
        if not hasattr(P, "_MusicWindow"):
            raise ImportError("stub")
        abiertos, evals = [], []
        lista = {"url": "https://music.youtube.com/playlist?list=LM",
                 "songs": [{"id": "abc123", "title": "Usseewa", "artist": "Ado"},
                           {"id": "def456", "title": "Marunouchi Sadistic", "artist": "Sheena Ringo"}]}
        viejo_eval, viejo_sleep = P._cdp_eval, P.time.sleep
        P._cdp_eval = lambda js, *a, **k: (evals.append(js), lista if "querySelectorAll" in js else True)[1]
        P.time.sleep = lambda s: None
        ventana = type("W", (), {"open": staticmethod(lambda u: abiertos.append(u))})
        try:
            res = P.PCTool._play_liked_random(P.PCTool.__new__(P.PCTool), ventana)
            lista["songs"] = []
            vacia = P.PCTool._play_liked_random(P.PCTool.__new__(P.PCTool), ventana)
        finally:
            P._cdp_eval, P.time.sleep = viejo_eval, viejo_sleep
        errs = []
        if abiertos[:1] != ["https://music.youtube.com/playlist?list=LM"]:
            errs.append(f"no abrió la lista Me gusta: {abiertos}")
        if not res.success or not re.search(r"Usseewa|Marunouchi", res.content) or not any("list=LM" in e and "watch?v=" in e for e in evals):
            errs.append(f"no puso una de la lista: {res.content}")
        if vacia.success or "Reproduciendo" in vacia.content:
            errs.append(f"sin canciones no debe decir que suena algo: {vacia.content}")
    except ImportError as exc:
        errs = [] if "stub" in str(exc) else [f"no pude cargar atlas_pc: {exc}"]
    except AttributeError as exc:
        errs = [f"falta algo en atlas_pc: {exc}"]
    out.append(("«pon una de mis Me gusta» elige al azar de la lista y no inventa", errs))
    # El modelo no puede dar por hecha una acción que ninguna herramienta hizo (uso real: "con música de Ado")
    falsas = ["Reproductor en marcha, señor: reproductor en marcha, señor: reproduciendo música de Ado.",
              "Listo, abrí YouTube.", "Puse la canción, señor.", "Agendaré la reunión.", "Ya está sonando, señor.",
              "Señor, tiene razón. Voy a reproducir «Hotel California» de Eagles para usted ahora mismo.",
              "Lo pondré enseguida, señor.", "Se la pongo ahora mismo, señor.",
              "Le he dado un vistazo a su correo de U-Cursos y a sus tareas, señor: tiene dos correos sin leer.",
              "Revisé su agenda, señor."]
    buenas = ["Los pulpos tienen tres corazones, señor.", "Su último correo es de Get on Board.",
              "Perdone, señor, no tengo esa información.", "¿Quiere que revise su agenda, señor?",
              "Puede revisar U-Cursos cuando quiera, señor."]
    errs = [f"no detectó: {x!r}" for x in falsas if not H.claims_action(x)]
    errs += [f"detectó de más: {x!r}" for x in buenas if H.claims_action(x)]
    out.append(("no da por hecha una acción sin herramienta", errs))
    # Equivalencias de la voz (hud/equivalencias.json): cada regla con un caso real que corrige y otro que NO debe tocar
    corrige = [
        ("Uh, guarda esta canción.", "guarda esta canción."), ("Un guarda esta canción.", "guarda esta canción."),
        ("Un Atlas, ¿qué hora es?", "Atlas, ¿qué hora es?"), ("Yarvis, pon música", "Jarvis, pon música"), ("Hatlas, pon música", "Atlas, pon música"), ("At las, ¿qué hora es?", "Atlas, ¿qué hora es?"),
        ("Conecta o cursos", "Conecta U-Cursos"), ("Claude Conecta u Cursos", "Claude Conecta U-Cursos"),
        ("Conect a U-Cursos", "conecta a U-Cursos"),
        ("Vela Estabela Red, a Internet.", "ve el estado de la red, a Internet."),
        ("Quiero que guardes la canción que está cenando.", "Quiero que guardes la canción que está sonando."),
        ("Recomindame una canción.", "recomiéndame una canción."), ("Recuérdame una canción.", "recomiéndame una canción."),
        ("Recomendemos una canción.", "recomiéndame una canción."),
        ("Mejor por una canción de Ado.", "pon una canción de Ado."), ("Pon essa.", "pon esa."),
        ("abre yutub", "abre YouTube"), ("Marca como leíos todos los mails", "Marca como leídos todos los mails"),
        ("¿Cuál era el último correo que me llevó?", "¿Cuál era el último correo que me llegó?"),
        ("Si, Leelu.", "léelo."), ("Resumele.", "resúmelo."),
        ("Quiero que también agentes else mismo viernes un evento llamado Jacatón",
         "Quiero que también agendes ese mismo viernes un evento llamado Hackathon"),
        ("¿Cuándo en mi próxima reunión?", "¿Cuándo es mi próxima reunión?"),
    ]
    no_toca = ["Recuérdame en 20 minutos sacar la ropa", "Recuérdame comprar una canción de regalo mañana",
               "Un minuto, por favor", "un evento el viernes", "los agentes de seguridad llegaron",
               "Juan me llevó al aeropuerto", "¿Cuándo en el año hay vacaciones?", "Voy por una pizza",
               "Tengo dos o tres cursos", "Ve la película", "Señor, ¿qué hora es?", "Pon una canción de Ado"]
    errs = [f"{a!r} -> {H.apply_equivalencias(a)!r} (se esperaba {b!r})" for a, b in corrige if H.apply_equivalencias(a) != b]
    errs += [f"tocó {a!r} -> {H.apply_equivalencias(a)!r}" for a in no_toca if H.apply_equivalencias(a) != a]
    out.append(("equivalencias de la voz: corrige lo real y no toca frases normales", errs))
    # Unificación (18-11-2026): equivalencias.json y vocabulario.txt se migraron a diccionario.json, la única fuente.
    # Cada corrección antigua debe corregir igual que antes (también «chego»), sin duplicados, y borrar en el panel la quita.
    import atlas_nombres as NM
    errs = []
    _viejas = [(re.compile(r["de"], re.I), r.get("a", "")) for r in json.loads(NM.EQUIV_VIEJO.read_text(encoding="utf-8"))["reglas"]]

    def _antes(s):
        o = s
        for rx, rep in _viejas:
            o = rx.sub(rep, o)
        return re.sub(r"\s{2,}", " ", o).strip() if o != s else o
    _extra = ["chego", "Chego viene mañana", "reunión con chegu por disco", "abre espotifai", "manda un jimeil",
              "SHEGU llegó", "Shego llegó", "conect a la reunión", "agentes else mismo"]
    for f in [a for a, _ in corrige] + no_toca + _extra:
        if H.apply_equivalencias(f) != _antes(f):
            errs.append(f"{f!r}: antes {_antes(f)!r}, ahora {H.apply_equivalencias(f)!r}")
    if H.apply_equivalencias("chego") != "Shego" or H.apply_equivalencias("Chego viene mañana") != "Shego viene mañana":
        errs.append(f"«chego» debe seguir siendo Shego: {H.apply_equivalencias('chego')!r}")
    _doc = NM._cargar()
    _claves = [NM._clave(p["escuchado"]) for p in NM.palabras()]
    if len(_claves) != len(set(_claves)):
        errs.append("hay palabras duplicadas en el diccionario")
    _simples = sum(len(NM.escucha_de(r["de"]) or []) for r in json.loads(NM.EQUIV_VIEJO.read_text(encoding="utf-8"))["reglas"]
                   if r.get("a") and "\\" not in r["a"])
    if sum(p.get("origen") == "equivalencias" for p in NM.palabras()) != _simples or not _doc.get("migrado") \
            or len(NM.reglas()) + _doc["migrado"]["palabras_de_equivalencias"] < 20 or len(NM.vocabulario()) < 10:
        errs.append(f"migración incompleta: {_doc.get('migrado')} · equivalencias "
                    f"{sum(p.get('origen') == 'equivalencias' for p in NM.palabras())}/{_simples} · reglas {len(NM.reglas())} "
                    f"· vocabulario {len(NM.vocabulario())} · {[(p['escuchado'], p.get('origen')) for p in NM.palabras() if p.get('origen') not in ('semilla', 'equivalencias')]}")
    jv = nuevo(H)
    jv.diccionario_cambiar({"op": "borrar_palabra", "escuchado": "chego"})
    if H.apply_equivalencias("Chego viene") != "Chego viene":
        errs.append("borrar «chego» en el panel debía dejar de corregirlo")
    jv.diccionario_cambiar({"op": "palabra", "escuchado": "chego", "correcto": "Shego"})
    if H.apply_equivalencias("Chego viene") != "Shego viene":
        errs.append("volver a agregar «chego» debía corregirlo otra vez")
    # Reglas del Diccionario (18-11-2026): las expresiones antiguas pasaron a reglas que se leen como frase y se editan
    if any(r.get("tipo") not in ("cambiar", "quitar") or not r.get("id") for r in NM.reglas()):
        errs.append("todas las reglas antiguas deben quedar como reglas editables (cambiar / quitar, con id)")
    _disco = next((r for r in NM.reglas() if r.get("escuchado") == "disco"), {})
    if NM.texto_regla(_disco) != ("Cambiar «disco» por «Discord» solo cuando justo antes venga «por», «en», «al» o «desde», "
                                  "excepto cuando después venga «de», «del», «duro» o «compacto»."):
        errs.append(f"la regla se lee como frase: {NM.texto_regla(_disco)!r}")
    _g = jv.diccionario_cambiar({"op": "regla", "regla": {"tipo": "cambiar", "escuchado": "pala", "correcto": "palta",
                                                           "cerca": [{"w": "compra", "lado": "antes", "justo": False, "parecido": True, "parecidas": ["compras", "comprar"]}]}})
    _id = (_g.get("item") or {}).get("id")
    if not _g.get("ok") or (_g.get("item") or {}).get("donde") != "regla" \
            or H.apply_equivalencias("comprar una pala") != "comprar una palta" or H.apply_equivalencias("dame la pala") != "dame la pala":
        errs.append(f"regla con condición: {_g.get('error')} {H.apply_equivalencias('comprar una pala')!r}")
    _e = jv.diccionario_cambiar({"op": "regla", "regla": {"tipo": "quitar", "escuchado": "pala", "inicio": True}, "antes": {"tipo": "regla", "id": _id}})
    if not _e.get("ok") or (_e.get("item") or {}).get("id") != _id or H.apply_equivalencias("pala abre spotify") != "abre spotify" \
            or sum(r.get("id") == _id for r in NM.reglas()) != 1:
        errs.append(f"editar una regla la reemplaza en su lugar: {_e.get('error')} {H.apply_equivalencias('pala abre spotify')!r}")
    jv.diccionario_cambiar({"op": "borrar_regla", "id": _id})
    if H.apply_equivalencias("pala abre spotify") != "pala abre spotify" or any(r.get("id") == _id for r in NM.reglas()):
        errs.append("borrar una regla la quita")
    _s = jv.diccionario_cambiar({"op": "regla", "regla": {"tipo": "cambiar", "escuchado": "blorp", "correcto": "Blorpo"}})
    if (_s.get("item") or {}).get("donde") != "palabra" or not any(p["escuchado"] == "blorp" for p in NM.palabras()):
        errs.append("un cambio sin condiciones queda como palabra")
    jv.diccionario_cambiar({"op": "borrar_palabra", "escuchado": "blorp"})
    if jv.diccionario_cambiar({"op": "regla", "regla": {"tipo": "cambiar", "escuchado": "", "correcto": "x"}}).get("ok"):
        errs.append("una regla sin palabra no se guarda")
    # se puede aplicar dos veces sin repetir («la u» -> «la U de Chile» no se vuelve «la U de Chile de Chile»)
    jv.diccionario_cambiar({"op": "palabra", "escuchado": "la uch", "correcto": "la uch de Chile"})
    if NM.aplicar_diccionario(NM.aplicar_diccionario("voy a la uch")) != "voy a la uch de Chile":
        errs.append(f"diccionario dos veces: {NM.aplicar_diccionario(NM.aplicar_diccionario('voy a la uch'))!r}")
    jv.diccionario_cambiar({"op": "borrar_palabra", "escuchado": "la uch"})
    # ✎ Corregir › «¿Qué quería?» (18-11-2026): con Pendientes propone cambiar el verbo solo si después viene «pendiente»
    _p = jv.corrector_proponer({"frase": "Marca como pendiente realizar ejercicios de intro a la progra", "accion": "mis pendientes"})
    _r = _p.get("regla") or {}
    if _p.get("tipo") != "regla" or _r.get("escuchado") != "marca" or _r.get("correcto") not in ("anota", "apunta", "agrega") \
            or not any(c.get("w") == "pendiente" and c.get("lado") == "después" for c in _r.get("cerca") or []):
        errs.append(f"corrector: «Marca como pendiente…» + Pendientes debe proponer «marca → anota» con «pendiente» después: {_p}")
    elif not any(e.get("tipo") == "done" for e in _p.get("ejemplos") or []):
        errs.append("corrector: la propuesta debe mostrar que «Marca … como hecho» sigue cerrando el pendiente")
    if jv.corrector_proponer({"frase": "marca estudiar", "accion": "mis pendientes"}).get("tipo") != "sin_regla":
        errs.append("corrector: sin «pendiente» en la frase no debe unirla a «mis pendientes» (listaría en vez de anotar)")
    if jv.corrector_proponer({"frase": "cómo ando de plata", "accion": "cuánto he gastado"}).get("tipo") != "frase":
        errs.append("corrector: una acción sin contenido propio se une a la frase")
    # vocabulario de voz: se ve, se agrega y se borra en el panel, y llega al reconocimiento de voz
    r1 = jv.diccionario_cambiar({"op": "vocab_agregar", "palabra": "Zorblax"})
    r2 = jv.diccionario_cambiar({"op": "vocab_agregar", "palabra": "zorblax"})
    if not r1.get("ok") or r2.get("ok") or "Zorblax" not in H.load_vocab() or "Zorblax" not in jv._stt_vocab():
        errs.append(f"vocabulario: agregar {r1.get('error')} / duplicado {r2.get('ok')}")
    jv.diccionario_cambiar({"op": "vocab_borrar", "palabra": "Zorblax"})
    if "Zorblax" in H.load_vocab():
        errs.append("vocabulario: borrar no lo quitó")
    _v = jv.diccionario_vista()
    if not _v.get("reglas") or not _v.get("vocabulario") or "contactos" not in _v.get("otras", {}) or not _v.get("migrado"):
        errs.append(f"el panel debe traer reglas, vocabulario y otras listas: {sorted(_v)}")
    _html_u = (HERE / "hud.html").read_text(encoding="utf-8")
    if "VOCABULARIO DE VOZ" not in _html_u or "filtrarDicc" not in _html_u or "palabras de voz" not in _html_u:
        errs.append("el panel DICCIONARIO debe tener buscador, contador y vocabulario de voz")
    out.append(("diccionario único: lo antiguo corrige igual (también «chego»), sin duplicados; borrar lo quita; vocabulario editable", errs))
    # Antes de confirmar un evento nuevo, «no, se llama …» corrige el nombre (no cancela)
    jr = nuevo(H)
    jr.route("agenda una sesión de Shoot Maxing el jueves a las 6")
    antes = dict((jr.pending or {}).get("params") or {})
    res = jr.calendar_rename_pending("no, se llama Chad Maxxing") or {}
    despues = (jr.pending or {}).get("params") or {}
    ok = "«Chad Maxxing»" in res.get("reply", "") and despues.get("start") == antes.get("start") and antes.get("start")
    out.append(("«no, se llama …» corrige el nombre antes de confirmar", [] if ok else [f"dijo {res.get('reply', '')[:120]!r}"]))
    # Uso real: pendiente «Cumpleaños Pedamia» y dijo solo «Cumpleaños Pepe Tamia»: el panel debe cambiar al nombre nuevo
    errs = []
    jr = nuevo(H)
    jr.route("Agenda un evento llamado Cumpleaños Pedamia el 27 de noviembre todo el día")
    antes = dict((jr.pending or {}).get("params") or {})
    res = jr.calendar_rename_pending("Cumpleaños Pepe Tamia") or {}
    st = (jr.pending or {}).get("summary", "")
    if "«Cumpleaños Pepe Tamia»" not in st or "Pedamia" in st:
        errs.append(f"el panel quedó con: {st!r}")
    if ((jr.pending or {}).get("params") or {}).get("start") != antes.get("start"):
        errs.append("cambió la fecha al corregir el nombre")
    for no_es in ["sí", "no", "¿Qué tengo mañana?", "Agenda otra cosa para el lunes", "cancela"]:
        if jr.calendar_rename_pending(no_es):
            errs.append(f"{no_es!r} no es un nombre nuevo")
    out.append(("decir solo el nombre bien dicho reemplaza el del panel de confirmación", errs))
    # Uso real: «Renombra … el evento del viernes 20 a las 9:30 «A» a «B» dejó el título «9:30 «A» a «B»
    import atlas_gcal as G
    errs = []
    ch = G.parse_change("Renombra en mi Google Calendar el evento del viernes 20 a las 9:30 "
                        "«En Google Calendar Entrevista Natalia Ibáñez» a «Entrevista Natalia Ibáñez") or {}
    if (ch.get("query"), ch.get("new_title")) != ("En Google Calendar Entrevista Natalia Ibáñez", "Entrevista Natalia Ibáñez"):
        errs.append(f"entendió {ch.get('query')!r} -> {ch.get('new_title')!r}")
    ch = G.parse_change("Cámbiale el nombre a la reunión de mañana a Almuerzo con papá") or {}
    if ch.get("new_title") != "Almuerzo con papá":
        errs.append(f"sin comillas: {ch.get('new_title')!r}")
    if "decide(true)" not in (HERE / "hud.html").read_text(encoding="utf-8").split('$("no").addEventListener', 1)[1][:600]:
        errs.append("Enter no confirma el panel")
    out.append(("renombrar con nombres entre comillas y confirmar con Enter", errs))
    # Agenda hablada agrupada (regla del usuario): todo el día por día, y los de la misma hora juntos
    import atlas_agenda as A
    d0 = datetime(2026, 11, 15)
    evs = [dict(summary="Feria", when=d0, allday=True), dict(summary="Cumpleaños de Ana", when=d0, allday=True),
           dict(summary="Hackathon", when=d0, allday=True),
           dict(summary="Reunión", when=d0.replace(hour=11)), dict(summary="Llamada", when=d0.replace(hour=11)),
           dict(summary="Almuerzo", when=d0.replace(hour=13)),
           dict(summary="Paseo", when=d0 + timedelta(days=1), allday=True)]
    A._TODAY = d0.date()
    got = A.say_grouped(evs)
    esp = ("hoy tiene Feria, Cumpleaños de Ana y Hackathon, todo el día; hoy a las 11:00 tiene Reunión y Llamada; "
           "Almuerzo hoy a las 13:00; mañana tiene Paseo, todo el día")
    got1 = A.say_grouped(evs[:5], one_day=True)
    esp1 = "todo el día: Feria, Cumpleaños de Ana y Hackathon; a las 11:00 tiene Reunión y Llamada"
    A._TODAY = None
    errs = [f"dijo {g!r}" for g, e in ((got, esp), (got1, esp1)) if g != e]
    out.append(("la agenda agrupa los de todo el día y los de la misma hora", errs))
    # «Espera un correo de Platanus Hack» respondía con los no leídos (uso real 17-11-2026): es una vigilancia de correo.
    # Solo se revisa cómo se entiende la frase (V.parse no guarda nada)
    import atlas_vigilancias as V
    casos = [("Espera un correo de Platanus Hack", "platanus hack"), ("espérame un correo de Platanus Hack", "platanus hack"),
             ("quédate esperando el correo de Platanus Hack", "platanus hack"), ("espera el mail de Platanus", "platanus"),
             ("espera a que me llegue un correo de Platanus Hack", "platanus hack"),
             ("Bueno, espera un correo de Platanus Hack.", "platanus hack"),
             ("avísame cuando llegue un correo de Platanus Hack", "platanus hack"),
             ("espera un momento", None), ("espera, ¿cuántos correos tengo?", None)]
    errs = []
    for x, esp in casos:
        r = V.parse(x)
        got = r["quien"] if r and r.get("op") == "correo" else None
        if got != esp:
            errs.append(f"{x!r} -> {r}")
    out.append(("«espera un correo de X» crea la vigilancia de correo", errs))
    # La voz inventa "señor señor…" con ruido o silencio (uso real 00:55 y 23:40)
    casos = [("Señor Señor, señor Señor señor señor señor señor señor señor señor señor señor señor señor señor señoringo", ""),
             ("Señor señor señor", ""),
             ("Pedro señor señor señor. Pregúntale a Claude cómo estará el clima mañana.", "Pregúntale a Claude cómo estará el clima mañana"),
             ("Señor, ¿qué hora es?", "Señor, ¿qué hora es?"),
             ("Pon música de Ado", "Pon música de Ado"),
             ("no no no no no no", "no")]
    errs = [f"{x!r} -> {H.clean_transcript(x)!r}" for x, esp in casos
            if (esp == "" and H.clean_transcript(x) != "") or (esp and esp not in H.clean_transcript(x))]
    out.append(("se descarta el «señor señor…» que inventa la voz", errs))
    # "Revisar Controles" en su calendario es trabajo suyo (corregir), no una evaluación (uso real 23:51)
    import atlas_agenda as A
    casos = [("Revisar Controles", False), ("Corregir el control 2", False), ("Estudiar para el examen", False),
             ("Control 2 Redes", True), ("Examen Lenguajes", True), ("Entrega proyecto", True)]
    errs = [f"{s!r}: dijo {not esp}" for s, esp in casos if A.is_evaluation({"summary": s}) != esp]
    out.append(("«Revisar Controles» no cuenta como evaluación", errs))
    # Fin de semana: "esta semana" = la semana que empieza el lunes (pedido del usuario). En tareas, desde hoy
    # hasta ese domingo, para no perder lo que vence el mismo fin de semana.
    import atlas_agenda as A
    from datetime import datetime as _dt
    errs = []
    for ahora in (_dt(2026, 11, 14, 23, 0), _dt(2026, 11, 15, 10, 0)):  # sábado y domingo
        r = A.answer("¿Qué tareo para esta semana?", now=ahora) or ""
        if not ("para el fin de semana y la próxima semana" in r and "Tarea 3 de Lenguajes el viernes 20" in r):
            errs.append(f"tareas {ahora:%a}: {r!r}")
        r = A.answer("¿Qué tengo esta semana?", now=ahora) or ""
        v = A.LAST_VIEW or {}
        if "la próxima semana" not in r or v.get("desde") != "2026-11-16" or v.get("tipo") != "calendario":
            errs.append(f"eventos {ahora:%a}: {r!r} vista={v.get('tipo')} {v.get('desde')}")
    r = A.answer("¿Qué tengo esta semana?", now=_dt(2026, 11, 11, 9, 0)) or ""
    if "esta semana" not in r:
        errs.append(f"un miércoles «esta semana» sigue siendo esta semana: {r!r}")
    # ...pero solo para la agenda: un hecho de la semana en curso no es agenda (ni aunque venga justo después)
    for frase in ("¿Cómo estuvo el dólar esta semana?", "¿y el dólar esta semana?", "¿Qué pasó con la bolsa esta semana?"):
        A.answer("¿Qué tengo esta semana?", now=_dt(2026, 11, 14, 12, 0))
        r = A.answer(frase, now=_dt(2026, 11, 14, 12, 1))
        if r is not None:
            errs.append(f"{frase!r} no es agenda, respondió: {r!r}")
    out.append(("fin de semana: «esta semana» = la que empieza el lunes (eventos, calendario y tareas)", errs))
    # Las enumeraciones de agenda traen la vista para la HUD: calendario si son días de una semana, lista si no
    A.answer("¿Qué tengo esta semana?")
    v1 = A.LAST_VIEW or {}
    A.answer("¿Cuándo es mi siguiente evaluación?")
    v2 = A.LAST_VIEW
    errs = []
    if v1.get("tipo") != "calendario" or not v1.get("items") or not all(k in v1["items"][0] for k in ("titulo", "dia", "hora", "tipo")):
        errs.append(f"semana: {v1}")
    if v2 is not None:
        errs.append(f"una sola respuesta no necesita vista: {v2}")
    out.append(("la agenda manda un calendario semanal a la pantalla", errs))
    # Alarma, recordatorio y temporizador suenan en bucle hasta apagarlos (pedido del usuario, 16-11-2026)
    j = H.Atlas()
    j._announce = lambda *a, **k: None  # sin sonido en las pruebas
    al = j.fire_reminder({"id": "a1", "tipo": "alarma", "texto": "", "cuando": AHORA.isoformat()})
    rc = j.fire_reminder({"id": "r1", "tipo": "recordatorio", "texto": "sacar la ropa", "cuando": AHORA.isoformat()})
    tm = j.fire_reminder({"id": "t1", "tipo": "temporizador", "texto": "", "cuando": AHORA.isoformat(), "duracion": 300})
    errs = [] if al["ring"] and rc["ring"] and tm["ring"] else [f"ring: alarma={al['ring']} recordatorio={rc['ring']} temporizador={tm['ring']}"]
    al["ts"] -= 3600  # una hora sin presionarlo: igual debe seguir en pantalla
    shown = {a["id"]: a["ring"] for a in j.status_alerts()} if hasattr(j, "status_alerts") else {}
    if shown.get("a1") is not True:
        errs.append(f"una alarma sin presionar debe seguir en la HUD: {shown}")
    j.ack_alert("a1")
    if al["ring"] or not rc["ring"]:
        errs.append("presionar el aviso de la alarma debía apagar solo esa")
    out.append(("alarmas, recordatorios y temporizadores suenan hasta presionarlos", errs))
    # apagarla por voz o con el botón ■ (sin que suene nada, «apaga la alarma» no es de esta ruta)
    errs = []
    j = nuevo(H)
    j._announce = lambda *a, **k: None
    if j.route_apagar_alarma("apaga la alarma") is not None:
        errs.append("sin nada sonando, «apaga la alarma» debía seguir a las otras rutas")
    tm = j.fire_reminder({"id": "t2", "tipo": "temporizador", "texto": "", "cuando": AHORA.isoformat(), "duracion": 60})
    for no in ("apaga la luz", "para qué sirve esto", "pon una alarma a las 7"):
        if j.route_apagar_alarma(no) is not None:
            errs.append(f"no es apagar la alarma: {no!r}")
    ruta, res, _ = j.route("Apaga el temporizador, por favor")
    if ruta != "recordatorio" or (res or {}).get("reply") != "Temporizador apagado, señor." or tm["ring"]:
        errs.append(f"voz: {ruta} {res} ring={tm['ring']}")
    al = j.fire_reminder({"id": "a2", "tipo": "alarma", "texto": "", "cuando": AHORA.isoformat()})
    ruta, res, _ = j.route("ya, basta")
    if (res or {}).get("reply") != "Alarma apagada, señor." or al["ring"]:
        errs.append(f"«ya, basta»: {ruta} {res}")
    al = j.fire_reminder({"id": "a3", "tipo": "alarma", "texto": "", "cuando": AHORA.isoformat()})
    for frase in ("apágala", "silencia la alarma", "para la alarma", "detén la alarma"):
        al["ring"] = True
        r = j.route_apagar_alarma(frase)
        if not r or al["ring"]:
            errs.append(f"no la apagó: {frase!r}")
    al["ring"] = True
    j.stop_turn()
    if al["ring"]:
        errs.append("el botón ■ debía apagar la alarma")
    html = (HERE / "hud.html").read_text(encoding="utf-8")
    if "function hideAlarm" not in html or "hideAlarm();   // el ■" not in html:
        errs.append("la ventana no cierra el aviso amarillo cuando la apagan por voz o con ■")
    out.append(("la alarma se apaga con ENTENDIDO, por voz o con el botón ■", errs))
    # uso real 17-11: «la alarma en loop no suena bien… se siente cortado»: el bucle es UN sonido continuo, sin clics
    import numpy as np

    import atlas_alarma_sonidos as AS

    errs = []
    for k in AS.SONIDOS:
        one = AS.SONIDOS[k]()
        b = AS.bucle(k, 30.0).astype(np.float64)
        lead = int(AS.RATE * AS.LEAD)
        if not 25 <= (len(b) - lead) / AS.RATE <= 35:
            errs.append(f"{k}: dura {(len(b) - lead) / AS.RATE:.1f} s")
        if abs(b[lead + len(one)] - b[lead + len(one) - 1]) > 1500:
            errs.append(f"{k}: salto (clic) al empalmar las vueltas")
        if np.abs(b).max() < 15000:
            errs.append(f"{k}: muy despacio ({int(np.abs(b).max())})")
    if nuevo(H)._sonido_alarma() != "pulso":
        errs.append("sin ajustes debía quedar «pulso» (el que eligió el usuario)")
    (tmp / "ajustes.json").write_text('{"sonido_alarma": "despertador"}', encoding="utf-8")
    if nuevo(H)._sonido_alarma() != "despertador":
        errs.append("no lee sonido_alarma de ajustes.json")
    (tmp / "ajustes.json").unlink()
    src = (HERE / "hud_server.py").read_text(encoding="utf-8")
    ann = src[src.find("    def _announce("):src.find("    def route_accesos(")]
    if "AS.bucle(sonido, 60.0)" not in ann or "sd.get_stream().active" not in ann:
        errs.append("_announce no toca el bucle continuo")
    a1 = AS.aviso()
    if not (1.5 <= len(a1) / AS.RATE <= 3.5) or np.abs(a1.astype(np.float64)).max() < 12000 or abs(int(a1[-1])) > 50:
        errs.append(f"aviso puntual: debía ser un Pulso de ~3 s que termina en silencio ({len(a1) / AS.RATE:.1f} s)")
    if "AS.aviso()" not in ann:
        errs.append("los avisos puntuales no usan el Pulso")
    out.append(("alarma en bucle: sonido «Pulso» continuo, fuerte y sin clics", errs))
    # borrar por día y hora: una hora que ya pasó hoy sigue siendo hoy; si hay varios a esa hora, pregunta cuál
    errs = []
    extra = [{"id": "g8", "summary": "Desayuno con Rocío", "start": datetime(2026, 11, 9, 8, 0), "end": datetime(2026, 11, 9, 8, 45),
              "allday": False, "location": "", "calendar": "Google"},
             {"id": "g6", "summary": "Café con Benji", "start": datetime(2026, 11, 20, 11, 0), "end": datetime(2026, 11, 20, 12, 0),
              "allday": False, "location": "", "calendar": "Google"},
             {"id": "g7", "summary": "Dentista", "start": datetime(2026, 11, 20, 11, 0), "end": datetime(2026, 11, 20, 11, 30),
              "allday": False, "location": "", "calendar": "Google"}]
    GOOGLE.extend(extra)
    try:
        jc = nuevo(H)
        ruta, res, _ = jc.route("Elimina el evento de hoy a las 8 de la mañana")
        if not (jc.pending and "«Desayuno con Rocío»" in (res or {}).get("reply", "")):
            errs.append(f"hora ya pasada hoy: {ruta} {res}")
        jc.pending = None
        ruta, res, _ = jc.route("borra el evento del viernes 20 a las 11")
        if jc.pending or not re.search(r"^Hay 2 eventos el viernes 20 a las 11:00, señor: «Café con Benji».*«Dentista».*¿Cuál de ellos\?",
                                       (res or {}).get("reply", "")):
            errs.append(f"dos a la misma hora: {res}")
        ruta, res, _ = jc.route("borra el dentista del viernes 20 a las 11")
        if not (jc.pending and "«Dentista»" in (res or {}).get("reply", "")):
            errs.append(f"con nombre y hora: {res}")
    finally:
        for e in extra:
            GOOGLE.remove(e)
    out.append(("borrar eventos por día y hora («el evento de hoy a las 11»)", errs))
    # Fortuna abre un programa del PC (ruta en accesos.json), no una página
    prog = tmp / "Fortuna.exe"
    prog.write_text("", encoding="utf-8")
    (tmp / "accesos.json").write_text(json.dumps({"accesos": [{"nombre": "Fortuna", "dice": ["fortuna"], "ruta": str(prog)}]}), encoding="utf-8")
    lanzados = []
    H.launch = lambda p: lanzados.append(p)
    j2 = nuevo(H)
    ruta, res, _ = j2.route("abre Fortuna")
    errs = [] if ruta == "acceso" and lanzados == [str(prog)] and not j2.pc_raw.calls else [f"ruta={ruta} lanzó={lanzados} pc={j2.pc_raw.calls} {res}"]
    out.append(("«Fortuna» abre el programa guardado en accesos.json", errs))
    # Fortuna "en_atlas": se muestra dentro de la HUD (marco) y «cierra Fortuna» la saca, sin abrir nada en el PC
    pag0 = tmp / "fortuna_embebida.html"
    pag0.write_text("<html>fortuna</html>", encoding="utf-8")
    (tmp / "accesos.json").write_text(json.dumps({"accesos": [{"nombre": "Fortuna", "dice": ["fortuna", "mis fondos"], "ruta": str(pag0), "en_atlas": True}]}), encoding="utf-8")
    lanzados.clear()
    j4 = nuevo(H)
    ra, resa, _ = j4.route("abre mis fondos")
    rb, resb, _ = j4.route("cierra Fortuna")
    rc, resc, _ = j4.route("cierra spotify")
    errs = []
    # uso real 16-11-2026: la voz repitió la palabra y Atlas buscó «historia historia» en el menú Inicio
    # uso real 16-11-2026 21:24: «La U Historia Historia Abre mi Historia» buscó un programa «historia»
    for frase in ("Abre Fortuna Fortuna", "Fortuna Abre Fortuna", "Fortuna, abre Fortuna", "La U Fortuna Fortuna Abre mi Fortuna", "muéstrame mis fondos por favor ya"):
        rr, resr, _ = j4.route(frase)
        if rr != "acceso" or (resr or {}).get("embed", {}).get("url") != "/acceso/fortuna":
            errs.append(f"{frase!r}: {rr} {resr}")
    if ra != "acceso" or (resa or {}).get("embed", {}).get("url") != "/acceso/fortuna" or lanzados or j4.pc_raw.calls:
        errs.append(f"abrir: {ra} {resa} lanzó={lanzados} pc={j4.pc_raw.calls}")
    if rb != "acceso" or not (resb or {}).get("embed", {}).get("close"):
        errs.append(f"cerrar: {rb} {resb}")
    if rc == "acceso":
        errs.append("«cierra spotify» no es un acceso")
    H.ACCESOS_DATOS = tmp / "accesos_datos.json"
    H.acceso_datos("Fortuna", "fm-mine", [{"monto": 1000}])
    if H.acceso_datos("Fortuna") != {"fm-mine": [{"monto": 1000}]}:
        errs.append(f"datos de Fortuna: {H.acceso_datos('Fortuna')}")
    out.append(("Fortuna se abre dentro de Atlas y guarda sus datos en Atlas", errs))
    # Aportes de Fortuna en archivo propio (18-11-2026: un reinicio de Atlas dañó el localStorage y se perdió uno)
    import atlas_fortuna_aportes as FA
    errs = []
    fa = tmp / "fortuna_aportes.json"
    if FA.http("GET", path=fa)[1] != {"ok": True, "existe": False, "aportes": []}:
        errs.append(f"sin archivo: {FA.http('GET', path=fa)}")
    uno = {"key": "10578-DIGITAL", "amount": 1000, "date": "2026-11-18", "target": None, "stop": None}
    c1, r1 = FA.http("POST", json.dumps({"aportes": [uno]}).encode(), path=fa)
    c2, r2 = FA.http("POST", json.dumps({"aportes": [uno, dict(uno, key="8116-WEB", date="2026-11-17")]}).encode(), path=fa)
    if c1 != 200 or c2 != 200 or len(FA.leer(fa)["aportes"]) != 2 or len(FA.leer(fa.with_name(fa.name + ".bak"))["aportes"]) != 1:
        errs.append(f"guardar con .bak: {c1} {c2} {FA.leer(fa)}")
    for malo in ([dict(uno, key="x y")], [dict(uno, amount=-5)], [dict(uno, date="18-11-2026")], "no", [dict(uno, amount=True)]):
        if FA.http("POST", json.dumps({"aportes": malo}).encode(), path=fa)[0] != 400:
            errs.append(f"aceptó {malo!r}")
    if len(FA.leer(fa)["aportes"]) != 2:
        errs.append("un intento inválido cambió el archivo")
    fa.write_text("{dañado", encoding="utf-8")
    if len(FA.leer(fa)["aportes"]) != 1:
        errs.append("archivo dañado: no usó el .bak")
    mf = Path(__file__).resolve().parent.parent / "apps" / "fortuna" / "mis_fondos.html"
    if mf.exists():
        t = mf.read_text(encoding="utf-8")
        if "'/aportes'" not in t or "fm-mine-pend" not in t or "subirMine" not in t:
            errs.append("mis_fondos.html no guarda los aportes en el archivo")
    if 'p0 == "/acceso/fortuna/aportes"' not in (HERE / "hud_server.py").read_text(encoding="utf-8") or not hasattr(H, "esperar_edge_perfil"):
        errs.append("hud_server sin /acceso/fortuna/aportes o sin esperar_edge_perfil")
    out.append(("Fortuna guarda los aportes en ~/.atlas/fortuna_aportes.json (con .bak) y Atlas espera al Edge viejo", errs))
    # Tecla Fin global: escucha, responde y lo dice por los parlantes; la ventana lo ve en /api/live
    j5 = nuevo(H)
    dichos = []
    j5.listen = lambda manual=False: {"text": "qué hora es"}
    j5.chat = lambda t: {"reply": "Son las nueve, señor.", "tools": []}
    j5._play = lambda t: dichos.append((t, j5.mode))
    j5.voice_turn()
    lv = j5.live()
    errs = []
    if lv["turn"].get("reply") != "Son las nueve, señor." or lv["turn"].get("you") != "qué hora es":
        errs.append(f"turno: {lv}")
    if dichos != [("Son las nueve, señor.", "speaking")] or lv["mode"] != "idle" or lv["busy"]:
        errs.append(f"habla={dichos} modo={lv['mode']} ocupado={lv['busy']}")
    j5.listen = lambda manual=False: {"text": "", "error": "No le escuché bien, señor."}
    j5.voice_turn()
    if j5.live()["turn"].get("reply") != "No le escuché bien, señor.":
        errs.append(f"sin voz: {j5.live()}")
    out.append(("tecla Fin global: escucha, responde y avisa a la ventana", errs))
    # Pantalla de carga: el servidor informa cada parte; lo que no llega a tiempo cuenta como falla
    j6 = nuevo(H)
    errs = []
    bv = j6.boot_view()
    faltan = [k for k in ("nucleo", "oido", "voz", "correo", "agenda", "google", "recordatorios", "tecla", "flotante",
                          "telegram", "whatsapp", "canvas", "_apps") if k not in bv]
    if faltan:
        errs.append(f"faltan partes: {faltan}")
    # pantalla de carga «Constelaciones»: APLICACIONES sale de las apps instaladas
    if [a["nombre"] for a in bv["_apps"]] != [a["nombre"] for a in H.apps_view()] or any(bv.get("app_" + a["k"]) is not True for a in bv["_apps"]):
        errs.append(f"las apps de la carga no calzan con las instaladas: {bv['_apps']}")
    if any(v not in (True, False, "error", "off") for k, v in bv.items() if not k.startswith("_")):
        errs.append(f"estado raro: {bv}")
    j6.t0 -= 120
    bv = j6.boot_view()
    if "--no-window" not in sys.argv and bv["flotante"] != "error":
        errs.append(f"círculo que nunca respondió no cuenta como falla: {bv['flotante']}")
    if bv["telegram"] is False or bv["agenda"] is False:
        errs.append(f"telegram/agenda siguen cargando tras 2 min: {bv}")
    out.append(("pantalla de carga: estado de cada parte, con tiempo límite", errs))
    # Calendario: el detalle de un evento trae las personas, con el nombre de la libreta si calzan
    import atlas_agenda as A7
    import atlas_contactos as C7
    errs = []
    viejo = C7.load
    C7.load = lambda: [{"id": "1", "nombre": "Valentina Soto", "apodos": ["Vale"], "correo": "vale@x.cl", "discord": ""}]
    try:
        ics = "\n".join(["BEGIN:VEVENT", "SUMMARY:Almuerzo", "DTSTART:20261119T130000", "DTEND:20261119T143000",
                         "ORGANIZER;CN=Pedro Soto:mailto:pedro@y.cl", 'ATTENDEE;CN="Vale R":mailto:vale@x.cl', "END:VEVENT"])
        ppl = A7._people(A7.parse_ics(ics, "Google")[0])
        if [(p["nombre"], p["contacto"], p["organiza"]) for p in ppl] != [("Pedro Soto", False, True), ("Valentina Soto", True, False)]:
            errs.append(f"personas: {ppl}")
    finally:
        C7.load = viejo
    out.append(("calendario: personas del evento, con nombre de contactos", errs))
    # Calendario semanal de la HUD (botón SEMANA ›, /api/horario): siempre lunes a domingo, 7 columnas, con los días
    # ya pasados. Uso real 17-11-2026: un martes mostraba solo 6 días (de hoy al domingo).
    errs = []
    ev7 = {"summary": "Reunión del lunes", "when": datetime(2026, 11, 16, 10), "start": datetime(2026, 11, 16, 10),
           "end": datetime(2026, 11, 16, 11), "allday": False, "calendar": "Google", "uid": "x@google.com"}
    rangos7 = []

    def up7(a, b, incluir_listas=False):
        rangos7.append((a, b))
        return ([ev7] if a <= ev7["when"] < b else []), [], False

    viejos7 = (A7.load_calendars, A7.upcoming, A7._gcal_connected)
    A7.load_calendars, A7.upcoming, A7._gcal_connected = (lambda: [{"nombre": "x"}]), up7, (lambda: True)
    try:
        for hoy in (datetime(2026, 11, 17, 15), datetime(2026, 11, 16, 8), datetime(2026, 11, 22, 21)):  # mar, lun, dom
            A7.answer("muéstrame mi horario de esta semana", hoy, semana_completa=True)
            v = A7.LAST_VIEW or {}
            if (v.get("desde"), v.get("dias")) != ("2026-11-16", 7) or not v.get("items"):
                errs.append(f"{hoy:%a %d}: vista {v.get('desde')} x {v.get('dias')} días, {len(v.get('items') or [])} eventos")
        rangos7.clear()
        A7.answer("¿qué tengo esta semana?", datetime(2026, 11, 17, 15))  # la respuesta hablada no cambia
        if ("2026-11-17", datetime(2026, 11, 23)) not in [(x.date().isoformat(), y) for x, y in rangos7]:  # lo hablado (la vista aparte)
            errs.append(f"«¿qué tengo esta semana?» debía seguir de hoy al domingo: {rangos7[-1:]}")
        # por voz o chat (sin semana_completa) la vista que se abre también es lunes a domingo, con el lunes ya pasado
        # (uso real 17-11-2026: el horario abierto por voz un martes no mostraba lo del lunes 16)
        for frase in ("muéstrame mi horario de esta semana", "mi horario", "¿qué tengo esta semana?"):
            A7._LAST, A7.LAST_VIEW = None, None
            A7.answer(frase, datetime(2026, 11, 17, 15))
            v = A7.LAST_VIEW or {}
            if (v.get("desde"), v.get("dias")) != ("2026-11-16", 7) or "2026-11-16" not in {i.get("dia") for i in v.get("items") or []}:
                errs.append(f"«{frase}» por voz: vista {v.get('desde')} x {v.get('dias')} días, {len(v.get('items') or [])} eventos")
    finally:
        A7.load_calendars, A7.upcoming, A7._gcal_connected = viejos7
        A7._LAST, A7.LAST_VIEW = None, None
    out.append(("calendario semanal de la HUD: lunes a domingo (7 días)", errs))
    # Al cerrar la ventana o la pestaña la voz se corta al instante (uso real 17-11-2026: seguía hablando)
    errs = []
    src_srv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    src_html = (HERE / "hud.html").read_text(encoding="utf-8")
    src_flo = (HERE / "atlas_flotante.py").read_text(encoding="utf-8")
    if 'if p0 == "/api/voz/detener":' not in src_srv or "def detener_voz() -> None:" not in src_srv:
        errs.append("falta el endpoint /api/voz/detener o detener_voz()")
    ap = src_srv.split('elif self.path == "/api/apagar":', 1)[-1][:600]
    if "detener_voz()  # lo primero" not in ap or "detener_voz(), os._exit(0)" not in ap:
        errs.append("/api/apagar no llama a detener_voz() antes de salir")
    if not ('window.addEventListener("pagehide", cortarVozAlCerrar);' in src_html
            and 'navigator.sendBeacon("/api/voz/detener?t=" + encodeURIComponent(TOKEN)' in src_html):
        errs.append("hud.html no corta la voz en pagehide con sendBeacon")
    if "detener_voz()" not in src_flo.split("if not gone_since:", 1)[-1][:120]:
        errs.append("el círculo flotante no calla la voz apenas desaparece la ventana")
    calls = []
    viejo_h, viejo_m = H.ATLAS.hush_voice, H.ATLAS.mode
    H.ATLAS.hush_voice = lambda page=True: calls.append(page)
    try:
        H.detener_voz()
        if calls != [True]:
            errs.append(f"detener_voz() no calló servidor y ventana: {calls}")
    finally:
        H.ATLAS.hush_voice, H.ATLAS.mode = viejo_h, viejo_m
    out.append(("al cerrar la ventana la voz se corta al instante", errs))
    # Una sola ventana al abrir Atlas, y las pruebas nunca abren nada visible (uso real 17-11-2026: se abrían de más)
    errs = []
    src_srv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    ow = src_srv.split("def open_window(url: str) -> None:", 1)[-1][:1200]
    for frag in ('"--hide-crash-restore-bubble", "--disable-session-crashed-bubble"', "_perfil_sin_restaurar(profile)"):
        if frag not in ow:
            errs.append(f"open_window sin {frag!r}")
    if src_srv.count('f"--app={') != 1:
        errs.append("debe haber un solo lugar que abre la ventana de Atlas (open_window)")
    mn = src_srv.split("def main() -> None:", 1)[-1][:2600]
    if not ("servidor_vivo()" in mn and "focus_window(wins[0])" in mn and mn.index("servidor_vivo()") < mn.index("stop_old_instances()")):
        errs.append("un segundo Atlas.cmd debe enfocar la ventana existente en vez de arrancar otro")
    if "cerrar_ventanas_viejas()" not in src_srv.split("def _serve(", 1)[-1]:
        errs.append("_serve no cierra las ventanas de un Atlas anterior")
    if '("hud_server.py" in cmd or "atlas_flotante.py" in cmd)' not in src_srv:
        errs.append("el círculo flotante viejo debe cerrarse junto con el servidor viejo")
    for lanz in ("Atlas.cmd", "Jarvis.cmd"):   # Jarvis.cmd se retiró (18-11-2026); si sigue en algún PC, tampoco abre Edge
        if not (HERE.parent / lanz).exists() and lanz != "Atlas.cmd":
            continue
        txt = (HERE.parent / lanz).read_text(encoding="utf-8", errors="replace").lower()
        if "msedge" in txt or "http" in txt:
            errs.append(f"{lanz} no debe abrir el navegador por su cuenta")
    # El ejecutable se llama Atlas (18-11-2026): Atlas.cmd arranca Atlas.exe y, si falta, lo crea o usa pythonw.exe
    _ac = (HERE.parent / "Atlas.cmd").read_text(encoding="utf-8", errors="replace")
    for frag in ("Scripts\\Atlas.exe", "atlas_crear_exe.py", 'if not exist "%EXE%" set "EXE=', 'start "Atlas" "%EXE%"', "hud_server.py"):
        if frag not in _ac:
            errs.append(f"Atlas.cmd sin {frag!r}")
    if "jarvis" in _ac.lower():
        errs.append("Atlas.cmd no debe nombrar a Jarvis")
    import atlas_crear_exe as _ACE
    _vi = _ACE._version()
    if b"F\x00i\x00l\x00e\x00D\x00e\x00s\x00c" not in _vi or "Atlas".encode("utf-16-le") not in _vi \
            or len(_vi) != int.from_bytes(_vi[:2], "little") or "Python".encode("utf-16-le") in _vi:
        errs.append("atlas_crear_exe: la versión debe decir «Atlas» (descripción)")
    if 'exe.name.lower() == "atlas.exe" else exe.with_name("pythonw.exe")' not in src_srv:
        errs.append("el círculo flotante debe correr como Atlas.exe cuando Atlas corre así")
    tmpp = tmp / "perfil_prueba"
    (tmpp / "Default").mkdir(parents=True, exist_ok=True)
    (tmpp / "Default" / "Preferences").write_text('{"profile": {"exit_type": "Crashed", "exited_cleanly": false}, "x": 1}', encoding="utf-8")
    H._perfil_sin_restaurar(str(tmpp))
    pr = json.loads((tmpp / "Default" / "Preferences").read_text(encoding="utf-8"))
    if pr.get("profile", {}).get("exit_type") != "Normal" or pr.get("x") != 1:
        errs.append(f"el perfil no quedó como cerrado bien: {pr}")
    abiertos = []
    viejo_popen, viejo_sf = H.subprocess.Popen, getattr(H.os, "startfile", None)
    H.subprocess.Popen = lambda *a, **k: abiertos.append(a)
    H.os.startfile = lambda *a, **k: abiertos.append(a)
    try:
        if not H.en_pruebas():
            errs.append("las pruebas deben correr con ATLAS_PRUEBAS=1")
        H.open_window("http://127.0.0.1:1/")
        H.launch(r"C:\no\existe.lnk")
    finally:
        H.subprocess.Popen = viejo_popen
        if viejo_sf:
            H.os.startfile = viejo_sf
    if abiertos:
        errs.append(f"con ATLAS_PRUEBAS=1 se abrió algo: {abiertos}")
    import atlas_canvas_notas as CN
    import atlas_ucursos_notas as UN
    for mod in (CN, UN):
        if 'os.environ.get("ATLAS_PRUEBAS") == "1"' not in Path(mod.__file__).read_text(encoding="utf-8").split("def login(", 1)[-1][:900]:
            errs.append(f"{Path(mod.__file__).name}: login() abriría su ventana durante las pruebas")
    out.append(("una sola ventana de Atlas, y las pruebas no abren nada visible", errs))
    # Ajustes › Instalación › texto plano para que otra IA instale Atlas (18-11-2026): completo y sin datos privados
    errs = []
    import atlas_ajustes as AJI
    import atlas_faltantes as FAI
    import atlas_instrucciones_ia as IAI
    fal = FAI.revisar("9.9", {}, {}, ["Fortuna", "Hermes", "Cronos"])
    aj = AJI.vista()
    txt = IAI.generar("9.9", fal, aj)
    for p in fal["pasos"]:
        if f"{p['titulo']}  [" not in txt:
            errs.append(f"falta el paso de instalación «{p['titulo']}»")
        if p["titulo"] not in IAI.VERIFICAR:
            errs.append(f"«{p['titulo']}» no tiene cómo verificarlo")
    for s in aj["secciones"]:
        if f" {s['nombre']}\n" not in txt:
            errs.append(f"falta la sección de ajustes «{s['nombre']}»")
        for a in s["ajustes"]:
            if a["nombre"] not in txt:
                errs.append(f"falta el ajuste «{a['nombre']}»")
    for sec in ("0. PARA LA IA", "1. QUÉ ES ATLAS", "OpenJarvis", "2. REQUISITOS", "3. CARPETAS", "4. CÓMO ARRANCAR",
                "8. CREDENCIALES Y SEGURIDAD", "9. PRUEBAS", "10. DIAGNÓSTICO", "Atlas-diagnostico.cmd", "pruebas_vigilancias.py"):
        if sec not in txt:
            errs.append(f"falta {sec!r}")
    prob = IAI.privacidad(txt, H.TOKEN)
    if prob:
        errs.append(f"privacidad: {prob}")
    for malo in ("x@y.cl", "C:\\Users\\Pedro\\x", "1234567", H.TOKEN):
        if not IAI.privacidad("hola " + malo, H.TOKEN):
            errs.append(f"el filtro de privacidad deja pasar {malo[:12]!r}")
    src_srv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    if 'if self.path == "/api/ajustes/instrucciones_ia":' not in src_srv or "IA.privacidad(txt, TOKEN)" not in src_srv:
        errs.append("falta el endpoint /api/ajustes/instrucciones_ia con su filtro")
    src_html = (HERE / "hud.html").read_text(encoding="utf-8")
    for frag in ('"MOSTRAR TEXTO PLANO PARA QUE UNA IA LO INSTALE"', 'api("/api/ajustes/instrucciones_ia")', "ta.readOnly = true", '"COPIAR"'):
        if frag not in src_html:
            errs.append(f"hud.html sin {frag!r}")
    out.append(("Ajustes: texto plano para que una IA instale Atlas, completo y sin datos privados", errs))
    # Hermes, método del 18-11-2026: correo de transferencias + avisos del banco (MacroDroid -> Syncthing); sin cartolas
    errs = []
    for frag in ("MacroDroid", "Syncthing", "--solo-avisos", "Solo enviar", "Solo recibir", "127.0.0.1:8384",
                 "Probar acción", "día hábil anterior"):
        if frag not in txt:
            errs.append(f"el texto para la IA no menciona {frag!r}")
    if re.search(r"(?i)cartola|estado de cuenta", txt):
        errs.append("el texto para la IA todavía presenta las cartolas o estados de cuenta como fuente")
    # 18-11-2026 (17:00): Hermes ya no es un paso de Instalación; su instalación va en Guía de las apps › Hermes
    if any(p["titulo"] == "Hermes: avisos del banco" for p in fal["pasos"]):
        errs.append("Hermes no debe seguir como paso de Ajustes › Instalación")
    ph = (fal.get("guia") or {}).get("Hermes")
    if not ph or [s["nombre"] for s in ph["sistemas"]] != ["Correo conectado", "Syncthing", "Syncthing corriendo", "Carpeta avisos_banco", "Último aviso"] \
            or not ph.get("clave_pdf") or ph.get("estado") not in ("g", "y", "x"):
        errs.append(f"la guía de Hermes debe traer su instalación con los 5 controles y la contraseña: {ph and [s['nombre'] for s in ph['sistemas']]}")
    _pa = next((p for p in fal["pasos"] if p["titulo"] == "Apps"), {})
    if not any(b["tipo"] == "seccion" and b["valor"] == "__guia#hermes" for b in _pa.get("botones", [])) \
            or "Hermes: avisos del banco»" in " ".join(_pa.get("como", [])):
        errs.append("Instalación › Apps debe llevar a Guía › Hermes (CONFIGURAR HERMES) y no a un paso que ya no existe")
    if "5b. INSTALACIÓN DE LAS APPS" not in txt or "no requiere nada extra" not in txt:
        errs.append("el texto para la IA debe tener la instalación de las apps")
    # 18-11-2026: Instalación solo configura (sin duplicar la guía); el uso de Hermes vive en Ajustes › Guía de las apps
    if ph:
        _txt_ph = " ".join([ph["que"], *ph["como"]])
        for _uso in ("día 23", "3 días", "fondos mutuos", "actualiza Hermes"):
            if _uso in _txt_ph:
                errs.append(f"Instalación › Hermes repite el uso ({_uso!r}): va en la guía")
    _hh = (HERE / "hud.html").read_text(encoding="utf-8")
    _gh = _hh.split('"app": "Hermes"', 1)[-1].split("];", 1)[0]
    for _m in ("CICLOS DE LA TARJETA", "día hábil anterior", "QUÉ CUENTA COMO GASTO", "no es gasto" if False else "son ahorro, no gasto",
               "APORTES Y RESCATES", "CÓMO ACTUALIZAR", "actualiza Hermes", "ACTUALIZAR dentro de Hermes"):
        if _m not in _gh:
            errs.append(f"la guía de Hermes debe explicar {_m!r}")
    for _app in ("Fortuna",):   # Cronos ya no: su instalación trae los dos modos (rutas y señales), 18-11-2026
        _ga = _hh.split(f'"app": "{_app}"', 1)[-1].split('"titulo"', 1)[0]
        if '"instalacion": "No requiere nada extra.' not in _ga:
            errs.append(f"la guía de {_app} debe decir en su instalación «No requiere nada extra»")
    _gc = FA_MOD.cronos_instalacion({"modo_ubicacion": "senales"}) if (FA_MOD := __import__("atlas_faltantes")) else {}
    _tc = " ".join(_gc.get("como") or [])
    for _m in ("MODO AUTOMÁTICO", "MODO MANUAL", "secretos.py token", "tarjetabip.cl", "takeout.google.com", "sin archivos"):
        if _m not in _tc:
            errs.append(f"la instalación de Cronos debe explicar {_m!r}")
    if '"app": "Cronos",\n  "instalacion"' in _hh.replace("\r\n", "\n"):
        errs.append("la guía de Cronos debe tomar su instalación de /api/faltantes (guia.Cronos), no de un texto fijo")
    if "MacroDroid anota cada notificación" in _gh or "texto mágico" in _gh:
        errs.append("la guía no debe repetir los pasos de configuración de Instalación")
    if 'document.getElementById("guia-" + ancla)' not in _hh or "...(g.uso || [])" not in _hh:
        errs.append("hud.html: el botón debe abrir la guía en la sección y mostrar las secciones de uso")
    _dav2 = tmp / "avisos_falt"
    _dav2.mkdir(exist_ok=True)
    _f2 = _dav2 / "avisos_banco.txt"
    _ah = datetime(2026, 11, 18, 12, 0)
    if FAI._ultimo_aviso(_dav2, _ah)[0] != "y":
        errs.append("sin archivo de avisos debe quedar a medias")
    _f2.write_text("@@|2026-11-18 1:38|{not_app_name}|{not_title}|{notification}", encoding="utf-8")   # «Probar acción»
    e2 = FAI._ultimo_aviso(_dav2, _ah)
    if e2[0] != "y" or "primer aviso real" not in e2[1]:
        errs.append(f"«Probar acción» debe mostrar «esperando el primer aviso real»: {e2}")
    _f2.write_text("@@|{year}-{month_digit}-{dayofmonth} {hour}:{minute}|{not_app_name}|{not_title}|{notification}\n", encoding="utf-8")
    e3 = FAI._ultimo_aviso(_dav2, _ah)
    if e3[0] != "x" or "insértelos con el botón" not in e3[1]:
        errs.append(f"llaves también en la fecha deben marcar «falta»: {e3}")
    _f2.write_text("@@|2026-11-18 1:38|{not_app_name}|{not_title}|{notification}@@|2026-11-18 9:05|Banco|Compra|Compra por $1.000\n",
                   encoding="utf-8")
    e4 = FAI._ultimo_aviso(_dav2, _ah)
    if e4 != ("g", "Último aviso: hoy 09:05"):
        errs.append(f"un aviso real debe quedar ok con su fecha: {e4}")
    if "Compra" in " ".join(e4) or "1.000" in " ".join(e4):
        errs.append("el estado no debe mostrar el contenido del aviso")
    out.append(("Instalación de Hermes: MacroDroid + Syncthing + --solo-avisos, sin cartolas, y control del último aviso", errs))
    # «OpenAtlas» fue un reemplazo equivocado de «OpenJarvis» (18-11-2026): 11 scripts apuntaban a una carpeta inexistente
    errs = []
    raiz = HERE.parent
    archivos = list(raiz.glob("*.cmd")) + list((raiz / "bin").glob("*.cmd")) + list(HERE.glob("*.py")) + list(HERE.glob("*.html"))
    for f in archivos:
        if f.name.startswith("pruebas_"):
            continue
        if "Open" + "Atlas" in f.read_text(encoding="utf-8", errors="replace"):
            errs.append(f"{f.name} dice «Open" + "Atlas»: la ruta es %LOCALAPPDATA%\\Atlas y el proyecto base es OpenJarvis")
    for f in raiz.glob("*.cmd"):
        for m in re.findall(r'%LOCALAPPDATA%\\Atlas\\hud\\([\w\\]+\.py)', f.read_text(encoding="utf-8", errors="replace")):
            if not (HERE / m.replace("\\", "/")).exists():
                errs.append(f"{f.name} llama a hud\\{m}, que no existe")
    if "Administrador de credenciales" not in txt or "atlas_secretos.py" not in txt:
        errs.append("el texto para la IA debe explicar que los secretos van al Administrador de credenciales")
    out.append(("ningún script ni módulo apunta a «Open" + "Atlas»", errs))
    # Apolo -> Hermes e Isis -> Fortuna (18-11-2026): los nombres viejos ya no son apps ni comandos (Apolo y Atenea
    # quedan libres para apps futuras); las carpetas de datos del usuario conservan su nombre
    errs = []
    viejos = ("apo" + "lo", "is" + "is")
    acc_real = json.loads((HERE / "accesos.json").read_text(encoding="utf-8"))["accesos"]
    nombres = {a["nombre"] for a in acc_real}
    if not {"Hermes", "Fortuna", "Cronos"} <= nombres:
        errs.append(f"accesos.json: {sorted(nombres)}")
    for a in acc_real:
        for v in viejos + ("Apollo",):
            if H.acceso_calza(v, a):
                errs.append(f"«{v}» todavía abre {a['nombre']}")
        if any(v in x.lower() for x in [a["nombre"], a.get("se_dice", "")] + a.get("dice", []) for v in viejos):
            errs.append(f"{a['nombre']} todavía se dice con un nombre viejo")
    for want, quien in (("Hermes", "Hermes"), ("abre Fortuna", None), ("Fortuna", "Fortuna"), ("mis gastos", "Hermes"), ("mis fondos", "Fortuna")):
        if quien and not any(H.acceso_calza(want, a) and a["nombre"] == quien for a in acc_real):
            errs.append(f"«{want}» no abre {quien}")
    src_html = (HERE / "hud.html").read_text(encoding="utf-8")
    for v in viejos:
        if re.search(rf"(?<![\w-]){v}\s*:", src_html, re.I) or re.search(rf"\bintro{v.capitalize()}\b", src_html):
            errs.append(f"hud.html todavía tiene la clave «{v}»")
        if (HERE / f"atlas_{v}.py").exists() or f"route_{v}" in (HERE / "hud_server.py").read_text(encoding="utf-8"):
            errs.append(f"queda el módulo o la ruta de «{v}»")
    for k in ("hermes", "fortuna"):
        for blo in ("const SONIDOS_INTRO", "const INTRO_APPS", "APP_LOOK." + k):
            i = src_html.find(blo)
            if i < 0 or (blo != "APP_LOOK." + k and f"{k}:" not in src_html[i:src_html.find("};", i)]):
                errs.append(f"hud.html: falta {k} en {blo}")
    from openjarvis.security import atlas_secretos as SEC
    antes = SEC._backend_prueba
    try:
        SEC._backend_prueba = {"Atlas-Apo" + "lo-PDF": "x1"}
        if SEC.leer(SEC.HERMES_PDF) != "x1" or SEC.APOLO_PDF != "Atlas-Hermes-PDF":
            errs.append("Hermes debe leer primero Atlas-Hermes-PDF y, si no está, la entrada vieja")
        SEC._backend_prueba["Atlas-Hermes-PDF"] = "x2"
        if SEC.leer(SEC.HERMES_PDF) != "x2":
            errs.append("Atlas-Hermes-PDF debe ganarle a la entrada vieja")
    finally:
        SEC._backend_prueba = antes
    out.append(("Apolo e Isis ya no son apps ni comandos: quedan Hermes y Fortuna", errs))
    # Contexto de la conversación (uso real): «agenda una reunión para Empresa hoy a las 9 y media de la noche» quedó
    # esperando el «sí» y «añade a Tipo y Pipe a esa reunión» se tomó como un evento nuevo («¿para qué día?»)
    errs = []
    jc = H.Atlas()
    jc.ready, jc.refresh_inbox, jc.pc_raw, jc.gmail_raw = True, (lambda: None), Fake("pc"), Fake("gmail")
    r0 = jc.chat("¿quiénes van a esa reunión?")
    if not re.search(r"A qué reunión se refiere", r0.get("reply", "")):
        errs.append(f"sin nada antes debía preguntar cuál: {r0.get('reply', '')[:160]!r}")
    jc.chat("Agenda una reunión para Empresa hoy a las nueve y media de la noche")
    if not (jc.pending and jc.pending["params"].get("start")):
        errs.append("no quedó la reunión esperando el «sí»")
    else:
        if "Reunión para Empresa" not in jc.conversation_context():
            errs.append(f"el modelo no recibe lo pendiente: {jc.conversation_context()!r}")
        rn = jc.chat("Quiero que añadas a la reunión de Empresa al tipo")
        if not re.search(r"Anoté a Sebastián Lagos en «Reunión para Empresa»", rn.get("reply", "")):
            errs.append(f"por su nombre, la reunión pendiente: {rn.get('reply', '')[:200]!r}")
        r1 = jc.chat("Añade a Tipo y Toño a esa reunión")
        if not re.search(r"Anoté a Sebastián Lagos, Antonio Fuenzalida en «Reunión para Empresa».*cuando diga «sí»", r1.get("reply", "")):
            errs.append(f"contactos en la reunión pendiente: {r1.get('reply', '')[:200]!r}")
        if "(con Sebastián Lagos, Antonio Fuenzalida)" not in jc.pending.get("summary", ""):
            errs.append(f"el panel no muestra los contactos: {jc.pending.get('summary')!r}")
        r2 = jc.chat("sí")
        if not re.search(r"Agendé «Reunión para Empresa».*Asocié a Sebastián Lagos, Antonio Fuenzalida", r2.get("reply", "")):
            errs.append(f"al confirmar: {r2.get('reply', '')[:200]!r}")
        if [c["nombre"] for c in AV.linked({"id": "nuevo1"})] != ["Sebastián Lagos", "Antonio Fuenzalida"]:
            errs.append(f"asociación guardada: {AV.linked({'id': 'nuevo1'})}")
        r3 = jc.route_evento_contactos("¿quiénes van a esa reunión?")
        if not re.search(r"«Reunión para Empresa».*están: Sebastián Lagos, Antonio Fuenzalida", (r3 or {}).get("reply", "")):
            errs.append(f"después de crearla, «esa reunión» es la recién agendada: {(r3 or {}).get('reply', '')[:200]!r}")
        t4, ref = jc.resolve_refs("cámbiale el nombre a esa reunión")
        if t4 != "cámbiale el nombre a la Reunión para Empresa" or not ref:
            errs.append(f"las demás órdenes reciben el nombre del evento: {t4!r}")
        if "Reunión para Empresa" not in jc.conversation_context():
            errs.append("el modelo no recibe el último evento")
    out.append(("contexto: «esa reunión» es la de la conversación, aunque espere el «sí»", errs))
    # «Mi día»: el detalle de un evento de Google trae los contactos asociados a mano (eventos_contactos.json)
    import atlas_agenda as A8
    errs = []
    AV.link({"id": "g2", "summary": "Reunión con Felipe", "start": ""}, CT.find("Toño"))
    ppl = A8._people({"id": "g2", "attendees": [{"email": "camila@uni.example", "name": "Camila"}]})
    if ppl[0]["nombre"] != "Camila Soto" or ppl[0].get("asociado") or ("Antonio Fuenzalida", True) not in [(p["nombre"], p.get("asociado", False)) for p in ppl]:
        errs.append(f"personas: {ppl}")
    ppl = A8._people({"uid": "g2@google.com", "attendees": []})
    if "Antonio Fuenzalida" not in [p["nombre"] for p in ppl]:
        errs.append(f"por el uid del iCal de Google: {ppl}")
    out.append(("agenda: el evento muestra los contactos asociados", errs))
    # U-Cursos (uso real): con la sesión vencida cada ramo daba 401 y Atlas decía «No hay notas nuevas. Revisé 0 ramos»
    import urllib.error

    import atlas_ucursos_notas as U9
    errs = []
    jn = H.Atlas()
    viejos = (U9.has_session, U9.check, U9.course_grades, U9.urlopen if hasattr(U9, "urlopen") else None)
    try:
        U9.has_session, U9.course_grades = (lambda: True), (lambda p, *a: (None, {}))
        U9.check = lambda *a, **k: {"nuevas": [], "errores": ["Redes: timeout", "Lenguajes: timeout"], "revisados": 0}
        r = jn.route_notas("¿Tengo alguna nueva nota?") or {}
        if "No hay notas nuevas" in r.get("reply", "") or "No pude revisar sus notas" not in r.get("reply", ""):
            errs.append(f"sin ningún ramo revisado no puede decir que no hay notas: {r.get('reply', '')[:160]!r}")
        real_open = U9.urllib.request.urlopen

        def _401(*a, **k):
            raise urllib.error.HTTPError("https://www.u-cursos.cl/x/notas/", 401, "Unauthorized", {}, None)
        U9.urllib.request.urlopen = _401
        U9.HERE = tmp  # nunca la sesión real del usuario
        U9._sess_file().write_text('{"cookies": [{"name": "a", "value": "b", "domain": ".u-cursos.cl"}]}', encoding="utf-8")
        try:
            U9.fetch("x/notas/")
            errs.append("un 401 debía contar como sesión vencida")
        except U9.SessionExpired:
            pass
        finally:
            U9.urllib.request.urlopen = real_open
            U9._sess_file().unlink(missing_ok=True)
    finally:
        U9.has_session, U9.check, U9.course_grades = viejos[:3]
    out.append(("notas: 401 es sesión vencida; sin ramos revisados no dice «no hay notas»", errs))
    # Avisos: Telegram solo si no le habló a Atlas hace rato; preguntas al usuario no son «prometer acciones»;
    # ruido corto pide repetir; el modelo ve la libreta de contactos
    errs = []
    jt = H.Atlas()
    jt._announce = lambda *a, **k: None
    tg_sent = []
    jt.telegram = type("TG", (), {"send": lambda self_, x: tg_sent.append(x)})()
    jt.presente = lambda: True  # 18-11-2026: presencia = teclado y mouse, no el rato sin hablarle a Atlas
    jt.notify("aviso con el usuario presente", "prueba")
    jt.presente = lambda: False
    jt.notify("aviso con el usuario lejos", "prueba")
    time.sleep(0.3)
    if tg_sent != ["aviso con el usuario lejos"]:
        errs.append(f"Telegram recibió {tg_sent}")
    if not H.claims_action("Entendido, señor: quiere llamar a Pipe. Le envío el mensaje de confirmación ahora."):
        errs.append("«Le envío…» sin herramienta no se detectó como promesa")
    if H.claims_action("No tengo ese contacto, señor. ¿Podría confirmar si desea abrir Discord?"):
        errs.append("una pregunta al usuario contó como acción prometida")
    if "Sebastián Lagos" not in jt.conversation_context():
        errs.append("el contexto del modelo no trae la libreta de contactos")
    out.append(("avisos por Telegram, preguntas y libreta en el contexto", errs))
    # Importar del teléfono: lee una copia de la base de Enlace Móvil; nada se añade sin elegirlo; saltados y repetidos no vuelven
    import sqlite3 as _sq

    import atlas_importar_contactos as IC

    errs = []
    db = tmp / "pl_contacts.db"
    con = _sq.connect(db)
    con.executescript("""create table contact(contact_id integer primary key, display_name text, nickname text);
        create table phonenumber(phone_number_id integer primary key, contact_id integer, phone_number text, display_phone_number text);
        insert into contact values (1,'Sebastián Lagos',''),(2,'Mamá',''),(3,'Pedro Pérez','Pedrito'),(4,'Sin Número','');
        insert into phonenumber values (1,1,'+56987654321','+56 9 8765 4321'),(2,2,'+56911112222','+56 9 1111 2222'),
            (3,3,'+56933334444','+56 9 3333 4444'),(4,3,'+56933334444','+56933334444');""")
    con.commit()
    con.close()
    IC.SKIPPED = tmp / "contactos_saltados.json"
    r = IC.candidates(db)
    if [c["nombre"] for c in r["pendientes"]] != ["Mamá", "Pedro Pérez"] or r["ya"] != 1:
        errs.append(f"candidatos: {r}")
    elif r["pendientes"][1]["telefonos"] != ["+56 9 3333 4444"] or r["pendientes"][1]["apodo"] != "Pedrito":
        errs.append(f"números/apodo de Pedro: {r['pendientes'][1]}")
    IC.skip("pl:2")
    IC.add("pl:3", "Pedro Pérez", "+56 9 3333 4444", "Pedrito")
    r2 = IC.candidates(db)
    if r2["pendientes"] or r2["saltados"] != 1 or r2["ya"] != 2:
        errs.append(f"después de saltar y añadir: {r2}")
    CT.delete(next(c["id"] for c in CT.load() if c["nombre"] == "Pedro Pérez"))
    # el nombre del teléfono suele ser el apodo: sin nombre completo, se guarda con el primer apodo
    c = IC.add("pl:9", "", "+56 9 7777 8888", "Pipe, Pipeño")
    if c["nombre"] != "Pipe" or [x["nombre"] for x in CT.find("Pipeño")] != ["Pipe"]:
        errs.append(f"solo apodo: {c}")
    CT.delete(c["id"])
    # mismo formato de número venga como venga (escrito con espacios, importado sin espacios, sin +56)
    fm = [CT.phone_fmt(x) for x in ("+56977778888", "+56 9 7777 8888", "977778888", "+56 9 7777-8888")]
    if set(fm) != {"+56 9 7777 8888"}:
        errs.append(f"formato de números: {fm}")
    out.append(("importar contactos del teléfono: uno por uno, sin repetidos ni saltados", errs))
    # uso real: «Llana a pipe» -> pregunta -> «Por teléfono» se tomaba como ruido
    errs = []
    jf = H.Atlas()
    jf.ready, jf.refresh_inbox, jf.pc_raw, jf.gmail_raw = True, (lambda: None), Fake("pc"), Fake("gmail")
    jf.chat("Llama a Tipo")
    jf.pending = None
    r = jf.chat("Por teléfono")
    if not (jf.pending and "Sebastián Lagos" in str(r.get("reply"))):
        errs.append(f"«Por teléfono» tras «llama a Tipo» dio {r.get('reply')!r}")
    jf.pending = None
    out.append(("«por teléfono» responde a la llamada anterior", errs))
    # Ninguna regla calza: el modelo reescribe la frase como orden directa y la toma la regla (con su confirmación)
    errs = []
    H.rewrite_order = lambda t, h=None, m="": "envía Hola por WhatsApp a Tipo"
    from openjarvis.core.types import Message, Role
    # lo que «eso que te dije» recuerda tiene que estar en la conversación: la reescritura no puede inventar el «Hola»
    jf.history.append(Message(role=Role.USER, content="Quiero mandarle un Hola a Tipo"))
    r = jf.chat("eso que te dije del Tipo, lo del WhatsApp")
    if not (jf.pending and str(r.get("reply", "")).startswith("Preparado") and "Hola" in jf.pending["summary"]):
        errs.append(f"reescrita: {r.get('reply')!r} pendiente={jf.pending}")
    jf.pending = None
    # uso real 17-11: «Tenías que dejar de esperar el otro, no ese» -> «recuérdame en una hora llamar al dentista»:
    # la reescritura copió el ejemplo de sus instrucciones y creó un recordatorio que nadie pidió
    import atlas_recordatorios as RR
    antes = len(RR.load())
    H.rewrite_order = lambda t, h=None, m="": "recuérdame en una hora llamar al dentista"
    for frase in ("Tenías que dejar de esperar el otro, no ese", "oye y lo de mañana que te conté"):
        r = jf.rewrite_and_route(frase)  # None = no usa la reescritura (sigue el modelo, que no crea nada solo)
        if r is not None or len(RR.load()) != antes:
            errs.append(f"«{frase}» se reescribió como orden inventada: {r!r}")
    H.rewrite_order = lambda t, h=None, m="": ""
    # uso real 17:25: «¿Tengo algún correo en Empresa?» fue al modelo y respondió «Verifico su bandeja…» sin revisar nada
    jf.gmail_raw.calls.clear()
    route, routed, _ = jf._route("¿Tengo algún correo en la chile?")
    last = jf.gmail_raw.calls[-1] if jf.gmail_raw.calls else {}
    if route != "correo" or last.get("action") != "unread" or last.get("account") != "prof@uni.example":
        errs.append(f"«¿tengo algún correo en la chile?» -> {route} {last}")
    if jf._route("¿tengo correos de Camila?")[0] == "correo" and (jf.gmail_raw.calls[-1].get("action") == "unread"):
        errs.append("«correos de Camila» es una búsqueda, no los sin leer")
    if not H.claims_action("Verifico su bandeja de trabajo, señor."):
        errs.append("«Verifico su bandeja» sin herramienta no se descarta")
    out.append(("frase desordenada: reescrita por el modelo y tomada por la regla, con confirmación", errs))
    if not H.claims_action("Señor, conecté sus cursos para que pueda ver las notas nuevas."):  # uso real: era falso
        out.append(("respuesta del modelo: «conecté…» sin herramienta se descarta", ["no la detecta"]))
    else:
        out.append(("respuesta del modelo: «conecté…» sin herramienta se descarta", []))
    # Lo de varios días (uso real: la hackatón del viernes 20:00 al domingo 23:59) sale en cada día que cubre
    from datetime import datetime as _dt
    errs = []
    hack = {"summary": "Hacatón", "start": _dt(2026, 11, 20, 20), "end": _dt(2026, 11, 22, 23, 59), "allday": False,
            "when": _dt(2026, 11, 20, 20), "calendar": "Google"}
    segs = A7._split_days(hack, _dt(2026, 11, 16), _dt(2026, 11, 23))
    got = [(s_["when"].day, s_["allday"], s_["tramo"]) for s_ in segs]
    if got != [(20, False, "inicio"), (21, True, "todo"), (22, True, "todo")]:
        errs.append(f"trozos: {got}")
    sab = A7._split_days(hack, _dt(2026, 11, 21), _dt(2026, 11, 22))
    if len(sab) != 1 or A7.say_event(sab[0], with_day=False) != "Hacatón todo el día":
        errs.append(f"sábado: {[A7.say_event(x, with_day=False) for x in sab]}")
    if "hasta el domingo 22" not in A7.say_event(segs[0], with_day=False):
        errs.append(f"viernes: {A7.say_event(segs[0], with_day=False)}")
    corto = {**hack, "end": _dt(2026, 11, 20, 23)}
    if len(A7._split_days(corto, _dt(2026, 11, 16), _dt(2026, 11, 23))) != 1:
        errs.append("un evento de 3 horas no se reparte")
    r = A7.parse_range("qué tengo el domingo 22", _dt(2026, 11, 15, 1, 40))
    if not r or r[0].day != 22:
        errs.append(f"«el domingo 22» un domingo 15: {r}")
    out.append(("calendario: lo de varios días sale en cada día; «el domingo 22» es ese día", errs))
    # Uso real: «¿Cómo está mi agenda la semana del 27 de noviembre?» respondía la próxima semana (16–22)
    errs = []
    hoy = _dt(2026, 11, 15, 1, 40)
    for frase, desde, hasta in [("¿Cómo está mi agenda la semana del 27 de noviembre?", 23, 30),
                                ("qué tengo la semana del 27", 23, 30),
                                ("qué tengo del 23 al 29 de noviembre", 23, 30),
                                ("qué tengo el 27 de noviembre", 27, 28),
                                ("qué tengo el 22", 22, 23)]:
        r = A7.parse_range(frase, hoy)
        if not r or (r[0].day, r[1].day) != (desde, hasta):
            errs.append(f"{frase}: {r}")
    r = A7.parse_range("qué tengo entre las 10 y las 12 mañana", hoy)
    if not r or r[0].day != 16:
        errs.append(f"«las 10» no es una fecha: {r}")
    if A7.spoken_name("En Google Calendar Entrevista Natalia Ibáñez") != "Entrevista Natalia Ibáñez":
        errs.append("«En Google Calendar» al hablar")
    if A7.spoken_name("Almuerzo con mi padre") != "Almuerzo con su padre":
        errs.append("«mi padre» al hablar")
    out.append(("agenda: «la semana del 27 de noviembre», «del 23 al 29», «el 27»; «su padre» al hablar", errs))
    # La app de fondos real: su página .html y otras formas de decirlo ("mis fondos")
    pag = tmp / "mis_fondos.html"
    pag.write_text("<html></html>", encoding="utf-8")
    (tmp / "accesos.json").write_text(json.dumps({"accesos": [{"nombre": "Fortuna", "dice": ["fortuna", "mis fondos"], "ruta": str(pag)}]}), encoding="utf-8")
    lanzados.clear()
    j3 = nuevo(H)
    r1, res1, _ = j3.route("Fortuna")
    r2, res2, _ = j3.route("abre mis fondos")
    errs = [] if r1 == r2 == "acceso" and lanzados == [str(pag), str(pag)] and "Abrí" in res1["reply"] else [f"{r1}/{r2} lanzó={lanzados} {res1}"]
    out.append(("«Fortuna» y «mis fondos» abren la página de fondos", errs))
    # «Actualiza Fortuna»: pide confirmación, corre el actualizador en segundo plano y avisa al terminar
    (tmp / "actualizar_fondos.py").write_text("", encoding="utf-8")
    (tmp / "accesos.json").write_text(json.dumps({"accesos": [{"nombre": "Fortuna", "dice": ["fortuna", "mis fondos"], "ruta": str(pag),
                                                               "actualizar": ["actualizar_fondos.py", "--no-abrir"]}]}), encoding="utf-8")
    corridas = []

    class _Proc:
        def __init__(self, rc):
            self.rc = rc

        def wait(self, timeout=None):
            return self.rc

    def _fake_update(cmd, cwd, log_path, rc=0):
        corridas.append((cmd, cwd))
        Path(log_path).write_text("Descargando Bci MACH... ok, último dato 14/11/2026\nDescargando Scotia... ERROR: timeout\n"
                                  if rc == 0 else "No se pudo descargar ningún fondo. Revisa tu conexión a internet.\n", encoding="utf-8")
        return _Proc(rc)

    viejo_upd = H.run_update
    H.run_update = _fake_update
    try:
        j6 = nuevo(H)
        j6._announce = lambda *a, **k: None
        errs = []
        r, res, _ = j6.route("Actualiza Fortuna")
        if r != "acceso" or not j6.pending or corridas:
            errs.append(f"debía pedir confirmación antes de correr nada: {r} {res} {corridas}")
        r2, _, _ = j6.route("actualiza mis fondos")
        if r2 != "acceso" or not j6.pending:
            errs.append(f"«actualiza mis fondos» no lo entendió: {r2}")
        fin = j6.confirm(True)
        if corridas != [(["actualizar_fondos.py", "--no-abrir"], str(tmp))] or "le aviso" not in fin["reply"]:
            errs.append(f"al confirmar debía correr el actualizador: {corridas} {fin}")
        for _ in range(30):
            if j6.alerts:
                break
            time.sleep(0.05)
        aviso = j6.alerts[-1]["texto"] if j6.alerts else ""
        if not re.search(r"Fortuna quedó actualizada.*1 fondos al día.*1 no se pudieron", aviso):
            errs.append(f"aviso al terminar: {aviso!r}")
        malo = j6._watch_update("Fortuna", _fake_update(["x"], str(tmp), str(tmp / "malo.log"), rc=1), str(tmp / "malo.log"))
        if "No pude actualizar Fortuna" not in malo or "conexión" not in malo:
            errs.append(f"si falla debe decirlo: {malo!r}")
        if j6.route("qué es actualizar")[0] == "acceso":
            errs.append("«qué es actualizar» no es actualizar Fortuna")
        # Uso real 16-11-2026: el botón Actualizar de Fortuna dentro de Atlas decía «Aquí no se puede actualizar»
        H._ACT_WEB.clear()
        corridas.clear()
        e1 = H.acceso_web_update("fortuna", "actualizar", forzar=True)
        for _ in range(40):
            if not H.acceso_web_update("fortuna", "estado")["corriendo"]:
                break
            time.sleep(0.05)
        e2 = H.acceso_web_update("fortuna", "estado")
        if (e1 or {}).get("accion") != "iniciado" or len(corridas) != 1 or e2.get("ok") is not True:
            errs.append(f"botón Actualizar dentro de Atlas: {e1} {e2} {corridas}")
        if H.acceso_web_update("fortuna", "actualizar")["accion"] != "reciente" or len(corridas) != 1:
            errs.append("al abrir la página recién actualizada no debía volver a bajar")
        if H.acceso_web_update("nadie", "actualizar") is not None:
            errs.append("un acceso que no existe no se actualiza")
    finally:
        H.run_update = viejo_upd
    out.append(("«actualiza Fortuna» pide confirmación, corre en segundo plano y avisa", errs))
    # Pedido 18-11-2026: el botón Actualizar de Hermes y los avisos del banco comparten candado (nunca dos a la vez)
    errs = []
    _cb = tmp / "avisos_cb"
    _cb.mkdir(exist_ok=True)
    (_cb / "avisos_banco.txt").write_text("x", encoding="utf-8")
    _scr = tmp / "actualizar_apolo_falso.py"
    _scr.write_text("", encoding="utf-8")
    _vistos, _run0 = [], H.subprocess.run

    def _run_falso(cmd, **k):
        _vistos.append(H._ACT_WEB.get("hermes", {}).get("corriendo"))
        return types.SimpleNamespace(returncode=0, stdout="0 compras nuevas", stderr="")
    H.subprocess.run = _run_falso
    try:
        H._ACT_WEB.clear()
        if not H.hermes_ocupar() or H.hermes_ocupar():
            errs.append("el candado de Hermes debía tomarse una sola vez")
        v = H.avisos_banco_turno(_cb, _scr, None)      # botón corriendo: se salta el turno, sin marcar visto
        if v is not None or _vistos:
            errs.append(f"con Hermes actualizándose, los avisos debían esperar: {v} {_vistos}")
        H.hermes_soltar()
        v = H.avisos_banco_turno(_cb, _scr, None)
        if not v or _vistos != [True] or H._ACT_WEB["hermes"]["corriendo"]:
            errs.append(f"los avisos debían tomar y soltar el candado de Hermes: {v} {_vistos} {H._ACT_WEB.get('hermes')}")
        if H.avisos_banco_turno(_cb, _scr, v) != v or len(_vistos) != 1:
            errs.append("el mismo archivo no se vuelve a sumar")
        _src = (HERE / "hud_server.py").read_text(encoding="utf-8")
        if 'acceso_slug(x["nombre"]) == slug' not in _src or H.acceso_slug("Hermes") != "hermes":
            errs.append("el botón (/acceso/hermes/actualizar) debe usar el mismo _ACT_WEB['hermes']")
    finally:
        H.subprocess.run = _run0
        H._ACT_WEB.clear()
    _corr0, _ru0 = [], H.run_update
    H.run_update = lambda *a_, **k_: _corr0.append(a_) or types.SimpleNamespace(wait=lambda timeout=None: 0)
    try:
        H._ACT_WEB.clear()
        H.hermes_ocupar()   # los avisos del banco están corriendo
        _jv = nuevo(H)
        _rv = H._AccesoUpdateTool(_jv).execute(nombre="Hermes", cmd=["actualizar_apolo.py"], cwd=str(tmp))
        if _corr0 or "Ya se está actualizando" not in _rv.content:
            errs.append(f"«actualiza Hermes» con los avisos corriendo no debía lanzar otra: {_corr0} {_rv.content}")
        H.hermes_soltar()
        if H.hermes_ocupar() is not True:
            errs.append("al soltarse, el candado debe quedar libre")
    finally:
        H.run_update = _ru0
        H._ACT_WEB.clear()
    out.append(("Hermes: botón Actualizar y avisos del banco comparten candado", errs))
    # Pedido 18-11-2026: «Contraseña de PDF del banco» en Instalación › Hermes. Prueba con una entrada de PRUEBA en un
    # almacén simulado: nunca se toca Atlas-Hermes-PDF ni el Administrador de credenciales real.
    import threading as _thc
    import urllib.error as _ue
    import urllib.request as _ur
    from http.server import ThreadingHTTPServer as _THS

    from openjarvis.security import atlas_secretos as _SEC
    errs = []
    _VAL = "Pr0ba-" + "zq7Kx91"   # valor de prueba
    _logs, _log0, _sec0, _nom0 = [], H.log, _SEC._backend_prueba, H.CLAVE_PDF_NOMBRE
    _SEC._backend_prueba, H.CLAVE_PDF_NOMBRE = {}, "Atlas-Prueba-ClavePDF"
    H.log = lambda m, *a_, **k_: _logs.append(str(m))
    _srv = _THS(("127.0.0.1", 0), H.Handler)
    _thc.Thread(target=_srv.serve_forever, daemon=True).start()
    _base = f"http://127.0.0.1:{_srv.server_address[1]}"

    def _pide(metodo, cuerpo=None, token=True, origen="mismo"):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Atlas-Token"] = H.TOKEN
        if origen:
            h["Origin"] = _base if origen == "mismo" else origen
        rq = _ur.Request(_base + "/api/credencial/hermes-pdf", method=metodo, headers=h,
                         data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
        try:
            with _ur.urlopen(rq, timeout=5) as r_:
                return r_.status, r_.read().decode("utf-8")
        except _ue.HTTPError as e_:
            return e_.code, e_.read().decode("utf-8")
    try:
        if _pide("GET", origen=None) != (200, '{"guardada": false}'):
            errs.append(f"GET sin clave: {_pide('GET', origen=None)}")
        if _pide("GET", token=False, origen=None)[0] != 403:
            errs.append("GET sin token debe rechazarse")
        c, b = _pide("POST", {"accion": "guardar", "valor": _VAL})
        if c != 200 or json.loads(b) != {"ok": True, "guardada": True} or _SEC._backend_prueba.get("Atlas-Prueba-ClavePDF") != _VAL:
            errs.append(f"guardar: {c} {b} {list(_SEC._backend_prueba)}")
        c, b = _pide("GET", origen=None)
        if (c, b) != (200, '{"guardada": true}') or _VAL in b:
            errs.append(f"GET debe decir solo guardada: {c} {b}")
        antes = dict(_SEC._backend_prueba)
        for nombre_, kw in (("origen ajeno", {"origen": "http://evil.example"}), ("otro puerto", {"origen": "http://127.0.0.1:1"}),
                            ("sin Origin", {"origen": None}), ("sin token", {"token": False})):
            c, b = _pide("POST", {"accion": "guardar", "valor": "otra"}, **kw)
            if c != 403:
                errs.append(f"POST con {nombre_} debía rechazarse: {c} {b}")
        c, _b = _pide("GET", origen="http://evil.example")
        if c != 403 or _SEC._backend_prueba != antes:
            errs.append(f"un origen ajeno no debe leer ni cambiar nada: {c}")
        if _pide("POST", {"accion": "guardar", "valor": ""})[0] != 400:
            errs.append("una contraseña vacía no se guarda")
        c, b = _pide("POST", {"accion": "borrar"})
        if c != 200 or json.loads(b).get("guardada") is not False or "Atlas-Prueba-ClavePDF" in _SEC._backend_prueba:
            errs.append(f"borrar: {c} {b}")
        if any(k_.startswith(("Atlas-Hermes", "Jarvis-Hermes", "Atlas-Apolo")) for k_ in _SEC._backend_prueba) or \
                any("Hermes-PDF" in k_ for k_ in antes):
            errs.append("la prueba no debe tocar Atlas-Hermes-PDF")
        if any(_VAL in m for m in _logs):
            errs.append("la contraseña quedó en el log")
        for f_ in list(tmp.rglob("*")) + [x for x in HERE.glob("*.log")]:
            try:
                if f_.is_file() and f_.stat().st_size < 20_000_000 and _VAL.encode() in f_.read_bytes():
                    errs.append(f"la contraseña quedó en un archivo: {f_.name}")
            except OSError:
                pass
    finally:
        _srv.shutdown()
        _srv.server_close()
        H.log, _SEC._backend_prueba, H.CLAVE_PDF_NOMBRE = _log0, _sec0, _nom0
    _hc = (HERE / "hud.html").read_text(encoding="utf-8")
    _fc = _hc.split("function fpClavePdf()", 1)[-1].split("\nfunction ", 1)[0]
    for frag in ('inp.type = "password"', 'setAttribute("autocomplete", "off")', 'let v = inp.value; inp.value = "";',
                 '"GUARDADA ✓"', '"NO GUARDADA"', '"REEMPLAZAR"', '"¿BORRAR? PRESIONE OTRA VEZ"', "if (inst.clave_pdf) box.appendChild(fpClavePdf());", "function ajGuiaInst(g)", "s.appendChild(ajGuiaInst(g));"):
        if frag not in _hc:
            errs.append(f"hud.html sin {frag}")
    if re.search(r"type\s*=\s*[\"']text|localStorage|sessionStorage|MOSTRAR|console\.log", _fc):
        errs.append("el control no debe mostrar la contraseña ni guardarla en el navegador")
    _sv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    _cl = _sv.split("def clave_pdf_guardada", 1)[-1].split("def hermes_ocupar", 1)[0]
    if "SEC.leer(" in _cl or "_leer(" in _cl:
        errs.append("el servidor no debe leer la contraseña guardada (solo si existe)")
    out.append(("Contraseña de PDF del banco: se guarda sin mostrarse, GET solo dice si existe, rechaza orígenes ajenos", errs))
    # Pedido 16-11-2026: Fortuna y Hermes se consultan y actualizan sin confirmación (solo bajan datos, no cambian nada suyo)
    (tmp / "accesos.json").write_text(json.dumps({"accesos": [{"nombre": "Fortuna", "dice": ["fortuna", "mis fondos"], "ruta": str(pag),
                                                               "actualizar": ["actualizar_fondos.py", "--no-abrir"],
                                                               "actualizar_sin_confirmar": True}]}), encoding="utf-8")
    import atlas_fortuna as _IS
    _IS.DATOS = tmp / "fondos_cmf.json"
    _ini = (datetime.now().date() - timedelta(days=400)).isoformat()
    _IS.DATOS.write_text(json.dumps({"funds": [
        {"name": "MACH Moderado", "start": _ini, "values": [100 + i * 0.05 for i in range(400)]},
        {"name": "Scotia Acciones USA", "start": _ini, "values": [200 - i * 0.1 for i in range(400)]},
        {"name": "Scotia Liquidez", "start": _ini, "values": [100.0] * 400},
        {"name": "Scotia Liquidez (historia desde 2011)", "start": _ini, "values": [1.0] * 400}]}), encoding="utf-8")
    H.run_update = _fake_update
    try:
        H._ACT_WEB.clear()
        corridas.clear()
        j7 = nuevo(H)
        j7._announce = lambda *a, **k: None
        errs = []
        r, res, _ = j7.route("Actualiza Fortuna")
        if r != "acceso" or j7.pending or len(corridas) != 1 or "le aviso" not in res["reply"]:
            errs.append(f"«actualiza Fortuna» debía correr al tiro, sin confirmación: {r} {res} {corridas} {j7.pending}")
        r, res, _ = j7.route("¿Cómo van mis fondos?")
        if r != "fortuna" or "MACH Moderado" not in res["reply"] or "Bajó Scotia Acciones USA" not in res["reply"]:
            errs.append(f"«cómo van mis fondos»: {r} {res}")
        r, res, _ = j7.route("cuánto ha rentado MACH Moderado este año")
        if r != "fortuna" or not re.search(r"MACH Moderado subió \d", res["reply"]):
            errs.append(f"rentabilidad de un fondo: {r} {res}")
        r, res, _ = j7.route("¿cuánto bajó acciones usa en el último mes?")
        if r != "fortuna" or "Scotia Acciones USA bajó" not in res["reply"]:
            errs.append(f"«cuánto bajó acciones usa»: {r} {res}")
        if j7.route("abre mis fondos")[0] != "acceso" or j7.route("cuánto gasté este mes")[0] == "fortuna":
            errs.append("«abre mis fondos» abre la página y «cuánto gasté» es de Hermes")
    finally:
        H.run_update = viejo_upd
    out.append(("Fortuna: consultas de fondos y «actualiza Fortuna» sin confirmación", errs))
    # «Otros fondos» (18-11-2026): fondos de otras administradoras solo seguidos; no suman a lo invertido
    errs = []
    _base = json.loads(_IS.DATOS.read_text(encoding="utf-8"))["funds"]
    _otros = [("Fintual Risky Norris", "Fintual", "agresivo", 9.0), ("Santander Money Market", "Santander", "conservador", 0.01),
              ("BancoEstado Acciones Nacionales", "BancoEstado", "agresivo", 0.3), ("LarrainVial Acciones Nacionales", "LarrainVial", "agresivo", -0.2)]
    _IS.DATOS.write_text(json.dumps({"funds": _base + [
        {"name": n, "adm": a, "perfil": p, "otro": True, "start": _ini, "values": [1000 + i * d for i in range(400)]}
        for n, a, p, d in _otros]}), encoding="utf-8")
    j8 = nuevo(H)
    r, res, _ = j8.route("¿Cómo van mis fondos?")
    if r != "fortuna" or any(n in res["reply"] for n, *_ in _otros) or "MACH Moderado" not in res["reply"]:
        errs.append(f"«cómo van mis fondos» no debe sumar los otros fondos: {res}")
    r, res, _ = j8.route("¿cómo van los otros fondos?")
    if r != "fortuna" or "Fintual Risky Norris" not in res["reply"] or "MACH" in res["reply"]:
        errs.append(f"«cómo van los otros fondos»: {res}")
    r, res, _ = j8.route("cuánto ha rentado Risky Norris este año")
    if r != "fortuna" or "Fintual Risky Norris subió" not in res["reply"]:
        errs.append(f"un otro fondo por nombre: {res}")
    r, res, _ = j8.route("¿cómo van los fondos de Santander?")
    if r != "fortuna" or "Santander Money Market" not in res["reply"] or "Fintual" in res["reply"]:
        errs.append(f"por administradora: {res}")
    r, res, _ = j8.route("¿cuál es el valor cuota de BancoEstado acciones nacionales?")
    if r != "fortuna" or "BancoEstado Acciones Nacionales" not in res["reply"] or "LarrainVial" in res["reply"]:
        errs.append(f"valor cuota con administradora: {res}")
    # la página: el total sale solo de «Mis inversiones» (fm-mine) y «Todos» no mezcla los seguidos
    _fm = Path(__file__).resolve().parent.parent / "apps" / "fortuna"
    if (_fm / "mis_fondos.html").exists():
        pg = (_fm / "mis_fondos.html").read_text(encoding="utf-8")
        tot = pg[pg.find("function renderTotal()"):pg.find("function spark(")]
        if "const xs=mine.map(h=>({h,x:holding(h)}))" not in tot or "funds" in tot:
            errs.append("el total de la página debe salir solo de las inversiones registradas")
        if ("fl==='all' ? !f.otro" not in pg or 'data-f="Otros"' not in pg or 'id="fbanco"' not in pg or 'data-f="MACH"' in pg
                or "funds.filter(f=>held.has(f.key)).map(f=>f.bank)" not in pg or "<optgroup" in pg):
            errs.append("la página debe tener «Míos», «Todos» sin los seguidos, «Otros» y el desplegable con los bancos de sus fondos (sin MACH/Scotia fijos)")
        d = json.loads((_fm / "fondos_cmf.json").read_text(encoding="utf-8"))["funds"]
        if any(f.get("otro") and not (f.get("adm") and f.get("perfil")) for f in d):
            errs.append("cada otro fondo debe traer administradora y perfil")
    out.append(("«Otros fondos» seguidos: se reconocen por nombre o administradora y no suman a lo invertido", errs))
    # Avisos del banco (18-11-2026): el hilo corre actualizar_apolo.py --solo-avisos, que reescribe el movimientos.json
    # real; con ATLAS_PRUEBAS=1 no se debe lanzar nunca
    errs = []
    import inspect as _insp
    src_serve = _insp.getsource(H._serve)
    lanzan = [ln for ln in src_serve.splitlines() if "target=avisos_banco_loop" in ln]
    i_guard = src_serve.find("if not en_pruebas():")
    if len(lanzan) != 1 or i_guard < 0 or not (i_guard < src_serve.find("target=avisos_banco_loop") < i_guard + 200):
        errs.append("avisos_banco_loop debe lanzarse solo dentro de «if not en_pruebas():»")
    src_todo = Path(H.__file__).read_text(encoding="utf-8")
    if src_todo.count("target=avisos_banco_loop") != 1 or not H.en_pruebas():
        errs.append("avisos_banco_loop no debe lanzarse en otro lugar, y las pruebas corren con ATLAS_PRUEBAS=1")
    out.append(("los avisos del banco no se leen ni se escriben durante las pruebas", errs))
    # MacroDroid no agrega salto de línea al final: dos avisos pegados en una línea deben salir como 2 registros.
    # Solo con una carpeta temporal (AVISOS_BANCO_DIR), nunca la real.
    errs = []
    import os as _os
    _apolo = Path(_os.path.expandvars(r"%USERPROFILE%\Downloads\Apolo\actualizar_apolo.py"))
    if _apolo.exists():
        import importlib.util as _ilu
        _dav = tmp / "avisos_prueba"
        _dav.mkdir(exist_ok=True)
        (_dav / "avisos_banco.txt").write_text(
            "@@|2026-11-18 1:05|Banco|Compra aprobada|Compra por $1.000 en TIENDA UNO."
            "@@|2026-11-18 1:07|Banco|Compra aprobada|Compra por $2.000 en TIENDA DOS.", encoding="utf-8")
        _viejo_env = _os.environ.get("AVISOS_BANCO_DIR")
        _os.environ["AVISOS_BANCO_DIR"] = str(_dav)
        try:
            _sp = _ilu.spec_from_file_location("apolo_prueba_avisos", _apolo)
            _AP = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_AP)
            if Path(_AP.AVISOS_DIR) != _dav:
                errs.append(f"AVISOS_BANCO_DIR no se respetó: {_AP.AVISOS_DIR}")
            else:
                regs = _AP.leer_avisos(_dav)
                if len(regs) != 2 or not regs[0]["texto"].endswith("TIENDA UNO.") or not regs[1]["texto"].endswith("TIENDA DOS."):
                    errs.append(f"dos avisos pegados debían dar 2 registros: {len(regs)}")
        finally:
            if _viejo_env is None:
                _os.environ.pop("AVISOS_BANCO_DIR", None)
            else:
                _os.environ["AVISOS_BANCO_DIR"] = _viejo_env
    out.append(("avisos del banco pegados sin salto de línea se leen como registros separados", errs))
    # Avisos de la app MACH (18-11-2026): banco MACH y sin marcar Visa; los de Scotiabank con «crédito» van a la Visa
    errs = []
    if _apolo.exists():
        _dmach = tmp / "avisos_mach"
        _dmach.mkdir(exist_ok=True)
        (_dmach / "avisos_banco.txt").write_text(
            "@@|2026-11-18 2:05|MACH|Compra aprobada|Compraste $3.000 en TIENDA TRES con tu tarjeta de crédito MACH\n"
            "@@|2026-11-18 2:07|Scotiabank|Compra aprobada|Compra por $4.000 en TIENDA CUATRO con tu tarjeta de crédito\n",
            encoding="utf-8")
        _viejo_env = _os.environ.get("AVISOS_BANCO_DIR")
        _os.environ["AVISOS_BANCO_DIR"] = str(_dmach)
        try:
            _sp = _ilu.spec_from_file_location("apolo_prueba_mach", _apolo)
            _AP = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_AP)
            movs_av = [_AP.aviso_a_mov(r) for r in _AP.leer_avisos(_dmach)]
            if len(movs_av) != 2 or None in movs_av:
                errs.append(f"debían salir 2 compras: {movs_av}")
            else:
                if movs_av[0]["banco"] != "MACH" or movs_av[0].get("cuenta") == "Visa":
                    errs.append(f"aviso de MACH: {movs_av[0].get('banco')} {movs_av[0].get('cuenta')}")
                if movs_av[1]["banco"] != "Scotiabank" or movs_av[1].get("cuenta") != "Visa":
                    errs.append(f"aviso de Scotiabank con crédito: {movs_av[1].get('banco')} {movs_av[1].get('cuenta')}")
            # «+ Agregar banco» (18-11-2026): un banco nuevo entra con el nombre de su app
            _bn = [_AP.banco_de_app(x) for x in ("MACH", "Scotiabank", "", "BancoEstado")]
            if _bn != ["MACH", "Scotiabank", "Scotiabank", "BancoEstado"]:
                errs.append(f"banco según la app del aviso: {_bn}")
            # banco sin lector propio (18-11-2026): modelo local (aquí uno falso) + patrones; lo dudoso queda «revisar»;
            # muestras sin montos ni nombres; MACH y Scotiabank no pasan por el modelo
            _AP.CACHE_MODELO = tmp / "avisos_modelo_prueba.json"
            _AP.MUESTRAS_DIR = tmp / "muestras_prueba"
            _llamadas = []
            def _falso(r):
                _llamadas.append(r["texto"])
                if "Recibiste" in r["texto"]:
                    return {"es_gasto": False, "monto": 50000, "comercio": "", "tipo": "compra"}
                if "LIDER" in r["texto"]:
                    return {"es_gasto": True, "monto": 15490, "comercio": "SUPERMERCADO LIDER", "tipo": "compra"}
                return {"es_gasto": True, "monto": 9990, "comercio": "", "tipo": "compra"}   # monto distinto: dudoso
            _orig = _AP._modelo_lee
            _AP._modelo_lee = _falso
            try:
                _dt = __import__("datetime").datetime(2026, 11, 18, 10, 0)
                _r = lambda t: {"cuando": _dt, "app": "BancoEstado", "titulo": "Aviso", "texto": t}
                g1 = _AP.aviso_a_mov(_r("Se realizó una compra por $15.490 en SUPERMERCADO LIDER con tu CuentaRUT"))
                g2 = _AP.aviso_a_mov(_r("Recibiste $50.000 de María López"))
                g3 = _AP.aviso_a_mov(_r("Pagaste $9.900 en Comercio raro"))
                g1b = _AP.aviso_a_mov(_r("Se realizó una compra por $15.490 en SUPERMERCADO LIDER con tu CuentaRUT"))
                if not g1 or g1["monto"] != -15490 or g1["banco"] != "BancoEstado" or g1.get("revisar"):
                    errs.append(f"banco nuevo, compra clara: {g1}")
                if g2 is not None:
                    errs.append(f"banco nuevo, abono no es gasto: {g2}")
                if not g3 or not g3.get("revisar"):
                    errs.append(f"banco nuevo, monto que no calza debe quedar «revisar»: {g3}")
                if g1b != g1 or len(_llamadas) != 3:
                    errs.append(f"el modelo se consulta una vez por aviso (caché): {len(_llamadas)} llamadas")
                _AP.aviso_a_mov({"cuando": _dt, "app": "MACH", "titulo": "Compra", "texto": "Compraste $3.000 en TIENDA"})
                if len(_llamadas) != 3:
                    errs.append("MACH no debe pasar por el modelo")
                mu = (tmp / "muestras_prueba" / "bancoestado.txt").read_text(encoding="utf-8")
                if any(x in mu for x in ("15.490", "15490", "LIDER", "María", "López", "50.000")) or mu.count("\n") != 3:
                    errs.append(f"muestras sin montos ni nombres y sin repetir: {mu!r}")
            finally:
                _AP._modelo_lee = _orig
        finally:
            if _viejo_env is None:
                _os.environ.pop("AVISOS_BANCO_DIR", None)
            else:
                _os.environ["AVISOS_BANCO_DIR"] = _viejo_env
    out.append(("avisos del celular: los de MACH quedan como MACH y los de Scotiabank con crédito como Visa", errs))
    # Fondos mutuos MACH por correo (18-11-2026): aporte y rescate ya abonado como «inversion» (ni gasto ni ingreso).
    # Correo falso, carpeta temporal, leer_cartolas falso y sin escribir apolo.html; dos pasadas seguidas.
    errs = []
    if _apolo.exists():
        import email as _em, sys as _sys, types as _ty
        from email.message import EmailMessage as _EM
        from email.utils import parsedate_to_datetime as _pdt
        import atlas_hermes as _HM
        _dff = tmp / "apolo_ffmm"
        _dff.mkdir(exist_ok=True)
        (_dff / "avisos").mkdir(exist_ok=True)
        # aviso del celular por el mismo aporte: debe quedar una sola vez (gana el correo)
        (_dff / "avisos" / "avisos_banco.txt").write_text(
            "@@|2026-11-18 9:01|MACH|Transferencia|Transferiste $12.345 a Fondo Agresivo\n", encoding="utf-8")

        def _correo(n, de, asunto, fecha, cuerpo):
            m = _EM()
            m["From"], m["Subject"], m["Date"], m["Message-ID"] = de, asunto, fecha, f"<ffmm{n}@prueba>"
            m.set_content(f"<html><body><p>{cuerpo}</p></body></html>", subtype="html")
            return m.as_bytes()
        _AP_TXT = ("Origen Cuenta MACH Destino Fondo Agresivo Monto invertido 12.345 Nombre del fondo FONDO MUTUO PRUEBA "
                   "SERIE X Nombre PERSONA PRUEBA RUT 1.111.111-1 Fecha 18/11/2026 N° de operación aa11bb22cc33 Síguenos")
        _RS_TXT = ("Origen Fondo Agresivo Destino Cuenta MACHBANK Monto rescatado $54321 N° de cuotas 10.5000 Nombre del fondo "
                   "FONDO MUTUO PRUEBA SERIE X Nombre PERSONA PRUEBA RUT 1.111.111-1 Fecha de operación 13/11/26 "   # día del pedido; llega el 18
                   "N° de operación ff99ee88dd77 Bci Asset Management")
        _correos = [
            _correo(1, "MACH <contacto@mail.somosmach.com>", "¡Acabas de hacer un aporte a Fondos Mutuos!",
                    "Wed, 18 Nov 2026 09:00:00 -0300", _AP_TXT),
            _correo(2, "MACH <contacto@mail.machbank.cl>", "Buenas noticias, tu rescate se encuentra en tu cuenta MACHBANK",
                    "Wed, 18 Nov 2026 13:00:00 -0300", _RS_TXT),
            _correo(3, "MACH <contacto@mail.somosmach.com>", "¡Acabas de solicitar un rescate!",
                    "Wed, 18 Nov 2026 10:00:00 -0300", "Monto referencial $54321 Tipo TOTAL N° de operación ff99ee88dd77"),
            _correo(4, "MACH <contacto@mail.machbank.cl>", "Ya tenemos fecha del rescate de tus Fondos Mutuos MACHBANK",
                    "Wed, 18 Nov 2026 11:00:00 -0300", "Monto estimado $54321 N° de operación ff99ee88dd77"),
            _correo(5, "MACH <contacto@mail.machbank.cl>", "Lo que esperabas, tu aporte se encuentra rentando en tu objetivo",
                    "Wed, 18 Nov 2026 12:00:00 -0300", "Tu aporte ya está rentando."),
            _correo(6, "MACH <contacto@mail.somosmach.com>", "¡Acabas de hacer un aporte a Fondos Mutuos!",
                    "Tue, 20 Oct 2026 14:10:00 -0300", _AP_TXT.replace("18/11/2026", "20/10/2026")),   # antes de DESDE
            _correo(7, "MACH <contacto@mail.machbank.cl>", "Buenas noticias, tu rescate se encuentra en tu cuenta MACHBANK",
                    "Wed, 18 Nov 2026 13:05:00 -0300", _RS_TXT),   # el mismo rescate repetido: mismo N° de operación
        ]

        def _pdf_falso(lineas, clave):
            """PDF de una página con esas líneas de texto, cifrado con «clave» (solo datos inventados)."""
            from pypdf import PdfWriter
            from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
            w = PdfWriter()
            pg = w.add_blank_page(612, 792)
            fuente = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                       NameObject("/BaseFont"): NameObject("/Helvetica")})
            pg[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(fuente)})})
            cs = DecodedStreamObject()
            cs.set_data(("BT /F1 10 Tf 50 750 Td 14 TL " + " ".join(f"({x}) Tj T*" for x in lineas) + " ET").encode("latin-1"))
            pg[NameObject("/Contents")] = w._add_object(cs)
            w.encrypt("clave-de-prueba")
            buf = io.BytesIO()
            w.write(buf)
            return buf.getvalue()
        import io
        _SC_AP = ["Junto con agradecer la confianza", "COMPROBANTE DE APORTE", "Nombre Fondo Mutuo : FONDO PRUEBA ARRIESGADO",
                  "Serie : WEB", "Fecha Aporte : 18/11/2026", "Hora Aporte : 10:00:00", "Valor Cuota : 1000.0000",
                  "Numero de Cuotas : 15.0000", "Monto del Aporte : 15000.0000", "Folio : 777000111"]
        _sc = _EM()
        _sc["From"], _sc["Subject"] = "Scotiabank <productos.info@scotiabank.cl>", "Comprobante Aporte o Rescate Fondos Mutuos"
        _sc["Date"], _sc["Message-ID"] = "Wed, 18 Nov 2026 11:00:00 -0300", "<ffmm-scotia@prueba>"
        _sc.set_content("<html><body>Adjuntamos su comprobante.</body></html>", subtype="html")
        _sc.add_attachment(_pdf_falso(_SC_AP, "clave-de-prueba"), maintype="application", subtype="octet-stream",
                           filename="ComprobanteFFMM.pdf")
        _correos.append(_sc.as_bytes())

        class _ImapFalso:
            def search(self, _c, q):
                desde = datetime.strptime(re.search(r"SINCE (\S+)", q).group(1), "%d-%b-%Y").date()
                pide = [x.lower() for x in re.findall(r'"([^"]+)"', q)]
                nums = []
                for i, raw in enumerate(_correos, 1):
                    m = _em.message_from_bytes(raw)
                    hay = (str(m["From"]) + " " + str(m["Subject"])).lower()
                    if _pdt(m["Date"]).date() >= desde and all(x in hay for x in pide):
                        nums.append(str(i).encode())
                return "OK", [b" ".join(nums)]

            def fetch(self, num, _spec):
                return "OK", [(b"", _correos[int(num) - 1])]

            def logout(self):
                pass
        _lc_falso = _ty.SimpleNamespace(CORTES=[], ciclo_de_archivo=lambda a: None, leer_todo=lambda: ([], []),
                                        leer_cortes=lambda: [])
        _lc_viejo = _sys.modules.get("leer_cartolas")
        _sys.modules["leer_cartolas"] = _lc_falso
        try:
            _sp = _ilu.spec_from_file_location("apolo_prueba_ffmm", _apolo)
            _AP = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_AP)
            if any(l == "mach_ffmm" for _c, l in _AP.FUENTES if l in _AP.LECTORES_APAGADOS) or "mach_ffmm" in _AP.LECTORES_APAGADOS:
                errs.append("mach_ffmm no puede estar en LECTORES_APAGADOS")
            crit_ff = " ".join(c for c, l in _AP.FUENTES if l == "mach_ffmm").lower()
            if "aporte a fondos mutuos" not in crit_ff or "rescate se encuentra en tu cuenta" not in crit_ff \
                    or any(x in crit_ff for x in ("solicitar", "fecha del rescate", "rentando")):
                errs.append(f"fuentes de mach_ffmm: {crit_ff}")
            if "scotia_ffmm" in _AP.LECTORES_APAGADOS or "adjunto_pdf" not in _AP.LECTORES_APAGADOS \
                    or not any(l == "scotia_ffmm" and "productos.info@scotiabank.cl" in c for c, l in _AP.FUENTES):
                errs.append("scotia_ffmm debe estar en FUENTES y encendido, sin reactivar adjunto_pdf")
            _AP._clave_pdf = lambda: "clave-de-prueba"   # nunca la clave real
            # con otra clave: no crea nada y el correo no se marca visto (se reintenta)
            _r_mala = _AP.scotia_ffmm_correo(_em.message_from_bytes(_correos[-1]), "2026-11-18", clave=lambda: "otra")
            if _r_mala != (None, False):
                errs.append(f"con una clave que no abre debía dar (None, False): {_r_mala}")
            _rsc = _AP.scotia_ffmm("COMPROBANTE DE RESCATE\nNombre Fondo Mutuo : FONDO PRUEBA\nSerie : WEB\n"
                                   "Fecha Rescate : 19/11/2026\nMonto del Rescate : 2500.5000\nFolio : 123", "2026-11-19")
            if not _rsc or _rsc["monto"] != 2501 or _rsc["tipo"] != "inversion" or _rsc["fecha"] != "2026-11-19" \
                    or not _rsc["comercio"].startswith("Fondos mutuos (rescate)"):
                errs.append(f"rescate Scotiabank mal leído: {_rsc}")
            _AP.DESDE = "18-Nov-2026"
            _AP.MOV_FILE, _AP.CAT_FILE, _AP.PRES_FILE = _dff / "movimientos.json", _dff / "categorias.json", _dff / "presupuestos.json"
            _AP.CARTOLAS, _AP.AVISOS_DIR = _dff / "cartolas", _dff / "avisos"
            _AP.conectar = lambda: _ImapFalso()
            _AP.escribir_pantalla = lambda *a, **k: None   # nunca la pantalla real
            _AP.log = lambda *a: None
            # ya había una compra del ciclo y una compra MACH por correo (esa se borra con SOLO_CORREO_Y_AVISOS)
            base = [{"id": "g1", "fecha": "2026-11-18", "comercio": "Tienda", "monto": -5000, "banco": "Scotiabank",
                     "tipo": "compra", "fuente": "aviso2", "categoria": "Comida"},
                    {"id": "mc1", "fecha": "2026-11-18", "comercio": "Otra tienda", "monto": -700, "banco": "MACH",
                     "tipo": "compra", "fuente": "correo"}]
            (_dff / "movimientos.json").write_text(json.dumps({"movimientos": base, "vistos": []}), encoding="utf-8")

            def _gasto(ms):
                return sum(-m["monto"] for m in ms if m["monto"] < 0 and m.get("categoria") not in _HM.NO_GASTO
                           and m.get("id") != "mc1")
            g0 = 5000
            pasadas = []
            for _ in range(2):
                _AP.actualizar()
                pasadas.append(json.loads((_dff / "movimientos.json").read_text(encoding="utf-8"))["movimientos"])
            for k, ms in enumerate(pasadas, 1):
                sc = [m for m in ms if m.get("tipo") == "inversion" and m.get("banco") == "Scotiabank"]
                if len(sc) != 1 or sc[0]["monto"] != -15000 or sc[0]["fecha"] != "2026-11-18" \
                        or sc[0]["categoria"] != "Inversiones" or sc[0].get("operacion") != "777000111" \
                        or not sc[0]["comercio"].startswith("Fondos mutuos (inversión) · Fondo Prueba Arriesgado (serie WEB)"):
                    errs.append(f"pasada {k}: comprobante Scotiabank (PDF con clave) mal leído: {sc}")
                inv = sorted((m for m in ms if m.get("tipo") == "inversion" and m.get("banco") == "MACH"), key=lambda m: m["monto"])
                if len(inv) != 2:
                    errs.append(f"pasada {k}: debían quedar 2 de inversión (aporte y rescate): {len(inv)}")
                    continue
                ap, rs = inv
                if ap["monto"] != -12345 or ap["categoria"] != "Inversiones" or ap["banco"] != "MACH" \
                        or ap["fecha"] != "2026-11-18" or not ap["comercio"].startswith("Fondos mutuos (inversión) · ") \
                        or ap.get("operacion") != "aa11bb22cc33":
                    errs.append(f"pasada {k}: aporte mal leído: {ap}")
                if rs["monto"] != 54321 or rs["categoria"] != "Inversiones" or rs["fecha"] != "2026-11-18" \
                        or not rs["comercio"].startswith("Fondos mutuos (rescate)"):
                    errs.append(f"pasada {k}: rescate mal leído: {rs}")
                if any(m.get("fuente") == "aviso" for m in ms):
                    errs.append(f"pasada {k}: el aviso del celular del mismo aporte se contó aparte")
                if _gasto(ms) != g0:
                    errs.append(f"pasada {k}: el gasto cambió: {_gasto(ms)} en vez de {g0}")
                if any(m.get("id") == "mc1" for m in ms):
                    errs.append(f"pasada {k}: la compra MACH por correo debía borrarse (SOLO_CORREO_Y_AVISOS)")
            if len(pasadas) == 2 and sorted(m["id"] for m in pasadas[0]) != sorted(m["id"] for m in pasadas[1]):
                errs.append("la segunda pasada cambió los movimientos")
            # el lector solo: montos estimados no crean movimiento
            if _AP.mach_ffmm("Monto rescatado $1000 monto referencial", "2026-11-18") is not None:
                errs.append("un rescate con monto referencial no debe crear movimiento")
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{type(exc).__name__}: {exc}")
        finally:
            if _lc_viejo is None:
                _sys.modules.pop("leer_cartolas", None)
            else:
                _sys.modules["leer_cartolas"] = _lc_viejo
    out.append(("fondos mutuos MACH y Scotiabank (PDF con clave): aporte y rescate como Inversiones, sin duplicar ni sumar al gasto", errs))
    # Voz y apps (uso real 18-11-2026: «¿Qué es Hermes?» se transcribió «¿Qué es Eernes?» y Atlas no lo conocía)
    errs = []
    _acc_antes = (tmp / "accesos.json").read_text(encoding="utf-8")
    _pg = tmp / "app_prueba.html"
    _pg.write_text("<html></html>", encoding="utf-8")
    _acc = json.loads((HERE / "accesos.json").read_text(encoding="utf-8"))
    for a in _acc["accesos"]:
        a["ruta"] = str(_pg)
    (tmp / "accesos.json").write_text(json.dumps(_acc, ensure_ascii=False), encoding="utf-8")
    try:
        jv = nuevo(H)
        casos_voz = [
            ("qué es eernes", "apps", r"^Hermes son sus gastos", None),
            ("¿Qué es Eernes?", "apps", r"^Hermes son sus gastos", None),
            ("qué hace Fortuna", "apps", r"fondos mutuos.*CMF", None),
            ("qué es Kronos", "apps", r"^Cronos es su historia", None),
            ("abre ermes", "acceso", None, "Hermes"),
            ("abre fortuma", "acceso", None, "Fortuna"),
            ("abre kronos", "acceso", None, "Cronos"),
            ("qué apps tienes", "apps", r"Hermes.*Fortuna.*Cronos", None),
            ("¿Qué aplicaciones tienes?", "apps", r"Hermes.*Fortuna.*Cronos", None),
            ("abre apolo", "apps", r"todavía no existe", None),
            ("abre atenea", "apps", r"todavía no existe", None),
            ("apolo", "apps", r"todavía no existe", None),
            ("isis", "apps", r"ya no existe", None),
        ]
        for frase, ruta, rx, app in casos_voz:
            jv.pc_raw.calls.clear()
            r, res, _ = jv.route(frase)
            emb = (res or {}).get("embed") or {}
            if r != ruta or (rx and not re.search(rx, (res or {}).get("reply", ""))) or (app and emb.get("nombre") != app)                     or (not app and (emb or jv.pc_raw.calls)):
                errs.append(f"«{frase}»: {r} {str(res)[:140]}")
        for frase in ("por fortuna llegué", "por fortuna llegué temprano a la U", "qué es la fortuna"):
            jv.pc_raw.calls.clear()
            r, res, _ = jv.route(frase)
            if r in ("acceso", "apps") or ((res or {}).get("embed")) or jv.pc_raw.calls:
                errs.append(f"«{frase}» no debía abrir ni describir una app: {r} {str(res)[:140]}")
        if H.corregir_apps("por fortuna llegué") != "por fortuna llegué" or H.corregir_apps("le dije ermes que viniera") != "le dije ermes que viniera":
            errs.append("la corrección de nombres de apps solo va en contexto de app")
        for v in ("apolo", "isis", "Apollo"):
            for a in _acc["accesos"]:
                if H.acceso_calza(v, a):
                    errs.append(f"«{v}» abre {a['nombre']}")
        voc = jv._stt_vocab()
        if not {"Hermes", "Fortuna", "Cronos"} <= set(voc):
            errs.append("Hermes, Fortuna y Cronos deben estar en el vocabulario de la voz")
        if "Hermes:" not in H.PERSONA or "Fortuna:" not in H.PERSONA or "Cronos:" not in H.PERSONA:
            errs.append("el contexto del modelo debe describir Hermes, Fortuna y Cronos")
    finally:
        (tmp / "accesos.json").write_text(_acc_antes, encoding="utf-8")
    out.append(("voz y apps: «qué es eernes» describe Hermes, «abre ermes» la abre; «por fortuna», Apolo e Isis no abren nada", errs))
    # Diccionario del lápiz ✎ (uso real 18-11-2026: «Conecta Ucursos» se transcribió «Conecta Ursus» y Atlas buscó
    # «ursus» en el menú Inicio). El usuario eligió «solo el diccionario»: Atlas no adivina nombres parecidos.
    # Diccionario y frases en archivos temporales.
    errs = []
    import atlas_nombres as NM
    NM.DICCIONARIO, NM.FRASES = tmp / "diccionario.json", tmp / "frases.json"
    for _f in (NM.DICCIONARIO, NM.FRASES):
        _f.unlink(missing_ok=True)
    jd = nuevo(H)
    jd._announce = lambda *a, **k: None
    _abiertas = []
    jd._ucursos_login = lambda: _abiertas.append(1)

    def _pc_ultima():
        return jd.pc_raw.calls[-1] if jd.pc_raw.calls else {}
    # sin entrada en el diccionario, «conecta ursus» no adivina U-Cursos
    r, res, _ = jd.route("conecta ursus")
    time.sleep(0.05)
    if r == "notas" or _abiertas:
        errs.append(f"sin diccionario, «conecta ursus» no debía adivinar U-Cursos: {r}")
    # las variantes de las apps vienen de inicio en el diccionario (contexto «app»), visibles en el panel
    sem = {(p["escuchado"], p["correcto"], p.get("contexto")) for p in NM.palabras()}
    if ("ermes", "Hermes", "app") not in sem or ("fortuma", "Fortuna", "app") not in sem or ("kronos", "Cronos", "app") not in sem:
        errs.append(f"las variantes de Hermes, Fortuna y Cronos deben venir en el diccionario: {sorted(sem)[:5]}")
    if NM.aplicar_diccionario("le dije ermes que viniera") != "le dije ermes que viniera" \
            or NM.aplicar_diccionario("por fortuma") != "por fortuma" or NM.aplicar_diccionario("abre ermes") != "abre Hermes":
        errs.append("las variantes de las apps solo valen al nombrar la app")
    # con «ursus -> U-Cursos» guardado desde el lápiz, conecta U-Cursos; palabra completa, sin tildes ni mayúsculas
    res_u = jd.diccionario_cambiar({"op": "palabra", "escuchado": "ursus", "correcto": "U-Cursos"})
    for frase in ("conecta ursus", "Conecta Ursus.", "Conecta ÚRSUS"):
        _abiertas.clear()
        r, res, _ = jd.route(frase)
        time.sleep(0.05)
        if not res_u.get("ok") or r != "notas" or not _abiertas:
            errs.append(f"con «ursus» en el diccionario, «{frase}» debía conectar U-Cursos: {r} {str(res)[:100]}")
    for a, z in (("tengo recursos humanos", "tengo recursos humanos"), ("ursusa y osos", "ursusa y osos")):
        if NM.aplicar_diccionario(a) != z:
            errs.append(f"diccionario: «{a}» -> «{NM.aplicar_diccionario(a)}» (esperaba «{z}»)")
    jd.pc_raw.calls.clear()
    r, res, _ = jd.route("abre bloc de notas")
    if r != "pc" or _pc_ultima().get("name") != "bloc de notas":
        errs.append(f"«abre bloc de notas» debía abrir el programa: {r} {_pc_ultima()}")
    jd.pc_raw.calls.clear()
    r, res, _ = jd.route("abre zqxvbrtplk")
    if r != "pc" or _pc_ultima().get("name") != "zqxvbrtplk":
        errs.append(f"un nombre inventado debía seguir igual (y decir que no lo encontró): {r} {_pc_ultima()}")
    for frase in ("por fortuna llegué", "por fortuna llegué temprano"):
        jd.pc_raw.calls.clear()
        r, res, _ = jd.route(frase)
        if r in ("acceso", "apps", "pc", "notas") or jd.pc_raw.calls:
            errs.append(f"«{frase}» no debía abrir nada: {r}")
    res_d = jd.diccionario_cambiar({"op": "palabra", "escuchado": "blognotas", "correcto": "bloc de notas"})
    jd.pc_raw.calls.clear()
    r, res, _ = jd.route("abre blognotas")
    if not res_d.get("ok") or r != "pc" or _pc_ultima().get("name") != "bloc de notas":
        errs.append(f"la palabra corregida debía usarse la vez siguiente: {res_d.get('error')} {r} {_pc_ultima()}")
    if "bloc de notas" not in jd._stt_vocab():
        errs.append("lo corregido debe ir al vocabulario de la voz")
    # frase -> acción (solo acciones de la lista)
    if jd.diccionario_cambiar({"op": "frase", "frase": "haz magia", "accion": "borra todo"}).get("ok"):
        errs.append("una acción que no está en la lista no se puede guardar")
    vista_d = jd.diccionario_vista()
    if not any(a["accion"] == "conecta U-Cursos" for a in vista_d["acciones"]) \
            or not any(a["accion"] == "abre bloc de notas" for a in vista_d["acciones"]):
        errs.append("la lista de acciones debe traer servicios, intenciones y programas")
    res_f = jd.diccionario_cambiar({"op": "frase", "frase": "quiero escribir algo", "accion": "abre bloc de notas"})
    for frase in ("quiero escribir algo", "Quiero escribir algo."):
        jd.pc_raw.calls.clear()
        r, res, _ = jd.route(frase)
        if not res_f.get("ok") or r != "pc" or _pc_ultima().get("name") != "bloc de notas":
            errs.append(f"la frase asociada debía hacer su acción: «{frase}» {r} {_pc_ultima()}")
    # borrar en el panel la elimina
    jd.diccionario_cambiar({"op": "borrar_frase", "frase": "quiero escribir algo"})
    jd.diccionario_cambiar({"op": "borrar_palabra", "escuchado": "blognotas"})
    jd.pc_raw.calls.clear()
    r, res, _ = jd.route("quiero escribir algo")
    if r == "pc" or NM.buscar_frase("quiero escribir algo") or NM.aplicar_diccionario("abre blognotas") != "abre blognotas":
        errs.append(f"borrar debía quitar la frase y la palabra: {r}")
    # por voz no se guarda nada: se indica el lápiz
    antes_d, antes_f = NM.DICCIONARIO.read_bytes(), NM.FRASES.read_bytes()
    for frase in ("me escuchaste mal", "Atlas, te equivocaste.", "no entendiste", "eso no era", "no era eso", "corrige eso",
                  "agrégalo al diccionario", "quiero corregir", "enséñale", "eso no es lo que dije", "no dije eso",
                  "entendiste mal", "me malentendiste", "no me escuchaste bien", "Atlas, entendiste otra cosa", "no es lo que te pedí"):
        r, res, _ = jd.route(frase)
        rep = (res or {}).get("reply", "")
        if r != "corregir" or "pestaña HISTORIAL" not in rep or "✎ Corregir" not in rep or rep.count(H.PISTA_CORREGIR) != 1:
            errs.append(f"«{frase}» debía indicar HISTORIAL › ✎ Corregir: {r} {str(res)[:120]}")
    for frase in ("corrige mi tarea de redes", "no entendí la clase", "me equivoqué de hora", "esa canción está mal escrita",
                  "no dije que fuera mañana, avísame el jueves"):
        if jd.route_corregir_voz(frase) is not None:
            errs.append(f"«{frase}» no es corregir a Atlas")
    # Cuando Atlas no entiende: agrega la indicación (sin abrir nada) y no la repite en el turno siguiente
    jp = nuevo(H)
    o1 = jp._pista_corregir({"reply": "No encontré un programa llamado 'ursus', señor.", "tools": []})
    o2 = jp._pista_corregir({"reply": "No sé dónde buscar eso, señor.", "tools": []})
    o3 = jp._pista_corregir({"reply": "Listo, señor.", "tools": []})
    o4 = jp._pista_corregir({"reply": "No tengo ese dato, señor.", "tools": []})
    o5 = jp._pista_corregir({"reply": "Son las 13:00, señor.", "tools": []})
    if not o1["reply"].endswith(H.PISTA_CORTA) or H.PISTA_CORTA in o2["reply"] or H.PISTA_CORTA in o3["reply"] \
            or not o4["reply"].endswith(H.PISTA_CORTA) or H.PISTA_CORTA in o5["reply"]:
        errs.append(f"indicación al no entender: {[o['reply'][-60:] for o in (o1, o2, o3, o4, o5)]}")
    # el aviso solo cuando Atlas de verdad no entendió (18-11-2026): si una herramienta corrió y no encontró nada, no
    jn = nuevo(H)
    jn._turn_route = ("notas", "evaluaciones de canvas")
    o6 = jn._pista_corregir({"reply": "No encontré evaluaciones en Redes, señor.", "tools": ["notas"]})
    jn._turn_route = ("pc", "abre ursus")
    o7 = jn._pista_corregir({"reply": "Lo siento, señor. No encontré un programa llamado 'ursus' en el menú Inicio.", "tools": ["pc"], "no_entendio": True})
    jn._turn_route, jn._pista_dicha = ("modelo", "x"), False
    o8 = jn._pista_corregir({"reply": "No le entendí bien, señor: escuché «pee pon». ¿Me lo repite?", "tools": []})
    jn._turn_route, jn._pista_dicha = ("modelo", "x"), False
    o9 = jn._pista_corregir({"reply": "No encontré nada sobre eso, señor.", "tools": ["gmail_search"]})
    if H.PISTA_CORTA in o6["reply"] or o6.get("no_entendio") or not o7["reply"].endswith(H.PISTA_CORTA) or not o7.get("no_entendio") \
            or not o8["reply"].endswith(H.PISTA_CORTA) or not o8.get("no_entendio") or H.PISTA_CORTA in o9["reply"]:
        errs.append(f"aviso ✎ Corregir solo si no entendió: {[(o['reply'][-50:], o.get('no_entendio')) for o in (o6, o7, o8, o9)]}")
    jn.pc_raw.calls.clear()
    _r_pc = jn.route_pc("abre zqxvbrtplk") or {}
    if jn.pc_raw.calls and not _r_pc.get("no_entendio") and "No encontré" in str(_r_pc.get("reply", "")):
        errs.append("abrir un programa que no existe debe marcar no_entendio")
    if "it.no_entendio != null ? !!it.no_entendio" not in (HERE / "hud.html").read_text(encoding="utf-8"):
        errs.append("el dorado del Historial debe usar la misma señal (no_entendio)")
    if "HISTORIAL" not in H.PISTA_CORTA or "✎ Corregir" not in H.PISTA_CORTA:
        errs.append("la indicación corta debe decir HISTORIAL y ✎ Corregir")
    _hh = (HERE / "hud.html").read_text(encoding="utf-8")
    # ✎ Corregir arregla lo que el mensaje ya guardó (18-11-2026): «anota … ejercicios de programa» -> «progra»
    _rp = jn.route_pendientes("anota como pendiente revisar los ejercicios de programa") or {}
    _hc = _rp.get("hecho") or {}
    if _hc.get("tipo") != "pendiente" or not _hc.get("id"):
        errs.append(f"anotar un pendiente debe devolver «hecho» para poder arreglarlo: {_rp}")
    else:
        _v = jn.hecho_action({"tipo": "pendiente", "id": _hc["id"], "op": "ver"})
        _e = jn.hecho_action({"tipo": "pendiente", "id": _hc["id"], "op": "editar", "texto": "revisar los ejercicios de progra"})
        _v2 = jn.hecho_action({"tipo": "pendiente", "id": _hc["id"], "op": "ver"})
        _d = jn.hecho_action({"tipo": "pendiente", "id": _hc["id"], "op": "deshacer"})
        _v3 = jn.hecho_action({"tipo": "pendiente", "id": _hc["id"], "op": "ver"})
        if not (_v.get("existe") and "programa" in _v.get("texto", "") and _e.get("ok")
                and _v2.get("texto") == "Revisar los ejercicios de progra" and _d.get("deshecho") and _v3.get("existe") is False):
            errs.append(f"arreglar el pendiente ya anotado: {[_v, _e, _v2, _d, _v3]}")
    if jn.hecho_action({"tipo": "evento", "id": "x", "op": "ver"}).get("ok") is not False:
        errs.append("hecho_action debe rechazar tipos que no sabe arreglar")
    if "hecho: it.hecho" not in _hh or 'data-m="hecho"' not in _hh or "function cstHechoOferta" not in _hh:
        errs.append("el corrector debe ofrecer arreglar lo que el mensaje ya guardó")
    _ask = _hh.split("async function ask(text)", 1)[1].split("let listening", 1)[0]
    if _ask.find("refresh()") < 0 or _ask.find("refresh()") > _ask.find("await say("):
        errs.append("la lista de pendientes debe refrescarse antes de que Atlas termine de hablar")
    _rf = _hh.split("async function refresh()", 1)[1].split("showPendientes(", 1)[0]
    if 'if ($("bootSteps")) keys.forEach' not in _rf or 'if ($("bootFill"))' not in _rf:
        errs.append("refresh() no debe caerse cuando ya se quitó la pantalla de carga (si no, PENDIENTES no se actualiza)")
    if re.search(r"\.corregir\b[^\n]{0,80}(setConsolaTab|abrirCorrector|showHistory)", _hh):
        errs.append("Atlas no debe abrir el historial ni el corrector por su cuenta")
    if NM.DICCIONARIO.read_bytes() != antes_d or NM.FRASES.read_bytes() != antes_f:
        errs.append("por voz no se debe guardar nada en el diccionario")
    _html_c = (HERE / "hud.html").read_text(encoding="utf-8")
    if 'id="youFix"' in _html_c or "function showCorregir" not in _html_c or '"/api/diccionario"' not in _html_c:
        errs.append("la consola ya no lleva lápiz ✎ (está en el Historial) y el panel de corrección debe seguir")
    # Corrector «Constelación»: componente abrirCorrector(texto, idMensaje), aún sin botón; fuentes locales
    _cst = _html_c.split("async function abrirCorrector", 1)
    if len(_cst) != 2 or "window.abrirCorrector = abrirCorrector" not in _html_c or "#constel{" not in _html_c:
        errs.append("falta el componente abrirCorrector (Constelación)")
    else:
        # 18-11-2026: la primera pantalla es «¿Qué quería que hiciera Atlas?» (acciones por sectores ‹ ›, el servidor
        # propone el arreglo) y reemplaza a «Darle significado a la frase»; «Corregir una palabra» sigue abajo
        for _m in ("Corregir una palabra", "¿Qué quería que hiciera Atlas?", "/api/corrector_proponer", 'data-act="sec"', 'data-act="sig"',
                   "Lo que hizo", 'op: "palabra"', 'op: "frase"', "borrar_palabra", "borrar_frase", 'data-act="undo"', 'data-act="retry"', "cstLineas"):
            if _m not in _html_c.split("/* Corrector «Constelación»", 1)[-1]:
                errs.append(f"al corrector Constelación le falta {_m!r}")
        if re.search(r"(?:addEventListener\([^\n]*|onclick=[^\n]*)abrirCorrector", _html_c):
            errs.append("abrirCorrector no debe estar enganchado a ningún botón todavía")
    if "fonts.googleapis" in _html_c:
        errs.append("el HUD no debe cargar fuentes de Google")
    out.append(("diccionario del lápiz: sin entrada «conecta ursus» no adivina; con «ursus → U-Cursos» conecta; por voz no se guarda", errs))
    # Consola con pestañas AHORA / HISTORIAL (propuesta C, 18-11-2026; el interior es la lista de siempre)
    errs = []
    _h = (HERE / "hud.html").read_text(encoding="utf-8")
    _bar = _h.split('<section id="talk"', 1)[1].split("</section>", 1)[0]
    if 'role="tablist"' not in _bar or 'id="tabAhora"' not in _bar or 'id="tabHist"' not in _bar or 'id="histBad"' not in _bar:
        errs.append("la barra de la consola debe tener las pestañas AHORA / HISTORIAL con insignia")
    if "CONSOLA // TRANSMISIÓN" in _bar or 'id="histOpen"' in _h or '$("histOpen")' in _h:
        errs.append("no deben quedar la barra antigua ni el botón Historial antiguo")
    if re.search(r">\s*H\s*<|<kbd", _bar):
        errs.append("la barra no debe mostrar una «H» ni teclas")
    if 'id="talkHist"' not in _bar or "✎" in _bar:
        errs.append("el historial va en la consola y la consola (AHORA) no lleva lápiz")
    if "H: HISTORIAL" not in _h.split('<div id="hint"', 1)[1][:200]:
        errs.append("la línea de ayuda debe explicar «H: HISTORIAL»")
    _js = _h.split("// Consola con pestañas AHORA / HISTORIAL", 1)[-1][:6000]
    for _m in ('e.key !== "h"', "INPUT|TEXTAREA|SELECT", 'localStorage.setItem(HIST_VISTO, "1")', 'classList.add("pulse")', "try {"):
        if _m not in _js:
            errs.append(f"pestañas: falta {_m!r}")
    if "#talk.histo{height:min(550px" not in _h or "#app.histo #core{opacity:.15}" not in _h or "histPulso 2.4s" not in _h:
        errs.append("la consola debe crecer, atenuar el núcleo y pulsar suave")
    if "@media (prefers-reduced-motion:reduce){#talk,#core{transition:none}}" not in _h or "#talk .ctabs button.pulse{animation:none}" not in _h:
        errs.append("sin transiciones ni pulso con movimiento reducido")
    # Historial «Conversación» (18-11-2026): chat dentro de la pestaña; «✎ Corregir» siempre visible; abre Constelación
    _ph = _h.split("function pintarHistorial", 1)[1].split("\nfunction hcBoton", 1)[0]
    _hb = _h.split("function hcBoton", 1)[1][:1500]
    if '$("talkHist")' not in _ph or '$("vista").classList.add' in _ph or "showCorregir(" in _ph + _hb:
        errs.append("el historial es un chat dentro de la consola, sin el panel CORREGIR viejo")
    if "if (it.dijo) {" not in _ph or "if (!malo) mt.appendChild(hcBoton(it, hora, false))" not in _ph or "hcBoton(it, hora, true)" not in _ph:
        errs.append("todo mensaje del usuario lleva su botón «✎ Corregir» (dorado si Atlas no entendió)")
    if "Atlas no entendió esta frase" not in _ph or "Todavía no hay conversaciones." not in _ph:
        errs.append("faltan el aviso dorado de «no entendió» o el texto vacío")
    if not re.search(r"#talkHist \.fixbtn\.soft\{height:26px", _h) or re.search(r"\.fixbtn[^{]*\{[^}]*opacity:0", _h):
        errs.append("el botón discreto se ve siempre (26 px), nunca escondido hasta hover")
    if "#talkHist .fixbtn{height:32px" not in _h or "max-width:78%" not in _h or "font-size:17px" not in _h:
        errs.append("burbujas y botón dorado como el diseño")
    for _m in ('abrirCorrector(it.dijo, id, {', '"VOLVER AL HISTORIAL"', '"CORRECTOR · "', "body.scrollTop = y", "pintarHistorial(true)",
               'aria-label", `Corregir «${it.dijo}»`'):
        if _m not in _hb:
            errs.append(f"botón Corregir del historial: falta {_m!r}")
    for _m in ("fin(!!S.cambio)", "S.opts.volver", "S.opts.encabezado", "S.cambio = true"):
        if _m not in _h:
            errs.append(f"corrector con opciones del historial: falta {_m!r}")
    if "it.ses === r.actual && hcMalo(it)" not in _h or "(d.frases || []).find" not in _h:
        errs.append("lo corregido se marca y deja de contar en la insignia")
    import tempfile as _tf
    _hd = Path(_tf.mkdtemp())
    (_hd / "historial").mkdir()
    (_hd / "historial" / "2026-11-17_0900.jsonl").write_text(json.dumps({"dijo": "uno", "respuesta": "a", "hora": "09:00:01"}) + "\n", encoding="utf-8")
    (_hd / "historial" / "2026-11-18_1000.jsonl").write_text(json.dumps({"dijo": "dos", "respuesta": "b", "hora": "10:00:02"}) + "\nno es json\n"
                                                            + json.dumps({"dijo": "tres", "respuesta": "c"}) + "\n", encoding="utf-8")
    _hs_here = H.HERE
    try:
        H.HERE = _hd
        _rt = H.read_history_todas()
    finally:
        H.HERE = _hs_here
    if [x["dijo"] for x in _rt["items"]] != ["uno", "dos", "tres"] or _rt["items"][2]["id"] != "2026-11-18_1000#2" or _rt["items"][0]["ses"] != "2026-11-17_0900":
        errs.append(f"historial de todas las sesiones, de la más antigua a la más nueva, con id: {_rt['items']}")
    shutil.rmtree(_hd, ignore_errors=True)
    # Ajustes: «Diccionario» único (antes «Voz y apodos») y guía de las apps
    import atlas_ajustes as _AJd
    _secs = {a["seccion"] for a in _AJd.CATALOGO}
    if "Voz y apodos" in _secs or "Diccionario" not in _secs:
        errs.append(f"la sección de Ajustes debe llamarse Diccionario: {sorted(_secs)}")
    if 'const VA_SEC = "Diccionario"' not in _h or 'showCorregir("", "", "dicc", box)' not in _h or "if (!dest && !frase)" not in _h:
        errs.append("Ajustes › Diccionario debe mostrar el diccionario unificado y ser el único lugar")
    _g = _h.split("const AJ_GUIA = ", 1)[-1].split("];", 1)[0]
    for _m in ("Cronos", "Fortuna", "Hermes", "Syncthing", "a mano", "historial por día", "SI NO MUESTRA DATOS", "abre Cronos", "barra de apps"):
        if _m not in _g and _m not in _h.split("function ajGuia", 1)[-1][:3000]:
            errs.append(f"la guía debe mencionar {_m!r}")
    if re.search(r"(?i)c:\\\\users|nombreusuario|@gmail|\d{4} ?\d{4} ?\d{4}", _g):
        errs.append("la guía no debe tener datos privados ni rutas con el nombre del usuario")
    if " tú " in _g.lower() or "puedes" in _g:
        errs.append("la guía va de «usted»")
    # La guía también se ve desde Ajustes › Instalación › Apps (ahí la buscaba el usuario, 18-11-2026)
    _src_af = (HERE / "atlas_faltantes.py").read_text(encoding="utf-8").split('paso("Apps"', 1)[1][:2500]
    _faltan_af = [x for x in ("Cronos (su historia", "Fortuna (fondos mutuos)", "Hermes (gastos)",
                              '_b("VER GUÍA DE LAS APPS", "seccion", "__guia"') if x not in _src_af]
    if _faltan_af or 'const [sec, ancla] = String(b.valor).split("#"); ajSel = sec;' not in _h:
        errs.append(f"Instalación › Apps debe explicar Cronos, Fortuna y Hermes y llevar a la guía: {_faltan_af}")
    out.append(("consola con pestañas AHORA/HISTORIAL (atajo H, pulso, crece); Ajustes › Diccionario único y guía de las apps", errs))
    # Gastos por intención (uso real 18-11-2026: «quiero ver mis gastos» no llegaba a Hermes y el modelo preguntaba)
    errs = []
    import atlas_hermes as _HEi
    for frase in ("quiero ver mis gastos", "muéstrame mis compras", "en qué he gastado", "me gustaría ver mis movimientos",
                  "revisa los gastos de este mes", "¿cuánto llevo gastado?"):
        if not _HEi.es_pregunta(frase):
            errs.append(f"«{frase}» debía ir a Hermes")
    for frase in ("gastos de envío de un paquete", "cuánto cuestan los gastos de envío", "abre mis gastos"):
        if _HEi.es_pregunta(frase):
            errs.append(f"«{frase}» no es una consulta de Hermes")
    jg = nuevo(H)
    r, res, _ = jg.route("quiero ver mis gastos")
    if r != "hermes":
        errs.append(f"«quiero ver mis gastos» llegó a {r}")
    if not all(x in H.REWRITE_PROMPT for x in ("Hermes", "Fortuna", "Cronos", "¿cuánto he gastado")):
        errs.append("la reescritura del modelo debe conocer Hermes, Fortuna y Cronos")
    out.append(("gastos por intención: «quiero ver mis gastos», «muéstrame mis compras» van a Hermes; «gastos de envío» no", errs))
    # Uso real a las 00:37: "pon una alarma" -> "A las 6 horas 38 minutos." debe quedar a las 6:38 de hoy
    from datetime import datetime as _dt
    noche = _dt(2026, 11, 15, 0, 37)
    errs = []
    for resp in ("A las 6 horas 38 minutos.", "6 horas 38 minutos", "a las 6:38", "las 6 38"):
        r = R.complete({"tipo": "alarma", "texto": ""}, resp, noche)
        if not r or r["cuando"] != _dt(2026, 11, 15, 6, 38) or r["texto"]:
            errs.append(f"{resp!r} -> {r}")
    for resp in ("dos cosas más", "en 10 minutos"):
        r = R.complete({"tipo": "alarma", "texto": ""}, resp, noche)
        if resp.startswith("dos") and r:
            errs.append(f"{resp!r} no es una hora: {r}")
    p = R.parse("Puedes poner una alarma para las... para las 0.38", noche)
    if not p or p.get("op") != "create" or p["cuando"] != _dt(2026, 11, 15, 0, 38) or p["texto"]:
        errs.append(f"«para las... para las 0.38» -> {p}")
    out.append(("alarma «a las 6 horas 38 minutos» a medianoche queda a las 6:38", errs))
    r0 = R.parse("pon una alarma a las cero 38", noche)
    out.append(("«a las cero 38» es 0:38", [] if r0 and r0["cuando"] == _dt(2026, 11, 15, 0, 38) else [f"{r0}"]))
    # Borrar alarmas (uso real: «Elimina la alarma puesta.» no la encontraba)
    errs = []
    (tmp / "recordatorios.json").unlink(missing_ok=True)
    mala = R.add("alarma", "las... para las 0.38", AHORA.replace(hour=18), None)
    j7 = nuevo(H)
    r, res, _ = j7.route("Elimina la alarma puesta.")
    if j7.pending:
        j7.confirm(True)
    if r != "recordatorio" or R.load() or "Cancelé" not in (res.get("reply", "") + str(j7.actions)):
        errs.append(f"«elimina la alarma puesta» debía borrar la única alarma: {r} {res} quedan={R.load()}")
    a6 = R.add("alarma", "", AHORA.replace(hour=18), None)
    a7 = R.add("alarma", "", AHORA.replace(hour=19, minute=30), None)
    r, res, _ = j7.route("cancela la alarma de las 7 30")
    left = [i["id"] for i in R.load()]
    if left != [a6["id"]]:
        errs.append(f"«cancela la alarma de las 7 30» debía borrar solo la de 19:30: {res} quedan={left}")
    r, res, _ = j7.route("borra la alarma de las 9")
    if a6["id"] not in [i["id"] for i in R.load()] or "¿Cuál cancelo" not in res.get("reply", "") and not j7.pending:
        errs.append(f"«la de las 9» no existe: no debía borrar la de las 18: {res}")
    j7.pending = None
    v = j7.reminders_view()
    if not v or v[0].get("id") != a6["id"]:
        errs.append(f"el panel necesita el id para la ✕: {v}")
    c = j7.cancel_reminder(a6["id"])
    if not c.get("ok") or R.load() or "Cancelé alarma" not in c.get("reply", ""):
        errs.append(f"la ✕ del panel no la borró: {c}")
    if j7.cancel_reminder("nada").get("ok"):
        errs.append("borrar un id que no existe no debe decir que lo borró")
    del mala
    out.append(("borrar alarmas: «elimina la alarma puesta», por hora y con la ✕ del panel", errs))
    # Notas de U-Cursos: lee la página de notas con la sesión del usuario y avisa solo lo nuevo
    import atlas_ucursos_notas as U
    errs = []
    U.HERE = tmp
    U.forget_session()
    (tmp / "ucursos_notas.json").unlink(missing_ok=True)
    j8 = nuevo(H)
    j8._announce = lambda *a, **k: None
    r, res, _ = j8.route("¿Tengo notas nuevas?")
    if r != "notas" or "conecta U-Cursos" not in res["reply"]:
        errs.append(f"sin sesión debía pedir conectar: {r} {res}")
    abiertas = []
    j8._ucursos_login = lambda: abiertas.append(1)
    r, res, _ = j8.route("conecta U-Cursos")
    time.sleep(0.1)
    if r != "notas" or not abiertas or "no veo su clave" not in res["reply"]:
        errs.append(f"«conecta U-Cursos» debía abrir la ventana: {r} {res} {abiertas}")
    for frase in ("Conecta o cursos", "conéctate a u cursos", "inicia sesión en ucursos", "Conectó cursos",
                  "conecto u cursos", "conectar ucursos", "Conecta mis cursos"):  # así lo transcribe la voz
        if j8.route(frase)[0] != "notas":
            errs.append(f"«{frase}» debía conectar U-Cursos")
    time.sleep(0.1)
    pagina = {"v": """<table><thead><tr><th>Evaluaci&oacute;n</th><th>Fecha</th><th>Nota</th></tr></thead><tbody>
        <tr><td>Control 1</td><td>01/10</td><td>5.8</td></tr><tr><td>Control 2</td><td>01/11</td><td>-</td></tr></tbody></table>"""}
    ramo = {"path": "ingenieria/2026/2/CC3301/1", "code": "CC3301", "sec": "1", "periodo": (2026, 2), "nombre": "Redes"}
    viejo_fetch, viejos_ramos = U.fetch, U.courses
    pedidas = []
    U.fetch = lambda path: (pedidas.append(path), pagina["v"])[1]
    U.courses = lambda *a, **k: [ramo]
    try:
        U.save_session([{"name": "sid", "value": "x", "domain": ".u-cursos.cl"}, {"name": "otro", "value": "y", "domain": "google.com"}])
        guardadas = json.loads((tmp / "ucursos_sesion.json").read_text(encoding="utf-8"))["cookies"]
        if [c["name"] for c in guardadas] != ["sid"]:
            errs.append(f"solo debe guardar cookies de U-Cursos: {guardadas}")
        r, res, _ = j8.route("¿tengo notas nuevas?")
        if not res["reply"].startswith("No hay notas nuevas") or pedidas != ["ingenieria/2026/2/CC3301/1/notas/"]:
            errs.append(f"la primera revisión solo guarda lo que hay: {res} {pedidas}")
        pagina["v"] = pagina["v"].replace("<td>-</td>", "<td>6.1</td>")
        r, res, _ = j8.route("salieron notas en u-cursos?")
        if not re.search(r"Sí, señor: 1 nota nueva\. Redes: Control 2, un 6,1\.", res["reply"]):
            errs.append(f"nota nueva: {res}")
        r, res, _ = j8.route("¿tengo notas nuevas?")
        if not re.search(r"No hay notas nuevas.*Esta semana salió: Redes: Control 2, un 6,1", res["reply"]):
            errs.append(f"sin novedades debe recordar la de esta semana: {res}")
        r, res, _ = j8.route("cuáles son mis notas de redes")
        if res["reply"] != "En Redes, señor: Control 1, 5,8; Control 2, 6,1.":
            errs.append(f"notas de un ramo: {res}")
        for frase in ("toma nota de comprar pan", "lee mis notas del celular", "anota que mañana hay control"):
            if j8.route(frase)[0] == "notas":
                errs.append(f"«{frase}» no es de U-Cursos")
        # Formato real de la página …/notas/alumno (uso real: no leía la nota y salían mal los acentos)
        real = """<table><thead class="sticky"><tr><th class="string">Evaluación</th><th class="number">P1</th>
          <th class="number gris">Prom.</th></tr></thead>
          <tr class="separador sticky"><td colspan="0">Controles</td></tr><tbody>
          <tr class=""><td><h1>
            Control 1		<a class="opcion stats" href="?x"><span class="tooltip">Estadísticas</span></a></h1>
            <dl id="d1" class="detalle"><dd class="box info"><span class="ta">Revisado por Ana<br>muy bien <a href="http://x">link</a> 7.0</span></dd></dl></td>
            <td><h1><span class=""></span></h1></td><td><h1 class="strong"><span class="">6.6</span></h1><h2>mi nota fue 6.6</h2></td></tr></tbody>
          <tr class="separador sticky"><td colspan="0">Ejercicios</td></tr><tbody>
          <tr class=""><td><h1><a href="javascript:toggle('d2')">Ejercicio 1</a></h1>
            <h2><span class="tiempo_rel" data-time="1787155200"><span>19 Ago</span></span></h2></td>
            <td><h1><span class="wrong">2.6</span></h1><h2>100%</h2></td><td><h1 class="strong"><span class="wrong">2.6</span></h1></td></tr>
          <tr class=""><td><h1><a href="javascript:toggle('d3')">Códigos C1</a></h1>
            <h2><span class="tiempo_rel" data-time="1790607600"><span>28 Sep</span></span></h2></td>
            <td><h1><span>6.5</span></h1></td><td><h1 class="strong"><span class="">6.5</span></h1></td></tr>
          <tr class=""><td><h1><a href="javascript:toggle('d4')">Control 2</a></h1></td>
            <td><h1><span></span></h1></td><td><h1 class="strong"><span class=""></span></h1></td></tr></tbody></table>"""
        filas = U.parse_notas(real)
        got = [(f["categoria"], f["evaluacion"], f["nota"], f["fecha"][:7]) for f in filas]
        if got != [("Controles", "Control 1", "6,6", ""), ("Ejercicios", "Ejercicio 1", "2,6", "2026-08"),
                   ("Ejercicios", "Códigos C1", "6,5", "2026-09"), ("Ejercicios", "Control 2", "", "")]:
            errs.append(f"página real de notas: {got}")
        pagina["v"] = real
        (tmp / "ucursos_notas.json").write_text(json.dumps({"ramos": {ramo["path"]: {"Control 1 Estadísticas": "1"}}}), encoding="utf-8")
        r, res, _ = j8.route("hay notas nuevas en u cursos")
        if not res["reply"].startswith("No hay notas nuevas"):
            errs.append(f"lo guardado con el lector viejo no debe avisar todo como nuevo: {res}")
        r, res, _ = j8.route("¿Cuál ha sido la última nota que me han entregado?")
        if r != "notas" or res["reply"] != "La última nota que veo es de Redes: Códigos C1, un 6,5, del 28 de septiembre, señor.":
            errs.append(f"última nota: {r} {res}")
        for frase in ("qué me saqué en redes", "cómo me fue en redes", "qué nota me pusieron en redes"):
            r, res, _ = j8.route(frase)
            if r != "notas" or not res["reply"].startswith("En Redes, señor: Control 1, 6,6; Ejercicio 1, 2,6; Códigos C1, 6,5."):
                errs.append(f"«{frase}»: {r} {res}")
        U.LAST_URL = ""
        U.fetch = lambda path: (setattr(U, "LAST_URL", f"https://www.u-cursos.cl/{path}"), pagina["v"])[1]
        st0 = json.loads((tmp / "ucursos_notas.json").read_text(encoding="utf-8"))
        U.check()
        st1 = json.loads((tmp / "ucursos_notas.json").read_text(encoding="utf-8"))
        if ramo["path"] not in st1.get("auxiliar", []) or st1["ramos"] != st0["ramos"]:
            errs.append("donde es auxiliar (página de todo el curso, no …/alumno) no debe leer notas")

        def _expirada(path):
            raise U.SessionExpired("x")
        U.fetch = _expirada
        r, res, _ = j8.route("hay notas nuevas")
        if "expiró" not in res["reply"]:
            errs.append(f"sesión vencida: {res}")
    finally:
        U.fetch, U.courses = viejo_fetch, viejos_ramos
    enviados = []
    j8.telegram = type("T", (), {"send": lambda self, t: enviados.append(t)})()
    j8.presente = lambda: False  # lejos del PC
    j8.notify("Señor, salió una nota en U-Cursos. Redes: Control 3, un 7,0.", "nota")
    time.sleep(0.1)
    if enviados != ["Señor, salió una nota en U-Cursos. Redes: Control 3, un 7,0."] or "Control 3" not in j8.alerts[-1]["texto"]:
        errs.append(f"el aviso debe ir a la pantalla y a Telegram: {enviados}")
    grande = "<table><tr><th>Evaluación</th><th>Nota</th></tr>" + "".join(f"<tr><td>Alumno {k}</td><td>5.0</td></tr>" for k in range(60)) + "</table>"
    if U.parse_notas(grande):
        errs.append("una lista de alumnos (vista de auxiliar) no son sus notas")
    U.forget_session()
    out.append(("notas de U-Cursos: conectar, avisar solo lo nuevo y no inventar", errs))
    (tmp / "recordatorios.json").unlink(missing_ok=True)
    item = R.add("recordatorio", "sacar la ropa", AHORA + timedelta(minutes=20), 1200)
    otro = H.Atlas()  # "reiniciar Atlas": una instancia nueva lee el mismo archivo
    errs = [] if any(i["id"] == item["id"] for i in R.load()) and otro.reminders_view() else ["no quedó guardado en recordatorios.json"]
    out.append(("persisten si se reinicia Atlas", errs))
    errs = []
    if R.take_due(AHORA + timedelta(minutes=19)):
        errs.append("avisó antes de tiempo")
    due = R.take_due(AHORA + timedelta(minutes=20, seconds=1))
    if [d["id"] for d in due] != [item["id"]]:
        errs.append(f"a la hora debía vencer el de la ropa, vencieron {due}")
    elif R.alert_text(due[0]) != "Señor, le recuerdo: sacar la ropa.":
        errs.append(f"aviso: {R.alert_text(due[0])!r}")
    if R.load():
        errs.append("después de avisar debía salir del archivo")
    out.append(("avisa a la hora y lo saca de la lista", errs))
    t = R.add("temporizador", "", AHORA - timedelta(minutes=10), 300)
    txt = R.alert_text(t, late=True)
    out.append(("lo vencido con Atlas cerrado se avisa al abrir",
                [] if re.search(r"mientras estaba cerrado venció un temporizador de las 8:50", txt) else [f"aviso: {txt!r}"]))
    R.remove([t["id"]])
    # Una sola voz a la vez (uso real: al presionar Confirmar seguía la pregunta y se superponían las voces)
    errs = []
    jv = H.Atlas()
    h0 = jv.live().get("hush")
    jv.hush_voice(page=False)
    if jv.live().get("hush") != h0:
        errs.append("al confirmar desde la ventana no debe callar a la propia ventana")
    jv.hush_voice()
    if jv.live().get("hush") != (h0 or 0) + 1:
        errs.append("una nueva voz del servidor debe avisar a la ventana que se calle")
    src = (HERE / "hud.html").read_text(encoding="utf-8")
    dec = src[src.find("async function decide"):][:400]
    if "stopAudio()" not in dec:
        errs.append("decide() (Confirmar/Cancelar) no calla la voz de la ventana")
    if "l.hush" not in src:
        errs.append("la ventana no escucha el aviso de callarse (hush)")
    srv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    for ruta in ('"/api/confirm"', '"/api/chat"'):
        i = srv.find("self.path == " + ruta)
        if "hush_voice" not in srv[i:i + 200]:
            errs.append(f"{ruta} no calla los parlantes antes de responder")
    out.append(("una sola voz: confirmar, nueva orden o aviso callan lo anterior", errs))
    # Hardware leído del sistema (uso real: el modelo inventó «RTX 2060» y «Ryzen 5 3600X»)
    errs = []
    jh = H.Atlas()
    jh.system_specs = lambda: {"cpu": "AMD Ryzen 7 3700X 8-Core Processor", "nucleos": 8, "hilos": 16,
                               "gpus": ["NVIDIA GeForce RTX 3050 de 8 GB"], "ram_gb": 32,
                               "discos": [{"unidad": "C:", "total_gb": 1093, "libre_gb": 99}]}
    casos_hw = {"¿Cuál es mi tarjeta gráfica y cuál es mi procesador?": r"Ryzen 7 3700X, con 8 núcleos.*RTX 3050 de 8 GB",
                "¿Cuánta RAM tengo?": r"32 GB de RAM", "¿Cuánto espacio libre me queda?": r"C: tiene 99 GB libres"}
    for frase, rx in casos_hw.items():
        nombre, r, _ = jh.route(frase)
        if nombre != "hardware" or not re.search(rx, (r or {}).get("reply", "")):
            errs.append(f"{frase!r} -> {nombre}: {(r or {}).get('reply', '')[:100]!r}")
    for frase in ["Hazme una gráfica de mis gastos", "Pon el disco de Ado", "¿Qué tarjeta gráfica me recomiendas comprar?",
                  "Guarda en memoria que mi procesador favorito es Intel"]:
        if jh.route_hardware(frase):
            errs.append(f"{frase!r} no es una pregunta por el hardware de este PC")
    out.append(("tarjeta gráfica, procesador, RAM y disco se leen del sistema, no se inventan", errs))
    # Ruteo mixto (17-11-2026): si el modelo responde un dato del usuario sin herramienta, se le da otra vuelta obligada a
    # consultar con «orden»; si tampoco consulta, no se da por cierto lo inventado. Modelo y reglas falsos: nada real.
    import os
    import types as _types

    errs = []
    for frase, rx in {"¿De quién estamos esperando correo ahora?": True, "¿cómo me fue en el control 2 de redes?": True,
                      "y el jueves qué tengo?": True, "¿qué hice el 12 de marzo?": True, "¿Tengo algo mañana?": True,
                      "¿Quién pintó la Mona Lisa?": False, "cuéntame un chiste": False,
                      "qué es una clase en Python": False}.items():
        if H.asks_user_data(frase) != rx:
            errs.append(f"asks_user_data({frase!r}) debía ser {rx}")

    class _Res:
        def __init__(self, content, tools=()):
            self.content, self.tool_results = content, [_types.SimpleNamespace(tool_name=t, success=True, content="")
                                                        for t in tools]

    for consulta in (True, False):
        jm = H.Atlas()
        jm.ready, jm.pending = True, None
        jm.route = lambda t: ("modelo", None, t)
        jm._route = lambda t: ("vigilancia", {"reply": "Estoy esperando el correo de Platanus Hack, señor.", "tools": []}, t)
        vueltas = []

        def _run(prompt, context=None, _j=jm, _c=consulta):
            vueltas.append(prompt)
            if len(vueltas) == 1:
                return _Res("Estamos esperando el correo de su banco, señor.")  # inventado
            if _c:
                _j.order_tool("¿De quién estamos esperando correo ahora?")
                return _Res("x", ["orden"])
            return _Res("Seguro es de su banco, señor.")

        jm.agent = _types.SimpleNamespace(run=_run)
        old = os.environ.get("ATLAS_REESCRIBIR")
        os.environ["ATLAS_REESCRIBIR"] = "0"
        try:
            r = jm._chat("¿De quién estamos esperando correo ahora?")
        finally:
            if old is None:
                os.environ.pop("ATLAS_REESCRIBIR", None)
            else:
                os.environ["ATLAS_REESCRIBIR"] = old
        rep = r.get("reply", "")
        if len(vueltas) != 2:
            errs.append(f"consulta={consulta}: {len(vueltas)} vueltas del modelo, se esperaban 2")
        if "banco" in rep:
            errs.append(f"consulta={consulta}: quedó el dato inventado: {rep!r}")
        if consulta and "Platanus" not in rep:
            errs.append(f"consulta={consulta}: no usó lo que trajo orden: {rep!r}")
        if not consulta and "no tengo ese dato" not in rep.lower():
            errs.append(f"consulta={consulta}: sin consulta debía decir que no tiene el dato: {rep!r}")
    out.append(("el modelo consulta los datos del usuario con orden y nunca los inventa", errs))
    # Botón «?» (17-11-2026): la instalación paso a paso, con cada sistema detectado desde archivos falsos
    import datetime as _dtf
    import tempfile as _tf
    from pathlib import Path as _P

    import atlas_faltantes as JF

    errs = []
    with _tf.TemporaryDirectory() as _tmpf:
        t = _P(_tmpf)
        oj, hd, cn, lo = t / "oj", t / "oj" / "hud", t / "conn", t / "local"
        for d in (oj / "src" / ".venv", oj / "voices" / "parakeet-v3", oj / "apps" / "cronos", hd, cn / "mail_accounts",
                  lo / "Discord", lo / "Packages" / "Microsoft.YourPhone_8wekyb3d8bbwe"):
            d.mkdir(parents=True)
        for v in JF.PIPER:
            (oj / "voices" / f"{v}.onnx").write_bytes(b"")
        (oj / "VERSION").write_text("9.001\r\n", encoding="utf-8")   # única fuente de la versión (18-11-2026)
        (hd / "agenda_u_cursos.ics").write_text("", encoding="utf-8")
        (hd / "contactos.json").write_text('{"contactos": [{}, {}]}', encoding="utf-8")
        (oj / "apps" / "cronos" / "config.json").write_text('{"pausado": true}', encoding="utf-8")
        (cn / "telegram.json").write_text("{}", encoding="utf-8")
        (cn / "mail_accounts" / "a.json").write_text("{}", encoding="utf-8")
        (lo / "Discord" / "Update.exe").write_bytes(b"")
        viejo = (JF.OJ, JF.HUD, JF.CONN, JF.LOCAL, JF.HISTORIA_CFG, JF._ollama_tags, JF._modulo)
        viejo_h = (JF.AVISOS_DIR, JF.WINGET_PKGS, JF.STARTUP, JF._syncthing_corre)   # Hermes: nada real del PC
        JF.AVISOS_DIR, JF.WINGET_PKGS, JF.STARTUP = hd / "sin_avisos", lo / "sin_winget", hd / "sin_inicio"
        JF._syncthing_corre = lambda: False
        JF.OJ, JF.HUD, JF.CONN, JF.LOCAL, JF.HISTORIA_CFG = oj, hd, cn, lo, oj / "apps" / "cronos" / "config.json"
        JF._ollama_tags = lambda: [{"name": "qwen3.5:9b", "size": 6.6e9}]
        JF._modulo = lambda n: n != "yt_dlp"
        try:
            r = JF.revisar("9.000", {"_modelo": "qwen3.5:9b", "oido": True, "voz": True, "tecla": True, "flotante": True,
                                     "telegram": True, "google": True},
                           {"ucursos": {"ok": False, "motivo": "la sesión expiró"}}, ["Fortuna", "Hermes", "Cronos"],
                           ahora=_dtf.datetime(2026, 11, 17, 13, 16))
            ex = JF.destino("extras")
        finally:
            JF.OJ, JF.HUD, JF.CONN, JF.LOCAL, JF.HISTORIA_CFG, JF._ollama_tags, JF._modulo = viejo
            JF.AVISOS_DIR, JF.WINGET_PKGS, JF.STARTUP, JF._syncthing_corre = viejo_h
    est = [p["estado"] for p in r["pasos"]]
    # 18-11-2026: U-Cursos y Canvas son un solo paso «Universidad (opcional)» con dos tarjetas independientes.
    # Aquí U-Cursos tiene su calendario .ics (configurado) y Canvas no se usa (opcional): el paso queda listo.
    # 18-11-2026 (17:00): Hermes salió de Instalación (va en la guía): 10 pasos; su estado viene aparte en r["guia"]
    if est != ["g", "y", "g", "g", "x", "g", "y", "x", "x", "g"]:   # Cronos en pausa no es pendiente (17-11)
        errs.append(f"estados de los pasos: {est}")
    if r.get("guia", {}).get("Hermes", {}).get("estado") != "x":   # sin Syncthing: falta, pero en la guía
        errs.append(f"Hermes sin Syncthing debe verse en la guía: {r.get('guia', {}).get('Hermes', {}).get('estado')}")
    if (r["listos"], r["total"], r["pendientes"], r["peor"], r["revisado"]) != (5, 10, 5, "x", "13:16"):
        errs.append(f"resumen {r['listos']}/{r['total']} pend={r['pendientes']} peor={r['peor']} {r['revisado']}")
    p = {x["n"]: x for x in r["pasos"]}
    if "Corre la 9.000" not in p[2]["sistemas"][1]["detalle"]:
        errs.append(f"paso 2 no avisa reiniciar: {p[2]['sistemas'][1]}")
    _pl = {c["nombre"]: c for c in p[6].get("plataformas") or []}
    if p[6]["titulo"] != "Universidad (opcional)" or list(_pl) != ["Canvas", "U-Cursos"]:
        errs.append(f"paso 6 debe ser Universidad con Canvas | U-Cursos: {p[6]['titulo']} {list(_pl)}")
    elif not any(b["tipo"] == "dicho" and b["valor"] == "conecta U-Cursos" and b["primario"] for b in _pl["U-Cursos"]["botones"]) \
            or (_pl["Canvas"]["estado"], _pl["Canvas"]["detalle"]) != ("o", "Opcional · no configurado"):
        errs.append(f"tarjetas de Universidad: {_pl}")
    if not any(b["tipo"] == "seccion" and b["valor"] == "Universidad" for b in p[6]["botones"]):
        errs.append("el paso Universidad debe llevar a Ajustes › Universidad")
    if not any(b["tipo"] == "abrir" and b["valor"] == "extras" for b in p[9]["botones"]) or not ex.endswith("Instalar-extras.cmd"):
        errs.append(f"Música sin INSTALAR EXTRAS: {p[9]['botones']} {ex}")
    if [s_["nombre"] for s_ in p[8]["sistemas"] if s_["estado"] == "x"] != ["WhatsApp"] or "2 contactos" not in p[8]["sistemas"][3]["detalle"]:
        errs.append(f"paso 8: {p[8]['sistemas']}")
    if JF.destino("..\\Windows\\notepad.exe") or JF.destino(""):
        errs.append("un id desconocido no debe abrir nada")
    if any(b["texto"] == "VOLVER A REVISAR" for b in p[1]["botones"][:-1]) or p[1]["botones"][-1]["tipo"] != "revisar":
        errs.append(f"VOLVER A REVISAR debe ir al final: {p[1]['botones']}")
    srv = open(H.__file__, encoding="utf-8").read()
    for frag in ('self.path == "/api/faltantes"', 'self.path == "/api/faltantes_abrir"', "atlas_faltantes.destino("):
        if frag not in srv:
            errs.append(f"hud_server sin {frag}")
    page = open(_P(H.__file__).with_name("hud.html"), encoding="utf-8").read()
    for frag in ("faltaBtnEl", 'id="faltan"', "function showFaltan", '"/api/faltantes"', '"/api/faltantes_abrir"', "function fpPaso",
                 "closeEmbed(); closeFaltan();", "if (embedName) { closeEmbed(true); showFaltan(); return; }"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    out.append(("el botón «?» muestra la instalación paso a paso con cada sistema detectado", errs))
    # Pedido 18-11-2026: Canvas y U-Cursos opcionales e independientes. Cuatro casos: ninguno, solo Canvas, solo U-Cursos, ambos
    errs = []
    with _tf.TemporaryDirectory() as _tmpu:
        hu = _P(_tmpu)
        ok_cv = {"canvas": {"ok": True, "conexion": {"ok": True}}}
        ok_uc = {"ucursos": {"ok": True, "conexion": {"ok": True}}}

        def _caso(canvas, ucursos, vig):
            for f in ("canvas_sesion.json", "ucursos_sesion.json", "agenda_u_cursos.ics"):
                (hu / f).unlink(missing_ok=True)
            if canvas:
                (hu / "canvas_sesion.json").write_text("{}", encoding="utf-8")
            if ucursos:
                (hu / "ucursos_sesion.json").write_text("{}", encoding="utf-8")
                (hu / "agenda_u_cursos.ics").write_text("", encoding="utf-8")
            u = JF.universidad(vig, hud=hu)
            return u, {c["nombre"]: c for c in u["plataformas"]}

        for nombre, cv_, uc_, vig, esp in (("ninguno", False, False, {}, ("o", "o", "o")),
                                            ("solo Canvas", True, False, ok_cv, ("g", "o", "g")),
                                            ("solo U-Cursos", False, True, ok_uc, ("o", "g", "g")),
                                            ("ambos", True, True, {**ok_cv, **ok_uc}, ("g", "g", "g"))):
            u, pl = _caso(cv_, uc_, vig)
            got = (pl["Canvas"]["estado"], pl["U-Cursos"]["estado"], u["estado"])
            if got != esp:
                errs.append(f"{nombre}: {got} (esperado {esp})")
            if not all(c["opcional"] for c in pl.values()):
                errs.append(f"{nombre}: las dos tarjetas deben ir marcadas opcional")
            for c in pl.values():   # sin configurar: «Opcional · no configurado», nunca un error
                if c["estado"] == "o" and (c["detalle"] != "Opcional · no configurado" or any(s_["estado"] == "x" for s_ in c["sistemas"])):
                    errs.append(f"{nombre}: {c['nombre']} sin configurar no es error: {c['detalle']} {c['sistemas']}")
                if c["estado"] == "g" and c["botones"] and c["nombre"] == "Canvas":
                    errs.append(f"{nombre}: Canvas configurado no pide conectar")
        # una plataforma rota no toca a la otra
        u, pl = _caso(True, False, {"canvas": {"ok": False, "motivo": "la sesión expiró", "conexion": {"ok": False, "motivo": "la sesión expiró"}}})
        if (pl["Canvas"]["estado"], pl["U-Cursos"]["estado"], u["estado"]) != ("x", "o", "x"):
            errs.append(f"Canvas vencido: {[(c['nombre'], c['estado']) for c in pl.values()]} {u['estado']}")
    if JF._peor(["o", "o"]) != "o" or JF._peor(["g", "o"]) != "g" or JF._peor(["o", "y"]) != "y":
        errs.append("«opcional» no debe pesar como problema")
    _src_jf = (HERE / "atlas_faltantes.py").read_text(encoding="utf-8")
    if 'listos = sum(p["estado"] in ("g", "o") for p in pasos)' not in _src_jf:
        errs.append("un paso opcional sin configurar debe contar como listo (no pendiente)")
    import atlas_instrucciones_ia as _IAI
    if _IAI.EST.get("o", "").split(" ")[0] != "OPCIONAL" or "Universidad (opcional)" not in _IAI.VERIFICAR:
        errs.append("las instrucciones para otra IA deben conocer el paso Universidad (opcional)")
    _pg = (HERE / "hud.html").read_text(encoding="utf-8")
    for frag in ("function fpUniCard(", "function uniPaint(", 'if (ajSel === "Universidad" && !ajQ) return uniPaint(main);',
                 'o: "OPCIONAL"', '.fk-o{', "PLATAFORMAS · OPCIONALES E INDEPENDIENTES", 'fpEl("span", "fp-op", "OPCIONAL")',
                 "v.ucursos.configurado === false"):
        if frag not in _pg:
            errs.append(f"hud.html sin {frag}")
    # Mensajes: con una sola plataforma lo dice con amabilidad; sin ninguna, explica que las dos son opcionales
    ju = nuevo(H)
    U_, C_ = ju._ucursos(), ju._canvas()
    _hs = (U_.has_session, C_.has_session)
    try:
        U_.has_session, C_.has_session = (lambda: False), (lambda: False)
        r0 = (ju.route_notas("mis notas de u-cursos") or {}).get("reply", "")
        r1 = (ju.route_canvas("mis notas de canvas") or {}).get("reply", "")
        U_.has_session, C_.has_session = (lambda: False), (lambda: True)
        r2 = (ju.route_notas("mis notas de u-cursos") or {}).get("reply", "")
        U_.has_session, C_.has_session = (lambda: True), (lambda: False)
        r3 = (ju.route_canvas("mis notas de canvas") or {}).get("reply", "")
    finally:
        U_.has_session, C_.has_session = _hs
    if not all("opcionales" in x and "conecta U-Cursos" in x and "conecta Canvas" in x for x in (r0, r1)):
        errs.append(f"sin ninguna: {r0!r} | {r1!r}")
    if "U-Cursos no está configurado" not in r2 or "es opcional" not in r2 or "Canvas sí" not in r2:
        errs.append(f"solo Canvas, pregunta por U-Cursos: {r2!r}")
    if "Canvas no está configurado" not in r3 or "es opcional" not in r3 or "U-Cursos sí" not in r3:
        errs.append(f"solo U-Cursos, pregunta por Canvas: {r3!r}")
    out.append(("Universidad: Canvas y U-Cursos opcionales e independientes (ninguno, solo uno, ambos)", errs))
    # entrada de Cronos («Órbita»): se arma con el logo real del riel y termina mostrándolo con el nombre
    errs = []
    for frag in ("function playAppIntro(", "const INTRO_APPS = {", "cronos: introCronos", "playAppIntro(embedName);",
                 'matchMedia("(prefers-reduced-motion: reduce)")', "#appIntro{", "paintAppName(nm, nombre)",
                 "if (t >= 1460) { o.remove(); return; }"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    if page.find("playAppIntro(embedName);") < page.find("function openEmbed(e)"):
        errs.append("la entrada debe partir desde openEmbed")
    out.append(("abrir Cronos muestra su animación de entrada y termina en su logo", errs))
    # las apps aparecen gradual siempre, también la primera vez, y no antes de que termine su entrada
    errs = []
    for frag in ("#embed iframe{opacity:0;transition:opacity .5s ease-out}#embed iframe.ver{opacity:1}", "function mostrarEmbed()",
                 'introHasta = performance.now() + 1300;', '$("embedFrame").classList.remove("ver");'):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    if "mostrarEmbed();" not in page.split('$("embedFrame").addEventListener("load"', 1)[1][:200]:
        errs.append("al cargar la app debe mostrarse con el fundido")
    out.append(("Fortuna, Hermes y Cronos aparecen con un fundido al abrirlas", errs))
    # sin destello: la app recién cambia cuando la capa de la entrada ya tapa todo
    errs = []
    for frag in ("function abrirEmbed(e)", "if (introHasta) embedAbrirT = setTimeout(abrir, 270); else abrir();", "clearTimeout(embedAbrirT);"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    oe = page.split("function openEmbed(e)", 1)[1].split("function abrirEmbed(e)", 1)[0]
    if 'classList.add("open")' in oe or ".src = " in oe:
        errs.append("openEmbed no debe mostrar la app antes de que la entrada la tape")
    out.append(("abrir una app no muestra un destello de ella antes de la animación", errs))
    # consola «escuchando» y demás esperas: el núcleo de Atlas en miniatura, no el reactor de Jarvis
    errs = []
    cw = page.split("function core(c, cx, cy, Rr, t, sp)", 1)[1].split("function along(p, t)", 1)[0] if "function core(c, cx, cy, Rr, t, sp)" in page else ""
    if not cw:
        errs.append("hud.html sin el dibujo de la espera de la consola")
    for frag in ("const CN_ST = [", "const CN_LN = [", '"#0E4A62"', "quadraticCurveTo"):
        if frag not in page.split("function along(p, t)", 1)[0]:
            errs.append(f"la espera de la consola no dibuja el núcleo de Atlas (falta {frag})")
    if "fillRect(cx + (i - 2)" in cw or "const ring = (rr, w, segs" in cw:
        errs.append("la espera de la consola todavía dibuja el reactor de Jarvis")
    out.append(("la consola muestra el núcleo de Atlas al escuchar (no el logo de Jarvis)", errs))
    # encabezado: «Atlas // núcleo local», con el crédito a OpenJarvis en el tooltip
    errs = []
    if '<span class="marca" title="Atlas, basado en OpenJarvis"><svg class="wmk"' not in page or 'id="mk_halo"' not in page:
        errs.append("el encabezado debe mostrar el logo completo de Atlas (constelación sobre ATLAS) con tooltip «Atlas, basado en OpenJarvis»")
    if "OPENJARVIS // NÚCLEO LOCAL" in page:
        errs.append("el encabezado todavía dice OPENJARVIS")
    out.append(("el encabezado dice Atlas y da el crédito a OpenJarvis en el tooltip", errs))
    # círculo flotante: dibuja el núcleo de Atlas (esfera oscura con constelación), con los colores de cada estado
    errs = []
    try:
        import numpy as _np
        import atlas_flotante as FL
        for m, esperado in (("idle", FL.NU_COLS["idle"][0]), ("listening", FL.NU_COLS["listening"][0]),
                            ("thinking", FL.NU_COLS["thinking"][0])):
            FL.nu["t"] = None
            for i in range(40):
                data = FL.render(0, m, 500.0 + i * 0.033, None)
            px = _np.frombuffer(data, _np.uint8).reshape(FL.H, FL.W, 4)
            if len(data) != FL.W * FL.H * 4:
                errs.append(f"{m}: tamaño de imagen {len(data)}")
            if px[0, 0, 3] != 0 or px[-1, -1, 3] != 0:
                errs.append(f"{m}: las esquinas deben quedar transparentes")
            cx, cy = int(FL.CX), int(FL.CY)
            if px[cy, cx, 3] < 240 or int(px[cy, cx, :3].max()) > 120:
                errs.append(f"{m}: el centro debe ser la esfera oscura, no {px[cy, cx].tolist()}")
            if _np.abs(_np.asarray(FL.nu["c1"]) - _np.asarray(esperado)).max() > 3:
                errs.append(f"{m}: color del borde {FL.nu['c1']} en vez de {esperado}")
        if "render_reactor(" in open(FL.__file__, encoding="utf-8").read().split("def tick(self):", 1)[1]:
            errs.append("el círculo todavía usa el reactor de Jarvis")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"no se pudo dibujar el círculo: {exc!r}")
    out.append(("el círculo flotante muestra el núcleo de Atlas en cada estado", errs))
    # barra de título oscura: Edge --app dibuja su propia barra; con --force-dark-mode la dibuja en su tema oscuro
    errs = []
    srv = (HERE / "hud_server.py").read_text(encoding="utf-8")
    ow = srv.split("def open_window(", 1)[1].split("\ndef ", 1)[0] if "def open_window(" in srv else ""
    if '"--force-dark-mode"' not in ow:
        errs.append("open_window debe abrir Edge con --force-dark-mode (barra de título oscura)")
    out.append(("la ventana de Atlas abre con la barra de título oscura", errs))
    # cargador «Pléyades» y logo del riel / VOLVER «Constelación» con el logo de Atlas
    errs = []
    for frag in ("cargador «Pléyades»", "const PLL = [", "function core(c, cx, cy, R, t) {", '<g class="cl"', 'class="atl"',
                 '$("embedClose").querySelector(".jring").innerHTML = RAIL_LOGO', "@keyframes atlDestello", "linear-gradient(135deg,#4FE3FF,#9C7BFF)"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    if "ring(R * 0.7, lw * 0.7" in page:
        errs.append("quedó el cargador viejo de arcos")
    out.append(("el cargador y el logo del riel / VOLVER usan el logo de Atlas", errs))
    # pantalla de inicio «Constelación»
    errs = []
    for frag in ('<div id="atlasIntro" aria-hidden="true">', "pantalla de inicio «Constelación»", "@media (prefers-reduced-motion:reduce){#atlasIntro{display:none}}", "cap.remove()", "window.atlasIntro = function (vuelta)", "closeEmbed(sinIntro)", '$("embedClose").addEventListener("click", () => closeEmbed());'):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    out.append(("Atlas abre con su pantalla de inicio", errs))
    # sonidos de apertura (Atlas, Hermes, Fortuna y Cronos)
    errs = []
    for frag in ("window.sonarIntro = function (k)", 'window.sonarIntro("atlas");', "window.sonarIntro(key);"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    for k in ("atlas", "hermes", "fortuna", "cronos"):
        if f'  {k}: "data:audio/ogg;codecs=opus;base64,' not in page:
            errs.append(f"hud.html sin el sonido de {k}")
    out.append(("cada app suena al abrirse", errs))
    # sonidos HD (18-11-2026): Eclipse en estéreo de buena calidad y la pantalla de carga con sonido
    errs = []
    import base64 as _b64
    m_at = re.search(r'  atlas: "data:audio/ogg;codecs=opus;base64,([^"]+)"', page)
    if not m_at or len(_b64.b64decode(m_at.group(1))) < 40000:
        errs.append("el sonido de inicio de Atlas debe ser la versión HD (Opus estéreo, no la de 15 kb/s)")
    for frag in ("const SONIDOS_CARGA = {", "window.sonarCarga = (function ()", 'window.sonarCarga("final")', 'window.sonarCarga("inicio")',
                 'window.sonarCarga("estrella", { dl: d, total: claves.length })', 'window.sonarCarga("grupo", { dl: dg })', "desfase (18-11-2026)", "setTimeout(terminar,", "g.connect(sonBus || c.destination); src.start("):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    for k in ("estrella", "grupo", "final"):
        if f'  {k}: "data:audio/ogg;codecs=opus;base64,' not in page:
            errs.append(f"la carga no tiene el sonido {k}")
    out.append(("la pantalla de carga suena y el inicio es HD", errs))
    # Uso real 18-11-2026: el sonido se trababa al entrar (Audio con data-URI que se decodificaba en cada clic)
    errs = []
    ini = page.find("const sonidosIntro = {};")
    bloque = page[ini:page.find("const ATLAS_INTRO_TPL", ini)] if ini >= 0 else ""
    for frag in ("decodeAudioData(", "Object.keys(SONIDOS_INTRO)", "window.sonidosListos", "createBufferSource()", "g.gain.value = .55",
                 "linearRampToValueAtTime(0", '"pointerdown"', "sonCtx.resume()"):
        if frag not in bloque:
            errs.append(f"sonidos de entrada sin {frag!r}")
    if "new Audio(SONIDOS_INTRO" in page or ".play()" in bloque:
        errs.append("los sonidos de entrada no deben ser elementos Audio")
    # Uso real 18-11-2026 (después): voz y sonido de entrada suenan juntos, sin ducking ni cortes entre ellos
    if "callarIntro(150)" in page or "callarVozHud" in page:
        errs.append("la voz no debe cortar ni bajar el sonido de entrada, ni el sonido a la voz")
    if "createDynamicsCompressor()" not in bloque or "g.connect(sonBus || c.destination)" not in bloque \
            or "audioCtx = sonidoCtx() || new AudioContext()" not in page:
        errs.append("voz y sonidos de entrada deben ir por el mismo AudioContext y bus con limitador")
    if "decodeAudioData(" in page[page.find("window.sonarIntro = function"):page.find("window.sonarIntro = function") + 1500]:
        errs.append("no se debe decodificar nada al tocar el sonido de entrada")
    if "embedSrcT = setTimeout(cargarApp, espera)" not in page:
        errs.append("la página de la app debe cargarse al terminar la entrada")
    # la única excepción es esa: cerrar corta todo al instante y dos voces no se superponen
    ini_c = page.find("function cortarVozAlCerrar()")
    cierre = page[ini_c:page.find("\n}", ini_c)]
    if "stopAudio()" not in cierre or "sonActual.n.stop()" not in cierre or "/api/voz/detener" not in cierre:
        errs.append("cerrar la ventana debe cortar al instante la voz y el sonido de entrada")
    ini_s = page.find("async function say(text)")
    cuerpo = page[ini_s:page.find("\n}", ini_s)]
    if "const my = ++speakToken;" not in cuerpo or cuerpo.find("stopAudio();") < 0 or cuerpo.find("stopAudio();") > cuerpo.find("createBufferSource()"):
        errs.append("una voz nueva debe callar la anterior (no se superponen)")
    out.append(("los sonidos de entrada se precargan como AudioBuffer y suenan junto con la voz, sin ducking ni decodificar en el momento", errs))
    # Uso real 18-11-2026: al terminar la entrada de Cronos el encabezado decía «CRONOS» en letras normales, sin el símbolo
    errs = []
    for frag in ("function paintAppName(el, nombre)", "function paintAppNameSvg(t, nombre)", "eg = paintAppNameSvg(t1, nm)",
                 'paintAppName($("embedName"), embedName)', "paintAppName(nm, nombre)", "paintAppName(t, nombre)"):
        if frag not in page:
            errs.append(f"hud.html: el nombre de la app debe llevar el glifo ({frag})")
    if "t1.textContent = esApp ? nm.toUpperCase()" in page:
        errs.append("hud.html: la pantalla de carga pinta el nombre de la app sin glifo")
    hist = (Path(__file__).resolve().parent.parent / "apps" / "cronos" / "historia.html").read_text(encoding="utf-8")
    if "nombreConGlifo($('#dout .inicio .inm'), 'Cronos')" not in hist or "parent.paintAppName" not in hist or '.inicio .inm .eg{' not in hist:
        errs.append("Cronos: el encabezado de inicio debe usar paintAppName del HUD")
    if re.search(r">\s*CRONOS\s*<", hist) and 'aria-label="Cronos">CRONOS<' not in hist:
        errs.append("Cronos: hay otro «CRONOS» en texto sin glifo")
    apo = Path.home() / "Downloads" / "Apolo" / "apolo.html"
    if apo.exists():
        h = apo.read_text(encoding="utf-8")
        if 'id="marcaNombre"' not in h or "parent.paintAppName" not in h or ".brand b .eg{" not in h:
            errs.append("Hermes: la marca de la barra debe usar paintAppName del HUD")
    out.append(("todo lugar que pinta CRONOS/HERMES/FORTUNA usa el nombre con glifo", errs))
    # Pedido 18-11-2026: Hermes agrupa por ciclo de la tarjeta (de corte a corte) o por mes calendario
    errs = []
    import importlib.util as _ilu
    import atlas_hermes as _HE
    from datetime import date as _date
    _tmpc = Path(tempfile.mkdtemp(prefix="atlas_ciclo_"))
    _viejo = (_HE.HERMES_DIR, _HE.CLS_FILE, _HE.HOY, list(_HE.CORTES))
    try:
        _HE.CORTES[:] = []
        c20 = {"modo": "ciclo", "dia": 20}
        # noviembre 2026: el 20 es viernes -> corte el 20; la compra del 21 ya es del ciclo de diciembre
        for d, want in ((19, (2026, 11)), (20, (2026, 11)), (21, (2026, 12))):
            if _HE.periodo_de(_date(2026, 11, d), c20) != want:
                errs.append(f"compra del {d}-11 con corte el 20: {_HE.periodo_de(_date(2026, 11, d), c20)} (esperaba {want})")
        if _HE.rango(2026, 11, c20) != (_date(2026, 10, 21), _date(2026, 11, 20)):
            errs.append(f"ciclo de noviembre con corte 20: {_HE.rango(2026, 11, c20)}")
        # con el corte real del estado de cuenta (18-11) se usa ese, no el 20
        _HE.CORTES[:] = ["2026-11-18"]
        for d, want in ((18, (2026, 11)), (19, (2026, 12)), (20, (2026, 12))):
            if _HE.periodo_de(_date(2026, 11, d), c20) != want:
                errs.append(f"con corte real el 18, compra del {d}-11: {_HE.periodo_de(_date(2026, 11, d), c20)}")
        # sábado o domingo -> día hábil anterior (como el banco: 23-08-2026 domingo -> viernes 21)
        _HE.CORTES[:] = []
        if _HE.corte(2026, 8, [], 23) != _date(2026, 8, 21) or _HE.corte(2026, 5, [], 23) != _date(2026, 5, 22):
            errs.append(f"corte en fin de semana: {_HE.corte(2026, 8, [], 23)} {_HE.corte(2026, 5, [], 23)}")
        if _HE.dia_auto(["2026-07-23", "2026-08-21", "2026-09-23"]) != 23 or _HE.dia_auto([]) != 20:
            errs.append("día de corte automático: el que más se repite, o el 20")
        # voz: «cuánto gasté este mes» con ciclo y con mes calendario (igual que antes del cambio)
        movs = [{"id": f"x{i}", "fecha": f, "monto": -m, "comercio": "Tienda", "categoria": "Comida", "banco": "Scotiabank", "cuenta": "Visa"}
                for i, (f, m) in enumerate((("2026-10-15", 1000), ("2026-10-22", 2000), ("2026-10-25", 4000), ("2026-11-05", 8000),
                                            ("2026-11-20", 16000), ("2026-11-21", 32000)))]
        (_tmpc / "movimientos.json").write_text(json.dumps({"movimientos": movs, "cortes": [{"tarjeta": "tarjeta 1", "fecha": "2026-10-23"}]}), encoding="utf-8")
        _HE.HERMES_DIR, _HE.HOY = _tmpc, _date(2026, 11, 22)
        _HE.CLS_FILE = _tmpc / "accesos_datos.json"
        # 18-11-2026: el ciclo es fijo (corte el 23 o el día hábil anterior); lo guardado en «periodo» ya no cuenta
        _HE.CLS_FILE.write_text(json.dumps({"hermes": {"periodo": {"modo": "mes", "dia": 20}}}), encoding="utf-8")
        r = (_HE.responder("cuánto gasté este mes") or {}).get("reply", "")
        # ciclo de noviembre: 24-oct..23-nov (23-11 es lunes) -> 4000 + 8000 + 16000 + 32000
        if "60 mil" not in r or "ciclo" not in r:
            errs.append(f"«cuánto gasté este mes» por ciclo fijo el 23 (aunque diga «mes» guardado): {r}")
        # compra Visa del 22-10 que el banco facturó en el estado de cuenta de noviembre (ciclo = su corte): cuenta en
        # el ciclo de noviembre, para cuadrar con lo facturado (uso real: julio, agosto y septiembre no cuadraban)
        movs[1]["ciclo"] = "2026-11-20"
        (_tmpc / "movimientos.json").write_text(json.dumps({"movimientos": movs, "cortes": [{"tarjeta": "tarjeta 1", "fecha": "2026-10-23"}]}), encoding="utf-8")
        r = (_HE.responder("cuánto gasté en noviembre") or {}).get("reply", "")
        if "62 mil" not in r:
            errs.append(f"compra facturada en el estado siguiente: {r}")
        r = (_HE.responder("cuánto gasté en octubre") or {}).get("reply", "")
        if "1 mil pesos" not in r:   # 24-sep..23-oct, sin la del 22 (facturada en noviembre)
            errs.append(f"ciclo de octubre sin la compra facturada en noviembre: {r}")
        if _HE.ajuste_periodo() != {"modo": "ciclo", "dia": 23}:
            errs.append(f"el período debe ser siempre el ciclo con corte el 23: {_HE.ajuste_periodo()}")
    finally:
        _HE.HERMES_DIR, _HE.CLS_FILE, _HE.HOY = _viejo[:3]
        _HE.CORTES[:] = _viejo[3]
        shutil.rmtree(_tmpc, ignore_errors=True)
    apo = Path.home() / "Downloads" / "Apolo" / "apolo.html"
    if apo.exists():
        h = apo.read_text(encoding="utf-8")
        for frag in ("function corteDe(y, m)", "m.pk === k", 'data-p="ciclo"', 'data-p="mes"',
                     'id="corteDia"', 'clave: "periodo"', "perFin(d) <= F.hasta", "rangoDe(d)",
                     "ciclo() && m.ciclo ? m.ciclo.slice(0, 7)",
                     # pedido 18-11-2026: sin «Compartidos con amigos»; resumen limpio con el balance solo a la derecha
                     '"trend mov" "cats mov"}', 'id="k-falta"', 'id="k-bal-s" hidden', 'id="k-top" hidden',
                     # 18-11-2026: ciclo fijo el 23, sin selector de mes calendario; solo correo y avisos
                     'const PER = {modo: "ciclo", dia: 23};', '<div class="per" id="per" hidden>', "const FUENTES = [];",
                     # botón Actualizar como en Fortuna (POST /actualizar?forzar=1, /estado cada 3 s)
                     'id="hupd-btn"', 'get("/actualizar?forzar=1", {method: "POST"})', 'setTimeout(esperar, 3000)',
                     # bancos en desplegable armado desde los datos, con «+ Agregar banco» (avisos del celular)
                     '<select class="sel" id="banco"', 'id="addb"', '"hermes-bancos"', "+ Agregar banco…"):
            if frag not in h:
                errs.append(f"Hermes (página): falta {frag!r}")
        if "Compartidos con amigos" in h:
            errs.append("Hermes (página): volvió la sección «Compartidos con amigos»")
    out.append(("Hermes agrupa por ciclo de la tarjeta (19, 20 y 21; corte real; mes calendario igual que antes)", errs))
    # fondo: carta celeste en vez de cuadrícula
    errs = []
    for frag in ('<canvas id="cielo" aria-hidden="true"></canvas>', "fondo «carta celeste»", "#cielo{position:absolute;inset:0"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    if '<div class="grid"></div>' in page:
        errs.append("quedó la cuadrícula vieja")
    out.append(("el fondo es una carta celeste", errs))
    # núcleo de la pantalla principal: logo Gd; el borde no se engrosa al hablar
    errs = []
    for frag in ("nucleo Gd", '<div id="nucleo" aria-hidden="true"></div>', "window.nucleoNivel = sum / N;", 'viewBox="56 56 400 400"',
                 "#core .disc,#core .ticks,#core .r1,#core .r2,#core .r3,#core .r4,#core #bars{display:none}", 'class="ondas"'):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    nu = page.split("// --- nucleo Gd", 1)[-1].split("function ensureAudio()", 1)[0]
    if "stroke-width\", (" in nu or "rimW" in nu:
        errs.append("el borde del núcleo no debe cambiar de grosor")
    out.append(("el núcleo de la pantalla principal es el logo de Atlas", errs))
    # el globo del núcleo gira (meridianos) y se acelera con la voz; las Pléyades no se mueven
    errs = []
    nu = page.split("// --- nucleo Gd", 1)[-1].split("function ensureAudio()", 1)[0]
    for frag in ('const mers = Array.from(host.querySelectorAll(".grid ellipse"))', "velGiro", 'm === "speaking" ? 10 * (1.5 + 5 * nivel)', "if (!quieto) giro ="):
        if frag not in nu:
            errs.append(f"núcleo sin {frag}")
    if 'setAttribute("cx"' in nu.split("// globo: una vuelta", 1)[-1].split("// estrellas", 1)[0]:
        errs.append("las Pléyades no deben moverse con el giro")
    out.append(("el globo del núcleo gira con la voz y las Pléyades quedan fijas", errs))
    # logotipo ATLAS en Cinzel (dibujo, sin depender de la fuente) en la pantalla de carga y en el encabezado
    errs = []
    for frag in ('<div class="wm"><svg class="wmk"', 'aria-label="ATLAS"', 'id="wm_b"', 'id="wm_h"', "header .marca{"):
        if frag not in page:
            errs.append(f"hud.html sin {frag}")
    if page.count('class="wmk"') != 2:
        errs.append("el logotipo debe aparecer en la carga y en el encabezado")
    out.append(("el logotipo ATLAS aparece en la carga y en el encabezado", errs))
    # ✓ de la pestaña TAREAS: marca por clave, sale al tiro de la lista y no se puede marcar algo que no existe
    import atlas_tareas_listas as TL

    errs = []
    (tmp / "tareas_listas.json").unlink(missing_ok=True)
    w = datetime(2026, 11, 18, 23, 59)
    evs = [{"summary": "Actividad 5 - Forwarding - CC3301-1 Redes", "kind": "Actividad 5 - Forwarding", "course": "Redes",
            "when": w, "task": True},
           {"summary": "Actividad 6 - Fragmentación - CC3301-1 Redes", "kind": "Actividad 6 - Fragmentación",
            "course": "Redes", "when": w, "task": True}]
    jt = nuevo(H)
    jt._deliveries = lambda incluir_listas=True: ([e for e in evs if incluir_listas or not TL.is_done(e)], w)
    k = TL.key(evs[0])
    jt._tasks_cache = (time.time(), [{"key": k, "texto": "x"}, {"key": TL.key(evs[1]), "texto": "y"}])
    r = jt.task_done_action(k)
    if not re.search(r"^Marqué como lista Actividad 5 - Forwarding de Redes\. .*«desmarca la Actividad 5 - Forwarding»", r["reply"]):
        errs.append(f"respuesta: {r['reply']!r}")
    if not TL.is_done(evs[0]) or TL.is_done(evs[1]):
        errs.append("debía quedar lista solo la Actividad 5")
    if [t["key"] for t in jt._tasks_cache[1]] != [TL.key(evs[1])]:
        errs.append(f"la pestaña debía quitarla al tiro: {jt._tasks_cache}")
    if "ya no está pendiente" not in jt.task_done_action(k)["reply"]:
        errs.append("marcar dos veces debía decir que ya no está pendiente")
    if "ya no está pendiente" not in jt.task_done_action("inventada|x|2026-01-01")["reply"]:
        errs.append("una clave inventada no debe marcarse")
    if len(TL.match("las tareas de redes del martes", evs)) != 2:
        errs.append("«del martes» (las de Redes son el miércoles) debía ignorar el día y tomar las 2")
    if len(TL.match("la actividad seis", evs)) != 1 or TL.match("la actividad 9", evs):
        errs.append("buscar por número")
    for no in ("ya terminé de comer", "terminé el libro", "marca esto", "qué tareas tengo"):
        if TL.parse(no):
            errs.append(f"no es marcar tarea: {no!r}")
    html = (HERE / "hud.html").read_text(encoding="utf-8")
    if "taskDoneBtn" not in html or '"/api/task_done"' not in html:
        errs.append("falta el ✓ en la pestaña TAREAS")
    (tmp / "tareas_listas.json").unlink(missing_ok=True)
    out.append(("tareas listas: el ✓ de la pestaña TAREAS", errs))
    out += pruebas_telegram()
    out += pruebas_tg_api()
    return out


def pruebas_tg_api() -> list[tuple[str, list[str]]]:
    """Telegram oculto (atlas_tg_api): destinatario exacto, y volver a la app solo si es seguro que no se envió."""
    import types as _ty

    import atlas_tg_api as T

    out = []
    U = lambda **k: _ty.SimpleNamespace(**{"username": None, "usernames": None, "phone": None, "deleted": False, **k})  # noqa: E731
    errs = []
    if T.check_match("@benji", U(username="Benji")):
        errs.append("@benji no calzó con Benji")
    if not T.check_match("@benji", U(username="benji2")):
        errs.append("@benji calzó con benji2")
    if T.check_match("+56912345678", U(phone="56912345678")):
        errs.append("el mismo teléfono no calzó")
    if not T.check_match("+56912345678", U(phone="56987654321")):
        errs.append("otro teléfono calzó")
    if not T.check_match("+56912345678", U()):
        errs.append("teléfono oculto sin búsqueda por número calzó")
    if T.check_match("+56912345678", U(), by_phone_lookup=True):
        errs.append("teléfono oculto encontrado por ese número no calzó")
    if not T.check_match("@x", None) or not T.check_match("@x", U(username="x", deleted=True)):
        errs.append("aceptó un destinatario inexistente o eliminado")
    out.append(("Telegram oculto: solo envía al usuario o número exacto de la libreta", errs))

    errs = []
    old = T._python
    try:
        T._python = lambda: sys.executable + "_no_existe"  # no se puede lanzar: no se envió nada
        r = T.send("@x", "hola")
        if r.get("ok") or not r.get("fallback"):
            errs.append(f"si no arranca debería volver a la app: {r}")
    finally:
        T._python = old
    pc = (HERE.parent / "src" / "src" / "openjarvis" / "tools" / "atlas_pc.py").read_text(encoding="utf-8")
    i = pc.find("def _telegram(")
    body = pc[i:i + 2500]
    if "TGA.send" not in body or 'not r.get("fallback")' not in body or body.find("TGA.send") > body.find("_tg_send_impl"):
        errs.append("atlas_pc._telegram no prueba primero la vía oculta o no respeta fallback")
    out.append(("Telegram oculto: si falla sin enviar usa la app; si quizás envió, no reintenta", errs))
    return out



def pruebas_telegram() -> list[tuple[str, list[str]]]:
    """Telegram: solo el chat del dueño, botones para confirmar y nada sin confirmar. Sin red: sesión falsa."""
    import time as _t

    import atlas_telegram as T

    OWNER, OTRO = 111, 222

    class Sesion:
        def __init__(self):
            self.calls = []

        def post(self, url, json=None, data=None, files=None, timeout=0):
            method = url.rsplit("/", 1)[-1]
            self.calls.append((method, json or data or {}))
            return types.SimpleNamespace(status_code=200, content=b"1", text="",
                                         json=lambda: {"ok": True, "result": {"message_id": 5}})

        def enviados(self, metodo="sendMessage"):
            return [p for m, p in self.calls if m == metodo]

    class Herramienta:
        def __init__(self):
            self.hecho = []
            self.spec = types.SimpleNamespace(name="pc")

        def execute(self, **params):
            self.hecho.append(params)
            return types.SimpleNamespace(success=True, content="Listo.", metadata={})

    class AtlasFalso:
        def __init__(self):
            self.pending = None
            self.voice = None
            self.textos = []
            self.tool = Herramienta()

        def chat(self, text):
            self.textos.append(text)
            if "apaga" in text:
                self.pending = {"tool": self.tool, "params": {"action": "shutdown"}, "summary": "Apagar el PC"}
                return {"reply": "Preparado, señor: apagar el pc. Confírmelo en pantalla o dígame «sí»."}
            return {"reply": "Son las nueve, señor."}

        def confirm(self, accept):
            pend, self.pending = self.pending, None
            if not accept:
                return {"reply": "Entendido, señor. Cancelé la acción; no se modificó nada."}
            pend["tool"].execute(**pend["params"])
            return {"reply": "Hecho, señor."}

    def msg(texto, de=OWNER, chat=None, tipo="private", fecha=None):
        return {"update_id": 1, "message": {"text": texto, "date": int(fecha or _t.time()), "from": {"id": de},
                                            "chat": {"id": chat or de, "type": tipo}}}

    def nuevo():
        j, s = AtlasFalso(), Sesion()
        return j, s, T.TelegramBridge(j, {"token": "x", "chat_id": OWNER, "voz": "nunca"}, log=lambda *_: None, session=s)

    out = []
    j, s, b = nuevo()
    b.handle(msg("qué hora es", de=OTRO))
    b.handle(msg("qué hora es", de=OTRO, chat=OWNER))
    b.handle(msg("qué hora es", de=OWNER, chat=-5, tipo="group"))
    out.append(("telegram ignora a quien no es el dueño, sin responderle",
                [] if not j.textos and not s.calls else [f"textos {j.textos}, llamadas {s.calls}"]))
    b.handle(msg("qué hora es", fecha=_t.time() - 3600))
    out.append(("telegram ignora mensajes viejos (de cuando Atlas estaba cerrado)", [] if not j.textos else [str(j.textos)]))
    b.handle(msg("qué hora es"))
    env = s.enviados()
    out.append(("telegram responde al dueño", [] if j.textos == ["qué hora es"] and env and env[-1]["text"] == "Son las nueve, señor."
                                           else [f"{j.textos} {env}"]))
    # acción que modifica: botones; botón ajeno o con otro código no hace nada; el correcto sí
    b.handle(msg("apaga el pc"))
    env = s.enviados()[-1]
    kb = (env.get("reply_markup") or {}).get("inline_keyboard") or [[]]
    errs = [] if len(kb[0]) == 2 and "pantalla" not in env["text"] and "botones" in env["text"] else [f"mensaje: {env}"]
    nonce = j.pending.get("tg_nonce", "") if j.pending else ""
    cb = lambda data, de=OWNER: {"update_id": 2, "callback_query": {"id": "c", "data": data, "from": {"id": de},  # noqa: E731
                                                                    "message": {"message_id": 5, "chat": {"id": OWNER}}}}
    b.handle(cb("ok:" + nonce, de=OTRO))
    b.handle(cb("ok:000000"))
    if j.tool.hecho:
        errs.append("se ejecutó con un botón ajeno o con otro código")
    if not j.pending:
        errs.append("un botón inválido no debe borrar la acción pendiente")
    b.handle(cb("ok:" + nonce))
    if j.tool.hecho != [{"action": "shutdown"}] or j.pending:
        errs.append(f"el botón Sí no ejecutó: {j.tool.hecho}")
    b.handle(cb("ok:" + nonce))
    if len(j.tool.hecho) != 1:
        errs.append("apretar Sí dos veces la ejecutó dos veces")
    out.append(("telegram confirma con botones y solo el botón correcto ejecuta", errs))
    # botón No y botones vencidos
    j, s, b = nuevo()
    b.handle(msg("apaga el pc"))
    nonce = j.pending["tg_nonce"]
    b.handle(cb("no:" + nonce))
    errs = [] if not j.tool.hecho and not j.pending else ["el No ejecutó o dejó la acción pendiente"]
    b.handle(msg("apaga el pc"))
    j.pending["tg_t"] -= T.BUTTON_TTL + 1
    b.handle(cb("ok:" + j.pending["tg_nonce"]))
    if j.tool.hecho or j.pending:
        errs.append("un botón vencido no debe ejecutar")
    out.append(("telegram: el No cancela y los botones vencen a los 10 minutos", errs))
    # acción esperando en la pantalla del PC: Telegram no la confirma
    j, s, b = nuevo()
    j.pending = {"tool": j.tool, "params": {"action": "shutdown"}, "summary": "Apagar el PC"}
    b.handle(msg("sí"))
    out.append(("telegram no confirma una acción que espera en la pantalla del PC",
                [] if not j.tool.hecho and not j.textos and "pantalla del PC" in s.enviados()[-1]["text"]
                else [f"hecho {j.tool.hecho}, textos {j.textos}"]))
    # el audio de respuesta
    errs = []
    for cfg, voz, esperado in (({"voz": "si_nota"}, True, True), ({"voz": "si_nota"}, False, False),
                               ({"voz": "siempre"}, False, True), ({"voz": "nunca"}, True, False)):
        if T.wants_voice(cfg, voz) != esperado:
            errs.append(f"{cfg} nota={voz}")
    out.append(("telegram responde con audio según la opción elegida", errs))
    return out

# ----------------------------------------------------------------------------- misma orden, otras palabras
# Cada frase de CASOS, dicha de otra forma («quiero que…», «¿podrías…?», «¿me puedes…?», «oye Atlas, …», «…, por
# favor», o con otro verbo que significa lo mismo), debe ir a la misma regla. Cambiar una palabra no puede cambiar lo
# que hace Atlas. (Antes de 0.110: 191 de 862 variantes se iban a otra regla o a ninguna.)
_V_FORMAS = {  # imperativo -> (subjuntivo, infinitivo)
    "agenda": ("agendes", "agendar"), "agéndame": ("me agendes", "agendarme"), "añade": ("añadas", "añadir"),
    "agrega": ("agregues", "agregar"), "pon": ("pongas", "poner"), "ponme": ("me pongas", "ponerme"),
    "reproduce": ("reproduzcas", "reproducir"), "borra": ("borres", "borrar"), "elimina": ("elimines", "eliminar"),
    "cancela": ("canceles", "cancelar"), "mueve": ("muevas", "mover"), "cambia": ("cambies", "cambiar"),
    "cámbiale": ("le cambies", "cambiarle"), "saca": ("saques", "sacar"), "quita": ("quites", "quitar"),
    "manda": ("mandes", "mandar"), "mándale": ("le mandes", "mandarle"), "envía": ("envíes", "enviar"),
    "envíale": ("le envíes", "enviarle"), "escribe": ("escribas", "escribir"), "escríbele": ("le escribas", "escribirle"),
    "dile": ("le digas", "decirle"), "llama": ("llames", "llamar"), "abre": ("abras", "abrir"), "cierra": ("cierres", "cerrar"),
    "busca": ("busques", "buscar"), "marca": ("marques", "marcar"), "recuérdame": ("me recuerdes", "recordarme"),
    "avísame": ("me avises", "avisarme"), "dime": ("me digas", "decirme"), "dame": ("me des", "darme"),
    "muéstrame": ("me muestres", "mostrarme"), "léeme": ("me leas", "leerme"), "lee": ("leas", "leer"),
    "revisa": ("revises", "revisar"), "apaga": ("apagues", "apagar"), "sube": ("subas", "subir"), "baja": ("bajes", "bajar"),
    "renombra": ("renombres", "renombrar"), "resume": ("resumas", "resumir"), "resúmeme": ("me resumas", "resumirme"),
    "hazme": ("me hagas", "hacerme"), "guarda": ("guardes", "guardar"), "anota": ("anotes", "anotar"), "crea": ("crees", "crear"),
    "actualiza": ("actualices", "actualizar"), "olvida": ("olvides", "olvidar"), "responde": ("respondas", "responder"),
}
_V_SINONIMOS = [["agrega", "añade", "suma", "incluye"], ["ponme", "reprodúceme", "tócame"], ["borra", "elimina", "quita"],
                ["cancela", "anula"], ["muéstrame", "enséñame"], ["recuérdame", "avísame"], ["manda", "envía"],
                ["mándale", "envíale", "escríbele"], ["abre", "inicia", "lanza"], ["cierra", "termina"], ["cambia", "modifica"]]


def variantes(frase: str) -> list[str]:
    f = frase.strip()
    out = [f"Oye Atlas, {f[0].lower() + f[1:]}", re.sub(r"([.?!]*)$", r", por favor\1", f, count=1)]
    m = re.match(r"^([¿¡]?)(\w+)\b(.*)$", f)
    if m and not m.group(1):
        for g in _V_SINONIMOS:
            if m.group(2).lower() in g:
                out += [w[:1].upper() + w[1:] + m.group(3) for w in g if w != m.group(2).lower()]
    if m and m.group(2).lower() in _V_FORMAS:
        sub, inf = _V_FORMAS[m.group(2).lower()]
        rest = m.group(3).rstrip(".?!")
        out += [f"Quiero que {sub}{rest}", f"¿Podrías {inf}{rest}?", f"¿Me puedes {inf}{rest}?", f"Necesito que {sub}{rest}"]
    return out


def pruebas_detener(H) -> list[tuple[str, list[str]]]:
    """Botón ■: suelta el turno que está pensando al tiro y no deja nada pendiente (usuario, 15-11-2026)."""
    import threading

    errs = []
    j = nuevo(H)
    j.hush_voice = lambda page=True: None

    def lento(text):
        time.sleep(1.5)
        j.pending = {"summary": "Enviar algo"}
        return {"reply": "respuesta tardía"}

    j.chat = lento
    threading.Timer(0.3, j.stop_turn).start()
    t0 = time.time()
    out = j.chat_cancelable("hola")
    if not out.get("detenido"):
        errs.append(f"no quedó detenido: {out}")
    if time.time() - t0 > 1.0:
        errs.append(f"tardó {time.time() - t0:.1f} s en soltar el turno")
    time.sleep(1.6)
    if j.pending:
        errs.append("quedó una confirmación colgando del turno detenido")
    j.chat = lambda text: {"reply": "ok"}
    out = j.chat_cancelable("otra")
    if out.get("reply") != "ok":
        errs.append(f"el turno siguiente no respondió: {out}")
    return [("botón ■ corta el turno que piensa", errs)]


def pruebas_http(H) -> list[tuple[str, list[str]]]:
    """El servidor responde de verdad por HTTP (0.180 dejó a Atlas sin arrancar: un error en do_GET tumbaba todo)."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    errs = []
    here0 = H.HERE
    H.HERE = Path(__file__).resolve().parent   # las pruebas apuntan HERE a una carpeta temporal sin hud.html ni íconos
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path, tipo in (("/favicon.ico?v=0.180", "image/x-icon"), ("/icon.png?v=0.180", "image/png"), ("/favicon.ico", "image/x-icon"), ("/icon-32.png?v=1", "image/png"), ("/icon-16.png", "image/png")):
            try:
                with urllib.request.urlopen(base + path, timeout=5) as r:
                    if r.status != 200 or r.headers.get("Content-Type") != tipo:
                        errs.append(f"{path}: {r.status} {r.headers.get('Content-Type')}")
            except Exception as exc:  # noqa: BLE001
                errs.append(f"{path}: {type(exc).__name__}: {exc}")
        try:
            with urllib.request.urlopen(base + "/", timeout=5) as r:
                html = r.read().decode("utf-8")
            if "__ATLAS_VERSION__" in html or f"favicon.ico?v={H.HUD_VERSION}" not in html:
                errs.append("la página no lleva la versión en el ícono")
        except Exception as exc:  # noqa: BLE001
            errs.append(f"/: {type(exc).__name__}: {exc}")
    finally:
        H.HERE = here0
        srv.shutdown()
        srv.server_close()
    # 18-11-2026: la versión de Atlas: una sola fuente (archivo VERSION), /api/version igual al archivo y visible en el HUD
    e2 = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    H.HERE = Path(__file__).resolve().parent
    try:
        v_arch = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8-sig").strip()
        if not re.fullmatch(r"\d+(\.\d+){0,3}", v_arch):
            e2.append(f"VERSION debe tener una sola línea con la versión: {v_arch!r}")
        if H.VERSION_ARCHIVO != Path(__file__).resolve().parent.parent / "VERSION" or H.version_atlas() != v_arch:
            e2.append(f"el servidor debe leer %LOCALAPPDATA%\\Atlas\\VERSION: {H.version_atlas()!r} vs {v_arch!r}")
        rq = urllib.request.Request(base + "/api/version", headers={"X-Atlas-Token": H.TOKEN})
        with urllib.request.urlopen(rq, timeout=5) as r:
            jv = json.loads(r.read().decode("utf-8"))
        if jv != {"version": v_arch} or H.HUD_VERSION != v_arch:
            e2.append(f"/api/version debe ser igual al archivo: {jv} vs {v_arch!r}")
        try:
            urllib.request.urlopen(base + "/api/version", timeout=5)
            e2.append("/api/version sin token debe rechazarse")
        except urllib.error.HTTPError as e_:
            if e_.code != 403:
                e2.append(f"/api/version sin token: {e_.code}")
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        # versión bajo la palabra ATLAS (18-11-2026): en el logo del encabezado y en el de la carga, leída de /api/version
        _marca = html.split('<span class="marca"', 1)[-1].split("</span>", 1)[0]
        if not _marca.endswith('</svg><span class="mver" hidden>') or 'aria-label="ATLAS"' not in _marca:
            e2.append("el logo del encabezado debe llevar la versión bajo ATLAS (.mver)")
        if """'<span class="mver" hidden></span>INICIANDO SISTEMAS<small>""" not in html or "atlasVerPinta();" not in html:
            e2.append("la pantalla de carga debe llevar la versión bajo ATLAS (.mver)")
        _fv = html.split("function atlasVer()", 1)[-1].split("atlasVerPinta();", 1)[0]
        if 'api("/api/version")' not in _fv or "if (!v) return;" not in _fv or 'e.textContent = "v" + v; e.hidden = false;' not in _fv:
            e2.append("la versión bajo ATLAS debe venir de /api/version y no mostrarse si falla")
        if "__ATLAS_VERSION__" in _fv or re.search(r'mver[^\n]*>v?\d+\.\d', html):
            e2.append("la versión bajo ATLAS no debe ir escrita a mano")
        if 'ver.id = "ajVer"; ver.hidden = true;' not in html or 'ver.textContent = "Atlas v" + v' not in html \
                or "nav.append(q, list, bi, ver);" not in html:
            e2.append("el pie de Ajustes debe decir «Atlas v…» leyendo /api/version")
        import atlas_crear_exe as _ACEv
        _nv = [int(x) for x in v_arch.split(".")]
        if list(_ACEv._numeros()) != (_nv + [0, 0, 0, 0])[:4] or ".".join(map(str, _ACEv._numeros())).encode("utf-16-le") not in _ACEv._version():
            e2.append(f"Atlas.exe debe tomar su versión de VERSION: {_ACEv._numeros()} vs {v_arch!r}")
        src_v = (Path(__file__).resolve().parent / "hud_server.py").read_text(encoding="utf-8")
        if re.search(r'^HUD_VERSION = "', src_v, re.M):
            e2.append("hud_server.py no debe volver a tener la versión escrita a mano (va en VERSION)")
        import atlas_faltantes as _JFv
        if _JFv._version_en_disco() != v_arch:
            e2.append(f"Instalación debe leer el mismo archivo VERSION: {_JFv._version_en_disco()!r}")
    except Exception as exc:  # noqa: BLE001
        e2.append(f"versión: {type(exc).__name__}: {exc}")
    finally:
        H.HERE = here0
        srv.shutdown()
        srv.server_close()
    return [("servidor HTTP: ícono con ?v= y página", errs),
            ("versión de Atlas: una sola fuente (VERSION), /api/version igual al archivo; versión bajo la palabra ATLAS, en Ajustes y en Atlas.exe", e2)]


def pruebas_primer_inicio(H, tmp) -> list[tuple[str, list[str]]]:
    """Asistente de primer inicio (tras el instalador): se abre solo si primer_inicio.json lo pide, elige una voz
    instalada en voz.json, rechaza voces que no existen y al terminar no vuelve a aparecer."""
    import json as _j
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import atlas_primer_inicio as PI

    errs = []
    arch0, voz0 = PI.ARCHIVO, PI.VOZ_JSON
    PI.ARCHIVO, PI.VOZ_JSON = Path(tmp) / "primer_inicio.json", Path(tmp) / "voz_prueba.json"
    PI.ARCHIVO.write_text(_j.dumps({"pendiente": True, "saltados": ["canvas", "hermes", "inventada"]}), encoding="utf-8")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def pedir(body=None):
        req = urllib.request.Request(base + "/api/primer_inicio", data=_j.dumps(body).encode() if body is not None else None,
                                     headers={"X-Atlas-Token": H.TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return _j.loads(r.read().decode("utf-8"))

    try:
        d = pedir()
        if not d.get("pendiente") or d.get("saltados") != ["Canvas", "Hermes (gastos del banco)"]:
            errs.append(f"estado inicial: {d}")
        if pedir({"op": "voz", "perfil": "no_existe"}).get("ok"):
            errs.append("aceptó una voz que no existe")
        if PI.VOZ_JSON.exists():
            errs.append("escribió voz.json con una voz inválida")
        voces = d.get("voces") or []
        if voces:
            r = pedir({"op": "voz", "perfil": voces[0]["id"]})
            guardado = _j.loads(PI.VOZ_JSON.read_text(encoding="utf-8")).get("activa") if PI.VOZ_JSON.exists() else None
            if not r.get("ok") or guardado != voces[0]["id"]:
                errs.append(f"no guardó la voz elegida: {r} / {guardado}")
        if "error" not in pedir({"op": "muestra", "perfil": "no_existe"}):
            errs.append("muestra de una voz que no existe no dio error")
        if pedir({"op": "otra"}).get("ok"):
            errs.append("aceptó una operación desconocida")
        pedir({"op": "terminar", "como": "saltado"})
        d2 = pedir()
        if d2.get("pendiente"):
            errs.append("sigue pendiente después de terminar")
        PI.ARCHIVO.unlink()
        if pedir().get("pendiente"):
            errs.append("sin archivo (Atlas instalado a mano) no debe abrirse")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"{type(exc).__name__}: {exc}")
    finally:
        PI.ARCHIVO, PI.VOZ_JSON = arch0, voz0
        srv.shutdown()
        srv.server_close()
    html = (Path(__file__).resolve().parent / "hud.html").read_text(encoding="utf-8")
    for falta in ('id="primer"', "window.primerPendiente", "abrirPrimerInicio", "SALTAR TODO"):
        if falta not in html:
            errs.append(f"hud.html sin {falta}")
    return [("primer inicio: abre, elige voz, valida y no vuelve a aparecer", errs)]


def pruebas_variantes(H) -> list[tuple[str, list[str]]]:
    import contextlib
    import io

    import atlas_agenda

    out = []
    for titulo, pasos in CASOS:
        errs = []
        for frase, esperado, checks in pasos:
            if checks.get("keep_pending") or esperado == "modelo":
                continue
            j = nuevo(H)
            base = None
            for v in [frase] + variantes(frase):
                j.pending = None
                atlas_agenda._LAST = None
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        ruta = j.route(H.canonicalize_people(H.canonicalize(v)))[0]
                except Exception as exc:  # noqa: BLE001
                    ruta = f"error {type(exc).__name__}"
                if base is None:
                    base = ruta
                    if base != esperado:
                        break  # depende de lo dicho antes en esa conversación: aislada no sirve
                elif ruta != base:
                    errs.append(f"«{v}» fue a «{ruta}» (la original va a «{base}»)")
        out.append((f"variantes: {titulo}", errs))
    # Reglas que no se pisan (usos reales)
    j = nuevo(H)
    choques = [
        ("Quiero que me recuerdes en 20 minutos sacar la ropa", "recordatorio"),  # pedía fecha de un evento
        ("Recuérdame a las 6 que llame a mi mamá", "recordatorio"),  # «avísame a las 6…» era recordatorio y esto evento
        ("Avísame llamar al dentista el lunes a las 9", "calendario"),  # con día es evento, igual que «recuérdame»
        ("Pon una canción de mis favoritos", "pc"),  # se guardaba «Pon una canción» como artista
        ("Quiero que añadas a la reunión con Felipe al tipo y a Toño", "contactos"),  # pedía fecha de un evento nuevo
        ("Anota en el calendario un evento el próximo viernes de 10 y cuarto a doce", "calendario"),  # no son contactos
        ("¿Me puedes abrir youtube?", "pc"), ("Termina spotify", "pc"), ("Inicia Fortuna", "acceso"),
    ]
    errs = []
    for frase, esperado in choques:
        j.pending = None
        with contextlib.redirect_stdout(io.StringIO()):
            ruta = j.route(H.canonicalize_people(H.canonicalize(frase)))[0]
        if ruta != esperado:
            errs.append(f"«{frase}» fue a «{ruta}», se esperaba «{esperado}»")
    out.append(("reglas que no se pisan entre sí", errs))
    norm = {"Quiero que me pongas música de Ado": "Ponme música de Ado", "¿Me puedes agendar una reunión mañana?":
            "Agéndame una reunión mañana", "Oye Atlas, ¿qué tengo hoy?, por favor": "¿qué tengo hoy?",
            "Quiero que sepas que mi hermana es Paula": "Quiero que sepas que mi hermana es Paula",
            "Quiero que me llames señor": "Quiero que me llames señor", "¿Podrías decirme qué hora es?": "Dime qué hora es"}
    out.append(("formas indirectas -> orden directa", [f"{k!r} -> {H.normalize_order(k)!r}, se esperaba {v!r}"
                                                         for k, v in norm.items() if H.normalize_order(k) != v]))
    return out


def comprobar(j, ruta, res, esperado_ruta, checks) -> list[str]:
    errores = []
    if ruta != esperado_ruta:
        errores.append(f"ruta «{ruta}», se esperaba «{esperado_ruta}»")
    res = res or {}
    if "reply" in checks and not re.search(checks["reply"], res.get("reply", ""), re.S):
        errores.append(f"respuesta: {res.get('reply', '')[:230]!r}")
    if "hint" in checks and not re.search(checks["hint"], res.get("hint", ""), re.S):
        errores.append(f"instrucción: {res.get('hint', '')[:160]!r}")
    for tool in ("gmail", "pc"):
        fake = getattr(j, f"{tool}_raw")
        if tool in checks:
            last = fake.calls[-1] if fake.calls else {}
            same = lambda a, b: a.lower() == b.lower() if isinstance(a, str) and isinstance(b, str) else a == b  # noqa: E731
            falta = {k: v for k, v in checks[tool].items() if not same(last.get(k), v)}
            if falta:
                errores.append(f"{tool}: se esperaba {checks[tool]}, se llamó con {last or 'nada'}")
        if checks.get(f"no_{tool}") and fake.calls:
            errores.append(f"{tool}: no debía usarse y se llamó con {fake.calls[-1]}")
    if "pending" in checks and bool(j.pending) != checks["pending"]:
        errores.append("debía quedar esperando confirmación" if checks["pending"] else "no debía pedir confirmación")
    return errores


def main() -> int:
    H, tmp = preparar()
    total = fallas = 0
    try:
        for titulo, pasos in CASOS:
            j = nuevo(H)
            import atlas_agenda

            atlas_agenda._LAST = None
            (tmp / "recordatorios.json").unlink(missing_ok=True)
            (tmp / "tareas_listas.json").unlink(missing_ok=True)
            atlas_agenda._cache["https://calendario.invalid/a.ics"] = (1e18, _ics(tareas="tareas de U-Cursos" in titulo))
            print(f"\n{titulo}")
            for frase, esperado, checks in pasos:
                total += 1
                j.gmail_raw.calls.clear()
                j.pc_raw.calls.clear()
                if not checks.get("keep_pending"):
                    j.pending = None
                texto = H.canonicalize_people(H.canonicalize(frase))
                try:
                    ruta, res, _ = j.route(texto)
                    errores = comprobar(j, ruta, res, esperado, checks)
                    if checks.get("confirm") and j.pending:
                        j.refresh_inbox = lambda: None
                        j.confirm(True)
                except Exception as exc:  # noqa: BLE001
                    errores = [f"error {type(exc).__name__}: {exc}"]
                if errores:
                    fallas += 1
                    print(f"  FALLA  {frase}")
                    for e in errores:
                        print(f"         - {e}")
                else:
                    print(f"  ok     {frase}")
        print("\nRecordatorios: guardar y avisar")
        for nombre, errores in pruebas_directas(H, tmp) + pruebas_variantes(H) + pruebas_http(H) + pruebas_detener(H) \
                + pruebas_primer_inicio(H, tmp):
            total += 1
            if errores:
                fallas += 1
                print(f"  FALLA  {nombre}")
                for e in errores:
                    print(f"         - {e}")
            else:
                print(f"  ok     {nombre}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{total - fallas} de {total} pruebas pasaron." + ("" if not fallas else f"  {fallas} FALLARON."))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())

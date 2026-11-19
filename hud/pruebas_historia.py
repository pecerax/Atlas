"""Pruebas de atlas_historia sin datos reales: fechas dichas, fechas en nombres de fotos, Takeout y Cronología
sintéticos, privacidad. Uso: src\\.venv\\Scripts\\python.exe hud\\pruebas_historia.py"""
import json
import os
os.environ["ATLAS_PRUEBAS"] = "1"  # nada abre ventanas visibles
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_historia as H  # noqa: E402

HOY = date(2026, 11, 16)  # lunes
ok = fail = 0


def check(nombre, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"FALLA {nombre}: {got!r} != {want!r}")


d = lambda s: date.fromisoformat(s)  # noqa: E731
F = lambda t: H.fechas_en(t, HOY)  # noqa: E731
check("12 de marzo", F("¿qué estaba haciendo el 12 de marzo?"), (d("2026-03-12"), d("2026-03-12")))
check("doce de marzo", F("que hacía el doce de marzo"), (d("2026-03-12"), d("2026-03-12")))
check("diciembre sin año = pasado", F("qué hice el 20 de diciembre"), (d("2025-12-20"), d("2025-12-20")))
check("con año", F("qué hacía el 3 de mayo de 2024"), (d("2024-05-03"), d("2024-05-03")))
check("alrededor", F("qué hacía alrededor del 10 de octubre"), (d("2026-10-08"), d("2026-10-12")))
check("barra", F("dónde estaba el 5/4"), (d("2026-04-05"), d("2026-04-05")))
check("barra año", F("dónde estaba el 5/4/25"), (d("2025-04-05"), d("2025-04-05")))
check("ayer", F("qué hice ayer"), (d("2026-11-15"), d("2026-11-15")))
check("sábado pasado", F("qué hice el sábado pasado"), (d("2026-11-14"), d("2026-11-14")))
check("semana del", F("qué hice la semana del 4 de noviembre"), (d("2026-11-02"), d("2026-11-08")))
check("en marzo", F("qué hacía en marzo"), (d("2026-03-01"), d("2026-03-31")))
check("hace dos semanas", F("qué hacía hace dos semanas"), (d("2026-10-30"), d("2026-11-05")))
check("sin fecha", F("qué hora es"), None)

check("pregunta sí", H.es_pregunta("Atlas, ¿qué estaba haciendo el 12 de marzo?"), True)
check("pregunta dónde", H.es_pregunta("¿dónde estaba el sábado pasado?"), True)
check("no es pregunta: agenda futura", H.es_pregunta("¿qué tengo el 12 de marzo?"), False)
check("no es pregunta: sin fecha", H.es_pregunta("qué estaba haciendo"), False)

check("nombre WA", H.fecha_de_nombre("IMG-20210220-WA0002.jpg"), ("2021-02-20", ""))
check("nombre WA pc", H.fecha_de_nombre("WhatsApp Image 2026-10-17 at 17.08.49.jpeg"), ("2026-10-17", "17:08"))
check("nombre cámara", H.fecha_de_nombre("20240101_123456.jpg"), ("2024-01-01", "12:34"))
check("nombre captura", H.fecha_de_nombre("Screenshot_20250703-221501_Chrome.jpg"), ("2025-07-03", "22:15"))
check("nombre hash", H.fecha_de_nombre("112e32e8f0d3cea20d85a462f341944e.jpg"), None)
check("origen enviada", H._origen("x/WhatsApp Images/Sent/IMG-1.jpg"), "whatsapp enviada")
check("origen cámara", H._origen("x/storage/DCIM/Camera/a.jpg"), "cámara")

# Takeout y Cronología sintéticos, en una base temporal
tmp = Path(tempfile.mkdtemp())
H.DB_FILE = tmp / "h.db"
H.CONFIG_FILE = tmp / "c.json"
con = H.db()
n = H.importar_takeout_json(con, "Takeout/Chrome/History.json", {"Browser History": [
    {"title": "Ejemplo", "url": "https://www.example.com/a", "time_usec": 1700000000000000}]})
check("chrome", n, 1)
n = H.importar_takeout_json(con, "Takeout/YouTube y YouTube Music/historial/historial-de-reproducciones.json", [
    {"header": "YouTube", "title": "Viste Video de prueba", "time": "2025-03-12T15:00:00.000Z", "subtitles": [{"name": "Canal"}]}])
check("youtube", n, 1)
n = H.importar_takeout_json(con, "Takeout/Mi actividad/Búsqueda/MiActividad.json", [
    {"header": "Búsqueda", "title": "Buscaste clima santiago", "time": "2025-03-12T12:00:00Z"}])
check("busqueda", n, 1)
n = H.importar_takeout_json(con, "Timeline.json", {"semanticSegments": [
    {"startTime": "2025-03-12T09:00:00.000-03:00", "endTime": "2025-03-12T18:00:00.000-03:00",
     "visit": {"topCandidate": {"placeId": "X", "semanticType": "WORK", "placeLocation": {"latLng": "-33.45°, -70.66°"}}}},
    {"startTime": "2025-03-12T18:00:00.000-03:00", "endTime": "2025-03-12T18:40:00.000-03:00",
     "activity": {"topCandidate": {"type": "IN_SUBWAY"}, "distanceMeters": 8200}}]})
check("cronologia", n, 2)
con.commit()
rows = con.execute("SELECT fuente, titulo FROM items WHERE fecha='2025-03-12' ORDER BY hora").fetchall()
check("items del día", sorted(r[0] for r in rows), ["busqueda", "ubicacion", "ubicacion", "youtube"])
check("texto metro", any("metro 8,2 km" in r[1] for r in rows), True)
con.close()
dd = H.dia(d("2025-03-12"), correos=False)
dd["eventos"] = []
txt = H.texto_para_modelo(dd)
check("texto para modelo trae el trabajo", "el trabajo" in txt, True)
check("dónde va primero, con confianza", txt.index("DÓNDE") < txt.index("ACTIVIDAD EN PANTALLA") and "confianza alta" in txt, True)
check("búsquedas como sesión, no como lugar", "búsqueda (1): clima santiago" in txt.split("ACTIVIDAD")[1], True)
check("limpia «Buscaste»", H.limpiar_titulo("Buscaste cambiar de escritorio"), "buscó cambiar de escritorio")
check("url -> dominio", H.limpiar_titulo("visitó https://maps.google.com/maps?client=x&q=y"), "visitó maps.google.com")
check("título vacío fuera", H.limpiar_titulo("Viste ㅤㅤ ᵒ"), None)
check("aviso fuera", H.limpiar_titulo("1 notificación Temas incluidos: Tiempo"), None)
its = [{"fuente": "busqueda", "fecha": "2025-03-12", "hora": h, "titulo": "buscó tema " + h, "detalle": "Búsqueda|"}
       for h in ("10:32", "10:41", "10:50", "11:07", "15:19")]
ss = H.sesiones(its, "2025-03-12")
check("sesiones", [(z["tipo"], z["ini"], z["fin"], z["n"]) for z in ss], [("búsqueda", "10:32", "11:07", 4), ("búsqueda", "15:19", "15:19", 1)])
mus = [{"fuente": "youtube", "fecha": "2025-03-12", "hora": "10:00", "titulo": "vio Tema", "detalle": "YouTube|Banda - Topic"}]
check("la música no se muestra", H.sesiones(mus, "2025-03-12") + H.cuartos(mus, "2025-03-12"), [])
from datetime import datetime as DT
mom = [DT(2025, 3, 11, 23, 50), DT(2025, 3, 12, 0, 20), DT(2025, 3, 12, 0, 40), DT(2025, 3, 12, 0, 55),
       DT(2025, 3, 12, 8, 30), DT(2025, 3, 12, 8, 45), DT(2025, 3, 12, 12, 0)]
sn = H.sueno(mom, d("2025-03-12"))
check("sueño", (sn["desde"], sn["hasta"], sn["horas"], sn["confianza"]), ("2025-03-12 00:55", "2025-03-12 08:30", 7.6, "media"))
dd2 = {"fotos": [], "eventos": [], "correos": [{"fecha": "2025-03-12", "hora": "21:10", "enviado": False, "quien": "Uber",
       "asunto": "Tu viaje del miércoles"}], "items": [{"fuente": "maps", "fecha": "2025-03-12", "hora": "19:00",
       "titulo": "Indicaciones a Plaza Ñuñoa", "detalle": "Maps"}, {"fuente": "actividad", "fecha": "2025-03-12", "hora": "",
       "titulo": "Actualizaste app", "detalle": "Google Play Store"}]}
r2 = H.clasificar(dd2)["2025-03-12"]
check("uber y maps son pistas de lugar", len(r2["lugares"]), 2)
check("play store es ruido", any("Play" in t for _, t in r2["contexto"]["otros"]) or any("Play" in t for _, t in r2["hechos"]), False)

# chats de WhatsApp exportados (formatos de Android en español)
ms = H.leer_chat_whatsapp("12/3/25, 20:15 - Ana: ¿dónde estás?\n12/3/25, 20:16 - Yo Mismo: llegando al metro\nsegunda línea\n"
                          "12/03/2025, 8:30 p. m. - Yo Mismo: ubicación: https://maps.google.com/?q=-33.4500,-70.6600\n")
check("wa mensajes", len(ms), 3)
check("wa multilínea", ms[1]["texto"], "llegando al metro segunda línea")
check("wa p. m.", (ms[2]["fecha"], ms[2]["hora"]), ("2025-03-12", "20:30"))
H._chats_whatsapp = lambda: [("Ana", "12/3/25, 20:15 - Ana: hola\n12/3/25, 20:16 - Yo Mismo: llegando al metro\n"
                                     "12/3/25, 20:30 - Yo Mismo: ubicación: https://maps.google.com/?q=-33.4500,-70.6600")]
con = H.db()
check("chats desactivados: no se importa nada", H.importar_whatsapp(con), 0)  # pedido 17-11: solo horas
check("chat_hora cuenta como uso", H.tipo_digital({"fuente": "chat_hora", "titulo": "", "detalle": ""}), "chat")
H.CHATS_SOLO_HORAS = False  # el importador antiguo sigue probado por si algún día se reactiva
check("wa importa solo lo suyo + ubicación", H.importar_whatsapp(con), 2)
con.commit()
r3 = H.clasificar({"fotos": [], "eventos": [{"fecha": "2025-03-12", "hora": "10:15", "titulo": "Cátedra Redes", "lugar": "",
                                              "clase": True, "curso": "Redes"}],
                   "correos": [{"fecha": "2025-03-12", "hora": "23:05", "enviado": False, "quien": "Uber", "asunto": "Tu viaje",
                                "viaje": {"origen": "Av. Uno 1", "destino": "Calle Dos 2", "inicio": "22:40", "fin": "23:00"}}],
                   "items": [dict(r) for r in con.execute("SELECT * FROM items WHERE fecha='2025-03-12'")]
                   + [{"fuente": "gasto", "fecha": "2025-03-12", "hora": "", "titulo": "cargo de 8.500 pesos en Sushi X",
                       "detalle": "Comida|compra"},
                      {"fuente": "gasto", "fecha": "2025-03-12", "hora": "", "titulo": "cargo de 5.990 pesos en Netflix",
                       "detalle": "Suscripciones|compra"}]})["2025-03-12"]
lug = " | ".join(t + " " + c for _, t, c in r3["lugares"])
check("uber con recibo = alta", "viaje en Uber de Av. Uno 1 a Calle Dos 2" in lug and "alta (recibo" in lug, True)
check("clase = baja", "probablemente en la universidad" in lug, True)
check("comida = media", "compró en Sushi X" in lug, True)
check("suscripción no es lugar", "Netflix" in lug, False)
check("ubicación compartida = alta", "compartió su ubicación con contacto A" in lug, True)
check("anonimizado: «Ana» no queda guardada", any("Ana" in (r[0] + (r[1] or "")) for r in
      H.db().execute("SELECT titulo, detalle FROM items WHERE fuente LIKE 'whatsapp%'")), False)
check("chat como contexto", len(r3["contexto"]["chats"]), 1)
con.close()

# lugares repetidos de Maps se juntan y se acortan
L = [("10:43", "miró en Maps «Calle Falsa 123»", "baja (miró un lugar; quizás fue)"),
     ("10:43", "buscó en Maps «Calle Falsa 123, 7500000 Ñuñoa, Región Metropolitana»", "baja (buscó un lugar; quizás fue)"),
     ("10:49", "pidió indicaciones en Maps para ir a Calle Falsa 123, 7500000 Ñuñoa, Región Metropolitana", "media (iba o pensaba ir)"),
     ("10:49", "pidió indicaciones en Maps para ir a Calle Falsa 123, 7500000 Ñuñoa, Región Metropolitana", "media (iba o pensaba ir)"),
     ("12:45", "evento «Cátedra» en G304", "media (estaba agendado)"),
     ("18:09", "pidió indicaciones en Maps para ir a Calle Falsa 123, Ñuñoa", "media (iba o pensaba ir)")]
check("maps agrupado", H.agrupar_lugares(L), [("10:43–10:49", "pidió ruta a Calle Falsa 123, Ñuñoa", "media (iba o pensaba ir)"),
      ("12:45", "evento «Cátedra» en G304", "media (estaba agendado)"), ("18:09", "pidió ruta a Calle Falsa 123, Ñuñoa", "media (iba o pensaba ir)")])

# bloques del día (caso real del viernes 13-11: durmió poco en la U, cátedra, control 14-16, casa de un amigo, Cabify de trasnoche)
from datetime import timedelta as _td
con = H.db()
for i, (hh, t) in enumerate([("10:43", "Buscó Calle Falsa 123, Ñuñoa"), ("10:49", "Indicaciones a Calle Falsa 123, Ñuñoa"),
                             ("18:09", "Indicaciones a Calle Falsa 123, Ñuñoa"), ("18:31", "Indicaciones a Calle Falsa 123, Ñuñoa")]):
    con.execute("INSERT OR REPLACE INTO items(id,fuente,fecha,hora,titulo,detalle) VALUES(?,?,?,?,?,?)", (f"bq{i}", "maps", "2001-02-09", hh, t, ""))
con.commit(); con.close()
H.casa_conocida = lambda: "calle ejemplo"
H._chat_dice = lambda f, m: [{"hora": "04:30", "lugar": "u", "actividad": "estudiando"}, {"hora": "08:40", "lugar": "u", "actividad": "estudiando"}]
D = {"items": [], "eventos": [
        {"fecha": "2001-02-09", "hora": "10:15", "fin": "11:45", "titulo": "Cátedra Ciberseguridad", "lugar": "B01", "tipo": "clase"},
        {"fecha": "2001-02-09", "hora": "14:00", "fin": "16:00", "titulo": "Control 2 Lenguajes", "lugar": "", "tipo": "evaluacion"},
        {"fecha": "2001-02-09", "hora": "14:00", "fin": "16:00", "titulo": "Control Lenguajes", "lugar": "", "tipo": "evaluacion"}],
     "correos": [], "sueno": {"2001-02-09": {"desde": "2001-02-09 04:40", "hasta": "2001-02-09 08:40", "horas": 4.0, "confianza": "media"}},
     "_previo": {"eventos": [], "correos": [], "despues": [
        {"fecha": "2001-02-10", "hora": "02:35", "quien": "Cabify <recibos@cabify.com>", "viaje":
         {"origen": "Calle Falsa, Ñuñoa", "destino": "Calle Ejemplo 100, Comuna Ejemplo", "inicio": "00:17", "fin": "00:34"}}]}}
BQ = H.bloques(D, date(2001, 2, 9))
fila = lambda f: [b for b in BQ if b["fila"] == f]
check("bloques: Cabify de trasnoche cuenta en el día", [(b["ini"], b["fin"]) for b in fila("viaje")], [("24:17", "24:34")])
check("bloques: termina en su casa", fila("lugar")[-1]["titulo"], "En su casa")
amigo = [b for b in fila("lugar") if "Falsa" in b["titulo"]]
check("bloques: dirección buscada + origen del viaje = visita segura", (len(amigo), amigo[0]["conf"], amigo[0]["ini"], amigo[0]["fin"]),
      (1, "alta", "19:01", "24:17"))
check("bloques: un solo control a las 14", len([b for b in fila("actividad") if "rindió" in b["titulo"]]), 1)
check("bloques: la cátedra es como alumno y poco segura", [b["conf"] for b in fila("actividad") if "alumno" in b["titulo"]], ["baja"])
check("bloques: en la U desde que despertó hasta antes de ir al amigo",
      [(b["ini"], b["fin"]) for b in fila("lugar") if b["titulo"] == "En la U"], [("08:40", "18:31")])
check("bloques: durmió poco en la U", ("la U" in fila("sueno")[0]["titulo"], "(poco)" in fila("sueno")[0]["titulo"]), (True, True))
H._chat_dice, _cd = (lambda f, m: [{"hora": "08:40", "lugar": "u", "actividad": "voy a la u"}]), H._chat_dice
check("durmió en su casa salvo evidencia fuerte (un solo «u» al despertar no basta)",
      [b["titulo"].endswith("en su casa (poco)") for b in H.bloques(D, date(2001, 2, 9)) if b["fila"] == "sueno"], [True])
H._chat_dice = _cd
check("bloques: nadie la dicta", any("dicta" in b["titulo"] for b in BQ), False)
check("misma dirección sin número", H.misma_direccion("calle falsa", "calle falsa 123"), True)
check("distinta dirección", H.misma_direccion("calle falsa", "calle verdadera 12"), False)

# poco celular = fuera u ocupado (idea del usuario; números reales del 13-11)
U = [{"h": h, "n": n, "base": b} for h, n, b in [(9, 4, 8.5), (10, 9, 4.2), (11, 0, 7.2), (12, 0, 2.0), (13, 3, 2.9), (14, 0, 2.6),
     (15, 0, 4.0), (16, 4, 5.0), (17, 11, 4.0), (18, 4, 2.5), (19, 1, 1.5), (20, 0, 3.2), (21, 2, 3.5), (22, 4, 4.1)]]
check("tramos quietos: clase, control y casa del amigo", [(a, b) for a, b, *_ in H.tramos_quietos(U, (9, 27))], [(11, 13), (14, 16), (19, 22)])
check("tramos quietos: dormido no cuenta", H.tramos_quietos(U, (17, 19)), [])
D2 = dict(D, uso={"2001-02-09": [{"h": h, "n": 0 if 19 <= h < 22 else 5, "base": 5} for h in range(30)]})
BQ2 = H.bloques(D2, date(2001, 2, 9))
check("el celular es señal interna: no aparece en la línea", any(b["fila"] == "quieto" or "celular" in b["titulo"].lower() for b in BQ2), False)
D3 = dict(D, uso={"2001-02-09": [{"h": h, "n": 0 if 9 <= h < 11 else 5, "base": 5} for h in range(30)]})
check("poco celular estando en la U no inventa «fuera»", any("fuera" in b["titulo"] for b in H.bloques(D3, date(2001, 2, 9))), False)
H._chat_dice = lambda f, m: []
D4 = {"items": [], "eventos": [], "correos": [], "sueno": {}, "_previo": {"eventos": [], "correos": [], "despues": []},
      "uso": {"2001-02-11": [{"h": h, "n": 0 if 15 <= h < 18 else 5, "base": 5} for h in range(30)]}}
check("poco celular sin otra pista = probablemente fuera de casa (baja)",
      [(b["ini"], b["fin"], b["fila"], b["conf"]) for b in H.bloques(D4, date(2001, 2, 11)) if "fuera" in b["titulo"]],
      [("15:00", "18:00", "lugar", "baja")])

# diagnóstico: el usuario marca bloques y la regla se ajusta
H._chat_dice = lambda f, m: [{"hora": "08:40", "lugar": "u", "actividad": "estudiando"}]
amigo = [b for b in H.bloques(D, date(2001, 2, 9)) if "Falsa" in b["titulo"]][0]
for i, (v, ci, ct) in enumerate([("corregido", "18:00", ""), ("corregido", "18:00", ""), ("corregido", "18:00", ""), ("ok", "", "")]):
    H.marcar_bloque({"id": f"t{i}", "fecha": "2001-02-0" + str(i + 1), "veredicto": v, "bloque": amigo, "c_ini": ci, "c_titulo": ct})
H.marcar_bloque({"fecha": "2001-02-09", "veredicto": "faltante", "c_ini": "21:00", "c_fin": "22:00", "c_titulo": "cena"})
R = H.resultado_revision()
check("diagnóstico: cuenta ok, solo hora y faltantes", (R["n"], R["ok"], R["solo_hora"], R["mal"], R["faltantes"]), (4, 1, 3, 0, 1))
amigo2 = [b for b in H.bloques(D, date(2001, 2, 9)) if "Falsa" in b["titulo"]][0]
check("diagnóstico: la hora se corre según sus correcciones", amigo2["ini"], "18:00")
check("diagnóstico: dice cuántas acierta", "acierta 4 de 4" in amigo2["por"], True)
st = {"x: y": {"n": 4, "bien": 1, "desfases": []}}
B5 = [{"ini": "10:00", "fin": "11:00", "fila": "x", "titulo": "t", "conf": "media", "por": "y", "regla": "x: y"}]
H.ajustar_con_revisiones(B5, st)
check("diagnóstico: regla que falla baja su confianza", B5[0]["conf"], "baja")

# por voz, «¿qué hice el ...?» lee el mismo relato que muestra Cronos (falla real 17-11: Atlas no leía el relato)
_narrar = H.narrar
H.narrar = lambda f, forzar=False: "Durmió en su casa. Fue a la U."
R = H.responder("¿Qué hice el 13 de noviembre de 2026?")
check("voz: qué hice = relato de Cronos", (R or {}).get("reply", "").endswith("Durmió en su casa. Fue a la U."), True)
H.narrar = _narrar

# falla real 17-11: el relato decía «llegó a casa 18:43» pero la línea dejaba la U hasta las 23:59
_cd2 = H._chat_dice
H._chat_dice = lambda f, m: [{"hora": "18:43", "lugar": "casa", "actividad": "llegué"}]
D6 = {"items": [], "eventos": [], "sueno": {"2001-03-05": {"desde": "2001-03-05 00:30", "hasta": "2001-03-05 08:44", "horas": 8.2, "confianza": "media"}},
      "correos": [{"fecha": "2001-03-05", "hora": "10:10", "quien": "Cabify", "viaje": {"origen": "Calle Ejemplo 100, Comuna Ejemplo",
                   "destino": "Beauchef 850, Santiago", "inicio": "09:31", "fin": "09:57"}}],
      "_previo": {"eventos": [], "correos": [], "despues": []}}
L6 = [(b["ini"], b["fin"], b.get("lugar")) for b in H.bloques(D6, date(2001, 3, 5)) if b["fila"] == "lugar"]
check("línea: casa → U → casa cuando dijo que llegó", L6, [("08:44", "09:31", "casa"), ("09:57", "18:43", "U"), ("18:43", "23:59", "casa")])
H._chat_dice = _cd2

# Intro a la Progra: cátedras, controles y auxiliares son como profesor auxiliar (pedido 17-11)
check("intro a la progra se reconoce", [H._es_ramo_dictado(t) for t in ("Cátedra Introducción a la Programación", "Control 2 Intro a la Progra", "Lenguajes de Programación")], [True, True, False])
D7 = {"items": [], "correos": [], "sueno": {}, "_previo": {"eventos": [], "correos": [], "despues": []},
      "eventos": [{"fecha": "2001-03-06", "hora": "12:45", "fin": "14:15", "titulo": "Cátedra Introducción a la Programación", "lugar": "", "tipo": "dicta"}]}
H._chat_dice, _cd3 = (lambda f, m: []), H._chat_dice
check("bloque del ramo que dicta", [b["titulo"] for b in H.bloques(D7, date(2001, 3, 6)) if b["fila"] == "actividad"],
      ["Cátedra Introducción a la Programación (como profesor auxiliar)"])
H._chat_dice = _cd3

# jueves 12-11: estuvo en la U y esa noche durmió ahí (el viernes despertó en la U). El día no termina en la casa.
B8 = [{"ini": "10:50", "fin": "20:00", "fila": "lugar", "titulo": "En la U", "lugar": "U", "conf": "alta", "por": "controles"}]
H._cerrar_noche(B8, date(2001, 3, 8), {"desde": "2001-03-09 04:41", "donde": "la U", "por": ""})
check("la noche en la U alarga el día", [(b["fila"], b["ini"], b["fin"][:5]) for b in B8], [("lugar", "10:50", "28:41"), ("sueno", "28:41", "29:59")])
B9 = [{"ini": "10:50", "fin": "18:00", "fila": "lugar", "titulo": "En la U", "lugar": "U", "conf": "alta", "por": "x"},
      {"ini": "18:00", "fin": "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "media", "por": "lo dijo por chat"}]
H._cerrar_noche(B9, date(2001, 3, 8), {"desde": "2001-03-09 01:00", "donde": "la U", "por": ""})
check("si volvió a la casa no se pisa", len(B9), 2)

# 16-11: el día terminaba en la U sin viaje de vuelta registrado; se supone la vuelta después de la última clase
D10 = {"items": [], "correos": [], "sueno": {}, "_previo": {"eventos": [], "correos": [], "despues": []},
       "eventos": [{"fecha": "2001-03-06", "hora": "12:45", "fin": "14:15", "titulo": "Cátedra Intro a la Programación", "lugar": "", "tipo": "dicta"},
                   {"fecha": "2001-03-06", "hora": "16:15", "fin": "17:45", "titulo": "Auxiliar Proyectos", "lugar": "", "tipo": "clase"}]}
H._chat_dice, _cd4 = (lambda f, m: []), H._chat_dice
B10 = H.bloques(D10, date(2001, 3, 6))
H._chat_dice = _cd4
check("vuelta a casa supuesta", [(b["fila"], b["ini"], b["fin"], b["conf"]) for b in B10 if b["fila"] in ("lugar", "viaje")],
      [("lugar", "12:45", "17:45", "baja"), ("viaje", "17:55", "18:40", "baja"), ("lugar", "18:40", "23:59", "baja")])

# 17-11: pidió ruta a unas cabañas en la costa y Cronos lo dejaba en su casa los días siguientes (datos inventados)
con = H.db()
con.execute("INSERT INTO items (fuente, fecha, hora, titulo, detalle) VALUES ('maps', '2001-05-07', '10:00', 'Indicaciones a Cabañas Ejemplo, Playa Inventada', '')")
con.execute("INSERT INTO items (fuente, fecha, hora, titulo, detalle) VALUES ('gasto', '2001-05-08', '12:00', 'abono de Amigo Inventado', 'Devoluciones y otros|transferencia')")
con.commit()
con.close()
H._chat_dice = lambda f, m: []
vacio = lambda: {"items": [], "correos": [], "eventos": [], "_previo": {"eventos": [], "correos": [], "despues": []}}  # noqa: E731
def lugares(f, **kw):
    d = vacio(); d.update(kw)
    return [(b["fila"], b["ini"], b["fin"], b["titulo"]) for b in H.bloques(d, f) if b["fila"] in ("lugar", "viaje", "sueno")]
check("estadía: llega a las cabañas", lugares(date(2001, 5, 7))[-2:],
      [("viaje", "10:30", "12:30", "Viaje a Cabañas Ejemplo, Playa Inventada (supuesto)"), ("lugar", "12:30", "23:59", "En Cabañas Ejemplo, Playa Inventada")])
check("estadía: al otro día sigue allá", lugares(date(2001, 5, 8), sueno={"2001-05-08": {"desde": "2001-05-08 01:00", "hasta": "2001-05-08 09:30", "horas": 8.5, "confianza": "media"}}),
      [("sueno", "01:00", "09:30", "Durmió ~8.5 h en Cabañas Ejemplo, Playa Inventada"), ("lugar", "09:30", "23:59", "En Cabañas Ejemplo, Playa Inventada")])
check("estadía: el último día vuelve", [x[3] for x in lugares(date(2001, 5, 10))], ["En Cabañas Ejemplo, Playa Inventada", "Vuelta a su casa (supuesta)", "En su casa"])
check("estadía: después ya no", lugares(date(2001, 5, 11)), [])
con = H.db()
con.execute("INSERT INTO items (fuente, fecha, hora, titulo, detalle) VALUES ('bip', '2001-05-09', '08:00', 'metro Ejemplo', 'uso|0')")
con.commit()
con.close()
check("estadía: si validó la bip! ya volvió", H._estadia(date(2001, 5, 9)), None)
H._chat_dice = _cd4

# 17-11: registro de empresas del SII en el PC (datos inventados, mismo formato que el SII)
import atlas_sii as S
sd = Path(tempfile.mkdtemp())
(sd / "PUB_NOMBRES_PJ.txt").write_text("RUT\tDV\tCOD_SUBTIPO\tRAZON_SOCIAL\tFECHA_INICIO_VIG\tFECHA_TG_VIG\n"
    "77000001\t1\t211\tCABANAS MAR INVENTADO LIMITADA\t01-01-2020\t\n77000002\t2\t211\tPANADERIA EJEMPLO SPA\t01-01-2020\t\n", encoding="latin-1")
(sd / "PUB_NOM_ACTECOS.txt").write_text("RUT\tDV\tCODIGO ACTIVIDAD\tDESC\tFECHA\tIVA\tCAT\n77000001\t1\t551001\tACTIVIDADES DE HOTELES\t01-01-2020\tS\t1\n"
    "77000002\t2\t107100\tELABORACION DE PRODUCTOS DE PANADERIA\t01-01-2020\tS\t1\n", encoding="latin-1")
cab = "RUT\tDV\tVIGENCIA\tFECHA\tTIPO\tCALLE\tNUMERO\tBLOQUE\tDEPTO\tVILLA\tCIUDAD\tCOMUNA\tREGION\n"
(sd / "PUB_NOM_DOMICILIO.txt").write_text(cab + "77000001\t1\tS\t2020-01-01\tDOMICILIO\tCALLE FALSA\t1\t\t\t\tPUEBLO\tPUEBLO INVENTADO\tV REGION\n", encoding="latin-1")
(sd / "PUB_NOM_SUCURSAL.txt").write_text(cab, encoding="latin-1")
_db0, S.DB = S.DB, sd / "sii.db"
S.construir(sd)
check("sii por rut", (S.por_rut("77.000.001-1") or {}).get("comuna"), "PUEBLO INVENTADO")
check("sii por nombre cortado", (S.por_nombre("CABANAS MAR INVEN") or {}).get("rut"), 77000001)
check("sii alojamiento", [S.es_alojamiento(S.por_rut(77000001)), S.es_alojamiento(S.por_rut(77000002))], [True, False])
check("sii persona natural no está", S.por_rut("8000000-1"), None)
check("gasto con empresa del sii", H._empresa_sii({"comercio": "CABANAS MAR INVENTADO"}), "Pueblo Inventado~1")
con = H.db()
con.execute("INSERT INTO items (fuente, fecha, hora, titulo, detalle) VALUES ('gasto', '2001-06-04', '', 'cargo de 90.000 pesos en CABANAS MAR INVENTADO', 'Compras|compra|Pueblo Inventado~1')")
con.commit()
con.close()
e = H._estadia(date(2001, 6, 5))
check("estadía por pago a un alojamiento", (e or {}).get("lugar"), "Cabanas Mar Inventado, Pueblo Inventado")
S.DB = _db0

# 17-11: el calendario de la fecha marca los días del mes que tienen datos (sin las horas de chat)
con = H.db()
con.execute("INSERT INTO items (fuente, fecha, hora, titulo, detalle) VALUES ('chat_hora', '2001-06-20', '10:00', '', '')")
con.commit()
con.close()
c, b, _ = H.http("GET", "api/dias_con_datos", {"mes": ["2001-06"]})
dd = json.loads(b)["dias"]
check("calendario: días con datos del mes", ["2001-06-04" in dd, "2001-06-20" in dd, all(x.startswith("2001-06") for x in dd)], [True, False, True])
check("calendario: mes inválido", H.http("GET", "api/dias_con_datos", {"mes": ["2001-6' OR 1"]})[0], 400)

# 16-11: el ejemplo del prompt traía un día real y el modelo lo copiaba (Américo Vespucio, «coordinó por chat»)
check("el prompt del relato no trae hechos reales", ["vespucio" in H.RELATO.lower(), "10:49" in H.RELATO], [False, False])

# 17-11: Cronología de Google Maps (datos inventados): manda sobre lo deducido, sin pisar los recibos
cd_ = Path(tempfile.mkdtemp()) / "cronologia_maps.db"
con = sqlite3.connect(cd_)
con.executescript("CREATE TABLE visitas(inicio TEXT, fin TEXT, utc_offset_min INTEGER, lat REAL, lng REAL, place_id TEXT, tipo_semantico TEXT, tipo_lugar INTEGER, probabilidad REAL, confirmada INTEGER, json TEXT);"
                  "CREATE TABLE trayectos(inicio TEXT, fin TEXT, lat_ini REAL, lng_ini REAL, lat_fin REAL, lng_fin REAL, distancia_m REAL, modo TEXT, json TEXT);")
con.executemany("INSERT INTO visitas VALUES (?,?,-180,?,?,?,?,0,?,0,'')", [
    ("2001-03-04T22:00:00-03:00", "2001-03-05T08:10:00-03:00", 10.0, 20.0, "pCasa", "HOME", .9),
    ("2001-03-05T09:00:00-03:00", "2001-03-05T13:00:00-03:00", 10.05, 20.0, "pU", "UNKNOWN", .7),
    ("2001-03-05T14:00:00-03:00", "2001-03-05T16:00:00-03:00", 10.1, 20.0, "pX", "UNKNOWN", .6)])
con.executemany("INSERT INTO trayectos VALUES (?,?,0,0,0,0,?,?,'')", [
    ("2001-03-05T08:10:00-03:00", "2001-03-05T09:00:00-03:00", 5400, "IN_PASSENGER_VEHICLE"),
    ("2001-03-05T13:10:00-03:00", "2001-03-05T13:50:00-03:00", 3000, "IN_BUS")])
con.commit()
con.close()
_cd0, H.CRONO_DB = H.CRONO_DB, cd_
B = [{"ini": "08:00", "fin": "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "baja", "por": "x", "_inferido": True},
     {"ini": "09:30", "fin": "12:30", "fila": "lugar", "titulo": "En la U", "lugar": "U", "conf": "media", "por": "horario"},
     {"ini": "13:05", "fin": "13:55", "fila": "viaje", "titulo": "Micro/metro: 210", "conf": "media", "por": "bip"},
     {"ini": "15:00", "fin": "17:00", "fila": "viaje", "titulo": "Vuelta a su casa (supuesta)", "conf": "baja", "por": "x", "_inferido": True}]
H._aplicar_cronologia(B, date(2001, 3, 5))
L = sorted((b["ini"], b["fin"], b["titulo"], b["conf"]) for b in B if b["fila"] in ("lugar", "viaje"))
check("maps: casa de noche", L[0][:3], ("00:00", "08:10", "En su casa"))
check("maps: trayecto en auto", ("08:10", "09:00", "Viaje en auto (5,4 km)", "alta") in L, True)
check("maps: toma el nombre de la U", ("09:00", "13:00", "En la U", "alta") in L, True)
check("maps: recibo de bip se confirma, no se reemplaza", [x for x in L if x[0] == "13:05"], [("13:05", "13:55", "Micro/metro: 210", "alta")])
check("maps: lugar sin nombre con distancia", ("14:00", "16:00", "En un lugar a 11,1 km de su casa", "alta") in L, True)
check("maps: borra lo supuesto que contradice", any("supuesta" in x[2] for x in L), False)
check("maps: deja lo deducido fuera de sus horas", ("16:00", "23:59", "En su casa", "baja") in L, True)
check("maps: día sin datos no cambia", H._aplicar_cronologia([], date(2001, 1, 1)), 0)
H.CRONO_DB = _cd0

# 17-11: el relato contaba publicidad como si él la hubiera revisado («llegó tarde porque un correo de Uber…»)
C = [{"quien": "Uber", "asunto": "Ofertas del súper con 30% de descuento"}, {"quien": "Boletín Cripto", "asunto": "Bitcoin esta semana"},
     {"quien": "PedidosYa", "asunto": "Tu pedido fue confirmado"}, {"quien": "Uber", "asunto": "Tu viaje del martes con Uber"},
     {"quien": "Rappi", "asunto": "Prueba Rappi Pro gratis: tu pedido sin costo de envío"}]
check("correos: solo comprobantes cuentan", [H._correo_es_comprobante(c) for c in C], [False, False, True, True, False])
check("el relato no usa correos recibidos como acciones", "nunca digas que revisó" in H.RELATO, True)

# 17-11: al cerrar Cronos se deja de escribir el relato (Ollama falso que manda una palabra cada 50 ms)
import http.server
import threading
import time as _t


class _Lento(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.end_headers()
        try:
            for i in range(40):
                self.wfile.write((json.dumps({"message": {"content": f"p{i} "}, "done": i == 39}) + "\n").encode())
                self.wfile.flush()
                _t.sleep(0.05)
        except OSError:
            pass

    def log_message(self, *a):
        pass


_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Lento)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{_srv.server_address[1]}"
check("relato completo sin cierre", len(H.ollama_chat([], cortar=lambda: False).split()), 40)
threading.Timer(0.3, H.cortar_relato).start()
g0, t0 = H._CORTE[0], _t.time()
try:
    H.ollama_chat([], cortar=lambda: H._CORTE[0] != g0)
    check("cerrar Cronos corta el relato", "siguió", "cortado")
except H.RelatoCortado:
    check("cerrar Cronos corta el relato", _t.time() - t0 < 1.0, True)
_srv.shutdown()
os.environ.pop("OLLAMA_HOST")

# 18-11: modo «señales»: de un chat exportado solo quedan las horas en que él escribió (±1 min), sin texto ni nombres
dd = Path(tempfile.mkdtemp())
(dd / "Chat de WhatsApp con Contacto Inventado.txt").write_text(
    "1/6/01, 10:00 - Contacto Inventado: hola\n1/6/01, 10:05 - Yo Inventado: secreto que no se guarda\n"
    "1/6/01, 22:30 - Yo Inventado: otro\n", encoding="utf-8")
(dd / "Chat de WhatsApp con Otro Inventado.txt").write_text(
    "2/6/01, 09:00 - Otro Inventado: buenas\n2/6/01, 09:10 - Yo Inventado: algo\n", encoding="utf-8")
(dd / "notas.txt").write_text("no es un chat", encoding="utf-8")
H.guardar_config(takeout=[str(dd)], mi_nombre_whatsapp="")
check("chats pendientes en Descargas", len(H.chats_pendientes()), 2)
con = H.db()
r = H.importar_chats_horas(con, borrar=False)
filas = con.execute("SELECT fecha, hora, titulo, detalle FROM items WHERE fuente='chat_hora' AND fecha LIKE '2001-06-0%' ORDER BY fecha, hora").fetchall()
check("chats: solo sus mensajes", (r["chats"], r["horas"], len(filas)), (2, 3, 3))
check("chats: hora corrida a lo más 1 min", all(abs(H._m(h) - H._m(o)) <= 1 for (_, h, _, _), o in zip(filas, ["10:05", "22:30", "09:10"])), True)
check("chats: sin texto ni nombres", all(t == "" and de == "" for _, _, t, de in filas), True)
check("chats: reimportar no duplica", H.importar_chats_horas(con, borrar=False)["horas"], 0)
con.close()
x = dd / "Chat de WhatsApp con Borrable.txt"
x.write_text("3/6/01, 10:00 - Yo Inventado: a\n", encoding="utf-8")
check("chat importado va a la papelera", H._a_papelera(x) and not x.exists(), True)
H.guardar_config(modo_ubicacion="")
c, b, _ = H.http("POST", "api/modo", {}, {"modo": "senales"})
check("modo señales se guarda", (c, json.loads(b)["modo"]), (200, "senales"))
check("modo inválido", H.http("POST", "api/modo", {}, {"modo": "x"})[0], 400)
check("fuentes: cinco con estado", [f["estado"] in ("ok", "pe", "no", "au") for f in json.loads(H.http("GET", "api/fuentes", {})[1])["fuentes"]], [True] * 5)

# 18-11: pegar la tabla de bip! en Cronos: queda solo movimiento, fecha, lugar y monto (sin número de tarjeta)
_bf, H.BIP_FILE = H.BIP_FILE, Path(tempfile.mkdtemp()) / "bip.txt"
c, b, _ = H.http("POST", "api/pegar_bip", {}, {"texto": "1234567890\tUso\t03/06/2001 08:10\tEstación Inventada\t$ 790\nbasura\n"})
check("pegar bip", (c, json.loads(b)["nuevos"], "1234567890" in H.BIP_FILE.read_text(encoding="utf-8")), (200, 1, False))
check("pegar bip sin viajes", H.http("POST", "api/pegar_bip", {}, {"texto": "nada"})[0], 400)
H.BIP_FILE = _bf

# privacidad
H._marcar_privado("¿qué hacía el 12 de marzo?", "Ese día estuvo en el trabajo hasta las 18:00, señor, y volvió en metro.")
check("privado exacto", H.es_privado("Ese día estuvo en el trabajo hasta las 18:00, señor, y volvió en metro."), True)
check("no privado", H.es_privado("¿Qué tiempo hace hoy?"), False)
os.environ["OLLAMA_HOST"] = "http://192.168.1.50:11434"
try:
    H._ollama_local()
    check("ollama remoto bloqueado", False, True)
except RuntimeError:
    check("ollama remoto bloqueado", True, True)
os.environ.pop("OLLAMA_HOST")

# 18-11: un viaje con recibo manda sobre la clase del horario (datos inventados)
def _v(ini, fin, o, d):
    return {"ini": ini, "fin": fin, "fila": "viaje", "titulo": f"Cabify: {o} → {d}", "conf": "alta", "por": "recibo del viaje", "_o": o, "_d": d}
def _c(ini, fin, nom="Ramo Inventado"):
    return {"ini": ini, "fin": fin, "fila": "actividad", "titulo": f"{nom} (como alumno)", "lugar": "U", "conf": "baja", "por": "estaba en su horario"}
VJ = _v("11:00", "11:40", "casa", "U")
BV = [_c("08:30", "10:00", "Ramo Uno"), _c("10:15", "11:45", "Ramo Dos"), VJ, _c("12:00", "13:30", "Ramo Tres")]
check("viaje real: cuántos cambia", H._viajes_mandan(BV), 2)
tit = [b["titulo"] for b in BV if b["fila"] == "actividad"]
check("viaje real: clase de antes no fue", any("Ramo Uno" in t for t in tit), False)
check("viaje real: llegó tarde", [(b["ini"], b["titulo"].endswith("llegó tarde")) for b in BV if "Ramo Dos" in b["titulo"]], [("11:40", True)])
check("viaje real: clase de después queda", any("Ramo Tres" in t for t in tit), True)
check("viaje real: explica en el viaje", "no estuvo en Ramo Uno" in VJ["por"] and "llegó tarde a Ramo Dos" in VJ["por"], True)
BV = [_v("09:00", "09:30", "casa", "U"), _c("10:00", "11:00"), _v("14:00", "14:40", "U", "casa"), _c("15:00", "16:30", "Ramo Tarde"),
      {"ini": "18:30", "fin": "23:59", "fila": "lugar", "titulo": "En su casa", "lugar": "casa", "conf": "baja", "por": "x"}]
H._viajes_mandan(BV)
check("viaje real: tras volver a casa no estuvo en la clase", any("Ramo Tarde" in b["titulo"] for b in BV), False)
check("viaje real: no toca lo de la U entre viajes ni su casa", (any("Ramo Inventado" in b["titulo"] for b in BV), any(b["fila"] == "lugar" for b in BV)), (True, True))
BV = [_v("09:00", "09:30", "casa", "U"), {"ini": "08:00", "fin": "12:00", "fila": "actividad", "titulo": "Examen (rindió)", "lugar": "U", "conf": "alta", "por": "x"}]
check("viaje real: no toca lo seguro", H._viajes_mandan(BV), 0)

# 18-11: Cronos pide el día y el relato a la vez; antes abrían dos Gmail y uno quedó colgado 165 s
import threading as _th, time as _ti
_llamadas = []
def _imap_lento(a, b, maximo=40, est=None):
    _llamadas.append(1); _ti.sleep(0.3); return [{"fecha": "2001-07-01", "asunto": "x"}]
_orig_imap, H._correos_imap = H._correos_imap, _imap_lento
_res = []
_hs = [_th.Thread(target=lambda: _res.append(H._correos(date(2001, 7, 1), date(2001, 7, 2)))) for _ in range(3)]
[h.start() for h in _hs]; [h.join() for h in _hs]
check("correos: pedidos a la vez abren Gmail una sola vez", (len(_llamadas), [len(r) for r in _res]), (1, [1, 1, 1]))
def _imap_falla(a, b, maximo=40, est=None):
    est["ok"] = False; return []
H._correos_imap = _imap_falla
H._correos(date(2001, 7, 5), date(2001, 7, 5))
check("correos: si Gmail falla se reintenta pronto", _ti.time() - H._cache_correos[(date(2001, 7, 5), date(2001, 7, 5), 40)][0] > 500, True)
H._correos_imap = _orig_imap

# 19-11: sin ningún dato de ubicación el calendario no prueba que fue (datos inventados)
BS = [{"ini": "14:30", "fin": "16:00", "fila": "actividad", "titulo": "Ramo X (como profesor auxiliar)", "lugar": "U", "conf": "media", "por": "ramo"}]
check("sin ubicación: la clase baja a «no se sabe»", (H._sin_ubicacion(BS), BS[0]["conf"]), (1, "baja"))
BS = [{"ini": "14:30", "fin": "16:00", "fila": "actividad", "titulo": "Ramo X (rindió)", "lugar": "U", "conf": "media", "por": "x"},
      {"ini": "13:00", "fin": "13:40", "fila": "viaje", "titulo": "Cabify: su casa → la U", "conf": "alta", "por": "recibo del viaje"}]
check("con un viaje real no se toca", (H._sin_ubicacion(BS), BS[0]["conf"]), (0, "media"))
_d = H.dia(date(2001, 3, 6), correos=False); _d["bloques"] = {"2001-03-06": B10}
check("aviso al modelo sin ubicación", "no hay ningún dato de dónde estuvo" in H.texto_para_modelo(_d) or not H.clasificar(_d), True)
check("sin ubicación: la U supuesta también baja", all(b["conf"] == "baja" for b in B10 if b.get("lugar") == "U"), True)

# 19-11: Rutas de Maps desconectado se avisa (log inventado)
_cd_db, _tmp_r = H.CRONO_DB, Path(tempfile.mkdtemp())
H.CRONO_DB = _tmp_r / "c.db"
(_tmp_r / "sincronizacion.log").write_text("2001-01-01T21:00:03  OK   1 visitas\n2001-01-02T21:00:03  ERROR  x (BadAuthentication). y\n"
                                          "2001-01-03T21:00:03  ERROR  x (BadAuthentication). y\n", encoding="utf-8")
check("rutas: avisa desde cuándo falla", H._rutas_error(), {"desde": "2001-01-02 21:00", "motivo": "Google cerró el acceso de Atlas a sus Rutas"})
(_tmp_r / "sincronizacion.log").write_text("2001-01-03T21:00:03  ERROR  x\n2001-01-04T21:00:03  OK   1 visitas\n", encoding="utf-8")
check("rutas: si volvió a funcionar no avisa", H._rutas_error(), None)
H.CRONO_DB = _cd_db

# 19-11: Rutas de solo la madrugada no prueba las clases de la tarde (datos inventados)
BP = [{"ini": "00:00", "fin": "01:33", "fila": "lugar", "titulo": "En un lugar", "lugar": "x", "conf": "alta", "por": "Rutas de Google Maps (ubicación real del celular)"},
      {"ini": "14:30", "fin": "16:00", "fila": "actividad", "titulo": "Ramo X (como alumno)", "lugar": "U", "conf": "media", "por": "x"},
      {"ini": "03:30", "fin": "04:00", "fila": "actividad", "titulo": "Ramo Y", "lugar": "U", "conf": "media", "por": "x"}]
H._sin_ubicacion(BP)
check("rutas parciales: la clase lejos queda sin pruebas y la cercana no", [b["conf"] for b in BP], ["alta", "baja", "media"])

print(f"{ok} de {ok + fail} pruebas pasan")
sys.exit(1 if fail else 0)

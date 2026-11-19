"""Pruebas de Baco (atlas_baco*.py) sin tocar los datos reales ni Windows ni la red. 18-11-2026; 19-11-2026: atlas_baco_mas.

Uso: python pruebas_baco.py   (desde la carpeta hud). Usa un baco.json temporal y simula TMDB.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp())
os.environ["BACO_ARCHIVO"] = str(_TMP / "baco.json")
os.environ["BACO_TIEMPO"] = str(_TMP / "baco_tiempo.json")
os.environ["BACO_SONADO"] = str(_TMP / "baco_sonado.json")
os.environ["BACO_PUNTOTICKET"] = str(_TMP / "baco_puntoticket.json")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import atlas_baco as B  # noqa: E402
import atlas_baco_audio as A  # noqa: E402
import atlas_baco_juegos as J  # noqa: E402
import atlas_baco_mas as MAS  # noqa: E402

FALLAS = []


def ok(cond, que):
    print(("  ok    " if cond else "  FALLA ") + que)
    if not cond:
        FALLAS.append(que)


def main() -> int:
    print("Baco")
    d = B.cargar()
    ok(len(d["enlaces"]) == 6 and d["pestana"] == "serie", "estado inicial con enlaces de partida")
    v = B.vdf('"UserLocalConfigStore"{"Software"{"Valve"{"Steam"{"apps"{"570"{"Playtime"\t"120" "LastPlayed" "1700000000"}}}}}}')
    ok(v["userlocalconfigstore"]["software"]["valve"]["steam"]["apps"]["570"]["playtime"] == "120", "lee localconfig.vdf de Steam")
    B.guardar({"series": [{"t": "Severance", "p": "apple", "T": 2, "E": 3, "tot": 10, "tmdb": 95396, "img": "/x.jpg"},
                          {"t": "Mala", "u": "javascript:alert(1)", "img": "../../etc"}, {"t": ""}],
               "enlaces": [{"t": "Sin url"}, {"t": "YT", "u": "https://youtube.com"}],
               "esperas": [{"t": "Concierto", "f": "2027-01-02", "k": "c"}, {"t": "Mala", "f": "mañana"}],
               "pestana": "juego", "favorito": "a<b>"})
    d = B.cargar()
    ok([s["t"] for s in d["series"]] == ["Severance", "Mala"], "series: descarta las vacías")
    ok(d["series"][1]["u"] == "" and d["series"][1]["img"] == "", "series: rechaza enlaces e imágenes peligrosos")
    ok(d["series"][0]["tmdb"] == 95396 and d["series"][0]["img"] == "/x.jpg", "series: guarda la ficha de TMDB")
    ok([e["t"] for e in d["enlaces"]] == ["YT"], "enlaces: exige dirección")
    ok(len(d["esperas"]) == 1 and d["pestana"] == "juego" and d["favorito"] == "ab", "fechas, pestaña y favorito validados")
    ok(B.abrir("javascript:alert(1)")["ok"] is False, "abrir: no abre esquemas raros")
    c, raw, _ = B.http("GET", "api/nada", {})
    ok(c == 404, "ruta desconocida: 404")
    c, raw, _ = B.http("POST", "api/guardar", {}, {"series": "no es lista"})
    ok(c == 400, "guardar con datos malos: 400")

    sr = 48000
    tono = [0.5 * math.sin(2 * math.pi * 1000 * i / sr) for i in range(4096)]
    b = A.bandas_de(tono, sr)
    ok(len(b) == 24 and b.index(max(b)) in range(10, 15) and min(b) == 0, "espectro: un tono de 1 kHz cae en las bandas medias")
    ok(max(A.bandas_de([0.0] * 100, sr)) == 0, "espectro: silencio = cero")
    ok(all(type(x) is float for x in b), "espectro: floats de Python (JSON sin numpy)")
    import numpy as np
    rng = np.random.default_rng(1)
    f = np.fft.rfftfreq(sr, 1 / sr)
    espec = np.fft.rfft(rng.standard_normal(sr))
    espec[1:] /= np.sqrt(f[1:])
    rosa = np.fft.irfft(espec)
    rosa = rosa / np.abs(rosa).max() * 0.3
    b = A.bandas_de(rosa, sr)
    ok(min(b[-5:]) > 0.3, "espectro: los agudos de un ruido rosa no quedan en cero")
    ok("480" in B.NO_JUEGOS, "Steam: oculta Spacewar (480)")

    B._tmdb_token = lambda: "eyJprueba"
    B._tmdb = lambda ruta, p=None: ({"results": [{"id": 1, "name": "X", "first_air_date": "2020-01-01"}]} if ruta.startswith("search")
                                    else {"name": "Severance", "seasons": [{"season_number": 0, "episode_count": 2}, {"season_number": 1, "episode_count": 9}],
                                          "next_episode_to_air": {"air_date": "2099-01-16", "season_number": 3, "episode_number": 1},
                                          "watch/providers": {"results": {"CL": {"flatrate": [{"provider_id": 999, "display_priority": 0},
                                                                                              {"provider_id": 350, "display_priority": 1},
                                                                                              {"provider_id": 4242, "provider_name": "HBO Max", "display_priority": 2},
                                                                                              {"provider_id": 4243, "provider_name": "Max Amazon Channel", "display_priority": 3}]},
                                                                          "US": {"flatrate": [{"provider_id": 8}]}}}})
    r = json.loads(B.http("GET", "api/tmdb/buscar", {"q": ["sev"]})[1])
    ok(r["res"][0]["tmdb"] == 1, "TMDB: búsqueda")
    r = json.loads(B.http("GET", "api/tmdb/ficha", {"id": ["95396"]})[1])
    ok(r["temporadas"] == [{"T": 1, "eps": 9, "f": ""}] and "_t" not in r, "TMDB: temporadas sin la de especiales")
    ok(r["donde"] == ["apple", "max"], "TMDB: dónde verla en Chile (por id o por nombre, sin los «channel»)")
    r = json.loads(B.http("GET", "api/estrenos", {})[1])
    ok(r["ev"] and r["ev"][0]["s"] == "Temporada 3", "TMDB: próximo estreno para «Lo que viene»")
    B._igdb_cred = lambda: ("id", "secreto")
    B._igdb = lambda ep, q: [{"id": 7, "name": "GTA VI", "url": "https://www.igdb.com/games/x", "cover": {"image_id": "co9abc"},
                              "platforms": [{"abbreviation": "PS5"}, {"abbreviation": "Series X|S"}],
                              "release_dates": [{"date": 4102444800, "human": "Jan 01, 2100", "date_format": 0, "platform": {"abbreviation": "PS5"}},
                                                {"date": 4102444800, "human": "Jan 01, 2100", "date_format": 0, "platform": {"abbreviation": "Series X|S"}},
                                                {"date": 4133894400, "human": "2100", "date_format": 2, "platform": {"abbreviation": "PC"}},
                                                {"date": None, "date_format": 7, "platform": {"abbreviation": "Switch"}}]}]
    r = json.loads(B.http("GET", "api/igdb/buscar", {"q": ['gta "vi']})[1])
    ok(r["res"][0]["proximo"]["plats"] == ["PS5", "Xbox Series"], "IGDB: agrupa plataformas por fecha")
    B.guardar({"esperados": [{"t": "GTA VI", "igdb": 7, "img": "co9abc"}, {"t": "Sin id", "igdb": 0}, {"t": "Mala", "igdb": 5, "img": "../x"}]})
    e = B.cargar()["esperados"]
    ok([x["id"] for x in e] == ["igdb:7", "igdb:5"] and e[1]["img"] == "", "IGDB: esperados validados")
    r = json.loads(B.http("GET", "api/estrenos", {})[1])
    ok(sum(1 for x in r["ev"] if x["id"].startswith("igdb:7:")) == 2, "IGDB: una fecha por salida en «Lo que viene»")
    B.guardar({"pc_manuales": [{"t": "Mi Juego", "exe": r"C:\Juegos\MiJuego\juego.exe"}, {"t": "Malo", "exe": "juego.exe"},
                               {"t": "Bat", "exe": r"C:\a\b.bat"}]})
    ok([m["id"] for m in B.cargar()["pc_manuales"]] == ["pc:m-mi-juego"], "juegos del PC: solo .exe con ruta completa")
    J._ESTADO["cache"], J._ESTADO["t_cache"] = [], 1e18   # sin launchers reales en la prueba
    J.procesos = lambda: {"juego.exe", "genshinimpact.exe", "explorer.exe"}
    ids = J.mirar(B._manuales)
    ok(sorted(ids) == ["pc:genshin-impact", "pc:m-mi-juego"], "juegos del PC: reconoce los procesos abiertos")
    J.sumar(ids, 1800)
    J.sumar(ids, 1800)
    L = {j["id"]: j for j in B.juegos_pc()["juegos"]}
    ok(L["pc:genshin-impact"]["h"] == 1.0 and L["pc:genshin-impact"]["h2"] == 1.0, "juegos del PC: suma el tiempo jugado")
    ok("pc:valorant" not in L, "juegos del PC: no muestra conocidos que no están ni se han jugado")
    J._ESTADO["hilo"] = None
    golpes()
    mas()
    eventos_pt()
    print("\n" + ("Todo bien." if not FALLAS else f"{len(FALLAS)} fallas."))
    return 1 if FALLAS else 0


RSS = (b'<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>'
       b'<item><title>Severance &amp; su tercera temporada</title><link>https://a.cl/1</link><pubDate>Wed, 18 Nov 2026 20:00:00 +0000</pubDate>'
       b'<description>&lt;img src="https://a.cl/i.jpg"&gt; Texto</description></item>'
       b'<item><title>Algo que no te importa</title><link>https://a.cl/2</link><pubDate>Wed, 18 Nov 2026 19:00:00 +0000</pubDate>'
       b'<media:content url="https://a.cl/m.jpg"/></item><item><title>Malo</title><link>javascript:x</link></item></channel></rss>')
ATOM = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>GTA VI tiene fecha</title><link href="https://b.cl/x"/>'
        b'<updated>2026-11-18T10:00:00Z</updated><summary>ok</summary></entry></feed>')


def golpes() -> None:
    """Pulso para las ondas: bombo a 124 BPM con un bajo que cambia de nota entre golpes (lo que confundía al detector)."""
    import numpy as np

    print("Baco: pulso de la música")
    sr, dur, bpm = 48000, 16, 124
    n, beat = sr * dur, 60 / bpm
    x = np.zeros(n, np.float32)
    golpes_ = np.arange(0, dur - 0.5, beat)
    for k0 in golpes_:
        i, L = int(k0 * sr), int(0.35 * sr)
        tt = np.arange(L) / sr
        seg = np.sin(2 * np.pi * np.cumsum(50 + 90 * np.exp(-tt * 30)) / sr) * np.exp(-tt * 9) * 0.45
        x[i:i + L] += seg[:max(0, min(L, n - i))]
    notas = [55, 55, 65.4, 73.4, 49, 49, 82.4, 73.4]
    for j, s0 in enumerate(np.arange(0, dur, beat / 2)):
        i0, i1 = int((s0 + beat / 4) * sr), min(n, int((s0 + beat * 0.75) * sr))
        x[i0:i1] += 0.1 * np.sign(np.sin(2 * np.pi * notas[j % 8] * np.arange(max(0, i1 - i0)) / sr))
    G = A.Golpes(sr)
    for i in range(0, n, 480):
        G.alimentar(x[i:i + 480])
    det = np.array([t for t in G.tiempos if t > 5])
    ref = golpes_[golpes_ > 5.3]
    a_tiempo = sum(1 for k in ref if len(det) and np.min(np.abs(det - k)) < 0.06) / len(ref)
    ok(abs(G.resumen()["bp"] - beat) < 0.02, "pulso: encuentra el tempo (124 BPM) aunque el bajo meta notas entre medio")
    ok(a_tiempo >= 0.9 and len(det) <= len(ref) + 2, "pulso: las ondas caen en el bombo (±60 ms)")
    G2 = A.Golpes(sr)
    G2.alimentar(np.zeros(sr * 4, np.float32))
    ok(G2.cuenta == 0 and G2.resumen()["bp"] == 0, "pulso: en silencio no hay ondas")
    if hasattr(G, "t_audio"):
        G.t_audio -= 1.0   # pausa: Windows deja de entregar audio
        ok(G.resumen()["bp"] == 0, "pulso: con la canción en pausa no quedan ondas pendientes")


def mas() -> None:
    print("Baco: perfil, noticias, playlists, eventos")
    p = MAS.limpiar_perfil({"ver": ["anime", "hackeo", "anime"], "donde": ["netflix"], "artistas": ["M83", "", "x" * 99], "listo": 1})
    ok(p["ver"] == ["anime"] and p["donde"] == ["netflix"] and p["artistas"] == ["M83", "x" * 60] and p["listo"] is True, "perfil: solo opciones conocidas")
    B.guardar({"perfil": {"ver": ["drama"], "listo": True}, "noticias": {"extra": ["Nintendo"], "fuentes_off": ["vandal", "nada"], "generales": 0}})
    d = B.cargar()
    ok(d["perfil"]["ver"] == ["drama"] and d["noticias"]["fuentes_off"] == ["vandal"] and d["noticias"]["extra"] == ["Nintendo"], "perfil y noticias se guardan validados")
    L = MAS.leer_feed(RSS)
    ok([x["t"] for x in L] == ["Severance & su tercera temporada", "Algo que no te importa"], "noticias: lee RSS y descarta enlaces raros")
    ok(L[0]["img"] == "https://a.cl/i.jpg" and L[1]["img"] == "https://a.cl/m.jpg" and L[0]["f"] > 0, "noticias: imagen y fecha del RSS")
    A2 = MAS.leer_feed(ATOM)
    ok(A2 and A2[0]["u"] == "https://b.cl/x" and A2[0]["f"] > 0, "noticias: lee Atom")
    ok(MAS.leer_feed(b"<no") == [], "noticias: un feed roto no rompe nada")
    B.guardar({"series": [{"t": "Severance", "p": "apple"}], "esperados": [{"t": "Grand Theft Auto VI", "igdb": 7}]})
    pedidos = []
    B._STEAM_CACHE.update(t=1e18, v={"ok": True, "juegos": [{"id": "steam:1", "appid": "1", "t": "Hades", "h": 3, "ultima": 5}]})

    def falso(url, horas=0.5, cab=None, tiempo=7):
        pedidos.append(url)
        if "news.google" in url:
            return (b'<rss><channel><item><title>GTA VI: nuevo avance - La Tercera</title><link>https://g.cl/1</link>'
                    b'<pubDate>Wed, 18 Nov 2026 21:00:00 +0000</pubDate></item></channel></rss>')
        if "mondosonoro" in url:
            raise OSError("caído")
        return RSS
    MAS._get = falso
    import time as _t
    MAS.time.time = lambda: 1795060000.0
    try:
        n = MAS.noticias()
    finally:
        MAS.time.time = _t.time
    temas = {t["t"]: t for t in n["temas"]}
    ok("Severance" in temas and "Grand Theft Auto VI" in temas and "Nintendo" in temas and temas["Hades"]["why"] == "Lo juegas", "noticias: temas de lo que ves, esperas y lo extra")
    ok(not any("vandal" in u for u in pedidos), "noticias: respeta las fuentes apagadas")
    ok(any(x["tema"] == "Severance" and x["why"] == "La ves" for x in n["res"]), "noticias: une titulares de sitios con tus temas")
    ok(not any(x["t"] == "Algo que no te importa" for x in n["res"]), "noticias: sin «generales», solo lo tuyo")
    ok(any(x["src"] == "La Tercera" and x["t"] == "GTA VI: nuevo avance" for x in n["res"]), "noticias: Google Noticias con su fuente")
    ok("Mondo Sonoro" in n["errores"], "noticias: avisa qué fuente no respondió")
    B.guardar({"noticias": {"off": ["Severance"]}})
    MAS.time.time = lambda: 1795060000.0
    try:
        n = MAS.noticias()
    finally:
        MAS.time.time = _t.time
    ok(not any(x.get("tema") == "Severance" for x in n["res"]), "noticias: quitar un tema lo saca")
    MAS.anotar_sonado({"hay": True, "estado": "Playing", "titulo": "Nightcall", "artista": "Kavinsky"})
    MAS.anotar_sonado({"hay": True, "estado": "Playing", "titulo": "Nightcall", "artista": "Kavinsky"})
    MAS.anotar_sonado({"hay": True, "estado": "Paused", "titulo": "Otra", "artista": "X"})
    ok([x["t"] for x in MAS.sonado()] == ["Nightcall"], "lo que sonó: anota una vez y solo si suena")
    B.guardar({"musica": [{"t": "Noche", "pistas": [{"t": "Nightcall", "a": "Kavinsky"}, {"t": ""}, "malo"], "animo": ["Noche", ""]}]})
    m = B.cargar()["musica"][0]
    ok(m["pistas"] == [{"t": "Nightcall", "a": "Kavinsky"}] and m["animo"] == ["Noche"], "playlists: canciones y ánimo validados")
    B.guardar({"musica": [{"t": "Mezcla", "pistas": [{"t": "Chill", "u": "https://music.youtube.com/playlist?list=PL1"}, {"t": "Mala", "u": "https://evil.cl/x"}]}]})
    m = B.cargar()["musica"][0]
    ok(m["pistas"] == [{"t": "Chill", "a": "", "u": "https://music.youtube.com/playlist?list=PL1"}, {"t": "Mala", "a": ""}], "playlists: mezcla playlists de YouTube Music con canciones (solo enlaces de YouTube)")
    B.guardar({"esperas": [{"t": "Lolla", "f": "2027-03-20", "k": "v", "u": "javascript:x"}, {"t": "Vieja", "f": "2027-01-01", "k": "e"}]})
    ok([e["k"] for e in B.cargar()["esperas"]] == ["v", "s"] and B.cargar()["esperas"][0]["u"] == "", "Lo que viene: tipos de evento y enlace seguro")
    ok(MAS._tipo(b"\xff\xd8\xffxx") == "image/jpeg" and MAS._tipo(b"<html>") == "", "portada: solo imágenes")
    pedidos.clear()

    def tienda(url, horas=0.5, cab=None, tiempo=7):
        pedidos.append(url)
        if "itunes.apple.com" in url:
            return b'{"results": []}' if "Xyzzy" in url else b'{"results": [{"artistName": "Otra", "artworkUrl100": "https://x/a/100x100bb.jpg"}, {"artistName": "Artista Demo", "artworkUrl100": "https://x/b/100x100bb.jpg"}]}'
        return b"\xff\xd8\xff" + url.encode()
    MAS._get = tienda
    c = MAS.portada_catalogo("Cancion Demo (Xyzzy Jam Vocal Mix)", "Artista Demo - Topic")
    ok(c.endswith(b"https://x/b/600x600bb.jpg") and len(pedidos) == 3, "portada: si Windows no la da, la busca por canción y artista (sin la versión)")
    MAS.portada = lambda k: (b"", "")
    ok(B.http("GET", "api/portada", {"k": ["x"]})[0] == 404, "portada: sin carátula responde 404")
    e = B.estado()
    ok(e["perfil"]["listo"] and "perfil_opciones" in e and e["tmdb_fondo"].startswith("https://"), "estado trae perfil y fondos")


PT_HTML = """<div><article id="event_0" class="col-4"><a href="/banda-demo-2026" target="_self"><div class="evento--box">
<p class="descripcion"><strong>Santander Arena - Santiago Centro</strong> / Pop Punk</p><h3 title="Banda Demo ">Banda Demo </h3>
<img src="https://static.ptocdn.net/images/eventos/lot220_calugalistado.jpg"><img src="https://cdnp.puntoticket.com/x/ico-ticket.png">
<p class="fecha">18 de noviembre 2027</p></div></a></article>
<article id="event_4"><a href="/malo"><h3>Fecha mala</h3><p class="fecha">31 de febrero 2027</p></a></article>
<article id="event_1"><a href="https://www.puntoticket.com/evento/edocaroe-comedy"><p class="descripcion"><strong>Teatro Caupolic&#225;n</strong> / Stand Up</p>
<h3>Edo Caroe &amp; amigos</h3><p class="fecha">06 de enero 2027 - 31 de enero 2027</p></a></article>
<article id="event_2"><a href="https://otro.sitio/x"><h3>Raro</h3><p class="fecha">01 de enero 2027</p></a></article>
<article id="event_3"><a href="/sin-fecha"><h3>Sin fecha</h3><p class="fecha">Pronto</p></a></article></div>"""


def cola_yt() -> None:
    """19-11-2026: la cola con canciones de YouTube sigue el <video> de la ventana de música (sin saltarse ninguna)."""
    import time as _t

    antes = (B._musica_estado, B.tocar, B._media, B._VIGIA.get("proc"), B._MEDIA_CACHE.get("v"))
    pasos: list = []
    tocados: list = []

    def estado(play=False):
        _t.sleep(0.01)
        return pasos.pop(0) if pasos else (pasos_fijo[0] if pasos_fijo else None)

    pasos_fijo: list = []
    B._musica_estado = estado
    B._media = lambda accion="": {"hay": False}
    B._MEDIA_CACHE["v"] = None
    B.tocar = lambda t="", a="", u="", sola=False: (tocados.append(u), {"ok": True, "url": u})[1]
    viejo_sleep = B.time.sleep
    B.time.sleep = lambda s: viejo_sleep(0.002)

    def st(v, t, d=200, p=False, e=False, ad=False, l=""):
        return {"hay": True, "u": f"https://music.youtube.com/watch?v={v}", "v": v, "t": t, "d": d, "p": p, "e": e, "ad": ad, "l": l}

    def esperar(cond, s=3.0):
        fin = _t.time() + s
        while _t.time() < fin and not cond():
            viejo_sleep(0.01)
        return cond()

    U = [f"https://music.youtube.com/watch?v=CANCION{i}" for i in range(4)]
    try:
        # mientras carga la nueva se ve la anterior terminando, luego un aviso, luego la canción: no salta nada
        pasos[:] = [st("CANCION9", 199), None, st("CANCION0", 0), st("CANCION0", 3, ad=True), st("CANCION0", 2), st("CANCION0", 60)]
        pasos_fijo[:] = [st("CANCION0", 61)]
        B.cola({"id": "yt", "j": 0, "items": [{"t": f"T{i}", "u": U[i]} for i in range(4)]})
        ok(esperar(lambda: not pasos) and B._COLA["j"] == 0 and B._COLA["cdp"] and tocados == [U[0]],
           "cola YouTube: la canción anterior, el hueco de carga y los avisos no la saltan")
        B._cola_vigilar({"hay": True, "titulo": "Otra cosa", "estado": "Playing", "app_n": "Edge", "pos": 1, "fin": 100})
        B._cola_vigilar({"hay": True, "titulo": "Otra más", "estado": "Playing", "app_n": "Edge", "pos": 1, "fin": 100})
        ok(B._COLA["j"] == 0, "cola YouTube: lo que diga Windows (títulos que cambian) ya no la salta")
        pasos_fijo[:] = [st("CANCION0", 150, p=True)]
        viejo_sleep(0.1)
        pasos_fijo[:] = [st("CANCION0", 199.5, p=True)]
        viejo_sleep(0.1)
        ok(B._COLA["j"] == 0, "cola YouTube: en pausa no avanza")
        pasos_fijo[:] = [st("CANCION1", 0)]
        pasos[:] = [st("CANCION0", 199.0)]
        ok(esperar(lambda: B._COLA["j"] == 1 and len(tocados) == 2) and tocados[-1] == U[1],
           "cola YouTube: un segundo antes del final pone la siguiente, una sola vez")
        pasos[:] = [st("CANCION1", 2), st("CANCION1", 100)]
        pasos_fijo[:] = [st("OTRAYTM1", 1, l="RDAMVMCANCION1")]
        ok(esperar(lambda: B._COLA["j"] == 2) and tocados[-1] == U[2] and len(tocados) == 3,
           "cola YouTube: si YouTube Music siguió con su radio (aunque la duración informada no calce), Baco pone la suya")
        n = len(tocados)
        ok(B.media("next")["cola"]["j"] == 3 and esperar(lambda: len(tocados) == n + 1) and tocados[-1] == U[3],
           "cola: ⏭ de «Ahora suena» mueve la cola de Baco (no la de YouTube Music)")
        ok(B.media("prev")["cola"]["j"] == 2 and esperar(lambda: len(tocados) == n + 2) and tocados[-1] == U[2],
           "cola: ⏮ de «Ahora suena» vuelve a la anterior de la cola")
        n = len(tocados)
        B._cola_avanzar(("yt", 1, 0))
        ok(B._COLA["j"] == 2 and len(tocados) == n, "cola: un aviso de fin atrasado (de la canción anterior) no salta la actual")
        pasos[:] = [st("CANCION2", 2), st("CANCION2", 50)]
        pasos_fijo[:] = [st("PONATLAS01", 1)]
        ok(esperar(lambda: B._COLA["fin"]) and len(tocados) == n and B._COLA["j"] == 2,
           "cola YouTube: «Atlas, pon …» a media canción corta la cola (no cambia a la siguiente encima)")
    finally:
        B.time.sleep = viejo_sleep
        B._musica_estado, B.tocar, B._media = antes[0], antes[1], antes[2]
        B._MEDIA_CACHE["v"] = antes[4]
        B._COLA.update(id="", items=[], j=0, fin=False)
        B._COLA["n"] += 1
        viejo_sleep(0.05)


def enlaces_exactos() -> None:
    """19-11-2026: las canciones guardadas sin enlace quedan con el video exacto apenas suena, y la página no lo borra."""
    B.guardar({"musica": [{"id": "pl9", "t": "Ado", "pistas": [{"t": "Usseewa", "a": "Ado"}, {"t": "Otra", "a": "X"}]}]})
    ok(B.poner_u_pista("Usseewa", "Ado", "https://music.youtube.com/watch?v=DEMOVIDEO01") == 1
       and B.cargar()["musica"][0]["pistas"][0]["u"] == "https://music.youtube.com/watch?v=DEMOVIDEO01"
       and "u" not in B.cargar()["musica"][0]["pistas"][1], "enlaces: la canción guardada por nombre queda con su video exacto")
    B.guardar({"musica": [{"id": "pl9", "t": "Ado", "pistas": [{"t": "Usseewa", "a": "Ado"}, {"t": "Otra", "a": "X"}, {"t": "Nueva", "a": "Y"}]}]})
    ok(B.cargar()["musica"][0]["pistas"][0].get("u") == "https://music.youtube.com/watch?v=DEMOVIDEO01" and len(B.cargar()["musica"][0]["pistas"]) == 3,
       "enlaces: si la página guarda su copia vieja (sin enlace), el enlace exacto no se pierde")
    B.guardar({"musica": []})


def portadas_playlist() -> None:
    """19-11-2026: portada de una playlist (carátula de una de sus canciones, imagen subida o un enlace)."""
    import base64 as b64
    B.guardar({"musica": [{"id": "pl7", "t": "Noche", "img": "https://i.ytimg.com/x.jpg", "pistas": [{"t": "A"}]},
                          {"id": "pl8", "t": "Mala", "img": "javascript:alert(1)", "pistas": [{"t": "A"}]},
                          {"id": "pl6", "t": "Sub", "img": "subida:1795", "pistas": [{"t": "A"}]}]})
    m = B.cargar()["musica"]
    ok(m[0].get("img") == "https://i.ytimg.com/x.jpg" and "img" not in m[1] and m[2].get("img") == "subida:1795",
       "portada: guarda enlaces https y subidas, rechaza lo peligroso")
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 64
    c, raw, _ = B.http("POST", "api/portada_pl", {}, {"id": "pl7", "datos": "data:image/jpeg;base64," + b64.b64encode(jpg).decode()})
    r = json.loads(raw)
    ok(c == 200 and r.get("ok") and r["img"].startswith("subida:"), "portada: sube una imagen")
    c, raw, t = B.http("GET", "api/portada_pl", {"id": ["pl7"]})
    ok(c == 200 and raw == jpg and t == "image/jpeg", "portada: la entrega de vuelta")
    c, _, _ = B.http("POST", "api/portada_pl", {}, {"id": "pl7", "datos": "data:image/jpeg;base64," + b64.b64encode(b"<html>").decode()})
    ok(c == 400, "portada: rechaza lo que no es imagen")
    c, _, _ = B.http("POST", "api/portada_pl", {}, {"id": "../../x", "datos": "data:image/jpeg;base64," + b64.b64encode(jpg).decode()})
    ok(c == 200 and not (B.PORTADAS.parent / "x.img").exists() and all(f.parent == B.PORTADAS for f in B.PORTADAS.iterdir()),
       "portada: el id no sale de la carpeta de portadas")
    viejo = MAS.portada_catalogo
    MAS.portada_catalogo = lambda t, a: jpg if t == "Nightcall" else b""
    try:
        r = json.loads(B.http("POST", "api/portada_pl", {}, {"id": "pl6", "t": "Nightcall", "a": "Kavinsky"})[1])
        ok(r.get("ok") and B.http("GET", "api/portada_pl", {"id": ["pl6"]})[1] == jpg, "portada: usa la carátula de una canción")
        r = json.loads(B.http("POST", "api/portada_pl", {}, {"id": "pl6", "t": "Nada"})[1])
        ok(r.get("ok") is False and r.get("error"), "portada: avisa si la canción no tiene carátula")
        ok(B.http("GET", "api/portada_cancion", {"t": ["Nightcall"], "a": ["Kavinsky"]})[0] == 200
           and B.http("GET", "api/portada_cancion", {"t": ["Nada"]})[0] == 404, "portada: carátula de cada canción de la lista")
    finally:
        MAS.portada_catalogo = viejo
    B.http("POST", "api/portada_pl", {}, {"id": "pl6", "quitar": True})
    ok(B.http("GET", "api/portada_pl", {"id": ["pl6"]})[0] == 404, "portada: se puede quitar")
    B.guardar({"musica": []})


def busqueda() -> None:
    """19-11-2026: con canciones guardadas sin enlace, elige el resultado que calza con el título (no el primero)."""
    res = {"songs": [{"id": "TETRIS0001", "title": "Tetris", "artists": ["Ado"]}, {"id": "BRAIN00001", "title": "BRAIN", "artists": ["Ado"]}],
           "yt": [{"id": "BRAINCOVER", "title": "【Ado】BRAIN 歌いました", "channel": "Ado"}]}
    llamadas = []

    class Falso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, u, download=False):
            llamadas.append(u)
            return {"entries": res["songs"] if "music.youtube.com" in u else res["yt"]}

    import types
    antes = sys.modules.get("yt_dlp")
    sys.modules["yt_dlp"] = types.SimpleNamespace(YoutubeDL=Falso)
    B._BUSCADOS.clear()
    B._vids_archivo().unlink(missing_ok=True)
    try:
        v = B._buscar_video("【Ado】BRAIN 歌いました", "Ado")
        ok(v in ("BRAINCOVER", "BRAIN00001"), "búsqueda: «【Ado】BRAIN 歌いました» no pone «Tetris» (otra del mismo álbum)")
        n = len(llamadas)
        ok(B._buscar_video("【Ado】BRAIN 歌いました", "Ado") == v and len(llamadas) == n, "búsqueda: la recuerda (misma versión siempre, sin esperar)")
        res["songs"] = [{"id": "USSEEWA001", "title": "うっせぇわ - Usseewa"}, {"id": "COVER00001", "title": "Usseewa"}]
        ok(B._buscar_video("Usseewa", "Ado") == "USSEEWA001", "búsqueda: gana la oficial de «Canciones», no un cover que se llama igual")
        res["songs"] = [{"id": "BRAINROT01", "title": "Internet Brain Rot"}]
        res["yt"] = [{"id": "REACCION01", "title": 'ADO "BRAIN 歌いました" (FIRST TIME REACTION)'}, {"id": "BRAINADO01", "title": "【Ado】BRAIN 歌いました"}]
        B._BUSCADOS.clear()
        B._vids_archivo().unlink(missing_ok=True)
        ok(B._buscar_video("【Ado】BRAIN 歌いました", "Ado") == "BRAINADO01", "búsqueda: ni «Internet Brain Rot» ni una reacción")
    finally:
        if antes is None:
            sys.modules.pop("yt_dlp", None)
        else:
            sys.modules["yt_dlp"] = antes
        B._BUSCADOS.clear()
    ok("beforeunload" in B._JS_ESTADO and "BeforeUnloadEvent" in B._JS_SIN_AVISO,
       "ventana de música: sin el aviso «¿Salir de la aplicación?» al cerrarla o cambiar de canción")


def eventos_pt() -> None:
    print("Baco: PuntoTicket y recomendaciones")
    L = MAS.leer_puntoticket(PT_HTML)
    ok([x["t"] for x in L] == ["Banda Demo", "Edo Caroe & amigos"], "PuntoTicket: lee los eventos y descarta enlaces de otros sitios o sin fecha")
    ok(L[0]["f"] == "2027-11-18" and L[0]["lugar"] == "Santander Arena - Santiago Centro" and L[0]["cat"] == "Pop Punk"
       and L[0]["u"] == "https://www.puntoticket.com/banda-demo-2026" and L[0]["img"].endswith("lot220_calugalistado.jpg"),
       "PuntoTicket: fecha, lugar, categoría, enlace e imagen (sin fechas imposibles)")
    ok(L[1]["f"] == "2027-01-06" and L[1]["fin"] == "2027-01-31" and L[1]["lugar"] == "Teatro Caupolicán", "PuntoTicket: rangos de fechas y acentos")
    pedidos = []

    class Resp:
        def __init__(self, b): self.b = b
        def read(self, n=-1): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def abrir(req, timeout=0):
        pedidos.append(req.full_url)
        if len(pedidos) > 1:
            raise OSError("bloqueado")
        return Resp(PT_HTML.encode())
    antes = MAS.urllib.request.urlopen
    MAS.urllib.request.urlopen = abrir
    try:
        a = MAS.puntoticket()
        b = MAS.puntoticket()
        ok(len(a["ev"]) == 2 and len(b["ev"]) == 2 and len(pedidos) == 1, "PuntoTicket: se lee una sola vez al día (lo demás sale de lo guardado)")
        c = MAS.puntoticket(forzar=True)
        ok(len(c["ev"]) == 2 and c["error"] == "OSError", "PuntoTicket: si lo bloquean, sigue con lo de ayer sin romper nada")
        MAS.PUNTOTICKET = False
        ok(MAS.puntoticket()["ev"] == [], "PuntoTicket: se apaga con un interruptor (para distribuir Atlas)")
        MAS.PUNTOTICKET = True
        B.guardar({"perfil": {"listo": True, "artistas": ["Banda Demo"]}})
        MAS._EV.update(k=None)
        ev = [e for e in MAS.eventos()["ev"] if e.get("pt")]
        ok(ev and ev[0]["tuyo"] and ev[0]["k"] == "c" and ev[0]["s"].startswith("★"), "PuntoTicket: marca a los artistas que escuchas y separa conciertos")
        ok(any(e["k"] == "v" and "hasta el 31/1" in e["s"] for e in ev), "PuntoTicket: el stand up va como evento, con su rango")
        B.guardar({"perfil": {"listo": True, "pt": False}})
        MAS._EV.update(k=None)
        ok(not [e for e in MAS.eventos()["ev"] if e.get("pt")], "PuntoTicket: apagado desde «Tu perfil»")
    finally:
        MAS.urllib.request.urlopen = antes
    ok(MAS.clave_juego("OCTOPATH TRAVELER™ II Digital Deluxe") == MAS.clave_juego("Octopath Traveler 2")
       and MAS.clave_juego("Octopath Traveler 0") != MAS.clave_juego("Octopath Traveler II"), "Para ti: reconoce un juego que ya tienes aunque el nombre cambie")
    B.guardar({"ocultos": ["j:123", "s:9", "j:123", "<x>"]})
    ok(B.cargar()["ocultos"] == ["j:123", "s:9", "x"], "Para ti: «ya lo tengo» se guarda limpio")
    B.guardar({"favoritos": {"serie": "s1", "juego": "steam:570<>", "otra": "x"}})
    ok(B.cargar()["favoritos"] == {"serie": "s1", "juego": "steam:570", "musica": ""}, "favoritos: uno de series, uno de juegos y uno de música")
    import types
    hechos = []
    pcm = types.SimpleNamespace(_cdp_eval=lambda js, parte="": hechos.append(("nav", js)),
                                _MusicWindow=types.SimpleNamespace(_autoplay=lambda: hechos.append(("auto",)), open=lambda u: hechos.append(("abre", u))))
    paquete = types.ModuleType("openjarvis"); herr = types.ModuleType("openjarvis.tools"); herr.atlas_pc = pcm; paquete.tools = herr
    antes_mod = {k: sys.modules.get(k) for k in ("openjarvis", "openjarvis.tools", "openjarvis.tools.atlas_pc")}
    sys.modules.update({"openjarvis": paquete, "openjarvis.tools": herr, "openjarvis.tools.atlas_pc": pcm})
    antes_b, B._buscar_video = B._buscar_video, lambda t, a: "VID123"
    antes_ir0, antes_hay0 = B._musica_ir, B._musica_hay_cdp
    B._musica_ir, B._musica_hay_cdp = (lambda u: False), (lambda: False)   # que no toque la ventana de música real
    try:
        r1 = B.tocar("Nightcall", "Kavinsky")
        r2 = B.tocar(u="https://music.youtube.com/playlist?list=PL9")
        import time as _t; _t.sleep(0.05)
        ok(r1["url"] == "https://music.youtube.com/watch?v=VID123" and r2["url"] == "https://music.youtube.com/watch?list=PL9"
           and any(h[0] == "nav" and "VID123" in h[1] for h in hechos), "cola: YouTube suena en la ventana de música de Atlas (canción buscada o playlist que parte sola)")
    finally:
        B._buscar_video = antes_b
        B._musica_ir, B._musica_hay_cdp = antes_ir0, antes_hay0
        for k, v in antes_mod.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    # 19-11-2026: con la ventana de música abierta se cambia de canción ahí mismo (no se cierra y abre otra)
    navs, abiertas = [], []
    antes_ir, antes_hay = B._musica_ir, B._musica_hay_cdp
    pcm2 = types.SimpleNamespace(_cdp_eval=lambda js, parte="": (_ for _ in ()).throw(RuntimeError("x")),
                                 _MusicWindow=types.SimpleNamespace(_autoplay=lambda: None, open=lambda u: abiertas.append(u)))
    paquete.tools.atlas_pc = pcm2
    sys.modules.update({"openjarvis": paquete, "openjarvis.tools": herr, "openjarvis.tools.atlas_pc": pcm2})
    try:
        B._musica_ir = lambda u: (navs.append(u), True)[1]
        r = B.tocar(u="https://music.youtube.com/watch?v=AAAAAAA1", sola=True)
        ok(r.get("misma") and navs == ["https://music.youtube.com/watch?v=AAAAAAA1"] and not abiertas,
           "música: la canción siguiente se pone en la misma ventana (no la cierra)")
        B._musica_ir, B._musica_hay_cdp = (lambda u: False), (lambda: False)
        B.tocar(u="https://music.youtube.com/watch?v=AAAAAAA2", sola=True)
        ok(abiertas == ["https://music.youtube.com/watch?v=AAAAAAA2"], "música: si no hay ventana de música, la abre")
    finally:
        B._musica_ir, B._musica_hay_cdp = antes_ir, antes_hay
        for k, v in antes_mod.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    cola_yt()
    busqueda()
    enlaces_exactos()
    portadas_playlist()
    ok(not B.abrir_en_ytm("https://www.youtube.com/watch?v=x") and not B.abrir_en_ytm("https://music.youtube.com/x'; calc"),
       "YouTube Music: solo reutiliza la pestaña con enlaces de music.youtube.com sin caracteres raros")
    import types as _ty
    falso = _ty.SimpleNamespace(stdout=iter([b"basura\n", b'{"hay":true,"titulo":"Uno","artista":"A","estado":"Playing","app":"Spotify.exe","pos":3,"fin":200}\n',
                                            b'{"hay":true,"titulo":"Dos","artista":"B","estado":"Playing","app":"Spotify.exe","pos":1,"fin":180}\n']), poll=lambda: None)
    antes_v = dict(B._VIGIA)
    try:
        B._vigia_leer(falso); B._VIGIA["proc"] = falso
        tocados = []
        antes_t, antes_m = B.tocar, B._media
        B.tocar = lambda t="", a="", u="", sola=False: (tocados.append(t or u), {"ok": True})[1]
        B._media = lambda accion="": {"hay": False}
        try:
            r = B.cola({"id": "pl1", "j": 0, "items": [{"t": "Uno", "a": "A"}, {"t": "Lista", "u": "https://music.youtube.com/playlist?list=PL1"}, {"t": "Tres", "a": "C"}, {"t": "Mala", "u": "javascript:x"}]})
            ok(r["ok"] and tocados == ["Uno"] and r["cola"] == {"id": "pl1", "j": 0, "n": 4, "fin": False} and B._COLA["items"][3]["u"] == "", "cola: la lleva el servidor y toca la primera parte")
            B._COLA["t0"] -= 30
            B._cola_vigilar({"hay": True, "titulo": "Uno", "estado": "Playing", "pos": 10, "fin": 200})
            B._cola_vigilar({"hay": True, "titulo": "Uno", "estado": "Playing", "pos": 199, "fin": 200})
            _t.sleep(0.05)
            ok(B._COLA["j"] == 1 and tocados[-1] == "Lista", "cola: salta un segundo antes del final (antes de que YouTube Music ponga la suya)")
            B._COLA["t0"] -= 30
            B._cola_vigilar({"hay": True, "titulo": "Tema 1 de la lista", "estado": "Playing", "pos": 5, "fin": 200})
            B._cola_vigilar({"hay": True, "titulo": "Tema 2 de la lista", "estado": "Playing", "pos": 199.5, "fin": 200})
            ok(B._COLA["j"] == 1, "cola: dentro de una playlist no salta en cada canción")
            B._cola_vigilar({"hay": True, "titulo": "Tema 2 de la lista", "estado": "Paused", "pos": 199, "fin": 200})
            _t.sleep(0.05)
            ok(B._COLA["j"] == 2 and tocados[-1] == "Tres", "cola: la playlist terminó y se detuvo: sigue la siguiente parte")
            B._COLA["t0"] -= 30
            B._cola_vigilar({"hay": True, "titulo": "Tres", "estado": "Playing", "pos": 5, "fin": 200})
            B._cola_vigilar({"hay": True, "titulo": "Tres", "estado": "Playing", "pos": 197, "fin": 200})
            B._cola_vigilar({"hay": True, "titulo": "Otra que puso YouTube", "estado": "Playing", "pos": 1, "fin": 180})
            _t.sleep(0.05)
            ok(B._COLA["j"] == 3, "cola: si el reproductor pasó a otra canción al terminar la nuestra, Baco pone la suya")
            B._COLA["t0"] -= 30
            B._cola_vigilar({"hay": True, "titulo": "Mala", "estado": "Playing", "pos": 5, "fin": 200})
            B._cola_vigilar({"hay": True, "titulo": "Mala", "estado": "Playing", "pos": 60, "fin": 200})
            n0 = len(tocados)
            B._cola_vigilar({"hay": True, "titulo": "La que pidió con Atlas", "estado": "Playing", "pos": 1, "fin": 180})
            _t.sleep(0.05)
            ok(B._COLA["fin"] and len(tocados) == n0, "cola: si a media canción se pone otra («Atlas, pon …»), la cola se corta y no la pisa")
            items, antes_cache = B._COLA["items"], B._MEDIA_CACHE.get("v")
            B._MEDIA_CACHE["v"] = {"hay": True, "titulo": "Lista", "estado": "Playing"}
            B.cola({"id": "pl1", "j": 1, "accion": "seguir", "items": items})
            n = len(tocados)
            ok(B._COLA["j"] == 1 and not B._COLA["fin"] and len(tocados) == n and B.media()["cola"]["j"] == 1,
               "cola: tras reiniciar Atlas, «seguir» retoma la cola si suena su canción, sin cortarla")
            B._MEDIA_CACHE["v"] = {"hay": True, "titulo": "Una canción suelta", "estado": "Playing"}
            B.cola({"id": "pl1", "j": 2, "accion": "seguir", "items": items})
            ok(B._COLA["fin"] and len(tocados) == n, "cola: tras reiniciar, una cola vieja no revive si suena otra cosa")
            B._MEDIA_CACHE["v"] = antes_cache
            ok(B.cola({"accion": "parar"})["cola"] is None and B.media()["cola"] is None, "cola: ✕ la detiene también en el servidor")
        finally:
            B.tocar, B._media = antes_t, antes_m
            B._COLA.update(id="", items=[], j=0, fin=False)
        import atlas_baco_mas as _MAS
        _MAS.anotar_sonado({"hay": True, "estado": "Playing", "titulo": "Exacta", "artista": "Z", "app_n": "Edge"})
        _MAS.poner_enlace("Exacta", "Z", "https://music.youtube.com/watch?v=abcdef123")
        _MAS.poner_enlace("Otra", "Z", "https://music.youtube.com/watch?v=zzz")
        ok(_MAS.sonado()[-1].get("u") == "https://music.youtube.com/watch?v=abcdef123" and not any(x["t"] == "Otra" for x in _MAS.sonado()),
           "lo que sonó guarda el video exacto (para no buscar otra versión con el mismo nombre)")
        ok(B._no_es_musica({"hay": True, "app": "com.squirrel.AnthropicClaude.claude"}) and not B._no_es_musica({"hay": True, "app": "Spotify.exe"}),
           "Ahora suena: la app de Claude no cuenta como música")
        ok(B.media()["titulo"] == "Dos" and B.media()["app_n"] == "Spotify" and "$padre" in B._PS_VIGIA and "function Elegir" in B._PS_VIGIA and "$s = Elegir $mgr" in B._PS_VIGIA and "anthropic|claude" in B._PS_MEDIA,
           "Ahora suena: el vigía de música deja al día la canción que cambió (sin esperar al sondeo)")
    finally:
        B._VIGIA.clear(); B._VIGIA.update(antes_v); B._MEDIA_CACHE.update(t=0.0, v=None)


if __name__ == "__main__":
    sys.exit(main())

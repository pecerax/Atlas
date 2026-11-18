"""Ajustes personales de Atlas en un solo lugar (pedido del usuario, 17-11-2026: «hay que analizar todas estas mañas
chicas para que las personas puedan personalizarlo»; eligió la opción B: ajustes.json + rueda de ajustes en la HUD).

hud/ajustes.json guarda solo lo que la persona cambió; lo que falta toma el valor de DEFAULTS (los de hoy).
CATALOGO describe cada ajuste para la rueda de la HUD y para responder «¿dónde cambio…?».
Claves con punto: get("avisos.antes_min"). Las dos claves antiguas (stt_model, sonido_alarma) siguen arriba.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "ajustes.json"

DEFAULTS: dict = {
    "sonido_alarma": "pulso",
    "ciudad_clima": {"name": "Santiago", "lat": -33.4489, "lon": -70.6693},
    "avisos": {
        "antes_min": 60,             # aviso antes de cada actividad del calendario
        "alarma_tope_min": 60,       # alarmas y llamadas suenan hasta apagarlas, con este tope
    },
    "telegram": {
        "ausente_min": 10,           # sin hablarle a Atlas este rato: se asume que no está frente al PC
    },
    # fuentes que el usuario pidió vigilar aunque no espere nada puntual (pedido del 17-11-2026: «solo vigilo cuando estoy
    # esperando algo; debo poder decir deja de vigilar Canvas»). Apagadas por defecto: una fuente se vigila mientras haya
    # algo esperado de ella o si el usuario dijo «vigila U-Cursos». «Deja de vigilar U-Cursos» la apaga.
    "vigilar": {"correo": False, "ucursos": False, "canvas": False},
    "frecuencias": {
        "bandeja_seg": 60,           # no leídos, pestaña Correo y los correos que espera (18-11-2026: una sola frecuencia)
        "ucursos_min": 20,
        "ucursos_con_nota_min": 5,  # cuando espera una nota puntual: solo ese ramo (pedido 18-11-2026)
    },
}

# seccion, clave, nombre, explicación, frase por voz (o ""), archivo si no es ajustes.json
CATALOGO: list[dict] = [
    {"seccion": "Avisos y alarmas", "clave": "avisos.antes_min", "min": 6, "nombre": "Avisar antes de una actividad",
     "unidad": "min", "explica": "Campanita, voz y Telegram una vez antes de cada actividad del calendario.",
     "palabras": "antes reunion actividad evento aviso previo anticipacion recordar hora"},
    {"seccion": "Avisos y alarmas", "clave": "ramos.json → avisar_antes", "nombre": "Qué clases cuentan como actividad",
     "explica": "En cada ramo, la lista avisar_antes (hoy solo los auxiliares de Introducción a la Programación).",
     "archivo": "ramos.json", "palabras": "clase clases auxiliar auxiliares catedra ramo cuenta actividad evento aviso avisar"},
    {"seccion": "Avisos y alarmas", "clave": "avisos.alarma_tope_min", "min": 1, "nombre": "Tope de las alarmas que suenan en bucle",
     "unidad": "min", "explica": "Alarmas, correos esperados y llamadas suenan hasta apagarlas, con este tope.",
     "palabras": "alarma tope bucle loop suena sonar cuanto rato llamada"},
    {"seccion": "Avisos y alarmas", "clave": "sonido_alarma", "opciones": ["pulso", "campanita", "despertador", "ascendente"], "nombre": "Sonido de las alarmas",
     "explica": "pulso, campanita, despertador o ascendente.",
     "palabras": "sonido alarma tono campanita despertador pulso ascendente"},
    {"seccion": "Telegram", "clave": "telegram.ausente_min", "min": 1, "nombre": "Cuándo se asume que no está frente al PC",
     "unidad": "min", "explica": "Pasado este rato sin tocar el teclado ni el mouse, los avisos van por Telegram. Si está en el PC, solo "
                "va por Telegram un aviso importante que nadie apagó en 3 minutos.",
     "palabras": "telegram celular ausente lejos pc frente minutos mandar notificacion"},
    {"seccion": "Correo", "clave": "frecuencias.bandeja_seg", "min": 20, "nombre": "Cada cuánto revisa la bandeja",
     "unidad": "s", "explica": "Contador de no leídos, pestaña Correo y, si espera un correo, también lo busca a este ritmo.",
     "palabras": "bandeja correo no leidos revisar frecuencia cada cuanto actualizar mail vigilancia esperado esperando buscar"},
    {"seccion": "Correo", "clave": "correo_filtro.json", "nombre": "Remitentes que nunca se esconden",
     "explica": "Además de los fijos (U-Cursos, @uchile.cl), los que ponga en correo_filtro.json.",
     "archivo": "correo_filtro.json", "palabras": "remitente esconder filtro publicidad spam importante nunca"},
    {"seccion": "Correo", "clave": "cuentas.json", "nombre": "Apodos de las cuentas de correo",
     "explica": "Cómo llama a cada cuenta (personal, la pega, la Chile).", "archivo": "cuentas.json",
     "palabras": "cuenta cuentas apodo nombre correo gmail empresa chile"},
    {"seccion": "Universidad", "clave": "frecuencias.ucursos_min", "min": 5, "nombre": "Cada cuánto revisa U-Cursos",
     "unidad": "min", "explica": "Notas y publicaciones de sus ramos.",
     "palabras": "ucursos u-cursos notas publicaciones revisar frecuencia cada cuanto"},
    {"seccion": "Universidad", "clave": "frecuencias.ucursos_con_nota_min", "min": 3, "nombre": "U-Cursos cuando espera una nota",
     "unidad": "min", "explica": "Más seguido mientras haya una vigilancia de nota.",
     "palabras": "ucursos nota esperando vigilancia frecuencia"},
    {"seccion": "Universidad", "clave": "ramos.json", "nombre": "Ramos, apodos y cuáles dicta",
     "explica": "Nombre, apodos, lo que dicta y lo que se avisa de cada ramo.", "archivo": "ramos.json",
     "palabras": "ramo ramos apodo dicta curso cursos universidad"},
    {"seccion": "Diccionario", "clave": "diccionario.json", "nombre": "Correcciones de voz",
     "explica": "Lo que la voz escribe mal y lo que Atlas entiende en su lugar (por ejemplo Chego → Shego). "
                "Es el mismo diccionario del lápiz ✎ de la consola (pestaña DICCIONARIO).",
     "archivo": "~/.atlas/diccionario.json",
     "palabras": "voz escucha entiende corregir correccion mal escrito apodo transcribe chego shego regla equivalencia"},
    {"seccion": "Diccionario", "clave": "contactos.json → apodos", "nombre": "Apodos de sus contactos",
     "explica": "Cómo les dice usted a las personas de su libreta.", "archivo": "contactos.json",
     "palabras": "apodo apodos contacto contactos persona nombre le digo libreta"},
    {"seccion": "Diccionario", "clave": "accesos.json → dice", "nombre": "Formas de decir cada acceso",
     "explica": "Cómo puede pedir Fortuna, Hermes o Cronos.", "archivo": "accesos.json",
     "palabras": "acceso accesos app abrir fortuna hermes cronos decir"},
    {"seccion": "Diccionario", "clave": "repertorio.json → alias", "nombre": "Cómo suenan sus artistas",
     "explica": "Cómo puede escuchar la voz el nombre de cada artista.", "archivo": "repertorio.json",
     "palabras": "artista artistas musica cancion alias suena nombre"},
    {"seccion": "Voz y trato", "clave": "ciudad_clima", "nombre": "Ciudad del clima",
     "explica": "Nombre, latitud y longitud de la ciudad que usa para el clima.",
     "palabras": "clima ciudad tiempo temperatura lluvia donde vivo"},
    {"seccion": "Voz y trato", "clave": "stt_model", "nombre": "Modelo para entender la voz",
     "explica": "parakeet o un tamaño de Whisper (por ejemplo large-v3-turbo).",
     "palabras": "reconocimiento voz entender escuchar modelo microfono parakeet whisper"},
    {"seccion": "Voz y trato", "clave": "voz.json", "nombre": "Voz con la que habla",
     "explica": "La voz de Piper y su velocidad.", "archivo": "voz.json",
     "palabras": "voz habla hablar velocidad lento rapido piper suena"},
]

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def leer() -> dict:
    """Lo que dejó la persona encima de DEFAULTS. Si el archivo está roto, valen los predeterminados."""
    global _cache
    try:
        mt = FILE.stat().st_mtime
    except OSError:
        return copy.deepcopy(DEFAULTS)
    with _lock:
        if _cache and _cache[0] == mt:
            return copy.deepcopy(_cache[1])
        try:
            data = json.loads(FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        full = _merge(DEFAULTS, data)
        _cache = (mt, full)
        return copy.deepcopy(full)


def get(clave: str, default=None):
    cur = leer()
    for part in clave.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def num(clave: str, default: float, minimo: float = 0) -> float:
    """Un número del archivo; si no es número o está bajo el mínimo, el predeterminado."""
    try:
        v = float(get(clave, default))
    except (TypeError, ValueError):
        return default
    return v if v >= minimo else default


FUENTES = {"correo": "su correo", "ucursos": "U-Cursos", "canvas": "Canvas"}


def vigilar(fuente: str) -> bool:
    """¿Pidió el usuario vigilar esa fuente (correo, ucursos, canvas) sin esperar nada puntual? Solo un sí claro cuenta."""
    return get(f"vigilar.{fuente}", False) is True


def guardar(clave: str, valor) -> None:
    """Cambia una clave en ajustes.json conservando el resto (stt_model, sonido_alarma, etc.)."""
    try:
        data = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    cur = data
    parts = clave.split(".")
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = valor
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(FILE)


# ------------------------------------------------------------------ «¿dónde cambio…?»
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


DONDE_RE = re.compile(r"(?i)\b(?:d[oó]nde|c[oó]mo)\s+(?:se\s+)?(?:cambi[oa]|configur[oa]|ajust[oa]|modific[oa]|personaliz[oa]|"
                      r"pued[oe]\s+cambiar|cambiar|configurar|ajustar|modificar|personalizar)\b")

_VACIAS = set("de la el los las un una que me se lo le en a y o por para con cuanto cuando donde como cambio cambia "
              "cambiar configuro configurar ajusto ajustar modifico modificar puedo puede atlas senor".split())


def es_pregunta(texto: str) -> bool:
    return bool(DONDE_RE.search(texto or ""))


def _valor_txt(item: dict, data: dict) -> str:
    if item.get("archivo"):
        return ""
    cur = data
    for p in item["clave"].split("."):
        cur = cur.get(p) if isinstance(cur, dict) else None
    if isinstance(cur, dict):
        cur = cur.get("name", "")
    if cur in (None, ""):
        return ""
    u = item.get("unidad")
    if u == "min":
        return "1 hora" if cur == 60 else f"{cur:g} minutos"
    if u == "s":
        return "1 minuto" if cur == 60 else f"{cur:g} segundos"
    return str(cur)


def buscar(texto: str, n: int = 2) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9]+", _norm(texto)) if w not in _VACIAS and len(w) > 2]
    bags = [set(re.findall(r"[a-z0-9]+", _norm(it["palabras"] + " " + it["nombre"]))) for it in CATALOGO]

    def hit(w: str, hay: set) -> bool:
        return w in hay or (len(w) >= 5 and any(h.startswith(w[:5]) for h in hay))

    scored = []
    for item, hay in zip(CATALOGO, bags):
        # una palabra que solo calza con pocos ajustes pesa más («clases» decide sobre «avisas»)
        s = sum(1 / sum(1 for b in bags if hit(w, b)) for w in words if hit(w, hay))
        if s:
            scored.append((round(s, 3), item))
    scored.sort(key=lambda x: -x[0])
    return [it for s, it in scored[:n] if s == scored[0][0]]


def donde(texto: str, trato: str = "señor") -> str:
    """Respuesta hablada a «¿dónde cambio…?»: dónde está en la rueda y en qué archivo, con el valor de hoy."""
    data = leer()
    hits = buscar(texto)
    if not hits:
        return (f"Casi todo se cambia en la rueda de ajustes, {trato}: el engranaje abajo en el riel de la izquierda. "
                "También está en el archivo ajustes.json, en la carpeta hud de Atlas. ¿Qué quiere cambiar?")
    parts = []
    for it in hits:
        val = _valor_txt(it, data)
        archivo = it.get("archivo") or f"ajustes.json, clave {it['clave']}"
        parts.append(f"{it['nombre']} está en la rueda de ajustes, sección {it['seccion']}"
                     + (f"; hoy está en {val}" if val else "") + f". En archivo: {archivo}.")
    return f"{' '.join(parts)} La rueda es el engranaje abajo en el riel, {trato}."


ABRIBLES = {"ajustes.json", "ramos.json", "correo_filtro.json", "cuentas.json", "voz.json", "equivalencias.json",
            "contactos.json", "accesos.json", "repertorio.json"}


def _crudo(clave: str, data: dict):
    cur = data
    for p in clave.split("."):
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def vista() -> dict:
    """Para la rueda de la HUD: secciones con sus ajustes, el valor actual y cómo se edita."""
    data = leer()
    secciones: dict[str, list] = {}
    for it in CATALOGO:
        crudo = None if it.get("archivo") else _crudo(it["clave"], data)
        tipo = "archivo" if it.get("archivo") else "num" if it.get("unidad") else "opcion" if it.get("opciones") else "texto"
        secciones.setdefault(it["seccion"], []).append(
            {"clave": it["clave"], "nombre": it["nombre"], "explica": it["explica"], "tipo": tipo,
             "valor": _valor_txt(it, data), "crudo": crudo if not isinstance(crudo, dict) else crudo.get("name", ""),
             "unidad": it.get("unidad", ""), "min": it.get("min", 0), "opciones": it.get("opciones", []),
             "archivo": it.get("archivo") or "ajustes.json"})
    return {"secciones": [{"nombre": k, "ajustes": v} for k, v in secciones.items()]}


def cambiar(clave: str, valor) -> dict:
    """Lo que manda la rueda: solo claves del catálogo, números sobre su mínimo y opciones de la lista."""
    it = next((x for x in CATALOGO if x["clave"] == clave and not x.get("archivo")), None)
    if not it:
        return {"ok": False, "error": "Ese ajuste no se cambia desde aquí."}
    if it.get("unidad"):
        try:
            v = float(valor)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Tiene que ser un número."}
        tope = 1440 if it["unidad"] == "min" else 86400
        if not (it.get("min", 0) <= v <= tope):
            return {"ok": False, "error": f"Tiene que estar entre {it.get('min', 0)} y {tope}."}
        guardar(clave, int(v) if v == int(v) else v)
    elif it.get("opciones"):
        if valor not in it["opciones"]:
            return {"ok": False, "error": "Esa opción no existe."}
        guardar(clave, valor)
    else:
        return {"ok": False, "error": f"Este se cambia en el archivo ajustes.json (clave {clave})."}
    return {"ok": True, "valor": _valor_txt(it, leer())}

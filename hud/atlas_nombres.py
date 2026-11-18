"""Diccionario del usuario y lista de lo que Atlas sabe abrir o conectar (18-11-2026).

Uso real: «Conecta Ucursos» se transcribió «Conecta Ursus» y Atlas buscó «ursus» en el menú Inicio. El usuario eligió
«solo el diccionario»: Atlas no adivina nombres parecidos. Orden con que se entiende una frase (hud_server._route):
  0. diccionario.json es la ÚNICA lista de correcciones (unificado 18-11-2026). Trae:
     - «palabras»: escuchado -> correcto («origen»: semilla, equivalencias o lápiz); se editan y borran en el panel.
     - «reglas»: correcciones que no son palabra -> palabra: quitar muletillas, cambiar solo si cerca viene otra
       palabra (o una parecida, que el modelo elige al guardar), solo al inicio, excepto si… Se aplican antes. Desde
       el 18-11-2026 se leen como frase y se editan en el Diccionario; las expresiones antiguas se pasaron con
       reglas_migracion.json (respaldo diccionario.json.antes_reglas.bak).
     - «vocabulario»: palabras que la voz debe reconocer mejor (antes vocabulario.txt); se agregan y borran en el panel.
     La primera vez se migra desde equivalencias.json y vocabulario.txt (quedan con respaldo .antes_unificar.bak y
     ya no se leen).
  1. diccionario.json (~/.atlas): palabras que la voz escribe mal -> lo que significaban («ursus» -> «U-Cursos»).
     Palabra o frase completa, sin importar tildes ni mayúsculas: «ursus» no toca «recursos». Las entradas con
     «contexto»: «app» solo valen al nombrar una app («abre ermes», «qué es eernes», «Ermes» a secas).
     Trae de inicio las variantes de Hermes, Fortuna y Cronos que antes estaban escondidas en el código.
  2. frases.json (~/.atlas): una frase -> una acción concreta de la lista. Se usa si la frase dicha es igual o casi igual.
  3. Las rutas normales y, al final, el menú Inicio.
Las dos listas se editan con el lápiz ✎ de cada mensaje en la consola; por voz no se guarda nada.
Nada de esto va al modelo.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path

DICCIONARIO = Path(os.environ.get("ATLAS_DICCIONARIO") or (Path.home() / ".atlas" / "diccionario.json"))
FRASES = Path(os.environ.get("ATLAS_FRASES") or (Path.home() / ".atlas" / "frases.json"))
# Fuentes antiguas (18-11-2026: todo se unificó en diccionario.json). Se leen UNA vez, al migrar; después no se usan.
HERE = Path(__file__).resolve().parent
EQUIV_VIEJO = HERE / "equivalencias.json"
VOCAB_VIEJO = HERE / "vocabulario.txt"
VOCAB_INICIAL = ["Atlas", "Jarvis", "Gmail", "correo", "correos", "bandeja", "cuenta personal", "cuenta del trabajo",
                 "Empresa", "Universidad de Chile", "la U", "Spotify", "Discord", "Steam", "YouTube", "PedidosYa", "Cabify",
                 "Platanus", "señor"]

# Acciones de Atlas (rutas) que se pueden asociar a una frase, además de lo que sabe abrir o conectar
INTENCIONES = [
    ("Horario de la semana", "muéstrame mi horario"), ("Agenda de hoy", "qué tengo hoy"),
    ("Tareas y entregas", "qué tareas tengo"), ("Notas nuevas (U-Cursos)", "¿tengo notas nuevas?"),
    ("Correos sin leer", "¿tengo correos sin leer?"), ("Mensajes sin leer", "¿tengo mensajes sin leer?"),
    ("Pendientes", "mis pendientes"), ("Gastos del ciclo (Hermes)", "cuánto he gastado"),
    ("Actualizar Hermes", "actualiza Hermes"), ("Actualizar Fortuna", "actualiza Fortuna"),
    ("Cómo van mis fondos (Fortuna)", "cómo van mis fondos"), ("Clima", "cómo está el clima"),
    ("Pon música", "pon música"), ("Siguiente canción", "siguiente canción"), ("Estado de la red", "estado de la red"),
    ("Notas nuevas (Canvas)", "¿tengo notas nuevas en Canvas?"),
    ("Conectar U-Cursos", "conecta U-Cursos"), ("Conectar Canvas", "conecta Canvas"),
]

# Servicios que se conectan (iniciar sesión) y qué hacer con cada verbo. «abre U-Cursos» abre la página;
# «conecta U-Cursos» inicia sesión para que Atlas revise las notas.
SERVICIOS = {
    "U-Cursos": {"conecta": "conecta U-Cursos", "abre": "abre la página www.u-cursos.cl"},
    "Canvas": {"conecta": "conecta Canvas", "abre": "conecta Canvas"},
}
# Variantes que la voz escribe para las apps (antes en hud_server._APP_VARIANTES): entradas iniciales del diccionario,
# solo en contexto de app («por fortuna llegué» o «le dije ermes que viniera» no cambian)
SEMILLA = ([(v, "Hermes") for v in ("eernes", "heernes", "ernes", "hernes", "ermes", "jermes", "hermez")]
           + [(v, "Fortuna") for v in ("fortunna", "fortuma")]
           + [(v, "Cronos") for v in ("kronos", "crono", "krono", "cronus")])
APP_CTX = (r"(?:(?:atlas|jarvis),?\s+)?(?:(?:qu[eé]|que)\s+(?:es|hace|tiene|hay\s+en)|para\s+qu[eé]\s+sirve|c[oó]mo\s+funciona|"
           r"h[aá]blame\s+de|abre(?:me)?|abrir|[aá]breme|mu[eé]strame|muestra|cierra|ve\s+a|ir\s+a|en|entra\s+a)\s+(?:la\s+app\s+)?")


def plano(s: str) -> str:
    """Minúsculas, sin tildes, sin espacios ni guiones: «U-Cursos» y «u cursos» -> «ucursos»."""
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


# ---------------------------------------------------------------------------------------------- menú Inicio
_MENU: dict = {"t": 0.0, "nombres": []}


def menu_inicio(cache_s: float = 300.0) -> list[str]:
    """Nombres de los accesos directos del menú Inicio y del escritorio (sin desinstaladores). Se recuerda 5 min."""
    if time.time() - _MENU["t"] < cache_s:
        return _MENU["nombres"]
    dirs = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("USERPROFILE", "")) / "Desktop"]
    nombres: set[str] = set()
    for d in dirs:
        try:
            if d.is_dir():
                nombres |= {p.stem for p in d.rglob("*.lnk") if not re.search(r"(?i)uninstall|desinstal", p.stem)}
        except OSError:
            pass
    _MENU.update(t=time.time(), nombres=sorted(nombres))
    return _MENU["nombres"]


def conocidos(apps: list[str] = (), accesos: list[dict] = (), pc_apps: list[str] = (), sitios: list[str] = (),
              menu: list[str] | None = None) -> dict[str, dict]:
    """Lista única: nombre visible -> {"tipo": servicio|app|acceso|programa|sitio|menu, "dice": [variantes]}."""
    out: dict[str, dict] = {}

    def add(nombre: str, tipo: str, dice=()):
        if not nombre:
            return
        k = next((x for x in out if plano(x) == plano(nombre)), None)
        if k is None:
            out[nombre] = {"tipo": tipo, "dice": list(dice)}
        else:
            out[k]["dice"] += list(dice)
    for s in SERVICIOS:
        add(s, "servicio", ["ucursos", "u cursos"] if s == "U-Cursos" else [])
    for a in apps:
        add(a, "app")
    for a in accesos:
        add(a.get("nombre", ""), "acceso", [d for d in a.get("dice", []) if d])
    for p in pc_apps:
        add(p, "programa")
    for s in sitios:
        add(s, "sitio")
    for m in (menu_inicio() if menu is None else menu):
        add(m, "menu")
    return out


# ---------------------------------------------------------------------------------------------- diccionario y frases
def _doc(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _leer(path: Path, clave: str) -> list[dict]:
    return [x for x in _doc(path).get(clave, []) if isinstance(x, dict)]


def _escribir_doc(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _escribir(path: Path, clave: str, lista: list, nota: str) -> None:
    """Cambia solo «clave»: el resto del archivo (reglas, vocabulario, migrado) queda igual."""
    doc = _doc(path)
    doc["_nota"], doc[clave] = nota, lista
    _escribir_doc(path, doc)


# una regla simple de equivalencias.json es \b(?:a|b|c)\b o \bpalabra\b, con palabras de letras y espacios
_SIMPLE = re.compile(r"^\\b(?:\(\?:(?P<alts>[^()\[\]{}*+?^$|\\]+(?:\|[^()\[\]{}*+?^$|\\]+)*)\)|(?P<one>[^()\[\]{}*+?^$|\\]+))\\b$")
_WORD = re.compile(r"^[a-záéíóúüñ][a-záéíóúüñ ]{0,38}[a-záéíóúüñ]$", re.I)


def escucha_de(patron: str) -> list[str] | None:
    """Las palabras que dispara una regla simple de equivalencias.json; None si es una expresión (avanzada)."""
    p = patron.replace("\\s+", " ").replace("\\s", " ")
    m = _SIMPLE.match(p)
    if not m:
        return None
    alts = (m.group("alts") or m.group("one") or "").split("|")
    return alts if all(_WORD.match(a) for a in alts) else None


_NOTA_DIC = ("Única lista de correcciones de Atlas. «palabras»: lo que la voz escribe mal (escuchado) y lo que significaba "
             "(correcto); «contexto»: «app» = solo al nombrar una app («abre ermes»); «origen»: semilla, equivalencias "
             "(migrado de equivalencias.json) o lápiz. «reglas»: correcciones con condiciones (quitar una muletilla, "
             "cambiar una palabra solo si cerca viene otra, solo al inicio, excepto si…); se aplican primero. Desde el "
             "18-11-2026 se leen como frase y se editan en el Diccionario (antes eran expresiones de solo lectura). "
             "«vocabulario»: palabras que la voz debe reconocer mejor (antes vocabulario.txt). "
             "Se edita en el Diccionario y con ✎ Corregir del Historial.")
# Cómo se pasó cada expresión antigua a reglas del Diccionario (se usa al migrar; ver _reglas_de_expresion)
TABLA_MIGRACION = HERE / "reglas_migracion.json"


def _migrar(p: Path, doc: dict) -> dict:
    """Primera vez (sin «migrado»): junta en diccionario.json las semillas de las apps, las correcciones de
    equivalencias.json (palabra -> palabra a «palabras»; las expresiones a «reglas», en su orden) y vocabulario.txt
    (a «vocabulario»). Sin duplicados: si «escuchado» ya estaba, gana lo que ya había (lo corregido con el lápiz)."""
    hoy = time.strftime("%Y-%m-%d")
    pal = [x for x in doc.get("palabras", []) if isinstance(x, dict)]
    if not p.exists():   # las variantes de las apps, visibles y editables en el panel
        pal = [{"escuchado": e, "correcto": c, "fecha": hoy, "veces": 0, "contexto": "app", "origen": "semilla"}
               for e, c in SEMILLA]
    for x in pal:
        x.setdefault("origen", "semilla" if x.get("contexto") == "app" and (x.get("escuchado"), x.get("correcto")) in SEMILLA
                     else "lápiz")
    vistos = {_clave(str(x.get("escuchado", ""))) for x in pal}
    reglas, n_pal, dup = [], 0, 0
    try:
        eq = json.loads(EQUIV_VIEJO.read_text(encoding="utf-8")).get("reglas", [])
    except (OSError, ValueError, AttributeError):
        eq = []
    for r in eq:
        if not isinstance(r, dict) or not r.get("de"):
            continue
        de, a, nota = str(r["de"]), str(r.get("a", "")), str(r.get("nota", ""))
        esc = escucha_de(de) if a.strip() and "\\" not in a else None
        if esc is None:   # expresión (muletillas, «por el disco» -> «por Discord»…): pasa a reglas que se leen y editan
            reglas += _reglas_de_expresion({"de": de, "a": a, "nota": nota, "origen": "equivalencias"})
            continue
        for w in esc:
            if _clave(w) in vistos:
                dup += 1
                continue
            vistos.add(_clave(w))
            n_pal += 1
            pal.append({"escuchado": w, "correcto": a, "fecha": hoy, "veces": 0, "origen": "equivalencias", "nota": nota})
    try:
        voc = [w.strip() for w in VOCAB_VIEJO.read_text(encoding="utf-8").splitlines()]
        voc = [w for w in voc if w and not w.startswith("#")]
    except OSError:
        voc = list(VOCAB_INICIAL)
    vocab, vv = [], set()
    for w in [*doc.get("vocabulario", []), *voc]:
        if isinstance(w, str) and _clave(w) and _clave(w) not in vv:
            vv.add(_clave(w))
            vocab.append(w.strip())
    doc.update(_nota=_NOTA_DIC, palabras=pal, reglas=reglas, vocabulario=vocab,
               migrado={"fecha": time.strftime("%Y-%m-%d %H:%M"), "palabras_de_equivalencias": n_pal,
                        "reglas_de_equivalencias": len(reglas), "palabras_de_vocabulario": len(voc),
                        "duplicados_omitidos": dup, "reglas_editables": time.strftime("%Y-%m-%d %H:%M")})
    return doc


def _nuevo_id() -> str:
    return "r" + uuid.uuid4().hex[:8]


def _reglas_de_expresion(r: dict) -> list[dict]:
    """Una expresión antigua -> sus reglas del Diccionario, según reglas_migracion.json (18-11-2026). Si alguna no
    estuviera en la tabla, queda como «expresion»: se aplica igual que antes y se puede borrar (no editar)."""
    try:
        tabla = {x["de"]: x for x in json.loads(TABLA_MIGRACION.read_text(encoding="utf-8")).get("expresiones", [])}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        tabla = {}
    t, hoy, origen = tabla.get(r.get("de")), time.strftime("%Y-%m-%d"), r.get("origen") or "equivalencias"
    if not t:
        return [{"id": _nuevo_id(), "tipo": "expresion", "de": r.get("de", ""), "a": r.get("a", ""),
                 "nota": r.get("nota", ""), "origen": origen}]
    return [{"id": _nuevo_id(), **x, "nota": r.get("nota") or t.get("nota", ""), "origen": origen, "fecha": hoy}
            for x in t.get("reglas", [])]


def _cargar(path: Path | None = None) -> dict:
    """diccionario.json completo; la primera vez lo migra (ver _migrar). Si todavía trae «reglas» antiguas
    (expresiones de solo lectura, sin «tipo»), las pasa a reglas editables, con respaldo .antes_reglas.bak."""
    p = path or DICCIONARIO
    doc = _doc(p)
    if "migrado" not in doc:
        doc = _migrar(p, doc)
        try:
            _escribir_doc(p, doc)
        except OSError:
            pass
    rs = [x for x in doc.get("reglas", []) if isinstance(x, dict)]
    if any("tipo" not in x or not x.get("id") for x in rs):
        nuevas = []
        for x in rs:
            if "tipo" in x:
                nuevas.append(x if x.get("id") else {"id": _nuevo_id(), **x})
            elif x.get("de"):
                nuevas += _reglas_de_expresion(x)
        bak = p.with_name(p.name + ".antes_reglas.bak")
        try:
            if p.exists() and not bak.exists():
                bak.write_bytes(p.read_bytes())
            doc["reglas"], doc["_nota"] = nuevas, _NOTA_DIC
            doc.setdefault("migrado", {})["reglas_editables"] = time.strftime("%Y-%m-%d %H:%M")
            _escribir_doc(p, doc)
        except OSError:
            doc["reglas"] = nuevas
    return doc


def palabras(path: Path | None = None) -> list[dict]:
    return [x for x in _cargar(path).get("palabras", [])
            if isinstance(x, dict) and str(x.get("escuchado", "")).strip() and x.get("correcto")]


def reglas(path: Path | None = None) -> list[dict]:
    """Reglas del Diccionario (quitar / cambiar con condiciones), en su orden. Cada una: id, tipo («cambiar»,
    «quitar» o «expresion» antigua), escuchado, correcto, cerca [{w, lado, justo, tambien, parecido, parecidas}],
    inicio, orden, app, excepto [{w, lado}], nota, origen, fecha."""
    return [x for x in _cargar(path).get("reglas", []) if isinstance(x, dict)
            and (str(x.get("escuchado", "")).strip() if x.get("tipo") in ("cambiar", "quitar") else x.get("de"))]


# ---------------------------------------------------------------------------------------------- motor de reglas
# Palabras que cuentan como «una orden» (opción «solo si después viene una orden»): las de la regla antigua de «un».
ORDENES = ["atlas", "jarvis", "guarda", "pon", "ponme", "abre", "marca", "agenda", "agéndame", "recuérdame", "qué",
           "cuál", "cuándo", "cómo", "dime", "busca", "lee", "léelo", "resume", "reproduce", "sube", "baja", "cierra"]
_PRE = re.compile(r"^[¿¡\"«(“']+")
_POST = re.compile(r"[?!.,;:\"»)”'…]+$")


def _k(s: str) -> str:
    """Clave de una palabra: minúsculas, sin tildes, sin signos alrededor («¿Cuándo» -> «cuando»; «U-Cursos» queda)."""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")
    return s.strip("¿?¡!.,;:\"'«»()“”…")


_ORD = {_k(w) for w in ORDENES}


def _tokens(text: str) -> list[tuple[str, str, str, str, str]]:
    """(original, signos antes, palabra, signos después, clave) por cada palabra de la frase."""
    out = []
    for raw in (text or "").split():
        m = _PRE.match(raw)
        pre = m.group(0) if m else ""
        rest = raw[len(pre):]
        m = _POST.search(rest)
        post = m.group(0) if m else ""
        core = rest[:len(rest) - len(post)]
        out.append((raw, pre, core, post, _k(core)))
    return out


def _cerca_palabras(c: dict) -> set[str]:
    ws = {_k(c.get("w", ""))} | {_k(x) for x in c.get("tambien") or []}
    if c.get("parecido"):
        ws |= {_k(x) for x in c.get("parecidas") or []}
    return ws - {""}


def _calza(r: dict, n: list[str], i: int, L: int, al_inicio: bool, toks: list) -> bool:
    if r.get("inicio") and not al_inicio:
        return False
    for c in r.get("cerca") or []:
        w = 2 if c.get("justo", True) else 4   # «justo al lado»: puede haber una palabra entre medio («una»)
        zona = n[i + L:i + L + w] if c.get("lado") == "después" else n[max(0, i - w):i]
        if not (_cerca_palabras(c) & set(zona)):
            return False
    if r.get("orden") and (i + L >= len(n) or n[i + L] not in _ORD):
        return False
    for x in r.get("excepto") or []:
        vecina = n[i + L:i + L + 1] if x.get("lado", "después") == "después" else n[max(0, i - 1):i]
        if _k(x.get("w", "")) in vecina:
            return False
    if r.get("app"):   # solo nombrando la app: «abre ermes», «qué es eernes» o el nombre solo
        antes = " ".join(t[0] for t in toks[:i])
        if not ((i == 0 and i + L == len(n)) or re.fullmatch(r"\s*¿?\s*" + APP_CTX, antes + " ", re.I)):
            return False
    return True


def aplicar_reglas_detalle(text: str, path: Path | None = None, lista: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Aplica las reglas del Diccionario a la frase -> (frase corregida, reglas que la cambiaron). Palabra por palabra:
    en cada lugar gana la regla de más palabras (y, a igual largo, la primera de la lista). Lo que reemplaza conserva
    los signos de alrededor («Si, Leelu.» -> «léelo.»); una muletilla se quita con su coma. Si nada cambia, la frase
    vuelve tal cual (mismos espacios)."""
    rs = reglas(path) if lista is None else lista
    out, usadas = text or "", []
    for r in rs:   # expresiones antiguas que no se pudieron pasar a reglas (si las hubiera): igual que antes
        if r.get("tipo") == "expresion":
            try:
                nuevo = re.sub(r["de"], str(r.get("a", "")), out, flags=re.I)
            except re.error:
                continue
            if nuevo != out:
                out = nuevo
                usadas.append(r)
    normales = []
    for r in rs:
        if r.get("tipo") in ("cambiar", "quitar"):
            f = [_k(w) for w in str(r.get("escuchado", "")).split()]
            if f and all(f) and (r["tipo"] == "quitar" or str(r.get("correcto", "")).strip()):
                normales.append((r, f))
    normales.sort(key=lambda rf: -len(rf[1]))   # estable: a igual largo, el orden de la lista
    toks = _tokens(out)
    n = [t[4] for t in toks]
    piezas, i, al_inicio, arrastre, cambio = [], 0, True, "", False
    while i < len(n):
        hit = None
        for r, f in normales:
            L = len(f)
            if n[i:i + L] != f or (r["tipo"] == "quitar" and L == len(n)):
                continue
            if r["tipo"] == "cambiar":
                a = str(r["correcto"]).split()
                if " ".join(t[2] for t in toks[i:i + len(a)]) == " ".join(a):
                    continue   # ya dice lo correcto («la U de Chile» no se vuelve «la U de Chile de Chile»)
            if _calza(r, n, i, L, al_inicio, toks):
                hit = (r, L)
                break
        if not hit:
            piezas.append(arrastre + toks[i][0])
            arrastre, al_inicio, i = "", False, i + 1
            continue
        r, L = hit
        if r not in usadas:
            usadas.append(r)
        cambio = True
        if r["tipo"] == "quitar":   # «¿Eh, qué hora es?» -> «¿qué hora es?»
            arrastre += toks[i][1]
            i += L
            continue
        piezas.append(arrastre + toks[i][1] + str(r["correcto"]).strip() + toks[i + L - 1][3])
        arrastre, al_inicio, i = "", False, i + L
    if arrastre:
        piezas.append(arrastre)
    return (" ".join(piezas) if cambio else out), usadas


def aplicar_reglas(text: str, path: Path | None = None) -> str:
    return aplicar_reglas_detalle(text, path)[0]


def _lista_txt(ws: list[str], y: str = "o") -> str:
    ws = [f"«{w}»" for w in ws if w]
    return ws[0] if len(ws) == 1 else ", ".join(ws[:-1]) + f" {y} " + ws[-1] if ws else ""


def texto_regla(r: dict) -> str:
    """La regla como frase normal: «Cambiar «disco» por «Discord» solo cuando justo antes venga «por» o «en»…»."""
    if r.get("tipo") == "expresion":
        return f"Regla antigua: {r.get('nota') or r.get('de', '')}"
    partes = []
    cerca = sorted(r.get("cerca") or [], key=lambda c: c.get("lado") != "antes")
    if cerca:
        partes.append("solo cuando " + " y ".join(
            f"{'justo ' if c.get('justo', True) else ''}{c.get('lado', 'antes')} venga "
            f"{_lista_txt([c.get('w', '')] + list(c.get('tambien') or []))}{' o algo parecido' if c.get('parecido') else ''}"
            for c in cerca))
    if r.get("app"):
        partes.append("solo al nombrar una app («abre …», «qué es …»)")
    if r.get("inicio"):
        partes.append("solo si es lo primero que dice")
    if r.get("orden"):
        partes.append("solo si después viene una orden (pon, abre, dime…)")
    if r.get("excepto"):
        lados = {}
        for x in r["excepto"]:
            lados.setdefault(x.get("lado", "después"), []).append(x.get("w", ""))
        partes.append("excepto cuando " + " o ".join(f"{lado} venga {_lista_txt(ws)}" for lado, ws in lados.items()))
    cola = " " + ", ".join(partes) if partes else (" cada vez que lo diga" if r.get("tipo") == "quitar" else " siempre")
    if r.get("tipo") == "quitar":
        return f"Quitar «{r.get('escuchado', '')}»{cola}."
    return f"Cambiar «{r.get('escuchado', '')}» por «{r.get('correcto', '')}»{cola}."


def parecidas_simples(w: str) -> list[str]:
    """Si el modelo no responde: al menos el plural o el singular («canción» -> «canciones»)."""
    w = (w or "").strip().lower()
    if not w or " " in w:
        return []
    sin = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}
    if w.endswith("es") and len(w) > 4:
        return [w[:-2]]
    if w.endswith("s") and len(w) > 3:
        return [w[:-1]]
    if re.search(r"[aeiouáéíóú]$", w):
        return [w + "s"]
    if re.search(r"[áéíóú]n$", w):
        return ["".join(sin.get(c, c) for c in w) + "es"]
    return [w + "es"]


def _limpia_regla(r: dict) -> dict:
    """Valida y ordena una regla que llega del corrector o del Diccionario. ValueError con el motivo si no sirve."""
    txt = lambda s, n: re.sub(r"\s+", " ", str(s or "")).strip()[:n]   # noqa: E731
    tipo = str(r.get("tipo", ""))
    if tipo not in ("cambiar", "quitar"):
        raise ValueError("Elija si se cambia o se quita.")
    de, a = txt(r.get("escuchado"), 61), txt(r.get("correcto"), 81)
    if not _k(de) or len(de) > 60:
        raise ValueError("Falta la palabra que Atlas escucha (máximo 60 letras).")
    if tipo == "cambiar" and (not a or len(a) > 80):
        raise ValueError("Falta lo que quiso decir (máximo 80 letras).")
    cerca = []
    for c in (r.get("cerca") or [])[:4]:
        w = txt(c.get("w"), 40)
        if not _k(w):
            continue
        it = {"w": w, "lado": "después" if c.get("lado") == "después" else "antes", "justo": bool(c.get("justo", True))}
        tam = [txt(x, 40) for x in (c.get("tambien") or []) if _k(txt(x, 40))][:8]
        if tam:
            it["tambien"] = tam
        if c.get("parecido"):
            it["parecido"] = True
            it["parecidas"] = [txt(x, 40) for x in (c.get("parecidas") or []) if _k(txt(x, 40))][:12]
        cerca.append(it)
    excepto = [{"w": txt(x.get("w"), 40), "lado": "antes" if x.get("lado") == "antes" else "después"}
               for x in (r.get("excepto") or [])[:6] if _k(txt(x.get("w"), 40))]
    out = {"tipo": tipo, "escuchado": de}
    if tipo == "cambiar":
        out["correcto"] = a
    for k in ("inicio", "orden", "app"):
        if r.get(k):
            out[k] = True
    if cerca:
        out["cerca"] = cerca
    if excepto:
        out["excepto"] = excepto
    sin_cond = not (cerca or excepto or out.get("inicio") or out.get("orden"))
    if tipo == "cambiar" and de == a:
        raise ValueError("Lo que escuchó y lo que quiso decir son iguales.")
    if tipo == "cambiar" and sin_cond and _k(de) == _k(a) and de.lower() == a.lower():
        raise ValueError("Lo que escuchó y lo que quiso decir son iguales.")
    if tipo == "quitar" and sin_cond and len(_k(de)) < 2:
        raise ValueError("Para quitar una sola letra, ponga una condición (por ejemplo, solo al inicio).")
    return out


def guardar_regla(regla: dict, antes: dict | None = None, path: Path | None = None) -> dict:
    """Guarda una regla del corrector o del Diccionario. «antes»: lo que se está editando ({"tipo": "palabra",
    "escuchado"} o {"tipo": "regla", "id"}), que se reemplaza. Un cambio sin condiciones queda como palabra
    (palabra -> palabra, como siempre); lo demás, como regla. Las palabras parecidas de cada condición vienen ya
    elegidas (las genera el modelo al guardar); si faltan, al menos el plural o singular."""
    p = path or DICCIONARIO
    r = _limpia_regla(regla)
    for c in r.get("cerca", []):
        if c.get("parecido") and not c.get("parecidas"):
            c["parecidas"] = parecidas_simples(c["w"])
    antes = antes or {}
    doc = _cargar(p)
    pal = [x for x in doc.get("palabras", []) if isinstance(x, dict)]
    rs = [x for x in doc.get("reglas", []) if isinstance(x, dict)]
    previa = next((x for x in rs if antes.get("tipo") == "regla" and x.get("id") == antes.get("id")), None)
    prev_p = next((x for x in pal if antes.get("tipo") == "palabra" and _clave(x.get("escuchado", "")) == _clave(antes.get("escuchado", ""))), None)
    hoy = time.strftime("%Y-%m-%d")
    simple = r["tipo"] == "cambiar" and not any(r.get(k) for k in ("cerca", "excepto", "inicio", "orden"))
    if simple:   # palabra -> palabra (también las de las apps, «solo al nombrar una app»)
        if prev_p is not None:
            pal = [x for x in pal if x is not prev_p]
        if previa is not None:
            rs = [x for x in rs if x is not previa]
        igual = next((x for x in pal if _clave(x.get("escuchado", "")) == _clave(r["escuchado"])), None)
        base = prev_p or igual or {}
        pal = [x for x in pal if x is not igual]
        item = {"escuchado": r["escuchado"], "correcto": r["correcto"], "fecha": hoy,
                "veces": int(base.get("veces", 0)) + 1, "origen": base.get("origen") or (previa or {}).get("origen") or "lápiz"}
        if r.get("app"):
            item["contexto"] = "app"
        if base.get("nota") or (previa or {}).get("nota"):
            item["nota"] = base.get("nota") or previa.get("nota")
        pal.append(item)
        doc.update(_nota=_NOTA_DIC, palabras=pal, reglas=rs)
        _escribir_doc(p, doc)
        return {**item, "donde": "palabra"}
    if prev_p is not None:
        pal = [x for x in pal if x is not prev_p]
    base = previa or prev_p or {}
    item = {"id": (previa or {}).get("id") or _nuevo_id(), **r, "fecha": hoy,
            "origen": base.get("origen") or "lápiz"}
    if base.get("nota"):
        item["nota"] = base["nota"]
    if previa is not None:
        rs = [item if x is previa else x for x in rs]
    else:
        # la misma palabra con las mismas condiciones reemplaza a la anterior
        rs = [x for x in rs if not (x.get("tipo") == r["tipo"] and _k(x.get("escuchado", "")) == _k(r["escuchado"])
                                     and x.get("cerca", []) == r.get("cerca", []) and bool(x.get("inicio")) == bool(r.get("inicio")))]
        rs.insert(0, item)
    doc.update(_nota=_NOTA_DIC, palabras=pal, reglas=rs)
    _escribir_doc(p, doc)
    return {**item, "donde": "regla"}


def borrar_regla(rid: str, path: Path | None = None) -> bool:
    p = path or DICCIONARIO
    doc = _cargar(p)
    rs = [x for x in doc.get("reglas", []) if isinstance(x, dict)]
    nuevas = [x for x in rs if x.get("id") != rid]
    if len(nuevas) != len(rs):
        doc.update(_nota=_NOTA_DIC, reglas=nuevas)
        _escribir_doc(p, doc)
    return len(nuevas) != len(rs)


def vocabulario(path: Path | None = None) -> list[str]:
    return [w for w in _cargar(path).get("vocabulario", []) if isinstance(w, str) and w.strip()]


def vocab_agregar(palabra: str, path: Path | None = None) -> str:
    w = re.sub(r"\s+", " ", palabra or "").strip()
    if not _clave(w) or len(w) > 60:
        raise ValueError("Escriba la palabra (máximo 60 letras).")
    lista = vocabulario(path)
    if any(_clave(x) == _clave(w) for x in lista):
        raise ValueError(f"«{w}» ya está en el vocabulario de voz.")
    _escribir(path or DICCIONARIO, "vocabulario", lista + [w], _NOTA_DIC)
    return w


def vocab_borrar(palabra: str, path: Path | None = None) -> bool:
    lista = vocabulario(path)
    nueva = [x for x in lista if _clave(x) != _clave(palabra)]
    if len(nueva) != len(lista):
        _escribir(path or DICCIONARIO, "vocabulario", nueva, _NOTA_DIC)
    return len(nueva) != len(lista)


def frases(path: Path | None = None) -> list[dict]:
    return [x for x in _leer(path or FRASES, "frases") if str(x.get("frase", "")).strip() and x.get("accion")]


def _clave(s: str) -> str:
    """Para comparar: minúsculas, sin tildes, espacios simples."""
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", s)).strip()


_VOCALES = {"a": "aáàäâ", "e": "eéèëê", "i": "iíìïî", "o": "oóòöô", "u": "uúùüû", "n": "nñ"}


def _patron(escuchado: str) -> re.Pattern:
    """«ursus» -> palabra completa, sin importar tildes ni mayúsculas (no toca «recursos»)."""
    partes = []
    for ch in _clave(escuchado):
        partes.append(r"[\s-]+" if ch in " -" else f"[{_VOCALES[ch]}]" if ch in _VOCALES else re.escape(ch))
    return re.compile(r"(?<!\w)" + "".join(partes) + r"(?!\w)", re.I)


def aplicar_diccionario(text: str, path: Path | None = None) -> str:
    """Corrige las palabras del diccionario en la frase (las más largas primero). Se puede aplicar dos veces: no toca
    lo que ya está dentro de lo correcto («la U» -> «la U de Chile» no se vuelve «la U de Chile de Chile»)."""
    out = text or ""
    for x in sorted(palabras(path), key=lambda x: -len(x["escuchado"])):
        if not _clave(x["escuchado"]):
            continue
        pat = _patron(x["escuchado"])
        if x.get("contexto") == "app":   # solo nombrando la app: «abre ermes», «qué es eernes» o el nombre solo
            out = re.sub(rf"(?i)^(\s*¿?\s*{APP_CTX})" + pat.pattern, lambda m: m.group(1) + x["correcto"], out, count=1)
            out = re.sub(r"(?i)^(\s*¿?\s*)" + pat.pattern + r"(\s*[?.!]*\s*)$", lambda m: m.group(1) + x["correcto"] + m.group(2),
                         out, count=1)
            continue
        ya = [m.span() for m in _patron(x["correcto"]).finditer(out)] if _clave(x["correcto"]) else []
        out = pat.sub(lambda m, ya=ya, c=x["correcto"]: m.group(0) if any(a <= m.start() and m.end() <= b for a, b in ya)
                      else c, out)
    return out


def buscar_frase(text: str, path: Path | None = None) -> dict | None:
    """La frase guardada igual o casi igual a lo dicho (parecido >= 0.9), o None."""
    k = _clave(text).strip(" .,!?")
    if len(k) < 3:
        return None
    mejor_f, mejor_s = None, 0.0
    for x in frases(path):
        s = 1.0 if _clave(x["frase"]) == k else difflib.SequenceMatcher(None, _clave(x["frase"]), k).ratio()
        if s > mejor_s:
            mejor_f, mejor_s = x, s
    return mejor_f if mejor_s >= 0.9 else None


def guardar_palabra(escuchado: str, correcto: str, antes: str = "", path: Path | None = None) -> dict:
    """Agrega o actualiza «escuchado -> correcto». «antes»: la clave que se estaba editando (si cambió)."""
    escuchado, correcto = re.sub(r"\s+", " ", escuchado or "").strip(), re.sub(r"\s+", " ", correcto or "").strip()
    if not _clave(escuchado) or not correcto or len(escuchado) > 60 or len(correcto) > 80:
        raise ValueError("Falta lo que escuchó o lo que significaba (máximo 60 y 80 letras).")
    if _clave(escuchado) == _clave(correcto):
        raise ValueError("Lo que escuchó y lo que significaba son iguales.")
    lista = [x for x in palabras(path) if _clave(x["escuchado"]) != _clave(antes or escuchado)]
    previo = next((x for x in palabras(path) if _clave(x["escuchado"]) == _clave(escuchado)), None)
    lista = [x for x in lista if _clave(x["escuchado"]) != _clave(escuchado)]
    item = {"escuchado": escuchado, "correcto": correcto, "fecha": time.strftime("%Y-%m-%d"),
            "veces": int((previo or {}).get("veces", 0)) + 1}
    if (previo or {}).get("contexto") and _clave(antes or escuchado) == _clave(escuchado):
        item["contexto"] = previo["contexto"]
    item["origen"] = (previo or {}).get("origen") or "lápiz"
    if (previo or {}).get("nota"):
        item["nota"] = previo["nota"]
    lista.append(item)
    _escribir(path or DICCIONARIO, "palabras", lista, _NOTA_DIC)
    return item


def guardar_frase(frase: str, accion: str, antes: str = "", path: Path | None = None) -> dict:
    frase, accion = re.sub(r"\s+", " ", frase or "").strip(" .,!?¡¿"), re.sub(r"\s+", " ", accion or "").strip()
    if len(_clave(frase)) < 3 or not accion or len(frase) > 200 or len(accion) > 200:
        raise ValueError("Falta la frase o la acción.")
    previo = next((x for x in frases(path) if _clave(x["frase"]) == _clave(frase)), None)
    lista = [x for x in frases(path) if _clave(x["frase"]) not in (_clave(frase), _clave(antes or frase))]
    item = {"frase": frase, "accion": accion, "fecha": time.strftime("%Y-%m-%d"), "veces": int((previo or {}).get("veces", 0)) + 1}
    lista.append(item)
    _escribir(path or FRASES, "frases", lista,
              "Frase dicha -> orden que Atlas ejecuta (accion). Se edita con el lápiz de la consola.")
    return item


def borrar_palabra(escuchado: str, path: Path | None = None) -> bool:
    lista = palabras(path)
    nueva = [x for x in lista if _clave(x["escuchado"]) != _clave(escuchado)]
    if len(nueva) != len(lista):
        _escribir(path or DICCIONARIO, "palabras", nueva, _NOTA_DIC)
    return len(nueva) != len(lista)


def borrar_frase(frase: str, path: Path | None = None) -> bool:
    lista = frases(path)
    nueva = [x for x in lista if _clave(x["frase"]) != _clave(frase)]
    if len(nueva) != len(lista):
        _escribir(path or FRASES, "frases", nueva, "Frase dicha -> orden que Atlas ejecuta (accion). Se edita con el lápiz de la consola.")
    return len(nueva) != len(lista)


def acciones(nombres: dict[str, dict]) -> list[dict]:
    """Para el buscador del panel: [{"nombre", "accion", "tipo"}] (intenciones de Atlas y todo lo que sabe abrir)."""
    out = [{"nombre": n, "accion": a, "tipo": "atlas"} for n, a in INTENCIONES]
    for n, info in sorted(nombres.items(), key=lambda kv: kv[0].lower()):
        if n in SERVICIOS:
            out.append({"nombre": f"Abrir {n}", "accion": SERVICIOS[n]["abre"], "tipo": "servicio"})
            continue
        out.append({"nombre": n, "accion": f"abre {n}", "tipo": info["tipo"]})
    vistos, unicos = set(), []
    for a in out:
        if a["accion"].lower() not in vistos:
            vistos.add(a["accion"].lower())
            unicos.append(a)
    return unicos

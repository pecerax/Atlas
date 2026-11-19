"""Exportar e importar el diccionario entre amigos (pedido del usuario, 19-11-2026: «pon opción de exportar
diccionario, para que mis amigos me puedan ayudar con pulir las reglas»).

Exportar: arma la lista de las correcciones propias (palabras, reglas, frases y vocabulario de diccionario.json y
frases.json) y marca las que parecen personales: las que nombran a un contacto, un apodo o un ramo de la persona.
Esas salen DESMARCADAS; la persona revisa la lista, elige y se guarda un .json en Descargas para mandarlo.
Importar: lee ese .json, muestra cada entrada como nueva, «ya la tiene» o «distinta a la suya», y suma solo las que
la persona marque (origen «amigo»). Nunca cambia ni borra lo que ya había. Las reglas pasan por la misma validación
que las del lápiz (atlas_nombres._limpia_regla): un archivo raro no puede meter expresiones ni datos de más.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atlas_nombres as NM

FORMATO = "atlas-diccionario"
MAX_BYTES = 1_000_000
# lo que ya trae Atlas: se puede mandar, pero sale desmarcado (al amigo no le sirve de nada)
DE_ATLAS = ("base", "semilla", "equivalencias")


def _txt(s, n: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def palabras_personales() -> list[tuple[str, str]]:
    """(palabra, motivo): nombres y apodos de contactos y ramos de esta persona. Solo se usan para marcar."""
    out: list[tuple[str, str]] = []
    try:
        import atlas_voz_apodos as VA

        v = VA.vista()
    except Exception:  # noqa: BLE001
        v = {}
    for k, motivo in (("contactos", "nombra a un contacto suyo"), ("ramos", "nombra un ramo suyo")):
        for it in v.get(k, []) or []:
            # nombres y apodos completos; del nombre también cada palabra («Lucía Rojas» -> «Lucía», «Rojas»),
            # pero no las de los apodos («el de este curso» marcaba cualquier regla con «este»)
            nombre = str(it.get("nombre", "") or "")
            for w in [nombre, *(it.get("lista") or []), *nombre.split()]:
                c = NM._clave(str(w or ""))
                if len(c) > 2 and c not in _COMUNES:
                    out.append((c, motivo))
    return out


# palabras comunes que nunca cuentan como «nombre de alguien» (aunque aparezcan en un nombre o apodo)
_COMUNES = {"este", "esta", "ese", "esa", "eso", "del", "las", "los", "con", "por", "para", "que", "una", "uno", "mi",
            "tu", "su", "san", "santa", "de", "la", "el", "y", "profe", "profesor", "profesora", "curso", "ramo",
            "taller", "seccion", "catedra", "auxiliar", "lab", "laboratorio", "introduccion", "fundamentos"}


def _personal(item, personales: list[tuple[str, str]]) -> str:
    txt = " " + NM._clave(json.dumps(item, ensure_ascii=False)) + " "
    for w, motivo in personales:
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", txt):
            return motivo
    return ""


def _limpia(tipo: str, x) -> dict | str | None:
    """La entrada tal como viaja en el archivo (sin fechas, contadores ni ids). None si no sirve."""
    try:
        if tipo == "palabra":
            e, c = _txt(x.get("escuchado"), 60), _txt(x.get("correcto"), 80)
            if not NM._clave(e) or not c or NM._clave(e) == NM._clave(c):
                return None
            out = {"escuchado": e, "correcto": c}
            if x.get("contexto") == "app":
                out["contexto"] = "app"
            if x.get("nota"):
                out["nota"] = _txt(x["nota"], 200)
            return out
        if tipo == "regla":
            out = NM._limpia_regla(x)
            if x.get("nota"):
                out["nota"] = _txt(x["nota"], 200)
            return out
        if tipo == "frase":
            f, a = _txt(x.get("frase"), 200), _txt(x.get("accion"), 200)
            return {"frase": f, "accion": a} if len(NM._clave(f)) >= 3 and a else None
        w = _txt(x, 60)
        return w if NM._clave(w) else None
    except (ValueError, AttributeError, TypeError):
        return None


def _texto(tipo: str, x) -> str:
    if tipo == "palabra":
        return f"«{x['escuchado']}» se entiende «{x['correcto']}»" + (" (al nombrar una app)" if x.get("contexto") == "app" else "")
    if tipo == "regla":
        return NM.texto_regla(x)
    if tipo == "frase":
        return f"Cuando diga «{x['frase']}», hacer «{x['accion']}»"
    return f"Vocabulario de voz: «{x}»"


def _entradas(doc: dict) -> list[tuple[str, object, str]]:
    """(tipo, entrada limpia, origen) de un diccionario con «palabras», «reglas», «vocabulario» y «frases»."""
    out = []
    for tipo, clave in (("palabra", "palabras"), ("regla", "reglas"), ("frase", "frases"), ("vocab", "vocabulario")):
        for x in (doc.get(clave) or [])[:2000]:
            limpia = _limpia(tipo, x)
            if limpia is not None:
                out.append((tipo, limpia, x.get("origen", "") if isinstance(x, dict) else ""))
    return out


def _mio() -> dict:
    d = NM._cargar()
    return {"palabras": d.get("palabras", []), "reglas": d.get("reglas", []),
            "vocabulario": d.get("vocabulario", []), "frases": NM.frases()}


def exportar_vista() -> dict:
    """Todo lo propio, con «marcada» (va o no por defecto) y «motivo» cuando sale desmarcada."""
    pers, items, vistas = palabras_personales(), [], set()
    for tipo, x, origen in _entradas(_mio()):
        k = NM.clave_base(tipo, x)
        if k in vistas:
            continue
        vistas.add(k)
        motivo = _personal(x, pers) or ("ya viene con Atlas" if origen in DE_ATLAS else
                                        "suele ser un nombre propio: márquela si sirve a cualquiera" if tipo == "vocab" else "")
        items.append({"clave": k, "tipo": tipo, "texto": _texto(tipo, x), "marcada": not motivo, "motivo": motivo})
    return {"ok": True, "items": items}


def exportar(claves: list[str], carpeta: Path | None = None) -> dict:
    """Guarda en Descargas (o «carpeta») un .json con las entradas elegidas. Devuelve la ruta."""
    elegidas = set(claves or [])
    doc = {"formato": FORMATO, "version": 1, "fecha": time.strftime("%Y-%m-%d %H:%M"),
           "palabras": [], "reglas": [], "frases": [], "vocabulario": []}
    destino = {"palabra": "palabras", "regla": "reglas", "frase": "frases", "vocab": "vocabulario"}
    for tipo, x, _o in _entradas(_mio()):
        k = NM.clave_base(tipo, x)
        if k in elegidas:
            elegidas.discard(k)
            doc[destino[tipo]].append(x)
    n = sum(len(doc[c]) for c in destino.values())
    if not n:
        return {"ok": False, "error": "Marque al menos una corrección para exportar."}
    base = carpeta or Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads"
    base.mkdir(parents=True, exist_ok=True)
    f = base / f"Atlas-diccionario-{time.strftime('%Y-%m-%d')}.json"
    i = 2
    while f.exists():
        f = base / f"Atlas-diccionario-{time.strftime('%Y-%m-%d')}-{i}.json"
        i += 1
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"ok": True, "ruta": str(f), "cuantas": n}


def _leer_archivo(contenido: str) -> dict:
    if not isinstance(contenido, str) or not contenido.strip():
        raise ValueError("El archivo está vacío.")
    if len(contenido.encode("utf-8")) > MAX_BYTES:
        raise ValueError("El archivo es demasiado grande para ser un diccionario de Atlas.")
    try:
        d = json.loads(contenido)
    except ValueError:
        raise ValueError("Ese archivo no es un diccionario de Atlas (no es JSON).") from None
    if not isinstance(d, dict) or not any(isinstance(d.get(k), list) for k in ("palabras", "reglas", "frases", "vocabulario")):
        raise ValueError("Ese archivo no es un diccionario de Atlas.")
    return d


def importar_vista(contenido: str) -> dict:
    """Cada entrada del archivo: nueva (marcada), ya la tiene, o distinta a la suya (desmarcada, para que decida)."""
    try:
        d = _leer_archivo(contenido)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    mio = _mio()
    tengo = {NM.clave_base(t, x): x for t, x, _o in _entradas(mio)}
    # misma palabra escuchada, otra corrección: «distinta a la suya»
    tengo_pal = {NM._clave(x["escuchado"]): x["correcto"] for t, x, _o in _entradas(mio) if t == "palabra"}
    tengo_fr = {NM._clave(x["frase"]): x["accion"] for t, x, _o in _entradas(mio) if t == "frase"}
    pers, items, vistas = palabras_personales(), [], set()
    for tipo, x, _o in _entradas(d):
        k = NM.clave_base(tipo, x)
        if k in vistas:
            continue
        vistas.add(k)
        estado, motivo = "nueva", ""
        if k in tengo and (tipo != "palabra" or NM._clave(tengo_pal.get(NM._clave(x["escuchado"]), "")) == NM._clave(x["correcto"])) \
                and (tipo != "frase" or tengo_fr.get(NM._clave(x["frase"])) == x["accion"]):
            estado = "ya la tiene"
        elif tipo == "palabra" and NM._clave(x["escuchado"]) in tengo_pal:
            estado, motivo = "distinta", f"usted la tiene como «{tengo_pal[NM._clave(x['escuchado'])]}»"
        elif tipo == "frase" and NM._clave(x["frase"]) in tengo_fr:
            estado, motivo = "distinta", "usted ya tiene esa frase con otra acción"
        motivo = motivo or _personal(x, pers)
        items.append({"clave": k, "tipo": tipo, "texto": _texto(tipo, x), "estado": estado,
                      "marcada": estado == "nueva" and not motivo, "motivo": motivo})
    return {"ok": True, "items": items, "fecha": _txt(d.get("fecha"), 20)}


def importar(contenido: str, claves: list[str], dic: Path | None = None, frases_path: Path | None = None) -> dict:
    """Suma las entradas elegidas (origen «amigo»). Si una palabra o frase elegida ya existe con otro valor, la del
    archivo la reemplaza (la persona la marcó a propósito); nada más se toca."""
    try:
        d = _leer_archivo(contenido)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    elegidas, hoy = set(claves or []), time.strftime("%Y-%m-%d")
    p = dic or NM.DICCIONARIO
    fp = frases_path or (NM.FRASES if p == NM.DICCIONARIO else p.with_name("frases.json"))
    doc = NM._cargar(p)
    pal = [x for x in doc.get("palabras", []) if isinstance(x, dict)]
    rs = [x for x in doc.get("reglas", []) if isinstance(x, dict)]
    voc = [w for w in doc.get("vocabulario", []) if isinstance(w, str)]
    fr = NM.frases(fp)
    n = {"palabras": 0, "reglas": 0, "frases": 0, "vocabulario": 0}
    for tipo, x, _o in _entradas(d):
        k = NM.clave_base(tipo, x)
        if k not in elegidas:
            continue
        elegidas.discard(k)
        if tipo == "palabra":
            pal = [y for y in pal if NM._clave(y.get("escuchado", "")) != NM._clave(x["escuchado"])]
            pal.append({**x, "fecha": hoy, "veces": 0, "origen": "amigo"})
            n["palabras"] += 1
        elif tipo == "regla" and not any(NM.clave_base("regla", y) == k for y in rs):
            rs.append({"id": NM._nuevo_id(), **x, "origen": "amigo", "fecha": hoy})
            n["reglas"] += 1
        elif tipo == "frase":
            fr = [y for y in fr if NM._clave(y.get("frase", "")) != NM._clave(x["frase"])]
            fr.append({**x, "fecha": hoy, "veces": 0, "origen": "amigo"})
            n["frases"] += 1
        elif tipo == "vocab" and not any(NM._clave(w) == NM._clave(x) for w in voc):
            voc.append(x)
            n["vocabulario"] += 1
    if not sum(n.values()):
        return {"ok": False, "error": "No había nada nuevo marcado para sumar."}
    doc.update(palabras=pal, reglas=rs, vocabulario=voc)
    NM._escribir_doc(p, doc)
    if n["frases"]:
        NM._escribir(fp, "frases", fr, NM._NOTA_FRASES)
    return {"ok": True, "sumadas": n}

"""Sección «Voz y apodos» de la rueda de ajustes (maqueta 1 elegida por el usuario, 17-11-2026: «en configuración todas
las reglas de voz y apodos que tenemos, por ejemplo que Chego es Shego»).

No hay datos nuevos: muestra y edita los archivos que ya existían, para que cada persona tenga los suyos.
- Correcciones de voz «cuando escucha → entiende»: desde el 18-11-2026 viven en ~/.atlas/diccionario.json (el mismo
  diccionario del lápiz ✎; antes en equivalencias.json). Las palabras se agrupan por lo que entiende y se editan como
  chips; las «reglas» (expresiones) quedan solo para ver («avanzada»).
- contactos.json (apodos), ramos.json (apodo + también), accesos.json (dice), repertorio.json (alias de artistas).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import atlas_nombres as NM

HERE = Path(__file__).resolve().parent
DICC: Path | None = None   # None = el diccionario de Atlas (atlas_nombres.DICCIONARIO); las pruebas usan otro
FILES = {"contactos": HERE / "contactos.json", "ramos": HERE / "ramos.json", "accesos": HERE / "accesos.json",
         "musica": HERE / "repertorio.json"}
_WORD = NM._WORD
escucha_de = NM.escucha_de


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data: dict) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _grupos() -> dict[str, dict]:
    """Palabras del diccionario agrupadas por lo que entiende (y su contexto): id «p:<entiende>|<contexto>»."""
    g: dict[str, dict] = {}
    for x in NM.palabras(DICC):
        k = f"p:{x['correcto']}|{x.get('contexto') or ''}"
        it = g.setdefault(k, {"i": k, "escucha": [], "avanzada": False, "patron": "", "entiende": x["correcto"],
                              "nota": x.get("nota") or ("solo al nombrar la app" if x.get("contexto") == "app" else ""),
                              "contexto": x.get("contexto") or ""})
        it["escucha"].append(x["escuchado"])
    return g


def vista() -> dict:
    out: dict = {"correcciones": [], "contactos": [], "ramos": [], "accesos": [], "musica": []}
    try:
        out["correcciones"] = list(_grupos().values())
        for r in NM.reglas(DICC):   # reglas con condiciones: se leen aquí y se editan en el Diccionario
            out["correcciones"].append({"i": f"r:{r.get('id', '')}", "escucha": [r.get("escuchado", "")] if r.get("escuchado") else [],
                                        "avanzada": True, "patron": NM.texto_regla(r),
                                        "entiende": r.get("correcto", "") if r.get("tipo") == "cambiar" else r.get("a", ""),
                                        "nota": r.get("nota", "")})
    except Exception:  # noqa: BLE001
        pass
    try:
        for c in _read(FILES["contactos"]).get("contactos", []):
            out["contactos"].append({"clave": c.get("id", ""), "nombre": c.get("nombre", ""), "lista": c.get("apodos") or []})
    except Exception:  # noqa: BLE001
        pass
    try:
        for r in _read(FILES["ramos"]).get("ramos", []):
            out["ramos"].append({"clave": r.get("ramo", ""), "nombre": r.get("ramo", ""),
                                 "lista": [r.get("apodo", "")] + list(r.get("tambien") or [])})
    except Exception:  # noqa: BLE001
        pass
    try:
        for a in _read(FILES["accesos"]).get("accesos", []):
            out["accesos"].append({"clave": a.get("nombre", ""), "nombre": a.get("nombre", ""), "lista": a.get("dice") or []})
    except Exception:  # noqa: BLE001
        pass
    try:
        for a in _read(FILES["musica"]).get("artistas", []):
            out["musica"].append({"clave": a.get("nombre", ""), "nombre": a.get("nombre", ""), "lista": a.get("alias") or []})
    except Exception:  # noqa: BLE001
        pass
    return out


def _limpia(lista) -> list[str]:
    vistos, out = set(), []
    for w in lista or []:
        w = re.sub(r"\s+", " ", str(w)).strip()
        if w and w.lower() not in vistos and len(w) <= 60:
            vistos.add(w.lower())
            out.append(w)
    return out


def guardar_correccion(i, escucha, entiende: str, nota: str = "") -> dict:
    """i = None crea una corrección; «p:…» reemplaza ese grupo de palabras; «r:…» (regla avanzada) no se edita aquí.
    Valida antes de escribir. Todo queda en el diccionario (el mismo del lápiz ✎)."""
    escucha = [w.lower() for w in _limpia(escucha)]
    entiende = re.sub(r"\s+", " ", str(entiende or "")).strip()
    if not escucha or not entiende:
        return {"ok": False, "error": "Falta qué escucha o qué entiende."}
    malas = [w for w in escucha if not _WORD.match(w)]
    if malas:
        return {"ok": False, "error": f"Solo letras y espacios: «{malas[0]}»."}
    if any(len(w) < 3 for w in escucha):
        return {"ok": False, "error": "Cada palabra debe tener al menos 3 letras (si no, cambia frases normales)."}
    if entiende.lower() in escucha:
        return {"ok": False, "error": "Lo que entiende no puede estar también en lo que escucha."}
    grupos = _grupos()
    previo = None
    if i is not None and i != "":
        if str(i).startswith("r:"):
            return {"ok": False, "error": "Esa corrección tiene condiciones: se edita en el Diccionario."}
        previo = grupos.get(str(i))
        if previo is None:
            return {"ok": False, "error": "No encontré esa corrección; recargue la lista."}
    otros = {NM._clave(w): g["entiende"] for k, g in grupos.items() if not previo or k != previo["i"] for w in g["escucha"]}
    choque = [w for w in escucha if NM._clave(w) in otros]
    if choque:
        return {"ok": False, "error": f"«{choque[0]}» ya se corrige como «{otros[NM._clave(choque[0])]}»."}
    del_grupo = (lambda x: previo is not None and x["correcto"] == previo["entiende"]
                 and (x.get("contexto") or "") == previo["contexto"])
    viejas = {NM._clave(x["escuchado"]): x for x in NM.palabras(DICC) if del_grupo(x)}
    lista = [x for x in NM.palabras(DICC) if not del_grupo(x)]
    nota = (nota or "").strip()[:200]
    for w in escucha:
        v = viejas.get(NM._clave(w), {})
        it = {"escuchado": w, "correcto": entiende, "fecha": v.get("fecha") or time.strftime("%Y-%m-%d"),
              "veces": int(v.get("veces", 0)), "origen": v.get("origen") or "ajustes"}
        if nota:
            it["nota"] = nota
        if previo and previo["contexto"]:
            it["contexto"] = previo["contexto"]
        lista.append(it)
    NM._escribir(DICC or NM.DICCIONARIO, "palabras", lista, NM._NOTA_DIC)
    return {"ok": True}


def borrar_correccion(i) -> dict:
    if str(i).startswith("r:"):
        return {"ok": False, "error": "Esa corrección tiene condiciones: se edita o se borra en el Diccionario."}
    g = _grupos().get(str(i))
    if g is None:
        return {"ok": False, "error": "No encontré esa corrección; recargue la lista."}
    lista = [x for x in NM.palabras(DICC) if not (x["correcto"] == g["entiende"] and (x.get("contexto") or "") == g["contexto"])]
    NM._escribir(DICC or NM.DICCIONARIO, "palabras", lista, NM._NOTA_DIC)
    return {"ok": True}


def guardar_lista(tipo: str, clave: str, lista) -> dict:
    """Apodos de un contacto, ramo, acceso o artista. En ramos, el primero es el apodo principal."""
    if tipo not in FILES:
        return {"ok": False, "error": "Tipo desconocido."}
    lista = _limpia(lista)
    data = _read(FILES[tipo])
    if tipo == "contactos":
        items, k, campo = data.get("contactos", []), "id", "apodos"
    elif tipo == "ramos":
        items, k, campo = data.get("ramos", []), "ramo", None
    elif tipo == "accesos":
        items, k, campo = data.get("accesos", []), "nombre", "dice"
    else:
        items, k, campo = data.get("artistas", []), "nombre", "alias"
    it = next((x for x in items if x.get(k) == clave), None)
    if it is None:
        return {"ok": False, "error": "No lo encontré."}
    if tipo == "ramos":
        if not lista:
            return {"ok": False, "error": "El ramo necesita al menos un apodo."}
        it["apodo"], it["tambien"] = lista[0], lista[1:]
        if not it["tambien"]:
            it.pop("tambien")
    elif tipo == "accesos" and not lista:
        return {"ok": False, "error": "El acceso necesita al menos una forma de decirlo."}
    else:
        it[campo] = lista
    _write(FILES[tipo], data)
    return {"ok": True}


def reglas_que_aplican(texto: str) -> list[str]:
    """Para el probador: qué correcciones del diccionario cambian esta frase (su «entiende», o la nota si borra algo)."""
    out = []
    try:
        for r in NM.aplicar_reglas_detalle(texto or "", DICC)[1]:
            out.append(r.get("correcto") or r.get("a") or NM.texto_regla(r)[:60])
        for x in NM.palabras(DICC):
            if NM._clave(x["escuchado"]) and NM._patron(x["escuchado"]).search(texto or "")                     and (x.get("contexto") != "app" or NM.aplicar_diccionario(texto, DICC) != texto):
                out.append(x["correcto"])
    except Exception:  # noqa: BLE001
        pass
    return out

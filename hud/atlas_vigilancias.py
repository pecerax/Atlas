"""Vigilancias: Atlas espera algo puntual y avisa una vez cuando llega (pedido del usuario, 16-11-2026).

Tipos:
- "correo": un correo esperado («avísame cuando me llegue el correo de Google Takeout», «estoy esperando un correo
  de Falabella»). Se revisan TODAS las cuentas y todo el correo (también Promociones, Notificaciones y lo que Atlas
  normalmente calla), solo lo que llegó desde que se creó la vigilancia.
- "publicacion": algo nuevo de un ramo en U-Cursos («avísame cuando haya una publicación nueva en Lenguajes»).
  U-Cursos lo manda por correo (noreply-ucursos@ucampus.cl) y el ramo aparece en el texto del mensaje.
- "nota": una nota puntual en U-Cursos («avísame cuando publiquen la nota del control 2 de Redes»). Usa lo que la
  revisión de notas (atlas_ucursos_notas.py) ya guarda; no abre U-Cursos por su cuenta.

Al cumplirse: aviso de voz + recuadro amarillo (suena hasta presionarlo) + Telegram, y la vigilancia se borra.
«¿Qué estás vigilando?» las lista; «ya no esperes el correo de X» / «cancela la vigilancia de X» las quita.
Crear o quitar una no pide confirmación (como los recordatorios: es local y se deshace con la voz).

Este módulo entiende las frases, guarda hud/vigilancias.json y revisa; quien avisa es hud_server.py.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
_LOCK = threading.Lock()
MAIL_EVERY = 60  # ya no se usa: los correos esperados se buscan al ritmo de frecuencias.bandeja_seg (18-11-2026)


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def _file() -> Path:
    return HERE / "vigilancias.json"


def load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("activas", [])
            d.setdefault("cumplidas", [])
            return d
    except (OSError, ValueError):
        pass
    return {"activas": [], "cumplidas": []}


def save(d: dict) -> None:
    d["cumplidas"] = d.get("cumplidas", [])[:30]
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_file())


def activas(tipo: str | None = None) -> list[dict]:
    return [w for w in load()["activas"] if tipo is None or w.get("tipo") == tipo]


def add(w: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    w = {"id": f"v{int(time.time() * 1000) % 10**10}", "creado": now.isoformat(timespec="seconds"),
         "desde": w.get("desde") or now.isoformat(timespec="seconds"), **w}
    with _LOCK:
        d = load()
        d["activas"].append(w)
        save(d)
    return w


def remove(ids: list[str], cumplida: dict | None = None) -> None:
    with _LOCK:
        d = load()
        d["activas"] = [w for w in d["activas"] if w["id"] not in ids]
        if cumplida:
            d["cumplidas"].insert(0, cumplida)
        save(d)


def set_campo(wid: str, campo: str, valor) -> None:
    """Guarda un dato de una vigilancia activa (p. ej. cuántos mensajes sin leer había al empezar a esperar)."""
    with _LOCK:
        d = load()
        for w in d["activas"]:
            if w["id"] == wid:
                w[campo] = valor
        save(d)


# ----------------------------------------------------------------------------- correos conocidos
# Nombres que el usuario dice -> qué buscar. «de» = alguna palabra en el remitente; «alguno» = alguna frase (todas
# sus palabras) en remitente + asunto.
CONOCIDOS = {
    "google takeout": {"nombre": "Google Takeout", "de": ["google"],
                       # el aviso de que está listo; NO el de «Se ha solicitado la creación de un archivo…» (uso real)
                       "alguno": ["puedes descargar", "listos para descargar", "listo para descargar", "datos listos",
                                  "datos estan listos", "archivo esta listo", "exportacion esta lista",
                                  "ready to download", "data is ready", "export is ready", "archive is ready"],
                       "excluir": ["solicitado", "solicitud", "requested"]},
    "takeout": "google takeout",
    "u-cursos": {"nombre": "U-Cursos", "de": ["ucursos", "u-cursos", "ucampus"], "alguno": []},
    "ucursos": "u-cursos",
    "u cursos": "u-cursos",
}

_STOP = {"de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "mi", "mis", "su", "sus", "que", "con",
         "por", "para", "y", "o", "a", "al", "en", "me", "le", "lo", "nuevo", "nueva", "atlas", "jarvis", "favor", "porfa",
         "correo", "correos", "mail", "mails", "email", "e-mail", "mensaje", "llegue", "llega"}


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9@._-]+", _plain(s)) if w not in _STOP and len(w) > 1]


def _phrase_in(phrase: str, text: str) -> bool:
    ws = [w for w in re.findall(r"[a-z0-9@._-]+", _plain(phrase)) if w not in _STOP or len(phrase.split()) == 1]
    return bool(ws) and all(w in text for w in ws)


def match_mail(w: dict, sender: str, subject: str, body: str = "") -> bool:
    """¿Este correo es el que espera la vigilancia `w`?"""
    fr, both = _plain(sender), _plain(sender + " " + subject)
    if w.get("de") and not any(d in fr for d in w["de"]):
        return False
    if w.get("todas") and not all(t in both for t in w["todas"]):
        return False
    if w.get("alguno"):
        where = both + " " + _plain(body) if w.get("cuerpo") else both
        if not any(_phrase_in(p, where) for p in w["alguno"]):
            return False
    if w.get("asunto") and not _phrase_in(w["asunto"], _plain(subject)):
        return False
    if any(x in _plain(subject) for x in w.get("excluir", [])):
        return False
    return bool(w.get("de") or w.get("todas") or w.get("alguno") or w.get("asunto"))


def correo_watch(quien: str, sobre: str = "") -> dict:
    """«de Google Takeout» / «de Falabella» (+ «sobre la boleta») -> campos de la vigilancia."""
    q = _plain(quien).strip(" .,;:!?¿¡")
    q = re.sub(r"^(?:el|la|los|las|un|una|parte de|de)\s+", "", q)
    known = CONOCIDOS.get(q)
    if isinstance(known, str):
        known = CONOCIDOS[known]
    if known is None:
        known = next((CONOCIDOS[k] if isinstance(CONOCIDOS[k], dict) else CONOCIDOS[CONOCIDOS[k]]
                      for k in CONOCIDOS if re.search(rf"\b{re.escape(k)}\b", q)), None)
    if known:
        w = {"tipo": "correo", "nombre": known["nombre"], "de": list(known["de"]), "alguno": list(known["alguno"])}
        if known.get("excluir"):
            w["excluir"] = list(known["excluir"])
    else:
        ws = _words(q)
        w = {"tipo": "correo", "nombre": quien.strip(" .,;:!?¿¡").strip(), "todas": ws}
    if sobre.strip():
        w["asunto"] = sobre.strip(" .,;:!?¿¡")
        w["nombre"] += f" sobre «{w['asunto']}»"
    return w


# ----------------------------------------------------------------------------- nombres ambiguos
def buscar_remitentes(words: list[str], accounts=None, limit: int = 80) -> list[dict]:
    """Quién le ha escrito antes con esas palabras en el nombre o la dirección (todas las cuentas).
    -> [{"nombre", "correo", "cuenta", "n"}], el que más le escribe primero."""
    import email
    from email.utils import parseaddr

    from openjarvis.tools.gmail_mark_read import _find_all_mail, mail_accounts

    words = [w for w in words if len(w) > 1]
    if not words:
        return []
    accounts = accounts if accounts is not None else mail_accounts()
    found: dict[str, dict] = {}
    recientes: dict[str, dict] = {}  # remitentes de los últimos meses, para nombres mal oídos
    for lab, conn in accounts:
        imap = None
        try:
            ea, pw, host, port, sec, _ = conn._resolve_connection()
            imap = conn._open_authenticated_imap(ea, pw, host, port, sec)
            box = _find_all_mail(imap)
            if imap.select(f'"{box}"' if " " in box and not box.startswith('"') else box, readonly=True)[0] != "OK":
                continue
            if "gmail" in host.lower() or "google" in host.lower():
                st, d = imap.uid("SEARCH", "X-GM-RAW", '"' + " ".join(f"from:{w}" for w in words) + '"')
            else:
                crit = []
                for w in words:
                    crit += ["FROM", f'"{w}"']
                st, d = imap.uid("SEARCH", None, *crit)
            uids = d[0].split() if st == "OK" and d and d[0] else []
            if not uids:  # nadie con ese nombre exacto: junta quiénes le escribieron en los últimos 4 meses
                st, d = imap.uid("SEARCH", None, "SINCE", (datetime.now() - timedelta(days=120)).strftime("%d-%b-%Y"))
                rec = d[0].split() if st == "OK" and d and d[0] else []
                if rec:
                    st, md = imap.uid("FETCH", b",".join(rec[-400:]), "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                    for part in (md if st == "OK" and md else []):
                        if isinstance(part, tuple):
                            name, addr = parseaddr(_hdr(email.message_from_bytes(part[1]).get("From")))
                            if addr:
                                c = recientes.setdefault(addr.lower(), {"nombre": name.strip(' "') or addr.lower(),
                                                                         "correo": addr.lower(), "cuenta": lab, "n": 0})
                                c["n"] += 1
                continue
            st, md = imap.uid("FETCH", b",".join(uids[-limit:]), "(BODY.PEEK[HEADER.FIELDS (FROM)])")  # todo de una vez
            for part in (md if st == "OK" and md else []):
                if not isinstance(part, tuple):
                    continue
                name, addr = parseaddr(_hdr(email.message_from_bytes(part[1]).get("From")))
                addr = addr.lower()
                if not addr or not all(w in _plain(name + " " + addr) for w in words):
                    continue
                c = found.setdefault(addr, {"nombre": name.strip(' "') or addr, "correo": addr, "cuenta": lab, "n": 0})
                c["n"] += 1
        except Exception:  # noqa: BLE001
            continue
        finally:
            try:
                conn._close_imap(imap)
            except Exception:  # noqa: BLE001
                pass
    if found:
        return sorted(found.values(), key=lambda c: -c["n"])
    return parecidos(words, list(recientes.values()))


def _similar(q: str, name: str) -> float:
    """Qué tan parecido suena lo dicho a un remitente: «tanus hack» ~ «Platanus Hack» (la voz se come sílabas)."""
    from difflib import SequenceMatcher

    qc = re.sub(r"[^a-z0-9]", "", _plain(q))
    nc = re.sub(r"[^a-z0-9]", "", _plain(name))
    if len(qc) < 4 or not nc:
        return 0.0
    best = SequenceMatcher(None, qc, nc).ratio()
    if qc in nc:  # lo dicho está dentro del nombre (le faltó el comienzo o el final)
        best = max(best, 0.6 + 0.4 * len(qc) / len(nc))
    for L in {len(qc) - 1, len(qc), len(qc) + 2, len(qc) + 3}:  # el pedazo del nombre más parecido a lo dicho
        for i in range(0, max(1, len(nc) - L + 1)):
            r = SequenceMatcher(None, qc, nc[i:i + L]).ratio()
            if r > best:
                best = r * min(1.0, 0.75 + 0.25 * L / max(len(nc), 1))
    return best


def parecidos(words: list[str], recientes: list[dict], umbral: float = 0.78) -> list[dict]:
    """Remitentes recientes cuyo nombre (o dominio) suena como lo dicho, del más parecido al menos. Marcados
    «parecido»: Atlas siempre pregunta antes de usarlos."""
    q = " ".join(words)
    grupos: dict[str, dict] = {}
    for c in recientes:
        dom = c["correo"].split("@")[-1].split(".")[0]
        s = max(_similar(q, c["nombre"]), _similar(q, dom) * 0.95)
        if s < umbral:
            continue
        key = _plain(c["nombre"])  # el mismo remitente con varias direcciones va junto
        g = grupos.get(key)
        if g is None or s > g["s"] or (s == g["s"] and c["n"] > g["n"]):
            grupos[key] = {**c, "s": s, "parecido": True}
    return sorted(grupos.values(), key=lambda c: (-round(c["s"], 2), -c["n"]))[:4]


def resolver(quien: str, sobre: str = "", cands: list[dict] | None = None) -> dict:
    """Decide a quién se refiere. -> {"watch": vigilancia} o {"ask": texto, "cands": [...]} (si hay varios)."""
    w = correo_watch(quien, sobre)
    if w.get("de") or not w.get("todas"):  # correo conocido (Google Takeout, U-Cursos)
        return {"watch": w}
    cands = buscar_remitentes(w["todas"]) if cands is None else cands
    if not cands:
        return {"watch": w, "nuevo": True}
    if any(c.get("parecido") for c in cands):  # nombre mal oído: siempre preguntar
        cands = cands[:4]
        if len(cands) == 1:
            c = cands[0]
            ask = (f"No le ha escrito nadie llamado «{quien.strip()}», señor, pero sí {_quien_dice(c, cands)}. "
                   f"¿Se refiere a ese?")
        else:
            ask = (f"No le ha escrito nadie llamado «{quien.strip()}», señor. Lo más parecido: "
                   + pregunta(quien, cands).split(": ", 1)[1])
        return {"ask": ask, "cands": cands, "base": w}
    domains = {c["correo"].split("@")[-1] for c in cands}
    if len(cands) == 1:
        return {"watch": elegir(w, cands[:1])}
    if len(domains) == 1 and any(x in next(iter(domains)) for x in w["todas"]):  # una empresa con varios buzones
        dom = next(iter(domains))
        return {"watch": {**w, "de": ["@" + dom], "todas": []}}
    cands = cands[:4]
    return {"ask": pregunta(quien, cands), "cands": cands, "base": w}


def _quien_dice(c: dict, cands: list[dict]) -> str:
    """«Pablo Fuentes, de uchile.cl»; con el correo completo si el nombre se repite."""
    dup = sum(1 for x in cands if _plain(x["nombre"]) == _plain(c["nombre"])) > 1
    return f"{c['nombre']} ({c['correo']})" if dup or c["nombre"] == c["correo"] else \
        f"{c['nombre']}, de {c['correo'].split('@')[-1]}"


def pregunta(quien: str, cands: list[dict]) -> str:
    ords = ["uno", "dos", "tres", "cuatro"]
    lista = "; ".join(f"{ords[i]}, {_quien_dice(c, cands)}" for i, c in enumerate(cands))
    return (f"Le han escrito {len(cands)} personas que calzan con «{quien.strip()}», señor: {lista}. "
            f"¿Cuál espera? También puede decir «cualquiera».")


_GENERICOS = {"universidad", "chile", "uchile", "gmail", "correo", "banco", "noreply", "no-reply", "escuela", "ingenieria",
               "ciencias", "equipo", "soporte", "hola", "info", "contacto", "notificaciones", "google", "cuenta"}


def elegir(base: dict, cands: list[dict]) -> dict:
    """Vigilancia para uno o varios remitentes concretos."""
    w = {k: v for k, v in base.items() if k not in ("todas",)}
    w["de"] = [c["correo"] for c in cands]
    # el mismo nombre desde otra dirección también cuenta («Platanus Hack» <hola@…> o <equipo@…>)
    w["de"] += [_plain(c["nombre"]) for c in cands if c["nombre"] != c["correo"] and len(c["nombre"]) > 5]
    # y lo que dijo el usuario, si está en el nombre elegido: «Hélice» también calza con otra dirección y otro nombre
    # de la misma organización. Uso real 17-11-2026: esperaba a «HÉLICE - Escuela de Ingeniería y Ciencias»
    # <helice@ing.uchile.cl> y llegó de «HÉLICE Área de Ingeniería e Innovación FCFM» <helice.fcfm@uchile.cl>.
    dicho = " ".join(base.get("todas") or [])
    # Solo si la palabra también está en la dirección (es la organización, como helice@…): con personas («Pablo» de
    # varios Pablo) no se amplía, porque ahí se eligió justamente a uno.
    if len(dicho) >= 4 and " " not in dicho and dicho not in _GENERICOS and dicho not in w["de"] and any(
            dicho in _plain(c["nombre"]) and dicho in _plain(c["correo"]) for c in cands):
        w["de"].append(dicho)
    if len(cands) == 1:
        nombre = cands[0]["nombre"] if cands[0]["nombre"] != cands[0]["correo"] else cands[0]["correo"]
        w["nombre"] = nombre + (f" sobre «{base['asunto']}»" if base.get("asunto") else "")
    return w


_ORD = {"1": 0, "uno": 0, "primero": 0, "primer": 0, "primera": 0, "2": 1, "dos": 1, "segundo": 1, "segunda": 1,
        "3": 2, "tres": 2, "tercero": 2, "tercera": 2, "4": 3, "cuatro": 3, "cuarto": 3, "cuarta": 3,
        "ultimo": -1, "ultima": -1}


def respuesta(text: str, cands: list[dict]) -> list[dict] | None:
    """Respuesta a «¿cuál espera?»: «el segundo», «Pablo Fuentes», «el de uchile», «cualquiera». None si no se entiende."""
    p = _plain(text)
    if len(cands) == 1 and re.match(r"\W*(?:si|sip|claro|exacto|correcto|ese|esa|eso|ese mismo|ese es|afirmativo|dale|"
                                    r"por supuesto|obvio)\b", p) and not re.search(r"\bno\b", p):
        return list(cands)
    if re.search(r"\b(?:cualquiera|cualquier|todos|todas|ambos|los dos|las dos|da igual|me da lo mismo)\b", p):
        return list(cands)
    for k, i in _ORD.items():
        if re.search(rf"\b(?:el|la|numero|opcion)?\s*{k}\b", p) and (i < len(cands)):
            return [cands[i]]
    ws = [w for w in re.findall(r"[a-z0-9]+", p) if len(w) > 2 and w not in _STOP | {"ese", "esa", "del", "que"}]
    if not ws:
        return None
    score = [sum(1 for w in ws if w in _plain(c["nombre"] + " " + c["correo"])) for c in cands]
    best = max(score)
    hits = [c for c, s in zip(cands, score) if s == best and s]
    return hits if len(hits) == 1 else None


# ----------------------------------------------------------------------------- U-Cursos
def _ramos_apodos() -> list[tuple[str, str]]:
    try:
        rs = json.loads((HERE / "ramos.json").read_text(encoding="utf-8")).get("ramos", [])
    except (OSError, ValueError):
        return []
    out = []
    for r in rs:
        for a in [r.get("apodo", "")] + list(r.get("tambien", [])):
            if a:
                out.append((_plain(a), r.get("ramo", "")))
    return sorted(out, key=lambda x: -len(x[0]))


def find_course(text: str, U=None, course_list: list[dict] | None = None) -> dict | None:
    """Ramo dicho (apodo de ramos.json, código o palabras del nombre)."""
    if U is None:
        import atlas_ucursos_notas as U  # noqa: N813
    q = _plain(text)
    cl = course_list if course_list is not None else U.courses()
    for apodo, ramo in _ramos_apodos():
        if re.search(rf"\b{re.escape(apodo)}\b", q):
            c = next((c for c in cl if _plain(c["nombre"]) == _plain(ramo)), None)
            if c:
                return c
    c = next((c for c in cl if _plain(c["code"]) in q.replace(" ", "")), None)
    if c:
        return c
    best, score = None, 0
    for c in cl:  # el ramo con más palabras de su nombre dichas (no el primero que calce una)
        ws = [w for w in re.findall(r"[a-z]+", _plain(c["nombre"])) if len(w) > 3]
        s = sum(1 for w in ws if re.search(rf"\b{w}\b", q))
        if s > score or (s == score and s and best and len(ws) < len(re.findall(r"[a-z]{4,}", _plain(best["nombre"])))):
            best, score = c, s
    return best if score else None


_EVAL = re.compile(r"\b(control|tarea|examen|prueba|certamen|proyecto|informe|entrega|ejercicio|laboratorio|lab|"
                   r"auxiliar|quiz|interrogacion|presentacion|avance|hito)\s*(?:n(?:umero|°|º)?\s*)?(\d+[a-z]?)?\b")
_NUMS = {"uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7", "ocho": "8",
         "nueve": "9", "diez": "10", "primer": "1", "primero": "1", "primera": "1", "segundo": "2", "segunda": "2",
         "tercer": "3", "tercero": "3", "tercera": "3", "cuarto": "4", "cuarta": "4", "quinto": "5", "quinta": "5"}


def eval_words(text: str) -> list[str]:
    """«la nota del control dos» -> ["control", "2"]; «la nota del primer control» -> ["control", "1"]."""
    q = re.sub(r"\b(" + "|".join(_NUMS) + r")\b", lambda m: _NUMS[m.group(1)], _plain(text))
    q = re.sub(r"\b(\d+)\s+(control|tarea|examen|prueba|certamen|informe|entrega|ejercicio|laboratorio|avance|hito)\b",
               r"\2 \1", q)  # «1 control» (de «primer control») -> «control 1»
    m = _EVAL.search(q)
    if not m:
        return []
    return [m.group(1)] + ([m.group(2)] if m.group(2) else [])


def _eval_matches(words: list[str], ev: str) -> bool:
    e = _plain(ev)
    if not words:
        return True
    if not re.search(rf"\b{re.escape(words[0])}", e):
        return False
    return len(words) < 2 or bool(re.search(rf"(?<![0-9]){re.escape(words[1])}(?![0-9])", e))


def nota_ya_publicada(w: dict, grades: dict) -> tuple[str, str] | None:
    for ev, nota in grades.items():
        if nota and w.get("evaluacion") and _eval_matches(w["evaluacion"], ev):
            return ev, nota
    return None


def revisar_notas(state: dict | None = None, fuente: str = "ucursos") -> list[tuple[dict, str, set]]:
    """Después de cada revisión de U-Cursos: vigilancias de nota cumplidas. -> [(vigilancia, texto, {(code, ev)})].
    Las quita de la lista. `state` = lo que guardó atlas_ucursos_notas (load_state())."""
    if state is None:
        import atlas_ucursos_notas as U  # noqa: N813
        state = U.load_state()
    out = []
    for w in activas("nota"):
        if w.get("fuente", "ucursos") != fuente:  # Canvas y U-Cursos se revisan aparte (18-11-2026)
            continue
        if w["path"] not in state.get("ramos", {}):
            continue  # ese ramo aún no se revisa: no se sabe qué había antes
        cur = state["ramos"][w["path"]]
        antes = w.get("antes")
        if antes is None:  # al crearla el ramo nunca se había revisado: lo de ahora es el punto de partida
            with _LOCK:
                d = load()
                for x in d["activas"]:
                    if x["id"] == w["id"]:
                        x["antes"] = dict(cur)
                save(d)
            continue
        for ev, nota in cur.items():
            if nota and antes.get(ev, "") != nota and _eval_matches(w.get("evaluacion", []), ev):
                # sin la nota: el aviso llega solo (voz, HUD, Telegram); la dice si la pregunta (pedido del usuario, 17-11)
                txt = f"Señor, ya publicaron la nota que esperaba: {w['ramo']}, {ev}."
                out.append((w, txt, {(w.get("code", ""), ev)}))
                remove([w["id"]], {**w, "cumplida": datetime.now().isoformat(timespec="seconds"), "aviso": txt})
                break
    return out


# ----------------------------------------------------------------------------- revisar el correo
def _hdr(raw) -> str:
    from email.header import decode_header, make_header

    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:  # noqa: BLE001
        return str(raw or "")


def fetch_since(since: datetime, accounts=None, want_body=None, max_per_account: int = 400) -> list[dict]:
    """Correos llegados desde `since` en todas las cuentas (todo el correo, no solo Recibidos).
    -> [{"cuenta", "de", "asunto", "fecha" (datetime local), "cuerpo" (solo si want_body(de, asunto))}], y errores."""
    import email
    import imaplib

    from openjarvis.tools.gmail_mark_read import _find_all_mail, _msg_text, mail_accounts

    accounts = accounts if accounts is not None else mail_accounts()
    out, errors = [], []
    for lab, conn in accounts:
        imap = None
        try:
            ea, pw, host, port, sec, _ = conn._resolve_connection()
            imap = conn._open_authenticated_imap(ea, pw, host, port, sec)
            box = _find_all_mail(imap)
            if imap.select(f'"{box}"' if " " in box and not box.startswith('"') else box, readonly=True)[0] != "OK":
                raise RuntimeError(f"no pude abrir {box}")
            st, d = imap.uid("SEARCH", None, "SINCE", (since - timedelta(days=1)).strftime("%d-%b-%Y"))
            uids = d[0].split() if st == "OK" and d and d[0] else []
            for uid in uids[-max_per_account:]:
                st, md = imap.uid("FETCH", uid, "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                if st != "OK" or not md or not isinstance(md[0], tuple):
                    continue
                tt = imaplib.Internaldate2tuple(md[0][0])
                when = datetime.fromtimestamp(time.mktime(tt)) if tt else None
                if when is None or when < since:
                    continue
                msg = email.message_from_bytes(md[0][1])
                row = {"cuenta": lab, "de": _hdr(msg.get("From")), "asunto": _hdr(msg.get("Subject")), "fecha": when,
                       "cuerpo": ""}
                if want_body and want_body(row["de"], row["asunto"]):
                    st, bd = imap.uid("FETCH", uid, "(BODY.PEEK[])")
                    if st == "OK" and bd and isinstance(bd[0], tuple):
                        try:
                            row["cuerpo"] = _msg_text(email.message_from_bytes(bd[0][1]))[:6000]
                        except Exception:  # noqa: BLE001
                            pass
                out.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{lab}: {exc}")
        finally:
            try:
                conn._close_imap(imap)
            except Exception:  # noqa: BLE001
                pass
    return out, errors


def _cuenta(lab: str) -> str:
    """Cómo decir la cuenta (alias de cuentas.json si hay)."""
    try:
        alias = json.loads((HERE / "cuentas.json").read_text(encoding="utf-8"))
        for k, v in (alias.items() if isinstance(alias, dict) else []):
            if isinstance(v, str) and v and v.lower() in lab.lower() and len(k) < 25:
                return {"trabajo": "su cuenta del trabajo", "universidad": "su cuenta de la universidad"}.get(
                    k, f"su cuenta {k}")
    except (OSError, ValueError):
        pass
    return lab


def revisar_correo(rows=None, errors=None, now: datetime | None = None) -> tuple[list[tuple[dict, str]], list[str]]:
    """Revisa las vigilancias de correo y publicación. -> ([(vigilancia, texto del aviso)], errores). Quita las cumplidas."""
    ws = [w for w in activas() if w.get("tipo") in ("correo", "publicacion")]
    if not ws:
        return [], []
    if rows is None:
        since = min(datetime.fromisoformat(w["desde"]) for w in ws)
        need_body = [w for w in ws if w.get("cuerpo")]
        rows, errors = fetch_since(since, want_body=(lambda fr, su: any(
            not w.get("de") or any(d in _plain(fr) for d in w["de"]) for w in need_body)) if need_body else None)
    fired = []
    for w in ws:
        desde = datetime.fromisoformat(w["desde"])
        hit = next((r for r in sorted(rows, key=lambda r: r["fecha"])
                    if r["fecha"] >= desde and match_mail(w, r["de"], r["asunto"], r.get("cuerpo", ""))), None)
        if not hit:
            continue
        quien = re.sub(r"\s*<[^>]+>", "", hit["de"]).strip(' "') or hit["de"]
        if w["tipo"] == "publicacion":
            txt = (f"Señor, hay algo nuevo de {w['ramo']} en U-Cursos: «{hit['asunto']}». "
                   f"Llegó a {_cuenta(hit['cuenta'])}.")
        else:
            txt = (f"Señor, llegó el correo que esperaba de {w['nombre']}: «{hit['asunto']}», de {quien}, "
                   f"en {_cuenta(hit['cuenta'])}.")
        fired.append((w, txt))
        remove([w["id"]], {**w, "cumplida": (now or datetime.now()).isoformat(timespec="seconds"), "aviso": txt})
    return fired, list(errors or [])


# ----------------------------------------------------------------------------- frases
_AVISA = r"(?:avisa(?:me|rme)?|av[ií]same|av[ií]seme|me avis(?:as|a|es|e|ara)|notif[ií]ca(?:me)?|d[ií]me|dime|me dices|me dice)"
_LLEGUE = (r"(?:me\s+)?(?:llegue|llega|lleguen|entre|caiga|aparezca|escriba[n]?|mande[n]?|env[ií]e[n]?|responda[n]?|"
           r"conteste[n]?)")
_MAIL = r"(?:correos?|e-?mails?|mails?|emails?)"
_CANCEL = (r"\b(?:cancela\w*|borra\w*|quita\w*|elimina\w*|olvida\w*|deja de (?:vigilar|esperar|revisar|buscar)|"
           r"ya no (?:esperes|espere|vigiles|vigile|estoy esperando|espero|me avises|me avise|necesito)|no esperes|"
           r"para de (?:vigilar|esperar))\b")
_TOPIC = r"\b(?:correos?|mails?|e-?mails?|notas?|publicacion\w*|vigilanci\w*|vigil\w*|esper\w*)\b"


def parse(text: str) -> dict | None:
    """-> {"op": "listar"} | {"op": "cancelar", "que": str} | {"op": "correo", "quien", "sobre"}
    | {"op": "nota", "texto"} | {"op": "publicacion", "texto"} | None."""
    p = _plain(text).strip()
    p = re.sub(r"^\W*(?:oye\s+)?atlas\W+", "", p)
    p = re.sub(r"[¿?¡!.]+", " ", p).strip()
    p = re.sub(r",\s*", " ", p)
    p = re.sub(r"\s+(?:por favor|porfa|gracias)$", "", p)

    # «¿de quién estamos esperando correo?», «¿qué correos esperamos?» (uso real 17-11-2026: lo tomaba el modelo y
    # respondía con los no leídos): la lista de lo vigilado, solo los correos
    if not re.search(_CANCEL, p) and not re.search(r"\b(?:sin leer|no leidos?|nuevos?)\b", p) and (
            re.search(r"\b(?:de quien(?:es)?|que|cuales?)\b.{0,30}\b(?:estamos|estoy|estas|esta|esperamos|espero|esperas|"
                      r"espera)\b(?:\s+esperando)?.{0,25}?\b" + _MAIL + r"\b", p)
            or re.search(r"\b(?:que|cuales?)\s+" + _MAIL + r"\s+(?:(?:estamos|estoy|estas|esta)\s+)?(?:esperando|esperamos|"
                         r"espero|esperas|vigilando|vigilamos)\b", p)):
        return {"op": "listar", "tipo": "correo"}
    # ¿qué estás vigilando? / ¿qué correos estoy esperando?
    if not re.search(_CANCEL, p) and (
            # «¿qué estamos monitoreando?» (uso real 17-11-2026: lo contestó el modelo, «no hay nada vigilado»)
            re.search(r"\b(?:que|cuales?|cuantas?)\b.{0,30}\b(?:estas|esta|estoy|estamos|estan|tienes|tiene|tenemos)\s+"
                      r"(?:vigilando|esperando|monitoreando|siguiendo)\b", p)
            or re.search(r"\bque\s+(?:monitoreas|monitorea|monitoreamos|vigilamos)\b", p)
            or re.search(r"\b(?:mis|las|tus|sus)\s+vigilancias\b|\bvigilancias\s+(?:activas|pendientes)\b", p)
            or re.fullmatch(r"(?:que|cuales?)\s+vigilancias(?:\s+\w+){0,3}", p)
            or re.search(r"\bque\s+(?:vigilas|vigila|esperas|espera)\b", p)
            # «¿Estás vigilando cursos?» (uso real 16-11: lo contestó el modelo, mal)
            or re.match(r"(?:y\s+)?(?:estas|esta|sigues|sigue)\s+(?:vigilando|monitoreando|revisando)\b", p)):
        if re.search(r"\b(?:vigil\w*|monitore\w*)\b", p) or re.search(_MAIL + r"|\bnotas?\b|\bpublicacion", p) or \
                re.search(r"\bque\s+(?:estas|esta|esperas|espera)\b", p):
            return {"op": "listar"}

    if re.search(_CANCEL, p) and re.search(_TOPIC, p):
        que = re.sub(_CANCEL, " ", p)
        que = re.sub(r"\b(?:la|las|el|los|mi|mis|su|sus)?\s*(?:vigilancias?|correos?|mails?|e-?mails?|que (?:espero|esperaba|"
                     r"estoy esperando|estaba esperando))\b", " ", que)
        que = re.sub(r"\b(?:ya|no|me|lo|la|esperar|esperando|vigilar|de|del|que|el|a)\b", " ", que)
        return {"op": "cancelar", "que": re.sub(r"\s+", " ", que).strip()}

    # notas de U-Cursos
    if re.search(rf"\b{_AVISA}\b.*\b(?:cuando|si|apenas|en cuanto)\b.*\bnotas?\b", p) \
            or re.search(r"\b(?:espero|esperando|estoy esperando)\b.*\bnotas?\b", p):
        if not re.search(r"\b(?:nota de voz|notas de voz|nota mental)\b", p):
            return {"op": "nota", "texto": p}

    # publicación nueva en un ramo (U-Cursos)
    if re.search(rf"\b{_AVISA}\b.*\b(?:cuando|si|apenas|en cuanto)\b", p) and re.search(
            r"\b(?:publicacion\w*|novedad\w*|anuncio\w*|material\w*|algo nuevo|publiquen algo|suban algo|"
            r"mensaje\w* nuevo\w*|foro)\b", p) and not re.search(_MAIL, p):
        return {"op": "publicacion", "texto": p}

    # mensaje de alguien por WhatsApp / Telegram (pedido del usuario, 18-11-2026: «avísame cuando escriba X por ambas
    # redes»). Si nombra el correo, sigue siendo un correo (abajo).
    if not re.search(_MAIL, p):
        m = (re.search(rf"\b{_AVISA}\b.*?\b(?:cuando|si|apenas|en cuanto)\s+(?:me\s+)?(?:escriba|escribe|hable|responda|"
                       rf"conteste|mande\s+(?:un\s+)?(?:mensaje|wsp|whatsapp|telegram))\s+(?P<q>.+?)"
                       rf"(?:\s+(?:por|en|al|a mi)\s+(?P<red>.+))?$", p)
             or re.search(rf"\b{_AVISA}\b.*?\b(?:cuando|si|apenas|en cuanto)\s+(?:me\s+)?(?:llegue|llega|entre)\s+"
                          rf"(?:un|algun|el)\s+(?:mensaje|wsp|whatsapp|telegram)\s+(?:de(?:l)?)\s+(?P<q>.+?)"
                          rf"(?:\s+(?:por|en|al)\s+(?P<red>.+))?$", p))
        if m:
            q = re.sub(r"^(?:el|la|los|las|un|una|a)\s+(?=\S)", "", m.group("q").strip())
            red_txt = m.group("red") or ""
            wa = bool(re.search(_RED_WA, red_txt + " " + p))
            tg = bool(re.search(r"\btele(?:gram|gran)?\b|\btg\b", red_txt + " " + p))
            if re.search(_RED_WA + r"|\btele(?:gram|gran)?\b", q):  # «cuando escriba Pablo por wsp» sin «por» leído
                q = re.split(r"\s+(?:por|en)\s+", q)[0]
            red = "whatsapp" if wa and not tg else "telegram" if tg and not wa else "ambas"
            if q and len(q.split()) <= 5:
                return {"op": "mensaje", "quien": q, "red": red}

    # correo esperado
    m = (re.search(rf"\b{_AVISA}\b.*?\b(?:cuando|si|apenas|en cuanto)\s+{_LLEGUE}\s+(?:un|el|algun|una|la)?\s*(?:nuevo\s+)?"
                   rf"{_MAIL}\s+(?:nuevo\s+)?(?:de(?:l)?|desde)\s+(?P<q>.+)$", p)
         or re.search(rf"\b(?:estoy|ando|estamos)\s+esperando\s+(?:un|el|una|algun)?\s*{_MAIL}\s+(?:de(?:l)?|desde)\s+(?P<q>.+)$", p)
         or re.search(rf"\bespero\s+(?:un|el|una|algun)\s+{_MAIL}\s+(?:de(?:l)?|desde)\s+(?P<q>.+)$", p)
         # «espera un correo de Platanus Hack», «espérame el mail de…», «quédate esperando un correo de…» (uso real 17-11)
         or re.search(rf"^(?:(?:ya|ok|bueno|entonces|y|ahora)\s+)?(?:espera(?:me|nos)?|esperemos|esperen|"
                      rf"(?:quedate|queda|estate|ponte)\s+(?:a\s+)?esperar?(?:ndo)?|espera\s+a\s+que\s+(?:me\s+)?(?:llegue|entre))\s+"
                      rf"(?:(?:que\s+)?(?:me\s+)?(?:llegue|entre)\s+)?(?:un|el|una|algun|la)?\s*(?:nuevo\s+)?{_MAIL}\s+(?:nuevo\s+)?"
                      rf"(?:de(?:l)?|desde)\s+(?P<q>.+)$", p)
         or re.search(rf"\b{_AVISA}\b.*?\b(?:cuando|si|apenas|en cuanto)\s+(?:me\s+)?(?:escriba|responda|conteste|mande un {_MAIL})\s+"
                      rf"(?:a mi correo\s+)?(?P<q>.+?)(?:\s+(?:al|por)\s+{_MAIL})?$", p)
         or re.search(rf"\b{_AVISA}\b.*?\b(?:cuando|si|apenas|en cuanto)\s+(?:me\s+)?llegue\s+(?:el|un|una|la)\s+"
                      rf"(?P<q>.+?)\s+(?:por|al)\s+{_MAIL}$", p)
         # «necesito que estés atento así llega un mail de la Tanus Hack» (uso real 16-11: «así» = «a si»),
         # «estate pendiente por si me llega un correo de…», «vigila si llega un mail de…», «fíjate cuando llegue…»
         or re.search(rf"\b(?:atent[oa]s?|pendientes?|alerta|ojo|vigila\w*|fijate|revisa\w*|mira)\b.*?"
                      rf"\b(?:a\s+si|asi|por\s+si|si|cuando|a\s+cuando|en\s+caso\s+de\s+que|apenas)\s+(?:me\s+)?"
                      rf"(?:llega|llegue|lleguen|llegan|entra|entre|escribe|escriba|manda|mande)\s+"
                      rf"(?:un|el|algun|una|la)?\s*(?:nuevo\s+)?{_MAIL}\s+(?:nuevo\s+)?(?:de(?:l)?|desde)\s+(?P<q>.+)$", p))
    if m:
        q = m.group("q").strip()
        sobre = ""
        sm = re.search(r"\s+(?:sobre|acerca de|con (?:el )?asunto|que diga|que dice|por lo de|por el tema de|del tema)\s+(.+)$", q)
        if sm:
            q, sobre = q[:sm.start()].strip(), sm.group(1).strip()
        q = re.sub(r"\s+(?:en|a)\s+(?:mi|la)\s+(?:cuenta|correo)\b.*$", "", q).strip()
        q = re.sub(r"^(?:el|la|los|las|un|una)\s+(?=\S)", "", q)  # «de la Tanus Hack» -> «tanus hack»
        if q:
            return {"op": "correo", "quien": q, "sobre": sobre}
    return None


_RED_WA = r"\b(?:whatsapp|whats\s?app|wsp|wasap|guasap|whats|wpp)\b"
RED_TXT = {"whatsapp": "WhatsApp", "telegram": "Telegram", "ambas": "WhatsApp o Telegram"}


def mensaje_calza(w: dict, chat: str) -> bool:
    """¿Este chat sin leer es de quien se espera? Compara con su nombre y apodos (como aparecen en WhatsApp/Telegram)."""
    c = _plain(chat)
    if not c:
        return False
    for b in w.get("buscar") or [w.get("nombre", "")]:
        b = _plain(b)
        if len(b) >= 3 and (b == c or re.search(rf"(?<!\w){re.escape(b)}(?!\w)", c)
                            or (len(c) >= 3 and re.search(rf"(?<!\w){re.escape(c)}(?!\w)", b))):
            return True
    return False


def describe(ws: list[dict]) -> str:
    """«el correo de Google Takeout y la nota de control 2 en Redes»."""
    parts = _parts(ws)
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " y " + parts[-1]


def lista_texto(ws: list[dict] | None = None) -> str:
    ws = activas() if ws is None else ws
    if not ws:
        return "No estoy esperando nada en este momento, señor."
    n = len(ws)
    return f"Estoy esperando {describe(ws)}, señor." if n == 1 else f"Estoy esperando {n} cosas, señor: {describe(ws)}."


def _parts(ws: list[dict]) -> list[str]:
    parts = []
    for w in ws:
        if w["tipo"] == "correo":
            parts.append(f"el correo de {w['nombre']}")
        elif w["tipo"] == "publicacion":
            parts.append(f"algo nuevo de {w['ramo']} en U-Cursos")
        elif w["tipo"] == "mensaje":
            parts.append(f"un mensaje de {w['nombre']} por {RED_TXT.get(w.get('red'), 'WhatsApp o Telegram')}")
        else:
            ev = " ".join(w.get("evaluacion", [])) or "cualquier nota"
            parts.append(f"la nota de {ev} en {w['ramo']}" if w.get("evaluacion") else f"una nota nueva en {w['ramo']}")
    return parts


def _fon(s: str) -> str:
    """Cómo suena en castellano: «Hélice» y «elise» suenan igual; «lice» ~ «lise» (la voz confunde c/s/z, b/v, h)."""
    s = re.sub(r"[^a-z0-9 ]", " ", _plain(s))
    s = s.replace("ch", "\x01").replace("qu", "k").replace("ll", "y")
    s = re.sub(r"c(?=[ei])", "s", s).replace("c", "k").replace("z", "s").replace("h", "").replace("v", "b")
    s = s.replace("\x01", "ch")
    return re.sub(r"(.)\1+", r"\1", s)


def _cancel_score(q: str, w: dict) -> float:
    """Qué tan bien suena lo dicho como alguna parte del nombre de la vigilancia (0 a 1)."""
    name = " ".join([w.get("nombre", ""), w.get("ramo", ""), w.get("code", ""), " ".join(w.get("evaluacion", []))])
    fq = _fon(q)
    words = [x for x in _fon(name).split() if len(x) > 2]
    nq = len(fq.split())
    grams = [" ".join(words[i:i + nq]) for i in range(max(1, len(words) - nq + 1))] if words else [""]
    return max(_similar(fq, g) for g in grams)


def find_to_cancel(que: str, ws: list[dict] | None = None) -> list[dict]:
    """Las vigilancias a quitar. Más de una (sin decir «todas») = no está claro cuál: quien llama debe preguntar.
    Uso real 17-11: «deja de esperar el correo de Lice» (era «elise») quitó «HÉLICE…» por contener «lice»."""
    ws = activas() if ws is None else ws
    q = _plain(que)
    if re.search(r"\b(?:todas?|todos?)\b", q):
        return ws
    words = [w for w in _words(q) if w not in {"nota", "notas", "publicacion", "vigilancia", "nueva", "nuevas", "mensaje", "mensajes",
                                         "whatsapp", "wsp", "telegram", "por"}]
    if not words:
        if re.search(r"\bnotas?\b", q):
            notas = [w for w in ws if w["tipo"] == "nota"]
            return notas if len(notas) == 1 else []
        return ws if len(ws) == 1 else []

    scored = sorted(((_cancel_score(" ".join(words), w), w) for w in ws), key=lambda x: -x[0])
    if not scored or scored[0][0] < 0.6:
        return []
    top = scored[0][0]
    # dos que suenan casi igual («elise» y «HÉLICE»): se devuelven los dos y Atlas pregunta, no adivina
    return [w for s, w in scored if s >= top - 0.06]


CORRECCION = re.compile(r"\b(?:el otro|la otra|los otros|no (?:era )?ese|ese no|no (?:era )?esa|esa no|no ese no|"
                        r"te equivocaste|se equivoco|equivocad[oa]|me referia (?:al? )?otr[oa]|al reves|no,? el otro|"
                        r"ese era el bueno|ese no era|dejar de esperar el otro)\b")


def es_correccion(text: str) -> bool:
    """«Tenías que dejar de esperar el otro, no ese» (uso real 17-11): corrige lo último que se hizo."""
    return bool(CORRECCION.search(_plain(text)))


def restaurar(ws: list[dict]) -> None:
    """Vuelve a poner vigilancias quitadas por error, tal como estaban (mismo id y desde)."""
    with _LOCK:
        d = load()
        ids = {x["id"] for x in d["activas"]}
        d["activas"] += [w for w in ws if w["id"] not in ids]
        save(d)

"""Corrección "por sonido" de lo que transcribe el reconocimiento de voz, contra el vocabulario propio.

Busca trozos de 1 a 4 palabras que suenan casi igual a un nombre del vocabulario (contactos, ramos, accesos,
artistas, comandos) y los reemplaza: "Siquer" -> "Zander", "Ermes" -> "Hermes", "prora" -> "progra".
Clave fonética del español de Chile (seseo, b=v, ll=y, h muda). No toca artículos ni preposiciones sueltas,
ni palabras que solo son el nombre con letras de más ("programa" no pasa a ser "progra").
"""

from __future__ import annotations

import difflib
import re
import unicodedata

STOP = {"de", "la", "el", "los", "las", "a", "al", "en", "con", "por", "y", "que", "un", "una", "del", "mi", "se", "lo",
        "le", "me", "te", "es", "o", "u"}
_TRAIL = re.compile(r"[^\wáéíóúñü]+$", re.IGNORECASE)
_HEAD = re.compile(r"^[^\wáéíóúñü]+", re.IGNORECASE)
_cache: tuple[str, list] = ("", [])


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def fon(s: str) -> str:
    """Clave fonética aproximada."""
    s = re.sub(r"[^a-zñ ]", "", _plain(s)).replace(" ", "")
    for a, b in (("ch", "C"), ("ll", "y"), ("qu", "k"), ("gue", "ge"), ("gui", "gi"), ("x", "ks"), ("w", "u"),
                 ("ce", "se"), ("ci", "si"), ("z", "s"), ("ge", "je"), ("gi", "ji"), ("c", "k"), ("v", "b"), ("h", ""),
                 ("ñ", "ny"), ("sh", "s")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def _table(vocab: list[str]) -> list[tuple[str, str, int, list[str]]]:
    global _cache
    key = "\n".join(vocab)
    if _cache[0] == key:
        return _cache[1]
    out = []
    for w in dict.fromkeys(v.strip() for v in vocab if v and v.strip()):
        if " " not in w and w == w.lower():
            continue  # palabra común suelta ("recordatorio", "personal"): corregirla cambia frases normales
        k = fon(w)
        if len(k) >= 4:
            out.append((w, k, len(w.split()), _plain(w).split()))
    _cache = (key, out)
    return out


def corregir(text: str, vocab: list[str], umbral: float = 0.8) -> str:
    """Devuelve el texto con los nombres del vocabulario mal escuchados corregidos."""
    toks = (text or "").split()
    if not toks or not vocab:
        return text or ""
    table = _table(vocab)
    res, i = [], 0
    while i < len(toks):
        best = None
        for w, k, n, ww in table:
            # una palabra de menos solo para nombres de dos ("CirLer" -> "sin leer"), no para frases largas
            for m in ((n - 1, n, n + 1) if n == 2 else (n, n + 1)):
                if m < 1 or i + m > len(toks):
                    continue
                chunk = " ".join(toks[i:i + m])
                core = re.sub(r"[^\wáéíóúñü ]", "", chunk, flags=re.IGNORECASE)
                cw = _plain(core).split()
                if not cw or (cw[0] in STOP and cw[0] != ww[0]) or (cw[-1] in STOP and cw[-1] != ww[-1]):
                    continue  # no comerse "de", "la", "con"… que no son parte del nombre
                ck = fon(core)
                if not ck or (ck != k and (ck in k or k in ck)):
                    continue  # "programa" contiene "progra", "curso" está en "U-Cursos": es otra palabra, no un error
                r = difflib.SequenceMatcher(None, ck, k).ratio()
                need = (umbral if len(k) >= 6 else 0.9) + (0.12 if m > n else 0.03 if m < n else 0)
                if r >= need and (best is None or r > best[0] or (r == best[0] and (m, n) > (best[1], best[4]))):
                    best = (r, m, w, chunk, n)
        if best:
            _, m, w, chunk, _n = best
            if re.sub(r"[^\w ]", "", _plain(chunk)).strip() == re.sub(r"[^\w ]", "", _plain(w)).strip():
                res.append(chunk)  # ya estaba bien: se deja como vino (mayúsculas, puntuación)
            else:
                head = _HEAD.match(chunk)
                tail = _TRAIL.search(chunk)
                res.append((head.group(0) if head else "") + w + (tail.group(0) if tail else ""))
            i += m
        else:
            res.append(toks[i])
            i += 1
    return " ".join(res)

"""Google Calendar para Atlas: autorización (OAuth de app de escritorio), leer y crear eventos.

Archivos (solo en este PC, fuera de la carpeta del programa):
    ~/.atlas/connectors/google_client.json          credencial de la app (descargada de Google Cloud)
    ~/.atlas/connectors/google_calendar_token.json  autorización del usuario (se crea al conectar)

Permiso pedido: solo "ver y editar eventos" (calendar.events). Nada de correo ni de otros datos.
Solo usa la biblioteca estándar de Python.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from openjarvis.security import atlas_secretos

CONN = Path.home() / ".atlas" / "connectors"
CLIENT = CONN / "google_client.json"
TOKEN = CONN / "google_calendar_token.json"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
API = "https://www.googleapis.com/calendar/v3"
_list_cache: dict[tuple, tuple[float, list]] = {}
NOW = None  # las pruebas lo reemplazan por una función que devuelve una fecha fija


class GCalError(Exception):
    pass


def is_connected() -> bool:
    return TOKEN.exists() and CLIENT.exists()


def _client() -> tuple[str, str]:
    data = atlas_secretos.cargar_json(CLIENT) or {}
    d = data.get("installed") or data.get("web") or data
    if not d.get("client_id"):
        raise GCalError("google_client.json no es una credencial OAuth válida")
    return d["client_id"], d.get("client_secret", "")


def _post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            err = {}
        raise GCalError(err.get("error_description") or err.get("error") or f"HTTP {exc.code}") from None


# ------------------------------------------------------------------ conexión (una sola vez)
def connect(timeout: int = 300) -> str:
    """Abre el navegador para que el usuario autorice; guarda la autorización. -> correo/calendario conectado."""
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    client_id, client_secret = _client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    got: dict = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:  # silencio
            pass

        def do_GET(self) -> None:  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and ("code" in q or "error" in q):
                got["code"] = q.get("code", [""])[0]
                got["error"] = q.get("error", [""])[0]
                msg = "Listo. Atlas ya puede usar su calendario. Puede cerrar esta pestaña." if got["code"] \
                    else "No se autorizó el acceso. Puede cerrar esta pestaña."
            else:
                msg = "Solicitud no reconocida."
            body = f"<html><meta charset='utf-8'><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2></body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Abriendo el navegador para autorizar. Si no se abre, copie este enlace:\n\n" + url + "\n")
    if not os.environ.get("ATLAS_PRUEBAS") == "1":  # las pruebas no abren el navegador
        webbrowser.open(url)
    server.timeout = 2
    end = time.time() + timeout
    while "code" not in got and time.time() < end:
        server.handle_request()
    server.server_close()
    if not got.get("code"):
        raise GCalError("no se recibió la autorización" + (f" ({got.get('error')})" if got.get("error") else " (tiempo agotado)"))
    tok = _post_form("https://oauth2.googleapis.com/token", {
        "code": got["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if not tok.get("refresh_token"):
        raise GCalError("Google no entregó una autorización permanente; intente de nuevo")
    _save_token({"refresh_token": tok["refresh_token"], "access_token": tok.get("access_token", ""),
                 "expires_at": time.time() + int(tok.get("expires_in", 0)) - 60})
    try:
        return _api("GET", "/calendars/primary").get("summary", "calendario principal")
    except Exception:  # noqa: BLE001
        return "calendario principal"


def _save_token(tok: dict) -> None:
    CONN.mkdir(parents=True, exist_ok=True)
    atlas_secretos.guardar_json(TOKEN, tok)  # cifrado en el Administrador de credenciales


def _access_token() -> str:
    if not is_connected():
        raise GCalError("Google Calendar no está conectado")
    tok = atlas_secretos.cargar_json(TOKEN) or {}
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 30:
        return tok["access_token"]
    client_id, client_secret = _client()
    try:
        new = _post_form("https://oauth2.googleapis.com/token", {
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    except GCalError as exc:
        if "invalid_grant" in str(exc) or "expired" in str(exc).lower() or "revoked" in str(exc).lower():
            raise GCalError("la autorización de Google venció o fue revocada; ejecute Conectar-Google-Calendar otra vez") from None
        raise
    tok["access_token"] = new["access_token"]
    tok["expires_at"] = time.time() + int(new.get("expires_in", 3600)) - 60
    _save_token(tok)
    return tok["access_token"]


def _api(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + _access_token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise GCalError(msg or f"Google respondió HTTP {exc.code}") from None


# ------------------------------------------------------------------ leer y crear
def _rfc3339(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")  # hora local de este PC, con su desfase


def _from_api(v: dict) -> tuple[datetime, bool]:
    if v.get("dateTime"):
        return datetime.fromisoformat(v["dateTime"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None), False
    d = date.fromisoformat(v["date"])
    return datetime(d.year, d.month, d.day), True


def list_events(a: datetime, b: datetime) -> list[dict]:
    """Eventos del calendario principal en [a, b), con las repeticiones ya expandidas."""
    key = (a.replace(second=0, microsecond=0), b.replace(second=0, microsecond=0))
    hit = _list_cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    out, page = [], None
    for _ in range(6):
        params = {"timeMin": _rfc3339(a), "timeMax": _rfc3339(b), "singleEvents": "true",
                  "orderBy": "startTime", "maxResults": "250"}
        if page:
            params["pageToken"] = page
        data = _api("GET", "/calendars/primary/events", params)
        for it in data.get("items", []):
            if it.get("status") == "cancelled" or not it.get("start"):
                continue
            start, allday = _from_api(it["start"])
            end = _from_api(it["end"])[0] if it.get("end") else start
            people = [{"name": p.get("displayName", ""), "email": p.get("email", ""), "organizer": bool(p.get("organizer"))}
                      for p in it.get("attendees") or [] if not p.get("self") and not p.get("resource")]
            org = it.get("organizer") or {}
            if not people and org.get("email") and not org.get("self"):
                people = [{"name": org.get("displayName", ""), "email": org["email"], "organizer": True}]
            out.append({"summary": it.get("summary", "(sin título)"), "start": start, "end": end, "allday": allday,
                        "location": it.get("location", ""), "calendar": "Google", "id": it.get("id", ""),
                        "description": (it.get("description") or "")[:300], "attendees": people})
        page = data.get("nextPageToken")
        if not page:
            break
    _list_cache[key] = (time.time(), out)
    return out


def create_event(summary: str, start: datetime, end: datetime | None = None, allday: bool = False,
                 location: str = "", description: str = "") -> dict:
    body: dict = {"summary": summary}
    if allday:
        last = (end or start).date() if end else start.date()
        body["start"] = {"date": start.date().isoformat()}
        body["end"] = {"date": (max(last, start.date()) + timedelta(days=1)).isoformat()}
    else:
        body["start"] = {"dateTime": _rfc3339(start)}
        body["end"] = {"dateTime": _rfc3339(end or start + timedelta(hours=1))}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    _list_cache.clear()
    return _api("POST", "/calendars/primary/events", body=body)


def delete_event(event_id: str) -> None:
    _list_cache.clear()
    _api("DELETE", "/calendars/primary/events/" + urllib.parse.quote(event_id, safe=""))


def patch_event(event_id: str, summary: str | None = None, start: datetime | None = None,
                end: datetime | None = None, allday: bool = False) -> dict:
    body: dict = {}
    if summary:
        body["summary"] = summary
    if start is not None:
        if allday:
            body["start"] = {"date": start.date().isoformat(), "dateTime": None}
            body["end"] = {"date": (start.date() + timedelta(days=1)).isoformat(), "dateTime": None}
        else:
            body["start"] = {"dateTime": _rfc3339(start), "date": None}
            body["end"] = {"dateTime": _rfc3339(end or start + timedelta(hours=1)), "date": None}
    _list_cache.clear()
    return _api("PATCH", "/calendars/primary/events/" + urllib.parse.quote(event_id, safe=""), body=body)


_Q_STOP = {"las", "los", "del", "con", "una", "uno", "por", "que", "evento", "eventos", "para", "este", "esta", "esos", "aquel", "tengo", "tenia", "habia", "donde", "sobre",
           "proximo", "proxima", "siguiente", "creaste", "hiciste", "agendaste", "pusiste", "fijaste", "calendario",
           "agenda", "favor", "quiero", "puedes", "cuarto", "media", "hora", "horas", "tarde", "manana", "noche"}


def _top(query: str, events: list[dict], day_given: bool) -> list[dict]:
    """Los eventos que mejor calzan con el nombre dicho (empatados en el mejor puntaje), o [] si ninguno calza."""
    toks = [w for w in re.findall(r"[a-z0-9]{3,}", _plain(query)) if w not in _Q_STOP]
    strong = [t for t in toks if t not in _Q_GENERIC]

    def hits(tokens: list[str], words: list[str]) -> int:
        return sum(1 for t in tokens if any(w.startswith(t[:5]) or t.startswith(w[:5]) for w in words))

    scored = []
    for e in events:
        words = re.findall(r"[a-z0-9]{3,}", _plain(e["summary"]))
        total, s_hits = hits(toks, words), hits(strong, words)
        # Con palabras propias ("Felipe", "decano") deben calzar al menos la mitad; el tipo de evento solo
        # ("reunión", "laboratorio") basta únicamente si no se dijo nada más o si se indicó el día.
        if total and (not strong or s_hits * 2 >= len(strong) or day_given):
            scored.append((s_hits * 10 + total, e))
    if not scored:
        return []
    best = max(sc for sc, _ in scored)
    return [e for sc, e in scored if sc == best]


def _has_name(query: str) -> bool:
    return bool([w for w in re.findall(r"[a-z0-9]{3,}", _plain(query)) if w not in _Q_STOP])


def find_events(query: str, day: date | None = None, at: datetime | None = None, any_half: bool = False,
                now: datetime | None = None) -> list[dict]:
    """Los eventos de Google Calendar a los que puede referirse la frase, por nombre, día y hora (los mejores primero).
    Sin nombre («el evento de hoy a las 11», «el evento de mañana») valen todos los de ese día / esa hora.
    any_half: «a las 5» sin decir mañana/tarde vale 5:00 y 17:00."""
    now = now or (NOW() if NOW else datetime.now())
    if day:
        a = datetime(day.year, day.month, day.day)
        b = a + timedelta(days=1)
    else:
        a, b = now - timedelta(hours=1), now + timedelta(days=60)
    events = list_events(a, b)
    if at is not None:
        hours = [at] + ([at + timedelta(hours=12), at - timedelta(hours=12)] if any_half else [])

        def at_hour(e):
            if e.get("allday"):
                return False
            s = e["start"].replace(tzinfo=None)
            f = (e.get("end") or e["start"]).replace(tzinfo=None)
            # empieza a esa hora (±30 min) o está en curso a esa hora
            return any(h.date() == s.date() and (abs((s - h).total_seconds()) <= 1800 or s <= h < f) for h in hours)

        events = [e for e in events if at_hour(e)]
    if not _has_name(query):
        return events if (day or at is not None) else []
    return _top(query, events, day is not None or at is not None)


def find_event(query: str, day: date | None = None, now: datetime | None = None) -> tuple[dict | None, int]:
    """Busca en Google Calendar el evento al que se refiere la frase. -> (evento o None, cuántos calzaban igual)."""
    now = now or (NOW() if NOW else datetime.now())
    if day:
        a = datetime(day.year, day.month, day.day)
        b = a + timedelta(days=1)
    else:
        a, b = now - timedelta(hours=1), now + timedelta(days=60)
    events = list_events(a, b)
    if not _has_name(query):
        return (events[0], len(events)) if (day and len(events) == 1) else (None, len(events))
    top = _top(query, events, day is not None)
    return (top[0], len(top)) if top else (None, 0)


_Q_GENERIC = {"reunion", "reuniones", "cita", "citas", "laboratorio", "lab", "clase", "clases", "taller", "llamada",
              "almuerzo", "cena", "junta", "control", "examen", "recordatorio", "compromiso", "turno", "auxiliar",
              "catedra", "ayudantia", "entrega"}

DEL = (r"(?:b[oó]rra(?:me|r|s)?|borres|elim[ií]na(?:me|r|s)?|elimines|canc[eé]la(?:me|r|s)?|canceles|qu[ií]ta(?:me|r|s)?|quites|"
       r"s[aá]ca(?:me|r|s)?|saques|an[uú]la(?:r|s)?|anules)")
MOVE = (r"(?:mu[eé]ve(?:me|lo|la)?|muevas|mover|c[aá]mbia(?:me|lo|la)?|cambies|cambiar|p[aá]sa(?:me|lo|la)?|pases|pasar|"
        r"reag[eé]nda(?:me|r|s)?|reagendes|reprogr[aá]ma(?:me|r|s)?|reprogrames|c[oó]rre(?:me|lo|la|r)?|corras|"
        r"atr[aá]sa(?:me|r|lo|la)?|adel[aá]nta(?:me|r|lo|la)?)")
_NOT_CAL = r"\b(notas?|like|me gusta|canci[oó]n|m[uú]sica|recomendaci\w*|repertorio|artistas?|apagado|reinicio|correos?|mails?|archivos?|alias|volumen|programa|app|ventana|sesi[oó]n)\b"


def _title(text: str) -> str:
    t = re.sub(r"\bque\s+(?:me\s+)?(?:creaste|hiciste|agendaste|pusiste|fijaste|anotaste|ten[ií]a|tengo|hab[ií]a)\b", " ", text, flags=re.I)
    t = re.sub(r"\b(?:de|en|a)\s+(?:mi|el|la)\s+(?:calendario|agenda)\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,.;:-")
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"^(un|una|el|la|los|las|que|de|para|a|y|al|mi|evento|eventos)\s+", "", t, flags=re.I).strip(" ,.;:-")
        t = re.sub(r"\s+(el|la|a|de|para|por|y|en|con|del|al)$", "", t, flags=re.I).strip(" ,.;:-")
    return t[:1].upper() + t[1:] if t else ""


def parse_change(text: str, now: datetime | None = None) -> dict | None:
    """Borrar, renombrar/reemplazar o mover un evento. -> {'op','query','day',…} o None si la frase no va por ahí."""
    now = now or (NOW() if NOW else datetime.now())
    if re.search(_NOT_CAL, text, re.I):
        return None
    m = re.match(LEAD + r"(?:ren[oó]mbra(?:me|r|lo|la)?|(?:c[aá]mbia|corr[ií]ge|corrige|modifica|arregla|edita|actualiza)(?:le|me)?\s+"
                 r"(?:el\s+)?(?:nombre|t[ií]tulo)\s+(?:de\s+la|de|del|al|a\s+la|a))\s+(.+?)\s+(?:a|por|como)\s+(.+?)[.!]?$", text, re.I)
    if m:
        # Nombres entre comillas mandan (uso real: «… el evento del viernes 20 a las 9:30 «A» a «B» se cortaba en
        # "a las" y el título nuevo quedó «9:30 «A» a «B»). La última comilla puede venir sin cerrar.
        quoted = [q.strip() for q in re.findall(r"[«“\"]\s*([^«»“”\"]+?)\s*(?:[»”\"]|$)", text) if q.strip()]
        if len(quoted) >= 2:
            return {"op": "rename", "query": _title(quoted[-2]), "day": None, "new_title": _title(quoted[-1]),
                    "has_noun": True}
        return {"op": "rename", "query": _title(m.group(1)), "day": None, "new_title": _title(m.group(2)),
                "has_noun": True}
    m = re.match(LEAD + DEL + r"\b", text, re.I)
    if m:
        rest = text[m.end():]
        new_title = None
        mm = re.search(r"\s+y\s+(?:luego\s+|despu[eé]s\s+)?(?:pon(?:me|gas)?|crea(?:me|s)?|ag[eé]nda(?:me)?|agr[eé]ga(?:me)?|a[nñ]ade|deja|fija)\s+"
                       r"(.+?)\s+(?:en|a)\s+(?:el|la|ese|esa)\s*mism[oa]\s+(?:horario|hora|d[ií]a|bloque)[^.]*\.?\s*$", rest, re.I)
        if mm:
            new_title, rest = _title(mm.group(1)), rest[:mm.start()]
        has_noun = bool(re.search(EVENT_NOUN, rest, re.I)) or bool(re.search(CAL_NOUN, _plain(rest)))
        # uso real 17-11: «Elimina el evento de hoy a las 11 de la mañana» (dicho 11:09) buscaba un evento LLAMADO
        # «Hoy a las 11 de la mañana»: la hora ya había pasado y parse_event lo rechazaba. Ahora el día y la hora
        # sirven para encontrarlo.
        ev = parse_event("agenda evento " + rest.strip(" ."), now, existing=True)
        if not (ev and "start" in ev) and re.search(r"\b(?:a|de)\s+las?\s+\d", rest, re.I):
            # «el evento de las 11», sin día: el de hoy
            ev = parse_event("agenda evento " + re.sub(r"\bde\s+(las?\s+\d)", r"a \1", rest.strip(" .")) + " hoy",
                             now, existing=True)
        at, any_half = None, False
        if ev and "start" in ev:
            query = _title(ev["summary"])
            day = ev["start"].date() if ev.get("explicit_date") or not ev["allday"] else None
            if not ev["allday"]:
                at = ev["start"]
                # «a las 5» sin «de la tarde»: puede ser 5:00 o 17:00
                any_half = not re.search(r"de la (?:ma[nñ]ana|tarde|noche|madrugada)|\b[ap]\.?\s?m\b|\d[:.]\d{2}|"
                                         r"\b(?:1[3-9]|2[0-3])\b|\b(?:mediod[ií]a|medianoche)\b", rest, re.I)
        else:
            query, day = _title(rest), None
        if query.lower() == "evento" or re.fullmatch(r"(?i)(?:lo|eso|esto|ese|esa|las?|los|de|de las?)", query):
            query = ""
        return {"op": "rename" if new_title else "delete", "query": query, "day": day, "new_title": new_title,
                "has_noun": has_noun or at is not None, "at": at, "any_half": any_half}
    m = re.match(LEAD + MOVE + r"\b", text, re.I)
    if m:
        rest = text[m.end():]
        has_noun = bool(re.search(EVENT_NOUN, rest, re.I)) or bool(re.search(CAL_NOUN, _plain(rest)))
        ev = parse_event("agenda evento " + rest.strip(" ."), now)
        if not ev or "start" not in ev:
            return None
        return {"op": "move", "query": _title(ev["summary"]), "day": None, "start": ev["start"], "end": ev["end"],
                "allday": ev["allday"], "explicit_end": ev["explicit_end"], "has_noun": has_noun}
    return None


# ------------------------------------------------------------------ entender "agéndame … mañana a las 5"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
_NUMW = {"una": 1, "uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
         "nueve": 9, "diez": 10, "once": 11, "doce": 12}
_NUM = r"(\d{1,2}(?:[:.]\d{2})?|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
_EXTRA = r"(?:\s*(?:horas?|hrs?\.?|h)\b)?(?:\s+y\s+(media|cuarto|\d{1,2}))?(?:\s+en punto)?"
_PER = r"(?:\s*(?:de|en|por)\s+la\s+(ma[nñ]ana|tarde|noche|madrugada)|\s*(a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z]))?"

VERBS = (r"(?:ag[eé]nda(?:me|lo|la|r|s)?|agend[ae]s?|agent[ae]s?|agendar|f[ií]ja(?:me|lo|r|s)?|fijes|fijar|progr[aá]ma(?:me|r|s)?|programes|"
         r"crea(?:me|r|s)?|crees|a[nñ]ad[ea]s?|a[nñ]adir|agr[eé]ga(?:me|r|s)?|agregues|an[oó]ta(?:me|r|s)?|anotes|"
         r"pon(?:me|er|gas)?|recu[eé]rda(?:me|r)|recuerdes|av[ií]sa(?:me|r)|avises|reserva(?:me|r|s)?|reserves|marca(?:me|r)?|marques|"
         # "hagamos / haz / abre / bloquea un cupo (un bloque, un espacio) para …"
         r"(?:hac(?:er|emos)|haz(?:me)?|hagamos|abr(?:e|ir|ime)|bloque(?:a|ar|ame))(?=\s+(?:un|una)\s+(?:cupo|bloque|espacio|hueco)\b))")
_ADV = r"(?:(?:tambi[eé]n|adem[aá]s|igual|ahora|luego|despu[eé]s)\s+)?"
LEAD = (r"^[\s¿¡]*(?:(?:oye|hey|atlas|jarvis|por favor|porfa|y|ah|ya)[,\s]+)*"
        r"(?:(?:quiero|necesito|me gustar[ií]a|quisiera)\s+que\s+" + _ADV + r"|(?:puedes|podr[ií]as|me puedes|podemos|podr[ií]amos|se puede)\s+" + _ADV + r")?"
        + _ADV + r"(?:me\s+)?")
EVENT_NOUN = r"\b(evento|reuni[oó]n|cita|recordatorio|junta|llamada|hora (?:con|al|en|para)|compromiso|cumplea[nñ]os|entrega|control|examen|laboratorio|lab|clase|taller|ayudant[ií]a|auxiliar|c[aá]tedra|almuerzo|cena|turno|sesi[oó]n|cupo|bloque)\b"
CAL_NOUN = r"\b(calendario|agenda)\b"


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _hm(num: str, extra: str | None) -> tuple[int, int]:
    num = num.lower()
    if num in _NUMW:
        h, m = _NUMW[num], 0
    elif ":" in num or "." in num:
        h, m = (int(x) for x in re.split(r"[:.]", num))
    else:
        h, m = int(num), 0
    if extra:
        m = {"media": 30, "cuarto": 15}.get(extra.lower(), int(extra) if extra.isdigit() else 0)
    return h, m


def _apply_period(h: int, per: str | None, ampm: str | None, explicit24: bool) -> int:
    per = _plain(per or "")
    ampm = re.sub(r"[.\s]", "", (ampm or "").lower())
    if per in ("tarde", "noche") or ampm == "pm":
        return 0 if (per == "noche" and h == 12) else (h + 12 if h < 12 else h)
    if per in ("manana", "madrugada") or ampm == "am":
        return 0 if h == 12 else h
    if explicit24 or h > 12 or h == 0:
        return h
    return h + 12 if 1 <= h <= 7 else h  # sin indicación: "a las 5" suele ser de la tarde


_DAY_AHEAD = (r"(?=(?:(?:pr[oó]ximo|este|ese|mismo)\s+)*(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
              r"ma[nñ]ana\b|pasado\s+ma[nñ]ana|d[ií]a\s+\d|\d{1,2}\s+de\s+[a-z]))")


_DAY_ANY = (r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|pasado\s+ma[nñ]ana|(?<!la )ma[nñ]ana\b|"
            r"d[ií]a\s+\d|\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|sep?tiembre|octubre|noviembre|diciembre))")


def parse_event(text: str, now: datetime | None = None, _inner: bool = False, existing: bool = False) -> dict | None:
    """-> {'summary','start','end','allday'} | {'ask': pregunta} | None si la frase no pide agendar algo.
    existing=True: la fecha y hora nombran un evento que YA está (para borrarlo o cambiarlo), así que una hora que ya
    pasó hoy sigue siendo hoy («borra el evento de hoy a las 11» a las 11:10) y no se rechaza por estar en el pasado."""
    now = now or (NOW() if NOW else datetime.now())
    m = re.match(LEAD + VERBS + r"\b", text, re.I)
    if not m:  # "Tiene que ser un evento que dure…", "quiero un evento el viernes…": también es pedir que se agende
        m = re.match(r"^\s*(?:(?:oye|atlas|jarvis|no|y|ah|ya)[,\s]+)*(?:tiene que ser|debe ser|deber[ií]a ser|que sea|ser[ií]a|quiero|necesito|hazme|haz)\s+"
                     r"(?=(?:un|una|el|la)\s+(?:evento|recordatorio|reuni[oó]n|cita)\b)", text, re.I)
        if m:
            text = text[:m.end()] + text[m.end():]
            verb, rest = "agenda", text[m.end():]
    else:
        verb, rest = _plain(m.group(0)), text[m.end():]
    if not m:
        return None
    low_all = _plain(text)
    if re.search(r"\b(musica|cancion|volumen|correos?|mails?|leid[oa]s?|recomendaci|repertorio|artista)\b", low_all):
        return None
    strong = bool(re.search(r"agend|agent|fij|program|recu[e]rd|avis|reserv", verb))
    has_noun = bool(re.search(EVENT_NOUN, rest, re.I)) or bool(re.search(CAL_NOUN, _plain(rest)))

    # "…el viernes a las 8 hasta el domingo a medianoche": lo que sigue a "hasta <día>" es el término
    end_override, end_title = None, ""
    mh = None if _inner else re.search(r"[\s,]+hasta\s+", rest, re.I)
    if mh and not re.search(_DAY_ANY, rest[mh.end():], re.I):
        mh = None  # "de 3 hasta las 5": mismo día, lo resuelve el rango de horas
    if mh:
        tail = re.sub(r"^(?:el|la)\s+(?=" + _DAY_ANY + ")", "", rest[mh.end():], flags=re.I)
        tail = re.sub(r"^(las?\s+\d)", r"a \1", tail, flags=re.I)  # "hasta las 23.59 del domingo" -> "a las 23.59 …"
        sub = parse_event("agenda " + tail, now, _inner=True)
        if sub and "start" in sub:
            end_override = sub["start"]
            if sub["allday"] or (re.search(r"media\s?noche", tail, re.I) and (end_override.hour, end_override.minute) == (0, 0)):
                end_override = end_override.replace(hour=23, minute=59)  # "hasta el domingo (a medianoche)": fin de ese día
            end_title = "" if sub["summary"] == "Evento" else sub["summary"]
            rest = rest[:mh.start()]

    spans: list[tuple[int, int]] = []

    def take(mo) -> None:
        spans.append(mo.span())

    start_t = end_t = None
    allday = bool(re.search(r"\btodo el d[ií]a\b", rest, re.I))
    for mo in re.finditer(r"\btodo el d[ií]a\b", rest, re.I):
        take(mo)
    # rango "de 3 a 5 de la tarde" / "desde las 15:00 hasta las 16:30"
    mo = re.search(rf"\b(?:de|desde)\s+(?:las?\s+)?{_NUM}{_EXTRA}\s+(?:a|hasta)\s+(?:las?\s+)?{_NUM}{_EXTRA}{_PER}", rest, re.I)
    if mo and not re.search(r"\b(de|del)\s+\d{1,2}\s+(de|al)\s+[a-z]", _plain(mo.group(0))):
        h1, m1 = _hm(mo.group(1), mo.group(2))
        h2, m2 = _hm(mo.group(3), mo.group(4))
        ex24 = ":" in mo.group(1) or ":" in mo.group(3)
        h2 = _apply_period(h2, mo.group(5), mo.group(6), ex24)
        h1 = _apply_period(h1, mo.group(5), mo.group(6), ex24) if (mo.group(5) or mo.group(6)) else _apply_period(h1, None, None, ex24)
        if h1 > h2 and h1 >= 12 and (mo.group(5) or mo.group(6)):
            h1 -= 12  # "de 11 a 1 de la tarde"
        if (h2, m2) <= (h1, m1) and h2 < 12:
            h2 += 12
        start_t, end_t = (h1, m1), (h2, m2)
        take(mo)
    else:
        mo = re.search(rf"\b(?:a|desde|despu[eé]s de|a partir de|tipo|como a)\s+(?:eso de\s+)?las?\s+{_NUM}{_EXTRA}{_PER}", rest, re.I) \
            or re.search(rf"(?<![\w:/-]){_NUM}{_EXTRA}\s*(?:de la\s+(ma[nñ]ana|tarde|noche)|(a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z]))", rest, re.I) \
            or re.search(r"(?<![\w:/-])(\d{1,2}:\d{2})()(?:\s*(?:horas?|hrs?\.?))?()()", rest, re.I)
        if mo:
            h, mi = _hm(mo.group(1), mo.group(2) or None)
            start_t = (_apply_period(h, mo.group(3), mo.group(4), ":" in mo.group(1)), mi)
            take(mo)
        else:
            mo = re.search(r"\bal?\s+medio\s?d[ií]a\b|\ba\s+(?:la\s+)?media\s?noche\b", rest, re.I)
            if mo:
                start_t = (0, 0) if "noche" in _plain(mo.group(0)) else (12, 0)
                take(mo)
    # duración "por una hora", "durante 30 minutos"
    dur = None
    mo = re.search(r"\b(?:por|durante|de)\s+(?:(media hora)|(una hora y media|hora y media)|(\d+|una|un|dos|tres|cuatro|cinco|seis)\s+horas?(\s+y\s+media)?|(\d+)\s+minutos?)\b", rest, re.I)
    if mo:
        if mo.group(1):
            dur = timedelta(minutes=30)
        elif mo.group(2):
            dur = timedelta(minutes=90)
        elif mo.group(3):
            n = _NUMW.get(mo.group(3).lower()) or int(mo.group(3))
            dur = timedelta(hours=n, minutes=30 if mo.group(4) else 0)
        else:
            dur = timedelta(minutes=int(mo.group(5)))
        take(mo)

    # fecha
    masked = list(rest)
    for a_, b_ in spans:
        masked[a_:b_] = " " * (b_ - a_)
    rest_d = "".join(masked)
    today = now.date()
    day = None
    explicit_date = True
    mo = re.search(r"\bpasado\s+ma[nñ]ana\b", rest_d, re.I)
    if mo:
        day = today + timedelta(days=2)
    if day is None:
        mo = re.search(r"\b(?:para\s+)?ma[nñ]ana\b", rest_d, re.I)
        if mo:
            day = today + timedelta(days=1)
    if day is None:
        mo = re.search(r"\b(?:para\s+)?hoy\b|\besta\s+(tarde|noche)\b", rest_d, re.I)
        if mo:
            day = today
            if start_t and start_t[0] < 12 and mo.group(1):
                start_t = (start_t[0] + 12, start_t[1])
    if day is None:
        mo = re.search(r"\b(?:el\s+|para el\s+|este\s+|para este\s+)?(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+)?(?:d[ií]a\s+)?(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|sep?tiembre|octubre|noviembre|diciembre)(?:\s+(?:de|del)\s+(\d{4}))?\b", rest_d, re.I)
        if mo:
            mon = [_plain(x) for x in MESES].index(_plain(mo.group(2)).replace("setiembre", "septiembre")) + 1
            year = int(mo.group(3)) if mo.group(3) else today.year
            try:
                day = date(year, mon, int(mo.group(1)))
                if not mo.group(3) and day < today:
                    day = date(year + 1, mon, int(mo.group(1)))
            except ValueError:
                return {"ask": "Esa fecha no existe, señor. ¿Para qué día lo agendo?"}
    if day is None:
        mo = re.search(r"\b(?:el\s+|para el\s+)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", rest_d)
        if mo:
            year = int(mo.group(3)) if mo.group(3) else today.year
            year += 2000 if year < 100 else 0
            try:
                day = date(year, int(mo.group(2)), int(mo.group(1)))
                if not mo.group(3) and day < today:
                    day = date(year + 1, int(mo.group(2)), int(mo.group(1)))
            except ValueError:
                return {"ask": "Esa fecha no existe, señor. ¿Para qué día lo agendo?"}
    if day is None:  # "el viernes 27": manda el número
        mo = re.search(r"\b(?:el\s+|para el\s+|este\s+|para este\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+(\d{1,2})\b(?!\s*(?:[:.]\d|horas?|hrs|de la|am|pm))", rest_d, re.I)
        if mo:
            n = int(mo.group(1))
            try:
                day = today.replace(day=n)
                if day < today:
                    day = (today.replace(day=1) + timedelta(days=32)).replace(day=n)
            except ValueError:
                return {"ask": "Ese día no existe en el mes, señor. ¿Para qué fecha lo agendo?"}
    if day is None:
        mo = re.search(r"\b(?:el\s+|para el\s+|este\s+|para este\s+)?(pr[oó]ximo\s+|siguiente\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)(\s+(?:pr[oó]ximo|siguiente|que viene))?\b", rest_d, re.I)
        if mo:
            wd = [_plain(x) for x in DIAS].index(_plain(mo.group(2)))
            delta = (wd - today.weekday()) % 7
            if delta == 0 and (mo.group(1) or mo.group(3) or (start_t and datetime.combine(today, datetime.min.time()).replace(hour=start_t[0] % 24, minute=start_t[1]) <= now)):
                delta = 7
            day = today + timedelta(days=delta)
    if day is None:
        mo = re.search(r"\b(?:el\s+|para el\s+)d[ií]a\s+(\d{1,2})\b|\b(?:el|para el)\s+(\d{1,2})\b(?!\s*(?:[:.]\d|horas?|hrs|de la|am|pm))", rest_d, re.I)
        if mo:
            n = int(mo.group(1) or mo.group(2))
            try:
                day = today.replace(day=n)
                if day < today:
                    day = (today.replace(day=1) + timedelta(days=32)).replace(day=n)
            except ValueError:
                return {"ask": "Ese día no existe en el mes, señor. ¿Para qué fecha lo agendo?"}
    if day is None:
        mo = re.search(r"\ben\s+(\d+|un|una|dos|tres|cuatro|cinco|seis|siete)\s+(d[ií]as?|semanas?)\b", rest_d, re.I)
        if mo:
            n = _NUMW.get(mo.group(1).lower()) or int(mo.group(1))
            day = today + timedelta(days=n * (7 if mo.group(2).lower().startswith("sem") else 1))
    if mo and day is not None:
        take(mo)
    if day is None:
        explicit_date = False

    if day is None and start_t is None:
        if strong or has_noun:
            return {"ask": "¿Para qué día y a qué hora lo agendo, señor?"}
        return None
    if not (strong or has_noun):
        return None  # "pon … a las 5" sin nada que indique un evento: no es para el calendario
    if day is None:
        day = today
    if start_t is None:
        allday = True
    if allday:
        start = datetime(day.year, day.month, day.day)
        end = start
    else:
        start = datetime(day.year, day.month, day.day) + timedelta(hours=start_t[0], minutes=start_t[1])
        if start <= now and not explicit_date and not existing:
            start += timedelta(days=1)  # "a las 9" y ya pasaron las 9: mañana
        if end_t:
            end = datetime(start.year, start.month, start.day) + timedelta(hours=end_t[0], minutes=end_t[1])
            if end <= start:
                end += timedelta(days=1)
        else:
            end = start + (dur or timedelta(hours=1))
    if end_override is not None:
        while end_override <= start:
            end_override += timedelta(days=7)  # "hasta el domingo": el domingo que viene después del inicio
        end = end_override
    if start < now - timedelta(minutes=1) and not allday and not existing:
        return {"ask": "Esa hora ya pasó, señor. ¿Para cuándo lo agendo?"}
    if allday and start.date() < today and not existing:
        return {"ask": "Esa fecha ya pasó, señor. ¿Para cuándo lo agendo?"}

    # título: lo que queda al quitar fecha, hora y muletillas
    chars = list(rest)
    for a_, b_ in spans:
        chars[a_:b_] = " " * (b_ - a_)
    title = "".join(chars)
    title = re.sub(r"\b(en|a|al)\s+(?:(mi|el|la)\s+)?(?:google\s+)?(calendario|calendar|agenda)\b", " ", title, flags=re.I)
    title = re.sub(r"\bque\s+(?:dure|durar[aá]|vaya|empiece|comience|parta|termine)\b", " ", title, flags=re.I)
    title = re.sub(r"^\s*(que\s+)?(tengo|tenemos|hay|debo|tengo que)\s+", " ", title, flags=re.I)
    # «anota como evento …»: el «como» también es de la orden (uso real: el título quedó «Como reunión con Chego…»)
    title = re.sub(r"\b(un|una|el|la)?\s*(evento|recordatorio)\b\s*(llamad[oa]\b|que se llame\b|con (el )?(nombre|t[ií]tulo)( de)?\b|titulad[oa]\b|para\b|de\b|:)?", " ", title, count=1, flags=re.I)
    title = re.sub(r"\b(llamad[oa]|que se llame|que sea( en)?|que diga|con (el )?(nombre|t[ií]tulo)( de)?|titulad[oa])\b", " ", title, flags=re.I)
    title = re.sub(r"\b(?:\w{2,4}\s+)?mism[oa]\b|\btambi[eé]n\b|\badem[aá]s\b", " ", title, flags=re.I)
    title = re.sub(r"^\s*(?:un|una)?\s*(?:cupo|bloque|espacio|hueco)\s+(?:para|de)\s+(?:(?:un|una)\s+)?", " ", title, flags=re.I)
    title = re.sub(r"[¿?¡!]", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    prev = None
    while prev != title:
        prev = title
        title = re.sub(r"^(un|una|el|la|los|las|que|de|del|para|a|y|al|en|ese|esa|desde|hasta|como)\s+", "", title, flags=re.I).strip(" ,.;:-")
        title = re.sub(r"\s+(el|la|a|de|para|por|y|en|con|del|al|desde|hasta|despu[eé]s de|a partir de)$", "", title, flags=re.I).strip(" ,.;:-")
    if not title or title.lower() in ("ese", "esa", "en", "el", "la", "del", "de", "desde", "hasta", "evento"):
        title = end_title or "Evento"
    title = title[:1].upper() + title[1:]
    return {"summary": title[:120], "start": start, "end": end, "allday": allday, "untitled": title == "Evento",
            "explicit_end": bool(end_t or dur or end_override), "explicit_date": explicit_date}


def say_when(ev: dict, now: datetime | None = None) -> str:
    now = now or (NOW() if NOW else datetime.now())

    def day_of(d: date) -> str:
        delta = (d - now.date()).days
        txt = "hoy" if delta == 0 else ("mañana" if delta == 1 else f"el {DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}")
        if delta in (0, 1):
            txt += f" {DIAS[d.weekday()]} {d.day}"
        return txt + (f" de {d.year}" if d.year != now.year else "")

    s, e = ev["start"], ev.get("end") or ev["start"]
    if ev["allday"]:
        if e.date() > s.date():
            return f"desde {day_of(s.date())} hasta {day_of(e.date())}, días completos"
        return f"{day_of(s.date())}, todo el día"
    if e.date() != s.date() and (e - s) > timedelta(hours=12):  # varios días
        return f"desde {day_of(s.date())} a las {s.hour}:{s.minute:02d} hasta {day_of(e.date())} a las {e.hour}:{e.minute:02d}"
    return f"{day_of(s.date())} de {s.hour}:{s.minute:02d} a {e.hour}:{e.minute:02d}"

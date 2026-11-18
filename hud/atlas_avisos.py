"""Contactos asociados a eventos y avisos cuando un evento se cancela o se mueve.

- La asociación se guarda en hud/eventos_contactos.json, por id de evento de Google Calendar (no se agregan como
  invitados en Google: eso les mandaría invitaciones). También cuentan los invitados de Google cuyo correo está
  en la libreta.
- Al borrar o mover un evento, Atlas ofrece avisarles. Cada aviso va por un canal: Discord, si no Telegram, si no
  correo. Siempre con confirmación en pantalla, mostrando a quién, por dónde y el texto exacto.
- Discord y Telegram usan las apps de escritorio del usuario (atlas_pc); el correo sale por SMTP con la cuenta del
  usuario que mejor calce con el destinatario.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import atlas_contactos as C

HERE = Path(__file__).resolve().parent
FILE = HERE / "eventos_contactos.json"
_LOCK = threading.Lock()
SEND = None  # las pruebas lo reemplazan: (canal, contacto, texto, asunto) -> (ok, detalle)


def _load() -> dict:
    try:
        return json.loads(Path(FILE).read_text(encoding="utf-8")).get("eventos") or {}
    except Exception:  # noqa: BLE001
        return {}


def _save(data: dict) -> None:
    Path(FILE).write_text(json.dumps({"eventos": data}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def link(event: dict, contacts: list[dict]) -> list[dict]:
    """Asocia contactos a un evento. -> todos los contactos asociados ahora."""
    with _LOCK:
        data = _load()
        e = data.setdefault(event["id"], {"titulo": event.get("summary", ""), "inicio": str(event.get("start", "")),
                                          "contactos": []})
        e["titulo"], e["inicio"] = event.get("summary", e["titulo"]), str(event.get("start", e["inicio"]))
        for c in contacts:
            if c["id"] not in e["contactos"]:
                e["contactos"].append(c["id"])
        _save(data)
    return linked(event)


def unlink(event: dict, contacts: list[dict]) -> list[dict]:
    with _LOCK:
        data = _load()
        e = data.get(event["id"])
        if e:
            e["contactos"] = [i for i in e["contactos"] if i not in {c["id"] for c in contacts}]
            if not e["contactos"]:
                data.pop(event["id"], None)
            _save(data)
    return linked(event)


def forget(event_id: str) -> None:
    with _LOCK:
        data = _load()
        if data.pop(event_id, None) is not None:
            _save(data)


def linked(event: dict) -> list[dict]:
    """Contactos del evento: los asociados a mano y los invitados de Google cuyo correo está en la libreta."""
    book = C.load()
    by_id = {c["id"]: c for c in book}
    out = [by_id[i] for i in (_load().get(event.get("id", "")) or {}).get("contactos", []) if i in by_id]
    mails = {str(a.get("email", "")).lower() for a in event.get("attendees") or [] if a.get("email")}
    for c in book:
        if c["correo"] and c["correo"].lower() in mails and c not in out:
            out.append(c)
    return out


def channel(c: dict) -> tuple[str, str] | None:
    """Por dónde avisarle: Discord, si no Telegram, si no correo."""
    if c.get("discord"):
        return "Discord", "@" + c["discord"]
    if c.get("telegram"):
        return "Telegram", "@" + c["telegram"]
    if c.get("correo"):
        return "correo", c["correo"]
    return None


def plan(event: dict, op: str, when: str, new_when: str = "") -> dict | None:
    """-> {"avisos": [...], "texto", "asunto", "sin_canal": [...], "resumen"} o None si no hay a quién avisar."""
    people = linked(event)
    if not people:
        return None
    title = event.get("summary", "el evento")
    if op == "move":
        texto = f"Hola, te aviso que «{title}» se cambió: era {when} y ahora es {new_when}."
        asunto = f"Cambio de horario: {title}"
    else:
        texto = f"Hola, te aviso que se canceló «{title}», que era {when}."
        asunto = f"Se canceló: {title}"
    avisos, sin = [], []
    for c in people:
        ch = channel(c)
        if ch:
            avisos.append({"id": c["id"], "nombre": c["nombre"], "canal": ch[0], "destino": ch[1]})
        else:
            sin.append(c["nombre"])
    if not avisos:
        return {"avisos": [], "texto": texto, "asunto": asunto, "sin_canal": sin, "resumen": ""}
    quien = "; ".join(f"{a['nombre']} por {a['canal']} ({a['destino']})" for a in avisos)
    resumen = f"Avisar a {quien} con el mensaje: «{texto}»"
    if sin:
        resumen += f". Sin forma de contacto: {', '.join(sin)}"
    return {"avisos": avisos, "texto": texto, "asunto": asunto, "sin_canal": sin, "resumen": resumen}


# ------------------------------------------------------------------ envío
def send_mail(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Correo desde la cuenta del usuario que mejor calce con el destinatario (mismo dominio; si no, la principal)."""
    import smtplib
    from email.message import EmailMessage

    from openjarvis.tools.gmail_mark_read import mail_accounts

    accts = []
    for _label, conn in mail_accounts():
        try:
            email_addr, password, imap_host = conn._resolve_connection()[:3]
        except Exception:  # noqa: BLE001
            continue
        if email_addr and password:
            accts.append((email_addr, password, imap_host or ""))
    if not accts:
        return False, "no tengo ninguna cuenta de correo configurada"
    dom = to.split("@")[-1].lower()
    pick = next((a for a in accts if a[0].split("@")[-1].lower() == dom), None) \
        or next((a for a in accts if dom.endswith(a[0].split("@")[-1].lower().split(".", 1)[-1])), None) or accts[0]
    email_addr, password, imap_host = pick
    host = imap_host.lower()
    smtp_host = ("smtp.gmail.com" if (not host or "gmail" in host or "google" in host)
                 else host.replace("imap.", "smtp.", 1) if host.startswith("imap.") else host)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = email_addr, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as s:
            s.login(email_addr, password)
            refused = s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return False, f"el servidor de correo respondió: {exc}"
    if refused:
        return False, f"el servidor rechazó {', '.join(refused)}"
    return True, f"el servidor de {email_addr} aceptó el correo"


def _send(pc, canal: str, c: dict, texto: str, asunto: str) -> tuple[bool, str]:
    if SEND is not None:
        return SEND(canal, c, texto, asunto)
    if canal == "correo":
        return send_mail(c["correo"], asunto, texto)
    if pc is None:
        return False, "no tengo acceso al PC"
    action = "discord_message" if canal == "Discord" else "telegram_message"
    res = pc.execute(action=action, name=c["nombre"], text=texto, confirm=True)
    return bool(res.success), str(res.content)


class AvisoTool:
    """Manda los avisos ya confirmados por el usuario y dice solo lo que se pudo comprobar."""

    class spec:  # noqa: N801
        name = "avisos"

    def __init__(self, pc) -> None:
        self.pc = pc

    def execute(self, **p):
        book = {c["id"]: c for c in C.load()}
        ok, bad = [], []
        for a in p.get("avisos") or []:
            c = book.get(a["id"])
            if c is None:
                bad.append(f"{a['nombre']}: ya no está en la libreta")
                continue
            try:
                good, detail = _send(self.pc, a["canal"], c, p["texto"], p.get("asunto", ""))
            except Exception as exc:  # noqa: BLE001
                good, detail = False, str(exc)
            (ok if good else bad).append(f"{a['nombre']} por {a['canal']}" if good else f"{a['nombre']} por {a['canal']}: {detail}")
        parts = []
        if ok:
            parts.append("Avisé a " + ", ".join(ok) + ".")
        if bad:
            parts.append("No pude confirmar el aviso a " + "; ".join(bad) + ".")
        return SimpleNamespace(success=bool(ok), metadata={}, content=" ".join(parts) or "No había a quién avisar.")


def find_contacts(who: str) -> tuple[list[dict], list[str]]:
    """«Tipo y Pipe», «Tipo, Pipe y Zander» -> (contactos encontrados, nombres que no calzan o calzan con varios)."""
    names = [n.strip() for n in re.split(r",|\s+y\s+|\s+e\s+", who) if n.strip()]
    found, missing = [], []
    for n in names:
        n = re.sub(r"^(?:a|al|el|la|mi amig[oa])\s+", "", n, flags=re.I)
        hit = C.find(n)
        if len(hit) == 1:
            if hit[0] not in found:
                found.append(hit[0])
        else:
            missing.append(n)
    return found, missing

"""Mensajes sin leer de las últimas 24 horas en Telegram (y WhatsApp), y de quién son. Solo lectura.

Telegram: la API de usuario (Telethon, la misma sesión que atlas_tg_api.py) lista los chats con su contador de no
leídos. No abre ni marca nada como leído (iter_dialogs solo lee la lista). Corre en un proceso aparte con tiempo máximo,
igual que los envíos, para no dejar nada cargado en el HUD.

Se cuentan chats de personas, grupos y canales, también los silenciados (van marcados «silenciado» y al final). Se
dejan fuera los bots (el bot de Atlas incluido) y el chat de servicio; los archivados solo se cuentan aparte.
«Últimas 24 horas» = el último mensaje del chat llegó hace menos de 24 horas.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

HUD_DIR = Path(__file__).resolve().parent
HOURS = 24


async def _telegram_async(hours: float, recent: bool = False) -> dict:
    """recent=False: solo chats con mensajes sin leer. recent=True: los chats con actividad en esas horas (hasta 8),
    cada uno con el texto de sus últimos mensajes (get_messages solo lee: no marca nada como leído)."""
    from datetime import datetime, timedelta, timezone

    from telethon import TelegramClient

    import atlas_tg_api as T

    conf = T.load_conf()
    if not conf or not T.sesion_existe():
        return {"ok": False, "msg": "Telegram no está vinculado."}
    client = TelegramClient(T.sesion(), int(conf["api_id"]), str(conf["api_hash"]),
                            receive_updates=False, device_model="Atlas (PC)", app_version="Atlas")
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "msg": "La sesión de Telegram no está vinculada."}
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        chats = []
        async for d in client.iter_dialogs(limit=200, archived=False):
            if not d.unread_count or (d.date and d.date < since):
                continue
            ent = d.entity
            canal = bool(d.is_channel and not d.is_group)  # canal de difusión (uso real: pidió incluirlos)
            if getattr(ent, "bot", False) or getattr(ent, "id", 0) == 777000:  # bots y el chat de servicio (códigos)
                continue
            try:
                muted = bool(d.dialog.notify_settings.mute_until and d.dialog.notify_settings.mute_until > datetime.now(timezone.utc))
            except Exception:  # noqa: BLE001
                muted = False
            # los silenciados se incluyen (uso real: todos sus grupos con mensajes eran silenciados y decía «no tiene»)
            item = {"nombre": d.name or "alguien", "n": int(d.unread_count), "grupo": bool(d.is_group),
                    "canal": canal, "silenciado": muted,
                    "usuario": getattr(ent, "username", "") or "", "telefono": getattr(ent, "phone", "") or "",
                    "hace_min": int((datetime.now(timezone.utc) - d.date).total_seconds() // 60) if d.date else None}
            if recent:
                msgs = []
                for m in reversed(await client.get_messages(d.entity, limit=min(int(d.unread_count), 30))):
                    txt = (m.message or "").strip() or ("[foto]" if m.photo else "[sticker]" if m.sticker else
                                                        "[audio]" if m.voice else "[archivo]" if m.document else "")
                    if not txt:
                        continue
                    who = "Usted" if m.out else (getattr(await m.get_sender(), "first_name", None) or d.name or "")
                    msgs.append(f"{who}: {txt[:300]}")
                item["mensajes"] = msgs
            chats.append(item)
        archived = 0
        try:  # archivados: solo cuántos tienen algo de las últimas 24 horas (no se leen)
            async for d in client.iter_dialogs(limit=100, archived=True):
                if d.unread_count and d.date and d.date >= since and not getattr(d.entity, "bot", False):
                    archived += 1
        except Exception:  # noqa: BLE001
            pass
        chats.sort(key=lambda c: (bool(c.get("silenciado")), -c["n"]))
        return {"ok": True, "chats": chats, "archivados": archived}
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


_WA_TIME = r"^(?:\d{1,2}:\d{2}|ayer|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})$"


def _wa_rows(recent: bool = False) -> dict:
    """En el proceso aparte: WhatsApp fuera de la pantalla (como al enviar), lee la lista de chats y lo devuelve como
    estaba. No hace clic ni abre chats: solo lee las filas («Nombre», «19:46», «4 mensajes no leídos», …)."""
    import ctypes
    import re

    import uiautomation as auto
    from openjarvis.tools import atlas_pc as P

    u = ctypes.windll.user32
    h = u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp")
    if not h:
        return {"ok": False, "msg": "WhatsApp de escritorio no está abierto."}
    prev = u.GetForegroundWindow()
    saved = P._wa_park(h)
    chats, muted, seen = [], 0, set()
    try:
        time.sleep(1.2)
        w = auto.ControlFromHandle(h)
        end = time.time() + 15
        for c, d in auto.WalkControl(w, maxDepth=30):
            if time.time() > end:
                break
            try:
                if c.ControlTypeName != "DataItemControl" or c.GetParentControl().ControlTypeName == "DataItemControl":
                    continue
                full = c.Name or ""
            except Exception:  # noqa: BLE001
                continue
            m = re.search(r"(\d+)\s+mensajes?\s+no\s+le[ií]dos?", full, re.I)
            if not m or full in seen:
                continue
            n = int(m[1]) if m else 0
            seen.add(full)
            texts = [(k.Name or "").strip() for k, _ in auto.WalkControl(c, maxDepth=6)
                     if k.ControlTypeName == "TextControl" and (k.Name or "").strip()]
            when = next((t for t in texts if re.match(_WA_TIME, t, re.I)), "")
            name = next((t for t in texts if not re.match(_WA_TIME, t, re.I) and not re.search(r"no\s+le[ií]d", t, re.I)
                         and t not in ("(Tú)",)), "alguien")
            group = bool(re.search(r"(?:^|\s)~[^:]{1,40}:\s", full)) or any(t == ":" for t in texts)
            if "(Tú)" in texts:  # el chat con uno mismo
                continue
            if (name, n, when) in seen:  # la lista aparece dos veces en el árbol
                continue
            seen.add((name, n, when))
            if recent and not re.match(r"^(?:\d{1,2}:\d{2}|ayer)$", when, re.I):
                continue
            if re.search(r"chat silenciado", full, re.I):  # se cuentan aparte (solo los de hoy y ayer)
                muted += bool(n and re.match(r"^(?:\d{1,2}:\d{2}|ayer)$", when, re.I))
                continue
            item = {"nombre": name, "n": n, "grupo": group, "cuando": when}
            if recent:  # lo que sigue a la hora: «~Seba», «:», «texto del último mensaje» (sin el contador)
                after = texts[texts.index(when) + 1:] if when in texts else texts[1:]
                after = [t for t in after if not re.search(r"no\s+le[ií]d", t, re.I)]
                item["ultimo"] = re.sub(r"\s*:\s+", ": ", " ".join(after)).strip()[:300]
                if len(chats) >= 10:
                    break
            chats.append(item)
    finally:
        P._give_back_focus(prev)
        P._wa_unpark(u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp") or h, saved)
        P._give_back_focus(prev)
    return {"ok": True, "chats": chats, "silenciados": muted}


_DATE_SEP = (r"^(?:hoy|ayer|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
             r"\d{1,2} de \w+(?: de \d{4})?)$")


_TIME = r"\d{1,2}:\d{2}(?:\s*[ap]\.?\s*m\.?)?"
_PHONE = r"\+?\d[\d\s()-]{7,}"
_NOISE = {"~", "Editado", ",", "…", ".", "Haz clic para volver a llamar.", "Reenviar archivo multimedia", "Leer más"}


def parse_chat(seq: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], int | None]:
    """Del panel de mensajes de WhatsApp (en orden: ("label"|"text"|"button"|"group"|"image", nombre)) saca los mensajes
    [(quién, texto)] y dónde empiezan los no leídos (el aviso «N mensajes no leídos»), o None.

    Cómo viene (visto el 15-11-2026, WhatsApp 2.2644): en un chat de persona, cada mensaje va bajo una etiqueta vacía
    «Venjo:» / «Tú:»; en un grupo, el que escribe aparece como botón «Quizá Dario» (o con su nombre) seguido de «~»,
    «Dario» y su número. El texto puede venir en varios trozos (cortado por emojis o enlaces) y termina con la hora.
    Varios mensajes seguidos de la misma persona van sin repetir quién. Un mensaje citado («Mensaje citado») trae el
    nombre y el texto del original: eso no cambia quién escribe ni se cuenta como mensaje."""
    import re

    msgs: list[tuple[str, str]] = []
    sender, parts, start, quote = "", [], None, False
    k = 0
    while k < len(seq):
        kind, v = seq[k][0], seq[k][1].strip()
        k += 1
        if not v:
            continue
        if kind == "label" and v.endswith(":"):
            sender, parts, quote = v[:-1].strip().lstrip("~").strip(), [], False
            continue
        if re.fullmatch(r"\d+\s+mensajes?\s+no\s+le[ií]dos?", v, re.I):
            start, parts = len(msgs), []
            continue
        if kind == "button" and v == "Mensaje citado":
            quote = True
            continue
        if kind in ("button", "group"):
            name = re.sub(r"^Quiz[aá]\s+", "", v).strip()
            nxt = [x[1].strip() for x in seq[k:k + 3]]
            is_person = v.startswith(("Quizá ", "Quiza ")) or (nxt and (nxt[0] == "~" or nxt[0] == v))
            if is_person and len(name) <= 40 and not v.startswith("Abrir los detalles"):
                if not quote:
                    sender, parts = name.lstrip("~").strip(), []
                k += sum(1 for x in nxt if x in ("~", name) or re.fullmatch(_PHONE, x))  # «~», «Dario», «+56 9 …»
                continue
            if quote:  # el botón con el texto citado cierra la cita
                quote = False
                continue
            if re.search(r"sticker", v, re.I):
                parts.append("[sticker]")
            continue
        if kind != "text" or v in _NOISE or re.match(_DATE_SEP, v, re.I) or re.fullmatch(_PHONE, v):
            continue
        if re.fullmatch(_TIME, v, re.I):
            if parts and sender:
                msgs.append((sender, " ".join(parts)[:400]))
            parts = []
            continue
        if sender:
            parts.append(v)
    return msgs, start


def chat_messages(seq: list[tuple[str, str]], n: int) -> list[str]:
    """Los mensajes sin leer de otros: lo que viene tras «N mensajes no leídos»; si no está ese aviso, los últimos n."""
    msgs, start = parse_chat(seq)
    if start is not None:
        msgs = msgs[start:]
    theirs = [f"{a}: {b}" for a, b in msgs if a not in ("Tú", "You")]
    return theirs if start is not None else theirs[-n:]


def recent_messages(seq: list[tuple[str, str]], n: int) -> list[str]:
    """Los últimos n mensajes del chat abierto, de todos (los del usuario como «Usted: …»)."""
    msgs, _ = parse_chat(seq)
    return [f"{'Usted' if a in ('Tú', 'You') else a}: {b}" for a, b in msgs][-n:]


def _chat_seq(auto, doc) -> list[tuple[str, str]]:
    """La secuencia del panel de mensajes para parse_chat."""
    kinds = {"GroupControl": "group", "TextControl": "text", "ButtonControl": "button", "ImageControl": "image"}
    seq = []
    for c, _ in auto.WalkControl(doc, maxDepth=40):
        try:
            typ, val = c.ControlTypeName, (c.Name or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if typ not in kinds or not val:
            continue
        seq.append(("label" if typ == "GroupControl" and val.endswith(":") else kinds[typ], val))
    return seq


def _wa_read_named(words: list[str], limit: int = 40) -> dict:
    """En el proceso aparte: busca el chat por nombre en el buscador de WhatsApp (se escribe con UI Automation, sin
    teclado), abre el más reciente que calce (clic enviado a la ventana, sin mover el mouse), lee sus últimos mensajes
    y borra la búsqueda. Uso real: «qué han hablado en el grupo de la IEEE en WhatsApp». Abrirlo lo deja leído."""
    import re

    import uiautomation as auto
    from openjarvis.tools import atlas_pc as P

    u = ctypes.windll.user32
    h = u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp")
    if not h:
        return {"ok": False, "msg": "WhatsApp de escritorio no está abierto."}
    web = _wa_web(u, h)
    prev = u.GetForegroundWindow()
    saved = P._wa_park(h)
    sb = None
    try:
        time.sleep(1.2)
        w = auto.ControlFromHandle(h)
        sb = next((c for c, _ in auto.WalkControl(w, maxDepth=30) if c.ControlTypeName == "EditControl"
                   and re.search(r"buscar|search", c.Name or "", re.I)), None)
        if sb is None or not web:
            return {"ok": False, "msg": "No encontré el buscador de WhatsApp."}
        sb.GetValuePattern().SetValue(words[0])
        time.sleep(2.0)
        rows = []
        for c, _ in auto.WalkControl(w, maxDepth=30):
            try:
                if c.ControlTypeName != "DataItemControl" or c.GetParentControl().ControlTypeName == "DataItemControl":
                    continue
                name = c.Name or ""
            except Exception:  # noqa: BLE001
                continue
            plain = _plain_txt(name)
            if all(wd in plain for wd in words) and re.search(r"\d{1,2}:\d{2}|ayer|lunes|martes|mi[eé]rcoles|jueves|"
                                                             r"viernes|s[aá]bado|domingo|\d{1,2}/\d{1,2}", name, re.I):
                rows.append(c)
        if not rows:
            return {"ok": True, "found": False}
        texts = [(k.Name or "").strip() for k, _ in auto.WalkControl(rows[0], maxDepth=6)
                 if k.ControlTypeName == "TextControl" and (k.Name or "").strip()]
        title = next((x for x in texts if not re.match(_WA_TIME, x, re.I) and not re.search(r"no\s+le[ií]d", x, re.I)), "")
        others = []
        for r in rows[1:6]:
            tx = [(k.Name or "").strip() for k, _ in auto.WalkControl(r, maxDepth=6)
                  if k.ControlTypeName == "TextControl" and (k.Name or "").strip()]
            others.append(next((x for x in tx if not re.match(_WA_TIME, x, re.I)), ""))
        def box_name():
            try:
                b = P._wa_box(auto, P._wa_doc(auto, w))
                return (b.Name or "") if b else ""
            except Exception:  # noqa: BLE001
                return ""

        before = box_name()
        _post_click(u, web, rows[0])
        opened = ""
        for _ in range(12):
            time.sleep(0.4)
            nm = box_name()
            if nm and nm != before:
                opened = nm
                break
        if not opened and before and (title and title.lower() in before.lower()
                                      or all(wd in _plain_txt(before) for wd in words)):
            opened = before  # ya estaba abierto
        if not opened:
            return {"ok": False, "msg": f"No pude abrir el chat {title or words[0]}."}
        time.sleep(1.0)
        seq = _chat_seq(auto, P._wa_doc(auto, w))
        return {"ok": True, "found": True, "nombre": title or words[0], "mensajes": recent_messages(seq, limit),
                "otros": [o for o in others if o and o != title]}
    finally:
        try:
            if sb is not None:
                sb.GetValuePattern().SetValue("")
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
        P._give_back_focus(prev)
        P._wa_unpark(u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp") or h, saved)
        P._give_back_focus(prev)


def _plain_txt(x: str) -> str:
    import unicodedata

    x = unicodedata.normalize("NFKD", (x or "").lower())
    return "".join(ch for ch in x if not unicodedata.combining(ch))


async def _telegram_named(words: list[str], limit: int = 40) -> dict:
    """El chat de Telegram cuyo nombre calza con esas palabras (el más reciente) y sus últimos mensajes. Solo lee."""
    from telethon import TelegramClient

    import atlas_tg_api as T

    conf = T.load_conf()
    if not conf or not T.sesion_existe():
        return {"ok": False, "msg": "Telegram no está vinculado."}
    client = TelegramClient(T.sesion(), int(conf["api_id"]), str(conf["api_hash"]),
                            receive_updates=False, device_model="Atlas (PC)", app_version="Atlas")
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "msg": "La sesión de Telegram no está vinculada."}
        hits = []
        async for d in client.iter_dialogs(limit=300):
            if getattr(d.entity, "id", 0) == 777000:
                continue
            if all(wd in _plain_txt(d.name or "") for wd in words):
                hits.append(d)
        if not hits:
            return {"ok": True, "found": False}
        d = hits[0]
        msgs = []
        for m in reversed(await client.get_messages(d.entity, limit=limit)):
            txt = (m.message or "").strip() or ("[foto]" if m.photo else "[sticker]" if m.sticker else
                                                "[audio]" if m.voice else "[archivo]" if m.document else "")
            if not txt:
                continue
            who = "Usted" if m.out else (getattr(await m.get_sender(), "first_name", None) or d.name or "")
            msgs.append(f"{who}: {txt[:300]}")
        return {"ok": True, "found": True, "nombre": d.name, "grupo": bool(d.is_group), "n": int(d.unread_count),
                "mensajes": msgs, "otros": [x.name for x in hits[1:6]]}
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _wa_web(u, h) -> int:
    """La ventana hija «Chrome_WidgetWin_0» de WhatsApp: ahí los clics enviados (PostMessage) llegan sin mover el mouse."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(c, _l):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(c, cls, 64)
        if cls.value == "Chrome_WidgetWin_0":
            found.append(c)
        return True

    u.EnumChildWindows(h, cb, 0)
    return found[0] if found else 0


def _post_click(u, web: int, ctrl) -> None:
    import ctypes.wintypes as wt

    r = ctrl.BoundingRectangle
    pt = wt.POINT((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    u.ScreenToClient(web, ctypes.byref(pt))
    lp = (pt.y << 16) | (pt.x & 0xFFFF)
    for m, wp in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):  # mover, apretar, soltar
        u.PostMessageW(web, m, wp, lp)


def _wa_read_unread(targets: list[dict]) -> dict:
    """En el proceso aparte: WhatsApp fuera de la pantalla, pestaña «No leídos» (así esos chats quedan arriba, donde se
    pueden presionar), abre cada chat pedido con un clic enviado a la ventana (sin mover el mouse ni usar el teclado),
    lee sus mensajes sin leer y vuelve a la pestaña «Todos». Abrirlos los deja leídos (el usuario lo pidió: «de tener
    50 mensajes en un grupo, me los hubiera resumido»). No escribe nada."""
    import re

    import uiautomation as auto
    from openjarvis.tools import atlas_pc as P

    u = ctypes.windll.user32
    h = u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp")
    if not h:
        return {"ok": False, "msg": "WhatsApp de escritorio no está abierto."}
    web = _wa_web(u, h)
    if not web:
        return {"ok": False, "msg": "No encontré la ventana de WhatsApp."}
    prev = u.GetForegroundWindow()
    saved = P._wa_park(h)
    out: dict = {}
    w = None

    def tabs():
        return {(c.Name or "").split(" ")[0].lower(): c for c, _ in auto.WalkControl(w, maxDepth=25)
                if c.ControlTypeName == "TabItemControl"}

    def box_name() -> str:
        try:
            b = P._wa_box(auto, P._wa_doc(auto, w))
            return (b.Name or "") if b else ""
        except Exception:  # noqa: BLE001
            return ""

    try:
        time.sleep(1.2)
        w = auto.ControlFromHandle(h)
        t = tabs()
        if "no" in t:
            _post_click(u, web, t["no"])
            time.sleep(1.5)
        for tg in targets:
            name = tg["nombre"]
            row = None
            for c, _ in auto.WalkControl(w, maxDepth=30):
                try:
                    if (c.ControlTypeName == "DataItemControl" and c.GetParentControl().ControlTypeName != "DataItemControl"
                            and name in (c.Name or "") and re.search(r"no\s+le[ií]d", c.Name or "", re.I)):
                        row = c
                        break
                except Exception:  # noqa: BLE001
                    continue
            if row is None:
                out[name] = {"ok": False, "msg": "no encontré la fila"}
                continue
            before = box_name()
            _post_click(u, web, row)
            changed = ""
            for _ in range(12):
                time.sleep(0.4)
                nm = box_name()
                if nm and nm != before:
                    changed = nm
                    break
            if not changed:
                out[name] = {"ok": False, "msg": "no se abrió el chat"}
                continue
            time.sleep(1.0)
            seq = _chat_seq(auto, P._wa_doc(auto, w))
            out[name] = {"ok": True, "chat": changed, "mensajes": chat_messages(seq, int(tg.get("n") or 1))[-80:]}
    finally:
        try:
            t = tabs() if w is not None else {}
            if "todos" in t:
                _post_click(u, web, t["todos"])
                time.sleep(0.8)
        except Exception:  # noqa: BLE001
            pass
        P._give_back_focus(prev)
        P._wa_unpark(u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp") or h, saved)
        P._give_back_focus(prev)
    return {"ok": True, "chats": out}


def _wa_read_chat(num: str, n: int) -> dict:
    """En el proceso aparte: abre el chat de ese número (enlace whatsapp://send, fuera de la pantalla, sin texto) y lee
    los últimos n mensajes que NO son del usuario. Abrirlo los marca como leídos en WhatsApp (el usuario lo pidió:
    «si son muchos, que Atlas acceda al chat para hacer un resumen»). No escribe nada."""
    import ctypes

    import uiautomation as auto
    from openjarvis.tools import atlas_pc as P

    u = ctypes.windll.user32
    h = u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp")
    if not h:
        return {"ok": False, "msg": "WhatsApp de escritorio no está abierto."}
    prev = u.GetForegroundWindow()
    saved = P._wa_park(h)
    dbg: list[str] = []
    try:
        w, doc, box = P._wa_open(auto, f"whatsapp://send?phone={num}")
        if box is None:
            return {"ok": False, "msg": "WhatsApp no abrió ese chat."}
        shown = P._wa_check_number(auto, doc, num, dbg)
        time.sleep(0.8)
        theirs = []
        for c in P._wa_all(auto, doc, budget=6.0):
            if P._cname(c) != "GroupControl":
                continue
            name = P._dc_name(c).strip()
            if not name.endswith(":") or name in ("Tú:", "You:"):
                continue
            try:
                txt = P._wa_msg_text(auto, c)
            except Exception:  # noqa: BLE001
                txt = ""
            theirs.append(f"{name[:-1]}: {txt[:300] or '[sin texto]'}")
        return {"ok": True, "disp": shown, "mensajes": theirs[-n:]}
    finally:
        P._give_back_focus(prev)
        P._wa_unpark(u.FindWindowW("WinUIDesktopWin32WindowClass", "WhatsApp") or h, saved)
        P._give_back_focus(prev)


def _child(kind: str, out: str, *args: str) -> None:
    import asyncio

    try:
        if kind == "whatsapp_chat":
            r = _wa_read_chat(args[0], int(args[1]))
        elif kind == "whatsapp_unread":
            r = _wa_read_unread(json.loads(args[0]))
        elif kind == "whatsapp_named":
            r = _wa_read_named(json.loads(args[0]))
        elif kind == "telegram_named":
            r = asyncio.run(_telegram_named(json.loads(args[0])))
        elif kind.startswith("telegram"):
            r = asyncio.run(_telegram_async(HOURS, recent=kind.endswith("_recent")))
        else:
            r = _wa_rows(recent=kind.endswith("_recent"))
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "msg": f"{'Telegram' if kind.startswith('telegram') else 'WhatsApp'} no respondió ({type(exc).__name__})."}
    Path(out).write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")


def _run(kind: str, timeout: float, *args: str) -> dict:
    """Corre la lectura en un proceso aparte (sin ventana) y devuelve su resultado."""
    import atlas_tg_api as T

    label = "Telegram" if kind.startswith("telegram") else "WhatsApp"
    out = Path(tempfile.gettempdir()) / f"atlas_sinleer_{kind}_{os.getpid()}_{int(time.time() * 1000)}.json"
    code = "import sys; import atlas_sin_leer as S; S._child(sys.argv[1], sys.argv[2], *sys.argv[3:])"
    src = HUD_DIR.parent / "src" / "src"  # openjarvis (para WhatsApp: atlas_pc._wa_park)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(HUD_DIR), str(src), os.environ.get("PYTHONPATH", "")]),
           "PYTHONIOENCODING": "utf-8"}
    try:
        cp = subprocess.run([T._python(), "-c", code, kind, str(out), *args], env=env, timeout=timeout,
                            capture_output=True, cwd=str(HUD_DIR), creationflags=0x08000000)
        if out.exists():
            return json.loads(out.read_text(encoding="utf-8"))
        return {"ok": False, "msg": f"No pude revisar {label}.", "err": cp.stderr.decode("utf-8", "replace")[-600:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": f"{label} tardó demasiado en responder."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "msg": f"No pude revisar {label} ({type(exc).__name__})."}
    finally:
        try:
            out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def telegram(timeout: float = 30.0, recent: bool = False) -> dict:
    """-> {"ok", "chats": [{"nombre", "n", "grupo", "usuario", "telefono", "hace_min"(, "mensajes")}]} o {"ok": False, "msg"}."""
    return _run("telegram_recent" if recent else "telegram", timeout)


def whatsapp(timeout: float = 40.0, recent: bool = False) -> dict:
    """-> {"ok", "chats": [{"nombre", "n", "grupo", "cuando"}], "silenciados"}. Solo chats de hoy («19:46») y de ayer
    («Ayer»): WhatsApp no muestra la hora exacta de los de ayer, así que esos se dicen aparte."""
    import re

    r = _run("whatsapp_recent" if recent else "whatsapp", timeout)
    if r.get("ok"):
        r["chats"] = [c for c in r.get("chats") or [] if re.match(r"^(?:\d{1,2}:\d{2}|ayer)$", c.get("cuando", ""), re.I)]
    if recent and r.get("ok"):
        _open_many(r["chats"])
    return r


MANY = 2      # con 2 o más sin leer, la vista previa (solo el último) no alcanza: se abre el chat
MAX_OPEN = 3  # cada chat abierto tarda ~7 s


def _open_many(chats: list[dict]) -> None:
    """Para los chats con varios mensajes sin leer (grupos incluidos): los abre desde la pestaña «No leídos» y trae
    esos mensajes; si no se pudo y es una persona, lo intenta por su número. Quedan leídos en WhatsApp (el usuario lo
    pidió). Los que no se pudieron abrir se quedan con la vista previa («solo_ultimo»)."""
    import re

    try:
        import atlas_contactos as C
        from openjarvis.tools import atlas_pc as P
    except Exception:  # noqa: BLE001
        return
    many = [c for c in sorted(chats, key=lambda c: -c.get("n", 0)) if c.get("n", 0) >= MANY]
    if not many:
        return
    pick, rest = many[:MAX_OPEN], many[MAX_OPEN:]
    for c in rest:
        c["solo_ultimo"] = True
    got = whatsapp_unread([{"nombre": c["nombre"], "n": c["n"]} for c in pick]).get("chats") or {}
    for c in pick:
        g = got.get(c["nombre"]) or {}
        if g.get("ok") and g.get("mensajes"):
            c["mensajes"], c["abierto"] = g["mensajes"], True
            continue
        num = ""  # respaldo para personas: abrir por número
        if not c.get("grupo"):
            digits = re.sub(r"\D", "", c["nombre"])
            if len(digits) >= 8 and re.fullmatch(r"[+\d\s()-]+", c["nombre"]):
                num = digits
            else:
                hit = C.find(c["nombre"])
                if len(hit) == 1:
                    num = P.wa_number(hit[0].get("telefono") or "")
        r2 = whatsapp_chat(num, int(c["n"])) if num else {}
        if r2.get("ok") and r2.get("mensajes"):
            c["mensajes"], c["abierto"] = r2["mensajes"], True
        else:
            c["solo_ultimo"] = True


def named(app: str, words: list[str], timeout: float = 60.0) -> dict:
    """Los últimos mensajes del chat de esa app cuyo nombre calza con las palabras (ya sin tildes, en minúscula).
    -> {"ok", "found", "nombre", "mensajes", "otros"}. En WhatsApp abre el chat (queda leído); en Telegram solo lee."""
    return _run(f"{app}_named", timeout, json.dumps(words, ensure_ascii=False))


def whatsapp_unread(targets: list[dict], timeout: float = 90.0) -> dict:
    """Abre esos chats (los que tienen mensajes sin leer) y trae sus mensajes sin leer. Quedan leídos en WhatsApp."""
    return _run("whatsapp_unread", timeout, json.dumps(targets, ensure_ascii=False))


def whatsapp_chat(num: str, n: int, timeout: float = 45.0) -> dict:
    """Los últimos n mensajes recibidos en el chat de ese número (lo abre: quedan leídos). -> {"ok", "mensajes"}."""
    return _run("whatsapp_chat", timeout, num, str(n))


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary(app: str, r: dict, contact_name=None) -> str:
    """Una frase: «En Telegram tiene 3 mensajes sin leer: 2 de Antonio y 1 del grupo Redes.»"""
    label = {"telegram": "Telegram", "whatsapp": "WhatsApp"}[app]
    if not r.get("ok"):
        return f"No pude revisar {label}: {r.get('msg', 'no respondió')}"
    chats = r.get("chats") or []
    muted = int(r.get("silenciados") or 0)
    note = (f" Aparte, hay {_plural(muted, 'chat silenciado', 'chats silenciados')} con mensajes."
            if muted else "")
    arch = int(r.get("archivados") or 0)
    if arch:
        note += f" Además, {_plural(arch, 'chat archivado tiene', 'chats archivados tienen')} mensajes de hoy."
    if not chats:
        return f"En {label} no tiene mensajes sin leer de las últimas 24 horas.{note}"
    total = sum(c["n"] for c in chats)

    def big(n: int) -> str:  # un grupo real tenía 378.425 sin leer: no se lee la cifra entera
        return "más de mil" if n >= 1000 else str(n)

    def count(n: int) -> str:
        return "más de mil mensajes sin leer" if n >= 1000 else _plural(n, "mensaje sin leer", "mensajes sin leer")

    parts, whos = [], []
    for c in sorted(chats, key=lambda c: (bool(c.get("silenciado")), -c["n"]))[:6]:
        name = (contact_name(c) if contact_name else None) or c["nombre"]
        ayer = " (de ayer)" if str(c.get("cuando", "")).lower() == "ayer" else ""
        mute = " (silenciado)" if c.get("silenciado") else ""
        kind = "del canal " if c.get("canal") else "del grupo " if c.get("grupo") else "de "
        whos.append(f"{kind}{name}{mute}{ayer}")
        parts.append(f"{big(c['n'])} {whos[-1]}")
    if len(chats) == 1:  # «tiene 2 mensajes sin leer de Antonio»
        return f"En {label} tiene {count(total)} {whos[0]}.{note}"
    more = len(chats) - len(parts)
    tail = f" y {_plural(more, 'chat más', 'chats más')}" if more > 0 else ""
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" y {parts[-1]}"
    return f"En {label} tiene {count(total)}: {joined}{tail}.{note}"

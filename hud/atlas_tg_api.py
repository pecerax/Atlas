"""Telegram oculto por la vía oficial: la API de usuario de Telegram (MTProto) con la librería Telethon.

Sin ventanas ni navegador: Atlas envía como el propio usuario, con un api_id/api_hash que el usuario crea en
my.telegram.org (Telegram lo permite para clientes de usuario). La sesión se vincula UNA vez con
vincular_telegram_api.py (Vincular-Telegram.cmd), donde el usuario escribe el código que le llega; nunca por el chat.

Cada envío corre en un proceso aparte que se cierra al terminar (no queda nada cargado en el HUD, ni procesos
colgados: el proceso tiene un tiempo máximo y se mata si se pasa).

send() devuelve {"ok", "msg", "fallback"}: fallback=True solo si es SEGURO que no se envió nada (sin vincular, sin
conexión, destinatario no encontrado o no calza), y entonces Atlas puede usar la app de escritorio. Si el envío se
intentó y no se pudo comprobar, fallback=False para no mandar el mensaje dos veces.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HUD_DIR = Path(__file__).resolve().parent
CONN_DIR = Path.home() / ".atlas" / "connectors"
CONF = CONN_DIR / "telegram_usuario.json"          # {"api_id": 123, "api_hash": "…", "telefono": "+569…"}
SESSION = CONN_DIR / "telegram_usuario"             # Telethon agrega .session (formato antiguo, en texto plano)
TIMEOUT = 45.0


def _secretos():
    from openjarvis.security import atlas_secretos

    return atlas_secretos


def sesion():
    """La sesión de Telethon: cifrada en el Administrador de credenciales si ya se migró; si no, el archivo."""
    S = _secretos()
    if CONN_DIR == S.CONN:  # las pruebas cambian CONN_DIR y nunca deben tocar la sesión real
        try:
            s = S.leer(S.TELEGRAM_SESION)
        except OSError:
            s = None
        if s:
            from telethon.sessions import StringSession

            return StringSession(s)
    return str(SESSION)


def sesion_existe() -> bool:
    S = _secretos()
    return SESSION.with_suffix(".session").exists() or (CONN_DIR == S.CONN and S.existe(S.TELEGRAM_SESION))


def _digits(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))


def load_conf() -> dict:
    try:
        d = _secretos().cargar_json(CONF) or {}
        if int(d.get("api_id") or 0) and str(d.get("api_hash") or "").strip():
            return d
    except Exception:  # noqa: BLE001
        pass
    return {}


def configured() -> bool:
    """Hay api_id guardado y una sesión vinculada (no comprueba la red)."""
    return bool(load_conf()) and sesion_existe()


def display_name(user) -> str:
    name = " ".join(x for x in (getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or "") if x).strip()
    return name or ("@" + user.username if getattr(user, "username", None) else "ese contacto")


def check_match(dest: str, user, by_phone_lookup: bool = False) -> str:
    """'' si el usuario de Telegram encontrado es exactamente el destinatario de la libreta; si no, el problema."""
    if user is None:
        return "no encontrado"
    if getattr(user, "deleted", False):
        return "la cuenta está eliminada"
    if dest.startswith("@"):
        want = dest[1:].lower()
        names = {(getattr(user, "username", None) or "").lower()}
        for u in getattr(user, "usernames", None) or []:
            names.add((getattr(u, "username", "") or "").lower())
        return "" if want in names else "el usuario no calza"
    want = _digits(dest)
    have = _digits(getattr(user, "phone", "") or "")
    if have:
        return "" if have == want else "el teléfono no calza"
    # Telegram oculta el teléfono por privacidad: vale solo si lo encontramos buscando exactamente ese número
    return "" if by_phone_lookup else "no se pudo comprobar el teléfono"


GROUP = object()  # _resolve: el @ es de un grupo o canal


async def _resolve(client, dest: str):
    """-> (user, encontrado_por_telefono). Nunca busca por nombre: solo usuario @ o teléfono de la libreta."""
    from telethon import functions, types

    if dest.startswith("@"):
        try:
            ent = await client.get_entity(dest)
        except Exception:  # noqa: BLE001
            return None, False
        if not isinstance(ent, types.User):  # grupo o canal público con ese @: nunca se le escribe (regla del usuario)
            return GROUP, False
        return ent, False
    phone = _digits(dest)
    try:
        res = await client(functions.contacts.ResolvePhoneRequest(phone=phone))
        users = [u for u in res.users if isinstance(u, types.User)]
        if users:
            return users[0], True
    except Exception:  # noqa: BLE001
        pass
    try:  # respaldo: los contactos guardados del usuario en Telegram
        res = await client(functions.contacts.GetContactsRequest(hash=0))
        for u in getattr(res, "users", []) or []:
            if _digits(getattr(u, "phone", "") or "") == phone:
                return u, True
    except Exception:  # noqa: BLE001
        pass
    return None, False


async def _send_async(dest: str, text: str, dbg: list[str]) -> dict:
    from telethon import TelegramClient

    conf = load_conf()
    if not conf:
        return {"ok": False, "fallback": True, "msg": "Telegram oculto no está configurado."}
    client = TelegramClient(sesion(), int(conf["api_id"]), str(conf["api_hash"]),
                            receive_updates=False, device_model="Atlas (PC)", app_version="Atlas")
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"ok": False, "fallback": True, "msg": "La sesión de Telegram oculto no está vinculada."}
        user, by_phone = await _resolve(client, dest)
        if user is GROUP:  # sin respaldo por la app de escritorio: ahí se abriría el grupo
            dbg.append(f"destino {dest!r}: es un grupo o canal, no se envía")
            return {"ok": False, "fallback": False,
                    "msg": f"{dest} es un grupo o canal de Telegram, y no envío mensajes a grupos. No envié nada."}
        problem = check_match(dest, user, by_phone)
        dbg.append(f"destino {dest!r}: {'OK' if not problem else problem}"
                   + (f" ({display_name(user)}, id {user.id})" if user is not None else ""))
        if problem:
            return {"ok": False, "fallback": True, "msg": f"No encontré a {dest} en Telegram ({problem}); no envié nada."}
        if getattr(user, "is_self", False):
            return {"ok": False, "fallback": False, "msg": "Ese contacto es su propia cuenta de Telegram; no envié nada."}
        who = display_name(user)
        dbg.append("ENVIANDO")
        try:
            m = await client.send_message(user, text, link_preview=False)
        except Exception as exc:  # noqa: BLE001
            dbg.append(f"error al enviar: {type(exc).__name__}: {exc}")
            return {"ok": False, "fallback": False,
                    "msg": f"Telegram no aceptó el mensaje para {who}. Revise el chat en Telegram antes de reintentar."}
        if getattr(m, "id", None) and (getattr(m, "message", "") or "").strip() == text.strip():
            dbg.append(f"verificado: mensaje id {m.id}")
            return {"ok": True, "fallback": False, "msg": f"Enviado por Telegram a {who}.", "disp": who}
        return {"ok": False, "fallback": False,
                "msg": f"Envié el mensaje a {who}, pero no pude comprobarlo. Revíselo en Telegram."}
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _child(dest: str, text: str, out: str) -> None:
    """Punto de entrada del proceso aparte."""
    import asyncio

    dbg: list[str] = []
    try:
        r = asyncio.run(_send_async(dest, text, dbg))
    except Exception as exc:  # noqa: BLE001
        dbg.append(f"EXCEPCION: {type(exc).__name__}: {exc}")
        sent = "ENVIANDO" in dbg
        r = {"ok": False, "fallback": not sent,
             "msg": ("Telegram no respondió después de enviar; revise el chat antes de reintentar." if sent
                     else "No pude conectarme a Telegram; no envié nada.")}
    Path(out).write_text(json.dumps({"r": r, "dbg": dbg}, ensure_ascii=False), encoding="utf-8")


def _python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() in ("pythonw.exe", "atlas.exe") and (exe.parent / "python.exe").exists():   # Atlas.exe = pythonw
        exe = exe.parent / "python.exe"
    return str(exe)


def send(dest: str, text: str, dbg: list[str] | None = None) -> dict:
    """Envía en un proceso aparte, sin ventana. dest = '@usuario' o '+569…' (de la libreta)."""
    dbg = dbg if dbg is not None else []
    out = Path(tempfile.gettempdir()) / f"atlas_tgapi_{os.getpid()}_{int(time.time() * 1000)}.json"
    code = "import sys; import atlas_tg_api as T; T._child(sys.argv[1], sys.argv[2], sys.argv[3])"
    env = {**os.environ, "PYTHONPATH": str(HUD_DIR) + os.pathsep + os.environ.get("PYTHONPATH", ""),
           "PYTHONIOENCODING": "utf-8"}
    r = None
    try:
        cp = subprocess.run([_python(), "-c", code, dest, text, str(out)], env=env, timeout=TIMEOUT,
                            capture_output=True, cwd=str(HUD_DIR), creationflags=0x08000000)
        if out.exists():
            data = json.loads(out.read_text(encoding="utf-8"))
            r = data["r"]
            dbg += data.get("dbg", [])
        else:
            err = cp.stderr.decode("utf-8", "replace")[-1200:]
            dbg.append(f"sin resultado (código {cp.returncode}): {err}")
            # si ni siquiera cargó (p. ej. falta Telethon) no se envió nada
            r = {"ok": False, "fallback": True, "msg": "Telegram oculto no funcionó; no envié nada por esa vía."}
    except subprocess.TimeoutExpired:  # subprocess.run mata el proceso al pasarse
        dbg.append("el proceso no terminó a tiempo (se cerró)")
        r = {"ok": False, "fallback": False,
             "msg": "Telegram tardó demasiado y no pude comprobar si se envió. Revise el chat antes de reintentar."}
    except Exception as exc:  # noqa: BLE001
        dbg.append(f"EXCEPCION al lanzar: {type(exc).__name__}: {exc}")
        r = {"ok": False, "fallback": True, "msg": "No pude iniciar Telegram oculto; no envié nada por esa vía."}
    finally:
        try:
            out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return r

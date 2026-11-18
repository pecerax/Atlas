"""Conecta Atlas con su bot de Telegram (creado con @BotFather).

El token se escribe aquí (oculto) y se guarda solo en este PC, en
~/.atlas/connectors/telegram.json, junto con el id de su chat: Atlas solo le responderá a ese chat.
"""
import getpass
import json
import sys
import time
from pathlib import Path

try:  # certificados con el almacén de Windows
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_telegram import API, CONFIG, load_config  # noqa: E402


def call(token, method, **params):
    r = requests.post(f"{API}/bot{token}/{method}", json=params, timeout=params.get("timeout", 0) + 20)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"{r.status_code}: {data.get('description')}")
    return data["result"]


print("=== Conectar Atlas con Telegram ===\n")
old = load_config()
token = ""
if old:
    print("Ya hay un bot conectado.")
    if input("¿Usar el mismo token y solo volver a vincular el chat? (s/n): ").strip().lower().startswith("s"):
        token = old["token"]
if not token:
    print("Pegue el token que le dio @BotFather (clic derecho para pegar). No se verá al escribir.")
    token = getpass.getpass("Token: ").strip()
if not token:
    raise SystemExit("Cancelado.")
try:
    me = call(token, "getMe")
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"\nTelegram no aceptó ese token ({exc}). Revise que lo copió completo.")
bot = me.get("username", "")
print(f"\nBot encontrado: @{bot}")
try:
    call(token, "deleteWebhook", drop_pending_updates=True)
except Exception as exc:  # noqa: BLE001
    if "409" in str(exc):
        raise SystemExit("Atlas está abierto y usando el bot. Ciérrelo y vuelva a correr este instalador.")

print(f"\nAhora, desde su celular, abra https://t.me/{bot} y mándele cualquier mensaje (por ejemplo «hola»).")
print("Espero hasta 3 minutos…")
offset, chat, fin = 0, None, time.time() + 180
while time.time() < fin and chat is None:
    try:
        ups = call(token, "getUpdates", offset=offset, timeout=25, allowed_updates=["message"])
    except Exception as exc:  # noqa: BLE001
        if "409" in str(exc):
            raise SystemExit("Atlas está abierto y usando el bot. Ciérrelo y vuelva a correr este instalador.")
        print(f"  (error: {exc}; reintento)")
        time.sleep(3)
        continue
    for up in ups:
        offset = up["update_id"] + 1
        m = up.get("message") or {}
        if (m.get("chat") or {}).get("type") != "private":
            continue
        frm = m.get("from") or {}
        nombre = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x)
        usuario = f" (@{frm['username']})" if frm.get("username") else ""
        print(f"\nLlegó un mensaje de: {nombre}{usuario}: «{(m.get('text') or '')[:60]}»")
        if input("¿Es usted? (s/n): ").strip().lower().startswith("s"):
            chat = frm["id"]
            break
        print("Ignorado. Espero otro mensaje…")
if chat is None:
    raise SystemExit("\nNo llegó ningún mensaje suyo. Vuelva a correr el instalador.")
call(token, "getUpdates", offset=offset, timeout=0)  # marcar como leídos los mensajes de la vinculación

print("\nCuando le mande una nota de voz, ¿quiere que también responda con audio?")
print("  1 = sí, cuando le hable con nota de voz (recomendado)")
print("  2 = siempre con audio")
print("  3 = nunca, solo texto")
voz = {"2": "siempre", "3": "nunca"}.get(input("Opción [1]: ").strip(), "si_nota")

CONFIG.parent.mkdir(parents=True, exist_ok=True)
from openjarvis.security import atlas_secretos  # noqa: E402

atlas_secretos.guardar_json(CONFIG, {"token": token, "chat_id": chat, "bot": bot, "voz": voz})
try:
    call(token, "sendMessage", chat_id=chat,
         text="Listo, señor. Este chat quedó vinculado con Atlas. Funciono mientras Atlas esté abierto en el PC.")
except Exception:  # noqa: BLE001
    pass
print("\nListo. El token quedó cifrado en el Administrador de credenciales de Windows (Atlas-Telegram-Bot).")
print("Solo este chat podrá hablarle a Atlas. Cierre y abra Atlas para activarlo.")

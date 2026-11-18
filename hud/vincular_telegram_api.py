"""Vincula una sola vez la cuenta de Telegram del usuario para que Atlas envíe mensajes sin abrir Telegram.

Lo corre el propio usuario (Vincular-Telegram.cmd). Todo lo secreto (api_hash, código, contraseña de dos pasos) se
escribe aquí, en esta ventana, sin mostrarse en pantalla, y nunca pasa por el chat ni por Atlas.
"""
from __future__ import annotations

import asyncio
import getpass
import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_tg_api as T  # noqa: E402


def ask(prompt: str, secret: bool = False) -> str:
    while True:
        v = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if v:
            return v
        print("  (no puede quedar vacío)")


def main() -> int:
    print("=" * 66)
    print(" Telegram oculto de Atlas: enviar mensajes sin abrir Telegram")
    print("=" * 66)
    print("""
Esto se hace UNA sola vez. Atlas usará la conexión oficial de Telegram
para cuentas de usuario, así que no se abrirán ventanas al enviar.

PASO 1. Cree su clave de aplicación en my.telegram.org (le abro la página):
  a) Escriba su número con +56 y presione Next.
  b) Telegram le manda un código AL CHAT DE TELEGRAM (no por SMS).
     Escríbalo en la página.
  c) Entre a «API development tools».
  d) Si le pide crear una aplicación, ponga:
       App title: Jarvis      Short name: jarvispc
       Platform: Desktop      (lo demás puede quedar vacío)
     y presione «Create application».
  e) Verá «App api_id» (un número) y «App api_hash» (letras y números).
     Déjelos a la vista: los copiará aquí abajo.
""")
    old = T.load_conf()
    if old:
        print("Ya hay una clave guardada. Si la deja igual, presione Enter dos veces más abajo.")
    try:
        webbrowser.open("https://my.telegram.org/auth")
    except Exception:  # noqa: BLE001
        pass
    input("Presione Enter cuando tenga el api_id y el api_hash a la vista... ")

    api_id = input("\napi_id (solo números" + (", Enter = el guardado" if old else "") + "): ").strip()
    if not api_id and old:
        api_id = str(old["api_id"])
    while not api_id.isdigit():
        api_id = ask("  El api_id son solo números. api_id: ")
    api_hash = getpass.getpass("api_hash (no se ve al escribir ni pegar" + (", Enter = el guardado" if old else "") + "): ").strip()
    if not api_hash and old:
        api_hash = str(old["api_hash"])
    while not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        api_hash = ask("  El api_hash tiene 32 letras y números. Péguelo de nuevo: ", secret=True)
    phone = input("\nSu número de Telegram con +56 (ej. +56 9 1234 5678): ").strip()
    while len(re.sub(r"\D", "", phone)) < 8:
        phone = ask("  Escriba el número completo con +56: ")
    phone = "+" + re.sub(r"\D", "", phone)

    print("""
PASO 2. Inicio de sesión. Telegram le enviará OTRO código a su Telegram.
Escríbalo aquí cuando lo pida. Si tiene verificación en dos pasos, también
le pedirá esa contraseña (no se ve al escribirla).
""")

    async def link() -> str:
        from telethon import TelegramClient

        from telethon.sessions import StringSession

        T.CONN_DIR.mkdir(parents=True, exist_ok=True)
        S = T._secretos()
        # La sesión queda cifrada en el Administrador de credenciales, no en telegram_usuario.session
        ses = StringSession() if S.disponible() else str(T.SESSION)
        client = TelegramClient(ses, int(api_id), api_hash, receive_updates=False,
                                device_model="Atlas (PC)", app_version="Atlas")
        await client.start(phone=lambda: phone,
                           code_callback=lambda: ask("Código que le llegó a Telegram: "),
                           password=lambda: getpass.getpass("Contraseña de verificación en dos pasos: "))
        me = await client.get_me()
        if isinstance(ses, StringSession):
            S.guardar(S.TELEGRAM_SESION, client.session.save())
            T.SESSION.with_suffix(".session").unlink(missing_ok=True)  # la antigua, si había
        await client.disconnect()
        return T.display_name(me) + (f" (@{me.username})" if me.username else "")

    try:
        who = asyncio.run(link())
    except Exception as exc:  # noqa: BLE001
        print(f"\nNo se pudo vincular: {type(exc).__name__}: {exc}")
        print("Revise el api_id y el api_hash y vuelva a abrir Vincular-Telegram.cmd.")
        return 1
    T._secretos().guardar_json(T.CONF, {"api_id": int(api_id), "api_hash": api_hash, "telefono": phone})
    print(f"\nListo. Telegram quedó vinculado como {who}.")
    print("Atlas ya puede enviar por Telegram sin abrir la app (no hace falta reiniciarlo).")
    print("Telegram le mostrará un aviso de «nuevo inicio de sesión»: es este, de Atlas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Guarda las claves de Baco (TMDB e IGDB) en el Administrador de credenciales de Windows.

18-11-2026. Se escriben sin que se vean en pantalla (getpass) y nunca van a archivos ni al registro.
Entradas: Atlas-Baco-TMDB (token de acceso de lectura) y Atlas-Baco-IGDB (Client ID y Client Secret de Twitch).
Uso: Guardar-claves-Baco.cmd en la carpeta de Atlas.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request

from openjarvis.security import atlas_secretos as SEC

TMDB = "Atlas-Baco-TMDB"
IGDB = "Atlas-Baco-IGDB"


def _probar_tmdb(token: str) -> str:
    if token.startswith("eyJ"):
        req = urllib.request.Request("https://api.themoviedb.org/3/authentication",
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    else:  # clave de API (v3)
        req = urllib.request.Request("https://api.themoviedb.org/3/authentication?api_key=" + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return "ok" if json.loads(r.read() or b"{}").get("success") else "rechazada"
    except urllib.error.HTTPError as e:
        return "rechazada" if e.code in (401, 403) else f"sin respuesta ({e.code})"
    except Exception:  # noqa: BLE001
        return "sin conexión"


def _probar_igdb(cid: str, sec: str) -> str:
    from urllib.parse import urlencode
    datos = urlencode({"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://id.twitch.tv/oauth2/token", data=datos), timeout=10) as r:
            return "ok" if json.loads(r.read() or b"{}").get("access_token") else "rechazada"
    except urllib.error.HTTPError as e:
        return "rechazada" if e.code in (400, 401, 403) else f"sin respuesta ({e.code})"
    except Exception:  # noqa: BLE001
        return "sin conexión"


def _estado(nombre: str) -> str:
    return "guardada" if SEC.existe(nombre) else "no guardada"


def tmdb() -> None:
    print("\n  Pegue el «Token de acceso de lectura de la API» de TMDB (el largo, empieza con eyJ).")
    print("  No se verá mientras lo pega. Enter vacío = cancelar.")
    v = getpass.getpass("  Token: ").strip()
    if not v:
        print("  Cancelado.")
        return
    if len(v) > 1200 or any(c.isspace() for c in v):
        print("  Eso no parece un token (tiene espacios o es demasiado largo). No se guardó nada.")
        return
    prueba = _probar_tmdb(v)
    if prueba == "rechazada":
        print("  TMDB rechazó ese token. Revise que copió el completo. No se guardó nada.")
        return
    SEC.guardar(TMDB, v)
    v = None
    print("  Guardado en el Administrador de credenciales." + ("" if prueba == "ok" else f" (No pude comprobarlo: {prueba}.)"))


def igdb() -> None:
    print("\n  Datos de su aplicación en dev.twitch.tv/console (botón Administrar). Enter vacío = cancelar.")
    cid = getpass.getpass("  Client ID (no se verá): ").strip()
    if not cid:
        print("  Cancelado.")
        return
    sec = getpass.getpass("  Client Secret (no se verá): ").strip()
    if not sec:
        print("  Cancelado.")
        return
    if any(c.isspace() for c in cid + sec) or len(cid) > 100 or len(sec) > 100:
        print("  Eso no parece correcto (tiene espacios o es demasiado largo). No se guardó nada.")
        return
    prueba = _probar_igdb(cid, sec)
    if prueba == "rechazada":
        print("  Twitch rechazó esos datos. Revise que sean de la misma aplicación. No se guardó nada.")
        return
    SEC.guardar(IGDB, json.dumps({"id": cid, "secreto": sec}, separators=(",", ":")))
    cid = sec = None
    print("  Guardado en el Administrador de credenciales." + ("" if prueba == "ok" else f" (No pude comprobarlo: {prueba}.)"))


def main() -> int:
    if not SEC.disponible():
        print("  El Administrador de credenciales solo existe en Windows.")
        return 1
    while True:
        print(f"\n  Claves de Baco\n  1 = TMDB (series)   [{_estado(TMDB)}]\n  2 = IGDB (juegos)   [{_estado(IGDB)}]")
        print("  3 = Borrar TMDB     4 = Borrar IGDB     Enter = Salir")
        op = input("  Elija: ").strip()
        try:
            if op == "1":
                tmdb()
            elif op == "2":
                igdb()
            elif op in ("3", "4"):
                SEC.borrar(TMDB if op == "3" else IGDB)
                print("  Borrada.")
            else:
                return 0
        except OSError:
            print("  No pude usar el Administrador de credenciales. No se guardó nada.")


if __name__ == "__main__":
    sys.exit(main())

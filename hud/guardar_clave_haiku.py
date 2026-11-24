"""Guarda la clave de API de Anthropic (para el intérprete con Haiku) en el Administrador de credenciales de Windows.

23-11-2026. Se escribe sin que se vea en pantalla (getpass) y nunca va a archivos ni al registro.
Entrada: Atlas-Haiku-API. Uso: Guardar-clave-Haiku.cmd en la carpeta de Atlas.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from openjarvis.security import atlas_secretos as SEC

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_interprete as IH  # noqa: E402


def _probar(clave: str) -> str:
    """Pregunta a Anthropic por el modelo (no gasta saldo). -> ok / rechazada / sin conexión."""
    req = urllib.request.Request("https://api.anthropic.com/v1/models/" + IH.MODELO,
                                 headers={"x-api-key": clave, "anthropic-version": IH.VERSION_API})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            return "ok" if json.loads(r.read() or b"{}").get("id") else "sin respuesta"
    except urllib.error.HTTPError as e:
        return "rechazada" if e.code in (401, 403) else f"sin respuesta ({e.code})"
    except Exception:  # noqa: BLE001
        return "sin conexión"


def guardar() -> None:
    print("\n  Pegue su clave de API de Anthropic (empieza con sk-ant-). La crea en")
    print("  https://console.anthropic.com/settings/keys   No se verá mientras la pega. Enter vacío = cancelar.")
    v = getpass.getpass("  Clave: ").strip()
    if not v:
        print("  Cancelado.")
        return
    if len(v) > 400 or any(c.isspace() for c in v) or not v.startswith("sk-ant-"):
        print("  Eso no parece una clave de Anthropic (debe empezar con sk-ant- y no tener espacios). No se guardó nada.")
        return
    prueba = _probar(v)
    if prueba == "rechazada":
        print("  Anthropic rechazó esa clave. Revise que la copió completa. No se guardó nada.")
        return
    SEC.guardar(IH.SECRETO, v)
    v = None
    IH.olvidar_clave()
    print("  Guardada en el Administrador de credenciales." + ("" if prueba == "ok" else f" (No pude comprobarla: {prueba}.)"))
    print("  Atlas la empieza a usar en un minuto; no hace falta reiniciarlo.")


def probar() -> None:
    e = IH.estado()
    if not e["disponible"]:
        print(f"  Haiku no se usaría ahora: {e['motivo']}.")
        return
    frase = "eh... el Felipe, llámalo"
    orden = IH.traducir(frase, [], "Traduces lo que dijo el usuario a UNA orden directa en español "
                                   "(por ejemplo «llama a <contacto>»). Responde solo la orden.", log=print)
    print(f"  «{frase}»  ->  {orden!r}" if orden is not None else "  No hubo respuesta; mire el mensaje de arriba.")


def main() -> int:
    if not SEC.disponible():
        print("  El Administrador de credenciales solo existe en Windows.")
        return 1
    while True:
        e = IH.estado()
        g = e["gasto"]
        print(f"\n  Intérprete con Haiku   [clave {'guardada' if SEC.existe(IH.SECRETO) else 'no guardada'}]"
              f"   [{'encendido' if IH.encendido() else 'apagado en ajustes'}]")
        print(f"  Gasto de {g['mes']}: {g['usd']:.4f} USD en {g['llamadas']} frases (tope {e['tope_usd_mes']:g} USD)")
        print("  1 = Guardar o cambiar la clave   2 = Probar con una frase   3 = Borrar la clave   Enter = Salir")
        op = input("  Elija: ").strip()
        try:
            if op == "1":
                guardar()
            elif op == "2":
                probar()
            elif op == "3":
                SEC.borrar(IH.SECRETO)
                IH.olvidar_clave()
                print("  Borrada. Atlas vuelve a usar solo el modelo local.")
            else:
                return 0
        except OSError:
            print("  No pude usar el Administrador de credenciales. No se guardó nada.")


if __name__ == "__main__":
    sys.exit(main())

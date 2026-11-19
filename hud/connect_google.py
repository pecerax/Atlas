"""Conecta Atlas con Google Calendar (una sola vez). Todo queda guardado solo en este PC.

Usa la llave de Google propia de Atlas (instalador\google_cliente.json, la trae Atlas-Instalar.exe). Si no está, busca
un JSON de cliente tipo "App de escritorio" descargado de Google Cloud.
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
import atlas_gcal as gcal  # noqa: E402


LLAVE_ATLAS = HERE.parent / "instalador" / "google_cliente.json"   # la app «Atlas» publicada (18-11-2026)


def find_client_file() -> Path | None:
    if LLAVE_ATLAS.exists():
        return LLAVE_ATLAS
    cands = []
    for folder in (Path.home() / "Downloads", Path.home() / "Descargas", Path.home() / "Desktop", HERE, HERE.parent):
        if folder.is_dir():
            cands += list(folder.glob("client_secret*.json")) + list(folder.glob("google_client*.json"))
    return max(cands, key=lambda f: f.stat().st_mtime) if cands else None


def main() -> None:
    print("=== Conectar Atlas con Google Calendar ===\n")
    gcal.CONN.mkdir(parents=True, exist_ok=True)
    if not gcal.CLIENT.exists():
        f = find_client_file()
        if f is None:
            print("No encontre el archivo de credencial (client_secret_....json).")
            print("Descarguelo desde Google Cloud (Clientes -> su cliente -> Descargar JSON),")
            print("dejelo en la carpeta Descargas y ejecute esto de nuevo.")
            return
        import json as _json

        gcal.atlas_secretos.guardar_json(gcal.CLIENT, _json.loads(f.read_text(encoding="utf-8")))
        print(f"Credencial encontrada: {f.name}  (guardada cifrada en el Administrador de credenciales)")
        if f != LLAVE_ATLAS:
            print(f"Ya puede borrar {f} de su carpeta: Atlas no lo necesita más.")
    try:
        gcal._client()
    except Exception as exc:  # noqa: BLE001
        print(f"El archivo de credencial no sirve: {exc}")
        print(f"Borre {gcal.CLIENT} y vuelva a descargar el JSON del cliente tipo 'App de escritorio'.")
        return
    print("\nSe abrira el navegador. Elija su cuenta de Google y acepte el permiso")
    print("'Ver y editar eventos de tus calendarios'. Si aparece 'Google no ha verificado")
    print("esta aplicacion', elija Configuracion avanzada -> Ir a Atlas.\n")
    try:
        name = gcal.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"\nNo se pudo conectar: {exc}")
        return
    print(f"\nListo: Atlas quedo conectado al calendario '{name}'.")
    print("Cierre Atlas y vuelva a abrirlo. Pruebe: 'agendame una prueba manana a las 10'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

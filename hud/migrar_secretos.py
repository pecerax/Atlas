"""Pasa las credenciales de Atlas de archivos de texto al Administrador de credenciales de Windows.

Uso (con Atlas CERRADO), desde Proteger-credenciales.cmd:
    python migrar_secretos.py            revisa y muestra qué haría, sin cambiar nada
    python migrar_secretos.py --aplicar  hace la migración
    python migrar_secretos.py --deshacer vuelve a dejar los archivos como estaban

Qué hace --aplicar, archivo por archivo:
 1. Antes de tocar nada, guarda una copia de TODOS los archivos originales en
    respaldo_credenciales.dpapi (cifrada con DPAPI: solo su usuario de Windows en este PC la abre).
 2. Guarda lo secreto en el Administrador de credenciales (entradas «Atlas-...»).
 3. Lo vuelve a leer y compara. Solo si es idéntico reemplaza el archivo por un «sobre» sin secretos.
 4. La sesión de Telegram (telegram_usuario.session) se convierte al formato de texto de Telethon,
    se guarda cifrada y se borra el archivo.
 5. Las claves de Hermes (clave_pdf.txt, clave_mach.txt) se guardan cifradas y se borran los .txt.

Nunca muestra ni escribe en el registro el valor de un secreto.
"""
from __future__ import annotations

import base64
import json
import socket
import sys
from pathlib import Path

from openjarvis.security import atlas_secretos as S

HERE = Path(__file__).resolve().parent
RESPALDO = HERE / "respaldo_credenciales.dpapi"


# ----------------------------------------------------------------------------- DPAPI para el respaldo
def _dpapi(datos: bytes, cifrar: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = BLOB()
    fn = crypt.CryptProtectData if cifrar else crypt.CryptUnprotectData
    ok = fn(ctypes.byref(entrada), None if not cifrar else "Atlas respaldo", None, None, None, 0,
            ctypes.byref(salida))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI falló")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        k32.LocalFree(salida.pbData)


# ----------------------------------------------------------------------------- qué hay que migrar
def candidatos() -> list[Path]:
    rutas = [S.CONN / "gmail_imap.json", S.CONN / "google_calendar_token.json", S.CONN / "google_client.json",
             S.CONN / "telegram.json", S.CONN / "telegram_usuario.json", S.HUD / "ucursos_sesion.json"]
    if (S.CONN / "mail_accounts").is_dir():
        rutas += sorted((S.CONN / "mail_accounts").glob("*.json"))
    return [p for p in rutas if p.exists()]


SESION_TG = S.CONN / "telegram_usuario.session"
CLAVES = [(S.HERMES_PDF, S.HERMES / "clave_pdf.txt"), (S.HERMES_MACH, S.HERMES / "clave_mach.txt")]


def atlas_abierto() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.5):
            return True
    except OSError:
        return False


def revisar() -> list[tuple[str, str, str]]:
    """(archivo, entrada, estado) sin cambiar nada."""
    filas = []
    for p in candidatos():
        filas.append((str(p), S.nombre_para(p) or "?", "ya cifrado" if S.esta_sellado(p) else "TEXTO PLANO"))
    if SESION_TG.exists():
        filas.append((str(SESION_TG), S.TELEGRAM_SESION, "TEXTO PLANO"))
    elif S.existe(S.TELEGRAM_SESION):
        filas.append(("(sesión de Telegram)", S.TELEGRAM_SESION, "ya cifrado"))
    for nombre, f in CLAVES:
        if f.exists():
            filas.append((str(f), nombre, "TEXTO PLANO"))
        elif S.existe(nombre):
            filas.append((f"({f.name})", nombre, "ya cifrado"))
    return filas


# ----------------------------------------------------------------------------- aplicar / deshacer
def respaldar() -> int:
    archivos = [p for p in candidatos() if not S.esta_sellado(p)]
    archivos += [SESION_TG] if SESION_TG.exists() else []
    archivos += [f for _, f in CLAVES if f.exists()]
    if not archivos:
        return 0
    contenido = {str(p): base64.b64encode(p.read_bytes()).decode() for p in archivos}
    previo = {}
    if RESPALDO.exists():  # se suma a un respaldo anterior, nunca lo pisa
        previo = json.loads(_dpapi(RESPALDO.read_bytes(), cifrar=False))
    previo.update(contenido)
    blob = _dpapi(json.dumps(previo).encode(), cifrar=True)
    RESPALDO.write_bytes(blob)
    if json.loads(_dpapi(RESPALDO.read_bytes(), cifrar=False)) != previo:
        raise SystemExit("El respaldo cifrado no se pudo comprobar. No cambié nada.")
    return len(archivos)


def aplicar() -> list[str]:
    hechos = []
    for p in candidatos():
        if S.esta_sellado(p):
            continue
        datos = json.loads(p.read_text(encoding="utf-8"))
        if not S.guardar_json(p, datos):
            hechos.append(f"OMITIDO  {p.name}: el Administrador de credenciales no está disponible")
            continue
        if S.cargar_json(p) != datos:
            p.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")  # vuelve atrás
            hechos.append(f"FALLÓ    {p.name}: no coincidió al releer; quedó como estaba")
            continue
        hechos.append(f"cifrado  {p.name} -> {S.nombre_para(p)}")

    if SESION_TG.exists():
        from telethon.sessions import SQLiteSession, StringSession

        ses = SQLiteSession(str(SESION_TG.with_suffix("")))
        try:
            texto = StringSession.save(ses)
        finally:
            ses.close()
        if not texto:
            hechos.append("FALLÓ    telegram_usuario.session: está vacía; vuelva a vincular Telegram")
        else:
            S.guardar(S.TELEGRAM_SESION, texto)
            if S.leer(S.TELEGRAM_SESION) == texto:
                SESION_TG.unlink()
                SESION_TG.with_name(SESION_TG.name + "-journal").unlink(missing_ok=True)
                hechos.append(f"cifrado  telegram_usuario.session -> {S.TELEGRAM_SESION}")
            else:
                hechos.append("FALLÓ    telegram_usuario.session: no coincidió al releer; quedó como estaba")

    for nombre, f in CLAVES:
        if f.exists():
            valor = f.read_text(encoding="utf-8").strip()
            if S.guardar_clave(nombre, valor, f):
                hechos.append(f"cifrado  {f.name} -> {nombre}")
            else:
                hechos.append(f"FALLÓ    {f.name}: quedó como estaba")
    return hechos


def deshacer() -> list[str]:
    if not RESPALDO.exists():
        raise SystemExit("No hay respaldo_credenciales.dpapi: no hay nada que deshacer.")
    contenido = json.loads(_dpapi(RESPALDO.read_bytes(), cifrar=False))
    hechos = []
    for ruta, b64 in contenido.items():
        p = Path(ruta)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(b64))
        hechos.append(f"restaurado  {p}")
    return hechos


def main(argv: list[str]) -> int:
    print("=== Proteger las credenciales de Atlas ===\n")
    if sys.platform != "win32":
        print("Esto solo funciona en Windows.")
        return 1
    modo = argv[1] if len(argv) > 1 else ""
    if modo in ("--aplicar", "--deshacer") and atlas_abierto():
        print("Atlas está abierto. Ciérrelo (también el círculo flotante) y vuelva a ejecutar esto.")
        return 1
    if modo == "--deshacer":
        for h in deshacer():
            print("  " + h)
        print("\nListo: los archivos quedaron como antes. Las entradas «Atlas-...» siguen en el")
        print("Administrador de credenciales; puede borrarlas desde ahí si quiere.")
        return 0

    filas = revisar()
    print("Estado actual:")
    for archivo, entrada, estado in filas:
        print(f"  [{estado:11}] {archivo}\n                -> {entrada}")
    pendientes = [f for f in filas if f[2] == "TEXTO PLANO"]
    if not pendientes:
        print("\nTodo ya está cifrado. No hay nada que hacer.")
        return 0
    if modo != "--aplicar":
        print(f"\n{len(pendientes)} credenciales en texto plano. Para cifrarlas, ejecute con --aplicar.")
        return 0

    n = respaldar()
    print(f"\nRespaldo cifrado de {n} archivos en {RESPALDO.name} (para --deshacer).")
    for h in aplicar():
        print("  " + h)
    print("\nListo. Abra Atlas y revise que el correo, Calendar, Telegram y U-Cursos sigan en verde.")
    print("Si algo falla, ejecute Proteger-credenciales.cmd y elija deshacer.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

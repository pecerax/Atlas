"""Secretos de Atlas en el Administrador de credenciales de Windows.

Las contraseñas, tokens y cookies ya no quedan legibles en archivos. Cada archivo de credenciales
conocido (correo, Google Calendar, Telegram, U-Cursos) se convierte en un «sobre»: el archivo sigue
existiendo, pero solo guarda datos que no son secretos (servidor IMAP, chat_id, fecha) y el nombre
de la entrada del Administrador de credenciales donde está lo secreto:

    {"imap_host": "mail.correo-empresa.example", "validated": true, "_secreto": "Atlas-Correo-..."}

Windows cifra esas entradas con DPAPI, ligadas a su usuario de Windows: otro usuario del PC o
alguien que copie la carpeta no las puede leer. Se ven y se borran en
Panel de control > Administrador de credenciales > Credenciales de Windows (todas empiezan con «Atlas-»).

Reglas de seguridad de este módulo:
- Solo sella los archivos REALES de Atlas (rutas fijas). Cualquier otra ruta (por ejemplo, la
  carpeta temporal de las pruebas) se lee y escribe como JSON normal, para que una prueba nunca
  toque las credenciales verdaderas.
- Fuera de Windows (o si el Administrador de credenciales falla al escribir) no inventa nada:
  escribe el archivo como antes y lo anota en el registro.
- Nunca escribe valores secretos en el registro ni en mensajes de error.

Sin dependencias: usa advapi32 con ctypes. El formato (texto UTF-16, tipo genérico) es el mismo
que usa la librería «keyring», así que las entradas son compatibles con ella.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

PREFIJO = "Atlas-"
USUARIO = "Atlas"
# Transición Jarvis -> Atlas: las entradas viejas «Jarvis-X» se siguen leyendo si «Atlas-X» no existe.
# Todo lo que se escribe va a «Atlas-X». Las «Jarvis-X» no se borran solas (salvo al desconectar un servicio).
PREFIJO_VIEJO = "Jarvis-"
_MAX_CHARS = 1200  # el blob admite 2560 bytes = 1280 caracteres UTF-16; los valores largos se parten


def _nuevo(nombre: str) -> str:
    """«Jarvis-X» -> «Atlas-X» (los demás nombres quedan igual)."""
    return PREFIJO + nombre[len(PREFIJO_VIEJO):] if nombre.startswith(PREFIJO_VIEJO) else nombre


def _viejo(nombre: str) -> str:
    """«Atlas-X» -> «Jarvis-X» (los demás nombres quedan igual)."""
    return PREFIJO_VIEJO + nombre[len(PREFIJO):] if nombre.startswith(PREFIJO) else nombre


HOME = Path.home()
_LOCAL = Path(os.environ.get("LOCALAPPDATA") or (HOME / "AppData" / "Local"))
# Carpetas: las nuevas (Atlas, .atlas) si ya existen; si no, las de siempre (OpenJarvis, .openjarvis)
CONN = (HOME / ".atlas" / "connectors") if (HOME / ".atlas" / "connectors").is_dir() else (HOME / ".openjarvis" / "connectors")
OJ = (_LOCAL / "Atlas") if (_LOCAL / "Atlas" / "hud").is_dir() else (_LOCAL / "OpenJarvis")
HUD = OJ / "hud"
HERMES = HOME / "Downloads" / "Apolo"  # la carpeta de datos de Hermes conserva su nombre (18-11-2026)
APOLO = HERMES  # los scripts de esa carpeta (leer_cartolas.py, configurar_*.py) usan este nombre

# Entradas fijas (las de correo se arman con el nombre del archivo)
GOOGLE_CALENDAR = "Atlas-GoogleCalendar"
GOOGLE_CLIENTE = "Atlas-GoogleCalendar-Cliente"
TELEGRAM_BOT = "Atlas-Telegram-Bot"
TELEGRAM_USUARIO = "Atlas-Telegram-Usuario"
TELEGRAM_SESION = "Atlas-Telegram-Sesion"
UCURSOS = "Atlas-UCursos"
CANVAS = "Atlas-Canvas"
HERMES_PDF = "Atlas-Hermes-PDF"
HERMES_MACH = "Atlas-Hermes-MACH"
APOLO_PDF, APOLO_MACH = HERMES_PDF, HERMES_MACH  # nombres que usan los scripts de Downloads\Apolo
# Respaldo de lectura: Hermes se llamaba Apolo; si «Atlas-Hermes-X» no está, se lee «Atlas-Apolo-X» (no se borra)
_RESPALDO = {HERMES_PDF: "Atlas-Apolo-PDF", HERMES_MACH: "Atlas-Apolo-MACH"}

# Campos que pueden quedar a la vista en el sobre (no son secretos y otros módulos los leen sin abrirlo)
_PUBLICOS: dict[str, tuple[str, ...]] = {
    "correo": ("imap_host", "imap_port", "imap_security", "validated"),
    GOOGLE_CALENDAR: ("expires_at",),
    GOOGLE_CLIENTE: (),
    TELEGRAM_BOT: ("chat_id", "bot", "voz"),
    TELEGRAM_USUARIO: ("api_id",),
    UCURSOS: ("guardada",),
    CANVAS: ("guardada", "url"),
}


# ----------------------------------------------------------------------------- qué archivo es cuál
def _abs(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def nombre_para(path: Path | str) -> Optional[str]:
    """Entrada del Administrador de credenciales para un archivo real de Atlas; None si no es uno."""
    p = _abs(path)
    fijos = {
        _abs(CONN / "gmail_imap.json"): "Atlas-Correo-principal",
        _abs(CONN / "google_calendar_token.json"): GOOGLE_CALENDAR,
        _abs(CONN / "google_client.json"): GOOGLE_CLIENTE,
        _abs(CONN / "telegram.json"): TELEGRAM_BOT,
        _abs(CONN / "telegram_usuario.json"): TELEGRAM_USUARIO,
        _abs(HUD / "ucursos_sesion.json"): UCURSOS,
        _abs(HUD / "canvas_sesion.json"): CANVAS,
    }
    if p in fijos:
        return fijos[p]
    carpeta = _abs(CONN / "mail_accounts")
    if os.path.dirname(p) == carpeta and p.endswith(".json"):
        return "Atlas-Correo-" + os.path.basename(p)[:-5]
    return None


def es_real(path: Path | str) -> bool:
    """True si la ruta es (o está dentro de) una carpeta real de credenciales de Atlas."""
    p = _abs(path)
    return any(p == _abs(r) or p.startswith(_abs(r) + os.sep) for r in (CONN, HUD, APOLO))


def _publicos(nombre: str) -> tuple[str, ...]:
    nombre = _nuevo(nombre)
    return _PUBLICOS["correo"] if nombre.startswith("Atlas-Correo-") else _PUBLICOS.get(nombre, ())


# ----------------------------------------------------------------------------- Administrador de credenciales
_backend_prueba: Optional[dict] = None  # las pruebas pueden poner un dict aquí para simular el almacén


def disponible() -> bool:
    return _backend_prueba is not None or sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CredWrite = _advapi.CredWriteW
    _CredWrite.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    _CredWrite.restype = wintypes.BOOL
    _CredRead = _advapi.CredReadW
    _CredRead.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    _CredRead.restype = wintypes.BOOL
    _CredDelete = _advapi.CredDeleteW
    _CredDelete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDelete.restype = wintypes.BOOL
    _CredFree = _advapi.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2  # queda en este PC; no viaja con la cuenta Microsoft
    _ERROR_NOT_FOUND = 1168

    def _w_escribir(objetivo: str, valor: str) -> None:
        blob = valor.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob) if blob else None
        c = _CREDENTIAL()
        c.Type = _CRED_TYPE_GENERIC
        c.TargetName = objetivo
        c.Comment = "Atlas: credencial cifrada por Windows"
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)) if buf else None
        c.Persist = _CRED_PERSIST_LOCAL_MACHINE
        c.UserName = USUARIO
        if not _CredWrite(ctypes.byref(c), 0):
            raise OSError(ctypes.get_last_error(), f"No pude guardar {objetivo} en el Administrador de credenciales")

    def _w_leer(objetivo: str) -> Optional[str]:
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _CredRead(objetivo, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            err = ctypes.get_last_error()
            if err == _ERROR_NOT_FOUND:
                return None
            raise OSError(err, f"No pude leer {objetivo} del Administrador de credenciales")
        try:
            n = p.contents.CredentialBlobSize
            return ctypes.string_at(p.contents.CredentialBlob, n).decode("utf-16-le") if n else ""
        finally:
            _CredFree(p)

    def _w_borrar(objetivo: str) -> None:
        if not _CredDelete(objetivo, _CRED_TYPE_GENERIC, 0):
            err = ctypes.get_last_error()
            if err != _ERROR_NOT_FOUND:
                raise OSError(err, f"No pude borrar {objetivo} del Administrador de credenciales")


def _escribir(objetivo: str, valor: str) -> None:
    if _backend_prueba is not None:
        _backend_prueba[objetivo] = valor
    else:
        _w_escribir(objetivo, valor)


def _leer(objetivo: str) -> Optional[str]:
    if _backend_prueba is not None:
        return _backend_prueba.get(objetivo)
    return _w_leer(objetivo)


def _borrar(objetivo: str) -> None:
    if _backend_prueba is not None:
        _backend_prueba.pop(objetivo, None)
    else:
        _w_borrar(objetivo)


def guardar(nombre: str, valor: str) -> None:
    """Guarda un texto. Si es largo lo parte en «nombre», «nombre#2», «nombre#3»...
    Un nombre viejo «Jarvis-X» se guarda como «Atlas-X»."""
    nombre = _nuevo(nombre)
    if not nombre.startswith(PREFIJO):
        raise ValueError("los secretos de Atlas empiezan con " + PREFIJO)
    if not disponible():
        raise OSError("El Administrador de credenciales solo existe en Windows")
    partes = [valor[i:i + _MAX_CHARS] for i in range(0, len(valor), _MAX_CHARS)] or [""]
    viejas = _contar_partes(nombre)
    if len(partes) == 1:
        _escribir(nombre, partes[0])
    else:
        for i, parte in enumerate(partes[1:], start=2):
            _escribir(f"{nombre}#{i}", parte)
        _escribir(nombre, f"\x00JSEC:{len(partes)}\x00" + partes[0])
    for i in range(len(partes) + 1, viejas + 1):  # sobras de una versión anterior más larga
        _borrar(f"{nombre}#{i}")


def _contar_partes(nombre: str) -> int:
    v = _leer(nombre)
    if v and v.startswith("\x00JSEC:"):
        try:
            return int(v[6:v.index("\x00", 6)])
        except ValueError:
            return 1
    return 1 if v is not None else 0


def leer(nombre: str) -> Optional[str]:
    """El texto guardado, o None si no existe (o si no estamos en Windows).
    Busca primero «Atlas-X» y, si no está, la entrada vieja «Jarvis-X»."""
    if not disponible():
        return None
    for candidato in dict.fromkeys(_candidatos(nombre)):
        v = _leer_entrada(candidato)
        if v is not None:
            return v
    return None


def _candidatos(nombre: str) -> tuple:
    """Dónde buscar al leer: «Atlas-X», la vieja «Jarvis-X» y, para Hermes, su nombre anterior «Atlas-Apolo-X»."""
    viejo_app = _RESPALDO.get(_nuevo(nombre))
    return (_nuevo(nombre), _viejo(nombre), nombre) + ((viejo_app, _viejo(viejo_app)) if viejo_app else ())


def _leer_entrada(nombre: str) -> Optional[str]:
    v = _leer(nombre)
    if v is None or not v.startswith("\x00JSEC:"):
        return v
    fin = v.index("\x00", 6)
    n = int(v[6:fin])
    trozos = [v[fin + 1:]]
    for i in range(2, n + 1):
        t = _leer(f"{nombre}#{i}")
        if t is None:
            raise OSError(f"Falta una parte de {nombre}; vuelva a conectar ese servicio")
        trozos.append(t)
    return "".join(trozos)


def borrar(nombre: str) -> None:
    """Borra la entrada (al desconectar un servicio): la nueva «Atlas-X» y también la vieja «Jarvis-X»,
    para que la lectura de respaldo no la «resucite»."""
    if not disponible():
        return
    for candidato in dict.fromkeys((_nuevo(nombre), _viejo(nombre), nombre)):
        n = _contar_partes(candidato)
        for i in range(2, n + 1):
            _borrar(f"{candidato}#{i}")
        _borrar(candidato)


def existe(nombre: str) -> bool:
    try:
        return disponible() and any(_leer(c) is not None for c in dict.fromkeys(_candidatos(nombre)))
    except OSError:
        return False


# ----------------------------------------------------------------------------- archivos JSON con sobre
def cargar_json(path: Path | str) -> Optional[dict]:
    """Lee un archivo de credenciales. Si es un sobre, junta lo público con lo secreto.

    Devuelve None si el archivo no existe o no es JSON (igual que antes). Si el sobre apunta a una
    entrada que ya no está, devuelve solo lo público: el servicio aparecerá como desconectado.
    """
    p = Path(path)
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or "_secreto" not in datos:
        return datos
    nombre = str(datos.pop("_secreto"))
    datos.pop("_nota", None)
    try:
        crudo = leer(nombre)
        secreto = json.loads(crudo) if crudo else {}
    except (OSError, ValueError):
        secreto = {}
    if isinstance(secreto, dict):
        datos.update(secreto)
    return datos


def guardar_json(path: Path | str, datos: dict) -> bool:
    """Guarda un archivo de credenciales. Si es uno real de Atlas, lo secreto va al Administrador
    de credenciales y el archivo queda como sobre. Devuelve True si quedó cifrado."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    nombre = nombre_para(p)
    if nombre and disponible():
        publicos = _publicos(nombre)
        secreto = {k: v for k, v in datos.items() if k not in publicos}
        sobre = {k: v for k, v in datos.items() if k in publicos}
        guardar(nombre, json.dumps(secreto, ensure_ascii=False, separators=(",", ":")))
        sobre["_secreto"] = nombre
        sobre["_nota"] = ("Lo secreto está cifrado en el Administrador de credenciales de Windows "
                          "(entrada " + nombre + "). Este archivo no contiene contraseñas.")
        _escribir_archivo(p, json.dumps(sobre, ensure_ascii=False, indent=1))
        return True
    _escribir_archivo(p, json.dumps(datos, ensure_ascii=False, indent=1))
    return False


def borrar_json(path: Path | str) -> None:
    """Borra el archivo y, si era un sobre, también su entrada."""
    p = Path(path)
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(datos, dict) and datos.get("_secreto"):
            borrar(str(datos["_secreto"]))
    except (OSError, ValueError):
        pass
    p.unlink(missing_ok=True)


def esta_sellado(path: Path | str) -> bool:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return isinstance(d, dict) and "_secreto" in d
    except (OSError, ValueError):
        return False


def _escribir_archivo(p: Path, texto: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, p)


# ----------------------------------------------------------------------------- claves de texto simple (Apolo)
def leer_clave(nombre: str, archivo_viejo: Path | str) -> Optional[str]:
    """Una clave corta: primero el Administrador de credenciales, después el .txt antiguo."""
    try:
        v = leer(nombre)
    except OSError:
        v = None
    if v:
        return v
    f = Path(archivo_viejo)
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def guardar_clave(nombre: str, valor: str, archivo_viejo: Path | str) -> bool:
    """Guarda una clave corta cifrada y borra el .txt antiguo. Si no hay Windows, usa el .txt."""
    if disponible():
        guardar(nombre, valor)
        if leer(nombre) == valor:
            Path(archivo_viejo).unlink(missing_ok=True)
            return True
    Path(archivo_viejo).write_text(valor, encoding="utf-8")
    return False

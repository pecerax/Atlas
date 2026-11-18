"""Crea src\\.venv\\Scripts\\Atlas.exe: una copia del lanzador pythonw.exe del entorno de Atlas con el ícono de Atlas y
la descripción «Atlas», para que el Administrador de tareas muestre «Atlas» en vez de «Python» (pedido 18-11-2026:
«el ejecutable se sigue llamando jarvis»).

La copia funciona igual que pythonw.exe (busca pyvenv.cfg en la carpeta de arriba y corre el Python del entorno).
Atlas.cmd la usa si existe y, si no, la crea con este script; si algo falla, Atlas.cmd sigue con pythonw.exe.
Si el entorno se rehace (instalador), basta con volver a correr este script. No toca nada fuera de .venv\\Scripts.
Uso:  pythonw.exe atlas_crear_exe.py [--forzar]
"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import sys
from ctypes import wintypes
from pathlib import Path

ATLAS = Path(os.environ.get("LOCALAPPDATA", "")) / "Atlas"
SCRIPTS = ATLAS / "src" / ".venv" / "Scripts"
ORIGEN = SCRIPTS / "pythonw.exe"
DESTINO = SCRIPTS / "Atlas.exe"
ICONO = ATLAS / "atlas-escritorio-2.ico"
RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.BeginUpdateResourceW.restype = wintypes.HANDLE
k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
k32.FreeLibrary.argtypes = [wintypes.HMODULE]
_ENUM_NOMBRES = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_ENUM_IDIOMAS = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p)
k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, _ENUM_NOMBRES, ctypes.c_void_p]
k32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, _ENUM_IDIOMAS, ctypes.c_void_p]


def _recursos(path: Path, tipos=(RT_ICON, RT_GROUP_ICON, RT_VERSION)) -> list[tuple[int, int, int]]:
    """(tipo, id, idioma) de los íconos y la versión del exe (solo ids numéricos, que es lo que trae el lanzador)."""
    h = k32.LoadLibraryExW(str(path), None, 0x2)  # LOAD_LIBRARY_AS_DATAFILE
    if not h:
        raise OSError(ctypes.get_last_error(), "no pude abrir el exe")
    out: list[tuple[int, int, int]] = []
    try:
        for tipo in tipos:
            nombres: list[int] = []
            cb = _ENUM_NOMBRES(lambda _m, _t, n, _p: (nombres.append(n) if n and n <= 0xFFFF else None) or True)
            k32.EnumResourceNamesW(h, tipo, cb, None)
            for n in nombres:
                idi: list[int] = []
                cl = _ENUM_IDIOMAS(lambda _m, _t, _n, l, _p: idi.append(l) or True)
                k32.EnumResourceLanguagesW(h, tipo, n, cl, None)
                out += [(tipo, n, l) for l in idi]
    finally:
        k32.FreeLibrary(h)
    return out


def _nodo(clave: str, valor: bytes = b"", tipo: int = 1, largo_valor: int = 0, hijos: tuple = ()) -> bytes:
    k = (clave + "\0").encode("utf-16-le")
    cab = 6 + len(k)
    p1 = (4 - cab % 4) % 4
    p2 = (4 - (cab + p1 + len(valor)) % 4) % 4 if hijos else 0
    cuerpo = b"".join(h + b"\0" * ((4 - len(h) % 4) % 4) for h in hijos)
    total = cab + p1 + len(valor) + p2 + len(cuerpo)
    return struct.pack("<HHH", total, largo_valor, tipo) + k + b"\0" * p1 + valor + b"\0" * p2 + cuerpo


def _numeros() -> tuple[int, int, int, int]:
    """La versión de Atlas del archivo VERSION (única fuente), en 4 números para Windows: 1.0 → (1, 0, 0, 0)."""
    try:
        txt = (ATLAS / "VERSION").read_text(encoding="utf-8-sig").strip()
        n = [int(x) for x in txt.split(".")] if txt and all(x.isdigit() for x in txt.split(".")) else []
    except OSError:
        n = []
    n = (n or [0])[:4]
    return tuple(min(x, 65535) for x in n + [0] * (4 - len(n)))  # type: ignore[return-value]


def _version() -> bytes:
    v = _numeros()
    txt = ".".join(map(str, v))
    fijo = struct.pack("<13I", 0xFEEF04BD, 0x10000, (v[0] << 16) | v[1], (v[2] << 16) | v[3], (v[0] << 16) | v[1],
                       (v[2] << 16) | v[3], 0x3F, 0, 0x40004, 1, 0, 0, 0)
    textos = {"CompanyName": "Atlas", "FileDescription": "Atlas", "FileVersion": txt, "InternalName": "Atlas",
              "OriginalFilename": "Atlas.exe", "ProductName": "Atlas", "ProductVersion": txt}
    tabla = _nodo("040904B0", hijos=tuple(_nodo(k, (s + "\0").encode("utf-16-le"), 1, len(s) + 1) for k, s in textos.items()))
    sfi = _nodo("StringFileInfo", hijos=(tabla,))
    vfi = _nodo("VarFileInfo", hijos=(_nodo("Translation", struct.pack("<HH", 0x0409, 0x04B0), 0, 4),))
    return _nodo("VS_VERSION_INFO", fijo, 0, len(fijo), (sfi, vfi))


def _icono() -> tuple[bytes, list[bytes]]:
    d = ICONO.read_bytes()
    _r, _t, n = struct.unpack_from("<HHH", d, 0)
    grupo, imagenes = struct.pack("<HHH", 0, 1, n), []
    for i in range(n):
        w, h, c, r, pl, bc, size, off = struct.unpack_from("<BBBBHHII", d, 6 + 16 * i)
        imagenes.append(d[off:off + size])
        grupo += struct.pack("<BBBBHHIH", w, h, c, r, pl, bc, size, i + 1)
    return grupo, imagenes


def crear(forzar: bool = False) -> Path:
    if not ORIGEN.exists():
        raise FileNotFoundError(ORIGEN)
    if DESTINO.exists() and not forzar and DESTINO.stat().st_mtime >= ORIGEN.stat().st_mtime:
        return DESTINO
    tmp = DESTINO.with_name("Atlas.exe.nuevo")
    shutil.copy2(ORIGEN, tmp)
    viejos = _recursos(tmp)
    grupo, imagenes = _icono()
    h = k32.BeginUpdateResourceW(str(tmp), False)
    if not h:
        raise OSError(ctypes.get_last_error(), "BeginUpdateResource")
    ok = True
    for tipo, n, l in viejos:  # fuera el ícono de Python y su versión
        ok &= bool(k32.UpdateResourceW(h, tipo, n, l, None, 0))
    for i, img in enumerate(imagenes, 1):
        b = ctypes.create_string_buffer(img, len(img))
        ok &= bool(k32.UpdateResourceW(h, RT_ICON, i, 1033, b, len(img)))
    b = ctypes.create_string_buffer(grupo, len(grupo))
    ok &= bool(k32.UpdateResourceW(h, RT_GROUP_ICON, 1, 1033, b, len(grupo)))
    ver = _version()
    b = ctypes.create_string_buffer(ver, len(ver))
    ok &= bool(k32.UpdateResourceW(h, RT_VERSION, 1, 1033, b, len(ver)))
    if not k32.EndUpdateResourceW(h, not ok) or not ok:
        tmp.unlink(missing_ok=True)
        raise OSError(ctypes.get_last_error(), "no pude escribir los recursos")
    os.replace(tmp, DESTINO)
    return DESTINO


if __name__ == "__main__":
    try:
        print(crear("--forzar" in sys.argv))
    except Exception as exc:  # noqa: BLE001
        print(f"No pude crear Atlas.exe: {exc}", file=sys.stderr)
        sys.exit(1)

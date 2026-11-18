"""Registro de Atlas (hud.log) sin datos personales y con fecha de vencimiento.

hud_server.py lo usa en lugar de abrir hud.log directo cuando corre sin consola (pythonw):

- Tapa correos, teléfonos, RUT, números de tarjeta y tokens largos en cada línea.
- Tapa el texto entre comillas ('…', "…", «…») y lo que viene después de los avisos que llevan
  contenido personal (correos leídos, WhatsApp, llamadas, recordatorios, consultas). Deja la
  estructura: hora, qué módulo, cuánto tardó, el error. Así sirve para diagnosticar sin guardar
  lo que usted dijo ni lo que leyó.
- Un archivo por día: hud.log es el de hoy; los anteriores pasan a logs\\hud-AAAA-MM-DD.log y se
  borran a los DIAS_LOG días.
- Las conversaciones del botón HISTORIAL (historial\\*.jsonl) se borran a los DIAS_HISTORIAL días.

Para diagnosticar un problema puntual con todo el texto, abra Atlas con Atlas-diagnostico.cmd: la
consola muestra todo y no se guarda en disco. O ponga ATLAS_LOG_COMPLETO=1 (no recomendado).
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

DIAS_LOG = 7
DIAS_HISTORIAL = 30

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TELEFONO = re.compile(r"(?<![\w.])\+?\(?\d[\d ()-]{7,}\d(?![\w.])")
_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_TOKEN = re.compile(r"\b[A-Za-z0-9_\-:]{32,}\b")
_COMILLAS = re.compile(r"'([^'\n]{4,})'|\"([^\"\n]{4,})\"|«([^»\n]{4,})»")
# Avisos cuyo contenido es personal: se deja el prefijo y se tapa el resto
_PERSONALES = re.compile(
    r"^(?P<pre>\s*(?:ruta directa \w+|herramienta \w+ ok=\w+|Usuario[^:]*:|Atlas(?! HUD)[^:]*:|respuesta[^:]*:|pregunta[^:]*:|"
    r"WhatsApp\b|Telegram\b|Discord\b|llamadas?\b|recordatorio\b|aviso\b|agenda:|calendario\b|Claude\b|"
    r"Nombres corregidos:|reescritura[^:]*:|transcripción limpiada[^:]*:|Orden directa[^:]*:|saludo[^:]*:|correo\b|"
    r"nota nueva|U-Cursos:))(?P<resto>.*)$",
    re.IGNORECASE,
)
# Rutas de archivos de Python en los errores (Traceback) no son personales: no se tocan
_RUTA_PY = re.compile(r'File "[^"]+\.py"')


def limpiar(linea: str) -> str:
    """Una línea del registro sin datos personales."""
    if os.environ.get("ATLAS_LOG_COMPLETO") == "1":
        return linea
    cabeza = ""
    m = re.match(r"^(\[HUD [0-9:]+\] ?)", linea)
    if m:
        cabeza, linea = m.group(1), linea[m.end():]
    rutas = _RUTA_PY.findall(linea)
    for i, r in enumerate(rutas):
        linea = linea.replace(r, f"\x00{i}\x00", 1)
    p = _PERSONALES.match(linea)
    if p and p.group("resto").strip():
        linea = p.group("pre") + f" [{len(p.group('resto').strip())} car. omitidos]"
    linea = _EMAIL.sub("[correo]", linea)
    linea = _RUT.sub("[rut]", linea)
    linea = _TOKEN.sub("[token]", linea)
    linea = _TELEFONO.sub(_tapar_telefono, linea)
    linea = _COMILLAS.sub(lambda mm: "'[" + str(len(next(g for g in mm.groups() if g))) + " car.]'", linea)
    for i, r in enumerate(rutas):
        linea = linea.replace(f"\x00{i}\x00", r, 1)
    return cabeza + linea


def _tapar_telefono(m: re.Match) -> str:
    s = m.group(0)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2})?", s.strip()) or sum(c.isdigit() for c in s) < 8:
        return s  # fechas y números cortos no son teléfonos
    return "[teléfono]"


class RegistroPrivado:
    """Archivo de texto que filtra cada línea y cambia de archivo cada día. Se usa como sys.stdout."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, carpeta: Path, nombre: str = "hud.log") -> None:
        self.carpeta = Path(carpeta)
        self.ruta = self.carpeta / nombre
        self.viejos = self.carpeta / "logs"
        self._lock = threading.Lock()
        self._pendiente = ""
        self._dia = ""
        self._f = None
        self._abrir()

    # -- archivo del día
    def _abrir(self) -> None:
        hoy = time.strftime("%Y-%m-%d")
        if self.ruta.exists():
            dia_archivo = time.strftime("%Y-%m-%d", time.localtime(self.ruta.stat().st_mtime))
            if dia_archivo != hoy:
                self._archivar(dia_archivo)
        self._dia = hoy
        self._f = open(self.ruta, "a", encoding="utf-8", buffering=1)

    def _archivar(self, dia: str) -> None:
        """Pasa hud.log a logs/hud-<dia>.log, limpio de datos personales, y borra los vencidos."""
        self.viejos.mkdir(exist_ok=True)
        destino = self.viejos / f"hud-{dia}.log"
        try:
            with open(self.ruta, encoding="utf-8", errors="replace") as src, \
                    open(destino, "a", encoding="utf-8") as dst:
                for ln in src:
                    dst.write(limpiar(ln.rstrip("\n")) + "\n")
            self.ruta.unlink()
        except OSError:
            return
        limite = time.time() - DIAS_LOG * 86400
        for f in self.viejos.glob("hud-*.log"):
            try:
                if f.stat().st_mtime < limite:
                    f.unlink()
            except OSError:
                pass

    # -- interfaz de archivo
    def write(self, texto: str) -> int:
        with self._lock:
            self._pendiente += texto
            while "\n" in self._pendiente:
                linea, self._pendiente = self._pendiente.split("\n", 1)
                if time.strftime("%Y-%m-%d") != self._dia:
                    self._f.close()
                    self._abrir()
                self._f.write(limpiar(linea) + "\n")
        return len(texto)

    def flush(self) -> None:
        with self._lock:
            if self._f:
                self._f.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._f.fileno()


def limpiar_historial(carpeta: Path, dias: int = DIAS_HISTORIAL) -> int:
    """Borra las conversaciones del HISTORIAL de más de `dias` días. Devuelve cuántas borró."""
    limite = time.time() - dias * 86400
    n = 0
    for f in Path(carpeta).glob("*.jsonl"):
        try:
            if f.stat().st_mtime < limite:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


def preparar_registro_existente(carpeta: Path) -> None:
    """Limpia una sola vez el hud.log que ya existía (antes de este cambio) y lo archiva."""
    ruta = Path(carpeta) / "hud.log"
    marca = Path(carpeta) / "logs" / ".hud_log_limpio"
    if marca.exists() or not ruta.exists():
        return
    r = RegistroPrivado.__new__(RegistroPrivado)
    r.carpeta, r.ruta, r.viejos = Path(carpeta), ruta, Path(carpeta) / "logs"
    r._archivar(time.strftime("%Y-%m-%d", time.localtime(ruta.stat().st_mtime)) + "-antes")
    marca.parent.mkdir(exist_ok=True)
    marca.write_text("hud.log anterior limpiado y archivado", encoding="utf-8")

"""Intérprete de órdenes con Claude Haiku (23-11-2026).

Cuando ninguna regla fija de Atlas entiende una frase, antes la reescribía el modelo local (Qwen) como una orden
directa. Ahora la reescribe Haiku, que entiende mejor y responde más rápido; las reglas de Atlas siguen ejecutando
todo en el PC. Si Haiku no está disponible (sin clave, sin internet, apagado, tope de gasto), sigue Qwen como antes.

Qué sale del PC hacia Anthropic (y nada más):
- la frase que el usuario acaba de decir y, como contexto, sus frases anteriores recientes;
- nunca las respuestas de Atlas (pueden traer correos, agenda o finanzas), ni la historia personal (Cronos);
- antes de enviar, un código fijo cambia montos, RUT, correos, tarjetas y teléfonos por etiquetas (MONTO_1, RUT_1…)
  y los vuelve a poner en la orden que llega de vuelta.

Cada envío queda anotado en hud/haiku_enviado.log, y el gasto del mes en hud/haiku_gasto.json.

Interruptor: ajustes.json  "interprete": {"haiku": "apagado"}  (o la rueda de ajustes, o ATLAS_HAIKU=0).
Clave: Guardar-clave-Haiku.cmd la deja en el Administrador de credenciales de Windows (entrada Atlas-Haiku-API).

Sin dependencias: Atlas no trae instalado el SDK de Anthropic (es un extra opcional de OpenJarvis), así que la
llamada va por HTTPS con la librería estándar, igual que la de Ollama.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
URL = "https://api.anthropic.com/v1/messages"
VERSION_API = "2026-10-21"
MODELO = "claude-haiku-5-5"
SECRETO = "Atlas-Haiku-API"
# USD por millón de tokens de Claude Haiku 5.5 (entrada, salida). Solo se usa para el tope de gasto local.
PRECIO_ENTRADA, PRECIO_SALIDA = 0.10, 0.50
TOPE_USD_MES = 5.0
ESPERA_SEG = 4.0
PAUSA_TRAS_FALLA = 60       # sin internet o error del servicio: no insistir en cada frase
PAUSA_CLAVE_MALA = 600      # clave rechazada: no insistir por 10 minutos
REGISTRO = "haiku_enviado.log"
GASTO = "haiku_gasto.json"
_REGISTRO_MAX = 400_000     # bytes; al pasar, se conserva la mitad más nueva

_lock = threading.Lock()
_pausa_hasta = 0.0
_pausa_motivo = ""
_clave_cache: tuple[float, Optional[str]] = (0.0, None)

AGREGADO = """

Datos ocultos: las palabras como MONTO_1, RUT_1, CORREO_1, TARJETA_1, TELEFONO_1 o NUMERO_1 reemplazan datos privados del usuario. Cópialas tal cual en la orden cuando correspondan; no las expliques ni las cambies.
Si te llegan «Frases anteriores del usuario», son solo contexto para entender a qué se refiere ahora: la orden es la de «Lo que dijo ahora»."""


# ----------------------------------------------------------------------------- enmascarado
_NUM = (r"(?:un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|"
        r"dieci(?:seis|séis|siete|ocho|nueve)|veinte|veinti\w+|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|"
        r"noventa|cien|ciento|doscient[oa]s|trescient[oa]s|cuatrocient[oa]s|quinient[oa]s|seiscient[oa]s|"
        r"setecient[oa]s|ochocient[oa]s|novecient[oa]s|mil|medio|media)")
_CANT = rf"(?:\d[\d.,]*\d|\d|{_NUM}(?:\s+(?:y\s+)?{_NUM})*)"
_MONEDA = r"(?:lucas?|lukas?|pesos?|palos?|gambas?|d[oó]lares|d[oó]lar|usd|clp|uf|euros?)"
_PATRONES: list[tuple[str, re.Pattern]] = [
    ("CORREO", re.compile(r"[\w.+-]+\s?@\s?[\w-]+(?:\s?\.\s?[\w-]+)+"
                          r"|[\w.+-]+(?:\s+[\w.+-]+)?\s+arroba\s+[\w-]+(?:\s+punto\s+[\w-]+)+", re.I)),
    ("TARJETA", re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])")),
    ("RUT", re.compile(r"(?<![\w.])\d{1,2}\.?\d{3}\.?\d{3}\s?(?:-|gui[oó]n)\s?[\dkK](?!\w)"
                       r"|(?<![\w.])\d{7,8}[kK](?!\w)", re.I)),
    ("TELEFONO", re.compile(r"(?<![\w-])(?:\+\d{1,3}[ -]?)?(?:\(?\d{1,2}\)?[ -]?)?9[ -]?\d{4}[ -]?\d{4}(?![\w-])"
                            r"|(?<!\w)\+\d{8,15}(?!\w)")),
    ("MONTO", re.compile(rf"\$\s?\d[\d.,]*(?:\s*(?:mil(?:lones)?|mill[oó]n)\b)?"
                         rf"|(?<!\w){_CANT}\s+(?:(?:mil|mill[oó]n|millones)\s+(?:de\s+)?)?{_MONEDA}\b"
                         rf"|(?<!\w)\d[\d.,]*\s*(?:mil|mill[oó]n|millones)\b"
                         rf"|(?<!\w){_NUM}(?:\s+(?:y\s+)?{_NUM})*\s+(?:mil|mill[oó]n|millones)\b", re.I)),
    # Auditoría 24-11-2026: cualquier cifra de 5 o más dígitos (montos sin «pesos», cuentas, RUT sin guion,
    # teléfonos fijos). No toca horas, duraciones ni fechas tipo 2026-11-24.
    ("NUMERO", re.compile(r"(?<![\w.,-])(?!\d{4}-\d{1,2}-\d{1,2}(?!\d))(?:\d[ .,-]?){4,}\d[kK]?(?![\w-])")),
]
_ETIQUETA = re.compile(r"\b(CORREO|TARJETA|RUT|TELEFONO|MONTO|NUMERO)_(\d+)\b", re.I)


def enmascarar(texto: str, mapa: Optional[dict] = None) -> tuple[str, dict]:
    """Cambia montos, RUT, correos, tarjetas y teléfonos por etiquetas. -> (texto con etiquetas, {etiqueta: original}).
    Con `mapa` se sigue usando el mismo (para varias frases de una conversación: el mismo dato, la misma etiqueta)."""
    mapa = {} if mapa is None else mapa
    inverso = {v.lower(): k for k, v in mapa.items()}

    def cambiar(tipo: str):
        def f(m: re.Match) -> str:
            original = m.group(0)
            if _ETIQUETA.fullmatch(original.strip()):
                return original
            etiqueta = inverso.get(original.lower())
            if not etiqueta:
                n = 1 + sum(1 for k in mapa if k.startswith(tipo + "_"))
                etiqueta = f"{tipo}_{n}"
                mapa[etiqueta] = original
                inverso[original.lower()] = etiqueta
            return etiqueta
        return f

    out = texto or ""
    for tipo, pat in _PATRONES:
        out = pat.sub(cambiar(tipo), out)
    return out, mapa


def desenmascarar(texto: str, mapa: dict) -> Optional[str]:
    """Vuelve a poner los datos reales. None si el texto trae una etiqueta que no existe (Haiku la inventó)."""
    malas = []

    def f(m: re.Match) -> str:
        k = f"{m.group(1).upper()}_{m.group(2)}"
        if k not in mapa:
            malas.append(k)
            return m.group(0)
        return mapa[k]

    out = _ETIQUETA.sub(f, texto or "")
    return None if malas else out


# ----------------------------------------------------------------------------- ajustes, clave y gasto
def _ajuste(clave: str, default):
    try:
        import atlas_ajustes as AJ

        if clave == "interprete.haiku":
            # Auditoría 24-11-2026: si ajustes.json existe pero está roto, no se sabe si el usuario apagó
            # Haiku; ante la duda, apagado (antes valía el predeterminado «encendido»).
            try:
                if AJ.FILE.exists():
                    json.loads(AJ.FILE.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return "apagado"
        return AJ.get(clave, default)
    except Exception:  # noqa: BLE001
        return "apagado" if clave == "interprete.haiku" else default


def encendido() -> bool:
    if os.environ.get("ATLAS_HAIKU", "1") == "0":
        return False
    v = _ajuste("interprete.haiku", "encendido")
    return v is True or str(v).strip().lower() in ("encendido", "si", "sí", "true", "1", "on")


def _numero(clave: str, default: float, minimo: float) -> float:
    try:
        v = float(_ajuste(clave, default))
    except (TypeError, ValueError):
        return default
    return v if v >= minimo else default


def _clave() -> Optional[str]:
    """La clave de API, desde el Administrador de credenciales de Windows. Se relee cada minuto."""
    global _clave_cache
    if os.environ.get("ATLAS_PRUEBAS") == "1":
        return None  # auditoría 24-11-2026: las suites nunca usan la clave real ni llaman a Anthropic
    if time.time() - _clave_cache[0] < 60:
        return _clave_cache[1]
    valor = None
    try:
        from openjarvis.security import atlas_secretos as SEC

        valor = (SEC.leer(SECRETO) or "").strip() or None
    except Exception:  # noqa: BLE001
        valor = None
    _clave_cache = (time.time(), valor)
    return valor


def olvidar_clave() -> None:
    global _clave_cache, _pausa_hasta, _pausa_motivo
    _clave_cache = (0.0, None)
    _pausa_hasta, _pausa_motivo = 0.0, ""


_usd_memoria: dict[str, float] = {}   # lo gastado en esta sesión, por mes: no se pierde si el archivo falla


def gasto() -> dict:
    """El gasto de este mes: {"mes", "llamadas", "entrada", "salida", "usd"} (+ "roto": True si el archivo está dañado)."""
    mes = time.strftime("%Y-%m")
    base = {"mes": mes, "llamadas": 0, "entrada": 0, "salida": 0, "usd": 0.0}
    f = HERE / GASTO
    if not f.exists():
        return base
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("no es un objeto")
        if d.get("mes") != mes:
            return base
        for k, v in base.items():
            d.setdefault(k, v)
        d["usd"] = float(d["usd"])
        return d
    except Exception:  # noqa: BLE001
        return {**base, "roto": True}


def _sobre_tope(tope: float) -> Optional[str]:
    """Motivo si no se debe llamar por gasto; None si se puede. Falla cerrado (auditoría 24-11-2026)."""
    g = gasto()
    if g.get("roto"):
        return f"el archivo {GASTO} está dañado; bórrelo para reiniciar la cuenta del mes"
    if max(float(g["usd"]), _usd_memoria.get(g["mes"], 0.0)) >= tope:
        return f"se alcanzó el tope de {tope:g} dólares de este mes"
    return None


def _sumar_gasto(uso: dict) -> float:
    entrada = int(uso.get("input_tokens") or 0)
    creada = int(uso.get("cache_creation_input_tokens") or 0)
    leida = int(uso.get("cache_read_input_tokens") or 0)
    salida = int(uso.get("output_tokens") or 0)
    usd = ((entrada + creada * 1.25 + leida * 0.1) * PRECIO_ENTRADA + salida * PRECIO_SALIDA) / 1_000_000
    with _lock:
        mes = time.strftime("%Y-%m")
        _usd_memoria[mes] = _usd_memoria.get(mes, 0.0) + usd
        d = gasto()
        if d.pop("roto", False):
            return usd  # no pisar un archivo dañado: el tope ya bloquea hasta que el usuario lo revise
        d["llamadas"] += 1
        d["entrada"] += entrada + creada + leida
        d["salida"] += salida
        d["usd"] = round(float(d["usd"]) + usd, 6)
        try:
            tmp = HERE / (GASTO + ".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(HERE / GASTO)
        except OSError:
            pass
    return usd


def _anotar(linea: dict) -> None:
    """Una línea por envío en haiku_enviado.log: exactamente lo que salió del PC y lo que volvió."""
    try:
        f = HERE / REGISTRO
        with _lock:
            if f.exists() and f.stat().st_size > _REGISTRO_MAX:
                datos = f.read_bytes()[-_REGISTRO_MAX // 2:]
                f.write_bytes(datos[datos.find(b"\n") + 1:])
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"cuando": time.strftime("%Y-%m-%d %H:%M:%S"), **linea}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _registro_ok() -> bool:
    """¿Se puede anotar en haiku_enviado.log? Si no, no se envía (auditoría 24-11-2026)."""
    try:
        with (HERE / REGISTRO).open("a", encoding="utf-8"):
            return True
    except OSError:
        return False


def estado() -> dict:
    """Para diagnóstico: por qué se usaría o no Haiku en este momento."""
    g = gasto()
    tope = _numero("interprete.tope_usd_mes", TOPE_USD_MES, 0.01)
    motivo = ""
    if not encendido():
        motivo = "apagado en los ajustes"
    elif not _clave():
        motivo = "falta la clave (Guardar-clave-Haiku.cmd)"
    elif _sobre_tope(tope):
        motivo = _sobre_tope(tope) or ""
    elif time.time() < _pausa_hasta:
        motivo = _pausa_motivo
    return {"disponible": not motivo, "motivo": motivo, "gasto": g, "tope_usd_mes": tope, "modelo": MODELO}


# ----------------------------------------------------------------------------- la traducción
_CONFIRMA = re.compile(r"(?:s[ií]|ya|ok(?:ey)?|okay|dale|bueno|hazlo|h[aá]galo|eso|claro|correcto|exacto|confirm[oa]|"
                       r"por favor|porfa|no|nop|mejor no|cancela(?:lo)?)(?:[\s,]+(?:s[ií]|dale|hazlo|por favor|porfa|"
                       r"gracias|no|se[nñ]or|atlas))*")


def _plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _es_privado(texto: str) -> bool:
    """¿Salió de la historia personal (Cronos)? Si no se puede saber, se trata como privado."""
    try:
        import atlas_historia

        return bool(atlas_historia.es_privado(texto))
    except Exception:  # noqa: BLE001
        return True


def _pedir(clave: str, sistema: str, usuario: str, espera: float) -> dict:
    cuerpo = json.dumps({
        "model": MODELO,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},         # una traducción corta: sin razonamiento, para que tarde lo mínimo
        "output_config": {"effort": "low"},
        "system": [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": usuario}],
    }).encode("utf-8")
    req = urllib.request.Request(URL, data=cuerpo, headers={
        "Content-Type": "application/json", "x-api-key": clave, "anthropic-version": VERSION_API})
    with urllib.request.urlopen(req, timeout=espera) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _pausar(seg: float, motivo: str) -> None:
    global _pausa_hasta, _pausa_motivo
    _pausa_hasta, _pausa_motivo = time.time() + seg, motivo


def traducir(texto: str, historial: list[tuple[str, str]] | None, instrucciones: str,
             log: Callable[[str], None] | None = None) -> Optional[str]:
    """La frase -> una orden directa, con Haiku.

    Devuelve la orden, "" si es conversación (CHARLA), o None si Haiku no se usó o falló: ahí sigue el modelo local.
    `historial` son los últimos turnos [(rol, texto)]; de ahí solo viajan las frases del usuario."""
    log = log or (lambda _m: None)
    texto = (texto or "").strip()
    if not texto or not encendido():
        return None
    if _CONFIRMA.fullmatch(_plano(texto).strip(" .,!¡¿?")):
        return None  # «sí», «dale», «hazlo»: depende de lo que Atlas propuso, y eso no sale del PC
    clave = _clave()
    if not clave:
        return None
    if time.time() < _pausa_hasta:
        return None
    tope = _numero("interprete.tope_usd_mes", TOPE_USD_MES, 0.01)
    motivo_tope = _sobre_tope(tope)
    if motivo_tope:
        log(f"  Haiku: {motivo_tope}; sigue el modelo local")
        _pausar(PAUSA_CLAVE_MALA, motivo_tope)
        return None
    if not _registro_ok():
        log("  Haiku: no se puede escribir haiku_enviado.log; no se envía nada sin dejarlo anotado")
        return None

    mapa: dict = {}
    antes = [c for r, c in (historial or [])[-4:] if r == "user" and c and not _es_privado(c)][-2:]
    antes_m = [enmascarar(c[:300], mapa)[0] for c in antes]
    ahora_m, _ = enmascarar(texto[:600], mapa)
    usuario = ("Frases anteriores del usuario:\n" + "".join(f"- {c}\n" for c in antes_m) + "\n" if antes_m else "") \
        + f"Lo que dijo ahora: {ahora_m}"

    t0 = time.time()
    try:
        resp = _pedir(clave, instrucciones + AGREGADO, usuario, _numero("interprete.espera_seg", ESPERA_SEG, 1))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            _pausar(PAUSA_CLAVE_MALA, "Anthropic rechazó la clave (revísela con Guardar-clave-Haiku.cmd)")
            log("  Haiku: la clave fue rechazada; sigue el modelo local")
        else:
            detalle = ""
            try:
                detalle = str((json.loads(exc.read().decode("utf-8")).get("error") or {}).get("message", ""))[:160]
            except Exception:  # noqa: BLE001
                pass
            _pausar(PAUSA_TRAS_FALLA, f"el servicio respondió con error {exc.code}")
            log(f"  Haiku: error {exc.code} {detalle}; sigue el modelo local")
        _anotar({"enviado": usuario, "error": f"HTTP {exc.code}"})
        return None
    except Exception as exc:  # noqa: BLE001  (sin internet, tiempo de espera, respuesta rota)
        _pausar(PAUSA_TRAS_FALLA, "sin conexión con Anthropic")
        log(f"  Haiku: sin respuesta ({type(exc).__name__}); sigue el modelo local")
        _anotar({"enviado": usuario, "error": type(exc).__name__})
        return None

    ms = int((time.time() - t0) * 1000)
    usd = _sumar_gasto(resp.get("usage") or {})
    bruto = "".join(b.get("text", "") for b in (resp.get("content") or []) if isinstance(b, dict) and b.get("type") == "text")
    _anotar({"enviado": usuario, "recibido": bruto[:400], "ms": ms, "usd": round(usd, 6),
             "tokens": {k: v for k, v in (resp.get("usage") or {}).items() if isinstance(v, int)}})
    if resp.get("stop_reason") == "refusal" or not bruto.strip():
        log("  Haiku: no dio una orden; sigue el modelo local")
        return None
    linea = bruto.strip().splitlines()[0].strip()
    linea = re.sub(r"^(?:orden|->)\s*:?\s*", "", linea, flags=re.I).strip(" «»\"'")
    if not linea or re.fullmatch(r"(?i)charla\.?", linea):
        log(f"  Haiku ({ms} ms): CHARLA")
        return ""
    orden = desenmascarar(linea, mapa)
    if orden is None:
        log("  Haiku: devolvió una etiqueta que no existe; sigue el modelo local")
        return None
    log(f"  Haiku ({ms} ms)")
    return orden[:300]

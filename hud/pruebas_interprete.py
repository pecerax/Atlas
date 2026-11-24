"""Pruebas del intérprete con Haiku (atlas_interprete.py). No llaman a Anthropic ni tocan credenciales reales.

Uso: Probar-Haiku.cmd, o  python pruebas_interprete.py
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_interprete as IH  # noqa: E402

PROMPT = "Traduces lo que dijo el usuario a UNA orden directa. Si no pide nada: CHARLA."


def _resp(texto: str, entrada: int = 700, salida: int = 12, stop: str = "end_turn") -> dict:
    return {"content": [{"type": "text", "text": texto}] if texto else [], "stop_reason": stop,
            "usage": {"input_tokens": entrada, "output_tokens": salida}}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atlas_haiku_"))
    IH.HERE = tmp
    ajustes = {"interprete.haiku": "encendido"}
    IH._ajuste = lambda clave, default: ajustes.get(clave, default)
    IH._clave = lambda: "clave-de-prueba"
    IH._es_privado = lambda t: "cronos" in t.lower()
    enviados: list[tuple[str, str]] = []
    respuesta = {"v": _resp("llama a Felipe")}

    def pedir(clave, sistema, usuario, espera):
        enviados.append((sistema, usuario))
        if isinstance(respuesta["v"], Exception):
            raise respuesta["v"]
        return respuesta["v"]

    IH._pedir = pedir
    res: list[tuple[str, list[str]]] = []

    def caso(nombre: str, errs: list[str]) -> None:
        res.append((nombre, errs))

    def limpio() -> None:
        enviados.clear()
        IH._pausa_hasta = 0.0
        ajustes.clear()
        ajustes["interprete.haiku"] = "encendido"

    # --- enmascarado
    errs = []
    casos = {
        "mándale a Benji que le deposité 50 lucas": ["50 lucas"],
        "transfiere $25.000 a la cuenta": ["$25.000"],
        "le debo cincuenta mil pesos al Pipe": ["cincuenta mil pesos"],
        "pagué 2 millones de pesos": ["2 millones de pesos"],
        "anota que gasté 15 mil en el súper": ["15 mil"],
        "mi rut es 12.345.678-9 y el de ella 9876543-K": ["12.345.678-9", "9876543-K"],
        "escríbele a juan.perez@gmail.com": ["juan.perez@gmail.com"],
        "la tarjeta es 4111 1111 1111 1111": ["4111 1111 1111 1111"],
        "su número es +56 9 8765 4321": ["+56 9 8765 4321"],
        "llámalo al 987654321": ["987654321"],
        "cuesta 3 UF": ["3 UF"],
        # auditoría 24-11-2026: fugas que antes pasaban
        "mi rut es 12345678K": ["12345678K"],
        "el rut es 12.345.678 guion k": ["12.345.678 guion k"],
        "anota que gasté 15000": ["15000"],
        "el sueldo es de 1.200.000": ["1.200.000"],
        "le debo cincuenta mil al Pipe": ["cincuenta mil"],
        "llama al 22 345 6789": ["22 345 6789"],
        "la cuenta es 00123456789": ["00123456789"],
        "escríbele a juan perez arroba gmail punto com": ["arroba gmail"],
        "escríbele a juan @ gmail.com": ["gmail.com"],
    }
    for frase, ocultos in casos.items():
        m, mapa = IH.enmascarar(frase)
        for o in ocultos:
            if o in m:
                errs.append(f"«{frase}»: no ocultó {o!r} -> {m!r}")
        if IH.desenmascarar(m, mapa) != frase:
            errs.append(f"«{frase}»: al devolver los datos quedó {IH.desenmascarar(m, mapa)!r}")
    caso("oculta montos, RUT, correos, tarjetas y teléfonos, y los devuelve", errs)

    errs = []
    for frase in ("pon una alarma a las 5", "recuérdame en 10 minutos llamar al dentista", "agenda dentista el 23 de noviembre a las 15:30",
                  "pon un temporizador de 2 horas", "¿qué tengo el 2026-11-24?", "llama a Felipe", "ponme música de Los Tres",
                  "sube el volumen a 40", "¿cuánto he gastado este mes?", "una reunión con la Cata mañana"):
        m, mapa = IH.enmascarar(frase)
        if m != frase or mapa:
            errs.append(f"«{frase}» no debía cambiar -> {m!r}")
    caso("no toca horas, fechas, nombres ni duraciones", errs)

    errs = []
    mapa: dict = {}
    a, _ = IH.enmascarar("le deposité 50 lucas", mapa)
    b, _ = IH.enmascarar("dile que son 50 lucas y no 30 lucas", mapa)
    if "MONTO_1" not in a or "MONTO_1" not in b or "MONTO_2" not in b:
        errs.append(f"mismo dato, misma etiqueta: {a!r} / {b!r}")
    if IH.desenmascarar("envía MONTO_7 a Benji", mapa) is not None:
        errs.append("una etiqueta inventada debe anular la orden")
    if IH.desenmascarar("envía monto_1 a Benji", mapa) != "envía 50 lucas a Benji":
        errs.append("la etiqueta en minúsculas también se devuelve")
    caso("etiquetas estables entre frases; una inventada anula la orden", errs)

    # --- qué viaja
    errs = []
    limpio()
    respuesta["v"] = _resp("envía te deposité MONTO_1 por WhatsApp a Benji")
    hist = [("user", "quiero avisarle al Benji"), ("assistant", "Señor, su saldo es $1.234.567 y tiene 3 correos del banco"),
            ("user", "lo de cronos del sábado"), ("assistant", "El sábado estuvo en Valparaíso")]
    out = IH.traducir("eh mándale al Benji que le deposité 50 lucas", hist, PROMPT)
    if out != "envía te deposité 50 lucas por WhatsApp a Benji":
        errs.append(f"orden devuelta: {out!r}")
    sistema, usuario = enviados[-1] if enviados else ("", "")
    for prohibido in ("50 lucas", "1.234.567", "saldo", "Valparaíso", "cronos", "correos del banco"):
        if prohibido in usuario or prohibido in sistema:
            errs.append(f"viajó {prohibido!r}: {usuario!r}")
    if "quiero avisarle al Benji" not in usuario or "MONTO_1" not in usuario:
        errs.append(f"debía viajar la frase anterior del usuario y la etiqueta: {usuario!r}")
    if "MONTO_1" not in sistema or PROMPT not in sistema:
        errs.append("las instrucciones deben explicar las etiquetas")
    reg = (tmp / IH.REGISTRO).read_text(encoding="utf-8") if (tmp / IH.REGISTRO).exists() else ""
    if "MONTO_1" not in reg or "50 lucas" in reg:
        errs.append(f"el registro debe anotar lo enviado (con etiquetas): {reg!r}")
    caso("solo viajan las frases del usuario, enmascaradas; queda en el registro", errs)

    # --- respuestas
    errs = []
    limpio()
    for texto, esperado in (("CHARLA", ""), ("charla.", ""), ("«llama a Felipe»", "llama a Felipe"), ("Orden: llama a Felipe\nporque sí", "llama a Felipe"),
                            ("-> pon música de Queen", "pon música de Queen")):
        respuesta["v"] = _resp(texto)
        out = IH.traducir("el Felipe, llámalo", [], PROMPT)
        if out != esperado:
            errs.append(f"{texto!r} -> {out!r}, esperaba {esperado!r}")
    respuesta["v"] = _resp("", stop="refusal")
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None:
        errs.append("una negativa debe dejar al modelo local")
    respuesta["v"] = _resp("envía MONTO_3 a Benji")
    if IH.traducir("mándale 50 lucas al Benji", [], PROMPT) is not None:
        errs.append("una etiqueta inventada debe dejar al modelo local")
    caso("lee la orden, CHARLA y las negativas", errs)

    # --- cuándo no se usa
    errs = []
    limpio()
    respuesta["v"] = _resp("llama a Felipe")
    for frase in ("sí", "Dale", "hazlo, por favor", "no", "ok", "Sí, dale."):
        n = len(enviados)
        if IH.traducir(frase, [("assistant", "¿Le mando el mensaje?")], PROMPT) is not None or len(enviados) != n:
            errs.append(f"«{frase}» no debe viajar (depende de lo que Atlas propuso)")
    ajustes["interprete.haiku"] = "apagado"
    n = len(enviados)
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or len(enviados) != n:
        errs.append("apagado en ajustes: no debe llamar")
    limpio()
    clave_ok = IH._clave
    IH._clave = lambda: None
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or enviados:
        errs.append("sin clave: no debe llamar")
    if IH.estado()["disponible"] or "clave" not in IH.estado()["motivo"]:
        errs.append(f"estado sin clave: {IH.estado()}")
    IH._clave = clave_ok
    caso("confirmaciones, apagado y sin clave: sigue el modelo local", errs)

    # --- fallas y pausa
    errs = []
    limpio()
    respuesta["v"] = TimeoutError("lento")
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None:
        errs.append("sin respuesta: debe devolver None")
    n = len(enviados)
    respuesta["v"] = _resp("llama a Felipe")
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or len(enviados) != n:
        errs.append("tras una falla no debe insistir de inmediato")
    limpio()
    respuesta["v"] = urllib.error.HTTPError(IH.URL, 401, "no", None, io.BytesIO(b'{"error":{"message":"invalid x-api-key"}}'))
    IH.traducir("el Felipe, llámalo", [], PROMPT)
    if "clave" not in IH.estado()["motivo"]:
        errs.append(f"clave rechazada: {IH.estado()['motivo']!r}")
    limpio()
    respuesta["v"] = urllib.error.HTTPError(IH.URL, 529, "no", None, io.BytesIO(b"{}"))
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or IH.estado()["disponible"]:
        errs.append("error del servicio: debe pausar")
    caso("sin internet, clave rechazada o servicio caído: pausa y sigue el modelo local", errs)

    # --- gasto y tope
    errs = []
    limpio()
    (tmp / IH.GASTO).unlink(missing_ok=True)
    respuesta["v"] = _resp("llama a Felipe", entrada=1_000_000, salida=1_000_000)
    IH.traducir("el Felipe, llámalo", [], PROMPT)
    g = IH.gasto()
    if abs(g["usd"] - 0.60) > 1e-6 or g["llamadas"] != 1:
        errs.append(f"gasto de 1M + 1M tokens debía ser 0,60 USD: {g}")
    ajustes["interprete.tope_usd_mes"] = 0.5
    n = len(enviados)
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or len(enviados) != n:
        errs.append("sobre el tope no debe llamar")
    if "tope" not in IH.estado()["motivo"]:
        errs.append(f"estado con tope: {IH.estado()['motivo']!r}")
    (tmp / IH.GASTO).write_text(json.dumps({"mes": "2020-01", "llamadas": 9, "entrada": 9, "salida": 9, "usd": 99}), encoding="utf-8")
    if IH.gasto()["usd"] != 0:
        errs.append("el gasto de otro mes no cuenta")
    (tmp / IH.GASTO).write_text("{roto", encoding="utf-8")
    ajustes["interprete.tope_usd_mes"] = 5
    IH._usd_memoria.clear()
    n = len(enviados)
    if IH.traducir("el Felipe, llámalo", [], PROMPT) is not None or len(enviados) != n:
        errs.append("con el archivo de gasto dañado no debe llamar (falla cerrado)")
    (tmp / IH.GASTO).unlink(missing_ok=True)
    caso("lleva el gasto del mes y respeta el tope", errs)

    # --- cuerpo de la petición
    errs = []
    capt = {}

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(_resp("ok")).encode()

    def falso(req, timeout=0):
        capt["cuerpo"] = json.loads(req.data.decode())
        capt["cab"] = {k.lower(): v for k, v in req.header_items()}
        capt["url"], capt["espera"] = req.full_url, timeout
        return _R()

    orig = IH.urllib.request.urlopen
    IH.urllib.request.urlopen = falso
    try:
        IH.__dict__["_pedir"] = _PEDIR_REAL
        IH._pedir("k123", "sis", "usu", 4)
    finally:
        IH.urllib.request.urlopen = orig
    c = capt.get("cuerpo", {})
    if c.get("model") != "claude-haiku-5-5" or c.get("thinking") != {"type": "disabled"} or c.get("output_config") != {"effort": "low"}:
        errs.append(f"cuerpo: {c}")
    if any(k in c for k in ("temperature", "top_p", "top_k")):
        errs.append("no debe mandar temperature/top_p/top_k (Haiku 5.5 los rechaza)")
    if capt.get("cab", {}).get("x-api-key") != "k123" or "anthropic-version" not in capt.get("cab", {}) or capt.get("url") != "https://api.anthropic.com/v1/messages":
        errs.append(f"cabeceras o dirección: {capt.get('cab')} {capt.get('url')}")
    caso("la petición a Anthropic tiene la forma correcta", errs)

    shutil.rmtree(tmp, ignore_errors=True)
    fallas = 0
    for nombre, errs in res:
        if errs:
            fallas += 1
            print(f"  FALLA  {nombre}")
            for e in errs:
                print(f"         - {e}")
        else:
            print(f"  ok     {nombre}")
    print(f"\n{len(res) - fallas} de {len(res)} pruebas pasaron." + ("" if not fallas else f"  {fallas} FALLARON."))
    return 1 if fallas else 0


_PEDIR_REAL = IH._pedir

if __name__ == "__main__":
    sys.exit(main())

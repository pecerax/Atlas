"""Botón «?» de la pantalla principal: instalación de Atlas paso a paso (diseño 2 elegido el 17-11-2026).

Cada paso de la guía de instalación (INSTALL.md) trae sus sistemas con el estado detectado en este PC, qué
permite, cómo completarlo y botones. Solo LEE estados (archivos, módulos, Ollama); nunca cambia nada.
  estado  "g" listo · "y" a medias · "x" falta
Las instrucciones marcan con `acentos graves` lo que se escribe o ejecuta (la ventana lo muestra como código).
Botones: {"texto", "tipo": "dicho" (le dice algo a Atlas) | "app" (abre una app del riel) | "abrir" (id de ABRIR) |
"revisar", "valor", "primario"}.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import urllib.request
from pathlib import Path

HUD = Path(__file__).resolve().parent
OJ = HUD.parent                                   # %LOCALAPPDATA%\Atlas
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(OJ.parent)))
CONN = Path(os.path.expanduser("~")) / ".atlas" / "connectors"
HISTORIA_CFG = OJ / "apps" / "cronos" / "config.json"
PIPER = ("es_ES-davefx-medium", "en_GB-alan-medium")

# lo único que pueden abrir los botones «abrir»: la ventana solo manda el id
ABRIR = {
    "carpeta": lambda: str(OJ),
    "ollama": lambda: "https://ollama.com/download",
    "bluetooth": lambda: "ms-settings:bluetooth",
    "enlace": lambda: r"shell:AppsFolder\Microsoft.YourPhone_8wekyb3d8bbwe!App",
    "extras": lambda: str(OJ / "Instalar-extras.cmd"),
    "parakeet": lambda: str(OJ / "Instalar-parakeet.cmd"),
    "correo": lambda: str(OJ / "Agregar-correo.cmd"),
    "diag_correo": lambda: str(OJ / "Diagnostico-correo.cmd"),
    "google": lambda: str(OJ / "Conectar-Google-Calendar.cmd"),
    "calendario": lambda: str(OJ / "Agregar-calendario.cmd"),
}


def destino(clave: str) -> str:
    """Qué abre el botón «abrir» con ese id ("" si no existe)."""
    f = ABRIR.get(str(clave))
    return f() if f else ""


def _ollama_tags() -> list[dict] | None:
    """Modelos de Ollama, o None si Ollama no responde."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as r:  # noqa: S310
            return json.loads(r.read()).get("models") or []
    except Exception:  # noqa: BLE001
        return None


def _modulo(nombre: str) -> bool:
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _version_en_disco() -> str:
    """La versión instalada: el archivo VERSION de la carpeta de Atlas (única fuente desde el 18-11-2026).
    Si falta (instalación vieja), la constante que antes vivía en hud_server.py."""
    try:
        v = (OJ / "VERSION").read_text(encoding="utf-8-sig").strip()
        if re.fullmatch(r"\d+(\.\d+){0,3}", v):
            return v
    except OSError:
        pass
    try:
        m = re.search(r'^HUD_VERSION = "([^"]+)"', (HUD / "hud_server.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def _sesion_tg_cifrada(conn: Path) -> bool:
    """La sesión de Telegram migrada al Administrador de credenciales (solo en la carpeta real, no en pruebas)."""
    try:
        from openjarvis.security import atlas_secretos as S

        return conn == S.CONN and S.existe(S.TELEGRAM_SESION)
    except Exception:  # noqa: BLE001
        return False


# Hermes · avisos del banco desde el celular (MacroDroid -> Syncthing -> esta carpeta). Las pruebas cambian estas rutas.
AVISOS_DIR = Path(os.environ.get("AVISOS_BANCO_DIR") or (Path(os.path.expanduser("~")) / ".atlas" / "avisos_banco"))
WINGET_PKGS = LOCAL / "Microsoft" / "WinGet" / "Packages"
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SYNCTHING_GUI = "http://127.0.0.1:8384/rest/noauth/health"


def _syncthing_exe() -> bool:
    return WINGET_PKGS.is_dir() and any(WINGET_PKGS.glob("Syncthing.Syncthing_*/*/syncthing.exe"))


def _syncthing_corre() -> bool:
    """La página local de Syncthing responde (solo 127.0.0.1; no necesita la clave)."""
    try:
        with urllib.request.urlopen(SYNCTHING_GUI, timeout=1) as r:  # noqa: S310
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


_LLAVES = re.compile(r"\{[a-z_]+\}")


def _ultimo_aviso(carpeta: Path, ahora: _dt.datetime) -> tuple[str, str]:
    """Estado del último avisos_banco*.txt sin mostrar su contenido. «Probar acción» de MacroDroid corre sin
    notificación real: deja {not_app_name}, {not_title} y {notification} sin valor (normal); la fecha sí se reemplaza."""
    fs = sorted(carpeta.glob("avisos_banco*.txt"), key=lambda f: f.stat().st_mtime) if carpeta.is_dir() else []
    if not fs:
        return "y", "Todavía no llega el archivo desde el celular"
    f = fs[-1]
    try:
        txt = f.read_text(encoding="utf-8-sig", errors="replace")
        txt = re.sub(r"(?<=[^\n])@@\|(?=\s*(?:\d{4}|\{year\})-)", "\n@@|", txt)   # MacroDroid no agrega salto de línea
        lineas = [ln for ln in txt.splitlines() if ln.startswith("@@|")]
    except OSError:
        return "x", "No se pudo leer el archivo"
    if not lineas:
        return "y", "El archivo llegó vacío: esperando el primer aviso"
    if all(_LLAVES.search(ln.split("|", 2)[1] if ln.count("|") >= 2 else ln) for ln in lineas[-1:]):
        return "x", "MacroDroid no está reemplazando los datos: insértelos con el botón …"
    reales = [ln for ln in lineas if not _LLAVES.search("|".join(ln.split("|")[2:]))]
    if not reales:
        return "y", "Esperando el primer aviso real del banco"
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", reales[-1].split("|")[1])
    try:
        t = _dt.datetime(*map(int, m.groups())) if m else _dt.datetime.fromtimestamp(f.stat().st_mtime)
    except ValueError:
        t = _dt.datetime.fromtimestamp(f.stat().st_mtime)
    cuando = t.strftime("hoy %H:%M") if t.date() == ahora.date() else t.strftime("%d-%m-%Y %H:%M")
    return "g", f"Último aviso: {cuando}"


def _s(estado, nombre, donde, detalle):
    return {"estado": estado, "nombre": nombre, "donde": donde, "detalle": detalle}


def _b(texto, tipo, valor="", primario=False):
    return {"texto": texto, "tipo": tipo, "valor": valor, "primario": primario}


def _boot(boot: dict, k: str, ok: str, off: str, err: str) -> tuple[str, str]:
    v = boot.get(k)
    if v is True:
        return "g", ok
    if v == "off":
        return "x", off
    if v == "error":
        return "x", err
    return "y", "Cargando…"


def _n(k: int, uno: str, varios: str) -> str:
    return f"{k} {uno if k == 1 else varios}"


def _peor(estados) -> str:
    """x > y > g; «o» (opcional, sin configurar) no cuenta como problema."""
    e = [x for x in estados if x != "o"]
    return "x" if "x" in e else "y" if "y" in e else "g" if e else "o"


def cronos_instalacion(cfg: dict, ahora: _dt.datetime | None = None) -> dict:
    """Ajustes › Guía de las apps › Cronos › Instalación (pedido del usuario, 18-11-2026): los dos modos de Cronos,
    automático (Rutas de Maps, vía cronologia_maps) y manual (señales), cada uno con sus pasos."""
    ahora = ahora or _dt.datetime.now()
    modo = cfg.get("modo_ubicacion") or ""
    cm = next((d for d in (OJ / "apps" / "cronos" / "cronologia_maps", OJ / "cronologia_maps") if d.is_dir()), None)
    est = _json(OJ / "datos" / "cronologia_maps" / "estado.json") or {}
    s = [_s("g", "Modo", "Cronos › ⚙ › Fuentes", "Automático: Rutas de Maps") if modo == "rutas"
         else _s("g", "Modo", "Cronos › ⚙ › Fuentes", "Manual: señales") if modo == "senales"
         else _s("y", "Modo", "Cronos › ⚙ › Fuentes", "Sin elegir: abra Cronos y elija uno")]
    if modo == "rutas":
        s.append(_s("g" if cm else "x", "Programa de Rutas", "apps\\cronos\\cronologia_maps",
                    "Instalado" if cm else "No está instalado"))
        if not est:
            s.append(_s("x", "Descarga de cada noche", "estado.json", "Nunca se ha descargado"))
        elif est.get("ok") is False:
            s.append(_s("x", "Descarga de cada noche", "estado.json", str(est.get("detalle") or "Falló la última descarga")))
        else:
            s.append(_s("g", "Descarga de cada noche", "estado.json",
                        "Última: " + str(est.get("ultimo_ok") or est.get("ultimo_intento") or "")[:16].replace("T", " ")))
    else:
        s.append(_s("g", "Recibos, gastos y calendario", "Gmail, Hermes y Calendar", "Llegan solos"))
        s.append(_s("o", "bip!, Takeout y chats", "Cronos › ⚙ › Fuentes", "Se agregan a mano de vez en cuando"))
    auto = ["MODO AUTOMÁTICO (Rutas de Maps): Atlas baja cada noche dónde estuvo y cómo se movió. Se configura una vez:",
            "1. En el celular: Google Maps › su foto › Rutas › ícono de nube › activar la copia de seguridad.",
            "2. En un PowerShell normal (no de administrador) ejecute `apps\\cronos\\cronologia_maps\\instalar.ps1`.",
            "3. En esa carpeta ejecute `.venv\\Scripts\\python secretos.py token`: abra el enlace, inicie sesión y pegue "
            "la cookie `oauth_token` (F12 › Application › Cookies). En su cuenta aparecerá un «Android Device»: es Atlas.",
            "4. Ejecute `.venv\\Scripts\\python secretos.py clave`: Google le pide la contraseña otra vez y entrega la clave.",
            "5. Pruebe con `.venv\\Scripts\\python sincronizar.py` y programe la tarea diaria «Atlas-CronologiaMaps» (LEAME.md, paso 5).",
            "Si falla con «no entregó el acceso temporal», repita el paso 3; si dice «no se pudo descifrar», repita el paso 4."]
    manual = ["MODO MANUAL (señales): sin ubicación, Cronos deduce dónde estuvo. Es menos preciso y le pide pasos de vez en cuando:",
              "Recibos de Uber, Didi o Cabify, gastos de Hermes y su calendario llegan solos (requieren el correo y Hermes conectados).",
              "bip!: en tarjetabip.cl copie la tabla de viajes y péguela en Cronos › ⚙ › Fuentes › PEGAR (cada semana).",
              "Rutas buscadas en Maps: en takeout.google.com desmarque todo, marque «Mi actividad» (solo Maps) y exporte; "
              "deje el zip en Descargas y Atlas lo toma solo (cada mes).",
              "Chats de WhatsApp: exporte un chat «sin archivos» y déjelo en Descargas; luego Cronos › ⚙ › Fuentes › IMPORTAR. "
              "Solo se guardan las horas en que usted escribió (±1 min) y el archivo va a la papelera."]
    como = ["Elija el modo la primera vez que abre Cronos, o cámbielo en Cronos › ⚙ › Fuentes de ubicación."]
    como += (auto + manual) if modo != "senales" else (manual + auto)
    inst = dict(titulo="Cronos: de dónde sale su historia",
                que="Cronos arma su historia de dos formas: automática, con Rutas de Google Maps, o manual, con señales "
                    "(bip!, recibos, gastos, calendario, búsquedas en Maps y horas de sus chats).",
                sistemas=s, como=como)
    inst["estado"] = _peor(x["estado"] for x in s)
    return inst


def universidad(vig: dict | None = None, hud: Path | None = None) -> dict:
    """Paso «Universidad (opcional)»: dos tarjetas lado a lado, Canvas | U-Cursos, cada una con su estado propio.
    Estados: g = configurado y funcionando; o = opcional, no configurado; y = a medias; x = configurado pero falla."""
    vig, hud = vig or {}, hud or HUD
    # --- Canvas (PUC, UDP, UdeC…)
    cv0 = vig.get("canvas") or {}
    cv = cv0.get("conexion") or cv0
    if not (hud / "canvas_sesion.json").exists():
        cs = [_s("o", "Notas", "canvas_sesion.json", "Opcional · sin conectar")]
    elif cv and cv.get("ok") is False:
        cs = [_s("x", "Notas", "canvas_sesion.json", (cv.get("motivo") or "la sesión expiró").capitalize())]
    else:
        cs = [_s("g", "Notas", "canvas_sesion.json",
                 "Conectado · revisa solo si dice «vigila Canvas»" if cv0.get("pausado") or not cv else "Conectado · revisando sus notas")]
    canvas = {"nombre": "Canvas", "que": "Sus notas de Canvas, si su universidad lo usa.", "sistemas": cs,
              "como": ["Diga «conecta Canvas» con la dirección del Canvas de su universidad (por ejemplo «conecta Canvas "
                       "cursos.uc.cl»). Se abre el navegador; inicie sesión con su cuenta.",
                       "Atlas guarda la sesión. Revisa sus notas solo si usted dice «vigila Canvas».",
                       "Si la sesión vence, vuelva a decir «conecta Canvas»."],
              "botones": [] if cs[0]["estado"] == "g" else [_b("CONECTAR CANVAS", "dicho", "conecta Canvas", primario=True)]}
    # --- U-Cursos (Universidad de Chile)
    ics = any(hud.glob("agenda_u*cursos*.ics"))
    uc0 = vig.get("ucursos") or {}
    uc = uc0.get("conexion") or uc0  # conectado o no; vigilar es aparte (solo mientras espera una nota)
    ses = (hud / "ucursos_sesion.json").exists()
    notas = (("g", "Conectado · revisa solo mientras espera una nota") if ses and uc.get("ok") and uc0.get("pausado") else
             ("g", "Conectado · revisando sus notas") if ses and uc.get("ok") else
             ("x", (uc.get("motivo") or "la sesión expiró").capitalize()) if ses and uc else
             ("y", "Sesión guardada · sin revisar todavía") if ses else ("o", "Opcional · sin conectar"))
    us = [_s("g" if ics else "o", "Agenda U-Cursos", "agenda_u_cursos.ics", "Archivo .ics cargado" if ics else "Opcional · sin calendario"),
          _s(notas[0], "Notas", "ucursos_sesion.json", notas[1])]
    ucursos = {"nombre": "U-Cursos", "que": "Sus tareas en la agenda y aviso cuando sale una nota nueva.", "sistemas": us,
               "como": ["Agenda: en U-Cursos descargue su calendario `.ics` y ejecute `Agregar-calendario.cmd`.",
                        "Notas: diga «conecta U-Cursos». Se abre Edge; inicie sesión con su cuenta de la U.",
                        "Atlas guarda la sesión y revisa sus notas cada 20 minutos.",
                        "Si la sesión vence, el ícono U de arriba se pone rojo: vuelva a decir «conecta U-Cursos»."],
               "botones": ([] if notas[0] == "g" else [_b("CONECTAR U-CURSOS", "dicho", "conecta U-Cursos", primario=True)]) +
                          ([] if ics else [_b("AGREGAR CALENDARIO", "abrir", "calendario", primario=notas[0] == "g")])}
    for c in (canvas, ucursos):
        c["estado"] = _peor(s["estado"] for s in c["sistemas"])
        c["opcional"] = True
        c["detalle"] = {"g": "Configurado", "o": "Opcional · no configurado", "y": "Configurado · a medias",
                        "x": "Configurado · con problemas"}[c["estado"]]
    plats = [canvas, ucursos]
    return {"titulo": "Universidad (opcional)",
            "que": "Canvas y U-Cursos son opcionales e independientes: configure el que use su universidad, los dos o "
                   "ninguno. Uno no necesita al otro y ninguno bloquea el resto de la instalación.",
            "sistemas": [_s(c["estado"], c["nombre"], c["sistemas"][-1]["donde"], c["detalle"]) for c in plats],
            "como": [f"{c['nombre']} (opcional): {x}" for c in plats for x in c["como"]],
            "botones": [b for c in plats for b in c["botones"]] + [_b("VER EN AJUSTES › UNIVERSIDAD", "seccion", "Universidad")],
            "plataformas": plats, "estado": _peor(c["estado"] for c in plats)}


def revisar(version: str, boot: dict | None = None, vigilancias: dict | None = None, apps: list[str] | None = None,
            ahora: _dt.datetime | None = None) -> dict:
    boot, vig, apps = boot or {}, vigilancias or {}, apps or []
    ahora = ahora or _dt.datetime.now()
    pasos = []

    def paso(titulo, que, sistemas, como, botones):
        pasos.append({"n": len(pasos) + 1, "titulo": titulo, "que": que, "sistemas": sistemas, "como": como,
                      "botones": botones + [_b("VOLVER A REVISAR", "revisar")]})

    # 1 · Ollama y el modelo
    tags = _ollama_tags()
    modelo = boot.get("_modelo") or "qwen3.5:9b"
    if tags is None:
        s = [_s("x", "Ollama", "ollama.exe", "No responde: instálelo o ábralo"),
             _s("x", f"Modelo {modelo}", "ollama list", "No se puede revisar sin Ollama")]
    else:
        m = next((t for t in tags if modelo in (t.get("name"), t.get("model"))), None)
        gb = (" · " + f"{m['size'] / 1e9:.1f}".replace(".", ",") + " GB") if m and m.get("size") else ""
        s = [_s("g", "Ollama", "ollama.exe", "Corriendo · " + _n(len(tags), "modelo", "modelos")),
             _s("g", f"Modelo {modelo}", "ollama list", "Descargado" + gb) if m
             else _s("x", f"Modelo {modelo}", "ollama list", "No está descargado")]
    paso("Ollama y el modelo", "El cerebro de Atlas: el modelo de lenguaje que corre en su tarjeta gráfica.", s,
         ["Instale Ollama desde `ollama.com` y déjelo corriendo.", f"Descargue el modelo: `ollama pull {modelo}`.",
          f"Pruébelo: `ollama run {modelo} \"hola\"`."],
         [_b("DESCARGAR OLLAMA", "abrir", "ollama", primario=True)] if tags is None else [])

    # 2 · OpenJarvis y el entorno de Python
    disco = _version_en_disco()
    venv = (OJ / "src" / ".venv").is_dir()
    uia = _modulo("uiautomation")
    s = [_s("g" if venv else "x", "OpenJarvis", "src\\.venv", "Entorno de Python listo" if venv else "No está instalado"),
         _s("y", "Versión de Atlas", "VERSION", f"Corre la {version} y está instalada la {disco}: reinicie Atlas")
         if disco and disco != version else _s("g", "Versión de Atlas", "VERSION", f"Al día · {version}"),
         _s("g" if uia else "x", "Automatización de Windows", "uiautomation", "Instalada" if uia else "Falta: ejecute los extras")]
    paso("Entorno de Python", "La base: Atlas está construido sobre OpenJarvis (proyecto libre); aquí van OpenJarvis, la carpeta hud y los extras que usan las apps de escritorio.", s,
         ["Instale OpenJarvis en `%LOCALAPPDATA%\\Atlas` con su instalador de Windows.",
          "Copie la carpeta `hud` y los `.cmd` dentro de esa carpeta.", "Ejecute `Instalar-extras.cmd`."],
         ([] if uia else [_b("INSTALAR EXTRAS", "abrir", "extras", primario=True)]) + [_b("ABRIR CARPETA", "abrir", "carpeta")])

    # 3 · Voz
    voces = OJ / "voices"
    pk = (voces / "parakeet-v3").is_dir() and _modulo("sherpa_onnx")
    oido = _boot(boot, "oido", "Escuchando con Parakeet", "Apagado", "Falló al cargar")
    voz = _boot(boot, "voz", "Piper · davefx y alan", "Apagada", "Falló al cargar")
    faltan_voces = [v for v in PIPER if not (voces / f"{v}.onnx").exists()]
    s = [_s(*oido[:1], "Oído", "voices\\parakeet-v3", oido[1]) if pk
         else _s("y", "Oído", "voices\\parakeet-v3", "Sin Parakeet: usa Whisper, más lento"),
         _s("x", "Voz", "voices\\*.onnx", "Faltan " + ", ".join(faltan_voces)) if faltan_voces
         else _s(voz[0], "Voz", "voices\\*.onnx", voz[1]),
         _s("g", "Tecla Fin", "teclado", "Hablar desde cualquier ventana") if boot.get("tecla") is True
         else _s("y", "Tecla Fin", "teclado", "No se tomó la tecla (¿Atlas abierto dos veces?)"),
         _s("g", "Círculo flotante", "atlas_flotante.py", "Activo") if boot.get("flotante") is True
         else _s("y", "Círculo flotante", "atlas_flotante.py", "No se abrió")]
    paso("Voz", "Oír, hablar y la tecla Fin para hablarle desde cualquier ventana.", s,
         ["Ejecute `Instalar-parakeet.cmd` (descarga ~490 MB).",
          "Deje las voces `es_ES-davefx-medium` y `en_GB-alan-medium` en `voices`, cada una con su `.onnx.json`.",
          "La tecla Fin y el círculo se activan solos al abrir Atlas."],
         [] if pk else [_b("INSTALAR PARAKEET", "abrir", "parakeet", primario=True)])

    # 4 · Correo
    cuentas = list((CONN / "mail_accounts").glob("*.json")) if (CONN / "mail_accounts").is_dir() else []
    n = len(cuentas) + (1 if (CONN / "gmail_imap.json").exists() else 0)
    # instalado = cuentas que funcionan; si ahora no espera ningún correo no es una falta (usuario, 18-11-2026)
    co = (vig.get("correo") or {}).get("conexion") or vig.get("correo") or {}
    falla = boot.get("_correo_falla") or ""
    if not n:
        s = _s("x", "Correo", "connectors\\mail_accounts", "Ninguna cuenta agregada")
    elif boot.get("correo") == "error" or co.get("ok") is False:
        s = _s("x", "Correo", "connectors\\mail_accounts", (co.get("motivo") or f"Falló la lectura {falla}").strip().capitalize())
    elif falla:
        s = _s("y", "Correo", "connectors\\mail_accounts", f"{boot.get('_correo') or n} · falla {falla}")
    else:
        s = _s("g", "Correo", "connectors\\mail_accounts", _n(n, "cuenta", "cuentas"))
    paso("Correo", "Leer y resumir sus correos, y avisar los importantes.", [s],
         ["Ejecute `Agregar-correo.cmd` una vez por cuenta.",
          "Use una contraseña de aplicación de Google, no su contraseña normal.",
          "Si una cuenta falla, ejecute `Diagnostico-correo.cmd`."],
         [_b("AGREGAR CUENTA", "abrir", "correo", primario=s["estado"] == "x"), _b("DIAGNÓSTICO", "abrir", "diag_correo")])

    # 5 · Google Calendar
    tok = (CONN / "google_calendar_token.json").exists()
    g = _boot(boot, "google", "Conectado", "No está conectado", "Falló la conexión") if tok else ("x", "No está conectado")
    paso("Google Calendar", "Ver su agenda, crear eventos y avisarle antes de cada uno.",
         [_s(g[0], "Google Calendar", "google_calendar_token.json", g[1])],
         ["En `console.cloud.google.com` active la Google Calendar API.",
          "Cree una credencial OAuth de escritorio y descargue el JSON.", "Ejecute `Conectar-Google-Calendar.cmd`."],
         [] if g[0] == "g" else [_b("CONECTAR", "abrir", "google", primario=True)])

    # 6 · Universidad: Canvas y U-Cursos son OPCIONALES e INDEPENDIENTES (pedido del usuario, 18-11-2026): se configura
    #     uno, el otro, los dos o ninguno; ninguno bloquea al otro ni cuenta como pendiente si no se usa.
    u = universidad(vig)
    paso(u["titulo"], u["que"], u["sistemas"], u["como"], u["botones"])
    pasos[-1]["plataformas"], pasos[-1]["estado_fijo"] = u["plataformas"], u["estado"]

    # 8 · Telegram
    bot = (CONN / "telegram.json").exists()
    tg = _boot(boot, "telegram", "Conectado", "No está configurado", "No arrancó") if bot else ("x", "No está configurado")
    cuenta = (CONN / "telegram_usuario.session").exists() or _sesion_tg_cifrada(CONN)
    paso("Telegram", "Hablarle a Atlas desde el celular y que lea sus mensajes sin leer.",
         [_s(tg[0], "Bot", "telegram.json", tg[1]),
          _s("g" if cuenta else "y", "Su cuenta", "telegram_usuario.session", "Vinculada" if cuenta else "Opcional · sin vincular")],
         ["En Telegram hable con @BotFather, cree un bot y copie el token.",
          "Cierre Atlas y ejecute `Agregar-telegram.cmd`.",
          "Opcional: ejecute `Vincular-Telegram.cmd` para que lea sus mensajes sin leer."],
         [] if tg[0] == "g" and cuenta else [_b("ABRIR CARPETA", "abrir", "carpeta")])

    # 8 · Discord, WhatsApp y Enlace Móvil
    pkg = LOCAL / "Packages"
    dc = (LOCAL / "Discord" / "Update.exe").exists()
    wa = pkg.is_dir() and any(pkg.glob("*WhatsAppDesktop*"))
    el = (pkg / "Microsoft.YourPhone_8wekyb3d8bbwe").is_dir()
    lib = _json(HUD / "contactos.json")
    nc = len(lib.get("contactos", [])) if isinstance(lib, dict) else len(lib) if isinstance(lib, list) else 0
    paso("Discord, WhatsApp, Enlace Móvil", "Escribir y llamar usando las apps de escritorio, solo a su libreta.",
         [_s("g" if dc else "x", "Discord", "Discord.exe", "App instalada" if dc else "No está instalada"),
          _s("g" if wa else "x", "WhatsApp", "Microsoft Store", "App instalada" if wa else "No está instalada"),
          _s("g" if el else "x", "Enlace Móvil", "Phone Link", "App instalada" if el else "No está instalada"),
          _s("g" if nc else "y", "Libreta de contactos", "contactos.json", _n(nc, "contacto", "contactos") if nc else "Vacía")],
         ["Instale Discord y WhatsApp e inicie sesión en cada una.",
          "Abra Enlace Móvil, vincule su teléfono y active las llamadas.",
          "En la pestaña CONTACTOS anote a cada persona; DEL TELÉFONO las importa desde Enlace Móvil.",
          "Pruebe con «llama a …» a alguien de su libreta."],
         [_b("ABRIR ENLACE MÓVIL", "abrir", "enlace", primario=not el), _b("AJUSTES DE BLUETOOTH", "abrir", "bluetooth")])

    # 9 · Música
    yt = _modulo("yt_dlp")
    perfil = (OJ / "music-profile").is_dir()
    paso("Música", "Poner música en YouTube Music por voz: «pon…», «salta», «pon una de mis favoritas».",
         [_s("g" if yt else "x", "Búsqueda de canciones", "yt-dlp", "Instalada" if yt else "Falta: ejecute los extras"),
          _s("g" if perfil else "y", "Perfil de YouTube Music", "music-profile", "Creado" if perfil else "Diga «pon música» e inicie sesión")],
         ["Ejecute `Instalar-extras.cmd`.", "Diga «pon música». Se abre YouTube Music en un perfil propio de Edge.",
          "Inicie sesión ahí una vez; Atlas la recuerda."],
         [] if yt else [_b("INSTALAR EXTRAS", "abrir", "extras", primario=True)])

    # Hermes: avisos del banco desde el celular (método del 18-11-2026; las cartolas ya no son fuente).
    # 18-11-2026 (17:00): ya NO es un paso de Instalación; va en Ajustes › Guía de las apps › Hermes › Instalación,
    # con los mismos controles en vivo. Se entrega aparte en «guia» y no cuenta en el avance de la instalación.
    exe, corre = _syncthing_exe(), _syncthing_corre()
    vbs = STARTUP.is_dir() and any(STARTUP.glob("*yncthing*.vbs"))
    av = _ultimo_aviso(AVISOS_DIR, ahora)
    correo_h = (CONN / "gmail_imap.json").exists() or (CONN / "mail_accounts").is_dir() and any((CONN / "mail_accounts").glob("*.json"))
    hermes_inst = dict(
        titulo="Hermes: avisos del banco",
        que="Lo que Hermes necesita para sumar sus gastos solo: el correo conectado y los avisos del banco del celular "
            "(MacroDroid los anota, Syncthing los trae al PC).",
        sistemas=[_s("g" if correo_h else "x", "Correo conectado", "connectors", "Conectado" if correo_h else "Sin correo: vea el paso «Correo»"),
          _s("g" if exe else "x", "Syncthing", "winget", "Instalado" if exe else "No está instalado"),
          _s("g" if corre else "x", "Syncthing corriendo", "127.0.0.1:8384",
             ("Corriendo · arranca solo al iniciar sesión" if vbs else "Corriendo · sin arranque automático")
             if corre else "No está corriendo"),
          _s("g" if AVISOS_DIR.is_dir() else "x", "Carpeta avisos_banco", "%USERPROFILE%\\.atlas\\avisos_banco",
             "Presente" if AVISOS_DIR.is_dir() else "No existe: acéptela en Syncthing"),
          _s(av[0], "Último aviso", "avisos_banco.txt", av[1])],
        como=["En el celular (Android) instale MacroDroid y cree la macro «Avisos banco». Disparador: «Notificación "
          "recibida» de las apps Scotiabank y MACH.",
          "Acción: «Escribir en archivo» en `Documents/Atlas/avisos_banco.txt`, agregando al final (sin sobrescribir). "
          "Escriba a mano solo los separadores `@@|` y `|`; cada dato insértelo con el botón «…» (texto mágico): año, "
          "mes en número, día, hora, minuto, nombre de la app, título de la notificación y texto de la notificación. "
          "Termine con un salto de línea.",
          "Queda parecido a `@@|{year}-{month_digit}-{dayofmonth} {hour}:{minute}|{not_app_name}|{not_title}|{notification}` "
          "(los nombres exactos dependen de la versión de MacroDroid). Si en el archivo aparecen llaves en la fecha, "
          "se escribieron a mano: vuelva a insertarlas con «…». «Probar acción» corre sin una notificación real y deja "
          "vacíos la app, el título y el texto: eso es normal.",
          "Dele a MacroDroid acceso a las notificaciones y a los archivos.",
          "En el celular instale Syncthing-Fork y comparta la carpeta `Documents/Atlas` como «avisos_banco», en modo Solo enviar.",
          "En el PC instale Syncthing: `winget install --id Syncthing.Syncthing -e --source winget` (usted acepta los "
          "términos). Arranca oculto con un `.vbs` en la carpeta Inicio y su página queda solo en `127.0.0.1:8384`.",
          "Empareje los dos equipos intercambiando sus ID de dispositivo. En el PC acepte la carpeta en modo Solo "
          "recibir, en `%USERPROFILE%\\.atlas\\avisos_banco`.",
          "Contraseña de los PDF del banco (los comprobantes que el banco manda con clave): escríbala en «Contraseña de PDF del banco», "
          "aquí mismo. Queda en el Administrador de credenciales de Windows (entrada `Atlas-Hermes-PDF`); Atlas nunca la muestra.",
          "Listo: Atlas revisa el archivo solo (`actualizar_apolo.py --solo-avisos`). Ciclos, qué cuenta como gasto y "
          "cómo actualizar a mano están más abajo, en el uso de Hermes."],
        clave_pdf=True)   # control «Contraseña de PDF del banco» (solo estado; el valor va al Administrador de credenciales)
    hermes_inst["estado"] = _peor(s_["estado"] for s_ in hermes_inst["sistemas"])
    cronos_inst = cronos_instalacion(_json(HISTORIA_CFG) or {}, ahora)

    # 10 · Apps dentro de Atlas
    cfg = _json(HISTORIA_CFG) or {}
    s = []
    for nombre, que in (("Fortuna", "Fondos mutuos"), ("Hermes", "Gastos por ciclo de la tarjeta"), ("Cronos", "Su historia día por día")):
        if nombre not in apps:
            s.append(_s("x", nombre, "accesos.json", "No está registrada"))
        # «pausado» de Cronos solo detenía el análfortuna de fotos, que ya no se usa; no es un pendiente (17-11)
        else:
            s.append(_s("g", nombre, "accesos.json", que))
    cronos_y = any(x["nombre"] == "Cronos" and x["estado"] == "y" for x in s)
    paso("Apps", "Fortuna, Hermes y Cronos se abren dentro de la pantalla, en el riel de la izquierda.", s,
         ["Cronos (su historia día a día): diga «abre Cronos» o use su ícono del riel. Se arma solo con el historial "
          "por día de Atlas (conversaciones, agenda, fotos, gastos y viajes); no hay que anotar nada.",
          "Fortuna (fondos mutuos): diga «abre Fortuna». Usted anota a mano cada aporte y cada rescate; los valores "
          "cuota de la CMF se descargan solos.",
          "Hermes (gastos): diga «abre Hermes» o «¿cuánto he gastado?». Su configuración (correo, MacroDroid, Syncthing "
          "y contraseña de PDF) está en Guía de las apps › Hermes › Instalación: presione «CONFIGURAR HERMES».",
          "Qué hacer si una app no muestra datos: presione «VER GUÍA DE LAS APPS» (también está en la lista de la izquierda).",
          "Para registrar una app nueva: `hud\\accesos.json` con `\"en_atlas\": true` y la ruta de su página."],
         ([_b("ABRIR CRONOS", "app", "Cronos", primario=True)] if cronos_y else [])
         + [_b("VER GUÍA DE LAS APPS", "seccion", "__guia", primario=not cronos_y),
            _b("CONFIGURAR HERMES", "seccion", "__guia#hermes")])

    for p in pasos:
        if "estado_fijo" in p:   # Universidad: lo decide cada plataforma por separado (opcional = no es pendiente)
            p["estado"] = p.pop("estado_fijo")
            continue
        e = [x["estado"] for x in p["sistemas"]]
        p["estado"] = "x" if "x" in e else "y" if "y" in e else "g"
    listos = sum(p["estado"] in ("g", "o") for p in pasos)
    return {"guia": {"Hermes": hermes_inst, "Cronos": cronos_inst},   # instalación de cada app, en Ajustes › Guía de las apps
            "pasos": pasos, "listos": listos, "total": len(pasos), "pendientes": len(pasos) - listos,
            "peor": "x" if any(p["estado"] == "x" for p in pasos) else "y" if any(p["estado"] == "y" for p in pasos) else "g",
            "revisado": ahora.strftime("%H:%M")}


if __name__ == "__main__":
    print(json.dumps(revisar("?"), ensure_ascii=False, indent=1))

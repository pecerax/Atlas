"""Rueda de ajustes › Instalación › «Mostrar texto plano para que una IA lo instale» (pedido del usuario, 18-11-2026).

Arma, desde la configuración real (los pasos de atlas_faltantes y las secciones de atlas_ajustes), un texto en español
para pegárselo a otra IA y que guíe o haga la instalación de Atlas en un PC. Solo LEE estados; nunca cambia nada.
SIN datos privados: ni credenciales, ni tokens, ni correos, ni nombres, ni números, ni rutas con el nombre de usuario.
privacidad() revisa el resultado; el endpoint devuelve sus problemas y las pruebas fallan si hay alguno.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

HUD = Path(__file__).resolve().parent
OJ = HUD.parent  # %LOCALAPPDATA%\Atlas

# Cómo comprobar que cada paso de Instalación quedó bien (por título del paso de atlas_faltantes)
VERIFICAR = {
    "Ollama y el modelo": "En una terminal: `ollama list` debe mostrar el modelo. En Atlas, pregúntele «¿qué hora es?».",
    "Entorno de Python": "Atlas abre su ventana con `Atlas.cmd` y en Ajustes › Instalación este paso queda en verde.",
    "Voz": "Apriete la tecla Fin, diga «¿qué hora es?» y Atlas debe responder en voz alta.",
    "Correo": "Pregunte «¿tengo correos nuevos?». Si falla, `Diagnostico-correo.cmd` muestra el motivo.",
    "Google Calendar": "Pregunte «¿qué tengo hoy?» o use el botón SEMANA de la tarjeta Agenda.",
    "U-Cursos": "Pregunte «¿tengo notas nuevas?». El ícono U de arriba debe quedar en verde.",
    "Canvas": "Pregunte «¿cuáles son mis notas de Canvas?». El ícono C de arriba debe quedar en verde.",
    "Universidad (opcional)": "Canvas y U-Cursos son opcionales e independientes: verifique solo el que configuró. "
                              "U-Cursos: pregunte «¿tengo notas nuevas?» (ícono U en verde). Canvas: pregunte «¿cuáles "
                              "son mis notas de Canvas?» (ícono C en verde). Si no usa ninguno, el paso queda «OPCIONAL» y está bien.",
    "Telegram": "Desde el celular escríbale «hola» al bot: Atlas responde ahí.",
    "Discord, WhatsApp, Enlace Móvil": "Agregue un contacto de prueba en la pestaña CONTACTOS y diga «escríbele a <ese contacto> por WhatsApp» (pide confirmación antes de enviar).",
    "Música": "Diga «pon música»: se abre YouTube Music en su propia ventana.",
    "Hermes: avisos del banco": "Haga una compra pequeña o espere un aviso del banco en el celular: en unos minutos el archivo "
                                "avisos_banco.txt llega al PC y Ajustes › Instalación muestra «Último aviso» en verde. "
                                "Luego pregunte «¿cuánto he gastado este mes?».",
    "Apps": "Haga clic en cada ícono del riel izquierdo: la app se abre dentro de Atlas, con su animación.",
}
EST = {"g": "LISTO en este PC", "y": "A MEDIAS en este PC", "x": "FALTA en este PC", "o": "OPCIONAL · no configurado en este PC"}


def _usuario() -> list[str]:
    nombres = {Path.home().name, os.environ.get("USERNAME", ""), Path(os.environ.get("USERPROFILE", "")).name}
    return sorted(n for n in nombres if len(n) >= 3)


def _limpio(t: str) -> str:
    """Quita rutas personales, arrobas y las comillas de código de la HUD (el texto es plano)."""
    t = str(t).replace("`", "")
    for var in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        v = os.environ.get(var)
        if v:
            t = re.sub(re.escape(v), "%" + var + "%", t, flags=re.I)
    t = re.sub(r"@(\w)", r"\1", t)  # «@BotFather» -> «BotFather»
    return t


def _scripts_rotos() -> list[str]:
    """.cmd de la carpeta de Atlas que apuntan a una carpeta de %LOCALAPPDATA% que no existe (p. ej. un renombre a medias)."""
    local = Path(os.environ.get("LOCALAPPDATA", str(OJ.parent)))
    out = []
    for f in sorted(OJ.glob("*.cmd")):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        faltan = {m for m in re.findall(r"%LOCALAPPDATA%\\([A-Za-z0-9_.-]+)\\", txt, flags=re.I) if not (local / m).exists()}
        if faltan:
            out.append(f"{f.name} (usa %LOCALAPPDATA%\\{', '.join(sorted(faltan))}, que no existe; debería ser %LOCALAPPDATA%\\Atlas)")
    return out


def generar(version: str, faltantes: dict, ajustes: dict, modelo: str = "") -> str:
    pasos = (faltantes or {}).get("pasos") or []
    secciones = (ajustes or {}).get("secciones") or []
    modelo = modelo or next((s["nombre"].removeprefix("Modelo ") for p in pasos for s in p.get("sistemas", [])
                             if str(s.get("nombre", "")).startswith("Modelo ")), "") or "el modelo configurado"
    L: list[str] = []
    h = lambda t: L.extend(["", "=" * 72, t, "=" * 72])  # noqa: E731
    L += [f"ATLAS · INSTRUCCIONES PARA INSTALARLO CON AYUDA DE UNA IA (versión {version})",
          "Texto generado por Atlas desde su configuración real. No contiene contraseñas, tokens, correos ni rutas personales."]

    h("0. PARA LA IA QUE LEE ESTO")
    L += ["- Guíe a la persona paso a paso, en orden, y confirme cada paso antes de seguir.",
          "- NUNCA le pida contraseñas, tokens ni códigos en el chat: la persona los escribe directamente en la ventana",
          "  del script .cmd que corresponda o en la página oficial del servicio.",
          "- Antes de ejecutar un comando, explique qué hace. No borre carpetas ni archivos de la persona.",
          "- Al terminar cada paso, use la verificación indicada. En Atlas: rueda de Ajustes (abajo a la izquierda) › Instalación."]

    h("1. QUÉ ES ATLAS")
    L += ["Atlas es un asistente de voz y pantalla que corre localmente en Windows. Está construido sobre OpenJarvis,",
          "un proyecto libre de asistente personal (todo el crédito de la base a sus autores). Atlas le agrega una pantalla",
          "propia (HUD), voz en español, correo, agenda, avisos, mensajería y apps propias que se abren dentro de la ventana.",
          "- Apps propias: Hermes (gastos del banco), Fortuna (fondos mutuos) y Cronos (su historia día a día). Baco",
          "  (entretenimiento) y Atenea (educación) aparecen como «próximamente»: todavía no hacen nada.",
          "- Telegram: un bot llamado «Atlas» le responde y le avisa desde el celular cuando no está frente al PC.",
          "- Código: repositorio público github.com/pecerax/Atlas (sin datos personales). La versión está en el archivo",
          "  %LOCALAPPDATA%\\Atlas\\VERSION."]

    h("1b. LA FORMA FÁCIL: EL INSTALADOR")
    L += ["- Atlas-Instalar.exe (sin permisos de administrador) copia Atlas en %LOCALAPPDATA%\\Atlas y abre un asistente",
          "  que instala Python, los componentes, Ollama, el modelo, las voces, Syncthing y el acceso directo, y al final",
          "  pide las cuentas una por una (U-Cursos, Canvas, correo, Google Calendar, Hermes y Cronos). Todo se puede saltar",
          "  y retomar en Ajustes › Instalación. Al abrir Atlas por primera vez, un asistente corto prueba el micrófono y",
          "  deja elegir la voz.",
          "- Si la persona usa el instalador, la IA solo acompaña: lo de abajo es para revisar o hacerlo a mano."]

    h("2. REQUISITOS")
    L += ["- Windows 10 u 11, con micrófono y parlantes o audífonos.",
          "- Microsoft Edge (Atlas abre su ventana con Edge en modo aplicación).",
          "- Python 3.13 gestionado con uv (el instalador de Atlas trae uv y lo deja listo).",
          f"- Ollama, con el modelo {modelo} descargado (`ollama pull {modelo}`).",
          "- Tarjeta gráfica opcional pero recomendada (NVIDIA con 8 GB de VRAM o más); sin ella el instalador elige un",
          "  modelo más chico (4B) que corre en CPU, más lento.",
          "- Espacio: unos 15 GB entre el modelo, las voces y el reconocimiento de voz."]

    h("3. CARPETAS")
    L += ["- %LOCALAPPDATA%\\Atlas            programa: src (OpenJarvis y su entorno .venv), hud (la pantalla y la lógica),",
          "                                   voices (voces y reconocimiento), los scripts .cmd y los perfiles de Edge (*-profile).",
          "- %LOCALAPPDATA%\\Atlas\\apps        las apps: hermes (gastos), fortuna (fondos) y cronos (historia; dentro",
          "                                   está cronologia_maps, la descarga de Rutas de Google Maps).",
          "- %LOCALAPPDATA%\\Atlas\\instalador  el asistente de instalación (asistente.py) y lo que usa.",
          "- %USERPROFILE%\\.atlas            configuración (config.toml: motor «ollama» y modelo) y connectors (conexiones).",
          "- %LOCALAPPDATA%\\Atlas\\hud\\ajustes.json   los ajustes que se cambian desde la rueda de Ajustes."]

    h("4. CÓMO ARRANCAR Y APAGAR")
    L += ["- Doble clic en Atlas.cmd (o en su acceso directo «Atlas» del escritorio). Abre una sola ventana; si Atlas ya",
          "  estaba abierto, solo la trae al frente.",
          "- Para hablarle: tecla Fin desde cualquier ventana, o el botón HABLAR. También se puede escribir.",
          "- Cerrar la ventana de Atlas apaga todo (servidor, Telegram, tecla Fin) y corta la voz al instante.",
          "- Atlas-diagnostico.cmd lo abre con una consola visible que muestra lo que va pasando (útil si algo falla)."]

    h("5. INSTALACIÓN PASO A PASO (lo mismo que Ajustes › Instalación)")
    for p in pasos:
        L += ["", f"5.{p['n']} {p['titulo']}  [{EST.get(p.get('estado'), '')}]", f"    Para qué sirve: {_limpio(p['que'])}"]
        if p.get("sistemas"):
            L.append("    Partes: " + "; ".join(f"{_limpio(s['nombre'])} ({_limpio(s['donde'])})" for s in p["sistemas"]))
        for c in p.get("plataformas") or []:   # Universidad: Canvas | U-Cursos, cada una opcional y con su estado
            L.append(f"    {_limpio(c['nombre'])} (opcional, independiente): {_limpio(c['detalle'])}")
        L.append("    Cómo instalarlo:")
        L += [f"      {i}. {_limpio(c)}" for i, c in enumerate(p.get("como") or [], 1)]
        atajos = []
        for b in p.get("botones") or []:
            if b.get("tipo") == "dicho":
                atajos.append(f"decirle a Atlas «{b['valor']}»")
            elif b.get("tipo") == "abrir" and b.get("valor"):
                atajos.append(f"botón {b['texto']} en Ajustes › Instalación")
        if atajos:
            L.append("    Atajo: " + "; ".join(dict.fromkeys(atajos)) + ".")
        L.append("    Cómo verificar: " + _limpio(VERIFICAR.get(p["titulo"], "En Ajustes › Instalación este paso debe quedar en verde (botón VOLVER A REVISAR).")))
    # Instalación de cada app: vive en Ajustes › Guía de las apps (Hermes y Cronos traen su guía; Fortuna no requiere nada)
    h("5b. INSTALACIÓN DE LAS APPS (Ajustes › Guía de las apps › cada app › Instalación)")
    L += ["- Fortuna: no requiere nada extra. Usa los valores cuota públicos de la CMF y los aportes que usted anota a mano.",
          "- Baco y Atenea: próximamente; no hay nada que instalar."]
    for app, g in ((faltantes or {}).get("guia") or {}).items():
        L += ["", f"- {app}: {_limpio(g.get('titulo', ''))}  [{EST.get(g.get('estado'), '')}]",
              f"    Para qué sirve: {_limpio(g.get('que', ''))}"]
        if g.get("sistemas"):
            L.append("    Partes: " + "; ".join(f"{_limpio(s['nombre'])} ({_limpio(s['donde'])})" for s in g["sistemas"]))
        L.append("    Cómo instalarlo:")
        L += [f"      {i}. {_limpio(c)}" for i, c in enumerate(g.get("como") or [], 1)]
        if g.get("titulo") in VERIFICAR:
            L.append("    Cómo verificar: " + _limpio(VERIFICAR[g["titulo"]]))

    h("6. TAREAS AUTOMÁTICAS")
    L += ["- Vigilancias: Atlas revisa solo la bandeja de correo, U-Cursos y Canvas (si están conectados) con las",
          "  frecuencias de la sección 7, y avisa con voz, en la pantalla y por Telegram cuando no está frente al PC.",
          "- Avisos previos: una vez antes de cada actividad del calendario (ajuste «Avisar antes de una actividad»).",
          "- Enlace Móvil: si está instalado, Atlas lo mantiene abierto minimizado para avisar las llamadas al celular.",
          "- Hermes: al iniciar y cada 10 minutos, si cambió el archivo de avisos del banco que trae Syncthing, corre",
          "  actualizar_apolo.py --solo-avisos (sin abrir el correo). Sus fuentes son solo dos: las transferencias que",
          "  llegan por correo y los avisos del banco del celular; los ciclos van de corte a corte (el 23 o el día hábil anterior).",
          "  El botón ACTUALIZAR de Hermes y «actualiza Hermes» usan el mismo candado que esta tarea: nunca corren dos a la vez.",
          "- Cronología de Google Maps (opcional, para Cronos): tarea programada diaria «Atlas-CronologiaMaps» que se",
          "  instala con %LOCALAPPDATA%\\Atlas\\apps\\cronos\\cronologia_maps\\instalar.ps1 (ver su LEAME.md)."]

    h("7. AJUSTES (rueda de Ajustes, secciones de la izquierda)")
    L.append("Cada ajuste se cambia en la rueda (se guarda en ajustes.json) o con ABRIR ARCHIVO si vive en su propio archivo.")
    for s in secciones:
        L += ["", f"7.{secciones.index(s) + 1} {s['nombre']}"]
        for a in s.get("ajustes") or []:
            donde = f"archivo {a['archivo']}" if a.get("tipo") == "archivo" else f"ajustes.json → {a['clave']}"
            extra = (f" Opciones: {', '.join(a['opciones'])}." if a.get("opciones") else
                     f" Número ({'minutos' if a.get('unidad') == 'min' else 'segundos'}, mínimo {a.get('min')})." if a.get("tipo") == "num" else "")
            L.append(f"    - {_limpio(a['nombre'])}: {_limpio(a['explica'])}{extra} [{donde}]")
    L += ["", "    Diccionario tiene además un panel propio: correcciones de lo que el oído entiende mal y apodos de",
          "    contactos, accesos y artistas. Se llena solo con el uso o a mano desde ese panel.",
          "    Corrector: el botón ✎ Corregir de cada mensaje pregunta «¿Qué quería que hiciera Atlas?» y guarda la",
          "    corrección en el diccionario, para que la próxima vez lo haga bien."]

    h("8. CREDENCIALES Y SEGURIDAD")
    L += ["- Cada conexión pide su credencial en la ventana de su propio script .cmd o en la página oficial (Google,",
          "  U-Cursos, Canvas). La IA no debe verla ni pedirla.",
          "- Correo: use una contraseña de aplicación del proveedor (por ejemplo de Google), no la contraseña normal.",
          "- Los secretos (contraseñas, tokens, cookies) se guardan en el Administrador de credenciales de Windows, en",
          "  entradas que empiezan con «Atlas-» (por ejemplo Atlas-Correo-<cuenta>, Atlas-GoogleCalendar, Atlas-Telegram-Bot,",
          "  Atlas-UCursos, Atlas-Canvas, Atlas-Hermes-PDF, Atlas-Syncthing-GUI), cifradas por Windows para su usuario.",
          "  Nunca se escriben en archivos ni en registros. Lo hace el módulo",
          "  %LOCALAPPDATA%\\Atlas\\src\\src\\openjarvis\\security\\atlas_secretos.py. Las entradas viejas «Jarvis-…» se",
          "  siguen leyendo solo si falta la «Atlas-…» equivalente.",
          "- En %USERPROFILE%\\.atlas\\connectors quedan solo «sobres»: archivos con datos no secretos (servidor, fecha) y",
          "  el nombre de su entrada en el Administrador de credenciales.",
          "- Para revisarlas: Panel de control › Administrador de credenciales › Credenciales de Windows (o `cmdkey /list`,",
          "  que muestra solo los nombres). Para quitar una conexión, borre su entrada «Atlas-…».",
          "- Proteger-credenciales.cmd (con Atlas cerrado) sirve para instalaciones antiguas que aún tengan secretos en",
          "  archivos: primero muestra qué haría, deja un respaldo cifrado y luego los pasa al Administrador de credenciales.",
          "- La página de Syncthing (127.0.0.1:8384) queda con usuario y contraseña al azar (Atlas-Syncthing-GUI); Atlas",
          "  habla con Syncthing con su clave de API y no los necesita.",
          "- Nunca pegue en el chat de la IA contraseñas, tokens, códigos de verificación ni el contenido de esos archivos."]

    h("9. PRUEBAS")
    L += ["- Probar-Atlas.cmd corre la suite principal. Las tres suites, desde %LOCALAPPDATA%\\Atlas\\hud, con el Python de Atlas:",
          "    ..\\src\\.venv\\Scripts\\python.exe pruebas_atlas.py",
          "    ..\\src\\.venv\\Scripts\\python.exe pruebas_historia.py",
          "    ..\\src\\.venv\\Scripts\\python.exe pruebas_vigilancias.py",
          "- No usan datos reales ni abren ventanas (ponen ATLAS_PRUEBAS=1). Todas deben terminar sin fallas."]

    h("10. DIAGNÓSTICO")
    L += ["- Ajustes › Instalación: cada paso en verde, amarillo (a medias) o rojo (falta), con botón VOLVER A REVISAR.",
          "- Atlas-diagnostico.cmd: abre Atlas con consola visible.",
          "- %LOCALAPPDATA%\\Atlas\\hud\\hud.log: registro sin datos personales (un archivo por día).",
          "- Diagnostico-correo.cmd: revisa la conexión y el certificado del correo.",
          "- Si la ventana no abre: revise que Ollama esté corriendo y que el puerto 8765 no lo use otro programa."]
    rotos = _scripts_rotos()
    if rotos:
        L += ["", "OJO, detectado en este PC: estos scripts apuntan a una carpeta que no existe y fallarán hasta corregirlos:"]
        L += [f"  - {r}" for r in rotos]
    L += ["", "Fin del texto."]
    return "\n".join(_limpio(x) for x in L) + "\n"


def privacidad(texto: str, token: str = "") -> list[str]:
    """Problemas de privacidad del texto (vacío = limpio)."""
    out = []
    if "@" in texto.replace("@@|", ""):   # «@@|» es el separador de los avisos del banco (MacroDroid), no un correo
        out.append("contiene «@» (posible correo o usuario)")
    for n in _usuario():
        if n and re.search(re.escape(n), texto, flags=re.I):
            out.append("contiene el nombre de usuario de Windows")
            break
    m = re.search(r"\d{6,}", texto)
    if m:
        out.append(f"contiene un número largo ({len(m.group())} dígitos)")
    if token and token in texto:
        out.append("contiene el token de la sesión")
    if re.search(r"[A-Za-z]:\\Users\\", texto, flags=re.I):
        out.append("contiene una ruta absoluta de usuario")
    return out

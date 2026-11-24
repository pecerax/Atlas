"""Puente Atlas (23-11-2026): la puerta por la que entra la app del celular (Atlas Móvil).

El servidor de la pantalla (hud_server.py) sigue escuchando solo en 127.0.0.1. Este módulo abre OTRO puerto, con TLS,
que ofrece una lista corta y fija de cosas (hablar, estado, voz, confirmar, música) y solo a celulares vinculados.

Cómo se protege:
  1. Vincular: el PC muestra un QR con un código de un solo uso (dura 2 minutos) y la huella de su certificado.
     El código nunca viaja por la red hasta que el celular lo usa, ya dentro de TLS y contra el certificado de la huella.
  2. El celular crea un par de llaves (P-256) en su almacén seguro y entrega solo la pública. La privada no sale de él.
  3. Cada pedido va firmado con esa llave: método, ruta, hora, número de un solo uso y el hash del cuerpo. Sin firma
     válida de un celular vinculado no se responde nada. Un pedido repetido o viejo se rechaza.
  4. Solo se atiende a direcciones privadas: la red de la casa y la red de Tailscale (100.64.0.0/10).
  5. Desde la pantalla de Atlas (solo este PC) se ve la lista de celulares y se desvincula con un clic.

Nada de esto corre hasta que el usuario lo activa en «Vincular celular». Los datos viven en ~/.atlas/puente/.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUERTO = int(os.environ.get("ATLAS_PUENTE_PORT", "8766"))
CODIGO_SEG = 120          # lo que dura el código del QR
CODIGO_INTENTOS = 5       # códigos malos antes de anular el QR
RELOJ_SEG = 300           # diferencia de hora tolerada entre el celular y el PC
CUERPO_MAX = 8 * 1024 * 1024   # un audio de 60 s a 16 kHz pesa ~2 MB
FALLOS_MAX = 12           # pedidos rechazados por minuto y por dirección antes de dejar de responderle
REDES = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                           "100.64.0.0/10", "169.254.0.0/16", "::1/128", "fd00::/8", "fe80::/10")]

_lock = threading.RLock()
_estado: dict = {"server": None, "hud": None, "codigo": None, "nonces": {}, "fallos": {}, "log": print}


def carpeta() -> Path:
    d = Path(os.environ.get("ATLAS_PUENTE_DIR") or (Path.home() / ".atlas" / "puente"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log(msg: str) -> None:
    try:
        _estado["log"](msg)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- ajustes y celulares vinculados
def _leer(nombre: str, defecto):
    try:
        return json.loads((carpeta() / nombre).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _guardar(nombre: str, dato) -> None:
    f = carpeta() / nombre
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(dato, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def activo() -> bool:
    return bool(_leer("puente.json", {}).get("activo"))


def dispositivos() -> list[dict]:
    d = _leer("dispositivos.json", [])
    return d if isinstance(d, list) else []


def desvincular(disp_id: str) -> bool:
    with _lock:
        ds = dispositivos()
        quedan = [d for d in ds if d.get("id") != disp_id]
        if len(quedan) == len(ds):
            return False
        _guardar("dispositivos.json", quedan)
        _estado["nonces"].pop(disp_id, None)
    _log(f"Puente: celular desvinculado ({disp_id})")
    return True


# ----------------------------------------------------------------------------- certificado del PC
def _certificado() -> tuple[Path, Path]:
    """Certificado propio del puente (se crea una vez). El celular no confía en él por su nombre sino por su huella,
    que recibe en el QR: por eso no importa a qué dirección se conecte."""
    cert, clave = carpeta() / "cert.pem", carpeta() / "clave.pem"
    if cert.exists() and clave.exists():
        return cert, clave
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Atlas Puente")])
    ahora = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
         .not_valid_after(ahora + timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName("atlas-puente")]), critical=False)
         .sign(key, hashes.SHA256()))
    clave.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    try:
        os.chmod(clave, 0o600)
    except OSError:
        pass
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    _log("Puente: creé el certificado de este PC")
    return cert, clave


def huella() -> str:
    """SHA-256 del certificado (DER), en hexadecimal. Es lo que el celular guarda al vincularse."""
    pem = _certificado()[0].read_text(encoding="ascii")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


# ----------------------------------------------------------------------------- direcciones de este PC
def _privada(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return any(a in n for n in REDES)


def _tailscale_nombre() -> str:
    """Nombre del PC en la red de Tailscale (MagicDNS), si Tailscale está instalado y conectado. Sin él, ''."""
    for exe in ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe"):
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=4,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            yo = (json.loads(out) or {}).get("Self") or {}
            return str(yo.get("DNSName") or "").rstrip(".")
        except Exception:  # noqa: BLE001
            continue
    return ""


def direcciones() -> dict:
    """{"casa": [ip...], "tailscale": [ip o nombre...]}: por dónde puede llegar el celular a este PC."""
    ips: set[str] = set()
    try:
        import psutil

        for lista in psutil.net_if_addrs().values():
            for a in lista:
                if a.family == socket.AF_INET:
                    ips.add(a.address)
    except Exception:  # noqa: BLE001
        try:
            ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
        except OSError:
            pass
    ts_net = ipaddress.ip_network("100.64.0.0/10")
    casa, ts = [], []
    for ip in sorted(ips):
        a = ipaddress.ip_address(ip)
        if a.is_loopback or a.is_link_local:
            continue
        if a in ts_net:
            ts.append(ip)
        elif _privada(ip):
            casa.append(ip)
    nombre = _tailscale_nombre()
    if nombre:
        ts.append(nombre)
    return {"casa": casa, "tailscale": ts}


# ----------------------------------------------------------------------------- vincular (código del QR)
def nuevo_codigo() -> dict:
    """Crea el código de un solo uso y devuelve lo que va en el QR. Anula el código anterior."""
    d = direcciones()
    with _lock:
        cod = secrets.token_urlsafe(18)
        _estado["codigo"] = {"c": cod, "vence": time.time() + CODIGO_SEG, "intentos": 0}
    carga = {"v": 1, "n": socket.gethostname(), "h": d["casa"] + d["tailscale"], "p": puerto_actual(), "f": huella(), "c": cod}
    b64 = base64.urlsafe_b64encode(json.dumps(carga, separators=(",", ":")).encode()).decode().rstrip("=")
    return {"qr": "atlas://vincular?d=" + b64, "segundos": CODIGO_SEG, "direcciones": d}


def _usar_codigo(cod: str) -> bool:
    with _lock:
        c = _estado["codigo"]
        if not c or time.time() > c["vence"]:
            _estado["codigo"] = None
            return False
        if not secrets.compare_digest(str(cod), c["c"]):
            c["intentos"] += 1
            if c["intentos"] >= CODIGO_INTENTOS:
                _estado["codigo"] = None
                _log("Puente: demasiados códigos equivocados; anulé el QR")
            return False
        _estado["codigo"] = None   # un solo uso
        return True


def _vincular(data: dict, ip: str) -> tuple[int, dict]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        der = base64.b64decode(str(data.get("pub", "")), validate=True)
        pub = serialization.load_der_public_key(der)
        if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
            raise ValueError("llave no admitida")
    except Exception:  # noqa: BLE001
        return 400, {"error": "llave"}
    if not _usar_codigo(str(data.get("c", ""))):
        return 403, {"error": "codigo"}
    nombre = "".join(ch for ch in str(data.get("nombre", "Celular"))[:40] if ch.isprintable()) or "Celular"
    disp = {"id": secrets.token_hex(8), "nombre": nombre, "pub": base64.b64encode(der).decode(),
            "creado": time.strftime("%Y-%m-%d %H:%M"), "visto": ""}
    with _lock:
        _guardar("dispositivos.json", dispositivos() + [disp])
    _log(f"Puente: celular vinculado «{nombre}» ({disp['id']}) desde {ip}")
    return 200, {"id": disp["id"], "pc": socket.gethostname()}


# ----------------------------------------------------------------------------- firma de cada pedido
def texto_firmado(metodo: str, ruta: str, t: str, n: str, cuerpo: bytes) -> bytes:
    return f"{metodo}\n{ruta}\n{t}\n{n}\n{hashlib.sha256(cuerpo).hexdigest()}".encode()


def _autorizado(h, metodo: str, ruta: str, cuerpo: bytes) -> dict | None:
    """El celular que firmó el pedido, o None. Revisa hora, repetición y firma, en ese orden de costo."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    did, t, n, firma = (h.get("X-Atlas-Id") or ""), (h.get("X-Atlas-T") or ""), (h.get("X-Atlas-N") or ""), (h.get("X-Atlas-F") or "")
    if not (did and t.isdigit() and 8 <= len(n) <= 64 and firma):
        return None
    if abs(time.time() - int(t) / 1000) > RELOJ_SEG:
        return None
    disp = next((d for d in dispositivos() if d.get("id") == did), None)
    if not disp:
        return None
    try:
        pub = serialization.load_der_public_key(base64.b64decode(disp["pub"]))
        pub.verify(base64.b64decode(firma), texto_firmado(metodo, ruta, t, n, cuerpo), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        return None
    with _lock:   # la firma es buena: ¿ya se usó este número? (alguien que copió el pedido y lo repite)
        vistos = _estado["nonces"].setdefault(did, {})
        ahora = time.time()
        for k in [k for k, v in vistos.items() if ahora - v > 2 * RELOJ_SEG]:
            del vistos[k]
        if n in vistos:
            return None
        vistos[n] = ahora
    return disp


def _fallo(ip: str) -> None:
    with _lock:
        f = _estado["fallos"].setdefault(ip, [])
        f.append(time.time())
        del f[:-FALLOS_MAX * 2]


def _bloqueada(ip: str) -> bool:
    with _lock:
        f = _estado["fallos"].get(ip) or []
        return sum(1 for x in f if time.time() - x < 60) >= FALLOS_MAX


# ----------------------------------------------------------------------------- lo que el celular puede pedir
def _vista_estado(hud) -> dict:
    """Lo que la app muestra: en qué está Atlas, lo pendiente de confirmar, la agenda corta, las apps y la música."""
    A = hud.ATLAS
    live = A.live()
    st = A.status()
    return {
        "listo": bool(st.get("ready")), "modo": live.get("mode"), "ocupado": bool(live.get("busy")),
        "fase": live.get("fase"), "pendiente": live.get("pendiente") or ((st.get("pending") or {}).get("summary")),
        "eleccion": live.get("eleccion"), "sonando": live.get("sonando"), "musica": live.get("musica"),
        "recordatorios": st.get("reminders") or [], "tareas": st.get("tasks") or [], "pendientes": st.get("pendientes") or [],
        "apps": [a.get("nombre") for a in (st.get("apps") or [])], "pc": socket.gethostname(),
        "version": getattr(hud, "HUD_VERSION", ""),
    }


def _vista(v) -> dict | None:
    """La vista que acompaña una respuesta (el horario de la semana, una lista), con solo lo que la app dibuja.
    Es la misma que hud.html muestra en el PC: {"tipo": "calendario"|"lista", "titulo", "desde", "dias", "pestana", "items"}."""
    if not isinstance(v, dict) or not isinstance(v.get("items"), list) or not v["items"]:
        return None
    items = [{k: it[k] for k in ("titulo", "dia", "hora", "fin", "lugar", "tipo", "detalle") if it.get(k) not in (None, "")}
             for it in v["items"][:80] if isinstance(it, dict)]
    return {"tipo": "calendario" if v.get("tipo") == "calendario" else "lista", "titulo": str(v.get("titulo") or ""),
            "desde": v.get("desde"), "dias": v.get("dias"), "pestana": v.get("pestana"), "items": items}


def _oir(hud, audio: bytes) -> dict:
    """Transcribe lo que grabó el celular con el mismo oído y las mismas correcciones que la tecla Fin del PC."""
    A = hud.ATLAS
    if A.voice is None:
        return {"text": "", "error": "Voz no disponible"}
    backend = A.voice.get_stt_backend()
    if backend is None:
        return {"text": "", "error": "No hay reconocimiento de voz disponible"}
    raw = A._transcribe(backend, audio)
    text = hud.clean_transcript(raw)
    try:
        import atlas_fonetica

        text = atlas_fonetica.corregir(text, A._stt_vocab())
    except Exception:  # noqa: BLE001
        pass
    low = text.lower()
    if any(x in low for x in getattr(hud, "WHISPER_HALLUCINATIONS", ())) or len(low.strip(" .,!?¿¡")) < 2:
        return {"text": "", "error": "No le escuché bien, señor. ¿Puede repetirlo?"}
    return {"text": text}


def _atender(hud, ruta: str, data: dict, cuerpo: bytes) -> tuple[int, object, str]:
    """(código, respuesta, tipo). La respuesta es un dict (JSON) o bytes (audio). Solo estas rutas existen."""
    A = hud.ATLAS
    if ruta == "/p/estado":
        return 200, _vista_estado(hud), "json"
    if ruta == "/p/chat":
        A.hush_voice(page=False)
        out = A.chat_cancelable(str(data.get("text", ""))[:4000]) or {}
        return 200, {"reply": out.get("reply", ""), "detenido": bool(out.get("detenido")), "vista": _vista(out.get("view")),
                     "pendiente": (A.pending or {}).get("summary") if getattr(A, "pending", None) else None}, "json"
    if ruta == "/p/oir":
        return 200, _oir(hud, cuerpo), "json"
    if ruta == "/p/voz":
        audio, tipo = A.speak(str(data.get("text", ""))[:4000])
        return 200, audio, tipo or "audio/wav"
    if ruta == "/p/confirmar":
        A.hush_voice(page=False)
        out = A.confirm(bool(data.get("accept"))) or {}
        return 200, {"reply": out.get("reply", "")}, "json"
    if ruta == "/p/detener":
        return 200, A.stop_turn(), "json"
    if ruta == "/p/musica":
        import atlas_baco

        accion = str(data.get("accion", ""))
        if accion not in ("toggle", "next", "prev", "pause"):
            return 400, {"error": "accion"}, "json"
        m = atlas_baco._media(accion) or {}
        return 200, {"ok": True, "estado": m.get("estado")}, "json"
    return 404, {"error": "no existe"}, "json"


class _Handler(BaseHTTPRequestHandler):
    server_version = "AtlasPuente"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def setup(self) -> None:
        # el saludo TLS se hace aquí, en el hilo de esta conexión y con plazo: uno que se conecta y se queda callado
        # no detiene a los demás
        self.request.settimeout(15)
        self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        self.request.settimeout(90)
        super().setup()

    def _resp(self, code: int, body, tipo: str = "json") -> None:
        if tipo == "json":
            body, tipo = json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _todo(self, metodo: str) -> None:
        ip = self.client_address[0]
        if not _privada(ip) or _bloqueada(ip):
            self.close_connection = True
            self._resp(403, {"error": "fuera"})
            return
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = -1
        if not 0 <= largo <= CUERPO_MAX:
            self.close_connection = True
            self._resp(413, {"error": "muy grande"})
            return
        cuerpo = self.rfile.read(largo) if largo else b""
        ruta = self.path.split("?")[0]
        hud = _estado["hud"]
        if metodo == "POST" and ruta == "/p/vincular":
            try:
                data = json.loads(cuerpo or b"{}")
            except ValueError:
                data = {}
            code, obj = _vincular(data if isinstance(data, dict) else {}, ip)
            if code != 200:
                _fallo(ip)
            self._resp(code, obj)
            return
        disp = _autorizado(self.headers, metodo, ruta, cuerpo)
        if not disp:
            _fallo(ip)
            self._resp(401, {"error": "no vinculado"})
            return
        data = {}
        if cuerpo and (self.headers.get("Content-Type") or "").startswith("application/json"):
            try:
                data = json.loads(cuerpo)
            except ValueError:
                data = {}
        try:
            code, obj, tipo = _atender(hud, ruta, data if isinstance(data, dict) else {}, cuerpo)
        except Exception as exc:  # noqa: BLE001
            _log(f"Puente: {ruta} falló: {type(exc).__name__}: {exc}")
            code, obj, tipo = 500, {"error": "Atlas tuvo un problema con ese pedido."}, "json"
        self._resp(code, obj, tipo)
        _marcar_visto(disp["id"])

    def do_GET(self) -> None:  # noqa: N802
        self._todo("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._todo("POST")


_visto_t: dict = {}


def _marcar_visto(disp_id: str) -> None:
    """Anota cuándo se vio cada celular por última vez, a lo más una vez por minuto (no escribir en cada pedido)."""
    if time.time() - _visto_t.get(disp_id, 0) < 60:
        return
    _visto_t[disp_id] = time.time()
    with _lock:
        ds = dispositivos()
        for d in ds:
            if d.get("id") == disp_id:
                d["visto"] = time.strftime("%Y-%m-%d %H:%M")
        _guardar("dispositivos.json", ds)


class _Servidor(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True
    tls: ssl.SSLContext

    def handle_error(self, request, client_address) -> None:
        pass   # conexiones cortadas, saludos TLS fallidos o sin TLS: no son un error de Atlas, no ensucian el registro


def puerto_actual() -> int:
    s = _estado["server"]
    return s.server_address[1] if s else PUERTO


def corriendo() -> bool:
    return _estado["server"] is not None


def iniciar(hud, log=print, puerto: int | None = None) -> bool:
    """Abre el puente si el usuario lo activó. hud es el módulo hud_server (ATLAS, clean_transcript...)."""
    _estado["hud"], _estado["log"] = hud, log
    if not activo():
        return False
    return _abrir(PUERTO if puerto is None else puerto)


def _abrir(puerto: int) -> bool:
    with _lock:
        if _estado["server"] is not None:
            return True
        try:
            cert, clave = _certificado()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(str(cert), str(clave))
            srv = _Servidor(("0.0.0.0", puerto), _Handler)
            srv.tls = ctx
        except Exception as exc:  # noqa: BLE001
            _log(f"Puente: no pude abrirlo ({type(exc).__name__}: {exc})")
            return False
        _estado["server"] = srv
        threading.Thread(target=srv.serve_forever, daemon=True, name="puente").start()
    _log(f"Puente: escuchando en el puerto {puerto_actual()} (solo redes privadas y Tailscale)")
    return True


def detener() -> None:
    with _lock:
        srv, _estado["server"] = _estado["server"], None
    if srv:
        srv.shutdown()
        srv.server_close()
        _log("Puente: cerrado")


def activar(si: bool) -> bool:
    """Lo prende o lo apaga desde «Vincular celular», y lo recuerda para el próximo arranque."""
    cfg = _leer("puente.json", {})
    cfg["activo"] = bool(si)
    _guardar("puente.json", cfg)
    if si:
        return _abrir(PUERTO)
    detener()
    return False


def vista() -> dict:
    """Para la página «Vincular celular» (solo este PC): si está prendido, por dónde se llega y quién está vinculado."""
    return {"activo": activo(), "corriendo": corriendo(), "puerto": puerto_actual(), "direcciones": direcciones() if corriendo() else {},
            "dispositivos": [{k: d.get(k, "") for k in ("id", "nombre", "creado", "visto")} for d in dispositivos()]}

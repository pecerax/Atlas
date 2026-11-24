"""Pruebas de atlas_puente.py con un Atlas de mentira y un «celular» en Python (mismo protocolo que la app).
Correr con el Python de Atlas:
    ..\\src\\.venv\\Scripts\\python.exe pruebas_puente.py
"""
import base64
import hashlib
import http.client
import json
import os
import secrets
import ssl
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["ATLAS_PRUEBAS"] = "1"
_dir = tempfile.mkdtemp(prefix="puente_")
os.environ["ATLAS_PUENTE_DIR"] = _dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_puente as P  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

fallas, total = [], 0


def ok(nombre, cond):
    global total
    total += 1
    if not cond:
        fallas.append(nombre)


# --- un Atlas de mentira: anota lo que le piden ---
class AtlasFalso:
    def __init__(self):
        self.pending, self.voice, self.dicho, self.detenido = None, None, [], 0

    def live(self):
        return {"mode": "idle", "busy": False, "musica": {"titulo": "BRAIN", "artista": "Ado", "estado": "Playing"}}

    def status(self):
        return {"ready": True, "apps": [{"nombre": "Cronos"}, {"nombre": "Baco"}], "reminders": [{"id": "r1", "texto": "Repasar"}],
                "tasks": [], "pendientes": [{"id": "p1", "texto": "Entregar T5"}], "pending": None,
                "inbox": {"secreto": "esto no debe salir"}, "hw": {"gpu": "x"}}

    def hush_voice(self, page=True):
        pass

    def chat_cancelable(self, text):
        self.dicho.append(text)
        if "recuerda" in text:
            self.pending = {"summary": "Crear recordatorio", "tool": None}
            return {"reply": "Necesito su confirmación."}
        if "horario" in text:
            return {"reply": "Esta semana tiene dos cosas.", "view": {"tipo": "calendario", "titulo": "Mi horario", "desde": "2026-11-23",
                    "dias": 7, "pestana": "clases", "items": [
                        {"titulo": "Redes", "dia": "2026-11-24", "hora": "10:15", "fin": "11:45", "lugar": "B101", "tipo": "clase",
                         "evento": {"interno": "no debe salir"}, "personas": [{"nombre": "x"}]},
                        {"titulo": "Entrega T5", "dia": "2026-11-25", "hora": None, "fin": None, "lugar": "", "tipo": "entrega"}]}}
        return {"reply": "Hola, señor: " + text}

    def confirm(self, accept):
        self.pending = None
        return {"reply": "Hecho, señor." if accept else "Cancelado."}

    def stop_turn(self):
        self.detenido += 1
        return {"ok": True}

    def speak(self, text):
        return b"RIFF" + text.encode(), "audio/wav"


hud = types.SimpleNamespace(ATLAS=AtlasFalso(), clean_transcript=lambda s: s.strip(), HUD_VERSION="prueba",
                            WHISPER_HALLUCINATIONS=())
registro = []

# --- apagado mientras nadie lo active ---
ok("sin activar no abre nada", P.iniciar(hud, log=registro.append, puerto=0) is False and not P.corriendo())
P._guardar("puente.json", {"activo": True})
ok("activado abre", P.iniciar(hud, log=registro.append, puerto=0) is True and P.corriendo())
PUERTO = P.puerto_actual()
HUELLA = P.huella()
ok("huella sha256", len(HUELLA) == 64)


# --- el «celular»: fija la huella del certificado y firma cada pedido ---
class Celular:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.id = ""

    def _con(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # no se confía por nombre: se compara la huella
        c = http.client.HTTPSConnection("127.0.0.1", PUERTO, context=ctx, timeout=10)
        c.connect()
        if hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() != HUELLA:
            raise ssl.SSLError("huella distinta")
        return c

    def pedir(self, metodo, ruta, cuerpo=b"", tipo="application/json", firmar=True, t=None, n=None, llave=None, did=None):
        if isinstance(cuerpo, dict):
            cuerpo = json.dumps(cuerpo).encode()
        h = {"Content-Type": tipo}
        if firmar:
            t = str(int(time.time() * 1000)) if t is None else t
            n = secrets.token_urlsafe(12) if n is None else n
            firma = (llave or self.key).sign(P.texto_firmado(metodo, ruta, t, n, cuerpo), ec.ECDSA(hashes.SHA256()))
            h.update({"X-Atlas-Id": did or self.id, "X-Atlas-T": t, "X-Atlas-N": n, "X-Atlas-F": base64.b64encode(firma).decode()})
        c = self._con()
        c.request(metodo, ruta, body=cuerpo, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        try:
            return r.status, json.loads(body)
        except ValueError:
            return r.status, body

    def vincular(self, codigo, nombre="Pixel de prueba"):
        st, o = self.pedir("POST", "/p/vincular", {"c": codigo, "nombre": nombre, "pub": self.pub}, firmar=False)
        if st == 200:
            self.id = o["id"]
        return st, o


def codigo_del_qr(qr):
    b = qr.split("d=")[1]
    return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))


cel = Celular()
# --- sin vincular no hay nada ---
ok("sin firma: 401", cel.pedir("GET", "/p/estado", firmar=False)[0] == 401)
cel.id = "noexiste"
ok("id desconocido: 401", cel.pedir("GET", "/p/estado")[0] == 401)
ok("vincular sin QR pedido: 403", cel.vincular("cualquiera")[0] == 403)

# --- el QR ---
q = P.nuevo_codigo()
carga = codigo_del_qr(q["qr"])
ok("QR trae huella, puerto y código", carga["f"] == HUELLA and carga["p"] == PUERTO and len(carga["c"]) >= 20 and carga["v"] == 1)
ok("código equivocado: 403", cel.vincular("x" * 24)[0] == 403)
st, o = cel.vincular(carga["c"])
ok("vincular con el código: 200", st == 200 and o.get("id"))
ok("el código es de un solo uso", Celular().vincular(carga["c"])[0] == 403)
ok("quedó guardado solo lo público", len(P.dispositivos()) == 1 and set(P.dispositivos()[0]) == {"id", "nombre", "pub", "creado", "visto"})

# código vencido
q = P.nuevo_codigo()
P._estado["codigo"]["vence"] = time.time() - 1
ok("código vencido: 403", Celular().vincular(codigo_del_qr(q["qr"])["c"])[0] == 403)
# demasiados intentos anulan el QR aunque después llegue el bueno
q = P.nuevo_codigo()
bueno = codigo_del_qr(q["qr"])["c"]
for _ in range(P.CODIGO_INTENTOS):
    Celular().vincular("malo-malo-malo-malo-malo")
P._estado["fallos"].clear()
ok("cinco códigos malos anulan el QR", Celular().vincular(bueno)[0] == 403)
P._estado["fallos"].clear()
# llave que no es P-256
q = P.nuevo_codigo()
otro = Celular()
otro.pub = base64.b64encode(b"no es una llave").decode()
ok("llave inválida: 400 y no gasta el código", otro.vincular(codigo_del_qr(q["qr"])["c"])[0] == 400 and P._estado["codigo"] is not None)
P._estado["fallos"].clear()

# --- pedidos firmados ---
st, e = cel.pedir("GET", "/p/estado")
ok("estado: 200", st == 200 and e["listo"] is True and e["apps"] == ["Cronos", "Baco"] and e["musica"]["titulo"] == "BRAIN")
ok("estado no filtra lo que no es de la app", "inbox" not in e and "hw" not in e and "secreto" not in json.dumps(e))
st, r = cel.pedir("POST", "/p/chat", {"text": "qué hora es"})
ok("chat llega a Atlas", st == 200 and r["reply"].endswith("qué hora es") and hud.ATLAS.dicho == ["qué hora es"])
r0 = r
ok("chat sin vista", r.get("vista") is None)
st, r = cel.pedir("POST", "/p/chat", {"text": "mi horario"})
v = r.get("vista") or {}
ok("chat pasa el horario", v.get("tipo") == "calendario" and v.get("pestana") == "clases" and v.get("dias") == 7 and len(v.get("items", [])) == 2)
ok("el horario lleva solo lo que la app dibuja", v["items"][0] == {"titulo": "Redes", "dia": "2026-11-24", "hora": "10:15", "fin": "11:45",
   "lugar": "B101", "tipo": "clase"} and v["items"][1] == {"titulo": "Entrega T5", "dia": "2026-11-25", "tipo": "entrega"})
st, r = cel.pedir("POST", "/p/chat", {"text": "recuerda repasar"})
ok("chat avisa lo pendiente", st == 200 and r["pendiente"] == "Crear recordatorio")
st, r = cel.pedir("POST", "/p/confirmar", {"accept": True})
ok("confirmar", st == 200 and r["reply"] == "Hecho, señor." and hud.ATLAS.pending is None)
st, a = cel.pedir("POST", "/p/voz", {"text": "hola"})
ok("voz devuelve audio", st == 200 and a == b"RIFFhola")
ok("detener", cel.pedir("POST", "/p/detener")[0] == 200 and hud.ATLAS.detenido == 1)
ok("oír sin voz no revienta", cel.pedir("POST", "/p/oir", b"RIFFxxxx", tipo="audio/wav")[1].get("error") == "Voz no disponible")
ok("ruta que no existe: 404", cel.pedir("GET", "/api/status")[0] == 404 and cel.pedir("POST", "/p/apagar")[0] == 404)
ok("música: acción desconocida 400", cel.pedir("POST", "/p/musica", {"accion": "borrar"})[0] == 400)

# --- ataques ---
t, n = str(int(time.time() * 1000)), secrets.token_urlsafe(12)
ok("pedido original pasa", cel.pedir("GET", "/p/estado", t=t, n=n)[0] == 200)
ok("el mismo pedido repetido: 401", cel.pedir("GET", "/p/estado", t=t, n=n)[0] == 401)
viejo = str(int((time.time() - P.RELOJ_SEG - 30) * 1000))
ok("pedido con hora vieja: 401", cel.pedir("GET", "/p/estado", t=viejo)[0] == 401)
ok("firma de otra llave: 401", cel.pedir("GET", "/p/estado", llave=ec.generate_private_key(ec.SECP256R1()))[0] == 401)
P._estado["fallos"].clear()
# cuerpo cambiado después de firmar
t, n = str(int(time.time() * 1000)), secrets.token_urlsafe(12)
firma = cel.key.sign(P.texto_firmado("POST", "/p/chat", t, n, b'{"text":"hola"}'), ec.ECDSA(hashes.SHA256()))
c = cel._con()
c.request("POST", "/p/chat", body=b'{"text":"borra todo"}', headers={"Content-Type": "application/json", "X-Atlas-Id": cel.id,
          "X-Atlas-T": t, "X-Atlas-N": n, "X-Atlas-F": base64.b64encode(firma).decode()})
ok("cuerpo cambiado tras firmar: 401", c.getresponse().status == 401 and "borra todo" not in hud.ATLAS.dicho)
c.close()
# firma para otra ruta
firma = cel.key.sign(P.texto_firmado("GET", "/p/estado", t, n + "b", b""), ec.ECDSA(hashes.SHA256()))
c = cel._con()
c.request("POST", "/p/detener", headers={"X-Atlas-Id": cel.id, "X-Atlas-T": t, "X-Atlas-N": n + "b",
                                          "X-Atlas-F": base64.b64encode(firma).decode()})
ok("firma de otra ruta: 401", c.getresponse().status == 401 and hud.ATLAS.detenido == 1)
c.close()
P._estado["fallos"].clear()
# sin TLS no hay respuesta
try:
    pl = http.client.HTTPConnection("127.0.0.1", PUERTO, timeout=5)
    pl.request("GET", "/p/estado")
    plano = pl.getresponse().status
except Exception:  # noqa: BLE001
    plano = None
ok("sin TLS no responde", plano is None)
# uno que se conecta y no dice nada no detiene a los demás
import socket as _socket  # noqa: E402
mudo = _socket.create_connection(("127.0.0.1", PUERTO), timeout=5)
ok("una conexión muda no bloquea al resto", cel.pedir("GET", "/p/estado")[0] == 200)
mudo.close()
# cuerpo enorme
c = cel._con()
c.putrequest("POST", "/p/oir")
c.putheader("Content-Length", str(P.CUERPO_MAX + 1))
c.endheaders()
ok("cuerpo más grande que el tope: 413", c.getresponse().status == 413)
c.close()
# muchos pedidos malos seguidos: deja de responderle a esa dirección
P._estado["fallos"].clear()
for _ in range(P.FALLOS_MAX):
    cel.pedir("GET", "/p/estado", firmar=False)
ok("tras muchos rechazos bloquea la dirección", cel.pedir("GET", "/p/estado")[0] == 403)
P._estado["fallos"].clear()
ok("y después vuelve a atender", cel.pedir("GET", "/p/estado")[0] == 200)

# --- direcciones ---
ok("de fuera se corta antes del saludo TLS", P._Servidor.verify_request(None, None, ("8.8.8.8", 1)) is False
   and P._Servidor.verify_request(None, None, ("192.168.1.9", 1)) is True)
ok("hora que no es un número: se rechaza sin reventar", P._autorizado({"X-Atlas-Id": "x", "X-Atlas-T": "\u00b2", "X-Atlas-N": "12345678", "X-Atlas-F": "x"}, "GET", "/p/estado", b"") is None)
ok("privadas", all(P._privada(x) for x in ("192.168.1.34", "10.0.0.5", "172.20.1.1", "100.101.102.103", "127.0.0.1", "::ffff:192.168.1.9")))
ok("públicas no", not any(P._privada(x) for x in ("8.8.8.8", "100.128.0.1", "172.32.0.1", "200.1.2.3", "no-es-ip")))

# --- desvincular ---
ok("vista lista el celular sin su llave", P.vista()["dispositivos"][0]["nombre"] == "Pixel de prueba" and "pub" not in P.vista()["dispositivos"][0])
ok("desvincular", P.desvincular(cel.id) and P.dispositivos() == [])
ok("desvinculado ya no entra", cel.pedir("GET", "/p/estado")[0] == 401)
ok("desvincular uno que no existe", P.desvincular("nada") is False)

# --- apagar ---
P.activar(False)
ok("apagar cierra y lo recuerda", not P.corriendo() and not P.activo())
try:
    cel._con()
    sigue = True
except Exception:  # noqa: BLE001
    sigue = False
ok("apagado no acepta conexiones", not sigue)

print(f"{total - len(fallas)} de {total} pruebas pasan")
for f in fallas:
    print("  FALLA:", f)
sys.exit(1 if fallas else 0)

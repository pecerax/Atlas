# Prueba de punta a punta con datos sintéticos: keyring, Google y la red están simulados.
import base64, os, struct, sys, json
from types import SimpleNamespace
from unittest import mock
W = sys.argv[1]; sys.path[:0] = [W, os.path.join(W, "vendor_timeline_export")]
import geller_fetch as g
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY = os.urandom(32)
def fx32(f, v): return g.tag(f, 5) + struct.pack('<I', v & 0xffffffff)
def e7(x): return int(round(x * 1e7))
def ts(f, sec): return g.fld_bytes(f, g.fld_varint(1, sec))
def visita(t0, t1, lat, lng):
    point = fx32(1, e7(lat)) + fx32(2, e7(lng))
    top = g.fld_bytes(5, point) + g.fld_varint(2, 1)
    cand = g.fld_bytes(4, top)
    neg = (-180) & ((1 << 64) - 1)
    return ts(1, t0) + ts(2, t1) + g.fld_bytes(3, g.fld_bytes(1, cand)) + g.fld_varint(7, neg) + g.fld_varint(8, neg)
def fila(seg_id, blob, t0, t1, tipo):
    vals = g.fld_bytes(1, g.fld_str(3, seg_id)) + g.fld_bytes(1, g.fld_bytes(4, blob))
    vals += g.fld_bytes(1, g.fld_varint(1, t0)) + g.fld_bytes(1, g.fld_varint(1, t1)) + g.fld_bytes(1, g.fld_varint(1, tipo))
    return g.fld_bytes(5, vals)
cols = ('segment_id', 'semantic_segment', 'start_timestamp_seconds', 'end_timestamp_seconds', 'segment_type')
snap = g.fld_str(1, 'semantic_segment_table') + b''.join(g.fld_str(4, c) for c in cols)
snap += fila('a', visita(1763370000, 1763380000, -33.4500, -70.6600), 1763370000, 1763380000, 1)
snap += fila('b', visita(1763390000, 1763400000, -33.45, -70.66), 1763390000, 1763400000, 1)
inner = g.fld_str(1, 'type.googleapis.com/geller.externaldb.ExternalDbSync') + g.fld_bytes(2, g.fld_bytes(3, snap))
iv = os.urandom(12); enc = iv + AESGCM(KEY).encrypt(iv, inner, None)
payload = g.fld_str(1, 'type.googleapis.com/geller.GellerE2eeElement') + g.fld_bytes(2, g.fld_bytes(1, enc))
result = g.fld_varint(1, g.ODLH) + g.fld_bytes(5, g.fld_bytes(3, payload))
msg = g.fld_bytes(1, g.fld_bytes(2, result) + g.fld_varint(3, g.ODLH))
resp = SimpleNamespace(status_code=200, headers={'grpc-status': '0'}, content=g.grpc_frame(msg))

store = {"email": "x@example.com", "android_id": "0123456789abcdef", "master_token": "aas_et/SINTETICO",
         "clave": base64.b64encode(KEY).decode()}
fake_kr = SimpleNamespace(get_password=lambda s, c: store.get(c), get_keyring=lambda: SimpleNamespace())
client = mock.MagicMock(); client.__enter__.return_value = client; client.post.return_value = resp
fake_httpx = SimpleNamespace(Client=mock.Mock(return_value=client))
fake_gps = SimpleNamespace(perform_oauth=lambda *a, **k: {"Auth": "ya29.SINTETICO"})
with mock.patch.dict(sys.modules, {"keyring": fake_kr, "httpx": fake_httpx, "gpsoauth": fake_gps}):
    import sincronizar
    segs, stats = sincronizar.descargar_segmentos()
print(json.dumps(segs, ensure_ascii=False, indent=1)); print(stats)
hdr = client.post.call_args.kwargs["headers"]["authorization"]; print("auth header:", hdr)
os.makedirs(sys.argv[2], exist_ok=True)
ruta, *n = sincronizar.importar(segs, sys.argv[2]); print("importado:", n)
# protección contra descargas incompletas
try: sincronizar.importar(segs[:1], sys.argv[2]); print("FALLO: debió rechazar")
except RuntimeError as e: print("rechazo correcto:", e)

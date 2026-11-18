"""Atlas por Telegram: hablarle desde el celular a un bot propio (creado con @BotFather).

- Long polling (getUpdates): el PC pregunta a Telegram si hay mensajes. No se abre ningún puerto.
- Solo atiende UN chat: el chat_id guardado por Agregar-telegram.cmd en
  ~/.atlas/connectors/telegram.json. Todo lo demás se ignora sin responder.
- Texto y notas de voz (se transcriben con el mismo reconocimiento de Atlas, Parakeet si está activo).
- Respuesta en texto y, si le mandó una nota de voz, también en audio con la voz de Atlas (Piper).
- Acciones que modifican algo: Telegram muestra botones «Sí, hazlo» / «No». Los botones valen 10 minutos
  y solo para la acción que se pidió desde Telegram. Si hay una acción esperando en la pantalla del PC,
  Telegram no la confirma: avisa que está esperando allá.
- Funciona mientras Atlas esté abierto (corre dentro de hud_server.py).
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
import wave
from pathlib import Path

CONFIG = Path(os.path.expanduser("~")) / ".atlas" / "connectors" / "telegram.json"
API = "https://api.telegram.org"
POLL_TIMEOUT = 50          # segundos que Telegram mantiene abierta cada consulta
BUTTON_TTL = 600           # los botones de confirmar valen 10 minutos
MAX_VOICE_SECONDS = 180
MAX_VOICE_BYTES = 8 * 1024 * 1024
OLD_MESSAGE = 300          # mensajes de hace más de 5 minutos (Atlas estaba cerrado) se ignoran
VOZ_MODOS = ("si_nota", "siempre", "nunca")  # cuándo responde también con audio


# ----------------------------------------------------------------------------- funciones puras (con pruebas)
def load_config(path: Path = CONFIG) -> dict | None:
    try:
        from openjarvis.security import atlas_secretos

        cfg = atlas_secretos.cargar_json(path)  # el token está cifrado en el Administrador de credenciales
        if not isinstance(cfg, dict):
            return None
    except Exception:  # noqa: BLE001
        return None
    if not cfg.get("token") or not str(cfg.get("chat_id", "")).lstrip("-").isdigit():
        return None
    cfg["chat_id"] = int(cfg["chat_id"])
    if cfg.get("voz") not in VOZ_MODOS:
        cfg["voz"] = "si_nota"
    return cfg


def allowed(update: dict, chat_id: int) -> bool:
    """Solo el chat privado del dueño: el chat y quien escribe tienen que ser ese mismo id."""
    msg = update.get("message") or update.get("edited_message")
    if msg:
        chat, frm = msg.get("chat") or {}, msg.get("from") or {}
        return chat.get("type") == "private" and chat.get("id") == chat_id and frm.get("id") == chat_id
    cb = update.get("callback_query")
    if cb:
        frm = cb.get("from") or {}
        chat = ((cb.get("message") or {}).get("chat")) or {}
        return frm.get("id") == chat_id and chat.get("id") == chat_id
    return False


def for_telegram(reply: str) -> str:
    """La respuesta pensada para la pantalla del PC, ajustada para el chat."""
    t = re.sub(r"\s*Conf[ií]rm\w* en (la )?pantalla[^.]*\.", " Use los botones de abajo.", reply or "")
    t = re.sub(r"\s*(?:que lo confirme|confírmelo|confirme) en pantalla o diciendo «s[ií]»\.?", " use los botones de abajo.", t)
    t = re.sub(r"(Use los botones de abajo\.\s*)+", "Use los botones de abajo.", t).strip()
    return t[:4000]


def wants_voice(cfg: dict, came_as_voice: bool) -> bool:
    modo = cfg.get("voz", "si_nota")
    return modo == "siempre" or (modo == "si_nota" and came_as_voice)


def ogg_to_wav(data: bytes) -> tuple[bytes, float]:
    """Nota de voz de Telegram (OGG/Opus) -> WAV 16 kHz mono de 16 bits, y su duración en segundos."""
    import av
    import numpy as np

    pcm = []
    with av.open(io.BytesIO(data)) as inp:
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in inp.decode(audio=0):
            for f in rs.resample(frame):
                pcm.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            pcm.append(f.to_ndarray().reshape(-1))
    a = np.concatenate(pcm).astype(np.int16) if pcm else np.zeros(0, dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(a.tobytes())
    return buf.getvalue(), len(a) / 16000


def wav_to_ogg(wav_bytes: bytes) -> bytes:
    """WAV (Piper) -> OGG/Opus, el formato que Telegram muestra como nota de voz."""
    import av
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
    out = io.BytesIO()
    with av.open(out, mode="w", format="ogg") as oc:
        st = oc.add_stream("libopus", rate=48000, layout="mono")
        st.bit_rate = 32000
        frame = av.AudioFrame.from_ndarray(a.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = sr
        rs = av.AudioResampler(format="s16", layout="mono", rate=48000, frame_size=960)
        for f in list(rs.resample(frame)) + list(rs.resample(None)):
            for p in st.encode(f):
                oc.mux(p)
        for p in st.encode(None):
            oc.mux(p)
    return out.getvalue()


# ----------------------------------------------------------------------------- el puente
class TelegramBridge:
    def __init__(self, atlas, cfg: dict, log=print, hallucinations=(), session=None) -> None:
        self.j = atlas
        self.cfg = cfg
        self.log = log
        self.halluc = tuple(hallucinations)
        self.offset = 0
        self.started = time.time()
        self.stop = threading.Event()
        self.ignored: set = set()
        if session is None:
            import requests

            session = requests.Session()
        self.http = session

    # ---- API de Telegram
    def call(self, method: str, http_timeout: float = 30, files=None, **params):
        url = f"{API}/bot{self.cfg['token']}/{method}"
        if files:
            r = self.http.post(url, data=params, files=files, timeout=http_timeout)
        else:
            r = self.http.post(url, json=params, timeout=http_timeout)
        data = r.json() if r.content else {}
        if not data.get("ok"):
            raise TelegramError(r.status_code, str(data.get("description", r.text))[:200])
        return data.get("result")

    def send(self, text: str, **extra):
        try:
            return self.call("sendMessage", chat_id=self.cfg["chat_id"], text=text[:4000] or "…", **extra)
        except Exception as exc:  # noqa: BLE001
            self.log(f"Telegram: no pude enviar el mensaje ({exc})")
            return None

    # ---- bucle principal
    def run(self) -> None:
        self.log(f"Telegram: escuchando el bot @{self.cfg.get('bot', '?')} (solo su chat)")
        wait = 2.0
        while not self.stop.is_set():
            try:
                ups = self.call("getUpdates", http_timeout=POLL_TIMEOUT + 15, offset=self.offset,
                                timeout=POLL_TIMEOUT, allowed_updates=["message", "callback_query"]) or []
                wait = 2.0
            except TelegramError as exc:
                if exc.code == 401:
                    self.log("Telegram: el token no es válido. Vuelva a correr Agregar-telegram.cmd. Lo apago.")
                    return
                if exc.code == 409:
                    self.log("Telegram: otro programa está leyendo este bot (¿Atlas abierto dos veces o el instalador?). Reintento.")
                else:
                    self.log(f"Telegram: error {exc}")
                self.stop.wait(wait)
                wait = min(wait * 2, 120)
                continue
            except Exception as exc:  # noqa: BLE001  (sin internet, etc.)
                self.log(f"Telegram: sin conexión ({type(exc).__name__}); reintento en {wait:.0f} s")
                self.stop.wait(wait)
                wait = min(wait * 2, 120)
                continue
            for up in ups:
                self.offset = max(self.offset, int(up.get("update_id", 0)) + 1)
                try:
                    self.handle(up)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"Telegram: falló un mensaje ({type(exc).__name__}: {exc})")
                    self.send("Lo siento, señor, algo falló al procesar eso.")

    def handle(self, up: dict) -> None:
        if not allowed(up, self.cfg["chat_id"]):
            who = ((up.get("message") or up.get("callback_query") or {}).get("from") or {}).get("id")
            if who not in self.ignored:  # anotarlo una vez, sin responderle nada
                self.ignored.add(who)
                self.log(f"Telegram: ignoré un mensaje de un chat no autorizado (id {who})")
            return
        if "callback_query" in up:
            return self.on_button(up["callback_query"])
        msg = up.get("message") or {}
        if msg.get("date", 0) < self.started - OLD_MESSAGE:
            return  # se mandó mientras Atlas estaba cerrado
        voice = msg.get("voice") or msg.get("audio")
        if voice:
            text = self.transcribe(voice)
            if not text:
                return
            self.send(f"Entendí: «{text}»")
            return self.answer(text, came_as_voice=True)
        text = (msg.get("text") or "").strip()
        if not text:
            self.send("Por ahora entiendo texto y notas de voz, señor.")
            return
        if text.startswith("/start") or text.startswith("/ayuda"):
            self.send("A sus órdenes, señor. Escríbame o mándeme una nota de voz. "
                      "Lo que modifique algo se lo voy a pedir confirmar con botones.")
            return
        self.answer(text, came_as_voice=False)

    def transcribe(self, voice: dict) -> str:
        if int(voice.get("duration") or 0) > MAX_VOICE_SECONDS or int(voice.get("file_size") or 0) > MAX_VOICE_BYTES:
            self.send("Esa nota es muy larga, señor. Mándeme una de menos de 3 minutos.")
            return ""
        voz = getattr(self.j, "voice", None)
        backend = voz.get_stt_backend() if voz is not None else None
        if backend is None:
            self.send("El reconocimiento de voz aún está cargando, señor. Pruebe en un momento o escríbame.")
            return ""
        self.call("sendChatAction", chat_id=self.cfg["chat_id"], action="typing")
        info = self.call("getFile", file_id=voice["file_id"])
        r = self.http.get(f"{API}/file/bot{self.cfg['token']}/{info['file_path']}", timeout=60)
        r.raise_for_status()
        wav, _secs = ogg_to_wav(r.content)
        text = (self.j._transcribe(backend, wav) or "").strip()
        low = text.lower()
        if any(h in low for h in self.halluc) or len(low.strip(" .,!?¿¡")) < 2:
            self.send("No le escuché bien, señor. ¿Puede repetirlo o escribírmelo?")
            return ""
        return text

    def answer(self, text: str, came_as_voice: bool) -> None:
        j = self.j
        pend = j.pending
        if pend and pend.get("origen") != "telegram":
            self.send(f"Hay una acción esperando confirmación en la pantalla del PC: {pend.get('summary', '')}. "
                      "Confírmela o cancélela allá y después sigo, señor.")
            return
        self.log(f"Telegram: {text[:200]}")
        if not getattr(j, "ready", True):  # recién abierto: esperar a que cargue el modelo en vez de decir "cargando"
            self.send("Un momento, señor, estoy terminando de arrancar.")
            for _ in range(180):
                if getattr(j, "ready", True) or getattr(j, "error", ""):
                    break
                time.sleep(1)
        try:
            self.call("sendChatAction", chat_id=self.cfg["chat_id"], action="typing")
        except Exception:  # noqa: BLE001
            pass
        out = j.chat(text)
        reply = out.get("reply") or out.get("error") or "…"
        new = j.pending
        if new and new is not pend:  # esta orden preparó una acción: botones para confirmarla
            new["origen"] = "telegram"
            new["tg_nonce"] = secrets.token_hex(6)
            new["tg_t"] = time.time()
            kb = {"inline_keyboard": [[{"text": "Sí, hazlo", "callback_data": "ok:" + new["tg_nonce"]},
                                       {"text": "No", "callback_data": "no:" + new["tg_nonce"]}]]}
            self.send(for_telegram(reply), reply_markup=kb)
        else:
            self.send(for_telegram(reply))
        if wants_voice(self.cfg, came_as_voice):
            self.send_voice(reply)

    def send_voice(self, text: str) -> None:
        try:
            audio, _ = self.j.speak(text)
            if not audio:
                return
            ogg = wav_to_ogg(audio)
            self.call("sendVoice", http_timeout=60, chat_id=self.cfg["chat_id"],
                      files={"voice": ("atlas.ogg", ogg, "audio/ogg")})
        except Exception as exc:  # noqa: BLE001
            self.log(f"Telegram: no pude mandar el audio ({exc})")

    def on_button(self, cb: dict) -> None:
        data = str(cb.get("data") or "")
        accept, _, nonce = data.partition(":")
        pend = self.j.pending
        msg = cb.get("message") or {}
        valid = (pend is not None and pend.get("origen") == "telegram" and nonce and pend.get("tg_nonce") == nonce)
        expired = valid and time.time() - pend.get("tg_t", 0) > BUTTON_TTL
        try:
            self.call("answerCallbackQuery", callback_query_id=cb.get("id"))
            self.call("editMessageReplyMarkup", chat_id=self.cfg["chat_id"], message_id=msg.get("message_id"),
                      reply_markup={"inline_keyboard": []})
        except Exception:  # noqa: BLE001
            pass
        if not valid:
            self.send("Esa acción ya no está pendiente, señor (se confirmó, se canceló o pidió otra). No hice nada.")
            return
        if expired:
            self.j.pending = None
            self.send("Pasaron más de 10 minutos y la cancelé por seguridad, señor. Si aún la quiere, pídamela de nuevo.")
            return
        self.log(f"Telegram: botón {'Sí' if accept == 'ok' else 'No'} para «{pend.get('summary', '')}»")
        out = self.j.confirm(accept == "ok")
        self.send(for_telegram(out.get("reply") or out.get("error") or "…"))


class TelegramError(Exception):
    def __init__(self, code: int, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def start(atlas, log=print, hallucinations=()) -> TelegramBridge | None:
    """Lo llama hud_server.py al arrancar. Sin telegram.json no hace nada."""
    cfg = load_config()
    if not cfg:
        return None
    bridge = TelegramBridge(atlas, cfg, log=log, hallucinations=hallucinations)
    threading.Thread(target=bridge.run, daemon=True, name="telegram").start()
    return bridge

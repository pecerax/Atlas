"""Espectro de Baco: escucha lo que sale por los parlantes (WASAPI en modo loopback, con comtypes) y lo reparte en bandas.

18-11-2026. bandas() -> {"ok", "b": [24 floats 0..1, de graves a agudos], "silencio", "error"}: siempre las mismas claves.
La captura corre en un hilo solo mientras la página la pide: si pasan 6 s sin pedidos, se detiene sola.
19-11-2026: además detecta los golpes de bajo (bombo) en el mismo hilo, cada ~10 ms de audio (Golpes): bandas() trae
"g" (cuántos pulsos van), "gf" (fuerza del último, 0..1), "bp" (segundos entre pulsos) y "bn" (cuánto falta para el
próximo): la página agenda cada onda para que salga justo en el pulso.
Sin sonido Windows no entrega paquetes y las bandas bajan a cero.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import POINTER, c_int, c_longlong, c_uint32, c_ulonglong, c_void_p
from ctypes.wintypes import DWORD

N_BANDAS = 24
N_FFT = 2048
F_MIN, F_MAX = 40.0, 16000.0
INCLINACION = 2.5  # dB por octava sobre 40 Hz (con ruido rosa las barras quedan parejas)

_lock = threading.Lock()
_estado: dict = {"hilo": None, "pedido": 0.0, "sr": 48000, "buf": None, "error": "", "t_dato": 0.0, "golpes": None}


class Golpes:
    """Pulso de la canción para las ondas de la portada.

    1) Cada ~10 ms de audio: «flujo espectral» (cuánto SUBE la energía de cada frecuencia), sobre todo en los graves
       (40-180 Hz, el bombo) y un poco en el resto: un bajo o un acorde sostenido no suma, un golpe sí.
    2) Cada medio segundo, con los últimos 8 s de ese flujo: el tempo (autocorrelación entre 60 y 200 BPM, prefiriendo
       ~120) y la fase (dónde caen los golpes). Con eso marca cada pulso a tiempo, aunque el bajo meta notas entre medio.
    3) Si la canción no tiene un pulso claro (ambiente, intro), marca solo los golpes fuertes sueltos.
    cuenta sube en 1 por cada pulso; fuerza (0..1) es qué tan marcado fue.
    """

    PASO, VENTANA = 512, 2048
    RETRASO = 0.02   # s: cuánto después del golpe real lo marca el flujo espectral (medido con bombos sintéticos)

    def __init__(self, sr: int):
        import numpy as np

        self.np, self.sr = np, sr
        self.fps = sr / self.PASO
        self.buf = np.zeros(self.VENTANA, dtype=np.float32)
        self.pend = 0
        self.ven = np.hanning(self.VENTANA).astype(np.float32)
        f = np.fft.rfftfreq(self.VENTANA, 1 / sr)
        self.graves = (f >= 40) & (f <= 180)
        self.resto = (f > 180) & (f <= 8000)
        self.prev = None
        self.env: list = []                     # flujo por paso, últimos 8 s
        self.n_env = int(8 * self.fps)
        self.paso_n = 0                          # pasos procesados
        self.periodo = 0.0                       # en pasos (0 = sin pulso claro)
        self.proximo = 0.0                       # paso del próximo pulso
        self.ultimo = -10**9                     # paso del último golpe marcado
        self.cand = None
        self.t_audio = 0.0                       # time.monotonic() del último audio recibido
        self.nivel = 0.0                         # volumen (RMS) del último medio segundo, más o menos
        self.flojo = 0                           # medias ventanas seguidas sin pulso claro
        self.desvio = 0                          # medias ventanas seguidas en que la fase no calza
        self.cuenta = 0
        self.fuerza = 0.0
        self.tiempos: list = []                  # en segundos (para las pruebas)

    def alimentar(self, mono) -> None:
        np = self.np
        mono = np.asarray(mono, dtype=np.float32)
        self.t_audio = time.monotonic()
        if len(mono):
            self.nivel = 0.9 * self.nivel + 0.1 * float(np.sqrt(np.mean(mono * mono)))
        while len(mono):
            k = min(len(mono), self.PASO - self.pend)
            self.buf[:-k] = self.buf[k:]
            self.buf[-k:] = mono[:k]
            mono = mono[k:]
            self.pend += k
            if self.pend >= self.PASO:
                self.pend = 0
                self._paso()

    def resumen(self) -> dict:
        """g: pulsos marcados; gf: fuerza del último; bp: segundos entre pulsos (0 si no hay pulso claro);
        bn: segundos hasta el próximo, para que la página lo lance justo a tiempo."""
        r = {"g": self.cuenta, "gf": self.fuerza, "bp": 0.0, "bn": 0.0}
        quieto = time.monotonic() - self.t_audio
        # Con la canción en pausa Windows deja de entregar audio: la grilla quedaba congelada y la página seguía
        # agendando ondas. Sin audio fresco (o en silencio) no hay pulso.
        if self.periodo and quieto < 0.12 and self.nivel > 1e-4:
            bp = self.periodo / self.fps
            # el flujo marca el golpe ~media ventana después de que suena (la ventana de análisis es de 43 ms);
            # y desde el último paquete ya pasó un poco de tiempo
            bn = (self.proximo - self.paso_n) / self.fps - self.pend / self.sr - quieto - self.RETRASO
            while bn < 0:
                bn += bp
            r["bp"], r["bn"] = round(bp, 4), round(bn, 4)
        return r

    def _marcar(self, fuerza: float) -> None:
        self.ultimo = self.paso_n
        self.cuenta += 1
        self.fuerza = round(max(0.15, min(1.0, fuerza)), 3)
        self.tiempos.append(self.paso_n * self.PASO / self.sr)

    def _tempo(self) -> None:
        """Tempo y fase con «inercia»: una canción no cambia de tempo cada medio segundo, así que una vez enganchado
        se queda con el pulso que tiene mientras siga calzando, en vez de saltar al doble o a la mitad (bombo en 1 y 3,
        caja en 2 y 4) o soltarse en un compás más suave. La fase se corrige de a poco, no a saltos."""
        np = self.np
        e = np.asarray(self.env, dtype=np.float64)
        if len(e) < 3 * self.fps or e.std() < 1e-6:
            self._soltar()
            return
        e = e - e.mean()
        lo, hi = int(self.fps * 60 / 200), int(self.fps * 60 / 60)
        n = len(e)
        F = np.fft.rfft(e, 2 * n)
        acc = np.fft.irfft(F * np.conj(F))[:n] / (n - np.arange(n))   # autocorrelación de todos los desfases
        ac = acc[lo:hi + 1]
        lags = np.arange(lo, hi + 1)
        bpm = 60 * self.fps / lags
        peso = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)   # a igualdad, el pulso «bailable» (~120)
        sc = ac * peso
        energia = np.dot(e, e) / len(e) + 1e-9
        b = int(np.argmax(sc))
        if self.periodo:   # enganchado: si el pulso actual sigue calzando razonablemente, se queda con él
            j = int(round(self.periodo)) - lo
            if 1 <= j < len(sc) - 1:
                j = j - 1 + int(np.argmax(sc[j - 1:j + 2]))
                if sc[j] >= 0.6 * sc[b] and ac[j] / energia >= 0.05:
                    b = j
        else:              # recién enganchando: entre un pulso y su doble, prefiere el más rápido si también calza
            Lh = lags[b] / 2
            if Lh >= lo:
                jh = int(round(Lh)) - lo
                jh = max(0, min(len(sc) - 1, jh - 1 + int(np.argmax(sc[max(0, jh - 1):jh + 2]))))
                if sc[jh] >= 0.5 * sc[b] and 60 * self.fps / lags[jh] <= 180:
                    b = jh
        conf = ac[b] / energia
        if conf < (0.06 if self.periodo else 0.12):
            self.flojo += 1
            if self.flojo >= 6:   # ~3 s sin pulso claro: ahora sí, se suelta
                self._soltar()
            return
        self.flojo = 0
        L = float(lags[b])
        # afinar: un paso son ~10 ms, y 1 paso de error en el período corre la grilla un compás después. Se busca el
        # período fino que mejor calza con sus múltiplos (2, 3, 4 pulsos), que se miden con mucha más precisión.
        finos = np.arange(L - 1.5, L + 1.5001, 0.05)
        ks = np.arange(1, 5)
        x = finos[:, None] * ks[None, :]
        x = np.where(x < n * 0.6, x, np.nan)
        i0 = np.floor(np.nan_to_num(x)).astype(int)
        fr = np.nan_to_num(x) - i0
        val = acc[i0] * (1 - fr) + acc[np.minimum(i0 + 1, n - 1)] * fr
        val = np.where(np.isnan(x), 0.0, val)
        L = float(finos[int(np.argmax(val.sum(axis=1)))])
        if self.periodo and abs(L - self.periodo) < 0.04 * self.periodo:
            L = 0.7 * self.periodo + 0.3 * L
        # fase: el desfase que junta más flujo sobre la grilla
        Li = int(round(L))
        mejor, fase = -1e18, 0
        for o in range(Li):
            idx = (n - 1 - o - np.arange(0, n - o, L)).astype(int)
            idx = idx[idx >= 0]
            v = e[idx].sum()
            if v > mejor:
                mejor, fase = v, o
        prox = self.paso_n - fase + L
        while prox <= self.paso_n:
            prox += L
        if self.periodo:
            # diferencia con la grilla que ya llevaba, entre -L/2 y L/2: se corrige de a poco
            d = (prox - self.proximo + L / 2) % L - L / 2
            if abs(d) < 0.25 * L:
                self.desvio = 0
                prox = self.proximo + 0.35 * d
            else:
                self.desvio += 1
                if self.desvio < 3:   # un desacuerdo aislado (un quiebre, un fill) no mueve la grilla
                    prox = self.proximo
                else:
                    self.desvio = 0
            while prox <= self.paso_n:
                prox += L
        if prox - self.ultimo < 0.5 * L:   # no marcar dos veces el mismo pulso al reajustar
            prox += L
        self.periodo, self.proximo = L, prox

    def _soltar(self) -> None:
        self.periodo, self.flojo, self.desvio = 0.0, 0, 0

    def _paso(self) -> None:
        np = self.np
        mag = np.abs(np.fft.rfft(self.buf * self.ven))
        lg = np.log1p(mag * 10.0)
        self.paso_n += 1
        if self.prev is None:
            self.prev = lg
            return
        d = np.maximum(0.0, lg - self.prev)
        self.prev = lg
        flujo = float(d[self.graves].mean() + 0.2 * d[self.resto].mean())   # promedios: los platillos no tapan al bombo
        self.env.append(flujo)
        if len(self.env) > self.n_env:
            del self.env[0]
        if self.paso_n % int(self.fps / 2) == 0:
            self._tempo()
        reciente = self.env[-int(1.5 * self.fps):]
        m = sum(reciente) / len(reciente)
        sd = (sum((x - m) ** 2 for x in reciente) / len(reciente)) ** 0.5
        if self.periodo:
            if self.paso_n >= self.proximo:
                ventana = self.env[-3:]
                if self.nivel > 1e-4:   # con la canción en pausa (paquetes en silencio) la grilla sigue, pero sin ondas
                    self._marcar(0.35 + 0.65 * (max(ventana) - m) / (3 * sd + 1e-6))
                self.proximo += self.periodo
            return
        # sin pulso claro: golpes fuertes sueltos (en el pico, con 0,25 s entre ellos)
        if self.cand and flujo < self.cand:
            v, self.cand = self.cand, None
            if self.paso_n - self.ultimo >= 0.25 * self.fps:
                self._marcar((v - m) / (3 * sd + 1e-6))
        elif len(reciente) > 8 and flujo > m + 2.0 * sd + 0.2 and (not self.cand or flujo >= self.cand):
            self.cand = flujo


def _interfaces():
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(c_void_p), "data"), (["out"], POINTER(c_uint32), "frames"),
                      (["out"], POINTER(DWORD), "flags"), (["out"], POINTER(c_ulonglong), "pos"),
                      (["out"], POINTER(c_ulonglong), "qpc")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "n")),
        ]

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Initialize", (["in"], c_int, "mode"), (["in"], DWORD, "flags"),
                      (["in"], c_longlong, "dur"), (["in"], c_longlong, "per"), (["in"], c_void_p, "fmt"),
                      (["in"], c_void_p, "sesion")),
            COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "n")),
            COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "l")),
            COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "n")),
            COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int, "mode"), (["in"], c_void_p, "fmt"),
                      (["out"], POINTER(c_void_p), "cerca")),
            COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(c_void_p), "fmt")),
            COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_longlong), "a"), (["out"], POINTER(c_longlong), "b")),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p, "h")),
            COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(POINTER(IUnknown)), "obj")),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "ctx"),
                      (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IUnknown)), "obj")),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int, "flow"), (["in"], DWORD, "mask"),
                      (["out"], POINTER(c_void_p), "c")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "flow"), (["in"], c_int, "role"),
                      (["out"], POINTER(POINTER(IMMDevice)), "d")),
        ]

    return comtypes, GUID, IAudioClient, IAudioCaptureClient, IMMDeviceEnumerator


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16), ("nSamplesPerSec", ctypes.c_uint32),
                ("nAvgBytesPerSec", ctypes.c_uint32), ("nBlockAlign", ctypes.c_uint16), ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16)]


def _es_float(ptr: int, wf: WAVEFORMATEX) -> bool:
    if wf.wFormatTag == 3:
        return True
    if wf.wFormatTag == 0xFFFE and wf.cbSize >= 22:  # WAVEFORMATEXTENSIBLE: SubFormat empieza en el byte 24
        return ctypes.c_uint32.from_address(ptr + 24).value == 3
    return False


def _captura() -> None:
    import numpy as np

    comtypes, GUID, IAudioClient, IAudioCaptureClient, IMMDeviceEnumerator = _interfaces()
    comtypes.CoInitialize()
    cliente = None
    try:
        en = comtypes.CoCreateInstance(GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), IMMDeviceEnumerator, comtypes.CLSCTX_ALL)
        dev = en.GetDefaultAudioEndpoint(0, 0)  # eRender, eConsole: lo que suena por los parlantes
        cliente = dev.Activate(ctypes.byref(IAudioClient._iid_), comtypes.CLSCTX_ALL, None).QueryInterface(IAudioClient)
        pfmt = cliente.GetMixFormat()
        wf = WAVEFORMATEX.from_address(pfmt)
        canales, bloque, sr = wf.nChannels, wf.nBlockAlign, wf.nSamplesPerSec
        flotante, bits = _es_float(pfmt, wf), wf.wBitsPerSample
        cliente.Initialize(0, 0x00020000, 2_000_000, 0, pfmt, None)  # compartido, LOOPBACK, búfer de 200 ms
        cap = cliente.GetService(ctypes.byref(IAudioCaptureClient._iid_)).QueryInterface(IAudioCaptureClient)
        cliente.Start()
        with _lock:
            _estado.update(sr=sr, buf=np.zeros(N_FFT * 2, dtype=np.float32), error="", golpes=Golpes(sr))
        golpes = _estado["golpes"]
        while time.time() - _estado["pedido"] < 6:
            n = cap.GetNextPacketSize()
            if not n:
                time.sleep(0.012)
                continue
            while n:
                data, frames, flags, _pos, _qpc = cap.GetBuffer()
                if frames:
                    if flags & 0x2 or not data:  # AUDCLNT_BUFFERFLAGS_SILENT
                        mono = np.zeros(frames, dtype=np.float32)
                    else:
                        crudo = ctypes.string_at(data, frames * bloque)
                        if flotante and bits == 32:
                            x = np.frombuffer(crudo, dtype=np.float32)
                        elif bits == 16:
                            x = np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
                        elif bits == 32:
                            x = np.frombuffer(crudo, dtype=np.int32).astype(np.float32) / 2147483648.0
                        else:
                            x = np.zeros(frames * canales, dtype=np.float32)
                        mono = x.reshape(-1, canales).mean(axis=1) if canales > 1 else x
                    with _lock:
                        b = _estado["buf"]
                        k = min(len(mono), len(b))
                        b[:-k] = b[k:]
                        b[-k:] = mono[-k:]
                        _estado["t_dato"] = time.time()
                    golpes.alimentar(mono)
                cap.ReleaseBuffer(frames)
                n = cap.GetNextPacketSize()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _estado["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    finally:
        try:
            if cliente is not None:
                cliente.Stop()
        except Exception:  # noqa: BLE001
            pass
        cliente = None
        with _lock:
            _estado["hilo"] = None
        comtypes.CoUninitialize()


def bandas_de(muestras, sr: int):
    """24 bandas logarítmicas de 40 Hz a 16 kHz, 0..1 (−65 dB → 0, −5 dB → 1, más la inclinación). Floats de Python."""
    import numpy as np

    x = np.asarray(muestras[-N_FFT:], dtype=np.float32)
    if len(x) < N_FFT:
        x = np.pad(x, (N_FFT - len(x), 0))
    mag = np.abs(np.fft.rfft(x * np.hanning(N_FFT))) / (N_FFT / 4)
    frec = np.fft.rfftfreq(N_FFT, 1 / sr)
    bordes = np.geomspace(F_MIN, min(F_MAX, sr / 2 - 1), N_BANDAS + 1)
    out = []
    for a, b in zip(bordes[:-1], bordes[1:]):
        sel = mag[(frec >= a) & (frec < b)]
        if not len(sel):  # banda más angosta que la resolución: el valor más cercano
            sel = mag[[int(np.argmin(np.abs(frec - (a + b) / 2)))]]
        db = 20 * np.log10(float(sel.max()) + 1e-9)
        db += INCLINACION * np.log2(np.sqrt(a * b) / F_MIN)  # la música trae menos energía arriba: así los agudos se ven
        out.append(round(float(min(1.0, max(0.0, (db + 65) / 60))), 3))
    return out


def bandas() -> dict:
    with _lock:
        _estado["pedido"] = time.time()
        if _estado["hilo"] is None:
            if _estado["error"] and time.time() - _estado.get("t_error", 0) < 5:
                return {"ok": False, "b": [0.0] * N_BANDAS, "silencio": True, "error": _estado["error"]}
            _estado["t_error"] = time.time()
            _estado["error"] = ""
            h = threading.Thread(target=_captura, name="baco-espectro", daemon=True)
            _estado["hilo"] = h
            h.start()
        buf, sr, err, t_dato = _estado["buf"], _estado["sr"], _estado["error"], _estado["t_dato"]
        buf = None if buf is None else buf.copy()
        G = _estado["golpes"]
        g = G.resumen() if G else {"g": 0, "gf": 0.0, "bp": 0.0, "bn": 0.0}
    if err:
        return {"ok": False, "b": [0.0] * N_BANDAS, "silencio": True, "error": err}
    if buf is None or time.time() - t_dato > 0.5:  # sin sonido: Windows no manda nada
        return {"ok": True, "b": [0.0] * N_BANDAS, "silencio": True, "error": "", **g}
    return {"ok": True, "b": bandas_de(buf, sr), "silencio": False, "error": "", **g}

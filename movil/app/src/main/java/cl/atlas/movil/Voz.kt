package cl.atlas.movil

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Build
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/**
 * Graba lo que dice el usuario (16 kHz, mono, 16 bits) y lo entrega como WAV: el mismo formato que usa el oído de
 * Atlas en el PC. Se detiene sola tras 1,4 s de silencio después de haber escuchado voz, o a los 60 s.
 */
class Grabadora(private val ctx: Context) {
    private companion object {
        const val HZ = 16000
        const val MAX_SEG = 60
        const val UMBRAL = 900.0        // volumen (RMS) sobre el que se considera voz
        const val SILENCIO_MS = 1400
    }

    @Volatile private var hilo: Thread? = null
    @Volatile private var seguir = false
    @Volatile private var botar = false

    fun grabando(): Boolean = hilo != null

    /** alTerminar recibe el WAV, o null si se canceló o no se pudo grabar. Se llama desde el hilo de grabación. */
    @SuppressLint("MissingPermission")
    fun empezar(alTerminar: (ByteArray?) -> Unit) {
        if (hilo != null) return
        seguir = true
        botar = false
        val t = Thread {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val conAudifono = usarMicrofonoDelAudifono(am)
            var rec: AudioRecord? = null
            var wav: ByteArray? = null
            try {
                val minimo = AudioRecord.getMinBufferSize(HZ, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
                val fuente = if (conAudifono) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.VOICE_RECOGNITION
                rec = AudioRecord(fuente, HZ, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimo, HZ))
                if (rec.state != AudioRecord.STATE_INITIALIZED) throw IllegalStateException("micrófono ocupado")
                rec.startRecording()
                val pcm = ByteArrayOutputStream()
                val buf = ShortArray(HZ / 10)   // 100 ms
                var huboVoz = false
                var silencioMs = 0
                while (seguir && pcm.size() < HZ * 2 * MAX_SEG) {
                    val n = rec.read(buf, 0, buf.size)
                    if (n <= 0) break
                    var suma = 0.0
                    for (i in 0 until n) suma += buf[i].toDouble() * buf[i]
                    val rms = sqrt(suma / n)
                    if (rms > UMBRAL) {
                        huboVoz = true
                        silencioMs = 0
                    } else if (huboVoz) {
                        silencioMs += n * 1000 / HZ
                    }
                    val bytes = ByteBuffer.allocate(n * 2).order(ByteOrder.LITTLE_ENDIAN)
                    for (i in 0 until n) bytes.putShort(buf[i])
                    pcm.write(bytes.array())
                    if (huboVoz && silencioMs >= SILENCIO_MS) break
                }
                if (!botar && pcm.size() > HZ / 2) wav = aWav(pcm.toByteArray())
            } catch (_: Exception) {
                wav = null
            } finally {
                try {
                    rec?.stop()
                } catch (_: Exception) {
                }
                rec?.release()
                if (conAudifono) soltarAudifono(am)
                hilo = null
            }
            alTerminar(if (botar) null else wav)
        }
        hilo = t
        t.start()
    }

    fun parar() {
        seguir = false
    }

    fun cancelar() {
        botar = true
        seguir = false
    }

    /** Si hay un audífono Bluetooth conectado, se pide su micrófono (Android 12 o más). */
    private fun usarMicrofonoDelAudifono(am: AudioManager): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return false
        return try {
            val d = am.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
            } ?: return false
            am.mode = AudioManager.MODE_IN_COMMUNICATION
            am.setCommunicationDevice(d)
        } catch (_: Exception) {
            false
        }
    }

    private fun soltarAudifono(am: AudioManager) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        try {
            am.clearCommunicationDevice()
            am.mode = AudioManager.MODE_NORMAL
        } catch (_: Exception) {
        }
    }

    private fun aWav(pcm: ByteArray): ByteArray {
        val b = ByteBuffer.allocate(44 + pcm.size).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
        b.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(HZ).putInt(HZ * 2).putShort(2).putShort(16)
        b.put("data".toByteArray()).putInt(pcm.size).put(pcm)
        return b.array()
    }
}

/** Reproduce la voz de Atlas (el WAV que sintetiza el PC). Sale por el audífono si hay uno conectado. */
class Parlante(private val ctx: Context) {
    private var mp: MediaPlayer? = null
    private var archivo: File? = null

    @Synchronized
    fun tocar(wav: ByteArray, alTerminar: () -> Unit) {
        callar()
        try {
            val f = File.createTempFile("voz", ".wav", ctx.cacheDir)
            f.writeBytes(wav)
            archivo = f
            val p = MediaPlayer()
            p.setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            )
            p.setDataSource(f.absolutePath)
            p.setOnCompletionListener {
                callar()
                alTerminar()
            }
            p.setOnErrorListener { _, _, _ ->
                callar()
                alTerminar()
                true
            }
            p.prepare()
            p.start()
            mp = p
        } catch (_: Exception) {
            callar()
            alTerminar()
        }
    }

    @Synchronized
    fun callar() {
        try {
            mp?.release()
        } catch (_: Exception) {
        }
        mp = null
        archivo?.delete()
        archivo = null
    }

    @Synchronized
    fun sonando(): Boolean = mp != null
}

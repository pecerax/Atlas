package cl.atlas.movil

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.URL
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.X509TrustManager

/** Lo que vuelve del PC: código HTTP (0 = no se pudo llegar), el cuerpo y su tipo. */
class Respuesta(val estado: Int, val cuerpo: ByteArray, val tipo: String) {
    fun texto(): String = String(cuerpo, Charsets.UTF_8)
}

/**
 * El lado del celular del Puente Atlas (hud/atlas_puente.py en el PC).
 *
 * - La llave privada se crea en el almacén seguro de Android (AndroidKeyStore) y no se puede sacar de ahí.
 * - Al PC se le cree por la huella de su certificado, que llegó en el QR, y no por su nombre ni por una autoridad.
 * - Cada pedido va firmado: método, ruta, hora, número de un solo uso y hash del cuerpo.
 */
class Puente(ctx: Context) {
    private val prefs = ctx.getSharedPreferences("puente", Context.MODE_PRIVATE)
    private val azar = SecureRandom()

    private companion object {
        const val ALIAS = "atlas_puente"
        const val CONECTAR_MS = 2500
    }

    // ---- el vínculo guardado
    fun vinculado(): Boolean = prefs.contains("id")

    /** Para la pantalla: nombre del PC, direcciones y por cuál se llegó la última vez. Vacío si no hay vínculo. */
    fun vinculoJson(): String {
        if (!vinculado()) return ""
        return JSONObject()
            .put("pc", prefs.getString("pc", ""))
            .put("hosts", JSONArray(prefs.getString("hosts", "[]")))
            .put("host", prefs.getString("ultimo", ""))
            .toString()
    }

    fun desvincular() {
        prefs.edit().clear().apply()
        try {
            KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry(ALIAS)
        } catch (_: Exception) {
        }
    }

    private fun hosts(): List<String> {
        val a = JSONArray(prefs.getString("hosts", "[]"))
        val lista = (0 until a.length()).map { a.getString(it) }
        val ultimo = prefs.getString("ultimo", null)
        return if (ultimo != null && ultimo in lista) listOf(ultimo) + lista.filter { it != ultimo } else lista
    }

    // ---- llaves
    private fun crearLlave(): ByteArray {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (ks.containsAlias(ALIAS)) ks.deleteEntry(ALIAS)
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        gen.initialize(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .build()
        )
        return gen.generateKeyPair().public.encoded   // SubjectPublicKeyInfo (DER): lo único que sale del celular
    }

    private fun firmar(datos: ByteArray): ByteArray {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val llave = ks.getKey(ALIAS, null) as? PrivateKey ?: throw IOException("sin llave")
        return Signature.getInstance("SHA256withECDSA").run {
            initSign(llave)
            update(datos)
            sign()
        }
    }

    private fun sha256Hex(b: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    // ---- TLS: solo vale el certificado cuya huella vino en el QR
    private fun fabrica(huella: String): SSLSocketFactory {
        val esperada = huella.lowercase().toByteArray()
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                throw CertificateException("no se usa")
            }

            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                val cert = chain?.firstOrNull() ?: throw CertificateException("sin certificado")
                if (!MessageDigest.isEqual(sha256Hex(cert.encoded).toByteArray(), esperada)) {
                    throw CertificateException("este no es el PC vinculado")
                }
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        return SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }.socketFactory
    }

    private fun abrir(host: String, puerto: Int, huella: String, ruta: String, leerMs: Int): HttpsURLConnection {
        val c = URL("https", host, puerto, ruta).openConnection() as HttpsURLConnection
        c.sslSocketFactory = fabrica(huella)
        c.hostnameVerifier = HostnameVerifier { _, _ -> true }   // la identidad la da la huella, no el nombre
        c.connectTimeout = CONECTAR_MS
        c.readTimeout = leerMs
        c.useCaches = false
        return c
    }

    private fun leer(c: HttpsURLConnection): Respuesta {
        val estado = c.responseCode
        val flujo = if (estado in 200..299) c.inputStream else c.errorStream
        val cuerpo = flujo?.use { it.readBytes() } ?: ByteArray(0)
        return Respuesta(estado, cuerpo, c.contentType ?: "")
    }

    /** Prueba cada dirección del PC hasta que una conecte (primero la que funcionó la última vez). */
    private fun porCadaHost(lista: List<String>, puerto: Int, huella: String, ruta: String, leerMs: Int,
                            preparar: (HttpsURLConnection) -> ByteArray?): Respuesta {
        for (host in lista) {
            val c = try {
                abrir(host, puerto, huella, ruta, leerMs)
            } catch (_: Exception) {
                continue
            }
            try {
                val cuerpo = preparar(c)
                try {
                    c.connect()
                } catch (_: IOException) {
                    continue   // esta dirección no responde (otra red): se prueba la siguiente
                }
                if (cuerpo != null) c.outputStream.use { it.write(cuerpo) }
                val r = leer(c)
                prefs.edit().putString("ultimo", host).apply()
                return r
            } catch (_: IOException) {
                return Respuesta(0, ByteArray(0), "")   // conectó pero se cortó: no se repite un pedido ya enviado
            } finally {
                c.disconnect()
            }
        }
        return Respuesta(0, ByteArray(0), "")
    }

    // ---- vincular con el QR del PC:  atlas://vincular?d=<base64url de {v,n,h,p,f,c}>
    fun vincular(textoQr: String, nombreCelular: String): String? {
        val d: JSONObject
        try {
            val b64 = textoQr.trim().substringAfter("atlas://vincular?d=", "")
            if (b64.isEmpty()) return "Ese código no es de Atlas."
            d = JSONObject(String(Base64.decode(b64, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP), Charsets.UTF_8))
            if (d.optInt("v") != 1) return "Actualiza Atlas Móvil para usar este código."
        } catch (_: Exception) {
            return "No pude leer ese código."
        }
        val hostsJson = d.optJSONArray("h") ?: JSONArray()
        val lista = (0 until hostsJson.length()).map { hostsJson.getString(it) }
        val puerto = d.optInt("p", 8766)
        val huella = d.optString("f")
        if (lista.isEmpty() || huella.length != 64) return "El código viene incompleto. Pide otro en el PC."
        val publica = try {
            crearLlave()
        } catch (e: Exception) {
            return "Este celular no pudo crear su llave segura."
        }
        val cuerpo = JSONObject()
            .put("c", d.optString("c"))
            .put("nombre", nombreCelular)
            .put("pub", Base64.encodeToString(publica, Base64.NO_WRAP))
            .toString().toByteArray()
        val r = porCadaHost(lista, puerto, huella, "/p/vincular", 15000) { c ->
            c.requestMethod = "POST"
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.setFixedLengthStreamingMode(cuerpo.size)
            cuerpo
        }
        if (r.estado == 0) return "No pude llegar al PC. Revisa que el celular esté en el mismo Wi‑Fi o con Tailscale activo."
        if (r.estado == 403) return "El código venció o ya se usó. Pide otro en el PC."
        if (r.estado != 200) return "El PC no aceptó la vinculación (${r.estado})."
        val o = try {
            JSONObject(r.texto())
        } catch (_: Exception) {
            return "El PC respondió algo que no entendí."
        }
        val ultimo = prefs.getString("ultimo", null)
        prefs.edit()
            .putString("id", o.optString("id"))
            .putString("pc", o.optString("pc", d.optString("n")))
            .putString("hosts", hostsJson.toString())
            .putInt("puerto", puerto)
            .putString("huella", huella)
            .putString("ultimo", ultimo)
            .apply()
        return null
    }

    // ---- pedidos firmados
    fun pedir(metodo: String, ruta: String, cuerpo: ByteArray, tipo: String, leerMs: Int = 20000): Respuesta {
        val id = prefs.getString("id", null) ?: return Respuesta(0, ByteArray(0), "")
        val huella = prefs.getString("huella", "") ?: ""
        val puerto = prefs.getInt("puerto", 8766)
        return porCadaHost(hosts(), puerto, huella, ruta, leerMs) { c ->
            val t = System.currentTimeMillis().toString()
            val n = ByteArray(12).also { azar.nextBytes(it) }
                .let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }
            val firma = firmar("$metodo\n$ruta\n$t\n$n\n${sha256Hex(cuerpo)}".toByteArray())
            c.requestMethod = metodo
            c.setRequestProperty("X-Atlas-Id", id)
            c.setRequestProperty("X-Atlas-T", t)
            c.setRequestProperty("X-Atlas-N", n)
            c.setRequestProperty("X-Atlas-F", Base64.encodeToString(firma, Base64.NO_WRAP))
            if (metodo == "POST") {
                c.doOutput = true
                c.setRequestProperty("Content-Type", tipo)
                c.setFixedLengthStreamingMode(cuerpo.size)
                cuerpo
            } else {
                null
            }
        }
    }
}

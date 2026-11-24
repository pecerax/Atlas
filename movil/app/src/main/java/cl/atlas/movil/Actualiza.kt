package cl.atlas.movil

import android.app.Activity
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.PublicKey
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.zip.ZipInputStream

/**
 * Actualizaciones sin instalar a mano.
 *
 * 1) La interfaz (lo que hay en assets/ui) puede venir más nueva en un paquete «ui.zip» publicado junto al APK.
 *    Solo se acepta si su firma corresponde a la MISMA llave con que está firmada esta app: la llave pública se
 *    saca del certificado de la app instalada, así que nadie sin esa llave puede darle una pantalla a la app,
 *    venga de donde venga la descarga. Tampoco se acepta una interfaz más antigua que la que ya hay.
 * 2) Cuando hay un APK con versión mayor, se baja y se entrega al instalador de Android, que comprueba la firma.
 */
class Actualiza(private val ctx: Context) {
    companion object {
        const val BASE = "https://raw.githubusercontent.com/pecerax/Atlas/apk-atlas-movil/"
        const val ACCION_INSTALAR = "cl.atlas.movil.INSTALAR"
        private const val CADA_MS = 3 * 60 * 1000L
        private val NOMBRE = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
    }

    class Novedad(val interfaz: Boolean, val apk: File?, val versionApk: Int)

    private val raiz = File(ctx.filesDir, "ui")
    private val prefs = ctx.getSharedPreferences("actualiza", Context.MODE_PRIVATE)

    @Volatile var activa: File? = null
        private set
    @Volatile var nInterfaz = 0
        private set
    @Volatile var apkLista: File? = null
        private set

    /** Qué pasó en la última búsqueda, en palabras para la persona. */
    @Volatile var motivo = ""
        private set

    val versionApp: Int by lazy {
        @Suppress("DEPRECATION") ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionCode
    }
    val nombreApp: String by lazy { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "" }

    private val nIncluida: Int by lazy {
        try {
            JSONObject(ctx.assets.open("ui/version.json").use { it.readBytes().toString(Charsets.UTF_8) }).optInt("n", 0)
        } catch (e: Exception) {
            0
        }
    }

    /** Al abrir: usar la interfaz bajada solo si es más nueva que la que trae el APK y sirve para esta versión. */
    fun elegir() {
        val n = prefs.getInt("ui_n", 0)
        val dir = File(raiz, n.toString())
        if (n > nIncluida && prefs.getInt("ui_min", 0) <= versionApp && File(dir, "index.html").isFile) {
            activa = dir
            nInterfaz = n
        } else {
            activa = null
            nInterfaz = nIncluida
            raiz.deleteRecursively()
        }
    }

    /** Un archivo de la interfaz bajada (o null para que se use el que trae el APK). */
    fun abrir(nombre: String): InputStream? {
        val dir = activa ?: return null
        if (!NOMBRE.matches(nombre)) return null
        val f = File(dir, nombre)
        return if (f.isFile) f.inputStream() else null
    }

    private fun bajar(nombre: String, tope: Int): ByteArray? {
        val c = URL(BASE + nombre).openConnection() as HttpURLConnection
        try {
            c.connectTimeout = 10000
            c.readTimeout = 30000
            c.instanceFollowRedirects = false
            c.useCaches = false
            if (c.responseCode != 200) return null
            val salida = java.io.ByteArrayOutputStream()
            val trozo = ByteArray(65536)
            c.inputStream.use { e ->
                while (true) {
                    val k = e.read(trozo)
                    if (k < 0) break
                    salida.write(trozo, 0, k)
                    if (salida.size() > tope) return null
                }
            }
            return salida.toByteArray()
        } finally {
            c.disconnect()
        }
    }

    private fun llaveDeLaApp(): PublicKey? {
        val pm = ctx.packageManager
        val der = if (Build.VERSION.SDK_INT >= 28) {
            val info = pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNING_CERTIFICATES).signingInfo ?: return null
            if (info.hasMultipleSigners()) return null
            info.signingCertificateHistory?.lastOrNull()?.toByteArray()
        } else {
            @Suppress("DEPRECATION", "PackageManagerGetSignatures")
            pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNATURES).signatures?.firstOrNull()?.toByteArray()
        } ?: return null
        return (CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(der)) as X509Certificate).publicKey
    }

    private fun firmaValida(datos: ByteArray, firma: ByteArray): Boolean {
        val llave = llaveDeLaApp() ?: return false
        val alg = when (llave.algorithm) {
            "RSA" -> "SHA256withRSA"
            "EC" -> "SHA256withECDSA"
            else -> return false
        }
        return try {
            Signature.getInstance(alg).run { initVerify(llave); update(datos); verify(firma) }
        } catch (e: Exception) {
            false
        }
    }

    private fun instalarInterfaz(zip: ByteArray): Boolean {
        val tmp = File(raiz, "nueva.tmp")
        tmp.deleteRecursively()
        if (!tmp.mkdirs()) return false
        try {
            var total = 0L
            var archivos = 0
            ZipInputStream(ByteArrayInputStream(zip)).use { z ->
                while (true) {
                    val e = z.nextEntry ?: break
                    if (e.isDirectory || !NOMBRE.matches(e.name) || ++archivos > 60) return false   // sin carpetas ni rutas raras
                    File(tmp, e.name).outputStream().use { o ->
                        val trozo = ByteArray(65536)
                        while (true) {
                            val k = z.read(trozo)
                            if (k < 0) break
                            total += k
                            if (total > 24L * 1024 * 1024) return false
                            o.write(trozo, 0, k)
                        }
                    }
                }
            }
            val v = JSONObject(File(tmp, "version.json").readText())
            val n = v.optInt("n", 0)
            val min = v.optInt("min_app", 0)
            // el número que vale es el que viene DENTRO del paquete firmado: no se vuelve a una interfaz anterior
            if (n <= nInterfaz || min > versionApp || !File(tmp, "index.html").isFile) return false
            val destino = File(raiz, n.toString())
            destino.deleteRecursively()
            if (!tmp.renameTo(destino)) return false
            prefs.edit().putInt("ui_n", n).putInt("ui_min", min).apply()
            val anterior = activa
            activa = destino
            nInterfaz = n
            if (anterior != null && anterior != destino) anterior.deleteRecursively()
            return true
        } catch (e: Exception) {
            return false
        } finally {
            tmp.deleteRecursively()
        }
    }

    /** Mira si hay algo nuevo (a lo más cada 3 minutos, salvo que la persona lo pida). Corre fuera del hilo principal. */
    @Synchronized
    fun revisar(forzar: Boolean = false): Novedad {
        val nada = Novedad(false, apkLista, prefs.getInt("apk_v", 0))
        val ahora = System.currentTimeMillis()
        val ultima = prefs.getLong("revisado", 0L)
        if (!forzar && ahora >= ultima && ahora - ultima < CADA_MS) return nada
        try {
            motivo = "NO PUDE LLEGAR A INTERNET"
            val aviso = JSONObject((bajar("actual.json", 4096) ?: return nada).toString(Charsets.UTF_8))
            motivo = "ESTÁ AL DÍA"
            prefs.edit().putLong("revisado", ahora).apply()
            var interfaz = false
            if (aviso.optInt("ui", 0) > nInterfaz && aviso.optInt("ui_min_app", 0) <= versionApp) {
                val zip = bajar("ui.zip", 16 * 1024 * 1024)
                val firma = bajar("ui.zip.sig", 2048)
                if (zip == null || firma == null) motivo = "NO PUDE BAJAR LA PANTALLA NUEVA"
                else if (!firmaValida(zip, firma)) motivo = "LA PANTALLA NUEVA NO TRAE LA FIRMA DE ESTA APP"
                else {
                    interfaz = instalarInterfaz(zip)
                    motivo = if (interfaz) "PANTALLA NUEVA LISTA" else "LA PANTALLA NUEVA NO SE PUDO GUARDAR"
                }
            }
            val v = aviso.optInt("app", 0)
            val carpeta = File(ctx.cacheDir, "apk")
            if (v > versionApp) {
                val f = File(carpeta, "Atlas-$v.apk")
                if (!f.isFile) {
                    carpeta.deleteRecursively()
                    carpeta.mkdirs()
                    val apk = bajar("Atlas-Movil.apk", 80 * 1024 * 1024)
                    if (apk == null) {
                        motivo = "NO PUDE BAJAR LA APP NUEVA"
                        return Novedad(interfaz, null, 0)
                    }
                    f.writeBytes(apk)
                }
                @Suppress("DEPRECATION")
                val info = ctx.packageManager.getPackageArchiveInfo(f.path, 0)
                @Suppress("DEPRECATION")
                if (info == null || info.packageName != ctx.packageName || info.versionCode <= versionApp) {
                    f.delete()
                    motivo = "LA APP BAJADA NO SIRVE"
                    return Novedad(interfaz, null, 0)
                }
                apkLista = f
                motivo = "HAY APP NUEVA: TOCA ACTUALIZAR"
                @Suppress("DEPRECATION")
                prefs.edit().putInt("apk_v", info.versionCode).apply()
                @Suppress("DEPRECATION")
                return Novedad(interfaz, f, info.versionCode)
            }
            carpeta.deleteRecursively()
            apkLista = null
            return Novedad(interfaz, null, 0)
        } catch (e: Exception) {
            motivo = "FALLÓ LA BÚSQUEDA (" + e.javaClass.simpleName + ")"
            return nada
        }
    }

    /** Entrega el APK bajado al instalador de Android. El resultado vuelve a MainActivity.onNewIntent. */
    fun instalar(act: Activity): Boolean {
        val apk = apkLista ?: return false
        return try {
            val pi = ctx.packageManager.packageInstaller
            val p = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            p.setAppPackageName(ctx.packageName)
            // desde Android 12, si la app ya se actualizó a sí misma una vez, las siguientes no preguntan
            if (Build.VERSION.SDK_INT >= 31) p.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            val id = pi.createSession(p)
            pi.openSession(id).use { s ->
                s.openWrite("atlas", 0, apk.length()).use { o ->
                    apk.inputStream().use { it.copyTo(o) }
                    s.fsync(o)
                }
                val vuelta = Intent(act, MainActivity::class.java).setAction(ACCION_INSTALAR).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                val marcas = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                s.commit(PendingIntent.getActivity(act, id, vuelta, marcas).intentSender)
            }
            true
        } catch (e: Exception) {
            false
        }
    }
}

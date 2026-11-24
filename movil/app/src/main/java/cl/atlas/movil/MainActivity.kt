package cl.atlas.movil

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * Una sola pantalla: la interfaz (assets/ui) corre en un WebView sin acceso a internet, y pide todo lo demás
 * (red, llaves, micrófono, parlante) a través de «Nativo».
 */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var puente: Puente
    private lateinit var grabadora: Grabadora
    private lateinit var parlante: Parlante
    private lateinit var actualiza: Actualiza
    private val red = Executors.newFixedThreadPool(3)
    private val turnoVoz = AtomicInteger(0)
    private val INICIO = "file:///android_asset/ui/index.html"

    // Candado: si la app estuvo más de 5 minutos fuera de pantalla, pide huella o el PIN del celular antes de mostrar
    // nada ni hablar con el PC. Solo aplica con un PC vinculado y si el celular tiene bloqueo de pantalla configurado.
    private val CANDADO_MS = 5 * 60 * 1000L
    private val LLAVES = BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    private lateinit var candado: TextView
    @Volatile private var bloqueada = false
    private var pidiendo = false
    private val memoria by lazy { getSharedPreferences("candado", MODE_PRIVATE) }

    private val escaner = registerForActivityResult(ScanContract()) { r ->
        val texto = r.contents ?: return@registerForActivityResult
        red.execute {
            val error = try {
                puente.vincular(texto, "${Build.MANUFACTURER} ${Build.MODEL}".trim())
            } catch (e: Exception) {
                "No pude vincular: ${e.javaClass.simpleName}"
            }
            if (error == null) evento("vinculado", JSONObject()) else evento("vincerror", JSONObject().put("error", error))
        }
    }

    private val permisoMicrofono = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) empezarAGrabar() else evento("sinpermiso", JSONObject())
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        puente = Puente(applicationContext)
        grabadora = Grabadora(applicationContext)
        parlante = Parlante(applicationContext)
        actualiza = Actualiza(applicationContext)
        actualiza.elegir()

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#01040A"))
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = false
        web.settings.allowContentAccess = false
        web.settings.mediaPlaybackRequiresUserGesture = true
        web.settings.blockNetworkLoads = true   // la página no sale a la red: solo la parte nativa habla con el PC
        web.overScrollMode = WebView.OVER_SCROLL_NEVER
        web.settings.cacheMode = WebSettings.LOAD_NO_CACHE
        web.webViewClient = object : WebViewClient() {
            // Nativo solo existe para la página que viene dentro de la app: nunca se navega a otra parte
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
                request?.url?.toString() != INICIO

            // Si hay una interfaz más nueva ya bajada y verificada, sus archivos reemplazan a los que trae el APK.
            // La dirección sigue siendo la misma: la página nunca sale de android_asset/ui.
            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                val u = request?.url ?: return null
                val ruta = u.path ?: return null
                if (u.scheme != "file" || !ruta.startsWith("/android_asset/ui/")) return null
                val nombre = ruta.removePrefix("/android_asset/ui/")
                val datos = actualiza.abrir(nombre) ?: return null
                val tipo = when (nombre.substringAfterLast('.', "")) {
                    "html" -> "text/html"
                    "js" -> "text/javascript"
                    "css" -> "text/css"
                    "json" -> "application/json"
                    "jpg", "jpeg" -> "image/jpeg"
                    "png" -> "image/png"
                    "svg" -> "image/svg+xml"
                    "woff2" -> "font/woff2"
                    else -> "application/octet-stream"
                }
                val texto = tipo.startsWith("text/") || tipo == "application/json" || tipo == "image/svg+xml"
                return WebResourceResponse(tipo, if (texto) "utf-8" else null, datos)
            }
        }
        web.addJavascriptInterface(Nativo(), "Nativo")
        candado = TextView(this).apply {
            text = "ATLAS\n\nToca para desbloquear"
            setTextColor(Color.parseColor("#8FB6C8"))
            textSize = 15f
            letterSpacing = 0.2f
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#01040A"))
            visibility = View.GONE
            isClickable = true
            setOnClickListener { pedirLlave() }
        }
        setContentView(FrameLayout(this).apply {
            addView(web, FrameLayout.LayoutParams(-1, -1))
            addView(candado, FrameLayout.LayoutParams(-1, -1))
        })
        web.loadUrl(INICIO)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("window.Atlas ? Atlas._atras() : false") { r ->
                    if (r != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })
    }

    override fun onStart() {
        super.onStart()
        val salida = memoria.getLong("salida", 0L)
        val ahora = SystemClock.elapsedRealtime()
        // ahora < salida: el celular se reinició desde la última vez, así que también se pide
        if (!bloqueada && salida != 0L && (ahora < salida || ahora - salida > CANDADO_MS) && puente.vinculado() &&
            BiometricManager.from(this).canAuthenticate(LLAVES) == BiometricManager.BIOMETRIC_SUCCESS
        ) bloquear()
        if (bloqueada) pedirLlave()
        red.execute {
            val n = actualiza.revisar()
            if (n.interfaz) evento("uinueva", JSONObject())
            if (n.apk != null) evento("appnueva", JSONObject())
        }
    }

    // El instalador de Android avisa aquí: si necesita que la persona confirme, se abre su pantalla.
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action != Actualiza.ACCION_INSTALAR) return
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val pedir = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                // solo se abre la pantalla del propio instalador del sistema
                if (pedir != null && !bloqueada) try { startActivity(pedir) } catch (e: Exception) { evento("apperror", JSONObject()) }
            }
            PackageInstaller.STATUS_SUCCESS -> {}
            else -> evento("apperror", JSONObject().put("error", intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: ""))
        }
    }

    override fun onStop() {
        // si ya estaba bloqueada no se renueva la hora: salir y volver a entrar no la desbloquea
        if (!bloqueada) memoria.edit().putLong("salida", SystemClock.elapsedRealtime()).apply()
        super.onStop()
    }

    private fun bloquear() {
        bloqueada = true
        turnoVoz.incrementAndGet()
        parlante.callar()
        grabadora.cancelar()
        candado.visibility = View.VISIBLE
        web.visibility = View.INVISIBLE
    }

    private fun pedirLlave() {
        if (pidiendo || !bloqueada) return
        pidiendo = true
        val aviso = BiometricPrompt.PromptInfo.Builder().setTitle("Atlas").setSubtitle("Confirma que eres tú")
            .setAllowedAuthenticators(LLAVES).build()
        BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                pidiendo = false
                bloqueada = false
                memoria.edit().putLong("salida", SystemClock.elapsedRealtime()).apply()
                candado.visibility = View.GONE
                web.visibility = View.VISIBLE
                evento("visible", JSONObject())
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                pidiendo = false   // canceló o falló: queda bloqueada y puede tocar la pantalla para reintentar
            }
        }).authenticate(aviso)
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
        if (!bloqueada) evento("visible", JSONObject())
    }

    override fun onPause() {
        grabadora.cancelar()
        web.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        parlante.callar()
        grabadora.cancelar()
        red.shutdownNow()
        web.destroy()
        super.onDestroy()
    }

    private fun js(codigo: String) {
        runOnUiThread {
            if (!isDestroyed) web.evaluateJavascript(codigo, null)
        }
    }

    private fun evento(nombre: String, datos: JSONObject) {
        js("window.Atlas && Atlas._evento(${JSONObject.quote(nombre)}, ${JSONObject.quote(datos.toString())})")
    }

    private fun empezarAGrabar() {
        if (bloqueada || grabadora.grabando()) return
        evento("grabando", JSONObject())
        grabadora.empezar { wav ->
            if (wav == null) {
                evento("nada", JSONObject())   // cancelada o sin audio: la pantalla vuelve a esperar
                return@empezar
            }
            evento("oyendo", JSONObject())
            red.execute {
                val o = try {
                    val r = puente.pedir("POST", "/p/oir", wav, "audio/wav", 60000)
                    when {
                        r.estado == 200 -> JSONObject(r.texto())
                        r.estado == 0 -> JSONObject().put("error", "No pude llegar al PC.").put("sinpc", true)
                        else -> JSONObject().put("error", "Atlas no pudo escuchar eso.")
                    }
                } catch (e: Exception) {
                    JSONObject().put("error", "No pude enviar el audio.")
                }
                evento("oido", o)
            }
        }
    }

    /** Lo que la página puede pedir. Cada método vuelve al tiro; los resultados llegan como eventos o respuestas. */
    inner class Nativo {
        @JavascriptInterface
        fun vinculo(): String = puente.vinculoJson()

        @JavascriptInterface
        fun version(): String = JSONObject().put("app", actualiza.nombreApp).put("ui", actualiza.nInterfaz)
            .put("appNueva", actualiza.apkLista != null).toString()

        @JavascriptInterface
        fun avisos(): String = JSONObject().put("activo", Avisos.activo(this@MainActivity))
            .put("permiso", Avisos.conPermiso(this@MainActivity)).toString()

        /** Activa o apaga el envío de notificaciones al PC. Si falta el permiso de Android, abre esa pantalla de ajustes. */
        @JavascriptInterface
        fun avisosPoner(si: Boolean) {
            if (bloqueada) return
            Avisos.poner(this@MainActivity, si)
            if (si && !Avisos.conPermiso(this@MainActivity)) runOnUiThread {
                try { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) } catch (e: Exception) { evento("apperror", JSONObject()) }
            }
        }

        @JavascriptInterface
        fun avisosApps(json: String) = Avisos.appsDelPc(this@MainActivity, json)

        @JavascriptInterface
        fun actualizar() {
            if (bloqueada) return
            runOnUiThread { if (!actualiza.instalar(this@MainActivity)) evento("apperror", JSONObject()) }
        }

        @JavascriptInterface
        fun escanear() {
            if (bloqueada) return
            runOnUiThread {
                escaner.launch(
                    ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setBeepEnabled(false)
                        .setOrientationLocked(true).setPrompt("Apunta al código de «Vincular celular» en el PC")
                )
            }
        }

        @JavascriptInterface
        fun desvincular() {
            parlante.callar()
            grabadora.cancelar()
            puente.desvincular()
        }

        @JavascriptInterface
        fun pedir(id: Int, metodo: String, ruta: String, cuerpo: String) {
            if (bloqueada || metodo != "GET" && metodo != "POST" || !ruta.startsWith("/p/")) return
            red.execute {
                val r = try {
                    puente.pedir(metodo, ruta, cuerpo.toByteArray(), "application/json", if (ruta == "/p/chat" || ruta == "/p/confirmar") 180000 else 15000)
                } catch (e: Exception) {
                    Respuesta(0, ByteArray(0), "")
                }
                js("window.Atlas && Atlas._cb($id, ${r.estado}, ${JSONObject.quote(r.texto())})")
            }
        }

        @JavascriptInterface
        fun grabar() {
            runOnUiThread {
                if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    empezarAGrabar()
                } else {
                    permisoMicrofono.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
        }

        @JavascriptInterface
        fun pararGrabacion() = grabadora.parar()

        @JavascriptInterface
        fun cancelarGrabacion() = grabadora.cancelar()

        @JavascriptInterface
        fun decir(texto: String) {
            if (bloqueada) return
            val turno = turnoVoz.incrementAndGet()
            red.execute {
                val r = try {
                    puente.pedir("POST", "/p/voz", JSONObject().put("text", texto).toString().toByteArray(), "application/json", 60000)
                } catch (e: Exception) {
                    Respuesta(0, ByteArray(0), "")
                }
                if (turno != turnoVoz.get() || bloqueada) return@execute   // lo callaron mientras el PC preparaba la voz
                if (r.estado == 200 && r.cuerpo.size > 44) {
                    parlante.tocar(r.cuerpo) { if (turno == turnoVoz.get()) evento("callado", JSONObject()) }
                } else {
                    evento("callado", JSONObject())
                }
            }
        }

        @JavascriptInterface
        fun callar() {
            turnoVoz.incrementAndGet()
            parlante.callar()
        }
    }
}

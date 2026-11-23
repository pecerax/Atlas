package cl.atlas.movil

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
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
    private val red = Executors.newFixedThreadPool(3)
    private val turnoVoz = AtomicInteger(0)
    private val INICIO = "file:///android_asset/ui/index.html"

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

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#01040A"))
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = false
        web.settings.allowContentAccess = false
        web.settings.mediaPlaybackRequiresUserGesture = true
        web.settings.blockNetworkLoads = true   // la página no sale a la red: solo la parte nativa habla con el PC
        web.overScrollMode = WebView.OVER_SCROLL_NEVER
        web.webViewClient = object : WebViewClient() {
            // Nativo solo existe para la página que viene dentro de la app: nunca se navega a otra parte
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
                request?.url?.toString() != INICIO
        }
        web.addJavascriptInterface(Nativo(), "Nativo")
        setContentView(web)
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

    override fun onResume() {
        super.onResume()
        web.onResume()
        evento("visible", JSONObject())
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
        if (grabadora.grabando()) return
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
        fun escanear() {
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
            if (metodo != "GET" && metodo != "POST" || !ruta.startsWith("/p/")) return
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
            val turno = turnoVoz.incrementAndGet()
            red.execute {
                val r = try {
                    puente.pedir("POST", "/p/voz", JSONObject().put("text", texto).toString().toByteArray(), "application/json", 60000)
                } catch (e: Exception) {
                    Respuesta(0, ByteArray(0), "")
                }
                if (turno != turnoVoz.get()) return@execute   // lo callaron mientras el PC preparaba la voz
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

package cl.atlas.movil

import android.app.Notification
import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Le cuenta al PC lo que llega al celular: mensajes de unas pocas apps elegidas y las llamadas.
 * Viene apagado. Solo corre si la persona lo activa en ENLACE y además le da a Atlas el acceso a notificaciones
 * en los ajustes de Android. Lo que se manda va por el mismo canal firmado y cifrado del Puente, solo a su PC:
 * app, remitente, un resumen corto y la hora. Nada se guarda en el celular.
 */
class Avisos : NotificationListenerService() {
    companion object {
        private const val PREFS = "avisos"
        val DE_FABRICA = setOf("com.whatsapp", "com.whatsapp.w4b", "org.telegram.messenger")

        fun activo(ctx: Context): Boolean = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("activo", false)

        fun poner(ctx: Context, si: Boolean) {
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("activo", si).apply()
        }

        fun conPermiso(ctx: Context): Boolean = NotificationManagerCompat.getEnabledListenerPackages(ctx).contains(ctx.packageName)

        /** Apps extra que pide el PC (por ejemplo la del banco). Solo nombres de paquete válidos, a lo más 30. */
        fun appsDelPc(ctx: Context, json: String) {
            val nombres = try {
                val a = JSONArray(json)
                (0 until minOf(a.length(), 30)).map { a.optString(it) }.filter { Regex("^[A-Za-z0-9_.]{3,120}$").matches(it) }.toSet()
            } catch (e: Exception) {
                return
            }
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putStringSet("apps", nombres).apply()
        }
    }

    private val cola = Executors.newSingleThreadExecutor()
    private val puente by lazy { Puente(applicationContext) }
    private val recientes = LinkedHashMap<String, Long>()   // para no mandar dos veces lo mismo

    private fun interesa(sbn: StatusBarNotification, llamada: Boolean): Boolean {
        if (sbn.packageName == packageName) return false
        if (llamada) return true
        val extra = getSharedPreferences(PREFS, Context.MODE_PRIVATE).getStringSet("apps", emptySet()) ?: emptySet()
        return sbn.packageName in DE_FABRICA || sbn.packageName in extra
    }

    private fun mandar(sbn: StatusBarNotification, fin: Boolean) {
        if (!activo(this) || !puente.vinculado()) return
        val n = sbn.notification ?: return
        val llamada = n.category == Notification.CATEGORY_CALL
        if (fin && !llamada) return
        if (!interesa(sbn, llamada)) return
        // el resumen de un grupo («3 mensajes de 2 chats») repite lo que ya se mandó uno por uno
        if (!llamada && n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val de = n.extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty().take(80)
        val texto = n.extras?.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty().take(240)
        if (!llamada && de.isEmpty() && texto.isEmpty()) return
        val clave = sbn.key + "|" + (if (fin) "fin" else "") + "|" + texto.hashCode()
        val ahora = System.currentTimeMillis()
        synchronized(recientes) {
            val antes = recientes[clave]
            if (antes != null && ahora - antes < (if (llamada) 60_000 else 600_000)) return
            recientes[clave] = ahora
            while (recientes.size > 200) recientes.remove(recientes.keys.first())
        }
        val ev = JSONObject().put("tipo", if (llamada) "llamada" else "notificacion").put("app", sbn.packageName)
            .put("de", de).put("texto", texto).put("t", if (fin) ahora else sbn.postTime)
        if (llamada) ev.put("estado", if (fin) "fin" else "entrante")
        cola.execute {
            try {
                puente.pedir("POST", "/p/evento", ev.toString().toByteArray(), "application/json", 10000)
            } catch (e: Exception) {
                // sin PC a mano el aviso se pierde: no se guarda nada en el celular
            }
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn != null) mandar(sbn, false)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        if (sbn != null) mandar(sbn, true)
    }

    override fun onDestroy() {
        cola.shutdownNow()
        super.onDestroy()
    }
}

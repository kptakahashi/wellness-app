package app.wellnessapp.collector

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ApiClient(private val prefs: Prefs) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS) // free hosts cold-start in ~60s
        .build()

    /** POST /api/ingest. Returns server response JSON or throws. */
    fun ingest(events: JSONArray): JSONObject {
        val body = JSONObject().apply {
            put("device_id", prefs.deviceId)
            put("events", events)
        }
        val req = Request.Builder()
            .url(prefs.serverUrl + "/api/ingest")
            .header("X-Api-Token", prefs.token)
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()
        http.newCall(req).execute().use { res ->
            val text = res.body?.string() ?: ""
            if (!res.isSuccessful) throw IllegalStateException("HTTP ${res.code}: ${text.take(200)}")
            return JSONObject(text)
        }
    }

    fun status(): JSONObject {
        val req = Request.Builder().url(prefs.serverUrl + "/api/status").header("X-Api-Token", prefs.token).get().build()
        http.newCall(req).execute().use { res ->
            val text = res.body?.string() ?: ""
            if (!res.isSuccessful) throw IllegalStateException("HTTP ${res.code}: ${text.take(200)}")
            return JSONObject(text)
        }
    }
}

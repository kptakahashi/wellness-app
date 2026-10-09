package app.wellnessapp.collector

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant

/**
 * Append-only JSON-lines queue on internal storage.
 * Collectors append; SyncWorker drains in batches and deletes what was accepted by the server.
 */
object EventQueue {
    private const val FILE = "events.jsonl"
    private const val MAX_BYTES = 8L * 1024 * 1024
    private val lock = Any()

    fun event(source: String, kind: String, start: Instant, end: Instant? = null, payload: JSONObject = JSONObject(), dedupeKey: String? = null): JSONObject =
        JSONObject().apply {
            put("source", source)
            put("kind", kind)
            put("start", start.toString())
            if (end != null) put("end", end.toString())
            put("payload", payload)
            if (dedupeKey != null) put("dedupe_key", dedupeKey)
        }

    fun append(context: Context, events: List<JSONObject>) {
        if (events.isEmpty()) return
        synchronized(lock) {
            val f = File(context.filesDir, FILE)
            if (f.exists() && f.length() > MAX_BYTES) f.delete() // never let the queue grow unbounded
            f.appendText(events.joinToString(separator = "\n", postfix = "\n") { it.toString() })
        }
    }

    fun append(context: Context, event: JSONObject) = append(context, listOf(event))

    fun size(context: Context): Int = synchronized(lock) {
        val f = File(context.filesDir, FILE)
        if (!f.exists()) 0 else f.readLines().count { it.isNotBlank() }
    }

    /** Take up to [limit] events. Call [commit] with the number actually sent. */
    fun peek(context: Context, limit: Int = 500): JSONArray = synchronized(lock) {
        val arr = JSONArray()
        val f = File(context.filesDir, FILE)
        if (!f.exists()) return arr
        f.useLines { lines ->
            lines.filter { it.isNotBlank() }.take(limit).forEach { line ->
                runCatching { arr.put(JSONObject(line)) }
            }
        }
        arr
    }

    fun commit(context: Context, sent: Int) {
        synchronized(lock) {
            val f = File(context.filesDir, FILE)
            if (!f.exists()) return
            val remaining = f.readLines().filter { it.isNotBlank() }.drop(sent)
            if (remaining.isEmpty()) f.delete() else f.writeText(remaining.joinToString("\n", postfix = "\n"))
        }
    }
}

package app.wellnessapp.collector.collectors

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Process
import app.wellnessapp.collector.EventQueue
import org.json.JSONObject
import java.time.Instant

/**
 * Foreground app sessions from the OS usage statistics (Settings > Digital Wellbeing uses the same API).
 * This is the Android-only channel that iPhone cannot offer: "YouTube for 70 minutes at 23:00".
 */
class UsageCollector(private val context: Context) {

    companion object {
        fun hasPermission(context: Context): Boolean {
            val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
            val mode = appOps.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
            return mode == AppOpsManager.MODE_ALLOWED
        }

        private val IGNORE = setOf("com.android.systemui", "android", "com.google.android.apps.nexuslauncher", "com.sec.android.app.launcher")
        private const val MIN_SESSION_SEC = 60
    }

    private val labelCache = HashMap<String, String>()

    private fun label(pkg: String): String = labelCache.getOrPut(pkg) {
        runCatching {
            val pm = context.packageManager
            pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        }.getOrDefault(pkg)
    }

    fun collect(startMillis: Long, endMillis: Long): Int {
        if (!hasPermission(context)) return 0
        val usm = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val events = usm.queryEvents(startMillis, endMillis)
        val open = HashMap<String, Long>()
        val out = mutableListOf<JSONObject>()
        val e = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            val pkg = e.packageName ?: continue
            if (pkg in IGNORE || pkg == context.packageName) continue
            when (e.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> open[pkg] = e.timeStamp
                UsageEvents.Event.ACTIVITY_PAUSED, UsageEvents.Event.ACTIVITY_STOPPED -> {
                    val s = open.remove(pkg) ?: continue
                    if ((e.timeStamp - s) / 1000 >= MIN_SESSION_SEC) {
                        out += EventQueue.event(
                            "usage", "app_usage", Instant.ofEpochMilli(s), Instant.ofEpochMilli(e.timeStamp),
                            JSONObject().put("package", pkg).put("app_label", label(pkg)),
                        )
                    }
                }
            }
        }
        EventQueue.append(context, out)
        return out.size
    }
}

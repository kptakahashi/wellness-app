package app.wellnessapp.collector

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.wellnessapp.collector.collectors.HealthCollector
import app.wellnessapp.collector.collectors.LocationCollector
import app.wellnessapp.collector.collectors.UsageCollector
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.time.ZoneId
import java.util.concurrent.TimeUnit

/**
 * Runs every 30 minutes (free hosts sleep after 15 idle minutes; 30 min keeps the server
 * awake only ~half the time, which keeps a Render free instance well under its 750 h/month):
 *   1. location sample -> queue
 *   2. every ~50 min: Health Connect + usage stats for the last 36 h -> queue (server dedupes)
 *   3. drain queue -> POST /api/ingest
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "WellnessSync"
        private const val PERIODIC = "wellness-sync"
        private const val ONESHOT = "wellness-sync-now"
        private const val HEALTH_INTERVAL_MS = 50L * 60 * 1000
        private const val LOOKBACK_MS = 36L * 60 * 60 * 1000

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        fun runNow(context: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>().build()
            WorkManager.getInstance(context).enqueueUniqueWork(ONESHOT, ExistingWorkPolicy.REPLACE, req)
        }

        suspend fun runOnce(context: Context, force: Boolean = false): String {
            val prefs = Prefs(context)
            val sb = StringBuilder()
            val now = System.currentTimeMillis()

            if (prefs.locationEnabled) {
                runCatching { if (LocationCollector(context).sample()) sb.append("位置 1件 / ") }
                    .onFailure { Log.w(TAG, "location failed", it) }
            }

            if (force || now - prefs.lastHealthSync > HEALTH_INTERVAL_MS) {
                val start = Instant.ofEpochMilli(now - LOOKBACK_MS)
                val end = Instant.ofEpochMilli(now)
                if (HealthCollector.sdkAvailable(context)) {
                    runCatching { HealthCollector(context).collect(start, end) }
                        .onSuccess { sb.append("健康 ${it}件 / ") }
                        .onFailure { Log.w(TAG, "health failed", it); sb.append("健康 失敗(${it.message?.take(40)}) / ") }
                }
                runCatching { UsageCollector(context).collect(now - LOOKBACK_MS, now) }
                    .onSuccess { sb.append("利用統計 ${it}件 / ") }
                    .onFailure { Log.w(TAG, "usage failed", it) }
                prefs.lastHealthSync = now
            }

            if (!prefs.isConfigured) {
                sb.append("サーバー未設定")
                return sb.toString()
            }
            val api = ApiClient(prefs)
            var sentTotal = 0
            var inserted = 0
            var rounds = 0
            while (rounds < 20) {
                val batch = EventQueue.peek(context, 500)
                if (batch.length() == 0) break
                val res = api.ingest(batch)
                inserted += res.optInt("inserted", 0)
                EventQueue.commit(context, batch.length())
                sentTotal += batch.length()
                rounds++
            }
            sb.append("送信 ${sentTotal}件 (新規 ${inserted})")
            val stamp = DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(ZoneId.systemDefault()).format(Instant.now())
            prefs.lastSyncResult = "$stamp  $sb"
            return sb.toString()
        }
    }

    override suspend fun doWork(): Result {
        return try {
            runOnce(applicationContext)
            Result.success()
        } catch (e: Exception) {
            Log.w(TAG, "sync failed", e)
            Prefs(applicationContext).lastSyncResult = "失敗: ${e.message?.take(80)}"
            Result.retry()
        }
    }
}

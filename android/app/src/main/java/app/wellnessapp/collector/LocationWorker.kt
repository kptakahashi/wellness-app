package app.wellnessapp.collector

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.wellnessapp.collector.collectors.LocationCollector
import java.util.concurrent.TimeUnit

/**
 * Samples the location every 15 minutes (WorkManager's minimum) into the local queue, without
 * touching the network, so short stays (a 20-minute lunch) are seen even though the server sync
 * runs only every 30 minutes. SyncWorker uploads whatever is queued.
 */
class LocationWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "WellnessLocation"
        private const val PERIODIC = "wellness-location"

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<LocationWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        }
    }

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (!prefs.locationEnabled) return Result.success()
        runCatching { LocationCollector(applicationContext).sample() }
            .onFailure { Log.w(TAG, "location sample failed", it) }
        return Result.success()
    }
}

package app.wellnessapp.collector.collectors

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.CancellationSignal
import androidx.core.content.ContextCompat
import app.wellnessapp.collector.EventQueue
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.time.Instant
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.coroutines.resume

/**
 * Low-frequency location sampling (every 15 min from LocationWorker, plus every sync). The server
 * clusters consecutive samples into "stayed at X for N minutes" and names the shop or facility from
 * a cached OpenStreetMap tile. Reverse geocoding happens on-device via the OS Geocoder, so no
 * coordinates are sent to any third-party API.
 *
 * A fresh fix is requested (fused provider on Android 12+, network/GPS before) with a short timeout;
 * if none arrives, the last known location is used when it is recent enough.
 */
class LocationCollector(private val context: Context) {

    companion object {
        private const val FIX_TIMEOUT_MS = 20_000L
        private const val STALE_MS = 30L * 60 * 1000

        fun hasPermission(context: Context): Boolean =
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        private var lastAddress: Pair<Location, String>? = null
    }

    @Suppress("MissingPermission")
    private suspend fun currentFix(lm: LocationManager, provider: String): Location? {
        if (Build.VERSION.SDK_INT < 30 || !lm.isProviderEnabled(provider)) return null
        return withTimeoutOrNull(FIX_TIMEOUT_MS) {
            suspendCancellableCoroutine { cont ->
                val signal = CancellationSignal()
                cont.invokeOnCancellation { signal.cancel() }
                runCatching {
                    lm.getCurrentLocation(provider, signal, Executors.newSingleThreadExecutor()) { loc ->
                        if (cont.isActive) cont.resume(loc)
                    }
                }.onFailure { if (cont.isActive) cont.resume(null) }
            }
        }
    }

    @Suppress("MissingPermission", "DEPRECATION")
    suspend fun sample(): Boolean {
        if (!hasPermission(context)) return false
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val providers = buildList {
            if (Build.VERSION.SDK_INT >= 31) add(LocationManager.FUSED_PROVIDER)
            add(LocationManager.NETWORK_PROVIDER)
            add(LocationManager.GPS_PROVIDER)
        }
        var loc: Location? = null
        for (p in providers) {
            loc = currentFix(lm, p)
            if (loc != null) break
        }
        if (loc == null) {
            loc = providers.mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }.maxByOrNull { it.time } ?: return false
            // Stale fix (older than 30 min) tells us nothing new.
            if (System.currentTimeMillis() - loc.time > STALE_MS) return false
        }

        val address = lastAddress?.takeIf { it.first.distanceTo(loc) < 100f }?.second ?: runCatching {
            if (Geocoder.isPresent()) {
                Geocoder(context, Locale.JAPAN).getFromLocation(loc.latitude, loc.longitude, 1)
                    ?.firstOrNull()?.let { a -> listOfNotNull(a.featureName, a.thoroughfare, a.locality).distinct().joinToString(" ") }
            } else null
        }.getOrNull() ?: ""
        lastAddress = loc to address

        val payload = JSONObject().apply {
            put("lat", Math.round(loc.latitude * 100000.0) / 100000.0)
            put("lon", Math.round(loc.longitude * 100000.0) / 100000.0)
            put("accuracy_m", loc.accuracy.toInt())
            put("address", address)
        }
        EventQueue.append(context, EventQueue.event("location", "location_sample", Instant.ofEpochMilli(loc.time), null, payload))
        return true
    }
}

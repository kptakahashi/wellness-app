package app.kizashi.collector.collectors

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.Build
import androidx.core.content.ContextCompat
import app.kizashi.collector.EventQueue
import org.json.JSONObject
import java.time.Instant
import java.util.Locale

/**
 * Low-frequency location sampling (every sync, ~15 min). The server clusters consecutive samples
 * into "stayed at X for N minutes". Reverse geocoding happens on-device via the OS Geocoder, so no
 * coordinates are sent to any third-party API.
 */
class LocationCollector(private val context: Context) {

    companion object {
        fun hasPermission(context: Context): Boolean =
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
    }

    private var lastAddress: Pair<Location, String>? = null

    @Suppress("MissingPermission", "DEPRECATION")
    fun sample(): Boolean {
        if (!hasPermission(context)) return false
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val providers = buildList {
            if (Build.VERSION.SDK_INT >= 31) add(LocationManager.FUSED_PROVIDER)
            add(LocationManager.NETWORK_PROVIDER)
            add(LocationManager.GPS_PROVIDER)
        }
        val loc = providers.mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
            .maxByOrNull { it.time } ?: return false
        // Stale fix (older than 30 min) tells us nothing new.
        if (System.currentTimeMillis() - loc.time > 30 * 60 * 1000) return false

        val address = lastAddress?.takeIf { it.first.distanceTo(loc) < 100f }?.second ?: runCatching {
            if (Geocoder.isPresent()) {
                Geocoder(context, Locale.JAPAN).getFromLocation(loc.latitude, loc.longitude, 1)
                    ?.firstOrNull()?.let { a -> listOfNotNull(a.featureName, a.thoroughfare, a.locality).distinct().joinToString(" ") }
            } else null
        }.getOrNull() ?: ""
        lastAddress = loc to address

        val payload = JSONObject().apply {
            put("lat", Math.round(loc.latitude * 10000.0) / 10000.0)
            put("lon", Math.round(loc.longitude * 10000.0) / 10000.0)
            put("accuracy_m", loc.accuracy.toInt())
            put("address", address)
        }
        EventQueue.append(context, EventQueue.event("location", "location_sample", Instant.ofEpochMilli(loc.time), null, payload))
        return true
    }
}

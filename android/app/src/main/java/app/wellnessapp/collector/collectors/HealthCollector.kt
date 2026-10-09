package app.wellnessapp.collector.collectors

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import app.wellnessapp.collector.EventQueue
import org.json.JSONObject
import java.time.Instant
import kotlin.reflect.KClass

/**
 * Reads the OS health hub. Any ring/watch that writes to Health Connect (RingConn, Oura, Garmin,
 * Pixel Watch, Galaxy Watch...) ends up here, so this one collector is device-agnostic.
 */
class HealthCollector(private val context: Context) {

    companion object {
        val PERMISSIONS: Set<String> = setOf(
            HealthPermission.getReadPermission(SleepSessionRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
            HealthPermission.getReadPermission(RestingHeartRateRecord::class),
            HealthPermission.getReadPermission(StepsRecord::class),
            HealthPermission.getReadPermission(ExerciseSessionRecord::class),
            HealthPermission.getReadPermission(OxygenSaturationRecord::class),
            HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND,
        )

        fun sdkAvailable(context: Context): Boolean =
            HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

        private val EXERCISE_NAMES = mapOf(
            ExerciseSessionRecord.EXERCISE_TYPE_RUNNING to "ランニング",
            ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL to "ランニング(トレッドミル)",
            ExerciseSessionRecord.EXERCISE_TYPE_WALKING to "ウォーキング",
            ExerciseSessionRecord.EXERCISE_TYPE_BIKING to "自転車",
            ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING to "筋力トレーニング",
            ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING to "ウェイトトレーニング",
            ExerciseSessionRecord.EXERCISE_TYPE_YOGA to "ヨガ",
            ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_POOL to "水泳",
            ExerciseSessionRecord.EXERCISE_TYPE_HIKING to "ハイキング",
            ExerciseSessionRecord.EXERCISE_TYPE_ELLIPTICAL to "エリプティカル",
            ExerciseSessionRecord.EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING to "HIIT",
        )
    }

    private val client by lazy { HealthConnectClient.getOrCreate(context) }

    suspend fun grantedPermissions(): Set<String> = client.permissionController.getGrantedPermissions()

    private suspend fun <T : Record> readAll(type: KClass<T>, start: Instant, end: Instant): List<T> {
        val out = mutableListOf<T>()
        var token: String? = null
        do {
            val res = client.readRecords(ReadRecordsRequest(type, TimeRangeFilter.between(start, end), pageToken = token, pageSize = 1000))
            out += res.records
            token = res.pageToken
        } while (token != null)
        return out
    }

    /** Collect everything in [start, end) into the queue. Returns number of events queued. */
    suspend fun collect(start: Instant, end: Instant): Int {
        val events = mutableListOf<JSONObject>()
        val granted = grantedPermissions()
        fun has(p: String) = p in granted

        if (has(HealthPermission.getReadPermission(SleepSessionRecord::class))) {
            for (s in readAll(SleepSessionRecord::class, start, end)) {
                var deep = 0L; var rem = 0L; var light = 0L; var awake = 0L
                for (st in s.stages) {
                    val mins = (st.endTime.epochSecond - st.startTime.epochSecond) / 60
                    when (st.stage) {
                        SleepSessionRecord.STAGE_TYPE_DEEP -> deep += mins
                        SleepSessionRecord.STAGE_TYPE_REM -> rem += mins
                        SleepSessionRecord.STAGE_TYPE_LIGHT, SleepSessionRecord.STAGE_TYPE_SLEEPING -> light += mins
                        SleepSessionRecord.STAGE_TYPE_AWAKE, SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED, SleepSessionRecord.STAGE_TYPE_OUT_OF_BED -> awake += mins
                    }
                }
                val payload = JSONObject().apply {
                    put("deep_min", deep); put("rem_min", rem); put("light_min", light); put("awake_min", awake)
                    put("origin", s.metadata.dataOrigin.packageName)
                }
                events += EventQueue.event("health_connect", "sleep_session", s.startTime, s.endTime, payload, dedupeKey = s.metadata.id)
            }
        }
        if (has(HealthPermission.getReadPermission(HeartRateRecord::class))) {
            for (r in readAll(HeartRateRecord::class, start, end)) {
                // Keep at most one sample per 5 minutes to stay light; the server buckets by 30 min anyway.
                var lastKept = 0L
                for (smp in r.samples) {
                    val t = smp.time.epochSecond
                    if (t - lastKept < 300) continue
                    lastKept = t
                    events += EventQueue.event("health_connect", "heart_rate", smp.time, null, JSONObject().put("bpm", smp.beatsPerMinute))
                }
            }
        }
        if (has(HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class))) {
            for (r in readAll(HeartRateVariabilityRmssdRecord::class, start, end)) {
                events += EventQueue.event("health_connect", "hrv", r.time, null, JSONObject().put("rmssd_ms", r.heartRateVariabilityMillis))
            }
        }
        if (has(HealthPermission.getReadPermission(RestingHeartRateRecord::class))) {
            for (r in readAll(RestingHeartRateRecord::class, start, end)) {
                events += EventQueue.event("health_connect", "resting_hr", r.time, null, JSONObject().put("bpm", r.beatsPerMinute))
            }
        }
        if (has(HealthPermission.getReadPermission(StepsRecord::class))) {
            for (r in readAll(StepsRecord::class, start, end)) {
                events += EventQueue.event("health_connect", "steps", r.startTime, r.endTime, JSONObject().put("count", r.count))
            }
        }
        if (has(HealthPermission.getReadPermission(ExerciseSessionRecord::class))) {
            for (r in readAll(ExerciseSessionRecord::class, start, end)) {
                val payload = JSONObject().apply {
                    put("type", EXERCISE_NAMES[r.exerciseType] ?: (r.title ?: "運動"))
                    put("type_code", r.exerciseType)
                    put("origin", r.metadata.dataOrigin.packageName)
                }
                events += EventQueue.event("health_connect", "exercise", r.startTime, r.endTime, payload, dedupeKey = r.metadata.id)
            }
        }
        if (has(HealthPermission.getReadPermission(OxygenSaturationRecord::class))) {
            for (r in readAll(OxygenSaturationRecord::class, start, end)) {
                events += EventQueue.event("health_connect", "spo2", r.time, null, JSONObject().put("percent", r.percentage.value))
            }
        }
        EventQueue.append(context, events)
        return events.size
    }
}

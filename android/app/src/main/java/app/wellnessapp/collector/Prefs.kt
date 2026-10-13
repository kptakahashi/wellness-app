package app.wellnessapp.collector

import android.content.Context
import android.content.SharedPreferences

/** Tiny settings store. Everything the collector needs to know lives here. */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("wellnessapp", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", "") ?: ""
        set(v) = sp.edit().putString("server_url", v.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    var deviceId: String
        get() {
            val existing = sp.getString("device_id", null)
            if (existing != null) return existing
            val id = "android-" + java.util.UUID.randomUUID().toString().take(8)
            sp.edit().putString("device_id", id).apply()
            return id
        }
        set(v) = sp.edit().putString("device_id", v).apply()

    /** Epoch millis of the last successful health/usage read. */
    var lastHealthSync: Long
        get() = sp.getLong("last_health_sync", 0L)
        set(v) = sp.edit().putLong("last_health_sync", v).apply()

    var lastSyncResult: String
        get() = sp.getString("last_sync_result", "") ?: ""
        set(v) = sp.edit().putString("last_sync_result", v).apply()

    /** Comma separated package names whose notifications are always captured. */
    var notificationPackages: String
        get() = (sp.getString("notification_packages", DEFAULT_PACKAGES) ?: DEFAULT_PACKAGES).ifBlank { DEFAULT_PACKAGES }
        set(v) = sp.edit().putString("notification_packages", v.ifBlank { DEFAULT_PACKAGES }).apply()

    var reminderHour: Int
        get() = sp.getInt("reminder_hour", 22)
        set(v) = sp.edit().putInt("reminder_hour", v).apply()

    var locationEnabled: Boolean
        get() = sp.getBoolean("location_enabled", true)
        set(v) = sp.edit().putBoolean("location_enabled", v).apply()

    val isConfigured: Boolean get() = serverUrl.startsWith("http") && token.isNotBlank()

    companion object {
        /** Payment apps (always captured) plus delivery / store apps whose notifications carry what was bought. */
        const val DEFAULT_PACKAGES =
            "jp.ne.paypay.android.app,com.moneyforward.android.app,jp.co.rakuten_card.rakutencard," +
                "com.smbc_card.vpass,jp.co.jcb.myjcb,jp.mobilesuica,jp.co.aeoncredit.aeonwallet," +
                "com.kddi.android.aupay,jp.mufg.bk.applisp.app,com.nttdocomo.keitai.payment,jp.co.rakuten.pay,com.google.android.apps.walletnfcrel," +
                "com.ubercab.eats,com.demaecan.androidapp,com.amazon.mShop.android.shopping,com.starbucks.jp," +
                "jp.co.sej.app,jp.co.family.familymart_app,jp.co.lawson.android"
        val PAYMENT_KEYWORDS = listOf("円", "¥", "￥", "ご利用", "お支払い", "支払い", "決済", "利用金額", "ご注文", "レシート", "お買い上げ", "paid", "payment")
    }
}

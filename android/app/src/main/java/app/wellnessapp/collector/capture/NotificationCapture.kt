package app.wellnessapp.collector.capture

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import app.wellnessapp.collector.EventQueue
import app.wellnessapp.collector.Prefs
import org.json.JSONObject
import java.time.Instant

/**
 * Captures payment-style notifications (PayPay, card apps, Money Forward "新着の入出金", Suica...).
 * Nothing is read from the notification beyond title/text, and only notifications that either come
 * from an allow-listed package or contain payment keywords are kept.
 */
class NotificationCapture : NotificationListenerService() {

    companion object {
        fun isEnabled(context: Context): Boolean {
            val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
            val me = ComponentName(context, NotificationCapture::class.java)
            return flat.split(":").any { ComponentName.unflattenFromString(it) == me }
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName == packageName) return
        if (sbn.isOngoing) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString() ?: ""
        if (title.isBlank() && text.isBlank() && big.isBlank()) return

        val prefs = Prefs(this)
        val allow = prefs.notificationPackages.split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        val blob = "$title $text $big"
        val looksLikePayment = Prefs.PAYMENT_KEYWORDS.any { blob.contains(it, ignoreCase = true) }
        if (sbn.packageName !in allow && !looksLikePayment) return

        val label = runCatching {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        }.getOrDefault(sbn.packageName)

        val payload = JSONObject().apply {
            put("package", sbn.packageName)
            put("app_label", label)
            put("title", title.take(200))
            put("text", text.take(500))
            if (big.isNotBlank() && big != text) put("big_text", big.take(800))
        }
        val key = "${sbn.packageName}:${sbn.postTime}:${title.hashCode()}"
        EventQueue.append(this, EventQueue.event("notification", "notification", Instant.ofEpochMilli(sbn.postTime), null, payload, dedupeKey = key))
    }
}

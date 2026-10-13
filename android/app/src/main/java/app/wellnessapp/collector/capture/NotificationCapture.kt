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
 * Captures payment-style notifications (PayPay, card apps, Money Forward "新着の入出金", Suica...) and
 * order/receipt notifications (Uber Eats, 出前館, Amazon, Gmail previews of order e-mails).
 *
 * What leaves the device: package name, app label, and the notification's visible text fields
 * (title, text, big text, inbox lines, sub text). Nothing else is read.
 *
 * What is kept:
 *   - everything from an allow-listed package (payment apps), unless it is obviously a promotion
 *   - from any other package, only text that looks like a payment or an order/receipt,
 *     and never from messaging apps (a friend writing "500円" must not end up on the server)
 */
class NotificationCapture : NotificationListenerService() {

    companion object {
        fun isEnabled(context: Context): Boolean {
            val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
            val me = ComponentName(context, NotificationCapture::class.java)
            return flat.split(":").any { ComponentName.unflattenFromString(it) == me }
        }

        /** Private conversations are never scanned for keywords. */
        val MESSENGER_PACKAGES = setOf(
            "jp.naver.line.android", "com.google.android.apps.messaging", "com.samsung.android.messaging",
            "com.android.mms", "com.Slack", "com.discord", "com.microsoft.teams", "com.whatsapp",
            "com.facebook.orca", "org.telegram.messenger", "com.instagram.android", "com.twitter.android",
            "com.zhiliaoapp.musically", "jp.co.yahoo.android.ymail", "com.kakao.talk", "org.thoughtcrime.securesms",
            "com.skype.raider", "us.zoom.videomeetings",
        )

        /** Coupons and campaigns from store apps are noise unless they also report a purchase. */
        val PROMO_KEYWORDS = listOf("クーポン", "キャンペーン", "セール", "プレゼント", "抽選", "ポイント進呈", "ポイントが貯まる", "お知らせ", "配信", "限定", "新発売", "おすすめ")
        val STRONG_PURCHASE_KEYWORDS = listOf("お支払い", "支払い", "決済", "ご利用", "利用金額", "ご注文", "注文", "レシート", "お買い上げ", "ご購入", "購入", "領収", "明細", "paid", "payment", "order", "receipt")
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
        val sub = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString() ?: ""
        val lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.joinToString("\n") { it.toString() } ?: ""
        if (title.isBlank() && text.isBlank() && big.isBlank() && lines.isBlank()) return

        val prefs = Prefs(this)
        val allow = prefs.notificationPackages.split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        val blob = "$title $text $big $lines $sub"
        val strong = STRONG_PURCHASE_KEYWORDS.any { blob.contains(it, ignoreCase = true) }
        val looksLikePayment = strong || Prefs.PAYMENT_KEYWORDS.any { blob.contains(it, ignoreCase = true) }
        val promo = PROMO_KEYWORDS.any { blob.contains(it) }
        val keep = when {
            sbn.packageName in allow -> !(promo && !strong)
            sbn.packageName in MESSENGER_PACKAGES -> false
            else -> looksLikePayment && !(promo && !strong)
        }
        if (!keep) return

        val label = runCatching {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        }.getOrDefault(sbn.packageName)

        val payload = JSONObject().apply {
            put("package", sbn.packageName)
            put("app_label", label)
            put("title", title.take(200))
            put("text", text.take(500))
            if (big.isNotBlank() && big != text) put("big_text", big.take(1200))
            if (lines.isNotBlank() && lines != text && lines != big) put("lines", lines.take(1200))
            if (sub.isNotBlank()) put("sub_text", sub.take(120))
        }
        val key = "${sbn.packageName}:${sbn.postTime}:${title.hashCode()}"
        EventQueue.append(this, EventQueue.event("notification", "notification", Instant.ofEpochMilli(sbn.postTime), null, payload, dedupeKey = key))
    }
}

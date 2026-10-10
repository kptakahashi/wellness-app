package app.wellnessapp.collector

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import java.util.Calendar

/** Evening nudge: one notification that opens the web review page. */
class ReviewReminder : BroadcastReceiver() {

    companion object {
        private const val CHANNEL = "wellness-review"
        private const val REQ = 4101

        fun schedule(context: Context) {
            val prefs = Prefs(context)
            val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val pi = PendingIntent.getBroadcast(
                context, REQ, Intent(context, ReviewReminder::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val cal = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, prefs.reminderHour); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0)
                if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
            }
            am.setInexactRepeating(AlarmManager.RTC_WAKEUP, cal.timeInMillis, AlarmManager.INTERVAL_DAY, pi)
        }

        fun show(context: Context) {
            val prefs = Prefs(context)
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "夜の確認", NotificationManager.IMPORTANCE_DEFAULT))
            val url = if (prefs.serverUrl.isNotBlank()) "${prefs.serverUrl}/?token=${Uri.encode(prefs.token)}" else "about:blank"
            val open = PendingIntent.getActivity(
                context, 0, Intent(Intent.ACTION_VIEW, Uri.parse(url)),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val n = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_agenda)
                .setContentTitle("今日の確認、2分で終わります")
                .setContentText("推定した1日を選択肢で確認するだけ")
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            nm.notify(REQ, n)
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        // Make sure today's data is on the server before the user opens the page.
        SyncWorker.runNow(context)
        show(context)
    }
}

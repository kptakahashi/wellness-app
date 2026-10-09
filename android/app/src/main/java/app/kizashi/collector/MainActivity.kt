package app.kizashi.collector

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import app.kizashi.collector.capture.NotificationCapture
import app.kizashi.collector.collectors.HealthCollector
import app.kizashi.collector.collectors.LocationCollector
import app.kizashi.collector.collectors.UsageCollector
import app.kizashi.collector.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private lateinit var prefs: Prefs

    private val healthPermissionLauncher =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { refreshStatus() }

    private val runtimePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refreshStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        prefs = Prefs(this)

        b.serverUrl.setText(prefs.serverUrl)
        b.token.setText(prefs.token)
        b.packages.setText(prefs.notificationPackages)
        b.reminderHour.setText(prefs.reminderHour.toString())

        b.saveBtn.setOnClickListener {
            prefs.serverUrl = b.serverUrl.text.toString()
            prefs.token = b.token.text.toString()
            prefs.notificationPackages = b.packages.text.toString()
            prefs.reminderHour = b.reminderHour.text.toString().toIntOrNull()?.coerceIn(0, 23) ?: 22
            SyncWorker.schedule(this)
            ReviewReminder.schedule(this)
            toast("保存しました。15分ごとに自動同期します")
            refreshStatus()
        }
        b.healthBtn.setOnClickListener {
            if (!HealthCollector.sdkAvailable(this)) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata")))
                return@setOnClickListener
            }
            healthPermissionLauncher.launch(HealthCollector.PERMISSIONS)
        }
        b.usageBtn.setOnClickListener { startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)) }
        b.notifBtn.setOnClickListener { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        b.locationBtn.setOnClickListener {
            val perms = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
            if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
            runtimePermissionLauncher.launch(perms.toTypedArray())
        }
        b.backgroundLocationBtn.setOnClickListener {
            if (Build.VERSION.SDK_INT >= 29) runtimePermissionLauncher.launch(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
        }
        b.syncBtn.setOnClickListener {
            b.syncBtn.isEnabled = false
            b.log.text = "同期中…"
            lifecycleScope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { SyncWorker.runOnce(this@MainActivity, force = true) } }
                b.log.text = result.getOrElse { "失敗: ${it.message}" }
                b.syncBtn.isEnabled = true
                refreshStatus()
            }
        }
        b.testBtn.setOnClickListener {
            lifecycleScope.launch {
                val r = withContext(Dispatchers.IO) { runCatching { ApiClient(prefs).status().toString(2) } }
                b.log.text = r.getOrElse { "接続失敗: ${it.message}" }
            }
        }
        b.openBtn.setOnClickListener {
            if (prefs.serverUrl.isBlank()) { toast("サーバーURLを先に保存してください"); return@setOnClickListener }
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("${prefs.serverUrl}/?token=${Uri.encode(prefs.token)}")))
        }
        b.reminderTestBtn.setOnClickListener { ReviewReminder.show(this) }

        if (prefs.isConfigured) {
            SyncWorker.schedule(this)
            ReviewReminder.schedule(this)
        }
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
    }

    private fun refreshStatus() {
        val ok = "✅"; val ng = "⬜"
        lifecycleScope.launch {
            val healthGranted = withContext(Dispatchers.IO) {
                runCatching {
                    if (HealthCollector.sdkAvailable(this@MainActivity)) HealthCollector(this@MainActivity).grantedPermissions().size else -1
                }.getOrDefault(-1)
            }
            val healthLine = when {
                healthGranted < 0 -> "$ng Health Connect が使えません(未インストール?)"
                healthGranted == 0 -> "$ng Health Connect: 未許可"
                else -> "$ok Health Connect: ${healthGranted}/${HealthCollector.PERMISSIONS.size} 項目を許可"
            }
            val usage = if (UsageCollector.hasPermission(this@MainActivity)) "$ok 使用状況へのアクセス" else "$ng 使用状況へのアクセス: 未許可"
            val notif = if (NotificationCapture.isEnabled(this@MainActivity)) "$ok 通知の読み取り(決済通知)" else "$ng 通知の読み取り: 未許可"
            val loc = if (LocationCollector.hasPermission(this@MainActivity)) "$ok 位置情報" else "$ng 位置情報: 未許可"
            val bg = if (Build.VERSION.SDK_INT >= 29 &&
                ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED
            ) "$ok バックグラウンド位置情報" else "$ng バックグラウンド位置情報: 「常に許可」が必要"
            val queue = "キュー: ${EventQueue.size(this@MainActivity)} 件 / 最終同期: ${prefs.lastSyncResult.ifBlank { "なし" }}"
            b.status.text = listOf(healthLine, usage, notif, loc, bg, queue).joinToString("\n")
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}

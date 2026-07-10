package com.solariz.nexgenprintbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*

/**
 * PrintForegroundService
 * ======================
 * Tek bir baskı işini yönetir:
 *  1. CPS'den payload al
 *  2. Claim et
 *  3. Bluetooth ile bas
 *  4. Success veya Fail bildir
 *  5. İşlem bitince servisi kendisi durdurur
 *
 * Kurallar:
 * - Foreground Service — Android 8+ arka plan kısıtlamalarını aşar.
 * - Bildirim sadece baskı sırasında görünür; işlem bitince bildirim kaldırılır.
 * - Aynı job_id ikinci kez gönderilirse reddedilir (PRINTED/FAILED kontrolü API'de).
 * - Bağlantı ve OutputStream her durumda kapatılır (BluetoothPrintService içinde).
 */
class PrintForegroundService : Service() {

    companion object {
        private const val NOTIF_ID       = 1001
        private const val CHANNEL_ID     = "nexgen_print"
        private const val CHANNEL_NAME   = "NexGen Baskı"

        const val EXTRA_JOB_ID   = "job_id"
        const val EXTRA_TOKEN    = "print_token"
        const val EXTRA_SERVER   = "server_url"
        const val EXTRA_PRINTER  = "printer_mac"

        fun buildStartIntent(
            context: Context,
            jobId: Int,
            token: String,
            serverUrl: String,
            printerMac: String,
        ): Intent = Intent(context, PrintForegroundService::class.java).apply {
            putExtra(EXTRA_JOB_ID, jobId)
            putExtra(EXTRA_TOKEN, token)
            putExtra(EXTRA_SERVER, serverUrl)
            putExtra(EXTRA_PRINTER, printerMac)
        }
    }

    // ── Binder: PrintJobActivity ile iletişim ─────────────────────────────────

    inner class LocalBinder : Binder() {
        fun getService(): PrintForegroundService = this@PrintForegroundService
    }

    private val binder = LocalBinder()
    override fun onBind(intent: Intent?): IBinder = binder

    // ── Durum callbacki — PrintJobActivity dinler ────────────────────────────

    var onProgress: ((String) -> Unit)? = null
    var onFinished: ((PrintResult) -> Unit)? = null

    // ── Coroutine scope ───────────────────────────────────────────────────────

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val notifManager by lazy {
        getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val jobId      = intent?.getIntExtra(EXTRA_JOB_ID, -1) ?: -1
        val token      = intent?.getStringExtra(EXTRA_TOKEN)    ?: ""
        val serverUrl  = intent?.getStringExtra(EXTRA_SERVER)   ?: ""
        val printerMac = intent?.getStringExtra(EXTRA_PRINTER)  ?: ""

        if (jobId < 0 || token.isEmpty() || serverUrl.isEmpty() || printerMac.isEmpty()) {
            stopSelf()
            return START_NOT_STICKY
        }

        startForeground(NOTIF_ID, buildNotification("Baskı hazırlanıyor..."))

        serviceScope.launch {
            executePrintJob(jobId, token, serverUrl, printerMac)
        }

        return START_NOT_STICKY
    }

    override fun onDestroy() {
        serviceScope.cancel()
        // Bildirimi kaldır
        notifManager.cancel(NOTIF_ID)
        super.onDestroy()
    }

    // ── Ana iş akışı ──────────────────────────────────────────────────────────

    private suspend fun executePrintJob(
        jobId: Int,
        token: String,
        serverUrl: String,
        printerMac: String,
    ) {
        val api = CpsApiService(serverUrl)
        val bt  = BluetoothPrintService(this)

        fun progress(msg: String) {
            updateNotification(msg)
            onProgress?.invoke(msg)
        }

        fun finish(result: PrintResult) {
            val notifMsg = when (result) {
                is PrintResult.Success         -> getString(R.string.notif_success)
                is PrintResult.Failure         -> getString(R.string.notif_failed)
            }
            // Bildirimi güncelle sonra kaldır (1s sonra)
            updateNotification(notifMsg)
            serviceScope.launch {
                delay(1_000)
                notifManager.cancel(NOTIF_ID)
                withContext(Dispatchers.Main) { onFinished?.invoke(result) }
                stopSelf()
            }
        }

        // 1. Payload al
        progress("Sunucudan etiket alınıyor...")
        val jobResult = api.getJob(jobId, token)
        if (jobResult.isFailure) {
            val ex = jobResult.exceptionOrNull()
            val result = when (ex) {
                is CpsApiException.TokenInvalid    -> PrintResult.Failure.InvalidToken()
                is CpsApiException.AlreadyPrinted  -> PrintResult.Failure.AlreadyPrinted()
                else -> PrintResult.Failure.ServerError(
                    ex?.message?.take(120) ?: "Sunucu bağlantısı kesildi"
                )
            }
            api.failJob(jobId, token, result.message).getOrNull()
            finish(result)
            return
        }

        val job = jobResult.getOrThrow()

        // Çift baskı son kontrol
        if (job.status in listOf("PRINTED", "FAILED")) {
            finish(PrintResult.Failure.AlreadyPrinted())
            return
        }

        // 2. Claim
        progress("Baskı başlatılıyor...")
        api.claimJob(jobId, token).getOrNull() // hata olsa da devam et (idempotent)

        // 3. Payload decode
        val bytes: ByteArray = try {
            decodePayload(job.payloadBase64)
        } catch (e: Exception) {
            val msg = "Payload decode hatası: ${e.message?.take(80)}"
            api.failJob(jobId, token, msg).getOrNull()
            finish(PrintResult.Failure.Unknown(msg))
            return
        }

        // 4. Bluetooth bas
        progress("Yazıcıya bağlanıyor...")
        val btResult = withContext(Dispatchers.IO) {
            bt.printBytes(printerMac, bytes)
        }

        // 5. Sonucu servera bildir
        when (btResult) {
            is PrintResult.Success -> {
                api.successJob(jobId, token).getOrNull()
                progress("Etiket basıldı")
                finish(PrintResult.Success)
            }
            is PrintResult.Failure -> {
                api.failJob(jobId, token, btResult.message).getOrNull()
                finish(btResult)
            }
        }
    }

    // ── Bildirim yönetimi ─────────────────────────────────────────────────────

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_LOW  // ses çıkmaz
            ).apply {
                description = "NexGen etiket baskı işlemi"
                setShowBadge(false)
            }
            notifManager.createNotificationChannel(ch)
        }
    }

    private fun buildNotification(contentText: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("NexGen Print Bridge")
            .setContentText(contentText)
            .setSmallIcon(android.R.drawable.ic_menu_printer)
            .setOngoing(true)
            .setSilent(true)
            .build()

    private fun updateNotification(text: String) {
        notifManager.notify(NOTIF_ID, buildNotification(text))
    }
}

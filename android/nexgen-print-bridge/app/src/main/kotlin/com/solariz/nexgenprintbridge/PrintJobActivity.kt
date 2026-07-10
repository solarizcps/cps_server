package com.solariz.nexgenprintbridge

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.net.Uri
import android.os.Bundle
import android.os.IBinder
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import com.solariz.nexgenprintbridge.databinding.ActivityPrintJobBinding

/**
 * PrintJobActivity
 * ================
 * URL scheme handler: nexgenprint://print?job_id=42&token=abc
 *
 * - Uygulama açık veya kapalı olsun, Android intent ile bu activity açılır.
 * - launchMode=singleTask: tekrar gelen intent onNewIntent() ile işlenir.
 * - PrintForegroundService'e bağlanır ve durumu dinler.
 * - 2-3s içinde biterse kullanıcı sadece sonucu görür.
 * - Uzun sürerse progress mesajı güncellenir.
 * - Sonuçta: ✓ Etiket basıldı [CPS'ye Dön]  veya  ✗ Hata [Tekrar Dene]
 */
class PrintJobActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPrintJobBinding
    private lateinit var prefs: PrefsManager

    private var currentJobId: Int = -1
    private var currentToken: String = ""
    private var bound = false
    private var printService: PrintForegroundService? = null

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val localBinder = binder as? PrintForegroundService.LocalBinder ?: return
            printService = localBinder.getService()
            bound = true

            printService?.onProgress = { msg ->
                runOnUiThread { showProgress(msg) }
            }
            printService?.onFinished = { result ->
                runOnUiThread { showResult(result) }
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            printService = null
            bound = false
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityPrintJobBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = PrefsManager.getInstance(this)

        binding.btnBackCps.setOnClickListener { backToCps() }
        binding.btnRetry.setOnClickListener {
            if (currentJobId > 0 && currentToken.isNotEmpty()) {
                startPrintJob(currentJobId, currentToken)
            } else {
                finish()
            }
        }

        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onDestroy() {
        if (bound) {
            unbindService(serviceConnection)
            bound = false
        }
        super.onDestroy()
    }

    // ── Intent parse ─────────────────────────────────────────────────────────

    private fun handleIntent(intent: Intent?) {
        val data: Uri? = intent?.data
        if (data == null || data.scheme != "nexgenprint") {
            showError("Geçersiz baskı bağlantısı")
            return
        }

        val jobId = data.getQueryParameter("job_id")?.toIntOrNull() ?: -1
        val token = data.getQueryParameter("token") ?: ""

        if (jobId < 0 || token.isEmpty()) {
            showError("Eksik parametre (job_id veya token)")
            return
        }

        currentJobId  = jobId
        currentToken  = token
        startPrintJob(jobId, token)
    }

    // ── Baskı başlat ─────────────────────────────────────────────────────────

    private fun startPrintJob(jobId: Int, token: String) {
        val printerMac = prefs.printerMac
        if (printerMac.isNullOrBlank()) {
            showError(getString(R.string.err_no_printer))
            return
        }

        showProgress("Baskı hazırlanıyor...")
        binding.btnRetry.visibility    = View.GONE
        binding.btnBackCps.visibility  = View.GONE

        val serviceIntent = PrintForegroundService.buildStartIntent(
            context    = this,
            jobId      = jobId,
            token      = token,
            serverUrl  = prefs.serverUrl,
            printerMac = printerMac,
        )

        // Foreground service başlat
        startForegroundService(serviceIntent)

        // Bind et (callback için)
        bindService(serviceIntent, serviceConnection, Context.BIND_AUTO_CREATE)
    }

    // ── UI güncellemeleri ─────────────────────────────────────────────────────

    private fun showProgress(msg: String) {
        binding.pbProgress.visibility    = View.VISIBLE
        binding.tvResultIcon.visibility  = View.GONE
        binding.tvStatusMsg.text         = msg
        binding.tvSubMsg.visibility      = View.GONE
        binding.btnBackCps.visibility    = View.GONE
        binding.btnRetry.visibility      = View.GONE
    }

    private fun showResult(result: PrintResult) {
        binding.pbProgress.visibility = View.GONE

        when (result) {
            is PrintResult.Success -> {
                binding.tvResultIcon.text       = "✓"
                binding.tvResultIcon.setTextColor(0xFF16A34A.toInt())
                binding.tvResultIcon.visibility = View.VISIBLE
                binding.tvStatusMsg.text        = getString(R.string.success_label)
                binding.tvSubMsg.visibility     = View.GONE
                binding.btnBackCps.visibility   = View.VISIBLE
                binding.btnRetry.visibility     = View.GONE
            }
            is PrintResult.Failure -> {
                binding.tvResultIcon.text       = "✗"
                binding.tvResultIcon.setTextColor(0xFFDC2626.toInt())
                binding.tvResultIcon.visibility = View.VISIBLE
                binding.tvStatusMsg.text        = result.message
                binding.tvSubMsg.visibility     = View.GONE
                binding.btnBackCps.visibility   = View.VISIBLE
                binding.btnRetry.visibility     = when (result) {
                    is PrintResult.Failure.AlreadyPrinted,
                    is PrintResult.Failure.InvalidToken   -> View.GONE
                    else                                   -> View.VISIBLE
                }
            }
        }
    }

    private fun showError(msg: String) {
        binding.pbProgress.visibility   = View.GONE
        binding.tvResultIcon.text       = "✗"
        binding.tvResultIcon.setTextColor(0xFFDC2626.toInt())
        binding.tvResultIcon.visibility = View.VISIBLE
        binding.tvStatusMsg.text        = msg
        binding.btnBackCps.visibility   = View.VISIBLE
        binding.btnRetry.visibility     = View.GONE
    }

    // ── CPS'ye dön ───────────────────────────────────────────────────────────

    private fun backToCps() {
        val serverUrl = prefs.serverUrl
        val cpsUri = Uri.parse("$serverUrl/nexgen/tablet/arge")
        try {
            val browserIntent = Intent(Intent.ACTION_VIEW, cpsUri)
            startActivity(browserIntent)
        } catch (e: Exception) {
            // Browser yoksa sadece kapat
        }
        finish()
    }
}

package com.solariz.nexgenprintbridge

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.solariz.nexgenprintbridge.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * MainActivity
 * ============
 * Ana ekran — Vedat için basit ve net:
 *  - Seçili yazıcı görüntüle
 *  - Eşleşmiş BT cihazları listele (tap → seç ve kaydet)
 *  - Bağlantıyı Test Et
 *  - Test Etiketi Bas (gerçek TSPL, XP365B uyumlu)
 *  - Server URL kaydet
 *  - Son baskı durumu
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: PrefsManager
    private lateinit var btService: BluetoothPrintService
    private var pairedDevices: List<BluetoothDevice> = emptyList()

    companion object {
        private const val REQ_BT_PERMISSIONS = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs     = PrefsManager.getInstance(this)
        btService = BluetoothPrintService(this)

        setupViews()
        requestBtPermissionsIfNeeded()
    }

    override fun onResume() {
        super.onResume()
        refreshDeviceList()
        updateSelectedPrinterLabel()
    }

    // ── UI kurulum ────────────────────────────────────────────────────────────

    private fun setupViews() {
        // Server URL
        binding.etServerUrl.setText(prefs.serverUrl)
        binding.btnSaveUrl.setOnClickListener {
            val url = binding.etServerUrl.text.toString().trim()
            if (url.startsWith("http")) {
                prefs.serverUrl = url
                Toast.makeText(this, "Sunucu adresi kaydedildi", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Geçerli bir URL girin (http://...)", Toast.LENGTH_SHORT).show()
            }
        }

        // Bağlantı testi
        binding.btnTestConnection.setOnClickListener {
            val mac = prefs.printerMac
            if (mac.isNullOrBlank()) {
                showStatus("Önce listeden bir yazıcı seçin", error = true)
                return@setOnClickListener
            }
            testConnection(mac)
        }

        // Test etiketi
        binding.btnTestLabel.setOnClickListener {
            val mac = prefs.printerMac
            if (mac.isNullOrBlank()) {
                showStatus("Önce listeden bir yazıcı seçin", error = true)
                return@setOnClickListener
            }
            printTestLabel(mac)
        }

        // Cihaz listesi seçimi
        binding.lvDevices.setOnItemClickListener { _, _, pos, _ ->
            val device = pairedDevices.getOrNull(pos) ?: return@setOnItemClickListener
            selectPrinter(device)
        }
    }

    // ── Cihaz listesi ─────────────────────────────────────────────────────────

    @SuppressLint("MissingPermission")
    private fun refreshDeviceList() {
        pairedDevices = btService.getPairedDevices()

        if (pairedDevices.isEmpty()) {
            binding.lvDevices.visibility    = View.GONE
            binding.tvNoDevices.visibility  = View.VISIBLE
        } else {
            binding.tvNoDevices.visibility = View.GONE
            binding.lvDevices.visibility   = View.VISIBLE

            val names = pairedDevices.map { d ->
                val name = try { d.name } catch (_: Exception) { "?" }
                val selected = d.address.equals(prefs.printerMac, ignoreCase = true)
                if (selected) "★ $name  [${d.address}]" else "$name  [${d.address}]"
            }
            binding.lvDevices.adapter = ArrayAdapter(
                this,
                android.R.layout.simple_list_item_1,
                names
            )
        }
        updateSelectedPrinterLabel()
    }

    @SuppressLint("MissingPermission")
    private fun selectPrinter(device: BluetoothDevice) {
        val name = try { device.name } catch (_: Exception) { device.address }
        prefs.printerMac  = device.address
        prefs.printerName = name
        updateSelectedPrinterLabel()
        refreshDeviceList()
        Toast.makeText(this, "Yazıcı seçildi: $name", Toast.LENGTH_SHORT).show()
    }

    private fun updateSelectedPrinterLabel() {
        val name = prefs.printerName ?: prefs.printerMac ?: "Yazıcı seçilmedi"
        binding.tvSelectedPrinter.text = name
    }

    // ── Bağlantı testi ────────────────────────────────────────────────────────

    private fun testConnection(mac: String) {
        binding.btnTestConnection.isEnabled = false
        showStatus("Bağlantı test ediliyor...", error = false)

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { btService.testConnection(mac) }
            binding.btnTestConnection.isEnabled = true
            when (result) {
                is PrintResult.Success  -> showStatus("Bağlantı başarılı ✓", error = false)
                is PrintResult.Failure  -> showStatus(result.message, error = true)
            }
        }
    }

    // ── Test etiketi baskısı (gerçek TSPL, XP365B uyumlu 40×80 mm) ──────────

    private fun printTestLabel(mac: String) {
        binding.btnTestLabel.isEnabled = false
        showStatus("Test etiketi basılıyor...", error = false)

        lifecycleScope.launch {
            val tsplBytes = buildTestTspl()
            val result = withContext(Dispatchers.IO) {
                btService.printBytes(mac, tsplBytes)
            }
            binding.btnTestLabel.isEnabled = true
            when (result) {
                is PrintResult.Success  -> showStatus("Test etiketi basıldı ✓", error = false)
                is PrintResult.Failure  -> showStatus(result.message, error = true)
            }
        }
    }

    /**
     * Gerçek TSPL komutu — XP365B uyumlu, 40×80 mm, CP857, Code128 barkod.
     * NexGen _m05_etiket_tspl_bytes() ile aynı yapı.
     */
    private fun buildTestTspl(): ByteArray {
        val barkod  = "TEST-NP-001"
        val argeKod = "NP-TEST"
        val musteri = "SOLARIZ NEXGEN"
        val tarih   = java.text.SimpleDateFormat("dd.MM.yyyy", java.util.Locale.getDefault())
            .format(java.util.Date())

        val cmds = listOf(
            "SIZE 40 mm,80 mm",
            "GAP 3 mm,0 mm",
            "DIRECTION 0",
            "REFERENCE 0,0",
            "OFFSET 0 mm",
            "SET PEEL OFF",
            "SET TEAR ON",
            "CODEPAGE 857",
            "SPEED 4",
            "DENSITY 10",
            "CLS",
            "BAR 0,0,320,30",
            """REVERSE 6,4,308,24,"4",0,1,1,"NEXGEN AR-GE"""",
            """TEXT 6,36,"4",0,1,1,"$argeKod"""",
            "BAR 0,62,320,1",
            """TEXT 6,68,"3",0,1,1,"Mst: $musteri"""",
            """TEXT 6,88,"3",0,1,1,"Tarih: $tarih"""",
            """TEXT 6,104,"3",0,1,1,"Test Baskisi - NexGen Print Bridge"""",
            """TEXT 6,120,"3",0,1,1,"REV: R00   N: N01"""",
            "BAR 0,138,320,1",
            """BARCODE 10,144,"128",60,1,0,2,4,"$barkod"""",
            """TEXT 6,218,"3",0,1,1,"$barkod"""",
            "PRINT 1,1",
        )
        val tspl = cmds.joinToString("\r\n") + "\r\n"
        return tspl.toByteArray(charset("Cp857"))
    }

    // ── Durum göster ─────────────────────────────────────────────────────────

    private fun showStatus(msg: String, error: Boolean) {
        binding.cardLastStatus.visibility = View.VISIBLE
        binding.tvLastStatus.text = msg
        binding.tvLastStatus.setTextColor(
            if (error) 0xFFDC2626.toInt() else 0xFF16A34A.toInt()
        )
        binding.tvLastError.visibility = View.GONE
    }

    // ── Bluetooth izinleri ────────────────────────────────────────────────────

    private fun requestBtPermissionsIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val needed = listOf(
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN,
            ).filter {
                ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
            }
            if (needed.isNotEmpty()) {
                ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQ_BT_PERMISSIONS)
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_BT_PERMISSIONS) {
            refreshDeviceList()
        }
    }
}

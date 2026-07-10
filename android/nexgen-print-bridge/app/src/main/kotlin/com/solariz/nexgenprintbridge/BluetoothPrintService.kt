package com.solariz.nexgenprintbridge

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import android.content.Context
import java.io.IOException
import java.io.OutputStream
import java.util.UUID

/**
 * Bluetooth Classic SPP (RFCOMM) bağlantısı ve ham byte yazma.
 *
 * Kurallar:
 * - Her baskı işlemi sonunda socket ve OutputStream kapatılır.
 * - Zaman aşımı: bağlantı 8s, yazma 10s (socket ayrı thread'de)
 * - XP365B destekler: Bluetooth Classic SPP UUID 00001101-...
 */
class BluetoothPrintService(private val context: Context) {

    companion object {
        private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        private const val CONNECT_TIMEOUT_MS = 8_000L
        private const val WRITE_TIMEOUT_MS   = 10_000L
    }

    private val adapter: BluetoothAdapter? = BluetoothAdapter.getDefaultAdapter()

    /**
     * Eşleşmiş Bluetooth cihazlarını döner.
     * Android 12+ için BLUETOOTH_CONNECT izni kontrolü dahil.
     */
    @SuppressLint("MissingPermission")
    fun getPairedDevices(): List<BluetoothDevice> {
        if (adapter == null || !adapter.isEnabled) return emptyList()
        if (!hasBtConnectPermission()) return emptyList()
        return adapter.bondedDevices?.toList() ?: emptyList()
    }

    /**
     * Belirtilen MAC adresine SPP bağlantısı kurar ve TSPL byte dizisini gönderir.
     * Her durumda socket güvenli kapatılır.
     *
     * @param macAddress XP365B Bluetooth MAC (örn: "00:11:22:33:44:55")
     * @param data TSPL komut baytları (CP857 encoded)
     * @return PrintResult.Success veya PrintResult.Failure.*
     */
    @SuppressLint("MissingPermission")
    fun printBytes(macAddress: String, data: ByteArray): PrintResult {
        // Bluetooth açık mı?
        if (adapter == null || !adapter.isEnabled) {
            return PrintResult.Failure.BluetoothOff()
        }
        if (!hasBtConnectPermission()) {
            return PrintResult.Failure.ConnectFailed("BLUETOOTH_CONNECT izni eksik")
        }

        // Cihaz listede var mı?
        val device: BluetoothDevice? = adapter.bondedDevices?.find {
            it.address.equals(macAddress, ignoreCase = true)
        }
        if (device == null) {
            return PrintResult.Failure.PrinterNotFound()
        }

        var socket: BluetoothSocket? = null
        var outputStream: OutputStream? = null

        return try {
            // RFCOMM socket oluştur
            socket = device.createRfcommSocketToServiceRecord(SPP_UUID)

            // Bağlantı zaman aşımı — coroutine ortamında withTimeout kullanılır;
            // burada blocking I/O thread'den çağrıldığı için thread interrupt ile kontrol.
            val connectThread = Thread { socket.connect() }
            connectThread.start()
            connectThread.join(CONNECT_TIMEOUT_MS)

            if (connectThread.isAlive) {
                connectThread.interrupt()
                return PrintResult.Failure.ConnectFailed("Bağlantı zaman aşımı (${CONNECT_TIMEOUT_MS / 1000}s)")
            }

            if (!socket.isConnected) {
                return PrintResult.Failure.ConnectFailed()
            }

            outputStream = socket.outputStream

            // Yazma zaman aşımı
            var writeException: Exception? = null
            val writeThread = Thread {
                try {
                    outputStream.write(data)
                    outputStream.flush()
                } catch (e: IOException) {
                    writeException = e
                }
            }
            writeThread.start()
            writeThread.join(WRITE_TIMEOUT_MS)

            if (writeThread.isAlive) {
                writeThread.interrupt()
                return PrintResult.Failure.WriteFailed("Yazma zaman aşımı")
            }

            if (writeException != null) {
                return PrintResult.Failure.WriteFailed(
                    writeException?.message?.take(120) ?: "Yazıcı kapalı veya menzil dışı"
                )
            }

            PrintResult.Success

        } catch (e: IOException) {
            PrintResult.Failure.ConnectFailed(
                e.message?.take(120) ?: "Bluetooth bağlantısı kurulamadı"
            )
        } catch (e: Exception) {
            PrintResult.Failure.Unknown(e.message?.take(120) ?: "Bilinmeyen Bluetooth hatası")
        } finally {
            // Her durumda güvenli kapat
            try { outputStream?.close() } catch (_: Exception) {}
            try { socket?.close() }       catch (_: Exception) {}
        }
    }

    /**
     * Test bağlantısı — veri göndermez, sadece bağlanıp keser.
     */
    @SuppressLint("MissingPermission")
    fun testConnection(macAddress: String): PrintResult {
        if (adapter == null || !adapter.isEnabled) return PrintResult.Failure.BluetoothOff()
        if (!hasBtConnectPermission()) return PrintResult.Failure.ConnectFailed("İzin eksik")

        val device = adapter.bondedDevices?.find {
            it.address.equals(macAddress, ignoreCase = true)
        } ?: return PrintResult.Failure.PrinterNotFound()

        var socket: BluetoothSocket? = null
        return try {
            socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
            val t = Thread { socket.connect() }
            t.start()
            t.join(CONNECT_TIMEOUT_MS)
            if (t.isAlive) {
                t.interrupt()
                return PrintResult.Failure.ConnectFailed("Zaman aşımı")
            }
            if (socket.isConnected) PrintResult.Success
            else PrintResult.Failure.ConnectFailed()
        } catch (e: IOException) {
            PrintResult.Failure.ConnectFailed(e.message?.take(80) ?: "Hata")
        } finally {
            try { socket?.close() } catch (_: Exception) {}
        }
    }

    // ── İzin yardımcısı ──────────────────────────────────────────────────────

    private fun hasBtConnectPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ContextCompat.checkSelfPermission(
                context,
                android.Manifest.permission.BLUETOOTH_CONNECT
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true // API < 31: BLUETOOTH izni manifest'te yeterli
        }
    }
}

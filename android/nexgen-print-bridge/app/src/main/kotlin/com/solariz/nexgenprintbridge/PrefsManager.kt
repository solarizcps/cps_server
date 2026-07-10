package com.solariz.nexgenprintbridge

import android.content.Context
import android.content.SharedPreferences

/**
 * Kalıcı ayarlar: seçili yazıcı MAC adresi, yazıcı adı, CPS server URL.
 * SharedPreferences kullanır — uygulama yeniden başlasa da ayarlar korunur.
 */
class PrefsManager private constructor(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    // ── Yazıcı MAC ────────────────────────────────────────────────────────────

    var printerMac: String?
        get() = prefs.getString(KEY_PRINTER_MAC, null)
        set(value) = prefs.edit().putString(KEY_PRINTER_MAC, value).apply()

    var printerName: String?
        get() = prefs.getString(KEY_PRINTER_NAME, null)
        set(value) = prefs.edit().putString(KEY_PRINTER_NAME, value).apply()

    fun hasPrinter(): Boolean = !printerMac.isNullOrBlank()

    // ── CPS Server URL ────────────────────────────────────────────────────────

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        set(value) {
            val trimmed = value.trimEnd('/')
            prefs.edit().putString(KEY_SERVER_URL, trimmed).apply()
        }

    // ── Singleton ─────────────────────────────────────────────────────────────

    companion object {
        private const val PREF_NAME         = "nexgen_print_bridge"
        private const val KEY_PRINTER_MAC   = "printer_mac"
        private const val KEY_PRINTER_NAME  = "printer_name"
        private const val KEY_SERVER_URL    = "server_url"
        private const val DEFAULT_SERVER_URL = "http://192.168.1.100:8080"

        @Volatile
        private var instance: PrefsManager? = null

        fun getInstance(context: Context): PrefsManager =
            instance ?: synchronized(this) {
                instance ?: PrefsManager(context).also { instance = it }
            }
    }
}

package com.solariz.nexgenprintbridge

import android.net.Uri
import android.util.Base64
import org.json.JSONObject
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * CPS server Android Print Bridge API istemcisi.
 * HttpURLConnection kullanır — harici bağımlılık gerektirmez.
 *
 * Tüm metodlar blocking — Coroutine/Thread içinden çağrılmalı.
 */
class CpsApiService(private val serverUrl: String) {

    companion object {
        private const val CONNECT_TIMEOUT = 8_000
        private const val READ_TIMEOUT    = 12_000
    }

    data class JobPayload(
        val jobId: Int,
        val etiketId: Int,
        val status: String,
        val payloadBase64: String,
    )

    // ── GET /api/android/print-job/<id> ──────────────────────────────────────

    fun getJob(jobId: Int, token: String): Result<JobPayload> = runCatching {
        val url = URL("$serverUrl/nexgen/api/android/print-job/$jobId")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        conn.connectTimeout = CONNECT_TIMEOUT
        conn.readTimeout    = READ_TIMEOUT
        conn.setRequestProperty("X-Print-Token", token)
        conn.setRequestProperty("Accept", "application/json")

        val code = conn.responseCode
        val body = conn.inputStream.bufferedReader().readText()
        conn.disconnect()

        val json = JSONObject(body)

        when {
            code == 403 -> throw CpsApiException.TokenInvalid
            code == 409 -> throw CpsApiException.AlreadyPrinted(
                json.optString("status", "PRINTED")
            )
            code != 200 -> throw CpsApiException.HttpError(code, json.optString("hata"))
            !json.optBoolean("ok", false) -> throw CpsApiException.HttpError(
                code, json.optString("hata")
            )
        }

        JobPayload(
            jobId       = json.getInt("job_id"),
            etiketId    = json.getInt("etiket_id"),
            status      = json.getString("status"),
            payloadBase64 = json.getString("payload_base64"),
        )
    }

    // ── POST /api/android/print-job/<id>/claim ────────────────────────────────

    fun claimJob(jobId: Int, token: String): Result<Unit> = runCatching {
        postEmpty("$serverUrl/nexgen/api/android/print-job/$jobId/claim", token)
    }

    // ── POST /api/android/print-job/<id>/success ─────────────────────────────

    fun successJob(jobId: Int, token: String): Result<Unit> = runCatching {
        postEmpty("$serverUrl/nexgen/api/android/print-job/$jobId/success", token)
    }

    // ── POST /api/android/print-job/<id>/fail ────────────────────────────────

    fun failJob(jobId: Int, token: String, hata: String): Result<Unit> = runCatching {
        val body = JSONObject().put("hata", hata).toString()
        postJson("$serverUrl/nexgen/api/android/print-job/$jobId/fail", token, body)
    }

    // ── Yardımcılar ──────────────────────────────────────────────────────────

    private fun postEmpty(urlStr: String, token: String) {
        val url = URL(urlStr)
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = CONNECT_TIMEOUT
        conn.readTimeout    = READ_TIMEOUT
        conn.setRequestProperty("X-Print-Token", token)
        conn.setRequestProperty("Content-Length", "0")
        val code = conn.responseCode
        conn.disconnect()
        if (code !in 200..299) {
            throw CpsApiException.HttpError(code, "HTTP $code")
        }
    }

    private fun postJson(urlStr: String, token: String, jsonBody: String) {
        val url = URL(urlStr)
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = CONNECT_TIMEOUT
        conn.readTimeout    = READ_TIMEOUT
        conn.doOutput = true
        conn.setRequestProperty("X-Print-Token", token)
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        val out: OutputStream = conn.outputStream
        out.write(jsonBody.toByteArray(Charsets.UTF_8))
        out.flush()
        out.close()
        val code = conn.responseCode
        conn.disconnect()
        if (code !in 200..299) {
            throw CpsApiException.HttpError(code, "HTTP $code")
        }
    }
}

/** CPS API'ye özgü istisnalar */
sealed class CpsApiException(message: String) : Exception(message) {
    object TokenInvalid : CpsApiException("Baskı yetkisi süresi dolmuş")
    data class AlreadyPrinted(val status: String) : CpsApiException("Bu etiket zaten basılmış ($status)")
    data class HttpError(val code: Int, val detail: String?) :
        CpsApiException("Sunucu hatası: HTTP $code — ${detail ?: "bilinmeyen"}")
}

/** payload_base64 → ByteArray */
fun decodePayload(base64: String): ByteArray = Base64.decode(base64, Base64.DEFAULT)

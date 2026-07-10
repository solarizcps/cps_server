package com.solariz.nexgenprintbridge

/** Bluetooth baskı sonucu — tüm olası durumları kapsar. */
sealed class PrintResult {
    object Success : PrintResult()

    sealed class Failure(open val message: String) : PrintResult() {
        /** Bluetooth adaptörü kapalı */
        data class BluetoothOff(override val message: String = "Bluetooth kapalı. Lütfen açın.") : Failure(message)

        /** Yazıcı eşleşmiş cihazlar listesinde bulunamadı */
        data class PrinterNotFound(override val message: String = "Yazıcı bulunamadı. Ana ekrandan seçin.") : Failure(message)

        /** RFCOMM socket bağlantısı kurulamadı */
        data class ConnectFailed(override val message: String = "Bluetooth bağlantısı kurulamadı") : Failure(message)

        /** Yazma başarısız veya zaman aşımı */
        data class WriteFailed(override val message: String = "Yazıcı kapalı veya menzil dışı") : Failure(message)

        /** Sunucu API hatası */
        data class ServerError(override val message: String = "Sunucu bağlantısı kesildi") : Failure(message)

        /** Token geçersiz veya süresi dolmuş */
        data class InvalidToken(override val message: String = "Baskı yetkisi süresi dolmuş") : Failure(message)

        /** Zaten basılmış */
        data class AlreadyPrinted(override val message: String = "Bu etiket zaten basılmış") : Failure(message)

        /** Genel/bilinmeyen hata */
        data class Unknown(override val message: String) : Failure(message)
    }
}

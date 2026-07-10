# NexGen Print Bridge — Kurulum ve Kullanım Rehberi

## Genel Bakış

NexGen Print Bridge, Android tabletlerin CPS web uygulamasından doğrudan
Bluetooth üzerinden XP365B termal yazıcıya etiket basmasını sağlar.

- **Paket adı:** `com.solariz.nexgenprintbridge`
- **Minimum Android:** 8.0 (API 26)
- **Yazıcı:** XP365B (Bluetooth Classic / SPP)
- **Etiket boyutu:** 40×80 mm, TSPL dili

---

## BÖLÜM 1 — APK Build (Geliştirici Bilgisayarında)

### Gereksinimler

| Araç | Sürüm |
|------|-------|
| Android Studio | Hedgehog (2023.1.1) veya üzeri |
| JDK | 17 (Android Studio bundled JDK yeterli) |
| Android SDK | API 34 |
| Gradle | 8.6 (wrapper otomatik indirir) |

### Adımlar

1. **Projeyi aç:**
   ```
   Android Studio → File → Open
   → C:\Solariz_CPS_SERVER\android\nexgen-print-bridge
   → OK
   ```

2. **Gradle Sync:**
   - Studio otomatik sync başlatacak.
   - Alt panelde "Gradle sync finished" yazısını bekle.
   - Hata varsa: `File → Sync Project with Gradle Files`

3. **Debug APK üret:**
   ```
   Build → Build Bundle(s) / APK(s) → Build APK(s)
   ```
   Ya da terminal ile:
   ```bat
   cd C:\Solariz_CPS_SERVER\android\nexgen-print-bridge
   gradlew.bat assembleDebug
   ```

4. **APK yolu:**
   ```
   android\nexgen-print-bridge\app\build\outputs\apk\debug\
   NexGen-Print-Bridge-debug.apk
   ```

5. **"locate" linkine tıkla** — APK Explorer'da açılır.

---

## BÖLÜM 2 — Tablete Kurulum

### Yöntem A: USB ile Kopyala

1. Tableti USB kabloyla bilgisayara bağla.
2. Tablette "Dosya Aktarımı / MTP" modunu seç.
3. `NexGen-Print-Bridge-debug.apk` dosyasını tablet'in **İndirilenler** klasörüne kopyala.
4. Tablette **Dosya Yöneticisi**ni aç → İndirilenler → APK dosyasına dokun.

### Yöntem B: Wi-Fi ile (Aynı ağdaysa)

1. APK'yı CPS sunucusuna koy:
   ```
   C:\Solariz_CPS_SERVER\app\static\apk\NexGen-Print-Bridge-debug.apk
   ```
2. Tablette tarayıcıda aç:
   ```
   http://192.168.1.16:8080/static/apk/NexGen-Print-Bridge-debug.apk
   ```
3. İndir → Aç.

### Bilinmeyen Kaynak İzni

Android bilinmeyen kaynaklardan uygulama kurulumunu engeller.

1. APK dosyasına dokunulduktan sonra uyarı çıkar.
2. **"Ayarlar"** butonuna dokun.
3. **"Bu kaynaktan izin ver"** seçeneğini aç.
4. Geri dön → **"Yükle"** butonuna dokun.
5. Kurulum tamamlandığında **"Aç"** butonuna dokun.

---

## BÖLÜM 3 — İlk Açılış ve Yapılandırma

### Adım 1: Bluetooth İzinleri

Uygulama açıldığında izin isteği gelir:

```
"NexGen Print Bridge uygulamasının yakındaki
 Bluetooth cihazlarını bulmasına izin verilsin mi?"
```

→ **"İzin ver"** seç.

### Adım 2: XP365B Yazıcıyı Eşleştir

Önce tablette XP365B'yi Bluetooth ile eşleştirmen gerekiyor:

1. Tablet → **Ayarlar → Bağlı Cihazlar → Yeni Cihaz Eşleştir**
2. XP365B'yi aç (güç tuşuna bas, mavi LED yanıp sönsün).
3. Listede **"XP365B"** veya **"Printer"** görünecek → dokun → **Eşleştir**.
4. Bağlantı PIN'i sorulursa: **`0000`** veya **`1234`**

### Adım 3: NexGen Print Bridge'de Yazıcı Seç

Uygulama açıkken:

1. **"EŞLEŞMIŞ BLUETOOTH CİHAZLARI"** listesinde **XP365B** görünecek.
2. Üzerine dokun → **"Yazıcı seçildi: XP365B"** mesajı çıkar.
3. Üst kartta **"SEÇİLİ YAZICI: XP365B"** güncellenir.

### Adım 4: CPS Server Adresi Kaydet

1. En altta **"CPS SUNUCU ADRESİ"** alanını bul.
2. Şu adresi gir:
   ```
   http://192.168.1.16:8080
   ```
3. **"Kaydet"** butonuna dokun → "Sunucu adresi kaydedildi" mesajı çıkar.

### Adım 5: Bağlantı Testi

1. **"Bağlantıyı Test Et"** butonuna dokun.
2. XP365B'nin açık ve yakında olduğundan emin ol.
3. **"Bağlantı başarılı ✓"** mesajı gelmeli.

### Adım 6: Test Etiketi Bas

1. **"Test Etiketi Bas"** butonuna dokun.
2. Yazıcıdan **"NexGen Print Bridge / TEST-NP-001"** yazılı bir etiket çıkmalı.
3. **"Test etiketi basıldı ✓"** mesajı gözükür.

---

## BÖLÜM 4 — CPS'den Gerçek Etiket Basma

1. Tablette tarayıcıyı aç → CPS giriş yap.
2. NexGen → AR-GE modülüne git.
3. Bir test kaydını aç → **"YENİ NUMUNE ETİKETİ OLUŞTUR"** veya **"YAZDIR"** butonuna dokun.
4. Uygulama otomatik açılacak ve yazıcıya gönderecek.
5. **"Etiket basıldı ✓"** mesajı geldikten sonra **"CPS'ye Dön"** butonuna dokun.

---

## BÖLÜM 5 — Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| "Bluetooth kapalı" | Tablet Bluetooth'u aç |
| "Yazıcı bulunamadı" | Adım 2'yi tekrarla (eşleştir) |
| "Bluetooth bağlantısı kurulamadı" | XP365B'yi kapat/aç, 1m yaklaşa |
| "Sunucu bağlantısı kesildi" | Server adresini kontrol et, Wi-Fi bağlantısını kontrol et |
| "NexGen Print Bridge bulunamadı" | APK kurulmamış, tekrar kur |
| "Baskı yetkisi süresi dolmuş" | CPS'de tekrar baskı isteği oluştur |
| "Bu etiket zaten basılmış" | Normal durum — çift baskı engellendi |

---

## BÖLÜM 6 — Güncelleme

Yeni APK mevcut APK'nın **üstüne kurulabilir**, veri kaybolmaz:

- Yazıcı MAC adresi korunur
- Server URL korunur
- Paket adı: `com.solariz.nexgenprintbridge` (değişmez)

Güncelleme adımları Bölüm 2 ile aynıdır.

---

## Teknik Bilgiler

```
Paket adı    : com.solariz.nexgenprintbridge
Min SDK      : 26 (Android 8.0)
Target SDK   : 34 (Android 14)
Bluetooth    : Classic SPP / RFCOMM
UUID         : 00001101-0000-1000-8000-00805F9B34FB
TSPL         : 40×80 mm, CP857, Code128
Server       : http://192.168.1.16:8080
URL Scheme   : nexgenprint://print?job_id=...&token=...
```

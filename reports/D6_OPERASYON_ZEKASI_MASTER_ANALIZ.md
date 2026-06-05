# D6 - OPERASYON ZEKASI MASTER ANALIZ

**Tarih:** 18.05.2026 10:36
**Tip:** RECON + ANALIZ - kod yok, patch yok, sisteme dokunma yok
**Amaç:** AI destekli operasyon zekasi icin veri yeterliligi + mimari yol haritasi

---

## 1. YONETICI OZETI

CPS sistemi C.8 sonrasi canliya gecti. uretim_kayit 1383 satir, 32 personel, 35 proses, 339 emir.
emir_alt_proses 2282 satir (595 emir, 44 proses). Korgun MSSQL canli baglantili.

**Buyuk bulgu:** Operasyon zekasi icin **veri ZATEN YETERLI**. Saat verisi %100 dolu, personel bazi miktar
+ proses zengin, durgun emir tespiti hemen mumkun (513 emir 7+ gundur durgun). AI 'Halil burada yavas'
seviyesine teknik olarak gidebilir, ama Halil su an **tek usta** (proses_usta_atama'da 10 prosese hepsi
halil) - bu calisma sekli D6 oncesi degismeli.

**Veri yeterlilik skoru: 7/10** (Korgun veri normalize edilirse 9/10).

---

## 2. VERI ENVANTERI

### uretim_kayit (1383)
- 23 kolon, saat/tarih/olusturma %100 dolu
- onaylandi %97, reddedildi 38, bekliyor 2
- Kaynak: LEGACY_5055 1171, CPS_CANLI 204, CPS_TEST 8
- 32 personel x 35 proses x 339 emir
- Audit: usta_ad, usta_not, onay_tarihi var

### emir_alt_proses (2282)
- 595 emir, 44 proses adi varyanti
- aktif %99 (2254), pasif 28
- Kaynak: 5055_IMPORT 2127, sablon: 126, CPS_TRIGGER_C5 1
- created_at NULL (P7 audit fix bekliyor)

### personel_kullanici (22, 33 kolon)
- AdSoyad, PersonelTipi, Vardiya, Yildiz, Pozisyon var
- PdksPersonelId (PDKS bagi), EkipLideri, SistemKullaniciId
- GuvenSkoru, IdentityDurum (SOIS spine)
- **D6 icin altin tablo**

### Diger
- proses_kategori (11 standart, standart_saniye field var memory'den)
- proses_usta_atama (10 - HEPSI HALIL)
- bildirim_log (24 - **push altyapisi schema'si var**)
- is_akisi (3 rol bazli is grubu)
- sistem_audit (893 - tum degisiklik izleme)
- vardiya_devir_log (0 - kullanilmiyor)
- planlama_karar (0 - karar masasi backend bos)

---

## 3. SINYALLER (mevcut veriden cikan)

### S1: GECIKEN EMIR (KRITIK)
- 513 emir aktif ama son 7 gun hareket yok
- 262 emir hic uretim_kayit yok
- Bu su an saha goremiyor

### S2: PROSES HIZI (ONEMLI)
Her proses icin ort/min/max var. Standart benchmark:
- ort kayit basina 400-500 cift
- atki silindi: 451, max 480
- asagi is indirme: 477, max 800

### S3: PERSONEL HIZI (ONEMLI)
- ilham jameshev: 4929/gun
- najova: 3954/gun
- merdan hojamkulov: 417/gun (5x daha az)
- "Halil hizli" gibi gozukuyor cunku usta_onay olarak sayiliyor

### S4: GERI BILDIRIM ORANI
- onaylandi %97
- reddedildi %3 (Halil reddetti)
- Saglikli oran

### S5: CPS_TRIGGER (cok dusuk)
- C.8 sonrasi 1 saatte sadece 1 trigger
- Saha CPS dolu emirleri cagiriyor, trigger zorunlu cikmiyor

---

## 4. ESKIKLER VE TEKNIK BORC

### 4.1 KRITIK
- **K1: Tek usta darbogaz** (Halil) - operasyon zekasi otomasyona donemez
- **K2: Korgun veri kalite** - LEGACY_5055'te model_kod %94 NULL, proses_kodu NULL
- **K3: bildirim sender yok** - schema var ama push gonderim yok

### 4.2 ONEMLI
- **O1: created_at audit fix** - P7 patch (2 satir, 30 dk)
- **O2: proses_adi normalize** - 44 varyant -> 11 standart mapping
- **O3: Korgun veri normalize katmani** - model_kod backfill, proses_kodu mapping
- **O4: Standart sure kolonu doldur** (proses_kategori) - bench icin

### 4.3 SONRA
- Vardiya devir log doldur
- planlama_karar tablosu kullanima al
- Korgun kayit baslangic-bitis ZAMAN (su an sadece miktar)
- Mola/duraklama kaydi
- Hatali parca tracking

---

## 5. MEVCUT ALTYAPI

### Push/Bildirim
- bildirim_log tablosu hazir (24 kayit, 13 kolon)
- push_gonderildi_mi, snooze_until, dismiss_count - rich schema
- **Ama gercek push gonderici YOK** (VAPID/FCM altyapisi bekleniyor)

### Realtime
- Websocket/SSE referansi yok
- Polling-only su an (192.168.1.196 /api/tasks/notifications/pending her 2sn)

### Mobile UI
- /personel-giris mobile-aware
- /kalite-mobil var (kalite kontrol)
- Diger mobile templates aranacak

### Saha cihaz
- 192.168.2.62 (saha mobil aktif - /emir,/prosesler triple call)
- 192.168.1.196 (yonetim PC izleme - darbogaz-ozet polling)
- 192.168.1.29 (test/admin)

---

## 6. ONERILEN D6 MIMARI

### Yaklasim: Realtime engine HAYIR, batch + polling EVET

Sebep:
- Saha 5dk gecikmeye toleranslı
- Realtime karmasik (websocket sticky session, server scaling)
- Polling 2sn aralikta zaten calisiyor (kanitli)
- AI önerileri 30sn-5dk gecikme ile OK

### Onerim: 5 katmanli operasyon zekasi

\\\
[1] SIGNAL_ENGINE (her 5 dk, scheduler)
    - Durgun emir tespiti
    - Hatali eslesme tespiti
    - Hiz alarmi (saatlik benchmark sapmasi)
    -> sinyaller tablosuna INSERT

[2] RULE_ENGINE (her sinyalle birlikte)
    - Rule-based oneri ('Bu emir 3 gun durdu, Halil'e bildirim at')
    - JSON konfig dosyasinda kurallar
    -> oneri/uyari tablosuna INSERT

[3] NOTIFICATION_DISPATCHER (event-driven)
    - bildirim_log'a INSERT eden kaynak
    - Push sender (VAPID web push, basit)
    - Snooze/dismiss yonetimi
    -> bildirim_log'a UPDATE

[4] KARAR_MASASI (UI, halil/usta)
    - Halil onlerine bekleyen oneriler
    - Tek tik kabul/red/erteleme
    - Aksiyon kayitli (usta_aksiyon)

[5] AUDIT (zaten var, sistem_audit)
    - AI'nin yaptigi her oneri kayit
    - Halil'in karari kayit
    - Geriye donus iz
\\\

### Olcek
- Saatlik 5-10 sinyal beklenir (50 oneri/gun)
- Halil 1-2 dakikada sweep yapar
- AI sadece tetikleyici, karar Halil'de

---

## 7. KORGUN VERI KALITE SKORU

### Yansima (CPS uretim_kayit'taki LEGACY_5055 kayitlarindan)

- model_kod: **%94 NULL** (kaynak 5055 zaten bos)
- proses_kodu: muhtemelen %100 NULL (5055 import script'te NULL bilerek)
- personel_id: doluluk degisken
- miktar: %100 dolu (saglikli)
- olusturma: %100 dolu

### Karar
- Korgun MSSQL'den **direkt cekecegimiz veri** kaliteli (online API'de model_kod/proses_kodu/Cari/Model_M dolu)
- 5055 IMPORT olan eski veri eksik (94% model_kod NULL) - ama bu **DURMUS bir veri**, dusunce ekleme/backfill yapilabilir, AI buna dayanmamali
- AI sinyallerinde **kaynak='CPS_CANLI'** ve **kaynak='LEGACY_5055' ayrimi** sart

### Iyi haber
- CPS_CANLI kaliteli giriyor (204 kayit, eksik az)
- Korgun da iyi (online query'de tum alanlar dolu)
- Sadece **LEGACY_5055 historic data** kirli

---

## 8. 6 AYLIK YOL HARITASI

### **D6 - OPERASYON ZEKASI (yarin -> 2 hafta)**

Sprint:
- **D6.1 (1-2 gun):** sinyaller tablosu + scheduler iskelet
- **D6.2 (1 gun):** durgun emir tespit kuralı (en kolay sinyal)
- **D6.3 (1 gun):** proses hiz sapma kuralı (benchmark ile)
- **D6.4 (2 gun):** rule_engine.json + UI (admin)
- **D6.5 (2 gun):** notification_dispatcher + push sender (VAPID)
- **D6.6 (1 gun):** Halil onay UI (karar masasi entegrasyon)
- **D6.7 (2 gun):** smoke test + saha review + iterasyon

Cikti: AI 'gerceklesen vs olmasi gereken' onerileri yapabilir.

### **D7 - PLAN OPTIMIZASYON (3-4 hafta sonra)**

Sprint:
- **D7.1:** Korgun termin/kapasite query'leri
- **D7.2:** plan_v2 cikti zenginlestir (termin, sira)
- **D7.3:** AI plan onerisi (kural-tabanli)
   - 'Bu emir terminden 3 gun gecmis, yer degistir'
   - 'Bu hafta hangi emir cikabilir?'
- **D7.4:** Halil ile karar masasi sec/onayla
- **D7.5:** Karar geri verme (saha override)
- **D7.6:** Kapasite vs hedef gosterge paneli
- **D7.7:** Smoke + iterasyon

Cikti: Plan motoru AI ile destek alir, Halil tek karar verici degil.

### **D8 - VARDIYA + KALITE INTEGRATION (6-8 hafta)**

Sprint:
- **D8.1:** vardiya_devir_log doldur (gunluk)
- **D8.2:** Vardiya farkı analizi
- **D8.3:** Kalite kontrol (mevcut /kalite-mobil + AQL)
- **D8.4:** Hatali parca tracking (yeni tablo)
- **D8.5:** Mola/duraklama (yeni)
- **D8.6:** Personel performans skor (D6'dan zenginlestir)
- **D8.7:** Yildiz/prim sistemi otomatize

Cikti: 200 personel performans takibi, vardiya optimizasyonu.

### **D9 - MAKINE OGRENMESI + TAHMINLEME (3-4 ay sonra)**

Sprint:
- **D9.1:** Veri lake olustur (Korgun + CPS + PDKS birlestir)
- **D9.2:** Iste 'darbogaz tahmini' modeli (XGBoost/LightGBM)
- **D9.3:** Termin uyumu tahmini (regresyon)
- **D9.4:** Anomali tespiti (isolation forest)
- **D9.5:** Saha ile feedback loop (Halil onaylari ML'a)
- **D9.6:** Tahminler UI'de gostergele
- **D9.7:** Iterasyon + ML monitoring

Cikti: 'Bu emir terminde teslim olmayabilir, dikkat' tarzi proactive AI.

---

## 9. ON GORULER

### Hizli kazanim (D6 1. hafta)
1. **Durgun emir uyarisi** - 513 emir tek tıkta gorunur
2. **Sapma raporu** - proses x personel x saatlik tablo
3. **Sablon kullanim oranlari** - AI hangi sablon cok yanlis eslesiyor

### Orta vadeli (D6 1. ay)
1. **Halil cogaltıcı** - usta atamasi 1 -> 3 kisi
2. **Push notification** - mobil bildirim altyapisi
3. **Karar masasi v2** - AI onerileri ile

### Uzun vadeli (D6+D7 2-3 ay)
1. **Tek bir komuta planlamasi** - Korgun + AI + Halil onay
2. **Saha performansi otomatik** - prim sistemi gercek zamanli
3. **5055 kapatildi** - tum saha CPS uzerinden

---

## 10. RISK MATRISI

| Risk | Olasilik | Etki | Azaltma |
|------|----------|------|---------|
| Halil tek usta darbogaz | YUKSEK | KRITIK | D6 baslamadan once 2. usta egitimi |
| Korgun veri kirli | DUSUK | ONEMLI | Online query yeterli (LEGACY_5055 ayri) |
| Push gondericinin AI ile uretmesi | ORTA | DUSUK | VAPID web push basit, FCM gerek yok |
| Saha 5055'e geri donmek isteyebilir | ORTA | ORTA | 5055 gozlem suresinde acik |
| AI yanlis oneri | YUKSEK | DUSUK | Halil her zaman onay kapisi |

---

## 11. SONRAKI ADIM

1. **Bu rapor goz gezdir** - Adem ile teknik tartisma
2. **D6.1 baslat:** sinyaller tablosu sema + ilk RECON
3. Korgun veri kalite testleri (yanlislama icin)
4. Halil ile saha review (usta cogaltma karari)
5. **Sprint review:** 1. hafta sonu D6 ilerleme degerlendirme

---

**HAZIRLAYAN:** Claude (Solariz CPS sprint kayitlarindan)
**KONUM:** D:\Firma_Ozel\adem\Solariz_CPS_SERVER\reports\D6_OPERASYON_ZEKASI_MASTER_ANALIZ.md
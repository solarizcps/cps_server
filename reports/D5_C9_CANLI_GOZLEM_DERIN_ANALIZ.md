# D5 C.9 - CANLI GOZLEM DERIN ANALIZ RAPORU

**Tarih:** 18.05.2026 10:27
**Pencere:** 10:10 (C.8 flip) -> 10:25 (analiz)
**Sure:** ~15 dakika canli rollout sonrasi
**Sistem:** FLAG=True, GOZLEM MODU, kod degisikligi YOK

---

## YONETICI OZETI

C.8 rollout sonrasi 15 dakika canli izleme. Sistem stabil, lazy hook calisiyor,
saha mobil cihazlarda hiçbir kesinti yok. Onemli bulgu: **5055 kapatma risksiz** -
CPS aktif 594 emir, 5055'te 592 emir, hepsi CPS'te de mevcut (only_5055=0).

5055 fallback su an pratikte hicbir emir icin tetiklenmiyor cunku zaten butun
veriler 12.05.2026 LEGACY_5055 import'u ile CPS'e tasinmis.

---

## SAHA CANLI DURUM (10:24-10:25 log analizi)

| Cihaz IP | Tip | Aktivite |
|----------|-----|----------|
| 192.168.2.62 | Saha mobil | /emir/110766, 110768, 110770 cagriyor (CPS dolu) |
| 192.168.1.196 | Yonetim PC | /darbogaz-ozet, /operasyon-ozet izleme |
| 127.0.0.1 | Local | /health periyodic, /api/tasks/notifications |

**Saha personeli aktif, CPS_NATIVE response aliyor, kesinti YOK.**

---

## [1] TRIGGER BUYUME — DUSUK RISK

| Olcum | Deger |
|-------|-------|
| Toplam CPS_TRIGGER kayit | 9 |
| Aktif | 1 (sadece 111015) |
| Pasif (P5/P6 test) | 8 (111005 - tum geri alindi) |
| Distinct emir | 2 |
| C.8 sonrasi saha kaynakli trigger | 0 (kontrolsuz tetikleme YOK) |

**Yorum:** Saha mesai aktif olmasina ragmen C.8'den beri (10:10) yeni hicbir
otomatik trigger gerceklesmedi. Cunku saha sadece **CPS dolu emirleri** cagiriyor.

---

## [2] FALLBACK ANALIZI — KRITIK BULGU

Veri seti dagilim:
- CPS aktif distinct emir: **594**
- 5055 distinct emir: **592**
- Sadece 5055'te: **0** (only_5055)
- Sadece CPS'te: **2** (111005 sablon manuel + 111015 trigger)
- Her ikisinde: **592**

**KRITIK:** Hicbir emir sadece 5055'te yok. 5055 kapanirsa kirilacak emir = 0.

**Sebep:** 12.05.2026 LEGACY_5055 FAZ 2C import ile 5055'in TUM kayitlari
(1171 satir, 592 distinct emir) CPS'e tasindi. CPS aktif kayitlarinin
%87'si (2127/2434) hala kaynak='5055_IMPORT'.

| kaynak (aktif) | kayit | distinct emir |
|----------------|-------|---------------|
| 5055_IMPORT | 2127 | 592 |
| sablon:Atki LCW | 126 | 62 |
| CPS_TRIGGER_C5:Asagi is indirme | 1 | 1 |

---

## [3] SABLON DOGRULUGU — MANUEL DOGRULAMA

(Runtime test app-context disinda calismadi, manuel sonuc)

**111005 (M tip, Sahin Taban) -> 'Atki LCW' (varsayilan onc 999):**
- P5 test (sablon_id=NULL): 4 proses INSERT, sonra geri alindi (pasif)
- P6 test (sablon_id=1): 4 proses INSERT, sonra geri alindi (pasif)
- Sablon eslesme MANTIKLI - cari/model 'sahin taban' icin varsayilan kural

**111015 (Y tip, cari=None) -> 'Asagi is indirme' (tip=Y, onc 100):**
- C.8 test (sablon_id=3): 1 proses INSERT, AKTIF
- Sablon eslesme **DOGRU** - tip=Y kurali oncelik 100 calisti

Yanlis eslesme suphesi YOK.

---

## [4] PERFORMANS — DUSUK RISK

Endpoint avg sureleri:

| Endpoint | avg | min | max |
|----------|-----|-----|-----|
| /health | 5 ms | 4 | 6 |
| /prosesler/110393 (CPS dolu) | 12 ms | 5 | 24 |
| /prosesler/111015 (trigger var) | 5 ms | 4 | 6 |
| /prosesler/999999 (3 yerde de yok) | 11 ms | 7 | 19 |

**Yorum:** Tum response <25ms. Lazy hook hicbir performans cezasi yok.
Korgun cagrisi 999999 icin de hizli (<11ms) - Korgun "yok" cevabini hizli veriyor.

---

## [5] AUDIT KALITESI — ONEMLI EKSIKLIK

| Alan | NULL orani |
|------|------------|
| created_at | **100% (9/9)** |
| updated_at | **100% (9/9)** |
| olusturan_id | 0% (her zaman dolu) |
| olusturan_ad | 0% (her zaman dolu) |
| sablon_id | 44% (4/9 - P5 oncesi audit oncesi) |

**TEKNIK BORC:** \_sablon_uygula_internal\ INSERT'i created_at/updated_at
kolonlarini DOLDURUYOR DEGIL. emir_alt_proses tablosunda DEFAULT YOK.

**Etki:** Trigger zaman cizgisi tutulamiyor (analizler gecikti).
**Cozum:** _sablon_uygula_internal'a 2 satir ekle (P7 kucuk patch):
\\\python
"created_at": datetime.now().isoformat(timespec='seconds'),
"updated_at": datetime.now().isoformat(timespec='seconds'),
\\\

---

## [6] 5055 BAGIMLILIK HARITASI — DUSUK RISK

**Kod path:** personel_giris/routes.py L496 (TEK YER) - veri_kaynagi='LEGACY_5055_SNAPSHOT'

**5055 fallback canli kullanimi (son 1000 log satir):**
- LEGACY_5055_WARNING: 4 occurrence
  - /prosesler/111015 (10:07 - C.8 oncesi dry-run bizim)
  - /prosesler/999999 x3 (10:24 - bizim test)
- Saha kaynakli 5055 fallback: **0**

**5055 kapatma senaryosu:**
- Veri kaybi: 0 (tum 592 emir CPS'e ezbere kopyalandi)
- Kod path: tek nokta, kapatildiginda gracefully return [] doner
- Saha etkisi: Yok (saha 5055'i fallback olarak hic kullanmiyor su an)
- Korgun bos donerse: [] doner (artik 5055 sigorta agi degil)

**Karar:** 5055 kapatma D6 sprint'inde guvenli yapilabilir.

---

## [7] SAHA DAVRANISI — DUSUK RISK

**uretim_kayit:** 1383 toplam (saba bashlangici 1380'di, +3)
- Bugun: 13 kayit (07:15 -> 10:22)
- Son 1 saat: 3 kayit
- Pazartesi sabah pattern, normal

**Bugun aktif personel (9):**
najova tunus, mustafa enes ozturk, badr safa, aman hudayberdiyev,
sham koibich, moustafa kordy, merdan hojamkulov, mahmoud alkhatib, adem ozkan

**Saha mobil cihazlar:**
- 192.168.2.62 - saha personeli, /emir + /prosesler cagri pattern
- 192.168.1.196 - yonetim (Halil?) izleme

**Saha sikayeti:** YOK (log'da kullanici-yuzlu hata yok)

---

## [8] LOG ANALIZI — DUSUK RISK

**logs/cps_8080.err.log** (15.7 MB):
- Son 1000 satir taramasi
- HOT reason=CPS_EMPTY_AND_5055_EMPTY: 4 occurrence
  - Hepsi 999999 + 111015 (bizim testler)
- Korgun timeout: 0
- Connection_fail: 0
- Traceback: 0
- Exception: 0

**logs/cps_8080.out.log** (5.4 MB):
- Temiz

**LEGACY_5055_WARNING'ler bizim testlerden, sahadan degil. Saha tarafindan
hicbir exception, hata, veya timeout YOK.**

---

# RISK SINIFLANDIRMASI

## KRITIK (acil eylem)
- **YOK** - C.8 rollout temiz, mimari risk yok

## ONEMLI (yakin zamanda yapilmali)

### O1: created_at/updated_at audit eksigi
- Tum CPS_TRIGGER kayitlarinda timestamp NULL
- Trigger zaman cizgisi tutulamiyor
- **Cozum:** _sablon_uygula_internal patch (P7, ~2 satir)
- **Risk:** Dusuk (audit ekleme)
- **Etki:** Dusuk (mevcut data degisme, gelecek INSERT'ler dolacak)

### O2: P5 oncesi 4 NULL sablon_id kaydi (111005 pasif)
- Manuel cleanup yapilabilir veya birakilabilir (aktif=0 zaten)
- **Cozum:** SQL backfill (UPDATE WHERE id IN (2274,2275,2276,2277) SET sablon_id=1)
- **Risk:** Cok dusuk
- **Etki:** Sadece audit gozelligi

## DUSUK (geri planda dusunulebilir)

### D1: 5055 kapatma plani (D6 sprint)
- Veri risksiz (only_5055=0)
- Kod tek nokta (L496)
- Saha kullanim sifir
- **Karar:** C.9 verify (24+ saat) sonrasi guvenli

### D2: sablon_eslesme kural genisletmesi
- Su an 5 kural (varsayilan, tip=Y, musteri=LCW, musteri=Esem, musteri=...)
- ozkod / stok_kodu / weighted match yok
- **Karar:** Saha geri bildirim sonrasi - su an yetiyor

### D3: 5055_IMPORT kaynakli 2127 kayit
- Aktif ama legacy (12.05 import)
- Yeni Korgun trigger kayitlari ile karisik
- **Karar:** Mantikli ayrim mevcut, dokunmaya gerek yok

### D4: Korgun latency timeout limiti
- Su an unlimited
- Korgun bir gun yavasaysa saha mobil bekleyebilir
- **Cozum:** _eslesme_meta_from_emir'a 3sn timeout
- **Karar:** Henuz problem yok, izlenecek

---

# TEKNIK BORC LISTESI

## Simdi ertelenebilecek
- D2 (kural genisletme)
- D3 (5055_IMPORT temizlik)
- D4 (Korgun timeout)
- O2 (NULL sablon_id backfill)

## Sart isler (D6 oncesi)
- O1 (created_at fix) - tek kucuk patch

## Operasyon zekasi oncesi (C.9 -> D6 yolunda)
- C.9 verify - 24+ saat izleme (yarin)
- O1 audit fix
- Saha geri bildirim toplama (Halil ile sozlu)
- 5055 kapatma planlamasi (D6)

---

# KARAR ONERILERI

1. **C.9 verify gozlem suresi:** 24 saat (yarin sabah 10:00'a kadar)
2. **O1 patch:** Yarin sabah, sahaya hazirlik sirasinda
3. **5055 kapatma:** C.9 PASS sonrasi (yarin ogleden sonra erken)
4. **Halil ile saha review:** Bugun ogle arasinda

---

# ROLLBACK HALA HAZIR

- FLAG=False geri al: \Copy-Item app\config.py.YEDEK_C8_FLAG_20260518_101006 app\config.py -Force\
- P4 hook geri al: STABLE_D5_FAZC5_ONCESI_P4_FULL_20260518_093937
- Tek emir trigger geri al: POST /hedef/sablon/geri-al body={"emir_no_listesi":["<emir>"]}
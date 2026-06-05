# D4.9 LEGACY PERSONEL ANALIZ OZETI

**Tarih:** 2026-05-16 12:43:17
**Veri Kaynak:** D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db
**Kural:** Sadece okuma. Hicbir DB degisikligi yok.

---

## 1. Genel Sayilar

| Olcum | Deger |
|---|---|
| personel_kullanici toplam | 21 |
| personel_kullanici aktif | 20 |
| Unique legacy_id | 16 |
| NULL legacy_id | 5 |
| PK duplicate legacy | 0 |
| PK duplicate isim | 0 |
| uretim_kayit toplam | 1346 |
| Unique personel_id (uretim) | 28 |
| sistem_kullanici aktif | 14 |

## 2. Kategori Dagilimi

| Kategori | Adet | Uretim Kayit |
|---|---|---|
| TEMIZ | 8 | 449 |
| KIRLI A (1 legacy, cok isim) | 8 | 670 |
| KIRLI B (1 isim, cok legacy) | 12 | - |
| KIRLI C (benzer isimler) | 1 | - |
| GHOST | 12 | 227 |

## 3. Risk Dagilimi

| Risk | Adet |
|---|---|
| LOW | 8 |
| MEDIUM | 9 |
| HIGH | 9 |
| CRITICAL | 15 |

## 4. En Riskli Legacy Listesi (CRITICAL)

| Kayit | Detay | Kategori | Risk |
|---|---|---|---|
| pid=4 | burçak çelenk / ilham jameshev(59) | burçak çelenk(29) | A | CRITICAL |
| pid=6 | ceren nur erzin / najova tunus(43) | ceren nur erzin(12) | serhat(1) | A | CRITICAL |
| halil kıraç | 2, 5 | B | CRITICAL |
| burçak çelenk | 3, 4 | B | CRITICAL |
| ilham jameshev | 4, 7 | B | CRITICAL |
| najova tunus | 6, 9 | B | CRITICAL |
| sham koıbıch | 7, 12 | B | CRITICAL |
| malika govassemi | 8, 13 | B | CRITICAL |
| mustafa enes öztürk | 9, 15 | B | CRITICAL |
| moustafa kordy | 10, 19 | B | CRITICAL |
| badr safa | 12, 22 | B | CRITICAL |
| adem özkan | 13, 23 | B | CRITICAL |
| merdan hojamkulov | 14, 24 | B | CRITICAL |
| aman hudayberdiyev | 16, 27 | B | CRITICAL |

## 5. Normalization Onerileri

### Oncelik 1: CRITICAL Risk (Manuel Karar Gerek)

- KIRLI A CRITICAL: 2 vaka
  - pk_majority_uyumsuzlugu olan vakalar (pid=4, pid=6 gibi)
  - Aksiyon: Yeni kisi olarak yeni kayit ac veya merge

- KIRLI B CRITICAL: 12 vaka
  - Ayni isim, cok legacy
  - Aksiyon: Birlestir (manuel onay)

- GHOST CRITICAL: 0 vaka
  - Cok isim variantli orphan kayitlar
  - Aksiyon: Manuel inceleme + sinif belirleme

### Oncelik 2: HIGH Risk (Otomatik Oneri ile)

- KIRLI A HIGH: 0 vaka
- GHOST HIGH: 9 vaka

### Oncelik 3: MEDIUM Risk

- Otomatik onerilebilir, dusuk risk

## 6. identity_map Stratejisi

Onerilen ilk seed:

```
AUTO ONAYLI (manuel onay GEREKSIZ):
  - TEMIZ 8 kayit  -> GuvenSkoru=100
  - KIRLI A LOW/MEDIUM 6 kayit  -> GuvenSkoru=80

MANUEL ONAY BEKLEMEDE:
  - KIRLI A HIGH/CRITICAL 2 kayit
  - KIRLI B 12 kayit
  - KIRLI C 1 kayit
  - GHOST 12 kayit
```

## 7. Risk Degerlendirmesi

**uretim_kayit kayit dagilimi:**

- TEMIZ guvenilir   : 449 (33.4%)
- KIRLI MEDIUM      : 526 (39.1%)
- KIRLI HIGH        : 0 (0.0%)
- KIRLI CRITICAL    : 144 (10.7%)
- GHOST orphan      : 227 (16.9%)
- **TOPLAM**        : 1346

**Karar onerisi:**

Veri kalitesi DUSUK. Once kapsamli manuel temizlik gerek.

---

**Olusturan:** D4.9 Legacy Analiz Script
**Cikti:** reports/D49_TEMIZ.csv, D49_KIRLI.csv, D49_GHOST.csv, D49_OZET.md
# EMIR_PROSES KAYNAK RECON RAPORU

**Tarih:** 2026-05-16
**Kapsam:** 5055 emir_proses tablosunun veri kaynağı, doluş mekanizması, CPS'e geçiş analizi
**Kural:** Sadece okuma. Hiçbir DB değişikliği yapılmadı.

---

## 1. ÖZET

5055 emir_proses tablosu **CPS personel-giris** modülünün **2 endpoint'inin** (`/emir/<no>` fallback, `/prosesler/<no>` ana) bağlı olduğu tek 5055 bağımlılık noktasıdır. Bu rapor:

- emir_proses'in **nasıl** dolduğunu
- proses_sablon ile **ilişkisini**
- Korgun ERP ile **ilişki olup olmadığını**
- CPS-native taşıma için **gerekli adımları**

belgeler.

---

## 2. 5055 DB GENEL DURUMU

5055 SQLite (`D:\Ortak\Solariz-ARGE\solariz.db`) sadece **7 tablo** içerir:

| Tablo | Kayıt | Açıklama |
|---|---|---|
| `emir_proses` | 2127 | Emir bazlı proses listesi |
| `pers_kullanici` | 27 | Personel (CPS'e import edildi) |
| `proses_sablon` | 18 | Şablon listesi |
| `sqlite_sequence` | 5 | SQLite internal |
| `uretim_kayit` | 1197 | Üretim kayıtları (CPS'e import edildi) |
| `usta_kullanici` | 3 | Usta listesi |
| `veri` | 1 | Genel config (?) |

**Önemli:** 5055'te `emir` veya `emirler` tablosu **YOK**. Yani 5055 emir bilgisini kendi tutmuyor — sadece emir_no referansı ile proses listesi tutuyor.

---

## 3. emir_proses TABLO ŞEMASI

```sql
CREATE TABLE emir_proses (
    id           INTEGER PRIMARY KEY,
    emir_no      INTEGER NOT NULL,            -- Korgun emir numarası referansı
    proses_adi   TEXT NOT NULL,               -- "gövde basıldı", "Rivet Takma" vs.
    limit_miktar INTEGER NULL DEFAULT 0,      -- Hedef adet
    olusturma    TEXT NULL DEFAULT datetime('now')
);
```

Sadece **5 kolon**. Şablon ID veya kaynak tracking YOK.

---

## 4. VERİ HACMİ ANALİZİ

- **Toplam:** 2127 satır
- **Unique emir_no:** 592 (her emirin ortalama 3.6 prosesi var)
- **Toplam unique proses_adi varyantı:** ~25-30
- **Aktif olarak yeni kayıt geliyor:** EVET, hala doluyor

### Son 15 Gün Doluş Tarihi

```
2026-05-12:  99 kayıt   ← AKTİF
2026-05-11:  85 kayıt
2026-05-08:  82 kayıt
2026-04-30: 112 kayıt
2026-04-28: 304 kayıt   ← pik (büyük sipariş grubu?)
2026-04-22: 270 kayıt   ← pik
```

**Yorum:** Düzenli olarak dolan canlı bir tablo. Manuel veya otomatik sürekli yeni emirler giriyor.

---

## 5. proses_sablon İLİŞKİSİ

### Şema

```sql
CREATE TABLE proses_sablon (
    id         INTEGER PRIMARY KEY,
    sablon_adi TEXT,
    prosesler  TEXT,                  -- VIRGULLU LISTE (JSON DEGIL)
    olusturma  TEXT
);
```

### 18 Şablon Listesi

| ID | Şablon | Proses Sayısı |
|---|---|---|
| 92 | tedii | 1 |
| 138 | lcw gövde ilerleme | 4 |
| 139 | lcw atkı ilerleme | 5 |
| 140 | lcw yezzy | 5 |
| 141 | ilham | 1 |
| 142 | ilham 2 | 3 |
| 143 | bahtiyar | 1 |
| 144 | esem atkı ilerleme | 2 |
| 145 | lcw gövde ilerleme frezeli | 5 |
| 146 | terda muya | 3 |
| 148 | terda 2 | 7 |
| 149 | ilham 3 | 2 |
| 150 | terda yzm | 6 |
| 151 | Eşek brz | 5 |
| 152 | Atkı Standart | 2 |
| 153 | Atkı LCW | 4 |
| 154 | Atkı Twigy | 3 |
| 155 | Atkı Esem | 1 |

### prosesler Kolonu Yapısı

**VIRGUL ile ayrılmış TEXT**, JSON değil. Örnek:

```
"gövde basıldı, gövde çapak alındı, gövde sayıldı, gövde aşagıya indi"
```

### Veri Kalitesi Sorunları

1. **Trailing comma'lar:** `... aşagıya indi,` (split sonrası boş eleman)
2. **Case karışıklığı:** `Gövde basıldı` vs `gövde basıldı`
3. **Türkçe karakter düzensiz:** `tambon` vs `tampon`, `dövde` vs `gövde`
4. **Typo'lar:** `paketleme yapılı`, `boy kotrolü`
5. **Personel adlı şablonlar:** `tedii`, `ilham`, `bahtiyar`, `terda 2` — geçici/test şablonlar
6. **Çift boşluk:** `dövde aşagı  indirme`

---

## 6. emir_proses Nasıl Doluyor?

### Hipotez (5055 server.py içinde)

```
1. Yönetici/sistem emir geldiğini bildiri (manuel veya Korgun sync)
2. Model/ürün tipine göre uygun proses_sablon seçilir
3. sablon.prosesler virgüllü liste split edilir
4. Her proses_adi için emir_proses INSERT yapılır
5. limit_miktar = emir miktarı (manuel veya Korgun'dan)
```

**Önemli:** emir_proses tablosunda **sablon_id veya kaynak referansı YOK**. Yani INSERT sonrası ilişki kaybediliyor.

### Doğrulama (Emir 110393 Örneği)

Emir 110393 prosesleri:
```
gövde basıldı
gövde çapak alındı
gövde sayıldı
gövde aşagıya indi
```

Bu **ID=138 'lcw gövde ilerleme'** şablonu ile **birebir eşleşiyor.**

---

## 7. KORGUN İLİŞKİSİ

5055 emir_proses tablosunda **Korgun referansı YOK**:
- ❌ Cari_Kart_Kod yok
- ❌ Korgun emir kodu yok
- ❌ Model_Kod yok

Sadece `emir_no` integer. Bu **muhtemelen** Korgun `Urt_Emir.EmirNo` ile aynı, ama 5055'te **referans yok**.

**Yorum:** 5055 ve Korgun arasında **doğrudan sync YOK**. emir_proses **manuel veya yarı-otomatik** dolduruluyor.

---

## 8. LIMIT_MIKTAR KAYNAK

```
emir_proses.limit_miktar INTEGER DEFAULT 0
```

Örneklerde:
```
emir 110393, hepsi 200
emir 110391, hepsi 480
emir 110389, hepsi 480
```

Bir emir için **tüm proseslerin limit_miktar'ı aynı** = emir miktarı.

**Olası kaynak:** Korgun `Urt_Emir.Miktar` veya manuel girilen değer.

---

## 9. CPS'E GEÇİŞ — VERİ MİMARİSİ

5055 emir_proses + proses_sablon yapısı CPS'e taşınmalı. Önerilen mimari:

```
CPS DB:
├─ sablon_master (yeniden tasarlanmış proses_sablon)
├─ sablon_proses (normalize: 1 satır = 1 proses)
├─ emir_alt_proses (eski emir_proses, schema iyileştirilmiş)
└─ proses_import_log (audit + tracking)
```

### Önemli — Migration İçin

- 2127 emir_proses kaydı + 18 sablon kayıtı **CPS'e import edilebilir**
- Veri kalitesi sorunları (case, trailing comma, typo) **normalize edilmeli**
- emir_proses ↔ sablon ilişkisi **şu an yok**, migration'da kuralla bağlanabilir (ad eşleştirmesi)

---

## 10. SONUÇ

| Soru | Cevap |
|---|---|
| emir_proses **manuel** mi otomatik mi? | Hibrit — 5055 server otomatik insert eder, ama tetikleme manuel olabilir |
| **5055 server** mı oluşturuyor? | Çok büyük olasılık EVET |
| **Korgun** ile ilgisi var mı? | Doğrudan YOK, emir_no referansı dolaylı |
| **proses_sablon** ilişkisi? | Var ama runtime kayıp (sablon_id tabloda yok) |
| **limit_miktar** nereden? | Muhtemelen manuel veya Korgun emir miktarı |
| Yeni emir geldiğinde **otomatik**? | EVET (günde 80-300 yeni kayıt geliyor) |

### Anahtar Sonuç

5055 emir_proses **basit bir şablonlama sistemi**. CPS'e taşınması:
- ✅ Mimari olarak basit (5 kolonlu tablo)
- ✅ Veri hacmi küçük (2127 kayıt)
- ⚠ Veri kalitesi temizlenmeli (case, typo)
- ⚠ Şablonla bağ kurulması gerek (ad eşleştirmesi)
- ⚠ Yeni emir geldiğinde tetiklenme nasıl olacak? (CPS'in kendi şablon motoru)

---

**Olusturan:** D5.1 emir_proses recon
**Sonraki belge:** `5055_KAPANIS_VE_PROSES_MOTORU_PLAN.md`

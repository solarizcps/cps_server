# 5055 KAPANIŞ VE CPS-NATIVE PROSES MOTORU GEÇİŞ PLANI

**Tarih:** 2026-05-16
**Hedef:** 5055 portu kapanmadan önce CPS-native proses motoru kurmak
**Kural:** Hiçbir mevcut çalışan akış bozulmayacak. Davranış değişimi disipline yapılacak.

---

## 1. MİMARİ DURUM ÖZETİ

```
Şimdi:                          Hedef:

┌─────────────┐                 ┌─────────────┐
│   Korgun    │                 │   Korgun    │ (Ana emir kaynağı)
│   (ERP)     │                 │   (ERP)     │
└──────┬──────┘                 └──────┬──────┘
       │                                │
       ▼                                ▼
┌─────────────┐                 ┌─────────────┐
│   5055      │                 │   CPS       │
│ emir_proses │ ───migration───▶│ emir_alt_   │ ◄── tek canlı sistem
│ proses_sablon│               │ proses +   │
│ (CANLI)     │                 │ sablon_*   │
└──────┬──────┘                 └─────────────┘
       │
       ▼
┌─────────────┐
│   CPS       │
│ personel-   │
│ giris (RT)  │
└─────────────┘
```

---

## 2. 5055 BAĞI KALAN DOSYALAR (FINAL)

D5.0 ve D5.1 tarama sonucu, **2 modülde** sadece **2 endpoint** 5055'e bağlı:

### Dosya: `app\modules\personel_giris\routes.py`

| Endpoint | Satır | 5055 Bağı | Risk |
|---|---|---|---|
| GET /emir/<no> | L227-237 | Fallback olarak `emir_proses MAX(limit)` okuyor | DÜŞÜK |
| GET /prosesler/<no> | L333-342 | Ana sorgu `emir_proses` okuyor | ORTA |

### Dosya: `app\modules\canli_saha\routes.py`

| Endpoint | Risk |
|---|---|
| Tüm endpoints | `uretim_kayit` 5055 DB'sinden okuyor (read-only bridge) |

**ÖNEMLİ:** Canli_saha modülü ayrıdır ve **port kapanmasında veri donar** ama servis çalışır. Bu modül **bilinçli olarak read-only bridge** olarak tasarlanmış. D5'in ana sorunu değil.

---

## 3. ENDPOINT BAZLI VERİ KAYNAĞI TABLOSU

`personel_giris\routes.py` 11 endpoint:

| Endpoint | Veri Kaynağı | 5055 Bağı | Risk | Not |
|---|---|---|---|---|
| GET / | - | YOK | ✅ OK | HTML render |
| GET /health | mock_data.db | YOK | ✅ OK | personel_kullanici COUNT |
| POST /login | mock_data.db | YOK | ✅ OK | personel_kullanici |
| GET /personeller | mock_data.db | YOK | ✅ OK | personel_kullanici |
| GET /dogrula/<pid> | mock_data.db | YOK | ✅ OK | personel_kullanici |
| GET /emir/<no> | mock_data.db + 5055 fallback | DOSYA | 🟡 DÜŞÜK | MAX(limit) fallback |
| GET /emir-toplam/<no> | mock_data.db | YOK | ✅ OK | uretim_kayit SUM |
| **GET /prosesler/<no>** | **5055 emir_proses + mock_data.db** | **DOSYA** | 🟠 ORTA | **Ana sorgu 5055'te** |
| POST /kaydet | mock_data.db | YOK | ✅ OK | uretim_kayit INSERT (en kritik!) |
| GET /gecmis/<pid> | mock_data.db | YOK | ✅ OK | - |
| GET /prim/<pid> | mock_data.db | YOK | ✅ OK | - |

**Sonuç:** 11 endpoint'ten **9'u TAMAMEN GÜVENLİ**, 2'si bağımlı.

---

## 4. 5055 KAPANINCA NE OLUR?

### Senaryo A: Port kapanır, dosya kalır (`D:\Ortak\Solariz-ARGE\solariz.db` durur)

```
✓ CPS auth çalışır
✓ Login çalışır
✓ Saha personeli üretim girer (POST /kaydet)
✓ Geçmiş/prim/raporlar çalışır
✓ Hedef ekranı çalışır
✓ Karar masası çalışır
⚠ /prosesler/<no> eski snapshot verisi gösterir
⚠ Yeni emirlerin prosesleri görünmez (5055 artık yazmıyor)
```

### Senaryo B: Port + dosya kapanır (yedek/Backup'a kaldırılır)

```
✓ CPS auth çalışır
✓ Login çalışır
✓ Saha personeli üretim girer (POST /kaydet)
⚠ /prosesler/<no> boş [] döner (try/except yakalıyor)
⚠ /emir/<no> fallback başarısız, sadece CPS'ten döner
```

**Kritik gözlem:** **Çökme YOK**. Sistem **çalışmaya devam eder**, sadece **proses listesi gösterilmez**.

---

## 5. GEÇİŞ FAZLARı (3 Faz)

### FAZ A — SNAPSHOT KORUMA (Şu An / 0-2 Gün)

**Amaç:** 5055 kapanır kapanmaz çökmeme garantisi.

**Aksiyon:**
1. Snapshot mekanizması zaten var (`DB_5055_SNAPSHOT` lokal)
2. `_5055_conn()` fonksiyonuna **uyarı log** ekle
3. `/prosesler/<no>` ve `/emir/<no>` endpoint'lerine **try/except sıkılaştırma**
4. UI'de küçük badge: "Bu liste 5055 snapshot'tan geliyor"

**Risk:** SIFIR (mevcut kod genişletmesi)
**Süre:** 30 dk
**Geri dönüş:** Anında

### FAZ B — CPS-NATIVE OKUMA (3-7 Gün)

**Amaç:** emir_proses verisini CPS'e taşı, prioritize et.

**Aksiyon:**
1. CPS'e `emir_alt_proses` + `sablon_master` + `sablon_proses` tabloları ekle
2. 5055'ten **bir kerelik migration** (2127 + 18 kayıt)
3. `/prosesler/<no>` davranışı:
   - **Önce CPS emir_alt_proses oku**
   - Bulamazsa **5055 snapshot fallback**
4. `/emir/<no>` aynı şekilde

**Risk:** DÜŞÜK
**Süre:** 2-3 saat
**Geri dönüş:** Snapshot DB ile rollback mümkün

### FAZ C — CPS-NATIVE ŞABLON MOTORU (1-2 Hafta)

**Amaç:** Yeni emirler için CPS kendi proses listesini üretsin.

**Aksiyon:**
1. CPS'te şablon yönetim UI (`/yonetim/sablon`)
2. Korgun'dan yeni emir geldiğinde **CPS otomatik şablon uygular** ve emir_alt_proses üretir
3. 5055 fallback **kapatılır**
4. canli_saha modülü için ayrı plan (bu modül zaten read-only)

**Risk:** ORTA (yeni motor mantığı + UI)
**Süre:** 1-2 hafta
**Geri dönüş:** Faz B durumuna dönüş (snapshot fallback aç)

---

## 6. ÖNERİLEN TABLO TASARIMI

### Tablo 1: `sablon_master`

```sql
CREATE TABLE sablon_master (
    Id              INTEGER PRIMARY KEY AUTOINCREMENT,
    SablonAdi       TEXT NOT NULL,
    Kategori        TEXT,                  -- 'govde', 'atki', 'paketleme', vs.
    Aciklama        TEXT,
    Aktif           INTEGER DEFAULT 1,
    LegacyId        INTEGER,                -- proses_sablon.id eski referans
    OlusturmaTarih  TEXT DEFAULT CURRENT_TIMESTAMP,
    GuncellemeTarih TEXT
);
```

### Tablo 2: `sablon_proses`

```sql
CREATE TABLE sablon_proses (
    Id              INTEGER PRIMARY KEY AUTOINCREMENT,
    SablonId        INTEGER NOT NULL,
    ProsesAdi       TEXT NOT NULL,         -- "gövde basıldı" gibi standart ad
    ProsesSira      INTEGER NOT NULL,
    LimitKatsayi    REAL DEFAULT 1.0,      -- emir_miktar × katsayi = proses limiti
    ProsesTipi      TEXT,                  -- 'govde', 'atki', 'silme', vs.
    Aktif           INTEGER DEFAULT 1,
    OlusturmaTarih  TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (SablonId) REFERENCES sablon_master(Id)
);
```

### Tablo 3: `emir_alt_proses` (5055 emir_proses CPS-native)

```sql
CREATE TABLE emir_alt_proses (
    Id                INTEGER PRIMARY KEY AUTOINCREMENT,
    EmirNo            INTEGER NOT NULL,
    SablonId          INTEGER,                  -- hangi sablondan geldi (NULL = manuel)
    ProsesAdi         TEXT NOT NULL,
    ProsesSira        INTEGER,
    HedefMiktar       INTEGER DEFAULT 0,        -- eski limit_miktar
    Durum             TEXT DEFAULT 'aktif',     -- 'aktif', 'tamamlandi', 'iptal'
    Kaynak            TEXT,                     -- 'LEGACY_5055', 'CPS_OTOMATIK', 'MANUEL'
    LegacyEmirProsesId INTEGER,                  -- 5055 emir_proses.id eski referans
    OlusturmaTarih    TEXT DEFAULT CURRENT_TIMESTAMP,
    GuncellemeTarih   TEXT,
    FOREIGN KEY (SablonId) REFERENCES sablon_master(Id)
);

CREATE INDEX idx_eap_emir ON emir_alt_proses(EmirNo);
CREATE INDEX idx_eap_durum ON emir_alt_proses(Durum);
CREATE INDEX idx_eap_legacy ON emir_alt_proses(LegacyEmirProsesId);
```

### Tablo 4: `proses_import_log` (Audit)

```sql
CREATE TABLE proses_import_log (
    Id              INTEGER PRIMARY KEY AUTOINCREMENT,
    Kaynak          TEXT NOT NULL,        -- '5055_emir_proses', '5055_proses_sablon', 'manuel'
    LegacyId        INTEGER,
    EmirNo          INTEGER,
    Status          TEXT,                  -- 'OK', 'SKIP_DUPLICATE', 'HATA'
    Mesaj           TEXT,
    OlusturmaTarih  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pil_kaynak ON proses_import_log(Kaynak);
CREATE INDEX idx_pil_emir ON proses_import_log(EmirNo);
```

---

## 7. VERİ NORMALIZASYON KURALLARI

5055 → CPS migration sırasında uygulanır:

### 7.1 proses_sablon Normalizasyon

| Sorun | Çözüm |
|---|---|
| Trailing comma | `strip(',').strip()` her item |
| Çift boşluk | `re.sub(r'\s+', ' ', ad)` |
| Case karışık | Şimdilik koru (yönetici UI'den düzeltir) |
| Personel adlı şablonlar (`tedii`, `ilham`, `bahtiyar`) | `Aktif=0` işaretle, gizle |
| Typo'lar (`tambon`, `paketleme yapılı`) | Şimdilik koru, Notlar kolonuna işaret koy |

### 7.2 Kategori Tahmini (Auto-fill)

```python
def kategori_tahmin(sablon_adi, prosesler):
    text = (sablon_adi + ' ' + ' '.join(prosesler)).lower()
    if 'gövde' in text or 'govde' in text: return 'govde'
    if 'atkı' in text or 'atki' in text: return 'atki'
    if 'paketleme' in text: return 'paketleme'
    if 'rivet' in text: return 'rivet'
    return 'genel'
```

### 7.3 emir_alt_proses Import

Her 5055 emir_proses kaydı için:
```python
INSERT INTO emir_alt_proses (
    EmirNo, ProsesAdi, HedefMiktar, Kaynak, LegacyEmirProsesId, OlusturmaTarih
) VALUES (
    eski.emir_no, eski.proses_adi.strip(), eski.limit_miktar,
    'LEGACY_5055', eski.id, eski.olusturma
)
```

**SablonId** başlangıçta NULL, sonra batch update ile ad eşleştirmesi ile doldurulabilir.

---

## 8. ROLLBACK PLANI

### Faz A Rollback

Hiçbir DB değişimi yok. Sadece log/UI eklemesi → kolayca geri alınır.

### Faz B Rollback

```sql
DROP TABLE proses_import_log;
DROP TABLE emir_alt_proses;
DROP TABLE sablon_proses;
DROP TABLE sablon_master;
```

Kod tarafında: `/prosesler/<no>` sadece 5055 snapshot'tan okumaya geri döner (eski hâl).

### Faz C Rollback

`5055 fallback` kapatılan kod açılır:
```python
# Comment uncomment
if not rows_from_cps:
    rows_from_cps = oku_5055_fallback(emir_no)
```

---

## 9. RİSK LİSTESİ

| # | Risk | Şiddet | Önlem |
|---|---|---|---|
| 1 | 5055 portu kapansa /prosesler endpoint 5xx döndürür | DÜŞÜK | Try/except mevcut, [] döner |
| 2 | Snapshot DB de kaybolur (dosya silinir) | DÜŞÜK | Yedek var, snapshot lokalde |
| 3 | CPS emir_alt_proses migration sırasında duplicate | ORTA | UNIQUE(EmirNo, ProsesAdi) constraint |
| 4 | Şablon ad eşleştirme yanlış olur | ORTA | Manuel onay UI'den sonra |
| 5 | Yeni emirler CPS-native şablon motoru gelene kadar 5055'siz prosessiz kalır | YÜKSEK | Faz C öncesi geçici çözüm |
| 6 | Korgun'dan emir geldiğinde tetikleme yok | YÜKSEK | Faz C'de çözülür |
| 7 | uretim_kayit'tan eski 5055 import edilen kayıtlar nasıl etkilenir? | DÜŞÜK | Dokunulmaz (sadece referans) |
| 8 | Yönetici UI'de şablon düzeltme yapamazsa | ORTA | Faz C UI sonra gelir, manuel SQL geçici |

---

## 10. ÖNERİLEN ZAMAN ÇİZELGESİ

| Faz | Süre | Başlangıç | Bitiş Beklenen |
|---|---|---|---|
| A — Snapshot koruma | 30 dk | Bugün | Bugün |
| B — CPS native okuma | 2-3 saat | Yarın | 18 May |
| C — Şablon motoru | 1-2 hafta | 19 May | 30 May |

**5055 portunun kapanması:** Hafta sonu (~22-23 May) güvenli görünüyor.

---

**Olusturan:** D5.1 5055 Kapanış Planı
**Sonraki belge:** `CPS_NATIVE_PROSES_MOTORU_MIGRATION_PLAN.md`

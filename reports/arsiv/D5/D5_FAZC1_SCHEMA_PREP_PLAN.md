# D5 FAZ C.1 — SCHEMA PREP PLAN

**Tarih:** 2026-05-16 16:16
**Sprint:** D5 Faz C.1 — emir_alt_proses sablon_id FK hazırlığı
**Kapsam:** Sadece şema değişikliği. Kod davranışı değişmez. Trigger yok. UI yok.
**Durum:** RECON tamamlandı, plan hazır

---

## 1. ÖZET

D5 Faz C'nin **ilk alt bölümü**. Amaç: `emir_alt_proses` tablosuna `sablon_id INTEGER` kolonu eklemek ve mevcut `sablon:*` kaynaklı kayıtlar için backfill yapmak.

**Davranış değişimi: SIFIR.** Sadece şema hazırlığı.

---

## 2. MEVCUT ŞEMA (Recon Sonucu)

### 2.1 emir_alt_proses (12 kolon, 2273 kayıt)

```
id              INTEGER PK
emir_no         TEXT NOT NULL
proses_adi      TEXT NOT NULL
hedef_adet      INTEGER NULL default=0
aktif           INTEGER NULL default=1
siralama        INTEGER NULL default=0
kaynak          TEXT NULL default='manuel'
olusturan_id    TEXT NULL
olusturan_ad    TEXT NULL
created_at      TEXT NULL
updated_at      TEXT NULL
legacy_id       INTEGER NULL                ← D5 Faz B eklendi
```

**Index'ler (3):**
- `idx_eap_legacy` [legacy_id, kaynak]
- `idx_eap_aktif` [aktif]
- `idx_eap_emir` [emir_no]

### 2.2 sablon (5 kayıt)

```
ID=1 'Atki LCW'         (2026-04-28)  aktif=1
ID=2 'İlham'            (2026-05-11)  aktif=0
ID=3 'Aşağı iş indirme' (2026-05-12)  aktif=1
ID=4 'Lcw atkı'         (2026-05-15)  aktif=1
ID=5 'Esem'             (2026-05-16)  aktif=1
```

### 2.3 sablon_proses (14 kayıt)

5 şablon için toplam 14 proses tanımı (sablon_id + siralama + proses_adi).

---

## 3. KAYNAK DAĞILIM (emir_alt_proses)

| kaynak | cnt | aktif | hedef0 |
|---|---|---|---|
| 5055_IMPORT | 2127 | 2127 | 3 |
| sablon:Lcw atkı | 65 | 65 | 65 |
| sablon:Atki LCW | 30 | 16 | 30 |
| sablon:Esem | 23 | 23 | 23 |
| sablon:Aşağı iş indirme | 22 | 22 | 22 |
| manuel | 6 | 0 | 6 |
| **TOPLAM** | **2273** | **2253** | **149** |

---

## 4. SABLON EŞLEŞME MAPPING

| emir_alt_proses.kaynak | sablon.id | sablon.sablon_adi | Kayıt |
|---|---|---|---|
| `sablon:Lcw atkı` | 4 | Lcw atkı | 65 |
| `sablon:Atki LCW` | 1 | Atki LCW | 30 |
| `sablon:Esem` | 5 | Esem | 23 |
| `sablon:Aşağı iş indirme` | 3 | Aşağı iş indirme | 22 |
| | | **TOPLAM** | **140** |

**Eşleşme:** %100 (4/4)

---

## 5. ÖNERILEN ALTER (Migration)

### 5.1 SQL Adımları

```sql
-- ADIM 1: Yeni kolon (NULLABLE, FK constraint YOK)
ALTER TABLE emir_alt_proses ADD COLUMN sablon_id INTEGER;

-- ADIM 2: Index (lookup performansı)
CREATE INDEX IF NOT EXISTS idx_eap_sablon_id 
ON emir_alt_proses(sablon_id);

-- ADIM 3: Backfill (mevcut sablon:* kayıtları için)
UPDATE emir_alt_proses
   SET sablon_id = (
       SELECT s.id FROM sablon s
       WHERE LOWER(s.sablon_adi) = LOWER(REPLACE(emir_alt_proses.kaynak, 'sablon:', ''))
   )
 WHERE kaynak LIKE 'sablon:%'
   AND sablon_id IS NULL;
```

### 5.2 Beklenen Sonuç

```
Önceki: 12 kolon, 3 index, 2273 kayıt (sablon_id YOK)
Sonraki: 13 kolon, 4 index, 2273 kayıt
  sablon_id dolu  : 140 kayıt (sablon:*)
  sablon_id NULL  : 2133 kayıt (5055_IMPORT 2127 + manuel 6)
```

### 5.3 FK Constraint Stratejisi

**FAZ C.1'de FK CONSTRAINT EKLENMİYOR.** Sebepler:
- SQLite default FK enforcement KAPALI (`PRAGMA foreign_keys = 0`)
- ALTER TABLE ile FK ekleme zor (tablo yeniden oluşturma gerek)
- Mevcut 5055_IMPORT kayıtları için sablon_id zaten NULL
- Faz C ileri aşamada (otomatik trigger sonrası) FK düşünülebilir

**Bu Faz C.1 = sadece nullable INTEGER kolon. FK uygulanması KASITLI ÇIKARILDI.**

---

## 6. RİSK ANALİZİ

### 6.1 Risk Matrisi

| Risk Faktörü | Değerlendirme | Risk |
|---|---|---|
| Canlı üretim etkisi | uretim_kayit DOKUNULMAZ | **DÜŞÜK** |
| Mevcut sorgular | 4/4 test PASS, NULL kolon eski sorguları etkilemez | **DÜŞÜK** |
| CPS_NATIVE endpoint | WHERE/SELECT yapıları aynı | **DÜŞÜK** |
| /prosesler JSON | Dönen yapı değişmez | **DÜŞÜK** |
| Saha personeli | /kaydet kolona dokunmaz | **YOK** |
| FK PRAGMA | Kapalı kalacak | **YOK** (kasıtlı) |
| Disk alanı | ~10-20 KB artış | **YOK** |
| Tablo lock süresi | <1 sn | **YOK** |
| Rollback (SQLite DROP COLUMN) | SQLite native desteği sınırlı | **ORTA** |

### 6.2 Genel Risk Seviyesi: **DÜŞÜK**

---

## 7. ROLLBACK STRATEJİSİ

### Yol A — Hiç Yapma (Önerim)
- `sablon_id` kolonu NULLABLE
- Eski sorgular kolonu görmezden gelir
- Sorun olursa kolon kalır ama kullanılmaz

### Yol B — Snapshot Restore
- `STABLE_D5_FAZC1_ONCESI_SCHEMA_PREP_20260516_161613` snapshot'tan `mock_data.db` kopyala
- Üretim kesintisi ~30 saniye
- Saha personeli o ara girdiği veriler kaybolur (canlı kayıt)

### Yol C — Tabloyu Yeniden Oluştur
- `CREATE new_table → INSERT data → DROP old → RENAME`
- En güvenli, en karmaşık, ~2-3 dakika kesinti

**Önerim: Yol A.** Risk düşük olduğu için snapshot restore'a gerek kalmaz.

---

## 8. MIGRATION ADIM SIRASI

```
1. ✓ Snapshot alındı: STABLE_D5_FAZC1_ONCESI_SCHEMA_PREP_20260516_161613
2. ⏳ DB yedek: mock_data.db.YEDEK_FAZC1_<ts>
3. ⏳ ALTER TABLE (nullable kolon)
4. ⏳ CREATE INDEX
5. ⏳ Idempotent kontrol: sablon_id zaten varsa skip
6. ⏳ UPDATE backfill (140 sablon:* kayıt için)
7. ⏳ Doğrulama (140 dolu, 2133 NULL)
8. ⏳ Test sorgular (4 test sorgu hâlâ çalışıyor mu?)
9. ⏳ Endpoint test (/prosesler/110393 hâlâ CPS_NATIVE mi?)
10. ⏳ Rapor yazma
11. ⏳ Snapshot: STABLE_D5_FAZC1_SCHEMA_PREP_OK_<ts>
```

---

## 9. ETKİLENEN/ETKİLENMEYECEK ALANLAR

### Etkilenecek

- `emir_alt_proses` şema (1 kolon + 1 index)
- DB boyutu (~10-20 KB)

### Etkilenmeyecek

- `routes.py` (kod hiç değişmez)
- `/prosesler/<no>` endpoint davranışı
- `/emir/<no>` endpoint davranışı
- `/kaydet` endpoint
- Login akışı
- `uretim_kayit` tablosu
- `sablon` tablosu
- `sablon_proses` tablosu
- 5055 fallback (D5 Faz A korundu)
- D5 Faz B CPS-first mantığı
- Saha personeli üretim akışı

---

## 10. SON KARAR

```
D5 FAZ C.1:
──────────────────────────────────────────
  patch gerekli mi      : EVET
  risk seviyesi         : DÜŞÜK
  migration tipi        : ALTER (1 kolon + 1 index + 1 UPDATE)
  rollback kolay mı     : EVET (Yol A: hiç yapma; Yol B: snapshot)
  patch'e hazır mı      : EVET
──────────────────────────────────────────
```

---

## 11. ONAY GEREKLİ — 3 Soru

### Soru 1: Backfill Kapsamı
- **A:** Sadece sablon:* kayıtları için sablon_id doldur (140 kayıt) ← **Önerim**
- **B:** Hiç backfill yapma, kolon eklensin, doldurma sonra

### Soru 2: FK Constraint
- **A:** FK constraint YOK (sadece INTEGER kolon) ← **Önerim**
- **B:** FK constraint ekle (tablo yeniden oluştur, riskli)

### Soru 3: Migration Stratejisi
- **A:** ALTER + INDEX + UPDATE — Atomic Python script (Faz B gibi)
- **B:** Manuel SQL adım adım

---

## 12. SONRAKİ ADIMLAR (Faz C bütünü)

```
✓ C.1  ALTER sablon_id FK             (BU SPRINT)
⏳ C.2  sablon_eslesme tablosu kurulumu
⏳ C.3  Yönetim UI - sablon liste
⏳ C.4  Yönetim UI - sablon CRUD
⏳ C.5  Otomatik trigger fonksiyonu (Korgun → CPS)
⏳ C.6  Scheduled task entegre
⏳ C.7  hedef_adet vardiya kuralı
⏳ C.8  USE_CPS_NATIVE_PROSES = True (5055 fallback kapatma)
⏳ C.9  Test + doğrulama
```

---

**Oluşturan:** D5 Faz C.1 Schema Prep Plan
**Snapshot:** STABLE_D5_FAZC1_ONCESI_SCHEMA_PREP_20260516_161613
**Önceki belgeler:**
- D5_FAZC_RECON_DEVAM.md
- D5_FAZB_FINAL_VERIFY.md
- D5_FAZB_MIGRATION_RAPORU.md

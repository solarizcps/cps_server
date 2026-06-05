# D6.0.1 PATCH-A - proses_alias Migration Plani

**Tarih:** 18.05.2026 10:52
**Sprint:** D6.0.1 - PATCH-A (Migration)
**Durum:** STAGING + DRY-RUN BASARILI, ATOMIC MOVE BEKLENIYOR

---

## Amac

CPS'te proses normalize altyapisinin ILK adimi. Saha varyantlarini standart koda baglayan yeni tablo.

**Sprint kapsamliligi:** SADECE altyapi - tablo + seed + schema_migrations kaydi.
**Hicbir runtime hook YOK. Hicbir UPDATE YOK. Hicbir mevcut tablo dokunulmaz.**

## Migration script

**Dosya:** app/migrations/010_proses_alias.py
**Boyut:** 7495 byte (staging dogrulandi)
**Idempotent:** EVET (CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE)

### Yeni tablo

\\\sql
CREATE TABLE IF NOT EXISTS proses_alias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saha_adi TEXT UNIQUE NOT NULL,
    standart_kod TEXT NOT NULL,
    standart_adi TEXT NOT NULL,
    kategori TEXT,
    guven_skoru INTEGER DEFAULT 0,
    karar_kaynak TEXT,
    onayli_mi INTEGER DEFAULT 0,
    olusturma TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pa_saha ON proses_alias(saha_adi);
CREATE INDEX idx_pa_kod ON proses_alias(standart_kod);
CREATE INDEX idx_pa_onayli ON proses_alias(onayli_mi);
\\\

### Seed - 15 kayit (6 typo grubu)

| Standart kod | Standart adi | Kategori | Varyant sayisi |
|--------------|--------------|----------|----------------|
| 60 | Capak | ATKI | 2 |
| 70 | Atki Silme | ATKI | 3 |
| 71 | Atki Rivet Takma | ATKI | 3 |
| 72 | Atki Tampon Baski | ATKI | 3 |
| 80 | Govde Baski | GOVDE | 2 |
| 90 | Asagi Is Indirme | TRANSFER | 2 |

Hepsi: guven=100, onayli=1, karar_kaynak='auto_typo'

### schema_migrations kaydi

\\\
version='010'
uygulama_zamani=DEFAULT (datetime now)
aciklama='010_proses_alias - D6.0.1 ...'
\\\

## STAGING DOGRULAMASI (yapildi)

| Test | Sonuc |
|------|-------|
| AST | PASS |
| py_compile | PASS |
| DRY-RUN 1. cagri | 15 INSERT, schema_migrations 1 kayit |
| DRY-RUN 2. cagri (idempotent) | 0 INSERT, schema_migrations hala 1 kayit |
| Canli DB temizliği | DOKUNULMADI |
| 3 dosya hash | korundu |
| /health | 200 |

## ATOMIC MOVE PLANI

1. **YEDEK al:** mock_data.db.YEDEK_D6_0_1_PATCH_A_<ts>
2. **Migration kopyala:** staging/010_proses_alias.py -> app/migrations/010_proses_alias.py
3. **Migration calistir:** python app/migrations/010_proses_alias.py
4. **Verify:**
   - canli DB'de proses_alias var
   - 15 kayit
   - schema_migrations[010] 1 kayit
5. **Smoke test:**
   - /health 200
   - 3 dosya hash korundu
   - 110393 BIREBIR korundu
   - 111015 duplicate guard OK
   - uretim_kayit dokunulmadi

## ROLLBACK

\\\powershell
# Yedek geri yukle
Copy-Item app\mock_data.db.YEDEK_D6_0_1_PATCH_A_<ts> app\mock_data.db -Force
# VEYA SQL ile
sqlite> DROP TABLE proses_alias;
sqlite> DELETE FROM schema_migrations WHERE version='010';
\\\

## RISK SEVIYESI

DUSUK (1/10)

- Yeni tablo (mevcut tablolara dokunmuyor)
- INSERT only, UPDATE/DELETE yok
- Idempotent (yeniden calistirilabilir)
- Runtime hook yok
- FLAG'a dokunmuyor
- Saha endpoint'leri etkilenmez
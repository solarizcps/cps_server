# D6.0.1 PATCH-A - proses_alias VERIFY RAPORU

**Tarih:** 18.05.2026 10:56
**Sprint:** D6.0.1 PATCH-A - proses_alias migration
**Sonuc:** TAMAMLANDI

## Yapilan

- Migration: app/migrations/010_proses_alias.py (7495 byte)
- Yedek: app\mock_data.db.YEDEK_D6_0_1_PATCH_A_20260518_105653
- proses_alias tablosu olusturuldu (9 kolon + 3 index)
- 15 seed kayit (6 typo grubu, hepsi guven=100, onayli=1, kaynak='auto_typo')
- schema_migrations[010] kaydedildi

## Standart kod dagilim

| Kod | Standart adi | Kategori | Varyant |
|-----|--------------|----------|---------|
| 60 | Capak | ATKI | 2 |
| 70 | Atki Silme | ATKI | 3 |
| 71 | Atki Rivet Takma | ATKI | 3 |
| 72 | Atki Tampon Baski | ATKI | 3 |
| 80 | Govde Baski | GOVDE | 2 |
| 90 | Asagi Is Indirme | TRANSFER | 2 |

Toplam: 15 varyant, 6 standart kod, 3 kategori.

## Idempotency

Migration 2. kez canli DB'de calistirildi:
- INSERT OR IGNORE -> 0 yeni kayit
- schema_migrations[010] hala 1 kayit
- proses_alias hala 15 kayit

## Runtime davranis korundu

- hedef/routes.py: 7EAC892167AFEAD1 (P6)
- config.py: 6CD32DCB1E1B3EBE (C.8)
- personel_giris/routes.py: F6D1953CC0243B0C (P4)
- /health: 200
- /prosesler/110393: BIREBIR (B9B1C8CC6C646AD5)
- /prosesler/111015: CPS_NATIVE (duplicate guard OK)
- uretim_kayit: dokunulmadi
- emir_alt_proses: dokunulmadi

## Rollback

\\\powershell
Copy-Item "app\mock_data.db.YEDEK_D6_0_1_PATCH_A_20260518_105653" "app\mock_data.db" -Force
\\\

VEYA SQL:
\\\sql
DROP TABLE IF EXISTS proses_alias;
DELETE FROM schema_migrations WHERE version='010';
\\\

## NEXT

- PATCH-B: yonetim/routes.py - GET /yonetim/proses-alias/liste (read-only JSON)
- PATCH-C: yonetim/proses_alias.html (mini UI)
- PATCH-D: yonetim/routes.py - GET /yonetim/proses-alias (render UI)
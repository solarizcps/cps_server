-- ============================================================
-- 042_uretim_emir_ilerleme.sql
-- CPS Uretim Emir Ilerleme - FAZ 1C Ara Kayit Altyapisi
--
-- Yapilan:
--   1. uretim_kayit_personel tablosu olusturulur
--   2. korgun_personel_eslestirme tablosu olusturulur
--
-- NOT: uretim_kayit ALTER TABLE kolonlari Python runner'da yapilir
--      (SQLite ALTER TABLE IF NOT EXISTS yok, kolon_var_mi ile guard edilir)
--
-- IDEMPOTENT:
--   - schema_migrations'da version='042' varsa runner skip eder
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
-- ============================================================

BEGIN TRANSACTION;

-- ============================================================
-- uretim_kayit_personel
-- Ekip/personel miktar kirilimi
-- Ornek: Halil kapatti, is yapanlar Ayse 100 + Fatma 200 + Bekleyen 180
-- ============================================================
CREATE TABLE IF NOT EXISTS uretim_kayit_personel (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kayit_id        INTEGER NOT NULL,
    personel_id     INTEGER,
    personel_ad     TEXT,
    miktar          REAL    DEFAULT 0,
    kaynak          TEXT    DEFAULT 'CPS',
    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_ukp_kayit_id
    ON uretim_kayit_personel(kayit_id);

CREATE INDEX IF NOT EXISTS idx_ukp_personel_id
    ON uretim_kayit_personel(personel_id);


-- ============================================================
-- korgun_personel_eslestirme
-- CPS kullanici/personel ile Korgun Personel kodu + insUN eslesmesi
-- Ornek: cps_kullanici_adi='halil' -> korgun_insUN='Halil', korgun_personel_kodu='30013'
-- ============================================================
CREATE TABLE IF NOT EXISTS korgun_personel_eslestirme (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    cps_personel_id         INTEGER,
    cps_kullanici_adi       TEXT,
    korgun_personel_kodu    TEXT,
    korgun_insUN            TEXT,
    aktif                   INTEGER DEFAULT 1,
    created_at              TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_kpe_cps_personel
    ON korgun_personel_eslestirme(cps_personel_id);

CREATE INDEX IF NOT EXISTS idx_kpe_cps_kullanici
    ON korgun_personel_eslestirme(cps_kullanici_adi);

CREATE INDEX IF NOT EXISTS idx_kpe_korgun_kod
    ON korgun_personel_eslestirme(korgun_personel_kodu);


-- ============================================================
-- MIGRATION KAYDI
-- ============================================================
INSERT OR IGNORE INTO schema_migrations (version, uygulama_zamani, aciklama)
    VALUES (
        '042',
        datetime('now', 'localtime'),
        '042_uretim_emir_ilerleme - FAZ1C: uretim_kayit_personel + korgun_personel_eslestirme tablolari'
    );

COMMIT;

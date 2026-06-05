-- ============================================================
-- 003_bildirim_log.sql
-- mock_data.db'ye bildirim_log tablosunu ekler.
-- ============================================================
--
-- Sema: solariz_dev.db'deki bildirim_log'un BIREBIR ayni hali,
-- ANCAK rol CHECK constraint'i KALDIRILDI.
--
-- Sebep:
--   Eski CHECK: rol IN ('personel','usta','kalite','admin','yonetim')
--   Yeni roller (CPS Tasks modulu): planlama, satin_alma, grafik, finans, depo
--   Constraint'i koruyacak olsak yeni rollerle INSERT patlardi.
--   Esnek tutuyoruz - rol degerleri uygulama katmaninda yonetilir.
--
-- IDEMPOTENT:
--   - schema_migrations'da version='003' varsa Python runner skip eder
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - INSERT OR IGNORE schema_migrations
-- ============================================================

BEGIN TRANSACTION;

-- ============================================================
-- bildirim_log
-- ============================================================
CREATE TABLE IF NOT EXISTS bildirim_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_id        INTEGER NOT NULL,
    rol                 TEXT    NOT NULL,           -- CHECK YOK (uygulama yonetir)
    tip                 TEXT    NOT NULL,
    mesaj               TEXT    NOT NULL,
    veri_json           TEXT,
    gonderim_zamani     TEXT DEFAULT (datetime('now')),
    okundu_mu           INTEGER DEFAULT 0,
    okundu_zamani       TEXT,
    push_gonderildi_mi  INTEGER DEFAULT 0
);

-- Indexler (legacy ile ayni isimler)
CREATE INDEX IF NOT EXISTS idx_bildirim_kullanici
    ON bildirim_log(kullanici_id, okundu_mu);

CREATE INDEX IF NOT EXISTS idx_bildirim_zaman
    ON bildirim_log(gonderim_zamani);

-- Ek (Tasks modulune ozgu): tip + zaman filtresi icin
CREATE INDEX IF NOT EXISTS idx_bildirim_tip
    ON bildirim_log(tip, gonderim_zamani DESC);


-- ============================================================
-- MIGRATION KAYDI
-- ============================================================
INSERT OR IGNORE INTO schema_migrations (version, uygulama_zamani, aciklama)
    VALUES (
        '003',
        datetime('now', 'localtime'),
        '003_bildirim_log.sql - bildirim_log tablosu (mock_data.db, CHECK constraint olmadan)'
    );


COMMIT;

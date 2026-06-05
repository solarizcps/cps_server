-- ============================================================
-- CPS DEV - MIGRATION 004 - GLOBAL OVERLAY DESTEK
-- ============================================================
-- Faz 3: Global task overlay sistemi icin DB genislemesi
--
-- Bu migration:
--   1. bildirim_log'a 3 yeni kolon (snooze_until, dismiss_count, last_shown_at)
--   2. Performans icin yeni index (idx_bildirim_pending)
--   3. task_settings'e 6 yeni overlay ayari
--
-- IDEMPOTENT: Tekrar calistirilabilir, zarar vermez.
-- schema_migrations tablosu ile takip edilir.
-- ============================================================

BEGIN TRANSACTION;

-- ============================================================
-- MIGRATION CHECK (idempotent)
-- ============================================================
-- Eger bu migration daha onceden uygulanmissa, hicbir sey yapma.
-- (Asagidaki INSERT OR IGNORE'lar zaten idempotent ama emin olalim)

-- schema_migrations tablosu yoksa olustur (002'de olusmus olmali ama guvenlik)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);


-- ============================================================
-- 1) bildirim_log'a yeni kolonlar
-- ============================================================
-- SQLite'da ALTER TABLE ADD COLUMN, kolon zaten varsa hata verir.
-- Bu nedenle PRAGMA table_info kontrol edilir, sadece yoksa eklenir.
-- Ama saf SQL ile bunu yapamayiz - migration runner Python tarafinda
-- her ALTER'i ayri try/except ile sarmalayacak.
--
-- Bu dosyanin uygulanma yolu: migrations/run_migration.py 004 calistirir,
-- her ALTER statement'i ayri ayri try-except'le calistirir.

ALTER TABLE bildirim_log ADD COLUMN snooze_until TEXT NULL;
ALTER TABLE bildirim_log ADD COLUMN dismiss_count INTEGER DEFAULT 0;
ALTER TABLE bildirim_log ADD COLUMN last_shown_at TEXT NULL;


-- ============================================================
-- 2) Performans index'i
-- ============================================================
-- Pending bildirimleri hizli cekmek icin compound index
-- Sorgu: WHERE kullanici_id=? AND okundu_mu=0 AND (snooze_until IS NULL OR snooze_until <= NOW)

CREATE INDEX IF NOT EXISTS idx_bildirim_pending
    ON bildirim_log(kullanici_id, okundu_mu, snooze_until);


-- ============================================================
-- 3) task_settings'e 6 yeni overlay ayari
-- ============================================================
-- INSERT OR IGNORE: Anahtar zaten varsa atla (idempotent)

INSERT OR IGNORE INTO task_settings (anahtar, deger, aciklama) VALUES
    ('overlay_polling_seconds',        '30',  'Overlay polling araligi - sayfa aktif (saniye)'),
    ('overlay_hidden_polling_seconds', '120', 'Overlay polling araligi - sayfa hidden (saniye)'),
    ('overlay_critical_repeat_min',    '15',  'Kritik bildirim tekrar araligi (dakika)'),
    ('overlay_normal_repeat_min',      '60',  'Normal bildirim tekrar araligi (dakika)'),
    ('overlay_overdue_repeat_min',     '30',  'Geciken gorev bildirim tekrar araligi (dakika)'),
    ('overlay_sound_enabled',          '1',   'Bildirim sesi aktif mi (0=hayir, 1=evet)');


-- ============================================================
-- 4) Migration kayit
-- ============================================================
INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES ('004_overlay', datetime('now', 'localtime'));


COMMIT;

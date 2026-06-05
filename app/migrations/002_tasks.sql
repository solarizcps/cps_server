-- ============================================================
-- 002_tasks.sql  (v2 - idempotent, guvenli)
-- CPS GOREV MODULU - FAZ 1 CEKIRDEK DB MIGRATION
-- ============================================================
--
-- Tablolar (5):
--   tasks_users      bagimsiz kullanici havuzu (UNIQUE kullanici_adi)
--   tasks            ana gorev tablosu (33 kolon)
--   task_files       dosya ekleri (Faz 2'de UI)
--   task_logs        audit history (her aksiyon)
--   task_settings    kullanici/departman ayarlari
--
-- Bilirim:        mevcut bildirim_log kullanilir (yeni tablo YOK)
-- Eski tablolar:  DOKUNULMAZ (usta_gorevleri, bildirim_log, vb.)
-- DB:             mock_data.db (Config.MOCK_DB_PATH)
--
-- IDEMPOTENT:
--   - schema_migrations kontrolu Python runner'da yapilir
--   - Tum CREATE TABLE  -> IF NOT EXISTS
--   - Tum CREATE INDEX  -> IF NOT EXISTS
--   - Tum INSERT'ler    -> OR IGNORE
--   - UNIQUE constraint -> kullanici_adi
--
-- TRANSACTION:
--   - Tum islemler tek BEGIN..COMMIT bloku icinde
--   - Hata olursa Python'da otomatik rollback
-- ============================================================

BEGIN TRANSACTION;

-- ============================================================
-- 0) schema_migrations tablosu (mock_data.db'de yok ise olustur)
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version           TEXT PRIMARY KEY,
    uygulama_zamani   TEXT DEFAULT (datetime('now', 'localtime')),
    aciklama          TEXT
);


-- ============================================================
-- 1) tasks_users  --  bagimsiz kullanici havuzu
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks_users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ad              TEXT    NOT NULL,
    kullanici_adi   TEXT    NOT NULL UNIQUE,            -- UNIQUE garanti
    rol             TEXT    NOT NULL,                   -- admin/genel_mudur/mudur/planlama/satin_alma/grafik/finans/usta/personel/kalite/depo
    departman       TEXT,                               -- yonetim/planlama/uretim/satin_alma/kalite/depo/finans/grafik
    aktif           INTEGER NOT NULL DEFAULT 1,

    -- Mevcut kullanici kaynaklarina mapping (ileride doldurulur)
    linked_source   TEXT,                               -- 'sistem_kullanici' / 'usta_kullanici' / 'pers_kullanici' / 'manual' / NULL
    linked_id       INTEGER,                            -- ilgili tablodaki id

    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_users_kadi   ON tasks_users(kullanici_adi);
CREATE INDEX IF NOT EXISTS idx_tasks_users_rol    ON tasks_users(rol);
CREATE INDEX IF NOT EXISTS idx_tasks_users_dep    ON tasks_users(departman);
CREATE INDEX IF NOT EXISTS idx_tasks_users_aktif  ON tasks_users(aktif);
CREATE INDEX IF NOT EXISTS idx_tasks_users_link   ON tasks_users(linked_source, linked_id);


-- ============================================================
-- 2) tasks  --  ana gorev tablosu
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Icerik
    title               TEXT    NOT NULL,
    description         TEXT,
    task_type           TEXT    NOT NULL DEFAULT 'operasyon_talimati',
    priority            TEXT    NOT NULL DEFAULT 'orta',         -- dusuk/orta/yuksek/kritik
    status              TEXT    NOT NULL DEFAULT 'bekliyor',     -- bekliyor/goruldu/devam_ediyor/onay_bekliyor/revize_istendi/tamamlandi/gecikti/iptal

    -- Atama (tasks_users.kullanici_adi - soft FK)
    created_by          TEXT    NOT NULL,
    assigned_to         TEXT,                                    -- NULL = birim havuzu
    department          TEXT    NOT NULL,

    -- Termin
    due_date            TEXT,                                    -- ISO datetime

    -- Baglam (sipariş/emir/model/musteri)
    related_order_no    TEXT,
    related_emir_no     TEXT,
    related_model       TEXT,
    related_customer    TEXT,
    -- Generic baglam (numune/malzeme/cari icin)
    baglam_tipi         TEXT,
    baglam_id           TEXT,
    baglam_ozet         TEXT,

    -- Onay sureci
    requires_approval   INTEGER NOT NULL DEFAULT 0,              -- 0/1
    approval_user_id    TEXT,
    approved_at         TEXT,
    rejected_at         TEXT,
    rejection_reason    TEXT,

    -- Durum gecisleri (zaman damgalari)
    created_at          TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT DEFAULT (datetime('now', 'localtime')),
    seen_at             TEXT,                                    -- goruldu
    started_at          TEXT,                                    -- devam_ediyor
    completed_at        TEXT,                                    -- tamamlandi

    -- Cevap (opsiyonel)
    requires_response   INTEGER NOT NULL DEFAULT 0,
    response_text       TEXT,
    response_by         TEXT,
    response_at         TEXT,

    -- Hierarsi (gelecek)
    parent_task_id      INTEGER,
    auto_source         TEXT                                     -- manual/otomatik_gecikme/vb.
);

CREATE INDEX IF NOT EXISTS idx_tasks_status         ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned       ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_dept           ON tasks(department);
CREATE INDEX IF NOT EXISTS idx_tasks_created_by     ON tasks(created_by);
CREATE INDEX IF NOT EXISTS idx_tasks_due            ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_baglam         ON tasks(baglam_tipi, baglam_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at     ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_parent         ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_approval       ON tasks(approval_user_id, status);


-- ============================================================
-- 3) task_files  --  dosya ekleri
-- ============================================================
CREATE TABLE IF NOT EXISTS task_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    file_name       TEXT    NOT NULL,                            -- orijinal ad
    file_path       TEXT    NOT NULL,                            -- disk yolu
    file_type       TEXT,                                        -- mime
    file_size       INTEGER,
    uploaded_by     TEXT    NOT NULL,                            -- tasks_users.kullanici_adi
    uploaded_at     TEXT DEFAULT (datetime('now', 'localtime')),
    deleted         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_files_task     ON task_files(task_id);
CREATE INDEX IF NOT EXISTS idx_task_files_user     ON task_files(uploaded_by);


-- ============================================================
-- 4) task_logs  --  audit + history (zorunlu)
-- ============================================================
CREATE TABLE IF NOT EXISTS task_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    user_id         TEXT    NOT NULL,                            -- tasks_users.kullanici_adi
    action          TEXT    NOT NULL,                            -- created/status_changed/file_added/approved/rejected/...
    old_status      TEXT,
    new_status      TEXT,
    note            TEXT,
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_logs_task      ON task_logs(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_logs_user      ON task_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_action    ON task_logs(action);


-- ============================================================
-- 5) task_settings  --  kullanici/departman bazli ayarlar
-- ============================================================
CREATE TABLE IF NOT EXISTS task_settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key     TEXT    NOT NULL,
    setting_value   TEXT,
    departman       TEXT,                                        -- NULL = global
    user_id         TEXT,                                        -- NULL = ortak
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- key + scope unique (NULL'lari COALESCE ile yoneten unique index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_settings_uniq
    ON task_settings(setting_key,
                     COALESCE(departman, ''),
                     COALESCE(user_id, ''));


-- ============================================================
-- VARSAYILAN AYARLAR (global, INSERT OR IGNORE)
-- ============================================================
INSERT OR IGNORE INTO task_settings (setting_key, setting_value, departman, user_id)
    VALUES ('overlay_enabled',    '1',  NULL, NULL);
INSERT OR IGNORE INTO task_settings (setting_key, setting_value, departman, user_id)
    VALUES ('sound_enabled',      '0',  NULL, NULL);
INSERT OR IGNORE INTO task_settings (setting_key, setting_value, departman, user_id)
    VALUES ('poll_interval_sec',  '30', NULL, NULL);
INSERT OR IGNORE INTO task_settings (setting_key, setting_value, departman, user_id)
    VALUES ('overdue_check_min',  '15', NULL, NULL);


-- ============================================================
-- MIGRATION KAYDI (idempotent: INSERT OR IGNORE)
-- ============================================================
INSERT OR IGNORE INTO schema_migrations (version, uygulama_zamani, aciklama)
    VALUES (
        '002',
        datetime('now', 'localtime'),
        '002_tasks.sql v2 - CPS gorev modulu cekirdek (5 tablo: tasks_users, tasks, task_files, task_logs, task_settings)'
    );


COMMIT;

-- ============================================================
-- SON
-- ============================================================

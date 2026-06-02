-- =====================================================
-- SOLARIZ CPS — FAZ 1 TABLOLARI
-- 5 May 2026
-- =====================================================

-- 1. PROSES KATEGORİ
CREATE TABLE IF NOT EXISTS proses_kategori (
    proses_kod TEXT PRIMARY KEY,
    proses_adi TEXT NOT NULL,
    kategori   TEXT NOT NULL CHECK(kategori IN ('ATKI','GOVDE','MAMUL')),
    sira       INTEGER DEFAULT 0
);

-- 2. PROSES USTA ATAMA
CREATE TABLE IF NOT EXISTS proses_usta_atama (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proses_kod      TEXT NOT NULL,
    usta_kullanici  TEXT NOT NULL,
    fallback_usta   TEXT DEFAULT 'halil',
    aktif           INTEGER DEFAULT 1,
    olusturma_tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (proses_kod) REFERENCES proses_kategori(proses_kod)
);

-- 3. SİPARİŞ PROSES DURUM (anlık ilerleme)
CREATE TABLE IF NOT EXISTS siparis_proses_durum (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    siparis_no      TEXT NOT NULL,
    proses_kod      TEXT NOT NULL,
    hedef           INTEGER NOT NULL,
    yapilan_korgun  INTEGER DEFAULT 0,
    yapilan_cps     INTEGER DEFAULT 0,
    yuzde           REAL DEFAULT 0,
    guncelleme      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(siparis_no, proses_kod)
);

-- 4. SİPARİŞ DARBOĞAZ (özet — saatlik güncellenir)
CREATE TABLE IF NOT EXISTS siparis_darbogaz (
    siparis_no            TEXT PRIMARY KEY,
    model_kod             TEXT,
    musteri               TEXT,
    hedef_toplam          INTEGER,
    atki_yuzde            REAL DEFAULT 0,
    govde_yuzde           REAL DEFAULT 0,
    mamul_yuzde           REAL DEFAULT 0,
    ana_darbogaz          TEXT,
    alt_darbogaz_proses   TEXT,
    kilitlenecek_usta     TEXT,
    sapma_yuzde           REAL DEFAULT 0,
    seviye                TEXT DEFAULT 'NORMAL',
    guncelleme            DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 5. SAPMA OLAY (her sapma kayıt)
CREATE TABLE IF NOT EXISTS sapma_olay (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    siparis_no      TEXT NOT NULL,
    proses_kod      TEXT NOT NULL,
    usta            TEXT,
    olmasi_gereken  INTEGER,
    gercek          INTEGER,
    sapma_yuzde     REAL,
    seviye          TEXT,
    durum           TEXT DEFAULT 'SEBEP_BEKLENIYOR',
    acilis_zamani   DATETIME DEFAULT CURRENT_TIMESTAMP,
    kapanis_zamani  DATETIME
);

-- 6. USTA KİLİT DURUM
CREATE TABLE IF NOT EXISTS usta_kilit_durum (
    kullanici       TEXT PRIMARY KEY,
    kilit_aktif     INTEGER DEFAULT 0,
    sapma_olay_id   INTEGER,
    baslangic       DATETIME,
    FOREIGN KEY (sapma_olay_id) REFERENCES sapma_olay(id)
);

-- 7. USTA AKSİYON (sebep + açıklama)
CREATE TABLE IF NOT EXISTS usta_aksiyon (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sapma_olay_id   INTEGER NOT NULL,
    usta            TEXT NOT NULL,
    sebep_kategori  TEXT NOT NULL,
    aciklama        TEXT NOT NULL,
    supheli_flag    INTEGER DEFAULT 0,
    sistem_yorumu   TEXT,
    giris_zamani    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sapma_olay_id) REFERENCES sapma_olay(id)
);

-- 8. PLANLAMA KARAR (Faz 2'de kullanılacak ama şimdi tablo hazır)
CREATE TABLE IF NOT EXISTS planlama_karar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sapma_olay_id   INTEGER NOT NULL,
    planlama        TEXT NOT NULL,
    karar           TEXT NOT NULL CHECK(karar IN ('ONAYLA','DUZELT','HEDEF_DEGISTIR')),
    yeni_hedef      INTEGER,
    not_metni       TEXT,
    karar_zamani    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sapma_olay_id) REFERENCES sapma_olay(id)
);

-- 9. VARDİYA DEVİR LOG (Faz 2)
CREATE TABLE IF NOT EXISTS vardiya_devir_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sapma_olay_id   INTEGER,
    onceki_usta     TEXT,
    yeni_usta       TEXT,
    proses_kod      TEXT,
    devir_zamani    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- SEED DATA — Proses Kategori (Korgun kodları)
-- =====================================================
INSERT OR REPLACE INTO proses_kategori (proses_kod, proses_adi, kategori, sira) VALUES
    ('26', 'Enjeksiyon',        'ATKI',  1),
    ('50', 'Eva Hazir',         'ATKI',  2),
    ('02', 'Kesim',             'GOVDE', 1),
    ('15', 'Saya',              'GOVDE', 2),
    ('18', 'Saya Kontrol',      'GOVDE', 3),
    ('42', 'Saya Hazir',        'GOVDE', 4),
    ('28', 'Monta Baslayacak',  'MAMUL', 1),
    ('30', 'Monta',             'MAMUL', 2),
    ('32', 'Mekval',            'MAMUL', 3),
    ('35', 'Temizleme',         'MAMUL', 4);

-- =====================================================
-- SEED DATA — Usta Atamaları (Faz 1 pilot: tek usta Halil)
-- =====================================================
INSERT OR REPLACE INTO proses_usta_atama (proses_kod, usta_kullanici, fallback_usta) VALUES
    ('26', 'halil', 'halil'),
    ('50', 'halil', 'halil'),
    ('02', 'halil', 'halil'),
    ('15', 'halil', 'halil'),
    ('18', 'halil', 'halil'),
    ('42', 'halil', 'halil'),
    ('28', 'halil', 'halil'),
    ('30', 'halil', 'halil'),
    ('32', 'halil', 'halil'),
    ('35', 'halil', 'halil');

-- =====================================================
-- SEED DATA — Halil için kilit kaydı (başta kapalı)
-- =====================================================
INSERT OR REPLACE INTO usta_kilit_durum (kullanici, kilit_aktif) VALUES
    ('halil', 0);
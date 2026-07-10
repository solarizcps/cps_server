# -*- coding: utf-8 -*-
"""
NexGen DB Audit & Repair Script
================================
Amaç  : NexGen için gereken tüm tabloları kontrol eder, eksikleri oluşturur,
        kritik kolon kontrolü yapar ve ekranlara göre durum raporu sunar.

Kullanım:
    python app/tools/nexgen_db_repair.py

Kurallar:
  - Çalışmadan önce backup alır (mock_data_backup_repair_YYYYMMDD_HHMM.db).
  - Mevcut veri (stok, fiyat, formül, reçete) asla silinmez.
  - Her işlem idempotent (CREATE IF NOT EXISTS, ALTER IF NOT EXISTS).
  - Schema_migrations tablosuna kayıt atar.
  - Eksik seed veri "VERİ EKSİK" olarak raporlanır, hata değil.
"""

import sqlite3
import os
import shutil
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, '..', 'mock_data.db')
DB_PATH = os.path.normpath(DB_PATH)

REPORTS_DIR = os.path.join(_HERE, '..', '..', 'reports')
REPORTS_DIR = os.path.normpath(REPORTS_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(
        f"PRAGMA table_info({tablo})"
    ).fetchall()]


def _index_var(cur, idx):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx,)
    ).fetchone() is not None


def _say(cur, tablo):
    try:
        return cur.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
    except Exception:
        return -1


def _alter_add(cur, con, tablo, kolon, tip):
    if not _kolon_var(cur, tablo, kolon):
        cur.execute(f"ALTER TABLE {tablo} ADD COLUMN {kolon} {tip}")
        con.commit()
        return True
    return False


def _create_index(cur, con, idx_ad, tablo_kolon):
    if not _index_var(cur, idx_ad):
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {tablo_kolon}")
        con.commit()
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# STEP 0 — BACKUP
# ──────────────────────────────────────────────────────────────────────────────
def step0_backup(log):
    ts  = datetime.now().strftime('%Y%m%d_%H%M')
    bak = DB_PATH.replace('.db', f'_backup_repair_{ts}.db')
    shutil.copy2(DB_PATH, bak)
    log.append(f"[BACKUP] {os.path.basename(bak)}")
    print(f"  BACKUP → {os.path.basename(bak)}")
    return bak


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — schema_migrations (bağımlılık: hiçbir şey)
# ──────────────────────────────────────────────────────────────────────────────
def step1_schema_migrations(cur, con, log):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version           TEXT PRIMARY KEY,
            uygulama_zamani   TEXT DEFAULT (datetime('now','localtime')),
            aciklama          TEXT
        )
    """)
    con.commit()
    log.append("[047] schema_migrations hazır")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 047 — nexgen_stok_kart + nexgen_stok_hareket
# ──────────────────────────────────────────────────────────────────────────────
def mig047(cur, con, log):
    tag = "[047]"
    created = []

    if not _tablo_var(cur, 'nexgen_stok_kart'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_stok_kart (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kod              TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                ad               TEXT    NOT NULL,
                kategori         TEXT    NOT NULL DEFAULT 'HAMMADDE',
                birim            TEXT    NOT NULL DEFAULT 'KG',
                minimum_stok     REAL    NOT NULL DEFAULT 0,
                kritik_stok      REAL    NOT NULL DEFAULT 0,
                aciklama         TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now')),
                guncelleyen_id   INTEGER,
                guncelleme_tarihi TEXT
            )
        """)
        con.commit()
        created.append('nexgen_stok_kart')

    if not _tablo_var(cur, 'nexgen_stok_hareket'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_stok_hareket (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                stok_kart_id     INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
                hareket_tipi     TEXT    NOT NULL,
                miktar_kg        REAL    NOT NULL,
                onceki_stok      REAL    NOT NULL DEFAULT 0,
                sonraki_stok     REAL    NOT NULL DEFAULT 0,
                aciklama         TEXT,
                referans_tip     TEXT,
                referans_id      INTEGER,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        _create_index(cur, con, 'idx_nsh_kart_id', 'nexgen_stok_hareket(stok_kart_id)')
        _create_index(cur, con, 'idx_nsh_tarih',   'nexgen_stok_hareket(olusturma_tarihi)')
        con.commit()
        created.append('nexgen_stok_hareket')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('047', 'nexgen stok kart + hareket')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK (zaten mevcut)'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 048 — nexgen_stok_kart opsiyonel kolonlar
# ──────────────────────────────────────────────────────────────────────────────
def mig048(cur, con, log):
    tag = "[048]"
    added = []
    alts = [
        ('tedarikci_kodu',    'TEXT'),
        ('barkod',            'TEXT'),
        ('orijin',            'TEXT'),
        ('son_giris_tarihi',  'TEXT'),
        ('son_cikis_tarihi',  'TEXT'),
    ]
    for kolon, tip in alts:
        if _alter_add(cur, con, 'nexgen_stok_kart', kolon, tip):
            added.append(kolon)
    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('048', 'stok_kart opsiyonel kolonlar')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK (zaten mevcut)'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 049 — nexgen_tedarikci + nexgen_satin_siparis
# ──────────────────────────────────────────────────────────────────────────────
def mig049(cur, con, log):
    tag = "[049]"
    created = []

    if not _tablo_var(cur, 'nexgen_tedarikci'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_tedarikci (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kod              TEXT    NOT NULL UNIQUE,
                ad               TEXT    NOT NULL,
                vergi_no         TEXT,
                iletisim         TEXT,
                adres            TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        created.append('nexgen_tedarikci')

    if not _tablo_var(cur, 'nexgen_satin_siparis'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_satin_siparis (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                siparis_no       TEXT    NOT NULL UNIQUE,
                tedarikci_id     INTEGER REFERENCES nexgen_tedarikci(id),
                stok_kart_id     INTEGER REFERENCES nexgen_stok_kart(id),
                miktar_kg        REAL    NOT NULL DEFAULT 0,
                birim_fiyat      REAL,
                para_birimi      TEXT    DEFAULT 'TRY',
                durum            TEXT    NOT NULL DEFAULT 'BEKLEMEDE',
                siparis_tarihi   TEXT    DEFAULT (datetime('now')),
                beklenen_teslim  TEXT,
                notlar           TEXT,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        created.append('nexgen_satin_siparis')
    else:
        # Tablo zaten varsa eksik kolon ekle
        if _alter_add(cur, con, 'nexgen_satin_siparis', 'beklenen_teslim', 'TEXT'):
            created.append('satin_siparis.beklenen_teslim (eklendi)')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('049', 'tedarikci + satin siparis')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 056 — fiyat tabloları
# ──────────────────────────────────────────────────────────────────────────────
def mig056(cur, con, log):
    tag = "[056]"
    created = []

    if not _tablo_var(cur, 'nexgen_fiyat_batch'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_fiyat_batch (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_kodu       TEXT    NOT NULL UNIQUE,
                aciklama         TEXT,
                kaynak           TEXT    DEFAULT 'EXCEL',
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        created.append('nexgen_fiyat_batch')

    if not _tablo_var(cur, 'nexgen_fiyat_batch_detay'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_fiyat_batch_detay (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id         INTEGER NOT NULL REFERENCES nexgen_fiyat_batch(id),
                stok_kart_id     INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
                birim_fiyat      REAL    NOT NULL DEFAULT 0,
                para_birimi      TEXT    DEFAULT 'TRY',
                gecerlilik_tarihi TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        created.append('nexgen_fiyat_batch_detay')

    if not _tablo_var(cur, 'nexgen_hammadde_fiyat'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_hammadde_fiyat (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                stok_kart_id     INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
                birim_fiyat      REAL    NOT NULL DEFAULT 0,
                para_birimi      TEXT    DEFAULT 'TRY',
                gecerlilik_baslangic TEXT,
                gecerlilik_bitis    TEXT,
                kaynak           TEXT    DEFAULT 'MANUEL',
                notlar           TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        _create_index(cur, con, 'idx_nhf_stok', 'nexgen_hammadde_fiyat(stok_kart_id)')
        con.commit()
        created.append('nexgen_hammadde_fiyat')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('056', 'fiyat batch + hammadde fiyat')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 057-059 — yetki/fiyat kaynak (sadece mevcut tablo kontrol)
# ──────────────────────────────────────────────────────────────────────────────
def mig057_059(cur, con, log):
    tag = "[057-059]"
    added = []
    if _tablo_var(cur, 'nexgen_satin_siparis'):
        if _alter_add(cur, con, 'nexgen_satin_siparis', 'fiyat_kaynak', 'TEXT'):
            added.append('nexgen_satin_siparis.fiyat_kaynak')
        if _alter_add(cur, con, 'nexgen_satin_siparis', 'fiyat_batch_id', 'INTEGER'):
            added.append('nexgen_satin_siparis.fiyat_batch_id')
    for v in ('057', '058', '059'):
        cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 060 — nexgen_mal_kabul
# ──────────────────────────────────────────────────────────────────────────────
def mig060(cur, con, log):
    tag = "[060]"
    if not _tablo_var(cur, 'nexgen_mal_kabul'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_mal_kabul (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                mal_kabul_no     TEXT    NOT NULL UNIQUE,
                stok_kart_id     INTEGER REFERENCES nexgen_stok_kart(id),
                tedarikci_id     INTEGER REFERENCES nexgen_tedarikci(id),
                miktar_kg        REAL    NOT NULL DEFAULT 0,
                kabul_tarihi     TEXT    DEFAULT (datetime('now')),
                lot_no           TEXT,
                durum            TEXT    NOT NULL DEFAULT 'BEKLEMEDE',
                notlar           TEXT,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('060', 'mal kabul')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_mal_kabul")
    else:
        log.append(f"{tag} OK")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 062 — nexgen_formul + renk_varyant + uretim_varyant + recete_kalem
# ──────────────────────────────────────────────────────────────────────────────
def mig062(cur, con, log):
    tag = "[062]"
    created = []

    if not _tablo_var(cur, 'nexgen_formul'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_formul (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kod              TEXT    NOT NULL UNIQUE,
                ad               TEXT    NOT NULL,
                aciklama         TEXT,
                durum            TEXT    NOT NULL DEFAULT 'TASLAK',
                onay_durumu      TEXT    NOT NULL DEFAULT 'BEKLIYOR',
                olusturan_id     INTEGER,
                onaylayan_id     INTEGER,
                onay_tarihi      TEXT,
                onay_notu        TEXT,
                notlar           TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                guncelleme_tarihi TEXT
            )
        """)
        _create_index(cur, con, 'idx_nf_kod',   'nexgen_formul(kod)')
        _create_index(cur, con, 'idx_nf_durum', 'nexgen_formul(durum)')
        con.commit()
        created.append('nexgen_formul')

    if not _tablo_var(cur, 'nexgen_renk_varyant'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_renk_varyant (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                formul_id        INTEGER NOT NULL REFERENCES nexgen_formul(id),
                kod              TEXT    NOT NULL,
                ad               TEXT    NOT NULL,
                renk             TEXT    NOT NULL,
                notlar           TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (formul_id, renk)
            )
        """)
        _create_index(cur, con, 'idx_nrv_formul', 'nexgen_renk_varyant(formul_id)')
        con.commit()
        created.append('nexgen_renk_varyant')

    if not _tablo_var(cur, 'nexgen_uretim_varyant'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_uretim_varyant (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                renk_varyant_id  INTEGER NOT NULL REFERENCES nexgen_renk_varyant(id),
                boyut            TEXT    NOT NULL DEFAULT 'STANDART',
                ad               TEXT    NOT NULL,
                onay_durumu      TEXT    NOT NULL DEFAULT 'BEKLIYOR',
                onaylayan_id     INTEGER,
                onay_tarihi      TEXT,
                onay_notu        TEXT,
                kaynak_varyant_id INTEGER REFERENCES nexgen_uretim_varyant(id),
                recete_durum     TEXT    DEFAULT 'TASLAK',
                notlar           TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (renk_varyant_id, boyut)
            )
        """)
        _create_index(cur, con, 'idx_nuv_renk',  'nexgen_uretim_varyant(renk_varyant_id)')
        _create_index(cur, con, 'idx_nuv_boyut', 'nexgen_uretim_varyant(boyut)')
        con.commit()
        created.append('nexgen_uretim_varyant')

    if not _tablo_var(cur, 'nexgen_recete_kalem'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_recete_kalem (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                uretim_varyant_id INTEGER NOT NULL REFERENCES nexgen_uretim_varyant(id),
                stok_kart_id      INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
                sira              INTEGER NOT NULL DEFAULT 1,
                miktar_kg         REAL    NOT NULL CHECK (miktar_kg > 0),
                aciklama          TEXT,
                aktif             INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (uretim_varyant_id, stok_kart_id)
            )
        """)
        _create_index(cur, con, 'idx_nrk_varyant', 'nexgen_recete_kalem(uretim_varyant_id)')
        _create_index(cur, con, 'idx_nrk_stok',    'nexgen_recete_kalem(stok_kart_id)')
        con.commit()
        created.append('nexgen_recete_kalem')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('062', 'recete tablolari FAZ-4A')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 064 — nexgen_arge_test + nexgen_arge_test_kalem
# ──────────────────────────────────────────────────────────────────────────────
def mig064(cur, con, log):
    tag = "[064]"
    created = []

    if not _tablo_var(cur, 'nexgen_arge_test'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_test (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                kaynak_uretim_varyant_id INTEGER NOT NULL,
                test_no                  TEXT    NOT NULL,
                test_tipi                TEXT    NOT NULL DEFAULT 'RENK_TEST',
                makina                   TEXT    NOT NULL DEFAULT '7.5 LT',
                test_batch_kg            REAL    NOT NULL DEFAULT 7.5,
                kaynak_batch_kg          REAL    NOT NULL DEFAULT 100,
                yeni_renk_adi            TEXT,
                notlar                   TEXT,
                durum                    TEXT    NOT NULL DEFAULT 'TASLAK',
                sonuc_notu               TEXT,
                renk_tuttu               INTEGER,
                shore_degeri             REAL,
                kopurme_notu             TEXT,
                cekme_problemi           INTEGER,
                genel_aciklama           TEXT,
                olusturan_id             INTEGER,
                olusturma_tarihi         TEXT    NOT NULL DEFAULT (datetime('now')),
                onaylayan_id             INTEGER,
                onay_tarihi              TEXT,
                aktif                    INTEGER NOT NULL DEFAULT 1
            )
        """)
        con.commit()
        created.append('nexgen_arge_test')

    if not _tablo_var(cur, 'nexgen_arge_test_kalem'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_test_kalem (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id           INTEGER NOT NULL,
                stok_kart_id      INTEGER NOT NULL,
                sira              INTEGER NOT NULL DEFAULT 1,
                orjinal_miktar_kg REAL    NOT NULL,
                test_miktar_kg    REAL    NOT NULL,
                aciklama          TEXT,
                olusturma_tarihi  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        created.append('nexgen_arge_test_kalem')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('064', 'arge test tablolari')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 065-068 — arge_test + uretim_batch ALTER kolonlar
# ──────────────────────────────────────────────────────────────────────────────
def mig065_068(cur, con, log):
    tag = "[065-068]"
    added = []

    # 065: aktarim baglanti
    if _tablo_var(cur, 'nexgen_arge_test'):
        for kolon, tip in [
            ('aktarildi_mi', 'INTEGER DEFAULT 0'),
            ('aktarim_tarihi', 'TEXT'),
            ('aktarim_notu', 'TEXT'),
        ]:
            if _alter_add(cur, con, 'nexgen_arge_test', kolon, tip):
                added.append(f'arge_test.{kolon}')

    # 066: uretim_batch (batch_kodu = migration 066 orijinal şeması)
    if not _tablo_var(cur, 'nexgen_uretim_batch'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_uretim_batch (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_kodu          TEXT    NOT NULL UNIQUE,
                uretim_varyant_id   INTEGER REFERENCES nexgen_uretim_varyant(id),
                plan_id             INTEGER REFERENCES nexgen_uretim_plan(id),
                planlanan_kg        REAL    NOT NULL DEFAULT 0,
                uretilen_kg         REAL    DEFAULT 0,
                fire_kg             REAL    DEFAULT 0,
                baslangic_tarihi    TEXT,
                bitis_tarihi        TEXT,
                durum               TEXT    NOT NULL DEFAULT 'BEKLEMEDE',
                notlar              TEXT,
                olusturan_id        INTEGER,
                olusturma_tarihi    TEXT    DEFAULT (datetime('now','localtime')),
                lot_kodu            TEXT
            )
        """)
        con.commit()
        added.append('nexgen_uretim_batch')

    # 067: recycle izin
    if not _tablo_var(cur, 'nexgen_recete_recycle_izin'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_recete_recycle_izin (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                uretim_varyant_id INTEGER NOT NULL,
                max_recycle_oran  REAL   DEFAULT 0.1,
                notlar           TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        added.append('nexgen_recete_recycle_izin')

    # 068: lot_kodu
    if _tablo_var(cur, 'nexgen_uretim_batch'):
        if _alter_add(cur, con, 'nexgen_uretim_batch', 'lot_kodu', 'TEXT'):
            added.append('uretim_batch.lot_kodu')

    for v in ('065', '066', '067', '068'):
        cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 069 — nexgen_uretim_plan
# ──────────────────────────────────────────────────────────────────────────────
def mig069(cur, con, log):
    tag = "[069]"
    if not _tablo_var(cur, 'nexgen_uretim_plan'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_uretim_plan (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_kodu           TEXT NOT NULL UNIQUE,
                kaynak              TEXT NOT NULL DEFAULT 'MANUEL',
                siparis_no          TEXT,
                musteri_adi         TEXT,
                uretim_varyant_id   INTEGER NOT NULL REFERENCES nexgen_uretim_varyant(id),
                planlanan_kg        REAL NOT NULL DEFAULT 0,
                oncelik_sira        INTEGER NOT NULL DEFAULT 10,
                plan_tarihi         TEXT NOT NULL,
                durum               TEXT NOT NULL DEFAULT 'PLANLANDI',
                notlar              TEXT,
                created_at          TEXT DEFAULT (datetime('now','localtime')),
                created_by          INTEGER,
                termin_tarihi       TEXT,
                cari_id             INTEGER,
                rf_renk_id          INTEGER,
                planlama_siparis_id INTEGER
            )
        """)
        _create_index(cur, con, 'idx_nup_durum',  'nexgen_uretim_plan(durum)')
        _create_index(cur, con, 'idx_nup_tarih',  'nexgen_uretim_plan(plan_tarihi)')
        _create_index(cur, con, 'idx_nup_cari',   'nexgen_uretim_plan(cari_id)')
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('069', 'uretim plan')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_uretim_plan")
    else:
        # Kolon kontrolü (mig 071-083 ALTER'ları)
        added = []
        alts = [
            ('cari_id',             'INTEGER'),
            ('rf_renk_id',          'INTEGER'),
            ('planlama_siparis_id', 'INTEGER'),
            ('termin_tarihi',       'TEXT'),
        ]
        for kolon, tip in alts:
            if _alter_add(cur, con, 'nexgen_uretim_plan', kolon, tip):
                added.append(kolon)
        if added:
            log.append(f"{tag} OK + eklendi: {', '.join(added)}")
        else:
            log.append(f"{tag} OK")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 070 — nexgen_cari
# ──────────────────────────────────────────────────────────────────────────────
def mig070(cur, con, log):
    tag = "[070]"
    if not _tablo_var(cur, 'nexgen_cari'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_cari (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cari_kod    TEXT NOT NULL UNIQUE,
                unvan       TEXT NOT NULL,
                aktif       INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()

        # Seed cariler
        seed = [
            ('120.NX.004', 'Beoss Ayakkabı Terlik İnşaat Otomotiv Sanayi ve Ticaret Limited Şirketi'),
            ('120.NX.006', 'Cihan Makina Mermer ve Madencilik San.Tic.Ltd.Şti'),
            ('120.NX.007', 'Ulkucan Ayakk.ve Ayak.Malz.San.ve Tic.Ltd.Şti'),
            ('120.NX.008', 'Poltab Ayakkabı Taban San.Tic.Lts.Şti'),
            ('120.NX.009', '3E Ayakkabı Taban San.Tic.Ltd.Şti'),
            ('120.NX.010', 'Burak Taban Ayakkabı İnşaat Sanayi ve Dış Ltd Şti'),
            ('120.NX.011', 'AYM Taban Poliüretan ve Gram.Em.San.Tic.Ltd.Şti'),
            ('120.NX.013', 'Bal Terlik Taban San.Ve Tic.Ltd. Şti.'),
            ('120.NX.018', 'SEHA AYAKKABI VE TEKSTİL SAN. TİC. A.Ş.'),
            ('120.NX.019', 'YILDIRIM AYAKKABI - MURAT YILDIRIM'),
            ('120.NX.020', 'NEZİH AYAKKABI MALZ.DERİ TEKS.ÜR.PAZ.SAN.TİC.LTD.ŞTİ.'),
            ('120.NX012',  'Akım Plastik Sanayi ve Ticaret Limited Şirketi'),
        ]
        for kod, unvan in seed:
            cur.execute(
                "INSERT OR IGNORE INTO nexgen_cari(cari_kod, unvan) VALUES(?, ?)",
                (kod, unvan)
            )
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('070', 'cari master + seed')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_cari + seed")
    else:
        log.append(f"{tag} OK ({_say(cur, 'nexgen_cari')} cari)")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 071-073 — batch plan link + uretim_parca + formul_batch_kg
# ──────────────────────────────────────────────────────────────────────────────
def mig071_073(cur, con, log):
    tag = "[071-073]"
    added = []

    # 071 + batch_kodu güvenlik (eski DB'lerde batch_no ile oluşturulmuş olabilir)
    if _tablo_var(cur, 'nexgen_uretim_batch'):
        if _alter_add(cur, con, 'nexgen_uretim_batch', 'plan_id', 'INTEGER'):
            added.append('uretim_batch.plan_id')
        if _alter_add(cur, con, 'nexgen_uretim_batch', 'batch_kodu', 'TEXT'):
            added.append('uretim_batch.batch_kodu')

    # 072 — batch_kodu + parca_no (mig072 orijinal şeması; parca_kodu yok)
    if not _tablo_var(cur, 'nexgen_uretim_parca'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_uretim_parca (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id         INTEGER NOT NULL REFERENCES nexgen_uretim_batch(id),
                batch_kodu       TEXT    NOT NULL,
                plan_id          INTEGER REFERENCES nexgen_uretim_plan(id),
                parca_no         INTEGER NOT NULL DEFAULT 1,
                hedef_kg         REAL    NOT NULL DEFAULT 0,
                uretilen_kg      REAL    NOT NULL DEFAULT 0,
                durum            TEXT    NOT NULL DEFAULT 'HAZIR',
                baslama_zamani   TEXT,
                bitis_zamani     TEXT,
                created_at       TEXT DEFAULT (datetime('now','localtime')),
                updated_at       TEXT DEFAULT (datetime('now','localtime')),
                operator_id      INTEGER,
                vardiya          TEXT,
                bekleme_sebebi   TEXT,
                notlar           TEXT,
                formul_batch_kg  REAL,
                UNIQUE(batch_kodu, parca_no)
            )
        """)
        _create_index(cur, con, 'idx_uretim_parca_batch', 'nexgen_uretim_parca(batch_kodu)')
        _create_index(cur, con, 'idx_uretim_parca_plan',  'nexgen_uretim_parca(plan_id)')
        con.commit()
        added.append('nexgen_uretim_parca')

    # 073: formul_batch_kg
    if _tablo_var(cur, 'nexgen_uretim_varyant'):
        if _alter_add(cur, con, 'nexgen_uretim_varyant', 'formul_batch_kg', 'REAL DEFAULT 0'):
            added.append('uretim_varyant.formul_batch_kg')

    for v in ('071', '072', '073'):
        cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 074-077 — arge_test kolon eklemeleri (routes.py inline mig'lerle aynı)
# ──────────────────────────────────────────────────────────────────────────────
def mig074_077(cur, con, log):
    tag = "[074-077]"
    added = []

    if _tablo_var(cur, 'nexgen_arge_test'):
        alts = [
            ('cari_id',            'INTEGER'),
            ('shore_hedef',        'REAL'),
            ('lot_no',             'TEXT'),
            ('talep_referansi',    'TEXT'),
            ('onay_notu',          'TEXT'),
            ('rf_renk_id',         'INTEGER'),
            ('numune_orani',       'REAL DEFAULT 0.1'),
            ('arge_kodu',          'TEXT'),
            ('renk_bilesenleri_json', 'TEXT'),
        ]
        for kolon, tip in alts:
            if _alter_add(cur, con, 'nexgen_arge_test', kolon, tip):
                added.append(f'arge_test.{kolon}')

    for v in ('074', '075', '076', '077'):
        cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 076 — RF tablolar
# ──────────────────────────────────────────────────────────────────────────────
def mig076_rf(cur, con, log):
    tag = "[076-RF]"
    created = []

    if not _tablo_var(cur, 'nexgen_rf_renk'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_rf_renk (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                rf_kod               TEXT    NOT NULL UNIQUE,
                ad                   TEXT    NOT NULL,
                durum                TEXT    NOT NULL DEFAULT 'ONAYLI',
                kaynak_arge_test_id  INTEGER UNIQUE,
                ilk_talep_cari_id    INTEGER,
                aciklama             TEXT,
                olusturan_id         INTEGER,
                olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
                onaylayan_id         INTEGER,
                onay_tarihi          TEXT,
                aktif                INTEGER NOT NULL DEFAULT 1
            )
        """)
        _create_index(cur, con, 'idx_nrf_kod',         'nexgen_rf_renk(rf_kod)')
        _create_index(cur, con, 'idx_nrf_durum',       'nexgen_rf_renk(durum)')
        _create_index(cur, con, 'idx_nrf_kaynak_test', 'nexgen_rf_renk(kaynak_arge_test_id)')
        con.commit()
        created.append('nexgen_rf_renk')

    if not _tablo_var(cur, 'nexgen_rf_kalem'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_rf_kalem (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                rf_renk_id       INTEGER NOT NULL,
                stok_kart_id     INTEGER NOT NULL,
                miktar_kg        REAL    NOT NULL CHECK (miktar_kg >= 0),
                sira             INTEGER NOT NULL DEFAULT 1,
                aciklama         TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (rf_renk_id, stok_kart_id)
            )
        """)
        _create_index(cur, con, 'idx_nrfk_rf',   'nexgen_rf_kalem(rf_renk_id)')
        _create_index(cur, con, 'idx_nrfk_stok', 'nexgen_rf_kalem(stok_kart_id)')
        con.commit()
        created.append('nexgen_rf_kalem')

    if not _tablo_var(cur, 'nexgen_rf_formul_uygunluk'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_rf_formul_uygunluk (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                rf_renk_id           INTEGER NOT NULL,
                formul_id            INTEGER NOT NULL,
                kaynak_arge_test_id  INTEGER UNIQUE,
                durum                TEXT    NOT NULL DEFAULT 'ONAYLI',
                ilk_talep_cari_id    INTEGER,
                shore_hedef          REAL,
                shore_sonuc          REAL,
                renk_sonucu          INTEGER,
                numune_sonucu        INTEGER,
                aciklama             TEXT,
                olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
                onay_tarihi          TEXT,
                aktif                INTEGER NOT NULL DEFAULT 1,
                UNIQUE (rf_renk_id, formul_id)
            )
        """)
        _create_index(cur, con, 'idx_nrfu_formul_durum', 'nexgen_rf_formul_uygunluk(formul_id, durum)')
        _create_index(cur, con, 'idx_nrfu_rf',           'nexgen_rf_formul_uygunluk(rf_renk_id)')
        con.commit()
        created.append('nexgen_rf_formul_uygunluk')

    if not _tablo_var(cur, 'nexgen_rf_kullanim'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_rf_kullanim (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                rf_renk_id       INTEGER NOT NULL,
                cari_id          INTEGER,
                siparis_id       INTEGER,
                kullanim_tipi    TEXT    DEFAULT 'NUMUNE',
                miktar_kg        REAL,
                notlar           TEXT,
                olusturma_tarihi TEXT    DEFAULT (datetime('now')),
                aktif            INTEGER NOT NULL DEFAULT 1
            )
        """)
        con.commit()
        created.append('nexgen_rf_kullanim')

    # rf_kullanim tablet kolonları (mig 079)
    if _tablo_var(cur, 'nexgen_rf_kullanim'):
        if _alter_add(cur, con, 'nexgen_rf_kullanim', 'tablet_kayit_id', 'INTEGER'):
            pass

    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 079 — stok_kart kimlik kolonları + güvenli seed
# Seed verisi 079 migration modülünden import edilir (tek kaynak, kopyalanmaz).
# ──────────────────────────────────────────────────────────────────────────────
def mig079(cur, con, log):
    tag = "[079]"
    added = []
    if _tablo_var(cur, 'nexgen_stok_kart'):
        for kolon, tip in [
            ('tanim',            'TEXT'),
            ('yeni_tanim',       'TEXT'),
            ('renk_bileseni_mi', 'INTEGER DEFAULT 0'),
        ]:
            if _alter_add(cur, con, 'nexgen_stok_kart', kolon, tip):
                added.append(kolon)

        # Güvenli seed — kaynak: app/migrations/079_nexgen_rf_kullanim_tablet.py
        try:
            import sys
            _mig_dir = os.path.normpath(os.path.join(_HERE, '..', 'migrations'))
            if _mig_dir not in sys.path:
                sys.path.insert(0, _mig_dir)
            from importlib import import_module as _imp
            _m079 = _imp('079_nexgen_rf_kullanim_tablet')
            tanim_n, renk_n = _m079._stok_kimlik_seed_uygula(cur, con)
            log.append(f"{tag} seed tanim/yeni_tanim guncellenen: {tanim_n}")
            log.append(f"{tag} seed renk_bileseni_mi=1 set edilen: {renk_n}")
        except Exception as _e:
            log.append(f"{tag} WARN seed: {_e}")

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('079')")
    con.commit()
    log.append(f"{tag} {'eklendi: '+', '.join(added) if added else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 080 — nexgen_arge_formul + nexgen_arge_formul_kalem
# ──────────────────────────────────────────────────────────────────────────────
def mig080(cur, con, log):
    tag = "[080]"
    created = []

    if not _tablo_var(cur, 'nexgen_arge_formul'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_formul (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_kodu            TEXT    UNIQUE,
                formul_adi           TEXT    NOT NULL,
                aciklama             TEXT,
                yontem               TEXT    NOT NULL DEFAULT 'SIFIRDAN',
                kaynak_formul_id     INTEGER REFERENCES nexgen_formul(id),
                cari_id              INTEGER REFERENCES nexgen_cari(id),
                renk_secim           TEXT    NOT NULL DEFAULT 'YOK',
                arge_notu            TEXT,
                durum                TEXT    NOT NULL DEFAULT 'TASLAK',
                olusan_formul_id     INTEGER REFERENCES nexgen_formul(id),
                olusturan_id         INTEGER,
                olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
                guncelleme_tarihi    TEXT,
                aktif                INTEGER NOT NULL DEFAULT 1
            )
        """)
        _create_index(cur, con, 'idx_naf_arge_kodu', 'nexgen_arge_formul(arge_kodu)')
        _create_index(cur, con, 'idx_naf_cari',      'nexgen_arge_formul(cari_id)')
        _create_index(cur, con, 'idx_naf_kaynak',    'nexgen_arge_formul(kaynak_formul_id)')
        _create_index(cur, con, 'idx_naf_durum',     'nexgen_arge_formul(durum)')
        con.commit()
        created.append('nexgen_arge_formul')

    if not _tablo_var(cur, 'nexgen_arge_formul_kalem'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_formul_kalem (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_formul_id  INTEGER NOT NULL
                                    REFERENCES nexgen_arge_formul(id)
                                    ON DELETE CASCADE,
                stok_kart_id    INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
                sira            INTEGER NOT NULL DEFAULT 1,
                miktar_kg       REAL    NOT NULL DEFAULT 0,
                renk_bileseni_mi INTEGER NOT NULL DEFAULT 0,
                miktar_gr       REAL,
                aciklama        TEXT,
                aktif           INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT   NOT NULL DEFAULT (datetime('now'))
            )
        """)
        _create_index(cur, con, 'idx_nafk_formul', 'nexgen_arge_formul_kalem(arge_formul_id)')
        _create_index(cur, con, 'idx_nafk_stok',   'nexgen_arge_formul_kalem(stok_kart_id)')
        con.commit()
        created.append('nexgen_arge_formul_kalem')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('080', 'arge_formul tablolari FAZ-3F-9')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 081 — VIEW v_nexgen_siparis_uretim_kontrol
# ──────────────────────────────────────────────────────────────────────────────
def mig081(cur, con, log):
    tag = "[081]"
    try:
        cur.execute("""
            CREATE VIEW IF NOT EXISTS v_nexgen_siparis_uretim_kontrol AS
            SELECT
                np.id,
                np.plan_kodu,
                np.siparis_no,
                np.musteri_adi,
                np.planlanan_kg,
                np.durum,
                np.plan_tarihi,
                uv.boyut,
                f.kod  AS formul_kod,
                f.ad   AS formul_ad
            FROM nexgen_uretim_plan np
            JOIN nexgen_uretim_varyant uv ON uv.id = np.uretim_varyant_id
            JOIN nexgen_renk_varyant   rv ON rv.id = uv.renk_varyant_id
            JOIN nexgen_formul          f ON  f.id = rv.formul_id
        """)
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('081')")
        con.commit()
        log.append(f"{tag} OK view v_nexgen_siparis_uretim_kontrol")
    except Exception as e:
        log.append(f"{tag} WARN view: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 082-083 — plan kolon eklemeleri
# ──────────────────────────────────────────────────────────────────────────────
def mig082_083(cur, con, log):
    tag = "[082-083]"
    # cari_id ve rf_renk_id + termin_tarihi zaten mig069'da eklendi, burada sadece kayıt
    for v in ('082', '083'):
        cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
    con.commit()
    log.append(f"{tag} OK (kolon kontrolü 069'da yapıldı)")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 084 — nexgen_planlama_siparis
# ──────────────────────────────────────────────────────────────────────────────
def mig084(cur, con, log):
    tag = "[084]"
    if not _tablo_var(cur, 'nexgen_planlama_siparis'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                siparis_no        TEXT NOT NULL UNIQUE,
                cari_id           INTEGER,
                cari_unvan        TEXT,
                termin_tarihi     TEXT,
                talep_referansi   TEXT,
                durum             TEXT NOT NULL DEFAULT 'TALEP',
                notlar            TEXT,
                olusturan_id      INTEGER,
                olusturma_tarihi  TEXT DEFAULT (datetime('now','localtime')),
                guncelleme_tarihi TEXT
            )
        """)
        _create_index(cur, con, 'idx_nps_siparis_no', 'nexgen_planlama_siparis(siparis_no)')
        _create_index(cur, con, 'idx_nps_cari',       'nexgen_planlama_siparis(cari_id)')
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('084', 'planlama siparis')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_planlama_siparis")
    else:
        log.append(f"{tag} OK ({_say(cur, 'nexgen_planlama_siparis')} siparis)")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 085 — nexgen_depo_hazirlik
# ──────────────────────────────────────────────────────────────────────────────
def mig085(cur, con, log):
    tag = "[085]"
    created = []

    if not _tablo_var(cur, 'nexgen_depo_hazirlik'):
        # batch_kodu: routes.py'deki tüm sorgular dh.batch_kodu kullanır (mig085 orijinal şema)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_depo_hazirlik (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                hazirlik_no         TEXT    NOT NULL UNIQUE,
                batch_kodu          TEXT    NOT NULL,
                plan_id             INTEGER,
                planlama_siparis_id INTEGER,
                cari_id             INTEGER,
                durum               TEXT    NOT NULL DEFAULT 'BEKLIYOR',
                hazirlayan_id       INTEGER,
                hazir_tarihi        TEXT,
                notlar              TEXT,
                olusturan_id        INTEGER,
                olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
                guncelleme_tarihi   TEXT
            )
        """)
        _create_index(cur, con, 'idx_ndh_batch', 'nexgen_depo_hazirlik(batch_kodu)')
        _create_index(cur, con, 'idx_ndh_durum', 'nexgen_depo_hazirlik(durum)')
        con.commit()
        created.append('nexgen_depo_hazirlik')

    if not _tablo_var(cur, 'nexgen_depo_hazirlik_kalem'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_depo_hazirlik_kalem (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                hazirlik_id     INTEGER NOT NULL REFERENCES nexgen_depo_hazirlik(id),
                stok_kart_id    INTEGER NOT NULL,
                kaynak          TEXT    NOT NULL,
                gerekli_kg      REAL    NOT NULL,
                hazirlanan_kg   REAL    NOT NULL DEFAULT 0
            )
        """)
        _create_index(cur, con, 'idx_ndhk_hazirlik', 'nexgen_depo_hazirlik_kalem(hazirlik_id)')
        con.commit()
        created.append('nexgen_depo_hazirlik_kalem')

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('085', 'depo hazirlik')")
    con.commit()
    log.append(f"{tag} {'OLUŞTURULDU: '+', '.join(created) if created else 'OK'}")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 086 — nexgen_stok_rezerv
# ──────────────────────────────────────────────────────────────────────────────
def mig086(cur, con, log):
    tag = "[086]"
    if not _tablo_var(cur, 'nexgen_stok_rezerv'):
        # rezerv_no, batch_kodu, miktar_kg, kalan_kg: mig086 orijinal şeması
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_stok_rezerv (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                rezerv_no           TEXT    NOT NULL UNIQUE,
                stok_kart_id        INTEGER NOT NULL,
                kaynak_tip          TEXT,
                kaynak_id           INTEGER,
                hazirlik_id         INTEGER,
                batch_kodu          TEXT    NOT NULL,
                plan_id             INTEGER,
                planlama_siparis_id INTEGER,
                cari_id             INTEGER,
                miktar_kg           REAL    NOT NULL,
                kalan_kg            REAL    NOT NULL,
                durum               TEXT    NOT NULL DEFAULT 'AKTIF',
                olusturan_id        INTEGER,
                olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
                kapanis_tarihi      TEXT,
                notlar              TEXT
            )
        """)
        _create_index(cur, con, 'idx_nsr_stok_durum', 'nexgen_stok_rezerv(stok_kart_id, durum)')
        _create_index(cur, con, 'idx_nsr_batch',      'nexgen_stok_rezerv(batch_kodu)')
        _create_index(cur, con, 'idx_nsr_hazirlik',   'nexgen_stok_rezerv(hazirlik_id)')
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('086', 'stok rezerv')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_stok_rezerv")
    else:
        log.append(f"{tag} OK ({_say(cur, 'nexgen_stok_rezerv')} rezerv)")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 088-089 — nexgen_uretim_plan_boyut (+ rebuild fix)
# ──────────────────────────────────────────────────────────────────────────────
def mig088_089(cur, con, log):
    tag = "[088-089]"
    if not _tablo_var(cur, 'nexgen_uretim_plan_boyut'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_uretim_plan_boyut (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id             INTEGER NOT NULL,
                uretim_varyant_id   INTEGER NOT NULL,
                boyut               TEXT NOT NULL,
                siparis_kg          REAL NOT NULL DEFAULT 0,
                formul_batch_kg     REAL DEFAULT 0,
                batch_sayisi        INTEGER DEFAULT 0,
                uretilecek_kg       REAL DEFAULT 0,
                fazla_kg            REAL DEFAULT 0,
                sira                INTEGER DEFAULT 0,
                aktif               INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
                guncelleme_tarihi   TEXT,
                UNIQUE(plan_id, uretim_varyant_id)
            )
        """)
        _create_index(cur, con, 'idx_nupb_plan_id', 'nexgen_uretim_plan_boyut(plan_id)')
        _create_index(cur, con, 'idx_nupb_uv_id',   'nexgen_uretim_plan_boyut(uretim_varyant_id)')
        con.commit()
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('088', 'uretim plan boyut')")
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES('089', 'plan boyut unique fix')")
        con.commit()
        log.append(f"{tag} OLUŞTURULDU nexgen_uretim_plan_boyut")
    else:
        for v in ('088', '089'):
            cur.execute(f"INSERT OR IGNORE INTO schema_migrations(version) VALUES('{v}')")
        con.commit()
        log.append(f"{tag} OK ({_say(cur, 'nexgen_uretim_plan_boyut')} satır)")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 090 — nexgen_arge_revizyon + aktif_rev_no (MODÜL-04)
# ──────────────────────────────────────────────────────────────────────────────
def mig090(cur, con, log):
    """MODÜL-04: revizyon tablosu ve aktif_rev_no kolonunu tesis eder."""
    import os as _os, sys as _sys, json as _json
    from datetime import datetime as _dt
    tag = "[090]"

    changed = False

    # aktif_rev_no
    if not _kolon_var(cur, 'nexgen_arge_test', 'aktif_rev_no'):
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN aktif_rev_no INTEGER DEFAULT 0')
        con.commit()
        log.append(f"{tag} nexgen_arge_test.aktif_rev_no eklendi.")
        changed = True

    # basarili alanlar
    for kolon, tip in [
        ('basarili_mi', 'INTEGER DEFAULT 0'),
        ('basarili_yapan_id', 'INTEGER'),
        ('basarili_yapan_adi', 'TEXT'),
        ('basarili_tarihi', 'TEXT'),
    ]:
        if not _kolon_var(cur, 'nexgen_arge_test', kolon):
            cur.execute(f'ALTER TABLE nexgen_arge_test ADD COLUMN {kolon} {tip}')
            con.commit()
            log.append(f"{tag} nexgen_arge_test.{kolon} eklendi.")
            changed = True

    # revizyon tablosu
    if not _tablo_var(cur, 'nexgen_arge_revizyon'):
        cur.execute("""
            CREATE TABLE nexgen_arge_revizyon (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id             INTEGER NOT NULL,
                rev_no              INTEGER NOT NULL,
                onceki_rev_no       INTEGER,
                neden               TEXT,
                ne_degisti          TEXT,
                revizyon_notu       TEXT,
                snapshot_json       TEXT NOT NULL DEFAULT '{}',
                degisiklik_json     TEXT NOT NULL DEFAULT '[]',
                olusturan_id        INTEGER,
                olusturan_adi       TEXT,
                olusturma_tarihi    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                basarili_mi         INTEGER NOT NULL DEFAULT 0,
                basarili_yapan_id   INTEGER,
                basarili_yapan_adi  TEXT,
                basarili_tarihi     TEXT,
                kilitli_mi          INTEGER NOT NULL DEFAULT 0,
                UNIQUE(test_id, rev_no),
                FOREIGN KEY(test_id) REFERENCES nexgen_arge_test(id)
            )
        """)
        _create_index(cur, con, 'idx_arge_rev_test_id', 'nexgen_arge_revizyon(test_id)')
        con.commit()
        log.append(f"{tag} nexgen_arge_revizyon tablosu oluşturuldu.")
        changed = True

    # REV-0 seed — mevcut testler için idempotent
    SNAP_ALANLAR = [
        'kaynak_uretim_varyant_id', 'test_no', 'test_tipi', 'makina',
        'test_batch_kg', 'kaynak_batch_kg', 'yeni_renk_adi', 'notlar',
        'durum', 'sonuc_notu', 'renk_tuttu', 'shore_degeri',
        'kopurme_notu', 'cekme_problemi', 'genel_aciklama',
        'olusturan_id', 'olusturma_tarihi',
        'onaylayan_id', 'onay_tarihi', 'onay_notu',
        'cari_id', 'shore_hedef', 'lot_no', 'talep_referansi',
        'rf_renk_id', 'arge_kodu', 'numune_orani', 'renk_bilesenleri_json',
        'olusan_uretim_varyant_id', 'olusan_renk_varyant_id', 'aktif',
    ]
    mevcut_kolonlar = [r[1] for r in cur.execute('PRAGMA table_info(nexgen_arge_test)').fetchall()]
    snap_alanlar = [a for a in SNAP_ALANLAR if a in mevcut_kolonlar]
    testler = cur.execute('SELECT id FROM nexgen_arge_test').fetchall()
    rev0_n = 0
    for (test_id,) in testler:
        var = cur.execute(
            'SELECT 1 FROM nexgen_arge_revizyon WHERE test_id=? AND rev_no=0', (test_id,)
        ).fetchone()
        if var:
            continue
        row = cur.execute(
            f'SELECT {", ".join(snap_alanlar)} FROM nexgen_arge_test WHERE id=?', (test_id,)
        ).fetchone()
        if not row:
            continue
        snapshot = dict(zip(snap_alanlar, row))
        olusturma = snapshot.get('olusturma_tarihi') or _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute("""
            INSERT INTO nexgen_arge_revizyon
                (test_id, rev_no, onceki_rev_no, neden, ne_degisti, revizyon_notu,
                 snapshot_json, degisiklik_json,
                 olusturan_id, olusturan_adi, olusturma_tarihi, basarili_mi, kilitli_mi)
            VALUES (?, 0, NULL, 'ilk_kayit', '[]', 'İlk kayıt', ?, '[]',
                    ?, NULL, ?, 0, 0)
        """, (test_id, _json.dumps(snapshot, ensure_ascii=False),
              snapshot.get('olusturan_id'), olusturma))
        rev0_n += 1

    if rev0_n:
        con.commit()
        log.append(f"{tag} {rev0_n} test için REV-0 oluşturuldu.")
        changed = True

    cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES('090')")
    con.commit()

    if not changed:
        log.append(f"{tag} OK — değişiklik yok.")
    return changed


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — TABLO RAPORU
# ──────────────────────────────────────────────────────────────────────────────
TABLO_MAP = [
    # (tablo_adi, kritik_kolonlar, hangi_ekran)
    ('nexgen_stok_kart',          ['id','kod','ad','kategori','aktif','renk_bileseni_mi'],
     'Stok Listesi, MODÜL-01/02/03'),
    ('nexgen_stok_hareket',       ['id','stok_kart_id','hareket_tipi','miktar_kg'],
     'Stok Hareketleri'),
    ('nexgen_tedarikci',          ['id','kod','ad','aktif'],
     'Satınalma'),
    ('nexgen_satin_siparis',      ['id','siparis_no','tedarikci_id','stok_kart_id'],
     'Satınalma'),
    ('nexgen_fiyat_batch',        ['id','durum'],
     'Fiyat Yönetimi'),
    ('nexgen_fiyat_batch_detay',  ['id','batch_id','stok_kart_id'],
     'Fiyat Yönetimi'),
    ('nexgen_hammadde_fiyat',     ['id','stok_kart_id','aktif'],
     'Fiyat Yönetimi, Reçete Maliyet'),
    ('nexgen_mal_kabul',          ['id','stok_kart_id','miktar_kg'],
     'Depo / Mal Kabul'),
    ('nexgen_formul',             ['id','kod','ad','durum','aktif'],
     'MODÜL-01/02/03, Reçete Ekranı'),
    ('nexgen_renk_varyant',       ['id','formul_id','kod','ad'],
     'MODÜL-01/02, Reçete Ekranı'),
    ('nexgen_uretim_varyant',     ['id','renk_varyant_id','boyut','aktif'],
     'MODÜL-01/02, MPR'),
    ('nexgen_recete_kalem',       ['id','uretim_varyant_id','stok_kart_id','miktar_kg'],
     'MODÜL-01, Reçete Detay'),
    ('nexgen_arge_test',          ['id','kaynak_uretim_varyant_id','arge_kodu','rf_renk_id','aktif_rev_no'],
     'MODÜL-01/02/04'),
    ('nexgen_arge_revizyon',      ['id','test_id','rev_no','snapshot_json','olusturma_tarihi'],
     'MODÜL-04 Revizyon Geçmişi'),
    ('nexgen_arge_test_kalem',    ['id','test_id','stok_kart_id'],
     'MODÜL-01/02'),
    ('nexgen_rf_renk',            ['id','rf_kod','ad','aktif'],
     'MODÜL-01/02, RF Seçimi'),
    ('nexgen_rf_kalem',           ['id','rf_renk_id','stok_kart_id','miktar_kg'],
     'MODÜL-01, RF Hesaplama'),
    ('nexgen_rf_formul_uygunluk', ['id','rf_renk_id','formul_id'],
     'MODÜL-01, RF Seçim Filtresi'),
    ('nexgen_rf_kullanim',        ['id','rf_renk_id'],
     'RF Kullanım Takibi'),
    ('nexgen_arge_formul',        ['id','arge_kodu','formul_adi','durum'],
     'MODÜL-03'),
    ('nexgen_arge_formul_kalem',  ['id','arge_formul_id','stok_kart_id'],
     'MODÜL-03'),
    ('nexgen_cari',               ['id','cari_kod','unvan','aktif'],
     'Tüm modüller (cari seçimi)'),
    ('nexgen_uretim_plan',        ['id','plan_kodu','uretim_varyant_id','durum'],
     'MPR / Üretim Planlama'),
    ('nexgen_planlama_siparis',   ['id','siparis_no'],
     'MPR Sipariş Header'),
    ('nexgen_uretim_batch',       ['id','batch_kodu','uretim_varyant_id','durum'],
     'Tablet Batch'),
    ('nexgen_uretim_parca',       ['id','batch_id','batch_kodu','parca_no','durum'],
     'Parça Takip'),
    ('nexgen_depo_hazirlik',      ['id','hazirlik_no','batch_kodu','durum'],
     'Depo Hazırlık'),
    ('nexgen_depo_hazirlik_kalem',['id','hazirlik_id'],
     'Depo Hazırlık Kalem'),
    ('nexgen_stok_rezerv',        ['id','rezerv_no','stok_kart_id','batch_kodu','miktar_kg','durum'],
     'Stok Rezerv'),
    ('nexgen_uretim_plan_boyut',  ['id','plan_id','uretim_varyant_id','boyut'],
     'MPR Boyut Satırları'),
    ('nexgen_recete_recycle_izin',['id','uretim_varyant_id'],
     'Recycle İzin'),
    ('nexgen_arge_etiket',        ['id','arge_kayit_id','revizyon_id','barkod_kodu','numune_no'],
     'MODÜL-05 AR-GE Numune Etiketi'),
    ('nexgen_arge_etiket_yazdirma',['id','etiket_id','barkod_kodu'],
     'MODÜL-05 Yazdırma Logu'),
    ('nexgen_print_job',          ['id','etiket_id','payload_base64','status','requested_at','print_token'],
     'Print Agent — Doğrudan Yazıcı Baskı Kuyruğu'),
]

SEED_KONTROL = [
    # (tablo, açıklama, min_kayıt)
    ('nexgen_stok_kart',      'Hammadde / stok kartları',  1),
    ('nexgen_cari',           'Cari / müşteri kayıtları',  1),
    ('nexgen_formul',         'Ana formül kayıtları',       1),
    ('nexgen_rf_renk',        'RF renk havuzu',             1),
    ('nexgen_hammadde_fiyat', 'Hammadde fiyat listesi',     1),
]


def step3_rapor(cur, log):
    log.append("")
    log.append("=" * 70)
    log.append("TABLO DURUM RAPORU")
    log.append("=" * 70)

    eksik_tablo = []
    eksik_kolon = []
    veri_eksik  = []

    for tablo, kritik_kolonlar, ekran in TABLO_MAP:
        var = _tablo_var(cur, tablo)
        if not var:
            eksik_tablo.append(tablo)
            log.append(f"  ✗ EKSİK    {tablo:<40} | {ekran}")
            continue
        say = _say(cur, tablo)
        mevcut_kolon = [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]
        eksik_k = [k for k in kritik_kolonlar if k not in mevcut_kolon]
        if eksik_k:
            eksik_kolon.append((tablo, eksik_k))
            log.append(f"  ! KOLON    {tablo:<40} | {say:>5} kayıt | EKSİK: {eksik_k}")
        else:
            log.append(f"  ✓ OK       {tablo:<40} | {say:>5} kayıt | {ekran}")

    # Seed kontrolü
    log.append("")
    log.append("--- VERİ KONTROL ---")
    for tablo, aciklama, min_k in SEED_KONTROL:
        if not _tablo_var(cur, tablo):
            continue
        say = _say(cur, tablo)
        if say < min_k:
            veri_eksik.append((tablo, aciklama))
            log.append(f"  VERİ EKSİK  {tablo:<30} ({say} kayıt) — {aciklama}")
        else:
            log.append(f"  VERİ OK     {tablo:<30} ({say} kayıt) — {aciklama}")

    # Schema_migrations durumu
    log.append("")
    log.append("--- SCHEMA_MIGRATIONS ---")
    try:
        mig_list = cur.execute(
            "SELECT version FROM schema_migrations ORDER BY CAST(version AS INTEGER)"
        ).fetchall()
        versions = [r[0] for r in mig_list]
        log.append(f"  Kayıtlı migration sayısı: {len(versions)}")
        log.append(f"  Versiyonlar: {', '.join(versions)}")
    except Exception as e:
        log.append(f"  HATA schema_migrations: {e}")

    return eksik_tablo, eksik_kolon, veri_eksik


# ──────────────────────────────────────────────────────────────────────────────
# MIG 091 — Vedat AR-GE kullanicisi + AR-GE Operatoru rolu
# ──────────────────────────────────────────────────────────────────────────────
def mig091(cur, con, log):
    """Vedat sistem_kullanici + AR-GE Operatoru rolu + nexgen.tablet.view yetkisi."""
    from datetime import datetime as _dt
    tag = "[091]"
    simdi = _dt.now().strftime('%Y-%m-%d %H:%M:%S')

    ROL_ID   = 42
    ROL_AD   = 'AR-GE Operatoru'
    ROL_ACIK = 'NexGen AR-GE tablet operatoru. Formul testi, revizyon, renk denemesi.'
    ROL_RENK = '#0891b2'
    YETKI_KODLAR = ['nexgen.view', 'nexgen.tablet.view', 'nexgen.recete.view', 'tasks']
    VEDAT_KADI   = 'vedat'
    VEDAT_ADSOYAD = 'Vedat (AR-GE)'
    VEDAT_EMAIL   = 'vedat@solariz.com.tr'
    VEDAT_SIFRE   = '147258'
    VEDAT_TIP     = 'sistem'

    # Rol
    mevcut_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Id=?", (ROL_ID,)).fetchone()
    if not mevcut_rol:
        cur.execute("""
            INSERT INTO sistem_rol(Id,Ad,Aciklama,Renk,Aktif,SuperAdmin,OlusturmaTarih,OlusturanKullanici)
            VALUES(?,?,?,?,1,0,?,'migration_091')
        """, (ROL_ID, ROL_AD, ROL_ACIK, ROL_RENK, simdi))
        con.commit()
        log.append(f"  {tag} sistem_rol {ROL_ID} olusturuldu.")

    # Yetki atamalari
    for kod in YETKI_KODLAR:
        yr = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not yr:
            continue
        yid = yr['Id']
        if not cur.execute("SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?", (ROL_ID, yid)).fetchone():
            cur.execute("""
                INSERT INTO sistem_rol_yetki
                    (RolId,YetkiId,Gorebilir,Duzenleyebilir,
                     can_view,can_create,can_update,can_delete,can_approve,can_report,can_manage)
                VALUES(?,?,1,1,1,1,1,0,0,1,0)
            """, (ROL_ID, yid))
    con.commit()

    # sistem_kullanici
    sk = cur.execute("SELECT Id FROM sistem_kullanici WHERE KullaniciAdi=?", (VEDAT_KADI,)).fetchone()
    if not sk:
        cur.execute("""
            INSERT INTO sistem_kullanici
                (KullaniciAdi,AdSoyad,Email,Sifre,RolId,Rol,
                 Aktif,ZorunluSifreDegistir,OlusturmaTarih,OlusturanKullanici,Tip)
            VALUES(?,?,?,?,?,?,1,0,?,'migration_091',?)
        """, (VEDAT_KADI, VEDAT_ADSOYAD, VEDAT_EMAIL, VEDAT_SIFRE, ROL_ID, ROL_AD, simdi, VEDAT_TIP))
        con.commit()
        vedat_id = cur.lastrowid
        log.append(f"  {tag} sistem_kullanici 'vedat' olusturuldu Id={vedat_id}")
    else:
        vedat_id = sk['Id']
        log.append(f"  {tag} sistem_kullanici 'vedat' mevcut Id={vedat_id}")

    # kullanici_profil
    profil = cur.execute(
        "SELECT id FROM kullanici_profil WHERE kaynak='sistem_kullanici' AND kaynak_id=?", (vedat_id,)
    ).fetchone()
    if not profil:
        p2 = cur.execute("SELECT id FROM kullanici_profil WHERE kullanici_adi=?", (VEDAT_KADI,)).fetchone()
        if not p2:
            cur.execute("""
                INSERT INTO kullanici_profil
                    (gercek_ad,kullanici_adi,departman,unvan,profil_tipi,aktif,kaynak,kaynak_id,created_at)
                VALUES(?,?,?,?,?,1,?,?,?)
            """, (VEDAT_ADSOYAD, VEDAT_KADI, 'AR-GE', 'AR-GE Operatoru', 'calisan',
                  'sistem_kullanici', vedat_id, simdi))
            con.commit()
            log.append(f"  {tag} kullanici_profil 'vedat' olusturuldu.")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 092 — nexgen_arge_etiket + nexgen_arge_etiket_yazdirma (MODÜL-05 FAZ-1)
# Merkezi kaynak: app/migrations/092_nexgen_arge_etiket.py
# ──────────────────────────────────────────────────────────────────────────────
def mig092(cur, con, log):
    """Merkezi migration dosyasini cagir — tek kaynak prensibi."""
    import sys, os
    _mig_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    if _mig_dir not in sys.path:
        sys.path.insert(0, _mig_dir)
    from importlib import import_module
    m = import_module('092_nexgen_arge_etiket')
    m.mig092(cur, con, log)


# ──────────────────────────────────────────────────────────────────────────────
# MIG 093 — nexgen_print_job (NexGen Print Agent FAZ-1)
# Merkezi kaynak: app/migrations/093_nexgen_print_job.py
# ──────────────────────────────────────────────────────────────────────────────
def mig093(cur, con, log):
    """Merkezi migration dosyasini cagir — tek kaynak prensibi.

    Schema drift tespiti:
      - schema_migrations kaydı VAR ama nexgen_print_job tablosu YOK
        → drift olarak raporla, migration yeniden uygula
      - Her iki durum da mig093 fonksiyonuna bırakılır (idempotent)
    """
    import sys, os
    _mig_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    _mig_dir = os.path.normpath(_mig_dir)
    if _mig_dir not in sys.path:
        sys.path.insert(0, _mig_dir)
    from importlib import import_module

    # Drift tespiti: kayıt var ama tablo yok mu?
    _kayit_var = cur.execute(
        "SELECT version FROM schema_migrations WHERE version = '093'"
    ).fetchone() is not None
    _tablo_var = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone() is not None

    if _kayit_var and not _tablo_var:
        log.append("[093] SCHEMA DRIFT: schema_migrations kaydı var ama nexgen_print_job tablosu yok!")
        log.append("[093] schema_migrations kaydı siliniyor — migration yeniden uygulanacak.")
        cur.execute("DELETE FROM schema_migrations WHERE version = '093'")
        con.commit()

    # Her durumda mig093 çalıştır (idempotent)
    m = import_module('093_nexgen_print_job')
    m.mig093(cur, con, log)

    # Son doğrulama: tablo gerçekten oluştu mu?
    _dogrulama = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone()
    if _dogrulama:
        _kolonlar = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_print_job)").fetchall()]
        log.append(f"[093] Doğrulama OK — kolonlar: {', '.join(_kolonlar)}")
    else:
        raise RuntimeError("[093] KRITIK: mig093 çalıştı ama nexgen_print_job tablosu oluşmadı!")


# ──────────────────────────────────────────────────────────────────────────────
# MIG 094 — nexgen_print_job.print_token (Android Print Bridge)
# Merkezi kaynak: app/migrations/094_print_job_token.py
# ──────────────────────────────────────────────────────────────────────────────
def mig094(cur, con, log):
    """Android Print Bridge token kolonu — merkezi migration dosyasini cagir."""
    import sys, os
    _mig_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    _mig_dir = os.path.normpath(_mig_dir)
    if _mig_dir not in sys.path:
        sys.path.insert(0, _mig_dir)
    from importlib import import_module
    m = import_module('094_print_job_token')
    m.mig094(cur, con, log)



def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    log = []

    print("=" * 70)
    print("  NexGen DB Audit & Repair")
    print(f"  Tarih : {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"  DB    : {DB_PATH}")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"\nHATA: DB bulunamadı: {DB_PATH}")
        return

    # STEP 0: Backup
    print("\n[STEP 0] Backup alınıyor...")
    bak = step0_backup(log)

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")  # migration süresince FK kapat
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # STEP 1: schema_migrations
    print("\n[STEP 1] Schema migrations tablosu...")
    step1_schema_migrations(cur, con, log)

    # STEP 2: Migration'lar (bağımlılık sırasıyla)
    print("\n[STEP 2] Migration'lar çalıştırılıyor...")
    steps = [
        ("MIG 047 — stok_kart + stok_hareket",      lambda: mig047(cur, con, log)),
        ("MIG 048 — stok_kart opsiyonel kolonlar",   lambda: mig048(cur, con, log)),
        ("MIG 049 — tedarikci + satin_siparis",      lambda: mig049(cur, con, log)),
        ("MIG 056 — fiyat tabloları",                lambda: mig056(cur, con, log)),
        ("MIG 057-059 — fiyat kaynak kolonlar",      lambda: mig057_059(cur, con, log)),
        ("MIG 060 — mal_kabul",                      lambda: mig060(cur, con, log)),
        ("MIG 062 — formul/varyant/recete",          lambda: mig062(cur, con, log)),
        ("MIG 064 — arge_test",                      lambda: mig064(cur, con, log)),
        ("MIG 065-068 — arge_test/batch kolonlar",   lambda: mig065_068(cur, con, log)),
        ("MIG 069 — uretim_plan",                    lambda: mig069(cur, con, log)),
        ("MIG 070 — cari",                           lambda: mig070(cur, con, log)),
        ("MIG 071-073 — batch/parca/formul_kg",      lambda: mig071_073(cur, con, log)),
        ("MIG 074-077 — arge_test kolon eklemeleri", lambda: mig074_077(cur, con, log)),
        ("MIG 076-RF — rf_renk/kalem/uygunluk",      lambda: mig076_rf(cur, con, log)),
        ("MIG 079 — stok kimlik kolonları",          lambda: mig079(cur, con, log)),
        ("MIG 080 — arge_formul",                    lambda: mig080(cur, con, log)),
        ("MIG 081 — view siparis_kontrol",           lambda: mig081(cur, con, log)),
        ("MIG 082-083 — plan kolon kayıtları",       lambda: mig082_083(cur, con, log)),
        ("MIG 084 — planlama_siparis",               lambda: mig084(cur, con, log)),
        ("MIG 085 — depo_hazirlik",                  lambda: mig085(cur, con, log)),
        ("MIG 086 — stok_rezerv",                    lambda: mig086(cur, con, log)),
        ("MIG 088-089 — uretim_plan_boyut",          lambda: mig088_089(cur, con, log)),
        ("MIG 090 — arge_revizyon (MODÜL-04)",        lambda: mig090(cur, con, log)),
        ("MIG 091 — vedat arge kullanici",             lambda: mig091(cur, con, log)),
        ("MIG 092 — nexgen_arge_etiket (MODÜL-05)",   lambda: mig092(cur, con, log)),
        ("MIG 093 — nexgen_print_job (Print Agent)",  lambda: mig093(cur, con, log)),
        ("MIG 094 — print_token (Android Bridge)",     lambda: mig094(cur, con, log)),
    ]

    for aciklama, fn in steps:
        try:
            print(f"  {aciklama}...", end=" ")
            fn()
            print("✓")
        except Exception as e:
            print(f"HATA: {e}")
            log.append(f"  HATA {aciklama}: {e}")

    # FK'ları tekrar aç
    con.execute("PRAGMA foreign_keys=ON")

    # STEP 3: Rapor
    print("\n[STEP 3] Tablo durumu raporlanıyor...")
    eksik_tablo, eksik_kolon, veri_eksik = step3_rapor(cur, log)

    # ÖZET
    log.append("")
    log.append("=" * 70)
    log.append("ÖZET")
    log.append("=" * 70)
    log.append(f"  Backup         : {os.path.basename(bak)}")
    log.append(f"  Eksik tablo    : {len(eksik_tablo)}")
    log.append(f"  Eksik kolon    : {len(eksik_kolon)}")
    log.append(f"  Veri eksik     : {len(veri_eksik)}")

    if eksik_tablo:
        log.append(f"\n  UYARI — Repair sonrası hâlâ eksik tablolar:")
        for t in eksik_tablo:
            log.append(f"    - {t}")
    if eksik_kolon:
        log.append(f"\n  UYARI — Eksik kolon(lar):")
        for t, k in eksik_kolon:
            log.append(f"    - {t}: {k}")
    if veri_eksik:
        log.append(f"\n  VERİ EKSİK (hata değil, import gerekiyor):")
        for t, a in veri_eksik:
            log.append(f"    - {t}: {a}")

    if not eksik_tablo and not eksik_kolon:
        log.append("\n  ✓ TÜM TABLOLAR VE KRİTİK KOLONLAR TAMAM.")

    log.append("")
    log.append(f"Rapor: reports/nexgen_db_repair_{ts}.txt")

    # Konsol özet
    print("\n" + "=" * 70)
    print("ÖZET")
    print("=" * 70)
    for satir in log[-20:]:
        print(satir)

    con.close()

    # Dosyaya kaydet
    os.makedirs(REPORTS_DIR, exist_ok=True)
    rpt_path = os.path.join(REPORTS_DIR, f'nexgen_db_repair_{ts}.txt')
    with open(rpt_path, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(log))
    print(f"\nRapor kaydedildi: {rpt_path}")
    print("Repair tamamlandı.")


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
132_finans_f1_core_database.py
================================
FAZ-FINANS-F1-CORE-DATABASE-IMPLEMENTATION-1

NexGen finans çekirdek DB temeli:
- finans_cari_kart
- finans_belgesi genişletme (ALTER, mevcut kayıt korunur)
- finans_belge_satir
- finans_hareket (Cari_Har metadata — ikinci defter değil)
- finans_open_item
- finans_audit
- Cari_Har kaynak kolonları (nullable, legacy uyum)

Backfill YOK. Cari_Har satırı oluşturulmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 132

# finans_belgesi — yeni nullable kolonlar (F1 çekirdek)
FB_YENI_KOLONLAR: tuple[tuple[str, str], ...] = (
    ('kaynak_sistem', 'TEXT'),
    ('olay_turu', 'TEXT'),
    ('olay_versiyonu', 'INTEGER'),
    ('kur', 'NUMERIC'),
    ('yerel_para_tutari', 'NUMERIC'),
    ('ters_belge_id', 'INTEGER'),
    ('orijinal_belge_id', 'INTEGER'),
    ('onaylayan_2_id', 'INTEGER'),
    ('dort_goz_bypass', 'INTEGER DEFAULT 0'),
    ('mal_kabul_id', 'INTEGER'),
    ('versiyon', 'INTEGER DEFAULT 1'),
)

# Cari_Har — nullable NexGen kaynak kolonları
CH_YENI_KOLONLAR: tuple[tuple[str, str], ...] = (
    ('kaynak_sistem', 'TEXT'),
    ('kaynak_id', 'INTEGER'),
    ('olusturma_tarihi', 'TEXT'),
    ('olusturan_id', 'INTEGER'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,),
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    if not _table_exists(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _ensure_finans_cari_kart(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_cari_kart'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_cari_kart — zaten var')
        return
    con.executescript("""
        CREATE TABLE finans_cari_kart (
            ckod                    TEXT PRIMARY KEY
                                    REFERENCES Cari_Kart(CKod) ON DELETE RESTRICT,
            unvan                   TEXT NOT NULL,
            tip                     TEXT NOT NULL
                                    CHECK (tip IN ('MUSTERI', 'TEDARIKCI', 'HER_IKISI')),
            para_birimi             TEXT NOT NULL DEFAULT 'TRY',
            aktif                   INTEGER NOT NULL DEFAULT 1
                                    CHECK (aktif IN (0, 1)),
            varsayilan_vade_gun     INTEGER,
            varsayilan_odeme_sekli  TEXT
                                    CHECK (varsayilan_odeme_sekli IS NULL OR varsayilan_odeme_sekli IN (
                                        'NAKIT', 'EFT', 'HAVALE', 'CEK', 'KART', 'MAHSUP'
                                    )),
            risk_limiti             NUMERIC,
            kredi_limiti            NUMERIC,
            vergi_no                TEXT,
            vergi_dairesi           TEXT,
            versiyon                INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            olusturan_id            INTEGER,
            guncelleyen_id          INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_fck_tip_aktif
            ON finans_cari_kart(tip, aktif);
        CREATE INDEX IF NOT EXISTS idx_fck_vergi_no
            ON finans_cari_kart(vergi_no)
            WHERE vergi_no IS NOT NULL;
    """)
    log(f'[{MIGRATION_VERSION}] finans_cari_kart created')


def _ensure_finans_belgesi_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'finans_belgesi'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_belgesi kolon — tablo yok')
        return
    for kolon, tip in FB_YENI_KOLONLAR:
        if _kolon_var(con, 'finans_belgesi', kolon):
            continue
        con.execute(f'ALTER TABLE finans_belgesi ADD COLUMN {kolon} {tip}')
        log(f'[{MIGRATION_VERSION}] finans_belgesi +{kolon}')


def _ensure_cari_har_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'Cari_Har'):
        log(f'[{MIGRATION_VERSION}] SKIP Cari_Har kolon — tablo yok')
        return
    for kolon, tip in CH_YENI_KOLONLAR:
        if _kolon_var(con, 'Cari_Har', kolon):
            continue
        con.execute(f'ALTER TABLE Cari_Har ADD COLUMN {kolon} {tip}')
        log(f'[{MIGRATION_VERSION}] Cari_Har +{kolon}')


def _ensure_finans_audit(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_audit'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_audit — zaten var')
        return
    con.executescript("""
        CREATE TABLE finans_audit (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            islem_turu              TEXT NOT NULL,
            entity_tipi             TEXT NOT NULL,
            entity_id               INTEGER NOT NULL,
            kaynak_belge_id         INTEGER,
            onceki_durum            TEXT,
            yeni_durum              TEXT,
            eski_degerler_json      TEXT NOT NULL DEFAULT '{}',
            yeni_degerler_json      TEXT NOT NULL DEFAULT '{}',
            kullanici_id            INTEGER,
            rol_kodu                TEXT,
            islem_zamani            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            gerekce                 TEXT,
            onaylayan_id            INTEGER,
            idempotency_key         TEXT,
            transaction_id          TEXT,
            terslenen_kayit_id      INTEGER,
            override_id             INTEGER,
            istemci_bilgisi         TEXT,
            dort_goz_bypass         INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_fa_entity_zaman
            ON finans_audit(entity_tipi, entity_id, islem_zamani);
        CREATE INDEX IF NOT EXISTS idx_fa_transaction
            ON finans_audit(transaction_id)
            WHERE transaction_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_fa_zaman
            ON finans_audit(islem_zamani);
    """)
    log(f'[{MIGRATION_VERSION}] finans_audit created')


def _ensure_finans_belge_satir(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_belge_satir'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_belge_satir — zaten var')
        return
    con.executescript("""
        CREATE TABLE finans_belge_satir (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            finans_belgesi_id       INTEGER NOT NULL
                                    REFERENCES finans_belgesi(id) ON DELETE RESTRICT,
            satir_no                INTEGER NOT NULL,
            satir_tipi              TEXT NOT NULL DEFAULT 'URUN'
                                    CHECK (satir_tipi IN (
                                        'URUN', 'HIZMET', 'MASRAF', 'ISKONTO', 'KDV', 'YUVARLAMA'
                                    )),
            aciklama                TEXT,
            miktar                  NUMERIC,
            birim                   TEXT,
            birim_fiyat             NUMERIC,
            iskonto_orani           NUMERIC,
            kdv_orani               NUMERIC,
            tutar                   NUMERIC NOT NULL,
            yerel_para_tutari       NUMERIC,
            para_birimi             TEXT NOT NULL DEFAULT 'TRY',
            kaynak_kalem_tipi       TEXT
                                    CHECK (kaynak_kalem_tipi IS NULL OR kaynak_kalem_tipi IN (
                                        'SEVKIYAT_KALEM', 'SIPARIS_KALEM', 'MAL_KABUL', 'MANUEL'
                                    )),
            kaynak_kalem_id         INTEGER,
            siparis_kalem_id        INTEGER,
            sevkiyat_kalem_id       INTEGER,
            mal_kabul_satir_id      INTEGER,
            open_item_id            INTEGER,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE (finans_belgesi_id, satir_no)
        );
        CREATE INDEX IF NOT EXISTS idx_fbs_belge
            ON finans_belge_satir(finans_belgesi_id, satir_no);
    """)
    log(f'[{MIGRATION_VERSION}] finans_belge_satir created')


def _ensure_finans_open_item(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_open_item'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_open_item — zaten var')
        return
    con.executescript("""
        CREATE TABLE finans_open_item (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            ckod                        TEXT NOT NULL
                                        REFERENCES finans_cari_kart(ckod) ON DELETE RESTRICT,
            finans_belgesi_id           INTEGER NOT NULL
                                        REFERENCES finans_belgesi(id) ON DELETE RESTRICT,
            finans_belge_satir_id       INTEGER
                                        REFERENCES finans_belge_satir(id) ON DELETE SET NULL,
            finans_odeme_plani_satir_id INTEGER,
            yon                         TEXT NOT NULL
                                        CHECK (yon IN ('BORC', 'ALACAK')),
            open_item_turu              TEXT NOT NULL DEFAULT 'STANDART'
                                        CHECK (open_item_turu IN (
                                            'STANDART', 'TAKSIT', 'DEKONT', 'KUR_FARKI'
                                        )),
            para_birimi                 TEXT NOT NULL DEFAULT 'TRY',
            yerel_para_birimi           TEXT NOT NULL DEFAULT 'TRY',
            orijinal_tutar              NUMERIC NOT NULL
                                        CHECK (orijinal_tutar >= 0),
            acik_tutar                  NUMERIC NOT NULL
                                        CHECK (acik_tutar >= 0),
            kapanan_tutar               NUMERIC NOT NULL DEFAULT 0
                                        CHECK (kapanan_tutar >= 0),
            vade_tarihi                 TEXT,
            durum                       TEXT NOT NULL DEFAULT 'ACIK'
                                        CHECK (durum IN (
                                            'ACIK', 'KISMI_KAPALI', 'KAPALI',
                                            'UYUSMAZLIK', 'IPTAL', 'TERS_ACILDI'
                                        )),
            versiyon                    INTEGER NOT NULL DEFAULT 1,
            kapanis_tarihi              TEXT,
            kaynak_open_item_id         INTEGER
                                        REFERENCES finans_open_item(id) ON DELETE SET NULL,
            idempotency_key             TEXT NOT NULL UNIQUE,
            olusturma_tarihi            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi           TEXT,
            CHECK (acik_tutar + kapanan_tutar <= orijinal_tutar + 0.001),
            CHECK (kapanan_tutar <= orijinal_tutar + 0.001)
        );
        CREATE INDEX IF NOT EXISTS idx_oi_ckod_durum_vade
            ON finans_open_item(ckod, durum, vade_tarihi);
        CREATE INDEX IF NOT EXISTS idx_oi_belge
            ON finans_open_item(finans_belgesi_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_oi_belge_satir_unique
            ON finans_open_item(finans_belgesi_id, finans_belge_satir_id)
            WHERE finans_belge_satir_id IS NOT NULL;
    """)
    log(f'[{MIGRATION_VERSION}] finans_open_item created')


def _ensure_finans_hareket(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_hareket'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_hareket — zaten var')
        return
    con.executescript("""
        CREATE TABLE finans_hareket (
            cari_har_id                 INTEGER PRIMARY KEY
                                        REFERENCES Cari_Har(Id) ON DELETE RESTRICT,
            ckod                        TEXT NOT NULL
                                        REFERENCES Cari_Kart(CKod) ON DELETE RESTRICT,
            finans_belgesi_id           INTEGER
                                        REFERENCES finans_belgesi(id) ON DELETE RESTRICT,
            finans_belge_satir_id       INTEGER
                                        REFERENCES finans_belge_satir(id) ON DELETE SET NULL,
            finans_open_item_id         INTEGER
                                        REFERENCES finans_open_item(id) ON DELETE SET NULL,
            kaynak_entity               TEXT NOT NULL
                                        CHECK (kaynak_entity IN (
                                            'FINANS_BELGESI', 'FINANS_TAHSILAT', 'FINANS_ODEME',
                                            'FINANS_MAHSUP', 'FINANS_AVANS', 'LEGACY', 'MANUEL'
                                        )),
            kaynak_entity_id            INTEGER,
            kaynak_sistem               TEXT NOT NULL DEFAULT 'NEXGEN'
                                        CHECK (kaynak_sistem IN ('NEXGEN', 'LEGACY', 'IMPORT')),
            islem_tipi                  TEXT NOT NULL,
            durum                       TEXT NOT NULL DEFAULT 'AKTIF'
                                        CHECK (durum IN ('AKTIF', 'IPTAL', 'TERS')),
            ters_cari_har_id            INTEGER
                                        REFERENCES Cari_Har(Id) ON DELETE RESTRICT,
            orijinal_cari_har_id        INTEGER
                                        REFERENCES Cari_Har(Id) ON DELETE RESTRICT,
            transaction_id              TEXT,
            idempotency_key             TEXT UNIQUE,
            audit_id                    INTEGER
                                        REFERENCES finans_audit(id) ON DELETE SET NULL,
            iptal_edildi                INTEGER NOT NULL DEFAULT 0
                                        CHECK (iptal_edildi IN (0, 1)),
            iptal_tarihi                TEXT,
            iptal_gerekce               TEXT,
            olusturma_tarihi            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            olusturan_id                INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_fh_ckod_tarih
            ON finans_hareket(ckod, olusturma_tarihi);
        CREATE INDEX IF NOT EXISTS idx_fh_belge
            ON finans_hareket(finans_belgesi_id)
            WHERE finans_belgesi_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_fh_open_item
            ON finans_hareket(finans_open_item_id)
            WHERE finans_open_item_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_fh_ters
            ON finans_hareket(ters_cari_har_id)
            WHERE ters_cari_har_id IS NOT NULL;
    """)
    log(f'[{MIGRATION_VERSION}] finans_hareket created')


def _ensure_finans_belgesi_indexes(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'finans_belgesi'):
        return
    specs = (
        (
            'idx_fb_ckod_durum',
            'CREATE INDEX IF NOT EXISTS idx_fb_ckod_durum ON finans_belgesi(cari_kart_ckod, durum)',
        ),
        (
            'idx_fb_ckod_tarih',
            'CREATE INDEX IF NOT EXISTS idx_fb_ckod_tarih ON finans_belgesi(cari_kart_ckod, islem_tarihi)',
        ),
        (
            'idx_fb_orijinal_belge',
            """
            CREATE INDEX IF NOT EXISTS idx_fb_orijinal_belge
            ON finans_belgesi(orijinal_belge_id)
            WHERE orijinal_belge_id IS NOT NULL
            """,
        ),
    )
    for name, sql in specs:
        if not _index_exists(con, name):
            con.execute(sql)
            log(f'[{MIGRATION_VERSION}] index {name}')


def verify_schema(con: sqlite3.Connection) -> list[str]:
    """Schema doğrulama — hata listesi döner (boş = OK)."""
    errors: list[str] = []
    required_tables = (
        'finans_cari_kart', 'finans_belge_satir', 'finans_hareket',
        'finans_open_item', 'finans_audit',
    )
    for t in required_tables:
        if not _table_exists(con, t):
            errors.append(f'missing_table:{t}')
    if _table_exists(con, 'finans_belgesi'):
        for kolon, _ in FB_YENI_KOLONLAR:
            if not _kolon_var(con, 'finans_belgesi', kolon):
                errors.append(f'missing_column:finans_belgesi.{kolon}')
    return errors


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] Finans F1 çekirdek DB')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'finans_cari_kart') and _table_exists(con, 'finans_audit'):
                errs = verify_schema(con)
                if not errs:
                    log(f'[{MIGRATION_VERSION}] SKIP — idempotent tam')
                    return
        con.execute('PRAGMA foreign_keys = ON')
        con.execute('BEGIN IMMEDIATE')
        _ensure_finans_cari_kart(con)
        _ensure_finans_belgesi_columns(con)
        _ensure_cari_har_columns(con)
        _ensure_finans_audit(con)
        _ensure_finans_belge_satir(con)
        _ensure_finans_open_item(con)
        _ensure_finans_hareket(con)
        _ensure_finans_belgesi_indexes(con)
        errs = verify_schema(con)
        if errs:
            raise RuntimeError(f'Schema verify FAIL: {errs}')
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — schema verify PASS')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

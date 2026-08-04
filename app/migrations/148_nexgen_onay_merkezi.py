# -*- coding: utf-8 -*-
"""
148_nexgen_onay_merkezi.py
=========================
FAZ-YONETIM-ONAY-MERKEZI-V1-OMURGA

- nexgen_onay genel onay omurgası
- MTT durum CHECK: + ONAY_BEKLIYOR
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 148
TABLO_ONAY = 'nexgen_onay'
TABLO_MTT = 'nexgen_musteri_temsilcisi_talep'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _mtt_has_onay_bekliyor(con) -> bool:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (TABLO_MTT,),
    ).fetchone()
    sql = (row[0] or '') if row else ''
    return 'ONAY_BEKLIYOR' in sql


def _create_onay(con: sqlite3.Connection) -> None:
    if _table_exists(con, TABLO_ONAY):
        log(f'[{MIGRATION_VERSION}] SKIP {TABLO_ONAY}')
        return
    con.execute(f"""
        CREATE TABLE {TABLO_ONAY} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            onay_no TEXT NOT NULL UNIQUE,
            kaynak_turu TEXT NOT NULL,
            kaynak_id INTEGER NOT NULL,
            onay_turu TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'ONAY_BEKLIYOR',
            olusturan_kullanici_id INTEGER NOT NULL,
            onaylayan_kullanici_id INTEGER,
            red_nedeni TEXT,
            aciklama TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            karar_tarihi TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            CHECK (durum IN (
                'ONAY_BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI', 'IPTAL'
            )),
            CHECK (kaynak_turu IN (
                'MUSTERI_TEMSILCISI_TALEP',
                'SIPARIS', 'NUMUNE', 'TAHSILAT', 'CEK',
                'MUHASEBE', 'SATINALMA', 'FIYAT'
            )),
            UNIQUE (kaynak_turu, kaynak_id, onay_turu)
        )
    """)
    for name, cols in (
        ('idx_nonay_durum', 'durum'),
        ('idx_nonay_kaynak', 'kaynak_turu, kaynak_id'),
        ('idx_nonay_turu', 'onay_turu'),
        ('idx_nonay_olusturan', 'olusturan_kullanici_id'),
        ('idx_nonay_created', 'created_at'),
    ):
        con.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {TABLO_ONAY}({cols})')
    # Aktif kaynak: bir kaynakta en fazla bir ONAY_BEKLIYOR
    con.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_nonay_aktif_kaynak
        ON {TABLO_ONAY}(kaynak_turu, kaynak_id)
        WHERE durum = 'ONAY_BEKLIYOR'
    """)
    log(f'[{MIGRATION_VERSION}] OK CREATE {TABLO_ONAY}')


def ensure_aktif_kaynak_unique(con: sqlite3.Connection) -> None:
    """Daha önce uygulanmış 148 için partial UNIQUE sonradan ekler."""
    if not _table_exists(con, TABLO_ONAY):
        return
    con.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_nonay_aktif_kaynak
        ON {TABLO_ONAY}(kaynak_turu, kaynak_id)
        WHERE durum = 'ONAY_BEKLIYOR'
    """)
    log(f'[{MIGRATION_VERSION}] OK ensure uq_nonay_aktif_kaynak')


def _rebuild_mtt_onay_bekliyor(con: sqlite3.Connection) -> None:
    if not _table_exists(con, TABLO_MTT):
        raise RuntimeError(f'{TABLO_MTT} yok — 146 gerekli')
    if _mtt_has_onay_bekliyor(con):
        log(f'[{MIGRATION_VERSION}] SKIP MTT CHECK ONAY_BEKLIYOR')
        return

    tmp = f'{TABLO_MTT}__mig148'
    if _table_exists(con, tmp):
        con.execute(f'DROP TABLE {tmp}')

    con.execute('PRAGMA foreign_keys=OFF')
    con.execute(f"""
        CREATE TABLE {tmp} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            talep_no TEXT NOT NULL UNIQUE,
            talep_turu TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'ONAY_BEKLIYOR',
            gorusme_id INTEGER NOT NULL,
            cari_id INTEGER,
            musteri_aday_id INTEGER,
            olusturan_kullanici_id INTEGER NOT NULL,
            atanan_kullanici_id INTEGER,
            oncelik TEXT NOT NULL DEFAULT 'NORMAL',
            aciklama TEXT,
            musteri_notu TEXT,
            geri_gonderme_notu TEXT,
            red_nedeni TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            donusturulen_siparis_id INTEGER,
            donusturulen_numune_talep_id INTEGER,
            isleme_alinma_tarihi TEXT,
            donusturulme_tarihi TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (talep_turu IN ('SIPARIS', 'NUMUNE')),
            CHECK (durum IN (
                'ONAY_BEKLIYOR',
                'YENI', 'ISLEME_ALINDI', 'EKSIK_BILGI',
                'SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU',
                'KISMEN_NUMUNEYE_DONUSTU',
                'REDDEDILDI', 'IPTAL'
            )),
            CHECK (oncelik IN ('DUSUK', 'NORMAL', 'YUKSEK', 'ACIL')),
            CHECK (
                (cari_id IS NOT NULL AND musteri_aday_id IS NULL)
                OR (cari_id IS NULL AND musteri_aday_id IS NOT NULL)
            )
        )
    """)
    cols = [
        'id', 'talep_no', 'talep_turu', 'durum', 'gorusme_id', 'cari_id',
        'musteri_aday_id', 'olusturan_kullanici_id', 'atanan_kullanici_id',
        'oncelik', 'aciklama', 'musteri_notu', 'geri_gonderme_notu', 'red_nedeni',
        'idempotency_key', 'donusturulen_siparis_id', 'donusturulen_numune_talep_id',
        'isleme_alinma_tarihi', 'donusturulme_tarihi', 'created_at', 'updated_at',
    ]
    col_sql = ', '.join(cols)
    con.execute(f'INSERT INTO {tmp} ({col_sql}) SELECT {col_sql} FROM {TABLO_MTT}')
    con.execute(f'DROP TABLE {TABLO_MTT}')
    con.execute(f'ALTER TABLE {tmp} RENAME TO {TABLO_MTT}')
    for name, ccols in (
        ('idx_nmtt_durum', 'durum'),
        ('idx_nmtt_turu', 'talep_turu'),
        ('idx_nmtt_gorusme', 'gorusme_id'),
        ('idx_nmtt_cari', 'cari_id'),
        ('idx_nmtt_aday', 'musteri_aday_id'),
        ('idx_nmtt_olusturan', 'olusturan_kullanici_id'),
        ('idx_nmtt_atanan', 'atanan_kullanici_id'),
        ('idx_nmtt_created', 'created_at'),
        ('idx_nmtt_siparis_ptr', 'donusturulen_siparis_id'),
        ('idx_nmtt_numune_ptr', 'donusturulen_numune_talep_id'),
    ):
        con.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {TABLO_MTT}({ccols})')
    con.execute('PRAGMA foreign_keys=ON')
    log(f'[{MIGRATION_VERSION}] OK REBUILD {TABLO_MTT} + ONAY_BEKLIYOR')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] onay merkezi starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, TABLO_ONAY) and _mtt_has_onay_bekliyor(con):
                log(f'[{MIGRATION_VERSION}] SKIP create — ensure indexes')
                ensure_aktif_kaynak_unique(con)
                con.commit()
                return

        con.execute('BEGIN IMMEDIATE')
        _create_onay(con)
        _rebuild_mtt_onay_bekliyor(con)
        ensure_aktif_kaynak_unique(con)

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'nexgen_onay + MTT ONAY_BEKLIYOR'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] DONE')
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

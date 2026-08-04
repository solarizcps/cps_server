# -*- coding: utf-8 -*-
"""
147_nexgen_mtt_kalem_numune_pointer.py
=====================================
FAZ-MTT-F5B — seçimli / kısmi numune dönüşümü

- Header durum CHECK: + KISMEN_NUMUNEYE_DONUSTU (rebuild)
- Kalem pointer: donusturulen_numune_talep_id, donusturulme_tarihi, donusturme_durumu
- Idempotency tablosu: nexgen_mtt_numune_donusum_idem
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 147
TABLO = 'nexgen_musteri_temsilcisi_talep'
TABLO_KALEM = 'nexgen_musteri_temsilcisi_talep_kalem'
TABLO_IDEM = 'nexgen_mtt_numune_donusum_idem'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _cols(con, tablo: str) -> set[str]:
    if not _table_exists(con, tablo):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()}


def _durum_check_has_kismen(con) -> bool:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (TABLO,),
    ).fetchone()
    sql = (row[0] or '') if row else ''
    return 'KISMEN_NUMUNEYE_DONUSTU' in sql


def _rebuild_talep_durum(con: sqlite3.Connection) -> None:
    if not _table_exists(con, TABLO):
        raise RuntimeError(f'{TABLO} yok — 146 gerekli')
    if _durum_check_has_kismen(con):
        log(f'[{MIGRATION_VERSION}] SKIP header durum CHECK (KISMEN var)')
        return

    tmp = f'{TABLO}__mig147'
    if _table_exists(con, tmp):
        con.execute(f'DROP TABLE {tmp}')

    # Kalem FK → talep; rebuild sırasında FK kapat
    con.execute('PRAGMA foreign_keys=OFF')
    con.execute(f"""
        CREATE TABLE {tmp} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            talep_no TEXT NOT NULL UNIQUE,
            talep_turu TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'YENI',
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
    con.execute(f'INSERT INTO {tmp} ({col_sql}) SELECT {col_sql} FROM {TABLO}')
    con.execute(f'DROP TABLE {TABLO}')
    con.execute(f'ALTER TABLE {tmp} RENAME TO {TABLO}')
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
        con.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {TABLO}({ccols})')
    con.execute('PRAGMA foreign_keys=ON')
    log(f'[{MIGRATION_VERSION}] OK REBUILD {TABLO} + KISMEN_NUMUNEYE_DONUSTU')


def _ensure_kalem_pointer(con: sqlite3.Connection) -> None:
    if not _table_exists(con, TABLO_KALEM):
        raise RuntimeError(f'{TABLO_KALEM} yok — 146 gerekli')
    cols = _cols(con, TABLO_KALEM)
    if 'donusturulen_numune_talep_id' not in cols:
        con.execute(
            f'ALTER TABLE {TABLO_KALEM} ADD COLUMN donusturulen_numune_talep_id INTEGER'
        )
        log(f'[{MIGRATION_VERSION}] OK ADD kalem.donusturulen_numune_talep_id')
    else:
        log(f'[{MIGRATION_VERSION}] SKIP kalem.donusturulen_numune_talep_id')
    if 'donusturulme_tarihi' not in cols:
        con.execute(f'ALTER TABLE {TABLO_KALEM} ADD COLUMN donusturulme_tarihi TEXT')
        log(f'[{MIGRATION_VERSION}] OK ADD kalem.donusturulme_tarihi')
    else:
        log(f'[{MIGRATION_VERSION}] SKIP kalem.donusturulme_tarihi')
    if 'donusturme_durumu' not in cols:
        con.execute(
            f"ALTER TABLE {TABLO_KALEM} ADD COLUMN donusturme_durumu TEXT "
            f"DEFAULT 'BEKLIYOR'"
        )
        log(f'[{MIGRATION_VERSION}] OK ADD kalem.donusturme_durumu')
    else:
        log(f'[{MIGRATION_VERSION}] SKIP kalem.donusturme_durumu')
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nmttk_numune_ptr '
        f'ON {TABLO_KALEM}(donusturulen_numune_talep_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nmttk_donusum_durum '
        f'ON {TABLO_KALEM}(donusturme_durumu)'
    )
    # Mevcut satırları normalize
    con.execute(
        f"UPDATE {TABLO_KALEM} SET donusturme_durumu='BEKLIYOR' "
        f"WHERE donusturme_durumu IS NULL OR TRIM(donusturme_durumu)=''"
    )


def _ensure_idem(con: sqlite3.Connection) -> None:
    if _table_exists(con, TABLO_IDEM):
        log(f'[{MIGRATION_VERSION}] SKIP {TABLO_IDEM}')
        return
    con.execute(f"""
        CREATE TABLE {TABLO_IDEM} (
            idempotency_key TEXT PRIMARY KEY,
            talep_id INTEGER NOT NULL,
            secilen_kalem_ids TEXT NOT NULL,
            primary_numune_id INTEGER,
            numune_ids_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    con.execute(
        f'CREATE INDEX IF NOT EXISTS idx_mtt_ndi_talep ON {TABLO_IDEM}(talep_id)'
    )
    log(f'[{MIGRATION_VERSION}] OK CREATE {TABLO_IDEM}')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] mtt kalem numune pointer starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _durum_check_has_kismen(con) and 'donusturme_durumu' in _cols(con, TABLO_KALEM):
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        con.execute('BEGIN IMMEDIATE')
        _rebuild_talep_durum(con)
        _ensure_kalem_pointer(con)
        _ensure_idem(con)

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'mtt kalem numune pointer + KISMEN durum'),
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

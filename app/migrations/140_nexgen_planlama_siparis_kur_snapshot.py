# -*- coding: utf-8 -*-
"""
140_nexgen_planlama_siparis_kur_snapshot.py
==========================================
FAZ-PAZARLAMA-TICARI-SARTLAR-T3

nexgen_planlama_siparis:
  kur NUMERIC NULL
  kur_tarihi TEXT NULL
  kur_kaynagi TEXT NULL

nexgen_planlama_siparis_kalem:
  net_birim_fiyat_try NUMERIC NULL
  satir_tutari_try NUMERIC NULL

- eski kayıtlar NULL
- tahmini backfill YOK
- idempotent
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 140

HDR_TABLE = 'nexgen_planlama_siparis'
KALEM_TABLE = 'nexgen_planlama_siparis_kalem'
HDR_KOLONLAR = (
    ('kur', 'NUMERIC'),
    ('kur_tarihi', 'TEXT'),
    ('kur_kaynagi', 'TEXT'),
)
KALEM_KOLONLAR = (
    ('net_birim_fiyat_try', 'NUMERIC'),
    ('satir_tutari_try', 'NUMERIC'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def run(db_path: str | None = None) -> dict:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] kur snapshot starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, HDR_TABLE) or not _table_exists(con, KALEM_TABLE):
            raise RuntimeError('planlama siparis/kalem tablolari yok')

        hdr_cols = _columns(con, HDR_TABLE)
        kalem_cols = _columns(con, KALEM_TABLE)
        all_ok = (
            all(c in hdr_cols for c, _ in HDR_KOLONLAR)
            and all(c in kalem_cols for c, _ in KALEM_KOLONLAR)
        )
        if all_ok and _table_exists(con, 'schema_migrations'):
            if con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone():
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return {'ok': True, 'yeni_degisiklik': False, 'version': MIGRATION_VERSION}

        con.execute('BEGIN IMMEDIATE')
        degisti = False
        for kolon, tip in HDR_KOLONLAR:
            if kolon not in _columns(con, HDR_TABLE):
                con.execute(f'ALTER TABLE {HDR_TABLE} ADD COLUMN {kolon} {tip}')
                log(f'[{MIGRATION_VERSION}] OK ADD {HDR_TABLE}.{kolon}')
                degisti = True
            else:
                log(f'[{MIGRATION_VERSION}] SKIP {HDR_TABLE}.{kolon}')

        for kolon, tip in KALEM_KOLONLAR:
            if kolon not in _columns(con, KALEM_TABLE):
                con.execute(f'ALTER TABLE {KALEM_TABLE} ADD COLUMN {kolon} {tip}')
                log(f'[{MIGRATION_VERSION}] OK ADD {KALEM_TABLE}.{kolon}')
                degisti = True
            else:
                log(f'[{MIGRATION_VERSION}] SKIP {KALEM_TABLE}.{kolon}')

        for kolon, _ in HDR_KOLONLAR:
            if kolon not in _columns(con, HDR_TABLE):
                raise RuntimeError(f'schema verify FAILED: {HDR_TABLE}.{kolon}')
        for kolon, _ in KALEM_KOLONLAR:
            if kolon not in _columns(con, KALEM_TABLE):
                raise RuntimeError(f'schema verify FAILED: {KALEM_TABLE}.{kolon}')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'siparis kur snapshot + kalem TRY karsilik'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] DONE yeni_degisiklik={degisti}')
        return {'ok': True, 'yeni_degisiklik': degisti, 'version': MIGRATION_VERSION}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    print(run())

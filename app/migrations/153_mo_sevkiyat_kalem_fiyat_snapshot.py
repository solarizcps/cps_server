# -*- coding: utf-8 -*-
"""
153_mo_sevkiyat_kalem_fiyat_snapshot.py
========================================
Sevkiyat kalem fiyat/PB snapshot — yeni sevkler için canonical tutar izi.

mo_musteri_sevkiyat_kalem:
  birim_fiyat_snapshot   REAL NULL
  para_birimi_snapshot   TEXT NULL
  fiyat_kaynagi          TEXT NULL

Eski sevkiyatlara backfill YOK. Idempotent.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 153
TABLE = 'mo_musteri_sevkiyat_kalem'
KOLONLAR = (
    ('birim_fiyat_snapshot', 'REAL'),
    ('para_birimi_snapshot', 'TEXT'),
    ('fiyat_kaynagi', 'TEXT'),
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


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(con, table):
        return False
    return column in [c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()]


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] mo_musteri_sevkiyat_kalem fiyat snapshot')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok — önce migration 127 uygulanmalı.')
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and all(_column_exists(con, TABLE, k) for k, _ in KOLONLAR):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        for kolon, tip in KOLONLAR:
            if not _column_exists(con, TABLE, kolon):
                con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {kolon} {tip}')
                log(f'[{MIGRATION_VERSION}] OK ADD {kolon}')
            else:
                log(f'[{MIGRATION_VERSION}] SKIP kolon {kolon}')
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

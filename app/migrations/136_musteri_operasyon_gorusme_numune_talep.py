# -*- coding: utf-8 -*-
"""
136_musteri_operasyon_gorusme_numune_talep.py
============================================
FAZ-CARI360-NUMUNE-ILISKILERI-UYGULAMA-1 Dilim 2

musteri_operasyon_gorusme.numune_talep_id INTEGER NULL
- mevcut kayıtlar NULL kalır
- toplu tahmini backfill YOK
- nexgen_numune_talep.mo_gorusme_id bozulmaz
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 136
COL = 'numune_talep_id'
TABLE = 'musteri_operasyon_gorusme'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] gorusme.numune_talep_id starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} tablosu yok')

        cols = _columns(con, TABLE)
        if COL in cols:
            if _table_exists(con, 'schema_migrations'):
                applied = con.execute(
                    'SELECT version FROM schema_migrations WHERE version=?',
                    (MIGRATION_VERSION,),
                ).fetchone()
                if applied:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                    return

        con.execute('BEGIN IMMEDIATE')
        cols = _columns(con, TABLE)
        if COL not in cols:
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COL} INTEGER')
            log(f'[{MIGRATION_VERSION}] OK ADD {COL} INTEGER')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP kolon {COL}')

        if COL not in _columns(con, TABLE):
            raise RuntimeError('numune_talep_id schema verify FAILED')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'gorusme.numune_talep_id nullable FK'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — committed')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

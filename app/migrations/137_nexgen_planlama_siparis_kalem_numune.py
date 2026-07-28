# -*- coding: utf-8 -*-
"""
137_nexgen_planlama_siparis_kalem_numune.py
==========================================
FAZ-CARI360-NUMUNE-ILISKILERI-UYGULAMA-1 Dilim 3

nexgen_planlama_siparis_kalem.numune_talep_id INTEGER NULL
- mevcut kayıtlar NULL
- toplu tahmini backfill YOK
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 137
TABLE = 'nexgen_planlama_siparis_kalem'
COL = 'numune_talep_id'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name):
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con, table):
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] kalem.numune_talep_id starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok')
        cols = _columns(con, TABLE)
        if COL in cols and _table_exists(con, 'schema_migrations'):
            if con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone():
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        con.execute('BEGIN IMMEDIATE')
        if COL not in _columns(con, TABLE):
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COL} INTEGER')
            log(f'[{MIGRATION_VERSION}] OK ADD {COL}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP kolon')

        if COL not in _columns(con, TABLE):
            raise RuntimeError('schema verify FAILED')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'siparis_kalem.numune_talep_id nullable FK'),
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

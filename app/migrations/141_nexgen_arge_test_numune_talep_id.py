# -*- coding: utf-8 -*-
"""
141_nexgen_arge_test_numune_talep_id.py
======================================
FAZ-CARI360-GORUSME-NUMUNE-ARGE-SERT-ILISKI-1A

nexgen_arge_test.numune_talep_id INTEGER NULL
- mevcut kayıtlar NULL kalır
- hard UNIQUE YOK
- hard FK YOK
- table rebuild YOK
- backfill UPDATE YOK (dry-run ayrı; apply 1C)
- idempotent
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 141
TABLE = 'nexgen_arge_test'
COL = 'numune_talep_id'
INDEX_NAME = 'idx_arge_numune_talep'


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


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,),
    ).fetchone())


def run(db_path: str | None = None) -> dict:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] arge.numune_talep_id starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} tablosu yok')

        cols = _columns(con, TABLE)
        idx_ok = _index_exists(con, INDEX_NAME)
        if COL in cols and idx_ok and _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return {
                    'ok': True,
                    'yeni_degisiklik': False,
                    'version': MIGRATION_VERSION,
                    'skipped': True,
                }

        con.execute('BEGIN IMMEDIATE')
        degisti = False
        cols = _columns(con, TABLE)
        if COL not in cols:
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COL} INTEGER')
            log(f'[{MIGRATION_VERSION}] OK ADD {TABLE}.{COL} INTEGER')
            degisti = True
        else:
            log(f'[{MIGRATION_VERSION}] SKIP kolon {COL}')

        if COL not in _columns(con, TABLE):
            raise RuntimeError('numune_talep_id schema verify FAILED')

        if not _index_exists(con, INDEX_NAME):
            con.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {INDEX_NAME}
                ON {TABLE}({COL})
                WHERE {COL} IS NOT NULL
                """
            )
            log(f'[{MIGRATION_VERSION}] OK INDEX {INDEX_NAME}')
            degisti = True
        else:
            log(f'[{MIGRATION_VERSION}] SKIP index {INDEX_NAME}')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'arge.numune_talep_id nullable + index (no hard FK/unique)'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — committed (yeni_degisiklik={degisti})')
        return {
            'ok': True,
            'yeni_degisiklik': degisti,
            'version': MIGRATION_VERSION,
            'skipped': False,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    # Güvenlik: canlı mock_data.db'ye sessizce yazmayı engelle.
    # Kullanım: python 141_....py --db <path> [--allow-live]
    args = sys.argv[1:]
    db_arg = None
    allow_live = False
    i = 0
    while i < len(args):
        if args[i] == '--db' and i + 1 < len(args):
            db_arg = args[i + 1]
            i += 2
            continue
        if args[i] == '--allow-live':
            allow_live = True
            i += 1
            continue
        if not args[i].startswith('-') and db_arg is None:
            db_arg = args[i]
            i += 1
            continue
        i += 1
    if not db_arg:
        raise SystemExit(
            'HATA: explicit --db <path> zorunlu. '
            'Örnek: python 141_nexgen_arge_test_numune_talep_id.py --db C:\\path\\copy.db'
        )
    base = os.path.basename(os.path.normpath(db_arg)).lower()
    if base == 'mock_data.db' and not allow_live:
        raise SystemExit(
            'HATA: mock_data.db (canlı) için --allow-live gerekir. '
            'Önce kopya DB ile çalıştırın.'
        )
    print(run(db_arg))

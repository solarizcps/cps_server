# -*- coding: utf-8 -*-
"""
181_arac_kayitli_yer_multi_location.py
======================================
Araç Takip — şirket başına çoklu kayıtlı konum (konum_adi, cari_id, idempotency).
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 181
TABLE = 'arac_kayitli_yer'

NEW_COLUMNS = (
    ('konum_adi', 'TEXT'),
    ('cari_id', 'INTEGER'),
    ('updated_at', 'TEXT'),
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
    cols = [r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]
    return column in cols


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_kayitli_yer_multi_location')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLE):
            log(f'[{MIGRATION_VERSION}] WARN {TABLE} yok — 176 önce uygulanmalı')
            return
        added = []
        for col, typedef in NEW_COLUMNS:
            if not _column_exists(con, TABLE, col):
                con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {col} {typedef}')
                added.append(col)
        if added:
            log(f'[{MIGRATION_VERSION}] columns added: {", ".join(added)}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP — kolonlar zaten var')

        if not _table_exists(con, 'arac_plana_idempotency'):
            con.execute("""
                CREATE TABLE arac_plana_idempotency (
                    token TEXT PRIMARY KEY,
                    talep_id INTEGER NOT NULL,
                    plan_id INTEGER NOT NULL,
                    plan_is_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            log(f'[{MIGRATION_VERSION}] CREATE arac_plana_idempotency')

        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else None)

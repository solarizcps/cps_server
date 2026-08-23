# -*- coding: utf-8 -*-
"""
178_arac_is_talebi_ux_v2_fields.py
=================================
Araç Takip — Yeni İş Talebi UX V2 ek alanları (nullable, idempotent).
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 178
TABLE = 'arac_is_talebi'

NEW_COLUMNS = (
    ('sofor_id', 'INTEGER'),
    ('sofor_adi_snapshot', 'TEXT'),
    (
        'is_turu',
        "TEXT CHECK (is_turu IS NULL OR is_turu IN ('ALINACAK','GONDERILECEK','ZIYARET'))",
    ),
    ('urun_malzeme', 'TEXT'),
    ('miktar', 'REAL'),
    ('miktar_birim', 'TEXT'),
    ('ek_not', 'TEXT'),
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
    log(f'[{MIGRATION_VERSION}] arac_is_talebi_ux_v2_fields')
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

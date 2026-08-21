# -*- coding: utf-8 -*-
"""
177_arac_operasyon_ayar.py
==========================
Araç Takip V1.4A — canonical başlangıç noktası (base) ayarı.
Schema only — sahte koordinat seed YOK.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 177


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_operasyon_ayar')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'arac_operasyon_ayar'):
            con.execute("""
                CREATE TABLE arac_operasyon_ayar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_name TEXT NOT NULL,
                    base_latitude REAL,
                    base_longitude REAL,
                    base_address TEXT,
                    base_maps_url TEXT,
                    aktif INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER
                )
            """)
            con.execute(
                'CREATE UNIQUE INDEX idx_arac_operasyon_ayar_single_active '
                'ON arac_operasyon_ayar(aktif) WHERE aktif=1',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_operasyon_ayar')

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

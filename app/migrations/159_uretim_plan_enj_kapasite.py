# -*- coding: utf-8 -*-
"""159 — uretim_model_plan enjeksiyon kapasite alanları."""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 159

ENJ_COLS = [
    ('enj_makine_id',       'INTEGER'),
    ('enj_istasyon_no',     'INTEGER'),
    ('enj_slot',            'TEXT'),
    ('enj_kalip_id',        'INTEGER'),
    ('enj_kalip_kod',       'TEXT'),
    ('enj_aktif_goz',       'INTEGER'),
    ('enj_kalip_basi_cift', 'INTEGER'),
    ('enj_tur_cift',        'INTEGER'),
    ('enj_gunluk_tur_plan', 'INTEGER'),
    ('enj_gunluk_kapasite', 'INTEGER'),
    ('enj_plan_baslangic',  'TEXT'),
    ('enj_plan_bitis',      'TEXT'),
    ('enj_tahmini_gun',     'REAL'),
    ('enj_planlanacak_cift','REAL'),
]


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _col_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]
    return col in cols


def _alter_table(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'uretim_model_plan'):
        log(f'[{MIGRATION_VERSION}] uretim_model_plan yok — atlanıyor')
        return
    added = 0
    for col, typ in ENJ_COLS:
        if not _col_exists(con, 'uretim_model_plan', col):
            con.execute(f'ALTER TABLE uretim_model_plan ADD COLUMN {col} {typ}')
            added += 1
    if added:
        log(f'[{MIGRATION_VERSION}] {added} enj_ kolonu eklendi')
    else:
        log(f'[{MIGRATION_VERSION}] enj_ kolonları zaten mevcut')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] uretim_plan_enj_kapasite')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return

        con.execute('BEGIN IMMEDIATE')
        _alter_table(con)
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

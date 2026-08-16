# -*- coding: utf-8 -*-
"""
154_mo_tahsilat_sevkiyat_bagi.py
==================================
TAHSİLAT ↔ SEVKİYAT V1 Faz 1 — mo_tahsilat_kayit sevkiyat bağlantısı.

mo_tahsilat_kayit:
  sevkiyat_id              INTEGER NULL  → mo_musteri_sevkiyat.id
  sevk_hedef_tutar_snapshot REAL NULL
  sevk_para_birimi_snapshot TEXT NULL

Eski kayıtlar NULL kalır. Backfill YOK. Idempotent.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 154

YENI_KOLONLAR = (
    ('sevkiyat_id', 'INTEGER'),
    ('sevk_hedef_tutar_snapshot', 'REAL'),
    ('sevk_para_birimi_snapshot', 'TEXT'),
)

INDEX_SPECS = (
    (
        'idx_mtk_sevkiyat',
        'CREATE INDEX IF NOT EXISTS idx_mtk_sevkiyat '
        'ON mo_tahsilat_kayit(sevkiyat_id) WHERE aktif=1',
    ),
    (
        'idx_mtk_sevkiyat_durum',
        'CREATE INDEX IF NOT EXISTS idx_mtk_sevkiyat_durum '
        'ON mo_tahsilat_kayit(sevkiyat_id, durum) WHERE aktif=1',
    ),
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


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,),
    ).fetchone())


def _ensure_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'mo_tahsilat_kayit'):
        log(f'[{MIGRATION_VERSION}] mo_tahsilat_kayit yok — kolon atlandı')
        return
    for col, typ in YENI_KOLONLAR:
        if _column_exists(con, 'mo_tahsilat_kayit', col):
            continue
        con.execute(f'ALTER TABLE mo_tahsilat_kayit ADD COLUMN {col} {typ}')
        log(f'[{MIGRATION_VERSION}] mo_tahsilat_kayit +{col}')


def _ensure_indexes(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'mo_tahsilat_kayit'):
        return
    for name, sql in INDEX_SPECS:
        if _index_exists(con, name):
            continue
        con.execute(sql)
        log(f'[{MIGRATION_VERSION}] index {name}')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] Tahsilat sevkiyat bağlantısı')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _column_exists(con, 'mo_tahsilat_kayit', 'sevkiyat_id'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        _ensure_columns(con)
        _ensure_indexes(con)
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

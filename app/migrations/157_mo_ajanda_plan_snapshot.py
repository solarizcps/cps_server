# -*- coding: utf-8 -*-
"""
157_mo_ajanda_plan_snapshot.py
================================
FAZ-2D — Ajanda plan snapshot alanları (PLANLA anında dondurulur).

musteri_operasyon_ajanda:
- plan_yetkili_metin TEXT NULL
- plan_telefon TEXT NULL
- plan_sehir TEXT NULL

Idempotent ALTER ADD; mevcut satırları silmez; CHECK/index dokunulmaz.
"""
from __future__ import annotations

import json
import os
import sqlite3

MIGRATION_VERSION = 157
TABLO = 'musteri_operasyon_ajanda'
YENI_KOLONLAR = (
    ('plan_yetkili_metin', 'TEXT'),
    ('plan_telefon', 'TEXT'),
    ('plan_sehir', 'TEXT'),
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


def _col_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _already_migrated(con: sqlite3.Connection) -> bool:
    if not _table_exists(con, TABLO):
        return False
    names = _col_names(con, TABLO)
    return all(col in names for col, _ in YENI_KOLONLAR)


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] ajanda plan snapshot kolonları')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLO):
            raise RuntimeError(f'{TABLO} tablosu yok — önce migration 151 gerekli.')

        before_count = con.execute(f'SELECT COUNT(*) FROM {TABLO}').fetchone()[0]
        before_cols = sorted(_col_names(con, TABLO))
        log(f'[{MIGRATION_VERSION}] BEFORE rows={before_count} cols={len(before_cols)}')

        if _already_migrated(con):
            log(f'[{MIGRATION_VERSION}] SKIP — kolonlar zaten mevcut')
            return

        con.execute('BEGIN IMMEDIATE')
        names = _col_names(con, TABLO)
        for col, typ in YENI_KOLONLAR:
            if col not in names:
                con.execute(f'ALTER TABLE {TABLO} ADD COLUMN {col} {typ}')
                log(f'[{MIGRATION_VERSION}] ADD COLUMN {col} {typ}')
        after_count = con.execute(f'SELECT COUNT(*) FROM {TABLO}').fetchone()[0]
        if after_count != before_count:
            raise RuntimeError(
                f'Row count mismatch: before={before_count} after={after_count}'
            )
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (str(MIGRATION_VERSION),),
            )
        con.commit()

        after_cols = sorted(_col_names(con, TABLO))
        log(f'[{MIGRATION_VERSION}] AFTER rows={after_count} cols={len(after_cols)}')
        log(f'[{MIGRATION_VERSION}] new_cols={json.dumps([c for c, _ in YENI_KOLONLAR])}')
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run(path)

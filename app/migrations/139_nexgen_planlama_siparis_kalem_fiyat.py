# -*- coding: utf-8 -*-
"""
139_nexgen_planlama_siparis_kalem_fiyat.py
=========================================
FAZ-PAZARLAMA-TICARI-SARTLAR-T2

nexgen_planlama_siparis_kalem:
  birim_fiyat NUMERIC NULL
  iskonto_orani NUMERIC NULL DEFAULT 0
  iskonto_tutari NUMERIC NULL
  net_birim_fiyat NUMERIC NULL
  satir_tutari NUMERIC NULL

- eski kayıtlar NULL
- tahmini backfill YOK
- idempotent
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 139
TABLE = 'nexgen_planlama_siparis_kalem'
KOLONLAR = (
    ('birim_fiyat', 'NUMERIC'),
    ('iskonto_orani', 'NUMERIC'),
    ('iskonto_tutari', 'NUMERIC'),
    ('net_birim_fiyat', 'NUMERIC'),
    ('satir_tutari', 'NUMERIC'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def run(db_path: str | None = None) -> dict:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] kalem fiyat/iskonto snapshot starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok')

        cols = _columns(con, TABLE)
        if all(c in cols for c, _ in KOLONLAR) and _table_exists(con, 'schema_migrations'):
            if con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone():
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return {'ok': True, 'yeni_degisiklik': False, 'version': MIGRATION_VERSION}

        con.execute('BEGIN IMMEDIATE')
        degisti = False
        for kolon, tip in KOLONLAR:
            if kolon not in _columns(con, TABLE):
                con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {kolon} {tip}')
                log(f'[{MIGRATION_VERSION}] OK ADD {kolon}')
                degisti = True
            else:
                log(f'[{MIGRATION_VERSION}] SKIP kolon {kolon}')

        for kolon, _ in KOLONLAR:
            if kolon not in _columns(con, TABLE):
                raise RuntimeError(f'schema verify FAILED: {kolon}')

        # Fiyat alanlarına indeks yok (seçicilik düşük / gereksiz)

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'kalem birim_fiyat/iskonto snapshot nullable'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] DONE yeni_degisiklik={degisti}')
        return {'ok': True, 'yeni_degisiklik': degisti, 'version': MIGRATION_VERSION}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    print(run())

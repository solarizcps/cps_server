# -*- coding: utf-8 -*-
"""
143_musteri_operasyon_gorusme_yetkili_metin.py
=============================================
FAZ-MUSTERI-OPERASYONU-GORUSME-MODAL-UX-IYILESTIRME-1

musteri_operasyon_gorusme.yetkili_metin TEXT NULL
— serbest yetkili adı (kart oluşturmaz; yetkili_id opsiyonel kalır)
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 143
COL = 'yetkili_metin'
TABLE = 'musteri_operasyon_gorusme'


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


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] {COL} starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok')
        if COL in _columns(con, TABLE):
            if _table_exists(con, 'schema_migrations'):
                applied = con.execute(
                    'SELECT version FROM schema_migrations WHERE version=?',
                    (MIGRATION_VERSION,),
                ).fetchone()
                if applied:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                    return

        con.execute('BEGIN IMMEDIATE')
        if COL not in _columns(con, TABLE):
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COL} TEXT')
            log(f'[{MIGRATION_VERSION}] OK ADD {COL}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP kolon {COL}')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'gorusme.yetkili_metin serbest metin'),
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

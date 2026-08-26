# -*- coding: utf-8 -*-
"""
187_arac_plan_cikis_saati.py
Araç Takip — plan bazlı çıkış saati.

Değişiklik:
  ALTER TABLE arac_gunluk_plan ADD COLUMN cikis_saati TEXT

Format: HH:mm (nullable — mevcut planlar etkilenmez)

Bağımlılık: 182

Güvenlik:
  run(db_path) zorunlu — hard-coded canonical fallback YOK.
  Canonical hedef için allow_canonical=True gerekir.
"""
from __future__ import annotations

import sqlite3

MIGRATION_VERSION = 187


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _col_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(
        r[1] == col
        for r in con.execute(f'PRAGMA table_info({table})').fetchall()
    )


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def run(db_path: str, *, allow_canonical: bool = False) -> None:
    """
    db_path: absolute path to target SQLite DB (zorunlu).
    allow_canonical: True değilse canonical mock_data.db reddedilir.
    """
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    log(f'[187] DB: {path}')
    con = sqlite3.connect(path)
    try:
        if not _table_exists(con, 'arac_gunluk_plan'):
            log('[187] SKIP — arac_gunluk_plan tablosu yok (test ortamı)')
            return

        if _col_exists(con, 'arac_gunluk_plan', 'cikis_saati'):
            log('[187] SKIP — arac_gunluk_plan.cikis_saati zaten mevcut (idempotent)')
            return

        con.execute(
            'ALTER TABLE arac_gunluk_plan ADD COLUMN cikis_saati TEXT'
        )
        con.commit()
        log('[187] OK   — arac_gunluk_plan.cikis_saati eklendi (TEXT nullable)')
    finally:
        con.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migration 187 — cikis_saati')
    parser.add_argument('--db-path', required=True, help='Hedef SQLite DB absolute path')
    parser.add_argument(
        '--allow-canonical',
        action='store_true',
        help='Canonical mock_data.db hedefine yazmaya izin ver',
    )
    args = parser.parse_args()
    run(args.db_path, allow_canonical=args.allow_canonical)

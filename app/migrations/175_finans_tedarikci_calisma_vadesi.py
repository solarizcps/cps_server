# -*- coding: utf-8 -*-
"""
175_finans_tedarikci_calisma_vadesi.py
======================================
FAZ 6D-VADE — CPS çalışma vadesi alanları.

payment_period = ödeme ritmi
working_term_* = kaç gün + başlangıç noktası

Korgün OdemeVade KOPYALANMAZ / UPDATE EDİLMEZ.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 175
TABLE = 'finans_odeme_tedarikci_ayar'


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
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] finans_tedarikci_calisma_vadesi')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLE):
            log(f'[{MIGRATION_VERSION}] WARN {TABLE} yok — 174 önce uygulanmalı')
            return
        added = []
        if not _column_exists(con, TABLE, 'working_term_days'):
            con.execute(
                f'ALTER TABLE {TABLE} ADD COLUMN working_term_days INTEGER'
            )
            added.append('working_term_days')
        if not _column_exists(con, TABLE, 'working_term_basis'):
            con.execute(
                f'ALTER TABLE {TABLE} ADD COLUMN working_term_basis TEXT'
            )
            added.append('working_term_basis')
        if added:
            log(f'[{MIGRATION_VERSION}] columns added: {", ".join(added)}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP — kolonlar zaten var')

        if con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
    finally:
        con.close()
    log(f'[{MIGRATION_VERSION}] OK')


if __name__ == '__main__':
    run()

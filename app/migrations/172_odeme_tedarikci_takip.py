# -*- coding: utf-8 -*-
"""
172_odeme_tedarikci_takip.py
============================
P3A.5 — Aktif Takip Master

Tedarikçi aktif takip flag CPS'de tutulur.
Finansal tutar TUTULMAZ — borç her zaman Korgün kg_fn_CariHesToplam'dan gelir.

Canonical key: location + cari_kod
Seed kaynağı: Excel import (başlangıç); sonrasında manuel admin write.
Korgün write: KESİNLİKLE 0.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 172


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
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] odeme_tedarikci_takip')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'finans_odeme_tedarikci_takip'):
            con.executescript("""
                CREATE TABLE finans_odeme_tedarikci_takip (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    location        TEXT NOT NULL
                                    CHECK (location IN ('YN001','SA001','YP001')),
                    cari_kod        TEXT NOT NULL,
                    aktif_takip     INTEGER NOT NULL DEFAULT 1
                                    CHECK (aktif_takip IN (0, 1)),
                    kaynak          TEXT NOT NULL DEFAULT 'MANUEL'
                                    CHECK (kaynak IN ('EXCEL_SEED','MANUEL')),
                    cari_adi_snapshot TEXT NOT NULL DEFAULT '',
                    import_batch    TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    created_by      TEXT NOT NULL DEFAULT 'sistem',
                    updated_at      TEXT,
                    updated_by      TEXT,
                    CONSTRAINT uq_takip_canonical UNIQUE (location, cari_kod)
                );
                CREATE INDEX idx_takip_location
                    ON finans_odeme_tedarikci_takip(location);
                CREATE INDEX idx_takip_aktif
                    ON finans_odeme_tedarikci_takip(location, aktif_takip);
            """)
            log(f'[{MIGRATION_VERSION}] finans_odeme_tedarikci_takip created')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP finans_odeme_tedarikci_takip -- zaten var')

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

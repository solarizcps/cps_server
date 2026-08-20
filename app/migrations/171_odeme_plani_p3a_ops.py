# -*- coding: utf-8 -*-
"""
171_odeme_plani_p3a_ops.py
=========================
P3A — Ödeme Sözü + Aradı/Ödeme Sordu CPS operasyon tabloları.

Canonical cari: location + cari_kod
Korgün write YOK — yalnız CPS SQLite.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 171


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
    log(f'[{MIGRATION_VERSION}] odeme_plani_p3a_ops')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'finans_odeme_plani_sozu'):
            con.executescript("""
                CREATE TABLE finans_odeme_plani_sozu (
                    Id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    location            TEXT NOT NULL
                                        CHECK (location IN ('YN001','SA001','YP001')),
                    cari_kod            TEXT NOT NULL,
                    cari_adi_snapshot   TEXT NOT NULL,
                    promise_date        TEXT NOT NULL,
                    amount              REAL NOT NULL CHECK (amount > 0),
                    currency            TEXT NOT NULL DEFAULT 'TRY'
                                        CHECK (currency IN ('TRY','USD','EUR')),
                    note                TEXT,
                    status              TEXT NOT NULL DEFAULT 'ACIK'
                                        CHECK (status IN ('ACIK','GERCEKLESTI','ERTELENDI','IPTAL')),
                    created_by          TEXT NOT NULL,
                    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_by          TEXT,
                    updated_at          TEXT
                );
                CREATE INDEX idx_ops_canonical
                    ON finans_odeme_plani_sozu(location, cari_kod);
                CREATE INDEX idx_ops_location
                    ON finans_odeme_plani_sozu(location);
                CREATE INDEX idx_ops_status
                    ON finans_odeme_plani_sozu(status);
                CREATE INDEX idx_ops_promise_date
                    ON finans_odeme_plani_sozu(promise_date);
            """)
            log(f'[{MIGRATION_VERSION}] finans_odeme_plani_sozu created')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP finans_odeme_plani_sozu — zaten var')

        if not _table_exists(con, 'finans_odeme_plani_iletisim'):
            con.executescript("""
                CREATE TABLE finans_odeme_plani_iletisim (
                    Id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    location            TEXT NOT NULL
                                        CHECK (location IN ('YN001','SA001','YP001')),
                    cari_kod            TEXT NOT NULL,
                    cari_adi_snapshot   TEXT NOT NULL,
                    contact_at          TEXT NOT NULL,
                    contact_person      TEXT,
                    phone               TEXT,
                    requested_amount    REAL,
                    currency            TEXT
                                        CHECK (currency IS NULL OR currency IN ('TRY','USD','EUR')),
                    note                TEXT,
                    callback_date       TEXT,
                    created_by          TEXT NOT NULL,
                    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_by          TEXT,
                    updated_at          TEXT
                );
                CREATE INDEX idx_opi_canonical
                    ON finans_odeme_plani_iletisim(location, cari_kod);
                CREATE INDEX idx_opi_location
                    ON finans_odeme_plani_iletisim(location);
                CREATE INDEX idx_opi_contact_at
                    ON finans_odeme_plani_iletisim(contact_at);
            """)
            log(f'[{MIGRATION_VERSION}] finans_odeme_plani_iletisim created')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP finans_odeme_plani_iletisim — zaten var')

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

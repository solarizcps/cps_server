# -*- coding: utf-8 -*-
"""
174_finans_odeme_tedarikci_ayar.py
==================================
FAZ 6C — Tedarikçi çalışma ayarı CPS tablosu.

Canonical identity: UNIQUE(location, cari_kod)
Korgün vade (OdemeVade) KOPYALANMAZ — READ-ONLY FAZ4 servis.
finans_odeme_tedarikci_takip AYRI kalır (aktif_takip).
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 174


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
    log(f'[{MIGRATION_VERSION}] finans_odeme_tedarikci_ayar')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')
        if not _table_exists(con, 'finans_odeme_tedarikci_ayar'):
            con.executescript("""
                CREATE TABLE finans_odeme_tedarikci_ayar (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    location                TEXT NOT NULL
                                            CHECK (location IN ('YN001','SA001','YP001')),
                    cari_kod                TEXT NOT NULL,
                    cari_adi_snapshot       TEXT NOT NULL DEFAULT '',
                    category_code           TEXT NOT NULL DEFAULT 'TANIMSIZ'
                                            REFERENCES finans_tedarikci_kategori(code)
                                                ON DELETE RESTRICT,
                    payment_mode            TEXT NOT NULL DEFAULT 'MANUEL'
                                            CHECK (payment_mode IN (
                                                'FATURA_BAZLI','SIPARIS_BAZLI','DUZENLI',
                                                'DONEMSEL','MANUEL','SOZLESME_BAZLI'
                                            )),
                    payment_period          TEXT
                                            CHECK (payment_period IS NULL OR payment_period IN (
                                                'HAFTALIK','ON_BES_GUNLUK','AYLIK',
                                                'BELIRLI_GUN','FATURA_VADESINDE','MANUEL'
                                            )),
                    payment_day             TEXT,
                    priority                TEXT NOT NULL DEFAULT 'NORMAL'
                                            CHECK (priority IN (
                                                'DUSUK','NORMAL','YUKSEK','KRITIK'
                                            )),
                    critical_supplier       INTEGER NOT NULL DEFAULT 0
                                            CHECK (critical_supplier IN (0, 1)),
                    must_not_stop           INTEGER NOT NULL DEFAULT 0
                                            CHECK (must_not_stop IN (0, 1)),
                    recurring_payment       INTEGER NOT NULL DEFAULT 0
                                            CHECK (recurring_payment IN (0, 1)),
                    recurring_amount        REAL,
                    recurring_currency      TEXT
                                            CHECK (recurring_currency IS NULL OR recurring_currency IN (
                                                'TRY','USD','EUR'
                                            )),
                    partial_payment_allowed INTEGER NOT NULL DEFAULT 0
                                            CHECK (partial_payment_allowed IN (0, 1)),
                    minimum_payment_amount  REAL,
                    responsible_user_id     INTEGER,
                    responsible_department  TEXT,
                    payment_working_note    TEXT,
                    settings_active         INTEGER NOT NULL DEFAULT 1
                                            CHECK (settings_active IN (0, 1)),
                    created_by              TEXT NOT NULL,
                    created_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_by              TEXT,
                    updated_at              TEXT,
                    CONSTRAINT uq_tedarikci_ayar_canonical UNIQUE (location, cari_kod)
                );
                CREATE INDEX idx_tedarikci_ayar_location
                    ON finans_odeme_tedarikci_ayar(location);
                CREATE INDEX idx_tedarikci_ayar_category
                    ON finans_odeme_tedarikci_ayar(category_code);
                CREATE INDEX idx_tedarikci_ayar_priority
                    ON finans_odeme_tedarikci_ayar(location, priority);
            """)
            log(f'[{MIGRATION_VERSION}] finans_odeme_tedarikci_ayar created')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP finans_odeme_tedarikci_ayar — zaten var')

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

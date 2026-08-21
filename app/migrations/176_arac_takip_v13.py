# -*- coding: utf-8 -*-
"""
176_arac_takip_v13.py
=====================
Araç Takip V1.3 — iş talebi, kayıtlı yer, günlük plan canonical tablolar.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 176


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
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_takip_v13')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'arac_kayitli_yer'):
            con.execute("""
                CREATE TABLE arac_kayitli_yer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firma_adi TEXT NOT NULL,
                    kisi_adi TEXT,
                    telefon TEXT,
                    adres TEXT NOT NULL,
                    konum_linki TEXT,
                    latitude REAL,
                    longitude REAL,
                    aktif INTEGER NOT NULL DEFAULT 1,
                    kullanim_sayisi INTEGER NOT NULL DEFAULT 0,
                    son_kullanim_at TEXT,
                    created_at TEXT NOT NULL,
                    created_by INTEGER
                )
            """)
            con.execute(
                'CREATE INDEX idx_arac_kayitli_yer_firma ON arac_kayitli_yer(firma_adi)',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_kayitli_yer')

        if not _table_exists(con, 'arac_is_talebi'):
            con.execute("""
                CREATE TABLE arac_is_talebi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    talep_no TEXT NOT NULL UNIQUE,
                    talep_eden_user_id INTEGER NOT NULL,
                    talep_eden_adi_snapshot TEXT NOT NULL,
                    talep_tarihi TEXT NOT NULL,
                    istenen_saat TEXT,
                    kayitli_yer_id INTEGER,
                    firma_adi TEXT NOT NULL,
                    kisi_adi TEXT,
                    telefon TEXT,
                    adres TEXT NOT NULL,
                    konum_linki TEXT,
                    latitude REAL,
                    longitude REAL,
                    yapilacak_is TEXT NOT NULL,
                    oncelik TEXT NOT NULL DEFAULT 'NORMAL',
                    not_text TEXT,
                    durum TEXT NOT NULL DEFAULT 'BEKLIYOR',
                    save_to_master INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER NOT NULL,
                    CHECK (durum IN ('BEKLIYOR','PLANA_ALINDI','REDDEDILDI','IPTAL')),
                    CHECK (oncelik IN ('DUSUK','NORMAL','YUKSEK','ACIL'))
                )
            """)
            con.execute('CREATE INDEX idx_arac_is_talebi_durum ON arac_is_talebi(durum)')
            con.execute('CREATE INDEX idx_arac_is_talebi_tarih ON arac_is_talebi(talep_tarihi)')
            log(f'[{MIGRATION_VERSION}] CREATE arac_is_talebi')

        if not _table_exists(con, 'arac_gunluk_plan'):
            con.execute("""
                CREATE TABLE arac_gunluk_plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_tarihi TEXT NOT NULL,
                    arac_provider TEXT NOT NULL DEFAULT 'TURKCELL_FILOM',
                    arac_external_id TEXT NOT NULL,
                    arac_plaka_snapshot TEXT NOT NULL,
                    sofor_id INTEGER,
                    sofor_adi_snapshot TEXT,
                    durum TEXT NOT NULL DEFAULT 'AKTIF',
                    created_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER NOT NULL,
                    UNIQUE(plan_tarihi, arac_provider, arac_external_id)
                )
            """)
            log(f'[{MIGRATION_VERSION}] CREATE arac_gunluk_plan')

        if not _table_exists(con, 'arac_gunluk_plan_is'):
            con.execute("""
                CREATE TABLE arac_gunluk_plan_is (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    is_talebi_id INTEGER NOT NULL UNIQUE,
                    sira INTEGER NOT NULL,
                    planlanan_saat TEXT,
                    durum TEXT NOT NULL DEFAULT 'PLANLANDI',
                    created_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id),
                    FOREIGN KEY (is_talebi_id) REFERENCES arac_is_talebi(id),
                    CHECK (durum IN ('PLANLANDI','BASLADI','TAMAMLANDI','IPTAL'))
                )
            """)
            con.execute('CREATE UNIQUE INDEX idx_arac_plan_is_sira ON arac_gunluk_plan_is(plan_id, sira)')
            log(f'[{MIGRATION_VERSION}] CREATE arac_gunluk_plan_is')

        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else None)

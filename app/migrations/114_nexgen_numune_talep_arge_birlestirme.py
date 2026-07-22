# -*- coding: utf-8 -*-
"""
114_nexgen_numune_talep_arge_birlestirme.py
============================================
FAZ-NUMUNE-TALEP-ARGE-AKIS-BIRLESTIRME-1

- İşleme al audit alanları
- Vedat ek çalışma alanları
- Talep gelişme geçmişi tablosu

Idempotent: ALTER guarded by PRAGMA table_info.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 114


def log(msg: str) -> None:
    print(msg)


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info({tablo})').fetchall()]
    return kolon in cols


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] numune_talep arge birlestirme starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        has_sm = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if has_sm:
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        yeni_kolonlar = (
            ('isleme_alan_kullanici_id', 'INTEGER'),
            ('isleme_alinma_tarihi', 'TEXT'),
            ('vedat_deneme_tarihi', 'TEXT'),
            ('vedat_yapilan_degisiklik', 'TEXT'),
        )
        for kolon, tip in yeni_kolonlar:
            if not _kolon_var(con, kolon=kolon, tablo='nexgen_numune_talep'):
                con.execute(
                    f'ALTER TABLE nexgen_numune_talep ADD COLUMN {kolon} {tip}'
                )
                log(f'[{MIGRATION_VERSION}] + nexgen_numune_talep.{kolon}')

        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS nexgen_numune_talep_gelisme (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                talep_id        INTEGER NOT NULL,
                olay_tarihi     TEXT NOT NULL,
                olay_tipi       TEXT,
                olay_metni      TEXT NOT NULL,
                kullanici_id    INTEGER,
                aktif           INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_nntg_talep ON nexgen_numune_talep_gelisme(talep_id);
            """
        )

        if has_sm:
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    finally:
        con.close()


if __name__ == '__main__':
    run()

# -*- coding: utf-8 -*-
"""
128_finans_belgesi.py
=====================
FAZ-FINANS-MUHASEBE-MERKEZI-1B — Finans Belgesi entity.

Sevkiyat / tahsilat → muhasebe onayı köprüsü.
Cari_Har bu migration'da yazılmaz; yalnız FinancialPostingService yazar.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 128


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _index_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone())


def _ensure_finans_belgesi(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_belgesi'):
        return
    con.execute("""
        CREATE TABLE finans_belgesi (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            belge_kodu              TEXT NOT NULL UNIQUE,
            belge_tipi              TEXT NOT NULL,
            durum                   TEXT NOT NULL DEFAULT 'BEKLIYOR',
            sevkiyat_id             INTEGER UNIQUE,
            tahsilat_kayit_id       INTEGER UNIQUE,
            siparis_id              INTEGER,
            cari_id                 INTEGER NOT NULL,
            cari_kart_ckod          TEXT,
            kaynak_no               TEXT,
            siparis_no              TEXT,
            cari_unvan              TEXT NOT NULL,
            irsaliye_no             TEXT,
            islem_tarihi            TEXT NOT NULL,
            toplam_kg               REAL,
            birim_fiyat             REAL,
            para_birimi             TEXT NOT NULL DEFAULT 'TRY',
            toplam_tutar            REAL NOT NULL,
            vade_gun                INTEGER,
            vade_tarihi             TEXT,
            muhasebe_notu           TEXT,
            belge_dosya_ref         TEXT,
            onaylayan_id            INTEGER,
            onay_tarihi             TEXT,
            red_gerekce             TEXT,
            cari_har_id             INTEGER,
            cari_har_belge_no       TEXT,
            idempotency_key         TEXT NOT NULL UNIQUE,
            olusturan_id            INTEGER,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            audit_json              TEXT NOT NULL DEFAULT '[]',
            aktif                   INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (sevkiyat_id) REFERENCES mo_musteri_sevkiyat(id),
            FOREIGN KEY (tahsilat_kayit_id) REFERENCES mo_tahsilat_kayit(id),
            FOREIGN KEY (siparis_id) REFERENCES nexgen_planlama_siparis(id),
            FOREIGN KEY (cari_id) REFERENCES nexgen_cari(id)
        )
    """)
    log(f'[{MIGRATION_VERSION}] finans_belgesi created')


def _ensure_indexes(con: sqlite3.Connection) -> None:
    specs = (
        ('idx_fb_belge_tipi', 'CREATE INDEX IF NOT EXISTS idx_fb_belge_tipi ON finans_belgesi(belge_tipi)'),
        ('idx_fb_durum', 'CREATE INDEX IF NOT EXISTS idx_fb_durum ON finans_belgesi(durum)'),
        ('idx_fb_cari', 'CREATE INDEX IF NOT EXISTS idx_fb_cari ON finans_belgesi(cari_id)'),
        ('idx_fb_siparis', 'CREATE INDEX IF NOT EXISTS idx_fb_siparis ON finans_belgesi(siparis_id)'),
        ('idx_fb_islem_tarihi', 'CREATE INDEX IF NOT EXISTS idx_fb_islem_tarihi ON finans_belgesi(islem_tarihi)'),
        ('idx_fb_cari_har', 'CREATE INDEX IF NOT EXISTS idx_fb_cari_har ON finans_belgesi(cari_har_id)'),
    )
    for name, sql in specs:
        if not _index_exists(con, name):
            con.execute(sql)
            log(f'[{MIGRATION_VERSION}] index {name}')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] Finans Belgesi entity')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'finans_belgesi'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        _ensure_finans_belgesi(con)
        _ensure_indexes(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

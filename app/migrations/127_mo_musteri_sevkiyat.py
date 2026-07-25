# -*- coding: utf-8 -*-
"""
127_mo_musteri_sevkiyat.py
==========================
FAZ-MO-GERCEK-SEVKIYAT-MODULU-1 — Gerçek outbound müşteri sevkiyat entity.

grafik_sevkiyat ≠ bu modül (ithalat/CIN maliyet).
Üretim BITTI ≠ sevk edildi.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 127


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _ensure_sevkiyat(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'mo_musteri_sevkiyat'):
        return
    con.execute("""
        CREATE TABLE mo_musteri_sevkiyat (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            sevkiyat_no         TEXT NOT NULL UNIQUE,
            siparis_id          INTEGER NOT NULL,
            cari_id             INTEGER NOT NULL,
            durum               TEXT NOT NULL DEFAULT 'HAZIRLANIYOR',
            hazirlik_tarihi     TEXT,
            sevk_tarihi         TEXT,
            teslim_tarihi       TEXT,
            tamamlanma_tarihi   TEXT,
            arac_plaka          TEXT,
            sofor               TEXT,
            irsaliye_no         TEXT,
            kargo_firmasi       TEXT,
            kargo_takip_no      TEXT,
            teslim_alan         TEXT,
            teslim_durumu       TEXT,
            notlar              TEXT,
            idempotency_key     TEXT NOT NULL UNIQUE,
            olusturan_id        INTEGER NOT NULL,
            aktif               INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi   TEXT,
            audit_json          TEXT,
            FOREIGN KEY (siparis_id) REFERENCES nexgen_planlama_siparis(id),
            FOREIGN KEY (cari_id) REFERENCES nexgen_cari(id)
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mms_siparis ON mo_musteri_sevkiyat(siparis_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mms_cari ON mo_musteri_sevkiyat(cari_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mms_durum ON mo_musteri_sevkiyat(durum)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mms_sevk_tarihi ON mo_musteri_sevkiyat(sevk_tarihi)'
    )
    log(f'[{MIGRATION_VERSION}] mo_musteri_sevkiyat created')


def _ensure_kalem(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'mo_musteri_sevkiyat_kalem'):
        return
    con.execute("""
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            sevkiyat_id         INTEGER NOT NULL,
            siparis_kalem_id    INTEGER,
            urun_adi            TEXT,
            renk_ad             TEXT,
            formul_ad           TEXT,
            miktar_kg           REAL NOT NULL DEFAULT 0,
            miktar_adet         REAL,
            notlar              TEXT,
            olusturma_tarihi    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (sevkiyat_id) REFERENCES mo_musteri_sevkiyat(id) ON DELETE CASCADE,
            FOREIGN KEY (siparis_kalem_id) REFERENCES nexgen_planlama_siparis_kalem(id)
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mmsk_sevkiyat ON mo_musteri_sevkiyat_kalem(sevkiyat_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mmsk_sip_kalem ON mo_musteri_sevkiyat_kalem(siparis_kalem_id)'
    )
    log(f'[{MIGRATION_VERSION}] mo_musteri_sevkiyat_kalem created')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] MO müşteri sevkiyat')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'mo_musteri_sevkiyat'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        _ensure_sevkiyat(con)
        _ensure_kalem(con)
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

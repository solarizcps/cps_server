# -*- coding: utf-8 -*-
"""
123_musteri_operasyon_gorusme.py
=================================
FAZ-MUSTERI-OPERASYONU-GORUSME-MVP-1

crm_gorusme firma_id (crm_firma) ile bağlı — nexgen_cari Golden Master için yetersiz.
Minimal yeni tablo: musteri_operasyon_gorusme → nexgen_cari.id
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 123


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _ensure_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'musteri_operasyon_gorusme'):
        return
    con.execute("""
        CREATE TABLE musteri_operasyon_gorusme (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id                 INTEGER NOT NULL,
            kullanici_id            INTEGER NOT NULL,
            kaynak                  TEXT NOT NULL DEFAULT 'MUSTERI_OPERASYONU',
            gorusme_tipi            TEXT NOT NULL,
            sonuc_tipi              TEXT NOT NULL,
            sonuc_etiketler         TEXT,
            kisa_not                TEXT NOT NULL,
            gorusme_tarihi          TEXT NOT NULL,
            sonraki_takip_tarihi    TEXT,
            oncelik                 TEXT NOT NULL DEFAULT 'NORMAL',
            tahmini_siparis_tutari  REAL,
            tahmini_siparis_tarihi  TEXT,
            istenen_vade_gun        INTEGER,
            cek_alim_tarihi         TEXT,
            rakip_firma             TEXT,
            makina_notu             TEXT,
            detay_not               TEXT,
            dosya_ref               TEXT,
            idempotency_key         TEXT NOT NULL UNIQUE,
            aktif                   INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            olusturan_kullanici_id  INTEGER NOT NULL,
            audit_json              TEXT
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mog_cari ON musteri_operasyon_gorusme(cari_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mog_gorusme_tarihi ON musteri_operasyon_gorusme(gorusme_tarihi)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_mog_takip ON musteri_operasyon_gorusme(sonraki_takip_tarihi)'
    )
    log(f'[{MIGRATION_VERSION}] musteri_operasyon_gorusme created')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] musteri_operasyon_gorusme')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'musteri_operasyon_gorusme'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return

        con.execute('BEGIN IMMEDIATE')
        _ensure_table(con)
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

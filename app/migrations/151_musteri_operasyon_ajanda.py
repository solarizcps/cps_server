# -*- coding: utf-8 -*-
"""
151_musteri_operasyon_ajanda.py
================================
FAZ-MUSTERI-OPERASYONU-AJANDA-V1

Planlanmış görüşmeler — gerçekleşmiş görüşmeden ayrı canonical tablo.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 151


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _ensure_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'musteri_operasyon_ajanda'):
        return
    con.execute("""
        CREATE TABLE musteri_operasyon_ajanda (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id                 INTEGER NOT NULL,
            kullanici_id            INTEGER NOT NULL,
            plan_tarihi             TEXT NOT NULL,
            gorusme_tipi            TEXT NOT NULL,
            plan_notu               TEXT,
            durum                   TEXT NOT NULL DEFAULT 'PLANLANDI',
            gorusme_id              INTEGER,
            idempotency_key         TEXT NOT NULL UNIQUE,
            aktif                   INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            olusturan_kullanici_id  INTEGER NOT NULL,
            CHECK (durum IN ('PLANLANDI', 'GERCEKLESTI', 'IPTAL')),
            CHECK (aktif IN (0, 1)),
            CHECK (
                (durum = 'GERCEKLESTI' AND gorusme_id IS NOT NULL)
                OR (durum IN ('PLANLANDI', 'IPTAL'))
            )
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_kullanici_plan '
        'ON musteri_operasyon_ajanda(kullanici_id, plan_tarihi)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_cari '
        'ON musteri_operasyon_ajanda(cari_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_gorusme '
        'ON musteri_operasyon_ajanda(gorusme_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_durum '
        'ON musteri_operasyon_ajanda(durum)'
    )
    log(f'[{MIGRATION_VERSION}] musteri_operasyon_ajanda created')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] musteri_operasyon_ajanda')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'musteri_operasyon_ajanda'):
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

# -*- coding: utf-8 -*-
"""
144_musteri_operasyon_gorusme_fiyat_snapshot.py
==============================================
FAZ-MUSTERI-OPERASYONU-GORUSME-MODAL-FIYAT-KOSULLU-ALANLAR-1

Görüşme anındaki ticari fiyat/ödeme snapshot alanları (nullable).
Finans/sipariş/cari şart yazılmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 144
TABLE = 'musteri_operasyon_gorusme'
COLS = (
    ('fiyat_verildi', 'INTEGER NOT NULL DEFAULT 0'),
    ('verilen_fiyat', 'REAL'),
    ('fiyat_para_birimi', 'TEXT'),
    ('fiyat_birimi', 'TEXT'),
    ('odeme_tipi', 'TEXT'),
    ('vade_gun', 'INTEGER'),
    ('cek_vade_gun', 'INTEGER'),
    ('cek_adedi', 'INTEGER'),
    ('ticari_not', 'TEXT'),
    ('cek_notu', 'TEXT'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] gorusme fiyat snapshot starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok')

        existing = _columns(con, TABLE)
        if all(c in existing for c, _ in COLS):
            if _table_exists(con, 'schema_migrations'):
                applied = con.execute(
                    'SELECT version FROM schema_migrations WHERE version=?',
                    (MIGRATION_VERSION,),
                ).fetchone()
                if applied:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                    return

        con.execute('BEGIN IMMEDIATE')
        existing = _columns(con, TABLE)
        for col, decl in COLS:
            if col not in existing:
                con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {col} {decl}')
                log(f'[{MIGRATION_VERSION}] OK ADD {col}')
            else:
                log(f'[{MIGRATION_VERSION}] SKIP {col}')

        # eski kayıtlar: fiyat_verildi default 0 zaten; NULL gelenleri 0 yap
        if 'fiyat_verildi' in _columns(con, TABLE):
            con.execute(
                f"UPDATE {TABLE} SET fiyat_verildi=0 WHERE fiyat_verildi IS NULL"
            )

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'gorusme fiyat/odeme snapshot alanlari'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — committed')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

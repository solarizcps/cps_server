# -*- coding: utf-8 -*-
"""
135_nexgen_cari_genel_bilgiler.py
=================================
FAZ-YONETIM-CARI360-GENEL-BILGILER-TAMAMLAMA-1

nexgen_cari üzerine operasyonel/genel bilgi kolonları (nullable).
- kart_acilis_tarihi YOK (created_at kullanılır)
- minimum_siparis_kg REAL NULL
- finans / risk / kredi / ayrı adres tablosu YOK

Rollback notu:
  SQLite ALTER DROP desteklemez; geri dönüş için
  backup/faz_yonetim_cari360_genel_bilgiler_tamamlama_1_*/mock_data.db restore.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 135

NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ('kisa_ad', 'TEXT'),
    ('cari_tipi', 'TEXT'),
    ('kategori', 'TEXT'),
    ('yurt_durumu', 'TEXT'),
    ('vergi_dairesi', 'TEXT'),
    ('vergi_no', 'TEXT'),
    ('tc_kimlik_no', 'TEXT'),
    ('ticaret_sicil_no', 'TEXT'),
    ('mersis_no', 'TEXT'),
    ('e_fatura_mukellefi', 'INTEGER'),
    ('e_irsaliye_mukellefi', 'INTEGER'),
    ('telefon', 'TEXT'),
    ('telefon2', 'TEXT'),
    ('eposta', 'TEXT'),
    ('web', 'TEXT'),
    ('kep', 'TEXT'),
    ('fax', 'TEXT'),
    ('ulke', 'TEXT'),
    ('sehir', 'TEXT'),
    ('ilce', 'TEXT'),
    ('acik_adres', 'TEXT'),
    ('para_birimi', 'TEXT'),
    ('odeme_vadesi_gun', 'INTEGER'),
    ('fiyat_grubu', 'TEXT'),
    ('iskonto_orani', 'REAL'),
    ('minimum_siparis_kg', 'REAL'),
    ('teslim_sekli', 'TEXT'),
    ('dil', 'TEXT'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _schema_ok(con: sqlite3.Connection) -> bool:
    cols = _columns(con, 'nexgen_cari')
    return all(name in cols for name, _ in NEW_COLUMNS)


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] nexgen_cari genel bilgiler starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'nexgen_cari'):
            raise RuntimeError('nexgen_cari tablosu yok')

        if _table_exists(con, 'schema_migrations') and _schema_ok(con):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        con.execute('BEGIN IMMEDIATE')
        cols = _columns(con, 'nexgen_cari')
        for name, typ in NEW_COLUMNS:
            if name in cols:
                log(f'[{MIGRATION_VERSION}] SKIP kolon {name}')
                continue
            con.execute(f'ALTER TABLE nexgen_cari ADD COLUMN {name} {typ}')
            log(f'[{MIGRATION_VERSION}] OK ADD {name} {typ}')

        if not _schema_ok(con):
            raise RuntimeError('nexgen_cari genel bilgiler schema verify FAILED')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'nexgen_cari genel bilgi kolonları'),
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

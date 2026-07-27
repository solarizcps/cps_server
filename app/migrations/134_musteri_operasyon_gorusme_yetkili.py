# -*- coding: utf-8 -*-
"""
134_musteri_operasyon_gorusme_yetkili.py
=======================================
FAZ-CARI-GORUSME-YETKILI-BAGI-VE-CARI-KART-CRM-1

musteri_operasyon_gorusme'ye yetkili/konu/aksiyon/takip_durumu alanları.
Yeni tablo YOK. mo_gorusme_id zinciri bozulmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 134

YENI_KOLONLAR = (
    ('yetkili_id', 'INTEGER'),
    ('konu', 'TEXT'),
    ('sonraki_aksiyon', 'TEXT'),
    ('takip_durumu', 'TEXT'),  # ACIK | TAMAMLANDI | IPTAL
    ('guncelleyen_kullanici_id', 'INTEGER'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _cols(con, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _index_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone())


def _schema_ok(con) -> bool:
    if not _table_exists(con, 'musteri_operasyon_gorusme'):
        return False
    cols = _cols(con, 'musteri_operasyon_gorusme')
    for name, _ in YENI_KOLONLAR:
        if name not in cols:
            return False
    if not _index_exists(con, 'idx_mog_yetkili_id'):
        return False
    return True


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] gorusme yetkili bag starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'musteri_operasyon_gorusme'):
            raise RuntimeError('musteri_operasyon_gorusme yok — migration 123 gerekli')

        already = False
        if _table_exists(con, 'schema_migrations') and _schema_ok(con):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            already = bool(applied)

        con.execute('BEGIN IMMEDIATE')
        if not already:
            cols = _cols(con, 'musteri_operasyon_gorusme')
            for name, typ in YENI_KOLONLAR:
                if name in cols:
                    log(f'[{MIGRATION_VERSION}] SKIP kolon {name}')
                    continue
                con.execute(
                    f'ALTER TABLE musteri_operasyon_gorusme ADD COLUMN {name} {typ}'
                )
                log(f'[{MIGRATION_VERSION}] OK kolon {name}')

            if not _index_exists(con, 'idx_mog_yetkili_id'):
                con.execute(
                    'CREATE INDEX idx_mog_yetkili_id ON musteri_operasyon_gorusme(yetkili_id)'
                )
                log(f'[{MIGRATION_VERSION}] OK index idx_mog_yetkili_id')
            else:
                log(f'[{MIGRATION_VERSION}] SKIP index idx_mog_yetkili_id')

            if not _index_exists(con, 'idx_mog_takip_durumu'):
                con.execute(
                    'CREATE INDEX idx_mog_takip_durumu ON musteri_operasyon_gorusme(takip_durumu)'
                )
                log(f'[{MIGRATION_VERSION}] OK index idx_mog_takip_durumu')
        else:
            log(f'[{MIGRATION_VERSION}] schema already applied — backfill only')

        # Mevcut takip tarihli kayıtlar → ACIK (yalnız NULL durumlular; idempotent)
        cur = con.execute(
            """
            UPDATE musteri_operasyon_gorusme
            SET takip_durumu='ACIK'
            WHERE aktif=1
              AND sonraki_takip_tarihi IS NOT NULL
              AND TRIM(sonraki_takip_tarihi) <> ''
              AND (takip_durumu IS NULL OR TRIM(takip_durumu)='')
            """
        )
        log(f'[{MIGRATION_VERSION}] OK backfill takip_durumu ACIK rows={cur.rowcount}')

        if not _schema_ok(con):
            raise RuntimeError('134 schema verify FAILED')

        if _table_exists(con, 'schema_migrations'):
            cols_m = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)')]
            if 'aciklama' in cols_m:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'gorusme yetkili_id + konu + takip_durumu'),
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

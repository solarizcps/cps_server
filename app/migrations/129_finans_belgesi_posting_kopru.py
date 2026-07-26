# -*- coding: utf-8 -*-
"""
129_finans_belgesi_posting_kopru.py
====================================
FAZ-FINANS-1C1 — finans_belgesi kaynak/posting köprü kolonları.

Migration 128 tablosuna ALTER TABLE ile kolon ekler.
Tablo boşsa backfill yapılmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 129

YENI_KOLONLAR: tuple[tuple[str, str], ...] = (
    ('kaynak_tipi', 'TEXT'),
    ('kaynak_id', 'INTEGER'),
    ('siparis_kalem_id', 'INTEGER'),
    ('posting_tarihi', 'TEXT'),
    ('posting_kullanici_id', 'INTEGER'),
    ('posting_idempotency_key', 'TEXT'),
    ('posting_durumu', 'TEXT'),
    ('posting_hata', 'TEXT'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    if not _table_exists(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone())


def _ensure_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'finans_belgesi'):
        log(f'[{MIGRATION_VERSION}] finans_belgesi yok — atlanıyor')
        return
    for kolon, tip in YENI_KOLONLAR:
        if _kolon_var(con, 'finans_belgesi', kolon):
            continue
        con.execute(f'ALTER TABLE finans_belgesi ADD COLUMN {kolon} {tip}')
        log(f'[{MIGRATION_VERSION}] kolon eklendi: {kolon}')


def _ensure_indexes(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'finans_belgesi'):
        return
    specs = (
        (
            'idx_fb_kaynak_unique',
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_kaynak_unique
            ON finans_belgesi(belge_tipi, kaynak_tipi, kaynak_id)
            WHERE kaynak_tipi IS NOT NULL AND kaynak_id IS NOT NULL
            """,
        ),
        (
            'idx_fb_posting_idem_unique',
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_posting_idem_unique
            ON finans_belgesi(posting_idempotency_key)
            WHERE posting_idempotency_key IS NOT NULL
            """,
        ),
        (
            'idx_fb_posting_durum',
            'CREATE INDEX IF NOT EXISTS idx_fb_posting_durum ON finans_belgesi(posting_durumu)',
        ),
        (
            'idx_fb_kaynak_lookup',
            'CREATE INDEX IF NOT EXISTS idx_fb_kaynak_lookup ON finans_belgesi(kaynak_tipi, kaynak_id)',
        ),
    )
    for name, sql in specs:
        if not _index_exists(con, name):
            con.execute(sql)
            log(f'[{MIGRATION_VERSION}] index {name}')


def _backfill_if_needed(con: sqlite3.Connection) -> None:
    """Satır varsa dry-run listele; apply yapma."""
    if not _table_exists(con, 'finans_belgesi'):
        return
    n = int(con.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0])
    if n == 0:
        log(f'[{MIGRATION_VERSION}] backfill SKIP — tablo boş')
        return
    aday = con.execute(
        """
        SELECT id, belge_tipi, sevkiyat_id, tahsilat_kayit_id, kaynak_tipi, kaynak_id
        FROM finans_belgesi WHERE aktif=1
        """
    ).fetchall()
    log(f'[{MIGRATION_VERSION}] backfill DRY-RUN — {len(aday)} satır (apply yapılmadı)')
    for r in aday:
        log(f'  id={r[0]} tip={r[1]} sevk={r[2]} tah={r[3]} kaynak=({r[4]},{r[5]})')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] Finans Belgesi posting köprü kolonları')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _kolon_var(con, 'finans_belgesi', 'kaynak_tipi'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        _ensure_columns(con)
        _ensure_indexes(con)
        _backfill_if_needed(con)
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

# -*- coding: utf-8 -*-
"""
124_mo_numune_talep_kopru.py
=============================
FAZ-MUSTERI-OPERASYONU-NUMUNE-TALEBI-BACKEND-1

nexgen_numune_talep — Müşteri Operasyonu merkezi onay köprüsü:
  kaynak_modul, mo_gorusme_id, idempotency_key, onay_notu,
  musteri_urun_kodu, revizyon_gerekce, dosya_ref
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 124

YENI_KOLONLAR = (
    ('kaynak_modul', 'TEXT'),
    ('mo_gorusme_id', 'INTEGER'),
    ('idempotency_key', 'TEXT'),
    ('onay_notu', 'TEXT'),
    ('musteri_urun_kodu', 'TEXT'),
    ('revizyon_gerekce', 'TEXT'),
    ('dosya_ref', 'TEXT'),
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


def _kolon_var(con, tablo: str, kolon: str) -> bool:
    if not _table_exists(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _ensure_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'nexgen_numune_talep'):
        log(f'[{MIGRATION_VERSION}] nexgen_numune_talep yok — atlanıyor')
        return
    for kolon, tip in YENI_KOLONLAR:
        if _kolon_var(con, 'nexgen_numune_talep', kolon):
            continue
        con.execute(f'ALTER TABLE nexgen_numune_talep ADD COLUMN {kolon} {tip}')
        log(f'[{MIGRATION_VERSION}] kolon eklendi: {kolon}')
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nnt_idempotency
        ON nexgen_numune_talep(idempotency_key)
        WHERE idempotency_key IS NOT NULL AND idempotency_key != ''
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_nnt_kaynak_modul
        ON nexgen_numune_talep(kaynak_modul, durum)
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_nnt_mo_gorusme
        ON nexgen_numune_talep(mo_gorusme_id)
        WHERE mo_gorusme_id IS NOT NULL
        """
    )


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] MO numune köprü kolonları')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _kolon_var(con, 'nexgen_numune_talep', 'kaynak_modul'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return
        con.execute('BEGIN IMMEDIATE')
        _ensure_columns(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] tamamlandı')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

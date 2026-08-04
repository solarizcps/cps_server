# -*- coding: utf-8 -*-
"""
149_nexgen_planlama_siparis_kalem_mtt_pointer.py
================================================
FAZ-MTT-KALEM-POINTER-PERSIST-149

nexgen_planlama_siparis_kalem.mtt_kalem_id INTEGER NULL
  -> nexgen_musteri_temsilcisi_talep_kalem.id (mantıksal FK)

- Mevcut kayıtlar NULL kalır (tahmini backfill YOK)
- Partial UNIQUE: aynı MTT kalemi ikinci sipariş satırında kullanılamaz
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime

MIGRATION_VERSION = 149
TABLE = 'nexgen_planlama_siparis_kalem'
COL = 'mtt_kalem_id'
SRC_TABLE = 'nexgen_musteri_temsilcisi_talep_kalem'
IDX_PTR = 'idx_npsk_mtt_kalem_ptr_uq'


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


def _index_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,),
    ).fetchone())


def _backup_db(db_path: str) -> tuple[str, str]:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'backup', f'mig149_pre_{ts}')
    )
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, 'mock_data.db')
    shutil.copy2(db_path, dest)
    with open(dest, 'rb') as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    sha_path = dest + '.sha256'
    with open(sha_path, 'w', encoding='utf-8') as fh:
        fh.write(digest + '\n')
    log(f'[{MIGRATION_VERSION}] BACKUP {dest}')
    log(f'[{MIGRATION_VERSION}] SHA256 {digest}')
    return dest, digest


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] {COL} starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    if not _table_exists(sqlite3.connect(db_path), TABLE):
        raise RuntimeError(f'{TABLE} yok')

    _backup_db(db_path)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} yok')
        if not _table_exists(con, SRC_TABLE):
            raise RuntimeError(f'{SRC_TABLE} yok — migration 146 gerekli')

        cols = _columns(con, TABLE)
        if COL in cols and _index_exists(con, IDX_PTR):
            if _table_exists(con, 'schema_migrations'):
                applied = con.execute(
                    'SELECT version FROM schema_migrations WHERE version=?',
                    (MIGRATION_VERSION,),
                ).fetchone()
                if applied:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                    return

        con.execute('BEGIN IMMEDIATE')
        if COL not in _columns(con, TABLE):
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COL} INTEGER')
            log(f'[{MIGRATION_VERSION}] OK ADD {COL}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP kolon {COL}')

        if COL not in _columns(con, TABLE):
            raise RuntimeError('schema verify FAILED — kolon yok')

        # SQLite ALTER ile hard FK eklenemez; mantıksal FK: SRC_TABLE.id
        if not _index_exists(con, IDX_PTR):
            con.execute(
                f'CREATE UNIQUE INDEX {IDX_PTR} ON {TABLE}({COL}) '
                f'WHERE {COL} IS NOT NULL'
            )
            log(f'[{MIGRATION_VERSION}] OK UNIQUE INDEX {IDX_PTR}')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP index {IDX_PTR}')

        con.execute(
            f'CREATE INDEX IF NOT EXISTS idx_npsk_mtt_kalem_id ON {TABLE}({COL})'
        )

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            aciklama = (
                f'siparis_kalem.{COL} nullable → {SRC_TABLE}.id '
                f'(partial unique, no backfill)'
            )
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, aciklama),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] DONE')
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()

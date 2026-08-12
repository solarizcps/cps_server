# -*- coding: utf-8 -*-
"""
Migration 151 — musteri_operasyon_ajanda — güvenli tek-migration apply.

Kullanım (server RDP):
  python app/tools/apply_migration_151_ajanda.py --db C:\\Solariz_CPS_SERVER\\app\\mock_data.db --check
  python app/tools/apply_migration_151_ajanda.py --db C:\\Solariz_CPS_SERVER\\app\\mock_data.db --apply

Backup almaz — operatör backup'ı apply öncesi alır.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

MIGRATION_VERSION = 151
TABLE = 'musteri_operasyon_ajanda'
EXPECTED_COLUMNS = (
    'id', 'cari_id', 'kullanici_id', 'plan_tarihi', 'gorusme_tipi', 'plan_notu',
    'durum', 'gorusme_id', 'idempotency_key', 'aktif', 'olusturma_tarihi',
    'guncelleme_tarihi', 'olusturan_kullanici_id',
)
EXPECTED_INDEXES = (
    'idx_moa_kullanici_plan', 'idx_moa_cari', 'idx_moa_gorusme', 'idx_moa_durum',
)
PROTECTED_COUNTS = (
    'musteri_operasyon_gorusme',
    'nexgen_planlama_siparis',
    'Cari_Har',
)


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _migration_applied(con: sqlite3.Connection) -> bool:
    if not _table_exists(con, 'schema_migrations'):
        return False
    return bool(con.execute(
        'SELECT 1 FROM schema_migrations WHERE version=?', (str(MIGRATION_VERSION),),
    ).fetchone())


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _count_safe(con: sqlite3.Connection, table: str) -> int | None:
    if not _table_exists(con, table):
        return None
    return int(con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])


def preflight(db: str) -> dict:
    db = os.path.abspath(db)
    if not os.path.isfile(db):
        raise FileNotFoundError(f'DB not found: {db}')

    con = _connect(db)
    try:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        ajanda_exists = _table_exists(con, TABLE)
        mig151 = _migration_applied(con)
        counts = {t: _count_safe(con, t) for t in PROTECTED_COUNTS}
        return {
            'db': db,
            'sha256': _sha256(db),
            'integrity': integrity,
            'ajanda_exists': ajanda_exists,
            'migration_151': mig151,
            'protected_counts': counts,
            'needs_apply': not (ajanda_exists and mig151),
        }
    finally:
        con.close()


def post_verify(db: str, pre_counts: dict[str, int | None]) -> dict:
    con = _connect(db)
    try:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        if not _table_exists(con, TABLE):
            raise RuntimeError(f'{TABLE} missing after apply')

        cols = [r[1] for r in con.execute(f'PRAGMA table_info({TABLE})').fetchall()]
        if tuple(cols) != EXPECTED_COLUMNS:
            raise RuntimeError(f'column mismatch: {cols}')

        indexes = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (TABLE,),
            ).fetchall()
        ]
        for idx in EXPECTED_INDEXES:
            if idx not in indexes:
                raise RuntimeError(f'missing index: {idx}')

        if not _migration_applied(con):
            raise RuntimeError('schema_migrations 151 missing after apply')

        post_counts = {t: _count_safe(con, t) for t in PROTECTED_COUNTS}
        for t, before in pre_counts.items():
            after = post_counts.get(t)
            if before is not None and after is not None and before != after:
                raise RuntimeError(f'{t} count changed: {before} -> {after}')

        return {
            'integrity': integrity,
            'ajanda_count': _count_safe(con, TABLE),
            'protected_counts': post_counts,
            'sha256': _sha256(db),
        }
    finally:
        con.close()


def apply_migration(db: str) -> dict:
    pre = preflight(db)
    if not pre['needs_apply']:
        return {'ok': True, 'action': 'SKIP', 'reason': 'already applied', 'pre': pre}

    if pre['integrity'] != 'ok':
        raise RuntimeError(f"integrity_check failed: {pre['integrity']}")

    mod = importlib.import_module('migrations.151_musteri_operasyon_ajanda')
    mod.run(db)

    post = post_verify(db, pre['protected_counts'])
    if post['integrity'] != 'ok':
        raise RuntimeError(f"post integrity_check failed: {post['integrity']}")

    return {'ok': True, 'action': 'APPLIED', 'pre': pre, 'post': post}


def main() -> None:
    ap = argparse.ArgumentParser(description='Apply migration 151 (Ajanda) safely')
    ap.add_argument('--db', required=True, help='Absolute path to mock_data.db')
    ap.add_argument('--check', action='store_true', help='Preflight only')
    ap.add_argument('--apply', action='store_true', help='Apply migration 151')
    args = ap.parse_args()

    db = os.path.abspath(args.db)
    canonical_hint = os.path.abspath(str(APP / 'mock_data.db'))

    if not args.check and not args.apply:
        args.check = True

    print(f'DB path     : {db}')
    print(f'Canonical   : {canonical_hint}')
    pre = preflight(db)
    print(f'SHA256      : {pre["sha256"]}')
    print(f'Integrity   : {pre["integrity"]}')
    print(f'Ajanda table: {pre["ajanda_exists"]}')
    print(f'Migration151: {pre["migration_151"]}')
    print(f'Needs apply : {pre["needs_apply"]}')
    for t, c in pre['protected_counts'].items():
        print(f'  {t}: {c}')

    if args.check and not args.apply:
        sys.exit(0 if pre['integrity'] == 'ok' else 1)

    if args.apply:
        result = apply_migration(db)
        print(f'Result: {result["action"]}')
        if result['action'] == 'APPLIED':
            print(f'Post SHA256 : {result["post"]["sha256"]}')
            print(f'Ajanda count: {result["post"]["ajanda_count"]}')
        sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()

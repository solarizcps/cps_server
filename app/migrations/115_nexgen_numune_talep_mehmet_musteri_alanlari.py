# -*- coding: utf-8 -*-
"""
115_nexgen_numune_talep_mehmet_musteri_alanlari.py
===================================================
FAZ-NUMUNE-YENI-TALEP-TAMAMLAMA-1

Mehmet numune talep — müşteri/numune kalıcı alanları.
Yalnız nexgen_numune_talep tablosuna kolon ekler.

Idempotent: ALTER guarded by PRAGMA table_info.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

MIGRATION_VERSION = 115

YENI_KOLONLAR = (
    ('karsilama_yolu', 'TEXT'),
    ('numune_adedi', 'INTEGER'),
    ('beden_kalip', 'TEXT'),
    ('patch_aksesuar_var', 'INTEGER NOT NULL DEFAULT 0'),
    ('patch_aksesuar_aciklama', 'TEXT'),
    ('paketleme_notu', 'TEXT'),
    ('kargo_teslim_notu', 'TEXT'),
    ('kullanim_amaci', 'TEXT'),
    ('benzer_urun_numune', 'TEXT'),
)


def log(msg: str) -> None:
    print(msg)


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info({tablo})').fetchall()]
    return kolon in cols


def _plan(con: sqlite3.Connection) -> list[tuple[str, str]]:
    plan: list[tuple[str, str]] = []
    for kolon, tip in YENI_KOLONLAR:
        if not _kolon_var(con, 'nexgen_numune_talep', kolon):
            plan.append((kolon, tip))
    return plan


def run(db_path: str | None = None, *, dry_run: bool = False) -> dict:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] mehmet musteri alanlari starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    if dry_run:
        log(f'[{MIGRATION_VERSION}] MODE: DRY-RUN (no writes)')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    result = {'applied': False, 'skipped': False, 'planned': [], 'dry_run': dry_run}
    try:
        has_sm = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if has_sm:
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (str(MIGRATION_VERSION),),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                result['skipped'] = True
                return result

        plan = _plan(con)
        result['planned'] = [k for k, _ in plan]
        if not plan:
            log(f'[{MIGRATION_VERSION}] All columns exist — nothing to do')
            if has_sm and not dry_run:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (str(MIGRATION_VERSION),),
                )
                con.commit()
            result['skipped'] = True
            return result

        for kolon, tip in plan:
            sql = f'ALTER TABLE nexgen_numune_talep ADD COLUMN {kolon} {tip}'
            log(f'[{MIGRATION_VERSION}] PLAN: {sql}')
            if not dry_run:
                con.execute(sql)
                log(f'[{MIGRATION_VERSION}] + nexgen_numune_talep.{kolon}')

        if dry_run:
            log(f'[{MIGRATION_VERSION}] DRY-RUN OK — {len(plan)} column(s) would be added')
            return result

        if has_sm:
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (str(MIGRATION_VERSION),),
            )
        con.commit()
        result['applied'] = True
        log(f'[{MIGRATION_VERSION}] OK')
        return result
    except Exception:
        if not dry_run:
            con.rollback()
            log(f'[{MIGRATION_VERSION}] ROLLBACK')
        raise
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Migration {MIGRATION_VERSION}')
    parser.add_argument('--dry-run', action='store_true', help='Plan only, no DB writes')
    parser.add_argument('--db', default=None, help='Optional DB path override')
    args = parser.parse_args(argv)
    try:
        run(args.db, dry_run=args.dry_run)
        return 0
    except Exception as exc:
        log(f'[{MIGRATION_VERSION}] HATA: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

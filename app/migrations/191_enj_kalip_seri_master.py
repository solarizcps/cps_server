# -*- coding: utf-8 -*-
"""
Migration 191 — enj_kalip seri/grup master + enj_kalip ek alanlar
==================================================================

Yeni tablolar (başlangıçta boş):
  - enj_kalip_seri
  - enj_kalip_seri_uye

enj_kalip ek kolonlar (mevcut veri değiştirilmez):
  - aktif_goz_sayisi INTEGER NULL
  - kapasite_onayli INTEGER NOT NULL DEFAULT 0

Prefix/model otomatik seri üretimi YOK.
Canonical DB yazımı guard ile engellenir.
"""
from __future__ import annotations

import sqlite3
import sys

MIGRATION_VERSION = 191
ACIKLAMA = 'enj_kalip_seri master + uye tablosu + enj_kalip aktif_goz/kapasite_onayli'
SERI_TABLE = 'enj_kalip_seri'
UYE_TABLE = 'enj_kalip_seri_uye'
KALIP_TABLE = 'enj_kalip'

ENJ_KALIP_NEW_COLS: list[tuple[str, str, str]] = [
    ('aktif_goz_sayisi', 'INTEGER', 'NULL'),
    ('kapasite_onayli', 'INTEGER', "NOT NULL DEFAULT 0"),
]

SERI_CREATE_SQL = f"""CREATE TABLE IF NOT EXISTS {SERI_TABLE} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seri_kod        TEXT NOT NULL COLLATE NOCASE,
    seri_ad         TEXT,
    model_kod       TEXT NOT NULL,
    model_ad        TEXT,
    aciklama        TEXT,
    aktif           INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_by      INTEGER,
    updated_by      INTEGER,
    UNIQUE (seri_kod)
)"""

UYE_CREATE_SQL = f"""CREATE TABLE IF NOT EXISTS {UYE_TABLE} (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    seri_id                 INTEGER NOT NULL,
    kalip_id                INTEGER NOT NULL,
    uye_rolu                TEXT NOT NULL CHECK (uye_rolu IN ('GOVDE', 'ATKI', 'DIGER')),
    beden_numara            TEXT,
    sira_no                 INTEGER,
    varsayilan_fiziksel_adet INTEGER,
    aktif                   INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_by              INTEGER,
    updated_by              INTEGER,
    FOREIGN KEY (seri_id) REFERENCES {SERI_TABLE}(id),
    FOREIGN KEY (kalip_id) REFERENCES {KALIP_TABLE}(id),
    UNIQUE (seri_id, kalip_id),
    CHECK (varsayilan_fiziksel_adet IS NULL OR varsayilan_fiziksel_adet > 0),
    CHECK (sira_no IS NULL OR sira_no > 0)
)"""

INDEX_SQL = [
    f'CREATE INDEX IF NOT EXISTS idx_enj_kalip_seri_model ON {SERI_TABLE}(model_kod, aktif)',
    f'CREATE INDEX IF NOT EXISTS idx_enj_kalip_seri_uye_seri ON {UYE_TABLE}(seri_id, aktif)',
    f'CREATE INDEX IF NOT EXISTS idx_enj_kalip_seri_uye_kalip ON {UYE_TABLE}(kalip_id)',
]


def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return bool(cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _col_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    return col in {r[1] for r in cur.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_kalip_columns(cur: sqlite3.Cursor) -> list[str]:
    if not _table_exists(cur, KALIP_TABLE):
        raise RuntimeError(f'{KALIP_TABLE} tablosu bulunamadı')
    added: list[str] = []
    for col, typ, extra in ENJ_KALIP_NEW_COLS:
        if _col_exists(cur, KALIP_TABLE, col):
            continue
        cur.execute(f'ALTER TABLE {KALIP_TABLE} ADD COLUMN {col} {typ} {extra}')
        added.append(col)
    return added


def _ensure_series_tables(cur: sqlite3.Cursor) -> None:
    cur.execute(SERI_CREATE_SQL)
    cur.execute(UYE_CREATE_SQL)
    for sql in INDEX_SQL:
        cur.execute(sql)


def _write_migration_record(cur: sqlite3.Cursor) -> None:
    try:
        cur.execute(
            'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
            (str(MIGRATION_VERSION), ACIKLAMA),
        )
    except sqlite3.OperationalError:
        cur.execute(
            'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
            (str(MIGRATION_VERSION),),
        )


def run(db_path: str | None = None, *, allow_canonical: bool = False,
        _inject_failure: bool = False) -> dict:
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    _log('=' * 70)
    _log(f'[{MIGRATION_VERSION}] {SERI_TABLE} + {UYE_TABLE}')
    _log(f'[{MIGRATION_VERSION}] DB: {path}')
    _log('=' * 70)

    con = sqlite3.connect(path, timeout=15, isolation_level=None)
    cur = con.cursor()
    result: dict = {
        'ok': False,
        'db_path': path,
        'version': MIGRATION_VERSION,
        'added_kalip_cols': [],
    }
    try:
        already = cur.execute(
            'SELECT version FROM schema_migrations WHERE version=?',
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f'[{MIGRATION_VERSION}] SKIP — zaten uygulanmış')
            result.update({'ok': True, 'skipped': True})
            return result

        cur.execute('BEGIN IMMEDIATE')
        result['added_kalip_cols'] = _add_kalip_columns(cur)
        _ensure_series_tables(cur)

        if _inject_failure:
            raise RuntimeError('_inject_failure: atomiklik testi')

        _write_migration_record(cur)
        cur.execute('COMMIT')
        result['ok'] = True
        _log(f'[{MIGRATION_VERSION}] COMMIT OK added_kalip_cols={result["added_kalip_cols"]}')
        return result

    except Exception as exc:
        try:
            cur.execute('ROLLBACK')
        except Exception:
            pass
        _log(f'[{MIGRATION_VERSION}] ROLLBACK — {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=f'Migration {MIGRATION_VERSION}')
    parser.add_argument('--db-path', required=True)
    parser.add_argument('--allow-canonical', action='store_true')
    args = parser.parse_args()
    print(run(args.db_path, allow_canonical=args.allow_canonical))

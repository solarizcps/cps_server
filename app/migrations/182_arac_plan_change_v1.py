# -*- coding: utf-8 -*-
"""
182_arac_plan_change_v1.py
Plan değişikliği / iptal / erteleme — durum genişletmesi + audit + idempotency.

Değişiklikler:
  - arac_gunluk_plan_is.durum CHECK → ERTELENDI, GIDILEMEDI eklenir (idempotent rebuild)
  - CREATE TABLE arac_plan_is_degisim (+ idempotency index)

Bağımlılık: 181

Güvenlik:
  run(db_path) zorunlu — hard-coded canonical fallback YOK.
  Canonical hedef için allow_canonical=True gerekir.
"""
from __future__ import annotations

import sqlite3

MIGRATION_VERSION = 182

_EXTENDED_STATUSES = ('ERTELENDI', 'GIDILEMEDI')
_VALID_DURUM = (
    'PLANLANDI', 'BASLADI', 'TAMAMLANDI', 'IPTAL', 'ERTELENDI', 'GIDILEMEDI',
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


def _plan_is_status_check_extended(con: sqlite3.Connection) -> bool:
    if not _table_exists(con, 'arac_gunluk_plan_is'):
        return False
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='arac_gunluk_plan_is'",
    ).fetchone()
    ddl = (row[0] or '') if row else ''
    return all(s in ddl for s in _EXTENDED_STATUSES)


def _rebuild_plan_is_status_check(con: sqlite3.Connection) -> bool:
    """Rebuild CHECK constraint; preserve all columns and rows. Returns True if rebuilt."""
    if not _table_exists(con, 'arac_gunluk_plan_is'):
        log(f'[{MIGRATION_VERSION}] SKIP — arac_gunluk_plan_is yok')
        return False
    if _plan_is_status_check_extended(con):
        log(f'[{MIGRATION_VERSION}] SKIP — durum CHECK zaten genişletilmiş')
        return False

    rows = con.execute('SELECT * FROM arac_gunluk_plan_is').fetchall()
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    con.execute('DROP TABLE arac_gunluk_plan_is')
    con.execute("""
        CREATE TABLE arac_gunluk_plan_is (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            is_talebi_id INTEGER NOT NULL UNIQUE,
            sira INTEGER NOT NULL,
            planlanan_saat TEXT,
            durum TEXT NOT NULL DEFAULT 'PLANLANDI',
            created_at TEXT NOT NULL,
            created_by INTEGER,
            FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id),
            FOREIGN KEY (is_talebi_id) REFERENCES arac_is_talebi(id),
            CHECK (durum IN (
                'PLANLANDI','BASLADI','TAMAMLANDI','IPTAL','ERTELENDI','GIDILEMEDI'
            )),
            UNIQUE (plan_id, sira)
        )
    """)
    con.execute(
        'CREATE INDEX idx_arac_gunluk_plan_is_plan ON arac_gunluk_plan_is(plan_id, sira)',
    )
    if rows:
        placeholders = ','.join('?' * len(cols))
        col_list = ','.join(cols)
        for row in rows:
            data = {cols[i]: row[i] for i in range(len(cols))}
            st = data.get('durum') or 'PLANLANDI'
            if st not in _VALID_DURUM:
                data['durum'] = 'PLANLANDI'
            con.execute(
                f'INSERT INTO arac_gunluk_plan_is ({col_list}) VALUES ({placeholders})',
                tuple(data[c] for c in cols),
            )
    log(f'[{MIGRATION_VERSION}] REBUILD arac_gunluk_plan_is CHECK ({len(rows)} satır korundu)')
    return True


def _ensure_plan_is_degisim(con: sqlite3.Connection) -> bool:
    """Create audit table if missing. Returns True if created."""
    if _table_exists(con, 'arac_plan_is_degisim'):
        log(f'[{MIGRATION_VERSION}] SKIP — arac_plan_is_degisim zaten mevcut')
        return False
    con.execute("""
        CREATE TABLE arac_plan_is_degisim (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_is_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            old_plan_tarihi TEXT,
            new_plan_tarihi TEXT,
            old_arac_external_id TEXT,
            new_arac_external_id TEXT,
            old_durum TEXT,
            new_durum TEXT,
            new_plan_is_id INTEGER,
            metadata_json TEXT,
            client_submit_id TEXT,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            FOREIGN KEY (plan_is_id) REFERENCES arac_gunluk_plan_is(id)
        )
    """)
    con.execute(
        'CREATE INDEX idx_arac_plan_is_degisim_item ON arac_plan_is_degisim(plan_is_id, created_at)',
    )
    con.execute("""
        CREATE UNIQUE INDEX idx_arac_plan_change_idempotency
        ON arac_plan_is_degisim(client_submit_id)
        WHERE client_submit_id IS NOT NULL
    """)
    log(f'[{MIGRATION_VERSION}] CREATE arac_plan_is_degisim')
    return True


def run(db_path: str, *, allow_canonical: bool = False) -> None:
    """
    db_path: absolute path to target SQLite DB (zorunlu).
    allow_canonical: True değilse canonical mock_data.db reddedilir.
    """
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_plan_change_v1')
    log(f'[{MIGRATION_VERSION}] DB: {path}')
    con = sqlite3.connect(path, timeout=30)
    try:
        rebuilt = _rebuild_plan_is_status_check(con)
        created = _ensure_plan_is_degisim(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        if not rebuilt and not created:
            log(f'[{MIGRATION_VERSION}] OK — zaten uygulanmış (idempotent skip)')
        else:
            log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migration 182 — plan change audit')
    parser.add_argument('--db-path', required=True, help='Hedef SQLite DB absolute path')
    parser.add_argument(
        '--allow-canonical',
        action='store_true',
        help='Canonical mock_data.db hedefine yazmaya izin ver',
    )
    args = parser.parse_args()
    run(args.db_path, allow_canonical=args.allow_canonical)

# -*- coding: utf-8 -*-
"""158 — uretim_model_plan (Planlama > Üretim Plan CPS kayıtları)."""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 158
MEHMET_KADI = 'mehmet'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _ensure_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'uretim_model_plan'):
        return
    con.execute("""
        CREATE TABLE uretim_model_plan (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            sip_no              INTEGER NOT NULL,
            sip_harinx          INTEGER NOT NULL,
            mamul_skod          TEXT NOT NULL,
            rkod                INTEGER NOT NULL DEFAULT 0,
            model_adi           TEXT,
            renk_adi            TEXT,
            miktar              REAL,
            termin              TEXT,
            plan_donemi         TEXT NOT NULL,
            plan_baslangic      TEXT,
            plan_bitis          TEXT,
            oncelik             INTEGER NOT NULL DEFAULT 3,
            plan_gerekce        TEXT,
            plan_notu           TEXT,
            aktif               INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            created_by          INTEGER,
            updated_at          TEXT,
            updated_by          INTEGER,
            CHECK (aktif IN (0, 1)),
            CHECK (oncelik BETWEEN 1 AND 5)
        )
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_uretim_model_plan_aktif
        ON uretim_model_plan(sip_no, sip_harinx, mamul_skod, rkod, plan_donemi)
        WHERE aktif = 1
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_ump_donem '
        'ON uretim_model_plan(plan_donemi, aktif)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_ump_tarih '
        'ON uretim_model_plan(plan_baslangic, plan_bitis)'
    )
    log(f'[{MIGRATION_VERSION}] uretim_model_plan created')


def _mehmet_planlama_edit(con: sqlite3.Connection) -> None:
    """Mehmet — planlama create/update (can_view zaten var)."""
    row = con.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1",
        (MEHMET_KADI,),
    ).fetchone()
    yetki = con.execute(
        "SELECT Id FROM sistem_yetki WHERE Kod='planlama'"
    ).fetchone()
    if not row or not yetki:
        log(f'[{MIGRATION_VERSION}] mehmet/planlama yetki atlanıyor')
        return
    uid, yid = int(row[0]), int(yetki[0])
    cols = {r[1] for r in con.execute('PRAGMA table_info(user_permission_override)').fetchall()}
    if not cols:
        return
    existing = con.execute(
        'SELECT Id FROM user_permission_override WHERE KullaniciId=? AND YetkiId=?',
        (uid, yid),
    ).fetchone()
    if existing:
        con.execute("""
            UPDATE user_permission_override
               SET can_create=1, can_update=1, can_delete=0
             WHERE KullaniciId=? AND YetkiId=?
        """, (uid, yid))
    else:
        con.execute("""
            INSERT INTO user_permission_override
                (KullaniciId, YetkiId, can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 1, 1, 0, 0, 0, 0)
        """, (uid, yid))
    log(f'[{MIGRATION_VERSION}] mehmet planlama can_create/update=1')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] uretim_model_plan')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'uretim_model_plan'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return

        con.execute('BEGIN IMMEDIATE')
        _ensure_table(con)
        _mehmet_planlama_edit(con)
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

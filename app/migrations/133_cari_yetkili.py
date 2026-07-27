# -*- coding: utf-8 -*-
"""
133_cari_yetkili.py
===================
FAZ-CARI-YETKILI-MODEL-1

Müşteri tarafı cari yetkilileri (cari_yetkili).
İç pazarlamacı ataması (cari_sorumlu) ile karıştırılmaz.
Yeni yetki kodu eklenmez — mevcut cari360.crm.write / view kullanılır.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 133


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone())


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


REQUIRED_COLS = (
    'id', 'cari_id', 'ad_soyad', 'unvan', 'departman', 'telefon',
    'cep_telefonu', 'eposta', 'ana_yetkili', 'aktif', 'notlar',
    'created_at', 'updated_at', 'created_by', 'updated_by',
)


def _ensure_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'cari_yetkili'):
        cols = _columns(con, 'cari_yetkili')
        missing = [c for c in REQUIRED_COLS if c not in cols]
        if missing:
            raise RuntimeError(f'cari_yetkili eksik kolonlar: {missing}')
        log('[133] SKIP cari_yetkili — tablo zaten var')
        return

    con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE cari_yetkili (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id         INTEGER NOT NULL,
            ad_soyad        TEXT NOT NULL,
            unvan           TEXT,
            departman       TEXT,
            telefon         TEXT,
            cep_telefonu    TEXT,
            eposta          TEXT,
            ana_yetkili     INTEGER NOT NULL DEFAULT 0,
            aktif           INTEGER NOT NULL DEFAULT 1,
            notlar          TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            created_by      INTEGER,
            updated_by      INTEGER,
            FOREIGN KEY (cari_id) REFERENCES nexgen_cari(id) ON DELETE RESTRICT,
            FOREIGN KEY (created_by) REFERENCES sistem_kullanici(Id) ON DELETE SET NULL,
            FOREIGN KEY (updated_by) REFERENCES sistem_kullanici(Id) ON DELETE SET NULL
        );
    """)
    log('[133] OK cari_yetkili tablosu oluşturuldu')


def _ensure_indexes(con: sqlite3.Connection) -> None:
    specs = (
        (
            'idx_cari_yetkili_cari_id',
            'CREATE INDEX idx_cari_yetkili_cari_id ON cari_yetkili(cari_id)',
        ),
        (
            'idx_cari_yetkili_cari_aktif',
            'CREATE INDEX idx_cari_yetkili_cari_aktif ON cari_yetkili(cari_id, aktif)',
        ),
        (
            'uq_cari_yetkili_ana_aktif',
            """
            CREATE UNIQUE INDEX uq_cari_yetkili_ana_aktif
                ON cari_yetkili(cari_id)
                WHERE ana_yetkili=1 AND aktif=1
            """,
        ),
    )
    for name, sql in specs:
        if _index_exists(con, name):
            log(f'[133] SKIP index {name}')
            continue
        con.execute(sql)
        log(f'[133] OK index {name}')


def _schema_ok(con: sqlite3.Connection) -> bool:
    if not _table_exists(con, 'cari_yetkili'):
        return False
    cols = _columns(con, 'cari_yetkili')
    if any(c not in cols for c in REQUIRED_COLS):
        return False
    for idx in (
        'idx_cari_yetkili_cari_id',
        'idx_cari_yetkili_cari_aktif',
        'uq_cari_yetkili_ana_aktif',
    ):
        if not _index_exists(con, idx):
            return False
    return True


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] cari_yetkili starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')

        if _table_exists(con, 'schema_migrations') and _schema_ok(con):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied (idempotent)')
                return

        con.execute('BEGIN IMMEDIATE')
        _ensure_table(con)
        _ensure_indexes(con)

        if not _schema_ok(con):
            raise RuntimeError('cari_yetkili schema verify FAILED')

        cnt = con.execute('SELECT COUNT(*) FROM cari_yetkili').fetchone()[0]
        log(f'[{MIGRATION_VERSION}] cari_yetkili satır: {cnt}')

        if _table_exists(con, 'schema_migrations'):
            cols = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in cols:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'cari_yetkili — müşteri yetkili modeli'),
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

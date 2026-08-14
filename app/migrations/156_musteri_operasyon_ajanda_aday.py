# -*- coding: utf-8 -*-
"""
156_musteri_operasyon_ajanda_aday.py
====================================
FAZ-2A — Ajanda aday desteği (tasarım doc: Migration 152).

musteri_operasyon_ajanda:
- cari_id nullable
- musteri_aday_id INTEGER NULL
- firma_adi_gorunum TEXT NULL
- XOR CHECK cari_id / musteri_aday_id
- Mevcut durum + GERCEKLESTI/gorusme_id CHECK korunur
- idx_moa_aday
- cari kayıtlarında firma_adi_gorunum ← nexgen_cari.unvan backfill
"""
from __future__ import annotations

import json
import os
import sqlite3

MIGRATION_VERSION = 156
TABLO = 'musteri_operasyon_ajanda'
TMP = 'musteri_operasyon_ajanda__mig156'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _col_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _schema_inventory(con: sqlite3.Connection) -> dict:
    inv: dict = {'indexes': [], 'triggers': []}
    for row in con.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE tbl_name=? AND type IN ('index','trigger')",
        (TABLO,),
    ).fetchall():
        key = 'indexes' if row[0] == 'index' else 'triggers'
        inv[key].append({'name': row[1], 'sql': row[2]})
    tbl = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLO,),
    ).fetchone()
    if tbl and tbl[0]:
        inv['table_sql'] = tbl[0]
    return inv


def _already_migrated(con: sqlite3.Connection) -> bool:
    if not _table_exists(con, TABLO):
        return False
    names = _col_names(con, TABLO)
    return (
        'musteri_aday_id' in names
        and 'firma_adi_gorunum' in names
        and not _col_notnull(con, TABLO, 'cari_id')
    )


def _col_notnull(con: sqlite3.Connection, table: str, col: str) -> bool:
    for c in con.execute(f'PRAGMA table_info({table})').fetchall():
        if c[1] == col:
            return bool(c[3])
    return False


def _rebuild(con: sqlite3.Connection) -> None:
    if _table_exists(con, TMP):
        con.execute(f'DROP TABLE {TMP}')

    con.execute(f"""
        CREATE TABLE {TMP} (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id                 INTEGER,
            musteri_aday_id         INTEGER,
            firma_adi_gorunum       TEXT,
            kullanici_id            INTEGER NOT NULL,
            plan_tarihi             TEXT NOT NULL,
            gorusme_tipi            TEXT NOT NULL,
            plan_notu               TEXT,
            durum                   TEXT NOT NULL DEFAULT 'PLANLANDI',
            gorusme_id              INTEGER,
            idempotency_key         TEXT NOT NULL UNIQUE,
            aktif                   INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            olusturan_kullanici_id  INTEGER NOT NULL,
            CHECK (durum IN ('PLANLANDI', 'GERCEKLESTI', 'IPTAL')),
            CHECK (aktif IN (0, 1)),
            CHECK (
                (durum = 'GERCEKLESTI' AND gorusme_id IS NOT NULL)
                OR (durum IN ('PLANLANDI', 'IPTAL'))
            ),
            CHECK (
                (cari_id IS NOT NULL AND musteri_aday_id IS NULL)
                OR (cari_id IS NULL AND musteri_aday_id IS NOT NULL)
            )
        )
    """)

    old_cols = _col_names(con, TABLO)
    rows = con.execute(f'SELECT * FROM {TABLO}').fetchall()
    for r in rows:
        d = dict(r)
        cid = d.get('cari_id')
        firma = None
        if cid:
            u = con.execute(
                'SELECT unvan FROM nexgen_cari WHERE id=?', (int(cid),),
            ).fetchone()
            firma = (u[0] if u else None) or None
        con.execute(
            f"""
            INSERT INTO {TMP} (
                id, cari_id, musteri_aday_id, firma_adi_gorunum,
                kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                durum, gorusme_id, idempotency_key, aktif,
                olusturma_tarihi, guncelleme_tarihi, olusturan_kullanici_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                d['id'], cid,
                d.get('musteri_aday_id') if 'musteri_aday_id' in old_cols else None,
                firma,
                d['kullanici_id'], d['plan_tarihi'], d['gorusme_tipi'], d.get('plan_notu'),
                d['durum'], d.get('gorusme_id'), d['idempotency_key'], d.get('aktif', 1),
                d.get('olusturma_tarihi'), d.get('guncelleme_tarihi'),
                d['olusturan_kullanici_id'],
            ),
        )

    con.execute(f'DROP TABLE {TABLO}')
    con.execute(f'ALTER TABLE {TMP} RENAME TO {TABLO}')

    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_kullanici_plan '
        'ON musteri_operasyon_ajanda(kullanici_id, plan_tarihi)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_cari '
        'ON musteri_operasyon_ajanda(cari_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_gorusme '
        'ON musteri_operasyon_ajanda(gorusme_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_durum '
        'ON musteri_operasyon_ajanda(durum)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_moa_aday '
        'ON musteri_operasyon_ajanda(musteri_aday_id)'
    )


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] musteri_operasyon_ajanda aday desteği')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, TABLO):
            raise RuntimeError(f'{TABLO} tablosu yok — önce migration 151 gerekli.')

        before_count = con.execute(f'SELECT COUNT(*) FROM {TABLO}').fetchone()[0]
        before_inv = _schema_inventory(con)
        log(f'[{MIGRATION_VERSION}] BEFORE rows={before_count}')
        log(f'[{MIGRATION_VERSION}] BEFORE inventory={json.dumps(before_inv, ensure_ascii=False)[:500]}')

        if _already_migrated(con):
            log(f'[{MIGRATION_VERSION}] SKIP — schema already OK')
            return

        con.execute('BEGIN IMMEDIATE')
        _rebuild(con)
        after_count = con.execute(f'SELECT COUNT(*) FROM {TABLO}').fetchone()[0]
        if after_count != before_count:
            raise RuntimeError(
                f'Row count mismatch: before={before_count} after={after_count}'
            )
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (str(MIGRATION_VERSION),),
            )
        con.commit()

        after_inv = _schema_inventory(con)
        log(f'[{MIGRATION_VERSION}] AFTER rows={after_count}')
        log(f'[{MIGRATION_VERSION}] AFTER inventory={json.dumps(after_inv, ensure_ascii=False)[:500]}')
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run(path)

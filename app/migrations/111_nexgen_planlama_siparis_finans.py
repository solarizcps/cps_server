# -*- coding: utf-8 -*-
"""
Migration 111 — Pazarlama sipariş finans alanları
=================================================
[1] nexgen_planlama_siparis.anlasma_para_birimi TEXT
[2] nexgen_planlama_siparis.vade_gun INTEGER
[3] nexgen_planlama_siparis.anlasma_birim_fiyat TEXT
[4] schema_migrations version=111

NOT: Canlı DB'ye otomatik uygulanmaz. İdempotent.
"""
from __future__ import annotations

import argparse
import os
import sqlite3

VERSION = '111'
DEFAULT_DB = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo: str, kolon: str) -> bool:
    return kolon in [c[1] for c in cur.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _tablo_var(cur, tablo: str) -> bool:
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo,),
    ).fetchone())


def run(db_path: str | None = None) -> dict:
    db_path = db_path or DEFAULT_DB
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    degisti = False

    if not _tablo_var(cur, 'nexgen_planlama_siparis'):
        con.close()
        return {'ok': False, 'hata': 'nexgen_planlama_siparis yok', 'yeni_degisiklik': False}

    if not _kolon_var(cur, 'nexgen_planlama_siparis', 'anlasma_para_birimi'):
        cur.execute(
            "ALTER TABLE nexgen_planlama_siparis "
            "ADD COLUMN anlasma_para_birimi TEXT"
        )
        degisti = True

    if not _kolon_var(cur, 'nexgen_planlama_siparis', 'vade_gun'):
        cur.execute(
            "ALTER TABLE nexgen_planlama_siparis "
            "ADD COLUMN vade_gun INTEGER"
        )
        degisti = True

    if not _kolon_var(cur, 'nexgen_planlama_siparis', 'anlasma_birim_fiyat'):
        cur.execute(
            "ALTER TABLE nexgen_planlama_siparis "
            "ADD COLUMN anlasma_birim_fiyat TEXT"
        )
        degisti = True

    con.commit()

    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
            (int(VERSION),),
        )
        con.commit()
    except Exception:
        pass

    con.close()
    return {'ok': True, 'yeni_degisiklik': degisti, 'version': VERSION}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    args = ap.parse_args()
    print(run(db_path=args.db))

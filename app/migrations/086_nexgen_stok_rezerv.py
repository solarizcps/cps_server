# -*- coding: utf-8 -*-
"""
Migration 086 — NexGen FAZ-5C-1: Stok rezerv altyapısı
======================================================
[1] nexgen_stok_rezerv
[2] schema_migrations version=86

Stok hareketi YAZILMAZ. Idempotent.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 086: nexgen_stok_rezerv ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_rezerv (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            rezerv_no           TEXT NOT NULL UNIQUE,
            stok_kart_id        INTEGER NOT NULL,
            kaynak_tip          TEXT,
            kaynak_id           INTEGER,
            hazirlik_id         INTEGER,
            batch_kodu          TEXT NOT NULL,
            plan_id             INTEGER,
            planlama_siparis_id INTEGER,
            cari_id             INTEGER,
            miktar_kg           REAL NOT NULL,
            kalan_kg            REAL NOT NULL,
            durum               TEXT NOT NULL DEFAULT 'AKTIF',
            olusturan_id        INTEGER,
            olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
            kapanis_tarihi      TEXT,
            notlar              TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsr_stok_durum
        ON nexgen_stok_rezerv(stok_kart_id, durum)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsr_batch
        ON nexgen_stok_rezerv(batch_kodu)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsr_hazirlik
        ON nexgen_stok_rezerv(hazirlik_id)
    """)
    con.commit()
    print("  OK    nexgen_stok_rezerv")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(86)")
        con.commit()
        print("  OK    schema_migrations version=86")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 086 tamamlandi ===\n")


if __name__ == '__main__':
    run()

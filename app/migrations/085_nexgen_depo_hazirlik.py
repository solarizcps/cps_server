# -*- coding: utf-8 -*-
"""
Migration 085 — NexGen FAZ-5B: Depo üretim hazırlık workflow
=============================================================
[1] nexgen_depo_hazirlik
[2] nexgen_depo_hazirlik_kalem
[3] schema_migrations version=85

Stok hareketi YAZILMAZ. Idempotent.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 085: nexgen_depo_hazirlik ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_depo_hazirlik (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            hazirlik_no         TEXT NOT NULL UNIQUE,
            batch_kodu          TEXT NOT NULL,
            plan_id             INTEGER,
            planlama_siparis_id INTEGER,
            cari_id             INTEGER,
            durum               TEXT NOT NULL DEFAULT 'BEKLIYOR',
            hazirlayan_id       INTEGER,
            hazir_tarihi        TEXT,
            notlar              TEXT,
            olusturan_id        INTEGER,
            olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi   TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ndh_batch
        ON nexgen_depo_hazirlik(batch_kodu)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ndh_durum
        ON nexgen_depo_hazirlik(durum)
    """)
    con.commit()
    print("  OK    nexgen_depo_hazirlik")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_depo_hazirlik_kalem (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hazirlik_id     INTEGER NOT NULL
                                REFERENCES nexgen_depo_hazirlik(id),
            stok_kart_id    INTEGER NOT NULL,
            kaynak          TEXT NOT NULL,
            gerekli_kg      REAL NOT NULL,
            hazirlanan_kg   REAL NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ndhk_hazirlik
        ON nexgen_depo_hazirlik_kalem(hazirlik_id)
    """)
    con.commit()
    print("  OK    nexgen_depo_hazirlik_kalem")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(85)")
        con.commit()
        print("  OK    schema_migrations version=85")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 085 tamamlandi ===\n")


if __name__ == '__main__':
    run()

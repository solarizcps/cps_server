# -*- coding: utf-8 -*-
"""
Migration 075 — NexGen FAZ-2A-P4: AR-GE Onay Notu
===================================================
Eklenen alan (nexgen_arge_test):
  [1] onay_notu  TEXT  — onay/red gerekçesi veya yönetim notu

İdempotent: Kolon varsa atlanır.
KURAL: nexgen_stok_hareket'e DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 075: nexgen_arge_test.onay_notu ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    mevcut = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_arge_test)"
    ).fetchall()]

    if 'onay_notu' not in mevcut:
        cur.execute("ALTER TABLE nexgen_arge_test ADD COLUMN onay_notu TEXT")
        con.commit()
        print("  OK    nexgen_arge_test.onay_notu eklendi")
    else:
        print("  SKIP  onay_notu zaten var - atlaniyor")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(75)")
        con.commit()
        print("  OK    schema_migrations version=75")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 075 tamamlandi ===\n")


if __name__ == '__main__':
    run()

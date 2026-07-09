# -*- coding: utf-8 -*-
"""
Migration 083 — NexGen FAZ-3B: Plan MPR rf_renk_id + termin_tarihi
===================================================================
[1] nexgen_uretim_plan.rf_renk_id INTEGER (NULL)
[2] nexgen_uretim_plan.termin_tarihi TEXT (NULL)
[3] schema_migrations version=83

NOT: Eski kayitlar NULL kalir. Stok hareketi yapilmaz.
Idempotent: Tekrar calistirilabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 083: nexgen_uretim_plan rf_renk_id + termin_tarihi ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    for kolon, tip in (
        ('rf_renk_id', 'INTEGER'),
        ('termin_tarihi', 'TEXT'),
    ):
        if not _kolon_var(cur, 'nexgen_uretim_plan', kolon):
            cur.execute(f"ALTER TABLE nexgen_uretim_plan ADD COLUMN {kolon} {tip}")
            con.commit()
            print(f"  OK    {kolon} sutunu eklendi")
        else:
            print(f"  SKIP  {kolon} zaten var")

    total = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]
    rf_dolu = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE rf_renk_id IS NOT NULL"
    ).fetchone()[0]
    term_dolu = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE termin_tarihi IS NOT NULL"
    ).fetchone()[0]
    print(f"  CHECK toplam plan: {total}")
    print(f"  CHECK rf_renk_id dolu: {rf_dolu}")
    print(f"  CHECK termin_tarihi dolu: {term_dolu}")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(83)")
        con.commit()
        print("  OK    schema_migrations version=83")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 083 tamamlandi ===\n")


if __name__ == '__main__':
    run()

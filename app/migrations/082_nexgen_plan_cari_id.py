# -*- coding: utf-8 -*-
"""
Migration 082 — NexGen FAZ-2B: Üretim plan cari_id FK
======================================================
[1] nexgen_uretim_plan.cari_id INTEGER (NULL, FK nexgen_cari)
[2] Backfill: TRIM(musteri_adi) = TRIM(unvan) eşleşmesi
[3] schema_migrations version=82

NOT: Stok hareketi yapılmaz. Eşleşmeyen planlar NULL kalır.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 082: nexgen_uretim_plan.cari_id ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    try:
        cur.execute(
            "ALTER TABLE nexgen_uretim_plan "
            "ADD COLUMN cari_id INTEGER REFERENCES nexgen_cari(id)"
        )
        con.commit()
        print("  OK    cari_id sütunu eklendi")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("  SKIP  cari_id sütunu zaten var")
        else:
            raise

    before = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE cari_id IS NOT NULL"
    ).fetchone()[0]

    cur.execute("""
        UPDATE nexgen_uretim_plan
        SET cari_id = (
            SELECT c.id FROM nexgen_cari c
            WHERE c.aktif = 1
              AND TRIM(c.unvan) = TRIM(nexgen_uretim_plan.musteri_adi)
            ORDER BY c.id
            LIMIT 1
        )
        WHERE cari_id IS NULL
          AND musteri_adi IS NOT NULL
          AND TRIM(musteri_adi) != ''
    """)
    con.commit()
    updated = cur.rowcount

    after = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE cari_id IS NOT NULL"
    ).fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]
    null_cari = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE cari_id IS NULL"
    ).fetchone()[0]

    print(f"  OK    backfill: {updated} satir guncellendi")
    print(f"  CHECK cari_id dolu: {after}/{total} (once: {before})")
    print(f"  CHECK cari_id NULL: {null_cari}")

    sample = cur.execute("""
        SELECT p.id, p.plan_kodu, p.cari_id, p.musteri_adi, c.unvan AS cari_unvan
        FROM nexgen_uretim_plan p
        LEFT JOIN nexgen_cari c ON c.id = p.cari_id
        ORDER BY p.id DESC LIMIT 5
    """).fetchall()
    print("  Son 5 plan:")
    for r in sample:
        musteri = (r['musteri_adi'] or '')[:40]
        print(f"    id={r['id']} cari_id={r['cari_id']} musteri={musteri}...")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(82)")
        con.commit()
        print("  OK    schema_migrations version=82")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 082 tamamlandı ===\n")


def rollback():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 082 (SQLite: DROP COLUMN desteklenmez — manuel) ===")
    print("  NOT: cari_id kolonu kalır; NULL yapılabilir veya DB restore gerekir.")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=82")
        con.commit()
    except Exception:
        pass
    con.close()


if __name__ == '__main__':
    run()

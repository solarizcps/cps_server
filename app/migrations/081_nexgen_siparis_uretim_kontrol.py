# -*- coding: utf-8 -*-
"""
Migration 081 — NexGen: Siparis / uretim KG kontrol VIEW
=========================================================
v_nexgen_siparis_uretim_kontrol

  siparis_toplam_kg  = plan.planlanan_kg (master)
  planlanan_kg       = alt emir hedef toplami (formul dagilim, bilgi)
  uretilen_kg        = rf_kullanim SUM (tek gerceklesen kaynak)
  fark_kg            = siparis_toplam_kg - uretilen_kg

Idempotent. Rollback: VIEW DROP.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_nexgen_siparis_uretim_kontrol AS
SELECT
    np.id AS siparis_id,
    ROUND(np.planlanan_kg, 3) AS siparis_toplam_kg,
    COALESCE((
        SELECT ROUND(SUM(p.hedef_kg), 3)
        FROM nexgen_uretim_parca p
        JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
        WHERE b.plan_id = np.id
    ), 0) AS planlanan_kg,
    COALESCE((
        SELECT ROUND(SUM(k.miktar_kg), 3)
        FROM nexgen_rf_kullanim k
        WHERE k.aktif = 1 AND k.siparis_id = np.id
    ), 0) AS uretilen_kg,
    ROUND(
        np.planlanan_kg - COALESCE((
            SELECT SUM(k.miktar_kg)
            FROM nexgen_rf_kullanim k
            WHERE k.aktif = 1 AND k.siparis_id = np.id
        ), 0),
    3) AS fark_kg
FROM nexgen_uretim_plan np
"""


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Migration 081: v_nexgen_siparis_uretim_kontrol ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    cur.execute("DROP VIEW IF EXISTS v_nexgen_siparis_uretim_kontrol")
    cur.execute(VIEW_SQL)
    con.commit()
    print("  OK    v_nexgen_siparis_uretim_kontrol")

    cnt = cur.execute("SELECT COUNT(*) FROM v_nexgen_siparis_uretim_kontrol").fetchone()[0]
    print(f"  CHECK view satir: {cnt}")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(81)")
        con.commit()
        print("  OK    schema_migrations version=81")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 081 tamamlandi ===\n")


def rollback():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 081 ===")
    cur.execute("DROP VIEW IF EXISTS v_nexgen_siparis_uretim_kontrol")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=81")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    VIEW kaldirildi")
    print("=== Rollback 081 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()

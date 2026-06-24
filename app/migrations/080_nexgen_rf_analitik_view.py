# -*- coding: utf-8 -*-
"""
Migration 080 — NexGen FAZ-3H: RF kullanim analitik VIEW
=========================================================
v_nexgen_rf_kullanim_ozet — rf_renk + cari + siparis bazli aggregation

Idempotent. Rollback: VIEW DROP.

KURAL: Mevcut tablolara yazma yok; sadece READ VIEW.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_nexgen_rf_kullanim_ozet AS
SELECT
    k.rf_renk_id,
    k.cari_id,
    k.siparis_id,
    k.formul_id,
    ROUND(SUM(COALESCE(k.miktar_kg, 0)), 3) AS toplam_uretim_kg,
    COUNT(*) AS kayit_sayisi,
    SUM(CASE WHEN COALESCE(k.durum, 'MANUEL') = 'MANUEL' THEN 1 ELSE 0 END) AS adet_manuel,
    SUM(CASE WHEN k.durum = 'URETIM' THEN 1 ELSE 0 END) AS adet_uretim,
    SUM(CASE WHEN k.durum = 'TAMAMLANDI' THEN 1 ELSE 0 END) AS adet_tamamlandi,
    ROUND(SUM(CASE WHEN COALESCE(k.durum, 'MANUEL') = 'MANUEL'
        THEN COALESCE(k.miktar_kg, 0) ELSE 0 END), 3) AS kg_manuel,
    ROUND(SUM(CASE WHEN k.durum = 'URETIM'
        THEN COALESCE(k.miktar_kg, 0) ELSE 0 END), 3) AS kg_uretim,
    ROUND(SUM(CASE WHEN k.durum = 'TAMAMLANDI'
        THEN COALESCE(k.miktar_kg, 0) ELSE 0 END), 3) AS kg_tamamlandi
FROM nexgen_rf_kullanim k
WHERE k.aktif = 1
GROUP BY k.rf_renk_id, k.cari_id, k.siparis_id, k.formul_id
"""


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 080: v_nexgen_rf_kullanim_ozet VIEW ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    tbl = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_rf_kullanim'"
    ).fetchone()
    if not tbl:
        print("  SKIP  nexgen_rf_kullanim yok — VIEW atlaniyor")
        con.close()
        return

    cur.execute("DROP VIEW IF EXISTS v_nexgen_rf_kullanim_ozet")
    cur.execute(VIEW_SQL)
    con.commit()
    print("  OK    v_nexgen_rf_kullanim_ozet")

    cnt = cur.execute("SELECT COUNT(*) FROM v_nexgen_rf_kullanim_ozet").fetchone()[0]
    print(f"  CHECK view satir: {cnt}")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(80)")
        con.commit()
        print("  OK    schema_migrations version=80")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 080 tamamlandi ===\n")


def rollback():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 080: VIEW DROP ===")
    cur.execute("DROP VIEW IF EXISTS v_nexgen_rf_kullanim_ozet")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=80")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    v_nexgen_rf_kullanim_ozet kaldirildi")
    print("=== Rollback 080 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()

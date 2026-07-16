# -*- coding: utf-8 -*-
"""
Migration 105 — v_nexgen_siparis_uretim_kontrol VIEW onarımı
=============================================================
nexgen_db_repair mig081 yanlış şema ile VIEW oluşturmuş olabilir.
Migration 081 KG kontrol şemasını idempotent olarak yeniden uygular.

Gerçek DB'de kullanıcı onayı olmadan çalıştırılmamalı.
"""

import os
import sqlite3
from datetime import datetime

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
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    import shutil
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre105_{ts}.db')
    try:
        shutil.copy2(DB_PATH, bak)
        print(f"[YEDEK] {os.path.basename(bak)}")
    except Exception as e:
        print(f"[UYARI] Yedek alinamadi: {e}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("=" * 70)
    print("Migration 105 - v_nexgen_siparis_uretim_kontrol VIEW repair")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    cur.execute("DROP VIEW IF EXISTS v_nexgen_siparis_uretim_kontrol")
    cur.execute(VIEW_SQL)
    con.commit()
    print("  OK    VIEW yeniden olusturuldu")

    cols = [c[1] for c in cur.execute(
        "PRAGMA table_info(v_nexgen_siparis_uretim_kontrol)"
    ).fetchall()]
    print(f"  CHECK kolonlar: {cols}")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(105)")
        con.commit()
        print("  OK    schema_migrations version=105")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    print("Migration 105 tamamlandi\n")
    con.close()


if __name__ == '__main__':
    run()

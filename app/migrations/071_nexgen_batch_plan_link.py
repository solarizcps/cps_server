# -*- coding: utf-8 -*-
"""
Migration 071 — NexGen FAZ-5E: Batch → Plan bağlantısı
========================================================
Yapılacaklar:
  [1] nexgen_uretim_batch tablosuna plan_id alanı ekle
      (nexgen_uretim_plan.id FK — NULL izinli, eski kayıtlar için)
  [2] Mevcut batch kayıtlarını plan_id ile backfill et
      (uretim_varyant_id eşleşmesine göre, en yakın PLANLANDI planı)
  [3] schema_migrations version=71

NOT: Stok hareketi yapılmaz.
     plan_id: hangi plandan bu batch oluşturuldu bağlantısı.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

# routes.py ile aynı yol: app/modules/nexgen/../../mock_data.db = app/mock_data.db
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 071: nexgen_uretim_batch.plan_id alanı ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # [1] plan_id sütunu ekle (zaten varsa hata vermez)
    try:
        cur.execute("ALTER TABLE nexgen_uretim_batch ADD COLUMN plan_id INTEGER REFERENCES nexgen_uretim_plan(id)")
        con.commit()
        print("  OK    plan_id sütunu eklendi")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("  SKIP  plan_id sütunu zaten var")
        else:
            raise

    # [2] Backfill: plan_id=NULL olan batch'ler için uretim_varyant_id eşleşen
    #     en son planı bul ve bağla
    try:
        null_batches = cur.execute("""
            SELECT nb.id, nb.batch_kodu, nb.uretim_varyant_id
            FROM nexgen_uretim_batch nb
            WHERE nb.plan_id IS NULL
        """).fetchall()

        backfill_count = 0
        for row in null_batches:
            plan = cur.execute("""
                SELECT id FROM nexgen_uretim_plan
                WHERE uretim_varyant_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (row['uretim_varyant_id'],)).fetchone()
            if plan:
                cur.execute(
                    "UPDATE nexgen_uretim_batch SET plan_id = ? WHERE id = ?",
                    (plan['id'], row['id'])
                )
                backfill_count += 1

        con.commit()
        print(f"  OK    {backfill_count} batch backfill edildi (plan_id atandı)")
        print(f"        {len(null_batches) - backfill_count} batch plan eşleşmesi bulunamadı (NULL kaldı)")
    except Exception as e:
        print(f"  WARN  Backfill hatası: {e}")

    # [3] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(71)")
        con.commit()
        print("  OK    schema_migrations version=71")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    # Kontrol çıktısı
    print("\n--- Doğrulama ---")
    cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_uretim_batch)").fetchall()]
    print(f"  nexgen_uretim_batch kolonları: {cols}")
    print(f"  plan_id kolonu: {'VAR' if 'plan_id' in cols else 'YOK - HATA!'}")

    sample = cur.execute("""
        SELECT nb.id, nb.batch_kodu, nb.plan_id, nb.durum,
               np.musteri_adi, np.siparis_no
        FROM nexgen_uretim_batch nb
        LEFT JOIN nexgen_uretim_plan np ON np.id = nb.plan_id
        ORDER BY nb.id DESC LIMIT 5
    """).fetchall()
    print("  Son 5 batch (plan_id + musteri_adi):")
    for r in sample:
        print(f"    batch={r['batch_kodu']} plan_id={r['plan_id']} durum={r['durum']} musteri={r['musteri_adi']} siparis={r['siparis_no']}")

    con.close()
    print("=== Migration 071 tamamlandı ===\n")


if __name__ == '__main__':
    run()

# -*- coding: utf-8 -*-
"""
Migration 073 — NexGen FAZ-5G: Alt Emir Formül KG Kaydı
=========================================================
Yapılacaklar:
  [1] nexgen_uretim_parca tablosuna formul_batch_kg kolonu ekle
      Alt emir oluşturulduğu andaki reçete KG'sini sabitler.
      Formül ileride değişirse geçmiş emirler bozulmaz.
  [2] schema_migrations version=73

İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 073: nexgen_uretim_parca.formul_batch_kg ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # Mevcut kolonları kontrol et
    mevcut = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_uretim_parca)"
    ).fetchall()]
    print(f"  Mevcut kolonlar: {mevcut}")

    # [1] formul_batch_kg ekle
    if 'formul_batch_kg' not in mevcut:
        cur.execute(
            "ALTER TABLE nexgen_uretim_parca ADD COLUMN formul_batch_kg REAL DEFAULT 0"
        )
        con.commit()
        print("  OK    formul_batch_kg kolonu eklendi")
    else:
        print("  SKIP  formul_batch_kg zaten var")

    # Doğrula
    guncel = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_uretim_parca)"
    ).fetchall()]
    print(f"  Güncel kolonlar: {guncel}")

    # [2] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(73)")
        con.commit()
        print("  OK    schema_migrations version=73")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 073 tamamlandı ===\n")


if __name__ == '__main__':
    run()

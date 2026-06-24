# -*- coding: utf-8 -*-
"""
Migration 074 — NexGen FAZ-2A-P1: AR-GE Kimlik ve İzleme Alanları
===================================================================
Eklenen alanlar (nexgen_arge_test):
  [1] cari_id          INTEGER  — hangi cari/firma için (nexgen_cari.id, NULL OK)
  [2] shore_hedef      REAL     — hedef shore/yumuşaklık değeri
  [3] lot_no           TEXT     — AR-GE deneme lotu (ARGE-LOT-YYYY-00001)
  [4] talep_referansi  TEXT     — müşteri talebi / referans notu

NOT: yapan_kullanici_id eklenmedi.
     olusturan_id (sistem_kullanici.Id) bu rolü taşıyor — tekrar etmez.

İdempotent: Kolon varsa atlanır.
KURAL: nexgen_stok_hareket'e DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 074: nexgen_arge_test kimlik alanları ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # Mevcut kolonları kontrol et
    mevcut = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_arge_test)"
    ).fetchall()]
    print(f"  Mevcut kolon sayısı: {len(mevcut)}")

    eklemeler = [
        ("cari_id",         "ALTER TABLE nexgen_arge_test ADD COLUMN cari_id INTEGER"),
        ("shore_hedef",     "ALTER TABLE nexgen_arge_test ADD COLUMN shore_hedef REAL"),
        ("lot_no",          "ALTER TABLE nexgen_arge_test ADD COLUMN lot_no TEXT"),
        ("talep_referansi", "ALTER TABLE nexgen_arge_test ADD COLUMN talep_referansi TEXT"),
    ]

    for kolon, sql in eklemeler:
        if kolon not in mevcut:
            cur.execute(sql)
            con.commit()
            print(f"  OK    nexgen_arge_test.{kolon} eklendi")
        else:
            print(f"  SKIP  {kolon} zaten var — atlanıyor")

    # Doğrula
    guncel = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_arge_test)"
    ).fetchall()]
    print(f"  Güncel kolonlar: {guncel}")

    # schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(74)")
        con.commit()
        print("  OK    schema_migrations version=74")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 074 tamamlandı ===\n")


if __name__ == '__main__':
    run()

# -*- coding: utf-8 -*-
"""
Migration 072 — NexGen FAZ-5F: Parçalı Üretim Kaydı
=====================================================
Yapılacaklar:
  [1] nexgen_uretim_parca tablosu
      Her batch altında parça parça üretim izlenir.
      Aynı batch_kodu + lot_kodu altında parca_no ile ayırt edilir.
  [2] schema_migrations version=72

Kural özeti:
  - Bir batch → birden fazla parça (parca_no: 1,2,3...)
  - hedef_kg: bu parça için planlanan kg
  - uretilen_kg: fiilen üretilen (operatör girer)
  - Toplam uretilen_kg ≤ batch.planlanan_kg (backend zorunlu)
  - Barkod batch bazlı korunur (parça ayrı lot almaz)
  - MRP / stok hareketi YOK

İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 072: nexgen_uretim_parca tablosu ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # [1] Tablo oluştur
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_parca (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Batch bağlantısı
            batch_id         INTEGER NOT NULL REFERENCES nexgen_uretim_batch(id),
            batch_kodu       TEXT NOT NULL,
            plan_id          INTEGER REFERENCES nexgen_uretim_plan(id),

            -- Parça kimliği (batch içinde sıra)
            parca_no         INTEGER NOT NULL DEFAULT 1,

            -- KG
            hedef_kg         REAL NOT NULL DEFAULT 0,
            uretilen_kg      REAL NOT NULL DEFAULT 0,

            -- Durum
            durum            TEXT NOT NULL DEFAULT 'HAZIR',

            -- Zaman
            baslama_zamani   TEXT,
            bitis_zamani     TEXT,
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            updated_at       TEXT DEFAULT (datetime('now','localtime')),

            -- Operatör / Vardiya
            operator_id      INTEGER,
            vardiya          TEXT,

            -- Notlar
            bekleme_sebebi   TEXT,
            notlar           TEXT,

            -- Bir batch içinde parca_no benzersiz
            UNIQUE(batch_kodu, parca_no)
        )
    """)
    con.commit()
    print("  OK    nexgen_uretim_parca tablosu oluşturuldu (veya zaten vardı)")

    # Kolon listesini doğrula
    cols = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_uretim_parca)"
    ).fetchall()]
    print(f"  Kolonlar: {cols}")

    # [2] İndeks — batch_kodu bazlı sorgu hızı
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_uretim_parca_batch
        ON nexgen_uretim_parca(batch_kodu)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_uretim_parca_plan
        ON nexgen_uretim_parca(plan_id)
    """)
    con.commit()
    print("  OK    indeksler oluşturuldu")

    # [3] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(72)")
        con.commit()
        print("  OK    schema_migrations version=72")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 072 tamamlandı ===\n")


if __name__ == '__main__':
    run()

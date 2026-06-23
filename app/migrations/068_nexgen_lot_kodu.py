# -*- coding: utf-8 -*-
"""
Migration 068 — NexGen FAZ-5C-0: LOT kodu altyapısı
=====================================================
Yapılacaklar:
  [1] nexgen_uretim_batch tablosuna lot_kodu alanı ekle
  [2] Mevcut batch kayıtlarına otomatik lot_kodu ata
  [3] schema_migrations version=68

NOT: Stok hareketi yapılmaz.
     lot_kodu = fiziksel ürün/compound takip kodu (NG-LOT-YYYY-NNNNN)
     batch_kodu = işlem kaydı kodu (NG-PRD-YYYY-NNNNN) — değişmez.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _lot_kodu_uret(cur, yil):
    """NG-LOT-YYYY-NNNNN formatında sıradaki lot kodu döner."""
    son = cur.execute(
        "SELECT lot_kodu FROM nexgen_uretim_batch "
        "WHERE lot_kodu LIKE ? ORDER BY id DESC LIMIT 1",
        (f"NG-LOT-{yil}-%",)
    ).fetchone()
    if son and son['lot_kodu']:
        try:
            son_no = int(son['lot_kodu'].split('-')[-1])
        except Exception:
            son_no = 0
    else:
        son_no = 0
    return f"NG-LOT-{yil}-{son_no + 1:05d}"


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 068: nexgen_uretim_batch.lot_kodu alanı ===")

    # [1] lot_kodu sütunu ekle (zaten varsa hata vermez)
    try:
        cur.execute("ALTER TABLE nexgen_uretim_batch ADD COLUMN lot_kodu TEXT")
        con.commit()
        print("  OK    lot_kodu sütunu eklendi")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("  SKIP  lot_kodu sütunu zaten var")
        else:
            raise

    # [2] Mevcut kayıtlara lot_kodu ata
    import datetime
    yil = datetime.datetime.now().year
    kayitsiz = cur.execute(
        "SELECT id, batch_kodu FROM nexgen_uretim_batch WHERE lot_kodu IS NULL ORDER BY id ASC"
    ).fetchall()

    if kayitsiz:
        print(f"  ...   lot_kodu atanacak kayıt sayısı: {len(kayitsiz)}")
        for row in kayitsiz:
            lot = _lot_kodu_uret(cur, yil)
            cur.execute(
                "UPDATE nexgen_uretim_batch SET lot_kodu=? WHERE id=?",
                (lot, row['id'])
            )
            con.commit()
            print(f"  OK    batch={row['batch_kodu']} → lot_kodu={lot}")
    else:
        print("  SKIP  Tüm kayıtlarda lot_kodu zaten var")

    # [3] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(68)")
        con.commit()
        print("  OK    schema_migrations version=68")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 068 tamamlandı ===\n")


if __name__ == '__main__':
    run()

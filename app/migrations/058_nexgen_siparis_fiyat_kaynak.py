# -*- coding: utf-8 -*-
"""
Migration 058 — NexGen FAZ-2.6: Sipariş Fiyat Kaynak Bağlantısı
================================================================

nexgen_satin_siparis tablosuna fiyat_kaynak_id kolonu eklenir.

Amaç:
  "Bu sipariş hangi fiyat geçmiş kaydından açıldı?"
  sorusuna ileride izlenebilirlik sağlar.

  Sipariş formu son fiyat önerisini kabul ettiğinde,
  fiyat_kaynak_id = nexgen_hammadde_fiyat.id olarak kaydedilir.
  Kullanıcı fiyatı değiştirse bile kaynak id korunur.

Bağımlılık: Migration 056 (nexgen_hammadde_fiyat tablosu)
Versiyon: 058
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 058 — NexGen FAZ-2.6: Sipariş Fiyat Kaynak ID")
    print("=" * 65)

    # nexgen_hammadde_fiyat var mı kontrol
    fiyat_tablo = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_hammadde_fiyat'"
    ).fetchone()
    if not fiyat_tablo:
        print("  HATA: nexgen_hammadde_fiyat tablosu bulunamadı!")
        print("  Önce Migration 056 çalıştırın.")
        con.close()
        return

    # fiyat_kaynak_id kolonu ekle
    mevcut_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(nexgen_satin_siparis)").fetchall()]
    if 'fiyat_kaynak_id' in mevcut_kolonlar:
        print("  SKIP  fiyat_kaynak_id kolonu zaten mevcut.")
    else:
        cur.execute("""
            ALTER TABLE nexgen_satin_siparis
            ADD COLUMN fiyat_kaynak_id INTEGER
                REFERENCES nexgen_hammadde_fiyat(id)
        """)
        print("  EKLENDI fiyat_kaynak_id → nexgen_satin_siparis")

    con.commit()

    # schema_migrations
    sm_kol = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'aciklama' in sm_kol:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (58, 'nexgen siparis fiyat_kaynak_id FK FAZ-2.6')")
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (58)")
    con.commit()

    # Doğrulama
    print("\n[Doğrulama] nexgen_satin_siparis kolonları:")
    for r in cur.execute("PRAGMA table_info(nexgen_satin_siparis)").fetchall():
        flag = " ← YENİ" if r[1] == 'fiyat_kaynak_id' else ""
        print(f"  {r[1]:25s}  {r[2]}{flag}")

    con.close()
    print("\nMigration 058 tamamlandı.")


if __name__ == '__main__':
    run()

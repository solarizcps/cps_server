# -*- coding: utf-8 -*-
"""
Migration 096 — FAZ-SATINALMA-FIYAT-01: Fiyat Geçerlilik Tarih İndeksi
=======================================================================

Amaç:
  _gecerli_fiyat() ve _fiyat_cakisma_kontrol() fonksiyonları şu sorguyu çalıştırır:
    WHERE tedarikci_id = ? AND stok_kart_id = ? AND aktif = 1
      AND (gecerlilik_bas  IS NULL OR gecerlilik_bas  <= ?)
      AND (gecerlilik_bitis IS NULL OR gecerlilik_bitis >= ?)

  Mevcut idx_nhf_ted_stok (tedarikci_id, stok_kart_id) ile temel tarama yapılabilir;
  ancak tarih filtresi için ek bir indeks performansı artırır.

Yapılanlar:
  1) idx_nhf_gecerlilik — (tedarikci_id, stok_kart_id, aktif, gecerlilik_bas, gecerlilik_bitis)
     Tekrar çalıştırılabilir: CREATE INDEX IF NOT EXISTS

Korunacaklar:
  - nexgen_hammadde_fiyat verisi değişmez.
  - nexgen_stok_hareket değişmez.
  - Mevcut 4 indeks korunur; yalnızca 1 yeni eklenir.

Versiyon: 096
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
    print("Migration 096 — Fiyat Geçerlilik Tarih İndeksi")
    print("=" * 65)

    # Güvenlik: veri sayısını önceden kaydet
    nhf_say = cur.execute("SELECT COUNT(*) FROM nexgen_hammadde_fiyat").fetchone()[0]
    print(f"\n[KONTROL] nexgen_hammadde_fiyat başlangıç: {nhf_say} kayıt — korunacak.")

    hrt_say = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"[KONTROL] nexgen_stok_hareket başlangıç: {hrt_say} — korunacak.")

    # ── Bileşik tarih indeksi ─────────────────────────────────
    print("\n[1] idx_nhf_gecerlilik:")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nhf_gecerlilik
        ON nexgen_hammadde_fiyat(tedarikci_id, stok_kart_id, aktif, gecerlilik_bas, gecerlilik_bitis)
    """)
    print("  OK idx_nhf_gecerlilik")

    con.commit()

    # ── Güvenlik doğrulaması ──────────────────────────────────
    nhf_son = cur.execute("SELECT COUNT(*) FROM nexgen_hammadde_fiyat").fetchone()[0]
    hrt_son = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    assert nhf_son == nhf_say, f"HATA: nexgen_hammadde_fiyat veri sayısı değişti!"
    assert hrt_son == hrt_say, f"HATA: nexgen_stok_hareket değişti!"
    print(f"\n[KONTROL] nexgen_hammadde_fiyat: {nhf_son} — değişmedi ✓")
    print(f"[KONTROL] nexgen_stok_hareket: {hrt_son} — değişmedi ✓")

    # ── schema_migrations ─────────────────────────────────────
    sm_kol = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'aciklama' in sm_kol:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
            "VALUES (96, 'fiyat gecerlilik tarih indeksi FAZ-SATINALMA-FIYAT-01')"
        )
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (96)")
    con.commit()

    # ── Mevcut indeksleri listele ─────────────────────────────
    print("\n[2] nexgen_hammadde_fiyat indeksleri:")
    for idx in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='nexgen_hammadde_fiyat'"
    ).fetchall():
        print(f"  {idx[0]}")

    con.close()
    print("\nMigration 096 tamamlandı.")


if __name__ == '__main__':
    run()

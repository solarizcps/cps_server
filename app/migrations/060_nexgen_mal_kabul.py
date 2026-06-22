# -*- coding: utf-8 -*-
"""
Migration 060 — NexGen FAZ-3A: Depo Mal Kabul Tablosu
======================================================
Yapılacaklar:
  [1] nexgen_mal_kabul tablosu — belge/geçmiş kaydı
  [2] nexgen_satin_siparis.durum güncelleme tetikleyicisi için index
  [3] schema_migrations version=60

Tasarım kararları:
  - nexgen_mal_kabul her fizisel mal kabulünü kaydeder (belge)
  - Stok hesabı nexgen_stok_hareket üzerinden yapılır (değişmez kural)
  - Sipariş gelen_kg stokta hesaplanır: SUM(mal_kabul.miktar_kg WHERE satin_siparis_id=X)
  - Sipariş durumu mal kabul sonrası uygulama katmanında güncellenir:
      toplam_gelen >= siparis_kg  → TAMAMLANDI
      0 < toplam_gelen < siparis_kg → KISMI_TESLIM
  - satin_siparis_id nullable — direkt giriş de desteklenir (referans_tip=DIREKT_GIRIS)
  - stok_hareket_id nullable — oluşturulan hareket ile bağlantı

İdempotent: Tekrar çalıştırılabilir.
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
    print("Migration 060 — NexGen FAZ-3A: Depo Mal Kabul Tablosu")
    print("=" * 65)

    # ── Güvenlik: stok hareket sayısı değişmeyecek ────────────────
    hrt_say = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"\n[KONTROL] nexgen_stok_hareket sayısı={hrt_say} — migration bu değeri değiştirmez")

    # ── 1) nexgen_mal_kabul tablosu ───────────────────────────────
    print("\n[1] nexgen_mal_kabul tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_mal_kabul (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Belge/kaynak bilgileri
            satin_siparis_id    INTEGER
                                    REFERENCES nexgen_satin_siparis(id),
            -- NULL → direkt giriş (satın alma siparişsiz)

            tedarikci_id        INTEGER NOT NULL
                                    REFERENCES nexgen_tedarikci(id),
            stok_kart_id        INTEGER NOT NULL
                                    REFERENCES nexgen_stok_kart(id),

            -- Fiziksel miktar
            miktar_kg           REAL    NOT NULL CHECK (miktar_kg > 0),

            -- Belge numaraları
            irsaliye_no         TEXT,
            lot_no              TEXT,

            -- Kabul yapan + zaman
            kabul_eden_id       INTEGER,
            kabul_tarihi        TEXT    NOT NULL
                                    DEFAULT (datetime('now')),

            -- Serbest not
            aciklama            TEXT,

            -- Stok hareketiyle 1:1 bağlantı (hareket oluşturulunca doldurulur)
            stok_hareket_id     INTEGER
                                    REFERENCES nexgen_stok_hareket(id)
        )
    """)
    con.commit()
    print("  OK nexgen_mal_kabul oluşturuldu veya zaten mevcut.")

    # ── 2) Index'ler ──────────────────────────────────────────────
    print("\n[2] Index'ler:")
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_nmk_siparis  ON nexgen_mal_kabul(satin_siparis_id)",
        "CREATE INDEX IF NOT EXISTS idx_nmk_stok     ON nexgen_mal_kabul(stok_kart_id)",
        "CREATE INDEX IF NOT EXISTS idx_nmk_tarih    ON nexgen_mal_kabul(kabul_tarihi)",
        "CREATE INDEX IF NOT EXISTS idx_nmk_tedarikci ON nexgen_mal_kabul(tedarikci_id)",
    ]:
        cur.execute(idx_sql)
        tbl = idx_sql.split('ON ')[1].split('(')[0].strip()
        idx = idx_sql.split('INDEX IF NOT EXISTS ')[1].split(' ')[0]
        print(f"  {idx} → {tbl}")
    con.commit()

    # ── 3) schema_migrations ──────────────────────────────────────
    print("\n[3] schema_migrations:")
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
        "VALUES (60, 'nexgen mal kabul tablosu FAZ-3A')"
    )
    con.commit()
    print("  version=60 (INSERT OR IGNORE)")

    # ── Kontrol ───────────────────────────────────────────────────
    hrt_say2 = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    cols = [r[1] for r in cur.execute("PRAGMA table_info(nexgen_mal_kabul)").fetchall()]

    print("\n" + "=" * 65)
    print("ÖZET:")
    print(f"  nexgen_mal_kabul kolonları: {', '.join(cols)}")
    print(f"  nexgen_stok_hareket sayısı ÖNCE={hrt_say} SONRA={hrt_say2} "
          f"— {'OK degismedi' if hrt_say == hrt_say2 else 'DIKKAT DEGISTI'}")
    print("=" * 65)

    con.close()
    print("Migration 060 tamamlandı.")


if __name__ == '__main__':
    run()

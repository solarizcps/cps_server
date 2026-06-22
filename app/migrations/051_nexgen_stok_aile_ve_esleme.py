# -*- coding: utf-8 -*-
"""
Migration 051 — NexGen FAZ-2.5: Stok Aile Yapısı + Tedarikçi-Stok Eşleşme
===========================================================================

Yapılanlar:
  1) nexgen_stok_aile      — Hammadde aile/grup tablosu (NEX-AA-BB sisteminin AA kısmı)
  2) nexgen_stok_kart      — aile_id kolonu eklenir (ALTER TABLE)
  3) nexgen_tedarikci_stok — Tedarikçi × Hammadde çoka-çok eşleşme tablosu
  4) 10 stok ailesi seed   — 01:EVA, 02:POE, 03:SBS, 04:Peroksit, 05:Yağlayıcı,
                              06:Dolgu, 07:Yağ/Plastifiyan, 08:Pigment/Boya,
                              09:Karbon Siyah, 10:Recycle
  5) schema_migrations kaydı

KURALLAR:
  - Test verisi DELETE YAPILMAZ. Temizlik ayrı script'tir.
  - nexgen_stok_hareket tablosuna DOKUNULMAZ.
  - Idempotent: tekrar çalıştırma güvenlidir.

NEX-AA-BB KOD SİSTEMİ:
  AA = stok ailesi kodu (01-99)
  BB = aile içi sıra (01-99)
  Örnek: NEX-01-01 = EVA18, NEX-08-03 = P.Red 122
  Kullanıcı kod girmez, sistem otomatik atar.
  Atanan kod değişmez; isim değişebilir.

Versiyon: 051
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


STOK_AİLELERİ = [
    # (aa_kodu, ad,                        aciklama,                        sira)
    ('01', 'EVA',                'Etilen-Vinil Asetat polimerleri',         1),
    ('02', 'POE',                'Poliolefin Elastomer',                    2),
    ('03', 'SBS',                'Stiren-Butadien-Stiren blok kopolimer',   3),
    ('04', 'Peroksit / Ajan',    'Peroksitler ve çapraz bağlama ajanları',  4),
    ('05', 'Yağlayıcı / Parafin','Yağlayıcılar, parafinler, stearatlar',   5),
    ('06', 'Dolgu',              'Kalsit ve diğer dolgu maddeleri',         6),
    ('07', 'Yağ / Plastifiyan',  'Beyaz yağlar, plastifiyanlar',            7),
    ('08', 'Pigment / Boya',     'Organik ve inorganik pigmentler',         8),
    ('09', 'Karbon Siyah',       'Karbon siyah takviye maddeleri',          9),
    ('10', 'Recycle',            'Geri dönüşüm hammaddeleri',               10),
]


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    print("=" * 65)
    print("Migration 051 — NexGen FAZ-2.5: Stok Aile + Eşleşme Tabloları")
    print("=" * 65)

    # ── Güvenlik: stok hareketi sayısı not al ─────────────────────
    hrt_say = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"\n[KONTROL] nexgen_stok_hareket başlangıç: {hrt_say} kayıt — korunacak.")

    # ─────────────────────────────────────────────────────────────
    # 1) nexgen_stok_aile tablosu
    # ─────────────────────────────────────────────────────────────
    print("\n[1] nexgen_stok_aile tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_aile (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            aa_kodu    TEXT    NOT NULL UNIQUE,
            ad         TEXT    NOT NULL,
            aciklama   TEXT,
            sira       INTEGER NOT NULL DEFAULT 0,
            aktif      INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT DEFAULT (datetime('now'))
        )
    """)
    print("  OK nexgen_stok_aile oluşturuldu veya zaten mevcut.")

    # ─────────────────────────────────────────────────────────────
    # 2) nexgen_stok_kart.aile_id kolonu ekle
    # ─────────────────────────────────────────────────────────────
    print("\n[2] nexgen_stok_kart.aile_id kolonu:")
    mevcut_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(nexgen_stok_kart)").fetchall()]
    if 'aile_id' in mevcut_kolonlar:
        print("  SKIP  aile_id kolonu zaten mevcut.")
    else:
        cur.execute("ALTER TABLE nexgen_stok_kart ADD COLUMN aile_id INTEGER REFERENCES nexgen_stok_aile(id)")
        print("  EKLENDI aile_id kolonu.")

    # ─────────────────────────────────────────────────────────────
    # 3) nexgen_tedarikci_stok tablosu
    # ─────────────────────────────────────────────────────────────
    print("\n[3] nexgen_tedarikci_stok tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_tedarikci_stok (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tedarikci_id     INTEGER NOT NULL REFERENCES nexgen_tedarikci(id),
            stok_kart_id     INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
            tercih_sirasi    INTEGER NOT NULL DEFAULT 1,
            -- 1=birincil, 2=alternatif, 3=acil/spot
            aktif            INTEGER NOT NULL DEFAULT 1,
            notlar           TEXT,
            olusturma_tarihi TEXT    DEFAULT (datetime('now')),
            UNIQUE(tedarikci_id, stok_kart_id)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nts_tedarikci
        ON nexgen_tedarikci_stok(tedarikci_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nts_stok_kart
        ON nexgen_tedarikci_stok(stok_kart_id)
    """)
    print("  OK nexgen_tedarikci_stok oluşturuldu veya zaten mevcut.")

    con.commit()

    # ─────────────────────────────────────────────────────────────
    # 4) 10 stok ailesi seed
    # ─────────────────────────────────────────────────────────────
    print("\n[4] 10 stok ailesi seed:")
    for aa, ad, acik, sira in STOK_AİLELERİ:
        mev = cur.execute("SELECT id FROM nexgen_stok_aile WHERE aa_kodu=?", (aa,)).fetchone()
        if mev:
            print(f"  SKIP  aa={aa} '{ad}' zaten mevcut (id={mev['id']})")
        else:
            cur.execute("""
                INSERT INTO nexgen_stok_aile (aa_kodu, ad, aciklama, sira)
                VALUES (?, ?, ?, ?)
            """, (aa, ad, acik, sira))
            print(f"  EKLENDI aa={aa} '{ad}'")

    con.commit()

    # ─────────────────────────────────────────────────────────────
    # 5) Güvenlik: stok hareketi hâlâ aynı mı?
    # ─────────────────────────────────────────────────────────────
    hrt_son = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    assert hrt_son == hrt_say, f"HATA: nexgen_stok_hareket değişti! {hrt_say} → {hrt_son}"
    print(f"\n[KONTROL] nexgen_stok_hareket: {hrt_son} kayıt — değişmedi ✓")

    # ─────────────────────────────────────────────────────────────
    # 6) schema_migrations
    # ─────────────────────────────────────────────────────────────
    sm_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'description' in sm_kolonlar and 'applied_at' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
            VALUES (51, 'nexgen stok aile + tedarikci_stok esleme tablosu FAZ-2.5', datetime('now'))
        """)
    elif 'aciklama' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, aciklama)
            VALUES (51, 'nexgen stok aile + tedarikci_stok esleme tablosu FAZ-2.5')
        """)
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (51)")
    con.commit()

    # ─────────────────────────────────────────────────────────────
    # 7) Doğrulama
    # ─────────────────────────────────────────────────────────────
    print("\n[5] Doğrulama:")
    n_aile = cur.execute("SELECT COUNT(*) FROM nexgen_stok_aile").fetchone()[0]
    aile_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(nexgen_stok_kart)").fetchall()]
    n_ted_stok = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci_stok").fetchone()[0]
    print(f"  nexgen_stok_aile         : {n_aile} kayıt")
    print(f"  nexgen_stok_kart.aile_id : {'mevcut ✓' if 'aile_id' in aile_kolonlar else 'EKSİK!'}")
    print(f"  nexgen_tedarikci_stok    : {n_ted_stok} kayıt (başlangıçta boş olması normal)")

    aileler = cur.execute("SELECT aa_kodu, ad FROM nexgen_stok_aile ORDER BY aa_kodu").fetchall()
    for a in aileler:
        print(f"  Aile {a['aa_kodu']} : {a['ad']}")

    con.close()
    print("\nMigration 051 tamamlandı.")
    print("Sıradaki adım: app/scripts/nexgen_test_veri_temizle.py --confirm")
    print("Sonra        : app/scripts/nexgen_gercek_veri_import.py --confirm")


if __name__ == '__main__':
    run()

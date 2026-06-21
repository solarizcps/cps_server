# -*- coding: utf-8 -*-
"""
Migration 048 — NexGen FAZ-1C: Stok Kart Opsiyonel Özellik Alanları
=====================================================================

Yapılanlar:
  1) nexgen_stok_kart tablosuna 5 nullable kolon eklenir (ALTER TABLE, idempotent):
       renk           TEXT NULL   — özellikle RECYCLE için, genelde boş
       alt_kategori   TEXT NULL   — hammadde tipi, boya tipi, recycle sınıfı vb.
       kalite_sinifi  TEXT NULL   — temiz, karışık, kirli, standart, deneme vb.
       shore_degeri   TEXT NULL   — mamul compound/test için, TEXT (Shore-A, Shore-C)
       notlar         TEXT NULL   — serbest açıklama

  2) Örnek kart eklenir (idempotent):
       RECYCLE_KARISIK / RECYCLE KARIŞIK / RECYCLE
       renk=KARISIK, kalite_sinifi=KARISIK
       Stok hareketi EKLENMEDİ — 0 stokla başlar.

Kurallar:
  - nexgen_stok_kart.mevcut_stok EKLENMEZ.
  - Stok yine nexgen_stok_hareket toplamından hesaplanır.
  - Mevcut kayıtlar (EVA18, POE, KALSIT, SIYAH_BOYA, RECYCLE_EVA) bozulmaz.
  - ALTER TABLE idempotent: kolon zaten varsa SKIP.
  - schema_migrations INSERT OR IGNORE.

Versiyon: 048
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YENI_KOLONLAR = [
    # (kolon_adi, tanim)
    ('renk',          "TEXT"),
    ('alt_kategori',  "TEXT"),
    ('kalite_sinifi', "TEXT"),
    ('shore_degeri',  "TEXT"),
    ('notlar',        "TEXT"),
]

ORNEK_KART = {
    'kod':           'RECYCLE_KARISIK',
    'ad':            'RECYCLE KARIŞIK',
    'kategori':      'RECYCLE',
    'birim':         'KG',
    'minimum_stok':  500.0,
    'kritik_stok':   100.0,
    'renk':          'KARISIK',
    'kalite_sinifi': 'KARISIK',
    'notlar':        'Karışık renk/tip recycle hammaddesi.',
}


def _kolon_var_mi(cur, tablo, kolon):
    satırlar = cur.execute(f"PRAGMA table_info({tablo})").fetchall()
    return any(r[1] == kolon for r in satırlar)


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 048 — NexGen Stok Kart Opsiyonel Özellikler")
    print("=" * 65)

    # ── 1) Kolon kontrolü: nexgen_stok_kart tablosu var mı? ───
    tablo_var = cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='nexgen_stok_kart'
    """).fetchone()
    if not tablo_var:
        print("HATA: nexgen_stok_kart tablosu bulunamadı. Önce Migration 047 çalıştırın.")
        con.close()
        return
    print("[OK] nexgen_stok_kart tablosu mevcut.")

    # ── 2) ALTER TABLE — 5 nullable kolon eklenir ─────────────
    print("\n[1] Yeni nullable kolonlar:")
    for kolon, tanim in YENI_KOLONLAR:
        if _kolon_var_mi(cur, 'nexgen_stok_kart', kolon):
            print(f"  SKIP  '{kolon}' zaten mevcut")
        else:
            cur.execute(f"ALTER TABLE nexgen_stok_kart ADD COLUMN {kolon} {tanim}")
            print(f"  EKLENDI '{kolon}' {tanim}")

    con.commit()

    # ── 3) mevcut_stok kolonu KESINLIKLE EKLENMEDİ kontrol ────
    if _kolon_var_mi(cur, 'nexgen_stok_kart', 'mevcut_stok'):
        print("\nUYARI: mevcut_stok kolonu tabloda mevcut! Bu kural ihlalidir.")
    else:
        print("\n[OK] mevcut_stok kolonu YOK (kural doğru).")

    # ── 4) Mevcut kartlar bozulmadı mı? ───────────────────────
    print("\n[2] Mevcut kartlar kontrolü:")
    for kod in ['EVA18', 'POE', 'KALSIT', 'SIYAH_BOYA', 'RECYCLE_EVA']:
        r = cur.execute(
            "SELECT id, ad, kategori FROM nexgen_stok_kart WHERE kod=?", (kod,)
        ).fetchone()
        if r:
            print(f"  OK  kod='{kod}' id={r['id']} ad='{r['ad']}' kat='{r['kategori']}'")
        else:
            print(f"  EKSIK kod='{kod}' — bu kart yok!")

    # ── 5) Örnek RECYCLE_KARISIK kartı ────────────────────────
    print("\n[3] Örnek RECYCLE_KARISIK kartı:")
    mevcut = cur.execute(
        "SELECT id FROM nexgen_stok_kart WHERE kod=?", (ORNEK_KART['kod'],)
    ).fetchone()
    if mevcut:
        print(f"  SKIP  kod='{ORNEK_KART['kod']}' zaten mevcut (id={mevcut['id']})")
    else:
        cur.execute("""
            INSERT INTO nexgen_stok_kart
              (kod, ad, kategori, birim, minimum_stok, kritik_stok,
               renk, kalite_sinifi, notlar,
               aktif, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, datetime('now'))
        """, (
            ORNEK_KART['kod'], ORNEK_KART['ad'], ORNEK_KART['kategori'],
            ORNEK_KART['birim'], ORNEK_KART['minimum_stok'], ORNEK_KART['kritik_stok'],
            ORNEK_KART['renk'], ORNEK_KART['kalite_sinifi'], ORNEK_KART['notlar'],
        ))
        yeni_id = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        print(f"  EKLENDI id={yeni_id} kod='{ORNEK_KART['kod']}' — stok hareketi YOK (0 KG)")
    con.commit()

    # ── 6) schema_migrations ──────────────────────────────────
    # Kolon adlarını doğrulayarak INSERT
    sm_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'description' in sm_kolonlar and 'applied_at' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
            VALUES (48, 'nexgen stok kart opsiyonel ozellikler (FAZ-1C)', datetime('now'))
        """)
    elif 'aciklama' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, aciklama)
            VALUES (48, 'nexgen stok kart opsiyonel ozellikler (FAZ-1C)')
        """)
    else:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (48)"
        )
    con.commit()

    # ── 7) Son durum ──────────────────────────────────────────
    print("\n[4] Doğrulama — tüm kolonlar:")
    kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(nexgen_stok_kart)").fetchall()]
    print("  " + ", ".join(kolonlar))

    print("\n[5] Tüm kartlar:")
    kartlar = cur.execute(
        "SELECT id, kod, kategori, renk, kalite_sinifi FROM nexgen_stok_kart"
    ).fetchall()
    for k in kartlar:
        print(f"  id={k['id']:3d}  {k['kod']:20s}  {k['kategori']:15s}"
              f"  renk={k['renk'] or '-':10s}  kalite={k['kalite_sinifi'] or '-'}")

    con.close()
    print("\nMigration 048 tamamlandı.")


if __name__ == '__main__':
    run()

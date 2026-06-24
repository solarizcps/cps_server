# -*- coding: utf-8 -*-
"""
Migration 077 — NexGen FAZ-3D: Eksik BOYA pigment stok kartlari
================================================================
RF legacy import oncesi 6 eksik pigment karti eklenir.

Kartlar (NEX-08 serisi devami):
  NEX-08-15  Green 7
  NEX-08-16  M.B 6501 Brown
  NEX-08-17  M.B 8502 Black
  NEX-08-18  Blue KNP 909
  NEX-08-19  Orange 34
  NEX-08-20  Yellow 15

Idempotent:
  - Ayni kod veya ayni ad varsa INSERT atlanir.
  - Mevcut BOYA kartlarina UPDATE yapilmaz.

KURAL: nexgen_stok_hareket DOKUNULMAZ.
       NEX-09 (N330/N550) DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YENI_BOYA_KARTLARI = (
    ('NEX-08-15', 'Green 7',           'Pigment'),
    ('NEX-08-16', 'M.B 6501 Brown',    'Pigment'),
    ('NEX-08-17', 'M.B 8502 Black',    'Pigment'),
    ('NEX-08-18', 'Blue KNP 909',      'Pigment'),
    ('NEX-08-19', 'Orange 34',         'Pigment'),
    ('NEX-08-20', 'Yellow 15',         'Pigment'),
)


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 077: nexgen BOYA eksik pigment kartlari ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    boya_once = cur.execute(
        "SELECT COUNT(*) FROM nexgen_stok_kart WHERE kategori='BOYA' AND aktif=1"
    ).fetchone()[0]
    print(f"  CHECK BOYA once: {boya_once}")

    aile = cur.execute(
        "SELECT id FROM nexgen_stok_aile WHERE aa_kodu='08'"
    ).fetchone()
    aile_id = aile['id'] if aile else None
    if not aile_id:
        print("  WARN  nexgen_stok_aile aa_kodu=08 bulunamadi — aile_id NULL")

    eklendi = skip = 0
    for kod, ad, alt_kat in YENI_BOYA_KARTLARI:
        mev_kod = cur.execute(
            "SELECT id, kod, ad FROM nexgen_stok_kart WHERE kod=? COLLATE NOCASE",
            (kod,),
        ).fetchone()
        mev_ad = cur.execute(
            "SELECT id, kod, ad FROM nexgen_stok_kart WHERE ad=? COLLATE NOCASE",
            (ad,),
        ).fetchone()
        if mev_kod:
            print(f"  SKIP  {kod} zaten var (id={mev_kod['id']})")
            skip += 1
            continue
        if mev_ad:
            print(f"  SKIP  ad='{ad}' zaten var (id={mev_ad['id']} kod={mev_ad['kod']})")
            skip += 1
            continue
        cur.execute("""
            INSERT INTO nexgen_stok_kart
                (kod, ad, kategori, birim, minimum_stok, kritik_stok,
                 alt_kategori, aktif, aile_id, aciklama)
            VALUES (?, ?, 'BOYA', 'KG', 0, 0, ?, 1, ?, ?)
        """, (kod, ad, alt_kat, aile_id,
              'FAZ-3D RF legacy import — eksik pigment'))
        print(f"  OK    {kod} / {ad} eklendi (id={cur.lastrowid})")
        eklendi += 1

    con.commit()

    boya_sonra = cur.execute(
        "SELECT COUNT(*) FROM nexgen_stok_kart WHERE kategori='BOYA' AND aktif=1"
    ).fetchone()[0]
    print(f"  CHECK BOYA sonra: {boya_sonra} (+{boya_sonra - boya_once} net)")

    dup_kod = cur.execute("""
        SELECT kod, COUNT(*) c FROM nexgen_stok_kart
        WHERE kategori='BOYA' AND aktif=1
        GROUP BY kod COLLATE NOCASE HAVING c > 1
    """).fetchall()
    dup_ad = cur.execute("""
        SELECT ad, COUNT(*) c FROM nexgen_stok_kart
        WHERE kategori='BOYA' AND aktif=1
        GROUP BY ad COLLATE NOCASE HAVING c > 1
    """).fetchall()
    print(f"  CHECK duplicate kod: {len(dup_kod)}")
    print(f"  CHECK duplicate ad: {len(dup_ad)}")
    print(f"  Ozet: {eklendi} eklendi, {skip} skip")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(77)")
        con.commit()
        print("  OK    schema_migrations version=77")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 077 tamamlandi ===\n")


if __name__ == '__main__':
    run()

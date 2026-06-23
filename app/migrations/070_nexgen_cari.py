# -*- coding: utf-8 -*-
"""
Migration 070 — NexGen FAZ-5E-3: Cari Master
=============================================
[1] nexgen_cari tablosu (id, cari_kod, unvan, aktif, created_at, updated_at)
[2] 12 seed cari kaydı
[3] schema_migrations version=70

NOT: Soft-delete — hard delete yok, aktif/pasif kullanılır.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

SEED_CARILER = [
    ('120.NX.004', 'Beoss Ayakkabı Terlik İnşaat Otomotiv Sanayi ve Ticaret Limited Şirketi'),
    ('120.NX.006', 'Cihan Makina Mermer ve Madencilik San.Tic.Ltd.Şti'),
    ('120.NX.007', 'Ulkucan Ayakk.ve Ayak.Malz.San.ve Tic.Ltd.Şti'),
    ('120.NX.008', 'Poltab Ayakkabı Taban San.Tic.Lts.Şti'),
    ('120.NX.009', '3E Ayakkabı Taban San.Tic.Ltd.Şti'),
    ('120.NX.010', 'Burak Taban Ayakkabı İnşaat Sanayi ve Dış Ltd Şti'),
    ('120.NX.011', 'AYM Taban Poliüretan ve Gram.Em.San.Tic.Ltd.Şti'),
    ('120.NX.013', 'Bal Terlik Taban San.Ve Tic.Ltd. Şti.'),
    ('120.NX.018', 'SEHA AYAKKABI VE TEKSTİL SAN. TİC. A.Ş.'),
    ('120.NX.019', 'YILDIRIM AYAKKABI - MURAT YILDIRIM'),
    ('120.NX.020', 'NEZİH AYAKKABI MALZ.DERİ TEKS.ÜR.PAZ.SAN.TİC.LTD.ŞTİ.'),
    ('120.NX012',  'Akım Plastik Sanayi ve Ticaret Limited Şirketi'),
]


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 070: nexgen_cari tablosu + seed ===")

    # [1] Tablo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_cari (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_kod    TEXT NOT NULL UNIQUE,
            unvan       TEXT NOT NULL,
            aktif       INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()
    print("  OK    nexgen_cari tablosu oluşturuldu (veya zaten vardı)")

    # [2] Seed kayıtları — INSERT OR IGNORE (idempotent)
    eklenen = 0
    for (kod, unvan) in SEED_CARILER:
        mev = cur.execute(
            "SELECT id FROM nexgen_cari WHERE cari_kod=?", (kod,)
        ).fetchone()
        if mev:
            print(f"  SKIP  cari '{kod}' zaten var")
            continue
        cur.execute(
            "INSERT INTO nexgen_cari(cari_kod, unvan, aktif) VALUES(?,?,1)",
            (kod, unvan)
        )
        eklenen += 1
    con.commit()
    print(f"  OK    {eklenen} cari kaydı eklendi")

    # [3] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(70)")
        con.commit()
        print("  OK    schema_migrations version=70")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 070 tamamlandı ===\n")


if __name__ == '__main__':
    run()

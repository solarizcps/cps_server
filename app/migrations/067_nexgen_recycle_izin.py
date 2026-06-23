# -*- coding: utf-8 -*-
"""
Migration 067 — NexGen FAZ-4F: Recycle İzin Altyapısı
=======================================================
[1] nexgen_recete_recycle_izin tablosu
[2] nexgen.recycle.manage yetkisi — Yönetim rolüne
[3] schema_migrations version=67

NOT: Stok hareketi yapılmaz. Sadece tablo + yetki.
İdempotent.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
YONETIM_ROL_ID = 1


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 067: nexgen_recete_recycle_izin + yetki ===")

    # [1] nexgen_recete_recycle_izin
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_recete_recycle_izin (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            uretim_varyant_id    INTEGER NOT NULL REFERENCES nexgen_uretim_varyant(id),
            recycle_stok_kart_id INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
            yerine_stok_kart_id  INTEGER REFERENCES nexgen_stok_kart(id),
            max_oran_pct         REAL NOT NULL DEFAULT 10,
            aktif                INTEGER NOT NULL DEFAULT 1,
            notlar               TEXT,
            created_at           TEXT DEFAULT (datetime('now','localtime')),
            created_by           INTEGER,
            UNIQUE(uretim_varyant_id, recycle_stok_kart_id)
        )
    """)
    con.commit()
    print("  OK    nexgen_recete_recycle_izin tablosu oluşturuldu (veya zaten vardı)")

    # [2] nexgen.recycle.manage yetkisi
    mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod='nexgen.recycle.manage'").fetchone()
    if mev:
        yetki_id = mev['Id']
        print(f"  SKIP  nexgen.recycle.manage zaten var Id={yetki_id}")
    else:
        cur.execute(
            "INSERT INTO sistem_yetki(Kod, Modul, Ad, Aciklama, Sira) VALUES(?,?,?,?,?)",
            ('nexgen.recycle.manage', 'nexgen',
             'NexGen Recycle İzin Yönetimi',
             'Reçete recycle izinlerini ekleme/pasif yapma', 162)
        )
        con.commit()
        yetki_id = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod='nexgen.recycle.manage'").fetchone()['Id']
        print(f"  OK    nexgen.recycle.manage eklendi Id={yetki_id}")

    # Yönetim rolüne ata
    mev_ry = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (YONETIM_ROL_ID, yetki_id)
    ).fetchone()
    if mev_ry:
        print(f"  SKIP  Yönetim → nexgen.recycle.manage zaten atanmış")
    else:
        cur.execute("INSERT INTO sistem_rol_yetki(RolId, YetkiId) VALUES(?,?)",
                    (YONETIM_ROL_ID, yetki_id))
        con.commit()
        print(f"  OK    Yönetim → nexgen.recycle.manage atandı")

    # [3] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(67)")
        con.commit()
        print("  OK    schema_migrations version=67")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 067 tamamlandı ===\n")


if __name__ == '__main__':
    run()

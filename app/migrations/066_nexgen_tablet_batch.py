# -*- coding: utf-8 -*-
"""
Migration 066 — NexGen FAZ-5A: Tablet Üretim Batch + Yetki
============================================================
Yapılacaklar:
  [1] nexgen_uretim_batch tablosu — tablet üretim kodları için
  [2] nexgen.tablet.view  — tablet ekranı görüntüleme yetkisi
  [3] nexgen.tablet.uretim — üretim akışı başlatma yetkisi
  [4] Rol atamaları: Yönetim (tam), nexgen.view sahibi (tablet.view)
  [5] schema_migrations version=66

NOT: Bu fazda stok hareketi yapılmaz. Batch kaydı TASLAK olarak açılır.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

YENI_YETKILER = [
    ('nexgen.tablet.view',   'nexgen', 'NexGen Tablet Görüntüleme',
     'Tablet üretim/AR-GE ekranını görüntüleme', 160),
    ('nexgen.tablet.uretim', 'nexgen', 'NexGen Tablet Üretim',
     'Tablet üzerinden üretim batch kodu oluşturma', 161),
]


def _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira):
    mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
    if mev:
        print(f"  SKIP  yetki '{kod}' zaten var Id={mev['Id']}")
        return mev['Id']
    cur.execute(
        "INSERT INTO sistem_yetki(Kod, Modul, Ad, Aciklama, Sira) VALUES(?,?,?,?,?)",
        (kod, modul, ad, acik, sira)
    )
    con.commit()
    yid = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()['Id']
    print(f"  OK    yetki '{kod}' eklendi Id={yid}")
    return yid


def _rol_yetki_ekle(cur, con, rol_id, yetki_id):
    mev = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (rol_id, yetki_id)
    ).fetchone()
    if mev:
        print(f"  SKIP  rol={rol_id} yetki={yetki_id} zaten atanmış")
        return
    cur.execute(
        "INSERT INTO sistem_rol_yetki(RolId, YetkiId) VALUES(?,?)",
        (rol_id, yetki_id)
    )
    con.commit()
    print(f"  OK    rol={rol_id} yetki={yetki_id} atandı")


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 066: nexgen_uretim_batch tablosu + tablet yetkileri ===")

    # [1] nexgen_uretim_batch tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_batch (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_kodu          TEXT NOT NULL UNIQUE,
            uretim_varyant_id   INTEGER NOT NULL REFERENCES nexgen_uretim_varyant(id),
            planlanan_kg        REAL NOT NULL DEFAULT 0,
            durum               TEXT NOT NULL DEFAULT 'TASLAK',
            olusturan_id        INTEGER,
            olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
            notlar              TEXT
        )
    """)
    con.commit()
    print("  OK    nexgen_uretim_batch tablosu oluşturuldu (veya zaten vardı)")

    # [2] Yeni yetkiler ekle
    yetki_idler = {}
    for (kod, modul, ad, acik, sira) in YENI_YETKILER:
        yid = _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira)
        yetki_idler[kod] = yid

    # [3] Yönetim rolüne tüm tablet yetkileri
    for (kod, *_rest) in YENI_YETKILER:
        _rol_yetki_ekle(cur, con, YONETIM_ROL_ID, yetki_idler[kod])

    # [4] nexgen.view sahibi tüm rollere tablet.view ata
    view_yetki = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod='nexgen.view'").fetchone()
    if view_yetki:
        rol_view_ids = cur.execute(
            "SELECT RolId FROM sistem_rol_yetki WHERE YetkiId=?",
            (view_yetki['Id'],)
        ).fetchall()
        tablet_view_id = yetki_idler.get('nexgen.tablet.view')
        if tablet_view_id:
            for r in rol_view_ids:
                _rol_yetki_ekle(cur, con, r['RolId'], tablet_view_id)

    # [5] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(66)")
        con.commit()
        print("  OK    schema_migrations version=66")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 066 tamamlandı ===\n")


if __name__ == '__main__':
    run()

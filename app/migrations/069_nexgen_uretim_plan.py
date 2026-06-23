# -*- coding: utf-8 -*-
"""
Migration 069 — NexGen FAZ-5D: Üretim Plan / İş Kuyruğu
=========================================================
[1] nexgen_uretim_plan tablosu
[2] nexgen.plan.view + nexgen.plan.manage yetkileri
[3] Yönetim rolüne yetki ataması
[4] schema_migrations version=69

NOT: Stok hareketi yapılmaz.
İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
YONETIM_ROL_ID = 1

YENI_YETKILER = [
    ('nexgen.plan.view',   'nexgen', 'NexGen Üretim Planı Görüntüleme',
     'Üretim plan listesini görüntüleme', 162),
    ('nexgen.plan.manage', 'nexgen', 'NexGen Üretim Planı Yönetimi',
     'Üretim planı oluşturma, düzenleme, iptal', 163),
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

    print("\n=== Migration 069: nexgen_uretim_plan tablosu + yetkileri ===")

    # [1] Tablo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_plan (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_kodu           TEXT NOT NULL UNIQUE,
            kaynak              TEXT NOT NULL DEFAULT 'MANUEL',
            siparis_no          TEXT,
            musteri_adi         TEXT,
            uretim_varyant_id   INTEGER NOT NULL REFERENCES nexgen_uretim_varyant(id),
            planlanan_kg        REAL NOT NULL DEFAULT 0,
            oncelik_sira        INTEGER NOT NULL DEFAULT 10,
            plan_tarihi         TEXT NOT NULL,
            durum               TEXT NOT NULL DEFAULT 'PLANLANDI',
            notlar              TEXT,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            created_by          INTEGER
        )
    """)
    con.commit()
    print("  OK    nexgen_uretim_plan tablosu oluşturuldu (veya zaten vardı)")

    # [2] Yetkiler
    yetki_idler = {}
    for (kod, modul, ad, acik, sira) in YENI_YETKILER:
        yid = _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira)
        yetki_idler[kod] = yid

    # [3] Yönetim rolüne ata
    for (kod, *_) in YENI_YETKILER:
        _rol_yetki_ekle(cur, con, YONETIM_ROL_ID, yetki_idler[kod])

    # nexgen.view sahibi rollere plan.view ata
    view_yetki = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod='nexgen.view'").fetchone()
    if view_yetki:
        rol_view_ids = cur.execute(
            "SELECT RolId FROM sistem_rol_yetki WHERE YetkiId=?",
            (view_yetki['Id'],)
        ).fetchall()
        plan_view_id = yetki_idler.get('nexgen.plan.view')
        if plan_view_id:
            for r in rol_view_ids:
                _rol_yetki_ekle(cur, con, r['RolId'], plan_view_id)

    # [4] schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(69)")
        con.commit()
        print("  OK    schema_migrations version=69")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 069 tamamlandı ===\n")


if __name__ == '__main__':
    run()

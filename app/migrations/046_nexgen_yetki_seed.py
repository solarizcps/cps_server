# -*- coding: utf-8 -*-
"""
Migration 046 — FAZ-1A NexGen: Yetki seed
==========================================

Yapılanlar:
  1) sistem_yetki: 'nexgen.view'  kodu eklenir
  2) sistem_yetki: 'nexgen.manage' kodu eklenir
  3) Yönetim rolü (RolId=1) her iki yetkiye TAM erişim
  4) kullanici_adi='altan' için user_permission_override üzerinden nexgen.view can_view

Kapsam:
  adem  — SuperAdmin, tüm yetkiler zaten var.
  alpay — Yönetim rolü (RolId=1), bu migration ile nexgen.view + nexgen.manage alır.
  altan — Rol bazlı yetki yok; override ile nexgen.view alır. Silme/geri dönüşsüz işlem yok.

Kurallar:
  - Mevcut ENJ_CORE / Finans / Planlama / Hedef tablolarına dokunulmaz.
  - personel_kullanici tablosuna dokunulmaz.
  - schema_migrations kaydı INSERT OR IGNORE.
  - Idempotent: tekrar çalıştırma güvenli.

Versiyon: 046
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

YENI_YETKILER = [
    # (Kod,             Modul,    Ad,                      Sira)
    ('nexgen.view',   'nexgen', 'NexGen Görüntüleme',     100),
    ('nexgen.manage', 'nexgen', 'NexGen Yönetim',         101),
]


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 60)
    print("Migration 046 — NexGen Yetki Seed")
    print("=" * 60)

    # ── 1) Yönetim rolü doğrulama ──────────────────────────────
    rol = cur.execute(
        "SELECT Id, Ad FROM sistem_rol WHERE Id = ?", (YONETIM_ROL_ID,)
    ).fetchone()
    if not rol:
        print(f"HATA: Yönetim rolü RolId={YONETIM_ROL_ID} bulunamadi.")
        con.close()
        return
    print(f"[1] Yönetim rolü: Id={rol['Id']} Ad={rol['Ad']}")

    # ── 2) sistem_yetki INSERT OR IGNORE ──────────────────────
    print("\n[2] sistem_yetki kodları:")
    for kod, modul, ad, sira in YENI_YETKILER:
        mevcut = cur.execute(
            "SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)
        ).fetchone()
        if mevcut:
            print(f"  SKIP  Id={mevcut['Id']} Kod='{kod}' — zaten mevcut")
        else:
            cur.execute("""
                INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira)
                VALUES (?, ?, ?, ?, ?)
            """, (kod, modul, ad, ad, sira))
            print(f"  EKLENDI Id={cur.lastrowid} Kod='{kod}'")

    con.commit()

    # ── 3) Yönetim rolüne nexgen.view + nexgen.manage tam yetki ─
    print(f"\n[3] Yönetim (RolId={YONETIM_ROL_ID}) → nexgen yetkileri:")
    for kod, _, _, _ in YENI_YETKILER:
        yid_row = cur.execute(
            "SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)
        ).fetchone()
        if not yid_row:
            print(f"  HATA: Kod='{kod}' sistem_yetki'de yok!")
            continue
        yid = yid_row["Id"]

        mev = cur.execute(
            "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (YONETIM_ROL_ID, yid)
        ).fetchone()
        if mev:
            print(f"  SKIP  Id={mev['Id']} Kod='{kod}' — zaten mevcut")
        else:
            cur.execute("""
                INSERT INTO sistem_rol_yetki
                  (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                   can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage)
                VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            """, (YONETIM_ROL_ID, yid))
            print(f"  EKLENDI Kod='{kod}' → Yönetim rolü tam yetki")

    con.commit()

    # ── 4) Altan kullanıcısı — user_permission_override ────────
    print("\n[4] altan kullanıcısı — user_permission_override:")

    # user_permission_override tablosu varlık kontrolü
    tablo_var = cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='user_permission_override'
    """).fetchone()

    if not tablo_var:
        print("  UYARI: user_permission_override tablosu yok — override atlanacak.")
        print("  Altan'a nexgen.view rolünden verilecekse önce rolüne manuel ekleyin.")
    else:
        altan = cur.execute(
            "SELECT Id, KullaniciAdi FROM sistem_kullanici WHERE KullaniciAdi='altan'"
        ).fetchone()

        if not altan:
            print("  UYARI: sistem_kullanici'de 'altan' kullanicisi bulunamadi.")
            print("  Altan kullanici kaydi oluşturulduğunda migration tekrar çalıştırılabilir.")
        else:
            yid_view = cur.execute(
                "SELECT Id FROM sistem_yetki WHERE Kod='nexgen.view'"
            ).fetchone()
            if not yid_view:
                print("  HATA: nexgen.view sistem_yetki'de yok!")
            else:
                mev_ov = cur.execute("""
                    SELECT Id FROM user_permission_override
                    WHERE KullaniciId=? AND YetkiId=?
                """, (altan["Id"], yid_view["Id"])).fetchone()

                if mev_ov:
                    print(f"  SKIP  altan (KulId={altan['Id']}) nexgen.view override zaten mevcut.")
                else:
                    cur.execute("""
                        INSERT INTO user_permission_override
                          (KullaniciId, YetkiId, can_view, can_create, can_update,
                           can_delete, can_approve, can_report, can_manage)
                        VALUES (?, ?, 1, 0, 0, 0, 0, 0, 0)
                    """, (altan["Id"], yid_view["Id"]))
                    print(f"  EKLENDI altan (KulId={altan['Id']}) → nexgen.view can_view=1")

        con.commit()

    # ── 5) schema_migrations kaydı ─────────────────────────────
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
        VALUES (46, 'nexgen yetki seed (FAZ-1A)', datetime('now'))
    """)
    con.commit()

    # ── 6) Doğrulama ───────────────────────────────────────────
    print("\n[5] Doğrulama:")
    for kod, _, _, _ in YENI_YETKILER:
        sy = cur.execute("SELECT Id, Kod FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if sy:
            print(f"  OK sistem_yetki: Id={sy['Id']} Kod='{sy['Kod']}'")
        else:
            print(f"  EKSIK: {kod}")

    yonetim_nexgen = cur.execute("""
        SELECT COUNT(*) as n FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE ry.RolId=? AND y.Modul='nexgen'
    """, (YONETIM_ROL_ID,)).fetchone()
    print(f"  OK Yönetim rolü nexgen yetki sayısı: {yonetim_nexgen['n']}")

    con.close()
    print("\nMigration 046 tamamlandı.")


if __name__ == '__main__':
    run()

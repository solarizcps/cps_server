# -*- coding: utf-8 -*-
"""
Migration 057 — NexGen FAZ-2.6: Fiyat Yönetimi Yetkileri
=========================================================

4 yeni yetki kodu:
  nexgen.fiyat.view    — Fiyat geçmişini görüntüleme
  nexgen.fiyat.manage  — Fiyat girişi (manuel + Excel yükleme)
  nexgen.fiyat.approve — Batch onaylama (Satın Alma kendi yüklemesini onaylayabilir)
  nexgen.fiyat.admin   — Fiyat pasife alma / tam geçmiş yönetimi (sadece Yönetim)

Rol atamaları:
  Yönetim (RolId=1): 4 yetki — tam erişim
  Satın Alma rolü  : view + manage + approve (admin yok — pasife alamaz)
  Depo rolü        : hiçbir fiyat yetkisi

Versiyon: 057
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
YONETIM_ROL_ID = 1

YENI_YETKILER = [
    # (kod, ad, aciklama, sira)
    ('nexgen.fiyat.view',    'NexGen Fiyat Görüntüleme',       'Fiyat geçmişini görüntüleme',             126),
    ('nexgen.fiyat.manage',  'NexGen Fiyat Girişi',            'Manuel ve Excel fiyat girişi',            127),
    ('nexgen.fiyat.approve', 'NexGen Fiyat Onay',              'Fiyat batch onaylama',                    128),
    ('nexgen.fiyat.admin',   'NexGen Fiyat Yönetimi (Admin)',  'Fiyat pasife alma, tam geçmiş yönetimi',  129),
]

# Satın Alma rolüne verilecek yetkiler ve izin seviyeleri
SATINALMA_YETKI_MAP = {
    'nexgen.fiyat.view':    dict(can_view=1),
    'nexgen.fiyat.manage':  dict(can_view=1, can_create=1, can_update=1),
    'nexgen.fiyat.approve': dict(can_view=1, can_approve=1),
    # nexgen.fiyat.admin → Satın Alma'ya VERİLMEZ
}


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 057 — NexGen FAZ-2.6: Fiyat Yönetimi Yetkileri")
    print("=" * 65)

    # ── 1) Yetki kodlarını ekle ───────────────────────────────────
    print("\n[1] sistem_yetki — 4 yeni fiyat yetkisi:")
    for kod, ad, acik, sira in YENI_YETKILER:
        mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if mev:
            print(f"  SKIP  Id={mev['Id']} Kod='{kod}'")
        else:
            cur.execute("""
                INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira)
                VALUES (?, 'nexgen', ?, ?, ?)
            """, (kod, ad, acik, sira))
            print(f"  EKLENDI Id={cur.lastrowid} Kod='{kod}'")
    con.commit()

    # ── 2) Yönetim rolü — tam yetki ──────────────────────────────
    print(f"\n[2] Yönetim (RolId={YONETIM_ROL_ID}) → 4 fiyat yetkisi:")
    for kod, _, _, _ in YENI_YETKILER:
        yid = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not yid:
            print(f"  HATA: Kod='{kod}' bulunamadı!")
            continue
        mev = cur.execute(
            "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (YONETIM_ROL_ID, yid['Id'])
        ).fetchone()
        if mev:
            print(f"  SKIP  Kod='{kod}'")
        else:
            cur.execute("""
                INSERT INTO sistem_rol_yetki
                  (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                   can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage)
                VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            """, (YONETIM_ROL_ID, yid['Id']))
            print(f"  EKLENDI Kod='{kod}' → Yönetim tam yetki")
    con.commit()

    # ── 3) Satın Alma rolü ────────────────────────────────────────
    print("\n[3] 'Satın Alma' rolü → fiyat yetkileri (admin hariç):")
    sa_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Ad='Satın Alma'").fetchone()
    if not sa_rol:
        print("  UYARI: 'Satın Alma' rolü DB'de yok — atlandı.")
        print("  (Rol oluşturulduktan sonra bu migration tekrar çalıştırılabilir.)")
    else:
        sa_rol_id = sa_rol['Id']
        for kod, izinler in SATINALMA_YETKI_MAP.items():
            yid = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
            if not yid:
                print(f"  HATA: Kod='{kod}' bulunamadı!")
                continue
            mev = cur.execute(
                "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (sa_rol_id, yid['Id'])
            ).fetchone()
            if mev:
                print(f"  SKIP  Kod='{kod}'")
            else:
                cur.execute("""
                    INSERT INTO sistem_rol_yetki
                      (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                       can_view, can_create, can_update, can_delete,
                       can_approve, can_report, can_manage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)
                """, (
                    sa_rol_id, yid['Id'],
                    izinler.get('can_view', 0),
                    izinler.get('can_update', 0),
                    izinler.get('can_view', 0),
                    izinler.get('can_create', 0),
                    izinler.get('can_update', 0),
                    izinler.get('can_approve', 0),
                    izinler.get('can_view', 0),
                ))
                print(f"  EKLENDI Kod='{kod}' → Satın Alma: {izinler}")
    con.commit()

    # ── schema_migrations ─────────────────────────────────────────
    sm_kol = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'aciklama' in sm_kol:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (57, 'nexgen fiyat yonetimi yetki kodlari FAZ-2.6')")
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (57)")
    con.commit()

    # ── Doğrulama ─────────────────────────────────────────────────
    print("\n[4] Doğrulama — nexgen.fiyat.* yetkileri:")
    for r in cur.execute("SELECT Kod, Ad FROM sistem_yetki WHERE Kod LIKE 'nexgen.fiyat.%' ORDER BY Sira").fetchall():
        print(f"  {r['Kod']:35s}  {r['Ad']}")

    con.close()
    print("\nMigration 057 tamamlandı.")


if __name__ == '__main__':
    run()

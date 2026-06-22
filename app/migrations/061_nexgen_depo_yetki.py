# -*- coding: utf-8 -*-
"""
Migration 061 — NexGen FAZ-3A: Depo Yetkileri
===============================================
Yapılacaklar:
  [1] nexgen.depo.view  — Depo ekranını görüntüleme
  [2] nexgen.depo.giris — Mal kabul / depo girişi yapma
  [3] Yönetim rolüne (RolId=1) her iki yetkiyi de tam ver
  [4] Depo rolü varsa (Ad='Depo') bu yetkileri ver — can_manage=0 (yönetim değil)
  [5] Satın Alma rolüne nexgen.depo.view ver (gelen/kalan görmesi için), depo.giris YOK
  [6] schema_migrations version=61

Yetki sınırları:
  Depo rolü:
    nexgen.depo.view  can_view=1
    nexgen.depo.giris can_view=1 can_create=1   ← mal kabul yapabilir
    fiyat yetkileri VERİLMEZ

  Satın Alma rolü:
    nexgen.depo.view  can_view=1               ← gelen/kalan görür
    nexgen.depo.giris VERİLMEZ                 ← mal kabul yapamaz

İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

YENI_YETKILER = [
    # (Kod, Modul, Ad, Aciklama, Sira)
    ('nexgen.depo.view',  'nexgen', 'NexGen Depo Görüntüleme',
     'Depo ekrani ve mal kabul gecmisi goruntulem', 140),
    ('nexgen.depo.giris', 'nexgen', 'NexGen Depo Mal Kabul',
     'Mal kabul yapma ve stok giris hareketi olusturma', 141),
]


def _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira):
    mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
    if mev:
        print(f"  SKIP  yetki '{kod}' zaten var Id={mev['Id']}")
        return mev['Id']
    cur.execute(
        "INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)",
        (kod, modul, ad, acik, sira)
    )
    yid = cur.lastrowid
    con.commit()
    print(f"  EKLENDI yetki '{kod}' Id={yid}")
    return yid


def _rol_yetki_ata(cur, con, rol_id, yetki_id, izinler, etiket):
    mev = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (rol_id, yetki_id)
    ).fetchone()
    if mev:
        print(f"  SKIP  {etiket} zaten atanmış")
        return
    fields = ['RolId', 'YetkiId', 'Gorebilir', 'Duzenleyebilir']
    vals   = [rol_id, yetki_id, 1, 0]
    for col in ('can_view', 'can_create', 'can_update', 'can_delete',
                'can_approve', 'can_report', 'can_manage'):
        fields.append(col)
        vals.append(izinler.get(col, 0))
    ph = ', '.join(['?'] * len(vals))
    cur.execute(f"INSERT INTO sistem_rol_yetki ({', '.join(fields)}) VALUES ({ph})", vals)
    con.commit()
    print(f"  EKLENDI {etiket}")


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 061 — NexGen FAZ-3A: Depo Yetkileri")
    print("=" * 65)

    # ── 1) Yetki kodlarını oluştur ────────────────────────────────
    print("\n[1] Yetki kodları:")
    yetki_idler = {}
    for (kod, modul, ad, acik, sira) in YENI_YETKILER:
        yetki_idler[kod] = _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira)

    # ── 2) Yönetim rolüne tam yetki ───────────────────────────────
    tam_izin = dict(can_view=1, can_create=1, can_update=1, can_delete=1,
                    can_approve=1, can_report=1, can_manage=1)
    print(f"\n[2] Yönetim (RolId={YONETIM_ROL_ID}) yetki atamaları:")
    for kod, yid in yetki_idler.items():
        _rol_yetki_ata(cur, con, YONETIM_ROL_ID, yid, tam_izin, f"Yönetim → {kod}")

    # ── 3) Depo rolü ──────────────────────────────────────────────
    print("\n[3] Depo rolü:")
    depo_rol = cur.execute(
        "SELECT Id FROM sistem_rol WHERE Ad='Depo'"
    ).fetchone()
    if depo_rol:
        depo_rol_id = depo_rol['Id']
        print(f"  Depo rolü bulundu Id={depo_rol_id}")
        _rol_yetki_ata(cur, con, depo_rol_id, yetki_idler['nexgen.depo.view'],
                       dict(can_view=1), "Depo → nexgen.depo.view")
        _rol_yetki_ata(cur, con, depo_rol_id, yetki_idler['nexgen.depo.giris'],
                       dict(can_view=1, can_create=1), "Depo → nexgen.depo.giris")
        # nexgen.view de verelim (modül kapısı)
        nv = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod='nexgen.view'").fetchone()
        if nv:
            _rol_yetki_ata(cur, con, depo_rol_id, nv['Id'],
                           dict(can_view=1), "Depo → nexgen.view")
    else:
        print("  Depo rolü DB'de bulunamadı — atlanıyor (henüz oluşturulmamış)")
        print("  NOT: Depo rolü oluşturulduğunda bu migration tekrar çalıştırılabilir")

    # ── 4) Satın Alma rolüne depo.view (gelen/kalan görsün) ───────
    print("\n[4] Satın Alma rolü (Id=38) → depo.view:")
    sa_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Ad='Satın Alma'").fetchone()
    if sa_rol:
        _rol_yetki_ata(cur, con, sa_rol['Id'], yetki_idler['nexgen.depo.view'],
                       dict(can_view=1), "SatınAlma → nexgen.depo.view")
        # depo.giris VERİLMEZ — satın alma mal kabul yapamaz
        print("  nexgen.depo.giris VERİLMEDİ (satın alma mal kabul yapamaz)")
    else:
        print("  Satın Alma rolü bulunamadı — atlanıyor")

    # ── 5) schema_migrations ──────────────────────────────────────
    print("\n[5] schema_migrations:")
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
        "VALUES (61, 'nexgen depo yetkileri FAZ-3A')"
    )
    con.commit()
    print("  version=61 (INSERT OR IGNORE)")

    # ── Özet doğrulama ────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("ÖZET:")
    for kod, yid in yetki_idler.items():
        print(f"  {kod} Id={yid}")

    yon_cnt = cur.execute(
        "SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId=? AND YetkiId IN (?,?)",
        (YONETIM_ROL_ID,
         yetki_idler['nexgen.depo.view'], yetki_idler['nexgen.depo.giris'])
    ).fetchone()[0]
    print(f"  Yönetim depo yetki satırları={yon_cnt} (beklenen=2)")

    if sa_rol:
        sa_depo_giris = cur.execute(
            "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (sa_rol['Id'], yetki_idler['nexgen.depo.giris'])
        ).fetchone()
        print(f"  SatınAlma depo.giris={'VAR (HATA)' if sa_depo_giris else 'YOK (dogru)'}")
    print("=" * 65)

    con.close()
    print("Migration 061 tamamlandı.")


if __name__ == '__main__':
    run()

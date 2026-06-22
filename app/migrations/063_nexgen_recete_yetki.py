# -*- coding: utf-8 -*-
"""
Migration 063 — NexGen FAZ-4A: Reçete Yetkileri
=================================================
Yapılacaklar:
  [1] nexgen.recete.view    — Formülleri görüntüleme
  [2] nexgen.recete.create  — Yeni formül/varyant/kalem oluşturma (AR-GE / Vedat)
  [3] nexgen.recete.approve — Formülü onaylama/reddetme (Yönetim)
  [4] nexgen.recete.manage  — Arşivleme, klonlama (Yönetim)
  [5] Rol atamaları:
        Yönetim (RolId=1)  → hepsi tam
        AR-GE rolü varsa   → view + create (onay ve manage YOK)
        Satın Alma rolü    → hiçbir reçete yetkisi YOK
        Depo rolü          → hiçbir reçete yetkisi YOK
  [6] schema_migrations version=63

Yetki sınırları:
  Satın Alma: reçete göremez. Hammadde ihtiyacını MRP önerisinden görecek (ileride).
  Depo: reçete göremez. Stok hareketi yapar; reçete içeriği yetkisiz kullanıcılarda görünmez.
  AR-GE: taslak oluşturabilir, düzenleyebilir, onaya gönderebilir; onaylayamaz, manage edemez.
  Onay yetkisi: sadece Yönetim.

İdempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

YENI_YETKILER = [
    # (Kod, Modul, Ad, Aciklama, Sira)
    ('nexgen.recete.view',    'nexgen', 'NexGen Reçete Görüntüleme',
     'Formül ve reçete listesini görüntüleme', 150),
    ('nexgen.recete.create',  'nexgen', 'NexGen Reçete Oluşturma',
     'Yeni formül, renk/boyut varyantı ve reçete kalemi oluşturma', 151),
    ('nexgen.recete.approve', 'nexgen', 'NexGen Reçete Onayı',
     'Taslak formülü onaylama veya reddetme', 152),
    ('nexgen.recete.manage',  'nexgen', 'NexGen Reçete Yönetimi',
     'Formül arşivleme, klonlama ve aktif reçete yönetimi', 153),
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
    print("Migration 063 — NexGen FAZ-4A: Reçete Yetkileri")
    print("=" * 65)

    # ── 1) Yetki kodlarını oluştur ────────────────────────────────
    print("\n[1] Yetki kodları:")
    yetki_idler = {}
    for (kod, modul, ad, acik, sira) in YENI_YETKILER:
        yetki_idler[kod] = _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira)

    # ── 2) Yönetim rolüne tam yetki ───────────────────────────────
    tam_izin = dict(can_view=1, can_create=1, can_update=1, can_delete=1,
                    can_approve=1, can_report=1, can_manage=1)
    print(f"\n[2] Yönetim (RolId={YONETIM_ROL_ID}) — tam yetki:")
    for kod, yid in yetki_idler.items():
        _rol_yetki_ata(cur, con, YONETIM_ROL_ID, yid, tam_izin, f"Yönetim → {kod}")

    # ── 3) AR-GE rolü: view + create (onay yetkisi yok) ──────────
    print("\n[3] AR-GE rolü:")
    arge_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Ad='AR-GE'").fetchone()
    if arge_rol:
        arge_id = arge_rol['Id']
        print(f"  AR-GE rolü bulundu Id={arge_id}")
        _rol_yetki_ata(cur, con, arge_id, yetki_idler['nexgen.recete.view'],
                       dict(can_view=1), "AR-GE → nexgen.recete.view")
        _rol_yetki_ata(cur, con, arge_id, yetki_idler['nexgen.recete.create'],
                       dict(can_view=1, can_create=1, can_update=1), "AR-GE → nexgen.recete.create")
        # nexgen.recete.approve VERİLMEZ — AR-GE kendi formülünü onaylayamaz
        print("  nexgen.recete.approve VERİLMEDİ (AR-GE onaylayamaz, sadece oluşturur)")
    else:
        print("  AR-GE rolü DB'de bulunamadı — atlanıyor")
        print("  NOT: AR-GE rolü oluşturulduğunda bu migration tekrar çalıştırılabilir")

    # ── 4) Satın Alma rolü — reçete yetkisi YOK ──────────────────
    print("\n[4] Satın Alma rolü:")
    print("  Reçete yetkileri VERİLMİYOR.")
    print("  Satın Alma hammadde ihtiyacını ileride MRP önerisinden görecek.")

    # ── 5) Depo rolü — reçete yetkisi YOK ────────────────────────
    print("\n[5] Depo rolü:")
    print("  Reçete yetkileri VERİLMİYOR.")
    print("  Depo stok hareketi yapar; reçete detayı yetkisiz kullanıcılarda görünmez.")

    # ── 6) schema_migrations ──────────────────────────────────────
    print("\n[6] schema_migrations:")
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
        "VALUES (63, 'nexgen recete yetkileri FAZ-4A')"
    )
    con.commit()
    print("  version=63 (INSERT OR IGNORE)")

    # ── Özet doğrulama ────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("ÖZET:")
    for kod, yid in yetki_idler.items():
        print(f"  {kod}  Id={yid}")

    yon_cnt = cur.execute(
        "SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId=? AND YetkiId IN ({})".format(
            ','.join('?' * len(yetki_idler))
        ),
        [YONETIM_ROL_ID] + list(yetki_idler.values())
    ).fetchone()[0]
    print(f"  Yönetim reçete yetki satırları={yon_cnt} (beklenen=4)")

    # AR-GE için negatif kontrol: approve ve manage verilmemeli
    arge_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Ad='AR-GE'").fetchone()
    if arge_rol:
        for yasak_kod in ('nexgen.recete.approve', 'nexgen.recete.manage'):
            yasak_yid = yetki_idler.get(yasak_kod)
            var = cur.execute(
                "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (arge_rol['Id'], yasak_yid)
            ).fetchone()
            durum = 'VAR (HATA!)' if var else 'YOK (doğru)'
            print(f"  AR-GE → {yasak_kod}: {durum}")

    print("  Satın Alma / Depo: reçete yetkisi verilmedi (tasarım gereği)")

    print("=" * 65)

    con.close()
    print("Migration 063 tamamlandı.")


if __name__ == '__main__':
    run()

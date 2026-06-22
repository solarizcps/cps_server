# -*- coding: utf-8 -*-
"""
Migration 059 — NexGen FAZ-2.8: Yönetim Merkezi Yetki + Satın Alma Rolü
=========================================================================
Yapılacaklar:
  [1] nexgen.view yetki kodu — yoksa oluştur, Yönetim rolüne ata
  [2] nexgen.yonetim.manage yetki kodu — yoksa oluştur, Yönetim rolüne ata
  [3] "Satın Alma" rolü oluştur (yoksa)
  [4] Satın Alma rolüne uygun nexgen yetkileri ata
      (nexgen.view dahil; nexgen.yonetim.manage VERİLMEZ)
  [5] İbrahim'e dokunma — rol değişikliği yok (ilerleyen faza bırakıldı)
  [6] schema_migrations version=59 kaydet

İdempotent: Tekrar çalıştırılabilir, mevcut kayıtları silmez.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1  # Yönetim rolü

# Yeni / eksik yetki kodları: (Kod, Modul, Ad, Aciklama, Sira)
YENI_YETKILER = [
    ('nexgen.view',
     'nexgen', 'NexGen Modül Görüntüleme',
     'NexGen modulune erisim - temel goruntulem', 100),
    ('nexgen.yonetim.manage',
     'nexgen', 'NexGen Yönetim Merkezi',
     'Stok kart/tedarikci/eslestirme master veri yonetimi', 130),
]

# Satın Alma rolüne verilecek yetki kodu → izin haritası
SATINALMA_YETKI_MAP = {
    'nexgen.view':             dict(can_view=1),
    'nexgen.stok.view':        dict(can_view=1),
    'nexgen.satinalma.view':   dict(can_view=1),
    'nexgen.satinalma.manage': dict(can_view=1, can_create=1, can_update=1),
    'nexgen.tedarikci.view':   dict(can_view=1),
    'nexgen.fiyat.view':       dict(can_view=1),
    'nexgen.fiyat.manage':     dict(can_view=1, can_create=1),
    'nexgen.fiyat.approve':    dict(can_view=1, can_approve=1),
    # nexgen.yonetim.manage  → VERİLMEZ
    # nexgen.fiyat.admin     → VERİLMEZ
    # nexgen.tedarikci.manage→ VERİLMEZ
    # nexgen.stok.manage     → VERİLMEZ
}


def _yetki_ekle_veya_bul(cur, kon, kod, modul, ad, acik, sira):
    """Yetki kodu yoksa oluştur, varsa mevcut Id'yi döner."""
    mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
    if mev:
        print(f"  SKIP  yetki '{kod}' zaten var Id={mev['Id']}")
        return mev['Id']
    cur.execute(
        "INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)",
        (kod, modul, ad, acik, sira)
    )
    yid = cur.lastrowid
    kon.commit()
    print(f"  EKLENDI yetki '{kod}' Id={yid}")
    return yid


def _rol_yetki_ata(cur, kon, rol_id, yetki_id, izinler, etiket):
    """Rol-yetki kaydı yoksa ekle."""
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
    kon.commit()
    print(f"  EKLENDI {etiket}")


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 059 — NexGen FAZ-2.8: Yönetim Yetki + Satın Alma Rolü")
    print("=" * 65)

    # ── 1) Yetki kodlarını oluştur / bul ──────────────────────────
    print("\n[1] Yetki kodları:")
    yetki_idler = {}
    for (kod, modul, ad, acik, sira) in YENI_YETKILER:
        yetki_idler[kod] = _yetki_ekle_veya_bul(cur, con, kod, modul, ad, acik, sira)

    # ── 2) Yönetim rolüne her iki yetki kodunu ata ───────────────
    print(f"\n[2] Yönetim (RolId={YONETIM_ROL_ID}) yetki atamaları:")
    tam_izin = dict(can_view=1, can_create=1, can_update=1, can_delete=1,
                    can_approve=1, can_report=1, can_manage=1)
    for kod, yid in yetki_idler.items():
        _rol_yetki_ata(cur, con, YONETIM_ROL_ID, yid, tam_izin,
                       f"Yönetim → {kod}")

    # ── 3) "Satın Alma" rolü oluştur ──────────────────────────────
    print("\n[3] 'Satın Alma' rolü:")
    sa_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Ad='Satın Alma'").fetchone()
    if sa_rol:
        sa_rol_id = sa_rol['Id']
        print(f"  SKIP — zaten var Id={sa_rol_id}")
    else:
        cur.execute("""
            INSERT INTO sistem_rol (Ad, Aciklama, Renk, Aktif, SuperAdmin)
            VALUES ('Satın Alma', 'NexGen satın alma kullanıcıları',
                    '#f59e0b', 1, 0)
        """)
        sa_rol_id = cur.lastrowid
        con.commit()
        print(f"  EKLENDI — Id={sa_rol_id}")

    # ── 4) Satın Alma rolüne nexgen yetkileri ─────────────────────
    print(f"\n[4] Satın Alma (RolId={sa_rol_id}) yetki atamaları:")
    for yetki_kod, izinler in SATINALMA_YETKI_MAP.items():
        # Önce yetki DB'de var mı kontrol et; nexgen.view artık garantili var
        yid_row = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (yetki_kod,)).fetchone()
        if not yid_row:
            print(f"  UYARI: Yetki kodu bulunamadı: '{yetki_kod}' — atlandı")
            continue
        _rol_yetki_ata(cur, con, sa_rol_id, yid_row['Id'], izinler,
                       f"SatınAlma → {yetki_kod}")

    # ── 5) İbrahim kontrolü — dokunma ─────────────────────────────
    print("\n[5] İbrahim kullanıcı kontrolü (değiştirilmeyecek):")
    ibrahim = cur.execute(
        "SELECT Id, KullaniciAdi, RolId FROM sistem_kullanici "
        "WHERE lower(KullaniciAdi)='ibrahim'"
    ).fetchone()
    if ibrahim:
        rol = cur.execute("SELECT Ad FROM sistem_rol WHERE Id=?", (ibrahim['RolId'],)).fetchone()
        print(f"  ibrahim — Id={ibrahim['Id']} RolId={ibrahim['RolId']} "
              f"Rol={rol['Ad'] if rol else '?'} — DOKUNULMADI")
    else:
        print("  ibrahim bulunamadı")

    # ── 6) schema_migrations ──────────────────────────────────────
    print("\n[6] schema_migrations:")
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
        "VALUES (59, 'nexgen yonetim yetki ve satin alma rolu FAZ-2.8')"
    )
    con.commit()
    print("  version=59 (INSERT OR IGNORE — zaten varsa atlanır)")

    # ── Özet ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("ÖZET:")
    for kod, yid in yetki_idler.items():
        print(f"  {kod} Id={yid}")

    sa_yetki_cnt = cur.execute(
        "SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId=?", (sa_rol_id,)
    ).fetchone()[0]
    print(f"  'Satın Alma' rolü Id={sa_rol_id}  yetki sayısı={sa_yetki_cnt}")

    # Doğrulama: Yönetim nexgen.view görüyor mu?
    nv_id = yetki_idler.get('nexgen.view')
    yon_nv = cur.execute(
        "SELECT can_view FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (YONETIM_ROL_ID, nv_id)
    ).fetchone()
    print(f"  Yönetim nexgen.view can_view={yon_nv['can_view'] if yon_nv else 'YOK'}")

    # Doğrulama: Satın Alma nexgen.view görüyor mu?
    sa_nv = cur.execute(
        "SELECT can_view FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (sa_rol_id, nv_id)
    ).fetchone()
    print(f"  SatınAlma nexgen.view can_view={sa_nv['can_view'] if sa_nv else 'YOK'}")

    # Doğrulama: Satın Alma nexgen.yonetim.manage ALMADI mi?
    ym_id = yetki_idler.get('nexgen.yonetim.manage')
    sa_ym = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (sa_rol_id, ym_id)
    ).fetchone()
    print(f"  SatınAlma nexgen.yonetim.manage={'VAR (HATA!)' if sa_ym else 'YOK (doğru)'}")

    print(f"  İbrahim RolId={ibrahim['RolId'] if ibrahim else '?'} "
          f"değişmedi={'EVET' if ibrahim and ibrahim['RolId'] == 34 else 'HAYIR'}")
    print("=" * 65)

    con.close()
    print("Migration 059 tamamlandı.")


if __name__ == '__main__':
    run()

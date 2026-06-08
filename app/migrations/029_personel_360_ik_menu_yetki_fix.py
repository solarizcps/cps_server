# -*- coding: utf-8 -*-
"""
Migration 029 — Personel 360 İK Menüsü Yetki Fix
==================================================

Amaç:
  Canlı servarda İdari İşler (ve Yönetim) rollerinin
  personel_360 can_view yetkisine sahip olmasını garantilemek.

  Migration 024 bu seed'leri zaten tanımlamıştır.
  Bu migration, 024'ün uygulanmamış olabileceği canlı ortamlarda
  güvenli bir yeniden uygulama sağlar.

  Menü koşulu: {% if yetki('personel_360') %}
  Route koşulu: @yetki_gerekli('personel_360', 'can_view')
  Bunların eşleşmesi için sistem_rol_yetki'de ilgili kayıt olmalıdır.

Rol tespiti:
  Sabit RolId KULLANILMAZ.
  Rol adına göre dinamik olarak bulunur:
    'İdari İşler'  → personel_360 + alt kodlar (can_view=1, can_create=1)
    'Yönetim'      → personel_360 + alt kodlar (tam yetki)
  Bu sayede canlı servarda RolId farklı olsa da çalışır.

Korunan:
  - Finans, Enjeksiyon, Planlama, Hedef modülleri: dokunulmaz
  - Mevcut kullanıcıların RolId'leri: değişmez
  - SuperAdmin, Muhasebe, Grafik, Kalite, Çin Ofis rolleri: dokunulmaz
  - Mevcut sistem_rol_yetki kayıtları: INSERT OR IGNORE ile korunur

Idempotent:
  INSERT OR IGNORE — tekrar çalıştırılabilir, veriyi bozmaz

Versiyon: 029
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "029"
ACIKLAMA = "personel_360 IK menu yetki fix: idari isler ve yonetim rolleri"

# ── Seed edilecek yetki kodları ───────────────────────────────────────────────
YENI_YETKILER = [
    # (Kod, Ad, Modul, Sira)
    ("personel_360",            "Personel 360 Erişim",               "yonetim", 144),
    ("personel_360.ik",         "Personel İK Alanları Görme",        "yonetim", 145),
    ("personel_360.ik.duzenle", "Personel İK Alanları Düzenleme",    "yonetim", 146),
    ("personel_360.usta",       "Personel 360 Usta Filtreli Görünüm","yonetim", 147),
    ("personel_maas",           "Maaş Görüntüleme",                  "yonetim", 148),
    ("personel_maas.duzenle",   "Maaş Girişi ve Düzenleme",          "yonetim", 149),
    ("personel_izin",           "İzin Yönetimi",                     "yonetim", 150),
    ("personel_devam",          "Devam / PDKS",                      "yonetim", 151),
    ("personel_ik_not",         "Gizli İK Görüşme Notları",          "yonetim", 152),
]

# Yönetim rolü: tüm yetki kodları, tam haklar
YONETIM_ROL_AD = "Yönetim"
YONETIM_KODLAR = [
    "personel_360", "personel_360.ik", "personel_360.ik.duzenle",
    "personel_360.usta", "personel_maas", "personel_maas.duzenle",
    "personel_izin", "personel_devam", "personel_ik_not",
]

# İdari İşler rolü: usta filtresi hariç, silme/onay/yönetim yok
IDARI_ROL_AD = "İdari İşler"
IDARI_KODLAR = [
    "personel_360", "personel_360.ik", "personel_360.ik.duzenle",
    "personel_maas", "personel_maas.duzenle",
    "personel_izin", "personel_devam", "personel_ik_not",
    # personel_360.usta intentionally excluded
]


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def _find_rol_id(con, rol_ad):
    """Rol adına göre Id bul."""
    r = con.execute("SELECT Id FROM sistem_rol WHERE Ad=? AND Aktif=1", (rol_ad,)).fetchone()
    if r:
        return r["Id"]
    r2 = con.execute("SELECT Id FROM sistem_rol WHERE Ad=?", (rol_ad,)).fetchone()
    return r2["Id"] if r2 else None


def _get_or_insert_yetki(cur, con, kod, ad, modul, sira):
    """sistem_yetki kaydını getir veya oluştur. YetkiId döner."""
    row = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
    if row:
        return row["Id"]
    cur.execute("""
        INSERT OR IGNORE INTO sistem_yetki (Kod, Ad, Aciklama, Modul, Sira)
        VALUES (?, ?, ?, ?, ?)
    """, (kod, ad, ad, modul, sira))
    row2 = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
    return row2["Id"] if row2 else None


def _seed_rol_yetki(cur, con, rol_id, kodlar, tam_yetki=False):
    """
    Verilen rolle yetki listesini seed'le.
    tam_yetki=True → can_delete=1, can_approve=1, can_manage=1
    tam_yetki=False → can_delete=0, can_approve=0, can_manage=0
    """
    for kod, ad, modul, sira in YENI_YETKILER:
        if kod not in kodlar:
            continue
        yid = _get_or_insert_yetki(cur, con, kod, ad, modul, sira)
        if not yid:
            continue
        if tam_yetki:
            cur.execute("""
                INSERT OR IGNORE INTO sistem_rol_yetki
                  (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                   can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage)
                VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            """, (rol_id, yid))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO sistem_rol_yetki
                  (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                   can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage)
                VALUES (?, ?, 1, 1, 1, 1, 1, 0, 0, 1, 0)
            """, (rol_id, yid))


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    yonetim_id = _find_rol_id(con, YONETIM_ROL_AD)
    idari_id   = _find_rol_id(con, IDARI_ROL_AD)
    print(f"\n  Yönetim rol ID    : {yonetim_id or '!! BULUNAMADI'}")
    print(f"  İdari İşler rol ID: {idari_id or '!! BULUNAMADI'}")

    print(f"\n[1] sistem_yetki — personel_360* kodları:")
    for kod, ad, modul, sira in YENI_YETKILER:
        row = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        durum = f"MEVCUT Id={row['Id']}" if row else "EKLENECEK"
        print(f"  [{durum:20s}] {kod}")

    for rol_id, rol_ad, kodlar in [
        (yonetim_id, YONETIM_ROL_AD, YONETIM_KODLAR),
        (idari_id,   IDARI_ROL_AD,   IDARI_KODLAR),
    ]:
        print(f"\n[2] sistem_rol_yetki — {rol_ad} (RolId={rol_id}):")
        if not rol_id:
            print(f"  !! ROL BULUNAMADI — atlanacak")
            continue
        for kod in kodlar:
            yid = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
            if yid:
                mev = con.execute(
                    "SELECT can_view FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                    (rol_id, yid["Id"])
                ).fetchone()
                durum = f"MEVCUT can_view={mev['can_view']}" if mev else "EKLENECEK"
            else:
                durum = "YETKI KODU YOK (önce eklenecek)"
            print(f"  [{durum:30s}] {kod}")

    mig = con.execute(
        "SELECT version FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n  schema_migrations {MIGRATION_VERSION}: {'KAYITLI — atlanacak' if mig else 'YOK — eklenecek'}")
    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()

    yonetim_id = _find_rol_id(con, YONETIM_ROL_AD)
    idari_id   = _find_rol_id(con, IDARI_ROL_AD)

    if not yonetim_id:
        print(f"  [UYARI] '{YONETIM_ROL_AD}' rolü bulunamadı — atlandı")
    if not idari_id:
        print(f"  [UYARI] '{IDARI_ROL_AD}' rolü bulunamadı — atlandı")

    # 1) Yönetim rolü seed
    if yonetim_id:
        _seed_rol_yetki(cur, con, yonetim_id, YONETIM_KODLAR, tam_yetki=True)

    # 2) İdari İşler rolü seed
    if idari_id:
        _seed_rol_yetki(cur, con, idari_id, IDARI_KODLAR, tam_yetki=False)

    # 3) schema_migrations kaydı
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"[APPLY OK] Migration {MIGRATION_VERSION} uygulandı.")


def verify(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    idari_id = _find_rol_id(con, IDARI_ROL_AD)
    yonetim_id = _find_rol_id(con, YONETIM_ROL_AD)

    print(f"\n[A] Kritik yetki kontrolü (menü görünürlüğü için):")
    for rol_id, rol_ad in [(yonetim_id, YONETIM_ROL_AD), (idari_id, IDARI_ROL_AD)]:
        if not rol_id:
            print(f"  {rol_ad}: ROL YOK")
            continue
        yid = con.execute("SELECT Id FROM sistem_yetki WHERE Kod='personel_360'").fetchone()
        if yid:
            srv = con.execute(
                "SELECT can_view, can_create FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (rol_id, yid["Id"])
            ).fetchone()
            if srv:
                print(f"  {rol_ad:20s} (RolId={rol_id}): personel_360 can_view={srv['can_view']} can_create={srv['can_create']} ✓")
            else:
                print(f"  {rol_ad:20s} (RolId={rol_id}): personel_360 KAYIT YOK ✗")
        else:
            print(f"  personel_360 yetki kodu TANIMLI DEĞİL ✗")

    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[B] schema_migrations: {dict(mig) if mig else 'KAYIT YOK!'}")
    print()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dryrun"
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"HATA: DB bulunamadı: {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    try:
        if mode == "--dryrun":
            dryrun(con)
        elif mode == "--apply":
            dryrun(con)
            print("\n[APPLY BAŞLIYOR]")
            apply(con)
            verify(con)
        elif mode == "--verify":
            verify(con)
        else:
            print(f"Kullanım: python {sys.argv[0]} [--dryrun | --apply | --verify]")
            sys.exit(1)
    except Exception as e:
        con.rollback()
        print(f"\n[HATA] Migration başarısız: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()

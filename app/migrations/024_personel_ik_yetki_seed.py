# -*- coding: utf-8 -*-
"""
Migration 024 — Personel İK / Personel 360 / Maaş / İzin / Devam Yetki Seed
=============================================================================

Amaç:
  İK ve Personel 360 erişim kontrol mimarisini kurmak.
  Yeni yetki kodları eklenir, Yönetim ve İdari İşler rollerine atanır.

Korunan:
  - ENJ_CORE, Finans, Planlama: dokunulmaz
  - Mevcut kullanıcıların RolId'leri: değişmez
  - Halil, İbrahim rolleri: değişmez
  - Mevcut sistem_yetki ve sistem_rol_yetki kayıtları: değişmez

Idempotent:
  - INSERT OR IGNORE ile güvenli tekrar çalıştırılabilir
  - Unique constraint: sistem_yetki.Kod, sistem_rol_yetki(RolId, YetkiId)

Versiyon: 024
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "024"
ACIKLAMA = "Personel IK / P360 / Maas / Izin / Devam yetki seed"

# ─── Yeni yetki kodları ───────────────────────────────────────────────────────
YENI_YETKILER = [
    # (Kod, Ad, Modul, Sira)
    ("personel_360",           "Personel 360 Erişim",              "yonetim", 144),
    ("personel_360.ik",        "Personel İK Alanları Görme",       "yonetim", 145),
    ("personel_360.ik.duzenle","Personel İK Alanları Düzenleme",   "yonetim", 146),
    ("personel_360.usta",      "Personel 360 Usta Filtreli Görünüm","yonetim",147),
    ("personel_maas",          "Maaş Görüntüleme",                 "yonetim", 148),
    ("personel_maas.duzenle",  "Maaş Girişi ve Düzenleme",         "yonetim", 149),
    ("personel_izin",          "İzin Yönetimi",                    "yonetim", 150),
    ("personel_devam",         "Devam / PDKS",                     "yonetim", 151),
    ("personel_ik_not",        "Gizli İK Görüşme Notları",         "yonetim", 152),
]

# ─── Yönetim rolü (Id=1, SuperAdmin) — tüm yetkileri tam ────────────────────
#     can_view=1, can_create=1, can_update=1, can_delete=1,
#     can_approve=1, can_report=1, can_manage=1
YONETIM_ROL_ID = 1
YONETIM_YETKI_KODLARI = [
    "personel_360",
    "personel_360.ik",
    "personel_360.ik.duzenle",
    "personel_360.usta",
    "personel_maas",
    "personel_maas.duzenle",
    "personel_izin",
    "personel_devam",
    "personel_ik_not",
]

# ─── İdari İşler rolü (Id=34) — İK alanları, maaş yaz, NOT yazabilir ────────
#     can_delete=0, can_approve=0, can_manage=0
IDARI_ROL_ID = 34
IDARI_YETKI_KODLARI = [
    "personel_360",
    "personel_360.ik",
    "personel_360.ik.duzenle",
    "personel_maas",
    "personel_maas.duzenle",
    "personel_izin",
    "personel_devam",
    "personel_ik_not",
    # personel_360.usta intentionally excluded: usta filtresi sadece usta rolüne
]


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def dryrun(con):
    """Neyin ekleneceğini göster, DB'ye yazma."""
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    print(f"\n[1] sistem_yetki — Eklenecek yetki kodları ({len(YENI_YETKILER)} adet):")
    for kod, ad, modul, sira in YENI_YETKILER:
        mevcut = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        durum  = f"ZATEN VAR (Id={mevcut['Id']}) — atlanacak" if mevcut else "YOK — eklenecek"
        print(f"  [{durum}] {kod} — {ad}")

    print(f"\n[2] sistem_rol_yetki — Yönetim (RolId={YONETIM_ROL_ID}) — Tam yetki:")
    for kod in YONETIM_YETKI_KODLARI:
        yid = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if yid:
            mev = con.execute(
                "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (YONETIM_ROL_ID, yid["Id"])
            ).fetchone()
            print(f"  {'ZATEN VAR — atlanacak' if mev else 'EKLENECEK':30s} {kod}")
        else:
            print(f"  {'YETKI KODU YOK (önce eklenecek)':30s} {kod}")

    print(f"\n[3] sistem_rol_yetki — İdari İşler (RolId={IDARI_ROL_ID}) — İK + Maaş:")
    for kod in IDARI_YETKI_KODLARI:
        yid = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if yid:
            mev = con.execute(
                "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (IDARI_ROL_ID, yid["Id"])
            ).fetchone()
            print(f"  {'ZATEN VAR — atlanacak' if mev else 'EKLENECEK':30s} {kod}")
        else:
            print(f"  {'YETKI KODU YOK (önce eklenecek)':30s} {kod}")

    print(f"\n[4] Değişmeyen kullanıcılar/roller:")
    for kadi in ["halil", "ibrahim", "admin", "alpay"]:
        r = con.execute(
            "SELECT KullaniciAdi, RolId, Tip FROM sistem_kullanici WHERE KullaniciAdi=?",
            (kadi,)
        ).fetchone()
        if r:
            print(f"  {r['KullaniciAdi']:15s} RolId={r['RolId']} Tip={r['Tip']} — DEĞİŞMEYECEK")

    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    """Asıl uygulama — transactional."""
    cur = con.cursor()

    # ── Unique index kontrolü (idempotent için) ──────────────────────────────
    # sistem_yetki.Kod zaten UNIQUE olabilir, yoksa runtime kontrol yeterli
    # sistem_rol_yetki için (RolId, YetkiId) çifti kontrol edilir

    # 1) sistem_yetki INSERT OR IGNORE
    for kod, ad, modul, sira in YENI_YETKILER:
        cur.execute("""
            INSERT OR IGNORE INTO sistem_yetki (Kod, Ad, Aciklama, Modul, Sira)
            VALUES (?, ?, ?, ?, ?)
        """, (kod, ad, ad, modul, sira))

    # 2) Yönetim rolü — tüm yetkiler tam
    for kod in YONETIM_YETKI_KODLARI:
        yid_row = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not yid_row:
            continue
        yid = yid_row["Id"]
        cur.execute("""
            INSERT OR IGNORE INTO sistem_rol_yetki
              (RolId, YetkiId, Gorebilir, Duzenleyebilir,
               can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 1, 1)
        """, (YONETIM_ROL_ID, yid))

    # 3) İdari İşler rolü — İK + Maaş, silme/onay/yönetim yok
    for kod in IDARI_YETKI_KODLARI:
        yid_row = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not yid_row:
            continue
        yid = yid_row["Id"]
        cur.execute("""
            INSERT OR IGNORE INTO sistem_rol_yetki
              (RolId, YetkiId, Gorebilir, Duzenleyebilir,
               can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 1, 1, 1, 1, 0, 0, 1, 0)
        """, (IDARI_ROL_ID, yid))

    # 4) schema_migrations kaydı
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"[APPLY OK] Migration {MIGRATION_VERSION} uygulandı.")


def verify(con):
    """Apply sonrası doğrulama."""
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    print(f"\n[A] sistem_yetki — Eklenen kodlar:")
    for kod, ad, _, _ in YENI_YETKILER:
        r = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        print(f"  {'OK Id='+str(r['Id']) if r else 'EKSIK!':15s} {kod}")

    print(f"\n[B] Yönetim (RolId={YONETIM_ROL_ID}) yetki sayısı:")
    cnt = con.execute(
        "SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId=?", (YONETIM_ROL_ID,)
    ).fetchone()[0]
    print(f"  Toplam: {cnt} yetki kaydı")

    print(f"\n[C] İdari İşler (RolId={IDARI_ROL_ID}) yetki sayısı:")
    cnt2 = con.execute(
        "SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId=?", (IDARI_ROL_ID,)
    ).fetchone()[0]
    print(f"  Toplam: {cnt2} yetki kaydı")

    print(f"\n[D] Kullanıcı rolleri değişmedi mi?")
    for kadi in ["halil", "ibrahim", "admin"]:
        r = con.execute(
            "SELECT KullaniciAdi, RolId FROM sistem_kullanici WHERE KullaniciAdi=?",
            (kadi,)
        ).fetchone()
        if r:
            print(f"  {r['KullaniciAdi']:15s} RolId={r['RolId']}")

    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[E] schema_migrations: {dict(mig) if mig else 'KAYIT YOK!'}")
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
            # Önce dryrun göster
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
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()

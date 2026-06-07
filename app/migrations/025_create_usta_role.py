# -*- coding: utf-8 -*-
"""
Migration 025 — Usta Rolü Altyapısı
=====================================

Amaç:
  Saha ustası için minimum yetkili, SuperAdmin olmayan bir rol oluşturmak.
  İleride Halil/Ferhat bu role taşınabilir — bu migration yalnızca altyapıyı kurar.

Kesinlikle yapılmayan:
  - Mevcut kullanıcıların RolId'si değiştirilmez.
  - Halil, Ferhat, Murat, Deniz rolleri dokunulmaz.
  - ENJ_CORE, Finans, Planlama etkilenmez.

Idempotent:
  - Rol adına göre INSERT OR IGNORE (tekrar çalıştırılabilir)
  - sistem_rol_yetki (RolId, YetkiId) unique korumalı

Versiyon: 025
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "025"
ACIKLAMA = "Usta rolu altyapisi: SuperAdmin=0, minimal yetki seti"

USTA_ROL_AD = "Usta"

USTA_YETKI_KODLARI = [
    "personel_360",
    "personel_360.usta",
    "usta",
    "hedef",
    "hedef.personel",
    "personel_giris",
    "tasks",
]


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    # Rol var mi?
    mevcut_rol = con.execute(
        "SELECT Id, Ad, SuperAdmin FROM sistem_rol WHERE Ad=?", (USTA_ROL_AD,)
    ).fetchone()
    print(f"\n[1] sistem_rol — '{USTA_ROL_AD}' rolü:")
    if mevcut_rol:
        print(f"  ZATEN VAR (Id={mevcut_rol['Id']}, SuperAdmin={mevcut_rol['SuperAdmin']}) — atlanacak")
    else:
        print(f"  YOK — yeni eklenecek (SuperAdmin=0)")

    print(f"\n[2] Usta rolüne atanacak yetki kodları ({len(USTA_YETKI_KODLARI)} adet):")
    for kod in USTA_YETKI_KODLARI:
        sy = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not sy:
            print(f"  EKSIK sistem_yetki kaydı: {kod} — EKLENEMEZ!")
        else:
            print(f"  OK Id={sy['Id']}: {kod}")

    print(f"\n[3] Mevcut kullanıcı rolleri — DEĞİŞMEYECEK:")
    for kadi in ["halil", "ferhat", "murat", "deniz", "ibrahim", "admin"]:
        r = con.execute(
            "SELECT KullaniciAdi, RolId, Tip FROM sistem_kullanici WHERE KullaniciAdi=?",
            (kadi,)
        ).fetchone()
        if r:
            sr = con.execute("SELECT Ad FROM sistem_rol WHERE Id=?", (r["RolId"],)).fetchone()
            print(f"  {r['KullaniciAdi']:15s} RolId={r['RolId']} ({sr['Ad'] if sr else '?'}) — DOKUNULMAYACAK")

    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()

    # 1) Usta rolü ekle (idempotent)
    cur.execute("""
        INSERT OR IGNORE INTO sistem_rol
          (Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturanKullanici)
        VALUES (?, ?, ?, 1, 0, 'migration_025')
    """, (
        USTA_ROL_AD,
        "Saha ustası: bağlı personel görünümü, üretim girişi, hedef. Maaş/İK/Finans göremez.",
        "#166534",
    ))

    # Yeni oluşturulan (veya mevcut) Usta rolünün Id'sini al
    usta_rol = con.execute(
        "SELECT Id FROM sistem_rol WHERE Ad=?", (USTA_ROL_AD,)
    ).fetchone()
    usta_rol_id = usta_rol["Id"]

    # 2) Yetki kodlarını ata (idempotent)
    for kod in USTA_YETKI_KODLARI:
        sy = con.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not sy:
            print(f"  UYARI: {kod} sistem_yetki'de yok — atlandı")
            continue
        cur.execute("""
            INSERT OR IGNORE INTO sistem_rol_yetki
              (RolId, YetkiId, Gorebilir, Duzenleyebilir,
               can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 0, 1, 0, 0, 0, 0, 1, 0)
        """, (usta_rol_id, sy["Id"]))

    # tasks için can_create ve can_update de verelim (görev oluşturup güncelleyebilsin)
    tasks_sy = con.execute("SELECT Id FROM sistem_yetki WHERE Kod='tasks'").fetchone()
    if tasks_sy:
        cur.execute("""
            UPDATE sistem_rol_yetki
            SET can_create=1, can_update=1
            WHERE RolId=? AND YetkiId=?
        """, (usta_rol_id, tasks_sy["Id"]))

    # 3) schema_migrations kaydı
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"[APPLY OK] Migration {MIGRATION_VERSION} — Usta rolü oluşturuldu (Id={usta_rol_id})")


def verify(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    # Rol kontrolü
    rol = con.execute(
        "SELECT Id, Ad, SuperAdmin, Aktif FROM sistem_rol WHERE Ad=?", (USTA_ROL_AD,)
    ).fetchone()
    print(f"\n[A] Usta rolü: {'OK Id='+str(rol['Id'])+' SuperAdmin='+str(rol['SuperAdmin']) if rol else 'EKSIK!'}")

    # Yetki atamaları
    if rol:
        print(f"\n[B] Usta rolü yetkileri:")
        for kod in USTA_YETKI_KODLARI:
            r = con.execute("""
                SELECT sry.can_view, sry.can_create, sry.can_update
                FROM sistem_rol_yetki sry
                JOIN sistem_yetki sy ON sy.Id = sry.YetkiId
                WHERE sry.RolId=? AND sy.Kod=?
            """, (rol["Id"], kod)).fetchone()
            if r:
                print(f"  OK: {kod} | v={r['can_view']} c={r['can_create']} u={r['can_update']}")
            else:
                print(f"  EKSIK: {kod}")

    # Kullanici rolleri degismedi mi?
    print(f"\n[C] Kullanıcı rolleri değişmedi mi?")
    for kadi, beklenen in [("halil", 1), ("ferhat", 35), ("ibrahim", 34), ("admin", 1)]:
        r = con.execute(
            "SELECT RolId FROM sistem_kullanici WHERE KullaniciAdi=?", (kadi,)
        ).fetchone()
        if r:
            ok = r["RolId"] == beklenen
            print(f"  {kadi:15s} RolId={r['RolId']} {'OK' if ok else 'DEGISTI!'}")

    # migrations
    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[D] schema_migrations: {dict(mig) if mig else 'KAYIT YOK!'}")
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
        print(f"\n[HATA] {e}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()

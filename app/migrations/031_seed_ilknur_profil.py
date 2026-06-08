# -*- coding: utf-8 -*-
"""
Migration 031 — İlknur Kullanici Profil Seed
=============================================

Amaç:
  sistem_kullanici kaydı olan 'ilknur' için kullanici_profil
  kaydı eksik. Bu migration eksik profili oluşturur.

  İlknur: RolId=34 (İdari İşler) → Personel 360 erişimi var
  ama kullanici_profil yoksa listede görünmez.

Korunan:
  - Var olan kullanici_profil kayıtları: değiştirilmez
  - Üretim, Finans, Enjeksiyon, Planlama: dokunulmaz

Idempotent:
  sistem_kullanici.KullaniciAdi = 'ilknur' ile dinamik arama
  INSERT OR IGNORE (tekrar çalıştırılabilir)

Versiyon: 031
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "031"
ACIKLAMA = "seed kullanici_profil for ilknur (İdari İşler)"

HEDEF_KULLANICI = "ilknur"
PROFIL_TIPI = "calisan"


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    sk = con.execute(
        "SELECT Id, KullaniciAdi, Aktif FROM sistem_kullanici WHERE LOWER(KullaniciAdi)=?",
        (HEDEF_KULLANICI,)
    ).fetchone()

    if not sk:
        print(f"  !! '{HEDEF_KULLANICI}' kullanıcısı bulunamadı — işlem gerekmez")
        return

    print(f"  sistem_kullanici: Id={sk['Id']} KullaniciAdi={sk['KullaniciAdi']} Aktif={sk['Aktif']}")

    kp = con.execute(
        "SELECT id, gercek_ad FROM kullanici_profil WHERE kaynak='sistem_kullanici' AND kaynak_id=?",
        (sk['Id'],)
    ).fetchone()

    if kp:
        print(f"  kullanici_profil: MEVCUT id={kp['id']} '{kp['gercek_ad']}' — seed gerekmez")
    else:
        print(f"  kullanici_profil: YOK — oluşturulacak")
        print(f"    gercek_ad   = İlknur")
        print(f"    profil_tipi = {PROFIL_TIPI}")
        print(f"    kaynak      = sistem_kullanici")
        print(f"    kaynak_id   = {sk['Id']}")

    mig = con.execute(
        "SELECT version FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n  schema_migrations {MIGRATION_VERSION}: {'KAYITLI' if mig else 'YOK — eklenecek'}")
    print(f"\n[DRY-RUN TAMAMLANDI]\n")


def apply(con):
    cur = con.cursor()

    sk = con.execute(
        "SELECT Id, KullaniciAdi FROM sistem_kullanici WHERE LOWER(KullaniciAdi)=?",
        (HEDEF_KULLANICI,)
    ).fetchone()

    if not sk:
        print(f"  [SKIP] '{HEDEF_KULLANICI}' bulunamadı")
    else:
        kp = con.execute(
            "SELECT id FROM kullanici_profil WHERE kaynak='sistem_kullanici' AND kaynak_id=?",
            (sk['Id'],)
        ).fetchone()

        if kp:
            print(f"  [SKIP] {HEDEF_KULLANICI} profili zaten mevcut (id={kp['id']})")
        else:
            # Departman ID: kod='idari' veya ad LIKE '%idari%' ile bul
            dept = con.execute(
                "SELECT id FROM departman_master WHERE kod='idari' OR LOWER(ad) LIKE '%idari%' LIMIT 1"
            ).fetchone()
            dept_id = dept['id'] if dept else None

            cur.execute("""
                INSERT INTO kullanici_profil
                    (kaynak, kaynak_id, gercek_ad, kullanici_adi, profil_tipi, aktif, departman_id)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, ('sistem_kullanici', sk['Id'], 'İlknur', HEDEF_KULLANICI, PROFIL_TIPI, dept_id))
            print(f"  [SEED] İlknur profili oluşturuldu dept_id={dept_id}")

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

    sk = con.execute(
        "SELECT Id FROM sistem_kullanici WHERE LOWER(KullaniciAdi)=?", (HEDEF_KULLANICI,)
    ).fetchone()
    if sk:
        kp = con.execute(
            "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE kaynak='sistem_kullanici' AND kaynak_id=?",
            (sk['Id'],)
        ).fetchone()
        if kp:
            print(f"  [OK] {HEDEF_KULLANICI} → kp.id={kp['id']} '{kp['gercek_ad']}' tip={kp['profil_tipi']} ✓")
        else:
            print(f"  [FAIL] {HEDEF_KULLANICI} için profil hâlâ yok ✗")
    else:
        print(f"  [N/A] '{HEDEF_KULLANICI}' sistem_kullanici'da bulunamadı")

    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"  schema_migrations: {dict(mig) if mig else 'YOK!'}")
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
        print(f"\n[HATA]: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()

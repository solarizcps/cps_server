# -*- coding: utf-8 -*-
"""
Migration 045 — FAZ-7B: kullanici_profil'e İK alanları + personel_maas_gecmis pk_id nullable

Değişiklikler:
  1) kullanici_profil tablosuna 9 yeni İK kolonu ekle (idempotent ALTER TABLE):
       ise_baslama_tarihi  TEXT NULL
       personel_tipi       TEXT NULL   (calisan/stajyer/sozlesmeli/diger)
       pozisyon            TEXT NULL
       ayrilma_tarihi      TEXT NULL
       calisma_durumu      TEXT NULL DEFAULT 'aktif'
       guven_skoru         INTEGER NULL
       telefon             TEXT NULL
       email               TEXT NULL
       genel_not           TEXT NULL

  2) personel_maas_gecmis: personel_pk_id NOT NULL → nullable
     SQLite NOT NULL'ı doğrudan ALTER ile kaldıramaz.
     RENAME → CREATE yeni → INSERT SELECT → DROP eski pattern.

Kural:
  - Mevcut veri bozulmaz.
  - ENJ_CORE / Finans / Planlama / Hedef tablolarına dokunulmaz.
  - personel_kullanici tablosuna dokunulmaz.
  - schema_migrations kaydı INSERT OR IGNORE.

Versiyon: 045
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "045"
ACIKLAMA = (
    "kullanici_profil IK alanlari ekle + "
    "personel_maas_gecmis.personel_pk_id nullable yap"
)

KP_YENI_KOLONLAR = [
    ("ise_baslama_tarihi", "TEXT"),
    ("personel_tipi",      "TEXT"),
    ("pozisyon",           "TEXT"),
    ("ayrilma_tarihi",     "TEXT"),
    ("calisma_durumu",     "TEXT DEFAULT 'aktif'"),
    ("guven_skoru",        "INTEGER"),
    ("telefon",            "TEXT"),
    ("email",              "TEXT"),
    ("genel_not",          "TEXT"),
]

KORUNAN_TABLOLAR = [
    "uretim_kayit", "sistem_kullanici", "sistem_rol",
    "finans_anlasma", "enj_gunluk_rapor", "personel_kullanici",
]


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def _kolon_var_mi(con, tablo, kolon):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({tablo})").fetchall()]
    return kolon in cols


def _tablo_var_mi(con, tablo):
    r = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    print("\n[1] kullanici_profil — yeni İK kolonları:")
    for kolon, tip in KP_YENI_KOLONLAR:
        var = _kolon_var_mi(con, "kullanici_profil", kolon)
        print(f"  {'MEVCUT — atlanacak' if var else 'EKLENECEK':22} {kolon} {tip}")

    print("\n[2] personel_maas_gecmis — personel_pk_id nullable kontrolü:")
    if not _tablo_var_mi(con, "personel_maas_gecmis"):
        print("  !! TABLO YOK — atlanacak")
    else:
        cols = con.execute("PRAGMA table_info(personel_maas_gecmis)").fetchall()
        for c in cols:
            if c[1] == "personel_pk_id":
                print(f"  Mevcut: personel_pk_id notnull={c[3]}")
                if c[3] == 1:
                    print("  → NOT NULL kısıtı kaldırılacak (tablo yeniden oluşturulacak)")
                else:
                    print("  → Zaten nullable, atlanacak")
        cnt = con.execute("SELECT COUNT(*) FROM personel_maas_gecmis").fetchone()[0]
        print(f"  Mevcut satır sayısı: {cnt} (taşınacak)")

    print("\n[3] Korunan tablolar kontrol:")
    for t in KORUNAN_TABLOLAR:
        var = _tablo_var_mi(con, t)
        print(f"  {t}: {'VAR (dokunulmayacak)' if var else 'YOK'}")

    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()

    # ─── 1) kullanici_profil kolonları ekle ───────────────────────────────────
    print("\n[APPLY 1] kullanici_profil — İK kolonları:")
    for kolon, tip in KP_YENI_KOLONLAR:
        if _kolon_var_mi(con, "kullanici_profil", kolon):
            print(f"  [SKIP]  {kolon} — zaten var")
        else:
            cur.execute(f"ALTER TABLE kullanici_profil ADD COLUMN {kolon} {tip}")
            print(f"  [ALTER] {kolon} {tip} — eklendi")

    # ─── 2) personel_maas_gecmis: pk_id nullable ──────────────────────────────
    print("\n[APPLY 2] personel_maas_gecmis — personel_pk_id nullable:")

    if not _tablo_var_mi(con, "personel_maas_gecmis"):
        print("  [SKIP] Tablo yok")
    else:
        cols = con.execute("PRAGMA table_info(personel_maas_gecmis)").fetchall()
        pk_id_notnull = next((c[3] for c in cols if c[1] == "personel_pk_id"), None)

        if pk_id_notnull == 0:
            print("  [SKIP] personel_pk_id zaten nullable")
        else:
            # SQLite NOT NULL kaldırma: RENAME → CREATE yeni → INSERT → DROP eski
            print("  [REBUILD] Tablo yeniden oluşturuluyor...")

            cnt_once = con.execute(
                "SELECT COUNT(*) FROM personel_maas_gecmis"
            ).fetchone()[0]
            print(f"  Mevcut satır: {cnt_once}")

            # Yeni DDL (personel_pk_id NULL yapıldı)
            cur.executescript("""
                ALTER TABLE personel_maas_gecmis
                    RENAME TO personel_maas_gecmis_old_045;

                CREATE TABLE personel_maas_gecmis (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    personel_pk_id      INTEGER,              -- NULL olabilir (profil_id'li kayıtlar)
                    kullanici_profil_id INTEGER,              -- migration 032'den
                    tutar               NUMERIC NOT NULL,
                    para_birimi         TEXT    NOT NULL DEFAULT 'TL',
                    gecerlilik_bas      TEXT    NOT NULL,
                    gecerlilik_bit      TEXT,
                    tip                 TEXT    NOT NULL DEFAULT 'maas',
                    aciklama            TEXT,
                    giren_kullanici     TEXT,
                    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                INSERT INTO personel_maas_gecmis
                    (id, personel_pk_id, kullanici_profil_id,
                     tutar, para_birimi, gecerlilik_bas, gecerlilik_bit,
                     tip, aciklama, giren_kullanici, created_at)
                SELECT
                    id, personel_pk_id,
                    CASE WHEN EXISTS(
                        SELECT 1 FROM pragma_table_info('personel_maas_gecmis_old_045')
                        WHERE name='kullanici_profil_id'
                    ) THEN kullanici_profil_id ELSE NULL END,
                    tutar, para_birimi, gecerlilik_bas, gecerlilik_bit,
                    tip, aciklama, giren_kullanici, created_at
                FROM personel_maas_gecmis_old_045;

                DROP TABLE personel_maas_gecmis_old_045;

                CREATE INDEX IF NOT EXISTS idx_pmg_personel_bit
                    ON personel_maas_gecmis (personel_pk_id, gecerlilik_bit);

                CREATE INDEX IF NOT EXISTS idx_pmg_gecerlilik_bas
                    ON personel_maas_gecmis (personel_pk_id, gecerlilik_bas);

                CREATE INDEX IF NOT EXISTS idx_pmg_profil_id
                    ON personel_maas_gecmis (kullanici_profil_id, gecerlilik_bit);
            """)

            cnt_sonra = con.execute(
                "SELECT COUNT(*) FROM personel_maas_gecmis"
            ).fetchone()[0]
            print(f"  Taşınan satır: {cnt_sonra}")
            if cnt_once != cnt_sonra:
                raise RuntimeError(
                    f"VERİ KAYBI! Önce={cnt_once} Sonra={cnt_sonra}"
                )
            print("  [OK] Tablo yeniden oluşturuldu, veri bütünlüğü korundu")

    # ─── 3) schema_migrations ─────────────────────────────────────────────────
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"\n[APPLY OK] Migration {MIGRATION_VERSION} tamamlandı.")


def verify(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    print("\n[A] kullanici_profil yeni kolonlar:")
    all_ok = True
    for kolon, _ in KP_YENI_KOLONLAR:
        var = _kolon_var_mi(con, "kullanici_profil", kolon)
        status = "OK ✓" if var else "EKSIK ✗"
        print(f"  {status:8} {kolon}")
        if not var:
            all_ok = False

    print("\n[B] personel_maas_gecmis.personel_pk_id nullable:")
    if _tablo_var_mi(con, "personel_maas_gecmis"):
        cols = con.execute("PRAGMA table_info(personel_maas_gecmis)").fetchall()
        for c in cols:
            if c[1] == "personel_pk_id":
                nn = c[3]
                print(f"  {'OK ✓' if nn == 0 else 'HALA NOT NULL ✗'} notnull={nn}")
                if nn != 0:
                    all_ok = False
        # kullanici_profil_id kolonu var mı?
        kp_id_var = _kolon_var_mi(con, "personel_maas_gecmis", "kullanici_profil_id")
        print(f"  kullanici_profil_id kolonu: {'OK ✓' if kp_id_var else 'YOK ✗'}")
        cnt = con.execute("SELECT COUNT(*) FROM personel_maas_gecmis").fetchone()[0]
        print(f"  Toplam satır: {cnt}")
    else:
        print("  [SKIP] Tablo yok")

    print("\n[C] Test: profil_id=12 için nullable insert (rollback):")
    try:
        con.execute("""
            INSERT INTO personel_maas_gecmis
                (personel_pk_id, kullanici_profil_id, tutar, para_birimi,
                 gecerlilik_bas, tip, giren_kullanici)
            VALUES (NULL, 12, 1000.0, 'TL', date('now'), 'maas', 'migration_verify_test')
        """)
        test_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("DELETE FROM personel_maas_gecmis WHERE id=?", (test_id,))
        con.commit()
        print("  OK ✓ NULL pk_id ile insert/delete başarılı (test kaydı temizlendi)")
    except Exception as e:
        con.rollback()
        print(f"  HATA ✗ {e}")
        all_ok = False

    print("\n[D] Korunan tablolar:")
    for t in KORUNAN_TABLOLAR:
        if _tablo_var_mi(con, t):
            cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt} kayıt — OK ✓")

    print(f"\n[E] schema_migrations:")
    mig = con.execute(
        "SELECT version, aciklama FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"  {dict(mig) if mig else 'KAYIT YOK ✗'}")

    print(f"\n{'VERIFY OK ✓' if all_ok else 'VERIFY BAŞARISIZ ✗'}\n")
    return all_ok


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
            print(f"\n{'='*60}")
            print("[APPLY BAŞLIYOR]")
            print(f"{'='*60}")
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

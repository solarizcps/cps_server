# -*- coding: utf-8 -*-
"""
Migration 026 — Personel İK Tabloları
=======================================

Oluşturulan tablolar (CREATE TABLE IF NOT EXISTS — idempotent):
  1. personel_maas_gecmis  : Maaş geçmişi; eski kayıt silinmez, gecerlilik_bit doldurulur
  2. personel_izin         : Yıllık izin hakkı ve kullanım kayıtları
  3. personel_devam        : Günlük devam/devamsızlık kaydı (UNIQUE: personel_pk_id + tarih)
  4. personel_ik_not       : İK görüşme notu, uyarı, performans notu (gizli flag)

Kesinlikle yapılmayan:
  - Mevcut tablolara ALTER/DROP yok.
  - Kullanıcı/rol değişikliği yok.
  - Veri seed edilmez (tablolar boş açılır).
  - ENJ_CORE, Finans, Planlama tabloları dokunulmaz.

Versiyon: 026
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "026"
ACIKLAMA = "Personel IK tablolari: personel_maas_gecmis, personel_izin, personel_devam, personel_ik_not"

TABLOLAR = [
    "personel_maas_gecmis",
    "personel_izin",
    "personel_devam",
    "personel_ik_not",
]


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


DDL = """
-- ─────────────────────────────────────────────
-- 1) personel_maas_gecmis
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS personel_maas_gecmis (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    personel_pk_id      INTEGER NOT NULL,     -- personel_kullanici.id
    tutar               NUMERIC NOT NULL,
    para_birimi         TEXT    NOT NULL DEFAULT 'TL',
    gecerlilik_bas      TEXT    NOT NULL,      -- YYYY-MM-DD; bu maaşın başladığı tarih
    gecerlilik_bit      TEXT,                  -- NULL = hala geçerli (aktif maaş)
    tip                 TEXT    NOT NULL DEFAULT 'maas',
    -- tip: maas | zam | prim_ekstra | duzeltme
    aciklama            TEXT,
    giren_kullanici     TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pmg_personel_bit
    ON personel_maas_gecmis (personel_pk_id, gecerlilik_bit);

CREATE INDEX IF NOT EXISTS idx_pmg_gecerlilik_bas
    ON personel_maas_gecmis (personel_pk_id, gecerlilik_bas);

-- ─────────────────────────────────────────────
-- 2) personel_izin
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS personel_izin (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    personel_pk_id      INTEGER NOT NULL,     -- personel_kullanici.id
    yil                 INTEGER NOT NULL,      -- Hangi yıl izni (2025, 2026 ...)
    hak_gun             REAL    NOT NULL DEFAULT 14,
    kullanilan_gun      REAL    NOT NULL DEFAULT 0,
    izin_tipi           TEXT    NOT NULL DEFAULT 'yillik',
    -- izin_tipi: yillik | ucretsiz | dogum | olum | hastalık | resmi_tatil
    baslangic_tarihi    TEXT,                  -- YYYY-MM-DD
    bitis_tarihi        TEXT,                  -- YYYY-MM-DD
    gun_sayisi          REAL,                  -- hesaplanan gerçek gün
    durum               TEXT    NOT NULL DEFAULT 'taslak',
    -- durum: taslak | onay_bekliyor | onaylandi | reddedildi | iptal
    onaylayan           TEXT,
    onay_tarihi         TEXT,
    notlar              TEXT,
    giren_kullanici     TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pizin_personel_yil
    ON personel_izin (personel_pk_id, yil);

CREATE INDEX IF NOT EXISTS idx_pizin_durum
    ON personel_izin (personel_pk_id, durum);

-- ─────────────────────────────────────────────
-- 3) personel_devam
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS personel_devam (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    personel_pk_id      INTEGER NOT NULL,     -- personel_kullanici.id
    tarih               TEXT    NOT NULL,      -- YYYY-MM-DD
    durum               TEXT    NOT NULL DEFAULT 'geldi',
    -- durum: geldi | gelmedi | izinli | resmi_tatil | yarim_gun | erken_cikis | gec_giris
    giris_saati         TEXT,                  -- HH:MM
    cikis_saati         TEXT,                  -- HH:MM
    calisma_dakika      INTEGER,               -- toplam çalışılan süre (dk)
    kaynak              TEXT    NOT NULL DEFAULT 'manuel',
    -- kaynak: manuel | pdks | ik_giris | toplu_giris
    aciklama            TEXT,
    giren_kullanici     TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (personel_pk_id, tarih)
);

CREATE INDEX IF NOT EXISTS idx_pdevam_personel_tarih
    ON personel_devam (personel_pk_id, tarih);

CREATE INDEX IF NOT EXISTS idx_pdevam_tarih_durum
    ON personel_devam (tarih, durum);

-- ─────────────────────────────────────────────
-- 4) personel_ik_not
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS personel_ik_not (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    personel_pk_id      INTEGER NOT NULL,     -- personel_kullanici.id
    tarih               TEXT    NOT NULL,      -- YYYY-MM-DD
    not_tipi            TEXT    NOT NULL DEFAULT 'genel',
    -- not_tipi: gorusme | uyari | performans | issizlik | istifa | olumlu | genel
    icerik              TEXT    NOT NULL,
    gizli               INTEGER NOT NULL DEFAULT 1,
    -- gizli=1: sadece IK / Yönetim; gizli=0: usta da görebilir
    giren_kullanici     TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pikn_personel_tarih
    ON personel_ik_not (personel_pk_id, tarih);

CREATE INDEX IF NOT EXISTS idx_pikn_gizli
    ON personel_ik_not (personel_pk_id, gizli);
"""


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    for tablo in TABLOLAR:
        mevcut = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
        ).fetchone()
        print(f"\n  [{tablo}]: {'ZATEN VAR — CREATE IF NOT EXISTS geçecek' if mevcut else 'YOK — yeni oluşturulacak'}")

    print(f"\n  Korunan tablolar kontrol:")
    korunan = ["uretim_kayit", "sistem_kullanici", "sistem_rol", "finans_anlasma", "enj_gunluk_rapor"]
    for t in korunan:
        var = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        print(f"    {t}: {'VAR (dokunulmayacak)' if var else 'YOK'}")

    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()
    cur.executescript(DDL)

    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"[APPLY OK] Migration {MIGRATION_VERSION} — 4 IK tablosu oluşturuldu.")


def verify(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    print(f"\n[A] Tablo varlığı:")
    for tablo in TABLOLAR:
        r = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
        ).fetchone()
        print(f"  {'OK' if r else 'EKSIK!'}: {tablo}")

    print(f"\n[B] İndeksler:")
    beklenen_indeksler = [
        "idx_pmg_personel_bit", "idx_pmg_gecerlilik_bas",
        "idx_pizin_personel_yil", "idx_pizin_durum",
        "idx_pdevam_personel_tarih", "idx_pdevam_tarih_durum",
        "idx_pikn_personel_tarih", "idx_pikn_gizli",
    ]
    for idx in beklenen_indeksler:
        r = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx,)
        ).fetchone()
        print(f"  {'OK' if r else 'EKSIK!'}: {idx}")

    print(f"\n[C] UNIQUE kısıtı (personel_devam):")
    r = con.execute("PRAGMA index_list(personel_devam)").fetchall()
    for row in r:
        print(f"  {dict(row)}")

    print(f"\n[D] Korunan tablolar sağlam mı?")
    for t in ["uretim_kayit", "sistem_kullanici", "kullanici_profil", "kullanici_yetkinlik",
              "yetkinlik_master", "usta_personel_iliskisi"]:
        cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {cnt} kayıt — OK")

    print(f"\n[E] schema_migrations kaydı:")
    mig = con.execute(
        "SELECT version, aciklama, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"  {dict(mig) if mig else 'KAYIT YOK!'}")
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

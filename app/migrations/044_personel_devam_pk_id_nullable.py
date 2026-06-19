# -*- coding: utf-8 -*-
"""
Migration 044 — personel_devam.personel_pk_id NOT NULL kaldır
===============================================================

KÖK NEDEN:
  Personel 360 mimarisinde ana kimlik kullanici_profil_id oldu.
  personel_pk_id artık opsiyonel eski köprü (personel_kullanici tablosu).
  Migration 026 personel_pk_id'yi NOT NULL tanımlamıştı.
  Bu yüzden pk_id'si olmayan 116 PDKS kaydı INSERT OR IGNORE ile yazılamadı.

YAPILAN DEĞİŞİKLİK:
  personel_devam.personel_pk_id  INTEGER NOT NULL  →  INTEGER (NULL izin verilir)

YÖNTEM (SQLite sınırlaması):
  SQLite ALTER TABLE ile NOT NULL kaldırılamaz.
  Çözüm: yeni tablo oluştur → veriyi kopyala → eskiyi drop et → rename.

KURAL:
  - Mevcut 1057+ kaynak='pdks' kayıt KESİNLİKLE KORUNUR.
  - Veri silme yok.
  - personel_pk_id'si olan kayıtlar değişmez.
  - Sadece NULL constraint kaldırılır.
  - Tüm diğer kolonlar, indexler ve unique constraint'ler yeniden oluşturulur.

Versiyon: 044
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "044"
ACIKLAMA = "personel_devam.personel_pk_id NOT NULL kaldirildi — P360 nullable pk_id"

DEVAM_INDEX_ADI = "udx_devam_kullanici_profil_tarih"  # 032'den, partial UNIQUE


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def _kolon_notnull(con, tablo, kolon):
    """True ise kolon NOT NULL tanımlı."""
    for r in con.execute(f"PRAGMA table_info({tablo})").fetchall():
        if r["name"] == kolon:
            return bool(r["notnull"])
    return False


def _kayit_say(con, tablo, where=""):
    q = f"SELECT COUNT(*) FROM {tablo}"
    if where:
        q += f" WHERE {where}"
    return con.execute(q).fetchone()[0]


def _index_var_mi(con, index_adi):
    r = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_adi,)
    ).fetchone()
    return r is not None


def dryrun(con):
    print(f"\n{'='*65}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*65}")

    pk_notnull = _kolon_notnull(con, "personel_devam", "personel_pk_id")
    toplam     = _kayit_say(con, "personel_devam")
    pdks_cnt   = _kayit_say(con, "personel_devam", "kaynak='pdks'")
    null_pk    = _kayit_say(con, "personel_devam", "personel_pk_id IS NULL")
    idx_var    = _index_var_mi(con, DEVAM_INDEX_ADI)

    print(f"\n[MEVCUT DURUM]")
    print(f"  personel_pk_id NOT NULL : {pk_notnull}")
    print(f"  personel_devam toplam   : {toplam}")
    print(f"  kaynak='pdks' kayıt     : {pdks_cnt}")
    print(f"  pk_id IS NULL mevcut    : {null_pk}")
    print(f"  partial UNIQUE index    : {idx_var}")

    if not pk_notnull:
        print(f"\n  [BİLGİ] personel_pk_id zaten NULL kabul ediyor. Migration atlanabilir.")
    else:
        print(f"\n[YAPILACAK]")
        print(f"  1. personel_devam_new tablosu oluşturulacak (personel_pk_id INTEGER NULL)")
        print(f"  2. Mevcut {toplam} kayıt kopyalanacak (INSERT INTO ... SELECT *)")
        print(f"  3. personel_devam DROP edilecek")
        print(f"  4. personel_devam_new → personel_devam rename edilecek")
        print(f"  5. Tüm index'ler yeniden oluşturulacak")
        print(f"  6. Partial UNIQUE index ({DEVAM_INDEX_ADI}) yeniden oluşturulacak")
        print(f"\n  [KORUNAN] {pdks_cnt} kaynak='pdks' kaydı değişmeyecek.")
        print(f"  [SONUÇ]  personel_pk_id notnull=0 olacak.")

    mig = con.execute(
        "SELECT version FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n  schema_migrations {MIGRATION_VERSION}: {'KAYITLI — atlanacak' if mig else 'YOK — eklenecek'}")
    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()

    # İdempotent kontrol
    if not _kolon_notnull(con, "personel_devam", "personel_pk_id"):
        print(f"  [SKIP] personel_pk_id zaten NULL kabul ediyor. Migration gerekmez.")
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?,?)",
            (MIGRATION_VERSION, ACIKLAMA)
        )
        con.commit()
        return

    toplam_once = _kayit_say(con, "personel_devam")
    pdks_once   = _kayit_say(con, "personel_devam", "kaynak='pdks'")
    print(f"  [ÖNCE] personel_devam: {toplam_once} kayıt, pdks={pdks_once}")

    # Foreign key kapatılsın (güvenlik)
    cur.execute("PRAGMA foreign_keys = OFF")

    # 1) Yeni tablo — personel_pk_id NULL yapıldı
    cur.execute("DROP TABLE IF EXISTS personel_devam_new")
    cur.execute("""
        CREATE TABLE personel_devam_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            personel_pk_id      INTEGER,             -- NULL izin verildi (P360 nullable)
            kullanici_profil_id INTEGER,
            tarih               TEXT    NOT NULL,
            durum               TEXT    NOT NULL DEFAULT 'geldi',
            giris_saati         TEXT,
            cikis_saati         TEXT,
            calisma_dakika      INTEGER,
            kaynak              TEXT    NOT NULL DEFAULT 'manuel',
            aciklama            TEXT,
            giren_kullanici     TEXT,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (personel_pk_id, tarih)
        )
    """)
    print(f"  [OK] personel_devam_new oluşturuldu")

    # 2) Veriyi kopyala — TÜM kayıtlar, sütun bazlı
    cur.execute("""
        INSERT INTO personel_devam_new
            (id, personel_pk_id, kullanici_profil_id, tarih, durum,
             giris_saati, cikis_saati, calisma_dakika, kaynak,
             aciklama, giren_kullanici, created_at, updated_at)
        SELECT
             id, personel_pk_id, kullanici_profil_id, tarih, durum,
             giris_saati, cikis_saati, calisma_dakika, kaynak,
             aciklama, giren_kullanici, created_at, updated_at
        FROM personel_devam
    """)
    kopyalanan = cur.rowcount
    print(f"  [OK] {kopyalanan} kayıt kopyalandı")

    # 3) Eski tabloyu drop et
    cur.execute("DROP TABLE personel_devam")
    print(f"  [OK] personel_devam (eski) drop edildi")

    # 4) Rename
    cur.execute("ALTER TABLE personel_devam_new RENAME TO personel_devam")
    print(f"  [OK] personel_devam_new → personel_devam rename edildi")

    # 5) Standart indexler (026'dan)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdevam_personel_tarih
        ON personel_devam (personel_pk_id, tarih)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdevam_tarih_durum
        ON personel_devam (tarih, durum)
    """)
    print(f"  [OK] Standart indexler oluşturuldu")

    # 6) Partial UNIQUE index (032'den — kullanici_profil_id + tarih)
    cur.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {DEVAM_INDEX_ADI}
        ON personel_devam(kullanici_profil_id, tarih)
        WHERE kullanici_profil_id IS NOT NULL
    """)
    print(f"  [OK] Partial UNIQUE index {DEVAM_INDEX_ADI} oluşturuldu")

    # 7) kullanici_profil_id indexi de ekle (yeni P360 sorguları için)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdevam_profil_tarih
        ON personel_devam (kullanici_profil_id, tarih)
        WHERE kullanici_profil_id IS NOT NULL
    """)
    print(f"  [OK] idx_pdevam_profil_tarih oluşturuldu")

    # FK'yı geri aç
    cur.execute("PRAGMA foreign_keys = ON")

    # 8) schema_migrations
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?,?)",
        (MIGRATION_VERSION, ACIKLAMA)
    )

    con.commit()

    toplam_sonra = _kayit_say(con, "personel_devam")
    pdks_sonra   = _kayit_say(con, "personel_devam", "kaynak='pdks'")
    pk_notnull   = _kolon_notnull(con, "personel_devam", "personel_pk_id")

    print(f"\n  [SONRA] personel_devam: {toplam_sonra} kayıt, pdks={pdks_sonra}")
    print(f"  [VERIFY] personel_pk_id notnull={pk_notnull} (beklenen: False)")

    if toplam_sonra != toplam_once:
        print(f"  [UYARI!] Kayıt sayısı değişti: {toplam_once} → {toplam_sonra}")
    else:
        print(f"  [OK] Kayıt sayısı korundu: {toplam_sonra}")

    if pdks_sonra != pdks_once:
        print(f"  [UYARI!] PDKS kayıt sayısı değişti: {pdks_once} → {pdks_sonra}")
    else:
        print(f"  [OK] PDKS kayıtları korundu: {pdks_sonra}")

    print(f"\n[APPLY OK] Migration {MIGRATION_VERSION} uygulandı.")


def verify(con):
    print(f"\n{'='*65}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*65}")

    pk_notnull = _kolon_notnull(con, "personel_devam", "personel_pk_id")
    toplam     = _kayit_say(con, "personel_devam")
    pdks_cnt   = _kayit_say(con, "personel_devam", "kaynak='pdks'")
    null_pk    = _kayit_say(con, "personel_devam", "personel_pk_id IS NULL")

    pragma_cols = con.execute("PRAGMA table_info(personel_devam)").fetchall()
    pragma_idx  = con.execute("PRAGMA index_list(personel_devam)").fetchall()

    print(f"\n[A] personel_pk_id NOT NULL = {pk_notnull}  (beklenen: False)")
    print(f"[B] Toplam kayıt            : {toplam}")
    print(f"    kaynak='pdks'           : {pdks_cnt}")
    print(f"    personel_pk_id IS NULL  : {null_pk}")

    print(f"\n[C] PRAGMA table_info(personel_devam):")
    for r in pragma_cols:
        notnull_str = "NOT NULL" if r["notnull"] else "nullable"
        print(f"  {r['cid']:2} {r['name']:25} {r['type']:10} {notnull_str}")

    print(f"\n[D] PRAGMA index_list(personel_devam):")
    for r in pragma_idx:
        cols = con.execute(f"PRAGMA index_info({r['name']})").fetchall()
        col_names = ", ".join(c["name"] for c in cols)
        print(f"  {'UNIQUE' if r['unique'] else 'INDEX ':6} {r['name']} [{col_names}]")

    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[E] schema_migrations: {dict(mig) if mig else 'KAYIT YOK!'}")
    print()


def main():
    mode    = sys.argv[1] if len(sys.argv) > 1 else "--dryrun"
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
            print(f"\n{'='*65}")
            print("[APPLY BAŞLIYOR]")
            print(f"{'='*65}")
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

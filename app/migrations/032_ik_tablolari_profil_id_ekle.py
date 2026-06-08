# -*- coding: utf-8 -*-
"""
Migration 032 — İK Tablolarına kullanici_profil_id Ekleme
===========================================================

Amaç:
  Personel 360 artık tüm şirket personelini (üretim + idari + ofis +
  yönetim) listeliyor. Ancak İK tabloları (maas, izin, devam, ik_not)
  yalnızca personel_kullanici.id üzerinden çalışıyor ve idari profiller
  için kayıt yapılamıyor.

  Bu migration her 4 İK tablosuna `kullanici_profil_id` kolonu ekler.
  Mevcut üretim personeli kayıtları retroaktif olarak doldurulur.
  Sonraki aşama (FAZ2G-15 Kod) route/helper değişikliklerini yapacak.

Tablo değişiklikleri:
  personel_maas_gecmis  → ADD COLUMN kullanici_profil_id INTEGER
  personel_izin         → ADD COLUMN kullanici_profil_id INTEGER
  personel_devam        → ADD COLUMN kullanici_profil_id INTEGER
  personel_ik_not       → ADD COLUMN kullanici_profil_id INTEGER

Retroaktif dolum:
  Her tabloda mevcut satırlar için kullanici_profil_id,
  personel_pk_id → kullanici_profil.kaynak_id eşlemesiyle doldurulur.

Ek index (personel_devam):
  UNIQUE(personel_pk_id, tarih) zaten var — üretim için korunuyor.
  İdari profiller için çakışma olmasın diye ek partial index:
  CREATE UNIQUE INDEX ... ON personel_devam(kullanici_profil_id, tarih)
  WHERE kullanici_profil_id IS NOT NULL;

Korunan:
  - personel_pk_id kolonu silinmez
  - Mevcut kayıtlar değiştirilmez (retroaktif dolum ek kolonu doldurur)
  - Üretim / hedef / telefon / legacy akışı bozulmaz
  - ENJ_CORE, Finans, Planlama, Hedef tabloları: dokunulmaz

Idempotent:
  - ALTER TABLE: sütun varlığı PRAGMA table_info ile kontrol edilir
  - Retroaktif UPDATE: WHERE kullanici_profil_id IS NULL
  - Index: CREATE UNIQUE INDEX IF NOT EXISTS
  - schema_migrations: INSERT OR IGNORE

Versiyon: 032
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "032"
ACIKLAMA = "ik tablolarina kullanici_profil_id kolonu ekle (hibrit kopru faz1)"

IK_TABLOLARI = [
    "personel_maas_gecmis",
    "personel_izin",
    "personel_devam",
    "personel_ik_not",
]

DEVAM_INDEX_ADI = "udx_devam_kullanici_profil_tarih"


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def _kolon_var_mi(con, tablo, kolon):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({tablo})")]
    return kolon in cols


def _tablo_var_mi(con, tablo):
    r = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def _index_var_mi(con, index_adi):
    r = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_adi,)
    ).fetchone()
    return r is not None


def _retroaktif_sayim(con, tablo):
    """Doldurulacak (pk_id var, profil_id NULL) satır sayısı."""
    if not _tablo_var_mi(con, tablo) or not _kolon_var_mi(con, tablo, "kullanici_profil_id"):
        return 0, 0
    dolacak = con.execute(f"""
        SELECT COUNT(*) FROM {tablo} t
        JOIN kullanici_profil kp
          ON kp.kaynak = 'personel_kullanici' AND kp.kaynak_id = t.personel_pk_id
        WHERE t.kullanici_profil_id IS NULL
    """).fetchone()[0]
    toplam = con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
    return dolacak, toplam


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    print(f"\n[1] ALTER TABLE — kullanici_profil_id kolonu:")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            print(f"  !! {tablo:30}: TABLO YOK — atlanacak")
            continue
        var = _kolon_var_mi(con, tablo, "kullanici_profil_id")
        print(f"  {'OK (mevcut)' if var else 'EKLENECEK':15} {tablo}")

    print(f"\n[2] Retroaktif dolum (personel_pk_id → kullanici_profil_id):")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            continue
        var = _kolon_var_mi(con, tablo, "kullanici_profil_id")
        if not var:
            # Kolon yok — dolum ALTER sonrası yapılacak
            cnt = con.execute(f"""
                SELECT COUNT(*) FROM {tablo} t
                JOIN kullanici_profil kp
                  ON kp.kaynak='personel_kullanici' AND kp.kaynak_id=t.personel_pk_id
            """).fetchone()[0]
            toplam = con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
            print(f"  {tablo:30}: {cnt}/{toplam} satır doldurulacak (kolon ALTER sonrası)")
        else:
            dolacak, toplam = _retroaktif_sayim(con, tablo)
            print(f"  {tablo:30}: {dolacak}/{toplam} satır doldurulacak")

    print(f"\n[3] personel_devam UNIQUE index ({DEVAM_INDEX_ADI}):")
    idx_var = _index_var_mi(con, DEVAM_INDEX_ADI)
    print(f"  {'MEVCUT — atlanacak' if idx_var else 'OLUŞTURULACAK'}")
    if not idx_var:
        print(f"  CREATE UNIQUE INDEX {DEVAM_INDEX_ADI}")
        print(f"    ON personel_devam(kullanici_profil_id, tarih)")
        print(f"    WHERE kullanici_profil_id IS NOT NULL;")

    print(f"\n[4] Mevcut İK veri özeti:")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            continue
        cnt = con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
        pk_dist = con.execute(f"""
            SELECT t.personel_pk_id, pk.kullanici_adi, COUNT(*) as n
            FROM {tablo} t
            LEFT JOIN personel_kullanici pk ON pk.id = t.personel_pk_id
            GROUP BY t.personel_pk_id
        """).fetchall()
        print(f"  {tablo:30}: {cnt} satır, {len(pk_dist)} farklı personel")
        for r in pk_dist:
            print(f"    pk_id={r[0]:3} {(r[1] or '?'):25} {r[2]} kayıt")

    mig = con.execute(
        "SELECT version FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[5] schema_migrations {MIGRATION_VERSION}: {'KAYITLI — atlanacak' if mig else 'YOK — eklenecek'}")
    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()

    # 1) Her tabloya kullanici_profil_id ekle (idempotent)
    print(f"\n[APPLY] ALTER TABLE adımları:")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            print(f"  [SKIP] {tablo} — tablo yok")
            continue
        if _kolon_var_mi(con, tablo, "kullanici_profil_id"):
            print(f"  [SKIP] {tablo} — kullanici_profil_id zaten var")
        else:
            cur.execute(f"ALTER TABLE {tablo} ADD COLUMN kullanici_profil_id INTEGER")
            print(f"  [ALTER] {tablo} — kullanici_profil_id eklendi")

    # 2) Retroaktif dolum: mevcut pk_id'lerden kullanici_profil_id bul
    print(f"\n[APPLY] Retroaktif dolum:")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            continue
        result = cur.execute(f"""
            UPDATE {tablo}
            SET kullanici_profil_id = (
                SELECT kp.id
                FROM kullanici_profil kp
                WHERE kp.kaynak = 'personel_kullanici'
                  AND kp.kaynak_id = {tablo}.personel_pk_id
                LIMIT 1
            )
            WHERE kullanici_profil_id IS NULL
              AND personel_pk_id IS NOT NULL
        """)
        print(f"  [UPDATE] {tablo}: {result.rowcount} satır güncellendi")

    # 3) personel_devam partial unique index (idari profiller için çakışma önleme)
    print(f"\n[APPLY] personel_devam index:")
    if _index_var_mi(con, DEVAM_INDEX_ADI):
        print(f"  [SKIP] {DEVAM_INDEX_ADI} zaten var")
    else:
        cur.execute(f"""
            CREATE UNIQUE INDEX {DEVAM_INDEX_ADI}
            ON personel_devam(kullanici_profil_id, tarih)
            WHERE kullanici_profil_id IS NOT NULL
        """)
        print(f"  [INDEX] {DEVAM_INDEX_ADI} oluşturuldu")

    # 4) schema_migrations kaydı
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (MIGRATION_VERSION, ACIKLAMA))

    con.commit()
    print(f"\n[APPLY OK] Migration {MIGRATION_VERSION} uygulandı.")


def verify(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — VERIFY")
    print(f"{'='*60}")

    print(f"\n[A] Kolon varlığı:")
    all_ok = True
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            print(f"  [SKIP] {tablo} — tablo yok")
            continue
        var = _kolon_var_mi(con, tablo, "kullanici_profil_id")
        print(f"  {'OK ✓' if var else 'EKSIK ✗':8} {tablo}.kullanici_profil_id")
        if not var:
            all_ok = False

    print(f"\n[B] Retroaktif dolum durumu:")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            continue
        toplam = con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
        if toplam == 0:
            print(f"  {tablo:30}: 0 satır (boş tablo)")
            continue
        null_profil = con.execute(
            f"SELECT COUNT(*) FROM {tablo} WHERE kullanici_profil_id IS NULL AND personel_pk_id IS NOT NULL"
        ).fetchone()[0]
        dolu = con.execute(
            f"SELECT COUNT(*) FROM {tablo} WHERE kullanici_profil_id IS NOT NULL"
        ).fetchone()[0]
        print(f"  {tablo:30}: {dolu}/{toplam} dolu, {null_profil} eksik (pk_id var ama profil_id NULL)")
        if null_profil > 0:
            # Neden NULL kaldı? Profil seed edilmemiş pk_id'ler var mı?
            orphans = con.execute(f"""
                SELECT DISTINCT t.personel_pk_id FROM {tablo} t
                WHERE t.kullanici_profil_id IS NULL AND t.personel_pk_id IS NOT NULL
            """).fetchall()
            for o in orphans:
                kp = con.execute(
                    "SELECT id FROM kullanici_profil WHERE kaynak='personel_kullanici' AND kaynak_id=?",
                    (o[0],)
                ).fetchone()
                print(f"    pk_id={o[0]} → kp={'id='+str(kp['id']) if kp else 'PROFIL YOK'}")

    print(f"\n[C] personel_devam index:")
    idx_var = _index_var_mi(con, DEVAM_INDEX_ADI)
    print(f"  {'OK ✓' if idx_var else 'EKSIK ✗'} {DEVAM_INDEX_ADI}")

    print(f"\n[D] Özet kontrol (örnek profil — Lanchyn pk_id=15):")
    for tablo in IK_TABLOLARI:
        if not _tablo_var_mi(con, tablo):
            continue
        r = con.execute(
            f"SELECT personel_pk_id, kullanici_profil_id FROM {tablo} WHERE personel_pk_id=15 LIMIT 1"
        ).fetchone()
        if r:
            print(f"  {tablo:30}: pk_id={r[0]} profil_id={r[1]} {'✓' if r[1] else '✗ profil_id NULL'}")
        else:
            print(f"  {tablo:30}: Lanchyn kaydı yok (normal olabilir)")

    print(f"\n[E] Backward compatibility — mevcut sorgular hâlâ çalışıyor mu:")
    try:
        r = con.execute("SELECT COUNT(*) FROM personel_maas_gecmis WHERE personel_pk_id=15").fetchone()[0]
        print(f"  personel_maas_gecmis WHERE personel_pk_id=15: {r} satır ✓")
        r2 = con.execute("SELECT COUNT(*) FROM personel_ik_not WHERE personel_pk_id=12").fetchone()[0]
        print(f"  personel_ik_not WHERE personel_pk_id=12: {r2} satır ✓")
    except Exception as e:
        print(f"  !! Sorgu hatası: {e} ✗")

    mig = con.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n[F] schema_migrations: {dict(mig) if mig else 'KAYIT YOK!'}")
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

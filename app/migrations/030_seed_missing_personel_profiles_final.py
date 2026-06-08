# -*- coding: utf-8 -*-
"""
Migration 030 — Seed Missing Personel 360 Profiles (Final)
===========================================================

Amaç:
  Personel 360 kuralı: Her aktif personel_kullanici kaydının
  mutlaka bir kullanici_profil karşılığı olmalı.

  Bu migration, kullanici_profil kaydı eksik olan tüm aktif
  personel_kullanici kayıtları için profil oluşturur.

  Migration 027'nin tamamlanmamış kaldığı canlı ortamlar için
  güvenli bir "final" geçişidir.

Bağlantı mantığı:
  kullanici_profil.kaynak     = 'personel_kullanici'
  kullanici_profil.kaynak_id  = personel_kullanici.id

Oluşturulan alanlar:
  gercek_ad   = COALESCE(pk.AdSoyad, pk.kullanici_adi)
  kullanici_adi = pk.kullanici_adi
  profil_tipi = 'SAHA_PERSONEL'
  aktif       = pk.aktif
  kaynak      = 'personel_kullanici'
  kaynak_id   = pk.id

Korunan:
  - Var olan kullanici_profil kayıtları: değiştirilmez
  - Finans, Enjeksiyon, Planlama, Hedef: dokunulmaz
  - sistem_kullanici, usta_kullanici: dokunulmaz
  - uretim_kayit, hedef tabloları: dokunulmaz

Idempotent:
  INSERT OR IGNORE (tekrar çalıştırılabilir, mevcut kaydı bozmaz)
  kullanici_profil (kaynak, kaynak_id) UNIQUE constraint korumalı
  (yoksa WHERE EXISTS kontrolü ile güvence altına alınır)

Versiyon: 030
"""

import sqlite3
import os
import sys

MIGRATION_VERSION = "030"
ACIKLAMA = "seed missing kullanici_profil for active personel_kullanici (final)"


def get_db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def _find_missing(con):
    """Profili olmayan aktif personel_kullanici kayıtlarını bul."""
    return con.execute("""
        SELECT pk.id,
               COALESCE(pk.AdSoyad, pk.kullanici_adi)  AS gercek_ad,
               pk.kullanici_adi,
               pk.aktif,
               pk.legacy_id
        FROM personel_kullanici pk
        LEFT JOIN kullanici_profil kp
               ON kp.kaynak = 'personel_kullanici' AND kp.kaynak_id = pk.id
        WHERE pk.aktif = 1
          AND kp.id IS NULL
        ORDER BY pk.id
    """).fetchall()


def dryrun(con):
    print(f"\n{'='*60}")
    print(f"MIGRATION {MIGRATION_VERSION} — DRY-RUN")
    print(f"{'='*60}")

    # Toplam durum
    total_pk = con.execute("SELECT COUNT(*) FROM personel_kullanici WHERE aktif=1").fetchone()[0]
    total_kp = con.execute(
        "SELECT COUNT(*) FROM kullanici_profil WHERE kaynak='personel_kullanici'"
    ).fetchone()[0]
    print(f"\n  Aktif personel_kullanici : {total_pk}")
    print(f"  Mevcut kullanici_profil  : {total_kp}")

    eksik = _find_missing(con)
    print(f"  Eksik profil sayısı      : {len(eksik)}")

    if eksik:
        print(f"\n  Eklenecek profiller:")
        for r in eksik:
            ad = r['gercek_ad'] or '(ad yok)'
            print(f"    pk.id={r['id']:3}  legacy_id={r['legacy_id']}  ad='{ad}'  kadi={r['kullanici_adi']}")
    else:
        print(f"\n  [OK] Tüm aktif personellerin profili mevcut — işlem gerekmez.")

    mig = con.execute(
        "SELECT version FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    print(f"\n  schema_migrations {MIGRATION_VERSION}: {'KAYITLI' if mig else 'YOK — eklenecek'}")
    print(f"\n[DRY-RUN TAMAMLANDI] DB'ye hiçbir şey yazılmadı.\n")


def apply(con):
    cur = con.cursor()
    eksik = _find_missing(con)

    if not eksik:
        print(f"  [OK] Tüm profiller zaten mevcut. Seed işlemi gerekmez.")
    else:
        print(f"  {len(eksik)} eksik profil seed ediliyor...")
        for r in eksik:
            gercek_ad = (r['gercek_ad'] or '').strip()
            if not gercek_ad:
                print(f"    [SKIP] pk.id={r['id']} — ad/soyad boş, atlandı")
                continue

            # Çift güvence: önce mevcut kontrol, sonra INSERT OR IGNORE
            mevcut = con.execute(
                "SELECT id FROM kullanici_profil WHERE kaynak='personel_kullanici' AND kaynak_id=?",
                (r['id'],)
            ).fetchone()
            if mevcut:
                print(f"    [SKIP] pk.id={r['id']} '{gercek_ad}' — profil mevcut (id={mevcut['id']})")
                continue

            cur.execute("""
                INSERT INTO kullanici_profil
                    (kaynak, kaynak_id, gercek_ad, kullanici_adi, profil_tipi, aktif)
                VALUES (?, ?, ?, ?, 'SAHA_PERSONEL', ?)
            """, ('personel_kullanici', r['id'], gercek_ad, r['kullanici_adi'], r['aktif']))
            print(f"    [SEED] pk.id={r['id']:3}  ad='{gercek_ad}'")

    # schema_migrations kaydı
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

    total_pk = con.execute("SELECT COUNT(*) FROM personel_kullanici WHERE aktif=1").fetchone()[0]
    total_kp = con.execute(
        "SELECT COUNT(*) FROM kullanici_profil WHERE kaynak='personel_kullanici' AND aktif=1"
    ).fetchone()[0]
    eksik = _find_missing(con)

    print(f"\n[A] Aktif personel_kullanici : {total_pk}")
    print(f"[B] Mevcut kullanici_profil  : {total_kp}")
    print(f"[C] Eksik profil sayısı      : {len(eksik)}")

    if eksik:
        print(f"\n  [UYARI] Hâlâ eksik profiller var:")
        for r in eksik:
            print(f"    pk.id={r['id']}  ad={r['gercek_ad']}")
    else:
        print(f"\n  [OK] Tüm aktif personellerin profili mevcut.")

    # Birkaç örnek kontrol
    print(f"\n[D] Örnek profil kontrolü:")
    ornekler = [
        ('ilham', 'İlham'),
        ('sham', 'Sham'),
        ('malika', 'Malika'),
        ('mustafa', 'Mustafa'),
    ]
    for arama, etiket in ornekler:
        r = con.execute("""
            SELECT kp.id, kp.gercek_ad, kp.profil_tipi
            FROM personel_kullanici pk
            JOIN kullanici_profil kp
                ON kp.kaynak='personel_kullanici' AND kp.kaynak_id=pk.id
            WHERE LOWER(pk.kullanici_adi) LIKE ?
               OR LOWER(pk.AdSoyad) LIKE ?
            LIMIT 1
        """, (f'%{arama}%', f'%{arama}%')).fetchone()
        if r:
            print(f"  {etiket:10} → kp.id={r['id']} '{r['gercek_ad']}' profil_tipi={r['profil_tipi']} ✓")
        else:
            print(f"  {etiket:10} → BULUNAMADI ✗")

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

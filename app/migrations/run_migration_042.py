# -*- coding: utf-8 -*-
"""
CPS - MIGRATION 042 RUNNER
===========================
FAZ 1C: Uretim Emir Ilerleme - Ara Kayit Altyapisi

Yapilan:
  1. uretim_kayit tablosuna 9 yeni kolon eklenir (zaten varsa SKIP)
  2. 042_uretim_emir_ilerleme.sql calistirilir:
       - uretim_kayit_personel tablosu
       - korgun_personel_eslestirme tablosu
  3. schema_migrations'a '042' kaydi eklenir

Yeni kolonlar (uretim_kayit):
  hat_adi              TEXT              -- Monta 1, Monta 2, Kesim, Temizleme...
  baslangic_saat       TEXT              -- proses baslangic saati (HH:MM veya ISO)
  bitis_saat           TEXT              -- proses bitis saati
  korgun_yazildi       INTEGER DEFAULT 0 -- 0=sadece CPS, 1=Korgun aktarildi
  korgun_hata          TEXT              -- aktarim hatasi mesaji
  korgun_emir_no       TEXT              -- Korgun EmirNo
  korgun_proses_kodu   TEXT              -- 02/26/28/30/35
  korgun_fis_no        TEXT              -- siparis FisNo
  korgun_fis_harinx    TEXT              -- Siparis_Har.SipHarinx

Geri uyumluluk:
  - Tablo yoksa hata verir (uretim_kayit her zaman var olmali)
  - Kolon varsa ALTER TABLE SKIP edilir
  - Mevcut veri korunur (yazma yok)
  - Idempotent: schema_migrations'da '042' varsa tum adimlar SKIP

Kullanim:
    cd C:\\Solariz_CPS_SERVER\\app
    python migrations\\run_migration_042.py
"""
import sys
import os
import sqlite3

# Config import
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)
try:
    from config import Config
except ImportError as e:
    print(f"[HATA] config.py import edilemedi: {e}")
    sys.exit(1)

VERSION = '042'
MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_FILE = os.path.join(MIGRATIONS_DIR, '042_uretim_emir_ilerleme.sql')

# uretim_kayit'e eklenecek kolonlar: (isim, tanim)
YENI_KOLONLAR = [
    ('hat_adi',            'TEXT'),
    ('baslangic_saat',     'TEXT'),
    ('bitis_saat',         'TEXT'),
    ('korgun_yazildi',     'INTEGER DEFAULT 0'),
    ('korgun_hata',        'TEXT'),
    ('korgun_emir_no',     'TEXT'),
    ('korgun_proses_kodu', 'TEXT'),
    ('korgun_fis_no',      'TEXT'),
    ('korgun_fis_harinx',  'TEXT'),
]


def _kolon_var_mi(conn, tablo, kolon):
    rows = conn.execute(f'PRAGMA table_info({tablo})').fetchall()
    return any(r[1] == kolon for r in rows)


def _tablo_var_mi(conn, tablo):
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def _is_applied(conn, version):
    r = conn.execute(
        "SELECT version, uygulama_zamani FROM schema_migrations WHERE version=?",
        (version,)
    ).fetchone()
    return r


def run():
    db_path = Config.MOCK_DB_PATH
    print(f"[INFO]  Migration runner: {VERSION}")
    print(f"[INFO]  DB: {db_path}")
    print(f"[INFO]  DB var mi: {os.path.exists(db_path)}")
    print()

    if not os.path.exists(db_path):
        print("[HATA]  DB dosyasi bulunamadi!")
        return 1

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        # schema_migrations tablosu garantisi
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version         TEXT PRIMARY KEY,
                uygulama_zamani TEXT DEFAULT (datetime('now', 'localtime')),
                aciklama        TEXT
            )
        """)
        conn.commit()

        # Idempotent kontrol
        applied = _is_applied(conn, VERSION)
        if applied:
            print(f"[SKIP]  Version {VERSION} zaten uygulanmis: {applied[1]}")
            return 0

        # --- ADIM 1: uretim_kayit kolon ekleme ---
        print("[INFO]  ADIM 1: uretim_kayit kolon ekleme")
        if not _tablo_var_mi(conn, 'uretim_kayit'):
            print("[HATA]  uretim_kayit tablosu bulunamadi!")
            return 1

        eklenen = []
        atlanan = []
        for kolon_adi, kolon_tanim in YENI_KOLONLAR:
            if _kolon_var_mi(conn, 'uretim_kayit', kolon_adi):
                atlanan.append(kolon_adi)
                print(f"  [SKIP]   {kolon_adi} zaten var")
            else:
                conn.execute(f"ALTER TABLE uretim_kayit ADD COLUMN {kolon_adi} {kolon_tanim}")
                conn.commit()
                eklenen.append(kolon_adi)
                print(f"  [OK]     {kolon_adi} eklendi")

        print(f"  Eklenen: {len(eklenen)}  Atlanan: {len(atlanan)}")
        print()

        # --- ADIM 2: SQL dosyasi (yeni tablolar + migration kaydi) ---
        print(f"[INFO]  ADIM 2: {os.path.basename(SQL_FILE)}")
        if not os.path.exists(SQL_FILE):
            print("[HATA]  SQL dosyasi bulunamadi!")
            return 1

        with open(SQL_FILE, 'r', encoding='utf-8') as f:
            sql = f.read()

        try:
            conn.executescript(sql)
            conn.commit()
            print("[OK]    SQL dosyasi uygulandi")
        except Exception as e:
            conn.rollback()
            print(f"[HATA]  SQL hatasi: {e}")
            return 1

        # --- Dogrulama ---
        print()
        print("[INFO]  Dogrulama:")

        check = _is_applied(conn, VERSION)
        if check:
            print(f"  [OK]  schema_migrations: {check[0]}  {check[1]}")
        else:
            print("  [UYARI] schema_migrations kaydi dusmedi!")

        # uretim_kayit yeni kolonlari
        for kolon_adi, _ in YENI_KOLONLAR:
            durum = "OK" if _kolon_var_mi(conn, 'uretim_kayit', kolon_adi) else "EKSIK"
            print(f"  [{durum}]  uretim_kayit.{kolon_adi}")

        # Yeni tablolar
        for tbl in ['uretim_kayit_personel', 'korgun_personel_eslestirme']:
            durum = "OK" if _tablo_var_mi(conn, tbl) else "EKSIK"
            cnt = conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0] if _tablo_var_mi(conn, tbl) else 0
            print(f"  [{durum}]  {tbl}  ({cnt} satir)")

        # Mevcut veri korunmus mu?
        cnt_uk = conn.execute('SELECT COUNT(*) FROM uretim_kayit').fetchone()[0]
        print(f"  [OK]  uretim_kayit satir sayisi: {cnt_uk} (korunmali)")

        print()
        print(f"[OK]    Migration {VERSION} basariyla tamamlandi.")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run())

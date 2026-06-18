# -*- coding: utf-8 -*-
"""
CPS - MIGRATION 043 RUNNER
===========================
İK PDKS FAZ-2B: kullanici_profil PDKS eşleştirme alanları

Yapılan:
  kullanici_profil tablosuna 4 yeni kolon + 2 index eklenir.
  Kolon zaten varsa SKIP edilir (idempotent).

Yeni kolonlar:
  pdks_personel_id    INTEGER NULL  — Azper PDKS personel.id
  pdks_sicilno        TEXT NULL     — Azper PDKS personel.sicilno (TC kimlik)
  pdks_eslesme_durumu TEXT NULL     — ESLESMIS / AD_SOYAD_ADAY / MANUEL
  pdks_eslesme_tarihi TEXT NULL     — ISO tarih string

Kullanım:
    cd C:\\Solariz_CPS_SERVER\\app
    python migrations\\run_migration_043.py
"""
import sys
import os
import sqlite3

_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)
try:
    from config import Config
except ImportError as e:
    print(f"[HATA] config.py import edilemedi: {e}")
    sys.exit(1)

VERSION = '043'

YENI_KOLONLAR = [
    ('pdks_personel_id',    'INTEGER NULL'),
    ('pdks_sicilno',        'TEXT NULL'),
    ('pdks_eslesme_durumu', 'TEXT NULL'),
    ('pdks_eslesme_tarihi', 'TEXT NULL'),
]


def _kolon_var_mi(conn, tablo, kolon):
    rows = conn.execute(f'PRAGMA table_info({tablo})').fetchall()
    return any(r[1] == kolon for r in rows)


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version         TEXT PRIMARY KEY,
                uygulama_zamani TEXT DEFAULT (datetime('now', 'localtime')),
                aciklama        TEXT
            )
        """)
        conn.commit()

        applied = _is_applied(conn, VERSION)
        if applied:
            print(f"[SKIP]  Version {VERSION} zaten uygulanmis: {applied[1]}")
            return 0

        # ADIM 1: Kolon ekleme
        print("[INFO]  ADIM 1: kullanici_profil kolon ekleme")
        eklenen, atlanan = [], []
        for kolon_adi, kolon_tanim in YENI_KOLONLAR:
            if _kolon_var_mi(conn, 'kullanici_profil', kolon_adi):
                atlanan.append(kolon_adi)
                print(f"  [SKIP]  {kolon_adi} zaten var")
            else:
                conn.execute(
                    f"ALTER TABLE kullanici_profil ADD COLUMN {kolon_adi} {kolon_tanim}"
                )
                conn.commit()
                eklenen.append(kolon_adi)
                print(f"  [OK]    {kolon_adi} eklendi")
        print(f"  Eklenen: {len(eklenen)}  Atlanan: {len(atlanan)}")
        print()

        # ADIM 2: Index'ler
        print("[INFO]  ADIM 2: index ekleme")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_kullanici_profil_pdks_personel_id
            ON kullanici_profil (pdks_personel_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_kullanici_profil_pdks_sicilno
            ON kullanici_profil (pdks_sicilno)
        """)
        conn.commit()
        print("  [OK]    idx_kullanici_profil_pdks_personel_id")
        print("  [OK]    idx_kullanici_profil_pdks_sicilno")
        print()

        # ADIM 3: schema_migrations kaydı
        print("[INFO]  ADIM 3: schema_migrations kaydi")
        conn.execute(
            "INSERT INTO schema_migrations (version, aciklama) VALUES (?, ?)",
            (VERSION, 'kullanici_profil PDKS eslestirme alanlari + index')
        )
        conn.commit()

        # Doğrulama
        print()
        print("[INFO]  Dogrulama:")
        check = _is_applied(conn, VERSION)
        if check:
            print(f"  [OK]  schema_migrations: {check[0]}  {check[1]}")
        else:
            print("  [UYARI] schema_migrations kaydi dusmedi!")

        for kolon_adi, _ in YENI_KOLONLAR:
            durum = "OK" if _kolon_var_mi(conn, 'kullanici_profil', kolon_adi) else "EKSIK"
            print(f"  [{durum}]  kullanici_profil.{kolon_adi}")

        cnt = conn.execute('SELECT COUNT(*) FROM kullanici_profil').fetchone()[0]
        print(f"  [OK]  kullanici_profil satir sayisi: {cnt} (korunmali)")

        print()
        print(f"[OK]    Migration {VERSION} basariyla tamamlandi.")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(run())

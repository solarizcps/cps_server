# -*- coding: utf-8 -*-
"""
CPS DEV - Migration Runner
==========================

Generic migration uygulayici. Hardcoded DB path YOK, Config.MOCK_DB_PATH
uzerinden baglantiyi alir.

Idempotent: schema_migrations tablosunda version varsa atlanir.
Transaction: Hata olursa otomatik ROLLBACK.

Kullanim:
    cd C:\\cps_dev
    python migrations\\run_migration.py 002_tasks.sql

Cikti:
    [INFO]  ... bilgi mesajlari
    [SKIP]  zaten uygulanmis
    [OK]    basarili
    [HATA]  hata + rollback
"""

import os
import sys
import sqlite3
import re

# Config'i import et (Config.MOCK_DB_PATH icin)
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)
try:
    from config import Config
except ImportError as e:
    print(f"[HATA] config.py import edilemedi: {e}")
    sys.exit(1)


# ============================================================
# MIGRATIONS KLASORU + DOSYA ADI
# ============================================================
MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_sql(filename):
    """Migration SQL dosyasini oku."""
    path = os.path.join(MIGRATIONS_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Migration dosyasi yok: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read(), path


def _extract_version(filename):
    """
    Dosya adindan version'i cikar:
        '002_tasks.sql' -> '002'
        '003_xxx.sql'   -> '003'
    """
    m = re.match(r"^(\d+)_", filename)
    if not m:
        raise ValueError(f"Dosya adi 'NNN_xxx.sql' formatinda olmali: {filename}")
    return m.group(1)


def _ensure_schema_migrations(conn):
    """schema_migrations tablosunu garanti et (yoksa olustur)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version           TEXT PRIMARY KEY,
            uygulama_zamani   TEXT DEFAULT (datetime('now', 'localtime')),
            aciklama          TEXT
        )
    """)
    conn.commit()


def _is_applied(conn, version):
    """Bu version zaten uygulanmis mi?"""
    r = conn.execute(
        "SELECT version, uygulama_zamani, aciklama FROM schema_migrations WHERE version=?",
        (version,)
    ).fetchone()
    return r


def run(filename):
    """Migration dosyasini uygula."""
    db_path = Config.MOCK_DB_PATH

    print(f"[INFO]  Migration:  {filename}")
    print(f"[INFO]  DB:         {db_path}")
    print(f"[INFO]  DB var mi:  {os.path.exists(db_path)}")
    if os.path.exists(db_path):
        print(f"[INFO]  DB boyutu:  {os.path.getsize(db_path)} byte")

    # SQL'i oku
    sql, sql_path = _read_sql(filename)
    version = _extract_version(filename)
    print(f"[INFO]  Version:    {version}")
    print(f"[INFO]  SQL dosyasi: {sql_path} ({len(sql)} karakter)")
    print()

    # Baglan
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # schema_migrations'i garanti et
        _ensure_schema_migrations(conn)

        # Idempotent kontrol
        applied = _is_applied(conn, version)
        if applied:
            print(f"[SKIP]  Version {version} zaten uygulanmis:")
            print(f"        Tarih:    {applied[1]}")
            print(f"        Aciklama: {applied[2]}")
            print()
            print("[INFO]  Migration ATLANDI. DB degismedi.")
            return 0

        # Uygula (transaction icinde)
        print(f"[INFO]  Version {version} uygulaniyor...")
        try:
            conn.executescript(sql)
            conn.commit()
            print(f"[OK]    Migration basariyla uygulandi.")
        except Exception as e:
            conn.rollback()
            print(f"[HATA]  SQL hatasi: {e}")
            print(f"[INFO]  Transaction ROLLBACK yapildi.")
            return 1

        # Dogrulama: schema_migrations'a kayit dustu mu?
        check = _is_applied(conn, version)
        if check:
            print(f"[OK]    schema_migrations'a kayit eklendi:")
            print(f"        {check[0]}  {check[1]}")
        else:
            print(f"[UYARI] schema_migrations'a kayit DUSMEDI (SQL'de INSERT eksik?)")
            return 2

        return 0

    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Kullanim: python run_migration.py <SQL_DOSYA_ADI>")
        print("Ornek:    python run_migration.py 002_tasks.sql")
        return 1

    filename = sys.argv[1]
    try:
        return run(filename)
    except Exception as e:
        print(f"[HATA]  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

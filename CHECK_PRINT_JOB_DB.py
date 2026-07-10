# -*- coding: utf-8 -*-
"""
NexGen Print Job — DB Tanı Scripti
===================================
Çalıştır:
    python CHECK_PRINT_JOB_DB.py

Kontrol eder:
  1. DB dosyası var mı ve konumu
  2. schema_migrations içinde 093 kayıtlı mı
  3. sqlite_master içinde nexgen_print_job tablosu var mı
  4. Tablo varsa PRAGMA table_info
  5. Tablo varsa PRAGMA index_list
  6. Mevcut satır sayısı
"""
import sqlite3
import os

# ── Aynı DB_PATH hesabı (nexgen_db_repair.py ile aynı) ─────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(_HERE, 'app', 'mock_data.db'))

print("=" * 60)
print("NexGen Print Job DB Tanı")
print("=" * 60)
print(f"DB yolu : {DB_PATH}")
print(f"Var mı  : {os.path.exists(DB_PATH)}")
if not os.path.exists(DB_PATH):
    print("HATA: DB bulunamadı!")
    exit(1)
print(f"Boyut   : {os.path.getsize(DB_PATH):,} bytes")
print()

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# 1. schema_migrations 093
print("── 1. schema_migrations ───────────────────────────────")
try:
    row = cur.execute(
        "SELECT version, aciklama FROM schema_migrations WHERE version = '093'"
    ).fetchone()
    if row:
        print(f"  093 KAYITLI : {row[1]}")
    else:
        print("  093 YOK — migration hiç çalışmamış.")
except Exception as e:
    print(f"  HATA: {e}")
print()

# 2. sqlite_master tablo kontrolü
print("── 2. sqlite_master — nexgen_print_job ────────────────")
try:
    tablo = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone()
    if tablo:
        print("  nexgen_print_job TABLOSU VAR ✓")
    else:
        print("  nexgen_print_job TABLOSU YOK ✗")
except Exception as e:
    print(f"  HATA: {e}")
print()

# 3. PRAGMA table_info
print("── 3. PRAGMA table_info(nexgen_print_job) ─────────────")
try:
    kolonlar = cur.execute("PRAGMA table_info(nexgen_print_job)").fetchall()
    if kolonlar:
        for c in kolonlar:
            notnull = "NOT NULL" if c[3] else "NULL ok"
            default = f"DEFAULT {c[4]}" if c[4] else ""
            print(f"  [{c[0]}] {c[1]:30s} {c[2]:20s} {notnull:10s} {default}")
    else:
        print("  (tablo yok veya kolon yok)")
except Exception as e:
    print(f"  HATA: {e}")
print()

# 4. PRAGMA index_list
print("── 4. PRAGMA index_list(nexgen_print_job) ─────────────")
try:
    indexler = cur.execute("PRAGMA index_list(nexgen_print_job)").fetchall()
    if indexler:
        for idx in indexler:
            print(f"  {idx[1]}")
    else:
        print("  (index yok)")
except Exception as e:
    print(f"  HATA: {e}")
print()

# 5. Satır sayısı
print("── 5. Mevcut print job kayıt sayısı ────────────────────")
try:
    n = cur.execute("SELECT COUNT(*) FROM nexgen_print_job").fetchone()[0]
    print(f"  Toplam kayıt: {n}")
except Exception as e:
    print(f"  HATA (tablo yok olabilir): {e}")
print()

# 6. Sonuç
print("── 6. Sonuç ────────────────────────────────────────────")
try:
    _093_var = cur.execute(
        "SELECT version FROM schema_migrations WHERE version='093'"
    ).fetchone() is not None
    _tablo_var = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone() is not None

    if _093_var and _tablo_var:
        print("  ✓ Her şey doğru — migration kayıtlı VE tablo mevcut.")
        print("  ✓ DB Repair yeniden çalıştırılabilir, sorun yok.")
    elif _093_var and not _tablo_var:
        print("  ✗ SCHEMA DRIFT tespit edildi!")
        print("    schema_migrations: 093 KAYITLI")
        print("    nexgen_print_job : TABLO YOK")
        print()
        print("  Çözüm: python app/tools/nexgen_db_repair.py")
        print("  (Yeni drift-recovery mantığı 093 kaydını siler ve yeniden oluşturur)")
    elif not _093_var and not _tablo_var:
        print("  → Migration hiç çalışmamış.")
        print("  Çözüm: python app/tools/nexgen_db_repair.py")
    else:
        print("  → Tablo var ama schema_migrations kaydı yok (nadir durum).")
        print("  Çözüm: python app/tools/nexgen_db_repair.py")
except Exception as e:
    print(f"  HATA: {e}")

con.close()
print("=" * 60)

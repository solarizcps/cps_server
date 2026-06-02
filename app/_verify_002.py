import sqlite3
import sys
import os
sys.path.insert(0, r"C:\cps_dev")
from config import Config

DB = Config.MOCK_DB_PATH
print(f"DB: {DB}")
print(f"   Boyut: {os.path.getsize(DB)} byte")
print()

c = sqlite3.connect(DB)

# 1) Yeni tablolar var mi?
print("=== 1) YENI 5 TABLO + schema_migrations ===")
hepsi_var = True
for tbl in ["schema_migrations", "tasks_users", "tasks", "task_files", "task_logs", "task_settings"]:
    r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
    isaret = "[OK]" if r else "[YOK]"
    if not r and tbl != "schema_migrations":
        hepsi_var = False
    print(f"  {tbl:22} {isaret}")

if not hepsi_var:
    print()
    print("  !! Tablolar eksik - migration basarisiz")
    c.close()
    sys.exit(1)

# 2) Eski tablolar dokunulmadi mi?
print()
print("=== 2) ESKI TABLOLAR (dokunulmamali) ===")
for tbl in ["sistem_kullanici", "sistem_rol", "sistem_yetki", "uretim_kayit", "finans_anlasma", "grafik_numune"]:
    r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
    cnt = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0] if r else "-"
    print(f"  {tbl:22} {'VAR' if r else 'YOK':4}  kayit: {cnt}")

# 3) tasks_users sema (UNIQUE kullanici_adi)
print()
print("=== 3) tasks_users SEMA ===")
for r in c.execute("PRAGMA table_info(tasks_users)"):
    print(f"  {r[0]:2}  {r[1]:18} {r[2]:10}  default={r[4]}")

# 4) tasks sema (kolon sayisi)
print()
print("=== 4) tasks SEMA ===")
cols = c.execute("PRAGMA table_info(tasks)").fetchall()
print(f"  Toplam kolon: {len(cols)} (beklenen: 33)")

# 5) Default ayarlar
print()
print("=== 5) DEFAULT AYARLAR ===")
for r in c.execute("SELECT setting_key, setting_value FROM task_settings WHERE departman IS NULL AND user_id IS NULL ORDER BY setting_key"):
    print(f"  {r[0]:22} = {r[1]}")

# 6) Indexler
print()
print("=== 6) INDEXLER ===")
idx_list = c.execute("""
    SELECT name, tbl_name FROM sqlite_master
    WHERE type='index' AND name LIKE 'idx_task%'
    ORDER BY tbl_name, name
""").fetchall()
print(f"  Toplam index: {len(idx_list)} (beklenen: 18)")

# 7) UNIQUE constraint testi
print()
print("=== 7) UNIQUE CONSTRAINT TESTI ===")
try:
    c.execute("INSERT INTO tasks_users (ad, kullanici_adi, rol) VALUES ('TEST_USER', '__test_unique__', 'usta')")
    c.execute("INSERT INTO tasks_users (ad, kullanici_adi, rol) VALUES ('TEST_USER2', '__test_unique__', 'usta')")
    print("  [HATA] UNIQUE calismiyor!")
except sqlite3.IntegrityError as e:
    print(f"  [OK] UNIQUE calisti: {e}")
finally:
    c.execute("DELETE FROM tasks_users WHERE kullanici_adi='__test_unique__'")
    c.commit()

# 8) schema_migrations
print()
print("=== 8) schema_migrations ===")
for r in c.execute("SELECT version, uygulama_zamani, aciklama FROM schema_migrations ORDER BY version"):
    print(f"  {r[0]}  {r[1]}")
    print(f"        {r[2]}")

# 9) Bos tablolar
print()
print("=== 9) KAYIT SAYILARI ===")
for tbl in ["tasks_users", "tasks", "task_files", "task_logs", "task_settings"]:
    cnt = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    print(f"  {tbl:18} {cnt}")

c.close()
print()
print("=== DOGRULAMA TAMAM ===")

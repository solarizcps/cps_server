# -*- coding: utf-8 -*-
"""
CPS DEV - MIGRATION 004 RUNNER (v2 - dogru sema ile)
====================================================

Bu script:
  1. mock_data.db (Config.MOCK_DB_PATH) acilir
  2. bildirim_log'a 3 kolon eklenir (zaten varsa SKIP)
  3. idx_bildirim_pending olusturulur
  4. task_settings'e EKSIK overlay ayarlari eklenir (mevcut olanlar dokunmaz)
  5. schema_migrations'a 004_overlay kayit edilir

Mevcut task_settings ayarlari (002'de eklenmisler):
  overlay_enabled       = 1     <- KORUNDU
  sound_enabled         = 0     <- KORUNDU
  poll_interval_sec     = 30    <- KORUNDU (overlay_polling_seconds yerine)
  overdue_check_min     = 15    <- KORUNDU (overlay_overdue_repeat_min yerine)

Yeni eklenecek 3 ayar:
  hidden_polling_sec    = 120   (sayfa hidden iken polling)
  critical_repeat_min   = 15    (kritik tekrar)
  normal_repeat_min     = 60    (normal tekrar)

Sema:
  task_settings: setting_key, setting_value, departman, user_id
  schema_migrations: version, uygulama_zamani, aciklama
"""
import sys
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config import Config
    DB_PATH = Config.MOCK_DB_PATH
except Exception as e:
    print(f"[HATA] config.py yuklenemedi: {e}")
    DB_PATH = str(PROJECT_ROOT / "mock_data.db")

print(f"[INFO] DB_PATH: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print(f"[HATA] DB bulunamadi: {DB_PATH}")
    sys.exit(1)


def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


def setting_exists(cur, key):
    cur.execute("SELECT 1 FROM task_settings WHERE setting_key=?", (key,))
    return cur.fetchone() is not None


def migration_already_applied(cur, version):
    try:
        cur.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,))
        return cur.fetchone() is not None
    except sqlite3.OperationalError:
        return False


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # 0) Tablolar var mi
        for tbl in ('bildirim_log', 'task_settings', 'schema_migrations'):
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
            if not cur.fetchone():
                print(f"[HATA] Tablo yok: {tbl}")
                return False

        # 1) Migration kaydi
        if migration_already_applied(cur, '004_overlay'):
            print("[INFO] 004_overlay schema_migrations'da kayitli (yine de eksik kontrol edilecek)")

        print()
        print("=== ADIM 1: bildirim_log kolonlari ===")
        new_cols = [
            ("snooze_until",  "TEXT"),
            ("dismiss_count", "INTEGER DEFAULT 0"),
            ("last_shown_at", "TEXT"),
        ]
        for col_name, col_def in new_cols:
            if column_exists(cur, "bildirim_log", col_name):
                print(f"  [SKIP] bildirim_log.{col_name} zaten var")
            else:
                try:
                    cur.execute(f"ALTER TABLE bildirim_log ADD COLUMN {col_name} {col_def}")
                    print(f"  [OK]   bildirim_log.{col_name} eklendi")
                except sqlite3.OperationalError as e:
                    print(f"  [HATA] bildirim_log.{col_name}: {e}")
                    raise

        print()
        print("=== ADIM 2: Index ===")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bildirim_pending
                ON bildirim_log(kullanici_id, okundu_mu, snooze_until)
        """)
        print("  [OK] idx_bildirim_pending hazir (yeni veya mevcut)")

        print()
        print("=== ADIM 3: task_settings overlay ayarlari ===")
        # Mevcut ayarlari KORU, sadece eksikleri ekle
        # Sema: setting_key, setting_value, departman, user_id, created_at, updated_at
        new_settings = [
            ('hidden_polling_sec',  '120', 'Overlay polling - sayfa hidden iken (saniye)'),
            ('critical_repeat_min', '15',  'Kritik bildirim tekrar araligi (dakika)'),
            ('normal_repeat_min',   '60',  'Normal bildirim tekrar araligi (dakika)'),
        ]
        for key, value, desc in new_settings:
            if setting_exists(cur, key):
                print(f"  [SKIP] {key} zaten var")
            else:
                # task_settings tablosunda 'aciklama' kolonu YOK, sadece value
                cur.execute("""
                    INSERT INTO task_settings (setting_key, setting_value)
                    VALUES (?, ?)
                """, (key, value))
                print(f"  [OK]   {key} = {value}")

        # Mevcut ayarlari da goster (referans)
        print()
        print("  Mevcut task_settings ayarlari (referans):")
        cur.execute("""
            SELECT setting_key, setting_value FROM task_settings
            WHERE setting_key IN (
                'overlay_enabled', 'sound_enabled', 'poll_interval_sec',
                'overdue_check_min', 'hidden_polling_sec',
                'critical_repeat_min', 'normal_repeat_min'
            )
            ORDER BY setting_key
        """)
        for row in cur.fetchall():
            print(f"    {row['setting_key']:25s} = {row['setting_value']}")

        print()
        print("=== ADIM 4: schema_migrations kayit ===")
        # Sema: version, uygulama_zamani, aciklama
        if migration_already_applied(cur, '004_overlay'):
            print("  [SKIP] 004_overlay zaten kayitli")
        else:
            cur.execute("""
                INSERT INTO schema_migrations (version, aciklama)
                VALUES (?, ?)
            """, (
                '004_overlay',
                'bildirim_log overlay kolonlari + 3 task_settings ayari'
            ))
            print("  [OK] 004_overlay kayit edildi")

        conn.commit()
        print()
        print("=== DOGRULAMA ===")

        # Kolonlar
        cur.execute("PRAGMA table_info(bildirim_log)")
        cols = [row[1] for row in cur.fetchall()]
        for c in ['snooze_until', 'dismiss_count', 'last_shown_at']:
            print(f"  bildirim_log.{c}: {'VAR' if c in cols else 'YOK'}")

        # Index
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_bildirim_pending'
        """)
        idx = cur.fetchone()
        print(f"  idx_bildirim_pending: {'VAR' if idx else 'YOK'}")

        # Settings count
        cur.execute("""
            SELECT COUNT(*) AS n FROM task_settings
            WHERE setting_key IN (
                'overlay_enabled', 'sound_enabled', 'poll_interval_sec',
                'overdue_check_min', 'hidden_polling_sec',
                'critical_repeat_min', 'normal_repeat_min'
            )
        """)
        n = cur.fetchone()['n']
        print(f"  task_settings overlay-iliskili sayisi: {n} (beklenen 7)")

        # Migrations
        cur.execute("SELECT version, uygulama_zamani FROM schema_migrations ORDER BY version")
        print()
        print("  schema_migrations:")
        for row in cur.fetchall():
            print(f"    {row['version']:25s} ({row['uygulama_zamani']})")

        return True

    except Exception as e:
        conn.rollback()
        print(f"\n[HATA] Migration basarisiz, rollback yapildi: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("CPS DEV - MIGRATION 004 v2 (Overlay Support)")
    print("=" * 60)
    success = run()
    print()
    print("=" * 60)
    if success:
        print("[OK] Migration 004 basariyla tamamlandi.")
        sys.exit(0)
    else:
        print("[HATA] Migration 004 basarisiz!")
        sys.exit(1)

# -*- coding: utf-8 -*-
"""
Migration 104 — NexGen FAZ-URETIM-KODU-1: Birleşik üretim kodu alanları
=========================================================================
AnaFormülKodu-RenkKodu formatı (ör. 1BA-FS02-0031).

Eklenen kolonlar:
  nexgen_rf_formul_uygunluk : uretim_kodu, ana_formul_kodu, renk_kodu
  nexgen_uretim_plan        : uretim_kodu, ana_formul_kodu, renk_kodu
  nexgen_uretim_batch       : uretim_kodu, ana_formul_kodu, renk_kodu

Kurallar:
  - Idempotent
  - Mevcut kayıtlar silinmez / güncellenmez
  - Gerçek DB'de kullanıcı onayı olmadan çalıştırılmamalı
"""

import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _tablo_var(cur, tablo):
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone())


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    import shutil
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre104_{ts}.db')
    try:
        shutil.copy2(DB_PATH, bak)
        print(f"[YEDEK] {os.path.basename(bak)}")
    except Exception as e:
        print(f"[UYARI] Yedek alinamadi: {e}")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("=" * 70)
    print("Migration 104 - nexgen_uretim_kodu alanlari")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    kolonlar = [
        ('nexgen_rf_formul_uygunluk', 'uretim_kodu', 'TEXT'),
        ('nexgen_rf_formul_uygunluk', 'ana_formul_kodu', 'TEXT'),
        ('nexgen_rf_formul_uygunluk', 'renk_kodu', 'TEXT'),
        ('nexgen_uretim_plan', 'uretim_kodu', 'TEXT'),
        ('nexgen_uretim_plan', 'ana_formul_kodu', 'TEXT'),
        ('nexgen_uretim_plan', 'renk_kodu', 'TEXT'),
        ('nexgen_uretim_batch', 'uretim_kodu', 'TEXT'),
        ('nexgen_uretim_batch', 'ana_formul_kodu', 'TEXT'),
        ('nexgen_uretim_batch', 'renk_kodu', 'TEXT'),
    ]

    for tablo, kolon, tip in kolonlar:
        if not _tablo_var(cur, tablo):
            print(f"  SKIP  {tablo} tablosu yok")
            continue
        if _kolon_var(cur, tablo, kolon):
            print(f"  SKIP  {tablo}.{kolon} zaten var")
        else:
            cur.execute(f"ALTER TABLE {tablo} ADD COLUMN {kolon} {tip}")
            con.commit()
            print(f"  OK    {tablo}.{kolon} eklendi")

    if _tablo_var(cur, 'nexgen_rf_formul_uygunluk') and _kolon_var(cur, 'nexgen_rf_formul_uygunluk', 'uretim_kodu'):
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_rf_fu_uretim_kodu
            ON nexgen_rf_formul_uygunluk (uretim_kodu)
            WHERE aktif = 1 AND uretim_kodu IS NOT NULL AND uretim_kodu != ''
        """)
        con.commit()
        print("  OK    UNIQUE index uq_rf_fu_uretim_kodu")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(104)")
        con.commit()
        print("  OK    schema_migrations version=104")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    print("Migration 104 tamamlandi\n")
    con.close()


if __name__ == '__main__':
    run()

# -*- coding: utf-8 -*-
"""
Migration 079 — NexGen FAZ-3G: RF kullanim ↔ tablet uretim baglantisi
======================================================================
nexgen_rf_kullanim genisletme:
  - uretim_emir_id    (nexgen_uretim_parca.id, nullable)
  - tablet_session_id (batch_kodu, nullable)
  - durum             (MANUEL | URETIM | TAMAMLANDI)
  - miktar_kg         (REAL, default 0)
  - guncelleme_tarihi (TEXT)

Idempotent. Rollback: yeni kolonlar SQLite'ta kalir (guvenli); index drop.

KURAL: RF/BOYA/ARGE/formul/recete_kalem DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 079: nexgen_rf_kullanim tablet baglantisi ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    yeni_kolonlar = (
        ('uretim_emir_id',    'INTEGER'),
        ('tablet_session_id', 'TEXT'),
        ('durum',             "TEXT NOT NULL DEFAULT 'MANUEL'"),
        ('miktar_kg',         'REAL NOT NULL DEFAULT 0'),
        ('guncelleme_tarihi', 'TEXT'),
    )
    for kolon, tip in yeni_kolonlar:
        if not _kolon_var(cur, 'nexgen_rf_kullanim', kolon):
            cur.execute(f"ALTER TABLE nexgen_rf_kullanim ADD COLUMN {kolon} {tip}")
            con.commit()
            print(f"  OK    nexgen_rf_kullanim.{kolon}")
        else:
            print(f"  SKIP  {kolon} zaten var")

    indexler = [
        ("idx_nrfkull_emir",    "nexgen_rf_kullanim(uretim_emir_id)"),
        ("idx_nrfkull_session", "nexgen_rf_kullanim(tablet_session_id)"),
        ("idx_nrfkull_durum",   "nexgen_rf_kullanim(durum)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(indexler)} index")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(79)")
        con.commit()
        print("  OK    schema_migrations version=79")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_rf_kullanim)").fetchall()]
    print(f"  CHECK kolonlar: {cols}")

    con.close()
    print("=== Migration 079 tamamlandi ===\n")


def rollback():
    """Indexleri kaldir; kolonlar SQLite ALTER DROP desteklemez."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 079: index drop ===")
    for idx in ('idx_nrfkull_emir', 'idx_nrfkull_session', 'idx_nrfkull_durum'):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=79")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    indexler kaldirildi (kolonlar kalir)")
    print("=== Rollback 079 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()

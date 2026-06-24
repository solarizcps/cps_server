# -*- coding: utf-8 -*-
"""
Migration 078 — NexGen FAZ-3F: RF cari/siparis baglantisi + kullanim logu
==========================================================================
Degisiklikler:
  [1] nexgen_rf_renk.cari_id     — nullable (RF olusturma / baglama)
  [2] nexgen_rf_renk.siparis_id  — nullable (nexgen_uretim_plan.id)
  [3] nexgen_rf_kullanim         — RF kullanim gecmisi

Not: durum kolonu 076'da zaten var; tekrar eklenmez.

Idempotent. Rollback: kullanim tablosunu kaldirir (ALTER kolonlari SQLite'ta geri alinmaz).

KURAL: BOYA / ARGE / formul / recete_kalem / tablet DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 078: nexgen RF kullanim + cari/siparis ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    if not _kolon_var(cur, 'nexgen_rf_renk', 'cari_id'):
        cur.execute("ALTER TABLE nexgen_rf_renk ADD COLUMN cari_id INTEGER")
        con.commit()
        print("  OK    nexgen_rf_renk.cari_id eklendi")
    else:
        print("  SKIP  cari_id zaten var")

    if not _kolon_var(cur, 'nexgen_rf_renk', 'siparis_id'):
        cur.execute("ALTER TABLE nexgen_rf_renk ADD COLUMN siparis_id INTEGER")
        con.commit()
        print("  OK    nexgen_rf_renk.siparis_id eklendi")
    else:
        print("  SKIP  siparis_id zaten var")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_rf_kullanim (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            rf_renk_id       INTEGER NOT NULL,
            formul_id        INTEGER,
            cari_id          INTEGER,
            siparis_id       INTEGER,
            aciklama         TEXT,
            olusturan_id     INTEGER,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
            aktif            INTEGER NOT NULL DEFAULT 1
        )
    """)
    con.commit()
    print("  OK    nexgen_rf_kullanim")

    indexler = [
        ("idx_nrf_cari",        "nexgen_rf_renk(cari_id)"),
        ("idx_nrf_siparis",     "nexgen_rf_renk(siparis_id)"),
        ("idx_nrfkull_rf",      "nexgen_rf_kullanim(rf_renk_id)"),
        ("idx_nrfkull_cari",    "nexgen_rf_kullanim(cari_id)"),
        ("idx_nrfkull_siparis", "nexgen_rf_kullanim(siparis_id)"),
        ("idx_nrfkull_tarih",   "nexgen_rf_kullanim(olusturma_tarihi)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(indexler)} index")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(78)")
        con.commit()
        print("  OK    schema_migrations version=78")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_rf_renk)").fetchall()]
    kull_cnt = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kullanim").fetchone()[0]
    print(f"  CHECK rf_renk kolonlari: cari_id={'cari_id' in cols}, siparis_id={'siparis_id' in cols}, durum={'durum' in cols}")
    print(f"  CHECK nexgen_rf_kullanim: {kull_cnt} satir")

    con.close()
    print("=== Migration 078 tamamlandi ===\n")


def rollback():
    """Yalnizca yeni tabloyu kaldirir; ALTER kolonlari guvenli sekilde birakilir."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 078: nexgen_rf_kullanim DROP ===")
    cur.execute("DROP TABLE IF EXISTS nexgen_rf_kullanim")
    for idx in (
        'idx_nrfkull_rf', 'idx_nrfkull_cari', 'idx_nrfkull_siparis', 'idx_nrfkull_tarih',
        'idx_nrf_cari', 'idx_nrf_siparis',
    ):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=78")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    nexgen_rf_kullanim kaldirildi (cari_id/siparis_id kolonlari kalir)")
    print("=== Rollback 078 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()

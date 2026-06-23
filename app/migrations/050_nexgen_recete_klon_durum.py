"""
Migration 050: nexgen_uretim_varyant.recete_durum + nexgen_recete_klon_log
FAZ-4C-2 — Recete Klonlama ve Durum Altyapisi

Degisiklikler:
1) nexgen_uretim_varyant tablosuna recete_durum kolonu eklenir (TASLAK varsayilan)
2) nexgen_recete_klon_log tablosu olusturulur (audit)
3) Mevcut kayitlar TASLAK ile guncellenir
"""

import sqlite3
import os


def run(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        # ── 1) recete_durum kolonu: nexgen_uretim_varyant
        cols = [c[1] for c in con.execute("PRAGMA table_info(nexgen_uretim_varyant)").fetchall()]
        if 'recete_durum' not in cols:
            con.execute("""
                ALTER TABLE nexgen_uretim_varyant
                ADD COLUMN recete_durum TEXT NOT NULL DEFAULT 'TASLAK'
            """)
            print("[050] nexgen_uretim_varyant.recete_durum eklendi (DEFAULT: TASLAK)")
        else:
            print("[050] recete_durum zaten var — atlanıyor")

        # ── 2) Klon log tablosu
        con.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_recete_klon_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kaynak_uv_id    INTEGER NOT NULL,
                hedef_uv_id     INTEGER NOT NULL,
                kalem_sayisi    INTEGER NOT NULL DEFAULT 0,
                yapan_id        INTEGER,
                islem_tarihi    TEXT    NOT NULL DEFAULT (datetime('now')),
                notlar          TEXT
            )
        """)
        print("[050] nexgen_recete_klon_log tablosu hazir")

        con.commit()
        print("[050] Migration basarili")

    except Exception as e:
        con.rollback()
        print(f"[050] HATA: {e}")
        raise
    finally:
        con.close()


if __name__ == '__main__':
    db = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
    run(os.path.abspath(db))

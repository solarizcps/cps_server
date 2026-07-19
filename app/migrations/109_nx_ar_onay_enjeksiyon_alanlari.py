# -*- coding: utf-8 -*-
"""
Migration 109 — NX-AR onay / Ferhat boyut sonuç alanları + olay geçmişi

Idempotent. Canlı apply kullanıcı onayı olmadan yapılmaz.
  python app/migrations/109_nx_ar_onay_enjeksiyon_alanlari.py --db PATH
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

VERSION = "109"
DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)

BOYUT_KOLONLAR = [
    ("enjeksiyon_saniye", "INTEGER"),
    ("kalite_sorunu_var", "INTEGER NOT NULL DEFAULT 0"),
    ("kalite_aciklama", "TEXT"),
]


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _tablo_var(cur, tablo):
    return bool(
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tablo,),
        ).fetchone()
    )


def run(db_path: str | None = None) -> dict:
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    stats = {"db": db_path, "ok": False, "kolon": 0, "tablo": 0, "log": []}

    def log(m):
        stats["log"].append(m)
        print(m)

    if not os.path.isfile(db_path):
        log(f"[109] HATA: DB yok: {db_path}")
        return stats

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    log("=" * 60)
    log(f"Migration {VERSION}")
    log(f"DB: {db_path}")

    if not _tablo_var(cur, "nexgen_arge_boyut_sonuc"):
        log("[109] HATA: nexgen_arge_boyut_sonuc yok (106 gerekli)")
        con.close()
        return stats

    for kolon, tip in BOYUT_KOLONLAR:
        if _kolon_var(cur, "nexgen_arge_boyut_sonuc", kolon):
            log(f"[109] SKIP boyut_sonuc.{kolon}")
        else:
            cur.execute(
                f"ALTER TABLE nexgen_arge_boyut_sonuc ADD COLUMN {kolon} {tip}"
            )
            stats["kolon"] += 1
            log(f"[109] OK   boyut_sonuc.{kolon}")

    if _tablo_var(cur, "nexgen_arge_olay"):
        log("[109] SKIP nexgen_arge_olay")
    else:
        cur.execute(
            """
            CREATE TABLE nexgen_arge_olay (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_test_id INTEGER NOT NULL,
                kullanici_id INTEGER,
                eski_durum TEXT,
                yeni_durum TEXT,
                olay_tipi TEXT NOT NULL,
                aciklama TEXT,
                olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_arge_olay_test "
            "ON nexgen_arge_olay(arge_test_id)"
        )
        stats["tablo"] += 1
        log("[109] OK   nexgen_arge_olay")

    con.commit()
    con.close()
    stats["ok"] = True
    log(f"[109] DONE kolon={stats['kolon']} tablo={stats['tablo']}")
    return stats


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None, help="Hedef DB (varsayılan: app/mock_data.db)")
    args = p.parse_args(argv)
    st = run(args.db)
    sys.exit(0 if st.get("ok") else 1)


if __name__ == "__main__":
    main()

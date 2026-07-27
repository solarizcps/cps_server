# -*- coding: utf-8 -*-
"""
Migration 117 — Ferhat tek deneme ölçümü + boyut kullanım oranı

Idempotent. Canlı apply kullanıcı onayı olmadan yapılmaz.

Tablo:
  nexgen_arge_deneme_boyut_oran (deneme_id + boyut → kullanim_orani)

Kolonlar (nexgen_arge_deneme):
  sonuc_modeli, olcum_shore, olcum_pisme_saniye, olcum_enjeksiyon_saniye,
  olcum_gramaj_gr, olcum_renk, olcum_yuzey, olcum_kalip, olcum_kalite_sorunu, olcum_not
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

VERSION = "117"
DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)

DENEME_KOLONLAR = [
    ("sonuc_modeli", "TEXT"),
    ("olcum_shore", "REAL"),
    ("olcum_pisme_saniye", "INTEGER"),
    ("olcum_enjeksiyon_saniye", "INTEGER"),
    ("olcum_gramaj_gr", "REAL"),
    ("olcum_renk", "TEXT"),
    ("olcum_yuzey", "TEXT"),
    ("olcum_kalip", "TEXT"),
    ("olcum_kalite_sorunu", "INTEGER"),
    ("olcum_not", "TEXT"),
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
    stats = {"db": db_path, "ok": False, "log": []}

    def log(m):
        stats["log"].append(m)
        print(m)

    if not os.path.isfile(db_path):
        log(f"[117] HATA: DB yok: {db_path}")
        return stats

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    log("=" * 60)
    log(f"Migration {VERSION}")
    log(f"DB: {db_path}")

    if not _tablo_var(cur, "nexgen_arge_deneme"):
        log("[117] HATA: nexgen_arge_deneme yok")
        con.close()
        return stats

    for kolon, tip in DENEME_KOLONLAR:
        if _kolon_var(cur, "nexgen_arge_deneme", kolon):
            log(f"[117] SKIP nexgen_arge_deneme.{kolon}")
        else:
            cur.execute(f"ALTER TABLE nexgen_arge_deneme ADD COLUMN {kolon} {tip}")
            log(f"[117] OK   nexgen_arge_deneme.{kolon}")

    if _tablo_var(cur, "nexgen_arge_deneme_boyut_oran"):
        log("[117] SKIP nexgen_arge_deneme_boyut_oran (tablo var)")
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_deneme_boyut_oran (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deneme_id INTEGER NOT NULL,
                arge_test_id INTEGER NOT NULL,
                boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
                kullanim_orani REAL NOT NULL,
                olusturan_id INTEGER,
                olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                guncelleme_tarihi TEXT,
                UNIQUE (deneme_id, boyut)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_arge_deneme_boyut_oran_deneme "
            "ON nexgen_arge_deneme_boyut_oran(deneme_id)"
        )
        log("[117] OK   nexgen_arge_deneme_boyut_oran")

    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
            (VERSION,),
        )
        log(f"[117] schema_migrations version={VERSION}")
    except Exception as e:
        log(f"[117] WARN schema_migrations: {e}")

    con.commit()
    con.close()
    stats["ok"] = True
    log("[117] DONE")
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Migration 117 Ferhat tek deneme oran")
    p.add_argument("--db", default=DEFAULT_DB)
    args = p.parse_args(argv)
    return 0 if run(args.db).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

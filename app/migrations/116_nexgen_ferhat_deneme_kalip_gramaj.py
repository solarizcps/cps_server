# -*- coding: utf-8 -*-
"""
Migration 116 — Ferhat deneme kalıp snapshot + boyut gramaj + saha.ferhat_islem yetkisi

Idempotent. Canlı apply kullanıcı onayı olmadan yapılmaz.

Kolonlar:
  nexgen_arge_deneme: kalip_id, kalip_kodu_snapshot, kalip_adi_snapshot,
                      kalip_beden_snapshot, kalip_makine_snapshot
  nexgen_arge_boyut_sonuc: gramaj_gr

Yetki:
  saha.ferhat_islem → yalnız RolId=35 (Enjeksiyon / Ferhat), can_view + can_update

Rollback:
  python app/migrations/116_nexgen_ferhat_deneme_kalip_gramaj.py --rollback --db PATH
  (Kolon drop SQLite'ta desteklenmez; yalnız yetki + schema_migrations geri alınır.)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

VERSION = "116"
YETKI_KOD = "saha.ferhat_islem"
FERHAT_ROL_ID = 35
DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)

DENEME_KOLONLAR = [
    ("kalip_id", "INTEGER"),
    ("kalip_kodu_snapshot", "TEXT"),
    ("kalip_adi_snapshot", "TEXT"),
    ("kalip_beden_snapshot", "TEXT"),
    ("kalip_makine_snapshot", "TEXT"),
]

BOYUT_KOLONLAR = [
    ("gramaj_gr", "REAL"),
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


def _ensure_yetki(cur, log):
    row = cur.execute(
        "SELECT Id FROM sistem_yetki WHERE Kod=?", (YETKI_KOD,)
    ).fetchone()
    if row:
        yetki_id = row[0]
        log(f"[116] SKIP yetki {YETKI_KOD} Id={yetki_id}")
    else:
        cur.execute(
            """
            INSERT INTO sistem_yetki (Kod, Ad, Aciklama, Modul)
            VALUES (?, ?, ?, ?)
            """,
            (
                YETKI_KOD,
                "Saha Ferhat İşlem",
                "Ferhat enjeksiyon deneme operasyon endpointleri",
                "saha",
            ),
        )
        yetki_id = cur.lastrowid
        log(f"[116] OK   yetki {YETKI_KOD} Id={yetki_id}")

    mevcut = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (FERHAT_ROL_ID, yetki_id),
    ).fetchone()
    if mevcut:
        cur.execute(
            """
            UPDATE sistem_rol_yetki
               SET can_view=1, can_update=1, Gorebilir=1, Duzenleyebilir=1
             WHERE Id=?
            """,
            (mevcut[0],),
        )
        log(f"[116] OK   rol_yetki güncellendi RolId={FERHAT_ROL_ID}")
    else:
        cur.execute(
            """
            INSERT INTO sistem_rol_yetki
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 1, 1, 0, 1, 0, 0, 0, 0)
            """,
            (FERHAT_ROL_ID, yetki_id),
        )
        log(f"[116] OK   RolId={FERHAT_ROL_ID} ← {YETKI_KOD}")


def rollback(db_path: str) -> int:
    if not os.path.isfile(db_path):
        print(f"[116] HATA: DB yok: {db_path}")
        return 1
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    yetki = cur.execute(
        "SELECT Id FROM sistem_yetki WHERE Kod=?", (YETKI_KOD,)
    ).fetchone()
    if yetki:
        cur.execute(
            "DELETE FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (FERHAT_ROL_ID, yetki[0]),
        )
        print(f"[116] rollback rol_yetki silindi")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=?", (VERSION,))
    except Exception as e:
        print(f"[116] rollback WARN schema_migrations: {e}")
    con.commit()
    con.close()
    print("[116] rollback OK (kolonlar SQLite'ta bırakıldı)")
    return 0


def run(db_path: str | None = None) -> dict:
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    stats = {"db": db_path, "ok": False, "kolon": 0, "log": []}

    def log(m):
        stats["log"].append(m)
        print(m)

    if not os.path.isfile(db_path):
        log(f"[116] HATA: DB yok: {db_path}")
        return stats

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    log("=" * 60)
    log(f"Migration {VERSION}")
    log(f"DB: {db_path}")

    for tablo, kolonlar in (
        ("nexgen_arge_deneme", DENEME_KOLONLAR),
        ("nexgen_arge_boyut_sonuc", BOYUT_KOLONLAR),
    ):
        if not _tablo_var(cur, tablo):
            log(f"[116] HATA: {tablo} yok")
            con.close()
            return stats
        for kolon, tip in kolonlar:
            if _kolon_var(cur, tablo, kolon):
                log(f"[116] SKIP {tablo}.{kolon}")
            else:
                cur.execute(f"ALTER TABLE {tablo} ADD COLUMN {kolon} {tip}")
                stats["kolon"] += 1
                log(f"[116] OK   {tablo}.{kolon}")

    _ensure_yetki(cur, log)

    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
            (VERSION,),
        )
        log(f"[116] schema_migrations version={VERSION}")
    except Exception as e:
        log(f"[116] WARN schema_migrations: {e}")

    con.commit()
    con.close()
    stats["ok"] = True
    log(f"[116] DONE kolon={stats['kolon']}")
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Migration 116 Ferhat kalip/gramaj")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--rollback", action="store_true")
    args = p.parse_args(argv)
    if args.rollback:
        return rollback(args.db)
    return 0 if run(args.db).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

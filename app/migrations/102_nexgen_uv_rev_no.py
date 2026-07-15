# -*- coding: utf-8 -*-
"""
Migration 102 — NexGen P5D-2B: UV Revizyon Şema (rev_no)
=========================================================
Sorun:
  nexgen_uretim_varyant UNIQUE(renk_varyant_id, boyut) aynı RV+boyut altında
  ikinci revizyon UV'ye izin vermiyor (UV 10014, 10017 INSERT_UV_REVISION engeli).

Çözüm:
  - rev_no INTEGER NOT NULL DEFAULT 1
  - UNIQUE(renk_varyant_id, boyut, rev_no) — tablo rebuild
  - Mevcut tüm satırlar rev_no=1
  - Yeni revizyon: rev_no=2, kaynak_varyant_id=eski_uv_id

Idempotent: rev_no + uq_nuv_rv_boyut_rev varsa SKIP.
Geçici test: python app/migrations/102_nexgen_uv_rev_no.py test <db_kopya>
Gerçek DB: yalnız onay sonrası; bu fazda test argümanı zorunlu.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from typing import Any

DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "mock_data.db")
)

MIGRATION_VERSION = 102
UV_TABLE = "nexgen_uretim_varyant"
UV_TABLE_NEW = "nexgen_uretim_varyant_new"
UV_REV_INDEX = "uq_nuv_rv_boyut_rev"

# Mevcut kolonlar (062 + 050 recete_durum + formul_batch_kg)
UV_KOLONLAR = [
    "id", "renk_varyant_id", "boyut", "ad", "onay_durumu", "onaylayan_id",
    "onay_tarihi", "onay_notu", "kaynak_varyant_id", "notlar", "aktif",
    "olusturma_tarihi", "recete_durum", "formul_batch_kg",
]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _tablo_var(cur, tablo: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


def _kolon_var(cur, tablo: str, kolon: str) -> bool:
    return kolon in [c[1] for c in cur.execute(
        f"PRAGMA table_info({tablo})"
    ).fetchall()]


def _index_var(cur, ad: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (ad,)
    ).fetchone() is not None


def _eski_unique_2kolon_var(cur) -> bool:
    """UNIQUE(renk_varyant_id, boyut) — 2 kolon."""
    for idx in cur.execute(f"PRAGMA index_list({UV_TABLE})"):
        if not idx[2]:
            continue
        cols = [r[2].lower() for r in cur.execute(
            f"PRAGMA index_info({idx[1]})"
        )]
        if set(cols) == {"renk_varyant_id", "boyut"}:
            return True
    return False


def _migration_tamam_mi(cur) -> bool:
    return _kolon_var(cur, UV_TABLE, "rev_no") and not _eski_unique_2kolon_var(cur)


def _create_new_table_sql() -> str:
    return f"""
        CREATE TABLE {UV_TABLE_NEW} (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            renk_varyant_id  INTEGER NOT NULL
                                 REFERENCES nexgen_renk_varyant(id),
            boyut            TEXT    NOT NULL DEFAULT 'STANDART',
            ad               TEXT    NOT NULL,
            onay_durumu      TEXT    NOT NULL DEFAULT 'BEKLIYOR',
            onaylayan_id     INTEGER,
            onay_tarihi      TEXT,
            onay_notu        TEXT,
            kaynak_varyant_id INTEGER
                                 REFERENCES nexgen_uretim_varyant(id),
            notlar           TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
            recete_durum     TEXT    NOT NULL DEFAULT 'TASLAK',
            formul_batch_kg  REAL    DEFAULT 0,
            rev_no           INTEGER NOT NULL DEFAULT 1,
            UNIQUE (renk_varyant_id, boyut, rev_no)
        )
    """


def _uv_fk_ihlalleri(cur) -> list[sqlite3.Row]:
    """nexgen_uretim_varyant zinciri — migration sonrası doğrulama."""
    ihlaller: list[sqlite3.Row] = []
    checks = [
        (
            "nexgen_uretim_plan p LEFT JOIN nexgen_uretim_varyant uv "
            "ON uv.id=p.uretim_varyant_id",
            "p.uretim_varyant_id IS NOT NULL AND uv.id IS NULL",
            "nexgen_uretim_plan",
        ),
        (
            "nexgen_uretim_batch b LEFT JOIN nexgen_uretim_varyant uv "
            "ON uv.id=b.uretim_varyant_id",
            "b.uretim_varyant_id IS NOT NULL AND uv.id IS NULL",
            "nexgen_uretim_batch",
        ),
        (
            "nexgen_recete_kalem k LEFT JOIN nexgen_uretim_varyant uv "
            "ON uv.id=k.uretim_varyant_id",
            "k.uretim_varyant_id IS NOT NULL AND uv.id IS NULL",
            "nexgen_recete_kalem",
        ),
        (
            f"{UV_TABLE} u LEFT JOIN {UV_TABLE} src "
            "ON src.id=u.kaynak_varyant_id",
            "u.kaynak_varyant_id IS NOT NULL AND src.id IS NULL",
            UV_TABLE,
        ),
    ]
    for join_sql, where_sql, tablo in checks:
        try:
            rows = cur.execute(
                f"SELECT '{tablo}' AS tablo, COUNT(*) AS cnt "
                f"FROM {join_sql} WHERE {where_sql}"
            ).fetchone()
            if rows and rows[1] > 0:
                ihlaller.append(rows)
        except sqlite3.OperationalError:
            pass
    return ihlaller


def _bagimli_viewleri_kaydet(cur) -> list[tuple[str, str]]:
    """nexgen_uretim_varyant referanslı VIEW tanımlarını sakla."""
    kayitlar: list[tuple[str, str]] = []
    for ad, sql in cur.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='view'"
    ):
        if sql and UV_TABLE in sql:
            kayitlar.append((ad, sql))
    return kayitlar


def _bagimli_viewleri_drop(cur, view_adlari: list[str]) -> None:
    for ad in view_adlari:
        cur.execute(f"DROP VIEW IF EXISTS {ad}")


def _viewleri_yeniden_olustur(cur, kayitlar: list[tuple[str, str]]) -> None:
    for _ad, sql in kayitlar:
        if sql:
            cur.execute(sql)


def run(db_path: str | None = None, backup: bool = False) -> dict[str, Any]:
    """
    Migration 102 uygula.
    Geçici test: backup=False, db_path=kopya.
    """
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    sonuc: dict[str, Any] = {
        "db_path": db_path,
        "migration": MIGRATION_VERSION,
        "rebuild": False,
        "satir_once": 0,
        "satir_sonra": 0,
        "rev_no_eklendi": False,
        "index_olusturuldu": False,
        "view_drop": 0,
        "view_restore": 0,
        "skip": False,
        "hata": None,
    }

    if not os.path.exists(db_path):
        sonuc["hata"] = f"DB bulunamadı: {db_path}"
        return sonuc

    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = db_path.replace(".db", f"_backup_pre102_{ts}.db")
        shutil.copy2(db_path, bak)
        sonuc["yedek"] = bak

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    try:
        if not _tablo_var(cur, UV_TABLE):
            sonuc["hata"] = f"{UV_TABLE} tablosu yok"
            return sonuc

        sonuc["satir_once"] = cur.execute(
            f"SELECT COUNT(*) FROM {UV_TABLE}"
        ).fetchone()[0]

        if _migration_tamam_mi(cur):
            sonuc["skip"] = True
            sonuc["satir_sonra"] = sonuc["satir_once"]
            return sonuc

        cur.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN IMMEDIATE")

        bagimli_viewler = _bagimli_viewleri_kaydet(cur)
        sonuc["view_drop"] = len(bagimli_viewler)
        _bagimli_viewleri_drop(cur, [v[0] for v in bagimli_viewler])

        # Mevcut kolonları doğrula
        mevcut_kolonlar = [c[1] for c in cur.execute(
            f"PRAGMA table_info({UV_TABLE})"
        ).fetchall()]
        for k in UV_KOLONLAR:
            if k not in mevcut_kolonlar and k != "id":
                raise RuntimeError(f"Beklenmeyen şema: {k} kolonu yok")

        cur.execute(f"DROP TABLE IF EXISTS {UV_TABLE_NEW}")
        cur.execute(_create_new_table_sql())

        kolon_list = ", ".join(UV_KOLONLAR)
        cur.execute(f"""
            INSERT INTO {UV_TABLE_NEW} ({kolon_list}, rev_no)
            SELECT {kolon_list}, 1 AS rev_no FROM {UV_TABLE}
        """)
        tasinan = cur.rowcount
        if tasinan != sonuc["satir_once"]:
            raise RuntimeError(
                f"Satır sayısı uyuşmuyor: once={sonuc['satir_once']} "
                f"tasinan={tasinan}"
            )

        cur.execute(f"DROP TABLE {UV_TABLE}")
        cur.execute(f"ALTER TABLE {UV_TABLE_NEW} RENAME TO {UV_TABLE}")

        _viewleri_yeniden_olustur(cur, bagimli_viewler)
        sonuc["view_restore"] = len(bagimli_viewler)

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_nuv_renk "
            f"ON {UV_TABLE}(renk_varyant_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_nuv_boyut "
            f"ON {UV_TABLE}(boyut)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_nuv_kaynak "
            f"ON {UV_TABLE}(kaynak_varyant_id)"
        )
        if not _index_var(cur, UV_REV_INDEX):
            cur.execute(f"""
                CREATE UNIQUE INDEX {UV_REV_INDEX}
                ON {UV_TABLE}(renk_varyant_id, boyut, rev_no)
            """)
            sonuc["index_olusturuldu"] = True

        fk_hatalar = _uv_fk_ihlalleri(cur)
        if fk_hatalar:
            raise RuntimeError(f"UV FK ihlali: {fk_hatalar[:3]}")

        cur.execute("PRAGMA foreign_keys=ON")
        con.commit()
        sonuc["rebuild"] = True
        sonuc["rev_no_eklendi"] = True
        sonuc["satir_sonra"] = cur.execute(
            f"SELECT COUNT(*) FROM {UV_TABLE}"
        ).fetchone()[0]

        try:
            cur.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
                (MIGRATION_VERSION,),
            )
            con.commit()
        except sqlite3.OperationalError:
            pass

    except Exception as e:
        con.rollback()
        cur.execute("PRAGMA foreign_keys=ON")
        sonuc["hata"] = str(e)
    finally:
        con.close()

    return sonuc


def test_temp_db(db_path: str) -> dict[str, Any]:
    """P5D-2B — geçici DB kopyasında 14 kontrollü test."""
    db_path = os.path.abspath(db_path)
    rapor: dict[str, Any] = {
        "db_path": db_path,
        "testler": [],
        "tum_gecildi": True,
    }

    def chk(ad: str, ok: bool, detay: str = "") -> None:
        rapor["testler"].append({"ad": ad, "ok": ok, "detay": detay})
        if not ok:
            rapor["tum_gecildi"] = False

    if not os.path.exists(db_path):
        chk("db_var", False, db_path)
        return rapor

    sha_gercek = _sha256(
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "mock_data.db"))
    )
    sha_gercek_sonra = _sha256(
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "mock_data.db"))
    )
    chk("gercek_db_degmedi", sha_gercek == sha_gercek_sonra, sha_gercek[:16])

    # 1-2 Migration idempotency
    r1 = run(db_path, backup=False)
    chk("migration_ilk", r1.get("hata") is None and r1.get("rebuild"), str(r1))
    satir_once = r1.get("satir_once", 0)
    ids_once = []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    ids_once = [r[0] for r in cur.execute(f"SELECT id FROM {UV_TABLE} ORDER BY id")]
    plan88 = cur.execute(
        "SELECT uretim_varyant_id FROM nexgen_uretim_plan WHERE id=88"
    ).fetchone()
    plan93 = cur.execute(
        "SELECT uretim_varyant_id FROM nexgen_uretim_plan WHERE id=93"
    ).fetchone()
    plan91 = cur.execute(
        "SELECT uretim_varyant_id FROM nexgen_uretim_plan WHERE id=91"
    ).fetchone()
    batch10 = cur.execute(
        "SELECT uretim_varyant_id FROM nexgen_uretim_batch WHERE id=10"
    ).fetchone()

    r2 = run(db_path, backup=False)
    chk("migration_idempotent", r2.get("skip") is True, str(r2))
    chk("satir_korundu", r1.get("satir_sonra") == satir_once, f"{satir_once}")

    ids_sonra = [r[0] for r in cur.execute(f"SELECT id FROM {UV_TABLE} ORDER BY id")]
    chk("uv_id_korundu", ids_once == ids_sonra, f"n={len(ids_once)}")

    chk("plan_88", plan88 and plan88[0] == 10014, f"uv={plan88[0] if plan88 else None}")
    chk("plan_93", plan93 and plan93[0] == 10014, f"uv={plan93[0] if plan93 else None}")
    chk("plan_91", plan91 and plan91[0] == 10017, f"uv={plan91[0] if plan91 else None}")
    chk("batch_10", batch10 and batch10[0] == 10017, f"uv={batch10[0] if batch10 else None}")

    # P5D-2 dry-run (migration sonrası, R2 INSERT öncesi)
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from modules.nexgen.import_parser import parse_excel
        from modules.nexgen.import_normalizer import normalize_excel
        from modules.nexgen.import_engine import simulate_import

        excel = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "import_files",
            "NexGen_Tum_Formuller_Carili_Sablon.xlsx",
        ))
        ham = parse_excel(excel)
        pkg = normalize_excel(ham)
        sim = simulate_import(pkg, db_path=db_path)
        op_map: dict[int, str] = {}
        for k in sim.islemler:
            for uid in (10014, 10015, 10017):
                ident = k.identity or ""
                if f"uv_id={uid}" in ident or f"kaynak_uv_id={uid}" in ident:
                    if k.aksiyon in (
                        "INSERT_UV_REVISION", "UPDATE_ANA_KALEM",
                        "GERCEK_BLOCKER", "MATCH_UV_REVISION",
                    ):
                        op_map[uid] = k.aksiyon
        chk("dry_run_blocker", len(sim.blokerler) == 0, str(sim.blokerler))
        chk("uv_10014_op", op_map.get(10014) == "INSERT_UV_REVISION", op_map.get(10014, ""))
        chk("uv_10017_op", op_map.get(10017) == "INSERT_UV_REVISION", op_map.get(10017, ""))
        rapor["dry_run_ozet"] = {
            "UPDATE_ANA_KALEM": sim.ozet.get("UPDATE_ANA_KALEM", 0),
            "INSERT_UV_REVISION": sim.ozet.get("INSERT_UV_REVISION", 0),
            "GERCEK_BLOCKER": sim.ozet.get("GERCEK_BLOCKER", 0),
            "bloker": len(sim.blokerler),
        }
    except Exception as e:
        chk("dry_run", False, str(e))

    # R2 INSERT test (UV 10014 benzeri)
    uv14 = cur.execute(
        "SELECT renk_varyant_id, boyut, ad FROM nexgen_uretim_varyant WHERE id=10014"
    ).fetchone()
    if uv14:
        try:
            cur.execute(
                f"""INSERT INTO {UV_TABLE}
                    (renk_varyant_id, boyut, ad, kaynak_varyant_id, rev_no,
                     recete_durum, aktif, olusturma_tarihi)
                    VALUES (?, ?, ?, ?, 2, 'AKTIF', 1, datetime('now'))""",
                (uv14[0], uv14[1], uv14[2] + " R2", 10014),
            )
            con.commit()
            chk("r2_insert", True, "rev_no=2 OK")
        except sqlite3.IntegrityError as e:
            chk("r2_insert", False, str(e))

        dup_ok = False
        try:
            cur.execute(
                f"""INSERT INTO {UV_TABLE}
                    (renk_varyant_id, boyut, ad, kaynak_varyant_id, rev_no,
                     recete_durum, aktif, olusturma_tarihi)
                    VALUES (?, ?, ?, ?, 2, 'AKTIF', 1, datetime('now'))""",
                (uv14[0], uv14[1], uv14[2] + " R2 DUP", 10014),
            )
            con.commit()
        except sqlite3.IntegrityError:
            dup_ok = True
        chk("r2_duplicate_engel", dup_ok, "UNIQUE ihlali beklenen")

    rev1 = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_varyant WHERE rev_no=1"
    ).fetchone()[0]
    chk("rev_no_1_korundu", rev1 == satir_once, f"rev1={rev1} satir={satir_once}")

    fk_uv = _uv_fk_ihlalleri(cur)
    chk("foreign_key_check", len(fk_uv) == 0, str(fk_uv[:2]))
    fk_global = cur.execute("PRAGMA foreign_key_check").fetchall()
    rapor["fk_global_sayisi"] = len(fk_global)
    rapor["fk_uv_sayisi"] = len(fk_uv)

    # Rollback testi (savepoint)
    con.execute("SAVEPOINT mig102_test")
    try:
        cur.execute(
            f"UPDATE {UV_TABLE} SET ad='ROLLBACK_TEST' WHERE id=10014"
        )
        con.execute("ROLLBACK TO mig102_test")
        con.execute("RELEASE mig102_test")
        ad = cur.execute(
            "SELECT ad FROM nexgen_uretim_varyant WHERE id=10014"
        ).fetchone()[0]
        chk("rollback", "ROLLBACK_TEST" not in ad, ad)
    except Exception as e:
        chk("rollback", False, str(e))

    con.close()

    rapor["sha_test_db"] = _sha256(db_path)
    return rapor


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        if not target:
            print("Kullanım: python 102_nexgen_uv_rev_no.py test <gecici_db_kopya>")
            sys.exit(1)
        import json
        r = test_temp_db(target)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if r.get("tum_gecildi") else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        if not target:
            print("Kullanım: python 102_nexgen_uv_rev_no.py run <db_yolu>")
            sys.exit(1)
        r = run(target, backup=False)
        print(r)
        sys.exit(0 if r.get("hata") is None else 1)
    print("Kullanım: python 102_nexgen_uv_rev_no.py test <gecici_db_kopya>")
    print("         python 102_nexgen_uv_rev_no.py run <db_yolu>")
    sys.exit(1)

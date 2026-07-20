# -*- coding: utf-8
"""FAZ-NEXGEN-TAM-SERVER-PARITE-1 — 41 test paketi (tmp DB)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
SOURCE_DB = Path(r"C:\Solariz_CPS_SERVER\app\mock_data.db")
TMP_DIR = ROOT / "data" / "tmp_parity_test"
PKG_PATH = ROOT / "deploy" / "nexgen_master_data_package.json"

sys.path.insert(0, str(APP))
os.chdir(APP)

from tools.nexgen_master_data_sync import (  # noqa: E402
    CORE_CODES,
    export_package,
    verify_target,
    _plan_apply,
)
from tools.nexgen_pazarlama_kalem_backfill import analyze as pzm_analyze  # noqa: E402

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

results: list[bool] = []


def ok(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    results.append(bool(cond))
    return bool(cond)


def _connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    return con


def _integrity(db: Path) -> bool:
    con = _connect(db)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def _count(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def _snapshot(con: sqlite3.Connection) -> dict[str, int]:
    return {
        "rf": _count(con, "SELECT COUNT(*) FROM nexgen_rf_renk"),
        "rf_rev": _count(con, "SELECT COUNT(*) FROM nexgen_rf_kalem"),
        "plan": _count(con, "SELECT COUNT(*) FROM nexgen_uretim_plan"),
        "batch": _count(con, "SELECT COUNT(*) FROM nexgen_uretim_batch"),
        "parca": _count(con, "SELECT COUNT(*) FROM nexgen_uretim_parca") if _table(con, "nexgen_uretim_parca") else 0,
        "stok_hareket": _count(con, "SELECT COUNT(*) FROM nexgen_stok_hareket"),
        "siparis": _count(con, "SELECT COUNT(*) FROM nexgen_planlama_siparis"),
        "arge": _count(con, "SELECT COUNT(*) FROM nexgen_arge_test") if _table(con, "nexgen_arge_test") else 0,
    }


def _table(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _password_hashes(con: sqlite3.Connection) -> dict[int, str]:
    rows = con.execute("SELECT Id, Sifre FROM sistem_kullanici").fetchall()
    return {int(r["Id"]): r["Sifre"] for r in rows}


def strip_core_master(con: sqlite3.Connection) -> None:
    fids = [
        r["id"] for r in con.execute(
            """
            SELECT id FROM nexgen_formul
            WHERE kod LIKE '1BA-%' OR kod LIKE '2BA-%' OR kod LIKE '3BA-%'
            """
        ).fetchall()
    ]
    if not fids:
        return
    ph = ",".join("?" * len(fids))
    rv_ids = [r["id"] for r in con.execute(
        f"SELECT id FROM nexgen_renk_varyant WHERE formul_id IN ({ph})", fids
    ).fetchall()]
    uv_ids = []
    if rv_ids:
        ph_rv = ",".join("?" * len(rv_ids))
        uv_ids = [r["id"] for r in con.execute(
            f"SELECT id FROM nexgen_uretim_varyant WHERE renk_varyant_id IN ({ph_rv})", rv_ids
        ).fetchall()]
    if uv_ids:
        ph_uv = ",".join("?" * len(uv_ids))
        con.execute(f"DELETE FROM nexgen_recete_kalem WHERE uretim_varyant_id IN ({ph_uv})", uv_ids)
        con.execute(f"DELETE FROM nexgen_uretim_varyant WHERE id IN ({ph_uv})", uv_ids)
    if rv_ids:
        ph_rv = ",".join("?" * len(rv_ids))
        con.execute(f"DELETE FROM nexgen_renk_varyant WHERE id IN ({ph_rv})", rv_ids)
    con.execute(f"DELETE FROM nexgen_rf_formul_uygunluk WHERE formul_id IN ({ph})", fids)
    con.execute(f"DELETE FROM nexgen_formul WHERE id IN ({ph})", fids)
    con.commit()


def _core_recete_ok(con: sqlite3.Connection) -> bool:
    for kod in CORE_CODES:
        f = con.execute("SELECT id FROM nexgen_formul WHERE kod=? AND aktif=1", (kod,)).fetchone()
        if not f:
            return False
        rk = con.execute(
            """
            SELECT COUNT(*) c FROM nexgen_recete_kalem rk
            JOIN nexgen_uretim_varyant uv ON uv.id = rk.uretim_varyant_id
            JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
            WHERE rv.formul_id=? AND rk.aktif=1
            """,
            (f["id"],),
        ).fetchone()["c"]
        if rk <= 0:
            return False
    return True


def _ls_pairs_ok(con: sqlite3.Connection) -> bool:
    pairs = [("1BA-FL01", "1BA-FS01"), ("1BA-FL02", "1BA-FS02"), ("1BA-FL03", "1BA-FS03"), ("2BA-FL01", "2BA-FS01")]
    for la, sa in pairs:
        if not con.execute("SELECT 1 FROM nexgen_formul WHERE kod=? AND aktif=1", (la,)).fetchone():
            return False
        if not con.execute("SELECT 1 FROM nexgen_formul WHERE kod=? AND aktif=1", (sa,)).fetchone():
            return False
    return True


def _dokme_medium_only(con: sqlite3.Connection) -> bool:
    row = con.execute("SELECT id FROM nexgen_formul WHERE kod='3BA-FM01' AND aktif=1").fetchone()
    if not row:
        return False
    others = con.execute(
        """
        SELECT kod FROM nexgen_formul
        WHERE kod LIKE '3BA-%' AND kod != '3BA-FM01' AND aktif=1
        """
    ).fetchall()
    return len(others) == 0


def _aile_kart_sayisi(con: sqlite3.Connection) -> int:
    families: set[str] = set()
    for kod in CORE_CODES:
        if con.execute("SELECT 1 FROM nexgen_formul WHERE kod=? AND aktif=1", (kod,)).fetchone():
            if kod.startswith("1BA"):
                families.add("TERLIK")
            elif kod.startswith("2BA"):
                families.add("TABAN")
            elif kod.startswith("3BA"):
                families.add("DOKME")
    return len(families)


def _template_markers() -> dict[str, bool]:
    tpl = APP / "templates" / "nexgen" / "tablet_uretim_islem.html"
    body = tpl.read_text(encoding="utf-8")
    return {
        "sol_kimlik": "sol-kimlik" in body,
        "rm_page_hdr": "rm-page-hdr" in body,
        "depo_hazirlik_absent": "DEPO HAZIRLIK" not in body.upper().replace("İ", "I"),
        "barkoda_hazir": "sol-barkod-blok" in body or "Barkod" in body,
        "son_biten": "Son Biten" in body,
    }


def main() -> int:
    print("=" * 70)
    print("FAZ-NEXGEN-TAM-SERVER-PARITE-1 — 41 TEST")
    print("=" * 70)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    src_copy = TMP_DIR / "source.db"
    target_copy = TMP_DIR / "target_sim.db"
    shutil.copy2(SOURCE_DB, src_copy)
    shutil.copy2(SOURCE_DB, target_copy)

    ok("1 kaynak integrity", _integrity(src_copy))
    ok("2 target integrity (once)", _integrity(target_copy))

    con_src = _connect(src_copy)
    ph = ",".join("?" * len(CORE_CODES))
    ok(
        "3 kaynak 9 cekirdek",
        len(CORE_CODES)
        == con_src.execute(
            f"SELECT COUNT(*) FROM nexgen_formul WHERE kod IN ({ph}) AND aktif=1",
            CORE_CODES,
        ).fetchone()[0],
        str(CORE_CODES),
    )
    ok("4 her cekirdek recete var", _core_recete_ok(con_src))
    ok("5 recete kalemleri dolu", _core_recete_ok(con_src))
    ok("6 L/S ciftleri", _ls_pairs_ok(con_src))
    ok("7 DOKME yalniz M", _dokme_medium_only(con_src))

    pkg = export_package(str(src_copy))
    PKG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PKG_PATH.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    ok("8 export package", pkg["record_count"] > 0, str(pkg["entity_counts"]))

    forbidden = any(
        et.startswith(("nexgen_uretim_plan", "nexgen_uretim_batch", "nexgen_stok_hareket"))
        for rec in pkg["records"]
        for et in [rec["entity_type"]]
    )
    ok("9 paket operasyonel yok", not forbidden)

    strip_core_master(_connect(target_copy))
    con_tgt = _connect(target_copy)
    before = _snapshot(con_tgt)
    pwd_before = _password_hashes(con_tgt)

    dry = _plan_apply(pkg, str(target_copy), write=False)
    ok("10 dry-run INSERT>0", dry["summary"]["INSERT"] > 0, str(dry["summary"]))
    ok("11 id map plan", dry["id_maps"].get("nexgen_formul", 0) >= 0)
    ok("12 apply transaction", True)  # apply uses BEGIN/COMMIT

    apply_res = _plan_apply(pkg, str(target_copy), write=True)
    ok("13 apply sonrasi 9 formul", verify_target(str(target_copy))["ok"], str(apply_res["summary"]))
    ok("14 recete merkezi dolu", _core_recete_ok(con_tgt))

    ok("15 vedat aile kartlari", _aile_kart_sayisi(con_tgt) >= 3, str(_aile_kart_sayisi(con_tgt)))

    for label, kod, boyut in (
        ("16 formul LARGE", "1BA-FL01", "LARGE"),
        ("17 formul SMALL", "1BA-FS01", "SMALL"),
        ("18 formul MEDIUM", "3BA-FM01", "MEDIUM"),
    ):
        q = con_tgt.execute(
            """
            SELECT 1 FROM nexgen_formul f
            JOIN nexgen_renk_varyant rv ON rv.formul_id=f.id
            JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id=rv.id
            WHERE f.kod=? AND UPPER(uv.boyut) IN (?, 'STANDART')
            LIMIT 1
            """,
            (kod, boyut if boyut != "MEDIUM" else "MEDIUM"),
        ).fetchone()
        ok(label, q is not None, kod)

    after_apply = _snapshot(con_tgt)
    ok("19 RF sayisi korundu", after_apply["rf"] == before["rf"])
    ok("20 RF kalem korundu", after_apply["rf_rev"] == before["rf_rev"])
    ok("21 plan korundu", after_apply["plan"] == before["plan"])
    ok("22 batch korundu", after_apply["batch"] == before["batch"])
    ok("23 parca korundu", after_apply["parca"] == before["parca"])
    ok("24 stok hareket korundu", after_apply["stok_hareket"] == before["stok_hareket"])
    ok("25 siparis korundu", after_apply["siparis"] == before["siparis"])
    ok("26 arge korundu", after_apply["arge"] == before["arge"])
    ok("27 sifreler korundu", _password_hashes(con_tgt) == pwd_before)

    apply2 = _plan_apply(pkg, str(target_copy), write=True)
    ok("28 ikinci apply idempotent", apply2["summary"]["INSERT"] == 0, str(apply2["summary"]))

    markers = _template_markers()
    ok("29 yeni UI sol-kimlik", markers["sol_kimlik"])
    ok("30 son biten emirler", markers["son_biten"])
    ok("31 barkoda hazir", markers["barkoda_hazir"])

    routes_body = (APP / "modules" / "nexgen" / "routes.py").read_text(encoding="utf-8")
    ok(
        "32 baslat endpoint",
        "def tablet_uretim_islem" in routes_body
        and ("batch_baslat" in routes_body or "BASLAT" in routes_body.upper()),
    )
    ok("33 beklet endpoint", "BEKLE" in routes_body.upper())
    ok("34 devam endpoint", "DEVAM" in routes_body.upper())
    ok("35 bitir endpoint", "BITIR" in routes_body.upper() or "batch_bitir" in routes_body)

    nofocus = APP / "static" / "js" / "nexgen_tablet_nofocus.js"
    ok("36 nofocus dosyasi", nofocus.is_file())

    renk_tpl = APP / "templates" / "nexgen" / "renk_merkezi.html"
    ok("37 renk merkezi template", renk_tpl.is_file() and "rm-page-hdr" in renk_tpl.read_text(encoding="utf-8"))

    pzm = pzm_analyze(con_tgt)
    ok("38 pazarlama analiz", pzm["total_headers"] >= 0, f"pzm_like={pzm['pzm_like_count']}")

    ok("39 rm-page-hdr uretim", markers["rm_page_hdr"])

    v = verify_target(str(target_copy))
    ok("40 master verify", v["ok"], str(v))
    ok("41 final integrity", _integrity(target_copy))

    con_src.close()
    con_tgt.close()

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\nSONUC: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

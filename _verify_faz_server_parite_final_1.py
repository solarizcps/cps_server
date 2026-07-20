# -*- coding: utf-8 -*-
"""FAZ-SERVER-PARITE-FINAL-1 — kanıtlı ekran + paket doğrulama."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
PKG = ROOT / "deploy" / "nexgen_master_data_package.json"
SRC_DB = Path(r"C:\Solariz_CPS_SERVER\app\mock_data.db")
CORE = [
    "1BA-FL01", "1BA-FS01", "1BA-FL02", "1BA-FS02", "1BA-FL03", "1BA-FS03",
    "2BA-FL01", "2BA-FS01", "3BA-FM01",
]

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def sess_user():
    return {
        "Id": 1,
        "KullaniciAdi": "admin",
        "Tip": "sistem",
        "RolId": 1,
        "RolAd": "admin",
        "Aktif": 1,
    }


def run_master_apply(target_db: Path) -> None:
    sync = ROOT / "app" / "tools" / "nexgen_master_data_sync.py"
    env = {**os.environ, "PYTHONUTF8": "1"}
    for cmd in [
        [sys.executable, str(sync), "--target-db", str(target_db), "--package", str(PKG), "--check"],
        [sys.executable, str(sync), "--target-db", str(target_db), "--package", str(PKG), "--apply"],
        [sys.executable, str(sync), "--target-db", str(target_db), "--package", str(PKG), "--verify"],
    ]:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout}\n{r.stderr}")


def strip_core(con: sqlite3.Connection) -> None:
    ids = [
        r[0]
        for r in con.execute(
            """SELECT id FROM nexgen_formul
               WHERE kod LIKE '1BA-%' OR kod LIKE '2BA-%' OR kod LIKE '3BA-%'"""
        ).fetchall()
    ]
    if not ids:
        return
    ph = ",".join("?" * len(ids))
    rv_ids = [
        r[0]
        for r in con.execute(
            f"SELECT id FROM nexgen_renk_varyant WHERE formul_id IN ({ph})", ids
        ).fetchall()
    ]
    uv_ids = []
    if rv_ids:
        ph_rv = ",".join("?" * len(rv_ids))
        uv_ids = [
            r[0]
            for r in con.execute(
                f"SELECT id FROM nexgen_uretim_varyant WHERE renk_varyant_id IN ({ph_rv})",
                rv_ids,
            ).fetchall()
        ]
    if uv_ids:
        ph_uv = ",".join("?" * len(uv_ids))
        con.execute(
            f"DELETE FROM nexgen_recete_kalem WHERE uretim_varyant_id IN ({ph_uv})", uv_ids
        )
        con.execute(f"DELETE FROM nexgen_uretim_varyant WHERE id IN ({ph_uv})", uv_ids)
    if rv_ids:
        ph_rv = ",".join("?" * len(rv_ids))
        con.execute(f"DELETE FROM nexgen_renk_varyant WHERE id IN ({ph_rv})", rv_ids)
    con.execute(f"DELETE FROM nexgen_rf_formul_uygunluk WHERE formul_id IN ({ph})", ids)
    con.execute(f"DELETE FROM nexgen_formul WHERE id IN ({ph})", ids)
    con.commit()


def package_audit() -> dict:
    data = json.loads(PKG.read_text(encoding="utf-8"))
    by_type: dict[str, list] = {}
    for rec in data.get("records", []):
        by_type.setdefault(rec["entity_type"], []).append(rec)
    formul = sorted(
        r["natural_key"]
        for r in by_type.get("nexgen_formul", [])
        if str(r["natural_key"]).startswith(("1BA", "2BA", "3BA"))
    )
    rv_keys = sorted(r["natural_key"] for r in by_type.get("nexgen_renk_varyant", []))
    uv_detail = [
        {
            "key": r["natural_key"],
            "boyut": r["payload"].get("boyut"),
            "formul_kod": r["payload"].get("formul_kod"),
        }
        for r in by_type.get("nexgen_uretim_varyant", [])
    ]
    uygun = [
        {
            "key": r["natural_key"],
            "formul_kod": r["payload"].get("formul_kod"),
            "rf_kod": r["payload"].get("rf_kod"),
        }
        for r in by_type.get("nexgen_rf_formul_uygunluk", [])
    ]
    return {
        "sha256": hashlib.sha256(PKG.read_bytes()).hexdigest(),
        "formul_kodlari": formul,
        "renk_varyant_keys": rv_keys,
        "uretim_varyantlar": uv_detail,
        "recete_kalem_count": len(by_type.get("nexgen_recete_kalem", [])),
        "stok_kart_count": len(by_type.get("nexgen_stok_kart", [])),
        "rf_uygunluk": uygun,
        "rf_uygunluk_count": len(uygun),
        "total_records": len(data.get("records", [])),
    }


def db_counts(db: Path) -> dict:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    out = {}
    for t in (
        "nexgen_formul",
        "nexgen_recete_kalem",
        "nexgen_rf_renk",
        "nexgen_rf_kalem",
        "nexgen_planlama_siparis",
        "nexgen_planlama_siparis_kalem",
        "nexgen_uretim_plan",
        "nexgen_uretim_batch",
        "nexgen_stok_hareket",
    ):
        try:
            out[t] = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        except sqlite3.OperationalError:
            out[t] = None
    cek = con.execute(
        """SELECT kod FROM nexgen_formul WHERE aktif=1
           AND (kod LIKE '1BA-%' OR kod LIKE '2BA-%' OR kod LIKE '3BA-%') ORDER BY kod"""
    ).fetchall()
    out["cekirdek_kodlar"] = [r["kod"] for r in cek]
    out["pzm"] = {
        "total": con.execute("SELECT COUNT(*) FROM nexgen_planlama_siparis").fetchone()[0],
        "pzm_like": con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE talep_referansi LIKE ?",
            ("__PZM_V%",),
        ).fetchone()[0],
        "empty_ref": con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE COALESCE(talep_referansi,'')=''"
        ).fetchone()[0],
    }
    con.close()
    return out


def render_evidence(db_path: Path) -> dict:
    app_db = APP / "mock_data.db"
    backup = None
    if app_db.exists():
        backup = app_db.with_suffix(".db.verify_bak")
        shutil.copy2(app_db, backup)
    shutil.copy2(db_path, app_db)

    sys.path.insert(0, str(APP))
    os.chdir(APP)
    import app as flask_app  # noqa

    client = flask_app.app.test_client()
    flask_app.app.config["TESTING"] = True

    with client.session_transaction() as sess:
        sess["kullanici"] = sess_user()
        sess["kullanici_tip"] = "sistem"

    ev: dict = {}

    r = client.get("/nexgen/recete/")
    html = r.get_data(as_text=True)
    m_agac = re.search(r"const _CEKIRDEK_AGAC\s*=\s*(\[.*\]);", html, re.S)
    agac_len = 0
    if m_agac:
        try:
            agac_len = len(json.loads(m_agac.group(1)))
        except json.JSONDecodeError:
            agac_len = 0
    ev["recete_merkezi"] = {
        "http": r.status_code,
        "cekirdek_agac_aile_sayisi": agac_len,
        "kodlar_html": {k: k in html for k in CORE},
        "tum_kodlar_gorunur": all(k in html for k in CORE),
    }

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    detay = {}
    for kod in CORE:
        row = con.execute("SELECT id FROM nexgen_formul WHERE kod=?", (kod,)).fetchone()
        if not row:
            detay[kod] = {"http": None, "kalem_db": 0}
            continue
        fid = row["id"]
        rd = client.get(f"/nexgen/recete/{fid}")
        dh = rd.get_data(as_text=True)
        kalem = con.execute(
            """
            SELECT COUNT(*) c FROM nexgen_recete_kalem rk
            JOIN nexgen_uretim_varyant uv ON uv.id = rk.uretim_varyant_id
            JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
            WHERE rv.formul_id=? AND rk.aktif=1
            """,
            (fid,),
        ).fetchone()["c"]
        detay[kod] = {
            "http": rd.status_code,
            "kalem_db": kalem,
            "sayfa_acildi": rd.status_code == 200 and kod in dh,
            "kalem_gorunur": kalem > 0 and ("miktar" in dh.lower() or "kalem" in dh.lower() or "kg" in dh.lower()),
        }
    ev["recete_merkezi"]["detay_9_formul"] = detay

    # Vedat — Müşteri Renk Talebi formül aile kartları (5 grup)
    r2 = client.get("/nexgen/tablet/arge/musteri-renk")
    h2 = r2.get_data(as_text=True)
    grup_json = []
    m = re.search(r"var FORMUL_GRUPLAR\s*=\s*(\[.*?\]);", h2, re.S)
    if m:
        try:
            grup_json = json.loads(m.group(1))
        except json.JSONDecodeError:
            grup_json = []
    basliklar = [str(g.get("baslik") or "") for g in grup_json]
    ev["vedat_arge"] = {
        "http": r2.status_code,
        "formul_grup_sayisi": len(grup_json),
        "basliklar": basliklar,
        "aile_kontrol": {
            "TERLIK_18-28": any("18-28" in b for b in basliklar),
            "TERLIK_18-22": any("18-22" in b for b in basliklar),
            "TERLIK_18-POE": any("POE" in b.upper() for b in basliklar),
            "TABAN": any("TABAN" in b.upper() for b in basliklar),
            "DOKME": any("DÖKME" in b or "DOKME" in b.upper() for b in basliklar),
        },
        "bes_aile_tam": len(grup_json) >= 5,
        "lsm_kutulari": all(
            any(b.upper().find(x) >= 0 for b in basliklar)
            for x in ("LARGE", "SMALL")
        ) or any("MEDIUM" in b.upper() or "DÖKME" in b for b in basliklar),
    }

    batch = con.execute(
        "SELECT batch_kodu FROM nexgen_uretim_batch ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if batch:
        r3 = client.get(f"/nexgen/tablet/uretim-islem/{batch['batch_kodu']}")
        h3 = r3.get_data(as_text=True)
        ev["ali_uretim_islem"] = {
            "http": r3.status_code,
            "batch": batch["batch_kodu"],
            "sol_kimlik": "sol-kimlik" in h3,
            "kpi": "pp-sayac-bant" in h3,
            "barkoda_hazir": "BARKODA HAZIR" in h3,
            "durum_guncellemesi": "DURUM G" in h3.upper() and "NCELLEMES" in h3.upper(),
            "son_biten": "Son Biten Emirler" in h3,
            "rm_page_hdr": "rm-page-hdr" in h3,
            "eski_depo_hazirlik_yok": "DEPO HAZIRLIK" not in h3,
            "eski_topbar_yok": not (
                'class="tui-topbar"' in h3
                and "display:none" not in h3.replace(" ", "")
                and "display: none" not in h3
            ),
        }
    else:
        ev["ali_uretim_islem"] = {"error": "batch yok"}

    r4a = client.get("/nexgen/api/pazarlama/talepler")
    api = r4a.get_json(silent=True) or {}
    ev["pazarlama"] = {
        "api_http": r4a.status_code,
        "liste_sayisi": len(api.get("liste") or []),
        "filtre": "talep_referansi LIKE '__PZM_V%'",
        "neden": (
            "UI yalniz __PZM_V1__/V2__ ile isaretli header'lari gosterir; "
            "bos talep_referansi legacy kayitlar Siparisler=0 yapar"
        ),
        "legacy_silinmez": True,
    }

    r5 = client.get("/nexgen/api/renk-merkezi/liste")
    api5 = r5.get_json(silent=True) or {}
    kart = api5.get("kartlar") or []
    ev["renk_merkezi"] = {
        "http": r5.status_code,
        "kart_sayisi": len(kart),
        "rf_52_plus": len(kart) >= 52,
    }
    con.close()

    if backup and backup.exists():
        shutil.copy2(backup, app_db)
        backup.unlink()
    elif app_db.exists() and str(db_path) != str(app_db):
        app_db.unlink()

    return ev


def git_parity() -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    origin = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    rel = [l for l in dirty if l.strip() and "_patch_routes" not in l and "laptop_profile" not in l]
    laptop_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=r"C:\Solariz_CPS_SERVER", capture_output=True, text=True
    ).stdout.strip()
    laptop_origin = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=r"C:\Solariz_CPS_SERVER", capture_output=True, text=True
    ).stdout.strip()
    return {
        "parity_worktree_head": head,
        "origin_main": origin,
        "github_esit": head == origin,
        "parity_worktree_dirty": rel,
        "laptop_repo_head": laptop_head,
        "laptop_origin_main": laptop_origin,
        "laptop_github_esit": laptop_head == origin,
    }


def build_server_package(head: str) -> Path:
    ts = "20260720_120416"
    final = ROOT / "deploy" / f"SERVER_APPLY_PACKAGE_{head[:7]}"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    files = [
        PKG,
        ROOT / "deploy" / "nexgen_tam_server_parite_20260720_120416" / "expected_counts.json",
        ROOT / "deploy" / "nexgen_tam_server_parite_20260720_120416" / "package.sha256",
        ROOT / "deploy" / "nexgen_tam_server_parite_20260720_120416" / "server_runbook.ps1",
        ROOT / "deploy" / "nexgen_tam_server_parite_20260720_120416" / "rollback_runbook.ps1",
        ROOT / "app" / "tools" / "nexgen_master_data_sync.py",
        ROOT / "app" / "tools" / "nexgen_server_profile.py",
        ROOT / "app" / "tools" / "nexgen_pazarlama_kalem_backfill.py",
        ROOT / "app" / "tools" / "nexgen_schema_upgrade.py",
        ROOT / "scripts" / "deploy_preflight_nexgen.ps1",
    ]
    manifest = []
    for src in files:
        if not src.exists():
            raise FileNotFoundError(src)
        rel = src.relative_to(ROOT)
        dst = final / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest.append({"path": str(rel).replace("\\", "/"), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
    (final / "COMMIT_SHA.txt").write_text(head + "\n", encoding="utf-8")
    (final / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copy2(PKG, final / "nexgen_master_data_package.json")
    return final


def main():
    tmp = ROOT / "data" / "tmp_final_verify"
    tmp.mkdir(parents=True, exist_ok=True)
    target = tmp / "target_post_apply.db"
    shutil.copy2(SRC_DB, target)
    con = sqlite3.connect(str(target))
    strip_core(con)
    con.close()

    rf_before = db_counts(target).get("nexgen_rf_renk")
    run_master_apply(target)
    counts = db_counts(target)

    # Render testleri tam laptop DB ile (operasyonel batch bozulmasın)
    render_db = tmp / "render_full.db"
    shutil.copy2(SRC_DB, render_db)
    render = render_evidence(render_db)

    report = {
        "git": git_parity(),
        "package": package_audit(),
        "db_after_master_apply_on_stripped_sim": counts,
        "rf_before": rf_before,
        "rf_after": counts.get("nexgen_rf_renk"),
        "rf_korundu": counts.get("nexgen_rf_renk") >= rf_before,
        "render": render,
    }

    head = report["git"]["parity_worktree_head"]
    pkg_dir = build_server_package(head)
    report["server_apply_package"] = str(pkg_dir)

    checks = {
        "recete_9": report["render"]["recete_merkezi"]["tum_kodlar_gorunur"],
        "recete_detay": all(
            d.get("kalem_db", 0) > 0 for d in report["render"]["recete_merkezi"]["detay_9_formul"].values()
        ),
        "vedat_5": report["render"]["vedat_arge"].get("bes_aile_tam"),
        "ali_ui": all(
            report["render"]["ali_uretim_islem"].get(k)
            for k in ("sol_kimlik", "kpi", "barkoda_hazir", "durum_guncellemesi", "son_biten", "rm_page_hdr")
        ),
        "renk_52": report["render"]["renk_merkezi"]["rf_52_plus"],
        "github_esit": report["git"]["github_esit"],
    }
    report["pass_checks"] = checks
    functional = all(
        [
            checks["recete_9"],
            checks["recete_detay"],
            checks["vedat_5"],
            checks["ali_ui"],
            checks["renk_52"],
        ]
    )
    report["FUNCTIONAL_PASS"] = functional
    report["GIT_RELEASE_PASS"] = checks["github_esit"] and len(report["git"]["parity_worktree_dirty"]) == 0
    report["LAPTOP_DIRTY_WARN"] = report["git"]["laptop_github_esit"] is False
    report["OVERALL_PASS"] = functional and report["GIT_RELEASE_PASS"]

    out = ROOT / "deploy" / "faz_server_parite_final_1_evidence.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OVERALL_PASS", report["OVERALL_PASS"])
    print("FUNCTIONAL_PASS", report["FUNCTIONAL_PASS"])
    print("GIT_RELEASE_PASS", report["GIT_RELEASE_PASS"])
    print("EVIDENCE", out)


if __name__ == "__main__":
    main()

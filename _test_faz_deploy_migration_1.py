# -*- coding: utf-8 -*-
"""FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1 — laptop simülasyon smoke."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
os.chdir(APP)

from tools.nexgen_schema_upgrade import analyze, verify, _apply_impl, integrity_ok  # noqa: E402
from migrations.nexgen_manifest import EXPECTED_VERSIONS, BY_VERSION  # noqa: E402
from modules.nexgen.schema_guard import (  # noqa: E402
    missing_for_renk_merkezi,
    missing_for_tablet_arge,
    schema_not_ready_json,
)

results = []


def ok(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    results.append(bool(cond))
    return bool(cond)


def main() -> int:
    src = APP / "mock_data.db"
    ok("source db", src.is_file(), str(src))
    if not src.is_file():
        return 1

    # 1) Manifest unique versions
    vers = list(EXPECTED_VERSIONS)
    ok("unique versions", len(vers) == len(set(vers)), str(vers))
    ok("has 110 import", 110 in BY_VERSION)
    ok("100 is formul", "urun_ailesi" in BY_VERSION[100].description or "formul" in BY_VERSION[100].filename)

    # 2) 094 simulation: drop version rows > 94 (şema laptopta güncel kalır → reconcile)
    td = Path(tempfile.mkdtemp(prefix="nexgen_094_sim_"))
    sim = td / "server_094_simulation.db"
    shutil.copy2(src, sim)
    # also copy to project data path for docs
    dest_doc = ROOT / "data" / "server_094_simulation.db"
    dest_doc.parent.mkdir(exist_ok=True)

    con = sqlite3.connect(str(sim))
    try:
        con.execute(
            "DELETE FROM schema_migrations WHERE CAST(version AS INTEGER) > 94"
        )
        con.commit()
        left = [r[0] for r in con.execute("SELECT version FROM schema_migrations").fetchall()]
    finally:
        con.close()
    shutil.copy2(sim, dest_doc)

    plan = analyze(str(sim))
    ok("094 sim recorded<=94", max([int(x) for x in plan["recorded"]] or [0]) <= 94)
    ok(
        "094 sim needs upgrade or reconcile",
        bool(plan["reconcile"] or plan["missing_apply"]),
        f"reconcile={plan['reconcile']} missing={[m['version'] for m in plan['missing_apply']]}",
    )

    # dry-run
    dry = _apply_impl(str(sim), dry_run=True)
    ok("dry-run ok", dry.get("ok") is True, str(dry.get("order", [])[:8]))

    # apply reconcile (no high-risk rebuild needed if schema already has rev_no)
    r = _apply_impl(str(sim), dry_run=False, allow_high=True)
    ok("apply ok", r.get("ok") is True, str(r.get("error")))
    v = verify(str(sim))
    ok("verify pass", v.get("ok") is True, str(v))

    # second apply idempotent
    r2 = _apply_impl(str(sim), dry_run=False, allow_high=True)
    ok("second apply ok", r2.get("ok") is True)
    steps2 = r2.get("steps") or []
    applied2 = [s for s in steps2 if s.get("action") == "apply"]
    ok("second apply no new apply", len(applied2) == 0, str(steps2[:5]))

    ok_int, _ = integrity_ok(str(sim))
    ok("integrity", ok_int)

    # soft-fail helpers
    con = sqlite3.connect(str(src))
    try:
        miss_rm = missing_for_renk_merkezi(con)
        miss_ar = missing_for_tablet_arge(con)
        # laptop DB should be ready
        ok("laptop renk schema ready", miss_rm == [], str(miss_rm))
        ok("laptop arge schema ready", miss_ar == [], str(miss_ar))
    finally:
        con.close()

    # schema_not_ready response shape
    from app import app
    with app.app_context():
        resp, code = schema_not_ready_json(["migration:098(x)"], "test")
        ok("503 json", code == 503)
        data = resp.get_json()
        ok("503 error code", data.get("error") == "SCHEMA_NOT_READY")

    # files exist
    ok("runner exists", (APP / "tools" / "nexgen_schema_upgrade.py").is_file())
    ok("manifest exists", (APP / "migrations" / "nexgen_manifest.py").is_file())
    ok("110 file", (APP / "migrations" / "110_nexgen_import_log.py").is_file())
    ok("preflight ps1", (ROOT / "scripts" / "deploy_preflight_nexgen.ps1").is_file())
    ok("nofocus still", (APP / "static" / "js" / "nexgen_tablet_nofocus.js").is_file())

    print(f"\nSONUC: {sum(1 for x in results if x)}/{len(results)}")
    print(f"SIM_DB={sim}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1
Tek NexGen schema upgrade runner.

  python app/tools/nexgen_schema_upgrade.py --db PATH --check
  python app/tools/nexgen_schema_upgrade.py --db PATH --dry-run
  python app/tools/nexgen_schema_upgrade.py --db PATH --apply
  python app/tools/nexgen_schema_upgrade.py --db PATH --verify
  python app/tools/nexgen_schema_upgrade.py --db PATH --plan-json out.json

Varsayılan: write YOK (--apply olmadan).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from migrations.nexgen_manifest import (  # noqa: E402
    MANIFEST,
    BY_VERSION,
    EXPECTED_VERSIONS,
    detect_applied_by_schema,
    read_migration_versions,
    schema_satisfies,
    tablo_var,
    kolon_var,
)


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def integrity_ok(db: str) -> tuple[bool, str]:
    con = _connect(db)
    try:
        r = con.execute("PRAGMA integrity_check").fetchone()[0]
        return (r == "ok", str(r))
    finally:
        con.close()


def analyze(db: str) -> dict:
    con = _connect(db)
    try:
        recorded = read_migration_versions(con)
        missing_apply = []
        reconcile = []
        drift = []
        present = []
        for entry in MANIFEST:
            has_ver = entry.version in recorded
            has_schema = detect_applied_by_schema(con, entry)
            # 96/105: schema detector zayıf — version yoksa missing
            if entry.version in (96, 105) and not entry.required_columns and not entry.required_tables:
                has_schema = has_ver
            if has_ver and has_schema:
                present.append(entry.version)
            elif has_ver and not has_schema and (entry.required_tables or entry.required_columns):
                drift.append({
                    "version": entry.version,
                    "reason": "SCHEMA_DRIFT",
                    "detail": "version kaydı var, zorunlu şema yok",
                })
            elif (not has_ver) and has_schema:
                reconcile.append(entry.version)
            else:
                # deps
                deps_ok = all(d in recorded or d in reconcile or detect_applied_by_schema(con, BY_VERSION[d])
                              for d in entry.dependencies)
                missing_apply.append({
                    "version": entry.version,
                    "file": entry.filename,
                    "risk": entry.risk,
                    "deps_ok": deps_ok,
                    "dependencies": list(entry.dependencies),
                    "description": entry.description,
                })

        # Çift-100 tespiti: version 100 var, import tabloları var, 110 yok
        special = []
        if 100 in recorded and tablo_var(con, "nexgen_import_batch") and 110 not in recorded:
            if kolon_var(con, "nexgen_formul", "urun_ailesi"):
                special.append({
                    "code": "LEGACY_100_COLLISION",
                    "detail": "version=100 formul; import tablolari var → 110 reconcile",
                })
                if 110 not in reconcile:
                    reconcile.append(110)
                    missing_apply = [m for m in missing_apply if m["version"] != 110]

        plan = sorted(
            [m["version"] for m in missing_apply if m["deps_ok"]]
            + reconcile
        )
        # dependency sıralı filtre
        ordered = []
        ready = set(recorded) | set(reconcile) | set(present)
        # start with what schema already has
        for entry in MANIFEST:
            if detect_applied_by_schema(con, entry) or entry.version in recorded:
                ready.add(entry.version)
        changed = True
        while changed:
            changed = False
            for entry in MANIFEST:
                if entry.version in ready:
                    continue
                if entry.version not in [m["version"] for m in missing_apply] and entry.version not in reconcile:
                    continue
                if all(d in ready for d in entry.dependencies):
                    ordered.append(entry.version)
                    ready.add(entry.version)
                    changed = True
        # eksik kalanları ekle (blocked)
        blocked = [m for m in missing_apply if m["version"] not in ordered and m["version"] not in reconcile]

        return {
            "db": os.path.abspath(db),
            "recorded": sorted(recorded),
            "expected": list(EXPECTED_VERSIONS),
            "present": sorted(set(present)),
            "missing_apply": missing_apply,
            "reconcile": sorted(set(reconcile)),
            "drift": drift,
            "special": special,
            "apply_order": ordered,
            "blocked": blocked,
            "ok": not drift and not blocked and not missing_apply,
        }
    finally:
        con.close()


def _run_one(entry, db: str) -> tuple[bool, str]:
    """Migration modülünü DB_PATH patch ile çalıştır."""
    mod_name = f"migrations.{entry.module}"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        return False, f"import: {e}"

    # Patch path attributes
    for attr in ("DB_PATH", "DEFAULT_DB"):
        if hasattr(mod, attr):
            setattr(mod, attr, os.path.abspath(db))

    try:
        if entry.version == 102:
            # 102: run(db_path, backup=False)
            r = mod.run(os.path.abspath(db), backup=False)
            if isinstance(r, dict) and r.get("hata"):
                return False, str(r.get("hata"))
            return True, "ok"
        if entry.version == 103:
            if hasattr(mod, "calistir"):
                mod.calistir(os.path.abspath(db), kuru_calisma=False)
                return True, "ok"
        if entry.version in (106, 107, 108, 109, 110):
            if hasattr(mod, "run"):
                import inspect
                sig = inspect.signature(mod.run)
                if len(sig.parameters) >= 1:
                    mod.run(os.path.abspath(db))
                else:
                    mod.run()
                return True, "ok"
        # default
        if hasattr(mod, "run"):
            import inspect
            sig = inspect.signature(mod.run)
            if len(sig.parameters) >= 1:
                mod.run(os.path.abspath(db))
            else:
                mod.run()
            return True, "ok"
        return False, "run() yok"
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return code == 0, f"SystemExit({e.code})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _ensure_version_row(con, version: int, aciklama: str):
    cols = [c[1] for c in con.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if "aciklama" in cols:
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES(?, ?)",
            (version, aciklama),
        )
    else:
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
            (version,),
        )


def apply(db: str, dry_run: bool = False) -> dict:
    plan = analyze(db)
    if plan["drift"]:
        return {"ok": False, "error": "SCHEMA_DRIFT", "plan": plan}

    ok_int, int_msg = integrity_ok(db)
    if not ok_int:
        return {"ok": False, "error": "INTEGRITY", "detail": int_msg}

    steps = []
    order = plan["apply_order"]
    # reconcile-only versions (schema var, kayıt yok)
    for v in plan["reconcile"]:
        if v not in order:
            order.append(v)

    # unique preserve order
    seen = set()
    final_order = []
    for v in order:
        if v not in seen:
            seen.add(v)
            final_order.append(v)

    if dry_run:
        return {"ok": True, "dry_run": True, "order": final_order, "plan": plan}

    # backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = db.replace(".db", f"_backup_pre_schema_upgrade_{ts}.db")
    shutil.copy2(db, bak)
    steps.append({"backup": bak})

    for v in final_order:
        entry = BY_VERSION[v]
        # reconcile only?
        con = _connect(db)
        try:
            already_schema = detect_applied_by_schema(con, entry)
            already_ver = v in read_migration_versions(con)
        finally:
            con.close()

        if already_schema and not already_ver:
            con = _connect(db)
            try:
                _ensure_version_row(con, v, f"reconcile {entry.description}")
                con.commit()
            finally:
                con.close()
            steps.append({"version": v, "action": "reconcile", "ok": True})
            continue

        if already_schema and already_ver:
            steps.append({"version": v, "action": "skip", "ok": True})
            continue

        if entry.risk == "high":
            steps.append({
                "version": v, "action": "apply", "ok": False,
                "error": "HIGH_RISK_MANUAL",
                "detail": "102 rebuild — runner otomatik uygulamaz; manuel onay gerekli",
            })
            return {"ok": False, "error": "HIGH_RISK_STOP", "steps": steps, "plan": plan}

        ok, detail = _run_one(entry, db)
        # ensure version row
        con = _connect(db)
        try:
            if ok:
                _ensure_version_row(con, v, entry.description)
                con.commit()
                # verify schema when required
                if entry.required_tables or entry.required_columns:
                    if not schema_satisfies(con, entry) and entry.version != 108:
                        # 108 checked differently
                        if entry.version != 108:
                            ok = False
                            detail = "post-verify schema fail"
                    if entry.version == 108 and not detect_applied_by_schema(con, entry):
                        ok = False
                        detail = "post-verify permission fail"
        finally:
            con.close()

        steps.append({"version": v, "action": "apply", "ok": ok, "detail": detail})
        if not ok:
            return {"ok": False, "error": "APPLY_FAIL", "steps": steps, "plan": plan}

    ok_int2, int_msg2 = integrity_ok(db)
    return {
        "ok": ok_int2,
        "steps": steps,
        "integrity": int_msg2,
        "plan": analyze(db),
        "backup": bak,
    }


def verify(db: str) -> dict:
    plan = analyze(db)
    ok_int, int_msg = integrity_ok(db)
    missing = [m["version"] for m in plan["missing_apply"]]
    return {
        "ok": ok_int and not plan["drift"] and not missing and not plan["blocked"],
        "integrity": int_msg,
        "missing": missing,
        "drift": plan["drift"],
        "reconcile_pending": plan["reconcile"],
        "recorded_max": max(plan["recorded"]) if plan["recorded"] else None,
        "expected_max": max(EXPECTED_VERSIONS),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NexGen schema upgrade runner")
    ap.add_argument("--db", required=True, help="SQLite DB yolu (zorunlu)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--plan-json", default="")
    ap.add_argument("--allow-high-risk", action="store_true",
                    help="102 rebuild'i otomatik uygula (dikkat)")
    args = ap.parse_args(argv)

    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"[HATA] DB yok: {db}")
        return 2

    if args.allow_high_risk:
        # monkeypatch apply to not stop on 102
        global apply  # noqa
        _orig = apply

        def apply(db, dry_run=False):  # type: ignore
            plan = analyze(db)
            # temporarily lower risk
            from migrations import nexgen_manifest as nm
            # call internal with risk override via env
            os.environ["NEXGEN_ALLOW_HIGH_RISK"] = "1"
            return _apply_impl(db, dry_run)

    mode = sum([args.check, args.dry_run, args.apply, args.verify])
    if mode == 0:
        args.check = True

    if args.plan_json or args.check or args.dry_run:
        plan = analyze(db)
        if args.plan_json:
            Path(args.plan_json).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[OK] plan -> {args.plan_json}")
        print(json.dumps({
            "recorded_max": max(plan["recorded"]) if plan["recorded"] else None,
            "missing": [m["version"] for m in plan["missing_apply"]],
            "reconcile": plan["reconcile"],
            "drift": plan["drift"],
            "apply_order": plan["apply_order"],
            "special": plan["special"],
        }, ensure_ascii=False, indent=2))
        if args.dry_run:
            r = apply(db, dry_run=True)
            print("[DRY-RUN]", json.dumps(r.get("order"), ensure_ascii=False))
        if args.check and (plan["drift"] or plan["missing_apply"] or plan["blocked"]):
            print("DEPLOY BLOKE — MIGRATION REQUIRED")
            return 1
        if args.check:
            print("CHECK OK")
            return 0

    if args.apply:
        # high risk gate
        def _apply_wrapped():
            plan = analyze(db)
            if plan["drift"]:
                print("SCHEMA_DRIFT — apply iptal")
                return 1
            # patch high risk if env
            result = _apply_impl(db, dry_run=False, allow_high=bool(args.allow_high_risk))
            print(json.dumps({k: result.get(k) for k in ("ok", "error", "backup")}, ensure_ascii=False, indent=2))
            for s in result.get("steps") or []:
                print(" STEP", s)
            return 0 if result.get("ok") else 1
        return _apply_wrapped()

    if args.verify:
        v = verify(db)
        print(json.dumps(v, ensure_ascii=False, indent=2))
        if not v["ok"]:
            print("DEPLOY BLOKE — MIGRATION REQUIRED")
            return 1
        print("VERIFY PASS")
        return 0

    return 0


def _apply_impl(db: str, dry_run: bool = False, allow_high: bool = False) -> dict:
    plan = analyze(db)
    if plan["drift"]:
        return {"ok": False, "error": "SCHEMA_DRIFT", "plan": plan}
    ok_int, int_msg = integrity_ok(db)
    if not ok_int:
        return {"ok": False, "error": "INTEGRITY", "detail": int_msg}
    if dry_run:
        order = list(plan["apply_order"])
        for v in plan["reconcile"]:
            if v not in order:
                order.append(v)
        return {"ok": True, "dry_run": True, "order": order, "plan": plan}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = db.replace(".db", f"_backup_pre_schema_upgrade_{ts}.db")
    shutil.copy2(db, bak)
    steps = [{"backup": bak}]

    order = list(plan["apply_order"])
    for v in plan["reconcile"]:
        if v not in order:
            order.append(v)
    seen = set()
    final_order = []
    for v in order:
        if v not in seen:
            seen.add(v)
            final_order.append(v)

    for v in final_order:
        entry = BY_VERSION[v]
        con = _connect(db)
        try:
            already_schema = detect_applied_by_schema(con, entry)
            already_ver = v in read_migration_versions(con)
            if entry.version in (96, 105):
                already_schema = already_ver or already_schema
        finally:
            con.close()

        if already_schema and not already_ver:
            con = _connect(db)
            try:
                _ensure_version_row(con, v, f"reconcile {entry.description}")
                con.commit()
            finally:
                con.close()
            steps.append({"version": v, "action": "reconcile", "ok": True})
            continue
        if already_schema and already_ver:
            steps.append({"version": v, "action": "skip", "ok": True})
            continue
        if entry.risk == "high" and not allow_high:
            steps.append({
                "version": v, "action": "blocked", "ok": False,
                "error": "HIGH_RISK_MANUAL",
                "hint": "--allow-high-risk ile 102 uygulanabilir",
            })
            return {"ok": False, "error": "HIGH_RISK_STOP", "steps": steps, "backup": bak}

        ok, detail = _run_one(entry, db)
        con = _connect(db)
        try:
            if ok:
                _ensure_version_row(con, v, entry.description)
                con.commit()
        finally:
            con.close()
        steps.append({"version": v, "action": "apply", "ok": ok, "detail": detail})
        if not ok:
            return {"ok": False, "error": "APPLY_FAIL", "steps": steps, "backup": bak}

    ok_int2, int_msg2 = integrity_ok(db)
    return {
        "ok": ok_int2,
        "steps": steps,
        "integrity": int_msg2,
        "plan": analyze(db),
        "backup": bak,
    }


if __name__ == "__main__":
    # simplify main to use _apply_impl
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--plan-json", default="")
    ap.add_argument("--allow-high-risk", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"[HATA] DB yok: {db}")
        sys.exit(2)

    if not any([args.check, args.dry_run, args.apply, args.verify]):
        args.check = True

    if args.check or args.dry_run or args.plan_json:
        plan = analyze(db)
        if args.plan_json:
            Path(args.plan_json).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(json.dumps({
            "recorded_max": max(plan["recorded"]) if plan["recorded"] else None,
            "missing": [m["version"] for m in plan["missing_apply"]],
            "reconcile": plan["reconcile"],
            "drift": plan["drift"],
            "apply_order": plan["apply_order"],
            "special": plan["special"],
        }, ensure_ascii=False, indent=2))
        if args.dry_run:
            r = _apply_impl(db, dry_run=True)
            print("[DRY-RUN] order=", r.get("order"))
        if args.check:
            bad = bool(plan["drift"] or plan["missing_apply"] or plan["blocked"])
            if bad:
                print("DEPLOY BLOKE — MIGRATION REQUIRED")
                sys.exit(1)
            print("CHECK OK")
            sys.exit(0)

    if args.apply:
        r = _apply_impl(db, dry_run=False, allow_high=args.allow_high_risk)
        print(json.dumps({
            "ok": r.get("ok"), "error": r.get("error"), "backup": r.get("backup"),
        }, ensure_ascii=False, indent=2))
        for s in r.get("steps") or []:
            print(" STEP", s)
        sys.exit(0 if r.get("ok") else 1)

    if args.verify:
        v = verify(db)
        print(json.dumps(v, ensure_ascii=False, indent=2))
        if not v["ok"]:
            print("DEPLOY BLOKE — MIGRATION REQUIRED")
            sys.exit(1)
        print("VERIFY PASS")
        sys.exit(0)

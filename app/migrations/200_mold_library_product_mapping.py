# -*- coding: utf-8 -*-
"""Migration 200 — mold_library_product_mapping (PHASE_7L additive)."""
from __future__ import annotations

import sqlite3
import sys

MIGRATION_VERSION = 200
ACIKLAMA = "mold_library_product_mapping — onaylı ürün-kalıp bağlantıları (preview)"

DDL = """
CREATE TABLE IF NOT EXISTS mold_library_product_mapping (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_model_code            TEXT NOT NULL,
    normalized_product_family_code TEXT NULL,
    mold_library_uuid           TEXT NOT NULL REFERENCES mold_library_mold(library_uuid),
    relation_type               TEXT NOT NULL CHECK (relation_type IN (
        'EXACT_MODEL', 'APPROVED_ALIAS', 'SUMMER_WINTER_SHARED_MOLD', 'MANUAL_APPROVED'
    )),
    product_variant             TEXT NOT NULL DEFAULT '',
    approved_by                 TEXT NOT NULL,
    approval_reason             TEXT NULL,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (order_model_code, mold_library_uuid, product_variant)
);

CREATE INDEX IF NOT EXISTS idx_ml_pm_order_model ON mold_library_product_mapping(order_model_code);
CREATE INDEX IF NOT EXISTS idx_ml_pm_library ON mold_library_product_mapping(mold_library_uuid);
CREATE INDEX IF NOT EXISTS idx_ml_pm_active ON mold_library_product_mapping(is_active);
"""


def _log(msg: str) -> None:
    print(msg, flush=True)


def _write_migration_record(cur) -> None:
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama, uygulama_zamani) VALUES (?,?,datetime('now','localtime'))",
        (str(MIGRATION_VERSION), ACIKLAMA),
    )


def run(path: str, *, allow_canonical: bool = False, _inject_failure: bool = False) -> dict:
    con = sqlite3.connect(path, timeout=15, isolation_level=None)
    cur = con.cursor()
    result: dict = {"ok": False, "db_path": path, "version": MIGRATION_VERSION}
    try:
        already = cur.execute(
            "SELECT version FROM schema_migrations WHERE version=?",
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f"[{MIGRATION_VERSION}] SKIP — zaten uygulanmış")
            result.update({"ok": True, "skipped": True})
            return result

        if _inject_failure:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("CREATE TABLE IF NOT EXISTS _mig195_rollback_probe (id INTEGER)")
            raise RuntimeError("_inject_failure: rollback testi")

        cur.executescript(DDL)
        cur.execute("BEGIN IMMEDIATE")
        _write_migration_record(cur)
        cur.execute("COMMIT")
        result["ok"] = True
        _log(f"[{MIGRATION_VERSION}] COMMIT OK")
        return result
    except Exception as exc:
        try:
            cur.execute("ROLLBACK")
        except Exception:
            pass
        _log(f"[{MIGRATION_VERSION}] ROLLBACK — {exc}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=f"Migration {MIGRATION_VERSION}")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--allow-canonical", action="store_true")
    args = parser.parse_args()
    print(run(args.db_path, allow_canonical=args.allow_canonical))

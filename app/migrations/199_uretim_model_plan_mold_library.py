# -*- coding: utf-8 -*-
"""Migration 199 — uretim_model_plan mold library identity (Option C, additive)."""
from __future__ import annotations

import sqlite3
import sys

MIGRATION_VERSION = 199
PARENT_TABLE = "uretim_model_plan"
ACIKLAMA = "mold_library_uuid + mold_library_snapshot_json + mold_source (additive)"

NEW_COLUMNS: list[tuple[str, str]] = [
    ("mold_library_uuid", "TEXT"),
    ("mold_library_snapshot_json", "TEXT"),
    ("mold_source", "TEXT"),
]


def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def _write_migration_record(cur: sqlite3.Cursor) -> None:
    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)",
            (str(MIGRATION_VERSION), ACIKLAMA),
        )
    except sqlite3.OperationalError:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (str(MIGRATION_VERSION),),
        )


def run(db_path: str | None = None, *, allow_canonical: bool = False, _inject_failure: bool = False) -> dict:
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    _log("=" * 70)
    _log(f"[{MIGRATION_VERSION}] Plan mold library identity columns")
    _log(f"[{MIGRATION_VERSION}] DB: {path}")
    _log("=" * 70)

    con = sqlite3.connect(path, timeout=15, isolation_level=None)
    cur = con.cursor()
    result: dict = {"ok": False, "db_path": path, "version": MIGRATION_VERSION, "added": []}
    try:
        already = cur.execute(
            "SELECT version FROM schema_migrations WHERE version=?",
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f"[{MIGRATION_VERSION}] SKIP — zaten uygulanmış")
            result.update({"ok": True, "skipped": True})
            return result

        if not cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (PARENT_TABLE,),
        ).fetchone():
            raise RuntimeError(f"{PARENT_TABLE} tablosu bulunamadı")

        if _inject_failure:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(f"ALTER TABLE {PARENT_TABLE} ADD COLUMN _mig199_probe INTEGER")
            raise RuntimeError("_inject_failure: rollback testi")

        cur.execute("BEGIN IMMEDIATE")
        for col, typ in NEW_COLUMNS:
            if not _column_exists(cur, PARENT_TABLE, col):
                cur.execute(f"ALTER TABLE {PARENT_TABLE} ADD COLUMN {col} {typ}")
                result["added"].append(col)
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_ump_mold_library_uuid ON {PARENT_TABLE}(mold_library_uuid)"
        )
        _write_migration_record(cur)
        cur.execute("COMMIT")
        result["ok"] = True
        _log(f"[{MIGRATION_VERSION}] COMMIT OK added={result['added']}")
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
    parser.add_argument("--inject-failure", action="store_true")
    args = parser.parse_args()
    print(run(args.db_path, allow_canonical=args.allow_canonical, _inject_failure=args.inject_failure))

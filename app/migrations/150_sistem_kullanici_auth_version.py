# -*- coding: utf-8 -*-
"""AUTH-1B: add the session revocation version to system users.

This migration has no production default path. ``--db`` is mandatory.
"""
from __future__ import annotations

import argparse
import os
import sqlite3

VERSION = 150
TABLE = "sistem_kullanici"
COLUMN = "AuthVersion"


def _columns(con):
    return {row[1]: row for row in con.execute(f"PRAGMA table_info({TABLE})")}


def run(db_path: str) -> dict:
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone():
            raise RuntimeError(f"required table missing: {TABLE}")
        before = _columns(con)
        changed = COLUMN not in before
        if changed:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} "
                "INTEGER NOT NULL DEFAULT 1"
            )
            con.commit()
        after = _columns(con)
        col = after.get(COLUMN)
        if not col or str(col[2]).upper() != "INTEGER" or col[3] != 1 or str(col[4]) != "1":
            raise RuntimeError("AuthVersion schema verification failed")
        invalid = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NULL OR {COLUMN} < 1"
        ).fetchone()[0]
        if invalid:
            raise RuntimeError("AuthVersion data verification failed")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check={integrity}")
        return {"changed": changed, "status": "APPLIED" if changed else "SKIP", "integrity": integrity}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Explicit isolated/test DB path")
    args = parser.parse_args()
    result = run(args.db)
    print(f"AUTH-1B migration {VERSION}: {result['status']}")
    print(f"integrity_check={result['integrity']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

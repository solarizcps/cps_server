# -*- coding: utf-8 -*-
"""Canonical DB read-only gate — SHA before/after must match during test runs."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

CANONICAL_DB = Path(__file__).resolve().parents[2] / 'app' / 'mock_data.db'


@dataclass(frozen=True)
class DbSnapshot:
    path: str
    sha256: str
    migration_max: int
    integrity: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot_canonical_db() -> DbSnapshot:
    if not CANONICAL_DB.is_file():
        raise FileNotFoundError(f'canonical DB missing: {CANONICAL_DB}')
    con = sqlite3.connect(str(CANONICAL_DB))
    try:
        mig_row = con.execute(
            'SELECT MAX(CAST(version AS INTEGER)) FROM schema_migrations'
        ).fetchone()
        migration_max = int(mig_row[0] or 0)
        integrity = str(con.execute('PRAGMA integrity_check').fetchone()[0])
    finally:
        con.close()
    return DbSnapshot(
        path=str(CANONICAL_DB.resolve()),
        sha256=_sha256(CANONICAL_DB),
        migration_max=migration_max,
        integrity=integrity,
    )


def assert_canonical_unchanged(before: DbSnapshot) -> DbSnapshot:
    after = snapshot_canonical_db()
    if after.sha256 != before.sha256:
        raise AssertionError(
            f'canonical DB SHA changed during tests: '
            f'before={before.sha256} after={after.sha256}'
        )
    return after

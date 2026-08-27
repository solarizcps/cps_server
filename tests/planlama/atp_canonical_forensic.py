# -*- coding: utf-8 -*-
"""Read-only canonical DB forensic snapshots for test hygiene closure."""
from __future__ import annotations

import os
import sqlite3
import subprocess
from typing import Any

from tools.atp_test_db_guard import guard_stats as nexgen_guard_stats
from tools.nexgen_tmp_db import db_fingerprint


ATP_TABLES = (
    'arac_gunluk_plan',
    'arac_gunluk_plan_is',
    'arac_is_talebi',
    'arac_kayitli_yer',
    'arac_operasyon_ayar',
)

GPS_TABLE = 'arac_gps_snapshot'


def _ro_connect(db_path: str) -> sqlite3.Connection:
    uri = f'file:{os.path.abspath(db_path)}?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_stats(con: sqlite3.Connection, table: str) -> dict[str, Any]:
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        return {'exists': False, 'count': 0, 'max_id': None}
    count = int(con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
    try:
        max_id = con.execute(f'SELECT MAX(id) FROM {table}').fetchone()[0]
    except sqlite3.Error:
        max_id = None
    return {'exists': True, 'count': count, 'max_id': max_id}


def canonical_logical_snapshot(db_path: str) -> dict[str, Any]:
    fp = db_fingerprint(db_path)
    con = _ro_connect(db_path)
    try:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        tables = {name: _table_stats(con, name) for name in ATP_TABLES}
        gps = _table_stats(con, GPS_TABLE)
    finally:
        con.close()
    return {
        'path': os.path.abspath(db_path),
        'fingerprint': fp,
        'integrity': integrity,
        'atp_tables': tables,
        'gps_snapshot': gps,
    }


def diff_logical(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed_atp = {}
    for name in ATP_TABLES:
        b = before['atp_tables'][name]
        a = after['atp_tables'][name]
        if b != a:
            changed_atp[name] = {'before': b, 'after': a}

    gps_before = before['gps_snapshot']
    gps_after = after['gps_snapshot']
    gps_changed = gps_before != gps_after

    fp_before = before['fingerprint']
    fp_after = after['fingerprint']
    sha_changed = fp_after['sha256'] != fp_before['sha256']
    wal_changed = (
        fp_after.get('wal_exists') != fp_before.get('wal_exists')
        or fp_after.get('wal_size') != fp_before.get('wal_size')
        or fp_after.get('shm_size') != fp_before.get('shm_size')
    )

    return {
        'sha_changed': sha_changed,
        'wal_changed': wal_changed,
        'atp_tables_changed': changed_atp,
        'gps_snapshot_changed': gps_changed,
        'gps_before': gps_before,
        'gps_after': gps_after,
        'integrity_before': before['integrity'],
        'integrity_after': after['integrity'],
    }


def classify_drift(diff: dict[str, Any]) -> str:
    atp_changed = bool(diff['atp_tables_changed'])
    gps_changed = diff['gps_snapshot_changed']
    sha_changed = diff['sha_changed']

    if not sha_changed and not atp_changed and not gps_changed:
        return 'NONE'

    if atp_changed:
        return 'ATP_OR_OTHER_TEST_WRITE'

    if gps_changed or diff['wal_changed']:
        return 'BACKGROUND_GPS_WORKER'

    if sha_changed:
        return 'UNKNOWN_SHA_DRIFT'

    return 'NONE'


def port_8080_pids() -> list[int]:
    if os.name != 'nt':
        return []
    try:
        out = subprocess.check_output(
            ['netstat', '-ano'],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    pids: set[int] = set()
    for line in out.splitlines():
        if ':8080' not in line or 'LISTENING' not in line.upper():
            continue
        parts = line.split()
        if parts:
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                pass
    return sorted(pids)


def assert_canonical_atp_unchanged(live_path: str, before_logical: dict) -> str:
    """Allow GPS-only drift; fail when ATP tables change."""
    after_logical = canonical_logical_snapshot(live_path)
    drift = diff_logical(before_logical, after_logical)
    root_cause = classify_drift(drift)
    if root_cause == 'ATP_OR_OTHER_TEST_WRITE':
        raise AssertionError(
            f'Canonical ATP tables changed: {drift["atp_tables_changed"]!r}'
        )
    return root_cause


def forensic_report(db_path: str, guard: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'logical': canonical_logical_snapshot(db_path),
        'guard': guard if guard is not None else nexgen_guard_stats(),
        'port_8080_pids': port_8080_pids(),
    }

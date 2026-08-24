# -*- coding: utf-8 -*-
"""Canonical GPS DB write guard — double-checked safety gate."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from modules.planlama.arac_geofence_repo import geofence_tables_ready
from modules.planlama.arac_gps_snapshot_repo import gps_tables_ready

_FORBIDDEN_WRONG_CANONICAL = Path(__file__).resolve().parents[1] / 'mock_data.db'


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _canonical_path() -> str:
    return os.path.normpath(str(Path(__file__).resolve().parents[2] / 'mock_data.db'))


def _config_db_path() -> str:
    from config import Config

    return os.path.normpath(Config.MOCK_DB_PATH)


def _forbidden_modules_stub_path() -> str:
    return os.path.normpath(str(_FORBIDDEN_WRONG_CANONICAL))


def active_db_path() -> str:
    env_mock = (os.environ.get('CPS_MOCK_DB_PATH') or '').strip()
    if env_mock:
        return os.path.normpath(env_mock)
    return _canonical_path()


def is_explicit_temp_db() -> bool:
    return bool((os.environ.get('CPS_MOCK_DB_PATH') or '').strip())


def is_canonical_path(path: str) -> bool:
    return _norm(path) == _norm(_canonical_path())


def is_forbidden_modules_stub(path: str) -> bool:
    return _norm(path) == _norm(_forbidden_modules_stub_path())


def validate_db_path_parity() -> dict[str, str | bool]:
    expected = _canonical_path()
    config_db = _config_db_path()
    active = active_db_path()
    explicit_temp = is_explicit_temp_db()

    if is_forbidden_modules_stub(active):
        parity = False
    elif explicit_temp:
        parity = _norm(active) == _norm(config_db)
    else:
        parity = (
            _norm(expected) == _norm(config_db) == _norm(active)
        )

    return {
        'expected_canonical': expected,
        'config_db': config_db,
        'active_db': active,
        'parity': parity,
        'explicit_temp_db': explicit_temp,
        'forbidden_modules_stub': _forbidden_modules_stub_path(),
    }


def _fail(msg: str, *, logger=None) -> None:
    if logger:
        logger.error(msg)
    else:
        print(msg, file=sys.stderr)
    raise SystemExit(2)


def _assert_db_file_ready(path: str, *, logger=None) -> None:
    if is_forbidden_modules_stub(path):
        _fail('STOP: forbidden modules stub DB path rejected', logger=logger)
    if not os.path.isfile(path):
        _fail(f'STOP: DB file missing: {path}', logger=logger)
    try:
        if os.path.getsize(path) <= 0:
            _fail(f'STOP: DB file is empty: {path}', logger=logger)
    except OSError as exc:
        _fail(f'STOP: DB file size check failed: {exc}', logger=logger)


def _open_existing_sqlite(path: str) -> sqlite3.Connection:
    _assert_db_file_ready(path)
    abs_path = os.path.abspath(path)
    uri = 'file:' + abs_path.replace('\\', '/').replace('?', '%3f') + '?mode=rw'
    return sqlite3.connect(uri, uri=True, timeout=10)


def assert_gps_db_write_allowed(*, logger=None) -> str:
    """
    Temp DB writes allowed only when CPS_MOCK_DB_PATH is explicitly set.
    Canonical writes only when ALL gates pass:
      - expected/active/config DB parity
      - exact canonical path (app/mock_data.db)
      - forbidden modules stub rejected
      - CPS_ARAC_GPS_CANONICAL_WRITE=YES
      - migration 179/180 tables ready
      - PRAGMA integrity_check = ok
    """
    parity_info = validate_db_path_parity()
    if not parity_info['parity']:
        _fail(
            'STOP: DB path parity failed '
            f"(expected={parity_info['expected_canonical']} "
            f"config={parity_info['config_db']} "
            f"active={parity_info['active_db']})",
            logger=logger,
        )

    path = str(parity_info['active_db'])

    if is_forbidden_modules_stub(path):
        _fail('STOP: forbidden modules stub DB path rejected', logger=logger)

    if not is_canonical_path(path):
        if not parity_info['explicit_temp_db']:
            _fail('STOP: non-canonical DB requires explicit CPS_MOCK_DB_PATH', logger=logger)
        _assert_db_file_ready(path, logger=logger)
        return path

    flag = (os.environ.get('CPS_ARAC_GPS_CANONICAL_WRITE') or '').strip().upper()
    if flag != 'YES':
        _fail('STOP: canonical DB write forbidden — set CPS_ARAC_GPS_CANONICAL_WRITE=YES', logger=logger)

    _assert_db_file_ready(path, logger=logger)

    if not gps_tables_ready() or not geofence_tables_ready():
        _fail('STOP: GPS/geofence tables not ready (migrations 179/180 required)', logger=logger)

    con = _open_existing_sqlite(path)
    try:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            _fail(f'STOP: DB integrity failed: {integrity}', logger=logger)
    finally:
        con.close()

    if logger:
        logger.info('canonical GPS write gate OPEN path=%s', path)
    return path

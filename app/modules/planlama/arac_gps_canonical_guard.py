# -*- coding: utf-8 -*-
"""Canonical GPS DB write guard — double-checked safety gate."""
from __future__ import annotations

import os
import sqlite3
import sys

from modules.planlama.arac_geofence_repo import geofence_tables_ready
from modules.planlama.arac_gps_snapshot_repo import gps_tables_ready


def _canonical_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(root, 'mock_data.db'))


def active_db_path() -> str:
    canonical = _canonical_path()
    active = os.environ.get('CPS_MOCK_DB_PATH') or canonical
    return os.path.normpath(active)


def is_canonical_path(path: str) -> bool:
    return os.path.normcase(os.path.normpath(path)) == os.path.normcase(_canonical_path())


def assert_gps_db_write_allowed(*, logger=None) -> str:
    """
    Allow temp DB writes always.
    Canonical writes only when ALL gates pass:
      - exact canonical path
      - CPS_ARAC_GPS_CANONICAL_WRITE=YES
      - migration 179/180 tables ready
      - PRAGMA integrity_check = ok
    """
    path = active_db_path()
    canonical = _canonical_path()

    if not is_canonical_path(path):
        return path

    flag = (os.environ.get('CPS_ARAC_GPS_CANONICAL_WRITE') or '').strip().upper()
    if flag != 'YES':
        msg = 'STOP: canonical DB write forbidden — set CPS_ARAC_GPS_CANONICAL_WRITE=YES'
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        raise SystemExit(2)

    if os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(canonical)):
        msg = 'STOP: canonical path mismatch'
        if logger:
            logger.error(msg)
        raise SystemExit(2)

    if not gps_tables_ready() or not geofence_tables_ready():
        msg = 'STOP: GPS/geofence tables not ready (migrations 179/180 required)'
        if logger:
            logger.error(msg)
        raise SystemExit(2)

    con = sqlite3.connect(path, timeout=10)
    try:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            msg = f'STOP: DB integrity failed: {integrity}'
            if logger:
                logger.error(msg)
            raise SystemExit(2)
    finally:
        con.close()

    if logger:
        logger.info('canonical GPS write gate OPEN path=%s', path)
    return path

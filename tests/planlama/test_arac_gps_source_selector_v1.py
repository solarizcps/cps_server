# -*- coding: utf-8 -*-
"""T01-T15 — freshest GPS source selection (Filom vs SQLite)."""
from __future__ import annotations

from datetime import datetime

import pytest

from modules.planlama.arac_gps_source_selector import (
    SOURCE_FILOM,
    SOURCE_SQLITE,
    apply_gps_bundle_to_vehicle,
    select_freshest_gps_source,
)

NOW = datetime(2026, 9, 14, 7, 30, 0)
FILOM_NEW = {
    'id': '45077045',
    'plate': '34MOR049',
    'latitude': 41.02,
    'longitude': 29.02,
    'speed_kmh': 0,
    'last_seen_at': '2026-09-14 06:22:59',
    'is_stale_data': False,
    'activity_status': 'DURAN',
    'activity_status_label': 'Duran',
    'ignition': 'Kapalı',
    'has_valid_location': True,
    'address': 'Filom Adres',
    'total_distance_km': 80091.2,
}
SQLITE_OLD = {
    'gps_timestamp': '2026-09-12 05:51:17',
    'latitude': 40.992918,
    'longitude': 28.69448,
    'speed_kmh': 0.0,
    'activity_status': 'DURAN',
    'ignition_status': 'Kapalı',
    'is_stale': 0,
    'odometer_km': 79760.2,
}


def _pick(filom=None, sqlite=None):
    return select_freshest_gps_source(filom, sqlite, now=NOW)


class TestFreshGpsSourceMatrix:
    def test_t01_filom_new_sqlite_old(self):
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        assert sel['source'] == SOURCE_FILOM
        assert sel['bundle']['gps_timestamp'] == '2026-09-14 06:22:59'
        assert sel['bundle']['latitude'] == 41.02

    def test_t02_sqlite_new_filom_old(self):
        filom_old = dict(FILOM_NEW, last_seen_at='2026-09-10 08:00:00')
        sqlite_new = dict(SQLITE_OLD, gps_timestamp='2026-09-14 08:00:00')
        sel = _pick(filom_old, sqlite_new)
        assert sel['source'] == SOURCE_SQLITE
        assert sel['bundle']['gps_timestamp'] == '2026-09-14 08:00:00'

    def test_t03_equal_ts_filom_has_coords(self):
        ts = '2026-09-14 06:00:00'
        filom = dict(FILOM_NEW, last_seen_at=ts, latitude=41.0, longitude=29.0)
        sqlite = dict(SQLITE_OLD, gps_timestamp=ts, latitude=None, longitude=None)
        sel = _pick(filom, sqlite)
        assert sel['source'] == SOURCE_FILOM

    def test_t04_equal_ts_sqlite_has_coords(self):
        ts = '2026-09-14 06:00:00'
        filom = dict(FILOM_NEW, last_seen_at=ts, latitude=None, longitude=None, has_valid_location=False)
        sqlite = dict(SQLITE_OLD, gps_timestamp=ts, latitude=41.0, longitude=29.0)
        sel = _pick(filom, sqlite)
        assert sel['source'] == SOURCE_SQLITE

    def test_t05_filom_timestamp_unparseable(self):
        filom = dict(FILOM_NEW, last_seen_at='not-a-date')
        sel = _pick(filom, SQLITE_OLD)
        assert sel['source'] == SOURCE_SQLITE

    def test_t06_sqlite_timestamp_unparseable(self):
        sqlite = dict(SQLITE_OLD, gps_timestamp='broken')
        sel = _pick(FILOM_NEW, sqlite)
        assert sel['source'] == SOURCE_FILOM

    def test_t07_both_timestamps_missing(self):
        filom = dict(FILOM_NEW, last_seen_at='', latitude=None, longitude=None, has_valid_location=False)
        sqlite = dict(SQLITE_OLD, gps_timestamp='', latitude=None, longitude=None)
        sel = _pick(filom, sqlite)
        assert sel['source'] is None

    def test_t08_filom_new_speed_zero_still_wins(self):
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        assert sel['source'] == SOURCE_FILOM
        assert sel['bundle']['speed_kmh'] == 0

    def test_t09_filom_new_ignition_off_still_wins(self):
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        assert sel['source'] == SOURCE_FILOM
        assert sel['bundle']['ignition'] == 'Kapalı'

    def test_t10_sqlite_new_stale_flag_ignored_when_ts_newer(self):
        filom_old = dict(FILOM_NEW, last_seen_at='2026-09-10 08:00:00')
        sqlite_new = dict(SQLITE_OLD, gps_timestamp='2026-09-14 08:00:00', is_stale=1)
        sel = _pick(filom_old, sqlite_new)
        assert sel['source'] == SOURCE_SQLITE
        assert sel['bundle']['gps_is_stale'] is False

    def test_t11_no_mixed_fields(self):
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        b = sel['bundle']
        assert b['latitude'] == FILOM_NEW['latitude']
        assert b['gps_timestamp'] == FILOM_NEW['last_seen_at']
        assert b['total_distance_km'] == FILOM_NEW['total_distance_km']

    def test_t12_plan_fields_preserved_on_apply(self):
        ops = {
            'plan_id': 44,
            'next_stop': 'Normal1',
            'driver_name': 'Ali',
            'route_state': 'ON_ROUTE',
            'progress_completed': 1,
        }
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        merged = apply_gps_bundle_to_vehicle(ops, sel)
        assert merged['next_stop'] == 'Normal1'
        assert merged['driver_name'] == 'Ali'
        assert merged['gps_timestamp'] == '2026-09-14 06:22:59'

    def test_t13_vehicle_id_unchanged(self):
        filom = dict(FILOM_NEW, id='45077045')
        sel = _pick(filom, SQLITE_OLD)
        merged = apply_gps_bundle_to_vehicle({'arac_external_id': '45077045', 'id': '45077045'}, sel)
        assert merged['arac_external_id'] == '45077045'

    def test_t15_mor049_regression(self):
        sel = _pick(FILOM_NEW, SQLITE_OLD)
        assert sel['source'] == SOURCE_FILOM
        assert sel['bundle']['gps_timestamp'] == '2026-09-14 06:22:59'
        assert sel['bundle']['gps_is_stale'] is False

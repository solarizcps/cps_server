# -*- coding: utf-8 -*-
"""Canlı Takip duplicate vehicle dedupe — read-model tests (no live Filom)."""
from __future__ import annotations

import os
import sys
import unittest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'app')
sys.path.insert(0, APP)
os.chdir(APP)

from modules.planlama.arac_live_vehicle_dedupe import (  # noqa: E402
    dedupe_live_vehicles,
    normalize_plate_key,
)
from modules.planlama.arac_live_vehicle_registry import (  # noqa: E402
    filter_live_tracking_vehicles,
    resolve_live_vehicle_status,
)
from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import compute_kpi  # noqa: E402


def _veh(vid, plate, last_seen, *, stale=False, in_use=True, valid=True, lat=41.0, lng=29.0):
    return {
        'id': str(vid),
        'plate': plate,
        'plate_display': plate,
        'last_seen_at': last_seen,
        'is_stale_data': stale,
        'in_use': in_use,
        'has_valid_location': valid,
        'latitude': lat if valid else None,
        'longitude': lng if valid else None,
        'activity_status': 'DURAN',
    }


class TestNormalizePlateKey(unittest.TestCase):
    def test_spacing_and_case(self):
        self.assertEqual(normalize_plate_key('34  BPY 282'), '34BPY282')
        self.assertEqual(normalize_plate_key('34bpy282'), '34BPY282')


class TestDedupeLiveVehicles(unittest.TestCase):
    def test_three_unique_plates_unchanged(self):
        items = [
            _veh('1', '34 MOR 049', '2026-09-13 10:00:00'),
            _veh('2', '34 GFK 183', '2026-09-13 10:00:00'),
            _veh('3', '34 BPY 282', '2026-09-13 10:00:00'),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(len(out['vehicles']), 3)
        self.assertFalse(out['deduplicated'])

    def test_same_plate_new_and_old_shows_newest(self):
        items = [
            _veh('45077046', '34BPY282', '2026-08-25 10:46:54', lat=38.44, lng=27.19),
            _veh('43567534', '34  BPY 282', '2025-01-28 21:34:12', stale=True, lat=40.97, lng=28.70),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(len(out['vehicles']), 1)
        winner = out['vehicles'][0]
        self.assertEqual(winner['id'], '45077046')
        self.assertEqual(winner['suppressed_device_ids'], ['43567534'])
        self.assertEqual(out['suppressed_count'], 1)

    def test_spacing_variant_collapses(self):
        items = [
            _veh('a', '34BPY282', '2026-09-01 08:00:00'),
            _veh('b', '34 BPY 282', '2026-08-01 08:00:00'),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(len(out['vehicles']), 1)
        self.assertEqual(out['vehicles'][0]['id'], 'a')

    def test_different_plates_not_merged(self):
        items = [
            _veh('1', '34 MOR 049', '2026-09-13 10:00:00'),
            _veh('2', '34 GFK 183', '2026-09-13 10:00:00'),
        ]
        out = dedupe_live_vehicles(items)
        plates = {normalize_plate_key(v['plate']) for v in out['vehicles']}
        self.assertEqual(plates, {'34MOR049', '34GFK183'})

    def test_newer_without_coords_beats_older_with_coords(self):
        items = [
            _veh('new', '34BPY282', '2026-09-13 10:00:00', valid=False, lat=None, lng=None),
            _veh('old', '34 BPY 282', '2025-01-01 10:00:00', valid=True),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(out['vehicles'][0]['id'], 'new')

    def test_equal_timestamp_prefers_valid_location(self):
        ts = '2026-09-13 10:00:00'
        items = [
            _veh('no_gps', '34BPY282', ts, valid=False, lat=None, lng=None),
            _veh('has_gps', '34 BPY 282', ts, valid=True),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(out['vehicles'][0]['id'], 'has_gps')

    def test_equal_rank_is_deterministic_not_random(self):
        ts = '2026-09-13 10:00:00'
        items = [
            _veh('100', '34BPY282', ts),
            _veh('200', '34 BPY 282', ts),
        ]
        out1 = dedupe_live_vehicles(items)
        out2 = dedupe_live_vehicles(list(reversed(items)))
        self.assertEqual(out1['vehicles'][0]['id'], out2['vehicles'][0]['id'])
        self.assertEqual(out1['vehicles'][0]['id'], '200')

    def test_mor049_gfk183_bpy282_realistic(self):
        items = [
            _veh('45077045', '34MOR049', '2026-09-13 16:44:29'),
            _veh('45074345', '34GFK183', '2026-09-13 16:18:19'),
            _veh('45077046', '34BPY282', '2026-08-25 10:46:54', lat=38.44, lng=27.19),
            _veh('43567534', '34  BPY 282', '2025-01-28 21:34:12', stale=True),
        ]
        out = dedupe_live_vehicles(items)
        self.assertEqual(len(out['vehicles']), 3)
        plates = sorted(normalize_plate_key(v['plate']) for v in out['vehicles'])
        self.assertEqual(plates, ['34BPY282', '34GFK183', '34MOR049'])


class TestLiveVehicleRegistry(unittest.TestCase):
    _REGISTRY = {
        'entries': [{'plate_key': '34BPY282', 'status': 'IPTAL'}],
        'by_plate_key': {'34BPY282': 'IPTAL'},
        'by_external_id': {},
    }

    def test_cancelled_plate_excluded_from_live(self):
        items = [
            _veh('45077045', '34MOR049', '2026-09-13 16:44:29'),
            _veh('45074345', '34GFK183', '2026-09-13 16:18:19'),
            _veh('45077046', '34BPY282', '2026-08-25 10:46:54'),
        ]
        deduped = dedupe_live_vehicles(items)['vehicles']
        out = filter_live_tracking_vehicles(deduped, self._REGISTRY)
        self.assertEqual(len(out['vehicles']), 2)
        plates = {normalize_plate_key(v['plate']) for v in out['vehicles']}
        self.assertEqual(plates, {'34MOR049', '34GFK183'})
        self.assertEqual(out['excluded_count'], 1)
        self.assertEqual(out['excluded'][0]['plate_key'], '34BPY282')

    def test_realistic_filom_four_to_two_active(self):
        items = [
            _veh('45077045', '34MOR049', '2026-09-13 16:44:29'),
            _veh('45074345', '34GFK183', '2026-09-13 16:18:19'),
            _veh('45077046', '34BPY282', '2026-08-25 10:46:54', lat=38.44, lng=27.19),
            _veh('43567534', '34  BPY 282', '2025-01-28 21:34:12', stale=True),
        ]
        deduped = dedupe_live_vehicles(items)['vehicles']
        out = filter_live_tracking_vehicles(deduped, self._REGISTRY)
        self.assertEqual(len(out['vehicles']), 2)
        kpi = compute_kpi(out['vehicles'])
        self.assertEqual(kpi['aktif_arac_toplam'], 2)
        self.assertEqual(kpi['aktif_arac'], 2)

    def test_unlisted_vehicle_defaults_aktif(self):
        v = _veh('999', '34 NEW 001', '2026-09-13 10:00:00')
        self.assertEqual(resolve_live_vehicle_status(v, self._REGISTRY), 'AKTIF')

    def test_preferred_external_id_breaks_tie(self):
        ts = '2026-09-13 10:00:00'
        items = [
            _veh('100', '34BPY282', ts),
            _veh('200', '34 BPY 282', ts),
        ]
        out = dedupe_live_vehicles(items, preferred_external_ids={'100'})
        self.assertEqual(out['vehicles'][0]['id'], '100')


if __name__ == '__main__':
    unittest.main()

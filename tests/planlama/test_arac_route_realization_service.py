# -*- coding: utf-8 -*-
"""Offline tests for arac_route_realization_service — trip window + quality fixes."""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.planlama.arac_route_geometry import latlng_pairs_to_geojson
from modules.planlama.arac_route_realization_models import (
    BASE_SOURCE_OPERATION,
    DATA_GAP_SECONDS,
    DEVIATION_CONFIRM_POINTS,
    DEVIATION_M,
    FLAG_DATA_GAP,
    FLAG_GPS_JUMP,
    FLAG_IGNITION_OFF_DWELL,
    REASON_DEPARTURE_NOT_DETECTED,
    REASON_RETURN_NOT_DETECTED,
)
from modules.planlama.arac_route_realization_service import (
    compute_route_realization,
    compute_route_realization_from_db,
)
from modules.planlama.arac_rota_deviation_service import (
    CONFIRM_OUTSIDE,
    DEVIATION_M as DEV_M_SRC,
    ON_ROUTE_M,
)

PLAN_DATE = '2026-08-27'
CIKIS = '08:00'
VEHICLE = '45077045'
PLAN_ID = 99

BASE_LAT, BASE_LON = 40.9928283, 28.6947341
STOP1 = {'id': '101', 'order_no': 1, 'company_name': 'Topkapı',
         'latitude': 41.0203, 'longitude': 28.9295}
STOP2 = {'id': '102', 'order_no': 2, 'company_name': 'Tuzla',
         'latitude': 40.8167, 'longitude': 29.3008}

ROUTE_VERTICES = [
    [BASE_LAT, BASE_LON],
    [STOP1['latitude'], STOP1['longitude']],
    [STOP2['latitude'], STOP2['longitude']],
    [BASE_LAT, BASE_LON],
]


def _ts(base: str, minutes: int) -> str:
    dt = datetime.strptime(base, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=minutes)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _gps(ts: str, lat: float, lon: float, **kw) -> dict:
    return {
        'gps_timestamp': ts,
        'latitude': lat,
        'longitude': lon,
        'ignition_status': kw.get('ignition', '1'),
        'is_stale': kw.get('is_stale', 0),
        'speed_kmh': kw.get('speed', 40),
    }


def _interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _base_dwell(minute_start: int = -10, count: int = 4) -> list[dict]:
    return [
        _gps(_ts(f'{PLAN_DATE} 08:00:00', minute_start + i), BASE_LAT, BASE_LON)
        for i in range(count)
    ]


def _base_return_dwell(minute_start: int = 90, count: int = 4) -> list[dict]:
    return [
        _gps(_ts(f'{PLAN_DATE} 08:00:00', minute_start + i), BASE_LAT, BASE_LON)
        for i in range(count)
    ]


def _track_through(vertices: list[list[float]], start_min: int = 0, step_min: int = 1,
                   lat_offset: float = 0.0, lon_offset: float = 0.0,
                   dwell_at_vertices: bool = False) -> list[dict]:
    rows: list[dict] = []
    minute = start_min
    for i in range(len(vertices) - 1):
        la1, lo1 = vertices[i]
        la2, lo2 = vertices[i + 1]
        steps = 8 if i < len(vertices) - 2 else 12
        for s in range(steps + 1):
            t = s / steps if steps else 1.0
            lat = _interp(la1, la2, t) + lat_offset
            lon = _interp(lo1, lo2, t) + lon_offset
            rows.append(_gps(_ts(f'{PLAN_DATE} 08:00:00', minute), lat, lon))
            minute += step_min
        if dwell_at_vertices and i < len(vertices) - 2:
            vx, vy = vertices[i + 1]
            for _ in range(3):
                rows.append(_gps(
                    _ts(f'{PLAN_DATE} 08:00:00', minute),
                    vx + lat_offset, vy + lon_offset,
                ))
                minute += step_min
    return rows


def _full_trip_gps(vertices: list[list[float]] | None = None, **kw) -> list[dict]:
    verts = vertices or ROUTE_VERTICES
    gps = _base_dwell()
    track = _track_through(verts, dwell_at_vertices=True, **kw)
    gps.extend(track)
    if track:
        last_dt = datetime.strptime(track[-1]['gps_timestamp'], '%Y-%m-%d %H:%M:%S')
        for i in range(1, 5):
            ts = (last_dt + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
            gps.append(_gps(ts, BASE_LAT, BASE_LON))
    return gps


def _snapshot(stops: list[dict], distance_m: float = 120000, duration_s: float = 3600) -> dict:
    geo = latlng_pairs_to_geojson(ROUTE_VERTICES)
    stop_order = [{
        'plan_item_id': s['id'],
        'order_no': s['order_no'],
        'company_name': s['company_name'],
        'latitude': s['latitude'],
        'longitude': s['longitude'],
        'eta_at': _ts(f'{PLAN_DATE} 08:00:00', 30 + 60 * (s['order_no'] - 1)),
        'planned_time': f'{8 + s["order_no"]:02d}:30',
    } for s in stops]
    return {
        'geometry': geo,
        'stop_order': stop_order,
        'total_distance_m': distance_m,
        'total_duration_s': duration_s,
        'routing_provider': 'google-google-traffic-fast',
    }


def _run(gps: list[dict], stops: list[dict] | None = None, **kw) -> dict:
    snap = _snapshot(stops or [STOP1, STOP2])
    dto = compute_route_realization(
        plan_id=PLAN_ID,
        vehicle_id=VEHICLE,
        plan_date=PLAN_DATE,
        route_snapshot=snap,
        gps_snapshots=gps,
        cikis_saati=CIKIS,
        base_latitude=BASE_LAT,
        base_longitude=BASE_LON,
        base_coordinate_source=BASE_SOURCE_OPERATION,
        **kw,
    )
    return dto.to_dict()


class TestThresholdSingleSource(unittest.TestCase):
    def test_deviation_confirm_matches_live_service(self):
        self.assertEqual(DEV_M_SRC, DEVIATION_M)
        self.assertEqual(DEVIATION_CONFIRM_POINTS, CONFIRM_OUTSIDE)
        self.assertEqual(CONFIRM_OUTSIDE, 3)


class TestTripWindowExclusion(unittest.TestCase):
    """Full-day GPS must not all enter the trip window."""

    def test_pre_departure_journey_excluded(self):
        early = [_gps(_ts(f'{PLAN_DATE} 06:00:00', 0), 41.5, 29.0)]
        trip = _full_trip_gps()
        result = _run(early + trip, [STOP1, STOP2])
        self.assertGreater(result['excluded_gps_point_count'], 0)
        self.assertEqual(early[0]['gps_timestamp'][:16], '2026-08-27 06:00')

    def test_post_buffer_journey_excluded(self):
        trip = _full_trip_gps()
        late = [_gps(f'{PLAN_DATE} 23:00:00', 41.5, 29.0)]
        result = _run(trip + late, [STOP1, STOP2])
        self.assertGreater(result['excluded_gps_point_count'], 0)

    def test_trip_window_bounded(self):
        trip = _full_trip_gps()
        result = _run(trip, [STOP1, STOP2])
        self.assertIsNotNone(result['trip_window_start_at'])
        self.assertIsNotNone(result['trip_window_end_at'])
        self.assertLess(
            result['actual_summary']['duration_s'],
            86400,
        )


class TestOnRouteCompliance(unittest.TestCase):
    def test_full_on_route_complete_trip(self):
        result = _run(_full_trip_gps(ROUTE_VERTICES[:3]), [STOP1, STOP2])
        self.assertTrue(result['comparison_complete'])
        self.assertEqual(len(result['deviations']), 0)
        self.assertIsNotNone(result['factory_departure_at'])
        self.assertIsNotNone(result['factory_return_at'])


class TestSustainedDeviation(unittest.TestCase):
    def test_three_point_deviation_required(self):
        gps = _base_dwell() + _track_through(ROUTE_VERTICES[:3], lat_offset=0.006)
        gps += _base_return_dwell(minute_start=120)
        result = _run(gps, [STOP1, STOP2])
        self.assertGreaterEqual(len(result['deviations']), 1)
        self.assertGreaterEqual(result['max_deviation_m'], DEVIATION_M)


class TestSingleAndDoubleSpikeIgnored(unittest.TestCase):
    def test_single_spike_not_deviation(self):
        gps = _full_trip_gps(ROUTE_VERTICES[:3])
        spike = _gps(_ts(f'{PLAN_DATE} 08:00:00', 5), BASE_LAT + 0.008, BASE_LON)
        gps = sorted(gps + [spike], key=lambda r: r['gps_timestamp'])
        result = _run(gps, [STOP1, STOP2])
        self.assertEqual(len(result['deviations']), 0)

    def test_two_point_spike_not_deviation(self):
        gps = _full_trip_gps(ROUTE_VERTICES[:3])
        spikes = [
            _gps(_ts(f'{PLAN_DATE} 08:00:00', 5), BASE_LAT + 0.008, BASE_LON),
            _gps(_ts(f'{PLAN_DATE} 08:00:00', 6), BASE_LAT + 0.008, BASE_LON),
        ]
        gps = sorted(gps + spikes, key=lambda r: r['gps_timestamp'])
        result = _run(gps, [STOP1, STOP2])
        self.assertEqual(len(result['deviations']), 0)


class TestDataGap(unittest.TestCase):
    def test_data_gap_flagged_and_segmented(self):
        gps = _base_dwell() + _track_through(ROUTE_VERTICES[:2], step_min=1)[:10]
        late = _track_through([ROUTE_VERTICES[1], ROUTE_VERTICES[2]], start_min=50, step_min=1)[:8]
        if late:
            last_dt = datetime.strptime(late[-1]['gps_timestamp'], '%Y-%m-%d %H:%M:%S')
            for i in range(1, 5):
                late.append(_gps((last_dt + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'), BASE_LAT, BASE_LON))
        gps = gps + late
        snap = _snapshot([STOP1, STOP2], duration_s=7200)
        dto = compute_route_realization(
            plan_id=PLAN_ID, vehicle_id=VEHICLE, plan_date=PLAN_DATE,
            route_snapshot=snap, gps_snapshots=gps, cikis_saati=CIKIS,
            base_latitude=BASE_LAT, base_longitude=BASE_LON,
        )
        result = dto.to_dict()
        self.assertIn(FLAG_DATA_GAP, result['data_quality']['flags'])
        self.assertGreaterEqual(len(result['actual_geometry']['coordinates']), 2)


class TestExcessiveGapsIncomplete(unittest.TestCase):
    """37 gap / 7200s scenario must be LOW + incomplete."""

    def test_many_gaps_low_and_incomplete(self):
        gps = _base_dwell()
        minute = 0
        lat = BASE_LAT
        for seg in range(15):
            gps.append(_gps(_ts(f'{PLAN_DATE} 08:00:00', minute), lat, BASE_LON + seg * 0.02))
            lat += 0.002
            minute += 3
            minute += 30  # 30 min gap (>180s) within trip buffer
        last_dt = datetime.strptime(gps[-1]['gps_timestamp'], '%Y-%m-%d %H:%M:%S')
        for i in range(1, 5):
            gps.append(_gps((last_dt + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'), BASE_LAT, BASE_LON))
        snap = _snapshot([STOP1, STOP2], duration_s=14400)
        dto = compute_route_realization(
            plan_id=PLAN_ID, vehicle_id=VEHICLE, plan_date=PLAN_DATE,
            route_snapshot=snap, gps_snapshots=gps, cikis_saati=CIKIS,
            base_latitude=BASE_LAT, base_longitude=BASE_LON,
        )
        result = dto.to_dict()
        self.assertEqual(result['data_quality']['level'], 'LOW')
        self.assertFalse(result['comparison_complete'])
        self.assertGreaterEqual(result['data_quality']['data_gap_count'], 3)


class TestGpsJump(unittest.TestCase):
    def test_jump_excluded_from_distance(self):
        gps = _base_dwell()
        a = _gps(_ts(f'{PLAN_DATE} 08:00:00', 0), BASE_LAT, BASE_LON)
        b = _gps(_ts(f'{PLAN_DATE} 08:00:00', 1), BASE_LAT, BASE_LON + 0.5)
        c = _gps(_ts(f'{PLAN_DATE} 08:00:00', 2), BASE_LAT, BASE_LON + 0.5001)
        cont = _track_through(ROUTE_VERTICES, start_min=3, dwell_at_vertices=True)
        gps = gps + [a, b, c] + cont + _base_return_dwell(minute_start=220)
        result = _run(gps, [STOP1, STOP2])
        self.assertIn(FLAG_GPS_JUMP, result['data_quality']['flags'])
        self.assertLess(result['actual_summary']['distance_m'], 200000)


class TestReturnNotDetected(unittest.TestCase):
    def test_no_return_means_incomplete(self):
        gps = _base_dwell() + _track_through(ROUTE_VERTICES[:3], dwell_at_vertices=True)
        result = _run(gps, [STOP1, STOP2])
        self.assertIsNone(result['factory_return_at'])
        self.assertFalse(result['comparison_complete'])
        self.assertIn(REASON_RETURN_NOT_DETECTED, result['incomplete_reasons'])


class TestDepartureNotDetected(unittest.TestCase):
    def test_no_departure_means_incomplete(self):
        # Start en route — never near factory base
        en_route = [
            [STOP1['latitude'], STOP1['longitude']],
            [STOP2['latitude'], STOP2['longitude']],
        ]
        gps = _track_through(en_route, start_min=60)
        result = _run(gps, [STOP1, STOP2])
        self.assertFalse(result['comparison_complete'])
        self.assertIn(REASON_DEPARTURE_NOT_DETECTED, result['incomplete_reasons'])


class TestCorrectStopOrder(unittest.TestCase):
    def test_correct_stop_order(self):
        result = _run(_full_trip_gps(), [STOP1, STOP2])
        self.assertEqual(result['actual_stop_order'], ['101', '102'])


class TestWrongStopOrder(unittest.TestCase):
    def test_wrong_stop_order(self):
        alt = [
            [BASE_LAT, BASE_LON],
            [STOP2['latitude'], STOP2['longitude']],
            [STOP1['latitude'], STOP1['longitude']],
            [BASE_LAT, BASE_LON],
        ]
        result = _run(_full_trip_gps(alt), [STOP1, STOP2])
        self.assertTrue(
            result['wrong_order_stop_ids']
            or any(s['visit_status'] == 'OUT_OF_ORDER' for s in result['stops'])
        )


class TestSkippedStop(unittest.TestCase):
    def test_skipped_stop(self):
        alt = [[BASE_LAT, BASE_LON], [STOP2['latitude'], STOP2['longitude']], [BASE_LAT, BASE_LON]]
        result = _run(_full_trip_gps(alt), [STOP1, STOP2])
        self.assertIn('101', result['skipped_stop_ids'])


class TestArrivalDepartureTimes(unittest.TestCase):
    def test_stop_arrival_departure(self):
        result = _run(_full_trip_gps(), [STOP1, STOP2])
        stop1 = next(s for s in result['stops'] if s['plan_item_id'] == '101')
        self.assertIsNotNone(stop1['actual_arrival_at'])
        self.assertIsNotNone(stop1['actual_departure_at'])


class TestFactoryReturn(unittest.TestCase):
    def test_factory_return_detected(self):
        result = _run(_full_trip_gps(), [STOP1, STOP2])
        self.assertIsNotNone(result['factory_return_at'])
        self.assertIsNotNone(result['factory_departure_at'])


class TestMidnightCrossing(unittest.TestCase):
    def test_midnight_trip_window(self):
        start = f'{PLAN_DATE} 23:30:00'
        gps = []
        for m in range(-5, 0):
            gps.append(_gps(
                (datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=m)).strftime('%Y-%m-%d %H:%M:%S'),
                BASE_LAT, BASE_LON,
            ))
        for m in range(0, 90, 5):
            ts = (datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=m)).strftime('%Y-%m-%d %H:%M:%S')
            t = m / 90
            lat = _interp(BASE_LAT, STOP1['latitude'], t)
            lon = _interp(BASE_LON, STOP1['longitude'], t)
            gps.append(_gps(ts, lat, lon))
        for m in range(95, 100):
            ts = (datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + timedelta(minutes=m)).strftime('%Y-%m-%d %H:%M:%S')
            gps.append(_gps(ts, BASE_LAT, BASE_LON))
        snap = _snapshot([STOP1], duration_s=120)
        dto = compute_route_realization(
            plan_id=PLAN_ID,
            vehicle_id=VEHICLE,
            plan_date=PLAN_DATE,
            route_snapshot=snap,
            gps_snapshots=gps,
            cikis_saati='23:30',
            base_latitude=BASE_LAT,
            base_longitude=BASE_LON,
        )
        self.assertIsNotNone(dto.trip_window_start_at)
        self.assertGreater(dto.actual_summary.duration_s, 0)


class TestLowDataQuality(unittest.TestCase):
    def test_low_quality_few_points(self):
        gps = _base_dwell(count=1)
        result = _run(gps, [STOP1])
        self.assertIn('LOW_POINT_COUNT', result['data_quality']['flags'])
        self.assertFalse(result['comparison_complete'])


class TestIgnitionOffDwell(unittest.TestCase):
    def test_ignition_off_dwell_flagged(self):
        gps = _base_dwell()
        for m in range(0, 20):
            gps.append(_gps(
                _ts(f'{PLAN_DATE} 08:00:00', m),
                STOP1['latitude'], STOP1['longitude'],
                ignition='0',
            ))
        result = _run(gps, [STOP1])
        self.assertIn(FLAG_IGNITION_OFF_DWELL, result['data_quality']['flags'])


class TestGapNotBridgedForDistance(unittest.TestCase):
    def test_gap_excluded_from_distance(self):
        seg_a = _base_dwell() + _track_through([ROUTE_VERTICES[0], ROUTE_VERTICES[1]], step_min=1)[:8]
        seg_b = _track_through([ROUTE_VERTICES[1], ROUTE_VERTICES[2]], start_min=50, step_min=1)[:8]
        ret = []
        if seg_b:
            last_dt = datetime.strptime(seg_b[-1]['gps_timestamp'], '%Y-%m-%d %H:%M:%S')
            for i in range(1, 5):
                ret.append(_gps((last_dt + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'), BASE_LAT, BASE_LON))
        gps = seg_a + seg_b + ret
        continuous = seg_a + _track_through(
            [ROUTE_VERTICES[1], ROUTE_VERTICES[2]], start_min=9, step_min=1,
        )[:8] + ret
        snap = _snapshot([STOP1, STOP2], duration_s=7200)
        gap_dto = compute_route_realization(
            plan_id=PLAN_ID, vehicle_id=VEHICLE, plan_date=PLAN_DATE,
            route_snapshot=snap, gps_snapshots=gps, cikis_saati=CIKIS,
            base_latitude=BASE_LAT, base_longitude=BASE_LON,
        )
        cont_dto = compute_route_realization(
            plan_id=PLAN_ID, vehicle_id=VEHICLE, plan_date=PLAN_DATE,
            route_snapshot=snap, gps_snapshots=continuous, cikis_saati=CIKIS,
            base_latitude=BASE_LAT, base_longitude=BASE_LON,
        )
        gap_result = gap_dto.to_dict()
        cont_result = cont_dto.to_dict()
        self.assertGreater(gap_result['data_quality']['data_gap_count'], 0)
        self.assertLessEqual(
            gap_result['actual_summary']['distance_m'],
            cont_result['actual_summary']['distance_m'] + 1.0,
        )


class TestBaseCoordinatePriority(unittest.TestCase):
    def test_explicit_base_over_geometry(self):
        gps = _full_trip_gps()
        result = _run(gps, [STOP1, STOP2])
        self.assertEqual(result['base_coordinate_source'], BASE_SOURCE_OPERATION)


class TestCanonicalSmokeReadOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'mock_data.db'),
        )
        cls.results: dict = {}
        if os.path.isfile(cls.db_path):
            for plan_id in (38, 7):
                cls.results[plan_id] = compute_route_realization_from_db(
                    plan_id=plan_id,
                    vehicle_id='45074345' if plan_id == 38 else '45077045',
                    plan_date='2026-08-24',
                    db_path=cls.db_path,
                ).to_dict()

    def test_plan_38_smoke(self):
        if not os.path.isfile(self.db_path):
            self.skipTest('canonical mock_data.db not present')
        r = self.results.get(38)
        if not r:
            self.skipTest('plan 38 not available')
        self.assertFalse(r['comparison_complete'])
        self.assertIn('data_quality', r)
        print('\n--- PLAN 38 SMOKE ---')
        print(json.dumps({
            'comparison_complete': r['comparison_complete'],
            'incomplete_reasons': r['incomplete_reasons'],
            'trip_window': [r['trip_window_start_at'], r['trip_window_end_at']],
            'excluded_gps_point_count': r['excluded_gps_point_count'],
            'planned_km': round(r['planned_summary']['distance_m'] / 1000, 1),
            'actual_km': round(r['actual_summary']['distance_m'] / 1000, 1),
            'planned_duration_s': r['planned_summary']['duration_s'],
            'actual_duration_s': r['actual_summary']['duration_s'],
            'data_quality': r['data_quality'],
            'factory_return_at': r['factory_return_at'],
            'base_coordinate_source': r['base_coordinate_source'],
        }, ensure_ascii=False, indent=2))

    def test_plan_7_smoke(self):
        if not os.path.isfile(self.db_path):
            self.skipTest('canonical mock_data.db not present')
        r = self.results.get(7)
        if not r:
            self.skipTest('plan 7 not available')
        self.assertFalse(r['comparison_complete'])
        print('\n--- PLAN 7 SMOKE ---')
        print(json.dumps({
            'comparison_complete': r['comparison_complete'],
            'incomplete_reasons': r['incomplete_reasons'],
            'trip_window': [r['trip_window_start_at'], r['trip_window_end_at']],
            'excluded_gps_point_count': r['excluded_gps_point_count'],
            'planned_km': round(r['planned_summary']['distance_m'] / 1000, 1),
            'actual_km': round(r['actual_summary']['distance_m'] / 1000, 1),
            'data_quality': r['data_quality'],
            'factory_return_at': r['factory_return_at'],
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    unittest.main()

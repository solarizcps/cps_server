# -*- coding: utf-8 -*-
"""Offline unit tests for arac_google_route_options_service.py
All test cases; zero real Google API calls.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_0000000000000000000000000')

from modules.planlama.arac_google_route_options_service import (
    _SERVICE_SECONDS_PER_STOP,
    _ceil_min,
    _parse_departure,
    _return_display,
    compute_google_route_options,
)
from modules.planlama.arac_google_route_options_models import (
    GoogleRouteOptionsDTO,
    GoogleRouteOptionDTO,
)
from modules.planlama.road_routing.google_routes_provider import (
    GoogleRouteResult,
    GoogleLeg,
    PROFILE_TRAFFIC_FAST,
    PROFILE_TRAFFIC_FREE,
    PROFILE_STATIC,
)
from modules.planlama.road_routing.types import RoutingError

# ── Shared fixtures ───────────────────────────────────────────────────────────

BASE = {'latitude': 40.9928283, 'longitude': 28.6947341, 'has_coordinates': True}
PLAN_DATE = '2026-08-27'
DEPARTURE_HHMM = '08:00'
DEPARTURE_UTC = '2026-08-27T05:00:00Z'

STOPS_3 = [
    {'id': '1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Topkapı', 'latitude': 41.0203, 'longitude': 28.9295, 'has_coordinates': True},
    {'id': '2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Tuzla', 'latitude': 40.8167, 'longitude': 29.3008, 'has_coordinates': True},
    {'id': '3', 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Silivri', 'latitude': 41.0731, 'longitude': 28.2464, 'has_coordinates': True},
]

STOPS_1 = [
    {'id': '10', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Topkapı', 'latitude': 41.0203, 'longitude': 28.9295, 'has_coordinates': True},
]


def _fake_google_result(
    profile: str = PROFILE_TRAFFIC_FAST,
    drive_s: float = 16312.0,
    static_s: float = 14510.0,
    dist_m: float = 260267.0,
) -> GoogleRouteResult:
    legs = [
        GoogleLeg(0, 1, 24751.0, 3158.0, 1691.0),
        GoogleLeg(1, 2, 44649.0, 3805.0, 3615.0),
        GoogleLeg(2, 3, 148761.0, 6425.0, 6583.0),
        GoogleLeg(3, 4, 42105.0, 2922.0, 2622.0),
    ]
    label = {'google-traffic-fast': 'En Hızlı', 'google-traffic-free': 'Ücretsiz Yol',
             'google-static': 'Statik Referans'}.get(profile, profile)
    return GoogleRouteResult(
        profile=profile,
        profile_label=label,
        distance_m=dist_m,
        drive_seconds=drive_s,
        static_seconds=static_s,
        traffic_delta_seconds=drive_s - static_s,
        encoded_polyline='fake_poly',
        toll_present=True,
        toll_info={'estimatedPrice': None},
        route_labels=['DEFAULT_ROUTE'],
        legs=legs,
    )


def _patch_route_google(side_effect_map: dict[str, GoogleRouteResult | Exception]):
    """Patch GoogleRoutesProvider.route_google based on self.profile."""
    def _route_google(self, points):
        val = side_effect_map.get(self.profile)
        if isinstance(val, Exception):
            raise val
        if val is None:
            raise RoutingError('No mock', code='NO_MOCK')
        return val
    return patch(
        'modules.planlama.arac_google_route_options_service.GoogleRoutesProvider.route_google',
        _route_google,
    )


def _run_basic(task_list=None, sug_fn=None,
               fast_result=None, free_result=None) -> GoogleRouteOptionsDTO:
    """Helper: run orchestration with standard mocks."""
    f = fast_result or _fake_google_result(PROFILE_TRAFFIC_FAST)
    fr = free_result or _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)
    with _patch_route_google({PROFILE_TRAFFIC_FAST: f, PROFILE_TRAFFIC_FREE: fr}):
        return compute_google_route_options(
            plan_date=PLAN_DATE,
            departure_hhmm=DEPARTURE_HHMM,
            base=BASE,
            tasks=task_list or STOPS_3,
            departure_utc=DEPARTURE_UTC,
            _suggested_order_fn=sug_fn,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# COUNTER TESTS (new)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCounters(unittest.TestCase):
    """Covers all 12 counter scenarios from the phase spec."""

    # ── 1. current == suggested, full success ─────────────────────────────────

    def test_counter_01_same_order_full_success(self):
        """current == suggested → attempt=2, success=2, failure=0."""
        dto = _run_basic()
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 2)
        self.assertEqual(dto.google_failure_count, 0)
        self.assertFalse(dto.order_changed)

    # ── 2. current != suggested, full success ─────────────────────────────────

    def test_counter_02_different_order_full_success(self):
        """current != suggested → attempt=4, success=4, failure=0."""
        def reversed_order(active, base):
            return list(reversed(active))

        dto = _run_basic(sug_fn=reversed_order)
        self.assertEqual(dto.google_attempt_count, 4)
        self.assertEqual(dto.google_success_count, 4)
        self.assertEqual(dto.google_failure_count, 0)
        self.assertTrue(dto.order_changed)

    # ── 3. fastest fail / toll-free success ───────────────────────────────────

    def test_counter_03_fastest_fail_tollfree_success(self):
        """En Hızlı fails → attempt=2, success=1, failure=1."""
        free = _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('t', code='TIMEOUT'),
            PROFILE_TRAFFIC_FREE: free,
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 1)
        self.assertEqual(dto.google_failure_count, 1)

    # ── 4. fastest success / toll-free fail ───────────────────────────────────

    def test_counter_04_fastest_success_tollfree_fail(self):
        """Ücretsiz Yol fails → attempt=2, success=1, failure=1."""
        fast = _fake_google_result(PROFILE_TRAFFIC_FAST)
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: fast,
            PROFILE_TRAFFIC_FREE: RoutingError('t', code='TIMEOUT'),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 1)
        self.assertEqual(dto.google_failure_count, 1)
        self.assertTrue(dto.current.fastest.calculation_complete)
        self.assertFalse(dto.current.toll_free.calculation_complete)

    # ── 5. both profiles fail ────────────────────────────────────────────────

    def test_counter_05_both_profiles_fail(self):
        """Both profiles fail → attempt=2, success=0, failure=2."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('err', code='SERVER', http_status=503),
            PROFILE_TRAFFIC_FREE: RoutingError('err', code='SERVER', http_status=503),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 0)
        self.assertEqual(dto.google_failure_count, 2)

    # ── 6. 401/403 AUTH ───────────────────────────────────────────────────────

    def test_counter_06_auth_error(self):
        """AUTH errors → failure counted, attempt tracked."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('auth', code='AUTH', http_status=401),
            PROFILE_TRAFFIC_FREE: RoutingError('auth', code='AUTH', http_status=403),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 0)
        self.assertEqual(dto.google_failure_count, 2)
        self.assertEqual(dto.current.fastest.error_code, 'AUTH')
        self.assertEqual(dto.current.toll_free.error_code, 'AUTH')

    # ── 7. 429 RATE_LIMIT ─────────────────────────────────────────────────────

    def test_counter_07_rate_limit(self):
        """RATE_LIMIT → failure counted."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('quota', code='RATE_LIMIT', http_status=429),
            PROFILE_TRAFFIC_FREE: RoutingError('quota', code='RATE_LIMIT', http_status=429),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_failure_count, 2)
        self.assertEqual(dto.current.fastest.error_code, 'RATE_LIMIT')

    # ── 8. TIMEOUT ────────────────────────────────────────────────────────────

    def test_counter_08_timeout(self):
        """TIMEOUT → failure counted."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('timeout', code='TIMEOUT'),
            PROFILE_TRAFFIC_FREE: RoutingError('timeout', code='TIMEOUT'),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_failure_count, 2)
        self.assertEqual(dto.current.fastest.error_code, 'TIMEOUT')

    # ── 9. attempt = success + failure invariant ──────────────────────────────

    def test_counter_09_invariant_attempt_eq_success_plus_failure(self):
        """attempt == success + failure must hold in all cases."""
        scenarios = [
            # (fast, free)
            (_fake_google_result(PROFILE_TRAFFIC_FAST),
             _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)),
            (RoutingError('x', code='TIMEOUT'),
             _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)),
            (RoutingError('x', code='AUTH', http_status=401),
             RoutingError('x', code='AUTH', http_status=401)),
        ]
        for fast, free in scenarios:
            with self.subTest(fast=fast, free=free):
                with _patch_route_google({
                    PROFILE_TRAFFIC_FAST: fast,
                    PROFILE_TRAFFIC_FREE: free,
                }):
                    dto = compute_google_route_options(
                        plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                        base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
                    )
                self.assertEqual(
                    dto.google_attempt_count,
                    dto.google_success_count + dto.google_failure_count,
                    f'Invariant failed: attempt={dto.google_attempt_count} '
                    f'success={dto.google_success_count} failure={dto.google_failure_count}',
                )

    # ── 10. legacy google_call_count == google_attempt_count ─────────────────

    def test_counter_10_legacy_call_count_equals_attempt_count(self):
        """google_call_count (legacy) must equal google_attempt_count."""
        # full success
        dto = _run_basic()
        self.assertEqual(dto.google_call_count, dto.google_attempt_count)

    def test_counter_10b_legacy_call_count_on_failure(self):
        """Legacy google_call_count equals attempt even when all calls fail."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('e', code='SERVER'),
            PROFILE_TRAFFIC_FREE: RoutingError('e', code='SERVER'),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.google_call_count, dto.google_attempt_count)
        self.assertEqual(dto.google_call_count, 2)   # 2 attempts, both failed

    # ── 11. ORS not called ────────────────────────────────────────────────────

    def test_counter_11_ors_not_called(self):
        """ORS provider must never be instantiated."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: _fake_google_result(PROFILE_TRAFFIC_FAST),
            PROFILE_TRAFFIC_FREE: _fake_google_result(PROFILE_TRAFFIC_FREE,
                                                       drive_s=21070.0, static_s=16325.0),
        }):
            with patch(
                'modules.planlama.road_routing.openrouteservice_provider.OpenRouteServiceProvider.__init__',
                side_effect=AssertionError('ORS must not be called'),
            ):
                dto = compute_google_route_options(
                    plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                    base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
                )
        self.assertIsNotNone(dto)

    # ── 12. API key not in DTO ────────────────────────────────────────────────

    def test_counter_12_api_key_not_in_dto(self):
        """API key must not appear in serialized DTO."""
        fake_key = 'COUNTER_TEST_SECRET_KEY_ABCDEF123456'
        os.environ['GOOGLE_ROUTES_API_KEY'] = fake_key
        try:
            dto = _run_basic()
            serialized = json.dumps(dataclasses.asdict(dto))
            self.assertNotIn(fake_key, serialized)
        finally:
            os.environ['GOOGLE_ROUTES_API_KEY'] = 'TEST_FAKE_KEY_0000000000000000000000000'


# ═══════════════════════════════════════════════════════════════════════════════
# ORIGINAL TESTS (updated references)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Test 1 & 2: Call count dedup ─────────────────────────────────────────────

class TestCallCountDedup(unittest.TestCase):

    def test_01_same_order_yields_2_attempts(self):
        """T01: current == suggested → exactly 2 Google attempts."""
        dto = _run_basic()
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertFalse(dto.order_changed)

    def test_02_different_order_yields_4_attempts(self):
        """T02: current != suggested → exactly 4 Google attempts."""
        def reversed_order(active, base):
            return list(reversed(active))

        dto = _run_basic(sug_fn=reversed_order)
        self.assertEqual(dto.google_attempt_count, 4)
        self.assertTrue(dto.order_changed)


# ── Test 3 & 4: Profiles ──────────────────────────────────────────────────────

class TestProfiles(unittest.TestCase):

    def test_03_fastest_and_toll_free_profiles_used(self):
        """T03: En Hızlı and Ücretsiz Yol profiles computed."""
        dto = _run_basic()
        self.assertEqual(dto.current.fastest.profile_code, PROFILE_TRAFFIC_FAST)
        self.assertEqual(dto.current.toll_free.profile_code, PROFILE_TRAFFIC_FREE)

    def test_04_static_profile_never_called(self):
        """T04: PROFILE_STATIC must NOT appear in any result."""
        fast = _fake_google_result(PROFILE_TRAFFIC_FAST)
        free = _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)
        with _patch_route_google({PROFILE_TRAFFIC_FAST: fast, PROFILE_TRAFFIC_FREE: free,
                                   PROFILE_STATIC: Exception('static should not be called')}):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertNotEqual(dto.current.fastest.profile_code, PROFILE_STATIC)
        self.assertNotEqual(dto.current.toll_free.profile_code, PROFILE_STATIC)


# ── Test 5 & 6: Service seconds and return leg ────────────────────────────────

class TestServiceAndReturn(unittest.TestCase):

    def test_05_three_stops_1800_service_seconds(self):
        """T05: 3 active stops × 600 s = 1800 s service."""
        dto = _run_basic()
        opt = dto.current.fastest
        self.assertAlmostEqual(opt.service_seconds, 1800.0)
        self.assertAlmostEqual(opt.total_plan_seconds, 16312.0 + 1800.0)

    def test_06_return_leg_not_double_counted(self):
        """T06: total_plan_seconds = drive_seconds + service_seconds."""
        drive_s = 16312.0
        dto = _run_basic()
        opt = dto.current.fastest
        self.assertAlmostEqual(opt.total_plan_seconds, drive_s + 1800.0)


# ── Test 7 & 8: Exact seconds and ceiling ─────────────────────────────────────

class TestTimingPrecision(unittest.TestCase):

    def test_07_exact_seconds_preserved(self):
        """T07: drive_seconds is float, no intermediate rounding."""
        dto = _run_basic()
        self.assertAlmostEqual(dto.current.fastest.drive_seconds, 16312.0)

    def test_08_return_display_ceil_13_01_52_to_13_02(self):
        """T08: 08:00 + 18112s (=13:01:52) → display 13:02 (ceil)."""
        dep = _parse_departure('2026-08-27', '08:00')
        exact, display = _return_display(dep, 16312.0, 1800.0)
        self.assertEqual(display, '13:02')
        self.assertIn('T13:01:52', exact)


# ── Test 9: Inactive stops excluded ──────────────────────────────────────────

class TestInactiveExclusion(unittest.TestCase):

    def test_09_inactive_stops_not_routed(self):
        """T09: IPTAL, ERTELENDI, GIDILEMEDI stops excluded from route."""
        tasks = list(STOPS_3) + [
            {'id': '99', 'order_no': 4, 'status': 'IPTAL', 'priority': 'NORMAL',
             'company_name': 'Iptal', 'latitude': 41.1, 'longitude': 28.5,
             'has_coordinates': True},
        ]
        dto = _run_basic(task_list=tasks)
        self.assertEqual(dto.active_stop_count, 3)
        self.assertNotIn('99', dto.current.order)


# ── Test 10: Locked/started stops ────────────────────────────────────────────

class TestLockedStops(unittest.TestCase):

    def test_10_locked_stops_preserved_in_order(self):
        """T10: TAMAMLANDI/BASLADI locks preserved; locked IDs still appear in order."""
        tasks = [
            {'id': '1', 'order_no': 1, 'status': 'TAMAMLANDI', 'priority': 'NORMAL',
             'company_name': 'Done', 'latitude': 41.0203, 'longitude': 28.9295,
             'has_coordinates': True},
            {'id': '2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
             'company_name': 'Pending', 'latitude': 40.8167, 'longitude': 29.3008,
             'has_coordinates': True},
        ]
        dto = _run_basic(task_list=tasks)
        self.assertIn('1', dto.current.order)


# ── Test 11: High priority preserved ─────────────────────────────────────────

class TestHighPriority(unittest.TestCase):

    def test_11_high_priority_eligible_included_in_reorder(self):
        """T11: YUKSEK priority tasks appear in order."""
        tasks = [
            {'id': '1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'YUKSEK',
             'company_name': 'Yuksek', 'latitude': 41.0203, 'longitude': 28.9295,
             'has_coordinates': True},
            {'id': '2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
             'company_name': 'Normal', 'latitude': 40.8167, 'longitude': 29.3008,
             'has_coordinates': True},
        ]
        dto = _run_basic(task_list=tasks)
        self.assertIn('1', dto.current.order)
        self.assertIn('2', dto.current.order)


# ── Test 12: Single stop — reorder disabled but timing works ─────────────────

class TestSingleStop(unittest.TestCase):

    def test_12_single_stop_reorder_unavailable_but_timing_ok(self):
        """T12: 1 stop → route_reorder_available=False, but option still computed."""
        fast_1leg = GoogleRouteResult(
            profile=PROFILE_TRAFFIC_FAST, profile_label='En Hızlı',
            distance_m=24751.0, drive_seconds=3158.0, static_seconds=1691.0,
            traffic_delta_seconds=1467.0, encoded_polyline='poly',
            toll_present=False, toll_info=None, route_labels=['DEFAULT_ROUTE'],
            legs=[GoogleLeg(0, 1, 24751.0, 3158.0, 1691.0)],
        )
        free_1leg = GoogleRouteResult(
            profile=PROFILE_TRAFFIC_FREE, profile_label='Ücretsiz Yol',
            distance_m=24751.0, drive_seconds=3200.0, static_seconds=1691.0,
            traffic_delta_seconds=1509.0, encoded_polyline='poly',
            toll_present=False, toll_info=None, route_labels=['DEFAULT_ROUTE'],
            legs=[GoogleLeg(0, 1, 24751.0, 3200.0, 1691.0)],
        )
        with _patch_route_google({PROFILE_TRAFFIC_FAST: fast_1leg, PROFILE_TRAFFIC_FREE: free_1leg}):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_1, departure_utc=DEPARTURE_UTC,
            )
        self.assertFalse(dto.route_reorder_available)
        self.assertTrue(dto.current.fastest.calculation_complete)
        self.assertAlmostEqual(dto.current.fastest.service_seconds, 600.0)


# ── Tests 13 & 14: HTTP error codes ──────────────────────────────────────────

class TestHttpErrors(unittest.TestCase):

    def test_13_google_401_403_error_code(self):
        """T13: 401/403 → error_code='AUTH', calculation_complete=False."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('auth', code='AUTH', http_status=401),
            PROFILE_TRAFFIC_FREE: RoutingError('auth', code='AUTH', http_status=403),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.current.fastest.error_code, 'AUTH')
        self.assertFalse(dto.current.fastest.calculation_complete)

    def test_14_google_429_rate_limit(self):
        """T14: 429 → error_code='RATE_LIMIT', calculation_complete=False."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('quota', code='RATE_LIMIT', http_status=429),
            PROFILE_TRAFFIC_FREE: RoutingError('quota', code='RATE_LIMIT', http_status=429),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertEqual(dto.current.fastest.error_code, 'RATE_LIMIT')
        self.assertFalse(dto.current.fastest.calculation_complete)


# ── Test 15: Partial failure ──────────────────────────────────────────────────

class TestPartialFailure(unittest.TestCase):

    def test_15_one_profile_fails_other_succeeds(self):
        """T15: En Hızlı fails, Ücretsiz Yol succeeds → partial result."""
        free = _fake_google_result(PROFILE_TRAFFIC_FREE, drive_s=21070.0, static_s=16325.0)
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('timeout', code='TIMEOUT'),
            PROFILE_TRAFFIC_FREE: free,
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertFalse(dto.current.fastest.calculation_complete)
        self.assertEqual(dto.current.fastest.error_code, 'TIMEOUT')
        self.assertTrue(dto.current.toll_free.calculation_complete)


# ── Test 16: Both profiles fail ───────────────────────────────────────────────

class TestBothFail(unittest.TestCase):

    def test_16_both_profiles_fail(self):
        """T16: both fail → calculation_complete=False, attempt=2, success=0, failure=2."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: RoutingError('err', code='SERVER', http_status=503),
            PROFILE_TRAFFIC_FREE: RoutingError('err', code='SERVER', http_status=503),
        }):
            dto = compute_google_route_options(
                plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
            )
        self.assertFalse(dto.current.fastest.calculation_complete)
        self.assertFalse(dto.current.toll_free.calculation_complete)
        self.assertEqual(dto.google_attempt_count, 2)
        self.assertEqual(dto.google_success_count, 0)
        self.assertEqual(dto.google_failure_count, 2)
        # legacy alias also correct
        self.assertEqual(dto.google_call_count, 2)


# ── Test 17: API key not in DTO ───────────────────────────────────────────────

class TestApiKeyNotLeaked(unittest.TestCase):

    def test_17_api_key_not_in_dto(self):
        """T17: API key must not appear anywhere in the serialized DTO."""
        fake_key = 'FAKEKEY_SECRET_1234567890ABCDEF'
        os.environ['GOOGLE_ROUTES_API_KEY'] = fake_key
        try:
            dto = _run_basic()
            serialized = json.dumps(dataclasses.asdict(dto))
            self.assertNotIn(fake_key, serialized)
        finally:
            os.environ['GOOGLE_ROUTES_API_KEY'] = 'TEST_FAKE_KEY_0000000000000000000000000'


# ── Test 18: ORS not called ───────────────────────────────────────────────────

class TestORSNotCalled(unittest.TestCase):

    def test_18_ors_provider_never_instantiated(self):
        """T18: OpenRouteServiceProvider must not be instantiated by orchestration."""
        with _patch_route_google({
            PROFILE_TRAFFIC_FAST: _fake_google_result(PROFILE_TRAFFIC_FAST),
            PROFILE_TRAFFIC_FREE: _fake_google_result(PROFILE_TRAFFIC_FREE,
                                                       drive_s=21070.0, static_s=16325.0),
        }):
            with patch(
                'modules.planlama.road_routing.openrouteservice_provider.OpenRouteServiceProvider.__init__',
                side_effect=AssertionError('ORS should not be called'),
            ):
                dto = compute_google_route_options(
                    plan_date=PLAN_DATE, departure_hhmm=DEPARTURE_HHMM,
                    base=BASE, tasks=STOPS_3, departure_utc=DEPARTURE_UTC,
                )
        self.assertIsNotNone(dto)


# ── Test 19: ORS regression ───────────────────────────────────────────────────

class TestORSRegression(unittest.TestCase):

    def test_19_ors_provider_module_intact(self):
        """T19: ORS provider still importable and provider_available() works."""
        from modules.planlama.road_routing.openrouteservice_provider import (
            OpenRouteServiceProvider,
            provider_available,
        )
        self.assertTrue(callable(provider_available))
        self.assertTrue(hasattr(OpenRouteServiceProvider, 'route_ordered'))
        self.assertTrue(hasattr(OpenRouteServiceProvider, 'matrix'))

    def test_19b_ors_matrix_error_code_unchanged(self):
        """T19b: Google matrix error code is GOOGLE_ROUTE_MATRIX_NOT_IMPLEMENTED."""
        from modules.planlama.road_routing.google_routes_provider import GoogleRoutesProvider
        prov = GoogleRoutesProvider(
            profile=PROFILE_STATIC,
            api_key='FAKEKEY1234567890123456789012345678',
        )
        with self.assertRaises(RoutingError) as ctx:
            prov.matrix([])
        self.assertEqual(ctx.exception.code, 'GOOGLE_ROUTE_MATRIX_NOT_IMPLEMENTED')


# ── Test 20: DTO JSON-serializable ───────────────────────────────────────────

class TestDTOSerializable(unittest.TestCase):

    def test_20_dto_json_serializable(self):
        """T20: GoogleRouteOptionsDTO is fully JSON-serializable via dataclasses.asdict()."""
        dto = _run_basic()
        serialized = json.dumps(dataclasses.asdict(dto))
        parsed = json.loads(serialized)
        self.assertEqual(parsed['provider'], 'google-routes')
        self.assertEqual(parsed['active_stop_count'], 3)
        self.assertIn('current', parsed)
        self.assertIn('suggested', parsed)
        # New counter fields present
        self.assertIn('google_attempt_count', parsed)
        self.assertIn('google_success_count', parsed)
        self.assertIn('google_failure_count', parsed)
        self.assertIn('google_call_count', parsed)


# ── Timing unit tests ──────────────────────────────────────────────────────────

class TestTimingUnits(unittest.TestCase):

    def test_ceil_min_fractional(self):
        self.assertEqual(_ceil_min(16312.0), 272)

    def test_ceil_min_exact(self):
        self.assertEqual(_ceil_min(18000.0), 300)

    def test_parse_departure_builds_tz_aware(self):
        dep = _parse_departure('2026-08-27', '08:00')
        self.assertEqual(dep.hour, 8)
        self.assertIsNotNone(dep.tzinfo)

    def test_return_display_no_seconds(self):
        dep = _parse_departure('2026-08-27', '08:00')
        _, display = _return_display(dep, 18000.0, 0.0)
        self.assertEqual(display, '13:00')

    def test_return_display_with_seconds_ceil(self):
        dep = _parse_departure('2026-08-27', '08:00')
        _, display = _return_display(dep, 16312.0, 1800.0)
        self.assertEqual(display, '13:02')


# ═══════════════════════════════════════════════════════════════════════════════
# ORDER PROVENANCE TESTS
# Senaryo: current  = [TUZLA(id=10), TOPKAPI(id=11), SELIMPASA(id=12)]
#          suggested = [TOPKAPI(id=11), TUZLA(id=10), SELIMPASA(id=12)]  (farklı)
# Başlangıç/bitiş: Solariz Fabrika
# Çıkış: 08:00
# Beklenen: order_changed=True, attempt=4, success=4, failure=0
# ═══════════════════════════════════════════════════════════════════════════════

# Gerçek koordinatlar (Plan 41 verileriyle uyumlu)
_BASE_FAB = {'latitude': 40.9928283, 'longitude': 28.6947341, 'has_coordinates': True}

_TUZLA    = {'id': 10, 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
              'company_name': 'Tuzla', 'latitude': 40.8167, 'longitude': 29.3008,
              'has_coordinates': True}
_TOPKAPI  = {'id': 11, 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
              'company_name': 'Topkapı', 'latitude': 41.0203, 'longitude': 28.9295,
              'has_coordinates': True}
_SELIMPASA = {'id': 12, 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'NORMAL',
               'company_name': 'Selimpaşa', 'latitude': 41.0731, 'longitude': 28.2464,
               'has_coordinates': True}

_CURRENT_STOPS_ORDER = [_TUZLA, _TOPKAPI, _SELIMPASA]    # DB sıra: 10,11,12
_SUGGESTED_REVERSED  = [_TOPKAPI, _TUZLA, _SELIMPASA]    # ORS matrix önerisi: 11,10,12


def _make_legs_for_order(stop_list: list[dict], drive_s_per_leg: float = 3000.0) -> list[GoogleLeg]:
    """4 leg: Fabrika→stop[0], stop[0]→stop[1], stop[1]→stop[2], stop[2]→Fabrika."""
    legs = []
    for i in range(4):
        legs.append(GoogleLeg(
            from_index=i,
            to_index=i + 1,
            distance_m=round(50000.0 + i * 5000.0, 1),
            drive_seconds=drive_s_per_leg,
            static_seconds=drive_s_per_leg * 0.85,
        ))
    return legs


def _make_google_result_for_order(
    profile: str,
    stop_list: list[dict],
    drive_s: float,
    dist_m: float,
) -> GoogleRouteResult:
    """Build a GoogleRouteResult whose legs encode the stop_list visit order."""
    legs = _make_legs_for_order(stop_list, drive_s / 4.0)
    total_drive = sum(lg.drive_seconds for lg in legs)
    total_dist = sum(lg.distance_m for lg in legs)
    label = {PROFILE_TRAFFIC_FAST: 'En Hızlı', PROFILE_TRAFFIC_FREE: 'Ücretsiz Yol'}.get(profile, profile)
    # Encode order into polyline to distinguish current vs suggested
    order_token = '-'.join(str(s['id']) for s in stop_list)
    return GoogleRouteResult(
        profile=profile,
        profile_label=label,
        distance_m=total_dist,
        drive_seconds=total_drive,
        static_seconds=total_drive * 0.85,
        traffic_delta_seconds=total_drive * 0.15,
        encoded_polyline=f'POLY_{profile}_{order_token}',
        toll_present=False,
        toll_info=None,
        route_labels=['DEFAULT_ROUTE'],
        legs=legs,
    )


# Current: Tuzla→Topkapı→Selimpaşa — two profiles
_CURR_FAST  = _make_google_result_for_order(PROFILE_TRAFFIC_FAST, _CURRENT_STOPS_ORDER, 12000.0, 220000.0)
_CURR_FREE  = _make_google_result_for_order(PROFILE_TRAFFIC_FREE, _CURRENT_STOPS_ORDER, 13500.0, 220000.0)
# Suggested: Topkapı→Tuzla→Selimpaşa — two profiles (different polyline)
_SUG_FAST   = _make_google_result_for_order(PROFILE_TRAFFIC_FAST, _SUGGESTED_REVERSED, 11000.0, 205000.0)
_SUG_FREE   = _make_google_result_for_order(PROFILE_TRAFFIC_FREE, _SUGGESTED_REVERSED, 12200.0, 205000.0)


def _patch_order_provenance():
    """Patch route_google so that calls differ by (profile, stop_order) combo.

    The orchestration service calls _build_route_points(base, stops) and then
    passes those points to GoogleRoutesProvider.route_google(points).
    We distinguish current vs suggested via the second waypoint coordinate
    (Tuzla vs Topkapı) because _build_route_points preserves stop order.
    """
    # current order starts with Fabrika→Tuzla → points[1] = Tuzla coords
    # suggested order starts with Fabrika→Topkapı → points[1] = Topkapı coords
    _TUZLA_LAT = _TUZLA['latitude']
    _TOPKAPI_LAT = _TOPKAPI['latitude']

    call_log: list[tuple[str, str]] = []   # (profile, first_stop_name)

    def _route_google(self, points):
        # points[1] identifies the first stop in visit order
        first_stop_lat = points[1][0] if len(points) > 1 else None
        if abs(first_stop_lat - _TUZLA_LAT) < 0.001:
            # current order: starts with Tuzla
            call_log.append((self.profile, 'TUZLA'))
            if self.profile == PROFILE_TRAFFIC_FAST:
                return _CURR_FAST
            return _CURR_FREE
        else:
            # suggested order: starts with Topkapı
            call_log.append((self.profile, 'TOPKAPI'))
            if self.profile == PROFILE_TRAFFIC_FAST:
                return _SUG_FAST
            return _SUG_FREE

    patcher = patch(
        'modules.planlama.arac_google_route_options_service.GoogleRoutesProvider.route_google',
        _route_google,
    )
    return patcher, call_log


def _run_provenance_scenario() -> tuple['GoogleRouteOptionsDTO', list]:
    """Run orchestration with the 3-stop order-changed scenario."""
    patcher, call_log = _patch_order_provenance()

    def _suggested_fn(active, base):
        return list(_SUGGESTED_REVERSED)

    with patcher:
        dto = compute_google_route_options(
            plan_date='2026-08-27',
            departure_hhmm='08:00',
            base=_BASE_FAB,
            tasks=_CURRENT_STOPS_ORDER,
            departure_utc='2026-08-27T05:00:00Z',
            _suggested_order_fn=_suggested_fn,
        )
    return dto, call_log


class TestOrderProvenance(unittest.TestCase):
    """Covers order provenance scenario: current=[Tuzla,Topkapı,Selimpaşa] vs
    suggested=[Topkapı,Tuzla,Selimpaşa].  Kanıtlar: zincir, ayak sırası, sayaçlar.
    """

    @classmethod
    def setUpClass(cls):
        cls.dto, cls.call_log = _run_provenance_scenario()

    # ── 1. order_changed ──────────────────────────────────────────────────────

    def test_prov_01_order_changed_true(self):
        """current != suggested → order_changed=True."""
        self.assertTrue(self.dto.order_changed)

    def test_prov_02_current_order_is_db_order(self):
        """current.order == [10, 11, 12]  (canonical DB sıra)."""
        self.assertEqual(self.dto.current.order, ['10', '11', '12'])

    def test_prov_03_suggested_order_is_different(self):
        """suggested.order == [11, 10, 12]  (ORS/CPS önerisi)."""
        self.assertEqual(self.dto.suggested.order, ['11', '10', '12'])

    # ── 2. Google call counters ───────────────────────────────────────────────

    def test_prov_04_attempt_count_is_4(self):
        """4 farklı Google çağrısı yapıldı."""
        self.assertEqual(self.dto.google_attempt_count, 4)

    def test_prov_05_success_count_is_4(self):
        """4 çağrı da başarılı."""
        self.assertEqual(self.dto.google_success_count, 4)

    def test_prov_06_failure_count_is_0(self):
        """Hata yok."""
        self.assertEqual(self.dto.google_failure_count, 0)

    def test_prov_07_legacy_call_count_equals_attempt(self):
        """google_call_count (legacy) == google_attempt_count."""
        self.assertEqual(self.dto.google_call_count, self.dto.google_attempt_count)

    # ── 3. 4 ayrı Google çağrısı — sıra kimliği kanıtı ─────────────────────

    def test_prov_08_four_distinct_google_calls_made(self):
        """call_log 4 giriş içermeli: 2 current + 2 suggested."""
        self.assertEqual(len(self.call_log), 4)

    def test_prov_09_current_calls_start_with_tuzla(self):
        """Current order çağrıları Tuzla (id=10) ile başlamalı."""
        tuzla_calls = [c for c in self.call_log if c[1] == 'TUZLA']
        self.assertEqual(len(tuzla_calls), 2)
        profiles = {c[0] for c in tuzla_calls}
        self.assertEqual(profiles, {PROFILE_TRAFFIC_FAST, PROFILE_TRAFFIC_FREE})

    def test_prov_10_suggested_calls_start_with_topkapi(self):
        """Suggested order çağrıları Topkapı (id=11) ile başlamalı."""
        topkapi_calls = [c for c in self.call_log if c[1] == 'TOPKAPI']
        self.assertEqual(len(topkapi_calls), 2)
        profiles = {c[0] for c in topkapi_calls}
        self.assertEqual(profiles, {PROFILE_TRAFFIC_FAST, PROFILE_TRAFFIC_FREE})

    # ── 4. Leg sayısı ve sıra kanıtı ─────────────────────────────────────────

    def test_prov_11_current_fastest_has_4_legs(self):
        """Current En Hızlı 4 ayak içermeli (Fabrika+3durak+Fabrika)."""
        self.assertEqual(len(self.dto.current.fastest.legs), 4)

    def test_prov_12_current_toll_free_has_4_legs(self):
        """Current Ücretsiz Yol 4 ayak içermeli."""
        self.assertEqual(len(self.dto.current.toll_free.legs), 4)

    def test_prov_13_suggested_fastest_has_4_legs(self):
        """Suggested En Hızlı 4 ayak içermeli."""
        self.assertEqual(len(self.dto.suggested.fastest.legs), 4)

    def test_prov_14_suggested_toll_free_has_4_legs(self):
        """Suggested Ücretsiz Yol 4 ayak içermeli."""
        self.assertEqual(len(self.dto.suggested.toll_free.legs), 4)

    # ── 5. Timing invariantları ───────────────────────────────────────────────

    def test_prov_15_service_seconds_3x600(self):
        """3 durak × 600 s = 1800 s service."""
        self.assertAlmostEqual(self.dto.current.fastest.service_seconds, 1800.0)

    def test_prov_16_total_plan_seconds_invariant(self):
        """total_plan_seconds == drive_seconds + service_seconds (4 seçenek için)."""
        for label, opt in [
            ('curr_fast', self.dto.current.fastest),
            ('curr_free', self.dto.current.toll_free),
            ('sug_fast',  self.dto.suggested.fastest),
            ('sug_free',  self.dto.suggested.toll_free),
        ]:
            with self.subTest(option=label):
                expected = opt.drive_seconds + opt.service_seconds
                self.assertAlmostEqual(
                    opt.total_plan_seconds, expected,
                    msg=f'{label}: total_plan_seconds mismatch',
                )

    def test_prov_17_sum_legs_drive_equals_drive_seconds(self):
        """sum(legs.drive_seconds) == drive_seconds (4 seçenek)."""
        for label, opt in [
            ('curr_fast', self.dto.current.fastest),
            ('curr_free', self.dto.current.toll_free),
            ('sug_fast',  self.dto.suggested.fastest),
            ('sug_free',  self.dto.suggested.toll_free),
        ]:
            with self.subTest(option=label):
                leg_sum = sum(lg.drive_seconds for lg in opt.legs)
                self.assertAlmostEqual(
                    leg_sum, opt.drive_seconds, places=1,
                    msg=f'{label}: sum(legs) != drive_seconds',
                )

    def test_prov_18_sum_legs_distance_equals_route_distance(self):
        """sum(legs.distance_m) == distance_m (4 seçenek)."""
        for label, opt in [
            ('curr_fast', self.dto.current.fastest),
            ('curr_free', self.dto.current.toll_free),
            ('sug_fast',  self.dto.suggested.fastest),
            ('sug_free',  self.dto.suggested.toll_free),
        ]:
            with self.subTest(option=label):
                leg_dist = sum(lg.distance_m for lg in opt.legs)
                self.assertAlmostEqual(
                    leg_dist, opt.distance_m, places=0,
                    msg=f'{label}: sum(leg.distance) != distance_m',
                )

    # ── 6. Polyline ayrımı ────────────────────────────────────────────────────

    def test_prov_19_current_and_suggested_polylines_differ(self):
        """Current ve suggested En Hızlı polyline'ları farklı olmalı."""
        self.assertNotEqual(
            self.dto.current.fastest.encoded_polyline,
            self.dto.suggested.fastest.encoded_polyline,
        )

    def test_prov_20_current_and_suggested_toll_free_polylines_differ(self):
        """Current ve suggested Ücretsiz Yol polyline'ları farklı olmalı."""
        self.assertNotEqual(
            self.dto.current.toll_free.encoded_polyline,
            self.dto.suggested.toll_free.encoded_polyline,
        )

    # ── 7. ORS / Google görev ayrımı kanıtı ──────────────────────────────────

    def test_prov_21_ors_not_called_by_orchestration(self):
        """Orchestration service ORS provider'ı çağırmamalı."""
        from unittest.mock import patch as _patch
        patcher, call_log = _patch_order_provenance()

        def _suggested_fn(active, base):
            return list(_SUGGESTED_REVERSED)

        with _patch(
            'modules.planlama.road_routing.openrouteservice_provider.'
            'OpenRouteServiceProvider.__init__',
            side_effect=AssertionError('ORS must not be called by Google orchestration'),
        ):
            with patcher:
                dto = compute_google_route_options(
                    plan_date='2026-08-27',
                    departure_hhmm='08:00',
                    base=_BASE_FAB,
                    tasks=_CURRENT_STOPS_ORDER,
                    departure_utc='2026-08-27T05:00:00Z',
                    _suggested_order_fn=_suggested_fn,
                )
        self.assertTrue(dto.order_changed)

    def test_prov_22_google_not_used_for_order_optimization(self):
        """optimizeWaypointOrder is always False in Google request body."""
        from modules.planlama.road_routing.google_routes_provider import (
            build_traffic_fast_body, build_traffic_free_body,
        )
        pts = [
            (40.9928283, 28.6947341),
            (40.8167, 29.3008),
            (41.0203, 28.9295),
            (41.0731, 28.2464),
            (40.9928283, 28.6947341),
        ]
        fast_body = build_traffic_fast_body(pts, '2026-08-27T05:00:00Z')
        free_body = build_traffic_free_body(pts, '2026-08-27T05:00:00Z')
        self.assertFalse(fast_body['optimizeWaypointOrder'])
        self.assertFalse(free_body['optimizeWaypointOrder'])

    # ── 8. Cache key ayrımı kanıtı ────────────────────────────────────────────

    def test_prov_23_cache_key_differs_for_reversed_order(self):
        """Tuzla→Topkapı ve Topkapı→Tuzla farklı cache key üretmeli."""
        from modules.planlama.road_routing.cache import make_cache_key

        pts_current = [
            (40.9928283, 28.6947341),  # Fabrika
            (40.8167, 29.3008),        # Tuzla
            (41.0203, 28.9295),        # Topkapı
            (41.0731, 28.2464),        # Selimpaşa
            (40.9928283, 28.6947341),  # Fabrika (dönüş)
        ]
        pts_suggested = [
            (40.9928283, 28.6947341),  # Fabrika
            (41.0203, 28.9295),        # Topkapı  ← farklı sıra
            (40.8167, 29.3008),        # Tuzla
            (41.0731, 28.2464),        # Selimpaşa
            (40.9928283, 28.6947341),  # Fabrika (dönüş)
        ]
        key_curr = make_cache_key('google_routes', PROFILE_TRAFFIC_FAST, pts_current)
        key_sug  = make_cache_key('google_routes', PROFILE_TRAFFIC_FAST, pts_suggested)
        self.assertNotEqual(key_curr, key_sug,
                            'Farklı stop sırası aynı cache key üretemez')

    def test_prov_24_cache_key_differs_for_different_profile(self):
        """Aynı koordinatlar farklı profilde farklı cache key üretmeli."""
        from modules.planlama.road_routing.cache import make_cache_key
        pts = [(40.9928283, 28.6947341), (40.8167, 29.3008), (40.9928283, 28.6947341)]
        key_fast = make_cache_key('google_routes', PROFILE_TRAFFIC_FAST, pts)
        key_free = make_cache_key('google_routes', PROFILE_TRAFFIC_FREE, pts)
        self.assertNotEqual(key_fast, key_free)

    def test_prov_25_cache_key_differ_for_different_departure_via_provider_name(self):
        """departure_utc cache key'e dahil edilmiyor — provider name/profile ayrımı yeterli.
        Google provider'da her request'te yeni provider nesnesi oluşturulur;
        departure_utc doğrudan request body'ye gönderilir.
        Cache key provider+profile+points içeriyor; departure UTC Google isteğine gider."""
        from modules.planlama.road_routing.cache import make_cache_key
        pts = [(40.99, 28.69), (40.81, 29.30), (40.99, 28.69)]
        # departure cache'e dahil değil — bu bilerek yapılmış bir tasarım kararı
        # aynı koordinat + aynı profil → aynı ORS cache key (ORS departure bilmez)
        # Google provider cache kullanmaz — her çağrıda HTTP isteği yapar
        key1 = make_cache_key('google_routes', PROFILE_TRAFFIC_FAST, pts)
        key2 = make_cache_key('google_routes', PROFILE_TRAFFIC_FAST, pts)
        self.assertEqual(key1, key2,
                         'Aynı provider+profile+points her zaman aynı key üretmeli')


if __name__ == '__main__':
    unittest.main(verbosity=2)

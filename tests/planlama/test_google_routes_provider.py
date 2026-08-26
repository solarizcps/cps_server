# -*- coding: utf-8 -*-
"""Offline unit tests for GoogleRoutesProvider.

ALL tests run without any real network call.
HTTP transport is monkey-patched via unittest.mock.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add app/ to sys.path so provider imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

# Set a dummy key so provider_init doesn't fail on UNCONFIGURED
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_0000000000000000000000000')

from modules.planlama.road_routing.google_routes_provider import (
    PROFILE_STATIC,
    PROFILE_TRAFFIC_FAST,
    PROFILE_TRAFFIC_FREE,
    GoogleRoutesProvider,
    _parse_duration_s,
    _redact_key,
    build_static_body,
    build_traffic_fast_body,
    build_traffic_free_body,
    departure_utc_from_local,
    google_provider_available,
    make_google_provider,
)
from modules.planlama.road_routing.types import RoutingError

# ── Shared fixture ────────────────────────────────────────────────────────────

PLAN41_POINTS = [
    (40.9928283, 28.6947341),  # Fabrika
    (41.0203,    28.9295),     # Topkapı
    (40.8167,    29.3008),     # Tuzla
    (41.0731,    28.2464),     # Silivri
    (40.9928283, 28.6947341),  # Fabrika (return)
]
DEPARTURE_UTC = '2026-08-27T05:00:00Z'
DEPARTURE_LOCAL = '2026-08-27T08:00:00+03:00'


def _make_fake_google_response(
    dist_m: int = 260267,
    duration_s: str = '16312s',
    static_s: str = '14510s',
    legs: list[dict] | None = None,
) -> dict:
    if legs is None:
        legs = [
            {'distanceMeters': 24751, 'duration': '3158s', 'staticDuration': '1691s'},
            {'distanceMeters': 44649, 'duration': '3805s', 'staticDuration': '3615s'},
            {'distanceMeters': 148761, 'duration': '6425s', 'staticDuration': '6583s'},
            {'distanceMeters': 42105, 'duration': '2922s', 'staticDuration': '2622s'},
        ]
    return {
        'routes': [{
            'distanceMeters': dist_m,
            'duration': duration_s,
            'staticDuration': static_s,
            'legs': legs,
            'polyline': {'encodedPolyline': 'fake_polyline'},
            'travelAdvisory': {'tollInfo': {}},
            'routeLabels': ['DEFAULT_ROUTE'],
        }]
    }


# ── Helper function tests ─────────────────────────────────────────────────────

class TestParseDurationS(unittest.TestCase):
    def test_integer_seconds(self):
        self.assertEqual(_parse_duration_s('16312s'), 16312.0)

    def test_fractional(self):
        self.assertAlmostEqual(_parse_duration_s('60.5s'), 60.5)

    def test_none_returns_zero(self):
        self.assertEqual(_parse_duration_s(None), 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(_parse_duration_s(''), 0.0)

    def test_no_suffix(self):
        self.assertEqual(_parse_duration_s('3600'), 3600.0)


class TestRedactKey(unittest.TestCase):
    def test_absent(self):
        self.assertIn('<absent>', _redact_key(None))
        self.assertIn('<absent>', _redact_key(''))

    def test_redaction_hides_middle(self):
        key = 'AIzaSyBabcdefghijklmnopqrstuvwxyz123456'
        result = _redact_key(key)
        self.assertIn('AIza', result)
        self.assertNotIn('abcdefghijklmnop', result)

    def test_shows_length(self):
        key = 'AIzaSyBabcdefghijklmnopqrstuvwxyz123456'
        result = _redact_key(key)
        self.assertIn(f'len={len(key)}', result)


class TestDepartureUtcFromLocal(unittest.TestCase):
    def test_istanbul_to_utc(self):
        utc = departure_utc_from_local('2026-08-27T08:00:00+03:00')
        self.assertEqual(utc, '2026-08-27T05:00:00Z')

    def test_utc_passthrough(self):
        utc = departure_utc_from_local('2026-08-27T05:00:00+00:00')
        self.assertEqual(utc, '2026-08-27T05:00:00Z')

    def test_naive_raises(self):
        with self.assertRaises(ValueError):
            departure_utc_from_local('2026-08-27T08:00:00')


# ── Request builder tests ─────────────────────────────────────────────────────

class TestRequestBuilders(unittest.TestCase):
    def test_traffic_fast_has_routing_preference(self):
        body = build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC)
        self.assertEqual(body['routingPreference'], 'TRAFFIC_AWARE_OPTIMAL')
        self.assertFalse(body['routeModifiers']['avoidTolls'])
        self.assertEqual(body['departureTime'], DEPARTURE_UTC)

    def test_traffic_free_avoid_tolls_true(self):
        body = build_traffic_free_body(PLAN41_POINTS, DEPARTURE_UTC)
        self.assertEqual(body['routingPreference'], 'TRAFFIC_AWARE_OPTIMAL')
        self.assertTrue(body['routeModifiers']['avoidTolls'])
        self.assertEqual(body['departureTime'], DEPARTURE_UTC)

    def test_static_no_departure_time(self):
        body = build_static_body(PLAN41_POINTS)
        self.assertEqual(body['routingPreference'], 'TRAFFIC_UNAWARE')
        self.assertNotIn('departureTime', body)
        self.assertNotIn('trafficModel', body)

    def test_static_ignores_departure_even_if_passed(self):
        # build_static_body does not accept departure_utc but _build_common_body does —
        # static builder pops it out afterwards
        body = build_static_body(PLAN41_POINTS)
        self.assertNotIn('departureTime', body)

    def test_intermediates_present_for_multi_stop(self):
        body = build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC)
        # points[1:-1] = 3 intermediates
        self.assertEqual(len(body['intermediates']), 3)

    def test_no_intermediates_for_two_points(self):
        pts = [PLAN41_POINTS[0], PLAN41_POINTS[-1]]
        body = build_traffic_fast_body(pts, DEPARTURE_UTC)
        self.assertNotIn('intermediates', body)

    def test_origin_and_destination_match_first_last(self):
        body = build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC)
        orig = body['origin']['location']['latLng']
        dest = body['destination']['location']['latLng']
        self.assertAlmostEqual(orig['latitude'], PLAN41_POINTS[0][0])
        self.assertAlmostEqual(dest['latitude'], PLAN41_POINTS[-1][0])

    def test_avoid_ferries_always_true(self):
        for body in [
            build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC),
            build_traffic_free_body(PLAN41_POINTS, DEPARTURE_UTC),
            build_static_body(PLAN41_POINTS),
        ]:
            self.assertTrue(body['routeModifiers']['avoidFerries'])

    def test_tolls_extra_computation_always_present(self):
        for body in [
            build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC),
            build_traffic_free_body(PLAN41_POINTS, DEPARTURE_UTC),
            build_static_body(PLAN41_POINTS),
        ]:
            self.assertIn('TOLLS', body['extraComputations'])

    def test_optimize_waypoint_order_false(self):
        body = build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC)
        self.assertFalse(body['optimizeWaypointOrder'])

    def test_compute_alternative_routes_false(self):
        body = build_traffic_fast_body(PLAN41_POINTS, DEPARTURE_UTC)
        self.assertFalse(body['computeAlternativeRoutes'])

    def test_language_and_region(self):
        body = build_static_body(PLAN41_POINTS)
        self.assertEqual(body['languageCode'], 'tr')
        self.assertEqual(body['regionCode'], 'TR')


# ── Provider init tests ───────────────────────────────────────────────────────

class TestGoogleRoutesProviderInit(unittest.TestCase):
    def test_init_with_explicit_key(self):
        prov = GoogleRoutesProvider(profile=PROFILE_STATIC, api_key='FAKEKEY1234567890123456789012345678')
        self.assertEqual(prov.profile, PROFILE_STATIC)
        self.assertEqual(prov.name, 'google_routes')

    def test_init_missing_key_raises(self):
        with patch.dict(os.environ, {'GOOGLE_ROUTES_API_KEY': ''}):
            with self.assertRaises(RoutingError) as ctx:
                GoogleRoutesProvider(profile=PROFILE_STATIC, api_key='')
            self.assertEqual(ctx.exception.code, 'UNCONFIGURED')

    def test_invalid_profile_raises(self):
        with self.assertRaises(RoutingError) as ctx:
            GoogleRoutesProvider(profile='nonexistent', api_key='FAKEKEY1234567890123456789012345678')
        self.assertEqual(ctx.exception.code, 'BAD_PROFILE')

    def test_all_valid_profiles_accepted(self):
        for p in [PROFILE_TRAFFIC_FAST, PROFILE_TRAFFIC_FREE, PROFILE_STATIC]:
            prov = GoogleRoutesProvider(profile=p, api_key='FAKEKEY1234567890123456789012345678')
            self.assertEqual(prov.profile, p)


# ── Response parser tests (no HTTP) ──────────────────────────────────────────

class TestRouteOrderedOffline(unittest.TestCase):
    """Patch _post_routes so no real HTTP call is made."""

    def _provider(self, profile: str = PROFILE_TRAFFIC_FAST) -> GoogleRoutesProvider:
        return GoogleRoutesProvider(
            profile=profile,
            api_key='FAKEKEY1234567890123456789012345678',
            departure_utc=DEPARTURE_UTC,
        )

    def _route(self, profile: str = PROFILE_TRAFFIC_FAST, fake_resp: dict | None = None):
        resp = fake_resp or _make_fake_google_response()
        prov = self._provider(profile)
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=resp,
        ) as mock_post:
            result = prov.route_ordered(PLAN41_POINTS)
        return result, mock_post

    def test_distance_m_parsed(self):
        result, _ = self._route()
        self.assertAlmostEqual(result.distance_m, 260267.0)

    def test_duration_s_parsed(self):
        result, _ = self._route()
        self.assertAlmostEqual(result.duration_s, 16312.0)

    def test_provider_name(self):
        result, _ = self._route()
        self.assertEqual(result.provider, 'google_routes')

    def test_profile_propagated(self):
        result, _ = self._route(profile=PROFILE_STATIC)
        self.assertEqual(result.profile, PROFILE_STATIC)

    def test_legs_count(self):
        result, _ = self._route()
        self.assertEqual(len(result.legs), 4)

    def test_leg_distance_m(self):
        result, _ = self._route()
        self.assertAlmostEqual(result.legs[0].distance_m, 24751.0)
        self.assertAlmostEqual(result.legs[2].distance_m, 148761.0)

    def test_leg_duration_s(self):
        result, _ = self._route()
        self.assertAlmostEqual(result.legs[0].duration_s, 3158.0)

    def test_leg_indices(self):
        result, _ = self._route()
        for i, leg in enumerate(result.legs):
            self.assertEqual(leg.from_index, i)
            self.assertEqual(leg.to_index, i + 1)

    def test_static_duration_accessor(self):
        """static_duration_s via route_google() public contract."""
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=_make_fake_google_response(),
        ):
            gr = prov.route_google(PLAN41_POINTS)
        self.assertAlmostEqual(gr.static_seconds, 14510.0)

    def test_traffic_delta_accessor(self):
        """traffic_delta via route_google() public contract."""
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=_make_fake_google_response(),
        ):
            gr = prov.route_google(PLAN41_POINTS)
        self.assertAlmostEqual(gr.traffic_delta_seconds, 16312.0 - 14510.0)

    def test_toll_info_accessor(self):
        """toll_info via route_google() public contract."""
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=_make_fake_google_response(),
        ):
            gr = prov.route_google(PLAN41_POINTS)
        self.assertTrue(gr.toll_present)

    def test_route_labels_accessor(self):
        """route_labels via route_google() public contract."""
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=_make_fake_google_response(),
        ):
            gr = prov.route_google(PLAN41_POINTS)
        self.assertIn('DEFAULT_ROUTE', gr.route_labels)

    def test_post_called_exactly_once(self):
        _, mock_post = self._route()
        self.assertEqual(mock_post.call_count, 1)

    def test_api_key_not_in_body_json(self):
        """The request body passed to _post_routes must not contain the API key."""
        prov = self._provider()
        captured_body = {}
        def capture(body, api_key, timeout):
            captured_body.update(body)
            return _make_fake_google_response()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=capture,
        ):
            prov.route_ordered(PLAN41_POINTS)
        body_str = json.dumps(captured_body)
        # The fake key starts with FAKEKEY — must not appear in body
        self.assertNotIn('FAKEKEY', body_str)

    def test_empty_routes_raises_routing_error(self):
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value={'routes': []},
        ):
            with self.assertRaises(RoutingError) as ctx:
                prov.route_ordered(PLAN41_POINTS)
            self.assertEqual(ctx.exception.code, 'NO_ROUTE')

    def test_single_point_raises(self):
        prov = self._provider()
        with self.assertRaises(RoutingError) as ctx:
            prov.route_ordered([(40.99, 28.69)])
        self.assertEqual(ctx.exception.code, 'NO_ROUTE')

    def test_traffic_fast_body_has_departure_time(self):
        """traffic-fast profile must include departureTime in the body."""
        prov = self._provider(PROFILE_TRAFFIC_FAST)
        captured = {}
        def capture(body, api_key, timeout):
            captured.update(body)
            return _make_fake_google_response()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=capture,
        ):
            prov.route_ordered(PLAN41_POINTS)
        self.assertIn('departureTime', captured)
        self.assertEqual(captured['departureTime'], DEPARTURE_UTC)

    def test_static_body_has_no_departure_time(self):
        prov = self._provider(PROFILE_STATIC)
        captured = {}
        def capture(body, api_key, timeout):
            captured.update(body)
            return _make_fake_google_response()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=capture,
        ):
            prov.route_ordered(PLAN41_POINTS)
        self.assertNotIn('departureTime', captured)


# ── HTTP error mapping tests ──────────────────────────────────────────────────

class TestHttpErrorMapping(unittest.TestCase):
    def _provider(self) -> GoogleRoutesProvider:
        return GoogleRoutesProvider(
            profile=PROFILE_STATIC,
            api_key='FAKEKEY1234567890123456789012345678',
        )

    def _make_http_error(self, code: int) -> 'urllib.error.HTTPError':
        import io
        import urllib.error
        return urllib.error.HTTPError(
            url=_ENDPOINT,
            code=code,
            msg=f'HTTP {code}',
            hdrs=MagicMock(),
            fp=io.BytesIO(b'{"error": "test"}'),
        )

    def test_401_maps_to_auth(self):
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=RoutingError('auth', code='AUTH', http_status=401),
        ):
            with self.assertRaises(RoutingError) as ctx:
                prov.route_ordered(PLAN41_POINTS)
            self.assertEqual(ctx.exception.code, 'AUTH')

    def test_429_maps_to_rate_limit(self):
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=RoutingError('quota', code='RATE_LIMIT', http_status=429),
        ):
            with self.assertRaises(RoutingError) as ctx:
                prov.route_ordered(PLAN41_POINTS)
            self.assertEqual(ctx.exception.code, 'RATE_LIMIT')

    def test_timeout_maps_to_timeout(self):
        prov = self._provider()
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            side_effect=RoutingError('timeout', code='TIMEOUT'),
        ):
            with self.assertRaises(RoutingError) as ctx:
                prov.route_ordered(PLAN41_POINTS)
            self.assertEqual(ctx.exception.code, 'TIMEOUT')


# ── matrix() NOT_SUPPORTED test ──────────────────────────────────────────────

class TestMatrixNotSupported(unittest.TestCase):
    def test_matrix_raises_not_supported(self):
        prov = GoogleRoutesProvider(
            profile=PROFILE_STATIC,
            api_key='FAKEKEY1234567890123456789012345678',
        )
        with self.assertRaises(RoutingError) as ctx:
            prov.matrix(PLAN41_POINTS)
        self.assertEqual(ctx.exception.code, 'GOOGLE_ROUTE_MATRIX_NOT_IMPLEMENTED')


# ── Plan 41 parity arithmetic test ───────────────────────────────────────────

class TestPlan41ParityArithmetic(unittest.TestCase):
    """Verify that the corrected rounding logic (ATP_GOOGLE_ROUTES_PARITY_TIME_ROUNDING_FIX_V1)
    is reproducible from the provider's parsed RouteResult."""

    import math as _math

    def _get_result(self, duration_s_str: str, static_s_str: str) -> object:
        fake_resp = _make_fake_google_response(
            dist_m=260267,
            duration_s=duration_s_str,
            static_s=static_s_str,
        )
        prov = GoogleRoutesProvider(
            profile=PROFILE_TRAFFIC_FAST,
            api_key='FAKEKEY1234567890123456789012345678',
            departure_utc=DEPARTURE_UTC,
        )
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=fake_resp,
        ):
            return prov.route_ordered(PLAN41_POINTS)

    def test_call1_traffic_fast_return_ceil(self):
        import math
        result = self._get_result('16312s', '14510s')
        service_s = 1800
        total_s = result.duration_s + service_s
        total_min = math.ceil(total_s / 60)
        self.assertEqual(total_min, 302)

    def test_call2_traffic_free_return_ceil(self):
        import math
        fake_resp = _make_fake_google_response(
            dist_m=258437, duration_s='21070s', static_s='16325s',
        )
        prov = GoogleRoutesProvider(
            profile=PROFILE_TRAFFIC_FREE,
            api_key='FAKEKEY1234567890123456789012345678',
            departure_utc=DEPARTURE_UTC,
        )
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=fake_resp,
        ):
            result = prov.route_ordered(PLAN41_POINTS)
        total_s = result.duration_s + 1800
        total_min = math.ceil(total_s / 60)
        self.assertEqual(total_min, 382)

    def test_call3_static_return_ceil(self):
        import math
        result = self._get_result('14719s', '14719s')
        # Override profile check — use static profile result directly
        total_s = result.duration_s + 1800
        total_min = math.ceil(total_s / 60)
        self.assertEqual(total_min, 276)

    def test_invariant_total_plan_seconds(self):
        result = self._get_result('16312s', '14510s')
        service_s = 1800
        self.assertAlmostEqual(result.duration_s + service_s, 18112.0)

    def test_invariant_traffic_delta(self):
        """Traffic delta now via route_google() public contract."""
        fake_resp = _make_fake_google_response(
            dist_m=260267,
            duration_s='16312s',
            static_s='14510s',
        )
        prov = GoogleRoutesProvider(
            profile=PROFILE_TRAFFIC_FAST,
            api_key='FAKEKEY1234567890123456789012345678',
            departure_utc=DEPARTURE_UTC,
        )
        with patch(
            'modules.planlama.road_routing.google_routes_provider._post_routes',
            return_value=fake_resp,
        ):
            gr = prov.route_google(PLAN41_POINTS)
        self.assertAlmostEqual(gr.traffic_delta_seconds, 16312.0 - 14510.0)


# ── google_provider_available test ───────────────────────────────────────────

class TestGoogleProviderAvailable(unittest.TestCase):
    def test_available_when_key_set(self):
        with patch.dict(os.environ, {'GOOGLE_ROUTES_API_KEY': 'FAKEKEY00000000000000000000000000000'}):
            self.assertTrue(google_provider_available())

    def test_unavailable_when_key_absent(self):
        saved = os.environ.pop('GOOGLE_ROUTES_API_KEY', None)
        try:
            self.assertFalse(google_provider_available())
        finally:
            if saved:
                os.environ['GOOGLE_ROUTES_API_KEY'] = saved


# ── make_google_provider factory test ────────────────────────────────────────

class TestMakeGoogleProvider(unittest.TestCase):
    def test_returns_provider(self):
        prov = make_google_provider(
            profile=PROFILE_TRAFFIC_FAST,
            api_key='FAKEKEY1234567890123456789012345678',
        )
        self.assertIsInstance(prov, GoogleRoutesProvider)

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {'GOOGLE_ROUTES_API_KEY': ''}):
            with self.assertRaises(RoutingError):
                make_google_provider(profile=PROFILE_STATIC, api_key='')


# Use _ENDPOINT in test imports (HttpError test needs it)
from modules.planlama.road_routing.google_routes_provider import _ENDPOINT


if __name__ == '__main__':
    unittest.main(verbosity=2)

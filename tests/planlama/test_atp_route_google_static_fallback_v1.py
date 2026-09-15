# -*- coding: utf-8 -*-
"""ORS kesintisinde google-static yedeği + geçmiş departureTime koruması (offline).

Kapsanan senaryolar:
  1. ORS başarılı  → mevcut davranış korunur (yedek yok).
  2. ORS kota (RATE_LIMIT) → google-static ile çizgi + mevcut plan km/süre.
  3. İki servis de hatalı → sahte değer yok, hata kodu döner.
  4. Geçmiş çıkış saati → Google'a 0 istek, PAST_DEPARTURE.
  5. Gelecek çıkış saati → Google trafik çağrıları başarılı.

Gerçek HTTP çağrısı yapılmaz; DB yazılmaz.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_0000000000000000000000000')

from modules.planlama.arac_google_route_options_service import (  # noqa: E402
    compute_google_route_options,
)
from modules.planlama.road_routing import google_static_fallback as gsf  # noqa: E402
from modules.planlama.road_routing import route_planner_service as rps  # noqa: E402
from modules.planlama.road_routing.cache import cache_clear  # noqa: E402
from modules.planlama.road_routing.google_routes_provider import (  # noqa: E402
    PROFILE_STATIC,
    GoogleLeg,
    GoogleRouteResult,
)
from modules.planlama.road_routing.types import (  # noqa: E402
    RouteLeg,
    RouteMatrix,
    RouteResult,
    RoutingError,
)

BASE = {'latitude': 40.9928283, 'longitude': 28.6947341, 'has_coordinates': True}

TASKS = [
    {'id': '1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Topkapı', 'latitude': 41.0203, 'longitude': 28.9295, 'has_coordinates': True},
    {'id': '2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Tuzla', 'latitude': 40.8167, 'longitude': 29.3008, 'has_coordinates': True},
    {'id': '3', 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'Silivri', 'latitude': 41.0731, 'longitude': 28.2464, 'has_coordinates': True},
]

# Google dokümantasyon örneği — 3 noktaya çözülür.
POLYLINE = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'

PAST_DATE = '2026-09-01'
FUTURE_DATE = '2099-09-01'
DEPARTURE_HHMM = '08:00'


# ── Sahte sağlayıcılar ────────────────────────────────────────────────────────

class _FakeOrs:
    """ORS sözleşmesini taklit eder; hata enjekte edilebilir."""

    name = 'ors'
    profile = 'driving-car'

    def __init__(self, route_error: RoutingError | None = None):
        self.route_error = route_error
        self.route_calls = 0
        self.matrix_calls = 0

    def route_ordered(self, points):
        self.route_calls += 1
        if self.route_error is not None:
            raise self.route_error
        pts = list(points)
        return RouteResult(
            provider='ors',
            profile='driving-car',
            distance_m=200000.0,
            duration_s=10800.0,
            geometry=[[float(a), float(b)] for a, b in pts],
            legs=[RouteLeg(i, i + 1, 50000.0, 2700.0) for i in range(len(pts) - 1)],
        )

    def matrix(self, points):
        self.matrix_calls += 1
        n = len(list(points))
        grid = [[abs(i - j) * 1000.0 for j in range(n)] for i in range(n)]
        return RouteMatrix(
            provider='ors', profile='driving-car', distance_m=grid, duration_s=grid,
        )


class _FakeGoogleStatic:
    """Sadece PROFILE_STATIC bekler; trafik profili gelirse test kırılır."""

    instances: list[str] = []

    def __init__(self, profile=None, departure_utc=None, api_key=None, timeout=None):
        assert profile == PROFILE_STATIC, f'yedek statik olmalı: {profile!r}'
        assert departure_utc is None, 'statik profilde departureTime gönderilmez'
        _FakeGoogleStatic.instances.append(profile)

    def route_google(self, points):
        pts = list(points)
        return GoogleRouteResult(
            profile=PROFILE_STATIC,
            profile_label='Statik Referans',
            distance_m=123400.0,
            drive_seconds=6000.0,
            static_seconds=6000.0,
            traffic_delta_seconds=0.0,
            encoded_polyline=POLYLINE,
            toll_present=False,
            toll_info=None,
            route_labels=['DEFAULT_ROUTE'],
            legs=[
                GoogleLeg(i, i + 1, 30850.0, 1500.0, 1500.0)
                for i in range(len(pts) - 1)
            ],
        )


class _FailingGoogleStatic(_FakeGoogleStatic):
    def route_google(self, points):
        raise RoutingError('google auth', code='AUTH', http_status=403)


def _google_raw_response() -> dict:
    return {
        'routes': [{
            'distanceMeters': 260267,
            'duration': '16312s',
            'staticDuration': '14510s',
            'polyline': {'encodedPolyline': POLYLINE},
            'legs': [
                {'distanceMeters': 24751, 'duration': '3158s', 'staticDuration': '1691s'},
                {'distanceMeters': 44649, 'duration': '3805s', 'staticDuration': '3615s'},
                {'distanceMeters': 148761, 'duration': '6425s', 'staticDuration': '6583s'},
                {'distanceMeters': 42105, 'duration': '2922s', 'staticDuration': '2622s'},
            ],
        }],
    }


@pytest.fixture(autouse=True)
def _clean_state():
    cache_clear()
    _FakeGoogleStatic.instances = []
    with patch.object(rps, 'load_visit_states_for_tasks', return_value={}):
        yield
    cache_clear()


def _dto(provider, *, google_cls=None, google_ready=True):
    stack = []
    if google_cls is not None:
        stack.append(patch.object(gsf, 'GoogleRoutesProvider', google_cls))
    stack.append(patch.object(gsf, 'google_provider_available', return_value=google_ready))
    for ctx in stack:
        ctx.start()
    try:
        return rps.build_plan_route_dto(BASE, TASKS, provider=provider)
    finally:
        for ctx in reversed(stack):
            ctx.stop()


# ── 1. ORS başarılı → mevcut davranış ─────────────────────────────────────────

def test_ors_success_keeps_current_behaviour():
    ors = _FakeOrs()
    dto = _dto(ors, google_cls=_FakeGoogleStatic)

    assert dto['status'] == 'OK'
    assert dto['current']['provider'] == 'ors'
    assert dto['current']['km'] == 200.0
    assert len(dto['current']['geometry']) >= 2
    assert 'route_fallback_provider' not in dto
    assert _FakeGoogleStatic.instances == []          # Google hiç kurulmadı
    assert ors.matrix_calls == 1                      # matrix akışı korunuyor
    assert isinstance(dto['gain']['km'], (int, float))
    assert dto['suggested']['apply_disabled_reason'] != 'NO_MATRIX_FALLBACK'
    codes = [w.get('code') for w in dto['warnings']]
    assert gsf.FALLBACK_WARNING_CODE not in codes


# ── 2. ORS kota hatası → google-static yedeği ─────────────────────────────────

@pytest.mark.parametrize('code', sorted(gsf.ORS_FALLBACK_CODES))
def test_ors_failure_falls_back_to_google_static(code):
    ors = _FakeOrs(RoutingError('ors down', code=code, http_status=429))
    dto = _dto(ors, google_cls=_FakeGoogleStatic)

    # Çizgi + mevcut plan km/süre google-static'ten
    assert dto['status'] == 'OK'
    assert dto['current']['provider'] == 'google-static'
    assert dto['current']['km'] == 123.4
    assert dto['current']['duration_label'] == '1 sa 40 dk'
    assert len(dto['current']['geometry']) == 3
    assert dto['route_fallback_provider'] == 'google-static'

    # Matrix yok → önerilen sıra mevcut sıra
    assert ors.matrix_calls == 0
    assert dto['suggested']['full_task_ids'] == dto['current']['full_task_ids']
    assert dto['suggested']['apply_enabled'] is False
    assert dto['suggested']['apply_disabled_reason'] == 'NO_MATRIX_FALLBACK'

    # Kazanç kartlarında sahte değer yok
    assert dto['suggested']['km'] == '—'
    assert dto['suggested']['duration_label'] == '—'
    assert dto['gain'] == {'km': '—', 'duration_label': '—', 'duration_min': None, 'pct': '—'}
    assert dto['gain_negative'] is False
    assert dto['gain_zero'] is False

    # Uyarı sağlayıcıyı belirtir
    warn = [w for w in dto['warnings'] if w.get('code') == gsf.FALLBACK_WARNING_CODE]
    assert len(warn) == 1
    assert warn[0]['provider'] == 'google-static'
    assert 'google-static fallback' in warn[0]['message']
    assert 'google-static' in dto['decision_reason']


def test_ors_bad_request_does_not_fall_back():
    """Kapsam dışı ORS hatası (BAD_REQUEST) yedek tetiklemez."""
    ors = _FakeOrs(RoutingError('bad', code='BAD_REQUEST', http_status=400))
    dto = _dto(ors, google_cls=_FakeGoogleStatic)

    assert dto['status'] == 'BAD_REQUEST'
    assert _FakeGoogleStatic.instances == []
    assert 'route_fallback_provider' not in dto


def test_no_fallback_when_google_key_absent():
    ors = _FakeOrs(RoutingError('quota', code='RATE_LIMIT', http_status=429))
    dto = _dto(ors, google_cls=_FakeGoogleStatic, google_ready=False)

    assert dto['status'] == 'RATE_LIMIT'
    assert _FakeGoogleStatic.instances == []


# ── 3. İki servis de hatalı ───────────────────────────────────────────────────

def test_both_services_fail_returns_ors_error_without_fake_values():
    ors = _FakeOrs(RoutingError('quota exceeded', code='RATE_LIMIT', http_status=429))
    dto = _dto(ors, google_cls=_FailingGoogleStatic)

    assert dto['status'] == 'RATE_LIMIT'
    assert dto['message'] == 'quota exceeded'
    assert dto['current']['km'] == '—'
    assert dto['current']['geometry'] == []
    assert dto['suggested']['km'] == '—'
    assert dto['gain'] == {'km': '—', 'duration_label': '—', 'pct': '—'}
    assert 'route_fallback_provider' not in dto


# ── 4-5. Google trafik: geçmiş / gelecek çıkış saati ──────────────────────────

def _run_google_options(plan_date: str):
    posted: list[dict] = []

    def _fake_post(body, api_key, timeout):
        posted.append(body)
        return _google_raw_response()

    with patch(
        'modules.planlama.road_routing.google_routes_provider._post_routes',
        side_effect=_fake_post,
    ):
        dto = compute_google_route_options(
            plan_date=plan_date,
            departure_hhmm=DEPARTURE_HHMM,
            base=BASE,
            tasks=TASKS,
        )
    return dto, posted


def test_past_departure_makes_zero_google_calls():
    dto, posted = _run_google_options(PAST_DATE)

    assert posted == []                       # Google'a hiç istek gitmedi
    assert dto.google_success_count == 0
    assert dto.current.fastest.error_code == 'PAST_DEPARTURE'
    assert dto.current.toll_free.error_code == 'PAST_DEPARTURE'
    assert dto.current.fastest.calculation_complete is False
    assert dto.current.fastest.distance_m == 0.0


def test_future_departure_calls_google_and_succeeds():
    dto, posted = _run_google_options(FUTURE_DATE)

    assert len(posted) == 2                   # En Hızlı + Ücretsiz Yol
    assert all(b.get('departureTime') for b in posted)
    assert dto.google_attempt_count == 2
    assert dto.google_success_count == 2
    assert dto.google_failure_count == 0
    assert dto.current.fastest.error_code is None
    assert dto.current.fastest.calculation_complete is True
    assert dto.current.fastest.distance_km_display == 260.3

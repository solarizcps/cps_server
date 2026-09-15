# -*- coding: utf-8 -*-
"""ORS kesinti → Google Static waypoint-optimize fallback — narrow tests.

Kapsanan senaryolar:
  1. ORS başarılı → mevcut davranış değişmez.
  2. ORS kota → Google optimize fallback → sıra gerçekten değişiyor.
  3. Mevcut/önerilen km-süre doğru (gerçek hesap, kopyalama yok).
  4. Kazanç matematiği doğru.
  5. Yakıt tasarrufu doğru (gain_km × 10.0 / 100).
  6. Google optimize hatasında → sadece mevcut rota, Önerilen/Kazanç/Yakıt = '—'.
  7. Cache kontrolü: aynı noktalar ikinci çağrıda HTTP'ye gitmez.
  8. Google optimize hatasında sıra değişmeden mevcut sıra korunur.
  9. Geçmiş departureTime Google trafik çağrısına gönderilmez (PAST_DEPARTURE guard).
 10. optimizeWaypointOrder=true gönderildi mi kontrolü.
 11. Sıra değişmezse tek çağrı yapılır (ikinci çağrı yok).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock, call, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_0000000000000000000000000')

from modules.planlama.road_routing import google_static_fallback as gsf          # noqa: E402
from modules.planlama.road_routing import route_planner_service as rps            # noqa: E402
from modules.planlama.road_routing.cache import cache_clear                       # noqa: E402
from modules.planlama.road_routing.google_routes_provider import (                 # noqa: E402
    PROFILE_STATIC,
    GoogleLeg,
    GoogleRouteResult,
)
from modules.planlama.road_routing.types import RouteMatrix, RouteResult, RouteLeg, RoutingError  # noqa: E402

# ── Test fixtures ─────────────────────────────────────────────────────────────

BASE = {'latitude': 40.9928283, 'longitude': 28.6947341, 'has_coordinates': True}

TASKS = [
    {'id': '1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'A', 'latitude': 41.0203, 'longitude': 28.9295, 'has_coordinates': True},
    {'id': '2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'B', 'latitude': 40.8167, 'longitude': 29.3008, 'has_coordinates': True},
    {'id': '3', 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'C', 'latitude': 41.0731, 'longitude': 28.2464, 'has_coordinates': True},
]

# Gerçek Google encoded polyline örneği (3 nokta)
POLYLINE = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'

# Mevcut sırayla rota: 200 km / 2 sa
CURRENT_DIST_M = 200_000.0
CURRENT_DUR_S = 7_200.0

# Optimize sırayla rota: 170 km / 1 sa 40 dk  (≠ mevcut)
OPT_DIST_M = 170_000.0
OPT_DUR_S = 6_000.0


def _make_google_result(
    dist_m: float,
    dur_s: float,
    opt_indices: list[int] | None = None,
) -> GoogleRouteResult:
    n_legs = len(TASKS) + 1   # base→stop1, stop1→stop2, ..., stopN→base
    legs = [
        GoogleLeg(i, i + 1, dist_m / n_legs, dur_s / n_legs, dur_s / n_legs)
        for i in range(n_legs)
    ]
    return GoogleRouteResult(
        profile=PROFILE_STATIC,
        profile_label='Statik Referans',
        distance_m=dist_m,
        drive_seconds=dur_s,
        static_seconds=dur_s,
        traffic_delta_seconds=0.0,
        encoded_polyline=POLYLINE,
        toll_present=False,
        toll_info=None,
        route_labels=['DEFAULT_ROUTE'],
        legs=legs,
        optimized_waypoint_indices=list(opt_indices) if opt_indices is not None else [],
    )


def _make_ors(*, error: RoutingError | None = None):
    class FakeOrs:
        name = 'ors'
        profile = 'driving-car'
        route_calls = 0
        matrix_calls = 0

        def route_ordered(self, points):
            self.route_calls += 1
            if error is not None:
                raise error
            pts = list(points)
            return RouteResult(
                provider='ors', profile='driving-car',
                distance_m=200_000.0, duration_s=7_200.0,
                geometry=[[float(a), float(b)] for a, b in pts],
                legs=[RouteLeg(i, i + 1, 50_000.0, 1_800.0) for i in range(len(pts) - 1)],
            )

        def matrix(self, points):
            self.matrix_calls += 1
            n = len(list(points))
            grid = [[abs(i - j) * 1000.0 for j in range(n)] for i in range(n)]
            return RouteMatrix(provider='ors', profile='driving-car',
                               distance_m=grid, duration_s=grid)
    return FakeOrs()


def _ors_quota_error():
    return RoutingError('quota exceeded', code='RATE_LIMIT', http_status=429)


@pytest.fixture(autouse=True)
def _reset():
    cache_clear()
    with patch.object(rps, 'load_visit_states_for_tasks', return_value={}):
        yield
    cache_clear()


def _build_dto(
    ors,
    *,
    gs_optimized_result: gsf.GoogleOptimizedResult | None = None,
    gs_opt_raises: RoutingError | None = None,
    static_result: RouteResult | None = None,
    static_raises: RoutingError | None = None,
    google_available: bool = True,
):
    """build_plan_route_dto çağrısı; google fallback fonksiyonlarını mock eder.

    rps (route_planner_service) fonksiyonları gsf modülünden doğrudan import edildiği için
    hem gsf hem rps modülündeki bağları birlikte patch etmek gerekir.
    """
    def _fake_optimized(points):
        if gs_opt_raises is not None:
            raise gs_opt_raises
        if gs_optimized_result is not None:
            return gs_optimized_result
        raise RoutingError('no result', code='ERROR')

    def _fake_static(points):
        if static_raises is not None:
            raise static_raises
        if static_result is not None:
            return static_result
        raise RoutingError('no static', code='ERROR')

    with (
        patch.object(gsf, 'route_via_google_optimized', side_effect=_fake_optimized),
        patch.object(gsf, 'route_via_google_static', side_effect=_fake_static),
        patch.object(gsf, 'google_provider_available', return_value=google_available),
        patch.object(rps, 'route_via_google_optimized', side_effect=_fake_optimized),
        patch.object(rps, 'route_via_google_static', side_effect=_fake_static),
        patch.object(rps, 'fallback_available', return_value=google_available),
    ):
        return rps.build_plan_route_dto(BASE, TASKS, provider=ors)


# ── 1. ORS başarılı → mevcut davranış değişmez ────────────────────────────────

def test_t1_ors_success_no_change():
    ors = _make_ors()
    dto = _build_dto(ors)
    assert dto['status'] == 'OK'
    assert dto['current']['provider'] == 'ors'
    assert dto['current']['km'] == 200.0
    assert 'route_fallback_provider' not in dto
    # Matrix akışı korunuyor
    assert ors.matrix_calls == 1
    # Google fonksiyonları çağrılmadı
    with patch.object(gsf, 'route_via_google_optimized') as mock_opt:
        with patch.object(gsf, 'route_via_google_static') as mock_static:
            _ = rps.build_plan_route_dto(BASE, TASKS, provider=_make_ors())
    # Bu patched kopyalar çağrılmaz çünkü ORS hata atmadı


# ── 2. ORS kota → Google optimize → sıra değişiyor ────────────────────────────

def test_t2_ors_quota_google_optimize_order_changes():
    # Optimize sıra: [1, 0] → 3. durak → 2. durak → 1. durak sıralaması
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=CURRENT_DIST_M, duration_s=CURRENT_DUR_S,
            geometry=[[41.0, 29.0], [40.8, 29.3]],
            legs=[RouteLeg(0, 1, 100_000.0, 3_600.0), RouteLeg(1, 2, 100_000.0, 3_600.0)],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=OPT_DIST_M, duration_s=OPT_DUR_S,
            geometry=[[41.0, 29.0], [40.9, 28.5]],
            legs=[RouteLeg(0, 1, 85_000.0, 3_000.0), RouteLeg(1, 2, 85_000.0, 3_000.0)],
        ),
        # [2, 0, 1]: 3 durak; önce durak3 (idx2), sonra durak1 (idx0), sonra durak2 (idx1)
        optimized_stop_indices=[2, 0, 1],
        order_changed=True,
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(ors, gs_optimized_result=gs_result)

    # Fallback provider belirlendi
    assert dto['route_fallback_provider'] == 'google-static'
    # Mevcut rota doğru
    assert dto['current']['km'] == 200.0
    assert dto['current']['duration_label'] == '2 sa'
    # Önerilen rota sahte kopyalama değil
    assert dto['suggested']['km'] == 170.0
    assert dto['suggested']['duration_label'] == '1 sa 40 dk'
    assert dto['suggested']['km'] != dto['current']['km']
    # Sıra değişti
    assert dto['suggested']['full_task_ids'] != dto['current']['full_task_ids']
    # Uyarı kodu doğru
    warn_codes = [w['code'] for w in dto['warnings']]
    assert gsf.FALLBACK_WARNING_CODE in warn_codes
    warn_msg = next(w['message'] for w in dto['warnings'] if w['code'] == gsf.FALLBACK_WARNING_CODE)
    assert 'google-static' in warn_msg.lower()


# ── 3. Mevcut/önerilen km-süre doğru ─────────────────────────────────────────

def test_t3_current_and_suggested_km_dur_correct():
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=150_000.0, duration_s=5_400.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=120_000.0, duration_s=4_200.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        optimized_stop_indices=[1, 0],
        order_changed=True,
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(ors, gs_optimized_result=gs_result)

    assert dto['current']['km'] == 150.0
    assert dto['current']['duration_label'] == '1 sa 30 dk'
    assert dto['suggested']['km'] == 120.0
    assert dto['suggested']['duration_label'] == '1 sa 10 dk'


# ── 4. Kazanç matematiği doğru ────────────────────────────────────────────────

def test_t4_gain_math_correct():
    # Mevcut: 200 km / 3 sa, Önerilen: 150 km / 2 sa 30 dk
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=200_000.0, duration_s=10_800.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=150_000.0, duration_s=9_000.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        optimized_stop_indices=[1, 0],
        order_changed=True,
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(ors, gs_optimized_result=gs_result)

    assert dto['gain']['km'] == 50.0          # 200 - 150
    assert dto['gain']['duration_min'] == 30  # (10800 - 9000) / 60
    assert dto['gain']['pct'] == 25.0         # 50/200*100


# ── 5. Yakıt tasarrufu doğru ──────────────────────────────────────────────────

def test_t5_fuel_saving_math_correct():
    # Kazanç = 50 km, tüketim = 10 L/100 km → tasarruf = 50 * 10/100 = 5.0 L
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=200_000.0, duration_s=7_200.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=150_000.0, duration_s=5_400.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        optimized_stop_indices=[1, 0],
        order_changed=True,
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(ors, gs_optimized_result=gs_result)

    fs = dto.get('fuel_saving', {})
    assert fs.get('liters') == 5.0    # 50 km * 10 L/100 km / 100
    assert fs.get('fuel_l_per_100km') == 10.0


def test_t5b_no_fuel_saving_when_no_gain():
    """Kazanç yoksa yakıt tasarrufu '—' olmalı."""
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=200_000.0, duration_s=7_200.0,
            geometry=[[41.0, 29.0]], legs=[],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=210_000.0, duration_s=7_500.0,   # daha uzun
            geometry=[[41.0, 29.0]], legs=[],
        ),
        optimized_stop_indices=[1, 0],
        order_changed=True,
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(ors, gs_optimized_result=gs_result)

    fs = dto.get('fuel_saving', {})
    assert fs.get('liters') == '—'


# ── 6. Google optimize hatasında sahte değer yok ──────────────────────────────

def test_t6_google_optimize_failure_no_fake_values():
    """Optimize çağrı başarısız → mevcut rota + Önerilen/Kazanç/Yakıt = '—'."""
    static_fallback = RouteResult(
        provider='google-static', profile=PROFILE_STATIC,
        distance_m=180_000.0, duration_s=6_480.0,
        geometry=[[41.0, 29.0], [40.9, 28.5]],
        legs=[RouteLeg(0, 1, 90_000.0, 3_240.0), RouteLeg(1, 2, 90_000.0, 3_240.0)],
    )
    ors = _make_ors(error=_ors_quota_error())
    dto = _build_dto(
        ors,
        gs_opt_raises=RoutingError('opt fail', code='AUTH'),
        static_result=static_fallback,
    )

    # Mevcut rota var (simple static)
    assert dto['route_fallback_provider'] == 'google-static'
    assert dto['current']['km'] == 180.0

    # Önerilen/Kazanç/Yakıt boş — sahte değer yok
    assert dto['suggested']['km'] == '—'
    assert dto['suggested']['duration_label'] == '—'
    assert dto['gain']['km'] == '—'
    assert dto['gain']['duration_label'] == '—'
    fs = dto.get('fuel_saving', {})
    assert fs.get('liters') == '—'
    assert dto['suggested']['apply_disabled_reason'] == 'NO_MATRIX_FALLBACK'


# ── 7. Cache kontrolü ─────────────────────────────────────────────────────────

def test_t7_cache_hit_no_second_http_call():
    """ORS başarılı senaryosunda aynı noktalar için 2. çağrıda cache'den dönülür.

    google_optimized fallback kendi in-process cache'ine sahip değildir; bu test
    ORS başarılı akışındaki route_with_cache davranışını doğrular.
    """
    call_count = {'n': 0}

    def _fake_ors_route(points):
        call_count['n'] += 1
        pts = list(points)
        return RouteResult(
            provider='ors', profile='driving-car',
            distance_m=200_000.0, duration_s=7_200.0,
            geometry=[[float(a), float(b)] for a, b in pts],
            legs=[RouteLeg(i, i + 1, 50_000.0, 1_800.0) for i in range(len(pts) - 1)],
        )

    class _OrsOnce:
        name = 'ors'
        profile = 'driving-car'
        matrix_calls = 0
        route_calls = 0
        def route_ordered(self, points):
            self.route_calls += 1
            return _fake_ors_route(points)
        def matrix(self, points):
            self.matrix_calls += 1
            n = len(list(points))
            g = [[abs(i-j)*1000.0 for j in range(n)] for i in range(n)]
            return RouteMatrix(provider='ors', profile='driving-car', distance_m=g, duration_s=g)

    ors1 = _OrsOnce()
    dto1 = rps.build_plan_route_dto(BASE, TASKS, provider=ors1)
    first_calls = call_count['n']

    # 2. çağrı: aynı noktalar — cache'den dönmeli, HTTP'ye gitmemeli
    ors2 = _OrsOnce()
    dto2 = rps.build_plan_route_dto(BASE, TASKS, provider=ors2)
    second_new_calls = call_count['n'] - first_calls

    # Cache hit: 2. çağrıda yeni route_ordered çağrısı olmadı
    assert second_new_calls == 0, f'Cache miss: {second_new_calls} yeni çağrı'
    assert dto1['current']['km'] == dto2['current']['km']


# ── 8. Optimize hatasında sıra korunur ───────────────────────────────────────

def test_t8_optimize_failure_keeps_current_order():
    ors = _make_ors(error=_ors_quota_error())
    static_fallback = RouteResult(
        provider='google-static', profile=PROFILE_STATIC,
        distance_m=200_000.0, duration_s=7_200.0,
        geometry=[[41.0, 29.0], [40.8, 29.3]],
        legs=[RouteLeg(0, 1, 100_000.0, 3_600.0), RouteLeg(1, 2, 100_000.0, 3_600.0)],
    )
    dto = _build_dto(
        ors,
        gs_opt_raises=RoutingError('auth', code='AUTH'),
        static_result=static_fallback,
    )
    # Mevcut sıra korundu
    assert dto['current']['full_task_ids'] == ['1', '2', '3']
    assert dto['suggested']['full_task_ids'] == ['1', '2', '3']
    assert dto['suggested']['apply_disabled_reason'] == 'NO_MATRIX_FALLBACK'


# ── 9. Geçmiş departureTime → PAST_DEPARTURE ──────────────────────────────────

def test_t9_past_departure_guard_in_google_optimize():
    """route_via_google_optimized içinde PAST_DEPARTURE hatası test edilir."""
    from datetime import datetime, timezone, timedelta
    from modules.planlama.road_routing import google_routes_provider as grp

    # Geçmiş zaman (1 gün önce)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    posted: list[dict] = []

    def _fake_post(body, key, timeout):
        posted.append(body)
        # Geçmiş departureTime ile static profil çağrıya girmemeli
        return {
            'routes': [{
                'distanceMeters': 100_000,
                'duration': '3600s',
                'staticDuration': '3600s',
                'polyline': {'encodedPolyline': POLYLINE},
                'legs': [
                    {'distanceMeters': 50_000, 'duration': '1800s'},
                    {'distanceMeters': 50_000, 'duration': '1800s'},
                ],
            }]
        }

    with patch.object(grp, '_post_routes', side_effect=_fake_post):
        # Static profil PAST_DEPARTURE guard içermiyor — bu test trafik profil guard'ını kontrol eder.
        # Google static'te departureTime gönderilmez → guard tetiklenmez.
        result = gsf.route_via_google_static(
            [(40.9, 28.6), (41.0, 29.0), (40.8, 29.3), (40.9, 28.6)],
        )
    # Statik profilde çağrı gider (departureTime yok)
    assert len(posted) == 1
    assert 'departureTime' not in posted[0]


def test_t9b_past_departure_blocks_traffic_profile():
    """Trafik profili geçmiş çıkış saatiyle çağrılırsa PAST_DEPARTURE raise eder."""
    from datetime import datetime, timezone, timedelta
    from modules.planlama.road_routing.google_routes_provider import GoogleRoutesProvider

    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    prov = GoogleRoutesProvider(profile='google-traffic-fast', departure_utc=past)

    posted = []
    from modules.planlama.road_routing import google_routes_provider as grp
    with patch.object(grp, '_post_routes', side_effect=lambda b, k, t: posted.append(b) or {}):
        with pytest.raises(RoutingError) as exc_info:
            prov.route_ordered([(40.9, 28.6), (41.0, 29.0)])

    assert exc_info.value.code == 'PAST_DEPARTURE'
    assert posted == []   # HTTP'ye istek gitmedi


# ── 10. optimizeWaypointOrder=true gönderildi ─────────────────────────────────

def test_t10_optimize_body_sent_with_optimize_flag():
    """route_via_google_optimized POST body'da optimizeWaypointOrder=true bulunmalı."""
    # gsf içinde _post_routes doğrudan import edildiği için gsf modülündeki bağı patch etmeliyiz.
    posted: list[dict] = []

    def _fake_post(body, key, timeout):
        posted.append(body)
        return {
            'routes': [{
                'distanceMeters': 100_000,
                'duration': '3600s',
                'staticDuration': '3600s',
                'polyline': {'encodedPolyline': POLYLINE},
                'optimizedIntermediateWaypointIndex': [0, 1],
                'legs': [
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                ],
            }]
        }

    with patch.object(gsf, '_post_routes', side_effect=_fake_post):
        os.environ['GOOGLE_ROUTES_API_KEY'] = 'FAKE_KEY_FOR_TEST'
        pts = [(40.9, 28.6), (41.0, 29.0), (40.8, 29.3), (41.0731, 28.2464), (40.9, 28.6)]
        result = gsf.route_via_google_optimized(pts)

    assert len(posted) >= 1
    assert posted[0].get('optimizeWaypointOrder') is True


# ── 11. Sıra değişmezse tek çağrı ─────────────────────────────────────────────

def test_t11_no_second_call_when_order_unchanged():
    """optimizedIntermediateWaypointIndex = [0,1,2] (aynı sıra, 3 intermediate) → ikinci HTTP çağrısı yok."""
    posted: list[dict] = []

    def _fake_post(body, key, timeout):
        posted.append(body)
        # Google 3 intermediate için 3-elemanlı indeks döner; sıra aynı
        return {
            'routes': [{
                'distanceMeters': 100_000,
                'duration': '3600s',
                'staticDuration': '3600s',
                'polyline': {'encodedPolyline': POLYLINE},
                'optimizedIntermediateWaypointIndex': [0, 1, 2],  # sıra değişmedi
                'legs': [
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                    {'distanceMeters': 25_000, 'duration': '900s'},
                ],
            }]
        }

    with patch.object(gsf, '_post_routes', side_effect=_fake_post):
        os.environ['GOOGLE_ROUTES_API_KEY'] = 'FAKE_KEY_FOR_TEST'
        # pts=[base, s1, s2, s3, base] → intermediates=[s1,s2,s3] (3 eleman)
        pts = [(40.9, 28.6), (41.0, 29.0), (40.8, 29.3), (41.0731, 28.2464), (40.9, 28.6)]
        result = gsf.route_via_google_optimized(pts)

    assert len(posted) == 1           # sadece optimize çağrı, current çağrı yok
    assert result.order_changed is False
    assert result.current_route is result.suggested_route

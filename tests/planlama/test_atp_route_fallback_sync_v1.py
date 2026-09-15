# -*- coding: utf-8 -*-
"""Google routing fallback — trafik proposal ile ezilmeme ve metrik tutarlılığı."""
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

from modules.planlama.arac_traffic_route_proposal_service import (  # noqa: E402
    sync_route_dto_metrics_from_traffic_proposal,
)
from modules.planlama.road_routing import route_planner_service as rps  # noqa: E402
from modules.planlama.road_routing.cache import cache_clear  # noqa: E402
from modules.planlama.road_routing import google_static_fallback as gsf  # noqa: E402
from modules.planlama.road_routing.types import RouteLeg, RouteResult, RoutingError  # noqa: E402
from modules.planlama.road_routing.google_routes_provider import PROFILE_STATIC  # noqa: E402

BASE = {'latitude': 40.99, 'longitude': 28.69, 'has_coordinates': True}
TASKS = [
    {'id': 'pi-113', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'A', 'latitude': 41.02, 'longitude': 28.93, 'has_coordinates': True},
    {'id': 'pi-114', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'B', 'latitude': 40.82, 'longitude': 29.30, 'has_coordinates': True},
    {'id': 'pi-115', 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'NORMAL',
     'company_name': 'C', 'latitude': 41.07, 'longitude': 28.25, 'has_coordinates': True},
]


def _fallback_dto_plan37_like():
    """Plan 37 benzeri: sıra değişir, km farkı 35.1, süre farkı pozitif."""
    gs_result = gsf.GoogleOptimizedResult(
        current_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=384_900.0, duration_s=24_720.0,
            geometry=[[41.0, 29.0], [41.1, 29.1]],
            legs=[RouteLeg(0, 1, 192_450.0, 12_360.0), RouteLeg(1, 2, 192_450.0, 12_360.0)],
        ),
        suggested_route=RouteResult(
            provider='google-static', profile=PROFILE_STATIC,
            distance_m=349_800.0, duration_s=24_480.0,
            geometry=[[41.0, 29.0], [41.2, 29.2]],
            legs=[RouteLeg(0, 1, 174_900.0, 12_240.0), RouteLeg(1, 2, 174_900.0, 12_240.0)],
        ),
        optimized_stop_indices=[0, 2, 1],
        order_changed=True,
    )

    class FakeOrs:
        name = 'ors'
        profile = 'driving-car'

        def route_ordered(self, points):
            raise RoutingError('quota', code='RATE_LIMIT', http_status=429)

        def matrix(self, points):
            raise RoutingError('quota', code='RATE_LIMIT')

    def _fake_opt(points):
        return gs_result

    def _fake_static(points):
        return gs_result.current_route

    with (
        patch.object(rps, 'load_visit_states_for_tasks', return_value={}),
        patch.object(gsf, 'route_via_google_optimized', side_effect=_fake_opt),
        patch.object(gsf, 'route_via_google_static', side_effect=_fake_static),
        patch.object(gsf, 'google_provider_available', return_value=True),
        patch.object(rps, 'route_via_google_optimized', side_effect=_fake_opt),
        patch.object(rps, 'route_via_google_static', side_effect=_fake_static),
        patch.object(rps, 'fallback_available', return_value=True),
    ):
        return rps.build_plan_route_dto(BASE, TASKS, provider=FakeOrs())


@pytest.fixture(autouse=True)
def _clean():
    cache_clear()
    yield
    cache_clear()


def test_sync_skips_when_route_fallback_provider():
    route = {
        'route_fallback_provider': 'google-static',
        'current': {'km': 100.0},
        'suggested': {'km': 80.0},
        'gain': {'km': 20.0, 'duration_label': '5 dk'},
    }
    tp = {
        'current_total_duration_seconds': 3600,
        'current_total_distance_meters': 50_000,
        'suggested_total_distance_meters': 50_000,
        'distance_delta_meters': 0,
        'time_delta_label': '0 sn',
    }
    out = sync_route_dto_metrics_from_traffic_proposal(dict(route), tp)
    assert out['current']['km'] == 100.0
    assert out['suggested']['km'] == 80.0
    assert out['gain']['km'] == 20.0
    assert out.get('metrics_source') != 'traffic_proposal'


def test_plan37_like_fallback_metrics_consistent():
    dto = _fallback_dto_plan37_like()
    assert dto.get('route_fallback_provider') == 'google-static'
    assert dto.get('order_same') is False

    cur_ids = dto['current']['full_task_ids']
    sug_ids = dto['suggested']['full_task_ids']
    assert cur_ids != sug_ids
    assert dto['current']['order_labels'] != dto['suggested']['order_labels']
    assert len(dto['current']['geometry']) >= 2
    assert len(dto['suggested']['geometry']) >= 2

    gain_km = dto['gain']['km']
    assert isinstance(gain_km, (int, float)) and gain_km > 0
    assert gain_km == pytest.approx(35.1, abs=0.05)

    fs = dto.get('fuel_saving') or {}
    assert fs.get('fuel_l_per_100km') == 10.0
    assert fs.get('liters') == pytest.approx(gain_km * 10.0 / 100.0, abs=0.01)

    reason = dto.get('decision_reason') or ''
    assert str(gain_km) in reason or '35.1' in reason


def test_traffic_sync_does_not_clobber_fallback_dto():
    dto = _fallback_dto_plan37_like()
    before_gain = dto['gain']['km']
    tp = {
        'current_total_duration_seconds': 1000,
        'current_total_distance_meters': 349_800,
        'suggested_total_distance_meters': 349_800,
        'suggested_total_duration_seconds': 1000,
        'distance_delta_meters': 0,
        'time_delta_label': '0 sn',
        'comparison_label': 'fake',
    }
    synced = sync_route_dto_metrics_from_traffic_proposal(dto, tp)
    assert synced['gain']['km'] == before_gain
    assert synced['suggested']['full_task_ids'] == dto['suggested']['full_task_ids']


def test_api_layer_preserves_fallback_suggested_ids():
    """arac_takip_api_route_plan: trafik önerisi fallback full_task_ids ezmez."""
    from modules.planlama import arac_takip_routes as routes_mod

    fallback_dto = _fallback_dto_plan37_like()
    sug_before = list(fallback_dto['suggested']['full_task_ids'])
    traffic = {
        'suggested_task_ids': ['pi-113', 'pi-114', 'pi-115'],
        'apply_enabled': False,
        'changed': False,
        'current_total_duration_seconds': 3600,
        'current_total_distance_meters': 349_800,
        'suggested_total_distance_meters': 349_800,
        'distance_delta_meters': 0,
        'time_delta_label': '0 sn',
    }
    route_dto = dict(fallback_dto)
    route_dto['traffic_proposal'] = traffic
    if traffic.get('suggested_task_ids') and not route_dto.get('route_fallback_provider'):
        route_dto.setdefault('suggested', {})
        route_dto['suggested']['full_task_ids'] = traffic['suggested_task_ids']
    from modules.planlama.arac_traffic_route_proposal_service import (
        sync_route_dto_metrics_from_traffic_proposal,
    )
    route_dto = sync_route_dto_metrics_from_traffic_proposal(route_dto, traffic)

    assert route_dto['suggested']['full_task_ids'] == sug_before
    assert route_dto['suggested']['full_task_ids'] != route_dto['current']['full_task_ids']

    dash_fuel = routes_mod._route_fuel_saving_for_dashboard(route_dto)
    assert dash_fuel['liters'] == route_dto['fuel_saving']['liters']


def test_ui_fuel_helper_accepts_liters_without_try():
    """Dashboard fuel helper — yalnız liters ile kart doldurulabilir."""
    from modules.planlama import arac_takip_routes as routes_mod

    dto = {'fuel_saving': {'liters': 3.51, 'fuel_l_per_100km': 10.0}}
    dash = routes_mod._route_fuel_saving_for_dashboard(dto)
    assert dash['liters'] == 3.51
    assert dash['try_amount'] == '—'

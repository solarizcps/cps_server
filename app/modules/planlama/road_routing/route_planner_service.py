# -*- coding: utf-8 -*-
"""Araç Takip V1.4B — route planner service boundary."""
from __future__ import annotations

import os
from typing import Any

from modules.planlama.road_routing.cache import cache_get, cache_set, make_cache_key
from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
from modules.planlama.road_routing.openrouteservice_provider import OpenRouteServiceProvider, provider_available
from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.suggest import suggest_stop_order
from modules.planlama.road_routing.types import RouteResult, RoutingError


def _format_km(distance_m: float | None) -> str | float:
    if distance_m is None:
        return '—'
    return round(float(distance_m) / 1000.0, 1)


def _format_duration(duration_s: float | None) -> str:
    if duration_s is None:
        return '—'
    total_min = int(round(float(duration_s) / 60.0))
    if total_min < 60:
        return f'{total_min} dk'
    h, m = divmod(total_min, 60)
    if m:
        return f'{h} sa {m} dk'
    return f'{h} sa'


def get_routing_provider(force_mock: bool = False) -> RoadRoutingProvider | None:
    if force_mock:
        return MockRoadRoutingProvider()
    provider_name = (os.environ.get('ARAC_ROUTING_PROVIDER') or 'ors').strip().lower()
    if provider_name == 'mock':
        return MockRoadRoutingProvider()
    if provider_name == 'ors':
        if not provider_available():
            return None
        try:
            return OpenRouteServiceProvider()
        except RoutingError:
            return None
    return None


def routing_status_message(provider: RoadRoutingProvider | None) -> tuple[str, str | None]:
    if provider is None:
        if not provider_available() and (os.environ.get('ARAC_ROUTING_PROVIDER') or 'ors').lower() != 'mock':
            return 'UNCONFIGURED', 'Rota servisi yapılandırılmamış.'
        return 'UNAVAILABLE', 'Rota servisi kullanılamıyor.'
    return 'READY', None


def _build_routable_points(
    base: dict | None,
    tasks: list[dict],
) -> tuple[list[tuple[float, float]], list[dict], list[dict], dict[str, Any]]:
    """Returns points [base, ...stops], routable_stops, missing_stops, meta."""
    routable: list[dict] = []
    missing: list[dict] = []
    if not base or not base.get('has_coordinates'):
        return [], [], [dict(t) for t in tasks], {
            'base_ready': False,
            'total_stops': len(tasks),
            'routable_count': 0,
            'missing_count': len(tasks),
        }
    points: list[tuple[float, float]] = [(float(base['latitude']), float(base['longitude']))]
    for t in sorted(tasks, key=lambda x: x.get('order_no') or 0):
        if t.get('has_coordinates') and t.get('latitude') is not None and t.get('longitude') is not None:
            points.append((float(t['latitude']), float(t['longitude'])))
            routable.append({
                **t,
                'matrix_index': len(points) - 1,
            })
        else:
            missing.append(dict(t))
    return points, routable, missing, {
        'base_ready': True,
        'total_stops': len(tasks),
        'routable_count': len(routable),
        'missing_count': len(missing),
    }


def _route_with_cache(provider: RoadRoutingProvider, points: list[tuple[float, float]]) -> RouteResult:
    key = make_cache_key(provider.name, provider.profile, points)
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = provider.route_ordered(points)
    cache_set(key, result)
    return result


def _legs_for_stops(route: RouteResult, stop_count: int) -> list[dict]:
    """Map route legs to stop rows (leg i = point i -> point i+1). Index 0 leg is base->stop1."""
    out: list[dict] = []
    for i in range(stop_count):
        leg_idx = i  # legs[0]: base->stop1
        if leg_idx < len(route.legs):
            lg = route.legs[leg_idx]
            out.append({
                'leg_index': leg_idx,
                'distance_m': lg.distance_m,
                'duration_s': lg.duration_s,
                'distance_km': _format_km(lg.distance_m),
                'duration_label': _format_duration(lg.duration_s),
            })
        else:
            out.append({
                'leg_index': leg_idx,
                'distance_m': None,
                'duration_s': None,
                'distance_km': '—',
                'duration_label': '—',
            })
    return out


def _order_labels(tasks: list[dict]) -> str:
    return ' → '.join(str(t.get('order_no') or '?') for t in tasks)


def _merge_apply_order(all_tasks: list[dict], suggested_routable_ids: list[str]) -> list[str]:
    """Keep missing-coordinate stops at canonical slots; apply suggestion to routable only."""
    canonical = sorted(all_tasks, key=lambda x: x.get('order_no') or 0)
    by_id = {t['id']: t for t in canonical}
    queue = [by_id[i] for i in suggested_routable_ids if i in by_id]
    out: list[str] = []
    for t in canonical:
        if not t.get('has_coordinates'):
            out.append(t['id'])
        elif queue:
            out.append(queue.pop(0)['id'])
    for t in queue:
        out.append(t['id'])
    return out


def build_plan_route_dto(
    base: dict | None,
    tasks: list[dict],
    provider: RoadRoutingProvider | None = None,
    force_mock: bool = False,
) -> dict[str, Any]:
    prov = provider if provider is not None else get_routing_provider(force_mock=force_mock)
    status, message = routing_status_message(prov)
    points, routable, missing, meta = _build_routable_points(base, tasks)

    empty_route = {
        'status': status,
        'message': message,
        'partial': meta['missing_count'] > 0,
        'meta': meta,
        'current': {'km': '—', 'duration_label': '—', 'geometry': [], 'legs': [], 'order_labels': _order_labels(tasks)},
        'suggested': {'km': '—', 'duration_label': '—', 'geometry': [], 'order_labels': '', 'task_ids': []},
        'gain': {'km': '—', 'duration_label': '—', 'pct': '—'},
        'leg_details': [],
        'suggested_preview_only': True,
    }

    if prov is None:
        return empty_route

    if not meta['base_ready']:
        empty_route['message'] = 'Başlangıç noktası tanımlanmamış.'
        empty_route['status'] = 'NO_BASE'
        return empty_route

    if len(routable) == 0:
        empty_route['status'] = 'NO_STOPS'
        empty_route['message'] = 'Rota için koordinatlı durak yok.'
        return empty_route

    if len(points) < 2:
        empty_route['status'] = 'NO_ROUTE'
        return empty_route

    try:
        current_route = _route_with_cache(prov, points)
    except RoutingError as exc:
        empty_route['status'] = exc.code
        empty_route['message'] = str(exc) or 'Rota hesaplanamadı.'
        return empty_route

    leg_details = []
    for i, stop in enumerate(routable):
        leg = _legs_for_stops(current_route, len(routable))[i]
        leg_details.append({
            'task_id': stop.get('id'),
            'order_no': stop.get('order_no'),
            'company_name': stop.get('company_name'),
            **leg,
        })

    current_dto = {
        'km': _format_km(current_route.distance_m),
        'duration_label': _format_duration(current_route.duration_s),
        'distance_m': current_route.distance_m,
        'duration_s': current_route.duration_s,
        'geometry': current_route.geometry,
        'legs': [lg.to_dict() if hasattr(lg, 'to_dict') else {
            'from_index': lg.from_index, 'to_index': lg.to_index,
            'distance_m': lg.distance_m, 'duration_s': lg.duration_s,
        } for lg in current_route.legs],
        'order_labels': _order_labels(routable),
        'task_ids': [s['id'] for s in routable],
        'provider': current_route.provider,
    }

    suggested_ids = list(current_dto['task_ids'])
    suggested_route = current_route
    try:
        matrix = prov.matrix(points)
        suggested_ids = suggest_stop_order(routable, matrix.duration_s, start_index=0)
        id_to_stop = {s['id']: s for s in routable}
        suggested_stops = [id_to_stop[i] for i in suggested_ids if i in id_to_stop]
        if suggested_ids != current_dto['task_ids']:
            sug_points = [points[0]] + [
                (float(s['latitude']), float(s['longitude'])) for s in suggested_stops
            ]
            suggested_route = _route_with_cache(prov, sug_points)
        else:
            suggested_stops = routable
    except RoutingError:
        suggested_stops = routable

    suggested_dto = {
        'km': _format_km(suggested_route.distance_m),
        'duration_label': _format_duration(suggested_route.duration_s),
        'distance_m': suggested_route.distance_m,
        'duration_s': suggested_route.duration_s,
        'geometry': suggested_route.geometry,
        'order_labels': _order_labels(suggested_stops),
        'task_ids': suggested_ids,
        'apply_task_ids': _merge_apply_order(tasks, suggested_ids),
        'provider': suggested_route.provider,
    }

    gain_km = None
    gain_min = None
    gain_pct = None
    if (
        isinstance(current_dto['km'], (int, float))
        and isinstance(suggested_dto['km'], (int, float))
        and current_dto['km'] > 0
    ):
        gain_km = round(float(current_dto['km']) - float(suggested_dto['km']), 1)
        cur_min = current_route.duration_s / 60.0
        sug_min = suggested_route.duration_s / 60.0
        gain_min = int(round(cur_min - sug_min))
        gain_pct = round(100.0 * gain_km / float(current_dto['km']), 1)

    partial_msg = None
    if meta['missing_count'] > 0:
        partial_msg = (
            f"{meta['routable_count']}/{meta['total_stops']} durak hesaplandı · "
            f"{meta['missing_count']} konum eksik"
        )

    return {
        'status': 'PARTIAL' if meta['missing_count'] > 0 else 'OK',
        'message': partial_msg,
        'partial': meta['missing_count'] > 0,
        'meta': meta,
        'current': current_dto,
        'suggested': suggested_dto,
        'gain': {
            'km': gain_km if gain_km is not None else '—',
            'duration_label': _format_duration(gain_min * 60) if gain_min is not None else '—',
            'duration_min': gain_min,
            'pct': gain_pct if gain_pct is not None else '—',
        },
        'leg_details': leg_details,
        'missing_stops': [{'id': m.get('id'), 'order_no': m.get('order_no'), 'company_name': m.get('company_name')} for m in missing],
        'suggested_preview_only': True,
    }

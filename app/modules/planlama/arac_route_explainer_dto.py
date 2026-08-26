# -*- coding: utf-8 -*-
"""Rota Kararı modal — timeline, ayak detayı, Google Maps, kaynak meta (read-only)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from modules.planlama.arac_timeline_service import (
    DEFAULT_STOP_SERVICE_MINUTES,
    build_duration_label_summary,
    build_timeline,
)
from modules.planlama.road_routing.route_planner_service import _format_duration, _format_km

TZ = ZoneInfo('Europe/Istanbul')

ORS_DISCLAIMER = (
    'Bu rota ORS yol ağı kullanılarak hesaplandı. Canlı trafik dahil değildir.'
)
GMAPS_TRAFFIC_NOTE = (
    'Google Maps canlı trafik kullanabilir; süre farkı normaldir — yalnızca manuel kıyas içindir.'
)

_PROVIDER_LABEL = {
    'ors': 'OpenRouteService',
    'mock': 'Mock (geliştirme)',
}


def _ceil_minutes(seconds: float) -> int:
    return math.ceil(max(0.0, float(seconds)) / 60.0)


def build_google_maps_dir_url(
    base_lat: float,
    base_lng: float,
    stops: list[dict],
) -> str:
    """Fabrika → sıralı duraklar → fabrika Google Maps yön linki."""
    coords: list[str] = [f'{base_lat},{base_lng}']
    for s in stops:
        lat, lng = s.get('latitude'), s.get('longitude')
        if lat is not None and lng is not None:
            coords.append(f'{float(lat)},{float(lng)}')
    coords.append(f'{base_lat},{base_lng}')
    if len(coords) < 3:
        return ''
    origin = coords[0]
    destination = coords[-1]
    waypoints = '|'.join(coords[1:-1]) if len(coords) > 2 else ''
    params: dict[str, str] = {
        'api': '1',
        'origin': origin,
        'destination': destination,
        'travelmode': 'driving',
    }
    if waypoints:
        params['waypoints'] = waypoints
    return 'https://www.google.com/maps/dir/?' + urlencode(params)


def _leg_details_for_route(ordered_stops: list[dict], route_legs_raw: list) -> tuple[list[dict], float | None]:
    """RouteResult.legs → leg_details list + return duration."""
    legs_norm = _normalize_legs(route_legs_raw)
    n = len(ordered_stops)
    leg_details: list[dict] = []
    for i, stop in enumerate(ordered_stops):
        lg = legs_norm[i] if i < len(legs_norm) else {}
        dur_s, dist_m = lg.get('duration_s'), lg.get('distance_m')
        leg_details.append({
            'task_id': stop.get('id'),
            'order_no': stop.get('order_no'),
            'display_order_no': stop.get('display_order_no') or stop.get('order_no'),
            'company_name': stop.get('company_name'),
            'duration_s': dur_s,
            'distance_m': dist_m,
            'distance_km': _format_km(dist_m),
            'duration_label': _format_duration(dur_s),
        })
    return_duration_s: float | None = None
    if len(legs_norm) > n:
        return_duration_s = legs_norm[n].get('duration_s')
    return leg_details, return_duration_s


def _normalize_legs(raw_legs: list) -> list:
    out = []
    for lg in raw_legs or []:
        if isinstance(lg, dict):
            out.append(lg)
        else:
            out.append({
                'from_index': lg.from_index,
                'to_index': lg.to_index,
                'distance_m': lg.distance_m,
                'duration_s': lg.duration_s,
            })
    return out


def build_leg_breakdown(
    base: dict | None,
    ordered_stops: list[dict],
    route_legs_raw: list,
    timeline: dict[str, Any],
) -> dict[str, Any]:
    """Ayak ayak hesap — timeline + RouteResult.legs birleşimi."""
    base_name = (base or {}).get('base_name') or 'Fabrika'
    legs_norm = _normalize_legs(route_legs_raw)
    tl_stops = timeline.get('stops') or []
    items: list[dict] = []

    for i, stop in enumerate(ordered_stops):
        from_label = base_name if i == 0 else (ordered_stops[i - 1].get('company_name') or '—')
        to_label = stop.get('company_name') or '—'
        lg = legs_norm[i] if i < len(legs_norm) else {}
        tl = tl_stops[i] if i < len(tl_stops) else {}
        dur_s = lg.get('duration_s')
        dist_m = lg.get('distance_m')
        items.append({
            'from_label': from_label,
            'to_label': to_label,
            'distance_km': _format_km(dist_m),
            'distance_m': dist_m,
            'travel_seconds': dur_s,
            'travel_minutes': _ceil_minutes(float(dur_s)) if dur_s is not None else None,
            'travel_label': _format_duration(dur_s),
            'arrival_time': tl.get('arrival_time'),
            'service_minutes': tl.get('service_minutes'),
            'departure_time': tl.get('departure_time'),
            'is_return': False,
        })

    if len(legs_norm) > len(ordered_stops) and ordered_stops:
        ret = legs_norm[len(ordered_stops)]
        ret_s = ret.get('duration_s')
        items.append({
            'from_label': ordered_stops[-1].get('company_name') or '—',
            'to_label': base_name,
            'distance_km': _format_km(ret.get('distance_m')),
            'distance_m': ret.get('distance_m'),
            'travel_seconds': ret_s,
            'travel_minutes': _ceil_minutes(float(ret_s)) if ret_s is not None else None,
            'travel_label': _format_duration(ret_s),
            'arrival_time': timeline.get('estimated_return_time'),
            'service_minutes': None,
            'departure_time': None,
            'is_return': True,
        })

    stop_count = len([s for s in tl_stops if s.get('eta_status') == 'HESAPLANDI'])
    svc_min = timeline.get('total_service_minutes') or (stop_count * DEFAULT_STOP_SERVICE_MINUTES)
    duration_labels = timeline.get('duration_labels') or build_duration_label_summary(
        outbound_travel_seconds=timeline.get('outbound_travel_seconds'),
        return_travel_seconds=timeline.get('return_travel_seconds') or timeline.get('return_seconds'),
        total_travel_seconds=timeline.get('total_travel_seconds'),
        total_service_seconds=timeline.get('total_service_seconds'),
    )
    total_min = duration_labels.get('total_plan_minutes') or timeline.get('estimated_total_minutes') or 0
    drive_min = duration_labels.get('total_drive_minutes') or timeline.get('total_travel_minutes') or 0

    return {
        'legs': items,
        'formula': {
            'drive_minutes': drive_min,
            'service_minutes': svc_min,
            'service_formula': f'{stop_count} × {DEFAULT_STOP_SERVICE_MINUTES} dk = {svc_min} dk',
            'total_minutes': total_min,
            'duration_labels': duration_labels,
            'formula_text': ' · '.join(duration_labels.get('lines') or []),
            'departure_time': timeline.get('plan_departure_time'),
            'estimated_return_time': timeline.get('estimated_return_time'),
        },
        'leg_count': len(items),
        'stop_count': stop_count,
    }


def _route_summary(timeline: dict, route_part: dict) -> dict:
    stop_count = len(timeline.get('stops') or [])
    svc = timeline.get('total_service_minutes') or stop_count * DEFAULT_STOP_SERVICE_MINUTES
    return {
        'km': route_part.get('km'),
        'drive_label': _format_duration(route_part.get('duration_s')),
        'drive_minutes': _ceil_minutes(float(route_part.get('duration_s') or 0)),
        'service_minutes': svc,
        'service_formula': f'{stop_count} × {DEFAULT_STOP_SERVICE_MINUTES} dk = {svc} dk',
        'total_minutes': timeline.get('estimated_total_minutes'),
        'departure_time': timeline.get('plan_departure_time'),
        'estimated_return_time': timeline.get('estimated_return_time'),
    }


def _source_info(provider_code: str | None, profile: str, leg_count: int) -> dict:
    code = (provider_code or 'mock').lower()
    return {
        'provider': _PROVIDER_LABEL.get(code, provider_code or '—'),
        'provider_code': code,
        'profile': profile or 'driving-car',
        'traffic': 'Canlı trafik dahil değil',
        'service_minutes_per_stop': DEFAULT_STOP_SERVICE_MINUTES,
        'computed_at': datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'),
        'leg_count': leg_count,
    }


def enrich_route_explainer_dto(
    dto: dict[str, Any],
    *,
    plan_date: str,
    departure_hhmm: str | None,
    base: dict | None,
    routable_tasks: list[dict],
    suggested_tasks: list[dict] | None = None,
    profile: str = 'driving-car',
) -> dict[str, Any]:
    """Route DTO'ya timeline, ayak detayı, Google Maps ve kaynak meta ekle."""
    if not dto or dto.get('status') not in ('OK', 'PARTIAL'):
        return dto

    base_lat = base.get('latitude') if base else None
    base_lng = base.get('longitude') if base else None
    cur = dto.get('current') or {}
    sug = dto.get('suggested') or {}
    cur_legs = _normalize_legs(cur.get('legs') or [])
    sug_legs = _normalize_legs(sug.get('legs') or [])

    cur_leg_details, cur_return_s = _leg_details_for_route(routable_tasks, cur_legs)
    cur_timeline = build_timeline(
        plan_date, departure_hhmm, routable_tasks,
        cur_leg_details, cur_return_s,
    )
    cur_breakdown = build_leg_breakdown(base, routable_tasks, cur_legs, cur_timeline)
    cur_summary = _route_summary(cur_timeline, cur)

    sug_stops = suggested_tasks if suggested_tasks else routable_tasks
    sug_leg_details, sug_return_s = _leg_details_for_route(sug_stops, sug_legs)
    sug_timeline = build_timeline(
        plan_date, departure_hhmm, sug_stops,
        sug_leg_details, sug_return_s,
    )
    sug_breakdown = build_leg_breakdown(base, sug_stops, sug_legs, sug_timeline)
    sug_summary = _route_summary(sug_timeline, sug)

    gmaps_current = ''
    gmaps_suggested = ''
    if base_lat is not None and base_lng is not None:
        gmaps_current = build_google_maps_dir_url(base_lat, base_lng, routable_tasks)
        gmaps_suggested = build_google_maps_dir_url(base_lat, base_lng, sug_stops)

    dto['ors_disclaimer'] = ORS_DISCLAIMER
    dto['gmaps_traffic_note'] = GMAPS_TRAFFIC_NOTE
    dto['departure_hhmm'] = departure_hhmm
    dto['current_timeline'] = cur_timeline
    dto['suggested_timeline'] = sug_timeline
    dto['current_breakdown'] = cur_breakdown
    dto['suggested_breakdown'] = sug_breakdown
    dto['current_summary'] = cur_summary
    dto['suggested_summary'] = sug_summary
    dto['google_maps_current'] = gmaps_current
    dto['google_maps_suggested'] = gmaps_suggested
    dto['source_info'] = _source_info(
        cur.get('provider'),
        profile,
        len(cur_legs),
    )
    dto['source_info_suggested'] = _source_info(
        sug.get('provider'),
        profile,
        len(sug_legs),
    )

    # Doğrulama meta (frontend/test)
    order_same = bool(dto.get('order_same'))
    if order_same:
        dto['suggested_breakdown'] = cur_breakdown
        dto['suggested_timeline'] = cur_timeline
        dto['suggested_summary'] = cur_summary

    dto['validation'] = {
        'active_stop_count': len(routable_tasks),
        'current_leg_count': len(cur_legs),
        'expected_leg_count': len(routable_tasks) + 1 if routable_tasks else 0,
        'current_distance_m': cur.get('distance_m'),
        'current_duration_s': cur.get('duration_s'),
        'sum_leg_distance_m': sum(lg.get('distance_m') or 0 for lg in cur_legs),
        'sum_leg_duration_s': sum(lg.get('duration_s') or 0 for lg in cur_legs),
        'service_seconds': cur_timeline.get('total_service_seconds'),
        'estimated_total_seconds': cur_timeline.get('estimated_total_seconds'),
    }

    gain = dto.get('gain') or {}
    gain_km = gain.get('km')
    gain_min = gain.get('duration_min')
    cur_ret = cur_summary.get('estimated_return_time')
    sug_ret = sug_summary.get('estimated_return_time')
    return_diff_min = None
    if cur_ret and sug_ret and cur_ret != sug_ret and not order_same:
        try:
            def _hhmm_to_min(hhmm: str) -> int:
                h, m = hhmm.split(':')
                return int(h) * 60 + int(m)

            return_diff_min = _hhmm_to_min(sug_ret) - _hhmm_to_min(cur_ret)
        except (ValueError, AttributeError):
            return_diff_min = None

    comparison_lines: list[str] = []
    if isinstance(gain_km, (int, float)) and gain_km > 0:
        comparison_lines.append(f'Mesafe farkı: {gain_km} km daha kısa')
    elif isinstance(gain_km, (int, float)) and gain_km < 0:
        comparison_lines.append(f'Mesafe farkı: {abs(gain_km)} km daha uzun')
    if isinstance(gain_min, (int, float)) and gain_min < 0:
        comparison_lines.append(f'Zaman farkı: {abs(gain_min)} dk daha uzun')
    elif isinstance(gain_min, (int, float)) and gain_min > 0:
        comparison_lines.append(f'Zaman farkı: {gain_min} dk daha kısa')
    if isinstance(return_diff_min, int) and return_diff_min != 0:
        if return_diff_min > 0:
            comparison_lines.append(f'Dönüş farkı: {return_diff_min} dk daha geç')
        else:
            comparison_lines.append(f'Dönüş farkı: {abs(return_diff_min)} dk daha erken')
    if dto.get('has_priority_override') or (
        dto.get('constraints') or {}
    ).get('important_task_ids'):
        comparison_lines.append('Öncelik etkisi: yüksek öncelikli durak daha erken ziyaret edildi')

    dto['gain_comparison'] = {
        'distance_km': gain_km,
        'duration_min': gain_min,
        'return_diff_min': return_diff_min,
        'lines': comparison_lines,
        'current_return': cur_ret,
        'suggested_return': sug_ret,
    }
    return dto

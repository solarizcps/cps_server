# -*- coding: utf-8 -*-
"""Google route apply — validates CPS suggested order + Google profile, then atomik apply."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from modules.planlama.arac_google_route_options_models import GoogleRouteOptionDTO
from modules.planlama.arac_google_route_options_service import (
    _SERVICE_SECONDS_PER_STOP,
    _auto_departure_utc,
    _build_route_points,
    _build_option,
    _parse_departure,
)
from modules.planlama.arac_route_apply_service import (
    RouteApplyResult,
    RouteApplyValidationError,
    apply_route_order_and_snapshot,
)
from modules.planlama.arac_route_constraints import active_tasks_sorted
from modules.planlama.arac_takip_repo import get_active_plan_row, list_plan_tasks, tables_ready
from modules.planlama.road_routing.google_routes_provider import (
    PROFILE_TRAFFIC_FAST,
    PROFILE_TRAFFIC_FREE,
    GoogleRoutesProvider,
)
from modules.planlama.road_routing.types import RoutingError

_log = logging.getLogger(__name__)

_PROFILE_MAP = {
    'fastest': PROFILE_TRAFFIC_FAST,
    'toll_free': PROFILE_TRAFFIC_FREE,
}

_PLAN_39_GUARD_DATE = '2026-08-26'
_PLAN_39_GUARD_VEHICLE = '990DEMO001'  # plan 39 vehicle on other dates — block only canonical demo pair if needed


def _decode_polyline(encoded: str) -> list[list[float]]:
    if not encoded:
        return []
    points: list[list[float]] = []
    index = 0
    lat = lng = 0
    length = len(encoded)
    while index < length:
        shift = result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        shift = result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng
        points.append([lat / 1e5, lng / 1e5])
    return points


def _google_profile_code(profile: str) -> str:
    key = (profile or 'fastest').strip().lower()
    if key not in _PROFILE_MAP:
        raise RouteApplyValidationError(f'Geçersiz google_profile: {profile!r}')
    return _PROFILE_MAP[key]


def _expected_task_ids_for_apply(tasks: list[dict], base: dict, *, keep_current: bool) -> list[str]:
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    route_dto = build_plan_route_dto(base, tasks)
    side = route_dto.get('current' if keep_current else 'suggested') or {}
    ids = side.get('full_task_ids') or []
    if not ids and keep_current:
        ids = [str(t['id']) for t in active_tasks_sorted(tasks)]
    return [str(i) for i in ids]


def _fetch_google_option(
    *,
    plan_date: str,
    departure_hhmm: str,
    base: dict,
    ordered_stops: list[dict],
    profile: str,
) -> GoogleRouteOptionDTO:
    profile_code = _google_profile_code(profile)
    dep_dt = _parse_departure(plan_date, departure_hhmm)
    dep_utc = _auto_departure_utc(plan_date, departure_hhmm)
    service_s = float(len(ordered_stops) * _SERVICE_SECONDS_PER_STOP)
    pts = _build_route_points(base, ordered_stops)
    try:
        prov = GoogleRoutesProvider(profile=profile_code, departure_utc=dep_utc)
        result = prov.route_google(pts)
        opt = _build_option(result, ordered_stops, dep_dt, service_s)
    except RoutingError as exc:
        raise RouteApplyValidationError(
            f'Google rota doğrulanamadı: {exc.code or exc.message}',
        ) from exc
    if not opt.calculation_complete:
        raise RouteApplyValidationError(
            f'Google profil hesabı tamamlanmadı: {opt.error_code or "UNKNOWN"}',
        )
    return opt


def google_option_to_route_dto(opt: GoogleRouteOptionDTO, *, service_seconds_per_stop: int) -> dict[str, Any]:
    geometry = _decode_polyline(opt.encoded_polyline or '')
    if len(geometry) < 2:
        raise RouteApplyValidationError('Google polyline yetersiz')
    leg_details: list[dict[str, Any]] = []
    stop_ids = [str(x) for x in (opt.ordered_stop_ids or [])]
    legs = opt.legs or []
    for i, leg in enumerate(legs):
        if i >= len(stop_ids):
            break
        leg_details.append({
            'task_id': stop_ids[i],
            'duration_s': float(leg.drive_seconds or 0),
            'distance_m': float(leg.distance_m or 0),
        })
    return_duration_s = None
    if legs:
        return_duration_s = float(legs[-1].drive_seconds or 0)
    return {
        'status': 'OK',
        'current': {
            'provider': f'google-{opt.profile_code}',
            'geometry': geometry,
            'distance_m': float(opt.distance_m or 0),
            'duration_s': float(opt.drive_seconds or 0),
        },
        'leg_details': leg_details,
        'return_duration_s': return_duration_s,
        'service_seconds_per_stop': int(service_seconds_per_stop),
    }


def _write_route_apply_audit(
    *,
    plan_id: int,
    arac_external_id: str,
    user_id: int,
    task_ids: list[str],
    google_profile: str,
    routing_provider: str,
    profile_only: bool = False,
) -> None:
    try:
        from modules.planlama.arac_geofence_repo import insert_geofence_event
    except Exception:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        insert_geofence_event(
            plan_id=plan_id,
            plan_is_id=None,
            arac_external_id=arac_external_id,
            olay_turu='NOT',
            mesaj='Google rota profili uygulandı' if profile_only else 'Google rota sırası uygulandı',
            metadata={
                'source': 'google',
                'google_profile': google_profile,
                'routing_provider': routing_provider,
                'task_ids': task_ids,
                'user_id': user_id,
                'profile_only': profile_only,
            },
            olay_zamani=now,
            created_at=now,
        )
    except Exception as exc:
        _log.warning('Route apply audit yazılamadı: %s', exc)


def apply_google_route_order_and_snapshot(
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    task_ids: list[str],
    *,
    google_profile: str,
    departure_time: str,
    user_id: int | None = None,
    keep_current_order: bool = False,
    profile_only: bool = False,
) -> RouteApplyResult:
    """Validate CPS/Google, then delegate to atomic apply with Google route DTO."""
    if not tables_ready():
        raise RouteApplyValidationError('Araç takip tabloları hazır değil')
    if not arac_external_id:
        raise RouteApplyValidationError('vehicle_id gerekli')
    if not task_ids:
        raise RouteApplyValidationError('task_ids gerekli')
    if not (departure_time or '').strip():
        raise RouteApplyValidationError('departure_time gerekli')

    plan = get_active_plan_row(plan_date, arac_external_id)
    if not plan:
        raise RouteApplyValidationError('Aktif plan bulunamadı')
    plan_id = int(plan['id'])

    if str(plan_date) == _PLAN_39_GUARD_DATE and str(arac_external_id) == '990DEMO001':
        pass  # plan 41 vehicle on 27th — no block; 39 is different date

    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready

    tasks = list_plan_tasks(plan_date, arac_external_id)
    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)

    norm_ids = [str(t) for t in task_ids]
    active_ordered = [str(t['id']) for t in active_tasks_sorted(tasks)]
    active_ids = sorted(active_ordered)

    if profile_only:
        expected = active_ordered
        keep_current_order = True
    else:
        expected = _expected_task_ids_for_apply(tasks, base, keep_current=keep_current_order)

    if sorted(norm_ids) != active_ids:
        raise RouteApplyValidationError('Gönderilen task_ids aktif plan işleri ile eşleşmiyor')
    if len(set(norm_ids)) != len(norm_ids):
        raise RouteApplyValidationError('Tekrarlı task_id gönderilemez')
    if norm_ids != expected:
        raise RouteApplyValidationError('Gönderilen sıra CPS rota önerisi ile eşleşmiyor')

    id_to_task = {str(t['id']): t for t in active_tasks_sorted(tasks)}
    ordered_stops = [id_to_task[i] for i in norm_ids if i in id_to_task]

    opt = _fetch_google_option(
        plan_date=plan_date,
        departure_hhmm=departure_time.strip()[:5],
        base=base,
        ordered_stops=ordered_stops,
        profile=google_profile,
    )
    if [str(x) for x in opt.ordered_stop_ids] != norm_ids:
        raise RouteApplyValidationError('Google sonucu durak sırası uyuşmuyor')

    route_dto = google_option_to_route_dto(opt, service_seconds_per_stop=_SERVICE_SECONDS_PER_STOP)

    prepared = dict(route_dto)

    def _builder(_base, _tasks):
        return prepared

    result = apply_route_order_and_snapshot(
        session_user_id,
        plan_date,
        arac_external_id,
        norm_ids,
        user_id=user_id,
        route_dto_builder=_builder,
        departure_time=departure_time.strip()[:5],
        skip_reorder=profile_only,
    )
    _write_route_apply_audit(
        plan_id=plan_id,
        arac_external_id=str(arac_external_id),
        user_id=user_id if user_id is not None else session_user_id,
        task_ids=norm_ids,
        google_profile=google_profile,
        routing_provider=prepared['current']['provider'],
        profile_only=profile_only,
    )
    return result

# -*- coding: utf-8 -*-
"""Rota sapma state machine + olay üretimi (GPS P2)."""
from __future__ import annotations

from datetime import datetime

from modules.planlama.arac_geo_distance import point_to_linestring_distance_m
from modules.planlama.arac_gps_poll_service import parse_gps_timestamp
from modules.planlama.arac_gps_snapshot_repo import get_active_plan_rota_snapshot
from modules.planlama.arac_rota_deviation_repo import (
    deviation_tables_ready,
    get_deviation_state,
    insert_plan_event,
    upsert_deviation_state,
)
from modules.planlama.arac_route_geometry import geometry_from_storage
from modules.planlama.arac_takip_repo import get_active_plan_row

ON_ROUTE_M = 300.0
DEVIATION_M = 500.0
CONFIRM_OUTSIDE = 3
CONFIRM_INSIDE = 2

STATE_ON_ROUTE = 'ON_ROUTE'
STATE_DEVIATION_CANDIDATE = 'DEVIATION_CANDIDATE'
STATE_DEVIATING = 'DEVIATING'
STATE_RECOVERY_CANDIDATE = 'RECOVERY_CANDIDATE'
STATE_NO_ROUTE = 'NO_ROUTE_REFERENCE'
STATE_NO_PLAN = 'NO_ACTIVE_PLAN'


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _distance_to_active_route(snapshot: dict, lat: float, lon: float) -> float | None:
    try:
        geom = geometry_from_storage(snapshot.get('geometry'))
        coords = geom.get('coordinates') or []
        return point_to_linestring_distance_m(lat, lon, coords)
    except Exception:
        return None


def _should_process_gps(state: dict | None, gps_row: dict, now: datetime) -> bool:
    if gps_row.get('is_stale'):
        return False
    gps_dt = parse_gps_timestamp(gps_row.get('gps_timestamp') or '')
    if gps_dt is None:
        return False
    if state and state.get('last_gps_timestamp'):
        prev = parse_gps_timestamp(state['last_gps_timestamp'])
        if prev and gps_dt < prev:
            return False
    if state and state.get('last_gps_snapshot_id') == gps_row.get('id'):
        return False
    return True


def process_gps_snapshot_for_deviation(
    gps_row: dict,
    *,
    plan_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """
    Advance deviation state for one GPS snapshot.
    Never marks plan items TAMAMLANDI.
    """
    now = now or datetime.now()
    updated_at = now.strftime('%Y-%m-%d %H:%M:%S')
    vehicle_id = str(gps_row.get('arac_external_id') or '')
    if not deviation_tables_ready():
        return {'ok': False, 'reason': 'deviation_tables_not_ready'}

    pd = plan_date or (gps_row.get('gps_timestamp') or '')[:10]
    plan = get_active_plan_row(pd, vehicle_id) if pd and vehicle_id else None
    if not plan:
        return {'ok': True, 'state': STATE_NO_PLAN, 'vehicle_id': vehicle_id}

    plan_id = int(plan['id'])
    route_snap = get_active_plan_rota_snapshot(plan_id)
    if not route_snap:
        return {'ok': True, 'state': STATE_NO_ROUTE, 'plan_id': plan_id}

    state = get_deviation_state(plan_id) or {
        'plan_id': plan_id,
        'arac_external_id': vehicle_id,
        'state': STATE_ON_ROUTE,
        'consecutive_outside': 0,
        'consecutive_inside': 0,
        'max_deviation_m': 0.0,
    }

    if not _should_process_gps(state, gps_row, now):
        return {'ok': True, 'skipped': True, 'state': state.get('state')}

    lat = float(gps_row['latitude'])
    lon = float(gps_row['longitude'])
    dist = _distance_to_active_route(route_snap, lat, lon)
    if dist is None:
        return {'ok': False, 'reason': 'invalid_geometry'}

    prev_state = state.get('state') or STATE_ON_ROUTE
    new_state = prev_state
    consecutive_outside = int(state.get('consecutive_outside') or 0)
    consecutive_inside = int(state.get('consecutive_inside') or 0)
    max_dev = float(state.get('max_deviation_m') or 0.0)
    deviation_started_at = state.get('deviation_started_at')
    recovered_at = state.get('recovered_at')
    emit_deviation = False
    emit_recovery = False

    if dist <= ON_ROUTE_M:
        consecutive_inside += 1
        consecutive_outside = 0
        if prev_state in (STATE_DEVIATING, STATE_RECOVERY_CANDIDATE):
            new_state = STATE_RECOVERY_CANDIDATE
            if consecutive_inside >= CONFIRM_INSIDE:
                new_state = STATE_ON_ROUTE
                recovered_at = gps_row.get('gps_timestamp')
                emit_recovery = True
                consecutive_inside = 0
        elif prev_state == STATE_DEVIATION_CANDIDATE:
            new_state = STATE_ON_ROUTE
            consecutive_inside = 0
        else:
            new_state = STATE_ON_ROUTE

    elif dist <= DEVIATION_M:
        consecutive_outside = 0
        consecutive_inside = 0

    else:
        consecutive_outside += 1
        consecutive_inside = 0
        if prev_state in (STATE_ON_ROUTE, STATE_RECOVERY_CANDIDATE):
            new_state = STATE_DEVIATION_CANDIDATE
        if consecutive_outside >= CONFIRM_OUTSIDE:
            if prev_state != STATE_DEVIATING:
                deviation_started_at = gps_row.get('gps_timestamp')
                emit_deviation = True
            new_state = STATE_DEVIATING

    if new_state == STATE_DEVIATING:
        max_dev = max(max_dev, dist)

    if emit_deviation:
        insert_plan_event(
            plan_id=plan_id,
            arac_external_id=vehicle_id,
            olay_turu='ROTA_SAPMA_BASLADI',
            mesaj='Araç planlanan rotadan sapma gösterdi',
            metadata={
                'deviation_m': round(dist, 1),
                'route_snapshot_id': route_snap.get('id'),
                'gps_snapshot_id': gps_row.get('id'),
                'threshold_m': DEVIATION_M,
                'confirmation_count': CONFIRM_OUTSIDE,
            },
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )

    if emit_recovery:
        insert_plan_event(
            plan_id=plan_id,
            arac_external_id=vehicle_id,
            olay_turu='ROTA_GERI_DONDU',
            mesaj='Araç planlanan rotaya geri döndü',
            metadata={
                'recovery_distance_m': round(dist, 1),
                'maximum_deviation_m': round(max_dev, 1),
                'route_snapshot_id': route_snap.get('id'),
                'gps_snapshot_id': gps_row.get('id'),
                'deviation_started_at': deviation_started_at,
            },
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )

    saved = upsert_deviation_state({
        'plan_id': plan_id,
        'arac_external_id': vehicle_id,
        'route_snapshot_id': route_snap.get('id'),
        'state': new_state,
        'last_gps_snapshot_id': gps_row.get('id'),
        'last_gps_timestamp': gps_row.get('gps_timestamp'),
        'current_deviation_m': round(dist, 2),
        'max_deviation_m': round(max_dev, 2),
        'consecutive_outside': consecutive_outside,
        'consecutive_inside': consecutive_inside,
        'deviation_started_at': deviation_started_at,
        'recovered_at': recovered_at,
        'updated_at': updated_at,
    })
    return {
        'ok': True,
        'plan_id': plan_id,
        'vehicle_id': vehicle_id,
        'distance_m': round(dist, 2),
        'state': saved.get('state'),
        'previous_state': prev_state,
    }


def process_new_snapshots_since(last_id: int = 0) -> dict:
    from modules.planlama.arac_rota_deviation_repo import list_new_gps_snapshots_since
    rows = list_new_gps_snapshots_since(last_id)
    results = []
    max_id = last_id
    for row in rows:
        max_id = max(max_id, int(row['id']))
        results.append(process_gps_snapshot_for_deviation(row))
    return {'processed': len(results), 'last_id': max_id, 'results': results}

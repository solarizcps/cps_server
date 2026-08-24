# -*- coding: utf-8 -*-
"""Geofence ziyaret state machine — GPS P3."""
from __future__ import annotations

from datetime import datetime

from modules.planlama.arac_geo_distance import haversine_m
from modules.planlama.arac_geofence_repo import (
    event_exists,
    geofence_tables_ready,
    get_visit_state,
    insert_geofence_event,
    upsert_visit_state,
)
from modules.planlama.arac_gps_poll_service import parse_gps_timestamp
from modules.planlama.arac_takip_repo import get_active_plan_row, list_plan_tasks

ENTER_M = 200.0
EXIT_M = 250.0
CONFIRM_INSIDE = 2
CONFIRM_OUTSIDE = 2

STATE_OUTSIDE = 'OUTSIDE'
STATE_ARRIVED = 'ARRIVED'
STATE_DEPARTED_PENDING = 'DEPARTED_PENDING'

ACTIVE_ITEM_STATUSES = frozenset({'PLANLANDI', 'BASLADI'})


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _eligible_items(plan_date: str, vehicle_id: str) -> list[dict]:
    items = []
    for t in list_plan_tasks(plan_date, vehicle_id):
        if t.get('status') not in ACTIVE_ITEM_STATUSES:
            continue
        if not t.get('has_coordinates') or t.get('latitude') is None:
            continue
        items.append(t)
    return items


def _should_process(gps_row: dict, visit: dict | None) -> bool:
    if gps_row.get('is_stale'):
        return False
    gps_dt = parse_gps_timestamp(gps_row.get('gps_timestamp') or '')
    if gps_dt is None:
        return False
    if visit and visit.get('last_gps_snapshot_id') == gps_row.get('id'):
        return False
    if visit and visit.get('last_gps_snapshot_id'):
        from modules.planlama.arac_gps_snapshot_repo import get_gps_snapshot_by_id
        prev_row = get_gps_snapshot_by_id(int(visit['last_gps_snapshot_id']))
        if prev_row:
            prev = parse_gps_timestamp(prev_row.get('gps_timestamp') or '')
            if prev and gps_dt < prev:
                return False
    return True


def _distance_to_item(gps_row: dict, item: dict) -> float:
    return haversine_m(
        float(gps_row['latitude']), float(gps_row['longitude']),
        float(item['latitude']), float(item['longitude']),
    )


def _inside_candidates(gps_row: dict, items: list[dict]) -> list[tuple[dict, float]]:
    out: list[tuple[dict, float]] = []
    for item in items:
        d = _distance_to_item(gps_row, item)
        if d <= ENTER_M:
            out.append((item, d))
    return out


def process_gps_snapshot_for_geofence(
    gps_row: dict,
    *,
    plan_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Per-vehicle geofence pass — never marks TAMAMLANDI."""
    now = now or datetime.now()
    updated_at = now.strftime('%Y-%m-%d %H:%M:%S')
    if not geofence_tables_ready():
        return {'ok': False, 'reason': 'geofence_tables_not_ready'}

    vehicle_id = str(gps_row.get('arac_external_id') or '')
    pd = plan_date or (gps_row.get('gps_timestamp') or '')[:10]
    plan = get_active_plan_row(pd, vehicle_id) if pd and vehicle_id else None
    if not plan:
        return {'ok': True, 'skipped': True, 'reason': 'no_active_plan'}

    plan_id = int(plan['id'])
    items = _eligible_items(pd, vehicle_id)
    if not items:
        return {'ok': True, 'processed': 0, 'plan_id': plan_id}

    inside = _inside_candidates(gps_row, items)
    results: list[dict] = []

    if len(inside) > 1:
        insert_geofence_event(
            plan_id=plan_id,
            plan_is_id=None,
            arac_external_id=vehicle_id,
            olay_turu='AMBIGUOUS_STOP',
            mesaj='Birden fazla durak geofence içinde — otomatik varış yapılmadı',
            metadata={
                'candidates': [
                    {'plan_item_id': it['id'], 'distance_m': round(d, 1)}
                    for it, d in inside
                ],
                'gps_snapshot_id': gps_row.get('id'),
            },
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )
        return {'ok': True, 'ambiguous': True, 'candidate_count': len(inside)}

    target_items = [inside[0][0]] if inside else items

    for item in target_items:
        plan_is_id = int(item.get('plan_item_id') or str(item['id']).replace('pi-', ''))
        visit = get_visit_state(plan_is_id)
        if not _should_process(gps_row, visit):
            continue

        dist = _distance_to_item(gps_row, item)
        state = (visit or {}).get('state') or STATE_OUTSIDE
        ci = int((visit or {}).get('consecutive_inside') or 0)
        co = int((visit or {}).get('consecutive_outside') or 0)
        arrived_at = (visit or {}).get('arrived_at')
        departed_at = (visit or {}).get('departed_at')
        new_state = state
        emit_arrived = emit_departed = False

        if dist <= ENTER_M:
            ci += 1
            co = 0
            if state == STATE_OUTSIDE and ci == 1:
                # İlk giriş adayı — arrived_at burada kaydedilir, doğrulama 2. noktada
                arrived_at = gps_row.get('gps_timestamp')
            if state == STATE_OUTSIDE and ci >= CONFIRM_INSIDE:
                new_state = STATE_ARRIVED
                # arrived_at zaten ilk giriş adayının timestamp'i (ci==1)
                if not arrived_at:
                    arrived_at = gps_row.get('gps_timestamp')
                if not event_exists(plan_is_id, 'KONUMA_VARILDI'):
                    emit_arrived = True
        elif dist >= EXIT_M:
            co += 1
            ci = 0
            if state == STATE_ARRIVED and co >= CONFIRM_OUTSIDE:
                new_state = STATE_DEPARTED_PENDING
                departed_at = gps_row.get('gps_timestamp')
                if not event_exists(plan_is_id, 'KONUMDAN_AYRILDI'):
                    emit_departed = True

        out_of_sequence = False
        if inside:
            first_pending = min(
                items,
                key=lambda x: x.get('order_no') or 999,
            )
            if first_pending.get('id') != item.get('id'):
                out_of_sequence = True

        if emit_arrived:
            insert_geofence_event(
                plan_id=plan_id,
                plan_is_id=plan_is_id,
                arac_external_id=vehicle_id,
                olay_turu='KONUMA_VARILDI',
                mesaj='Araç planlı durağa vardı',
                metadata={
                    'distance_m': round(dist, 1),
                    'gps_snapshot_id': gps_row.get('id'),
                    'plan_item_id': item.get('id'),
                    'kayitli_yer_id': item.get('kayitli_yer_id'),
                    'enter_radius_m': ENTER_M,
                    'out_of_sequence': out_of_sequence,
                    'arrived_at_rule': 'first_inside_candidate_timestamp',
                    'confirmed_at': gps_row.get('gps_timestamp'),
                },
                olay_zamani=arrived_at or gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )

        dwell_seconds = (visit or {}).get('dwell_seconds')
        if emit_departed:
            dwell = None
            if arrived_at and gps_row.get('gps_timestamp'):
                a_dt = parse_gps_timestamp(arrived_at)
                d_dt = parse_gps_timestamp(gps_row['gps_timestamp'])
                if a_dt and d_dt:
                    dwell = int((d_dt - a_dt).total_seconds())
                    dwell_seconds = dwell
            insert_geofence_event(
                plan_id=plan_id,
                plan_is_id=plan_is_id,
                arac_external_id=vehicle_id,
                olay_turu='KONUMDAN_AYRILDI',
                mesaj='Konumdan ayrıldı — iş sonucu doğrulanmadı',
                metadata={
                    'distance_m': round(dist, 1),
                    'gps_snapshot_id': gps_row.get('id'),
                    'plan_item_id': item.get('id'),
                    'exit_radius_m': EXIT_M,
                    'dwell_seconds': dwell,
                    'out_of_sequence': out_of_sequence,
                },
                olay_zamani=gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )
            insert_geofence_event(
                plan_id=plan_id,
                plan_is_id=plan_is_id,
                arac_external_id=vehicle_id,
                olay_turu='ZIYARET_SONUC_BEKLIYOR',
                mesaj='Ziyaret sonucu bekleniyor',
                metadata={'plan_item_id': item.get('id')},
                olay_zamani=gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )

        saved = upsert_visit_state({
            'plan_id': plan_id,
            'plan_is_id': plan_is_id,
            'arac_external_id': vehicle_id,
            'kayitli_yer_id': item.get('kayitli_yer_id'),
            'state': new_state,
            'consecutive_inside': ci,
            'consecutive_outside': co,
            'arrived_at': arrived_at,
            'departed_at': departed_at,
            'dwell_seconds': dwell_seconds,
            'last_gps_snapshot_id': gps_row.get('id'),
            'result_status': 'SONUC_BEKLIYOR' if new_state == STATE_DEPARTED_PENDING else None,
            'updated_at': updated_at,
            'created_at': (visit or {}).get('created_at') or updated_at,
        })
        results.append({'plan_is_id': plan_is_id, 'state': saved.get('state'), 'distance_m': round(dist, 1)})

    return {'ok': True, 'plan_id': plan_id, 'processed': len(results), 'results': results}


def process_new_snapshots_since(last_id: int = 0) -> dict:
    from modules.planlama.arac_rota_deviation_repo import list_new_gps_snapshots_since
    rows = list_new_gps_snapshots_since(last_id)
    outcomes = []
    max_id = last_id
    for row in rows:
        max_id = max(max_id, int(row['id']))
        try:
            outcomes.append(process_gps_snapshot_for_geofence(row))
        except Exception as exc:
            outcomes.append({'ok': False, 'error': exc.__class__.__name__})
    return {'processed': len(outcomes), 'last_id': max_id, 'results': outcomes}

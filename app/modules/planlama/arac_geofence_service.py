# -*- coding: utf-8 -*-
"""Geofence ziyaret state machine — GPS P3."""
from __future__ import annotations

from datetime import datetime

from modules.planlama.arac_geo_distance import haversine_m
from modules.planlama.arac_geofence_repo import (
    event_exists_conn,
    geofence_metadata_event_exists_conn,
    geofence_tables_ready,
    geofence_write_transaction,
    get_visit_state_conn,
    insert_geofence_event_conn,
    upsert_visit_state_conn,
)
from modules.planlama.arac_gps_poll_service import parse_gps_timestamp
from modules.planlama.arac_takip_repo import get_active_plan_row, list_plan_tasks

APPROACHING_M = 500.0
ENTER_M = 200.0
EXIT_M = 300.0
CONFIRM_INSIDE = 2
CONFIRM_OUTSIDE = 2
GEOFENCE_STALE_SECONDS = 30 * 60

STATE_OUTSIDE = 'OUTSIDE'
STATE_APPROACHING = 'APPROACHING'
STATE_ARRIVED = 'ARRIVED'
STATE_DEPARTED_PENDING = 'DEPARTED_PENDING'

# DB CHECK constraint uyumlu olay tipleri (migration 180)
EVENT_APPROACHING = 'GEOFENCE_GIRIS'
EVENT_ARRIVED = 'KONUMA_VARILDI'
EVENT_DEPARTED = 'KONUMDAN_AYRILDI'
EVENT_RESULT_PENDING = 'ZIYARET_SONUC_BEKLIYOR'
EVENT_AMBIGUOUS = 'AMBIGUOUS_STOP'
EVENT_OUT_OF_SEQUENCE = 'NOT'
OUT_OF_SEQUENCE_KIND = 'OUT_OF_SEQUENCE_GEOFENCE'
APPROACHING_KIND = 'APPROACHING'

ACTIVE_ITEM_STATUSES = frozenset({'PLANLANDI', 'BASLADI'})
TERMINAL_VISIT_STATES = frozenset({STATE_DEPARTED_PENDING})


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _plan_is_id(item: dict) -> int:
    return int(item.get('plan_item_id') or str(item['id']).replace('pi-', ''))


def _eligible_items(plan_date: str, vehicle_id: str) -> list[dict]:
    items = []
    for t in list_plan_tasks(plan_date, vehicle_id):
        if t.get('status') not in ACTIVE_ITEM_STATUSES:
            continue
        if not t.get('has_coordinates') or t.get('latitude') is None:
            continue
        items.append(t)
    return items


def _active_expected_task(items: list[dict]) -> dict | None:
    """First open automation-eligible task by canonical order_no/sira."""
    if not items:
        return None
    return min(items, key=lambda x: (x.get('order_no') or 999, x.get('id') or ''))


def _geofence_gps_unusable(gps_row: dict, now: datetime) -> bool:
    if gps_row.get('is_stale'):
        return True
    gps_dt = parse_gps_timestamp(gps_row.get('gps_timestamp') or '')
    if gps_dt is None:
        return True
    age = (now - gps_dt).total_seconds()
    if age > GEOFENCE_STALE_SECONDS:
        return True
    return False


def _should_process(gps_row: dict, visit: dict | None) -> bool:
    if visit and visit.get('last_gps_snapshot_id') == gps_row.get('id'):
        return False
    if visit and visit.get('last_gps_snapshot_id'):
        from modules.planlama.arac_gps_snapshot_repo import get_gps_snapshot_by_id
        prev_row = get_gps_snapshot_by_id(int(visit['last_gps_snapshot_id']))
        if prev_row:
            gps_dt = parse_gps_timestamp(gps_row.get('gps_timestamp') or '')
            prev = parse_gps_timestamp(prev_row.get('gps_timestamp') or '')
            if prev and gps_dt and gps_dt < prev:
                return False
    return True


def _distance_to_item(gps_row: dict, item: dict) -> float:
    return haversine_m(
        float(gps_row['latitude']), float(gps_row['longitude']),
        float(item['latitude']), float(item['longitude']),
    )


def _inside_enter_candidates(gps_row: dict, items: list[dict]) -> list[tuple[dict, float]]:
    out: list[tuple[dict, float]] = []
    for item in items:
        d = _distance_to_item(gps_row, item)
        if d <= ENTER_M:
            out.append((item, d))
    return out


def _emit_out_of_sequence_conn(
    con,
    *,
    plan_id: int,
    plan_is_id: int,
    vehicle_id: str,
    item: dict,
    dist: float,
    gps_row: dict,
    updated_at: str,
) -> None:
    if geofence_metadata_event_exists_conn(
        con, plan_is_id, EVENT_OUT_OF_SEQUENCE, OUT_OF_SEQUENCE_KIND,
    ):
        return
    insert_geofence_event_conn(
        con,
        plan_id=plan_id,
        plan_is_id=plan_is_id,
        arac_external_id=vehicle_id,
        olay_turu=EVENT_OUT_OF_SEQUENCE,
        mesaj='Sıra dışı geofence — otomatik varış yapılmadı',
        metadata={
            'geofence_kind': OUT_OF_SEQUENCE_KIND,
            'distance_m': round(dist, 1),
            'gps_snapshot_id': gps_row.get('id'),
            'plan_item_id': item.get('id'),
            'kayitli_yer_id': item.get('kayitli_yer_id'),
        },
        olay_zamani=gps_row.get('gps_timestamp'),
        created_at=updated_at,
    )


def _apply_state_machine(
    *,
    dist: float,
    state: str,
    ci: int,
    co: int,
    arrived_at: str | None,
    departed_at: str | None,
    gps_row: dict,
    plan_is_id: int,
    plan_id: int,
    vehicle_id: str,
    item: dict,
    con,
    updated_at: str,
) -> tuple[str, int, int, str | None, str | None, int | None, bool, bool]:
    """Returns new_state, ci, co, arrived_at, departed_at, dwell_seconds, emit_arrived, emit_departed."""
    new_state = state
    emit_arrived = emit_departed = False
    dwell_seconds = None

    if state in TERMINAL_VISIT_STATES:
        return state, ci, co, arrived_at, departed_at, None, False, False

    if state == STATE_ARRIVED:
        if dist < EXIT_M:
            co = 0
        elif dist >= EXIT_M:
            co += 1
            ci = 0
            if co >= CONFIRM_OUTSIDE:
                new_state = STATE_DEPARTED_PENDING
                departed_at = gps_row.get('gps_timestamp')
                if not event_exists_conn(con, plan_is_id, EVENT_DEPARTED):
                    emit_departed = True
        return new_state, ci, co, arrived_at, departed_at, None, emit_arrived, emit_departed

    if state == STATE_APPROACHING:
        if dist > APPROACHING_M:
            new_state = STATE_OUTSIDE
            ci = 0
            co = 0
        elif dist <= ENTER_M:
            ci += 1
            co = 0
            if ci == 1:
                arrived_at = gps_row.get('gps_timestamp')
            if ci >= CONFIRM_INSIDE:
                new_state = STATE_ARRIVED
                if not arrived_at:
                    arrived_at = gps_row.get('gps_timestamp')
                if not event_exists_conn(con, plan_is_id, EVENT_ARRIVED):
                    emit_arrived = True
        return new_state, ci, co, arrived_at, departed_at, None, emit_arrived, emit_departed

    # OUTSIDE (default)
    if dist <= ENTER_M:
        ci += 1
        co = 0
        if ci == 1:
            arrived_at = gps_row.get('gps_timestamp')
        if ci >= CONFIRM_INSIDE:
            new_state = STATE_ARRIVED
            if not arrived_at:
                arrived_at = gps_row.get('gps_timestamp')
            if not event_exists_conn(con, plan_is_id, EVENT_ARRIVED):
                emit_arrived = True
    elif dist <= APPROACHING_M:
        new_state = STATE_APPROACHING
        ci = 0
        co = 0
        if not event_exists_conn(con, plan_is_id, EVENT_APPROACHING):
            insert_geofence_event_conn(
                con,
                plan_id=plan_id,
                plan_is_id=plan_is_id,
                arac_external_id=vehicle_id,
                olay_turu=EVENT_APPROACHING,
                mesaj='Duraga yaklaşıyor',
                metadata={
                    'geofence_kind': APPROACHING_KIND,
                    'distance_m': round(dist, 1),
                    'gps_snapshot_id': gps_row.get('id'),
                    'plan_item_id': item.get('id'),
                    'approaching_radius_m': APPROACHING_M,
                },
                olay_zamani=gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )
    else:
        ci = 0
        co = 0

    return new_state, ci, co, arrived_at, departed_at, dwell_seconds, emit_arrived, emit_departed


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

    if _geofence_gps_unusable(gps_row, now):
        return {'ok': True, 'skipped': True, 'reason': 'geofence_stale_gps'}

    vehicle_id = str(gps_row.get('arac_external_id') or '')
    pd = plan_date or (gps_row.get('gps_timestamp') or '')[:10]
    plan = get_active_plan_row(pd, vehicle_id) if pd and vehicle_id else None
    if not plan:
        return {'ok': True, 'skipped': True, 'reason': 'no_active_plan'}

    plan_id = int(plan['id'])
    items = _eligible_items(pd, vehicle_id)
    if not items:
        return {'ok': True, 'processed': 0, 'plan_id': plan_id}

    active = _active_expected_task(items)
    if not active:
        return {'ok': True, 'processed': 0, 'plan_id': plan_id}

    inside = _inside_enter_candidates(gps_row, items)
    if len(inside) > 1:
        with geofence_write_transaction() as con:
            insert_geofence_event_conn(
                con,
                plan_id=plan_id,
                plan_is_id=None,
                arac_external_id=vehicle_id,
                olay_turu=EVENT_AMBIGUOUS,
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

    active_id = _plan_is_id(active)
    dist_active = _distance_to_item(gps_row, active)

    with geofence_write_transaction() as con:
        for item in items:
            if _plan_is_id(item) == active_id:
                continue
            dist_other = _distance_to_item(gps_row, item)
            if dist_other <= APPROACHING_M:
                _emit_out_of_sequence_conn(
                    con,
                    plan_id=plan_id,
                    plan_is_id=_plan_is_id(item),
                    vehicle_id=vehicle_id,
                    item=item,
                    dist=dist_other,
                    gps_row=gps_row,
                    updated_at=updated_at,
                )

        visit = get_visit_state_conn(con, active_id)
        if not _should_process(gps_row, visit):
            return {'ok': True, 'processed': 0, 'plan_id': plan_id, 'skipped': True}

        state = (visit or {}).get('state') or STATE_OUTSIDE
        ci = int((visit or {}).get('consecutive_inside') or 0)
        co = int((visit or {}).get('consecutive_outside') or 0)
        arrived_at = (visit or {}).get('arrived_at')
        departed_at = (visit or {}).get('departed_at')
        dwell_seconds = (visit or {}).get('dwell_seconds')

        new_state, ci, co, arrived_at, departed_at, _, emit_arrived, emit_departed = _apply_state_machine(
            dist=dist_active,
            state=state,
            ci=ci,
            co=co,
            arrived_at=arrived_at,
            departed_at=departed_at,
            gps_row=gps_row,
            plan_is_id=active_id,
            plan_id=plan_id,
            vehicle_id=vehicle_id,
            item=active,
            con=con,
            updated_at=updated_at,
        )

        if emit_arrived:
            insert_geofence_event_conn(
                con,
                plan_id=plan_id,
                plan_is_id=active_id,
                arac_external_id=vehicle_id,
                olay_turu=EVENT_ARRIVED,
                mesaj='Araç planlı durağa vardı',
                metadata={
                    'distance_m': round(dist_active, 1),
                    'gps_snapshot_id': gps_row.get('id'),
                    'plan_item_id': active.get('id'),
                    'kayitli_yer_id': active.get('kayitli_yer_id'),
                    'enter_radius_m': ENTER_M,
                    'arrived_at_rule': 'first_inside_candidate_timestamp',
                    'confirmed_at': gps_row.get('gps_timestamp'),
                },
                olay_zamani=arrived_at or gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )

        if emit_departed:
            dwell = None
            if arrived_at and gps_row.get('gps_timestamp'):
                a_dt = parse_gps_timestamp(arrived_at)
                d_dt = parse_gps_timestamp(gps_row['gps_timestamp'])
                if a_dt and d_dt:
                    dwell = int((d_dt - a_dt).total_seconds())
                    dwell_seconds = dwell
            insert_geofence_event_conn(
                con,
                plan_id=plan_id,
                plan_is_id=active_id,
                arac_external_id=vehicle_id,
                olay_turu=EVENT_DEPARTED,
                mesaj='Konumdan ayrıldı — iş sonucu doğrulanmadı',
                metadata={
                    'distance_m': round(dist_active, 1),
                    'gps_snapshot_id': gps_row.get('id'),
                    'plan_item_id': active.get('id'),
                    'exit_radius_m': EXIT_M,
                    'dwell_seconds': dwell,
                },
                olay_zamani=gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )
            insert_geofence_event_conn(
                con,
                plan_id=plan_id,
                plan_is_id=active_id,
                arac_external_id=vehicle_id,
                olay_turu=EVENT_RESULT_PENDING,
                mesaj='Ziyaret sonucu bekleniyor',
                metadata={'plan_item_id': active.get('id')},
                olay_zamani=gps_row.get('gps_timestamp'),
                created_at=updated_at,
            )

        upsert_visit_state_conn(con, {
            'plan_id': plan_id,
            'plan_is_id': active_id,
            'arac_external_id': vehicle_id,
            'kayitli_yer_id': active.get('kayitli_yer_id'),
            'state': new_state,
            'geofence_radius_m': ENTER_M,
            'exit_radius_m': EXIT_M,
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

        saved = get_visit_state_conn(con, active_id)
        return {
            'ok': True,
            'plan_id': plan_id,
            'processed': 1,
            'active_plan_is_id': active_id,
            'results': [{
                'plan_is_id': active_id,
                'state': saved.get('state') if saved else new_state,
                'distance_m': round(dist_active, 1),
            }],
        }


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

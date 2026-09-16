# -*- coding: utf-8 -*-
"""Geofence ziyaret state machine — GPS P3 + P0 auto-complete patch.

P0 DEĞİŞİKLİKLER (candidate/atp-route-status-p0-auto-complete-v1):
- _active_expected_task kısıtlaması kaldırıldı: tüm açık duraklar taranır.
- Sıra dışı durağa gerçekten gidilirse ARRIVED/DEPARTED/TAMAMLANDI zinciri çalışır.
- Deterministik çoklu eşleşme kuralı uygulanır.
- DEPARTED_PENDING → TAMAMLANDI otomatik zinciri eklendi.
- İdempotency: aynı GPS snapshot'ı veya aynı complete iki kez çalışmaz.
"""
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
EVENT_AUTO_COMPLETE = 'AUTO_TAMAMLANDI'
OUT_OF_SEQUENCE_KIND = 'OUT_OF_SEQUENCE_GEOFENCE'
OUT_OF_SEQUENCE_VISIT_ALERT_KIND = 'OUT_OF_SEQUENCE_VISIT_ALERT'
APPROACHING_KIND = 'APPROACHING'
AUTO_COMPLETE_KIND = 'AUTO_COMPLETE_GPS'

ACTIVE_ITEM_STATUSES = frozenset({'PLANLANDI', 'BASLADI'})
TERMINAL_VISIT_STATES = frozenset({STATE_DEPARTED_PENDING})

# Priority rank for deterministic tie-breaking (P0)
_PRIORITY_RANK = {'ACIL': 0, 'YUKSEK': 1, 'NORMAL': 2, 'DUSUK': 3}


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


def _select_target_item(
    candidates: list[tuple[dict, float]],
    visit_states: dict[int, dict],
) -> dict | None:
    """
    P0: Deterministik tek hedef seçimi.
    1. En kısa mesafe (±1m tolerans)
    2. Mevcut ARRIVED/APPROACHING state'i olan
    3. Öncelik: ACIL > YUKSEK > NORMAL > DUSUK
    4. Düşük sira
    5. Hâlâ eşitse: AMBIGUOUS → None
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    min_dist = min(d for _, d in candidates)
    close = [(item, d) for item, d in candidates if abs(d - min_dist) <= 1.0]
    if len(close) == 1:
        return close[0][0]

    active_visit = [
        (item, d) for item, d in close
        if (visit_states.get(_plan_is_id(item)) or {}).get('state') in (STATE_ARRIVED, STATE_APPROACHING)
    ]
    if len(active_visit) == 1:
        return active_visit[0][0]
    pool = active_visit if active_visit else close

    def _sk(pair: tuple) -> tuple:
        item, _ = pair
        pri = _PRIORITY_RANK.get((item.get('priority') or item.get('oncelik') or 'NORMAL').upper(), 2)
        sira = int(item.get('order_no') or 999)
        return (pri, sira)

    pool.sort(key=_sk)
    if len(pool) > 1 and _sk(pool[0]) == _sk(pool[1]):
        return None  # AMBIGUOUS
    return pool[0][0]


def _auto_complete_task_conn(
    con,
    *,
    plan_id: int,
    plan_is_id: int,
    vehicle_id: str,
    item: dict,
    visit: dict,
    gps_row: dict,
    updated_at: str,
    is_out_of_sequence: bool = False,
    expected_item_id: int | None = None,
) -> None:
    """P0: DEPARTED_PENDING → TAMAMLANDI. Idempotent."""
    import sqlite3 as _sq
    row = con.execute(
        'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,)
    ).fetchone()
    if not row:
        return
    current = row['durum'] if hasattr(row, '__getitem__') else row[0]
    if current == 'TAMAMLANDI':
        return  # idempotent
    if current not in ACTIVE_ITEM_STATUSES:
        return  # IPTAL/inactive — never auto-complete
    already_audited = event_exists_conn(con, plan_is_id, EVENT_AUTO_COMPLETE)
    con.execute(
        'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
        ('TAMAMLANDI', plan_is_id),
    )
    con.execute(
        "UPDATE arac_plan_is_ziyaret_durum SET result_status='SONUC_BEKLIYOR', updated_at=? WHERE plan_is_id=?",
        (updated_at, plan_is_id),
    )
    if not already_audited:
        insert_geofence_event_conn(
            con,
            plan_id=plan_id,
            plan_is_id=plan_is_id,
            arac_external_id=vehicle_id,
            olay_turu=EVENT_AUTO_COMPLETE,
            mesaj='GPS hareketine göre rota görevi otomatik tamamlandı',
            metadata={
                'geofence_kind': AUTO_COMPLETE_KIND,
                'arrived_at': visit.get('arrived_at'),
                'departed_at': visit.get('departed_at'),
                'dwell_seconds': visit.get('dwell_seconds'),
                'gps_snapshot_id': gps_row.get('id'),
                'plan_item_id': item.get('id'),
                'actual_item_id': item.get('plan_item_id') or item.get('id'),
                'expected_item_id': expected_item_id,
                'out_of_sequence': is_out_of_sequence,
                'p0_trigger': 'confirmed_enter_confirmed_exit',
            },
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )


def _stop_label(item: dict | None) -> str:
    if not item:
        return '—'
    return (
        item.get('company_name')
        or item.get('job_title')
        or f"Durak #{item.get('order_no') or item.get('display_order_no') or '?'}"
    )


def _emit_out_of_sequence_visit_alert_conn(
    con,
    *,
    plan_id: int,
    plan_is_id: int,
    vehicle_id: str,
    item: dict,
    expected_item: dict | None,
    gps_row: dict,
    updated_at: str,
    olay_zamani: str | None = None,
) -> None:
    """R13: doğrulanmış sıra dışı ARRIVED (2× GPS) için tek kullanıcı uyarısı."""
    if geofence_metadata_event_exists_conn(
        con, plan_is_id, EVENT_OUT_OF_SEQUENCE, OUT_OF_SEQUENCE_VISIT_ALERT_KIND,
    ):
        return
    expected_name = _stop_label(expected_item)
    actual_name = _stop_label(item)
    plate = item.get('arac_plaka_snapshot') or item.get('plate') or vehicle_id
    expected_item_id = None
    if expected_item:
        expected_item_id = expected_item.get('plan_item_id') or expected_item.get('id')
    actual_item_id = item.get('plan_item_id') or item.get('id')
    when = olay_zamani or gps_row.get('gps_timestamp')
    message = (
        f"Araç planlanan {expected_name} durağı yerine {actual_name} durağına ulaştı (GPS doğrulandı). "
        f"{expected_name} sıradaki beklenen durak olarak korunuyor."
    )
    insert_geofence_event_conn(
        con,
        plan_id=plan_id,
        plan_is_id=plan_is_id,
        arac_external_id=vehicle_id,
        olay_turu=EVENT_OUT_OF_SEQUENCE,
        mesaj=message,
        metadata={
            'geofence_kind': OUT_OF_SEQUENCE_VISIT_ALERT_KIND,
            'plate': plate,
            'expected_stop': expected_name,
            'actual_stop': actual_name,
            'expected_item_id': expected_item_id,
            'actual_item_id': actual_item_id,
            'vehicle_id': vehicle_id,
            'plan_id': plan_id,
            'result': 'ARRIVED',
            'gps_snapshot_id': gps_row.get('id'),
            'olay_zamani': when,
        },
        olay_zamani=when,
        created_at=updated_at,
    )


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
        mesaj='Sıra dışı geofence — audit kaydı (P0: ziyaret işleniyor)',
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


def _process_single_item_conn(
    *,
    gps_row: dict,
    item: dict,
    plan_id: int,
    vehicle_id: str,
    is_out_of_sequence: bool,
    expected_item: dict | None = None,
    con,
    updated_at: str,
) -> dict:
    """P0: state machine + auto-complete zinciri tek kalem için, mevcut transaction içinde."""
    plan_is_id = _plan_is_id(item)
    dist = _distance_to_item(gps_row, item)

    visit = get_visit_state_conn(con, plan_is_id)
    if not _should_process(gps_row, visit):
        return {'plan_is_id': plan_is_id, 'skipped': True, 'distance_m': round(dist, 1)}

    state = (visit or {}).get('state') or STATE_OUTSIDE
    ci = int((visit or {}).get('consecutive_inside') or 0)
    co = int((visit or {}).get('consecutive_outside') or 0)
    arrived_at = (visit or {}).get('arrived_at')
    departed_at = (visit or {}).get('departed_at')
    dwell_seconds = (visit or {}).get('dwell_seconds')

    new_state, ci, co, arrived_at, departed_at, _, emit_arrived, emit_departed = _apply_state_machine(
        dist=dist,
        state=state,
        ci=ci,
        co=co,
        arrived_at=arrived_at,
        departed_at=departed_at,
        gps_row=gps_row,
        plan_is_id=plan_is_id,
        plan_id=plan_id,
        vehicle_id=vehicle_id,
        item=item,
        con=con,
        updated_at=updated_at,
    )

    if emit_arrived:
        insert_geofence_event_conn(
            con,
            plan_id=plan_id,
            plan_is_id=plan_is_id,
            arac_external_id=vehicle_id,
            olay_turu=EVENT_ARRIVED,
            mesaj='Araç planlı durağa vardı' + (' (sıra dışı)' if is_out_of_sequence else ''),
            metadata={
                'distance_m': round(dist, 1),
                'gps_snapshot_id': gps_row.get('id'),
                'plan_item_id': item.get('id'),
                'kayitli_yer_id': item.get('kayitli_yer_id'),
                'enter_radius_m': ENTER_M,
                'arrived_at_rule': 'first_inside_candidate_timestamp',
                'confirmed_at': gps_row.get('gps_timestamp'),
                'out_of_sequence': is_out_of_sequence,
            },
            olay_zamani=arrived_at or gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )
        if is_out_of_sequence:
            _emit_out_of_sequence_visit_alert_conn(
                con,
                plan_id=plan_id,
                plan_is_id=plan_is_id,
                vehicle_id=vehicle_id,
                item=item,
                expected_item=expected_item,
                gps_row=gps_row,
                updated_at=updated_at,
                olay_zamani=arrived_at or gps_row.get('gps_timestamp'),
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
            plan_is_id=plan_is_id,
            arac_external_id=vehicle_id,
            olay_turu=EVENT_DEPARTED,
            mesaj='Konumdan ayrıldı — iş sonucu doğrulanmadı',
            metadata={
                'distance_m': round(dist, 1),
                'gps_snapshot_id': gps_row.get('id'),
                'plan_item_id': item.get('id'),
                'exit_radius_m': EXIT_M,
                'dwell_seconds': dwell,
                'out_of_sequence': is_out_of_sequence,
            },
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )
        insert_geofence_event_conn(
            con,
            plan_id=plan_id,
            plan_is_id=plan_is_id,
            arac_external_id=vehicle_id,
            olay_turu=EVENT_RESULT_PENDING,
            mesaj='Ziyaret sonucu bekleniyor',
            metadata={'plan_item_id': item.get('id')},
            olay_zamani=gps_row.get('gps_timestamp'),
            created_at=updated_at,
        )

    upsert_visit_state_conn(con, {
        'plan_id': plan_id,
        'plan_is_id': plan_is_id,
        'arac_external_id': vehicle_id,
        'kayitli_yer_id': item.get('kayitli_yer_id'),
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

    # P0 + live reconciliation: DEPARTED_PENDING → TAMAMLANDI.
    # emit_departed bir kerelik event kapısıdır; AUTO_TAMAMLANDI ondan bağımsızdır.
    # Terminal DEPARTED_PENDING + PLANLANDI/BASLADI split-brain'i de iyileştirir.
    auto_completed = False
    if new_state == STATE_DEPARTED_PENDING:
        updated_visit = get_visit_state_conn(con, plan_is_id)
        _auto_complete_task_conn(
            con,
            plan_id=plan_id,
            plan_is_id=plan_is_id,
            vehicle_id=vehicle_id,
            item=item,
            visit=dict(updated_visit) if updated_visit else {
                'arrived_at': arrived_at,
                'departed_at': departed_at,
                'dwell_seconds': dwell_seconds,
            },
            gps_row=gps_row,
            updated_at=updated_at,
            is_out_of_sequence=is_out_of_sequence,
            expected_item_id=(
                (expected_item.get('plan_item_id') or expected_item.get('id'))
                if expected_item else None
            ),
        )
        row_after = con.execute(
            'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
        ).fetchone()
        current_after = row_after['durum'] if row_after is not None and hasattr(row_after, '__getitem__') else (
            row_after[0] if row_after else None
        )
        auto_completed = current_after == 'TAMAMLANDI'

    saved = get_visit_state_conn(con, plan_is_id)
    return {
        'plan_is_id': plan_is_id,
        'state': saved.get('state') if saved else new_state,
        'distance_m': round(dist, 1),
        'out_of_sequence': is_out_of_sequence,
        'auto_completed': auto_completed,
    }


def _list_unreconciled_departed_conn(
    con,
    *,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
) -> list[dict]:
    """DEPARTED_PENDING visit + still-open plan item (PLANLANDI/BASLADI)."""
    sql = """
        SELECT z.plan_id, z.plan_is_id, z.arac_external_id,
               z.arrived_at, z.departed_at, z.dwell_seconds, z.last_gps_snapshot_id,
               i.durum
        FROM arac_plan_is_ziyaret_durum z
        JOIN arac_gunluk_plan_is i ON i.id = z.plan_is_id
        JOIN arac_gunluk_plan p ON p.id = z.plan_id
        WHERE z.state = ?
          AND i.durum IN ('PLANLANDI', 'BASLADI')
    """
    params: list = [STATE_DEPARTED_PENDING]
    if plan_date:
        sql += ' AND p.plan_tarihi = ?'
        params.append(plan_date)
    if vehicle_id:
        sql += ' AND z.arac_external_id = ?'
        params.append(vehicle_id)
    rows = con.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(dict(r) if hasattr(r, 'keys') else {
            'plan_id': r[0], 'plan_is_id': r[1], 'arac_external_id': r[2],
            'arrived_at': r[3], 'departed_at': r[4], 'dwell_seconds': r[5],
            'last_gps_snapshot_id': r[6], 'durum': r[7],
        })
    return out


def reconcile_departed_pending_completions(
    *,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Heal visit/status split-brain: confirmed depart must complete the plan item."""
    if not geofence_tables_ready():
        return {'ok': False, 'reconciled': 0, 'reason': 'geofence_tables_not_ready'}
    now = now or datetime.now()
    updated_at = now.strftime('%Y-%m-%d %H:%M:%S')
    reconciled = 0
    with geofence_write_transaction() as con:
        rows = _list_unreconciled_departed_conn(
            con, plan_date=plan_date, vehicle_id=vehicle_id,
        )
        for row in rows:
            plan_is_id = int(row['plan_is_id'])
            _auto_complete_task_conn(
                con,
                plan_id=int(row['plan_id']),
                plan_is_id=plan_is_id,
                vehicle_id=str(row.get('arac_external_id') or ''),
                item={'id': plan_is_id, 'plan_item_id': plan_is_id},
                visit={
                    'arrived_at': row.get('arrived_at'),
                    'departed_at': row.get('departed_at'),
                    'dwell_seconds': row.get('dwell_seconds'),
                },
                gps_row={
                    'id': row.get('last_gps_snapshot_id'),
                    'gps_timestamp': row.get('departed_at') or updated_at,
                },
                updated_at=updated_at,
            )
            reconciled += 1
    return {'ok': True, 'reconciled': reconciled}


def process_gps_snapshot_for_geofence(
    gps_row: dict,
    *,
    plan_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """
    P0: Per-vehicle geofence pass.
    - Tüm açık planlı durakları tarar (sıra kısıtı yok).
    - Doğrulanmış ENTER+EXIT sonrası TAMAMLANDI yazar.
    """
    now = now or datetime.now()
    updated_at = now.strftime('%Y-%m-%d %H:%M:%S')
    if not geofence_tables_ready():
        return {'ok': False, 'reason': 'geofence_tables_not_ready'}

    vehicle_id = str(gps_row.get('arac_external_id') or '')
    pd = plan_date or (gps_row.get('gps_timestamp') or '')[:10]
    if _geofence_gps_unusable(gps_row, now):
        rec = reconcile_departed_pending_completions(
            plan_date=pd or None,
            vehicle_id=vehicle_id or None,
            now=now,
        )
        return {'ok': True, 'skipped': True, 'reason': 'geofence_stale_gps', 'reconcile': rec}

    plan = get_active_plan_row(pd, vehicle_id) if pd and vehicle_id else None
    if not plan:
        return {'ok': True, 'skipped': True, 'reason': 'no_active_plan'}

    plan_id = int(plan['id'])
    items = _eligible_items(pd, vehicle_id)
    if not items:
        rec = reconcile_departed_pending_completions(
            plan_date=pd, vehicle_id=vehicle_id, now=now,
        )
        return {'ok': True, 'processed': 0, 'plan_id': plan_id, 'reconcile': rec}

    # P0: expected_task referans için (artık işlemi kısıtlamaz)
    expected = _active_expected_task(items)
    expected_id = _plan_is_id(expected) if expected else None

    inside = _inside_enter_candidates(gps_row, items)

    if len(inside) > 1:
        # P0: deterministik seçim dene
        with geofence_write_transaction() as con:
            vs_map = {
                _plan_is_id(it): dict(get_visit_state_conn(con, _plan_is_id(it)) or {})
                for it, _ in inside
            }
            target = _select_target_item(inside, vs_map)
            if target is None:
                insert_geofence_event_conn(
                    con,
                    plan_id=plan_id,
                    plan_is_id=None,
                    arac_external_id=vehicle_id,
                    olay_turu=EVENT_AMBIGUOUS,
                    mesaj='Birden fazla durak geofence içinde — AMBIGUOUS_STOP_MATCH',
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
            # Deterministik hedef seçildi
            target_id = _plan_is_id(target)
            is_oos = (expected_id is not None and target_id != expected_id)
            if is_oos:
                _emit_out_of_sequence_conn(
                    con, plan_id=plan_id, plan_is_id=target_id,
                    vehicle_id=vehicle_id, item=target,
                    dist=_distance_to_item(gps_row, target),
                    gps_row=gps_row, updated_at=updated_at,
                )
            result = _process_single_item_conn(
                gps_row=gps_row, item=target, plan_id=plan_id,
                vehicle_id=vehicle_id, is_out_of_sequence=is_oos,
                expected_item=expected, con=con, updated_at=updated_at,
            )
            return {'ok': True, 'plan_id': plan_id, 'processed': 1, 'results': [result]}

    elif len(inside) == 1:
        target = inside[0][0]
        target_id = _plan_is_id(target)
        is_oos = (expected_id is not None and target_id != expected_id)
        with geofence_write_transaction() as con:
            if is_oos:
                _emit_out_of_sequence_conn(
                    con, plan_id=plan_id, plan_is_id=target_id,
                    vehicle_id=vehicle_id, item=target,
                    dist=inside[0][1], gps_row=gps_row, updated_at=updated_at,
                )
            result = _process_single_item_conn(
                gps_row=gps_row, item=target, plan_id=plan_id,
                vehicle_id=vehicle_id, is_out_of_sequence=is_oos,
                expected_item=expected, con=con, updated_at=updated_at,
            )
            return {'ok': True, 'plan_id': plan_id, 'processed': 1, 'results': [result]}

    else:
        # Hiçbiri ENTER mesafesinde değil.
        # P0: ARRIVED state'indeki duraklar EXIT → TAMAMLANDI için işlenmeli.
        # Ayrıca expected durağı APPROACHING/OUTSIDE için işle.
        with geofence_write_transaction() as con:
            results = []

            # ARRIVED durakları EXIT için işle (expected dışındaki sıra dışı olanlar dahil)
            for item in items:
                item_id = _plan_is_id(item)
                visit = get_visit_state_conn(con, item_id)
                visit_state = (visit or {}).get('state') or STATE_OUTSIDE
                is_oos = (expected_id is not None and item_id != expected_id)

                if visit_state == STATE_ARRIVED:
                    # Bu durak ARRIVED — EXIT kontrolü yap
                    result = _process_single_item_conn(
                        gps_row=gps_row, item=item, plan_id=plan_id,
                        vehicle_id=vehicle_id, is_out_of_sequence=is_oos,
                        expected_item=expected, con=con, updated_at=updated_at,
                    )
                    results.append(result)
                elif item_id == expected_id:
                    # Expected durak — APPROACHING/OUTSIDE state güncellemesi
                    dist_other = _distance_to_item(gps_row, item)
                    if dist_other <= APPROACHING_M:
                        result = _process_single_item_conn(
                            gps_row=gps_row, item=item, plan_id=plan_id,
                            vehicle_id=vehicle_id, is_out_of_sequence=False,
                            expected_item=expected, con=con, updated_at=updated_at,
                        )
                        results.append(result)
                else:
                    # Diğer duraklar — sadece APPROACHING mesafesinde OUT_OF_SEQUENCE audit
                    dist_other = _distance_to_item(gps_row, item)
                    if dist_other <= APPROACHING_M:
                        _emit_out_of_sequence_conn(
                            con, plan_id=plan_id, plan_is_id=item_id,
                            vehicle_id=vehicle_id, item=item,
                            dist=dist_other, gps_row=gps_row, updated_at=updated_at,
                        )

            return {
                'ok': True, 'plan_id': plan_id, 'processed': len(results),
                'results': results,
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
    rec = reconcile_departed_pending_completions()
    return {
        'processed': len(outcomes),
        'last_id': max_id,
        'results': outcomes,
        'reconcile': rec,
    }

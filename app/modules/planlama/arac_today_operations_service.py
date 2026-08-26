# -*- coding: utf-8 -*-
"""Gün geneli birleşik read model — today_vehicle_operations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from modules.planlama.arac_geofence_repo import geofence_tables_ready, get_visit_state
from modules.planlama.arac_gps_poll_service import STALE_AGE, parse_gps_timestamp
from modules.planlama.arac_gps_snapshot_repo import (
    get_latest_gps_snapshot,
    gps_tables_ready,
    list_gps_snapshots_ordered,
)
from modules.planlama.arac_rota_deviation_repo import deviation_tables_ready, get_deviation_state
from modules.planlama.arac_takip_repo import (
    INACTIVE_PLAN_STATUSES,
    build_daily_plan_aggregate,
    tables_ready,
)

ROUTE_LABELS = {
    'ON_ROUTE': 'Rotada',
    'DEVIATION_CANDIDATE': 'Sapma doğrulanıyor',
    'DEVIATING': 'Rotadan saptı',
    'RECOVERY_CANDIDATE': 'Rotaya dönüyor',
    'NO_ROUTE_REFERENCE': 'Rota referansı yok',
    'NO_ACTIVE_PLAN': 'Aktif plan yok',
}

VISIT_LABELS = {
    'OUTSIDE': 'Henüz varmadı',
    'ARRIVED': 'Konumda',
    'DEPARTED_PENDING': 'Sonuç bekleniyor',
}

APPROACHING_M = 500.0


def _fmt_hhmm(ts: str | None) -> str | None:
    if not ts:
        return None
    dt = parse_gps_timestamp(ts)
    return dt.strftime('%H:%M') if dt else None


def _gps_age_seconds(gps_row: dict | None, now: datetime | None = None) -> int | None:
    if not gps_row or not gps_row.get('gps_timestamp'):
        return None
    gps_dt = parse_gps_timestamp(gps_row['gps_timestamp'])
    if not gps_dt:
        return None
    now = now or datetime.now()
    return max(0, int((now - gps_dt).total_seconds()))


def _dwell_minutes(
    arrived_at: str | None,
    departed_at: str | None,
    *,
    now: datetime | None = None,
    stored_seconds: int | None = None,
) -> int | None:
    if stored_seconds is not None:
        return max(0, int(stored_seconds // 60))
    if not arrived_at:
        return None
    a_dt = parse_gps_timestamp(arrived_at)
    if not a_dt:
        return None
    now = now or datetime.now()
    end_dt = parse_gps_timestamp(departed_at) if departed_at else now
    if not end_dt:
        return None
    return max(0, int((end_dt - a_dt).total_seconds() // 60))


def _build_visit_label(
    visit: dict | None,
    *,
    item: dict | None = None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now()
    state = (visit or {}).get('state') or 'OUTSIDE'
    arrived_at = (visit or {}).get('arrived_at')
    departed_at = (visit or {}).get('departed_at')
    dwell = _dwell_minutes(
        arrived_at, departed_at,
        now=now,
        stored_seconds=(visit or {}).get('dwell_seconds'),
    )

    if state == 'OUTSIDE':
        return VISIT_LABELS['OUTSIDE']
    if state == 'ARRIVED':
        arr = _fmt_hhmm(arrived_at)
        if arr and dwell is not None:
            return f'Varış {arr} · Konumda {dwell} dk'
        if arr:
            return f'Varış {arr}'
        return VISIT_LABELS['ARRIVED']
    if state == 'DEPARTED_PENDING':
        arr = _fmt_hhmm(arrived_at)
        dep = _fmt_hhmm(departed_at)
        if arr and dep and dwell is not None:
            return f'{arr} Varış · {dep} Ayrılış · {dwell} dk'
        if dep:
            return f'Ayrılış {dep} · Sonuç bekleniyor'
        return VISIT_LABELS['DEPARTED_PENDING']
    return VISIT_LABELS.get(state, state)


def _is_active_plan_item(item: dict | None) -> bool:
    st = (item or {}).get('status') or 'PLANLANDI'
    return st not in INACTIVE_PLAN_STATUSES


def _build_vehicle_visit_summary(items: list[dict], vid: str) -> dict | None:
    """Active visit info for vehicle card from today's active items."""
    active = [
        it for it in items
        if _is_active_plan_item(it)
        and str(it.get('arac_external_id') or '') == vid
        and it.get('visit_state') in ('ARRIVED', 'DEPARTED_PENDING')
    ]
    if not active:
        pending = [
            it for it in items
            if _is_active_plan_item(it)
            and str(it.get('arac_external_id') or '') == vid
            and it.get('status') in ('PLANLANDI', 'BASLADI')
            and it.get('visit_state') == 'OUTSIDE'
        ]
        if pending:
            return {'label': 'Henüz varmadı', 'state': 'OUTSIDE'}
        return None
    it = active[0]
    return {
        'label': it.get('visit_label'),
        'state': it.get('visit_state'),
        'arrived_at': it.get('arrived_at'),
        'departed_at': it.get('departed_at'),
        'dwell_minutes': it.get('dwell_minutes'),
    }


def _fmt_km(m: float | None) -> str:
    if m is None:
        return '—'
    km = m / 1000.0
    if km < 1:
        return f'{km:.1f} km'.replace('.', ',')
    return f'{km:.1f} km'.replace('.', ',')


def _route_status_label(state: str | None, deviation_m: float | None) -> str:
    st = state or 'NO_ACTIVE_PLAN'
    if st == 'DEVIATING' and deviation_m:
        return f'Rotadan {_fmt_km(deviation_m)} saptı'
    if st == 'ON_ROUTE':
        return 'Rotada'
    return ROUTE_LABELS.get(st, st)


def _gps_stale(gps_row: dict | None, now: datetime | None = None) -> bool:
    if not gps_row:
        return True
    if gps_row.get('is_stale'):
        return True
    gps_dt = parse_gps_timestamp(gps_row.get('gps_timestamp') or '')
    if gps_dt is None:
        return True
    now = now or datetime.now()
    return (now - gps_dt) > STALE_AGE


def _build_alerts(
    plan_date: str,
    vehicles: list[dict],
    items: list[dict],
    filom_by_id: dict[str, dict],
) -> list[dict]:
    alerts: list[dict] = []
    now = datetime.now()

    for v in vehicles:
        vid = str(v.get('arac_external_id') or '')
        gps = v.get('latest_gps')
        if v.get('plan_id') and v.get('route_state') == 'DEVIATING':
            alerts.append({
                'type': 'ROUTE_DEVIATION',
                'severity': 'warning',
                'message': f"{v.get('plate') or v.get('arac_plaka_snapshot')} — {_route_status_label('DEVIATING', v.get('current_deviation_m'))}",
                'vehicle_id': vid,
                'plan_id': v.get('plan_id'),
                'action': 'inspect',
            })
        if v.get('route_state') == 'NO_ROUTE_REFERENCE':
            alerts.append({
                'type': 'NO_ROUTE',
                'severity': 'info',
                'message': f"{v.get('plate') or v.get('arac_plaka_snapshot')} — rota referansı yok",
                'vehicle_id': vid,
                'plan_id': v.get('plan_id'),
            })
        if _gps_stale(gps, now) and vid:
            alerts.append({
                'type': 'GPS_STALE',
                'severity': 'warning',
                'message': f"{v.get('plate') or v.get('arac_plaka_snapshot')} — GPS verisi eski",
                'vehicle_id': vid,
                'plan_id': v.get('plan_id'),
            })

    for item in items:
        if not _is_active_plan_item(item):
            continue
        if item.get('visit_state') == 'DEPARTED_PENDING' and item.get('status') != 'TAMAMLANDI':
            alerts.append({
                'type': 'VISIT_RESULT_PENDING',
                'severity': 'warning',
                'message': f"{item.get('company_name')} — konuma gidildi/ayrıldı, sonuç girilmedi",
                'plan_item_id': item.get('plan_item_id'),
                'vehicle_id': item.get('arac_external_id'),
            })
        if not item.get('has_coordinates'):
            alerts.append({
                'type': 'MISSING_LOCATION',
                'severity': 'info',
                'message': f"{item.get('company_name')} — konumu eksik",
                'plan_item_id': item.get('plan_item_id'),
            })
        if not item.get('arac_external_id'):
            alerts.append({
                'type': 'UNASSIGNED_VEHICLE',
                'severity': 'info',
                'message': f"{item.get('company_name')} — araç atanmamış",
                'plan_item_id': item.get('plan_item_id'),
            })
        pt = item.get('planned_time')
        if pt and item.get('status') in ('PLANLANDI', 'BASLADI'):
            try:
                planned_dt = datetime.strptime(f"{plan_date} {pt[:5]}", '%Y-%m-%d %H:%M')
                if planned_dt < now - timedelta(minutes=15):
                    alerts.append({
                        'type': 'PLANNED_TIME_PASSED',
                        'severity': 'warning',
                        'message': f"{item.get('company_name')} — planlı saat geçti ({pt})",
                        'plan_item_id': item.get('plan_item_id'),
                    })
            except ValueError:
                pass

    # Ambiguous stop events today
    if geofence_tables_ready():
        from modules.planlama.arac_takip_repo import get_conn
        con = get_conn()
        try:
            rows = con.execute(
                """
                SELECT * FROM arac_plan_olay
                WHERE olay_turu='AMBIGUOUS_STOP' AND date(olay_zamani)=?
                ORDER BY created_at DESC LIMIT 20
                """,
                (plan_date,),
            ).fetchall()
            for row in rows:
                alerts.append({
                    'type': 'AMBIGUOUS_STOP',
                    'severity': 'danger',
                    'message': row['mesaj'],
                    'vehicle_id': row['arac_external_id'],
                    'plan_id': row['plan_id'],
                })
        finally:
            con.close()

    return alerts


def get_today_vehicle_operations(
    plan_date: str,
    *,
    filom_payload: dict | None = None,
) -> dict:
    """Unified read model for Mehmet V1–V2 daily screen."""
    now = datetime.now()
    if not tables_ready():
        return {
            'ok': True,
            'plan_date': plan_date,
            'data_source': 'unavailable',
            'kpi': {},
            'vehicles': [],
            'items': [],
            'alerts': [],
            'map': {'vehicles': [], 'tracks': [], 'routes': []},
            'gps_health': {'stale_count': 0, 'total_tracked': 0},
            'message': 'Tablolar hazır değil',
        }

    aggregate = build_daily_plan_aggregate(plan_date)
    filom_vehicles: list[dict] = []
    filom_kpi: dict | None = None
    if filom_payload and filom_payload.get('ok'):
        filom_vehicles = filom_payload.get('vehicles') or []
        filom_kpi = filom_payload.get('kpi')
    elif filom_payload is None:
        try:
            from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import get_live_vehicles
            live = get_live_vehicles()
            if live.get('ok'):
                filom_vehicles = live.get('vehicles') or []
                filom_kpi = live.get('kpi')
        except Exception:
            filom_vehicles = []
            filom_kpi = None

    filom_by_id = {str(v.get('id')): v for v in filom_vehicles if v.get('id')}
    active_filom = [v for v in filom_vehicles if v.get('activity_status') != 'PASIF']
    moving = [v for v in active_filom if v.get('activity_status') in ('HAREKETLI', 'MOVING') or (v.get('speed_kmh') or 0) > 5]

    _gps_ready = gps_tables_ready()
    vehicles_out: list[dict] = []
    map_vehicles: list[dict] = []
    stale_count = 0

    for plan_v in aggregate.get('vehicles') or []:
        vid = str(plan_v.get('arac_external_id') or '')
        plan_id = plan_v.get('plan_id')
        filom = filom_by_id.get(vid)
        gps_db = get_latest_gps_snapshot(vid) if _gps_ready else None
        gps_row = gps_db or (filom and {
            'latitude': filom.get('latitude'),
            'longitude': filom.get('longitude'),
            'gps_timestamp': filom.get('last_seen_at'),
            'is_stale': filom.get('is_stale_data'),
            'speed_kmh': filom.get('speed_kmh'),
        })
        stale = _gps_stale(gps_row if isinstance(gps_row, dict) else None, now)
        if stale:
            stale_count += 1

        route_state = 'NO_ACTIVE_PLAN'
        deviation_m = None
        max_deviation_m = None
        deviation_started_at = None
        if deviation_tables_ready() and plan_id:
            dev = get_deviation_state(int(plan_id))
            if dev:
                route_state = dev.get('state') or route_state
                deviation_m = dev.get('current_deviation_m')
                max_deviation_m = dev.get('max_deviation_m')
                deviation_started_at = dev.get('deviation_started_at')

        physical = '—'
        if gps_db and not stale:
            # Prefer sqlite GPS activity_status (direct from DB, most up-to-date)
            db_act = gps_db.get('activity_status') if isinstance(gps_db, dict) else None
            physical = db_act or '—'
        elif filom:
            physical = filom.get('activity_label') or filom.get('status_label') or filom.get('activity_status') or '—'
        elif gps_row and not stale:
            spd = (gps_row.get('speed_kmh') if isinstance(gps_row, dict) else None) or 0
            physical = 'Hareket halinde' if spd and float(spd) > 5 else 'Duruyor'

        gps_age = _gps_age_seconds(gps_row if isinstance(gps_row, dict) else None, now)
        vehicles_out.append({
            'plan_id': plan_id,
            'arac_external_id': vid,
            'plate': plan_v.get('arac_plaka_snapshot'),
            'driver': plan_v.get('sofor_adi_snapshot'),
            'driver_name': plan_v.get('sofor_adi_snapshot'),
            'cikis_saati': plan_v.get('cikis_saati'),
            'departure_time': plan_v.get('cikis_saati'),
            'progress_completed': plan_v.get('progress_completed', 0),
            'progress_total': plan_v.get('progress_total', 0),
            'progress_label': plan_v.get('progress_label', '0/0'),
            'next_stop': plan_v.get('next_stop_label') or (plan_v.get('next_item') or {}).get('company_name'),
            'next_stop_label': plan_v.get('next_stop_label'),
            'next_order_no': plan_v.get('next_order_no'),
            'next_display_order_no': plan_v.get('next_display_order_no'),
            'next_time': plan_v.get('next_time'),
            'physical_status': physical,
            'physical_source': 'filom' if filom else ('sqlite' if gps_db else None),
            'route_state': route_state,
            'route_status_label': _route_status_label(route_state, deviation_m),
            'current_deviation_m': deviation_m,
            'deviation_m': deviation_m,
            'max_deviation_m': max_deviation_m,
            'deviation_started_at': deviation_started_at,
            'latest_gps': gps_row if isinstance(gps_row, dict) else None,
            'gps_stale': stale,
            'gps_is_stale': stale,
            'gps_timestamp': (gps_row or {}).get('gps_timestamp') if isinstance(gps_row, dict) else None,
            'gps_last_seen_at': (gps_row or {}).get('gps_timestamp') if isinstance(gps_row, dict) else None,
            'gps_age_seconds': gps_age,
            'gps_source': 'sqlite' if gps_db else ('filom' if filom else None),
        })

        if gps_row and isinstance(gps_row, dict) and gps_row.get('latitude') is not None:
            map_vehicles.append({
                'id': vid,
                'plate': plan_v.get('arac_plaka_snapshot'),
                'lat': float(gps_row['latitude']),
                'lng': float(gps_row['longitude']),
                'stale': stale,
                'selected': False,
            })

    items_out: list[dict] = []
    for item in aggregate.get('items') or []:
        plan_is_id = item.get('plan_item_id')
        visit = get_visit_state(int(plan_is_id)) if geofence_tables_ready() and plan_is_id else None
        visit_state = (visit or {}).get('state') or 'OUTSIDE'
        arrived_at = (visit or {}).get('arrived_at')
        departed_at = (visit or {}).get('departed_at')
        dwell_min = _dwell_minutes(
            arrived_at, departed_at,
            now=now,
            stored_seconds=(visit or {}).get('dwell_seconds'),
        )
        items_out.append({
            'id': item.get('id'),
            'plan_item_id': plan_is_id,
            'is_talebi_id': item.get('is_talebi_id'),
            'order_no': item.get('order_no'),
            'display_order_no': item.get('display_order_no'),
            'planned_time': item.get('planned_time'),
            'eta_time': item.get('eta_time'),
            'tahmini_varis_saati': item.get('tahmini_varis_saati'),
            'company_name': item.get('company_name'),
            'job_title': item.get('job_title'),
            'address_text': item.get('address_text'),
            'priority': item.get('priority'),
            'priority_label': item.get('priority_label'),
            'plate': item.get('arac_plaka_snapshot'),
            'driver': item.get('sofor_adi_snapshot'),
            'arac_external_id': item.get('arac_external_id'),
            'status': item.get('status'),
            'status_label': item.get('status_label'),
            'visit_state': visit_state,
            'visit_label': _build_visit_label(visit, item=item, now=now),
            'arrived_at': arrived_at,
            'departed_at': departed_at,
            'dwell_minutes': dwell_min,
            'arrival_confirmed': visit_state in ('ARRIVED', 'DEPARTED_PENDING'),
            'departure_confirmed': visit_state == 'DEPARTED_PENDING',
            'has_coordinates': item.get('has_coordinates'),
            'latitude': item.get('latitude'),
            'longitude': item.get('longitude'),
        })

    active_items_out = [it for it in items_out if _is_active_plan_item(it)]

    # Vehicle visit summary from active items only
    for v in vehicles_out:
        vid = str(v.get('arac_external_id') or '')
        summary = _build_vehicle_visit_summary(active_items_out, vid)
        v['visit_summary'] = summary
        if summary and summary.get('label'):
            v['visit_label'] = summary['label']
        else:
            v['visit_label'] = None
        if v.get('route_state') == 'DEVIATING' and v.get('deviation_m') and v.get('deviation_started_at'):
            dev_dt = parse_gps_timestamp(v['deviation_started_at'])
            if dev_dt:
                dev_min = max(0, int((now - dev_dt).total_seconds() // 60))
                v['deviation_label'] = f"Rotadan {_fmt_km(v['deviation_m'])} saptı · {dev_min} dk"
            else:
                v['deviation_label'] = _route_status_label('DEVIATING', v.get('deviation_m'))
        elif v.get('gps_is_stale'):
            v['gps_stale_label'] = 'GPS verisi eski'
        else:
            v['deviation_label'] = None
            v['gps_stale_label'] = None

    problem_count = sum(
        1 for a in _build_alerts(plan_date, vehicles_out, active_items_out, filom_by_id)
        if a.get('severity') in ('warning', 'danger')
    )

    kpi = {
        'aktif_arac': (filom_kpi or {}).get('aktif_arac') if filom_kpi else (len(active_filom) if filom_vehicles else None),
        'aktif_arac_source': 'filom' if filom_kpi or filom_vehicles else None,
        'hareket_halinde': (filom_kpi or {}).get('hareket_halinde') if filom_kpi else (len(moving) if filom_vehicles else None),
        'hareket_source': 'filom' if filom_kpi or filom_vehicles else None,
        'toplam_is': aggregate.get('operational_total_count', 0),
        'toplam_is_source': 'canonical',
        'tamamlandi': aggregate.get('completed_count', 0),
        'tamamlandi_source': 'canonical',
        'devam_ediyor': aggregate.get('started_count', 0) + aggregate.get('planned_count', 0),
        'devam_source': 'canonical',
        'sorunlu': problem_count,
        'sorunlu_source': 'alerts',
    }

    tracks: list[dict] = []
    for v in vehicles_out:
        vid = v.get('arac_external_id')
        if not vid or not _gps_ready:
            continue
        snaps = list_gps_snapshots_ordered(str(vid), limit=200)
        if len(snaps) >= 2:
            tracks.append({
                'vehicle_id': vid,
                'points': [[s['latitude'], s['longitude']] for s in snaps if s.get('latitude') is not None],
                'source': 'sqlite',
            })

    alerts = _build_alerts(plan_date, vehicles_out, active_items_out, filom_by_id)
    normal_message = 'Bugünkü plan normal ilerliyor' if not alerts else None

    return {
        'ok': True,
        'plan_date': plan_date,
        'data_source': 'merged',
        'kpi': kpi,
        'vehicles': vehicles_out,
        'items': active_items_out,
        'alerts': alerts,
        'alerts_normal_message': normal_message,
        'map': {
            'vehicles': map_vehicles,
            'tracks': tracks,
            'routes': [],
        },
        'gps_health': {
            'schema_ready': _gps_ready,
            'stale_count': stale_count,
            'total_tracked': len(vehicles_out),
        },
        'day_plan_summary': aggregate,
    }

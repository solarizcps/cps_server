# -*- coding: utf-8 -*-
"""Gün geneli birleşik read model — today_vehicle_operations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from modules.planlama.arac_geofence_repo import geofence_tables_ready, get_visit_state
from modules.planlama.arac_gps_poll_service import STALE_AGE, parse_gps_timestamp
from modules.planlama.arac_gps_source_selector import (
    SOURCE_FILOM,
    SOURCE_SQLITE,
    apply_gps_bundle_to_vehicle,
    select_freshest_gps_source,
)
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
    'APPROACHING': 'Yaklaşıyor',
    'ARRIVED': 'Konumda',
    'DEPARTED_PENDING': 'Sonuç bekleniyor',
}

APPROACHING_M = 500.0
STOP_OVERSTAY_THRESHOLD_SECONDS = 600
STOP_OVERSTAY_MOVING_SPEED_KMH = 5.0
STOP_OVERSTAY_ALERT_TYPE = 'STOP_OVERSTAY'

STATUS_CONTRACT_VERSION = 'ATP_LIVE_STATUS_V1'

PLAN_TRIP_STATUS_LABELS = {
    'PLANLANDI': 'Planlandı',
    'YOLDA': 'Yolda',
    'KONUMA_YAKLASIYOR': 'Konuma yaklaşıyor',
    'VARILDI': 'Varıldı',
    'SONUC_BEKLIYOR': 'Sonuç bekliyor',
    'TAMAMLANDI': 'Tamamlandı',
    'GECIKIYOR': 'Gecikiyor',
}

VEHICLE_PHYSICAL_LABELS = {
    'HAREKETLI': 'Araç hareketli',
    'DURAN': 'Araç duruyor',
    'GPS_ESKI': 'GPS eski',
    'BILINMIYOR': 'GPS bilinmiyor',
}

_ACTIVE_ROUTE_STATES = frozenset({
    'ON_ROUTE', 'DEVIATING', 'DEVIATION_CANDIDATE', 'RECOVERY_CANDIDATE',
})

_TRIP_START_EVENTS = frozenset({
    'ROTA_SAPMA_BASLADI', 'ROTA_GERI_DONDU', 'KONUMA_VARILDI',
    'KONUMDAN_AYRILDI', 'GEOFENCE_GIRIS', 'ZIYARET_SONUC_BEKLIYOR',
})


def _parse_plan_date(plan_date: str):
    return datetime.strptime(plan_date[:10], '%Y-%m-%d').date()


def _physical_status_alias(vehicle_physical_status: str) -> str:
    if vehicle_physical_status == 'HAREKETLI':
        return 'Hareketli'
    if vehicle_physical_status == 'DURAN':
        return 'Duruyor'
    return '—'


def _resolve_vehicle_physical_status(
    gps_row: dict | None,
    *,
    filom: dict | None,
    gps_db: dict | None,
    stale: bool,
) -> str:
    if stale or not gps_row:
        return 'GPS_ESKI'
    raw = None
    if gps_db and isinstance(gps_db, dict):
        raw = gps_db.get('activity_status')
    elif filom:
        raw = filom.get('activity_status') or filom.get('activity_label')
    elif isinstance(gps_row, dict):
        raw = gps_row.get('activity_status')
    text = str(raw or '').strip()
    upper = text.upper()
    if upper in ('HAREKETLI', 'MOVING') or text in ('Hareketli', 'Hareket halinde'):
        return 'HAREKETLI'
    if upper in ('DURAN', 'STOPPED', 'ROLANTI') or text in ('Duran', 'Duruyor'):
        return 'DURAN'
    spd = 0.0
    try:
        spd = float((gps_row or {}).get('speed_kmh') or 0)
    except (TypeError, ValueError):
        spd = 0.0
    if spd > 5:
        return 'HAREKETLI'
    if spd >= 0 and (gps_row or {}).get('speed_kmh') is not None:
        return 'DURAN'
    return 'BILINMIYOR'


def _plan_has_trip_start_events(plan_id: int, plan_date: str) -> bool:
    from modules.planlama.arac_takip_repo import get_conn, tablo_var_mi
    if not tablo_var_mi('arac_plan_olay'):
        return False
    placeholders = ','.join('?' * len(_TRIP_START_EVENTS))
    con = get_conn()
    try:
        row = con.execute(
            f"""
            SELECT 1 FROM arac_plan_olay
            WHERE plan_id=? AND date(olay_zamani)=?
              AND olay_turu IN ({placeholders})
            LIMIT 1
            """,
            (int(plan_id), plan_date, *_TRIP_START_EVENTS),
        ).fetchone()
        return bool(row)
    finally:
        con.close()


def _is_trip_started(
    plan_date: str,
    plan_id: int | None,
    vehicle_items: list[dict],
    route_state: str | None,
    *,
    local_today,
) -> bool:
    """Verified trip start — cikis_saati alone or GPS speed does NOT qualify."""
    if plan_date != local_today.isoformat():
        return False
    for it in vehicle_items:
        if not _is_active_plan_item(it):
            continue
        if (it.get('status') or '').upper() == 'BASLADI':
            return True
        if (it.get('visit_state') or 'OUTSIDE') in ('ARRIVED', 'DEPARTED_PENDING'):
            return True
    if (route_state or '') in _ACTIVE_ROUTE_STATES:
        return True
    if plan_id and _plan_has_trip_start_events(int(plan_id), plan_date):
        return True
    return False


def _is_approaching_stop(gps_row: dict | None, item: dict | None) -> bool:
    if not gps_row or not item:
        return False
    try:
        lat = float(gps_row['latitude'])
        lng = float(gps_row['longitude'])
        slat = float(item['latitude'])
        slng = float(item['longitude'])
    except (KeyError, TypeError, ValueError):
        return False
    from modules.planlama.arac_geo_distance import haversine_m
    return haversine_m(lat, lng, slat, slng) <= APPROACHING_M


def _past_plan_trip_status(vehicle_items: list[dict]) -> str:
    active = [it for it in vehicle_items if _is_active_plan_item(it)]
    if active and all((it.get('status') or '').upper() == 'TAMAMLANDI' for it in active):
        return 'TAMAMLANDI'
    for it in active:
        vs = it.get('visit_state') or 'OUTSIDE'
        st = (it.get('status') or '').upper()
        if vs == 'DEPARTED_PENDING' and st != 'TAMAMLANDI':
            return 'SONUC_BEKLIYOR'
    for it in active:
        if (it.get('visit_state') or '') == 'ARRIVED':
            return 'VARILDI'
    for it in active:
        if (it.get('status') or '').upper() == 'BASLADI':
            return 'YOLDA'
    return 'PLANLANDI'


def _item_is_late(item: dict, plan_date: str, now: datetime) -> bool:
    pt = item.get('planned_time')
    st = (item.get('status') or 'PLANLANDI').upper()
    if not pt or st not in ('PLANLANDI', 'BASLADI'):
        return False
    try:
        planned_dt = datetime.strptime(f'{plan_date} {pt[:5]}', '%Y-%m-%d %H:%M')
    except ValueError:
        return False
    return planned_dt < now - timedelta(minutes=15)


def _compute_item_plan_trip_status(
    plan_date: str,
    *,
    local_today,
    trip_started: bool,
    item: dict,
    vehicle_physical: str,
    now: datetime,
) -> tuple[str, str]:
    pd = _parse_plan_date(plan_date)
    if pd > local_today:
        return 'PLANLANDI', 'FUTURE_PLAN'
    if pd < local_today:
        st = (item.get('status') or 'PLANLANDI').upper()
        vs = item.get('visit_state') or 'OUTSIDE'
        if st == 'TAMAMLANDI':
            return 'TAMAMLANDI', 'PAST_PLAN'
        if vs == 'DEPARTED_PENDING':
            return 'SONUC_BEKLIYOR', 'PAST_PLAN'
        if vs == 'ARRIVED':
            return 'VARILDI', 'PAST_PLAN'
        if st == 'BASLADI':
            return 'YOLDA', 'PAST_PLAN'
        return 'PLANLANDI', 'PAST_PLAN'
    st = (item.get('status') or 'PLANLANDI').upper()
    if st == 'TAMAMLANDI':
        return 'TAMAMLANDI', 'ITEM_COMPLETE'
    if not trip_started:
        return 'PLANLANDI', 'DEPARTURE_NOT_STARTED'
    vs = item.get('visit_state') or 'OUTSIDE'
    if vs == 'DEPARTED_PENDING':
        return 'SONUC_BEKLIYOR', 'VISIT_DEPARTED'
    if vs == 'ARRIVED':
        return 'VARILDI', 'VISIT_ARRIVED'
    if _item_is_late(item, plan_date, now):
        return 'GECIKIYOR', 'PLANNED_TIME_PASSED'
    if st in ('BASLADI', 'YOLDA'):
        return 'YOLDA', 'ITEM_STARTED'
    if vs == 'OUTSIDE' and vehicle_physical == 'HAREKETLI':
        return 'YOLDA', 'EN_ROUTE'
    return 'PLANLANDI', 'TRIP_STARTED_WAITING'


def _pick_approach_target(vehicle_items: list[dict], next_item: dict | None) -> dict | None:
    """Next stop with coordinates for proximity check."""
    active = [it for it in vehicle_items if _is_active_plan_item(it)]
    for it in active:
        if (it.get('visit_state') or 'OUTSIDE') != 'OUTSIDE':
            continue
        if it.get('latitude') is not None and it.get('longitude') is not None:
            return it
    if next_item and next_item.get('latitude') is not None and next_item.get('longitude') is not None:
        return next_item
    return None


def _compute_vehicle_plan_trip_status(
    plan_date: str,
    *,
    local_today,
    trip_started: bool,
    vehicle_items: list[dict],
    vehicle_physical: str,
    gps_row: dict | None,
    next_item: dict | None,
    now: datetime,
) -> tuple[str, bool, str]:
    pd = _parse_plan_date(plan_date)
    if pd > local_today:
        return 'PLANLANDI', False, 'FUTURE_PLAN'
    if pd < local_today:
        return _past_plan_trip_status(vehicle_items), False, 'PAST_PLAN'

    active = [it for it in vehicle_items if _is_active_plan_item(it)]
    if active and all((it.get('status') or '').upper() == 'TAMAMLANDI' for it in active):
        return 'TAMAMLANDI', True, 'ALL_COMPLETE'

    if not trip_started:
        return 'PLANLANDI', False, 'DEPARTURE_NOT_STARTED'

    if any(
        (it.get('visit_state') or '') == 'DEPARTED_PENDING'
        and (it.get('status') or '').upper() != 'TAMAMLANDI'
        for it in active
    ):
        return 'SONUC_BEKLIYOR', True, 'VISIT_RESULT_PENDING'

    if any((it.get('visit_state') or '') == 'ARRIVED' for it in active):
        return 'VARILDI', True, 'AT_STOP'

    approach_target = _pick_approach_target(vehicle_items, next_item)
    if _is_approaching_stop(gps_row, approach_target):
        return 'KONUMA_YAKLASIYOR', True, 'APPROACHING'

    if any(_item_is_late(it, plan_date, now) for it in active):
        return 'GECIKIYOR', True, 'PLANNED_TIME_PASSED'

    if vehicle_physical == 'HAREKETLI':
        return 'YOLDA', True, 'GPS_MOVING'

    if any((it.get('status') or '').upper() in ('BASLADI', 'YOLDA') for it in active):
        return 'YOLDA', True, 'ITEMS_STARTED'

    return 'PLANLANDI', True, 'TRIP_STARTED_IDLE'


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


def _gps_reference_now(vehicle_row: dict | None, fallback: datetime) -> datetime:
    """R05: in-stop dwell display uses freshest GPS timestamp, not wall clock."""
    if not vehicle_row:
        return fallback
    lg = vehicle_row.get('latest_gps') or {}
    ts = lg.get('gps_timestamp') or vehicle_row.get('gps_timestamp') or vehicle_row.get('gps_last_seen_at')
    dt = parse_gps_timestamp(str(ts or ''))
    return dt if dt else fallback


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


_ALERT_TYPE_PRIORITY = {
    'OUT_OF_SEQUENCE_VISIT': 0,
    'AMBIGUOUS_STOP': 1,
    'STOP_OVERSTAY': 2,
    'ROUTE_DEVIATION': 3,
    'VISIT_RESULT_PENDING': 4,
    'GPS_STALE': 5,
    'PLANNED_TIME_PASSED': 6,
    'NO_ROUTE': 8,
    'MISSING_LOCATION': 9,
    'UNASSIGNED_VEHICLE': 9,
}
_ALERT_SEVERITY_RANK = {'danger': 0, 'warning': 1, 'info': 2}


def _sort_alerts_for_display(alerts: list[dict]) -> list[dict]:
    """R13: sıra dışı ziyaret uyarısı her zaman üstte görünsün."""

    def _key(a: dict) -> tuple:
        t = a.get('type') or ''
        return (
            _ALERT_TYPE_PRIORITY.get(t, 50),
            _ALERT_SEVERITY_RANK.get(a.get('severity') or 'info', 9),
        )

    return sorted(alerts, key=_key)


def _vehicle_gps_by_id(vehicles: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for v in vehicles:
        vid = str(v.get('arac_external_id') or '')
        if not vid:
            continue
        gps = v.get('latest_gps')
        if isinstance(gps, dict) and gps.get('gps_timestamp'):
            out[vid] = gps
            continue
        ts = v.get('gps_timestamp') or v.get('gps_last_seen_at')
        if ts:
            out[vid] = {
                'gps_timestamp': ts,
                'latitude': v.get('latitude'),
                'longitude': v.get('longitude'),
                'speed_kmh': v.get('speed_kmh'),
                'activity_status': v.get('activity_status'),
                'is_stale': v.get('gps_is_stale') or v.get('gps_stale'),
            }
    return out


def _gps_has_valid_coords(gps_row: dict | None) -> bool:
    if not gps_row:
        return False
    lat, lon = gps_row.get('latitude'), gps_row.get('longitude')
    if lat is None or lon is None:
        return False
    try:
        float(lat)
        float(lon)
    except (TypeError, ValueError):
        return False
    return True


def _vehicle_is_moving(gps_row: dict | None) -> bool:
    if not gps_row:
        return False
    act = str(gps_row.get('activity_status') or '').upper()
    if act in ('HAREKETLI', 'MOVING'):
        return True
    try:
        spd = float(gps_row.get('speed_kmh') or 0)
    except (TypeError, ValueError):
        spd = 0.0
    return spd > STOP_OVERSTAY_MOVING_SPEED_KMH


def _stop_overstay_elapsed_seconds(
    arrived_at: str | None,
    gps_timestamp: str | None,
) -> int | None:
    if not arrived_at or not gps_timestamp:
        return None
    start_dt = parse_gps_timestamp(arrived_at)
    end_dt = parse_gps_timestamp(gps_timestamp)
    if not start_dt or not end_dt:
        return None
    if end_dt < start_dt:
        return None
    return max(0, int((end_dt - start_dt).total_seconds()))


def _stop_overstay_alert_id(vehicle_id: str, plan_item_id: int | str, arrived_at: str) -> str:
    return f'STOP_OVERSTAY:{vehicle_id}:{plan_item_id}:{arrived_at}'


def _build_stop_overstay_alert(
    *,
    item: dict,
    vehicle: dict | None,
    elapsed_seconds: int,
    gps_timestamp: str,
) -> dict:
    plate = (
        (vehicle or {}).get('plate')
        or item.get('plate')
        or item.get('arac_plaka_snapshot')
        or '—'
    )
    company = item.get('company_name') or item.get('job_title') or '—'
    minutes = max(1, elapsed_seconds // 60)
    plan_item_id = item.get('plan_item_id')
    vid = str(item.get('arac_external_id') or '')
    arrived_at = item.get('arrived_at') or ''
    return {
        'type': STOP_OVERSTAY_ALERT_TYPE,
        'severity': 'warning',
        'title': 'Durakta bekleme',
        'message': f'{plate} — {company} durağında {minutes} dakikadır bekliyor.',
        'vehicle_id': vid,
        'plan_id': (vehicle or {}).get('plan_id') or item.get('plan_id'),
        'plan_item_id': plan_item_id,
        'alert_id': _stop_overstay_alert_id(vid, plan_item_id, arrived_at),
        'overstay_seconds': elapsed_seconds,
        'geofence_entry_at': arrived_at,
        'gps_timestamp': gps_timestamp,
        'action': 'inspect',
    }


def _collect_stop_overstay_alerts(
    vehicles: list[dict],
    items: list[dict],
    *,
    now: datetime | None = None,
) -> list[dict]:
    """R05: geofence ARRIVED + fresh GPS timestamp elapsed >= 600s."""
    now = now or datetime.now()
    gps_by_vehicle = _vehicle_gps_by_id(vehicles)
    vehicle_by_id = {str(v.get('arac_external_id') or ''): v for v in vehicles if v.get('arac_external_id')}
    alerts: list[dict] = []
    seen_ids: set[str] = set()

    for item in items:
        if not _is_active_plan_item(item):
            continue
        item_status = (item.get('status') or '').upper()
        if item_status == 'TAMAMLANDI':
            continue
        if item.get('visit_state') != 'ARRIVED':
            continue
        arrived_at = item.get('arrived_at')
        if not arrived_at:
            continue
        vid = str(item.get('arac_external_id') or '')
        gps_row = gps_by_vehicle.get(vid)
        if not gps_row or _gps_stale(gps_row, now):
            continue
        if not _gps_has_valid_coords(gps_row):
            continue
        if _vehicle_is_moving(gps_row):
            continue
        gps_ts = str(gps_row.get('gps_timestamp') or '')
        elapsed = _stop_overstay_elapsed_seconds(arrived_at, gps_ts)
        if elapsed is None or elapsed < STOP_OVERSTAY_THRESHOLD_SECONDS:
            continue
        alert = _build_stop_overstay_alert(
            item=item,
            vehicle=vehicle_by_id.get(vid),
            elapsed_seconds=elapsed,
            gps_timestamp=gps_ts,
        )
        aid = alert.get('alert_id')
        if aid and aid in seen_ids:
            continue
        if aid:
            seen_ids.add(aid)
        alerts.append(alert)
    return alerts


def _resolve_out_of_sequence_alert_plate(oos: dict, vehicles: list[dict]) -> str:
    """Günlük uyarı: metadata plate yoksa veya vehicle_id ise plan plakasını kullan."""
    vid = str(oos.get('vehicle_id') or '')
    raw = (oos.get('plate') or '').strip()
    if raw and raw != vid:
        return raw
    pid = oos.get('plan_id')
    for v in vehicles:
        if str(v.get('arac_external_id') or '') != vid:
            continue
        if pid is not None and v.get('plan_id') is not None and int(v['plan_id']) != int(pid):
            continue
        snap = (v.get('plate') or v.get('arac_plaka_snapshot') or '').strip()
        if snap:
            return snap
    return raw or vid or '—'


def _primary_plan_item_for_vehicle(items: list[dict], vehicle_id: str) -> int | None:
    """First actionable plan row for alert → Planı Değiştir navigation."""
    vid = str(vehicle_id or '')
    if not vid:
        return None
    active = [
        it for it in items
        if str(it.get('arac_external_id') or '') == vid
        and _is_active_plan_item(it)
        and it.get('plan_item_id') is not None
    ]
    if not active:
        return None

    def _sort_key(it: dict) -> tuple:
        st = (it.get('status') or '').upper()
        pri = 0 if st == 'BASLADI' else 1
        return (pri, it.get('sira') or 9999, int(it['plan_item_id']))

    active.sort(key=_sort_key)
    return int(active[0]['plan_item_id'])


def _filter_alerts_for_vehicle(alerts: list[dict], vehicle_id: str | None) -> list[dict]:
    if not vehicle_id:
        return alerts
    vid = str(vehicle_id)
    out: list[dict] = []
    for alert in alerts:
        av = alert.get('vehicle_id')
        if av is not None and str(av) != vid:
            continue
        out.append(alert)
    return out


def _build_alerts(
    plan_date: str,
    vehicles: list[dict],
    items: list[dict],
    filom_by_id: dict[str, dict],
    *,
    vehicle_id: str | None = None,
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
            stale_alert = {
                'type': 'GPS_STALE',
                'severity': 'warning',
                'message': f"{v.get('plate') or v.get('arac_plaka_snapshot')} — GPS verisi eski",
                'vehicle_id': vid,
                'plan_id': v.get('plan_id'),
            }
            plan_item_id = _primary_plan_item_for_vehicle(items, vid)
            if plan_item_id is not None:
                stale_alert['plan_item_id'] = plan_item_id
            alerts.append(stale_alert)

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
                'vehicle_id': item.get('arac_external_id'),
            })
        if not item.get('arac_external_id'):
            alerts.append({
                'type': 'UNASSIGNED_VEHICLE',
                'severity': 'info',
                'message': f"{item.get('company_name')} — araç atanmamış",
                'plan_item_id': item.get('plan_item_id'),
                'vehicle_id': item.get('arac_external_id'),
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
                        'vehicle_id': item.get('arac_external_id'),
                    })
            except ValueError:
                pass

    # Ambiguous stop events today
    if geofence_tables_ready():
        from modules.planlama.arac_geofence_repo import list_out_of_sequence_visit_alerts_for_date
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

        for oos in list_out_of_sequence_visit_alerts_for_date(plan_date):
            plate = _resolve_out_of_sequence_alert_plate(oos, vehicles)
            expected = oos.get('expected_stop') or '—'
            actual = oos.get('actual_stop') or '—'
            when = oos.get('olay_zamani') or ''
            result = oos.get('result') or 'TAMAMLANDI'
            alerts.append({
                'type': 'OUT_OF_SEQUENCE_VISIT',
                'severity': 'warning',
                'title': 'Sıra dışı ziyaret',
                'message': oos.get('message') or (
                    f"{plate}: planlanan {expected} yerine {actual} ziyaret edildi."
                ),
                'plate': plate,
                'expected_stop': expected,
                'actual_stop': actual,
                'expected_item_id': oos.get('expected_item_id'),
                'actual_item_id': oos.get('actual_item_id'),
                'olay_zamani': when,
                'result': result,
                'vehicle_id': oos.get('vehicle_id'),
                'plan_id': oos.get('plan_id'),
                'plan_item_id': oos.get('plan_item_id'),
                'event_id': oos.get('event_id'),
                'action': 'acknowledge',
            })

    alerts.extend(_collect_stop_overstay_alerts(vehicles, items, now=now))

    return _sort_alerts_for_display(_filter_alerts_for_vehicle(alerts, vehicle_id))


_MOVING_KPI_STATUSES = frozenset({'YOLDA', 'KONUMA_YAKLASIYOR'})


def _compute_plan_kpi(
    plan_date: str,
    *,
    local_today,
    vehicles: list[dict],
) -> tuple[int, int]:
    """Canonical Aktif Araç / Hareket Halinde — ATP_LIVE_STATUS_V1."""
    pd = _parse_plan_date(plan_date)
    if pd > local_today:
        return 0, 0

    active_vids: set[str] = set()
    moving_vids: set[str] = set()
    for v in vehicles:
        vid = str(v.get('arac_external_id') or '')
        if not vid:
            continue
        pts = (v.get('plan_trip_status') or 'PLANLANDI').upper()
        if pts != 'TAMAMLANDI':
            active_vids.add(vid)
        if pd == local_today:
            if v.get('trip_started') and pts in _MOVING_KPI_STATUSES:
                moving_vids.add(vid)
        elif pts in _MOVING_KPI_STATUSES:
            moving_vids.add(vid)
    return len(active_vids), len(moving_vids)


def get_today_vehicle_operations(
    plan_date: str,
    *,
    filom_payload: dict | None = None,
    vehicle_id: str | None = None,
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

    _gps_ready = gps_tables_ready()
    local_today = now.date()
    vehicles_out: list[dict] = []
    map_vehicles: list[dict] = []
    stale_count = 0

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
    trip_started_by_vid: dict[str, bool] = {}

    for plan_v in aggregate.get('vehicles') or []:
        vid = str(plan_v.get('arac_external_id') or '')
        plan_id = plan_v.get('plan_id')
        filom = filom_by_id.get(vid)
        gps_db = get_latest_gps_snapshot(vid) if _gps_ready else None
        selection = select_freshest_gps_source(filom, gps_db, now=now)
        gps_row = selection.get('gps_row')
        gps_bundle = selection.get('bundle') or {}
        stale = bool(gps_bundle.get('gps_is_stale'))
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

        vehicle_physical = _resolve_vehicle_physical_status(
            gps_row if isinstance(gps_row, dict) else None,
            filom=filom,
            gps_db=gps_db if isinstance(gps_db, dict) else None,
            stale=stale,
        )
        physical = _physical_status_alias(vehicle_physical)

        vid_items = [
            it for it in active_items_out
            if str(it.get('arac_external_id') or '') == vid
        ]
        trip_started = _is_trip_started(
            plan_date, plan_id, vid_items, route_state, local_today=local_today,
        )
        trip_started_by_vid[vid] = trip_started
        next_item = plan_v.get('next_item')
        plan_trip_status, trip_started_flag, status_reason = _compute_vehicle_plan_trip_status(
            plan_date,
            local_today=local_today,
            trip_started=trip_started,
            vehicle_items=vid_items,
            vehicle_physical=vehicle_physical,
            gps_row=gps_row if isinstance(gps_row, dict) else None,
            next_item=next_item,
            now=now,
        )

        gps_age = _gps_age_seconds(gps_row if isinstance(gps_row, dict) else None, now)
        vehicle_row = {
            'plan_id': plan_id,
            'arac_external_id': vid,
            'latest_gps': gps_row if isinstance(gps_row, dict) else None,
            'plate': plan_v.get('arac_plaka_snapshot'),
            'driver': plan_v.get('sofor_adi_snapshot'),
            'driver_name': plan_v.get('sofor_adi_snapshot'),
            'cikis_saati': plan_v.get('cikis_saati'),
            'departure_time': plan_v.get('cikis_saati'),
            'progress_completed': plan_v.get('progress_completed', 0),
            'progress_total': plan_v.get('progress_total', 0),
            'progress_label': plan_v.get('progress_label', '0/0'),
            'next_stop': plan_v.get('next_stop_label') or (next_item or {}).get('company_name'),
            'next_stop_label': plan_v.get('next_stop_label'),
            'next_order_no': plan_v.get('next_order_no'),
            'next_display_order_no': plan_v.get('next_display_order_no'),
            'next_time': plan_v.get('next_time'),
            'next_eta_time': (next_item or {}).get('tahmini_varis_saati') or (next_item or {}).get('eta_time'),
            'eta_is_traffic_free': True,
            'eta_honesty_note': (
                'Tahmini varış trafiksizdir; canlı trafik dahil değildir.'
                if ((next_item or {}).get('tahmini_varis_saati') or (next_item or {}).get('eta_time'))
                else None
            ),
            'vehicle_physical_status': vehicle_physical,
            'vehicle_physical_label': VEHICLE_PHYSICAL_LABELS.get(
                vehicle_physical, VEHICLE_PHYSICAL_LABELS['BILINMIYOR'],
            ),
            'plan_trip_status': plan_trip_status,
            'plan_trip_status_label': PLAN_TRIP_STATUS_LABELS.get(
                plan_trip_status, plan_trip_status,
            ),
            'trip_started': trip_started_flag,
            'status_reason': status_reason,
            'physical_status': physical,
            'route_state': route_state,
            'route_status_label': _route_status_label(route_state, deviation_m),
            'current_deviation_m': deviation_m,
            'deviation_m': deviation_m,
            'max_deviation_m': max_deviation_m,
            'deviation_started_at': deviation_started_at,
            'gps_age_seconds': gps_age,
        }
        vehicles_out.append(apply_gps_bundle_to_vehicle(vehicle_row, selection))

        if gps_row and isinstance(gps_row, dict) and gps_row.get('latitude') is not None:
            map_vehicles.append({
                'id': vid,
                'plate': plan_v.get('arac_plaka_snapshot'),
                'lat': float(gps_row['latitude']),
                'lng': float(gps_row['longitude']),
                'stale': stale,
                'selected': False,
            })

    vehicle_by_id = {str(v.get('arac_external_id') or ''): v for v in vehicles_out if v.get('arac_external_id')}

    for it in items_out:
        plan_is_id = it.get('plan_item_id')
        visit = get_visit_state(int(plan_is_id)) if geofence_tables_ready() and plan_is_id else None
        item_vid = str(it.get('arac_external_id') or '')
        ref_now = _gps_reference_now(vehicle_by_id.get(item_vid), now)
        it['dwell_minutes'] = _dwell_minutes(
            it.get('arrived_at'), it.get('departed_at'),
            now=ref_now,
            stored_seconds=(visit or {}).get('dwell_seconds'),
        )
        it['visit_label'] = _build_visit_label(visit, item=it, now=ref_now)

    vehicle_physical_by_vid = {
        str(v.get('arac_external_id') or ''): v.get('vehicle_physical_status', 'BILINMIYOR')
        for v in vehicles_out
    }
    for it in active_items_out:
        vid = str(it.get('arac_external_id') or '')
        vphys = vehicle_physical_by_vid.get(vid, 'BILINMIYOR')
        started = trip_started_by_vid.get(vid, False)
        pts, reason = _compute_item_plan_trip_status(
            plan_date,
            local_today=local_today,
            trip_started=started,
            item=it,
            vehicle_physical=vphys,
            now=now,
        )
        it['plan_trip_status'] = pts
        it['plan_trip_status_label'] = PLAN_TRIP_STATUS_LABELS.get(pts, pts)
        it['status_reason'] = reason
        it['trip_started'] = started and plan_date == local_today.isoformat()

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
        1 for a in _build_alerts(
            plan_date, vehicles_out, active_items_out, filom_by_id, vehicle_id=vehicle_id,
        )
        if a.get('severity') in ('warning', 'danger')
    )

    aktif_arac, hareket_halinde = _compute_plan_kpi(
        plan_date, local_today=local_today, vehicles=vehicles_out,
    )

    kpi = {
        'aktif_arac': aktif_arac,
        'aktif_arac_source': 'canonical_plan_trip',
        'hareket_halinde': hareket_halinde,
        'hareket_source': 'canonical_plan_trip',
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

    alerts = _build_alerts(
        plan_date, vehicles_out, active_items_out, filom_by_id, vehicle_id=vehicle_id,
    )
    normal_message = 'Bugünkü plan normal ilerliyor' if not alerts else None

    return {
        'ok': True,
        'plan_date': plan_date,
        'status_contract_version': STATUS_CONTRACT_VERSION,
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

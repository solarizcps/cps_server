# -*- coding: utf-8 -*-
"""
Araç GPS P1 — Filom DTO → snapshot, dedup, poll_once contract.

Retention (spec only — job not implemented this phase):
- Raw GPS snapshot: 90 days
- Daily route summary + olaylar: permanent

Polling interval (spec — live scheduler blocked until Filom rate limit confirmed):
- Pilot default: 60 seconds single interval
- Target adaptive: moving 30–60s, parked 2–5 min (future)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Callable

from modules.planlama.arac_gps_snapshot_repo import get_max_gps_snapshot_id, gps_tables_ready, insert_gps_snapshot
from modules.planlama.arac_takip_repo import PLAN_PROVIDER_FILOM

# Assumed local wall time (Filom posTimestamp has no TZ suffix; sample aligns with TR).
GPS_TIMESTAMP_FMT = '%Y-%m-%d %H:%M:%S'
FUTURE_TOLERANCE = timedelta(minutes=5)
STALE_AGE = timedelta(hours=6)
RETENTION_DAYS_RAW_SNAPSHOT = 90


def make_dedup_key(
    gps_timestamp: str,
    latitude: float,
    longitude: float,
) -> str:
    payload = f'{gps_timestamp}|{latitude:.6f}|{longitude:.6f}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


def parse_gps_timestamp(raw: str) -> datetime | None:
    text = (raw or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, GPS_TIMESTAMP_FMT)
    except ValueError:
        return None


def is_valid_coordinate(lat: Any, lon: Any) -> bool:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if la == 0.0 and lo == 0.0:
        return False
    return -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0


def evaluate_stale(
    *,
    adapter_stale: bool,
    gps_dt: datetime | None,
    now: datetime,
) -> bool:
    if adapter_stale:
        return True
    if gps_dt is None:
        return True
    return (now - gps_dt) > STALE_AGE


def vehicle_dto_to_snapshot_row(
    vehicle: dict,
    *,
    received_at: str,
    created_at: str,
    now: datetime | None = None,
) -> tuple[dict | None, str | None]:
    """Map normalized Filom vehicle DTO → DB row or rejection reason."""
    now = now or datetime.now()
    ext_id = str(vehicle.get('id') or '').strip()
    if not ext_id:
        return None, 'missing_external_id'

    lat = vehicle.get('latitude')
    lon = vehicle.get('longitude')
    if not vehicle.get('has_valid_location') or not is_valid_coordinate(lat, lon):
        return None, 'invalid_coordinates'

    gps_raw = vehicle.get('last_seen_at') or ''
    gps_dt = parse_gps_timestamp(gps_raw)
    if gps_dt is None:
        return None, 'missing_gps_timestamp'

    if gps_dt > now + FUTURE_TOLERANCE:
        return None, 'future_gps_timestamp'

    is_stale = evaluate_stale(
        adapter_stale=bool(vehicle.get('is_stale_data')),
        gps_dt=gps_dt,
        now=now,
    )

    la, lo = float(lat), float(lon)
    gps_iso = gps_dt.strftime(GPS_TIMESTAMP_FMT)
    return {
        'arac_provider': PLAN_PROVIDER_FILOM,
        'arac_external_id': ext_id,
        'plate_snapshot': vehicle.get('plate_display') or vehicle.get('plate'),
        'gps_timestamp': gps_iso,
        'received_at': received_at,
        'latitude': la,
        'longitude': lo,
        'speed_kmh': vehicle.get('speed_kmh'),
        'activity_status': vehicle.get('activity_status'),
        'ignition_status': vehicle.get('ignition'),
        'odometer_km': vehicle.get('total_distance_km'),
        'is_stale': is_stale,
        'dedup_key': make_dedup_key(gps_iso, la, lo),
        'created_at': created_at,
    }, None


def persist_vehicle_snapshot(vehicle: dict, *, now: datetime | None = None) -> dict:
    """Persist one vehicle; never raises — per-vehicle result dict."""
    now = now or datetime.now()
    received_at = now.strftime(GPS_TIMESTAMP_FMT)
    row, reject = vehicle_dto_to_snapshot_row(
        vehicle, received_at=received_at, created_at=received_at, now=now,
    )
    if reject:
        return {
            'vehicle_id': vehicle.get('id'),
            'status': 'rejected',
            'reason': reject,
        }
    result = insert_gps_snapshot(row)
    return {
        'vehicle_id': row['arac_external_id'],
        'status': result,
        'is_stale': row['is_stale'],
        'gps_timestamp': row['gps_timestamp'],
    }


def poll_once(
    live_fetcher: Callable[[], dict] | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """
    Single poll cycle — no loop, no scheduler.

    Contract:
        {
          ok: bool,
          polled_at: str,
          vehicles_total: int,
          inserted: int,
          skipped_dedup: int,
          rejected: int,
          stale_marked: int,
          errors: list,
          per_vehicle: list,
          fetch_error: str | None,
        }
    """
    if not gps_tables_ready():
        return {
            'ok': False,
            'polled_at': '',
            'vehicles_total': 0,
            'inserted': 0,
            'skipped_dedup': 0,
            'rejected': 0,
            'stale_marked': 0,
            'errors': [{'reason': 'gps_tables_not_ready'}],
            'per_vehicle': [],
            'fetch_error': 'gps_tables_not_ready',
        }

    now = now or datetime.now()
    polled_at = now.strftime(GPS_TIMESTAMP_FMT)
    before_max_id = get_max_gps_snapshot_id()

    if live_fetcher is None:
        from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import get_live_vehicles
        live_fetcher = get_live_vehicles

    try:
        payload = live_fetcher()
    except Exception as exc:
        return {
            'ok': False,
            'polled_at': polled_at,
            'vehicles_total': 0,
            'inserted': 0,
            'skipped_dedup': 0,
            'rejected': 0,
            'stale_marked': 0,
            'errors': [{'reason': 'fetch_exception', 'detail': exc.__class__.__name__}],
            'per_vehicle': [],
            'fetch_error': exc.__class__.__name__,
        }

    if not payload.get('ok'):
        return {
            'ok': False,
            'polled_at': polled_at,
            'vehicles_total': 0,
            'inserted': 0,
            'skipped_dedup': 0,
            'rejected': 0,
            'stale_marked': 0,
            'errors': [{
                'reason': payload.get('error_category') or 'fetch_failed',
                'detail': payload.get('error'),
            }],
            'per_vehicle': [],
            'fetch_error': payload.get('error'),
        }

    vehicles = payload.get('vehicles') or []
    inserted = skipped = rejected = stale_marked = 0
    per_vehicle: list[dict] = []
    errors: list[dict] = []

    for v in vehicles:
        outcome = persist_vehicle_snapshot(v, now=now)
        per_vehicle.append(outcome)
        st = outcome.get('status')
        if st == 'inserted':
            inserted += 1
            if outcome.get('is_stale'):
                stale_marked += 1
        elif st == 'dedup':
            skipped += 1
        elif st == 'rejected':
            rejected += 1
            errors.append({
                'vehicle_id': outcome.get('vehicle_id'),
                'reason': outcome.get('reason'),
            })

    return {
        'ok': True,
        'polled_at': polled_at,
        'vehicles_total': len(vehicles),
        'inserted': inserted,
        'skipped_dedup': skipped,
        'rejected': rejected,
        'stale_marked': stale_marked,
        'errors': errors,
        'per_vehicle': per_vehicle,
        'fetch_error': None,
        'deviation': _run_deviation_pass(before_max_id),
    }


def _run_deviation_pass(since_id: int = 0) -> dict:
    try:
        from modules.planlama.arac_rota_deviation_service import process_new_snapshots_since
        from modules.planlama.arac_rota_deviation_repo import deviation_tables_ready
        if not deviation_tables_ready():
            return {'skipped': True, 'reason': 'deviation_tables_not_ready'}
        return process_new_snapshots_since(since_id)
    except Exception as exc:
        return {'ok': False, 'error': exc.__class__.__name__}

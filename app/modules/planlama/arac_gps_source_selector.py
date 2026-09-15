# -*- coding: utf-8 -*-
"""GPS source freshness — atomic Filom vs SQLite bundle selection."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from modules.planlama.arac_gps_poll_service import STALE_AGE, evaluate_stale, is_valid_coordinate, parse_gps_timestamp

SOURCE_FILOM = 'filom'
SOURCE_SQLITE = 'sqlite'


def _ts_rank(raw: str | None) -> float:
    dt = parse_gps_timestamp(str(raw or '').strip())
    return dt.timestamp() if dt else float('-inf')


def _has_coords(lat: Any, lon: Any) -> bool:
    return is_valid_coordinate(lat, lon)


def _filom_adapter_stale(filom: dict) -> bool:
    return bool(filom.get('is_stale_data'))


def _sqlite_adapter_stale(row: dict) -> bool:
    return bool(row.get('is_stale'))


def extract_filom_gps_bundle(filom: dict | None) -> dict[str, Any] | None:
    if not filom:
        return None
    ts = (filom.get('last_seen_at') or '').strip()
    if not ts and not _has_coords(filom.get('latitude'), filom.get('longitude')):
        return None
    return {
        'source': SOURCE_FILOM,
        'latitude': filom.get('latitude'),
        'longitude': filom.get('longitude'),
        'speed_kmh': filom.get('speed_kmh'),
        'activity_status': filom.get('activity_status'),
        'activity_status_label': filom.get('activity_status_label'),
        'ignition': filom.get('ignition'),
        'address': filom.get('address'),
        'total_distance_km': filom.get('total_distance_km'),
        'has_valid_location': bool(filom.get('has_valid_location'))
        if filom.get('has_valid_location') is not None
        else _has_coords(filom.get('latitude'), filom.get('longitude')),
        'gps_timestamp': ts or None,
        'last_seen_at': ts or None,
        'last_seen_label': filom.get('last_seen_label'),
        'adapter_stale': _filom_adapter_stale(filom),
    }


def extract_sqlite_gps_bundle(gps_db: dict | None) -> dict[str, Any] | None:
    if not gps_db:
        return None
    ts = (gps_db.get('gps_timestamp') or '').strip()
    if not ts and not _has_coords(gps_db.get('latitude'), gps_db.get('longitude')):
        return None
    ignition = gps_db.get('ignition_status')
    return {
        'source': SOURCE_SQLITE,
        'latitude': gps_db.get('latitude'),
        'longitude': gps_db.get('longitude'),
        'speed_kmh': gps_db.get('speed_kmh'),
        'activity_status': gps_db.get('activity_status'),
        'activity_status_label': gps_db.get('activity_status'),
        'ignition': ignition,
        'address': None,
        'total_distance_km': gps_db.get('odometer_km'),
        'has_valid_location': _has_coords(gps_db.get('latitude'), gps_db.get('longitude')),
        'gps_timestamp': ts or None,
        'last_seen_at': ts or None,
        'last_seen_label': None,
        'adapter_stale': _sqlite_adapter_stale(gps_db),
        'latest_gps': dict(gps_db),
    }


def extract_sqlite_gps_bundle_from_ops(ops: dict | None) -> dict[str, Any] | None:
    if not ops:
        return None
    if ops.get('latest_gps') and isinstance(ops['latest_gps'], dict):
        return extract_sqlite_gps_bundle(ops['latest_gps'])
    if ops.get('gps_source') == SOURCE_SQLITE or ops.get('gps_timestamp'):
        return extract_sqlite_gps_bundle({
            'gps_timestamp': ops.get('gps_timestamp') or ops.get('gps_last_seen_at'),
            'latitude': ops.get('latitude'),
            'longitude': ops.get('longitude'),
            'speed_kmh': ops.get('speed_kmh'),
            'activity_status': ops.get('activity_status'),
            'ignition_status': ops.get('ignition'),
            'odometer_km': ops.get('total_distance_km'),
            'is_stale': ops.get('gps_is_stale') or ops.get('gps_stale'),
        })
    return None


def _candidate_rank(bundle: dict, *, source_priority: int) -> tuple:
    ts = _ts_rank(bundle.get('gps_timestamp'))
    return (
        ts,
        1 if bundle.get('has_valid_location') else 0,
        0 if bundle.get('adapter_stale') else 1,
        source_priority,
    )


def select_freshest_gps_source(
    filom: dict | None,
    sqlite_gps: dict | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Pick atomic GPS bundle from Filom DTO and/or SQLite snapshot row.
    Returns {source, bundle, gps_row, rank_meta}.
    """
    now = now or datetime.now()
    filom_bundle = extract_filom_gps_bundle(filom)
    sqlite_bundle = extract_sqlite_gps_bundle(sqlite_gps)

    candidates: list[tuple[tuple, dict]] = []
    if filom_bundle:
        candidates.append((_candidate_rank(filom_bundle, source_priority=1), filom_bundle))
    if sqlite_bundle:
        candidates.append((_candidate_rank(sqlite_bundle, source_priority=0), sqlite_bundle))

    if not candidates:
        return {'source': None, 'bundle': None, 'gps_row': None}

    candidates.sort(key=lambda item: item[0], reverse=True)
    winner = candidates[0][1]
    source = winner['source']

    gps_dt = parse_gps_timestamp(winner.get('gps_timestamp') or '')
    stale = evaluate_stale(adapter_stale=False, gps_dt=gps_dt, now=now)
    if not stale and bool(winner.get('adapter_stale')):
        won_on_newer_ts = (
            len(candidates) >= 2
            and candidates[0][0][0] > candidates[1][0][0]
        )
        if not won_on_newer_ts:
            stale = True

    bundle = {
        'latitude': winner.get('latitude'),
        'longitude': winner.get('longitude'),
        'speed_kmh': winner.get('speed_kmh'),
        'activity_status': winner.get('activity_status'),
        'activity_status_label': winner.get('activity_status_label'),
        'ignition': winner.get('ignition'),
        'address': winner.get('address'),
        'total_distance_km': winner.get('total_distance_km'),
        'has_valid_location': winner.get('has_valid_location'),
        'gps_timestamp': winner.get('gps_timestamp'),
        'last_seen_at': winner.get('gps_timestamp'),
        'last_seen_label': winner.get('last_seen_label'),
        'gps_last_seen_at': winner.get('gps_timestamp'),
        'is_stale_data': stale,
        'gps_is_stale': stale,
        'gps_stale': stale,
        'gps_source': source,
        'latest_gps': winner.get('latest_gps') if source == SOURCE_SQLITE else None,
    }

    gps_row = {
        'latitude': bundle['latitude'],
        'longitude': bundle['longitude'],
        'gps_timestamp': bundle['gps_timestamp'],
        'is_stale': stale,
        'speed_kmh': bundle['speed_kmh'],
        'activity_status': bundle.get('activity_status'),
    }

    return {
        'source': source,
        'bundle': bundle,
        'gps_row': gps_row,
        'filom_timestamp': (filom_bundle or {}).get('gps_timestamp'),
        'sqlite_timestamp': (sqlite_bundle or {}).get('gps_timestamp'),
    }


def apply_gps_bundle_to_vehicle(vehicle: dict, selection: dict[str, Any]) -> dict:
    """Merge plan fields preserved; GPS fields replaced atomically from selection."""
    out = dict(vehicle)
    bundle = selection.get('bundle')
    if not bundle:
        return out
    for key, val in bundle.items():
        if val is not None or key in ('gps_is_stale', 'gps_stale', 'is_stale_data'):
            out[key] = val
    if selection.get('source') == SOURCE_SQLITE and bundle.get('latest_gps'):
        out['latest_gps'] = bundle['latest_gps']
    elif selection.get('gps_row'):
        out['latest_gps'] = selection['gps_row']
    out['gps_source'] = selection.get('source')
    out['physical_source'] = selection.get('source')
    return out

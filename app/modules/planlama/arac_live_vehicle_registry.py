# -*- coding: utf-8 -*-
"""Canlı Takip aktif araç registry — yönetilebilir AKTIF/IPTAL filtresi."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from modules.planlama.arac_live_vehicle_dedupe import normalize_plate_key

_REGISTRY_CACHE: dict[str, Any] | None = None
_LIVE_STATUSES = frozenset({'AKTIF', 'IPTAL', 'PASIF'})
_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / 'config' / 'atp_live_vehicle_registry.json'
)


def _registry_path() -> Path:
    custom = (os.environ.get('CPS_ATP_LIVE_VEHICLE_REGISTRY_PATH') or '').strip()
    return Path(custom) if custom else _DEFAULT_REGISTRY_PATH


def load_live_vehicle_registry(force: bool = False) -> dict[str, Any]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None and not force:
        return _REGISTRY_CACHE

    path = _registry_path()
    if not path.is_file():
        _REGISTRY_CACHE = {'entries': [], 'by_plate_key': {}, 'by_external_id': {}}
        return _REGISTRY_CACHE

    with path.open(encoding='utf-8') as handle:
        data = json.load(handle)

    by_plate: dict[str, str] = {}
    by_external: dict[str, str] = {}
    for entry in data.get('entries') or []:
        status = str(entry.get('status') or 'AKTIF').upper()
        if status not in _LIVE_STATUSES:
            continue
        plate_key = normalize_plate_key(entry.get('plate_key') or entry.get('plate') or '')
        ext_id = str(entry.get('external_id') or entry.get('arac_external_id') or '').strip()
        if plate_key:
            by_plate[plate_key] = status
        if ext_id:
            by_external[ext_id] = status

    _REGISTRY_CACHE = {
        'entries': data.get('entries') or [],
        'by_plate_key': by_plate,
        'by_external_id': by_external,
    }
    return _REGISTRY_CACHE


def resolve_live_vehicle_status(vehicle: dict, registry: dict[str, Any] | None = None) -> str:
    reg = registry or load_live_vehicle_registry()
    ext_id = str(vehicle.get('id') or vehicle.get('arac_external_id') or '').strip()
    plate_key = normalize_plate_key(
        vehicle.get('plate') or vehicle.get('plate_display') or vehicle.get('arac_plaka_snapshot') or ''
    )
    if ext_id and ext_id in reg.get('by_external_id', {}):
        return reg['by_external_id'][ext_id]
    if plate_key and plate_key in reg.get('by_plate_key', {}):
        return reg['by_plate_key'][plate_key]
    return 'AKTIF'


def filter_live_tracking_vehicles(
    vehicles: list[dict],
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canlı Takip read-model — IPTAL/PASIF araçları listeden çıkar (silmez)."""
    reg = registry or load_live_vehicle_registry()
    active: list[dict] = []
    excluded: list[dict] = []

    for vehicle in vehicles:
        status = resolve_live_vehicle_status(vehicle, reg)
        if status in ('IPTAL', 'PASIF'):
            excluded.append({
                'id': str(vehicle.get('id') or ''),
                'plate_key': normalize_plate_key(vehicle.get('plate') or vehicle.get('plate_display') or ''),
                'status': status,
                'last_seen_at': vehicle.get('last_seen_at'),
            })
            continue
        active.append(vehicle)

    return {
        'vehicles': active,
        'excluded_count': len(excluded),
        'excluded': excluded,
        'registry_applied': bool(reg.get('entries')),
    }

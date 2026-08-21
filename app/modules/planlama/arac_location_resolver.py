# -*- coding: utf-8 -*-
"""Araç Takip V1.4A — plan item koordinat çözümleyici (snapshot → master → missing)."""
from __future__ import annotations

from typing import Any

LOCATION_STATUS_SNAPSHOT = 'SNAPSHOT'
LOCATION_STATUS_MASTER = 'MASTER_FALLBACK'
LOCATION_STATUS_MISSING = 'MISSING'

SOURCE_REQUEST = 'request'
SOURCE_SAVED = 'saved_location'
SOURCE_NONE = 'none'

SOURCE_LABELS = {
    SOURCE_REQUEST: 'Talep kaydı',
    SOURCE_SAVED: 'Kayıtlı yer',
    SOURCE_NONE: 'Konum eksik',
}


def _valid_coord(lat: Any, lng: Any) -> bool:
    try:
        if lat is None or lng is None:
            return False
        float(lat)
        float(lng)
        return True
    except (TypeError, ValueError):
        return False


def resolve_item_location(talep: dict | None, master: dict | None = None) -> dict:
    """Resolve coordinates for a plan item without mutating talep snapshot."""
    t = talep or {}
    m = master or {}
    snap_lat = t.get('latitude')
    snap_lng = t.get('longitude')
    if _valid_coord(snap_lat, snap_lng):
        return {
            'latitude': float(snap_lat),
            'longitude': float(snap_lng),
            'location_status': LOCATION_STATUS_SNAPSHOT,
            'location_source': SOURCE_REQUEST,
            'location_source_label': SOURCE_LABELS[SOURCE_REQUEST],
            'has_coordinates': True,
            'kayitli_yer_id': t.get('kayitli_yer_id'),
        }
    master_lat = m.get('latitude')
    master_lng = m.get('longitude')
    if _valid_coord(master_lat, master_lng):
        return {
            'latitude': float(master_lat),
            'longitude': float(master_lng),
            'location_status': LOCATION_STATUS_MASTER,
            'location_source': SOURCE_SAVED,
            'location_source_label': SOURCE_LABELS[SOURCE_SAVED],
            'has_coordinates': True,
            'kayitli_yer_id': t.get('kayitli_yer_id'),
        }
    return {
        'latitude': None,
        'longitude': None,
        'location_status': LOCATION_STATUS_MISSING,
        'location_source': SOURCE_NONE,
        'location_source_label': SOURCE_LABELS[SOURCE_NONE],
        'has_coordinates': False,
        'kayitli_yer_id': t.get('kayitli_yer_id'),
    }


def resolve_base_location(base_row: dict | None) -> dict:
    b = base_row or {}
    lat = b.get('base_latitude')
    lng = b.get('base_longitude')
    has = _valid_coord(lat, lng)
    return {
        'id': b.get('id'),
        'base_name': b.get('base_name') or '',
        'base_address': b.get('base_address') or '',
        'base_maps_url': b.get('base_maps_url') or '',
        'latitude': float(lat) if has else None,
        'longitude': float(lng) if has else None,
        'has_coordinates': has,
        'configured': bool(b.get('id')),
    }

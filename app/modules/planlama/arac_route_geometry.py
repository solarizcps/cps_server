# -*- coding: utf-8 -*-
"""Canonical route geometry — GeoJSON LineString [lon, lat] contract."""
from __future__ import annotations

import hashlib
import json
from typing import Any

GEOMETRY_SCHEMA = 'geojson_linestring_v1'


class GeometryError(ValueError):
    pass


def _valid_lonlat(lon: float, lat: float) -> bool:
    if lat == 0.0 and lon == 0.0:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def latlng_pairs_to_geojson(pairs: list[list[float]]) -> dict[str, Any]:
    """Convert legacy [[lat,lng],...] or already [[lng,lat],...] heuristically."""
    if len(pairs) < 2:
        raise GeometryError('En az iki koordinat gerekli')
    coords: list[list[float]] = []
    for pair in pairs:
        if len(pair) < 2:
            raise GeometryError('Koordinat çifti eksik')
        a, b = float(pair[0]), float(pair[1])
        # Turkey bbox heuristic: lat ~36-42, lon ~26-45
        if 35.0 <= a <= 43.0 and 25.0 <= b <= 46.0:
            lat, lon = a, b
        elif 35.0 <= b <= 43.0 and 25.0 <= a <= 46.0:
            lon, lat = a, b
        else:
            # Default legacy CPS mock: [lat, lng]
            lat, lon = a, b
        if not _valid_lonlat(lon, lat):
            raise GeometryError(f'Geçersiz koordinat: {lon},{lat}')
        coords.append([round(lon, 6), round(lat, 6)])
    return {
        'type': 'LineString',
        'coordinates': coords,
        'crs': 'WGS84',
        'schema': GEOMETRY_SCHEMA,
    }


def validate_geojson_linestring(geometry: dict[str, Any]) -> list[list[float]]:
    if geometry.get('type') != 'LineString':
        raise GeometryError('LineString bekleniyor')
    coords = geometry.get('coordinates')
    if not isinstance(coords, list) or len(coords) < 2:
        raise GeometryError('coordinates en az 2 nokta olmalı')
    out: list[list[float]] = []
    for pt in coords:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            raise GeometryError('coordinate format hatalı')
        lon, lat = float(pt[0]), float(pt[1])
        if not _valid_lonlat(lon, lat):
            raise GeometryError(f'Geçersiz lon/lat: {lon},{lat}')
        if abs(lon) <= 90 and abs(lat) > 90:
            raise GeometryError('Koordinat sırası [longitude, latitude] olmalı')
        out.append([lon, lat])
    return out


def geometry_from_storage(raw: Any) -> dict[str, Any]:
    """Load geometry from DB — supports GeoJSON wrapper or legacy pair list."""
    if isinstance(raw, dict):
        if raw.get('type') == 'LineString':
            validate_geojson_linestring(raw)
            return raw
        if 'coordinates' in raw:
            return raw
    if isinstance(raw, list):
        return latlng_pairs_to_geojson(raw)
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return geometry_from_storage(parsed)
    raise GeometryError('Geometry okunamadı')


def route_content_hash(
    geometry: dict[str, Any],
    stop_order: list[dict],
    total_distance_m: float | None,
    total_duration_s: float | None,
) -> str:
    payload = json.dumps({
        'geometry': geometry.get('coordinates'),
        'stop_order': stop_order,
        'distance': total_distance_m,
        'duration': total_duration_s,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

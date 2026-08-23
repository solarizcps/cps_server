# -*- coding: utf-8 -*-
"""WGS84 geodesic helpers — point/segment distance in metres (Turkey scale)."""
from __future__ import annotations

import math
from typing import Sequence

EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = la2 - la1
    dlon = lo2 - lo1
    x = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1.0, x)))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _closest_point_on_segment(
    lat: float,
    lon: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> tuple[float, float]:
    """Planar equirectangular projection — valid for short segments (< ~50 km)."""
    cos_lat = math.cos(math.radians((lat1 + lat2 + lat) / 3.0))
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6
    x, y = lon * cos_lat, lat
    x1, y1 = lon1 * cos_lat, lat1
    x2, y2 = lon2 * cos_lat, lat2
    dx, dy = x2 - x1, y2 - y1
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return lat1, lon1
    t = _clamp(((x - x1) * dx + (y - y1) * dy) / seg_len2, 0.0, 1.0)
    cx = x1 + t * dx
    cy = y1 + t * dy
    return cy, cx / cos_lat


def point_to_segment_distance_m(
    lat: float,
    lon: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    clat, clon = _closest_point_on_segment(lat, lon, lat1, lon1, lat2, lon2)
    return haversine_m(lat, lon, clat, clon)


def point_to_linestring_distance_m(
    lat: float,
    lon: float,
    coordinates: Sequence[Sequence[float]],
) -> float | None:
    """
    Minimum distance from point to GeoJSON LineString coordinates [[lon,lat],...].
    Returns None for invalid geometry.
    """
    if len(coordinates) < 2:
        return None
    best: float | None = None
    for i in range(len(coordinates) - 1):
        lon1, lat1 = coordinates[i][0], coordinates[i][1]
        lon2, lat2 = coordinates[i + 1][0], coordinates[i + 1][1]
        if not _valid_lonlat(lon1, lat1) or not _valid_lonlat(lon2, lat2):
            return None
        d = point_to_segment_distance_m(lat, lon, lat1, lon1, lat2, lon2)
        best = d if best is None else min(best, d)
    return best


def _valid_lonlat(lon: float, lat: float) -> bool:
    if lat == 0.0 and lon == 0.0:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

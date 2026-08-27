# -*- coding: utf-8 -*-
"""Resolve approved Solariz factory Google Maps short link — no coordinate guessing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

FACTORY_SHORT_LINK = 'https://maps.app.goo.gl/XzV9ZcXDfdaeCcpM9'
FACTORY_DISPLAY_NAME = 'Solariz Fabrika'

# Forbidden fallback coordinates (must not match resolved values)
FORBIDDEN_COORDS = (
    (40.818, 29.305),   # TEST FABRİKA seed
    (40.818, 29.3050),
)


@dataclass(frozen=True)
class FactoryLinkResolution:
    short_link: str
    resolved_url: str | None
    place_name: str | None
    latitude: float
    longitude: float
    coordinate_source: str
    confidence: str
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            'FACTORY_SHORT_LINK': self.short_link,
            'FACTORY_RESOLVED_URL': self.resolved_url,
            'FACTORY_PLACE_NAME': self.place_name,
            'FACTORY_LATITUDE': self.latitude,
            'FACTORY_LONGITUDE': self.longitude,
            'COORDINATE_SOURCE': self.coordinate_source,
            'COORDINATE_CONFIDENCE': self.confidence,
        }


def _valid_range(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _extract_dir_origin(url: str) -> tuple[float, float, str] | None:
    m = re.search(r'/dir/(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    if not _valid_range(lat, lng):
        return None
    return lat, lng, 'google_maps_dir_origin_segment'


def _extract_at_center(url: str) -> tuple[float, float, str] | None:
    m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    if not _valid_range(lat, lng):
        return None
    return lat, lng, 'google_maps_at_map_center'


def _destination_label(url: str) -> str | None:
    m = re.search(r'/dir/[^/]+/([^/@]+)', url)
    if not m:
        return None
    label = unquote(m.group(1).replace('+', ' ')).strip()
    return label or None


def resolve_factory_link(short_link: str = FACTORY_SHORT_LINK) -> FactoryLinkResolution:
    """Follow redirects via CPS allowlisted resolver; fail closed on missing coords."""
    from modules.planlama.arac_lokasyon_service import (
        parse_maps_coords,
        resolve_google_maps_url,
        resolve_maps_input,
    )

    resolved_url = resolve_google_maps_url(short_link)
    if not resolved_url:
        raise RuntimeError(f'BLOCK: short link did not resolve: {short_link}')

    payload = resolve_maps_input({'maps_url': short_link})
    lat = float(payload['latitude'])
    lng = float(payload['longitude'])
    if not _valid_range(lat, lng):
        raise RuntimeError(f'BLOCK: coordinates out of range: {lat}, {lng}')

    for forbidden in FORBIDDEN_COORDS:
        if abs(lat - forbidden[0]) < 0.0001 and abs(lng - forbidden[1]) < 0.0001:
            raise RuntimeError(f'BLOCK: resolved coords match forbidden TEST seed {forbidden}')

    dir_origin = _extract_dir_origin(resolved_url)
    at_center = _extract_at_center(resolved_url)
    dest_name = _destination_label(resolved_url)

    if dir_origin and abs(dir_origin[0] - lat) < 0.00001 and abs(dir_origin[1] - lng) < 0.00001:
        source = 'resolved_url_/dir/origin_lat_lng (directions route start = factory)'
        confidence = 'HIGH'
    elif at_center and abs(at_center[0] - lat) < 0.00001 and abs(at_center[1] - lng) < 0.00001:
        source = 'resolved_url_@map_center (matches parse_maps_coords)'
        confidence = 'HIGH'
    else:
        source = 'parse_maps_coords_from_resolved_url'
        confidence = 'MEDIUM'

    return FactoryLinkResolution(
        short_link=short_link,
        resolved_url=resolved_url,
        place_name=dest_name,
        latitude=lat,
        longitude=lng,
        coordinate_source=source,
        confidence=confidence,
        raw={'payload': payload, 'dir_origin': dir_origin, 'at_center': at_center},
    )

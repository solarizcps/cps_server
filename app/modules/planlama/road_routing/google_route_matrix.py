# -*- coding: utf-8 -*-
"""Google Routes computeRouteMatrix — traffic-aware duration matrix."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Sequence

from modules.planlama.road_routing.google_routes_provider import _parse_duration_s, departure_utc_from_local
from modules.planlama.road_routing.types import RouteMatrix, RoutingError

_log = logging.getLogger(__name__)

_MATRIX_ENDPOINT = 'https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix'
_FIELD_MASK = 'originIndex,destinationIndex,duration,staticDuration,distanceMeters,condition'
_MAX_ELEMENTS = 625


def _waypoint(lat: float, lng: float) -> dict:
    return {'waypoint': {'location': {'latLng': {'latitude': lat, 'longitude': lng}}}}


def _post_matrix(body: dict, api_key: str, timeout: float) -> list[dict]:
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        _MATRIX_ENDPOINT,
        data=data,
        method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': _FIELD_MASK,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list):
                return raw
            return raw.get('elements') or raw.get('rows') or []
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            detail = str(exc)
        if api_key and api_key in detail:
            detail = detail.replace(api_key, '<REDACTED>')
        _log.warning('Google Route Matrix HTTP %s: %s', exc.code, detail)
        if exc.code in (401, 403):
            raise RoutingError('Google Route Matrix kimlik doğrulama hatası.', code='AUTH', http_status=exc.code) from exc
        if exc.code == 429:
            raise RoutingError('Google Route Matrix kota aşıldı.', code='RATE_LIMIT', http_status=exc.code) from exc
        if exc.code >= 500:
            raise RoutingError('Google Route Matrix sunucu hatası.', code='SERVER', http_status=exc.code) from exc
        raise RoutingError('Google Route Matrix isteği başarısız.', code='ERROR', http_status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise RoutingError('Google Route Matrix bağlantı hatası.', code='TIMEOUT') from exc


def compute_google_traffic_matrix(
    points: Sequence[tuple[float, float]],
    *,
    departure_utc: str,
    api_key: str,
    timeout: float = 10.0,
) -> tuple[RouteMatrix, list[list[float | None]], int]:
    """Full N×N traffic duration matrix. Returns (matrix, static_duration_s, element_count)."""
    pts = list(points)
    n = len(pts)
    if n < 2:
        raise RoutingError('Matrix için en az iki nokta gerekli.', code='NO_MATRIX')
    elements = n * n
    if elements > _MAX_ELEMENTS:
        raise RoutingError(
            f'Plan {n} nokta ile Google matrix limitini ({_MAX_ELEMENTS} eleman) aşıyor.',
            code='MATRIX_TOO_LARGE',
        )

    body = {
        'origins': [_waypoint(lat, lng) for lat, lng in pts],
        'destinations': [_waypoint(lat, lng) for lat, lng in pts],
        'travelMode': 'DRIVE',
        'routingPreference': 'TRAFFIC_AWARE_OPTIMAL',
        'departureTime': departure_utc,
        'languageCode': 'tr',
        'regionCode': 'TR',
    }
    rows = _post_matrix(body, api_key, timeout)
    duration_s: list[list[float | None]] = [[None] * n for _ in range(n)]
    static_s: list[list[float | None]] = [[None] * n for _ in range(n)]
    distance_m: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        duration_s[i][i] = 0.0
        static_s[i][i] = 0.0
        distance_m[i][i] = 0.0

    parsed = 0
    for cell in rows:
        oi = cell.get('originIndex')
        di = cell.get('destinationIndex')
        if oi is None or di is None:
            continue
        oi, di = int(oi), int(di)
        if oi >= n or di >= n:
            continue
        dur = _parse_duration_s(cell.get('duration'))
        stat = _parse_duration_s(cell.get('staticDuration')) or dur
        dist = float(cell.get('distanceMeters') or 0)
        duration_s[oi][di] = dur
        static_s[oi][di] = stat
        distance_m[oi][di] = dist
        parsed += 1

    if parsed == 0:
        raise RoutingError('Google Route Matrix boş yanıt.', code='EMPTY_MATRIX')

    return RouteMatrix(
        provider='google_routes_matrix',
        profile='google-traffic-fast',
        duration_s=duration_s,
        distance_m=distance_m,
    ), static_s, elements

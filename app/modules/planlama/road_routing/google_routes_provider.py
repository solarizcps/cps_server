# -*- coding: utf-8 -*-
"""Google Routes API adapter (v2:computeRoutes).

Supports three routing profiles:
  - TRAFFIC_AWARE_OPTIMAL  (tolls allowed)   → label: 'google-traffic-fast'
  - TRAFFIC_AWARE_OPTIMAL  (avoid tolls)     → label: 'google-traffic-free'
  - TRAFFIC_UNAWARE                          → label: 'google-static'

Implements the same RoadRoutingProvider contract as OpenRouteServiceProvider.
Secret: GOOGLE_ROUTES_API_KEY from .env — never written to logs or returned in DTOs.

Public contract for Google-specific fields:
  GoogleRouteResult — typed dataclass; orchestration layer uses this, not _attr hacks.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from modules.planlama.road_routing.env_loader import load_routing_env
from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.types import RouteLeg, RouteMatrix, RouteResult, RoutingError

_log = logging.getLogger(__name__)

_ENDPOINT = 'https://routes.googleapis.com/directions/v2:computeRoutes'
_DEFAULT_TIMEOUT = 10.0

# ── Routing profiles ─────────────────────────────────────────────────────────

PROFILE_TRAFFIC_FAST = 'google-traffic-fast'   # TRAFFIC_AWARE_OPTIMAL, tolls OK
PROFILE_TRAFFIC_FREE = 'google-traffic-free'   # TRAFFIC_AWARE_OPTIMAL, avoidTolls
PROFILE_STATIC       = 'google-static'         # TRAFFIC_UNAWARE

_VALID_PROFILES = frozenset({PROFILE_TRAFFIC_FAST, PROFILE_TRAFFIC_FREE, PROFILE_STATIC})

# Field mask sent with every request
_FIELD_MASK = (
    'routes.distanceMeters,'
    'routes.duration,'
    'routes.staticDuration,'
    'routes.routeLabels,'
    'routes.polyline.encodedPolyline,'
    'routes.travelAdvisory.tollInfo,'
    'routes.legs.distanceMeters,'
    'routes.legs.duration,'
    'routes.legs.staticDuration,'
    'routes.legs.travelAdvisory.tollInfo'
)

load_routing_env(force_routing=True)


# ── Public GoogleRouteResult dataclass ───────────────────────────────────────

@dataclass
class GoogleLeg:
    """Per-leg data from Google Routes API."""
    from_index: int
    to_index: int
    distance_m: float
    drive_seconds: float
    static_seconds: float
    toll_info: dict | None = None


@dataclass
class GoogleRouteResult:
    """Public contract for Google Routes API results.

    Orchestration services use this; never access _attr hacks on base RouteResult.
    """
    profile: str
    profile_label: str
    distance_m: float
    drive_seconds: float        # traffic-aware (or static if TRAFFIC_UNAWARE)
    static_seconds: float       # no-traffic baseline
    traffic_delta_seconds: float
    encoded_polyline: str | None
    toll_present: bool
    toll_info: dict | None
    route_labels: list[str]
    legs: list[GoogleLeg]

    @property
    def distance_km(self) -> float:
        return round(self.distance_m / 1000.0, 1)


_PROFILE_LABELS: dict[str, str] = {
    PROFILE_TRAFFIC_FAST: 'En Hızlı',
    PROFILE_TRAFFIC_FREE: 'Ücretsiz Yol',
    PROFILE_STATIC:       'Statik Referans',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _api_key() -> str | None:
    key = (os.environ.get('GOOGLE_ROUTES_API_KEY') or '').strip()
    return key or None


def _timeout_sec() -> float:
    try:
        return float(os.environ.get('ARAC_ROUTING_TIMEOUT', _DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT


def _redact_key(key: str | None) -> str:
    """Return non-secret repr suitable for logs."""
    if not key:
        return '<absent>'
    return f'{key[:4]}***{key[-2:]}(len={len(key)})'


def _parse_duration_s(val: str | None) -> float:
    """'16312s' → 16312.0.  Returns 0.0 for None/empty."""
    if not val:
        return 0.0
    v = val.strip()
    if v.endswith('s'):
        v = v[:-1]
    try:
        return float(v)
    except ValueError:
        return 0.0


# ── Request builders ──────────────────────────────────────────────────────────

def _waypoint(lat: float, lng: float) -> dict[str, Any]:
    return {'location': {'latLng': {'latitude': lat, 'longitude': lng}}}


def _build_common_body(
    points: Sequence[tuple[float, float]],
    departure_utc: str | None,
) -> dict[str, Any]:
    """Shared fields for all three profiles."""
    pts = list(points)
    body: dict[str, Any] = {
        'origin': _waypoint(*pts[0]),
        'destination': _waypoint(*pts[-1]),
        'travelMode': 'DRIVE',
        'optimizeWaypointOrder': False,
        'computeAlternativeRoutes': False,
        'languageCode': 'tr',
        'regionCode': 'TR',
        'units': 'METRIC',
        'routeModifiers': {
            'avoidFerries': True,
        },
        'extraComputations': ['TOLLS'],
    }
    intermediates = [_waypoint(*p) for p in pts[1:-1]]
    if intermediates:
        body['intermediates'] = intermediates
    if departure_utc:
        body['departureTime'] = departure_utc
    return body


def build_traffic_fast_body(
    points: Sequence[tuple[float, float]],
    departure_utc: str | None = None,
) -> dict[str, Any]:
    """TRAFFIC_AWARE_OPTIMAL — tolls allowed."""
    body = _build_common_body(points, departure_utc)
    body['routingPreference'] = 'TRAFFIC_AWARE_OPTIMAL'
    body['trafficModel'] = 'BEST_GUESS'
    body['routeModifiers']['avoidTolls'] = False
    body['routeModifiers']['avoidHighways'] = False
    return body


def build_traffic_free_body(
    points: Sequence[tuple[float, float]],
    departure_utc: str | None = None,
) -> dict[str, Any]:
    """TRAFFIC_AWARE_OPTIMAL — avoid tolls."""
    body = _build_common_body(points, departure_utc)
    body['routingPreference'] = 'TRAFFIC_AWARE_OPTIMAL'
    body['trafficModel'] = 'BEST_GUESS'
    body['routeModifiers']['avoidTolls'] = True
    body['routeModifiers']['avoidHighways'] = False
    return body


def build_static_body(
    points: Sequence[tuple[float, float]],
) -> dict[str, Any]:
    """TRAFFIC_UNAWARE — no departure time, no traffic model."""
    body = _build_common_body(points, departure_utc=None)
    body['routingPreference'] = 'TRAFFIC_UNAWARE'
    body['routeModifiers']['avoidTolls'] = False
    body['routeModifiers']['avoidHighways'] = False
    body.pop('departureTime', None)
    return body


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_google_route(
    raw: dict[str, Any],
    profile: str,
) -> GoogleRouteResult:
    """Parse a single Google Routes API response → GoogleRouteResult (public contract)."""
    routes = raw.get('routes') or []
    if not routes:
        raise RoutingError('Google Routes API boş yanıt döndürdü.', code='NO_ROUTE')
    route = routes[0]

    distance_m = float(route.get('distanceMeters') or 0)
    drive_s = _parse_duration_s(route.get('duration'))
    static_s = _parse_duration_s(route.get('staticDuration')) or drive_s

    encoded_polyline = (route.get('polyline') or {}).get('encodedPolyline') or None
    toll_advisory = (route.get('travelAdvisory') or {}).get('tollInfo')
    toll_present = toll_advisory is not None
    route_labels = route.get('routeLabels') or []

    raw_legs = route.get('legs') or []
    legs: list[GoogleLeg] = []
    for i, raw_leg in enumerate(raw_legs):
        leg_toll = (raw_leg.get('travelAdvisory') or {}).get('tollInfo')
        legs.append(GoogleLeg(
            from_index=i,
            to_index=i + 1,
            distance_m=float(raw_leg.get('distanceMeters') or 0),
            drive_seconds=_parse_duration_s(raw_leg.get('duration')),
            static_seconds=_parse_duration_s(raw_leg.get('staticDuration')) or
                           _parse_duration_s(raw_leg.get('duration')),
            toll_info=leg_toll,
        ))

    return GoogleRouteResult(
        profile=profile,
        profile_label=_PROFILE_LABELS.get(profile, profile),
        distance_m=distance_m,
        drive_seconds=drive_s,
        static_seconds=static_s,
        traffic_delta_seconds=drive_s - static_s,
        encoded_polyline=encoded_polyline,
        toll_present=toll_present,
        toll_info=toll_advisory,
        route_labels=route_labels,
        legs=legs,
    )


def _parse_route(raw: dict[str, Any], provider_name: str, profile: str) -> RouteResult:
    """Parse → base RouteResult (RoadRoutingProvider contract).
    For Google-specific fields use _parse_google_route() instead."""
    gr = _parse_google_route(raw, profile)
    base_legs = [
        RouteLeg(
            from_index=lg.from_index,
            to_index=lg.to_index,
            distance_m=lg.distance_m,
            duration_s=lg.drive_seconds,
        )
        for lg in gr.legs
    ]
    return RouteResult(
        provider=provider_name,
        profile=profile,
        distance_m=gr.distance_m,
        duration_s=gr.drive_seconds,
        geometry=[],
        legs=base_legs,
        raw_status='OK',
    )


# ── HTTP transport ────────────────────────────────────────────────────────────

def _post_routes(body: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    """Send one POST to Google Routes API.  Never logs the api_key value."""
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        _ENDPOINT,
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
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            detail = str(exc)
        if api_key and api_key in detail:
            detail = detail.replace(api_key, '<REDACTED>')
        _log.warning('Google Routes HTTP %s: %s', code, detail)
        if code in (400,):
            raise RoutingError('Google Routes isteği geçersiz.', code='BAD_REQUEST', http_status=code) from exc
        if code in (401, 403):
            raise RoutingError('Google Routes API kimlik doğrulama hatası.', code='AUTH', http_status=code) from exc
        if code == 429:
            raise RoutingError('Google Routes API kota aşıldı.', code='RATE_LIMIT', http_status=code) from exc
        if code >= 500:
            raise RoutingError('Google Routes sunucu hatası.', code='SERVER', http_status=code) from exc
        raise RoutingError('Rota hesaplanamadı.', code='ERROR', http_status=code) from exc
    except urllib.error.URLError as exc:
        _log.warning('Google Routes timeout/network: %s', exc.reason)
        raise RoutingError('Google Routes bağlantı hatası.', code='TIMEOUT') from exc
    except json.JSONDecodeError as exc:
        raise RoutingError('Google Routes geçersiz JSON yanıtı.', code='INVALID_JSON') from exc


# ── Provider class ────────────────────────────────────────────────────────────

class GoogleRoutesProvider(RoadRoutingProvider):
    """Google Routes API v2 adapter.

    profile must be one of:
        'google-traffic-fast'  — TRAFFIC_AWARE_OPTIMAL, tolls OK
        'google-traffic-free'  — TRAFFIC_AWARE_OPTIMAL, avoidTolls
        'google-static'        — TRAFFIC_UNAWARE

    departure_utc: RFC3339 UTC Zulu string, e.g. '2026-08-27T05:00:00Z'.
    Required for traffic profiles; silently ignored for static.
    """

    name = 'google_routes'

    def __init__(
        self,
        profile: str = PROFILE_TRAFFIC_FAST,
        departure_utc: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        if profile not in _VALID_PROFILES:
            raise RoutingError(
                f'Geçersiz Google Routes profili: {profile!r}. '
                f'Geçerli seçenekler: {sorted(_VALID_PROFILES)}',
                code='BAD_PROFILE',
            )
        self.profile = profile
        self._departure_utc = departure_utc
        self._key = (api_key or _api_key() or '').strip()
        if not self._key:
            raise RoutingError(
                'GOOGLE_ROUTES_API_KEY yapılandırılmamış.',
                code='UNCONFIGURED',
            )
        self._timeout = timeout if timeout is not None else _timeout_sec()

    def _build_body(self, points: Sequence[tuple[float, float]]) -> dict[str, Any]:
        if self.profile == PROFILE_TRAFFIC_FAST:
            return build_traffic_fast_body(points, self._departure_utc)
        if self.profile == PROFILE_TRAFFIC_FREE:
            return build_traffic_free_body(points, self._departure_utc)
        return build_static_body(points)

    def route_ordered(self, points: Sequence[tuple[float, float]]) -> RouteResult:
        """Base contract — returns RouteResult.  For full Google data use route_google()."""
        pts = list(points)
        if len(pts) < 2:
            raise RoutingError('En az iki nokta gerekli.', code='NO_ROUTE')
        body = self._build_body(pts)
        raw = _post_routes(body, self._key, self._timeout)
        return _parse_route(raw, self.name, self.profile)

    def route_google(self, points: Sequence[tuple[float, float]]) -> GoogleRouteResult:
        """Public contract for orchestration — returns GoogleRouteResult with all fields."""
        pts = list(points)
        if len(pts) < 2:
            raise RoutingError('En az iki nokta gerekli.', code='NO_ROUTE')
        body = self._build_body(pts)
        raw = _post_routes(body, self._key, self._timeout)
        return _parse_google_route(raw, self.profile)

    def matrix(self, points: Sequence[tuple[float, float]]) -> RouteMatrix:
        """Compute Route Matrix is not yet implemented in this adapter.
        Callers must fall back to ORS or MockProvider for matrix operations.
        """
        raise RoutingError(
            'Bu adaptörde matrix henüz uygulanmadı.',
            code='GOOGLE_ROUTE_MATRIX_NOT_IMPLEMENTED',
        )

    # ── Static accessors kept for backward-compat with existing tests ─────────

    @staticmethod
    def static_duration_s(result: RouteResult) -> float:
        return getattr(result, '_static_duration_s', result.duration_s)

    @staticmethod
    def traffic_delta_s(result: RouteResult) -> float:
        return getattr(result, '_traffic_delta_s', 0.0)

    @staticmethod
    def toll_info(result: RouteResult) -> dict | None:
        return getattr(result, '_toll_info', None)

    @staticmethod
    def route_labels(result: RouteResult) -> list[str]:
        return getattr(result, '_route_labels', [])


# ── Convenience factories ─────────────────────────────────────────────────────

def make_google_provider(
    profile: str = PROFILE_TRAFFIC_FAST,
    departure_utc: str | None = None,
    api_key: str | None = None,
) -> GoogleRoutesProvider:
    """Shorthand constructor; raises RoutingError if key is absent."""
    return GoogleRoutesProvider(
        profile=profile,
        departure_utc=departure_utc,
        api_key=api_key,
    )


def google_provider_available() -> bool:
    from modules.planlama.road_routing.env_loader import google_routes_key_present
    return google_routes_key_present()


def departure_utc_from_local(local_iso: str) -> str:
    """Convert 'YYYY-MM-DDTHH:MM:SS+03:00' → '2026-08-27T05:00:00Z'.
    Accepts any timezone-aware ISO 8601 string.  Raises ValueError on bad input.
    """
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        raise ValueError(f'departure_utc_from_local: timezone-naive input: {local_iso!r}')
    utc = dt.astimezone(timezone.utc)
    return utc.strftime('%Y-%m-%dT%H:%M:%SZ')

# -*- coding: utf-8 -*-
"""OpenRouteService adapter — secrets via environment only."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Sequence

from modules.planlama.road_routing.env_loader import load_routing_env
from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.types import RouteLeg, RouteMatrix, RouteResult, RoutingError

_log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 8.0
_ORS_BASE = 'https://api.openrouteservice.org/v2'

load_routing_env(force_routing=True)


def _timeout_sec() -> float:
    try:
        return float(os.environ.get('ARAC_ROUTING_TIMEOUT', _DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT


def _api_key() -> str | None:
    key = (os.environ.get('ORS_API_KEY') or '').strip()
    return key or None


def _profile() -> str:
    return (os.environ.get('ORS_PROFILE') or 'driving-car').strip() or 'driving-car'


def _to_ors_locations(points: Sequence[tuple[float, float]]) -> list[list[float]]:
    return [[float(lng), float(lat)] for lat, lng in points]


def _from_ors_geometry(coords: list) -> list[list[float]]:
    out: list[list[float]] = []
    for pair in coords or []:
        if not pair or len(pair) < 2:
            continue
        lng, lat = float(pair[0]), float(pair[1])
        out.append([lat, lng])
    return out


class OpenRouteServiceProvider(RoadRoutingProvider):
    name = 'ors'
    profile = 'driving-car'

    def __init__(self, api_key: str | None = None, profile: str | None = None, timeout: float | None = None):
        self._key = (api_key or _api_key() or '').strip()
        if not self._key:
            raise RoutingError('Rota servisi yapılandırılmamış.', code='UNCONFIGURED')
        self.profile = profile or _profile()
        self._timeout = timeout if timeout is not None else _timeout_sec()

    def _request(self, path: str, body: dict) -> dict:
        url = f'{_ORS_BASE}/{path}/{self.profile}/geojson'
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            method='POST',
            headers={
                'Authorization': self._key,
                'Content-Type': 'application/json; charset=utf-8',
                # /geojson endpoint requires geo+json in Accept (ORS error 2007 otherwise).
                'Accept': 'application/geo+json, application/json',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            code = exc.code
            err_code = 'ERROR'
            if code in (401, 403):
                err_code = 'AUTH'
            elif code == 429:
                err_code = 'RATE_LIMIT'
            elif code >= 500:
                err_code = 'SERVER'
            try:
                detail = exc.read().decode('utf-8', errors='replace')[:200]
            except Exception:
                detail = str(exc)
            _log.warning('ORS HTTP %s: %s', code, detail)
            raise RoutingError('Rota hesaplanamadı.', code=err_code, http_status=code) from exc
        except urllib.error.URLError as exc:
            _log.warning('ORS timeout/network: %s', exc.reason)
            raise RoutingError('Rota hesaplanamadı.', code='TIMEOUT') from exc
        except json.JSONDecodeError as exc:
            raise RoutingError('Rota hesaplanamadı.', code='INVALID_JSON') from exc

    def route_ordered(self, points: Sequence[tuple[float, float]]) -> RouteResult:
        if len(points) < 2:
            raise RoutingError('En az iki nokta gerekli.', code='NO_ROUTE')
        body = {'coordinates': _to_ors_locations(points)}
        payload = self._request('directions', body)
        features = payload.get('features') or []
        if not features:
            raise RoutingError('Rota hesaplanamadı.', code='NO_ROUTE')
        feat = features[0]
        geom = _from_ors_geometry((feat.get('geometry') or {}).get('coordinates') or [])
        props = feat.get('properties') or {}
        summary = props.get('summary') or {}
        segments = props.get('segments') or []
        legs: list[RouteLeg] = []
        for i, seg in enumerate(segments):
            legs.append(RouteLeg(
                from_index=i,
                to_index=i + 1,
                distance_m=float(seg.get('distance') or 0),
                duration_s=float(seg.get('duration') or 0),
            ))
        return RouteResult(
            provider=self.name,
            profile=self.profile,
            distance_m=float(summary.get('distance') or sum(l.distance_m for l in legs)),
            duration_s=float(summary.get('duration') or sum(l.duration_s for l in legs)),
            geometry=geom,
            legs=legs,
        )

    def matrix(self, points: Sequence[tuple[float, float]]) -> RouteMatrix:
        if len(points) < 2:
            raise RoutingError('Matrix için en az iki nokta gerekli.', code='NO_ROUTE')
        body = {
            'locations': _to_ors_locations(points),
            'metrics': ['distance', 'duration'],
            'units': 'm',
        }
        url = f'{_ORS_BASE}/matrix/{self.profile}'
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            method='POST',
            headers={
                'Authorization': self._key,
                'Content-Type': 'application/json; charset=utf-8',
                'Accept': 'application/json',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            err_code = 'AUTH' if exc.code in (401, 403) else ('RATE_LIMIT' if exc.code == 429 else 'ERROR')
            _log.warning('ORS matrix HTTP %s', exc.code)
            raise RoutingError('Rota hesaplanamadı.', code=err_code, http_status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise RoutingError('Rota hesaplanamadı.', code='TIMEOUT') from exc
        dist = payload.get('distances') or []
        dur = payload.get('durations') or []
        return RouteMatrix(
            provider=self.name,
            profile=self.profile,
            distance_m=dist,
            duration_s=dur,
        )


def provider_available() -> bool:
    from modules.planlama.road_routing.env_loader import ors_key_present
    return ors_key_present()

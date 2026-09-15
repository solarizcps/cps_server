# -*- coding: utf-8 -*-
"""ORS kesintisinde Google Static yedeği — rota çizgisi, km/süre ve waypoint optimizasyonu.

Kapsam sınırları:
  - Sadece TRAFFIC_UNAWARE (static) profil kullanılır; departureTime gönderilmez.
  - ORS fallback kodu ile tetiklenen iki yol:
      1. route_via_google_static()       — mevcut sırayla tek istek.
      2. route_via_google_optimized()    — optimizeWaypointOrder=true ile tek istek;
         hem mevcut hem de optimize rota döner (2 RouteResult + optimize sıra indeksleri).
  - Trafik profilleri (google-traffic-*) bu yolda kullanılmaz.
  - Secret okunmaz/yazılmaz; anahtar Google provider katmanında kalır.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Sequence

from modules.planlama.road_routing.google_routes_provider import (
    PROFILE_STATIC,
    GoogleLeg,
    GoogleRouteResult,
    GoogleRoutesProvider,
    _api_key,
    _parse_duration_s,
    _parse_google_route,
    _timeout_sec,
    _FIELD_MASK,
    _post_routes,
    _waypoint,
    google_provider_available,
)
from modules.planlama.road_routing.types import RouteLeg, RouteResult, RoutingError

PROVIDER_NAME = 'google-static'

# Yalnız bu ORS hata kodlarında yedek sağlayıcı denenir.
ORS_FALLBACK_CODES = frozenset({'AUTH', 'RATE_LIMIT', 'TIMEOUT', 'SERVER'})

FALLBACK_WARNING_CODE = 'PROVIDER_FALLBACK_GOOGLE_STATIC'
FALLBACK_WARNING_MESSAGE = (
    'Rota servisi (ORS) yanıt vermedi; güzergâh çizgisi ve mevcut plan km/süre '
    'google-static fallback ile hesaplandı. Önerilen sıra ve kazanç hesaplanmadı.'
)
FALLBACK_OPTIMIZED_WARNING_MESSAGE = (
    'Rota servisi (ORS) yanıt vermedi; güzergâh ve sıra optimizasyonu '
    'google-static fallback ile hesaplandı.'
)


@dataclass
class GoogleOptimizedResult:
    """Tek çağrıyla elde edilen mevcut + optimize rota çifti."""
    current_route: RouteResult       # mevcut stop sırasıyla çizgi + km/süre
    suggested_route: RouteResult     # optimize sırayla çizgi + km/süre
    optimized_stop_indices: list[int]  # intermediate stops yeni sıra (0-based, input sırasına göre)
    order_changed: bool


def decode_polyline(encoded: str | None) -> list[list[float]]:
    """Google encoded polyline → [[lat, lng], ...] (RouteResult.geometry biçimi)."""
    if not encoded:
        return []
    points: list[list[float]] = []
    index = 0
    lat = lng = 0
    length = len(encoded)
    while index < length:
        shift = result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += ~(result >> 1) if (result & 1) else (result >> 1)
        shift = result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lng += ~(result >> 1) if (result & 1) else (result >> 1)
        points.append([lat / 1e5, lng / 1e5])
    return points


def fallback_available() -> bool:
    return google_provider_available()


def _google_result_to_route_result(result: GoogleRouteResult) -> RouteResult:
    geometry = decode_polyline(result.encoded_polyline)
    return RouteResult(
        provider=PROVIDER_NAME,
        profile=PROFILE_STATIC,
        distance_m=result.distance_m,
        duration_s=result.drive_seconds,
        geometry=geometry,
        legs=[
            RouteLeg(
                from_index=lg.from_index,
                to_index=lg.to_index,
                distance_m=lg.distance_m,
                duration_s=lg.drive_seconds,
            )
            for lg in result.legs
        ],
        raw_status='OK_GOOGLE_STATIC_FALLBACK',
    )


def route_via_google_static(points: Sequence[tuple[float, float]]) -> RouteResult:
    """TRAFFIC_UNAWARE tek çağrı (mevcut sıra) → RouteResult(provider='google-static')."""
    prov = GoogleRoutesProvider(profile=PROFILE_STATIC)
    result = prov.route_google(list(points))
    route = _google_result_to_route_result(result)
    if len(route.geometry) < 2:
        raise RoutingError('Google Static güzergâh çizgisi yetersiz.', code='NO_ROUTE')
    return route


def route_via_google_optimized(
    points: Sequence[tuple[float, float]],
) -> GoogleOptimizedResult:
    """optimizeWaypointOrder=true ile tek Google Static çağrısı.

    Döndürür:
        current_route   — giriş sırasıyla mevcut rota (optimize edilmemiş).
        suggested_route — Google'ın önerdiği sırayla yeniden hesaplanmış rota.
        optimized_stop_indices — [i0, i1, ...] ara durak yeni sıra (0=ilk intermediate).
        order_changed   — sıra değiştiyse True.

    Sadece 2 intermediate ve üzeri için optimize anlamlıdır.
    1 intermediate'te Google zaten tek sıra döner; order_changed=False olur.
    """
    pts = list(points)
    if len(pts) < 2:
        raise RoutingError('En az iki nokta gerekli.', code='NO_ROUTE')

    key = (os.environ.get('GOOGLE_ROUTES_API_KEY') or '').strip()
    if not key:
        raise RoutingError('GOOGLE_ROUTES_API_KEY yapılandırılmamış.', code='UNCONFIGURED')

    timeout = _timeout_sec()
    intermediates = pts[1:-1]  # duraklar (base ve dönüş base hariç)

    # ── 1. Optimize çağrı (optimizeWaypointOrder=true) ───────────────────────
    body_opt: dict = {
        'origin': _waypoint(*pts[0]),
        'destination': _waypoint(*pts[-1]),
        'travelMode': 'DRIVE',
        'routingPreference': 'TRAFFIC_UNAWARE',
        'optimizeWaypointOrder': True,
        'computeAlternativeRoutes': False,
        'languageCode': 'tr',
        'regionCode': 'TR',
        'units': 'METRIC',
        'routeModifiers': {
            'avoidFerries': True,
            'avoidTolls': False,
            'avoidHighways': False,
        },
    }
    if intermediates:
        body_opt['intermediates'] = [_waypoint(*p) for p in intermediates]

    raw_opt = _post_routes(body_opt, key, timeout)
    result_opt = _parse_google_route(raw_opt, PROFILE_STATIC)

    opt_indices = list(result_opt.optimized_waypoint_indices)
    original_indices = list(range(len(intermediates)))
    order_changed = bool(intermediates) and (opt_indices != original_indices)

    suggested_route = _google_result_to_route_result(result_opt)
    if len(suggested_route.geometry) < 2 and len(pts) >= 2:
        raise RoutingError('Google Static optimize rota çizgisi yetersiz.', code='NO_ROUTE')

    # ── 2. Mevcut sırayla çağrı (optimizeWaypointOrder=false) ────────────────
    # Yalnız sıra değiştiyse ikinci çağrı gerekir; değişmediyse current==suggested.
    if order_changed:
        body_cur: dict = {
            'origin': _waypoint(*pts[0]),
            'destination': _waypoint(*pts[-1]),
            'travelMode': 'DRIVE',
            'routingPreference': 'TRAFFIC_UNAWARE',
            'optimizeWaypointOrder': False,
            'computeAlternativeRoutes': False,
            'languageCode': 'tr',
            'regionCode': 'TR',
            'units': 'METRIC',
            'routeModifiers': {
                'avoidFerries': True,
                'avoidTolls': False,
                'avoidHighways': False,
            },
        }
        if intermediates:
            body_cur['intermediates'] = [_waypoint(*p) for p in intermediates]
        raw_cur = _post_routes(body_cur, key, timeout)
        result_cur = _parse_google_route(raw_cur, PROFILE_STATIC)
        current_route = _google_result_to_route_result(result_cur)
    else:
        # Sıra aynı → mevcut = önerilen (tek çağrı yeterli).
        current_route = suggested_route

    return GoogleOptimizedResult(
        current_route=current_route,
        suggested_route=suggested_route,
        optimized_stop_indices=opt_indices,
        order_changed=order_changed,
    )

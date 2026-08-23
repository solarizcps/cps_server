# -*- coding: utf-8 -*-
"""Deterministic mock provider for ROUTE14B tests."""
from __future__ import annotations

import math
from typing import Sequence

from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.types import RouteLeg, RouteMatrix, RouteResult, RoutingError


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(x))


class MockRoadRoutingProvider(RoadRoutingProvider):
    """Test double — returns deterministic road-like metrics (not straight-line labeled as road)."""

    name = 'mock'
    profile = 'driving-car'
    road_factor = 1.35
    speed_mps = 12.0

    def route_ordered(self, points: Sequence[tuple[float, float]]) -> RouteResult:
        if len(points) < 2:
            raise RoutingError('En az iki nokta gerekli.', code='NO_ROUTE')
        legs: list[RouteLeg] = []
        total_d = 0.0
        total_t = 0.0
        geometry: list[list[float]] = [[points[0][0], points[0][1]]]
        for i in range(len(points) - 1):
            d = _haversine_m(points[i], points[i + 1]) * self.road_factor
            t = d / self.speed_mps
            legs.append(RouteLeg(from_index=i, to_index=i + 1, distance_m=d, duration_s=t))
            total_d += d
            total_t += t
            geometry.append([points[i + 1][0], points[i + 1][1]])
        return RouteResult(
            provider=self.name,
            profile=self.profile,
            distance_m=total_d,
            duration_s=total_t,
            geometry=geometry,
            legs=legs,
        )

    def matrix(self, points: Sequence[tuple[float, float]]) -> RouteMatrix:
        n = len(points)
        dist = [[None] * n for _ in range(n)]
        dur = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    dist[i][j] = 0.0
                    dur[i][j] = 0.0
                else:
                    d = _haversine_m(points[i], points[j]) * self.road_factor
                    dist[i][j] = d
                    dur[i][j] = d / self.speed_mps
        return RouteMatrix(provider=self.name, profile=self.profile, distance_m=dist, duration_s=dur)

# -*- coding: utf-8 -*-
"""RoadRoutingProvider contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from modules.planlama.road_routing.types import RouteMatrix, RouteResult


class RoadRoutingProvider(ABC):
    """Provider boundary — normalized lat/lng points in, normalized DTO out."""

    name: str = 'base'
    profile: str = 'driving-car'

    @abstractmethod
    def route_ordered(self, points: Sequence[tuple[float, float]]) -> RouteResult:
        """points: [(lat, lng), ...] in visit order."""

    @abstractmethod
    def matrix(self, points: Sequence[tuple[float, float]]) -> RouteMatrix:
        """Full NxN road matrix for points."""

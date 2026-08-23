# -*- coding: utf-8 -*-
"""Normalized road routing DTOs — provider-agnostic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteLeg:
    from_index: int
    to_index: int
    distance_m: float
    duration_s: float


@dataclass
class RouteMatrix:
    provider: str
    profile: str
    distance_m: list[list[float | None]]
    duration_s: list[list[float | None]]


@dataclass
class RouteResult:
    provider: str
    profile: str
    distance_m: float
    duration_s: float
    geometry: list[list[float]]  # [[lat, lng], ...]
    legs: list[RouteLeg] = field(default_factory=list)
    raw_status: str = 'OK'

    def to_dict(self) -> dict[str, Any]:
        return {
            'provider': self.provider,
            'profile': self.profile,
            'distance_m': self.distance_m,
            'duration_s': self.duration_s,
            'geometry': self.geometry,
            'legs': [
                {
                    'from_index': lg.from_index,
                    'to_index': lg.to_index,
                    'distance_m': lg.distance_m,
                    'duration_s': lg.duration_s,
                }
                for lg in self.legs
            ],
        }


class RoutingError(Exception):
    """Provider routing failure."""

    def __init__(self, message: str, code: str = 'ERROR', http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

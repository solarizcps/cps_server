# -*- coding: utf-8 -*-
"""DTO models for ATP Google Route Options orchestration.

These are pure data classes — no DB, no HTTP, no Flask dependencies.
JSON-serializable via dataclasses.asdict().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoogleRouteLegDTO:
    from_index: int
    to_index: int
    distance_m: float
    distance_km_display: float
    drive_seconds: float
    static_seconds: float
    drive_minutes_display: int
    toll_present: bool


@dataclass
class GoogleRouteOptionDTO:
    """Single profile result (En Hızlı OR Ücretsiz Yol) for one stop order."""
    profile_code: str                    # 'google-traffic-fast' | 'google-traffic-free'
    profile_label: str                   # 'En Hızlı' | 'Ücretsiz Yol'
    ordered_stop_ids: list[str]
    ordered_stop_names: list[str]
    distance_m: float
    distance_km_display: float
    drive_seconds: float
    static_drive_seconds: float
    traffic_delay_seconds: float
    service_seconds: float
    total_plan_seconds: float
    drive_minutes_display: int
    traffic_delay_minutes_display: int
    total_plan_minutes_display: int
    return_exact: str                    # ISO8601 with tz
    return_display: str                  # 'HH:MM'
    toll_present: bool
    toll_price_known: bool
    toll_price: Any                      # None or monetary dict
    encoded_polyline: str | None
    legs: list[GoogleRouteLegDTO]
    calculation_complete: bool
    error_code: str | None


@dataclass
class GoogleRouteOrderDTO:
    """Results for one stop ordering (current or suggested)."""
    order: list[str]                     # task IDs in visit order
    fastest: GoogleRouteOptionDTO | None
    toll_free: GoogleRouteOptionDTO | None


@dataclass
class GoogleRouteOptionsDTO:
    """Top-level DTO returned by the orchestration service."""
    provider: str                        # always 'google-routes'
    departure_time: str                  # 'HH:MM' local
    timezone: str                        # 'Europe/Istanbul'
    plan_date: str                       # 'YYYY-MM-DD'
    service_minutes_per_stop: int        # 10
    active_stop_count: int
    order_changed: bool
    route_reorder_available: bool
    # ── Call counters ──────────────────────────────────────────────────────────
    google_attempt_count: int            # total requests sent to Google (success + failure)
    google_success_count: int            # requests that returned a valid route
    google_failure_count: int            # requests that raised RoutingError / HTTP error
    # Legacy alias — same value as google_attempt_count (deprecated, keep for compat)
    google_call_count: int               # deprecated: use google_attempt_count
    # ── Route results ─────────────────────────────────────────────────────────
    current: GoogleRouteOrderDTO
    suggested: GoogleRouteOrderDTO

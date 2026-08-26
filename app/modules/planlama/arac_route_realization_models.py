# -*- coding: utf-8 -*-
"""DTO models for planned vs actual route realization (ATP engine v1)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from modules.planlama.arac_geofence_service import CONFIRM_INSIDE as STOP_ENTER_CONFIRM_POINTS
from modules.planlama.arac_geofence_service import ENTER_M as STOP_ENTER_M
from modules.planlama.arac_rota_deviation_service import (
    CONFIRM_OUTSIDE as DEVIATION_CONFIRM_POINTS,
    DEVIATION_M,
    ON_ROUTE_M,
)

STOP_EXIT_M = 300.0
STOP_EXIT_CONFIRM_POINTS = 2
DATA_GAP_SECONDS = 180
GPS_JUMP_SPEED_KMH = 180.0
BASE_ENTER_M = STOP_ENTER_M
IGNITION_OFF_DWELL_SECONDS = 300

TRIP_PRE_DEPARTURE_MINUTES = 15
TRIP_RETURN_BUFFER_MINUTES = 120
GAP_MEDIUM_THRESHOLD_SECONDS = 300
GAP_LOW_THRESHOLD_SECONDS = 900
CRITICAL_GAP_COUNT = 3
EXPECTED_GPS_INTERVAL_SECONDS = 60

QUALITY_HIGH = 'HIGH'
QUALITY_MEDIUM = 'MEDIUM'
QUALITY_LOW = 'LOW'

BASE_SOURCE_OPERATION = 'OPERATION_SETTINGS'
BASE_SOURCE_ROUTE_GEOMETRY = 'ROUTE_GEOMETRY_START'
BASE_SOURCE_EXPLICIT = 'EXPLICIT'

FLAG_DATA_GAP = 'DATA_GAP'
FLAG_LOW_POINT_COUNT = 'LOW_POINT_COUNT'
FLAG_STALE_POINTS = 'STALE_POINTS'
FLAG_NO_GPS = 'NO_GPS'
FLAG_NO_ROUTE = 'NO_ROUTE'
FLAG_SHORT_COVERAGE = 'SHORT_COVERAGE'
FLAG_IGNITION_OFF_DWELL = 'IGNITION_OFF_DWELL'
FLAG_GPS_JUMP = 'GPS_JUMP'
FLAG_EXCESSIVE_GAPS = 'EXCESSIVE_GAPS'
FLAG_CRITICAL_GAP = 'CRITICAL_GAP'

REASON_DEPARTURE_NOT_DETECTED = 'DEPARTURE_NOT_DETECTED'
REASON_RETURN_NOT_DETECTED = 'RETURN_NOT_DETECTED'
REASON_LOW_DATA_QUALITY = 'LOW_DATA_QUALITY'
REASON_CRITICAL_DATA_GAP = 'CRITICAL_DATA_GAP'
REASON_NO_GPS_FOR_TRIP = 'NO_GPS_FOR_TRIP_WINDOW'
REASON_ROUTE_GEOMETRY_MISSING = 'ROUTE_GEOMETRY_MISSING'


@dataclass
class DataQualityDTO:
    level: str
    confidence: float
    gps_point_count: int = 0
    data_gap_count: int = 0
    max_gap_seconds: float = 0.0
    stale_point_count: int = 0
    ignition_off_dwell_count: int = 0
    coverage_ratio: float | None = None
    expected_point_count: int | None = None
    observed_point_count: int = 0
    gps_jump_count: int = 0
    flags: list[str] = field(default_factory=list)


@dataclass
class RouteSummaryDTO:
    distance_m: float = 0.0
    duration_s: float = 0.0
    start_at: str | None = None
    end_at: str | None = None


@dataclass
class StopRealizationDTO:
    plan_item_id: str | int | None
    order_no: int | None
    company_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    planned_eta_at: str | None = None
    planned_time: str | None = None
    actual_arrival_at: str | None = None
    actual_departure_at: str | None = None
    eta_delta_seconds: float | None = None
    visit_status: str = 'PENDING'
    actual_visit_sequence: int | None = None


@dataclass
class DeviationEpisodeDTO:
    started_at: str
    ended_at: str | None
    max_deviation_m: float
    duration_s: float = 0.0


@dataclass
class RouteRealizationDTO:
    plan_id: int
    vehicle_id: str
    plan_date: str
    comparison_complete: bool
    incomplete_reasons: list[str] = field(default_factory=list)
    data_quality: DataQualityDTO = field(default_factory=lambda: DataQualityDTO(QUALITY_LOW, 0.0))
    planned_summary: RouteSummaryDTO = field(default_factory=RouteSummaryDTO)
    actual_summary: RouteSummaryDTO = field(default_factory=RouteSummaryDTO)
    stops: list[StopRealizationDTO] = field(default_factory=list)
    deviations: list[DeviationEpisodeDTO] = field(default_factory=list)
    actual_geometry: dict[str, Any] = field(default_factory=lambda: {
        'type': 'MultiLineString',
        'coordinates': [],
        'crs': 'WGS84',
    })
    factory_departure_at: str | None = None
    factory_return_at: str | None = None
    base_coordinate_source: str | None = None
    trip_window_start_at: str | None = None
    trip_window_end_at: str | None = None
    excluded_gps_point_count: int = 0
    actual_stop_order: list[str | int] = field(default_factory=list)
    skipped_stop_ids: list[str | int] = field(default_factory=list)
    wrong_order_stop_ids: list[str | int] = field(default_factory=list)
    max_deviation_m: float = 0.0
    deviation_time_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

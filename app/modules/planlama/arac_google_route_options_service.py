# -*- coding: utf-8 -*-
"""ATP Google Route Options Orchestration Service.

Calculates En Hızlı / Ücretsiz Yol Google route options for current and
suggested stop orderings.  ORS is NOT used here.

Call contract:
  compute_google_route_options(
      plan_date='2026-08-27',
      departure_hhmm='08:00',
      base={'latitude': ..., 'longitude': ..., 'has_coordinates': True},
      tasks=[{id, order_no, status, priority, company_name,
              latitude, longitude, has_coordinates, ...}],
      api_key=None,        # reads from env if None
      departure_utc=None,  # auto-derived from plan_date+departure_hhmm if None
  ) -> GoogleRouteOptionsDTO

Call count rule:
  current_order == suggested_order → 2 Google calls
  current_order != suggested_order → 4 Google calls
  Static profile is NEVER called.
  No auto-retry.

Failure policy:
  - If a single profile fails → calculation_complete=False, error_code set.
  - The other profile result is still returned.
  - ORS is NEVER used as fallback — no silent substitution.

Timing rules (arac_timeline_service.py canonical):
  service_seconds = stop_count × 600
  total_plan_seconds = route.drive_seconds + service_seconds
  return_exact = departure_exact + total_plan_seconds  (no rounding)
  return_display = ceil(return_exact to next minute)
  drive_minutes_display = ceil(drive_seconds / 60)
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from modules.planlama.arac_google_route_options_models import (
    GoogleRouteLegDTO,
    GoogleRouteOptionDTO,
    GoogleRouteOrderDTO,
    GoogleRouteOptionsDTO,
)
from modules.planlama.arac_route_constraints import (
    INACTIVE_PLAN_STATUSES,
    active_tasks_sorted,
    classify_route_tasks,
)
from modules.planlama.road_routing.google_routes_provider import (
    PROFILE_TRAFFIC_FAST,
    PROFILE_TRAFFIC_FREE,
    GoogleRoutesProvider,
    GoogleRouteResult,
    departure_utc_from_local,
)
from modules.planlama.road_routing.types import RoutingError

_log = logging.getLogger(__name__)

_TZ = ZoneInfo('Europe/Istanbul')
_SERVICE_MINUTES = 10
_SERVICE_SECONDS_PER_STOP = _SERVICE_MINUTES * 60

_PROFILE_LABELS = {
    PROFILE_TRAFFIC_FAST: 'En Hızlı',
    PROFILE_TRAFFIC_FREE: 'Ücretsiz Yol',
}


# ── Timing helpers ────────────────────────────────────────────────────────────

def _ceil_min(seconds: float) -> int:
    return math.ceil(seconds / 60)


def _parse_departure(plan_date: str, hhmm: str) -> datetime:
    """'2026-08-27', '08:00' → timezone-aware datetime."""
    s = hhmm.strip()[:5]
    h, m = int(s[:2]), int(s[3:5])
    naive = datetime(int(plan_date[:4]), int(plan_date[5:7]), int(plan_date[8:10]), h, m, 0)
    return naive.replace(tzinfo=_TZ)


def _return_display(dep: datetime, drive_s: float, service_s: float) -> tuple[str, str]:
    """Returns (return_exact_iso, return_display_hhmm)."""
    total_s = drive_s + service_s
    ret = dep + timedelta(seconds=total_s)
    local = ret.astimezone(_TZ)
    if local.second > 0 or local.microsecond > 0:
        display_dt = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    else:
        display_dt = local
    return ret.isoformat(), display_dt.strftime('%H:%M')


def _auto_departure_utc(plan_date: str, hhmm: str) -> str:
    dep = _parse_departure(plan_date, hhmm)
    return departure_utc_from_local(dep.isoformat())


# ── Stop ordering helpers ─────────────────────────────────────────────────────

def _build_route_points(
    base: dict,
    stops: list[dict],
) -> list[tuple[float, float]]:
    """base + stops + base (round-trip)."""
    pts: list[tuple[float, float]] = [(float(base['latitude']), float(base['longitude']))]
    for s in stops:
        pts.append((float(s['latitude']), float(s['longitude'])))
    pts.append((float(base['latitude']), float(base['longitude'])))
    return pts


def _suggested_order(
    active_tasks: list[dict],
    base: dict,
) -> list[dict]:
    """Use CPS constraint + matrix-free ordering for the suggested order.
    Falls back to current order if matrix (ORS) is unavailable.
    Google waypoint optimization is NEVER used.
    Returns tasks in suggested visit order.
    """
    constraints = classify_route_tasks(active_tasks)
    eligible_ids = set(constraints.get('eligible_task_ids') or [])
    if len(eligible_ids) < 2:
        return list(active_tasks)

    # Without a matrix we can only preserve current order.
    # A future phase can inject an ORS matrix here if desired.
    # The orchestration layer is responsible for providing the matrix.
    return list(active_tasks)


# ── Single-profile option builder ────────────────────────────────────────────

def _build_option(
    google_result: GoogleRouteResult,
    ordered_stops: list[dict],
    departure_dt: datetime,
    service_s: float,
) -> GoogleRouteOptionDTO:
    stop_ids = [str(s['id']) for s in ordered_stops]
    stop_names = [s.get('company_name') or '—' for s in ordered_stops]

    drive_s = google_result.drive_seconds
    total_s = drive_s + service_s

    ret_exact, ret_display = _return_display(departure_dt, drive_s, service_s)
    traffic_delay_s = google_result.traffic_delta_seconds

    legs_dto = [
        GoogleRouteLegDTO(
            from_index=lg.from_index,
            to_index=lg.to_index,
            distance_m=lg.distance_m,
            distance_km_display=round(lg.distance_m / 1000.0, 1),
            drive_seconds=lg.drive_seconds,
            static_seconds=lg.static_seconds,
            drive_minutes_display=_ceil_min(lg.drive_seconds),
            toll_present=lg.toll_info is not None,
        )
        for lg in google_result.legs
    ]

    toll_info = google_result.toll_info
    toll_price_known = bool(
        toll_info and toll_info.get('estimatedPrice')
    )

    return GoogleRouteOptionDTO(
        profile_code=google_result.profile,
        profile_label=google_result.profile_label,
        ordered_stop_ids=stop_ids,
        ordered_stop_names=stop_names,
        distance_m=google_result.distance_m,
        distance_km_display=google_result.distance_km,
        drive_seconds=drive_s,
        static_drive_seconds=google_result.static_seconds,
        traffic_delay_seconds=traffic_delay_s,
        service_seconds=service_s,
        total_plan_seconds=total_s,
        drive_minutes_display=_ceil_min(drive_s),
        traffic_delay_minutes_display=_ceil_min(traffic_delay_s) if traffic_delay_s > 0 else 0,
        total_plan_minutes_display=_ceil_min(total_s),
        return_exact=ret_exact,
        return_display=ret_display,
        toll_present=google_result.toll_present,
        toll_price_known=toll_price_known,
        toll_price=toll_info.get('estimatedPrice') if toll_price_known else None,
        encoded_polyline=google_result.encoded_polyline,
        legs=legs_dto,
        calculation_complete=True,
        error_code=None,
    )


def _failed_option(
    profile_code: str,
    error_code: str,
    ordered_stops: list[dict],
) -> GoogleRouteOptionDTO:
    """Return a sentinel DTO for a failed Google call — never silently substitute ORS."""
    stop_ids = [str(s['id']) for s in ordered_stops]
    stop_names = [s.get('company_name') or '—' for s in ordered_stops]
    return GoogleRouteOptionDTO(
        profile_code=profile_code,
        profile_label=_PROFILE_LABELS.get(profile_code, profile_code),
        ordered_stop_ids=stop_ids,
        ordered_stop_names=stop_names,
        distance_m=0.0,
        distance_km_display=0.0,
        drive_seconds=0.0,
        static_drive_seconds=0.0,
        traffic_delay_seconds=0.0,
        service_seconds=0.0,
        total_plan_seconds=0.0,
        drive_minutes_display=0,
        traffic_delay_minutes_display=0,
        total_plan_minutes_display=0,
        return_exact='',
        return_display='—',
        toll_present=False,
        toll_price_known=False,
        toll_price=None,
        encoded_polyline=None,
        legs=[],
        calculation_complete=False,
        error_code=error_code,
    )


# ── Call counters ─────────────────────────────────────────────────────────────

class _Counters:
    """Mutable call counters passed through _calc_order calls."""
    __slots__ = ('attempt', 'success', 'failure')

    def __init__(self) -> None:
        self.attempt = 0
        self.success = 0
        self.failure = 0


# ── Per-order two-profile calculator ─────────────────────────────────────────

def _calc_order(
    ordered_stops: list[dict],
    base: dict,
    departure_dt: datetime,
    departure_utc: str,
    service_s: float,
    api_key: str | None,
    counters: _Counters,
) -> tuple[GoogleRouteOptionDTO, GoogleRouteOptionDTO]:
    """Compute En Hızlı + Ücretsiz Yol for a given stop order.
    Returns (fastest_dto, toll_free_dto).

    Counters updated:
      attempt +1 before every route_google() call
      success +1 on successful parse
      failure +1 on any RoutingError
    """
    pts = _build_route_points(base, ordered_stops)

    def _call(profile: str) -> GoogleRouteOptionDTO:
        counters.attempt += 1
        try:
            prov = GoogleRoutesProvider(
                profile=profile,
                departure_utc=departure_utc,
                api_key=api_key,
            )
            result: GoogleRouteResult = prov.route_google(pts)
            counters.success += 1
            return _build_option(result, ordered_stops, departure_dt, service_s)
        except RoutingError as exc:
            counters.failure += 1
            _log.warning('Google Routes [%s] failed: %s', profile, exc.code)
            return _failed_option(profile, exc.code or 'GOOGLE_ROUTE_UNAVAILABLE', ordered_stops)

    fastest = _call(PROFILE_TRAFFIC_FAST)
    toll_free = _call(PROFILE_TRAFFIC_FREE)
    return fastest, toll_free


# ── Main public function ──────────────────────────────────────────────────────

def compute_google_route_options(
    *,
    plan_date: str,
    departure_hhmm: str,
    base: dict,
    tasks: list[dict],
    api_key: str | None = None,
    departure_utc: str | None = None,
    _suggested_order_fn=None,    # injectable for tests
) -> GoogleRouteOptionsDTO:
    """Compute En Hızlı / Ücretsiz Yol options for current and (if different) suggested order.

    Parameters:
        plan_date       — 'YYYY-MM-DD'
        departure_hhmm  — 'HH:MM' local Europe/Istanbul
        base            — {'latitude', 'longitude', 'has_coordinates': True}
        tasks           — full task list including inactive
        api_key         — if None, read from GOOGLE_ROUTES_API_KEY env
        departure_utc   — if None, auto-derived from plan_date + departure_hhmm
        _suggested_order_fn — inject alternate ordering function for tests
    """
    dep_utc = departure_utc or _auto_departure_utc(plan_date, departure_hhmm)
    dep_dt = _parse_departure(plan_date, departure_hhmm)

    active = active_tasks_sorted(tasks)
    routable = [
        t for t in active
        if t.get('has_coordinates')
        and t.get('latitude') is not None
        and t.get('longitude') is not None
    ]

    stop_count = len(routable)
    service_s = float(stop_count * _SERVICE_SECONDS_PER_STOP)

    constraints = classify_route_tasks(active)
    eligible_count = len(constraints.get('eligible_task_ids') or [])
    route_reorder_available = eligible_count >= 2

    # Build current order
    current_stops = list(routable)

    # Build suggested order via CPS logic (Google optimization NOT used)
    _sug_fn = _suggested_order_fn or _suggested_order
    suggested_stops = _sug_fn(active, base)
    # Limit suggested to routable stops preserving their order
    routable_ids = [str(t['id']) for t in routable]
    suggested_stops = [
        t for t in suggested_stops
        if str(t.get('id')) in set(routable_ids)
        and t.get('has_coordinates')
        and t.get('latitude') is not None
        and t.get('longitude') is not None
    ]

    current_ids = [str(t['id']) for t in current_stops]
    suggested_ids = [str(t['id']) for t in suggested_stops]
    order_changed = current_ids != suggested_ids

    counters = _Counters()

    # current order → 2 attempts
    curr_fast, curr_free = _calc_order(
        current_stops, base, dep_dt, dep_utc, service_s, api_key, counters,
    )

    if order_changed:
        # suggested order → 2 more attempts
        sug_fast, sug_free = _calc_order(
            suggested_stops, base, dep_dt, dep_utc, service_s, api_key, counters,
        )
    else:
        # reuse current results — same route, no extra Google calls
        sug_fast, sug_free = curr_fast, curr_free

    return GoogleRouteOptionsDTO(
        provider='google-routes',
        departure_time=departure_hhmm,
        timezone='Europe/Istanbul',
        plan_date=plan_date,
        service_minutes_per_stop=_SERVICE_MINUTES,
        active_stop_count=stop_count,
        order_changed=order_changed,
        route_reorder_available=route_reorder_available,
        google_attempt_count=counters.attempt,
        google_success_count=counters.success,
        google_failure_count=counters.failure,
        google_call_count=counters.attempt,   # legacy alias
        current=GoogleRouteOrderDTO(
            order=current_ids,
            fastest=curr_fast,
            toll_free=curr_free,
        ),
        suggested=GoogleRouteOrderDTO(
            order=suggested_ids,
            fastest=sug_fast,
            toll_free=sug_free,
        ),
    )

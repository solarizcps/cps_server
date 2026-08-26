# -*- coding: utf-8 -*-
"""Planned vs actual route realization engine — offline replay over GPS snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from modules.planlama.arac_geo_distance import haversine_m, point_to_linestring_distance_m
from modules.planlama.arac_gps_poll_service import GPS_TIMESTAMP_FMT, parse_gps_timestamp
from modules.planlama.arac_route_geometry import geometry_from_storage
from modules.planlama.arac_route_realization_models import (
    BASE_ENTER_M,
    BASE_SOURCE_EXPLICIT,
    BASE_SOURCE_OPERATION,
    BASE_SOURCE_ROUTE_GEOMETRY,
    CRITICAL_GAP_COUNT,
    DATA_GAP_SECONDS,
    DEVIATION_CONFIRM_POINTS,
    EXPECTED_GPS_INTERVAL_SECONDS,
    FLAG_CRITICAL_GAP,
    FLAG_DATA_GAP,
    FLAG_EXCESSIVE_GAPS,
    FLAG_GPS_JUMP,
    FLAG_IGNITION_OFF_DWELL,
    FLAG_LOW_POINT_COUNT,
    FLAG_NO_GPS,
    FLAG_NO_ROUTE,
    FLAG_SHORT_COVERAGE,
    FLAG_STALE_POINTS,
    GAP_LOW_THRESHOLD_SECONDS,
    GAP_MEDIUM_THRESHOLD_SECONDS,
    GPS_JUMP_SPEED_KMH,
    IGNITION_OFF_DWELL_SECONDS,
    QUALITY_HIGH,
    QUALITY_LOW,
    QUALITY_MEDIUM,
    REASON_CRITICAL_DATA_GAP,
    REASON_DEPARTURE_NOT_DETECTED,
    REASON_LOW_DATA_QUALITY,
    REASON_NO_GPS_FOR_TRIP,
    REASON_RETURN_NOT_DETECTED,
    REASON_ROUTE_GEOMETRY_MISSING,
    STOP_ENTER_CONFIRM_POINTS,
    STOP_ENTER_M,
    STOP_EXIT_CONFIRM_POINTS,
    STOP_EXIT_M,
    TRIP_PRE_DEPARTURE_MINUTES,
    TRIP_RETURN_BUFFER_MINUTES,
    DataQualityDTO,
    DeviationEpisodeDTO,
    RouteRealizationDTO,
    RouteSummaryDTO,
    StopRealizationDTO,
)
from modules.planlama.arac_rota_deviation_service import DEVIATION_M, ON_ROUTE_M


@dataclass
class _TripWindow:
    rows: list[dict]
    departure_at: str | None
    departure_verified: bool
    return_at: str | None
    return_verified: bool
    window_start_at: str | None
    window_end_at: str | None
    excluded_count: int


def _parse_departure(plan_date: str, cikis_saati: str | None) -> datetime | None:
    if not cikis_saati:
        return None
    text = cikis_saati.strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            t = datetime.strptime(text, fmt)
            return datetime.strptime(plan_date, '%Y-%m-%d').replace(
                hour=t.hour, minute=t.minute, second=t.second,
            )
        except ValueError:
            continue
    return None


def _stop_distance_m(lat: float, lon: float, stop: dict) -> float | None:
    slat = stop.get('latitude')
    slon = stop.get('longitude')
    if slat is None or slon is None:
        return None
    return haversine_m(lat, lon, float(slat), float(slon))


def _normalize_gps_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        ts = parse_gps_timestamp(row.get('gps_timestamp') or '')
        if ts is None:
            continue
        try:
            lat = float(row['latitude'])
            lon = float(row['longitude'])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            'id': row.get('id'),
            'gps_timestamp': ts.strftime(GPS_TIMESTAMP_FMT),
            '_dt': ts,
            'latitude': lat,
            'longitude': lon,
            'speed_kmh': row.get('speed_kmh'),
            'ignition_status': row.get('ignition_status'),
            'is_stale': bool(row.get('is_stale')),
        })
    out.sort(key=lambda r: (r['_dt'], r.get('id') or 0))
    return out


def _filter_gps_by_plan_dates(rows: list[dict], plan_date: str) -> list[dict]:
    if not rows:
        return []
    plan_day = datetime.strptime(plan_date, '%Y-%m-%d').date()
    next_day = plan_day + timedelta(days=1)
    return [r for r in rows if r['_dt'].date() in (plan_day, next_day)]


def _implied_speed_kmh(a: dict, b: dict) -> float:
    dist_m = haversine_m(a['latitude'], a['longitude'], b['latitude'], b['longitude'])
    dt_s = (b['_dt'] - a['_dt']).total_seconds()
    if dt_s <= 0:
        return float('inf')
    return (dist_m / dt_s) * 3.6


def _segment_by_gaps_and_jumps(
    rows: list[dict],
    gap_seconds: int = DATA_GAP_SECONDS,
) -> tuple[list[list[dict]], int, int]:
    if not rows:
        return [], 0, 0
    segments: list[list[dict]] = [[rows[0]]]
    gap_count = 0
    jump_count = 0
    for prev, cur in zip(rows, rows[1:]):
        delta = (cur['_dt'] - prev['_dt']).total_seconds()
        speed = _implied_speed_kmh(prev, cur)
        if speed > GPS_JUMP_SPEED_KMH:
            jump_count += 1
            segments.append([cur])
        elif delta > gap_seconds:
            gap_count += 1
            segments.append([cur])
        else:
            segments[-1].append(cur)
    return segments, gap_count, jump_count


def _segment_distance_m(segment: list[dict]) -> float:
    total = 0.0
    for a, b in zip(segment, segment[1:]):
        if _implied_speed_kmh(a, b) > GPS_JUMP_SPEED_KMH:
            continue
        total += haversine_m(a['latitude'], a['longitude'], b['latitude'], b['longitude'])
    return total


def _build_multiline_geometry(segments: list[list[dict]]) -> dict[str, Any]:
    coords: list[list[list[float]]] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        line = [[round(r['longitude'], 6), round(r['latitude'], 6)] for r in segment]
        coords.append(line)
    return {'type': 'MultiLineString', 'coordinates': coords, 'crs': 'WGS84'}


def _classify_points(rows: list[dict], route_coords: list[list[float]]) -> list[dict]:
    classified: list[dict] = []
    for i, row in enumerate(rows):
        dist = point_to_linestring_distance_m(row['latitude'], row['longitude'], route_coords)
        if dist is None:
            dist = float('inf')
        dt_seconds = 0.0
        if i > 0:
            dt_seconds = (row['_dt'] - rows[i - 1]['_dt']).total_seconds()
        classified.append({**row, 'dist_to_route': dist, 'dt_seconds': dt_seconds})
    return classified


def _detect_deviations(classified: list[dict]) -> tuple[list[DeviationEpisodeDTO], float, float]:
    episodes: list[DeviationEpisodeDTO] = []
    consecutive_high = 0
    in_deviation = False
    episode_start: str | None = None
    episode_max = 0.0
    episode_time_s = 0.0
    global_max = 0.0
    total_dev_time = 0.0
    streak_start_idx: int | None = None

    def _close_episode(end_ts: str) -> None:
        nonlocal in_deviation, episode_start, episode_max, episode_time_s
        if not in_deviation or episode_start is None:
            return
        episodes.append(DeviationEpisodeDTO(
            started_at=episode_start,
            ended_at=end_ts,
            max_deviation_m=round(episode_max, 1),
            duration_s=round(episode_time_s, 1),
        ))
        in_deviation = False
        episode_start = None
        episode_max = 0.0
        episode_time_s = 0.0

    for i, pt in enumerate(classified):
        d = pt['dist_to_route']
        dt = pt['dt_seconds']
        ts = pt['gps_timestamp']

        if d >= DEVIATION_M:
            if streak_start_idx is None:
                streak_start_idx = i
            consecutive_high += 1
            if consecutive_high >= DEVIATION_CONFIRM_POINTS:
                if not in_deviation:
                    in_deviation = True
                    episode_start = classified[streak_start_idx]['gps_timestamp']
                    episode_max = d
                else:
                    episode_max = max(episode_max, d)
                    episode_time_s += dt
                    global_max = max(global_max, d)
                    total_dev_time += dt
            continue

        if in_deviation:
            if d <= ON_ROUTE_M:
                _close_episode(ts)
            else:
                episode_max = max(episode_max, d)
                episode_time_s += dt
                global_max = max(global_max, d)
                total_dev_time += dt

        consecutive_high = 0
        streak_start_idx = None

    if in_deviation and episode_start:
        last_ts = classified[-1]['gps_timestamp']
        episodes.append(DeviationEpisodeDTO(
            started_at=episode_start,
            ended_at=last_ts,
            max_deviation_m=round(episode_max, 1),
            duration_s=round(episode_time_s, 1),
        ))
        global_max = max(global_max, episode_max)
        total_dev_time += episode_time_s

    return episodes, round(global_max, 1), round(total_dev_time, 1)


def _analyze_stop_visits(
    rows: list[dict],
    stop_order: list[dict],
) -> list[StopRealizationDTO]:
    stops: list[StopRealizationDTO] = []
    for stop in stop_order:
        stops.append(StopRealizationDTO(
            plan_item_id=stop.get('plan_item_id'),
            order_no=stop.get('order_no'),
            company_name=stop.get('company_name'),
            latitude=stop.get('latitude'),
            longitude=stop.get('longitude'),
            planned_eta_at=stop.get('eta_at'),
            planned_time=stop.get('planned_time'),
        ))

    visit_sequence = 0
    for stop_dto in stops:
        state = 'OUTSIDE'
        consecutive_inside = 0
        consecutive_outside = 0
        arrival_candidate: str | None = None

        for row in rows:
            dist = _stop_distance_m(row['latitude'], row['longitude'], {
                'latitude': stop_dto.latitude,
                'longitude': stop_dto.longitude,
            })
            if dist is None:
                continue

            if state in ('OUTSIDE', 'ENTERING'):
                if dist <= STOP_ENTER_M:
                    consecutive_inside += 1
                    consecutive_outside = 0
                    if consecutive_inside == 1:
                        arrival_candidate = row['gps_timestamp']
                    if consecutive_inside >= STOP_ENTER_CONFIRM_POINTS:
                        stop_dto.actual_arrival_at = arrival_candidate or row['gps_timestamp']
                        state = 'ARRIVED'
                        if stop_dto.actual_visit_sequence is None:
                            visit_sequence += 1
                            stop_dto.actual_visit_sequence = visit_sequence
                else:
                    consecutive_inside = 0
                    arrival_candidate = None

            elif state == 'ARRIVED':
                if dist >= STOP_EXIT_M:
                    consecutive_outside += 1
                    consecutive_inside = 0
                    if consecutive_outside >= STOP_EXIT_CONFIRM_POINTS:
                        stop_dto.actual_departure_at = row['gps_timestamp']
                        state = 'DEPARTED'
                        break
                else:
                    consecutive_outside = 0

        if stop_dto.actual_arrival_at:
            if stop_dto.planned_eta_at:
                planned_dt = parse_gps_timestamp(stop_dto.planned_eta_at)
                actual_dt = parse_gps_timestamp(stop_dto.actual_arrival_at)
                if planned_dt and actual_dt:
                    stop_dto.eta_delta_seconds = round((actual_dt - planned_dt).total_seconds(), 1)
        else:
            stop_dto.visit_status = 'SKIPPED'

    return stops


def _order_analysis(stops: list[StopRealizationDTO]) -> tuple[list, list, list]:
    visited = [s for s in stops if s.actual_arrival_at]
    visited.sort(key=lambda s: s.actual_arrival_at or '')
    actual_order = [s.plan_item_id for s in visited if s.plan_item_id is not None]

    planned_ids = [s.plan_item_id for s in sorted(stops, key=lambda x: x.order_no or 999) if s.plan_item_id is not None]
    skipped = [s.plan_item_id for s in stops if s.visit_status == 'SKIPPED' and s.plan_item_id is not None]

    wrong: list = []
    planned_pos = {pid: i for i, pid in enumerate(planned_ids)}
    last_pos = -1
    for pid in actual_order:
        pos = planned_pos.get(pid, 999)
        if pos < last_pos:
            if pid not in wrong:
                wrong.append(pid)
        last_pos = max(last_pos, pos)

    for stop in stops:
        if stop.plan_item_id in skipped:
            stop.visit_status = 'SKIPPED'
        elif stop.plan_item_id in wrong:
            stop.visit_status = 'OUT_OF_ORDER'
        elif stop.actual_arrival_at:
            stop.visit_status = 'VISITED'

    return actual_order, skipped, wrong


def _detect_factory_departure(
    rows: list[dict],
    base_lat: float,
    base_lon: float,
    search_start: datetime,
    search_end: datetime,
) -> str | None:
    was_near = False
    consecutive_outside = 0
    for row in rows:
        if row['_dt'] < search_start:
            continue
        if row['_dt'] > search_end:
            break
        dist = haversine_m(row['latitude'], row['longitude'], base_lat, base_lon)
        if dist <= STOP_ENTER_M:
            was_near = True
            consecutive_outside = 0
        elif dist >= STOP_EXIT_M and was_near:
            consecutive_outside += 1
            if consecutive_outside >= STOP_EXIT_CONFIRM_POINTS:
                return row['gps_timestamp']
        elif dist >= STOP_EXIT_M:
            consecutive_outside += 1
        else:
            consecutive_outside = 0
    return None


def _detect_factory_return(
    rows: list[dict],
    base_lat: float,
    base_lon: float,
    after_ts: str | None,
) -> str | None:
    after_dt = parse_gps_timestamp(after_ts) if after_ts else None
    consecutive = 0
    for row in rows:
        if after_dt and row['_dt'] <= after_dt:
            continue
        dist = haversine_m(row['latitude'], row['longitude'], base_lat, base_lon)
        if dist <= BASE_ENTER_M:
            consecutive += 1
            if consecutive >= STOP_ENTER_CONFIRM_POINTS:
                return row['gps_timestamp']
        else:
            consecutive = 0
    return None


def _max_gap_seconds(rows: list[dict]) -> float:
    max_gap = 0.0
    for a, b in zip(rows, rows[1:]):
        max_gap = max(max_gap, (b['_dt'] - a['_dt']).total_seconds())
    return max_gap


def _infer_departure_anchor(
    rows: list[dict],
    plan_date: str,
    base_lat: float,
    base_lon: float,
) -> datetime:
    day = datetime.strptime(plan_date, '%Y-%m-%d').date()
    for row in rows:
        if row['_dt'].date() != day:
            continue
        if haversine_m(row['latitude'], row['longitude'], base_lat, base_lon) <= STOP_ENTER_M:
            return row['_dt']
    for row in rows:
        if row['_dt'].date() == day:
            return row['_dt']
    return datetime.strptime(plan_date, '%Y-%m-%d') + timedelta(hours=7)


def _extract_trip_window(
    rows: list[dict],
    plan_date: str,
    cikis_saati: str | None,
    planned_duration_s: float,
    base_lat: float,
    base_lon: float,
    stop_order: list[dict],
) -> _TripWindow:
    planned_departure = _parse_departure(plan_date, cikis_saati)
    day_start = datetime.strptime(plan_date, '%Y-%m-%d')
    if planned_departure:
        search_start = planned_departure - timedelta(minutes=TRIP_PRE_DEPARTURE_MINUTES)
        planned_return = planned_departure + timedelta(seconds=max(planned_duration_s, 0))
        buffer_end = planned_return + timedelta(minutes=TRIP_RETURN_BUFFER_MINUTES)
    elif rows:
        anchor = _infer_departure_anchor(rows, plan_date, base_lat, base_lon)
        search_start = anchor - timedelta(minutes=TRIP_PRE_DEPARTURE_MINUTES)
        planned_return = anchor + timedelta(seconds=max(planned_duration_s, 3600))
        buffer_end = planned_return + timedelta(minutes=TRIP_RETURN_BUFFER_MINUTES)
    else:
        return _TripWindow([], None, False, None, False, None, None, 0)

    midnight_cap = day_start + timedelta(days=1, hours=6)
    buffer_end = min(buffer_end, midnight_cap)

    search_end = buffer_end
    departure_at = _detect_factory_departure(rows, base_lat, base_lon, search_start, search_end)
    departure_verified = departure_at is not None

    if departure_at:
        trip_start_dt = parse_gps_timestamp(departure_at)
    elif planned_departure:
        trip_start_dt = planned_departure
    elif rows:
        trip_start_dt = _infer_departure_anchor(rows, plan_date, base_lat, base_lon)
    else:
        trip_start_dt = search_start

    preliminary = [r for r in rows if trip_start_dt <= r['_dt'] <= buffer_end]
    prelim_stops = _analyze_stop_visits(preliminary, stop_order)
    departed = [s.actual_departure_at for s in prelim_stops if s.actual_departure_at]
    last_stop_departure = max(departed) if departed else None
    arrivals = [s.actual_arrival_at for s in prelim_stops if s.actual_arrival_at]
    after_for_return = last_stop_departure or (max(arrivals) if arrivals else departure_at)

    return_at = _detect_factory_return(preliminary, base_lat, base_lon, after_for_return)
    return_verified = return_at is not None

    if return_at:
        trip_end_dt = parse_gps_timestamp(return_at) or buffer_end
    else:
        trip_end_dt = buffer_end

    trip_rows = [r for r in rows if trip_start_dt <= r['_dt'] <= trip_end_dt]
    excluded = len(rows) - len(trip_rows)

    return _TripWindow(
        rows=trip_rows,
        departure_at=departure_at,
        departure_verified=departure_verified,
        return_at=return_at,
        return_verified=return_verified,
        window_start_at=trip_rows[0]['gps_timestamp'] if trip_rows else None,
        window_end_at=trip_rows[-1]['gps_timestamp'] if trip_rows else None,
        excluded_count=excluded,
    )


def _count_ignition_off_dwells(rows: list[dict], stop_order: list[dict]) -> int:
    if not stop_order:
        return 0
    dwell_count = 0
    for stop in stop_order:
        slat = stop.get('latitude')
        slon = stop.get('longitude')
        if slat is None or slon is None:
            continue
        inside_start: datetime | None = None
        for row in rows:
            dist = haversine_m(row['latitude'], row['longitude'], float(slat), float(slon))
            ign_off = str(row.get('ignition_status') or '').lower() in ('0', 'false', 'off', 'kapali', 'kapalı')
            if dist <= STOP_ENTER_M and ign_off:
                if inside_start is None:
                    inside_start = row['_dt']
            elif inside_start is not None:
                dwell = (row['_dt'] - inside_start).total_seconds()
                if dwell >= IGNITION_OFF_DWELL_SECONDS:
                    dwell_count += 1
                inside_start = None
        if inside_start is not None and rows:
            dwell = (rows[-1]['_dt'] - inside_start).total_seconds()
            if dwell >= IGNITION_OFF_DWELL_SECONDS:
                dwell_count += 1
    return dwell_count


def _assess_data_quality(
    rows: list[dict],
    gap_count: int,
    max_gap: float,
    jump_count: int,
    planned_duration_s: float | None,
    actual_duration_s: float,
    stop_order: list[dict],
) -> DataQualityDTO:
    flags: list[str] = []
    stale_count = sum(1 for r in rows if r.get('is_stale'))
    point_count = len(rows)

    expected_points: int | None = None
    if planned_duration_s and planned_duration_s > 0:
        expected_points = max(1, int(planned_duration_s / EXPECTED_GPS_INTERVAL_SECONDS))

    if point_count == 0:
        flags.append(FLAG_NO_GPS)
    if expected_points and point_count < max(5, int(expected_points * 0.25)):
        flags.append(FLAG_LOW_POINT_COUNT)
    if gap_count > 0:
        flags.append(FLAG_DATA_GAP)
    if gap_count >= CRITICAL_GAP_COUNT:
        flags.append(FLAG_EXCESSIVE_GAPS)
    if max_gap > GAP_LOW_THRESHOLD_SECONDS:
        flags.append(FLAG_CRITICAL_GAP)
    if jump_count > 0:
        flags.append(FLAG_GPS_JUMP)
    if stale_count > 0:
        flags.append(FLAG_STALE_POINTS)

    ignition_dwells = _count_ignition_off_dwells(rows, stop_order)
    if ignition_dwells > 0:
        flags.append(FLAG_IGNITION_OFF_DWELL)

    coverage_ratio: float | None = None
    if expected_points and point_count > 0:
        coverage_ratio = round(min(1.0, point_count / expected_points), 3)
    elif planned_duration_s and planned_duration_s > 0 and actual_duration_s > 0:
        coverage_ratio = round(min(1.0, actual_duration_s / planned_duration_s), 3)

    if coverage_ratio is not None and coverage_ratio < 0.3:
        flags.append(FLAG_SHORT_COVERAGE)

    if max_gap > GAP_LOW_THRESHOLD_SECONDS or gap_count >= CRITICAL_GAP_COUNT:
        level = QUALITY_LOW
    elif coverage_ratio is not None and coverage_ratio < 0.3:
        level = QUALITY_LOW
    elif FLAG_LOW_POINT_COUNT in flags or max_gap > GAP_MEDIUM_THRESHOLD_SECONDS or gap_count > 0 or jump_count > 0:
        level = QUALITY_MEDIUM
    elif point_count < 5:
        level = QUALITY_LOW
    else:
        level = QUALITY_HIGH

    confidence = 1.0
    if FLAG_NO_GPS in flags:
        confidence = 0.0
    else:
        if FLAG_CRITICAL_GAP in flags or FLAG_EXCESSIVE_GAPS in flags:
            confidence -= 0.45
        elif FLAG_DATA_GAP in flags:
            confidence -= 0.25
        if FLAG_GPS_JUMP in flags:
            confidence -= 0.15
        if FLAG_LOW_POINT_COUNT in flags:
            confidence -= 0.2
        if FLAG_STALE_POINTS in flags:
            confidence -= 0.1
        if FLAG_SHORT_COVERAGE in flags:
            confidence -= 0.15
        confidence = max(0.0, min(1.0, confidence))

    if level == QUALITY_HIGH and confidence < 0.75:
        level = QUALITY_MEDIUM
    if level != QUALITY_LOW and (max_gap > GAP_LOW_THRESHOLD_SECONDS or gap_count >= CRITICAL_GAP_COUNT):
        level = QUALITY_LOW

    return DataQualityDTO(
        level=level,
        confidence=round(confidence, 3),
        gps_point_count=point_count,
        data_gap_count=gap_count,
        max_gap_seconds=round(max_gap, 1),
        stale_point_count=stale_count,
        ignition_off_dwell_count=ignition_dwells,
        coverage_ratio=coverage_ratio,
        expected_point_count=expected_points,
        observed_point_count=point_count,
        gps_jump_count=jump_count,
        flags=flags,
    )


def _evaluate_comparison_complete(
    trip: _TripWindow,
    dq: DataQualityDTO,
    stops: list[StopRealizationDTO],
    max_gap: float,
    gap_count: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not trip.departure_verified:
        reasons.append(REASON_DEPARTURE_NOT_DETECTED)
    if not trip.return_verified:
        reasons.append(REASON_RETURN_NOT_DETECTED)
    if not trip.rows:
        reasons.append(REASON_NO_GPS_FOR_TRIP)
    if dq.level == QUALITY_LOW:
        reasons.append(REASON_LOW_DATA_QUALITY)
    if dq.coverage_ratio is not None and dq.coverage_ratio < 0.3:
        if REASON_LOW_DATA_QUALITY not in reasons:
            reasons.append(REASON_LOW_DATA_QUALITY)
    if max_gap > GAP_LOW_THRESHOLD_SECONDS or gap_count >= CRITICAL_GAP_COUNT:
        reasons.append(REASON_CRITICAL_DATA_GAP)
    return (len(reasons) == 0), reasons


def _resolve_base_with_source(
    route_coords: list[list[float]],
    base_latitude: float | None,
    base_longitude: float | None,
    base_source: str | None = None,
) -> tuple[float, float, str] | None:
    if base_latitude is not None and base_longitude is not None:
        src = base_source or BASE_SOURCE_EXPLICIT
        return float(base_latitude), float(base_longitude), src
    if route_coords:
        lon, lat = route_coords[0][0], route_coords[0][1]
        return lat, lon, BASE_SOURCE_ROUTE_GEOMETRY
    return None


def _resolve_base_from_db(con: Any) -> tuple[float, float, str] | None:
    try:
        row = con.execute(
            'SELECT base_latitude, base_longitude FROM arac_operasyon_ayar WHERE aktif=1 ORDER BY id DESC LIMIT 1',
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1]), BASE_SOURCE_OPERATION
    except Exception:
        pass
    return None


def compute_route_realization(
    *,
    plan_id: int,
    vehicle_id: str,
    plan_date: str,
    route_snapshot: dict[str, Any],
    gps_snapshots: list[dict],
    cikis_saati: str | None = None,
    base_latitude: float | None = None,
    base_longitude: float | None = None,
    base_coordinate_source: str | None = None,
) -> RouteRealizationDTO:
    """Compare applied plan route snapshot against ordered GPS snapshots."""
    incomplete: list[str] = []
    raw_geometry = route_snapshot.get('geometry') or route_snapshot.get('geometry_json')
    stop_order: list[dict] = route_snapshot.get('stop_order') or []
    if isinstance(stop_order, str):
        import json
        stop_order = json.loads(stop_order)

    try:
        geom = geometry_from_storage(raw_geometry)
        route_coords = geom.get('coordinates') or []
    except Exception:
        route_coords = []
        incomplete.append(FLAG_NO_ROUTE)

    planned_distance = float(route_snapshot.get('total_distance_m') or 0)
    planned_duration = float(route_snapshot.get('total_duration_s') or 0)

    normalized = _normalize_gps_rows(gps_snapshots)
    date_filtered = _filter_gps_by_plan_dates(normalized, plan_date)

    base_resolved = _resolve_base_with_source(
        route_coords, base_latitude, base_longitude, base_coordinate_source,
    )

    if not route_coords:
        incomplete.append(REASON_ROUTE_GEOMETRY_MISSING)
    if not date_filtered:
        incomplete.append(REASON_NO_GPS_FOR_TRIP)
    if not base_resolved:
        incomplete.append('BASE_COORDINATE_MISSING')

    if not route_coords or not date_filtered or not base_resolved:
        dq = _assess_data_quality([], 0, 0.0, 0, planned_duration or None, 0.0, stop_order)
        return RouteRealizationDTO(
            plan_id=plan_id,
            vehicle_id=vehicle_id,
            plan_date=plan_date,
            comparison_complete=False,
            incomplete_reasons=incomplete or [REASON_NO_GPS_FOR_TRIP],
            data_quality=dq,
            planned_summary=RouteSummaryDTO(
                distance_m=planned_distance,
                duration_s=planned_duration,
            ),
            stops=[
                StopRealizationDTO(
                    plan_item_id=s.get('plan_item_id'),
                    order_no=s.get('order_no'),
                    company_name=s.get('company_name'),
                    planned_eta_at=s.get('eta_at'),
                    planned_time=s.get('planned_time'),
                )
                for s in stop_order
            ],
            base_coordinate_source=base_resolved[2] if base_resolved else None,
            excluded_gps_point_count=len(normalized),
        )

    base_lat, base_lon, base_src = base_resolved
    trip = _extract_trip_window(
        date_filtered, plan_date, cikis_saati, planned_duration, base_lat, base_lon, stop_order,
    )

    if not trip.rows:
        incomplete.append(REASON_NO_GPS_FOR_TRIP)
        dq = _assess_data_quality([], 0, 0.0, 0, planned_duration or None, 0.0, stop_order)
        return RouteRealizationDTO(
            plan_id=plan_id,
            vehicle_id=vehicle_id,
            plan_date=plan_date,
            comparison_complete=False,
            incomplete_reasons=incomplete,
            data_quality=dq,
            planned_summary=RouteSummaryDTO(distance_m=planned_distance, duration_s=planned_duration),
            factory_departure_at=trip.departure_at,
            base_coordinate_source=base_src,
            trip_window_start_at=trip.window_start_at,
            trip_window_end_at=trip.window_end_at,
            excluded_gps_point_count=trip.excluded_count,
        )

    segments, gap_count, jump_count = _segment_by_gaps_and_jumps(trip.rows)
    actual_geometry = _build_multiline_geometry(segments)
    actual_distance = sum(_segment_distance_m(seg) for seg in segments)
    max_gap = _max_gap_seconds(trip.rows)

    classified = _classify_points(trip.rows, route_coords)
    deviations, max_deviation_m, deviation_time_s = _detect_deviations(classified)

    stops = _analyze_stop_visits(trip.rows, stop_order)
    actual_stop_order, skipped_ids, wrong_ids = _order_analysis(stops)

    actual_duration_s = (trip.rows[-1]['_dt'] - trip.rows[0]['_dt']).total_seconds()
    dq = _assess_data_quality(
        trip.rows, gap_count, max_gap, jump_count,
        planned_duration or None, actual_duration_s, stop_order,
    )

    comparison_complete, completeness_reasons = _evaluate_comparison_complete(
        trip, dq, stops, max_gap, gap_count,
    )
    all_reasons = list(dict.fromkeys(incomplete + completeness_reasons))

    return RouteRealizationDTO(
        plan_id=plan_id,
        vehicle_id=vehicle_id,
        plan_date=plan_date,
        comparison_complete=comparison_complete,
        incomplete_reasons=all_reasons,
        data_quality=dq,
        planned_summary=RouteSummaryDTO(
            distance_m=planned_distance,
            duration_s=planned_duration,
            start_at=_parse_departure(plan_date, cikis_saati).strftime(GPS_TIMESTAMP_FMT)
            if _parse_departure(plan_date, cikis_saati) else None,
            end_at=None,
        ),
        actual_summary=RouteSummaryDTO(
            distance_m=round(actual_distance, 1),
            duration_s=round(actual_duration_s, 1),
            start_at=trip.rows[0]['gps_timestamp'],
            end_at=trip.rows[-1]['gps_timestamp'],
        ),
        stops=stops,
        deviations=deviations,
        actual_geometry=actual_geometry,
        factory_departure_at=trip.departure_at,
        factory_return_at=trip.return_at,
        base_coordinate_source=base_src,
        trip_window_start_at=trip.window_start_at,
        trip_window_end_at=trip.window_end_at,
        excluded_gps_point_count=trip.excluded_count,
        actual_stop_order=actual_stop_order,
        skipped_stop_ids=skipped_ids,
        wrong_order_stop_ids=wrong_ids,
        max_deviation_m=max_deviation_m,
        deviation_time_s=deviation_time_s,
    )


def compute_route_realization_from_db(
    plan_id: int,
    vehicle_id: str,
    plan_date: str,
    *,
    db_path: str,
    cikis_saati: str | None = None,
    base_latitude: float | None = None,
    base_longitude: float | None = None,
) -> RouteRealizationDTO:
    """Read-only helper: load snapshot + GPS from SQLite and compute."""
    import json
    import sqlite3

    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        snap_row = con.execute(
            """
            SELECT * FROM arac_plan_rota_snapshot
            WHERE plan_id=? AND is_active=1
            ORDER BY id DESC LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
        if not snap_row:
            return RouteRealizationDTO(
                plan_id=plan_id,
                vehicle_id=vehicle_id,
                plan_date=plan_date,
                comparison_complete=False,
                incomplete_reasons=['NO_ROUTE_SNAPSHOT'],
            )

        snap = dict(snap_row)
        snap['geometry'] = json.loads(snap.pop('geometry_json') or '{}')
        snap['stop_order'] = json.loads(snap.pop('stop_order_json') or '[]')

        if cikis_saati is None:
            plan_row = con.execute(
                'SELECT cikis_saati FROM arac_gunluk_plan WHERE id=?', (plan_id,),
            ).fetchone()
            if plan_row:
                cikis_saati = plan_row['cikis_saati']

        base_src: str | None = None
        if base_latitude is None or base_longitude is None:
            db_base = _resolve_base_from_db(con)
            if db_base:
                base_latitude, base_longitude, base_src = db_base

        day_start = f'{plan_date} 00:00:00'
        next_day = (datetime.strptime(plan_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        day_end = f'{next_day} 23:59:59'
        gps_rows = con.execute(
            """
            SELECT * FROM arac_gps_snapshot
            WHERE arac_external_id=? AND gps_timestamp >= ? AND gps_timestamp <= ?
            ORDER BY gps_timestamp ASC, id ASC
            """,
            (vehicle_id, day_start, day_end),
        ).fetchall()
        gps = [dict(r) for r in gps_rows]
    finally:
        con.close()

    return compute_route_realization(
        plan_id=plan_id,
        vehicle_id=vehicle_id,
        plan_date=plan_date,
        route_snapshot=snap,
        gps_snapshots=gps,
        cikis_saati=cikis_saati,
        base_latitude=base_latitude,
        base_longitude=base_longitude,
        base_coordinate_source=base_src,
    )

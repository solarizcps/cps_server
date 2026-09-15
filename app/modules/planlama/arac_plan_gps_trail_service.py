# -*- coding: utf-8 -*-
"""GPS Geçmişi trail API — read-only plan + snapshot + GPS + olay birleşimi."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from modules.planlama.arac_gps_poll_service import GPS_TIMESTAMP_FMT, parse_gps_timestamp
from modules.planlama.arac_gps_snapshot_repo import get_active_plan_rota_snapshot, gps_tables_ready
from modules.planlama.arac_plan_timeline_service import list_plan_timeline
from modules.planlama.arac_route_geometry import geometry_from_storage
from modules.planlama.arac_route_realization_models import DATA_GAP_SECONDS
from modules.planlama.arac_route_realization_service import (
    _normalize_gps_rows,
    _segment_by_gaps_and_jumps,
    compute_route_realization,
)
from modules.planlama.arac_takip_repo import PLAN_PROVIDER_FILOM, get_conn, tables_ready

MAX_GPS_POINTS = 2000
NO_GPS_HISTORY = 'NO_GPS_HISTORY'
NO_ROUTE_SNAPSHOT = 'NO_ROUTE_SNAPSHOT'

_QUALITY_LABELS = {
    'HIGH': 'Yüksek',
    'MEDIUM': 'Orta',
    'LOW': 'Düşük',
}


class PlanGpsTrailError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


def _plan_row(con: sqlite3.Connection, plan_id: int) -> dict | None:
    row = con.execute(
        """
        SELECT id, plan_tarihi, arac_external_id, arac_plaka_snapshot,
               sofor_id, sofor_adi_snapshot, cikis_saati, durum
        FROM arac_gunluk_plan WHERE id=?
        """,
        (int(plan_id),),
    ).fetchone()
    return dict(row) if row else None


def _gps_for_plan_day(
    con: sqlite3.Connection,
    vehicle_id: str,
    plan_date: str,
    *,
    limit: int = MAX_GPS_POINTS,
) -> list[dict]:
    if not gps_tables_ready():
        return []
    day_start = f'{plan_date} 00:00:00'
    next_day = (datetime.strptime(plan_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
    day_end = f'{next_day} 23:59:59'
    rows = con.execute(
        """
        SELECT * FROM arac_gps_snapshot
        WHERE arac_provider=? AND arac_external_id=?
          AND gps_timestamp >= ? AND gps_timestamp <= ?
        ORDER BY gps_timestamp ASC, id ASC
        LIMIT ?
        """,
        (PLAN_PROVIDER_FILOM, str(vehicle_id), day_start, day_end, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def _build_gps_points_dto(raw_rows: list[dict], route_coords: list[list[float]]) -> tuple[list[dict], list[dict]]:
    """Return (gps_points, gap_segments) — stale excluded from deviation context in realization."""
    normalized = _normalize_gps_rows(raw_rows)
    if not normalized:
        return [], []

    segments, gap_count, _jump_count = _segment_by_gaps_and_jumps(normalized, gap_seconds=DATA_GAP_SECONDS)
    gap_segments: list[dict] = []
    points: list[dict] = []
    seg_idx = 0
    point_global_idx = 0

    for seg_i, segment in enumerate(segments):
        if seg_i > 0 and segment:
            prev_seg_last = segments[seg_i - 1][-1] if segments[seg_i - 1] else None
            cur_first = segment[0]
            if prev_seg_last and cur_first:
                gap_s = (cur_first['_dt'] - prev_seg_last['_dt']).total_seconds()
                if gap_s > DATA_GAP_SECONDS:
                    gap_segments.append({
                        'after_point_index': point_global_idx - 1,
                        'gap_seconds': round(gap_s, 1),
                        'from_timestamp': prev_seg_last['gps_timestamp'],
                        'to_timestamp': cur_first['gps_timestamp'],
                    })

        for j, row in enumerate(segment):
            is_gap_after = False
            if j < len(segment) - 1:
                nxt = segment[j + 1]
                delta = (nxt['_dt'] - row['_dt']).total_seconds()
                is_gap_after = delta > DATA_GAP_SECONDS

            points.append({
                'snapshot_id': row.get('id'),
                'timestamp': row['gps_timestamp'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'speed_kmh': row.get('speed_kmh'),
                'ignition_status': row.get('ignition_status'),
                'activity_status': row.get('activity_status'),
                'is_stale': bool(row.get('is_stale')),
                'data_quality': 'STALE' if row.get('is_stale') else 'OK',
                'gap_after': is_gap_after,
                'segment_index': seg_i,
            })
            point_global_idx += 1
        seg_idx += 1

    return points, gap_segments


def _kpi_from_realization(realization: Any) -> dict:
    dq = realization.data_quality
    planned_km = round((realization.planned_summary.distance_m or 0) / 1000.0, 1)
    actual_km = round((realization.actual_summary.distance_m or 0) / 1000.0, 1)
    dev_count = len(realization.deviations or [])
    dev_time_min = round((realization.deviation_time_s or 0) / 60.0, 1)
    dwell_min = 0.0
    for stop in realization.stops or []:
        if stop.actual_arrival_at and stop.actual_departure_at:
            a = parse_gps_timestamp(stop.actual_arrival_at)
            b = parse_gps_timestamp(stop.actual_departure_at)
            if a and b and b > a:
                dwell_min += (b - a).total_seconds() / 60.0
    dwell_min = round(dwell_min, 1)
    level = dq.level if dq else 'LOW'
    return {
        'actual_distance_km': actual_km,
        'planned_distance_km': planned_km,
        'deviation_count': dev_count,
        'deviation_duration_min': dev_time_min,
        'stop_dwell_min': dwell_min,
        'gps_quality_level': level,
        'gps_quality_label': _QUALITY_LABELS.get(level, level),
        'gap_count': dq.data_gap_count if dq else 0,
        'gps_point_count': dq.gps_point_count if dq else 0,
        'max_deviation_m': round(realization.max_deviation_m or 0, 1),
    }


def _status_summary(realization: Any, has_gps: bool) -> dict:
    if not has_gps:
        return {'code': NO_GPS_HISTORY, 'label': 'GPS geçmişi yok', 'severity': 'neutral'}
    reasons = list(realization.incomplete_reasons or [])
    if realization.deviations:
        return {'code': 'DEVIATION', 'label': 'Sapma tespit edildi', 'severity': 'warn'}
    if reasons:
        return {'code': reasons[0], 'label': reasons[0].replace('_', ' ').title(), 'severity': 'info'}
    if realization.comparison_complete:
        return {'code': 'OK', 'label': 'Plan tamamlandı', 'severity': 'ok'}
    return {'code': 'PARTIAL', 'label': 'Kısmi veri', 'severity': 'info'}


def get_plan_gps_trail(plan_id: int) -> dict[str, Any]:
    """Read-only GPS trail DTO for a daily plan."""
    if not tables_ready():
        raise PlanGpsTrailError('Plan tabloları hazır değil.', 503)

    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        plan = _plan_row(con, int(plan_id))
        if not plan:
            raise PlanGpsTrailError('Plan bulunamadı.', 404)

        plan_date = plan['plan_tarihi']
        vehicle_id = str(plan['arac_external_id'] or '')
        snap = get_active_plan_rota_snapshot(int(plan_id))

        gps_raw = _gps_for_plan_day(con, vehicle_id, plan_date, limit=MAX_GPS_POINTS)
        has_gps = bool(gps_raw)

        route_geometry: dict[str, Any] = {'type': 'LineString', 'coordinates': [], 'crs': 'WGS84'}
        stop_order: list[dict] = []
        route_status = 'OK'
        if snap:
            try:
                geom = snap.get('geometry') or geometry_from_storage(snap.get('geometry_json'))
                route_geometry = geom or route_geometry
            except Exception:
                route_geometry = {'type': 'LineString', 'coordinates': [], 'crs': 'WGS84'}
                route_status = NO_ROUTE_SNAPSHOT
            stop_order = snap.get('stop_order') or []
        else:
            route_status = NO_ROUTE_SNAPSHOT

        route_coords: list[list[float]] = []
        if route_geometry.get('type') == 'LineString':
            route_coords = route_geometry.get('coordinates') or []
        elif route_geometry.get('type') == 'MultiLineString':
            for line in route_geometry.get('coordinates') or []:
                route_coords.extend(line)

        snap_for_realization = {
            'geometry': route_geometry,
            'stop_order': stop_order,
            'total_distance_m': (snap or {}).get('total_distance_m'),
            'total_duration_s': (snap or {}).get('total_duration_s'),
        }

        from modules.planlama.arac_route_realization_service import _resolve_base_from_db
        base = _resolve_base_from_db(con)
        base_lat, base_lon, base_src = base if base else (None, None, None)

        realization = compute_route_realization(
            plan_id=int(plan_id),
            vehicle_id=vehicle_id,
            plan_date=plan_date,
            route_snapshot=snap_for_realization,
            gps_snapshots=gps_raw,
            cikis_saati=plan.get('cikis_saati'),
            base_latitude=base_lat,
            base_longitude=base_lon,
            base_coordinate_source=base_src,
        )

        gps_points, gap_segments = _build_gps_points_dto(gps_raw, route_coords)
        timeline = list_plan_timeline(plan_id=int(plan_id), limit=200)

        trip_start = realization.trip_window_start_at or (gps_points[0]['timestamp'] if gps_points else None)
        trip_end = realization.trip_window_end_at or (gps_points[-1]['timestamp'] if gps_points else None)

        return {
            'ok': True,
            'plan_id': int(plan_id),
            'plan_date': plan_date,
            'vehicle_external_id': vehicle_id,
            'plate': plan.get('arac_plaka_snapshot') or '—',
            'driver': plan.get('sofor_adi_snapshot') or '—',
            'departure_time': plan.get('cikis_saati'),
            'window_start': trip_start,
            'window_end': trip_end,
            'route_geometry': route_geometry,
            'route_status': route_status,
            'stop_order': stop_order,
            'actual_trail_geometry': realization.actual_geometry,
            'gps_points': gps_points,
            'gap_segments': gap_segments,
            'deviations': [d.__dict__ if hasattr(d, '__dict__') else d for d in (realization.deviations or [])],
            'timeline_events': timeline.get('events') or [],
            'kpi': _kpi_from_realization(realization),
            'status': _status_summary(realization, has_gps),
            'data_quality': realization.data_quality.__dict__ if realization.data_quality else {},
            'comparison_complete': realization.comparison_complete,
            'incomplete_reasons': realization.incomplete_reasons or [],
            'has_gps_history': has_gps,
            'empty_code': None if has_gps else NO_GPS_HISTORY,
        }
    finally:
        con.close()


def plan_has_gps_history(plan_id: int) -> bool:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        plan = _plan_row(con, int(plan_id))
        if not plan:
            return False
        gps = _gps_for_plan_day(con, str(plan['arac_external_id']), plan['plan_tarihi'], limit=1)
        return bool(gps)
    finally:
        con.close()


def list_history_plans(
    *,
    baslangic: str | None = None,
    bitis: str | None = None,
    arac_external_id: str | None = None,
    sofor_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Read-only geçmiş plan listesi — GPS geçmişi bayrağı ile."""
    if not tables_ready():
        return {'ok': True, 'rows': [], 'count': 0}

    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        clauses = ['1=1']
        params: list[Any] = []
        if baslangic:
            clauses.append('p.plan_tarihi >= ?')
            params.append(baslangic)
        if bitis:
            clauses.append('p.plan_tarihi <= ?')
            params.append(bitis)
        if arac_external_id:
            clauses.append('p.arac_external_id=?')
            params.append(str(arac_external_id))
        if sofor_id:
            clauses.append('p.sofor_id=?')
            params.append(str(sofor_id))

        where = ' AND '.join(clauses)
        rows = con.execute(
            f"""
            SELECT
                p.id AS plan_id,
                p.plan_tarihi AS date,
                p.arac_external_id,
                p.arac_plaka_snapshot AS vehicle,
                p.sofor_adi_snapshot AS driver,
                p.durum,
                COUNT(pi.id) AS total_jobs,
                SUM(CASE WHEN pi.durum = 'TAMAMLANDI' THEN 1 ELSE 0 END) AS completed
            FROM arac_gunluk_plan p
            LEFT JOIN arac_gunluk_plan_is pi ON pi.plan_id = p.id
            WHERE {where}
            GROUP BY p.id
            ORDER BY p.plan_tarihi DESC, p.id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

        out: list[dict] = []
        for row in rows:
            d = dict(row)
            plan_id = int(d['plan_id'])
            has_gps = False
            if gps_tables_ready() and d.get('arac_external_id') and d.get('date'):
                cnt = con.execute(
                    """
                    SELECT COUNT(*) FROM arac_gps_snapshot
                    WHERE arac_provider=? AND arac_external_id=?
                      AND date(gps_timestamp)=?
                    LIMIT 1
                    """,
                    (PLAN_PROVIDER_FILOM, str(d['arac_external_id']), d['date']),
                ).fetchone()[0]
                has_gps = int(cnt or 0) > 0

            st = d.get('durum') or 'AKTIF'
            status_label = {'AKTIF': 'Aktif', 'TAMAMLANDI': 'Tamamlandı', 'KAPALI': 'Kapalı'}.get(st, st)
            total = int(d.get('total_jobs') or 0)
            completed = int(d.get('completed') or 0)
            if total and completed >= total:
                status_label = 'Tamamlandı'
                st = 'TAMAMLANDI'
            elif completed > 0:
                status_label = 'Kısmi'
                st = 'KISMI'

            out.append({
                'plan_id': plan_id,
                'date': d['date'],
                'vehicle': d.get('vehicle') or '—',
                'driver': d.get('driver') or '—',
                'vehicle_external_id': d.get('arac_external_id'),
                'total_jobs': total,
                'completed': completed,
                'total_km': None,
                'planned_km': None,
                'km_diff': None,
                'status': st,
                'status_label': status_label,
                'has_gps_history': has_gps,
            })

        return {'ok': True, 'rows': out, 'count': len(out)}
    finally:
        con.close()

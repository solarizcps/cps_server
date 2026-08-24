# -*- coding: utf-8 -*-
"""Araç GPS snapshot — DB persistence (P1)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.planlama.arac_takip_repo import PLAN_PROVIDER_FILOM, get_conn


def gps_tables_ready() -> bool:
    con = get_conn()
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_gps_snapshot'",
        ).fetchone()
        return bool(row)
    finally:
        con.close()


def insert_gps_snapshot(row: dict[str, Any]) -> str:
    """Insert snapshot. Returns 'inserted' | 'dedup' | 'rejected'."""
    con = get_conn()
    try:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO arac_gps_snapshot (
                arac_provider, arac_external_id, plate_snapshot,
                gps_timestamp, received_at, latitude, longitude,
                speed_kmh, activity_status, ignition_status, odometer_km,
                is_stale, dedup_key, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row['arac_provider'],
                row['arac_external_id'],
                row.get('plate_snapshot'),
                row['gps_timestamp'],
                row['received_at'],
                row['latitude'],
                row['longitude'],
                row.get('speed_kmh'),
                row.get('activity_status'),
                row.get('ignition_status'),
                row.get('odometer_km'),
                1 if row.get('is_stale') else 0,
                row['dedup_key'],
                row['created_at'],
            ),
        )
        con.commit()
        return 'inserted' if cur.rowcount else 'dedup'
    finally:
        con.close()


def count_gps_snapshots(
    arac_external_id: str | None = None,
    *,
    provider: str = PLAN_PROVIDER_FILOM,
) -> int:
    con = get_conn()
    try:
        if arac_external_id:
            return con.execute(
                'SELECT COUNT(*) FROM arac_gps_snapshot '
                'WHERE arac_provider=? AND arac_external_id=?',
                (provider, arac_external_id),
            ).fetchone()[0]
        return con.execute('SELECT COUNT(*) FROM arac_gps_snapshot').fetchone()[0]
    finally:
        con.close()


def list_gps_snapshots_ordered(
    arac_external_id: str,
    *,
    provider: str = PLAN_PROVIDER_FILOM,
    limit: int = 500,
) -> list[dict]:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT * FROM arac_gps_snapshot
            WHERE arac_provider=? AND arac_external_id=?
            ORDER BY gps_timestamp ASC, id ASC
            LIMIT ?
            """,
            (provider, arac_external_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_max_gps_snapshot_id() -> int:
    con = get_conn()
    try:
        row = con.execute('SELECT COALESCE(MAX(id),0) FROM arac_gps_snapshot').fetchone()[0]
        return int(row or 0)
    finally:
        con.close()


def get_gps_snapshot_by_id(snapshot_id: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (int(snapshot_id),)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def get_latest_gps_snapshot(
    arac_external_id: str,
    *,
    provider: str = PLAN_PROVIDER_FILOM,
) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """
            SELECT * FROM arac_gps_snapshot
            WHERE arac_provider=? AND arac_external_id=?
            ORDER BY gps_timestamp DESC, id DESC LIMIT 1
            """,
            (provider, str(arac_external_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def plan_rota_tables_ready() -> bool:
    con = get_conn()
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_rota_snapshot'",
        ).fetchone()
        return bool(row)
    finally:
        con.close()


def save_plan_rota_snapshot(
    plan_id: int,
    *,
    geometry: dict,
    stop_order: list,
    routing_provider: str | None,
    total_distance_m: float | None,
    total_duration_s: float | None,
    content_hash: str,
    geometry_schema: str = 'geojson_linestring_v1',
    arac_provider: str = PLAN_PROVIDER_FILOM,
    created_by: int | None = None,
    created_at: str,
) -> dict | None:
    """Deactivate prior active snapshot; insert new version. Returns None if dedup."""
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN IMMEDIATE')
        result = _save_plan_rota_snapshot_conn(
            con,
            plan_id,
            geometry=geometry,
            stop_order=stop_order,
            routing_provider=routing_provider,
            total_distance_m=total_distance_m,
            total_duration_s=total_duration_s,
            content_hash=content_hash,
            geometry_schema=geometry_schema,
            arac_provider=arac_provider,
            created_by=created_by,
            created_at=created_at,
        )
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _save_plan_rota_snapshot_conn(
    con: sqlite3.Connection,
    plan_id: int,
    *,
    geometry: dict,
    stop_order: list,
    routing_provider: str | None,
    total_distance_m: float | None,
    total_duration_s: float | None,
    content_hash: str,
    geometry_schema: str = 'geojson_linestring_v1',
    arac_provider: str = PLAN_PROVIDER_FILOM,
    created_by: int | None = None,
    created_at: str,
) -> dict:
    """Transaction-aware snapshot write — caller owns commit/rollback."""
    active = con.execute(
        """
        SELECT id, content_hash, route_version FROM arac_plan_rota_snapshot
        WHERE plan_id=? AND is_active=1 ORDER BY route_version DESC LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    if active and active['content_hash'] == content_hash:
        return {
            'id': int(active['id']),
            'plan_id': plan_id,
            'route_version': int(active['route_version']),
            'is_active': True,
            'dedup': True,
        }
    prev = con.execute(
        'SELECT MAX(route_version) v FROM arac_plan_rota_snapshot WHERE plan_id=?',
        (plan_id,),
    ).fetchone()[0]
    route_version = int(prev or 0) + 1
    con.execute(
        'UPDATE arac_plan_rota_snapshot SET is_active=0 WHERE plan_id=? AND is_active=1',
        (plan_id,),
    )
    cur = con.execute(
        """
        INSERT INTO arac_plan_rota_snapshot (
            plan_id, route_version, arac_provider, routing_provider,
            geometry_json, geometry_schema, content_hash,
            total_distance_m, total_duration_s,
            stop_order_json, is_active, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
        """,
        (
            plan_id,
            route_version,
            arac_provider,
            routing_provider,
            json.dumps(geometry, ensure_ascii=False),
            geometry_schema,
            content_hash,
            total_distance_m,
            total_duration_s,
            json.dumps(stop_order, ensure_ascii=False),
            created_at,
            created_by,
        ),
    )
    return {
        'id': int(cur.lastrowid),
        'plan_id': plan_id,
        'route_version': route_version,
        'is_active': True,
        'dedup': False,
    }


def get_active_plan_rota_snapshot(plan_id: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """
            SELECT * FROM arac_plan_rota_snapshot
            WHERE plan_id=? AND is_active=1
            ORDER BY route_version DESC LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        raw_geom = json.loads(out.pop('geometry_json') or '{}')
        from modules.planlama.arac_route_geometry import geometry_from_storage
        out['geometry'] = geometry_from_storage(raw_geom)
        out['stop_order'] = json.loads(out.pop('stop_order_json') or '[]')
        return out
    finally:
        con.close()


def get_plan_rota_snapshot_version(plan_id: int, route_version: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """
            SELECT * FROM arac_plan_rota_snapshot
            WHERE plan_id=? AND route_version=?
            """,
            (plan_id, route_version),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        raw_geom = json.loads(out.pop('geometry_json') or '{}')
        from modules.planlama.arac_route_geometry import geometry_from_storage
        out['geometry'] = geometry_from_storage(raw_geom)
        out['stop_order'] = json.loads(out.pop('stop_order_json') or '[]')
        return out
    finally:
        con.close()

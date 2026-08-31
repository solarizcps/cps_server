# -*- coding: utf-8 -*-
"""Plan rota snapshot — persist applied route geometry (GeoJSON) for a plan day."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from modules.planlama.arac_gps_snapshot_repo import (
    get_active_plan_rota_snapshot,
    get_plan_rota_snapshot_version,
    plan_rota_tables_ready,
    save_plan_rota_snapshot,
)
from modules.planlama.arac_route_geometry import (
    GEOMETRY_SCHEMA,
    GeometryError,
    latlng_pairs_to_geojson,
    route_content_hash,
)
from modules.planlama.arac_takip_repo import PLAN_PROVIDER_FILOM


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _plan_rota_snapshot_table_exists_conn(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_rota_snapshot'",
    ).fetchone())


def invalidate_active_plan_route_snapshot_conn(
    con: sqlite3.Connection,
    plan_id: int,
) -> int:
    """
    Deactivate active route snapshots for one plan on caller-owned connection.

    Returns number of rows updated. No-op when table missing or no active row.
    """
    if not _plan_rota_snapshot_table_exists_conn(con):
        return 0
    cur = con.execute(
        'UPDATE arac_plan_rota_snapshot SET is_active=0 WHERE plan_id=? AND is_active=1',
        (int(plan_id),),
    )
    return int(cur.rowcount or 0)


def invalidate_plan_route_state_after_acil_insert_conn(
    con: sqlite3.Connection,
    plan_id: int,
    oncelik: str | None,
) -> None:
    """
    ACIL sıra değişimi sonrası stale snapshot/ETA temizliği — aynı transaction.

    Yalnız ACIL önceliğinde çalışır; rota motoru veya ETA hesabı yapmaz.
    """
    if (oncelik or 'NORMAL').strip().upper() != 'ACIL':
        return
    invalidate_active_plan_route_snapshot_conn(con, plan_id)
    from modules.planlama.arac_takip_repo import clear_plan_item_etas_conn
    clear_plan_item_etas_conn(con, plan_id)


def invalidate_plan_route_state_after_manual_reorder_conn(
    con: sqlite3.Connection,
    plan_id: int,
) -> dict[str, int]:
    """
    Manuel reorder sonrası stale snapshot/ETA temizliği — aynı transaction.

    Öncelik parametresi istemez. Commit/rollback yapmaz.
    """
    snapshots_deactivated = invalidate_active_plan_route_snapshot_conn(con, plan_id)
    from modules.planlama.arac_takip_repo import clear_plan_item_etas_conn
    etas_cleared = clear_plan_item_etas_conn(con, plan_id)
    return {
        'snapshots_deactivated': snapshots_deactivated,
        'etas_cleared': etas_cleared,
    }


def build_stop_order_from_tasks(
    tasks: list[dict],
    eta_by_task: dict[str, dict] | None = None,
) -> list[dict]:
    ordered = sorted(tasks, key=lambda t: t.get('order_no') or 0)
    eta_by_task = eta_by_task or {}
    out: list[dict] = []
    for t in ordered:
        tid = str(t.get('id') or '')
        eta = eta_by_task.get(tid) or {}
        out.append({
            'plan_item_id': t.get('id'),
            'is_talebi_id': t.get('is_talebi_id') or t.get('request_id'),
            'order_no': t.get('order_no'),
            'company_name': t.get('company_name'),
            'latitude': t.get('latitude'),
            'longitude': t.get('longitude'),
            'planned_time': eta.get('display_hhmm') or t.get('planned_time'),
            'eta_at': eta.get('eta_at'),
            'leg_duration_s': eta.get('leg_duration_s'),
        })
    return out


def persist_plan_route_from_dto(
    plan_id: int,
    route_dto: dict[str, Any],
    tasks: list[dict],
    *,
    created_by: int | None = None,
    created_at: str | None = None,
) -> dict | None:
    """Save active route snapshot when route OK/PARTIAL with valid geometry."""
    if not plan_rota_tables_ready():
        return None
    status = route_dto.get('status')
    if status not in ('OK', 'PARTIAL'):
        return None
    current = route_dto.get('current') or {}
    raw_geometry = current.get('geometry') or []
    if len(raw_geometry) < 2:
        return None
    try:
        geojson = latlng_pairs_to_geojson(raw_geometry)
    except GeometryError:
        return None
    stop_order = build_stop_order_from_tasks(tasks)
    content_hash = route_content_hash(
        geojson,
        stop_order,
        current.get('distance_m'),
        current.get('duration_s'),
    )
    return save_plan_rota_snapshot(
        plan_id,
        geometry=geojson,
        stop_order=stop_order,
        routing_provider=current.get('provider'),
        total_distance_m=current.get('distance_m'),
        total_duration_s=current.get('duration_s'),
        content_hash=content_hash,
        geometry_schema=GEOMETRY_SCHEMA,
        arac_provider=PLAN_PROVIDER_FILOM,
        created_by=created_by,
        created_at=created_at or _now_str(),
    )


def persist_applied_route_after_reorder(
    plan_date: str,
    vehicle_external_id: str,
    tasks: list[dict],
    *,
    user_id: int | None = None,
) -> dict | None:
    """
    Called only after successful route/apply reorder.
    Computes route for applied order and persists snapshot (dedup aware).
    """
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.arac_takip_repo import get_active_plan_row
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    if not vehicle_external_id or not tasks:
        return None
    plan = get_active_plan_row(plan_date, vehicle_external_id)
    if not plan:
        return None
    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)
    route_dto = build_plan_route_dto(base, tasks)
    return persist_plan_route_from_dto(
        int(plan['id']),
        route_dto,
        tasks,
        created_by=user_id,
    )


def get_applied_route_for_plan(plan_id: int) -> dict | None:
    return get_active_plan_rota_snapshot(plan_id)


def get_route_version_for_plan(plan_id: int, route_version: int) -> dict | None:
    return get_plan_rota_snapshot_version(plan_id, route_version)

# -*- coding: utf-8 -*-
"""Route apply — atomic reorder + plan rota snapshot (GPS P2)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from db import get_conn
from modules.planlama.arac_gps_snapshot_repo import (
    _save_plan_rota_snapshot_conn,
    gps_tables_ready,
    plan_rota_tables_ready,
)
from modules.planlama.arac_plan_rota_snapshot_service import build_stop_order_from_tasks
from modules.planlama.arac_route_geometry import (
    GEOMETRY_SCHEMA,
    GeometryError,
    latlng_pairs_to_geojson,
    route_content_hash,
)
from modules.planlama.arac_route_constraints import (
    RouteApplyConflictError,
    active_tasks_sorted,
    classify_route_tasks,
    load_visit_states_for_tasks,
    validate_apply_task_ids,
)
from modules.planlama.arac_takip_repo import (
    PLAN_PROVIDER_FILOM,
    _reorder_plan_items_bulk_conn,
    get_active_plan_row,
    list_plan_tasks,
    tables_ready,
)


class RouteApplyValidationError(ValueError):
    """Input / plan item validation — HTTP 400."""


class RouteApplyRouteError(ValueError):
    """Route DTO / geometry cannot be prepared — HTTP 400, no DB writes."""


class RouteApplySchemaError(RuntimeError):
    """P2 schema incomplete — HTTP 503, no DB writes."""


class RouteApplyPersistenceError(RuntimeError):
    """Snapshot persist failed inside transaction — rolled back."""


@dataclass
class PreparedRouteSnapshot:
    geometry: dict
    stop_order: list[dict]
    routing_provider: str | None
    total_distance_m: float | None
    total_duration_s: float | None
    content_hash: str
    geometry_schema: str = GEOMETRY_SCHEMA


@dataclass
class RouteApplyResult:
    tasks: list[dict]
    route_snapshot: dict
    route_version: int
    deduplicated: bool
    applied: bool = True


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def resolve_route_apply_mode() -> str:
    """
    atomic — migration 179 plan rota tablosu mevcut, tam atomik apply.
    legacy — canonical / pre-179: yalnız reorder, snapshot zorunlu değil.
    schema_error — GPS tabloları var ama plan rota yok (yarım migration).
    """
    if plan_rota_tables_ready():
        return 'atomic'
    if gps_tables_ready():
        return 'schema_error'
    return 'legacy'


def route_apply_atomic_enabled() -> bool:
    return resolve_route_apply_mode() == 'atomic'


def prepare_route_snapshot_payload(
    route_dto: dict[str, Any],
    tasks: list[dict],
) -> PreparedRouteSnapshot:
    """Pre-transaction: validate route DTO and build snapshot payload."""
    status = route_dto.get('status')
    if status not in ('OK', 'PARTIAL'):
        raise RouteApplyRouteError(
            route_dto.get('message') or f'Rota hesaplanamadı ({status or "UNKNOWN"})',
        )
    current = route_dto.get('current') or {}
    raw_geometry = current.get('geometry') or []
    if len(raw_geometry) < 2:
        raise RouteApplyRouteError('Rota geometry yetersiz')
    try:
        geojson = latlng_pairs_to_geojson(raw_geometry)
    except GeometryError as exc:
        raise RouteApplyRouteError(str(exc)) from exc
    stop_order = build_stop_order_from_tasks(tasks)
    content_hash = route_content_hash(
        geojson,
        stop_order,
        current.get('distance_m'),
        current.get('duration_s'),
    )
    return PreparedRouteSnapshot(
        geometry=geojson,
        stop_order=stop_order,
        routing_provider=current.get('provider'),
        total_distance_m=current.get('distance_m'),
        total_duration_s=current.get('duration_s'),
        content_hash=content_hash,
    )


def _reordered_tasks_preview(current_tasks: list[dict], task_ids: list[str]) -> list[dict]:
    active = active_tasks_sorted(current_tasks)
    by_id = {t['id']: t for t in active}
    if set(task_ids) != set(by_id.keys()):
        raise RouteApplyValidationError('Görev listesi plan ile uyuşmuyor')
    out: list[dict] = []
    for i, tid in enumerate(task_ids, start=1):
        t = dict(by_id[tid])
        t['order_no'] = i
        out.append(t)
    return out


def apply_route_order_and_snapshot(
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    task_ids: list[str],
    *,
    user_id: int | None = None,
    route_dto_builder: Callable[[dict, list[dict]], dict] | None = None,
) -> RouteApplyResult:
    """
    Single unit-of-work: reorder plan items + persist route snapshot atomically.

    Route calculation (ORS/network) MUST occur before BEGIN — via route_dto_builder
    or default build_plan_route_dto outside the open transaction.
    """
    if not tables_ready():
        raise RouteApplyValidationError('Araç takip tabloları hazır değil')
    if not arac_external_id:
        raise RouteApplyValidationError('vehicle_id gerekli')
    if not task_ids:
        raise RouteApplyValidationError('task_ids gerekli')

    mode = resolve_route_apply_mode()
    if mode == 'schema_error':
        raise RouteApplySchemaError('Plan rota snapshot şeması eksik (migration 179)')
    if mode != 'atomic':
        raise RouteApplySchemaError('Atomik route apply bu ortamda aktif değil')

    plan = get_active_plan_row(plan_date, arac_external_id)
    if not plan:
        raise RouteApplyValidationError('Aktif plan bulunamadı')
    plan_id = int(plan['id'])

    current_tasks = list_plan_tasks(plan_date, arac_external_id)
    visit_states = load_visit_states_for_tasks(current_tasks)
    constraints = classify_route_tasks(current_tasks, visit_states)
    validate_apply_task_ids(current_tasks, task_ids, constraints)
    reordered_tasks = _reordered_tasks_preview(current_tasks, task_ids)

    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location

    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)
    if route_dto_builder is not None:
        route_dto = route_dto_builder(base, reordered_tasks)
    else:
        from modules.planlama.road_routing.route_planner_service import build_plan_route_dto
        route_dto = build_plan_route_dto(base, reordered_tasks)

    prepared = prepare_route_snapshot_payload(route_dto, reordered_tasks)
    created_by = user_id if user_id is not None else session_user_id
    created_at = _now_str()

    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        _reorder_plan_items_bulk_conn(
            con, session_user_id, plan_date, arac_external_id, task_ids,
        )
        try:
            snapshot = _save_plan_rota_snapshot_conn(
                con,
                plan_id,
                geometry=prepared.geometry,
                stop_order=prepared.stop_order,
                routing_provider=prepared.routing_provider,
                total_distance_m=prepared.total_distance_m,
                total_duration_s=prepared.total_duration_s,
                content_hash=prepared.content_hash,
                geometry_schema=prepared.geometry_schema,
                arac_provider=PLAN_PROVIDER_FILOM,
                created_by=created_by,
                created_at=created_at,
            )
        except Exception as exc:
            raise RouteApplyPersistenceError(str(exc)) from exc
        con.commit()
    except (RouteApplyValidationError, RouteApplyRouteError, RouteApplySchemaError):
        con.rollback()
        raise
    except ValueError as exc:
        con.rollback()
        raise RouteApplyValidationError(str(exc)) from exc
    except RouteApplyPersistenceError:
        con.rollback()
        raise
    except Exception as exc:
        con.rollback()
        raise RouteApplyPersistenceError(str(exc)) from exc
    finally:
        con.close()

    tasks = list_plan_tasks(plan_date, arac_external_id)
    return RouteApplyResult(
        tasks=tasks,
        route_snapshot=snapshot,
        route_version=int(snapshot['route_version']),
        deduplicated=bool(snapshot.get('dedup')),
        applied=True,
    )

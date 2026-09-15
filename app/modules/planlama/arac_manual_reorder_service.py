# -*- coding: utf-8 -*-
"""U3C — Manual reorder backend: state token, context, atomic apply."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from modules.planlama.arac_route_order_policy import (
    ManualReorderValidationError,
    build_manual_reorder_segments,
    can_move_task,
    movement_lock_reason,
    normalize_plan_status,
    normalize_visit_state,
    task_id,
    validate_manual_reorder,
)


class ManualReorderServiceError(Exception):
    """Service-level manual reorder error with HTTP hint and stable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        task_id: str | None = None,
        canonical_index: int | None = None,
        proposed_index: int | None = None,
        segment_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.task_id = task_id
        self.canonical_index = canonical_index
        self.proposed_index = proposed_index
        self.segment_index = segment_index

    def to_dict(self) -> dict[str, Any]:
        err: dict[str, Any] = {
            'code': self.code,
            'message': self.message,
        }
        if self.task_id is not None:
            err['task_id'] = self.task_id
        if self.canonical_index is not None:
            err['canonical_index'] = self.canonical_index
        if self.proposed_index is not None:
            err['proposed_index'] = self.proposed_index
        if self.segment_index is not None:
            err['segment_index'] = self.segment_index
        return {'ok': False, 'error': err}


def _validation_http_status(code: str) -> int:
    if code in ('LOCKED_TASK_MOVE', 'SEGMENT_BOUNDARY_CROSS', 'TASK_SET_MISMATCH'):
        return 409
    if code in ('DUPLICATE_CANONICAL_TASK_ID', 'DUPLICATE_PROPOSED_TASK_ID', 'MISSING_TASK_ID'):
        return 422
    return 400


def _service_error_from_validation(exc: ManualReorderValidationError) -> ManualReorderServiceError:
    return ManualReorderServiceError(
        exc.code,
        exc.message,
        http_status=_validation_http_status(exc.code),
        task_id=exc.task_id,
        canonical_index=exc.canonical_index,
        proposed_index=exc.proposed_index,
        segment_index=exc.segment_index,
    )


def build_manual_reorder_state_token(plan_row: dict, canonical_tasks: list[dict]) -> str:
    """
    Deterministic SHA256 fingerprint of plan + canonical task state.

    Captures visit/geofence fields that plan.updated_at may not reflect.
    """
    items: list[dict[str, Any]] = []
    for task in canonical_tasks:
        items.append({
            'task_id': task_id(task),
            'sira': int(task.get('sira') or task.get('order_no') or 0),
            'status': normalize_plan_status(task.get('status')),
            'visit_state': normalize_visit_state(task.get('visit_state')),
            'arrived_at': task.get('arrived_at') or None,
            'departed_at': task.get('departed_at') or None,
        })
    payload = {
        'plan_id': int(plan_row['id']),
        'plan_tarihi': str(plan_row.get('plan_tarihi') or ''),
        'arac_external_id': str(plan_row.get('arac_external_id') or ''),
        'updated_at': str(plan_row.get('updated_at') or ''),
        'items': items,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _assert_plan_scope(
    plan_row: dict,
    *,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
) -> None:
    if plan_date and str(plan_row.get('plan_tarihi') or '') != str(plan_date):
        raise ManualReorderServiceError(
            'PLAN_SCOPE_MISMATCH',
            'Plan date does not match request scope',
            http_status=404,
        )
    if vehicle_id and str(plan_row.get('arac_external_id') or '') != str(vehicle_id):
        raise ManualReorderServiceError(
            'PLAN_SCOPE_MISMATCH',
            'Plan vehicle does not match request scope',
            http_status=404,
        )


def _build_context_tasks(canonical_tasks: list[dict]) -> tuple[list[str], list[dict]]:
    segments = build_manual_reorder_segments(canonical_tasks)
    segment_by_task: dict[str, int] = {}
    for segment in segments:
        if segment['kind'] == 'locked':
            segment_by_task[str(segment['task_id'])] = int(segment['segment_index'])
        else:
            for tid in segment['task_ids']:
                segment_by_task[str(tid)] = int(segment['segment_index'])

    ordered_ids: list[str] = []
    task_rows: list[dict] = []
    for index, task in enumerate(canonical_tasks):
        tid = task_id(task)
        ordered_ids.append(tid)
        task_rows.append({
            'task_id': tid,
            'order_no': int(task.get('sira') or task.get('order_no') or index + 1),
            'can_move': can_move_task(task),
            'lock_reason': movement_lock_reason(task),
            'segment_index': segment_by_task.get(tid),
        })
    return ordered_ids, task_rows


def get_manual_reorder_context(
    plan_id: int,
    *,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
) -> dict[str, Any]:
    from modules.planlama.arac_takip_repo import (
        get_conn,
        get_plan_row_by_id_conn,
        load_manual_reorder_policy_tasks_conn,
        tables_ready,
    )

    if not tables_ready():
        raise ManualReorderServiceError('TABLES_NOT_READY', 'Tablolar hazır değil', http_status=503)
    if not plan_id:
        raise ManualReorderServiceError('INVALID_REQUEST', 'plan_id gerekli', http_status=400)

    con = get_conn()
    try:
        plan_row = get_plan_row_by_id_conn(con, int(plan_id))
        if not plan_row:
            raise ManualReorderServiceError('PLAN_NOT_FOUND', 'Plan bulunamadı', http_status=404)
        _assert_plan_scope(plan_row, plan_date=plan_date, vehicle_id=vehicle_id)
        canonical_tasks = load_manual_reorder_policy_tasks_conn(con, int(plan_id))
        ordered_ids, task_rows = _build_context_tasks(canonical_tasks)
        token = build_manual_reorder_state_token(plan_row, canonical_tasks)
        return {
            'ok': True,
            'plan_id': int(plan_id),
            'state_token': token,
            'ordered_item_ids': ordered_ids,
            'tasks': task_rows,
        }
    finally:
        con.close()


def apply_manual_reorder(
    session_user_id: int,
    plan_id: int,
    state_token: str,
    ordered_item_ids: list[Any],
    *,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
) -> dict[str, Any]:
    from modules.planlama.arac_plan_rota_snapshot_service import (
        invalidate_plan_route_state_after_manual_reorder_conn,
    )
    from modules.planlama.arac_takip_repo import (
        get_conn,
        get_plan_row_by_id_conn,
        list_plan_tasks,
        load_manual_reorder_policy_tasks_conn,
        reorder_plan_items_by_plan_id_conn,
        tables_ready,
    )

    if not tables_ready():
        raise ManualReorderServiceError('TABLES_NOT_READY', 'Tablolar hazır değil', http_status=503)
    if not plan_id:
        raise ManualReorderServiceError('INVALID_REQUEST', 'plan_id gerekli', http_status=400)
    if not state_token or not isinstance(state_token, str):
        raise ManualReorderServiceError('INVALID_REQUEST', 'state_token gerekli', http_status=400)
    if not isinstance(ordered_item_ids, list):
        raise ManualReorderServiceError('INVALID_REQUEST', 'ordered_item_ids list olmalı', http_status=400)

    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        plan_row = get_plan_row_by_id_conn(con, int(plan_id))
        if not plan_row:
            raise ManualReorderServiceError('PLAN_NOT_FOUND', 'Plan bulunamadı', http_status=404)
        _assert_plan_scope(plan_row, plan_date=plan_date, vehicle_id=vehicle_id)

        canonical_tasks = load_manual_reorder_policy_tasks_conn(con, int(plan_id))
        current_token = build_manual_reorder_state_token(plan_row, canonical_tasks)
        if current_token != state_token.strip():
            raise ManualReorderServiceError(
                'PLAN_STATE_CONFLICT',
                'Plan durumu değişti; yeniden yükleyin',
                http_status=409,
            )

        canonical_ids = [task_id(t) for t in canonical_tasks]
        try:
            validated_ids = validate_manual_reorder(canonical_tasks, ordered_item_ids)
        except ManualReorderValidationError as exc:
            raise _service_error_from_validation(exc) from exc

        changed = validated_ids != canonical_ids
        route_state_invalidated = False
        snapshot_deactivated = False
        etas_cleared = False

        if changed:
            reorder_plan_items_by_plan_id_conn(
                con, session_user_id, int(plan_id), validated_ids,
            )
            inv = invalidate_plan_route_state_after_manual_reorder_conn(con, int(plan_id))
            route_state_invalidated = True
            snapshot_deactivated = int(inv.get('snapshots_deactivated') or 0) > 0
            etas_cleared = int(inv.get('etas_cleared') or 0) > 0

        plan_row = get_plan_row_by_id_conn(con, int(plan_id))
        refreshed_tasks = load_manual_reorder_policy_tasks_conn(con, int(plan_id))
        new_token = build_manual_reorder_state_token(plan_row or {}, refreshed_tasks)
        new_ordered_ids, _ = _build_context_tasks(refreshed_tasks)

        con.commit()

        daily_tasks = list_plan_tasks(
            str(plan_row.get('plan_tarihi') or ''),
            str(plan_row.get('arac_external_id') or ''),
        )
        return {
            'ok': True,
            'plan_id': int(plan_id),
            'plan_date': str(plan_row.get('plan_tarihi') or ''),
            'vehicle_id': str(plan_row.get('arac_external_id') or ''),
            'state_token': new_token,
            'ordered_item_ids': new_ordered_ids,
            'changed': changed,
            'route_state_invalidated': route_state_invalidated,
            'snapshot_deactivated': snapshot_deactivated,
            'etas_cleared': etas_cleared,
            'daily_tasks': daily_tasks,
        }
    except ManualReorderServiceError:
        con.rollback()
        raise
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

# -*- coding: utf-8 -*-
"""Pure route order policy — move locks and ACIL safe insert (U1 additive core).

No DB, Flask, or global state. Production wiring is deferred to U2+.
"""
from __future__ import annotations

from typing import Any

INACTIVE_PLAN_STATUSES = frozenset({'IPTAL', 'ERTELENDI', 'GIDILEMEDI'})
LOCKED_PLAN_STATUSES = frozenset({'TAMAMLANDI', 'BASLADI'})
KNOWN_PLAN_STATUSES = frozenset({
    'PLANLANDI', 'BASLADI', 'TAMAMLANDI', 'IPTAL', 'ERTELENDI', 'GIDILEMEDI',
})
KNOWN_VISIT_STATES = frozenset({'OUTSIDE', 'ARRIVED', 'DEPARTED_PENDING', 'DEPARTED'})
MOVABLE_VISIT_STATES = frozenset({'OUTSIDE'})


class RouteOrderPolicyError(ValueError):
    """Invalid task input for order policy helpers."""


def normalize_plan_status(value: Any) -> str | None:
    """Normalize plan status; None/blank → None."""
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def normalize_visit_state(value: Any) -> str | None:
    """Normalize visit state; None/blank → None (treated as no visit row)."""
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _plan_status_raw(task: dict) -> Any:
    if 'status' in task and task.get('status') is not None:
        return task.get('status')
    if 'durum' in task and task.get('durum') is not None:
        return task.get('durum')
    return task.get('status') or task.get('durum')


def _visit_state_raw(task: dict) -> Any:
    if task.get('visit_state') is not None:
        return task.get('visit_state')
    visit = task.get('visit')
    if isinstance(visit, dict) and visit.get('state') is not None:
        return visit.get('state')
    return None


def _timestamp_raw(task: dict, field: str) -> Any:
    if task.get(field) not in (None, ''):
        return task.get(field)
    visit = task.get('visit')
    if isinstance(visit, dict) and visit.get(field) not in (None, ''):
        return visit.get(field)
    return None


def task_id(task: dict) -> str:
    """Resolve canonical task id; raise RouteOrderPolicyError when missing."""
    for key in ('plan_item_id', 'task_id', 'id'):
        val = task.get(key)
        if val is not None and str(val).strip() != '':
            return str(val).strip()
    raise RouteOrderPolicyError('Task ID missing')


def movement_lock_reason(task: dict) -> str | None:
    """Deterministic lock code, or None when manually movable."""
    status = normalize_plan_status(_plan_status_raw(task))

    if status is None:
        return 'UNKNOWN_PLAN_STATUS'

    if status in INACTIVE_PLAN_STATUSES:
        return 'STATUS_INACTIVE'

    if status not in KNOWN_PLAN_STATUSES:
        return 'UNKNOWN_PLAN_STATUS'

    if status == 'TAMAMLANDI':
        return 'STATUS_TAMAMLANDI'

    if status == 'BASLADI':
        return 'STATUS_BASLADI'

    if status != 'PLANLANDI':
        return 'UNKNOWN_PLAN_STATUS'

    if _timestamp_raw(task, 'arrived_at') or _timestamp_raw(task, 'departed_at'):
        return 'VISIT_TIMESTAMP'

    visit = normalize_visit_state(_visit_state_raw(task))
    if visit is None:
        return None

    if visit not in KNOWN_VISIT_STATES:
        return 'UNKNOWN_VISIT_STATE'

    if visit == 'ARRIVED':
        return 'VISIT_ARRIVED'

    if visit == 'DEPARTED_PENDING':
        return 'VISIT_DEPARTED_PENDING'

    if visit == 'DEPARTED':
        return 'VISIT_DEPARTED_LEGACY'

    if visit == 'OUTSIDE':
        return None

    return 'UNKNOWN_VISIT_STATE'


def can_move_task(task: dict) -> bool:
    """True only for active PLANLANDI tasks with no visit lock."""
    return movement_lock_reason(task) is None


def classify_order_tasks(tasks: list[dict]) -> dict[str, Any]:
    """Classify tasks preserving input order."""
    movable_task_ids: list[str] = []
    locked_task_ids: list[str] = []
    inactive_task_ids: list[str] = []
    lock_reasons: dict[str, str] = {}

    for task in tasks:
        tid = task_id(task)
        reason = movement_lock_reason(task)
        if reason == 'STATUS_INACTIVE':
            inactive_task_ids.append(tid)
            lock_reasons[tid] = reason
        elif reason:
            locked_task_ids.append(tid)
            lock_reasons[tid] = reason
        else:
            movable_task_ids.append(tid)

    return {
        'movable_task_ids': movable_task_ids,
        'locked_task_ids': locked_task_ids,
        'lock_reasons': lock_reasons,
        'inactive_task_ids': inactive_task_ids,
    }


def compute_first_safe_insert_index(tasks: list[dict]) -> int:
    """Index immediately after the last non-movable task, or 0 when none locked."""
    last_locked_index = -1
    for index, task in enumerate(tasks):
        if not can_move_task(task):
            last_locked_index = index
    if last_locked_index < 0:
        return 0
    return last_locked_index + 1


def build_order_with_inserted_task(
    tasks: list[dict],
    new_task: dict,
    *,
    insert_index: int | None = None,
) -> list[dict]:
    """Return new task list with new_task inserted; inputs are not mutated."""
    new_tid = task_id(new_task)
    seen: set[str] = set()
    for task in tasks:
        tid = task_id(task)
        if tid in seen:
            raise RouteOrderPolicyError(f'Duplicate task ID: {tid}')
        seen.add(tid)
    if new_tid in seen:
        raise RouteOrderPolicyError(f'Duplicate task ID: {new_tid}')

    index = compute_first_safe_insert_index(tasks) if insert_index is None else insert_index
    if index < 0 or index > len(tasks):
        raise RouteOrderPolicyError(f'Insert index out of range: {index}')

    ordered = [dict(t) for t in tasks]
    ordered.insert(index, dict(new_task))
    return ordered

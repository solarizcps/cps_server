# -*- coding: utf-8 -*-
"""Canonical route constraint classification — shared by planner and apply."""
from __future__ import annotations

from typing import Any

LOCKED_STATUSES = frozenset({'TAMAMLANDI', 'BASLADI'})
LOCKED_VISIT_STATES = frozenset({'ARRIVED', 'DEPARTED', 'DEPARTED_PENDING'})
VALID_PRIORITIES = frozenset({'ACIL', 'YUKSEK', 'NORMAL', 'DUSUK'})


def normalize_priority(value: str | None) -> str:
    pri = (value or 'NORMAL').strip().upper()
    if pri not in VALID_PRIORITIES:
        return 'NORMAL'
    return pri


def load_visit_states_for_tasks(tasks: list[dict]) -> dict[int, dict]:
    """plan_item_id -> visit row."""
    from modules.planlama.arac_geofence_repo import geofence_tables_ready, get_visit_state

    if not geofence_tables_ready():
        return {}
    out: dict[int, dict] = {}
    for task in tasks:
        plan_is_id = task.get('plan_item_id')
        if not plan_is_id:
            continue
        visit = get_visit_state(int(plan_is_id))
        if visit:
            out[int(plan_is_id)] = visit
    return out


def _visit_fields(task: dict, visit_states: dict[int, dict] | None) -> tuple[str | None, str | None, str | None]:
    plan_is_id = task.get('plan_item_id')
    visit = (visit_states or {}).get(int(plan_is_id)) if plan_is_id else None
    if visit:
        return (
            visit.get('state'),
            visit.get('arrived_at'),
            visit.get('departed_at'),
        )
    return (
        task.get('visit_state'),
        task.get('arrived_at'),
        task.get('departed_at'),
    )


def _lock_reason(task: dict, visit_states: dict[int, dict] | None) -> str | None:
    status = (task.get('status') or 'PLANLANDI').upper()
    if status == 'IPTAL':
        return None
    if status in LOCKED_STATUSES:
        return status
    visit_state, arrived_at, departed_at = _visit_fields(task, visit_states)
    if visit_state in LOCKED_VISIT_STATES:
        return str(visit_state)
    if arrived_at or departed_at:
        return 'VISIT_TIMESTAMP'
    pri = normalize_priority(task.get('priority'))
    if pri == 'ACIL':
        return 'ACIL'
    return None


def classify_route_tasks(
    tasks: list[dict],
    visit_states: dict[int, dict] | None = None,
) -> dict[str, Any]:
    """Classify tasks for route planning and apply validation."""
    sorted_tasks = sorted(tasks, key=lambda x: x.get('order_no') or 0)
    locked_task_ids: list[str] = []
    eligible_task_ids: list[str] = []
    cancelled_task_ids: list[str] = []
    lock_reasons: dict[str, str] = {}
    important_task_ids: list[str] = []
    critical_task_ids: list[str] = []
    active_tasks: list[dict] = []

    for task in sorted_tasks:
        tid = str(task['id'])
        status = (task.get('status') or 'PLANLANDI').upper()
        pri = normalize_priority(task.get('priority'))

        if pri == 'ACIL':
            critical_task_ids.append(tid)
        if pri == 'YUKSEK':
            important_task_ids.append(tid)

        if status == 'IPTAL':
            cancelled_task_ids.append(tid)
            continue

        active_tasks.append(task)
        reason = _lock_reason(task, visit_states)
        if reason:
            locked_task_ids.append(tid)
            lock_reasons[tid] = reason
        elif status == 'PLANLANDI':
            eligible_task_ids.append(tid)

    return {
        'locked_task_ids': locked_task_ids,
        'eligible_task_ids': eligible_task_ids,
        'cancelled_task_ids': cancelled_task_ids,
        'lock_reasons': lock_reasons,
        'important_task_ids': important_task_ids,
        'critical_task_ids': critical_task_ids,
        'active_tasks': active_tasks,
    }


def active_tasks_sorted(tasks: list[dict]) -> list[dict]:
    return [
        t for t in sorted(tasks, key=lambda x: x.get('order_no') or 0)
        if (t.get('status') or 'PLANLANDI').upper() != 'IPTAL'
    ]


def active_task_ids(tasks: list[dict]) -> list[str]:
    return [str(t['id']) for t in active_tasks_sorted(tasks)]


def _start_matrix_index(
    output_ids: list[str],
    routable_by_id: dict[str, dict],
) -> int:
    for tid in reversed(output_ids):
        stop = routable_by_id.get(tid)
        if stop is not None:
            return int(stop['matrix_index'])
    return 0


def build_constrained_full_order(
    active_tasks: list[dict],
    constraints: dict[str, Any],
    routable_stops: list[dict],
    duration_matrix: list[list[float | None]],
    *,
    suggest_segment_order_fn,
) -> tuple[list[str], list[dict]]:
    """
    Build full active-task order preserving locked slot indices.
    Returns (full_task_ids, warnings).
    """
    from modules.planlama.road_routing.suggest import detect_important_order_warnings

    sorted_active = sorted(active_tasks, key=lambda x: x.get('order_no') or 0)
    locked = set(constraints.get('locked_task_ids') or [])
    eligible = set(constraints.get('eligible_task_ids') or [])
    routable_by_id = {str(s['id']): s for s in routable_stops}
    warnings: list[dict] = []
    output: list[str] = []
    idx = 0

    while idx < len(sorted_active):
        task = sorted_active[idx]
        tid = str(task['id'])
        if tid in locked or tid not in eligible:
            output.append(tid)
            idx += 1
            continue

        segment: list[dict] = []
        while idx < len(sorted_active):
            seg_task = sorted_active[idx]
            seg_id = str(seg_task['id'])
            if seg_id in eligible:
                segment.append(seg_task)
                idx += 1
            else:
                break

        seg_routable = [
            routable_by_id[str(t['id'])]
            for t in segment
            if str(t['id']) in routable_by_id
        ]
        if len(seg_routable) <= 1:
            output.extend(str(t['id']) for t in segment)
            continue

        old_routable_order = [str(t['id']) for t in seg_routable]
        start_index = _start_matrix_index(output, routable_by_id)
        new_routable_order = suggest_segment_order_fn(
            seg_routable,
            duration_matrix,
            start_index=start_index,
        )
        warnings.extend(
            detect_important_order_warnings(
                old_routable_order,
                new_routable_order,
                constraints.get('important_task_ids') or [],
            ),
        )
        routable_queue = list(new_routable_order)
        for seg_task in segment:
            seg_id = str(seg_task['id'])
            if seg_id in routable_by_id:
                output.append(routable_queue.pop(0))
            else:
                output.append(seg_id)

    return output, warnings


class RouteApplyConflictError(Exception):
    """Constraint violation — HTTP 409, no DB writes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        locked_task_ids: list[str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.locked_task_ids = locked_task_ids or []
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        out = {
            'ok': False,
            'code': self.code,
            'message': self.message,
            'error': self.message,
        }
        if self.locked_task_ids:
            out['locked_task_ids'] = self.locked_task_ids
        out.update(self.extra)
        return out


def validate_apply_task_ids(
    tasks: list[dict],
    proposed_ids: list[str],
    constraints: dict[str, Any],
) -> None:
    """Raise RouteApplyConflictError when payload violates route locks."""
    active = active_tasks_sorted(tasks)
    canonical_ids = [str(t['id']) for t in active]
    proposed = [str(tid) for tid in proposed_ids]
    locked = set(constraints.get('locked_task_ids') or [])
    cancelled = set(constraints.get('cancelled_task_ids') or [])
    critical = set(constraints.get('critical_task_ids') or [])

    if not proposed:
        raise RouteApplyConflictError('TASK_IDS_REQUIRED', 'task_ids gerekli')

    if cancelled.intersection(proposed):
        raise RouteApplyConflictError(
            'CANCELLED_TASK_IN_PAYLOAD',
            'İptal edilmiş işler rota sırasına dahil edilemez.',
            cancelled_task_ids=sorted(cancelled.intersection(proposed)),
        )

    if set(proposed) != set(canonical_ids):
        raise RouteApplyConflictError(
            'TASK_SET_MISMATCH',
            'Görev listesi plan ile uyuşmuyor.',
            expected=sorted(canonical_ids),
            received=sorted(proposed),
        )

    if len(proposed) != len(canonical_ids):
        raise RouteApplyConflictError(
            'TASK_SET_MISMATCH',
            'Görev listesi eksik veya fazla.',
        )

    moved_locked = [
        tid for i, tid in enumerate(canonical_ids)
        if tid in locked and proposed[i] != tid
    ]
    if moved_locked:
        raise RouteApplyConflictError(
            'LOCKED_TASK_MOVE',
            'Tamamlanmış, başlamış veya kilitli işler taşınamaz.',
            locked_task_ids=moved_locked,
        )

    def _subseq(order: list[str], allowed: set[str]) -> list[str]:
        return [tid for tid in order if tid in allowed]

    if critical:
        if _subseq(proposed, critical) != _subseq(canonical_ids, critical):
            raise RouteApplyConflictError(
                'CRITICAL_ORDER_CHANGED',
                'Acil işlerin sırası değiştirilemez.',
                critical_task_ids=sorted(critical),
            )

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


# ── U3B — Manual reorder validation (pure, no DB) ───────────────────────────


class ManualReorderValidationError(Exception):
    """Fail-closed manual reorder validation error with stable machine code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        task_id: str | None = None,
        canonical_index: int | None = None,
        proposed_index: int | None = None,
        segment_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.task_id = task_id
        self.canonical_index = canonical_index
        self.proposed_index = proposed_index
        self.segment_index = segment_index

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            'code': self.code,
            'message': self.message,
        }
        if self.task_id is not None:
            out['task_id'] = self.task_id
        if self.canonical_index is not None:
            out['canonical_index'] = self.canonical_index
        if self.proposed_index is not None:
            out['proposed_index'] = self.proposed_index
        if self.segment_index is not None:
            out['segment_index'] = self.segment_index
        return out


def _normalize_proposed_task_ids(proposed_task_ids: list[Any]) -> list[str]:
    if not isinstance(proposed_task_ids, list):
        raise ManualReorderValidationError(
            'INVALID_PROPOSED_ORDER',
            'Proposed order must be a list of task IDs',
        )
    normalized: list[str] = []
    for index, raw in enumerate(proposed_task_ids):
        if raw is None or str(raw).strip() == '':
            raise ManualReorderValidationError(
                'INVALID_PROPOSED_ORDER',
                f'Proposed task ID missing at index {index}',
                proposed_index=index,
            )
        normalized.append(str(raw).strip())
    return normalized


def _canonical_task_ids(tasks: list[dict]) -> list[str]:
    if not isinstance(tasks, list):
        raise ManualReorderValidationError(
            'INVALID_CANONICAL_TASKS',
            'Canonical tasks must be a list',
        )
    ids: list[str] = []
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ManualReorderValidationError(
                'INVALID_CANONICAL_TASKS',
                f'Canonical task at index {index} must be a dict',
                canonical_index=index,
            )
        try:
            tid = task_id(task)
        except RouteOrderPolicyError as exc:
            raise ManualReorderValidationError(
                'MISSING_TASK_ID',
                str(exc),
                canonical_index=index,
            ) from exc
        if tid in seen:
            raise ManualReorderValidationError(
                'DUPLICATE_CANONICAL_TASK_ID',
                f'Duplicate canonical task ID: {tid}',
                task_id=tid,
                canonical_index=index,
            )
        seen.add(tid)
        ids.append(tid)
    return ids


def build_manual_reorder_segments(tasks: list[dict]) -> list[dict[str, Any]]:
    """
    Build locked/movable segment model from canonical task order.

    Locked tasks are fixed boundaries; movable tasks belong to a segment index
    between those boundaries (or at the ends).
    """
    canonical_ids = _canonical_task_ids(tasks)
    segments: list[dict[str, Any]] = []
    segment_index = 0
    index = 0
    while index < len(tasks):
        if not can_move_task(tasks[index]):
            segments.append({
                'kind': 'locked',
                'segment_index': segment_index,
                'task_id': canonical_ids[index],
                'canonical_index': index,
                'lock_reason': movement_lock_reason(tasks[index]),
            })
            segment_index += 1
            index += 1
            continue
        start = index
        movable_ids: list[str] = []
        while index < len(tasks) and can_move_task(tasks[index]):
            movable_ids.append(canonical_ids[index])
            index += 1
        segments.append({
            'kind': 'movable',
            'segment_index': segment_index,
            'start_index': start,
            'end_index': index,
            'task_ids': list(movable_ids),
        })
        segment_index += 1
    return segments


def validate_manual_reorder(
    tasks: list[dict],
    proposed_task_ids: list[Any],
) -> list[str]:
    """
    Validate a proposed manual reorder against canonical task order.

    Returns the normalized proposed ID list on success. Inputs are not mutated.
    Raises ManualReorderValidationError on any rule violation.
    """
    canonical_ids = _canonical_task_ids(tasks)
    proposed = _normalize_proposed_task_ids(proposed_task_ids)

    if len(proposed) != len(canonical_ids):
        raise ManualReorderValidationError(
            'TASK_SET_MISMATCH',
            'Proposed order length does not match canonical task count',
        )

    seen_proposed: set[str] = set()
    for index, tid in enumerate(proposed):
        if tid in seen_proposed:
            raise ManualReorderValidationError(
                'DUPLICATE_PROPOSED_TASK_ID',
                f'Duplicate proposed task ID: {tid}',
                task_id=tid,
                proposed_index=index,
            )
        seen_proposed.add(tid)

    canonical_set = set(canonical_ids)
    proposed_set = set(proposed)
    if proposed_set != canonical_set:
        missing = sorted(canonical_set - proposed_set)
        extra = sorted(proposed_set - canonical_set)
        if missing and not extra:
            raise ManualReorderValidationError(
                'TASK_SET_MISMATCH',
                f'Missing task IDs in proposed order: {", ".join(missing)}',
                task_id=missing[0],
            )
        if extra and not missing:
            raise ManualReorderValidationError(
                'TASK_SET_MISMATCH',
                f'Extra task IDs in proposed order: {", ".join(extra)}',
                task_id=extra[0],
            )
        raise ManualReorderValidationError(
            'TASK_SET_MISMATCH',
            'Proposed task set does not match canonical task set',
        )

    for index, (task, cid) in enumerate(zip(tasks, canonical_ids)):
        if not can_move_task(task) and proposed[index] != cid:
            raise ManualReorderValidationError(
                'LOCKED_TASK_MOVE',
                f'Locked task cannot move: {cid}',
                task_id=cid,
                canonical_index=index,
                proposed_index=index,
            )

    segments = build_manual_reorder_segments(tasks)
    for segment in segments:
        if segment['kind'] != 'movable':
            continue
        start = int(segment['start_index'])
        end = int(segment['end_index'])
        canonical_seg = canonical_ids[start:end]
        proposed_seg = proposed[start:end]
        if sorted(proposed_seg) != sorted(canonical_seg):
            raise ManualReorderValidationError(
                'SEGMENT_BOUNDARY_CROSS',
                'Movable task crossed a locked segment boundary',
                segment_index=int(segment['segment_index']),
            )

    return list(proposed)

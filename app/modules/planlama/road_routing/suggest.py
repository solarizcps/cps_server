# -*- coding: utf-8 -*-
"""Suggested visit order heuristic — matrix + priority/time guards."""
from __future__ import annotations

from typing import Any

PRIORITY_WEIGHT = {
    'ACIL': 0,
    'YUKSEK': 1,
    'NORMAL': 2,
    'DUSUK': 3,
}

# Yalnızca sıralama skorunda — gerçek rota süresi/mesafesi değişmez.
PRIORITY_TRAVEL_BONUS_S = {
    'ACIL': 5400.0,
    'YUKSEK': 3000.0,
    'NORMAL': 0.0,
    'DUSUK': 0.0,
}


def _effective_travel_s(stop: dict, duration_s: float) -> float:
    bonus = PRIORITY_TRAVEL_BONUS_S.get(_normalize_priority(stop.get('priority')), 0.0)
    return max(0.0, float(duration_s) - bonus)


def _time_minutes(label: str | None) -> int | None:
    if not label or label == '—':
        return None
    s = str(label).strip()
    if ':' not in s:
        return None
    parts = s.split(':')
    try:
        h, m = int(parts[0]), int(parts[1])
        return h * 60 + m
    except (TypeError, ValueError, IndexError):
        return None


def _normalize_priority(value: str | None) -> str:
    pri = (value or 'NORMAL').strip().upper()
    if pri not in PRIORITY_WEIGHT:
        return 'NORMAL'
    return pri


def _score_stop(
    stop: dict,
    duration_matrix: list[list[float | None]],
    current: int,
) -> tuple:
    mi = int(stop['matrix_index'])
    dur = duration_matrix[current][mi]
    if dur is None:
        dur = 1e12
    else:
        dur = _effective_travel_s(stop, float(dur))
    pri = PRIORITY_WEIGHT.get(_normalize_priority(stop.get('priority')), 2)
    tm = _time_minutes(stop.get('planned_time'))
    canonical = int(stop.get('order_no') or 0)
    return (dur, pri, tm if tm is not None else 9999, canonical)


def _pick_next(
    remaining: dict[str, dict],
    duration_matrix: list[list[float | None]],
    current: int,
    *,
    dusuk_only: bool = False,
    non_dusuk_only: bool = False,
) -> dict | None:
    candidates = list(remaining.values())
    if non_dusuk_only:
        candidates = [s for s in candidates if _normalize_priority(s.get('priority')) != 'DUSUK']
    elif dusuk_only:
        candidates = [s for s in candidates if _normalize_priority(s.get('priority')) == 'DUSUK']
    if not candidates:
        return None
    return min(candidates, key=lambda s: _score_stop(s, duration_matrix, current))


def suggest_stop_order(
    stops: list[dict[str, Any]],
    duration_matrix: list[list[float | None]],
    start_index: int = 0,
) -> list[str]:
    """
    Nearest-feasible heuristic on road duration matrix.
    stops: routable stops with 'id', 'matrix_index', 'priority', 'planned_time', 'order_no'
    Returns ordered task ids.
    """
    return suggest_segment_order(stops, duration_matrix, start_index=start_index)


def suggest_segment_order(
    stops: list[dict[str, Any]],
    duration_matrix: list[list[float | None]],
    start_index: int = 0,
) -> list[str]:
    """
    Optimize a single eligible segment.
    DUSUK stops cannot be placed before NORMAL/YUKSEK within the segment.
    """
    if not stops:
        return []
    remaining = {str(s['id']): s for s in stops}
    order_ids: list[str] = []
    current = start_index

    while True:
        pick = _pick_next(remaining, duration_matrix, current, non_dusuk_only=True)
        if pick is None:
            break
        order_ids.append(str(pick['id']))
        current = int(pick['matrix_index'])
        del remaining[str(pick['id'])]

    while remaining:
        pick = _pick_next(remaining, duration_matrix, current, dusuk_only=True)
        if pick is None:
            pick = _pick_next(remaining, duration_matrix, current)
        if pick is None:
            break
        order_ids.append(str(pick['id']))
        current = int(pick['matrix_index'])
        del remaining[str(pick['id'])]

    return order_ids


def detect_important_order_warnings(
    old_order: list[str],
    new_order: list[str],
    important_task_ids: list[str],
) -> list[dict]:
    warnings: list[dict] = []
    important = set(str(tid) for tid in important_task_ids)
    for tid in important:
        if tid not in old_order or tid not in new_order:
            continue
        if old_order.index(tid) != new_order.index(tid):
            warnings.append({
                'code': 'IMPORTANT_ORDER_CHANGED',
                'task_id': tid,
                'message': 'Yüksek öncelikli işin önerilen sırası değişti — onay gerektirir.',
            })
    return warnings

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
    if not stops:
        return []
    remaining = {s['id']: s for s in stops}
    order_ids: list[str] = []
    current = start_index

    def score(stop: dict) -> tuple:
        mi = int(stop['matrix_index'])
        dur = duration_matrix[current][mi]
        if dur is None:
            dur = 1e12
        pri = PRIORITY_WEIGHT.get(stop.get('priority') or 'NORMAL', 2)
        tm = _time_minutes(stop.get('planned_time'))
        canonical = int(stop.get('order_no') or 0)
        return (dur, pri, tm if tm is not None else 9999, canonical)

    while remaining:
        candidates = list(remaining.values())
        pick = min(candidates, key=score)
        order_ids.append(pick['id'])
        current = int(pick['matrix_index'])
        del remaining[pick['id']]
    return order_ids

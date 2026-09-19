# -*- coding: utf-8 -*-
"""ACİL-first full-route segment optimization (insertion order not binding)."""
from __future__ import annotations

import itertools
from typing import Any, Callable

from modules.planlama.arac_route_constraints import normalize_priority

_MAX_EXACT_PERMUTE = 8


def _leg_s(matrix: list[list[float | None]], a: int, b: int) -> float:
    if a < 0 or b < 0 or a >= len(matrix) or b >= len(matrix):
        return 1e12
    val = matrix[a][b]
    if val is None:
        return 1e12
    return float(val)


def segment_travel_cost(
    ordered_matrix_indices: list[int],
    *,
    start_index: int,
    matrix: list[list[float | None]],
    return_to_factory: bool,
) -> float:
    if not ordered_matrix_indices:
        return 0.0
    total = 0.0
    cur = start_index
    for mi in ordered_matrix_indices:
        total += _leg_s(matrix, cur, mi)
        cur = mi
    if return_to_factory:
        total += _leg_s(matrix, cur, 0)
    return total


def optimize_routable_segment_ids(
    routable_stops: list[dict],
    matrix: list[list[float | None]],
    *,
    start_index: int,
    return_to_factory: bool,
    seed_order_fn: Callable[..., list[str]] | None = None,
) -> list[str]:
    """
    Minimize travel time for a segment (exact permute if n<=8 else 2-opt seeds).
    Does not use insertion order; seed_order_fn optional for tie-break only.
    """
    if not routable_stops:
        return []
    if len(routable_stops) == 1:
        return [str(routable_stops[0]['id'])]

    stops = list(routable_stops)
    ids = [str(s['id']) for s in stops]
    mi_map = {str(s['id']): int(s['matrix_index']) for s in stops}

    def cost_for(id_order: list[str]) -> float:
        mis = [mi_map[i] for i in id_order]
        return segment_travel_cost(
            mis,
            start_index=start_index,
            matrix=matrix,
            return_to_factory=return_to_factory,
        )

    best_ids = list(ids)
    best_cost = cost_for(best_ids)

    if len(stops) <= _MAX_EXACT_PERMUTE:
        for perm in itertools.permutations(ids):
            c = cost_for(list(perm))
            if c < best_cost:
                best_cost = c
                best_ids = list(perm)
        return best_ids

    seeds: list[list[str]] = [list(ids)]
    if seed_order_fn:
        try:
            seeded = seed_order_fn(stops, matrix, start_index=start_index)
            if seeded and set(seeded) == set(ids):
                seeds.append(list(seeded))
        except Exception:
            pass
    seeds.append(sorted(ids))

    for seed in seeds:
        improved = _two_opt(seed, cost_for)
        c = cost_for(improved)
        if c < best_cost:
            best_cost = c
            best_ids = improved
    return best_ids


def _two_opt(order: list[str], cost_fn: Callable[[list[str]], float]) -> list[str]:
    best = list(order)
    best_c = cost_fn(best)
    n = len(best)
    if n < 3:
        return best
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                cand = best[: i + 1] + list(reversed(best[i + 1 : j + 1])) + best[j + 1 :]
                c = cost_fn(cand)
                if c < best_c:
                    best = cand
                    best_c = c
                    improved = True
    return best


def acil_before_normal_violation(
    proposed: list[str],
    tasks: list[dict],
    *,
    critical_ids: set[str],
) -> bool:
    """True when any ACİL appears after a non-ACİL eligible stop."""
    if not critical_ids:
        return False
    by_id = {str(t['id']): t for t in tasks}
    seen_normal = False
    for tid in proposed:
        task = by_id.get(str(tid))
        if not task:
            continue
        pri = normalize_priority(task.get('priority'))
        is_acil = pri == 'ACIL' and str(tid) in critical_ids
        if is_acil:
            if seen_normal:
                return True
        else:
            seen_normal = True
    return False


def active_has_acil(tasks: list[dict]) -> bool:
    for t in tasks:
        if normalize_priority(t.get('priority')) == 'ACIL':
            return True
    return False

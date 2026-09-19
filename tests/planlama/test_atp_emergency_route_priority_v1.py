# -*- coding: utf-8 -*-
"""ATP emergency-first full-route optimization R1 (temp DB / pure matrix)."""
from __future__ import annotations

from modules.planlama.arac_emergency_route_order import (
    acil_before_normal_violation,
    optimize_routable_segment_ids,
    segment_travel_cost,
)
from modules.planlama.arac_route_constraints import build_r07_constrained_full_order
from modules.planlama.road_routing.suggest import suggest_segment_order


def _matrix_factory_abcd() -> list[list[float | None]]:
    # 0=factory, A=1, B=2, C=3, D=4
    return [
        [0, 100, 400, 150, 500],
        [100, 0, 50, 200, 450],
        [400, 50, 0, 300, 100],
        [150, 200, 300, 0, 350],
        [500, 450, 100, 350, 0],
    ]


def _run_r07(tasks, routable, matrix):
    constraints = {
        'locked_task_ids': [],
        'eligible_task_ids': [str(t['id']) for t in tasks],
        'critical_task_ids': [str(t['id']) for t in tasks if t.get('priority') == 'ACIL'],
        'important_task_ids': [],
    }
    return build_r07_constrained_full_order(
        tasks,
        constraints,
        routable,
        matrix,
        suggest_segment_order_fn=suggest_segment_order,
    )[0]


def test_one_emergency_first_even_if_last_in_list():
    tasks = [
        {'id': 'n1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'NORMAL'},
        {'id': 'n2', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL'},
        {'id': 'a1', 'order_no': 99, 'status': 'PLANLANDI', 'priority': 'ACIL'},
    ]
    matrix = _matrix_factory_abcd()
    routable = [
        {'id': 'n1', 'matrix_index': 1, 'priority': 'NORMAL', 'order_no': 1},
        {'id': 'n2', 'matrix_index': 2, 'priority': 'NORMAL', 'order_no': 2},
        {'id': 'a1', 'matrix_index': 3, 'priority': 'ACIL', 'order_no': 99},
    ]
    order = _run_r07(tasks, routable, matrix)
    assert order.index('a1') < order.index('n1')
    assert order.index('a1') < order.index('n2')


def test_three_emergency_before_normals():
    tasks = [
        {'id': 'a1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'ACIL'},
        {'id': 'n1', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL'},
        {'id': 'a2', 'order_no': 3, 'status': 'PLANLANDI', 'priority': 'ACIL'},
        {'id': 'a3', 'order_no': 4, 'status': 'PLANLANDI', 'priority': 'ACIL'},
        {'id': 'n2', 'order_no': 5, 'status': 'PLANLANDI', 'priority': 'NORMAL'},
    ]
    matrix = _matrix_factory_abcd()
    routable = [
        {'id': 'a1', 'matrix_index': 1, 'priority': 'ACIL', 'order_no': 1},
        {'id': 'a2', 'matrix_index': 2, 'priority': 'ACIL', 'order_no': 3},
        {'id': 'a3', 'matrix_index': 3, 'priority': 'ACIL', 'order_no': 4},
        {'id': 'n1', 'matrix_index': 4, 'priority': 'NORMAL', 'order_no': 2},
        {'id': 'n2', 'matrix_index': 2, 'priority': 'NORMAL', 'order_no': 5},
    ]
    order = _run_r07(tasks, routable, matrix)
    acil_positions = [order.index('a1'), order.index('a2'), order.index('a3')]
    normal_positions = [order.index('n1'), order.index('n2')]
    assert max(acil_positions) < min(normal_positions)


def test_factory_return_leg_in_normal_segment_cost():
    matrix = _matrix_factory_abcd()
    stops = [
        {'id': 'n1', 'matrix_index': 1},
        {'id': 'n2', 'matrix_index': 2},
    ]
    with_return = segment_travel_cost(
        [1, 2], start_index=0, matrix=matrix, return_to_factory=True,
    )
    without = segment_travel_cost(
        [1, 2], start_index=0, matrix=matrix, return_to_factory=False,
    )
    assert with_return > without
    assert with_return - without == _matrix_factory_abcd()[2][0]


def test_traffic_prefers_full_route_over_nearest_neighbor():
    """S5: farther first stop can win when return leg is cheaper overall."""
    matrix = [
        [0, 10, 100],
        [10, 0, 5],
        [100, 5, 0],
    ]
    stops = [
        {'id': 'near', 'matrix_index': 1},
        {'id': 'far', 'matrix_index': 2},
    ]
    nn = suggest_segment_order(stops, matrix, start_index=0)
    opt = optimize_routable_segment_ids(
        stops, matrix, start_index=0, return_to_factory=True,
        seed_order_fn=suggest_segment_order,
    )
    nn_cost = segment_travel_cost(
        [1 if i == 'near' else 2 for i in nn],
        start_index=0,
        matrix=matrix,
        return_to_factory=True,
    )
    opt_cost = segment_travel_cost(
        [1 if i == 'near' else 2 for i in opt],
        start_index=0,
        matrix=matrix,
        return_to_factory=True,
    )
    assert opt_cost <= nn_cost


def test_acil_before_normal_apply_rule():
    tasks = [
        {'id': 'a1', 'order_no': 1, 'status': 'PLANLANDI', 'priority': 'ACIL'},
        {'id': 'n1', 'order_no': 2, 'status': 'PLANLANDI', 'priority': 'NORMAL'},
    ]
    assert not acil_before_normal_violation(
        ['a1', 'n1'], tasks, critical_ids={'a1'},
    )
    assert acil_before_normal_violation(
        ['n1', 'a1'], tasks, critical_ids={'a1'},
    )


def test_acil_internal_order_may_change():
    tasks = [
        {'id': 'a1', 'order_no': 50, 'status': 'PLANLANDI', 'priority': 'ACIL'},
        {'id': 'a2', 'order_no': 51, 'status': 'PLANLANDI', 'priority': 'ACIL'},
    ]
    assert not acil_before_normal_violation(
        ['a2', 'a1'], tasks, critical_ids={'a1', 'a2'},
    )

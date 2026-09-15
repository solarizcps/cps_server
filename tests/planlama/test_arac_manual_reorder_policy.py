# -*- coding: utf-8 -*-
"""U3B — Pure unit tests for manual reorder validation policy (no DB)."""
from __future__ import annotations

import copy

import pytest

from modules.planlama.arac_route_order_policy import (
    ManualReorderValidationError,
    RouteOrderPolicyError,
    build_manual_reorder_segments,
    validate_manual_reorder,
)


def _task(
    tid: str,
    *,
    status: str = 'PLANLANDI',
    visit_state: str | None = None,
    arrived_at: str | None = None,
    departed_at: str | None = None,
    priority: str = 'NORMAL',
) -> dict:
    row: dict = {'id': tid, 'status': status, 'priority': priority}
    if visit_state is not None:
        row['visit_state'] = visit_state
    if arrived_at is not None:
        row['arrived_at'] = arrived_at
    if departed_at is not None:
        row['departed_at'] = departed_at
    return row


def _ids(tasks: list[dict]) -> list[str]:
    return [t['id'] for t in tasks]


# ── A. Basic permutation ───────────────────────────────────────────────────


class TestBasicPermutation:
    def test_empty_lists_pass(self):
        assert validate_manual_reorder([], []) == []

    def test_single_movable_unchanged(self):
        tasks = [_task('a')]
        assert validate_manual_reorder(tasks, ['a']) == ['a']

    def test_all_movable_permutation_pass(self):
        tasks = [_task('a'), _task('b'), _task('c')]
        assert validate_manual_reorder(tasks, ['c', 'a', 'b']) == ['c', 'a', 'b']

    def test_same_order_pass(self):
        tasks = [_task('a'), _task('b')]
        assert validate_manual_reorder(tasks, ['a', 'b']) == ['a', 'b']

    def test_reverse_all_movable_pass(self):
        tasks = [_task('a'), _task('b'), _task('c')]
        assert validate_manual_reorder(tasks, ['c', 'b', 'a']) == ['c', 'b', 'a']


# ── B. Locked tasks ────────────────────────────────────────────────────────


class TestLockedTasks:
    def test_tamamlandi_prefix_segment_swap_pass(self):
        tasks = [_task('a', status='TAMAMLANDI'), _task('b'), _task('c')]
        assert validate_manual_reorder(tasks, ['a', 'c', 'b']) == ['a', 'c', 'b']

    def test_tamamlandi_prefix_locked_move_fail(self):
        tasks = [_task('a', status='TAMAMLANDI'), _task('b'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['b', 'a', 'c'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'
        assert exc.value.task_id == 'a'

    def test_basladi_middle_locked(self):
        tasks = [_task('a'), _task('b', status='BASLADI'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'c', 'b'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_arrived_middle_boundary_fail(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_departed_pending_locked(self):
        tasks = [_task('a'), _task('b', visit_state='DEPARTED_PENDING'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_legacy_departed_locked(self):
        tasks = [_task('a'), _task('b', visit_state='DEPARTED'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_iptal_inactive_locked(self):
        tasks = [_task('a', status='IPTAL'), _task('b'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['b', 'a', 'c'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_ertelendi_inactive_locked(self):
        tasks = [_task('a'), _task('b', status='ERTELENDI'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'c', 'b'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_gidilemedi_inactive_locked(self):
        tasks = [_task('a'), _task('b', status='GIDILEMEDI'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'c', 'b'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_arrived_at_timestamp_locks(self):
        tasks = [_task('a'), _task('b', arrived_at='2026-08-26 10:00:00'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_departed_at_timestamp_locks(self):
        tasks = [_task('a'), _task('b', departed_at='2026-08-26 11:00:00'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_unknown_plan_status_fail_closed(self):
        tasks = [_task('a', status='MYSTERY'), _task('b')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['b', 'a'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_unknown_visit_state_fail_closed(self):
        tasks = [_task('a'), _task('b', visit_state='ALIEN'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'c', 'b'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_multiple_locked_relative_order_preserved(self):
        tasks = [
            _task('a', status='TAMAMLANDI'),
            _task('b', visit_state='ARRIVED'),
            _task('c'),
        ]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['b', 'a', 'c'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'


# ── C. Segment rules ───────────────────────────────────────────────────────


class TestSegmentRules:
    def test_same_segment_swap_pass(self):
        tasks = [_task('a'), _task('b', status='TAMAMLANDI'), _task('c'), _task('d')]
        assert validate_manual_reorder(tasks, ['a', 'b', 'd', 'c']) == ['a', 'b', 'd', 'c']

    def test_same_segment_reverse_pass(self):
        tasks = [_task('a'), _task('b'), _task('c', status='TAMAMLANDI')]
        assert validate_manual_reorder(tasks, ['b', 'a', 'c']) == ['b', 'a', 'c']

    def test_single_boundary_crossing_fail(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_multi_segment_example_four(self):
        tasks = [
            _task('a'),
            _task('b', status='BASLADI'),
            _task('c'),
            _task('d', visit_state='DEPARTED_PENDING'),
            _task('e'),
        ]
        for bad in (['c', 'b', 'a', 'd', 'e'], ['a', 'b', 'e', 'd', 'c'], ['e', 'b', 'c', 'd', 'a']):
            with pytest.raises(ManualReorderValidationError):
                validate_manual_reorder(tasks, bad)

    def test_example_five_valid(self):
        tasks = [
            _task('a', status='TAMAMLANDI'),
            _task('b'),
            _task('c'),
            _task('d', visit_state='ARRIVED'),
            _task('e'),
            _task('f'),
        ]
        assert validate_manual_reorder(tasks, ['a', 'c', 'b', 'd', 'f', 'e']) == [
            'a', 'c', 'b', 'd', 'f', 'e',
        ]

    def test_example_five_invalid_boundary_cross(self):
        tasks = [
            _task('a', status='TAMAMLANDI'),
            _task('b'),
            _task('c'),
            _task('d', visit_state='ARRIVED'),
            _task('e'),
            _task('f'),
        ]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'e', 'c', 'd', 'b', 'f'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_locked_same_index_movable_crossing(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'c', 'b'])
        assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_build_segments_model(self):
        tasks = [
            _task('a', status='TAMAMLANDI'),
            _task('b'),
            _task('c', visit_state='ARRIVED'),
            _task('d'),
        ]
        segments = build_manual_reorder_segments(tasks)
        kinds = [s['kind'] for s in segments]
        assert kinds == ['locked', 'movable', 'locked', 'movable']
        assert segments[1]['task_ids'] == ['b']
        assert segments[3]['task_ids'] == ['d']


# ── D. ACIL / priority ─────────────────────────────────────────────────────


class TestAcilPriority:
    def test_acil_single_segment_permutation_pass(self):
        tasks = [_task('a', priority='ACIL'), _task('b'), _task('c', priority='YUKSEK')]
        assert validate_manual_reorder(tasks, ['c', 'b', 'a']) == ['c', 'b', 'a']

    def test_two_acil_swap_in_segment_pass(self):
        tasks = [_task('a', priority='ACIL'), _task('b', priority='ACIL'), _task('c')]
        assert validate_manual_reorder(tasks, ['b', 'a', 'c']) == ['b', 'a', 'c']

    def test_acil_cannot_cross_arrived_boundary(self):
        tasks = [_task('a', priority='ACIL'), _task('b', visit_state='ARRIVED'), _task('c')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['c', 'b', 'a'])
        assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_yuksek_movable_parity(self):
        tasks = [_task('a', priority='YUKSEK'), _task('b', priority='NORMAL')]
        assert validate_manual_reorder(tasks, ['b', 'a']) == ['b', 'a']

    def test_dusuk_movable_parity(self):
        tasks = [_task('a', priority='DUSUK'), _task('b')]
        assert validate_manual_reorder(tasks, ['b', 'a']) == ['b', 'a']


# ── E. Validation errors ───────────────────────────────────────────────────


class TestValidationErrors:
    def test_missing_id_in_proposed_set(self):
        tasks = [_task('a'), _task('b')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a'])
        assert exc.value.code == 'TASK_SET_MISMATCH'

    def test_extra_id_in_proposed_set(self):
        tasks = [_task('a')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'x'])
        assert exc.value.code == 'TASK_SET_MISMATCH'

    def test_duplicate_proposed_id(self):
        tasks = [_task('a'), _task('b')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'a'])
        assert exc.value.code == 'DUPLICATE_PROPOSED_TASK_ID'

    def test_duplicate_canonical_id(self):
        tasks = [_task('a'), _task('a')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['a', 'a'])
        assert exc.value.code == 'DUPLICATE_CANONICAL_TASK_ID'

    def test_missing_task_id_in_canonical(self):
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder([{'status': 'PLANLANDI'}], [])
        assert exc.value.code == 'MISSING_TASK_ID'

    def test_invalid_canonical_not_list(self):
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder('bad', [])  # type: ignore[arg-type]
        assert exc.value.code == 'INVALID_CANONICAL_TASKS'

    def test_invalid_proposed_not_list(self):
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder([], 'bad')  # type: ignore[arg-type]
        assert exc.value.code == 'INVALID_PROPOSED_ORDER'

    def test_plan_item_id_key_supported(self):
        tasks = [{'plan_item_id': 42, 'status': 'PLANLANDI'}, {'plan_item_id': 43, 'status': 'PLANLANDI'}]
        assert validate_manual_reorder(tasks, ['43', '42']) == ['43', '42']

    def test_input_not_mutated(self):
        tasks = [_task('a'), _task('b')]
        proposed = ['b', 'a']
        tasks_copy = copy.deepcopy(tasks)
        proposed_copy = list(proposed)
        validate_manual_reorder(tasks, proposed)
        assert tasks == tasks_copy
        assert proposed == proposed_copy

    def test_error_to_dict_metadata(self):
        tasks = [_task('a', status='TAMAMLANDI'), _task('b')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, ['b', 'a'])
        payload = exc.value.to_dict()
        assert payload['code'] == 'LOCKED_TASK_MOVE'
        assert payload['task_id'] == 'a'
        assert payload['canonical_index'] == 0

    def test_deterministic_repeat_calls(self):
        tasks = [_task('a'), _task('b'), _task('c')]
        first = validate_manual_reorder(tasks, ['c', 'a', 'b'])
        second = validate_manual_reorder(tasks, ['c', 'a', 'b'])
        assert first == second == ['c', 'a', 'b']

    def test_outside_visit_state_movable(self):
        tasks = [_task('a', visit_state='OUTSIDE'), _task('b')]
        assert validate_manual_reorder(tasks, ['b', 'a']) == ['b', 'a']

    def test_empty_proposed_id_rejected(self):
        tasks = [_task('a')]
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(tasks, [''])
        assert exc.value.code == 'INVALID_PROPOSED_ORDER'

    def test_canonical_dict_entry_must_be_dict(self):
        with pytest.raises(ManualReorderValidationError) as exc:
            validate_manual_reorder(['not-a-dict'], [])  # type: ignore[list-item]
        assert exc.value.code == 'INVALID_CANONICAL_TASKS'


class TestU1RegressionUnchanged:
    def test_compute_first_safe_insert_index_still_works(self):
        from modules.planlama.arac_route_order_policy import compute_first_safe_insert_index
        tasks = [_task('a', status='TAMAMLANDI'), _task('b')]
        assert compute_first_safe_insert_index(tasks) == 1

    def test_build_order_duplicate_still_raises_route_error(self):
        from modules.planlama.arac_route_order_policy import build_order_with_inserted_task
        tasks = [_task('a')]
        with pytest.raises(RouteOrderPolicyError):
            build_order_with_inserted_task(tasks, _task('a'))

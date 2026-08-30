# -*- coding: utf-8 -*-
"""Pure unit tests for arac_route_order_policy (U1 — no DB)."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from modules.planlama.arac_route_order_policy import (  # noqa: E402
    RouteOrderPolicyError,
    build_order_with_inserted_task,
    can_move_task,
    classify_order_tasks,
    compute_first_safe_insert_index,
    movement_lock_reason,
    normalize_plan_status,
    normalize_visit_state,
    task_id,
)

CANONICAL_DB = APP / 'mock_data.db'


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope='module')
def canonical_sha_before_after():
    if CANONICAL_DB.is_file():
        before = _sha256(CANONICAL_DB)
        yield before
        after = _sha256(CANONICAL_DB)
        assert before == after, 'Canonical DB SHA256 changed during tests'
    else:
        yield None
        assert not CANONICAL_DB.is_file(), 'Canonical DB was created during tests'


def _task(
    tid: str,
    *,
    status: str = 'PLANLANDI',
    visit_state: str | None = None,
    arrived_at: str | None = None,
    departed_at: str | None = None,
    priority: str = 'NORMAL',
    latitude: float | None = None,
) -> dict:
    row: dict = {
        'id': tid,
        'status': status,
        'priority': priority,
    }
    if visit_state is not None:
        row['visit_state'] = visit_state
    if arrived_at is not None:
        row['arrived_at'] = arrived_at
    if departed_at is not None:
        row['departed_at'] = departed_at
    if latitude is not None:
        row['latitude'] = latitude
    return row


# ── Normalization ───────────────────────────────────────────────────────────

class TestNormalization:
    def test_plan_status_case_and_whitespace(self):
        assert normalize_plan_status(' planlandi ') == 'PLANLANDI'
        assert normalize_plan_status(None) is None
        assert normalize_plan_status('') is None

    def test_visit_state_case_and_whitespace(self):
        assert normalize_visit_state(' outside ') == 'OUTSIDE'
        assert normalize_visit_state(None) is None
        assert normalize_visit_state('  ') is None


# ── Movability (1–16) ───────────────────────────────────────────────────────

class TestMovability:
    def test_01_planlandi_outside_movable(self):
        assert can_move_task(_task('1', visit_state='OUTSIDE')) is True

    def test_02_planlandi_no_visit_movable(self):
        assert can_move_task(_task('2')) is True

    def test_03_basladi_locked(self):
        assert movement_lock_reason(_task('3', status='BASLADI')) == 'STATUS_BASLADI'

    def test_04_tamamlandi_locked(self):
        assert movement_lock_reason(_task('4', status='TAMAMLANDI')) == 'STATUS_TAMAMLANDI'

    def test_05_iptal_inactive(self):
        assert movement_lock_reason(_task('5', status='IPTAL')) == 'STATUS_INACTIVE'

    def test_06_ertelendi_inactive(self):
        assert movement_lock_reason(_task('6', status='ERTELENDI')) == 'STATUS_INACTIVE'

    def test_07_gidilemedi_inactive(self):
        assert movement_lock_reason(_task('7', status='GIDILEMEDI')) == 'STATUS_INACTIVE'

    def test_08_arrived_locked(self):
        assert movement_lock_reason(_task('8', visit_state='ARRIVED')) == 'VISIT_ARRIVED'

    def test_09_departed_pending_locked(self):
        reason = movement_lock_reason(_task('9', visit_state='DEPARTED_PENDING'))
        assert reason == 'VISIT_DEPARTED_PENDING'

    def test_10_departed_legacy_locked(self):
        assert movement_lock_reason(_task('10', visit_state='DEPARTED')) == 'VISIT_DEPARTED_LEGACY'

    def test_11_arrived_at_timestamp_locked(self):
        assert movement_lock_reason(_task('11', arrived_at='2026-08-30 10:00:00')) == 'VISIT_TIMESTAMP'

    def test_12_departed_at_timestamp_locked(self):
        assert movement_lock_reason(_task('12', departed_at='2026-08-30 11:00:00')) == 'VISIT_TIMESTAMP'

    def test_13_unknown_visit_state_locked(self):
        assert movement_lock_reason(_task('13', visit_state='VISITED')) == 'UNKNOWN_VISIT_STATE'

    def test_14_none_visit_movable(self):
        assert can_move_task(_task('14', visit_state=None)) is True

    def test_15_acil_planlandi_outside_movable(self):
        assert can_move_task(_task('15', priority='ACIL', visit_state='OUTSIDE')) is True

    def test_16_yuksek_planlandi_outside_movable(self):
        assert can_move_task(_task('16', priority='YUKSEK', visit_state='OUTSIDE')) is True


# ── ACIL insert index (17–25) ───────────────────────────────────────────────

class TestAcilInsertIndex:
    def test_17_all_movable_index_zero(self):
        tasks = [_task('a'), _task('b')]
        assert compute_first_safe_insert_index(tasks) == 0

    def test_18_locked_prefix_then_movable(self):
        tasks = [_task('done', status='TAMAMLANDI'), _task('mov')]
        assert compute_first_safe_insert_index(tasks) == 1

    def test_19_two_locked_prefix(self):
        tasks = [
            _task('l1', status='TAMAMLANDI'),
            _task('l2', status='BASLADI'),
            _task('mov'),
        ]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_20_locked_block_acil_and_normal_movable(self):
        tasks = [
            _task('done', status='TAMAMLANDI'),
            _task('acil', priority='ACIL'),
            _task('norm'),
        ]
        assert compute_first_safe_insert_index(tasks) == 1

    def test_21_no_movable_tasks_end_index(self):
        tasks = [
            _task('a', status='TAMAMLANDI'),
            _task('b', visit_state='ARRIVED'),
        ]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_22_empty_list_index_zero(self):
        assert compute_first_safe_insert_index([]) == 0

    def test_23_multiple_acil_relative_order_preserved_on_insert(self):
        tasks = [
            _task('acil1', priority='ACIL'),
            _task('acil2', priority='ACIL'),
            _task('norm'),
        ]
        new_task = _task('new-acil', priority='ACIL')
        result = build_order_with_inserted_task(tasks, new_task)
        ids = [task_id(t) for t in result]
        assert ids == ['new-acil', 'acil1', 'acil2', 'norm']

    def test_24_same_input_same_output_deterministic(self):
        tasks = [_task('done', status='TAMAMLANDI'), _task('mov')]
        a = compute_first_safe_insert_index(tasks)
        b = compute_first_safe_insert_index(tasks)
        assert a == b == 1

    def test_25_input_list_not_mutated(self):
        tasks = [_task('a'), _task('b')]
        snapshot = [dict(t) for t in tasks]
        build_order_with_inserted_task(tasks, _task('new'))
        assert tasks == snapshot


# ── Scattered locked insert (U1.1) ──────────────────────────────────────────

class TestScatteredLockedInsert:
    def test_scattered_movable_arrived_movable_index_2(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2
        result = build_order_with_inserted_task(tasks, _task('acil', priority='ACIL'))
        assert [task_id(t) for t in result] == ['a', 'b', 'acil', 'c']

    def test_scattered_movable_basladi_movable(self):
        tasks = [_task('a'), _task('b', status='BASLADI'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_scattered_movable_departed_pending_movable(self):
        tasks = [_task('a'), _task('b', visit_state='DEPARTED_PENDING'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_scattered_movable_legacy_departed_movable(self):
        tasks = [_task('a'), _task('b', visit_state='DEPARTED'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_scattered_movable_arrived_at_locked_movable(self):
        tasks = [_task('a'), _task('b', arrived_at='2026-08-30 09:00:00'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_scattered_movable_departed_at_locked_movable(self):
        tasks = [_task('a'), _task('b', departed_at='2026-08-30 10:00:00'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_multiple_scattered_locked_tasks(self):
        tasks = [
            _task('a'),
            _task('b', status='BASLADI'),
            _task('c'),
            _task('d', visit_state='DEPARTED_PENDING'),
            _task('e'),
        ]
        assert compute_first_safe_insert_index(tasks) == 4
        result = build_order_with_inserted_task(tasks, _task('acil', priority='ACIL'))
        assert [task_id(t) for t in result] == ['a', 'b', 'c', 'd', 'acil', 'e']

    def test_unknown_visit_state_in_middle(self):
        tasks = [_task('a'), _task('b', visit_state='VISITED'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2
        result = build_order_with_inserted_task(tasks, _task('acil', priority='ACIL'))
        assert [task_id(t) for t in result] == ['a', 'b', 'acil', 'c']

    def test_unknown_plan_status_in_middle(self):
        tasks = [_task('a'), _task('b', status='MYSTERY'), _task('c')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_locked_task_at_end(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_no_locked_tasks_index_zero(self):
        tasks = [_task('a'), _task('b')]
        assert compute_first_safe_insert_index(tasks) == 0

    def test_only_locked_tasks_index_at_end(self):
        tasks = [_task('a', visit_state='ARRIVED'), _task('b', status='TAMAMLANDI')]
        assert compute_first_safe_insert_index(tasks) == 2

    def test_scattered_input_not_mutated(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        snapshot = [dict(t) for t in tasks]
        compute_first_safe_insert_index(tasks)
        build_order_with_inserted_task(tasks, _task('new'))
        assert tasks == snapshot

    def test_build_order_uses_computed_scattered_index(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        idx = compute_first_safe_insert_index(tasks)
        result = build_order_with_inserted_task(tasks, _task('acil', priority='ACIL'))
        assert idx == 2
        assert [task_id(t) for t in result] == ['a', 'b', 'acil', 'c']

    def test_duplicate_and_missing_id_guards_unchanged(self):
        tasks = [_task('a'), _task('b', visit_state='ARRIVED'), _task('c')]
        with pytest.raises(RouteOrderPolicyError, match='Duplicate task ID'):
            build_order_with_inserted_task(tasks, _task('b'))
        with pytest.raises(RouteOrderPolicyError, match='Task ID missing'):
            build_order_with_inserted_task(tasks, {'status': 'PLANLANDI'})

    def test_example_tamamlandi_prefix_index_1(self):
        tasks = [_task('done', status='TAMAMLANDI'), _task('a'), _task('b')]
        assert compute_first_safe_insert_index(tasks) == 1


# ── Validation (26–31) ──────────────────────────────────────────────────────

class TestValidation:
    def test_26_duplicate_id_raises(self):
        tasks = [_task('dup'), _task('other')]
        with pytest.raises(RouteOrderPolicyError, match='Duplicate task ID'):
            build_order_with_inserted_task(tasks, _task('dup'))

    def test_27_missing_task_id_raises(self):
        with pytest.raises(RouteOrderPolicyError, match='Task ID missing'):
            task_id({'status': 'PLANLANDI'})

    def test_28_durum_field_normalized_via_movement(self):
        t = {'id': 'x', 'durum': 'tamamlandi'}
        assert movement_lock_reason(t) == 'STATUS_TAMAMLANDI'

    def test_29_whitespace_status_normalized(self):
        t = {'id': 'x', 'status': '  basladi  '}
        assert movement_lock_reason(t) == 'STATUS_BASLADI'

    def test_30_unknown_plan_status_locked(self):
        assert movement_lock_reason(_task('u', status='MYSTERY')) == 'UNKNOWN_PLAN_STATUS'

    def test_31_coordinates_do_not_affect_movability(self):
        with_coords = _task('c1', latitude=41.0)
        without = _task('c2')
        assert can_move_task(with_coords) == can_move_task(without) is True


# ── classify_order_tasks & nested fields ────────────────────────────────────

class TestClassifyAndFields:
    def test_classify_splits_movable_locked_inactive(self):
        tasks = [
            _task('mov'),
            _task('done', status='TAMAMLANDI'),
            _task('cancel', status='IPTAL'),
            _task('visit', visit_state='ARRIVED'),
        ]
        out = classify_order_tasks(tasks)
        assert out['movable_task_ids'] == ['mov']
        assert out['locked_task_ids'] == ['done', 'visit']
        assert out['inactive_task_ids'] == ['cancel']
        assert out['lock_reasons']['done'] == 'STATUS_TAMAMLANDI'
        assert out['lock_reasons']['cancel'] == 'STATUS_INACTIVE'

    def test_nested_visit_state_and_plan_item_id(self):
        t = {
            'plan_item_id': 42,
            'durum': 'PLANLANDI',
            'visit': {'state': 'OUTSIDE'},
        }
        assert can_move_task(t) is True
        assert task_id(t) == '42'

    def test_build_order_uses_safe_index_by_default(self):
        tasks = [_task('locked', status='TAMAMLANDI'), _task('mov')]
        result = build_order_with_inserted_task(tasks, _task('new'))
        assert [task_id(t) for t in result] == ['locked', 'new', 'mov']

    def test_no_db_import_in_policy_module(self, canonical_sha_before_after):
        import ast
        import modules.planlama.arac_route_order_policy as mod
        source = Path(mod.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        imported = {
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        imported_from = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        forbidden = {'get_conn', 'db', 'flask', 'sqlite3'}
        assert not any(name in forbidden for name in imported)
        assert not any(
            mod_name.split('.')[0] in forbidden
            for mod_name in imported_from
        )
        if canonical_sha_before_after is not None:
            assert len(canonical_sha_before_after) == 64
        else:
            assert not CANONICAL_DB.is_file()


def test_canonical_db_unchanged(canonical_sha_before_after):
    if canonical_sha_before_after is not None:
        assert len(canonical_sha_before_after) == 64
    else:
        assert not CANONICAL_DB.is_file()

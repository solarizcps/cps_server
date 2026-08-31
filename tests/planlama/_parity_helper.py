# -*- coding: utf-8 -*-
"""Stdin JSON helper for JS/Python manual reorder contract parity tests."""
from __future__ import annotations

import json
import sys

from modules.planlama.arac_route_order_policy import (
    ManualReorderValidationError,
    build_manual_reorder_segments,
    can_move_task,
    movement_lock_reason,
    task_id,
    validate_manual_reorder,
)


def _build_js_context(tasks: list[dict], plan_id: int = 41, token: str = 'parity') -> dict:
    segments = build_manual_reorder_segments(tasks)
    segment_by_task: dict[str, int] = {}
    for segment in segments:
        if segment['kind'] == 'locked':
            segment_by_task[str(segment['task_id'])] = int(segment['segment_index'])
        else:
            for tid in segment['task_ids']:
                segment_by_task[str(tid)] = int(segment['segment_index'])

    ordered_ids = [task_id(t) for t in tasks]
    task_rows = []
    for index, task in enumerate(tasks):
        tid = task_id(task)
        task_rows.append({
            'task_id': tid,
            'order_no': index + 1,
            'can_move': can_move_task(task),
            'lock_reason': movement_lock_reason(task),
            'segment_index': segment_by_task.get(tid),
            'visible': task.get('visible', True),
            'priority': task.get('priority', 'NORMAL'),
        })
    return {
        'plan_id': plan_id,
        'state_token': token,
        'ordered_item_ids': ordered_ids,
        'tasks': task_rows,
    }


def main() -> int:
    payload = json.load(sys.stdin)
    op = payload.get('op')
    if op == 'validate':
        try:
            order = validate_manual_reorder(payload['tasks'], payload['proposed'])
            print(json.dumps({'ok': True, 'order': order}))
        except ManualReorderValidationError as exc:
            print(json.dumps({'ok': False, 'code': exc.code, 'message': exc.message}))
        return 0
    if op == 'context':
        print(json.dumps(_build_js_context(payload['tasks'], payload.get('plan_id', 41), payload.get('token', 'parity'))))
        return 0
    print(json.dumps({'ok': False, 'code': 'BAD_OP', 'message': f'Unknown op: {op}'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

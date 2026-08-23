# -*- coding: utf-8 -*-
"""Araç Takip & Plan — plan sırası, WhatsApp mesaj (V1.3 canonical)."""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List

from modules.planlama.arac_dashboard_service import PRIORITY_LABEL, get_arac_dashboard_dto


def get_tasks_for_session(
    user_id: int,
    plan_date: str,
    vehicle_external_id: str | None = None,
) -> List[dict]:
    from modules.planlama.arac_takip_repo import list_plan_tasks, tables_ready
    if tables_ready() and vehicle_external_id:
        return list_plan_tasks(plan_date, vehicle_external_id)
    if tables_ready():
        return []
    from copy import deepcopy
    dto = get_arac_dashboard_dto()
    return deepcopy(dto['daily_tasks'])


def list_plans_for_date(plan_date: str) -> List[dict]:
    from modules.planlama.arac_takip_repo import list_plans_for_date as _list_plans
    return _list_plans(plan_date)


def get_daily_plan_aggregate(plan_date: str) -> Dict[str, Any]:
    from modules.planlama.arac_takip_repo import build_daily_plan_aggregate
    return build_daily_plan_aggregate(plan_date)


def reorder_tasks(
    user_id: int,
    plan_date: str,
    task_ids: List[str],
    vehicle_external_id: str | None = None,
) -> List[dict]:
    from modules.planlama.arac_takip_repo import list_plan_tasks, reorder_plan_items_bulk, tables_ready
    if tables_ready() and vehicle_external_id and task_ids:
        return reorder_plan_items_bulk(user_id, plan_date, vehicle_external_id, task_ids)
    if tables_ready() and vehicle_external_id:
        return list_plan_tasks(plan_date, vehicle_external_id)
    return get_tasks_for_session(user_id, plan_date, vehicle_external_id)


def move_task(
    user_id: int,
    plan_date: str,
    task_id: str,
    direction: str,
    vehicle_external_id: str | None = None,
) -> List[dict]:
    from modules.planlama.arac_takip_repo import reorder_plan_items, tables_ready
    if tables_ready() and vehicle_external_id:
        return reorder_plan_items(user_id, plan_date, vehicle_external_id, task_id, direction)
    tasks = get_tasks_for_session(user_id, plan_date, vehicle_external_id)
    ids = [t['id'] for t in sorted(tasks, key=lambda x: x['order_no'])]
    try:
        idx = ids.index(task_id)
    except ValueError:
        return tasks
    if direction == 'up' and idx > 0:
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
    elif direction == 'down' and idx < len(ids) - 1:
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
    by_id = {t['id']: t for t in tasks}
    ordered = []
    for i, tid in enumerate(ids):
        if tid in by_id:
            t = dict(by_id[tid])
            t['order_no'] = i + 1
            ordered.append(t)
    return ordered


def build_whatsapp_plan_message(dto: Dict[str, Any]) -> str:
    lines = [
        'GÜNLÜK ARAÇ PROGRAMI',
        f"Tarih: {dto.get('date_label', dto.get('date', ''))}",
        f"Sürücü: {dto.get('selected_driver_name', '—')}",
        f"Plaka: {dto.get('selected_plate', '—')}",
        '',
    ]
    for t in dto.get('daily_tasks') or []:
        pri = t.get('priority_label') or PRIORITY_LABEL.get(t.get('priority', ''), '')
        lines.append(f"{t.get('order_no')}. [{pri}] {t.get('job_title') or t.get('company_name')}")
        lines.append(f"Firma: {t.get('company_name', '—')}")
        if t.get('phone'):
            lines.append(f"Telefon: {t['phone']}")
        lines.append(f"Saat: {t.get('planned_time', '—')}")
        lines.append(f"Adres: {t.get('address_text', '—')}")
        if t.get('location_url'):
            lines.append(f"Konum: {t['location_url']}")
        lines.append('')
    return '\n'.join(lines).strip()


def whatsapp_web_url(message: str, phone: str = '') -> str:
    text = urllib.parse.quote(message)
    if phone:
        digits = ''.join(c for c in phone if c.isdigit())
        if digits.startswith('0'):
            digits = '90' + digits[1:]
        elif not digits.startswith('90'):
            digits = '90' + digits
        return f'https://wa.me/{digits}?text={text}'
    return f'https://wa.me/?text={text}'


def add_job_request(payload: dict, session_user_id: int = 0) -> dict:
    from modules.planlama.arac_lokasyon_service import create_job_request
    return create_job_request(session_user_id, payload)

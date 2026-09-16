# -*- coding: utf-8 -*-
"""Dikkat paneli Planı Değiştir — plan_item_id + UI binding regression."""
from __future__ import annotations

from modules.planlama.arac_today_operations_service import (  # noqa: E402
    _build_alerts,
    _primary_plan_item_for_vehicle,
)


def test_primary_plan_item_prefers_started_then_sira():
    items = [
        {
            'arac_external_id': 'V1',
            'plan_item_id': 20,
            'status': 'PLANLANDI',
            'sira': 2,
        },
        {
            'arac_external_id': 'V1',
            'plan_item_id': 15,
            'status': 'BASLADI',
            'sira': 1,
        },
    ]
    assert _primary_plan_item_for_vehicle(items, 'V1') == 15


def test_gps_stale_alert_includes_plan_item_for_vehicle():
    alerts = _build_alerts(
        '2026-09-07',
        vehicles=[{
            'arac_external_id': '990DEMO001',
            'plate': '34 DEMO 001',
            'plan_id': 43,
            'latest_gps': {'recorded_at': '2000-01-01T00:00:00'},
            'route_state': 'OK',
        }],
        items=[{
            'arac_external_id': '990DEMO001',
            'plan_item_id': 155,
            'status': 'BASLADI',
            'sira': 1,
            'has_coordinates': True,
        }],
        filom_by_id={},
    )
    stale = [a for a in alerts if a.get('type') == 'GPS_STALE']
    assert len(stale) == 1
    assert stale[0]['plan_item_id'] == 155


def test_planned_time_passed_alert_keeps_plan_item_id():
    from datetime import datetime, timedelta

    plan_date = datetime.now().strftime('%Y-%m-%d')
    past = (datetime.now() - timedelta(hours=2)).strftime('%H:%M')
    alerts = _build_alerts(
        plan_date,
        vehicles=[],
        items=[{
            'arac_external_id': 'V9',
            'plan_item_id': 901,
            'status': 'PLANLANDI',
            'sira': 1,
            'planned_time': past,
            'has_coordinates': True,
        }],
        filom_by_id={},
    )
    late = [a for a in alerts if a.get('type') == 'PLANNED_TIME_PASSED']
    assert len(late) == 1
    assert late[0]['plan_item_id'] == 901

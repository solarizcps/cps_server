# -*- coding: utf-8 -*-
"""Apply response route_snapshot includes client readback fields."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.planlama.test_atp_traffic_route_apply_contracts_r07_v1 import temp_db  # noqa: F401


def test_google_apply_enriches_route_snapshot(temp_db, monkeypatch):
    """POST apply (google, profile_only) returns routing_provider + google metrics on snapshot."""
    from tests.planlama.test_atp_traffic_route_apply_contracts_r07_v1 import (
        PLAN_DATE,
        VID,
        _client,
        _seed_plan,
    )
    from modules.planlama.arac_google_route_options_models import (
        GoogleRouteLegDTO,
        GoogleRouteOptionDTO,
    )

    seeded = _seed_plan(temp_db)
    tasks = seeded['tasks']
    task_ids = [str(t['id']) for t in sorted(tasks, key=lambda x: x['order_no'])]

    def _mock_opt(**kwargs):
        ids = [str(t['id']) for t in kwargs.get('ordered_stops') or []]
        legs = [
            GoogleRouteLegDTO(
                from_index=i,
                to_index=i + 1,
                distance_m=5000.0,
                distance_km_display=5.0,
                drive_seconds=600.0,
                static_seconds=540.0,
                drive_minutes_display=10,
                toll_present=False,
            )
            for i in range(len(ids))
        ]
        legs.append(
            GoogleRouteLegDTO(
                from_index=len(ids),
                to_index=len(ids) + 1,
                distance_m=8000.0,
                distance_km_display=8.0,
                drive_seconds=900.0,
                static_seconds=800.0,
                drive_minutes_display=15,
                toll_present=False,
            )
        )
        return GoogleRouteOptionDTO(
            profile_code='google-traffic-fast',
            profile_label='En Hızlı',
            ordered_stop_ids=ids,
            ordered_stop_names=['A'] * len(ids),
            distance_m=123456.0,
            distance_km_display=123.5,
            drive_seconds=3600.0,
            static_drive_seconds=3400.0,
            traffic_delay_seconds=200.0,
            service_seconds=600.0,
            total_plan_seconds=7200.0,
            drive_minutes_display=60,
            traffic_delay_minutes_display=3,
            total_plan_minutes_display=120,
            return_exact='2026-01-01T18:30:00+03:00',
            return_display='18:30',
            toll_present=False,
            toll_price_known=False,
            toll_price=None,
            encoded_polyline='_p~iF~ps|U_ulLnnqC_mqNvxq`@',
            legs=legs,
            calculation_complete=True,
            error_code=None,
        )

    monkeypatch.setenv('GOOGLE_ROUTES_API_KEY', 'TEST_DUMMY_KEY')
    client = _client(can_edit=True)
    with patch(
        'modules.planlama.arac_google_route_apply_service._fetch_google_option',
        side_effect=_mock_opt,
    ):
        r = client.post(
            '/planlama/arac-takip/api/route/apply',
            json={
                'date': PLAN_DATE,
                'vehicle_id': VID,
                'task_ids': task_ids,
                'apply_source': 'google',
                'google_profile': 'fastest',
                'departure_time': '08:00',
                'profile_only': True,
                'keep_current_order': True,
            },
        )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body.get('ok') is True
    snap = body.get('route_snapshot') or {}
    assert 'google-traffic-fast' in str(snap.get('routing_provider') or '')
    assert snap.get('google_distance_m') == 123456.0
    assert snap.get('google_return_display') == '18:30'
    assert snap.get('departure_time') == '08:00'
    assert isinstance(snap.get('stop_order'), list) and snap['stop_order']
    assert isinstance(snap.get('geometry_pairs'), list) and len(snap['geometry_pairs']) >= 2

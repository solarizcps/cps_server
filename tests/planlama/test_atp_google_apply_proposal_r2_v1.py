# -*- coding: utf-8 -*-
"""Google apply proposal — TEMP DB contract tests."""
from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
_MIGRATIONS = APP / 'migrations'
PLAN_DATE = '2026-09-22'
VID = '991GAPPLY01'
USER_ID = 1
BASE = {'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True, 'base_name': 'Fabrika'}


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, restore_path: str | None = None):
    import tempfile
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='google_apply_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
        '187_arac_plan_cikis_saati.py',
        '188_arac_plan_is_zaman_alanlari.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, aktif, created_at, updated_at, updated_by
        ) VALUES (?,?,?,?,1,datetime('now'),datetime('now'),1)
        """,
        ('Fabrika', 41.0, 29.0, 'Istanbul'),
    )
    con.commit()
    con.close()
    bind_temp_db_path(db_path)
    try:
        yield db_path
    finally:
        if restore_path:
            bind_temp_db_path(restore_path)


@pytest.fixture
def temp_db(atp_planlama_db_guard_session):
    session_db = atp_planlama_db_guard_session['temp_db']
    with _temp_atp_db(restore_path=session_db) as db_path:
        yield db_path


def _seed_vehicle(db_path: str) -> tuple[list[str], str]:
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    dep = (datetime.now(ZoneInfo('Europe/Istanbul')) + timedelta(hours=1)).strftime('%H:%M')
    specs = [
        ('N1', 'NORMAL', 41.01, 29.01),
        ('N2', 'NORMAL', 41.02, 29.02),
        ('A1', 'ACIL', 41.03, 29.03),
    ]
    for name, pri, lat, lon in specs:
        t = create_is_talebi(
            USER_ID,
            {
                'tarih': PLAN_DATE,
                'is': name,
                'firma': name,
                'latitude': lat,
                'longitude': lon,
                'oncelik': pri,
                'save_to_master': False,
            },
        )
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, VID, '34 GA', None, 'Drv', dep, None)
    tasks = list_plan_tasks(PLAN_DATE, VID)
    ids = [str(t['id']) for t in sorted(tasks, key=lambda x: x['order_no'])]
    acil = [str(t['id']) for t in tasks if (t.get('priority') or '').upper() == 'ACIL']
    normal = [str(t['id']) for t in tasks if (t.get('priority') or '').upper() != 'ACIL']
    suggested = acil + normal
    return suggested, dep


def _mock_google_option(*args, **kwargs):
    from modules.planlama.arac_google_route_options_models import (
        GoogleRouteLegDTO,
        GoogleRouteOptionDTO,
    )
    from modules.planlama.road_routing.google_routes_provider import PROFILE_TRAFFIC_FAST

    ordered = kwargs.get('ordered_stops') or []
    ids = [str(t['id']) for t in ordered]
    legs = [
        GoogleRouteLegDTO(0, 1, 1000, 1.0, 600, 600, 10, False)
        for _ in range(max(1, len(ids)))
    ]
    return GoogleRouteOptionDTO(
        profile_code=PROFILE_TRAFFIC_FAST,
        profile_label='En Hızlı',
        ordered_stop_ids=ids,
        ordered_stop_names=['x'] * len(ids),
        distance_m=10000,
        distance_km_display=10.0,
        drive_seconds=3600,
        static_drive_seconds=3500,
        traffic_delay_seconds=100,
        service_seconds=600,
        total_plan_seconds=4200,
        drive_minutes_display=60,
        traffic_delay_minutes_display=2,
        total_plan_minutes_display=70,
        return_exact='2026-09-22T20:00:00+03:00',
        return_display='20:00',
        toll_present=False,
        toll_price_known=False,
        toll_price=None,
        encoded_polyline='_p~iF~ps|U_ulLnnqC_mqNvxq`@',
        legs=legs,
        calculation_complete=True,
        error_code=None,
    )


def test_google_apply_with_proposal_reorders(temp_db):
    suggested, dep = _seed_vehicle(temp_db)
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_google_route_apply_proposal import build_google_apply_proposal
    from modules.planlama.arac_google_route_apply_service import apply_google_route_order_and_snapshot

    tasks = list_plan_tasks(PLAN_DATE, VID)
    proposal = build_google_apply_proposal(
        plan_date=PLAN_DATE,
        vehicle_id=VID,
        departure_time=dep,
        google_profile='fastest',
        suggested_order=suggested,
        tasks=tasks,
    )
    with patch(
        'modules.planlama.arac_google_route_apply_service._fetch_google_option',
        side_effect=_mock_google_option,
    ):
        apply_google_route_order_and_snapshot(
            USER_ID,
            PLAN_DATE,
            VID,
            suggested,
            google_profile='fastest',
            departure_time=dep,
            google_apply_proposal=proposal,
        )
    tasks2 = list_plan_tasks(PLAN_DATE, VID)
    order = [str(t['id']) for t in sorted(tasks2, key=lambda x: x['order_no'])]
    assert order == suggested
    assert (tasks2[0].get('priority') or '').upper() == 'ACIL'


def test_tampered_order_409_zero_write(temp_db):
    suggested, dep = _seed_vehicle(temp_db)
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_google_route_apply_proposal import build_google_apply_proposal
    from modules.planlama.arac_google_route_apply_service import apply_google_route_order_and_snapshot
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    tasks = list_plan_tasks(PLAN_DATE, VID)
    before = [str(t['id']) for t in sorted(tasks, key=lambda x: x['order_no'])]
    proposal = build_google_apply_proposal(
        plan_date=PLAN_DATE,
        vehicle_id=VID,
        departure_time=dep,
        google_profile='fastest',
        suggested_order=suggested,
        tasks=tasks,
    )
    tampered = list(reversed(suggested))
    with pytest.raises(RouteApplyConflictError):
        apply_google_route_order_and_snapshot(
            USER_ID,
            PLAN_DATE,
            VID,
            tampered,
            google_profile='fastest',
            departure_time=dep,
            google_apply_proposal=proposal,
        )
    tasks2 = list_plan_tasks(PLAN_DATE, VID)
    after = [str(t['id']) for t in sorted(tasks2, key=lambda x: x['order_no'])]
    assert after == before


def test_stale_proposal_expired_409(temp_db):
    suggested, dep = _seed_vehicle(temp_db)
    from modules.planlama.arac_takip_repo import list_plan_tasks
    from modules.planlama.arac_google_route_apply_proposal import build_google_apply_proposal
    from modules.planlama.arac_google_route_apply_service import apply_google_route_order_and_snapshot
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    tasks = list_plan_tasks(PLAN_DATE, VID)
    proposal = build_google_apply_proposal(
        plan_date=PLAN_DATE,
        vehicle_id=VID,
        departure_time=dep,
        google_profile='fastest',
        suggested_order=suggested,
        tasks=tasks,
        ttl_minutes=-1,
    )
    with pytest.raises(RouteApplyConflictError) as exc:
        apply_google_route_order_and_snapshot(
            USER_ID,
            PLAN_DATE,
            VID,
            suggested,
            google_profile='fastest',
            departure_time=dep,
            google_apply_proposal=proposal,
        )
    assert exc.value.code == 'STALE_PROPOSAL'

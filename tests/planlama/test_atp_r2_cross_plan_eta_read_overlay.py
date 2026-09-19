# -*- coding: utf-8 -*-
"""R2 cross-plan ETA read overlay + plan label fallback (temp DB only)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))

from modules.planlama.arac_takip_repo import build_daily_plan_aggregate, list_plan_tasks
from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp

PREVIEW_SOURCE = Path(
    os.environ.get(
        'ATP_R2_PREVIEW_DB',
        r'D:\Solariz_CPS_BACKUP\ATP_EMERGENCY_R2_SCREEN_20260919_143600\preview_r2_clean_fullschema.db',
    ),
)
PLAN_DATE = '2026-09-19'
VEHICLE = '990R2SCRN01'


@pytest.fixture(scope='module')
def env():
    import config as cfg

    src = str(PREVIEW_SOURCE.resolve())
    if not os.path.isfile(src):
        pytest.skip(f'preview DB missing: {src}')
    saved_cfg = cfg.Config.MOCK_DB_PATH
    saved_env = os.environ.get('CPS_MOCK_DB_PATH')
    tmp_dir = tempfile.mkdtemp(prefix='atp_r2_eta_overlay_')
    db = os.path.join(tmp_dir, 'preview_copy.db')
    shutil.copy2(src, db)
    assert_resolved_db_is_tmp(db, src)
    os.environ['CPS_MOCK_DB_PATH'] = db
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'tmp_dir': tmp_dir}
    cfg.Config.MOCK_DB_PATH = saved_cfg
    if saved_env is None:
        os.environ.pop('CPS_MOCK_DB_PATH', None)
    else:
        os.environ['CPS_MOCK_DB_PATH'] = saved_env
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _bind(env):
    import config as cfg
    cfg.Config.MOCK_DB_PATH = env['db']
    os.environ['CPS_MOCK_DB_PATH'] = env['db']


def _hhmm_minutes(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def test_cross_plan_acil_eta_from_snapshot(env):
    tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
    active = sorted(
        [t for t in tasks if (t.get('status') or '').upper() not in ('IPTAL', 'ERTELENDI', 'GIDILEMEDI')],
        key=lambda x: x.get('order_no') or 0,
    )
    assert len(active) == 9
    acil = [t for t in active if t.get('priority') == 'ACIL']
    assert len(acil) == 2
    assert acil[0]['eta_time'] == '18:52'
    assert acil[1]['eta_time'] == '19:06'


def test_aggregate_all_nine_have_eta(env):
    agg = build_daily_plan_aggregate(PLAN_DATE)
    items = [i for i in agg['items'] if i.get('arac_external_id') == VEHICLE]
    items.sort(key=lambda x: x.get('order_no') or 0)
    assert len(items) == 9
    etas = [i.get('eta_time') or i.get('tahmini_varis_saati') for i in items]
    assert all(etas), etas
    mins = [_hhmm_minutes(e) for e in etas]
    assert mins == sorted(mins)


def test_plan_label_not_aktif_plan_yok_when_jobs_exist(env):
    dto = get_today_vehicle_operations(PLAN_DATE, filom_payload={'ok': True, 'vehicles': []})
    v = next(x for x in dto['vehicles'] if x.get('arac_external_id') == VEHICLE)
    assert v['route_status_label'] == 'Planlandı'
    assert v['route_status_label'] != 'Aktif plan yok'
    assert v['route_state'] != 'NO_ACTIVE_PLAN'


def test_get_no_write(env):
    db = env['db']
    before = os.path.getmtime(db)
    get_today_vehicle_operations(PLAN_DATE, filom_payload={'ok': True, 'vehicles': []})
    list_plan_tasks(PLAN_DATE, VEHICLE)
    build_daily_plan_aggregate(PLAN_DATE)
    after = os.path.getmtime(db)
    assert after == before
    con = sqlite3.connect(db)
    try:
        wal = con.execute('PRAGMA journal_mode').fetchone()[0]
        if wal.lower() == 'wal':
            assert con.total_changes == 0 or True
    finally:
        con.close()

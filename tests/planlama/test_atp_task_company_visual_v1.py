# -*- coding: utf-8 -*-
"""ATP görev/firma görsel ayrımı — temp DB + WhatsApp read path."""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(APP))

from modules.planlama.arac_takip_repo import list_plan_tasks
from modules.planlama.arac_whatsapp_message_service import (
    build_whatsapp_plan_message_v2,
    load_whatsapp_plan_context,
)
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
    tmp_dir = tempfile.mkdtemp(prefix='atp_task_co_visual_')
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


def test_dto_has_separate_task_and_company_fields(env):
    tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
    assert tasks
    for t in tasks:
        assert 'job_title' in t and 'company_name' in t
        assert 'address_text' in t


def test_whatsapp_message_task_before_company_no_slash(env):
    from modules.planlama.arac_whatsapp_message_service import build_whatsapp_api_response

    ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
    assert ctx
    msg = build_whatsapp_plan_message_v2(ctx)
    assert ' / ' not in msg
    assert 'İş:' not in msg
    assert '*1. ACİL —' in msg or '*1.' in msg
    if 'Acil numune teslim edilecek' in msg:
        assert 'Firma: Atlas Ayakkabı' in msg
    api = build_whatsapp_api_response(PLAN_DATE, VEHICLE)
    assert api.get('ok') is True
    assert api.get('message_preview')
    stops = api.get('preview_stops') or []
    assert len(stops) == 9
    assert stops[0].get('job_title')
    assert stops[0].get('company_name')
    assert 'Başlangıç' in api.get('message_preview', '') or 'Fabrika' in api.get('message_preview', '')


def test_global_order_and_eta_unchanged(env):
    tasks = sorted(list_plan_tasks(PLAN_DATE, VEHICLE), key=lambda x: x.get('order_no') or 0)
    assert [t['plan_item_id'] for t in tasks] == [169, 170, 168, 167, 166, 165, 164, 163, 162]
    etas = [t.get('eta_time') for t in tasks]
    assert all(etas)
    assert etas[0] == '18:52'


def test_get_no_write(env):
    import os
    db = env['db']
    before = os.path.getmtime(db)
    load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
    list_plan_tasks(PLAN_DATE, VEHICLE)
    assert os.path.getmtime(db) == before

# -*- coding: utf-8 -*-
"""Fix-1 regression: defer_next_day tuple-unpack bug + full defer flow."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

APP = os.path.join(os.path.dirname(__file__), '..', '..', 'app')
_APP_DIR = Path(APP)
_MIGRATIONS = _APP_DIR / 'migrations'
if APP not in __import__('sys').path:
    __import__('sys').path.insert(0, APP)

PLAN_DATE = '2026-09-25'
TARGET_DATE = '2026-09-26'
VID_A = '991DEFER_VEH_A'
VID_B = '991DEFER_VEH_B'
USER_ID = 1


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_db(*, restore_path: str | None = None):
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='defer_fix1_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
        '179_arac_gps_snapshot_p1.py',
    ):
        _run_migration(db_path, mig)
    bind_temp_db_path(db_path)
    try:
        yield db_path
    finally:
        if restore_path:
            bind_temp_db_path(restore_path)


@pytest.fixture
def temp_db(atp_planlama_db_guard_session):
    session_db = atp_planlama_db_guard_session['temp_db']
    with _temp_db(restore_path=session_db) as db_path:
        yield db_path


def _seed(db_path: str) -> dict:
    """Seed iki araç, araç A'ya iki PLANLANDI iş."""
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        get_active_plan_row,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    items: list[int] = []
    for label, vid in [('DeferMe', VID_A), ('OtherJob', VID_A), ('BVehicle', VID_B)]:
        t = create_is_talebi(USER_ID, {
            'tarih': PLAN_DATE,
            'is': label,
            'firma': f'{label} Co',
            'latitude': 41.0 + len(items) * 0.01,
            'longitude': 29.0 + len(items) * 0.01,
            'oncelik': 'NORMAL',
            'save_to_master': False,
        })
        assign_to_plan(
            USER_ID, t['id'], PLAN_DATE, vid,
            f'34 {label[:3]}', None, 'TestDriver', '10:00', None,
        )
        tasks = list_plan_tasks(PLAN_DATE, vid)
        items.append(int(str(tasks[-1]['plan_item_id'])))

    plan_a = get_active_plan_row(PLAN_DATE, VID_A)
    plan_b = get_active_plan_row(PLAN_DATE, VID_B)
    return {
        'defer_id': items[0],       # DeferMe — target of defer
        'other_id': items[1],       # OtherJob — stays on VID_A
        'b_id': items[2],           # BVehicle — on VID_B
        'plan_a_id': int(plan_a['id']),
        'plan_b_id': int(plan_b['id']),
    }


def _audit_rows(db_path: str, plan_is_id: int, action: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            'SELECT * FROM arac_plan_is_degisim WHERE plan_is_id=? AND action=? ORDER BY id',
            (plan_is_id, action),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _row(db_path: str, plan_is_id: int) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(
            'SELECT * FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
        ).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 1. Core: defer no longer raises TypeError
# ---------------------------------------------------------------------------
def test_defer_does_not_raise_tuple_error(temp_db):
    """Before fix: ProgrammingError: type 'tuple' is not supported."""
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']

    # Must not raise
    result = apply_plan_job_change(did, USER_ID, {
        'action': 'defer_next_day',
        'reason': 'test defer fix-1',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': str(uuid.uuid4()),
    })
    assert result.get('ok') is True


# ---------------------------------------------------------------------------
# 2. Old item: PLANLANDI → ERTELENDI (not PLANLANDI)
# ---------------------------------------------------------------------------
def test_defer_old_item_status_becomes_ertelendi(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']
    before = _row(temp_db, did)['durum']

    apply_plan_job_change(did, USER_ID, {
        'action': 'defer_next_day',
        'reason': 'status test',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': str(uuid.uuid4()),
    })

    after = _row(temp_db, did)['durum']
    assert before == 'PLANLANDI'
    assert after == 'ERTELENDI'


# ---------------------------------------------------------------------------
# 3. New plan item created on target date with PLANLANDI
# ---------------------------------------------------------------------------
def test_defer_creates_new_plan_item(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']

    result = apply_plan_job_change(did, USER_ID, {
        'action': 'defer_next_day',
        'reason': 'new item test',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': str(uuid.uuid4()),
    })

    new_id = result.get('new_plan_is_id')
    assert new_id is not None
    assert isinstance(new_id, int), f'new_plan_is_id must be int, got {type(new_id)}'
    new_row = _row(temp_db, new_id)
    assert new_row['durum'] == 'PLANLANDI'


# ---------------------------------------------------------------------------
# 4. Audit record created with integer plan_is_id
# ---------------------------------------------------------------------------
def test_defer_audit_row_created(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']
    cid = str(uuid.uuid4())

    apply_plan_job_change(did, USER_ID, {
        'action': 'defer_next_day',
        'reason': 'audit test',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': cid,
    })

    rows = _audit_rows(temp_db, did, 'defer_next_day')
    assert len(rows) == 1
    ar = rows[0]
    assert ar['plan_is_id'] == did
    assert ar['action'] == 'defer_next_day'
    assert ar['new_plan_tarihi'] == TARGET_DATE
    assert ar['client_submit_id'] == cid


# ---------------------------------------------------------------------------
# 5. Transaction integrity: no partial state — missing reason rejected
# ---------------------------------------------------------------------------
def test_defer_no_partial_state_on_missing_reason(temp_db):
    """Empty reason must be rejected before any DB write."""
    from modules.planlama.arac_plan_change_service import (
        apply_plan_job_change, get_plan_job_detail, PlanChangeError,
    )

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']

    with pytest.raises((PlanChangeError, ValueError)):
        apply_plan_job_change(did, USER_ID, {
            'action': 'defer_next_day',
            'reason': '',           # blank reason — service should reject
            'target_date': TARGET_DATE,
            'target_vehicle_external_id': det['arac_external_id'],
            'sofor_adi': det['sofor_adi_snapshot'],
            'plan_tarihi': det['plan_tarihi'],
            'client_submit_id': str(uuid.uuid4()),
        })

    # DB must be rolled back — old item still PLANLANDI
    after = _row(temp_db, did)['durum']
    rows = _audit_rows(temp_db, did, 'defer_next_day')
    assert after == 'PLANLANDI', f'Old item should stay PLANLANDI, got {after!r}'
    assert len(rows) == 0, f'No audit row expected on rejection, got {len(rows)}'


# ---------------------------------------------------------------------------
# 6. Idempotency: same client_submit_id → duplicate response, no second row
# ---------------------------------------------------------------------------
def test_defer_idempotency(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']
    cid = str(uuid.uuid4())
    payload = {
        'action': 'defer_next_day',
        'reason': 'idempotency test',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': cid,
    }

    r1 = apply_plan_job_change(did, USER_ID, payload)
    r2 = apply_plan_job_change(did, USER_ID, payload)

    assert r1.get('ok') is True
    # Second call must be idempotent (duplicate flag or ok without double-writing)
    assert r2.get('ok') is True or r2.get('duplicate') is True
    rows = _audit_rows(temp_db, did, 'defer_next_day')
    assert len(rows) == 1, f'Expected 1 audit row, got {len(rows)}'


# ---------------------------------------------------------------------------
# 7. new_plan_is_id is integer in result dict
# ---------------------------------------------------------------------------
def test_defer_result_new_plan_is_id_is_int(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change, get_plan_job_detail

    ctx = _seed(temp_db)
    did = ctx['defer_id']
    det = get_plan_job_detail(did)['detail']

    result = apply_plan_job_change(did, USER_ID, {
        'action': 'defer_next_day',
        'reason': 'int check',
        'target_date': TARGET_DATE,
        'target_vehicle_external_id': det['arac_external_id'],
        'sofor_adi': det['sofor_adi_snapshot'],
        'plan_tarihi': det['plan_tarihi'],
        'client_submit_id': str(uuid.uuid4()),
    })

    nid = result.get('new_plan_is_id')
    assert isinstance(nid, int), f'new_plan_is_id must be int, got {type(nid)!r}: {nid!r}'
    assert nid > 0


# ---------------------------------------------------------------------------
# 8. API route returns 200 with ok=true
# ---------------------------------------------------------------------------
def test_defer_api_route_returns_200(temp_db):
    from modules.planlama.arac_takip_repo import (
        assign_to_plan, create_is_talebi, ensure_seed_locations, list_plan_tasks,
    )
    import flask
    import importlib
    import modules.auth as auth_mod
    import modules.planlama.arac_takip_routes as routes_mod
    from functools import wraps

    def _open(f):
        @wraps(f)
        def wrapper(*a, **kw):
            return f(*a, **kw)
        return wrapper

    auth_mod.yetki_gerekli = lambda *a, **k: _open
    auth_mod.yetki_var = lambda *a, **k: True
    routes_mod = importlib.reload(routes_mod)
    routes_mod.yetki_gerekli = auth_mod.yetki_gerekli
    routes_mod.yetki_var = auth_mod.yetki_var

    app = flask.Flask(
        __name__,
        template_folder=str(_APP_DIR / 'templates'),
        static_folder=str(_APP_DIR / 'static'),
    )
    app.secret_key = 'defer-route-test'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)

    ensure_seed_locations(USER_ID)
    t = create_is_talebi(USER_ID, {
        'tarih': PLAN_DATE,
        'is': 'RouteDefer',
        'firma': 'Route Co',
        'latitude': 41.2,
        'longitude': 29.2,
        'oncelik': 'NORMAL',
        'save_to_master': False,
    })
    assign_to_plan(USER_ID, t['id'], PLAN_DATE, VID_A, '34 RTE', None, 'TestDrv', '11:00', None)
    tasks = list_plan_tasks(PLAN_DATE, VID_A)
    pid = int(str(tasks[-1]['plan_item_id']))

    with app.test_client() as client:
        with app.test_request_context():
            import flask as fk
            fk.g.user_id = USER_ID
        resp = client.post(
            f'/planlama/arac-takip/api/plan-job/{pid}/change',
            json={
                'action': 'defer_next_day',
                'reason': 'route test',
                'target_date': TARGET_DATE,
                'target_vehicle_external_id': VID_A,
                'sofor_adi': 'TestDrv',
                'plan_tarihi': PLAN_DATE,
                'client_submit_id': str(uuid.uuid4()),
            },
        )
    data = resp.get_json()
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {data}'
    assert data.get('ok') is True

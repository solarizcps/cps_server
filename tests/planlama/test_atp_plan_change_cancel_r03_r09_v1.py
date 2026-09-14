# -*- coding: utf-8 -*-
"""R03/R09 — transfer deferred, soft cancel, consumer parity, guards."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

APP = os.path.join(os.path.dirname(__file__), '..', '..', 'app')
_APP_DIR = Path(APP)
_MIGRATIONS = _APP_DIR / 'migrations'
if APP not in __import__('sys').path:
    __import__('sys').path.insert(0, APP)

PLAN_DATE = '2026-09-20'
VID_A = '991R03VEH_A'
VID_B = '991R03VEH_B'
USER_ID = 1
TRANSFER_DEFERRED_MSG = 'Başka araca aktarma özelliği şu anda kullanıma kapalıdır'


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, restore_path: str | None = None):
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='r03_r09_')
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
    with _temp_atp_db(restore_path=session_db) as db_path:
        yield db_path


def _client(*, can_edit: bool = True):
    import importlib
    from functools import wraps

    import flask
    import modules.auth as auth_mod
    import modules.planlama.arac_takip_routes as routes_mod

    def _open(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapper

    auth_mod.yetki_gerekli = lambda *a, **k: _open
    auth_mod.yetki_var = lambda *a, **k: can_edit
    routes_mod = importlib.reload(routes_mod)
    routes_mod.yetki_gerekli = auth_mod.yetki_gerekli
    routes_mod.yetki_var = auth_mod.yetki_var

    app = flask.Flask(
        __name__,
        template_folder=str(_APP_DIR / 'templates'),
        static_folder=str(_APP_DIR / 'static'),
    )
    app.secret_key = 'r03-r09-test'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)
    return app.test_client()


def _seed_scenario():
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        get_active_plan_row,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    specs = [
        ('Tamam', 'NORMAL', VID_A, 1),
        ('Basladi', 'NORMAL', VID_A, 2),
        ('EskiAcil', 'ACIL', VID_A, 3),
        ('NormalMove', 'NORMAL', VID_A, 4),
        ('Yuksek', 'YUKSEK', VID_A, 5),
        ('TargetNorm', 'NORMAL', VID_B, 1),
    ]
    item_ids = []
    for label, pri, vid, _ in specs:
        t = create_is_talebi(USER_ID, {
            'tarih': PLAN_DATE,
            'is': label,
            'firma': f'{label} Co',
            'latitude': 40.9 + len(item_ids) * 0.01,
            'longitude': 29.1 + len(item_ids) * 0.01,
            'oncelik': pri,
            'save_to_master': False,
        })
        assign_to_plan(USER_ID, t['id'], PLAN_DATE, vid, f'34 {label[:3]}', None, 'Drv', '09:00', None)
        items = list_plan_tasks(PLAN_DATE, vid)
        item_ids.append(int(str(items[-1]['plan_item_id'])))
    plan_a = get_active_plan_row(PLAN_DATE, VID_A)
    plan_b = get_active_plan_row(PLAN_DATE, VID_B)
    con = sqlite3.connect(os.environ['CPS_MOCK_DB_PATH'])
    con.row_factory = sqlite3.Row
    try:
        move_id = item_ids[3]
        con.execute("UPDATE arac_gunluk_plan_is SET durum='TAMAMLANDI' WHERE id=?", (item_ids[0],))
        con.execute("UPDATE arac_gunluk_plan_is SET durum='BASLADI' WHERE id=?", (item_ids[1],))
        con.commit()
    finally:
        con.close()
    return {
        'plan_a_id': int(plan_a['id']),
        'plan_b_id': int(plan_b['id']),
        'completed_id': item_ids[0],
        'started_id': item_ids[1],
        'movable_id': move_id,
        'cancel_id': item_ids[4],
    }


def _active_tasks(vid: str) -> list[dict]:
    from modules.planlama.arac_takip_repo import list_plan_tasks

    active = [
        t for t in list_plan_tasks(PLAN_DATE, vid)
        if (t.get('status') or '').upper() not in {'IPTAL', 'ERTELENDI', 'GIDILEMEDI'}
    ]
    return sorted(active, key=lambda x: x.get('order_no') or 0)


def _active_ids(vid: str) -> list[int]:
    return [int(t['plan_item_id']) for t in _active_tasks(vid)]


def _active_sira_contiguous(vid: str) -> bool:
    tasks = _active_tasks(vid)
    siralar = [int(t.get('order_no') or 0) for t in tasks]
    return siralar == list(range(1, len(siralar) + 1))


def _full_snapshot(db_path: str, ctx: dict) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        def _items(plan_id: int) -> list[tuple]:
            rows = con.execute(
                """
                SELECT id, plan_id, sira, durum
                FROM arac_gunluk_plan_is
                WHERE plan_id=?
                ORDER BY id
                """,
                (int(plan_id),),
            ).fetchall()
            return [(int(r['id']), int(r['plan_id']), int(r['sira']), str(r['durum'])) for r in rows]

        audit = con.execute(
            """
            SELECT plan_is_id, action, old_arac_external_id, new_arac_external_id, old_durum, new_durum
            FROM arac_plan_is_degisim
            ORDER BY id
            """,
        ).fetchall()
        audit_rows = [
            (
                int(r['plan_is_id']),
                str(r['action']),
                r['old_arac_external_id'],
                r['new_arac_external_id'],
                r['old_durum'],
                r['new_durum'],
            )
            for r in audit
        ]
        snap = []
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_rota_snapshot'",
        ).fetchone():
            snap = [
                (int(r['plan_id']), int(r['route_version']), int(r['is_active']))
                for r in con.execute(
                    """
                    SELECT plan_id, route_version, is_active
                    FROM arac_plan_rota_snapshot
                    ORDER BY plan_id, route_version
                    """,
                ).fetchall()
            ]
        return {
            'plan_a': _items(ctx['plan_a_id']),
            'plan_b': _items(ctx['plan_b_id']),
            'audit': audit_rows,
            'snapshots': snap,
        }
    finally:
        con.close()


def _audit_rows(plan_is_id: int, *, action: str | None = None) -> list[sqlite3.Row]:
    con = sqlite3.connect(os.environ['CPS_MOCK_DB_PATH'])
    con.row_factory = sqlite3.Row
    try:
        if action:
            return con.execute(
                """
                SELECT * FROM arac_plan_is_degisim
                WHERE plan_is_id=? AND action=?
                ORDER BY id
                """,
                (int(plan_is_id), action),
            ).fetchall()
        return con.execute(
            'SELECT * FROM arac_plan_is_degisim WHERE plan_is_id=? ORDER BY id',
            (int(plan_is_id),),
        ).fetchall()
    finally:
        con.close()


def _item_status(plan_is_id: int) -> str:
    con = sqlite3.connect(os.environ['CPS_MOCK_DB_PATH'])
    try:
        row = con.execute(
            'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (int(plan_is_id),),
        ).fetchone()
        return str(row[0]) if row else ''
    finally:
        con.close()


def _consumer_ids(vid: str) -> dict[str, list[int]]:
    from modules.planlama.arac_driver_map_service import build_driver_map_dto
    from modules.planlama.arac_whatsapp_message_service import load_whatsapp_plan_context
    from modules.planlama.arac_takip_repo import list_plan_tasks

    tasks = list_plan_tasks(PLAN_DATE, vid)
    active = [t for t in tasks if (t.get('status') or '').upper() not in {'IPTAL', 'ERTELENDI', 'GIDILEMEDI'}]
    db_ids = [int(t['plan_item_id']) for t in sorted(active, key=lambda x: x.get('order_no') or 0)]
    wa = load_whatsapp_plan_context(PLAN_DATE, vid) or {}
    wa_stops = wa.get('stops') or []
    wa_ids = [int(s.get('plan_item_id') or s.get('id')) for s in wa_stops]
    dm = build_driver_map_dto(PLAN_DATE, vid)
    dm_ids = [int(s.get('plan_item_id')) for s in (dm.get('stops') or [])]
    return {
        'db': db_ids,
        'whatsapp': wa_ids,
        'driver_map': dm_ids,
    }


def _transfer_payload(**extra) -> dict:
    payload = {
        'action': 'transfer_vehicle',
        'target_vehicle_external_id': VID_B,
        'target_plate': '34 TRG',
        'reason': 'transfer attempt',
        'client_submit_id': str(uuid.uuid4()),
    }
    payload.update(extra)
    return payload


def test_transfer_option_not_in_ui(temp_db):
    js = (_APP_DIR / 'static' / 'js' / 'planlama_arac_takip_plan_change.js').read_text(encoding='utf-8')
    html = (_APP_DIR / 'templates' / 'planlama' / 'arac_takip_plan.html').read_text(encoding='utf-8')
    assert 'Başka Araca Aktar' not in js
    assert 'Başka Araca Aktar' not in html
    assert 'atpPcPanelTransfer' not in html
    assert 'transfer_vehicle' not in js


def test_transfer_allowed_actions_false_in_detail(temp_db):
    from modules.planlama.arac_plan_change_service import get_plan_job_detail

    ctx = _seed_scenario()
    detail = get_plan_job_detail(ctx['movable_id'])
    assert detail['detail']['allowed_actions']['transfer_vehicle'] is False


def test_transfer_direct_api_rejected_no_db_change(temp_db):
    from modules.planlama.arac_plan_change_service import PlanChangeError, apply_plan_job_change

    ctx = _seed_scenario()
    before = _full_snapshot(temp_db, ctx)
    with pytest.raises(PlanChangeError, match='kullanıma kapalı'):
        apply_plan_job_change(ctx['movable_id'], USER_ID, _transfer_payload())
    after = _full_snapshot(temp_db, ctx)
    assert before == after
    assert ctx['movable_id'] in _active_ids(VID_A)
    assert ctx['movable_id'] not in _active_ids(VID_B)
    assert _audit_rows(ctx['movable_id'], action='transfer_vehicle') == []


def test_transfer_api_route_returns_400(temp_db):
    ctx = _seed_scenario()
    client = _client()
    r = client.post(
        f'/planlama/arac-takip/api/plan-job/{ctx["movable_id"]}/change',
        json=_transfer_payload(),
    )
    assert r.status_code == 400
    assert TRANSFER_DEFERRED_MSG in (r.get_json() or {}).get('error', '')
    assert ctx['movable_id'] in _active_ids(VID_A)


def test_transfer_rejected_even_for_completed_or_started(temp_db):
    from modules.planlama.arac_plan_change_service import PlanChangeError, apply_plan_job_change

    ctx = _seed_scenario()
    for pid in (ctx['completed_id'], ctx['started_id']):
        with pytest.raises(PlanChangeError, match='kullanıma kapalı'):
            apply_plan_job_change(pid, USER_ID, _transfer_payload())


def test_soft_cancel_hides_from_consumers(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change
    from modules.planlama.arac_takip_repo import get_conn

    ctx = _seed_scenario()
    cid = ctx['cancel_id']
    r = apply_plan_job_change(cid, USER_ID, {
        'action': 'cancel',
        'reason': 'musteri iptal',
        'client_submit_id': str(uuid.uuid4()),
    })
    assert r['ok']
    assert cid not in _active_ids(VID_A)
    cons = _consumer_ids(VID_A)
    assert cid not in cons['db']
    assert cid not in cons['whatsapp']
    assert cid not in cons['driver_map']
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute('SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (cid,)).fetchone()
        assert row['durum'] == 'IPTAL'
        audit = con.execute(
            'SELECT action FROM arac_plan_is_degisim WHERE plan_is_id=? ORDER BY id DESC LIMIT 1',
            (cid,),
        ).fetchone()
        assert audit and audit['action'] == 'cancel'
    finally:
        con.close()


def test_cancel_idempotent(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change

    ctx = _seed_scenario()
    cid = ctx['cancel_id']
    csid = str(uuid.uuid4())
    apply_plan_job_change(cid, USER_ID, {
        'action': 'cancel', 'reason': 'once', 'client_submit_id': csid,
    })
    r2 = apply_plan_job_change(cid, USER_ID, {
        'action': 'cancel', 'reason': 'twice', 'client_submit_id': csid,
    })
    assert r2.get('duplicate') or r2.get('ok')


def test_cancelled_geofence_skip(temp_db):
    from modules.planlama.arac_geofence_service import ACTIVE_ITEM_STATUSES
    from modules.planlama.arac_plan_change_service import apply_plan_job_change

    ctx = _seed_scenario()
    apply_plan_job_change(ctx['cancel_id'], USER_ID, {
        'action': 'cancel', 'reason': 'geo', 'client_submit_id': str(uuid.uuid4()),
    })
    con = sqlite3.connect(os.environ['CPS_MOCK_DB_PATH'])
    con.row_factory = sqlite3.Row
    try:
        st = con.execute(
            'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (ctx['cancel_id'],),
        ).fetchone()['durum']
        assert st == 'IPTAL'
        assert st not in ACTIVE_ITEM_STATUSES
    finally:
        con.close()


def test_unauthorized_api_change(temp_db):
    ctx = _seed_scenario()
    client = _client(can_edit=False)
    r = client.post(
        f'/planlama/arac-takip/api/plan-job/{ctx["movable_id"]}/change',
        json={'action': 'cancel', 'reason': 'hack'},
    )
    assert r.status_code == 403


def test_plan_change_modal_contract_in_template(temp_db):
    html = (_APP_DIR / 'templates' / 'planlama' / 'arac_takip_plan.html').read_text(encoding='utf-8')
    js = (_APP_DIR / 'static' / 'js' / 'planlama_arac_takip_plan_change.js').read_text(encoding='utf-8')
    assert 'Planı Değiştir' in html
    assert 'atpPcCancelNote' in html
    assert 'Sonraki Güne Aktar' in js
    assert 'Saat/Sıra Değiştir' in js
    assert 'planlama_arac_takip_plan_change.js' in html


def test_cancel_rollback_on_finalize_failure(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change

    ctx = _seed_scenario()
    before = _full_snapshot(temp_db, ctx)
    with patch(
        'modules.planlama.arac_plan_change_service._finalize_plan_change_conn',
        side_effect=RuntimeError('rollback-inject'),
    ):
        with pytest.raises(RuntimeError, match='rollback-inject'):
            apply_plan_job_change(ctx['cancel_id'], USER_ID, {
                'action': 'cancel',
                'reason': 'rollback test',
                'client_submit_id': str(uuid.uuid4()),
            })
    after = _full_snapshot(temp_db, ctx)
    assert before == after
    assert ctx['cancel_id'] in _active_ids(VID_A)
    assert _audit_rows(ctx['cancel_id'], action='cancel') == []


def test_parallel_cancel_same_job_one_wins(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change

    ctx = _seed_scenario()
    cid = ctx['cancel_id']

    def _cancel(tag: int) -> dict:
        try:
            return apply_plan_job_change(cid, USER_ID, {
                'action': 'cancel',
                'reason': f'parallel-{tag}',
                'client_submit_id': str(uuid.uuid4()),
            })
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1, r2 = list(pool.map(_cancel, (1, 2)))

    ok_count = sum(1 for r in (r1, r2) if r.get('ok'))
    assert ok_count == 1
    assert cid not in _active_ids(VID_A)
    assert _item_status(cid) == 'IPTAL'
    assert len(_audit_rows(cid, action='cancel')) == 1
    assert _active_sira_contiguous(VID_A)


def test_parallel_cancel_transfer_race_cancel_wins(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change

    ctx = _seed_scenario()
    mid = ctx['movable_id']
    before = _full_snapshot(temp_db, ctx)

    def _cancel() -> dict:
        try:
            return apply_plan_job_change(mid, USER_ID, {
                'action': 'cancel',
                'reason': 'race-cancel',
                'client_submit_id': str(uuid.uuid4()),
            })
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def _transfer() -> dict:
        try:
            return apply_plan_job_change(mid, USER_ID, _transfer_payload(reason='race-transfer'))
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    start = threading.Barrier(2)

    def _cancel_sync() -> dict:
        start.wait(timeout=5)
        return _cancel()

    def _transfer_sync() -> dict:
        start.wait(timeout=5)
        return _transfer()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_cancel = pool.submit(_cancel_sync)
        f_transfer = pool.submit(_transfer_sync)
        r_cancel, r_transfer = f_cancel.result(), f_transfer.result()

    assert r_transfer.get('ok') is not True
    assert 'kullanıma kapalı' in str(r_transfer.get('error', '')).lower()
    assert r_cancel.get('ok') is True
    assert _item_status(mid) == 'IPTAL'
    assert mid not in _active_ids(VID_A)
    assert mid not in _active_ids(VID_B)
    assert len(_audit_rows(mid, action='cancel')) == 1
    assert _audit_rows(mid, action='transfer_vehicle') == []
    after = _full_snapshot(temp_db, ctx)
    assert after['plan_a'] != before['plan_a']
    assert after['plan_b'] == before['plan_b']


HISTORY_TODAY = '2026-09-14'


def _seed_plan_on_date(plan_date: str) -> dict:
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        create_is_talebi,
        ensure_seed_locations,
        get_active_plan_row,
        list_plan_tasks,
    )

    ensure_seed_locations(USER_ID)
    t = create_is_talebi(USER_ID, {
        'tarih': plan_date,
        'is': 'HistJob',
        'firma': 'HistJob Co',
        'latitude': 40.91,
        'longitude': 29.11,
        'oncelik': 'NORMAL',
        'save_to_master': False,
    })
    assign_to_plan(USER_ID, t['id'], plan_date, VID_A, '34 HIST', None, 'Drv', '09:00', None)
    items = list_plan_tasks(plan_date, VID_A)
    plan = get_active_plan_row(plan_date, VID_A)
    return {
        'plan_date': plan_date,
        'plan_id': int(plan['id']),
        'item_id': int(items[-1]['plan_item_id']),
    }


def test_history_transition_past_today_future(temp_db):
    from modules.planlama.arac_takip_repo import list_history_plans

    past = _seed_plan_on_date('2026-09-10')
    today = _seed_plan_on_date(HISTORY_TODAY)
    future = _seed_plan_on_date('2026-09-20')

    res = list_history_plans(today=HISTORY_TODAY)
    dates = {r['date'] for r in res['rows']}
    plan_ids = {int(r['plan_id']) for r in res['rows']}

    assert past['plan_id'] in plan_ids
    assert today['plan_id'] not in plan_ids
    assert future['plan_id'] not in plan_ids
    assert '2026-09-10' in dates
    assert HISTORY_TODAY not in dates
    assert '2026-09-20' not in dates


def test_cancelled_item_audit_in_past_history_detail(temp_db):
    from modules.planlama.arac_plan_change_service import apply_plan_job_change
    from modules.planlama.arac_takip_repo import get_history_plan_detail, list_history_plans, list_plan_tasks

    ctx = _seed_plan_on_date('2026-09-11')
    apply_plan_job_change(ctx['item_id'], USER_ID, {
        'action': 'cancel',
        'reason': 'musteri vazgecti',
        'client_submit_id': str(uuid.uuid4()),
    })

    active_on_day = [
        int(t['plan_item_id']) for t in list_plan_tasks('2026-09-11', VID_A)
        if (t.get('status') or '').upper() not in {'IPTAL', 'ERTELENDI', 'GIDILEMEDI'}
    ]
    assert ctx['item_id'] not in active_on_day
    audit = _audit_rows(ctx['item_id'], action='cancel')
    assert len(audit) == 1
    assert audit[0]['reason'] == 'musteri vazgecti'

    hist = list_history_plans(today=HISTORY_TODAY)
    assert any(int(r['plan_id']) == ctx['plan_id'] for r in hist['rows'])

    detail = get_history_plan_detail(ctx['plan_id'])
    cancelled = [it for it in detail['items'] if it.get('category') == 'IPTAL']
    assert len(cancelled) == 1
    assert cancelled[0]['cancel_reason'] == 'musteri vazgecti'
    assert cancelled[0]['cancel_at']


def test_toast_css_global_and_success_contract(temp_db):
    css = (_APP_DIR / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')
    js = (_APP_DIR / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
    pcjs = (_APP_DIR / 'static' / 'js' / 'planlama_arac_takip_plan_change.js').read_text(encoding='utf-8')
    assert '.atp-toast {' in css
    assert 'atp-toast-success' in css
    assert '_toastHideTimer' in js
    assert 'geçmiş kaydı korundu' in pcjs
    assert "type: 'success'" in pcjs

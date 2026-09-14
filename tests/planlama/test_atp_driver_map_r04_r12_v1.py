# -*- coding: utf-8 -*-
"""R04/R12 — driver map DTO, WhatsApp link, ORS fallback, map contract."""
from __future__ import annotations

import importlib.util
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

APP = os.path.join(os.path.dirname(__file__), '..', '..', 'app')
_APP_DIR = Path(APP)
_MIGRATIONS = _APP_DIR / 'migrations'
if APP not in __import__('sys').path:
    __import__('sys').path.insert(0, APP)


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, restore_path: str | None = None):
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='driver_map_r04_')
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


def _driver_map_client():
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
    auth_mod.yetki_var = lambda *a, **k: True
    routes_mod = importlib.reload(routes_mod)
    routes_mod.yetki_gerekli = auth_mod.yetki_gerekli
    routes_mod.yetki_var = auth_mod.yetki_var

    app = flask.Flask(
        __name__,
        template_folder=str(_APP_DIR / 'templates'),
        static_folder=str(_APP_DIR / 'static'),
    )
    app.secret_key = 'driver-map-test'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)
    return app.test_client()


def test_driver_map_dto_contract(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations
    from modules.planlama.arac_driver_map_service import build_driver_map_dto

    ensure_seed_locations(1)
    d = '2026-12-20'
    vid = '991R04TEST'
    t1 = create_is_talebi(1, {'tarih': d, 'is': 'Job1', 'firma': 'A Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    t2 = create_is_talebi(1, {'tarih': d, 'is': 'Job2', 'firma': 'B Co', 'latitude': 40.91, 'longitude': 29.11, 'save_to_master': False})
    assign_to_plan(1, t1['id'], d, vid, '34 R04', None, 'Drv', '09:00', 1)
    assign_to_plan(1, t2['id'], d, vid, '34 R04', None, 'Drv', '10:00', 2)

    dto = build_driver_map_dto(d, vid)
    assert dto is not None
    assert dto['plan_id'] > 0
    assert len(dto['stops']) == 2
    assert dto['stops'][0]['sira'] == 1
    assert dto['stops'][0]['plan_item_id']
    assert 'location_valid' in dto['stops'][0]
    assert dto['item_id_order'] == [s['plan_item_id'] for s in dto['stops']]


def test_whatsapp_includes_driver_map_url_not_raw_stop_urls(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations
    from modules.planlama.arac_whatsapp_message_service import build_whatsapp_payload

    ensure_seed_locations(1)
    d = '2026-12-21'
    vid = '991R04WA'
    t = create_is_talebi(1, {'tarih': d, 'is': 'WA', 'firma': 'WA Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    assign_to_plan(1, t['id'], d, vid, '34 WA', None, 'Drv', '09:00', 1)

    import flask
    from modules.planlama import arac_takip_routes  # noqa: F401 — register blueprint endpoints

    app = flask.Flask(__name__)
    app.config['TESTING'] = True
    with app.app_context():
        payload = build_whatsapp_payload(d, vid)
    assert payload and payload.get('ok')
    ctx = payload['context']
    assert ctx.get('driver_map_url')
    assert '/sofor-haritasi' in ctx['driver_map_url']
    msg = payload['message']
    assert 'maps?q=' not in msg or 'haritada görüntüle' in msg.lower() or 'tek haritada' in msg.lower()
    assert ctx['driver_map_url'] in msg


def test_route_unconfigured_full_task_ids_fallback(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations, list_plan_tasks
    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    ensure_seed_locations(1)
    d = '2026-12-22'
    vid = '991R04ORS'
    t = create_is_talebi(1, {'tarih': d, 'is': 'X', 'firma': 'X Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    assign_to_plan(1, t['id'], d, vid, '34 ORS', None, 'Drv', '09:00', 1)
    tasks = list_plan_tasks(d, vid)
    base = resolve_base_location(None)
    with patch('modules.planlama.road_routing.route_planner_service.get_routing_provider', return_value=None):
        route = build_plan_route_dto(base, tasks)
    assert route['status'] in ('UNCONFIGURED', 'UNAVAILABLE')
    full = route['current']['full_task_ids']
    assert len(full) >= 1
    assert route.get('route_fallback') is True


def test_driver_map_token_gate(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations, get_active_plan_row
    from modules.planlama.arac_driver_map_token import sign_driver_map_token

    ensure_seed_locations(1)
    d = '2026-12-23'
    vid = '991R04TOK'
    t = create_is_talebi(1, {'tarih': d, 'is': 'T', 'firma': 'T Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    assign_to_plan(1, t['id'], d, vid, '34 TOK', None, 'Drv', '09:00', 1)
    plan = get_active_plan_row(d, vid)
    pid = int(plan['id'])
    token = sign_driver_map_token(d, vid, pid)

    c = _driver_map_client()
    bad = c.get(f'/planlama/arac-takip/sofor-haritasi?date={d}&vehicle_id={vid}&plan_id={pid}&t=bad')
    assert bad.status_code == 403
    ok = c.get(f'/planlama/arac-takip/sofor-haritasi?date={d}&vehicle_id={vid}&plan_id={pid}&t={token}')
    assert ok.status_code == 200
    html = ok.get_data(as_text=True)
    assert 'atpDriverMapJson' in html
    visible = html.split('atpDriverMapJson')[0]
    assert 'maps?q=' not in visible
    assert 'Sıralı Duraklar' in html or 'Haritada Aç' in html


def test_inactive_stop_excluded_from_driver_map(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations, get_conn
    from modules.planlama.arac_driver_map_service import build_driver_map_dto

    ensure_seed_locations(1)
    d = '2026-12-24'
    vid = '991R04IPT'
    t1 = create_is_talebi(1, {'tarih': d, 'is': 'Active', 'firma': 'Active Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    t2 = create_is_talebi(1, {'tarih': d, 'is': 'Cancel', 'firma': 'Cancel Co', 'latitude': 40.91, 'longitude': 29.11, 'save_to_master': False})
    assign_to_plan(1, t1['id'], d, vid, '34 IPT', None, 'Drv', '09:00', 1)
    assign_to_plan(1, t2['id'], d, vid, '34 IPT', None, 'Drv', '10:00', 2)
    from modules.planlama.arac_takip_repo import list_plan_tasks
    items = list_plan_tasks(d, vid)
    cancel_id = next(x['plan_item_id'] for x in items if x.get('company_name') == 'Cancel Co')
    con = get_conn()
    con.execute("UPDATE arac_gunluk_plan_is SET durum='IPTAL' WHERE id=?", (cancel_id,))
    con.commit()
    con.close()

    dto = build_driver_map_dto(d, vid)
    firms = [s['firma'] for s in dto['stops']]
    assert 'Active Co' in firms
    assert 'Cancel Co' not in firms


def test_missing_coords_listed_not_on_map(temp_db):
    from modules.planlama.arac_driver_map_service import build_driver_map_dto
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations

    ensure_seed_locations(1)
    d = '2026-12-25'
    vid = '991R04MISS'
    t1 = create_is_talebi(1, {'tarih': d, 'is': 'Ok', 'firma': 'Ok Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    t2 = create_is_talebi(1, {'tarih': d, 'is': 'No', 'firma': 'No Co', 'adres': 'No addr', 'save_to_master': False})
    assign_to_plan(1, t1['id'], d, vid, '34 MISS', None, 'Drv', '09:00', 1)
    assign_to_plan(1, t2['id'], d, vid, '34 MISS', None, 'Drv', '10:00', 2)

    dto = build_driver_map_dto(d, vid)
    assert dto['completeness']['missing'] == 1
    assert len(dto['missing_location_stops']) == 1
    assert dto['missing_location_stops'][0]['firma'] == 'No Co'


def test_whatsapp_api_driver_map_url_field(temp_db):
    from modules.planlama.arac_takip_repo import create_is_talebi, assign_to_plan, ensure_seed_locations
    from modules.planlama.arac_whatsapp_message_service import build_whatsapp_api_response

    ensure_seed_locations(1)
    d = '2026-12-26'
    vid = '991R04API'
    t = create_is_talebi(1, {'tarih': d, 'is': 'API', 'firma': 'API Co', 'latitude': 40.9, 'longitude': 29.1, 'save_to_master': False})
    assign_to_plan(1, t['id'], d, vid, '34 API', None, 'Drv', '09:00', 1)

    import flask
    app = flask.Flask(__name__)
    with app.app_context():
        r = build_whatsapp_api_response(d, vid)
    assert r.get('ok')
    assert r.get('driver_map_url')
    assert '/sofor-haritasi' in r.get('driver_map_url', '')
    assert r.get('order_ids')

# -*- coding: utf-8 -*-
"""Real factory link + Plan-2 temp DB route gate validation."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))
os.environ.setdefault(
    'GOOGLE_ROUTES_API_KEY',
    'TEST_FAKE_KEY_API_0000000000000000000',
)

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, sha256_file

from atp_factory_link import (
    FACTORY_DISPLAY_NAME,
    FACTORY_SHORT_LINK,
    FactoryLinkResolution,
    resolve_factory_link,
)
from atp_plan2_fixture import (
    CIKIS,
    PLAN_DATE,
    PLAN_ID,
    STOP_LAT,
    STOP_LNG,
    VEHICLE,
    clear_factory_base,
    insert_factory_base,
    seed_plan2_fixture,
)

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))

MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
_URL = '/planlama/arac-takip/api/plan/google-route-options'


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def factory_resolution() -> FactoryLinkResolution:
    try:
        return resolve_factory_link(FACTORY_SHORT_LINK)
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope='module')
def env(factory_resolution: FactoryLinkResolution):
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    sha_before = sha256_file(live)
    logical_before = canonical_logical_snapshot(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_real_factory_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)

    con = sqlite3.connect(db)
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()
    _load_migration(MIG189).run(db)

    os.environ['CPS_MOCK_DB_PATH'] = db
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {
        'db': db,
        'live': live,
        'sha_before': sha_before,
        'logical_before': logical_before,
        'tmp_dir': tmp_dir,
        'factory': factory_resolution,
    }
    assert_canonical_atp_unchanged(live, logical_before)
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def client(env):
    from functools import wraps
    import flask
    import config as cfg

    cfg.Config.MOCK_DB_PATH = env['db']
    os.environ['CPS_MOCK_DB_PATH'] = env['db']

    def _fake_yetki_gerekli(kod, action='can_view'):
        def deco(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                return f(*args, **kwargs)
            return wrapper
        return deco

    def _fake_yetki_var(kod, action='can_view'):
        return True

    import modules.auth as auth_mod
    auth_mod.yetki_gerekli = _fake_yetki_gerekli
    auth_mod.yetki_var = _fake_yetki_var
    from modules.planlama import arac_takip_routes as routes_mod
    routes_mod.yetki_gerekli = _fake_yetki_gerekli
    routes_mod.yetki_var = _fake_yetki_var
    from modules.planlama.arac_takip_routes import arac_takip_bp

    app = flask.Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    app.register_blueprint(arac_takip_bp)
    return app.test_client()


def _login(client):
    with client.session_transaction() as sess:
        sess['kullanici'] = {'Id': 1, 'AdSoyad': 'Admin', 'AuthVersion': 1, 'RolId': 1}


def _prepare_db(env, *, with_base: bool = True, with_stop_coords: bool = True) -> dict:
    factory: FactoryLinkResolution = env['factory']
    con = sqlite3.connect(env['db'])
    try:
        seed_plan2_fixture(con, with_coords=with_stop_coords)
        base_rec = None
        if with_base:
            base_rec = insert_factory_base(
                con,
                base_name=FACTORY_DISPLAY_NAME,
                latitude=factory.latitude,
                longitude=factory.longitude,
                maps_url=FACTORY_SHORT_LINK,
            )
        else:
            clear_factory_base(con)
        con.commit()
    finally:
        con.close()
    return {'base': base_rec}


def _post_google_options(client, captured: dict):
    from modules.planlama.road_routing.google_routes_provider import (
        PROFILE_TRAFFIC_FAST,
        PROFILE_TRAFFIC_FREE,
        GoogleLeg,
        GoogleRouteResult,
    )

    def _fake_result(profile):
        return GoogleRouteResult(
            profile=profile,
            profile_label=profile,
            distance_m=10000.0,
            drive_seconds=900.0,
            static_seconds=800.0,
            traffic_delta_seconds=100.0,
            encoded_polyline='fake',
            toll_present=False,
            toll_info=None,
            route_labels=[],
            legs=[GoogleLeg(0, 1, 1000.0, 120.0, 100.0)],
        )

    import modules.planlama.arac_google_route_options_service as svc
    orig_build = svc._build_route_points

    def _fake_route(self, pts):
        captured['google_points'] = list(pts)
        return _fake_result(self.profile)

    def _capture_build(base, stops):
        pts = orig_build(base, stops)
        captured['route_points'] = pts
        captured['base'] = dict(base)
        captured['stops'] = [dict(s) for s in stops]
        return pts

    with patch.object(svc, '_build_route_points', side_effect=_capture_build), \
         patch(
             'modules.planlama.arac_google_route_options_service.GoogleRoutesProvider.route_google',
             _fake_route,
         ):
        return client.post(
            _URL,
            json={
                'date': PLAN_DATE,
                'vehicle_id': VEHICLE,
                'departure_time': CIKIS,
                'plan_id': PLAN_ID,
            },
        )


class TestFactoryLinkResolution:
    def test_resolves_without_guessing(self, factory_resolution: FactoryLinkResolution):
        assert factory_resolution.resolved_url
        assert factory_resolution.latitude != 40.818
        assert factory_resolution.longitude != 29.305
        assert -90 <= factory_resolution.latitude <= 90
        assert -180 <= factory_resolution.longitude <= 180
        assert factory_resolution.confidence in ('HIGH', 'MEDIUM')


class TestRealFactoryRouteGate:
    def test_route_gate_pass_round_trip_coords(self, env, client):
        _prepare_db(env, with_base=True, with_stop_coords=True)
        _login(client)
        captured: dict = {}
        resp = _post_google_options(client, captured)
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body.get('ok') is True
        assert body.get('code') not in ('NO_BASE', 'MISSING_STOP_COORDINATES', 'MISSING_COORDINATES')

        factory = env['factory']
        pts = captured['route_points']
        assert len(pts) == 3
        assert abs(pts[0][0] - factory.latitude) < 1e-6
        assert abs(pts[0][1] - factory.longitude) < 1e-6
        assert abs(pts[1][0] - STOP_LAT) < 1e-6
        assert abs(pts[1][1] - STOP_LNG) < 1e-6
        assert abs(pts[2][0] - factory.latitude) < 1e-6
        assert abs(pts[2][1] - factory.longitude) < 1e-6

        from modules.planlama.arac_plan_service import get_tasks_for_session
        from modules.planlama.arac_route_constraints import active_tasks_sorted
        from modules.planlama.arac_location_resolver import resolve_base_location
        from modules.planlama.arac_operasyon_ayar_repo import get_active_base

        tasks = get_tasks_for_session(1, PLAN_DATE, VEHICLE)
        active = active_tasks_sorted(tasks)
        routable = [t for t in active if t.get('has_coordinates')]
        base = resolve_base_location(get_active_base())
        assert len(routable) == 1
        assert base.get('has_coordinates') is True

    def test_no_base_with_routable_stop(self, env, client):
        _prepare_db(env, with_base=False, with_stop_coords=True)
        _login(client)
        resp = _post_google_options(client, {})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data['code'] == 'NO_BASE'
        assert 'Fabrika' in data['error']

    def test_missing_stop_with_base(self, env, client):
        _prepare_db(env, with_base=True, with_stop_coords=False)
        _login(client)
        resp = _post_google_options(client, {})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data['code'] == 'MISSING_STOP_COORDINATES'
        assert 'missing_items' in data

    def test_temp_base_record_fields(self, env):
        base = _prepare_db(env, with_base=True)['base']
        assert base['base_name'] == FACTORY_DISPLAY_NAME
        assert base['base_maps_url'] == FACTORY_SHORT_LINK
        factory = env['factory']
        assert abs(base['base_latitude'] - factory.latitude) < 1e-6
        assert abs(base['base_longitude'] - factory.longitude) < 1e-6

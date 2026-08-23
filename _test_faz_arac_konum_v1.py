# -*- coding: utf-8 -*-
"""Araç Takip Konum Ekle V1 — isolated fixture, deterministic mock routing."""
from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
CANONICAL_DB = os.path.join(APP, 'mock_data.db')
sys.path.insert(0, APP)
os.chdir(APP)

# Benzersiz fixture sabitleri — canonical DB satırlarına bağımlı değil
FIXTURE = {
    'plan_date': '2026-12-15',
    'vehicle_id': '991KONUM01',
    'plate': '34 KON V1',
    'sofor': 'Oktay KONUM TEST',
    'base_name': 'KONUM-V1 Fabrika',
    'base_lat': 41.015,
    'base_lng': 29.02,
    'base_address': 'KONUM-V1 Base Adres Tuzla',
    'item_count': 3,
}

PASS = 0
FAIL = 0
FIXTURE_STATE: dict = {}


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f'  PASS {name}')


def bad(name: str, detail: str = '') -> None:
    global FAIL
    FAIL += 1
    print(f'  FAIL {name} {detail}')


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(
        filename, os.path.join(APP, 'migrations', filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _assert_not_canonical(db_path: str) -> None:
    canon = os.path.normcase(os.path.normpath(CANONICAL_DB))
    act = os.path.normcase(os.path.normpath(db_path))
    if act == canon:
        raise RuntimeError(f'STOP: active DB is canonical: {db_path}')


def seed_konum_fixture(db_path: str) -> dict:
    """Deterministic 3-item plan + base — temp DB only."""
    _assert_not_canonical(db_path)
    con = sqlite3.connect(db_path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    now = '2026-12-15 08:00:00'
    fx = FIXTURE

    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES (?,?,?,?,?,1,?,?,1)
        """,
        (fx['base_name'], fx['base_lat'], fx['base_lng'], fx['base_address'],
         f"https://maps.google.com/?q={fx['base_lat']},{fx['base_lng']}", now, now),
    )

    talep_specs = [
        ('AIT-KONUM-0001', 'KONUM-V1 Reuse Co', 'KONUM-V1 Shared Adres 1', 'Is 1'),
        ('AIT-KONUM-0002', 'KONUM-V1 Beta Co', 'KONUM-V1 Beta Adres 2', 'Is 2'),
        ('AIT-KONUM-0003', 'KONUM-V1 Reuse Co', 'KONUM-V1 Shared Adres 1', 'Is 3'),
    ]
    talep_ids: list[int] = []
    for talep_no, firma, adres, is_text in talep_specs:
        cur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?)
            """,
            (talep_no, 1, 'KONUM Test User', fx['plan_date'], firma, adres, is_text,
             'NORMAL', 'PLANA_ALINDI', now, 1, now, 1),
        )
        talep_ids.append(int(cur.lastrowid))

    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,1,?,'AKTIF',?,?,?,?)
        """,
        (fx['plan_date'], fx['vehicle_id'], fx['plate'], fx['sofor'], now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)

    for sira, talep_id in enumerate(talep_ids, start=1):
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, talep_id, sira, f'0{8 + sira}:00', 'PLANLANDI', now, 1),
        )

    con.commit()
    item_count = con.execute(
        'SELECT COUNT(*) c FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,),
    ).fetchone()[0]
    con.close()
    if item_count != fx['item_count']:
        raise RuntimeError(f'Fixture seed item_count={item_count} expected {fx["item_count"]}')
    return {
        **fx,
        'db_path': db_path,
        'plan_id': plan_id,
        'talep_ids': talep_ids,
        'fixture_item_count': item_count,
    }


@contextmanager
def isolated_konum_db():
    tmpdir = tempfile.mkdtemp(prefix='konum_v1_')
    db_path = os.path.join(tmpdir, 'konum_v1_isolated.db')
    _run_migration(db_path, '176_arac_takip_v13.py')
    _run_migration(db_path, '177_arac_operasyon_ayar.py')
    _run_migration(db_path, '178_arac_is_talebi_ux_v2_fields.py')
    state = seed_konum_fixture(db_path)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        print(f'  [DB-PATH-TEMP] {db_path}')
        print(f'  [FIXTURE] plan_date={state["plan_date"]} vehicle={state["vehicle_id"]} '
              f'items={state["fixture_item_count"]} talep_ids={state["talep_ids"]}')
        yield db_path, state


def test_parser_static() -> None:
    print('PARSER_STATIC')
    from modules.planlama.arac_lokasyon_service import parse_maps_coords
    cases = [
        ('https://maps.google.com/?q=40.818,29.305', (40.818, 29.305)),
        ('https://www.google.com/maps/@40.876,29.234,17z', (40.876, 29.234)),
        ('https://www.google.com/maps/place/X/@40.818,29.305,17z/data=!3d40.819!4d29.306', (40.818, 29.305)),
        ('', (None, None)),
        ('random text', (None, None)),
        ('https://evil.com/@40.1,29.1', (None, None)),
    ]
    for url, expected in cases:
        lat, lng = parse_maps_coords(url, resolve_redirects=False)
        if (lat, lng) == expected:
            ok(url[:40] or 'empty')
        else:
            bad(url[:40], f'got {lat},{lng} expected {expected}')


def test_host_allowlist() -> None:
    print('HOST_ALLOWLIST')
    from modules.planlama.arac_lokasyon_service import _host_allowed
    assert _host_allowed('maps.google.com')
    assert _host_allowed('maps.app.goo.gl')
    assert not _host_allowed('evil.com')
    ok('allowlist')


def test_negative_api_no_write(fx: dict) -> None:
    print('NEGATIVE_API')
    from modules.planlama.arac_takip_repo import get_conn
    from modules.planlama.arac_lokasyon_service import MAPS_COORD_USER_ERROR

    YK = frozenset({'planlama:can_view'})
    talep_id = fx['talep_ids'][1]
    with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
         patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
         patch('modules.auth.yetki_var', return_value=True), \
         patch('modules.auth.is_superadmin', return_value=True):
        import app as flask_app
        c = flask_app.app.test_client()
        with c.session_transaction() as s:
            s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
            s['kullanici_tip'] = 'sistem'

        con = get_conn()
        before = con.execute(
            'SELECT latitude, kayitli_yer_id FROM arac_is_talebi WHERE id=?', (talep_id,),
        ).fetchone()
        con.close()

        payloads = [
            ('empty', {'is_talebi_id': talep_id, 'maps_url': '', 'date': fx['plan_date'], 'vehicle_id': fx['vehicle_id']}),
            ('random', {'is_talebi_id': talep_id, 'maps_url': 'not-a-url', 'date': fx['plan_date'], 'vehicle_id': fx['vehicle_id']}),
            ('evil', {'is_talebi_id': talep_id, 'maps_url': 'https://evil.com/@40.1,29.1', 'date': fx['plan_date'], 'vehicle_id': fx['vehicle_id']}),
            ('no_coords', {'is_talebi_id': talep_id, 'maps_url': 'https://www.google.com/maps/search/Tuzla', 'date': fx['plan_date'], 'vehicle_id': fx['vehicle_id']}),
        ]
        for label, payload in payloads:
            r = c.post('/planlama/arac-takip/api/plan-items/konum', json=payload)
            j = r.get_json()
            if r.status_code == 400 and not j.get('ok'):
                ok(f'negative_{label}')
            else:
                bad(f'negative_{label}', str(j))
        ok(f'negative_user_error_constant={MAPS_COORD_USER_ERROR[:20]}')

        con = get_conn()
        after = con.execute(
            'SELECT latitude, kayitli_yer_id FROM arac_is_talebi WHERE id=?', (talep_id,),
        ).fetchone()
        con.close()
        if dict(before) == dict(after):
            ok('negative_db_unchanged')
        else:
            bad('negative_db_unchanged', f'{dict(before)} -> {dict(after)}')


def _reset_fixture_coords(fx: dict) -> None:
    from modules.planlama.arac_takip_repo import get_conn
    con = get_conn()
    for tid in fx['talep_ids']:
        con.execute(
            """
            UPDATE arac_is_talebi
            SET latitude=NULL, longitude=NULL, konum_linki=NULL, kayitli_yer_id=NULL
            WHERE id=?
            """,
            (tid,),
        )
    con.commit()
    con.close()


def test_acceptance_plan(fx: dict) -> None:
    print('ACCEPTANCE_PLAN')
    from modules.planlama.arac_lokasyon_service import parse_maps_coords
    from modules.planlama.arac_takip_repo import get_conn, list_plan_tasks, save_talep_konum_with_master, tables_ready
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider

    if not tables_ready():
        bad('tables', 'not ready')
        return

    tasks_before = list_plan_tasks(fx['plan_date'], fx['vehicle_id'])
    if len(tasks_before) != fx['fixture_item_count']:
        bad('fixture_item_count', f'got {len(tasks_before)} expected {fx["fixture_item_count"]}')
        return
    ok(f'fixture_item_count={fx["fixture_item_count"]}')

    _reset_fixture_coords(fx)
    tasks_reset = list_plan_tasks(fx['plan_date'], fx['vehicle_id'])
    ready_before = sum(1 for t in tasks_reset if t.get('has_coordinates'))
    if ready_before == 0:
        ok('ready_before_zero')
    else:
        bad('ready_before_zero', f'ready={ready_before}')

    coord_specs = [
        (fx['talep_ids'][0], 'https://www.google.com/maps/@40.876,29.234,17z'),
        (fx['talep_ids'][1], 'https://maps.google.com/?q=40.818,29.305'),
        (fx['talep_ids'][2], 'https://www.google.com/maps/@40.825,29.372,17z'),
    ]
    master_ids: list[int | None] = []
    for talep_id, url in coord_specs:
        lat, lng = parse_maps_coords(url)
        if lat is None:
            bad(f'parse_{talep_id}')
            continue
        res = save_talep_konum_with_master(1, talep_id, lat, lng, url)
        master_ids.append(res.get('kayitli_yer_id'))
        con = get_conn()
        row = con.execute(
            'SELECT latitude, kayitli_yer_id FROM arac_is_talebi WHERE id=?', (talep_id,),
        ).fetchone()
        con.close()
        if row and row['latitude'] == lat and row['kayitli_yer_id']:
            ok(f'save_talep_{talep_id}')
        else:
            bad(f'save_talep_{talep_id}')

    tasks = list_plan_tasks(fx['plan_date'], fx['vehicle_id'])
    ready = sum(1 for t in tasks if t.get('has_coordinates'))
    if ready == 3:
        ok('3_ready')
    else:
        bad('3_ready', f'ready={ready}')

    missing = sum(1 for t in tasks if not t.get('has_coordinates'))
    if missing == 0:
        ok('missing_count_zero')
    else:
        bad('missing_count_zero', f'missing={missing}')

    if len(master_ids) >= 3 and master_ids[0] == master_ids[2]:
        ok('reuse_same_firma_adres')
    else:
        bad('reuse_same_firma_adres', str(master_ids))

    order_before = [t.get('order_no') for t in sorted(tasks, key=lambda x: x.get('order_no') or 0)]
    if order_before == [1, 2, 3]:
        ok('stop_order_fixture')
    else:
        bad('stop_order_fixture', str(order_before))

    ors_calls: list[str] = []

    class _OrsGuard:
        def route_ordered(self, *args, **kwargs):
            ors_calls.append('route_ordered')
            raise AssertionError('Real ORS must not be called in KONUM V1 test')

    YK = frozenset({'planlama:can_view'})
    mock_provider = MockRoadRoutingProvider()

    with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
         patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
         patch('modules.auth.yetki_var', return_value=True), \
         patch('modules.auth.is_superadmin', return_value=True), \
         patch('modules.planlama.road_routing.route_planner_service.get_routing_provider',
               return_value=mock_provider), \
         patch('modules.planlama.road_routing.openrouteservice_provider.OpenRouteServiceProvider',
               return_value=_OrsGuard()):
        import app as flask_app
        c = flask_app.app.test_client()
        with c.session_transaction() as s:
            s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
            s['kullanici_tip'] = 'sistem'
        r = c.get(
            f'/planlama/arac-takip/api/route/plan?date={fx["plan_date"]}&vehicle_id={fx["vehicle_id"]}',
        )
        j = r.get_json()
        rt = j.get('route') or {}
        meta = rt.get('meta') or {}

        if meta.get('base_ready'):
            ok('base_ready')
        else:
            bad('base_ready', str(meta))

        if meta.get('routable_count') == 3:
            ok('route_3_routable')
        else:
            bad('route_3_routable', str(meta))

        if meta.get('missing_count') == 0:
            ok('route_missing_zero')
        else:
            bad('route_missing_zero', str(meta))

        if rt.get('status') == 'OK':
            ok('route_computed')
        else:
            bad('route_computed', rt.get('status'))

        cur = rt.get('current') or {}
        if cur.get('provider') == 'mock' and len(cur.get('geometry') or []) >= 2:
            ok('route_mock_provider')
        else:
            bad('route_mock_provider', str({'provider': cur.get('provider'), 'geom': len(cur.get('geometry') or [])}))

        if cur.get('order_labels') == '1 → 2 → 3':
            ok('route_stop_order')
        else:
            bad('route_stop_order', cur.get('order_labels'))

        if not ors_calls:
            ok('no_real_ors_call')
        else:
            bad('no_real_ors_call', str(ors_calls))


def main() -> int:
    global FIXTURE_STATE
    with isolated_konum_db() as (_db_path, fx):
        FIXTURE_STATE = fx
        test_parser_static()
        test_host_allowlist()
        test_negative_api_no_write(fx)
        test_acceptance_plan(fx)
    print(f'\nTOTAL {PASS} pass / {FAIL} fail')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())

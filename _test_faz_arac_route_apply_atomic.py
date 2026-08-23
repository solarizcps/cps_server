# -*- coding: utf-8 -*-
"""Route apply atomic — failure injection + success paths (temp DB only)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
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
CANONICAL_SHA = 'b79bb0da49c884d8dd5330810469bab85f73e78db1f7be8eb57a95a7951dd51b'
sys.path.insert(0, APP)
os.chdir(APP)

PASS = FAIL = 0
PLAN_DATE = '2026-12-22'
VEHICLE = '994ATOM01'
YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})


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


def _route_dto(variant: str = 'ok') -> dict:
    if variant == 'fail':
        return {'status': 'NO_ROUTE', 'message': 'Rota yok'}
    if variant == 'bad_geom':
        return {'status': 'OK', 'current': {'provider': 'mock', 'geometry': [[41.0, 29.0]]}}
    return {
        'status': 'OK',
        'current': {
            'provider': 'mock',
            'geometry': [[41.0, 29.0], [40.99, 28.89], [40.98, 28.88]],
            'distance_m': 12000.0,
            'duration_s': 1800.0,
        },
    }


def _route_dto_v2() -> dict:
    return {
        'status': 'OK',
        'current': {
            'provider': 'mock',
            'geometry': [[41.0, 29.0], [40.97, 28.87], [40.96, 28.86]],
            'distance_m': 15000.0,
            'duration_s': 2000.0,
        },
    }


@contextmanager
def temp_atomic_db():
    tmpdir = tempfile.mkdtemp(prefix='route_atomic_')
    db_path = os.path.join(tmpdir, 'atomic.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    now = '2026-12-22 08:00:00'
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('Atom Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,'34 ATOM 01',1,'Oktay','AKTIF',?,?,?,?)
        """,
        (PLAN_DATE, VEHICLE, now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    item_ids: list[str] = []
    for i, (lat, lng) in enumerate([(40.99, 28.89), (40.98, 28.88), (40.97, 28.87)], 1):
        tcur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f'AT-{i}', 1, 'Test', PLAN_DATE, f'Co{i}', f'Ad{i}', f'Is{i}', 'NORMAL',
             'PLANA_ALINDI', lat, lng, now, 1, now, 1),
        )
        icur = con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, int(tcur.lastrowid), i, f'0{8+i}:00', 'PLANLANDI', now, 1),
        )
        item_ids.append(f'pi-{icur.lastrowid}')
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path, plan_id, item_ids


def db_state(db_path: str, plan_id: int) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    order = [r['sira'] for r in con.execute(
        'SELECT sira FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY id', (plan_id,),
    ).fetchall()]
    active = con.execute(
        'SELECT id, route_version, is_active, content_hash FROM arac_plan_rota_snapshot '
        'WHERE plan_id=? AND is_active=1', (plan_id,),
    ).fetchone()
    count = con.execute(
        'SELECT COUNT(*) c FROM arac_plan_rota_snapshot WHERE plan_id=?', (plan_id,),
    ).fetchone()[0]
    con.close()
    return {
        'order': order,
        'active': dict(active) if active else None,
        'snapshot_count': int(count),
    }


def apply_atomic(task_ids: list[str], dto_variant: str = 'ok', dto_fn=None):
    from modules.planlama.arac_route_apply_service import apply_route_order_and_snapshot
    builder = dto_fn or (lambda _b, _t: _route_dto(dto_variant))
    return apply_route_order_and_snapshot(
        1, PLAN_DATE, VEHICLE, task_ids, user_id=1, route_dto_builder=builder,
    )


def apply_http(task_ids: list[str], dto_variant: str = 'ok'):
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'alpay', 'AdSoyad': 'Alpay Test',
            'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
    with patch('modules.planlama.road_routing.route_planner_service.build_plan_route_dto',
               side_effect=lambda b, t: _route_dto(dto_variant)):
        return c.post('/planlama/arac-takip/api/route/apply', json={
            'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'task_ids': task_ids,
        })


def main() -> int:
    global PASS, FAIL
    print('=' * 72)
    print('ROUTE APPLY ATOMIC — failure injection')
    print('=' * 72)

    canon_before = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()

    with temp_atomic_db() as (db_path, plan_id, item_ids):
        from modules.planlama.arac_route_apply_service import (
            RouteApplyPersistenceError,
            RouteApplyRouteError,
            RouteApplyValidationError,
            apply_route_order_and_snapshot,
        )
        from modules.planlama.arac_gps_snapshot_repo import _save_plan_rota_snapshot_conn

        base = db_state(db_path, plan_id)

        # 1. Reorder validation fail
        try:
            apply_atomic([item_ids[0]])
            bad('01-validation-no-change', 'should raise')
        except RouteApplyValidationError:
            after = db_state(db_path, plan_id)
            if after == base:
                ok('01-validation-no-change')
            else:
                bad('01-validation-no-change', str(after))

        # 2. Route calculation fail
        try:
            apply_atomic(list(item_ids), dto_variant='fail')
            bad('02-route-fail-no-change', 'should raise')
        except RouteApplyRouteError:
            if db_state(db_path, plan_id) == base:
                ok('02-route-fail-no-change')
            else:
                bad('02-route-fail-no-change', 'db changed')

        # 3. Geometry invalid
        try:
            apply_atomic(list(item_ids), dto_variant='bad_geom')
            bad('03-geometry-invalid', 'should raise')
        except RouteApplyRouteError:
            if db_state(db_path, plan_id) == base:
                ok('03-geometry-invalid')
            else:
                bad('03-geometry-invalid', 'db changed')

        # 4. Snapshot exception after reorder → rollback
        rev = list(reversed(item_ids))
        before4 = db_state(db_path, plan_id)
        real_save = _save_plan_rota_snapshot_conn

        def boom_save(con, *a, **kw):
            raise RuntimeError('injected snapshot fail')

        with patch('modules.planlama.arac_route_apply_service._save_plan_rota_snapshot_conn', boom_save):
            try:
                apply_route_order_and_snapshot(
                    1, PLAN_DATE, VEHICLE, rev, user_id=1,
                    route_dto_builder=lambda _b, _t: _route_dto('ok'),
                )
                bad('04-snapshot-exception-rollback', 'should raise')
            except RouteApplyPersistenceError:
                after4 = db_state(db_path, plan_id)
                if after4 == before4:
                    ok('04-snapshot-exception-rollback')
                else:
                    bad('04-snapshot-exception-rollback', f'{before4} -> {after4}')

        # 8. Successful first apply → version 1
        r8 = apply_atomic(list(item_ids))
        st8 = db_state(db_path, plan_id)
        if r8.route_version == 1 and not r8.deduplicated and st8['snapshot_count'] == 1:
            ok('08-first-apply-v1')
        else:
            bad('08-first-apply-v1', str(r8))

        # 9. Second different apply → version 2
        r9 = apply_atomic(rev, dto_fn=lambda _b, _t: _route_dto_v2())
        st9 = db_state(db_path, plan_id)
        if r9.route_version == 2 and st9['snapshot_count'] == 2 and st9['active']['route_version'] == 2:
            ok('09-second-apply-v2')
        else:
            bad('09-second-apply-v2', str(st9))

        # 10. Same route dedup
        r10 = apply_atomic(rev, dto_fn=lambda _b, _t: _route_dto_v2())
        if r10.deduplicated and db_state(db_path, plan_id)['snapshot_count'] == 2:
            ok('10-dedup-same-route')
        else:
            bad('10-dedup-same-route', str(r10))

        # 5. Deactivate then insert fail → rollback restores active v2
        before5 = db_state(db_path, plan_id)
        call = {'n': 0}

        def fail_on_insert(con, pid, **kw):
            call['n'] += 1
            active = con.execute(
                'SELECT id FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1', (pid,),
            ).fetchone()
            if active:
                con.execute(
                    'UPDATE arac_plan_rota_snapshot SET is_active=0 WHERE plan_id=? AND is_active=1',
                    (pid,),
                )
            raise RuntimeError('insert fail after deactivate')

        with patch('modules.planlama.arac_route_apply_service._save_plan_rota_snapshot_conn', fail_on_insert):
            try:
                apply_route_order_and_snapshot(
                    1, PLAN_DATE, VEHICLE, list(item_ids), user_id=1,
                    route_dto_builder=lambda _b, _t: _route_dto('ok'),
                )
                bad('05-deactivate-insert-rollback', 'should raise')
            except RouteApplyPersistenceError:
                after5 = db_state(db_path, plan_id)
                if after5['active'] and after5['active']['route_version'] == before5['active']['route_version']:
                    ok('05-deactivate-insert-rollback')
                else:
                    bad('05-deactivate-insert-rollback', str(after5))

        # 6. Unique index failure → full rollback
        before6 = db_state(db_path, plan_id)
        import sqlite3 as _sqlite3

        def unique_fail(con, pid, **kw):
            raise _sqlite3.IntegrityError('UNIQUE constraint failed: arac_plan_rota_snapshot.plan_id')

        with patch('modules.planlama.arac_route_apply_service._save_plan_rota_snapshot_conn', unique_fail):
            try:
                apply_atomic(list(reversed(item_ids)), dto_fn=lambda _b, _t: _route_dto_v2())
                bad('06-unique-index-rollback', 'should raise')
            except RouteApplyPersistenceError:
                after6 = db_state(db_path, plan_id)
                if after6['order'] == before6['order'] and after6['active']['route_version'] == before6['active']['route_version']:
                    ok('06-unique-index-rollback')
                else:
                    bad('06-unique-index-rollback', f'{before6} -> {after6}')

        # 11. Stale task set
        stale_ids = item_ids[:2]
        try:
            apply_atomic(stale_ids)
            bad('11-stale-item-set', 'should raise')
        except RouteApplyValidationError:
            ok('11-stale-item-set')

        # HTTP contract success
        with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
             patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
             patch('modules.auth.yetki_var', return_value=True), \
             patch('modules.auth.is_superadmin', return_value=True):
            resp = apply_http(list(item_ids))
            body = resp.get_json() or {}
            if resp.status_code == 200 and body.get('ok') and body.get('applied') and body.get('route_snapshot'):
                ok('http-success-contract')
            else:
                bad('http-success-contract', f'status={resp.status_code} body={body}')

        # 13. GET route plan — no writes
        before13 = db_state(db_path, plan_id)
        with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
             patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
             patch('modules.auth.yetki_var', return_value=True), \
             patch('modules.auth.is_superadmin', return_value=True), \
             patch.dict(os.environ, {'ARAC_ROUTING_PROVIDER': 'mock'}, clear=False):
            import app as flask_app
            flask_app.app.config['TESTING'] = True
            c = flask_app.app.test_client()
            with c.session_transaction() as s:
                s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
                s['kullanici_tip'] = 'sistem'
            r = c.get(f'/planlama/arac-takip/api/route/plan?date={PLAN_DATE}&vehicle_id={VEHICLE}')
            if r.status_code == 200 and db_state(db_path, plan_id) == before13:
                ok('13-get-route-plan-no-write')
            else:
                bad('13-get-route-plan-no-write', str(r.status_code))

    # 12. Snapshot table missing → controlled error, no reorder
    tmpdir = tempfile.mkdtemp(prefix='route_no179_')
    db12 = os.path.join(tmpdir, 'no179.db')
    for mig in ('176_arac_takip_v13.py', '177_arac_operasyon_ayar.py', '178_arac_is_talebi_ux_v2_fields.py'):
        _run_migration(db12, mig)
    _run_migration(db12, '179_arac_gps_snapshot_p1.py')
    con = sqlite3.connect(db12)
    con.execute('DROP TABLE IF EXISTS arac_plan_rota_snapshot')
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db12):
        from modules.planlama.arac_route_apply_service import resolve_route_apply_mode
        if resolve_route_apply_mode() == 'schema_error':
            ok('12-schema-error-mode')
        else:
            bad('12-schema-error-mode', resolve_route_apply_mode())
        with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
             patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
             patch('modules.auth.yetki_var', return_value=True), \
             patch('modules.auth.is_superadmin', return_value=True):
            import app as flask_app
            flask_app.app.config['TESTING'] = True
            c = flask_app.app.test_client()
            with c.session_transaction() as s:
                s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
                s['kullanici_tip'] = 'sistem'
            r = c.post('/planlama/arac-takip/api/route/apply', json={
                'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'task_ids': ['pi-1'],
            })
            if r.status_code == 503 and not (r.get_json() or {}).get('ok'):
                ok('12-http-503-no-reorder')
            else:
                bad('12-http-503-no-reorder', f'{r.status_code} {r.get_json()}')

    # 14. Canonical unchanged
    canon_after = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()
    if canon_before == canon_after == CANONICAL_SHA:
        ok('14-canonical-unchanged')
    else:
        bad('14-canonical-unchanged', f'{canon_before} -> {canon_after}')

    print('=' * 72)
    print(f'TOTAL {PASS} pass / {FAIL} fail')
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())

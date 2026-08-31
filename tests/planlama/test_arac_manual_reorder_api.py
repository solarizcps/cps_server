# -*- coding: utf-8 -*-
"""U3C — Manual reorder API/service integration tests (temp DB only)."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sqlite3
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import flask
import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'
_WORKTREE_CANONICAL_DB = _APP_DIR / 'mock_data.db'
_PLANLAMA_TESTS = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_PLANLAMA_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atp_test_hygiene import capture_env_state, restore_env_state  # noqa: E402
from tools.atp_test_db_guard import (  # noqa: E402
    bind_temp_db_path,
    install_atp_test_db_guard,
    is_canonical_path,
    resolve_path,
)

# Bind guard to worktree default path before any get_conn() from route/service imports.
os.environ['CPS_TEST_DB_GUARD'] = '1'
install_atp_test_db_guard(str(_WORKTREE_CANONICAL_DB))

PLAN_DATE = '2026-08-26'
OTHER_DATE = '2026-08-27'
VEHICLE = '45077045'
OTHER_VEHICLE = '45077046'
PLAKA = '34 MOR 049'
NOW = '2026-08-26 10:00:00'
USER_ID = 1

CONTEXT_URL = '/planlama/arac-takip/api/plan/manual-reorder-context'
APPLY_URL = '/planlama/arac-takip/api/plan/manual-reorder'


def _assert_worktree_canonical_absent(phase: str) -> None:
    if _WORKTREE_CANONICAL_DB.exists():
        pytest.fail(
            f'worktree app/mock_data.db must not exist ({phase}); '
            f'path={_WORKTREE_CANONICAL_DB!s}',
        )


@pytest.fixture(scope='module', autouse=True)
def _u3c_module_canonical_guard():
    _assert_worktree_canonical_absent('before module')
    yield
    _assert_worktree_canonical_absent('after module')


@pytest.fixture(autouse=True)
def _u3c_test_canonical_invariant():
    _assert_worktree_canonical_absent('before test')
    yield
    _assert_worktree_canonical_absent('after test')


def _active_mock_db_path() -> str:
    import config
    return str(config.Config.MOCK_DB_PATH)


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, with_rota: bool = True, with_eta: bool = True):
    saved = capture_env_state()
    tmpdir = tempfile.mkdtemp(prefix='u3c_manual_')
    db_path = str(Path(tmpdir) / 'test.db')
    migs = [
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
    ]
    if with_rota:
        migs.append('179_arac_gps_snapshot_p1.py')
    if with_eta:
        migs.append('188_arac_plan_is_zaman_alanlari.py')
    for mig in migs:
        _run_migration(db_path, mig)
    try:
        os.environ['CPS_TEST_DB_GUARD'] = '1'
        bound = bind_temp_db_path(db_path)
        assert not is_canonical_path(bound)
        assert resolve_path(bound) != resolve_path(str(_WORKTREE_CANONICAL_DB))
        _assert_worktree_canonical_absent('temp_atp_db active')
        yield db_path
    finally:
        restore_env_state(saved)
        _assert_worktree_canonical_absent('temp_atp_db teardown')


def _conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _seed_location(con: sqlite3.Connection) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_kayitli_yer (
            firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
        ) VALUES (?,?,?,?,1,0,?,?)
        """,
        ('Test Firma', 'Adres', 41.0, 29.0, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_talep(
    con: sqlite3.Connection,
    *,
    oncelik: str = 'NORMAL',
    durum: str = 'BEKLIYOR',
    yapilacak_is: str = 'Is',
    suffix: str = '',
) -> int:
    loc_id = _seed_location(con)
    talep_no = f'U3C-{oncelik}-{suffix}-{uuid.uuid4().hex[:8]}'
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            kayitli_yer_id, firma_adi, adres, latitude, longitude, yapilacak_is,
            oncelik, durum, save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)
        """,
        (
            talep_no, USER_ID, 'User', PLAN_DATE, loc_id, 'Firma', 'Adres',
            41.0, 29.0, yapilacak_is, oncelik, durum, NOW, USER_ID, NOW, USER_ID,
        ),
    )
    return int(cur.lastrowid)


def _seed_plan(
    con: sqlite3.Connection,
    *,
    plan_date: str = PLAN_DATE,
    vehicle: str = VEHICLE,
    plaka: str = PLAKA,
    updated_at: str = NOW,
) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,'AKTIF',?,?,?,?)
        """,
        (plan_date, 'TURKCELL_FILOM', vehicle, plaka, NOW, USER_ID, updated_at, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_plan_item(
    con: sqlite3.Connection,
    plan_id: int,
    talep_id: int,
    sira: int,
    *,
    durum: str = 'PLANLANDI',
    eta: str | None = '09:30',
) -> int:
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    if 'tahmini_varis_saati' in cols:
        cur = con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, tahmini_varis_saati, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, talep_id, sira, durum, eta, NOW, USER_ID),
        )
    else:
        cur = con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?)
            """,
            (plan_id, talep_id, sira, durum, NOW, USER_ID),
        )
    return int(cur.lastrowid)


def _seed_visit(
    con: sqlite3.Connection,
    plan_id: int,
    plan_is_id: int,
    *,
    state: str = 'ARRIVED',
    arrived_at: str | None = NOW,
) -> None:
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m,
            consecutive_inside, consecutive_outside,
            arrived_at, departed_at, updated_at, created_at
        ) VALUES (?,?,?,?,200,250,0,0,?,NULL,?,?)
        """,
        (plan_id, plan_is_id, VEHICLE, state, arrived_at, NOW, NOW),
    )


def _seed_snapshot(con: sqlite3.Connection, plan_id: int) -> None:
    con.execute(
        """
        INSERT INTO arac_plan_rota_snapshot (
            plan_id, geometry_json, stop_order_json, routing_provider,
            total_distance_m, total_duration_s, content_hash, geometry_schema,
            arac_provider, is_active, route_version, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?)
        """,
        (
            plan_id, '{}', '[]', 'google', 1000, 600, 'abc', 'geojson-v1',
            'TURKCELL_FILOM', NOW, USER_ID,
        ),
    )


def _pi_ids(db_path: str, plan_id: int) -> list[str]:
    con = _conn(db_path)
    try:
        rows = con.execute(
            'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (plan_id,),
        ).fetchall()
        return [f"pi-{int(r['id'])}" for r in rows]
    finally:
        con.close()


def _siras(db_path: str, plan_id: int) -> list[int]:
    con = _conn(db_path)
    try:
        rows = con.execute(
            'SELECT sira FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (plan_id,),
        ).fetchall()
        return [int(r['sira']) for r in rows]
    finally:
        con.close()


def _plan_updated_at(db_path: str, plan_id: int) -> str:
    con = _conn(db_path)
    try:
        row = con.execute('SELECT updated_at FROM arac_gunluk_plan WHERE id=?', (plan_id,)).fetchone()
        return str(row['updated_at'])
    finally:
        con.close()


def _seed_basic_plan(
    db_path: str,
    count: int = 3,
    *,
    oncelik_list: list[str] | None = None,
    vehicle: str = VEHICLE,
    plan_date: str = PLAN_DATE,
) -> tuple[int, list[str]]:
    con = _conn(db_path)
    try:
        plan_id = _seed_plan(con, vehicle=vehicle, plan_date=plan_date)
        for i in range(count):
            pri = (oncelik_list[i] if oncelik_list and i < len(oncelik_list) else 'NORMAL')
            talep = _seed_talep(con, oncelik=pri, suffix=str(i))
            _seed_plan_item(con, plan_id, talep, i + 1)
        con.commit()
    finally:
        con.close()
    return plan_id, _pi_ids(db_path, plan_id)


def _build_flask_client(*, can_update: bool = True):
    from functools import wraps

    _assert_worktree_canonical_absent('flask client setup')
    active = _active_mock_db_path()
    if is_canonical_path(active) or resolve_path(active) == resolve_path(str(_WORKTREE_CANONICAL_DB)):
        pytest.fail(f'Flask client requires temp DB binding; got {active!r}')

    def _fake_yetki_gerekli(kod, action='can_view'):
        def deco(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                flask.session['kullanici'] = {'Id': USER_ID, 'AdSoyad': 'Test User'}
                return f(*args, **kwargs)
            return wrapper
        return deco

    def _fake_yetki_var(kod, action='can_view'):
        if kod == 'planlama' and action in ('can_update', 'can_manage'):
            return can_update
        if kod == 'planlama.arac_takip' and action in ('can_update', 'can_manage'):
            return can_update
        return True

    import modules.auth as auth_mod
    auth_mod.yetki_gerekli = _fake_yetki_gerekli
    auth_mod.yetki_var = _fake_yetki_var
    import modules.planlama.arac_takip_routes as routes_mod
    importlib.reload(routes_mod)
    app = flask.Flask(__name__)
    app.secret_key = 'test'
    app.config['TESTING'] = True
    app.register_blueprint(routes_mod.arac_takip_bp)
    return app.test_client()


# ── A. Context/read ──────────────────────────────────────────────────────────


class TestManualReorderContext:
    def test_authorized_context_200(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            assert ctx['ok'] is True
            assert ctx['plan_id'] == plan_id
            assert len(ctx['ordered_item_ids']) == 3

    def test_canonical_order(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            assert ctx['ordered_item_ids'] == ids

    def test_state_token_deterministic(self):
        with _temp_atp_db() as db_path:
            plan_id, _ = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            a = get_manual_reorder_context(plan_id)['state_token']
            b = get_manual_reorder_context(plan_id)['state_token']
            assert a == b
            assert len(a) == 64

    def test_lock_info_in_context(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            p1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_plan_item(con, plan_id, t2, 2, durum='TAMAMLANDI')
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            by_id = {t['task_id']: t for t in ctx['tasks']}
            assert by_id[f'pi-{p1}']['can_move'] is True
            locked = [t for t in ctx['tasks'] if not t['can_move']]
            assert len(locked) == 1
            assert locked[0]['lock_reason'] == 'STATUS_TAMAMLANDI'

    def test_segment_info(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            _seed_plan_item(con, plan_id, t1, 1)
            p2 = _seed_plan_item(con, plan_id, t2, 2)
            _seed_visit(con, plan_id, p2)
            _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            segments = {t['task_id']: t['segment_index'] for t in ctx['tasks']}
            assert len(set(segments.values())) == 3

    def test_plan_not_found(self):
        with _temp_atp_db():
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                get_manual_reorder_context,
            )
            with pytest.raises(ManualReorderServiceError) as exc:
                get_manual_reorder_context(99999)
            assert exc.value.code == 'PLAN_NOT_FOUND'
            assert exc.value.http_status == 404

    def test_wrong_vehicle_scope(self):
        with _temp_atp_db() as db_path:
            plan_id, _ = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                get_manual_reorder_context,
            )
            with pytest.raises(ManualReorderServiceError) as exc:
                get_manual_reorder_context(plan_id, vehicle_id=OTHER_VEHICLE)
            assert exc.value.http_status == 404

    def test_unauthorized_context_http(self):
        with _temp_atp_db():
            client = _build_flask_client(can_update=False)
            resp = client.get(CONTEXT_URL, query_string={'plan_id': 1})
            assert resp.status_code == 403


# ── B. Successful reorder ────────────────────────────────────────────────────


class TestSuccessfulReorder:
    def test_all_movable_reorder(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[2], ids[0], ids[1]]
            result = apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert result['changed'] is True
            assert result['ordered_item_ids'] == proposed
            assert _siras(db_path, plan_id) == [1, 2, 3]

    def test_same_segment_swap(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            i1 = _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            i3 = _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}', f'pi-{i3}']
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[0], ids[2], ids[1]]
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert _pi_ids(db_path, plan_id) == proposed

    def test_multi_segment_independent_reorder(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            items = []
            for i, st in enumerate(['TAMAMLANDI', 'PLANLANDI', 'PLANLANDI', 'PLANLANDI']):
                t = _seed_talep(con, suffix=str(i))
                items.append(_seed_plan_item(con, plan_id, t, i + 1, durum=st))
            con.commit()
            con.close()
            ids = [f'pi-{x}' for x in items]
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[0], ids[3], ids[2], ids[1]]
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert _pi_ids(db_path, plan_id) == proposed

    def test_acil_movable_in_segment(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path, oncelik_list=['ACIL', 'NORMAL', 'YUKSEK'])
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[2], ids[1], ids[0]]
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert _pi_ids(db_path, plan_id) == proposed

    def test_two_acil_swap(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path, oncelik_list=['ACIL', 'ACIL', 'NORMAL'])
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[1], ids[0], ids[2]]
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert _pi_ids(db_path, plan_id) == proposed

    def test_completed_task_stays_fixed(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[1], ids[0]])
            assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_arrived_task_stays_fixed(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            _seed_visit(con, plan_id, i2)
            i3 = _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}', f'pi-{i3}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[1], ids[0]])
            assert exc.value.code == 'SEGMENT_BOUNDARY_CROSS'

    def test_unique_sira_preserved(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path, count=4)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[3], ids[1], ids[0], ids[2]]
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert _siras(db_path, plan_id) == [1, 2, 3, 4]
            assert len(set(_siras(db_path, plan_id))) == 4


# ── C. Validation ────────────────────────────────────────────────────────────


class TestManualReorderValidationApi:
    def test_locked_move_409(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1, durum='BASLADI')
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': [ids[1], ids[0]],
            })
            assert resp.status_code == 409
            assert resp.get_json()['error']['code'] == 'LOCKED_TASK_MOVE'

    def test_segment_crossing_409(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            _seed_visit(con, plan_id, i2)
            i3 = _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            ids = [f'pi-{x}' for x in (i1, i2, i3)]
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': [ids[2], ids[1], ids[0]],
            })
            assert resp.status_code == 409
            assert resp.get_json()['error']['code'] == 'SEGMENT_BOUNDARY_CROSS'

    def test_missing_id(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids[:2])
            assert exc.value.code == 'TASK_SET_MISMATCH'

    def test_extra_id(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids + ['pi-9999'])
            assert exc.value.code == 'TASK_SET_MISMATCH'

    def test_duplicate_id(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            bad = [ids[0], ids[0], ids[1]]
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], bad)
            assert exc.value.code == 'DUPLICATE_PROPOSED_TASK_ID'
            assert exc.value.http_status == 422

    def test_cross_plan_id_rejected(self):
        with _temp_atp_db() as db_path:
            plan_a, ids_a = _seed_basic_plan(db_path, count=2)
            plan_b, ids_b = _seed_basic_plan(db_path, count=2, vehicle=OTHER_VEHICLE)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_a)
            mixed = [ids_b[0], ids_a[1]]
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_a, ctx['state_token'], mixed)
            assert exc.value.code == 'TASK_SET_MISMATCH'

    def test_inactive_injection_blocked(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1, durum='IPTAL')
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[1], ids[0]])
            assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_unknown_visit_fail_closed(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.execute(
                """
                INSERT INTO arac_plan_is_ziyaret_durum (
                    plan_id, plan_is_id, arac_external_id, state,
                    geofence_radius_m, exit_radius_m,
                    consecutive_inside, consecutive_outside,
                    arrived_at, departed_at, updated_at, created_at
                ) VALUES (?,?,?,?,200,250,0,0,NULL,NULL,?,?)
                """,
                (plan_id, i2, VEHICLE, 'ALIEN', NOW, NOW),
            )
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[1], ids[0]])
            assert exc.value.code == 'LOCKED_TASK_MOVE'


# ── D. Conflict ──────────────────────────────────────────────────────────────


class TestManualReorderConflict:
    def test_stale_token_409(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            proposed = [ids[2], ids[0], ids[1]]
            client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': proposed,
            })
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': ids,
            })
            assert resp.status_code == 409
            assert resp.get_json()['error']['code'] == 'PLAN_STATE_CONFLICT'

    def test_acil_insert_between_changes_token(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path, count=2)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            token_before = get_manual_reorder_context(plan_id)['state_token']
            con = _conn(db_path)
            talep = _seed_talep(con, oncelik='ACIL', suffix='new')
            _seed_plan_item(con, plan_id, talep, 3)
            con.commit()
            con.close()
            token_after = get_manual_reorder_context(plan_id)['state_token']
            assert token_before != token_after

    def test_gps_arrived_changes_token_without_plan_updated_at(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            updated_before = _plan_updated_at(db_path, plan_id)
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            token_before = get_manual_reorder_context(plan_id)['state_token']
            con = _conn(db_path)
            _seed_visit(con, plan_id, i2)
            con.commit()
            con.close()
            updated_after = _plan_updated_at(db_path, plan_id)
            token_after = get_manual_reorder_context(plan_id)['state_token']
            assert updated_before == updated_after
            assert token_before != token_after

    def test_status_change_changes_token(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path, count=2)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            token_before = get_manual_reorder_context(plan_id)['state_token']
            con = _conn(db_path)
            pi_id = int(ids[0].split('-')[1])
            con.execute(
                "UPDATE arac_gunluk_plan_is SET durum='BASLADI' WHERE id=?",
                (pi_id,),
            )
            con.commit()
            con.close()
            token_after = get_manual_reorder_context(plan_id)['state_token']
            assert token_before != token_after

    def test_parallel_reorder_second_fails(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[0], ids[1]])
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            assert exc.value.code == 'PLAN_STATE_CONFLICT'

    def test_token_catches_visit_change_when_updated_at_unchanged(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            con = _conn(db_path)
            _seed_visit(con, plan_id, i2)
            con.commit()
            con.close()
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            assert exc.value.code == 'PLAN_STATE_CONFLICT'

    def test_same_state_same_token(self):
        with _temp_atp_db() as db_path:
            plan_id, _ = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            a = get_manual_reorder_context(plan_id)
            b = get_manual_reorder_context(plan_id)
            assert a['state_token'] == b['state_token']

    def test_other_plan_change_does_not_affect_target_token(self):
        with _temp_atp_db() as db_path:
            plan_a, _ = _seed_basic_plan(db_path)
            plan_b, ids_b = _seed_basic_plan(db_path, vehicle=OTHER_VEHICLE)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            token_a_before = get_manual_reorder_context(plan_a)['state_token']
            ctx_b = get_manual_reorder_context(plan_b)
            apply_manual_reorder(USER_ID, plan_b, ctx_b['state_token'], [ids_b[2], ids_b[0], ids_b[1]])
            token_a_after = get_manual_reorder_context(plan_a)['state_token']
            assert token_a_before == token_a_after


# ── E. Invalidation / rollback ───────────────────────────────────────────────


class TestInvalidationRollback:
    def test_snapshot_deactivated_on_reorder(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            con = _conn(db_path)
            _seed_snapshot(con, plan_id)
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            result = apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[0], ids[1]])
            assert result['snapshot_deactivated'] is True
            con = _conn(db_path)
            active = con.execute(
                'SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1',
                (plan_id,),
            ).fetchone()[0]
            con.close()
            assert active == 0

    def test_etas_cleared_on_reorder(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            result = apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[0], ids[1]])
            assert result['etas_cleared'] is True
            con = _conn(db_path)
            non_null = con.execute(
                'SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE plan_id=? AND tahmini_varis_saati IS NOT NULL',
                (plan_id,),
            ).fetchone()[0]
            con.close()
            assert non_null == 0

    def test_other_plan_snapshot_preserved(self):
        with _temp_atp_db() as db_path:
            plan_a, ids_a = _seed_basic_plan(db_path)
            plan_b, _ = _seed_basic_plan(db_path, vehicle=OTHER_VEHICLE)
            con = _conn(db_path)
            _seed_snapshot(con, plan_b)
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_a)
            apply_manual_reorder(USER_ID, plan_a, ctx['state_token'], [ids_a[2], ids_a[0], ids_a[1]])
            con = _conn(db_path)
            active_b = con.execute(
                'SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1',
                (plan_b,),
            ).fetchone()[0]
            con.close()
            assert active_b == 1

    def test_other_plan_eta_preserved(self):
        with _temp_atp_db() as db_path:
            plan_a, ids_a = _seed_basic_plan(db_path)
            plan_b, _ = _seed_basic_plan(db_path, vehicle=OTHER_VEHICLE)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_a)
            apply_manual_reorder(USER_ID, plan_a, ctx['state_token'], [ids_a[2], ids_a[0], ids_a[1]])
            con = _conn(db_path)
            eta_b = con.execute(
                'SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE plan_id=? AND tahmini_varis_saati IS NOT NULL',
                (plan_b,),
            ).fetchone()[0]
            con.close()
            assert eta_b == 3

    def test_invalidation_error_full_rollback(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            before = _pi_ids(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with patch(
                'modules.planlama.arac_plan_rota_snapshot_service.invalidate_plan_route_state_after_manual_reorder_conn',
                side_effect=RuntimeError('boom'),
            ):
                with pytest.raises(RuntimeError):
                    apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[0], ids[1]])
            assert _pi_ids(db_path, plan_id) == before

    def test_reorder_error_full_rollback(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            before = _pi_ids(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with patch(
                'modules.planlama.arac_takip_repo.reorder_plan_items_by_plan_id_conn',
                side_effect=RuntimeError('db fail'),
            ):
                with pytest.raises(RuntimeError):
                    apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[2], ids[0], ids[1]])
            assert _pi_ids(db_path, plan_id) == before

    def test_conflict_no_writes(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            before_order = _pi_ids(db_path, plan_id)
            before_updated = _plan_updated_at(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
            )
            with pytest.raises(ManualReorderServiceError):
                apply_manual_reorder(USER_ID, plan_id, 'deadbeef', ids)
            assert _pi_ids(db_path, plan_id) == before_order
            assert _plan_updated_at(db_path, plan_id) == before_updated

    def test_validation_error_no_writes(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            before = _pi_ids(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError):
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids[:2])
            assert _pi_ids(db_path, plan_id) == before


# ── F. No-op / auth / misc ───────────────────────────────────────────────────


class TestNoOpAndAuth:
    def test_same_order_changed_false(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            result = apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            assert result['changed'] is False
            assert result['route_state_invalidated'] is False

    def test_noop_snapshot_preserved(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            con = _conn(db_path)
            _seed_snapshot(con, plan_id)
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            con = _conn(db_path)
            active = con.execute(
                'SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1',
                (plan_id,),
            ).fetchone()[0]
            con.close()
            assert active == 1

    def test_noop_eta_preserved(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            con = _conn(db_path)
            eta_count = con.execute(
                'SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE plan_id=? AND tahmini_varis_saati IS NOT NULL',
                (plan_id,),
            ).fetchone()[0]
            con.close()
            assert eta_count == 3

    def test_noop_updated_at_and_token_same(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            from modules.planlama.arac_manual_reorder_service import (
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            updated_before = _plan_updated_at(db_path, plan_id)
            result = apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], ids)
            updated_after = _plan_updated_at(db_path, plan_id)
            assert updated_before == updated_after
            assert result['state_token'] == ctx['state_token']

    def test_unauthorized_post_403(self):
        with _temp_atp_db():
            client = _build_flask_client(can_update=False)
            resp = client.post(APPLY_URL, json={'plan_id': 1, 'state_token': 'x', 'ordered_item_ids': []})
            assert resp.status_code == 403

    def test_missing_json_fields_400(self):
        with _temp_atp_db():
            client = _build_flask_client()
            resp = client.post(APPLY_URL, json={'plan_id': 'bad'})
            assert resp.status_code == 400

    def test_invalid_plan_id_zero(self):
        with _temp_atp_db():
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
            )
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, 0, 'token', [])
            assert exc.value.http_status == 400

    def test_manual_invalidation_helper_no_commit(self):
        from modules.planlama.arac_plan_rota_snapshot_service import (
            invalidate_plan_route_state_after_manual_reorder_conn,
        )
        src = inspect.getsource(invalidate_plan_route_state_after_manual_reorder_conn)
        assert 'con.commit' not in src
        assert 'con.rollback' not in src

    def test_build_state_token_module_imports(self):
        from modules.planlama import arac_manual_reorder_service as svc
        src = inspect.getsource(svc)
        assert 'get_conn' not in src.split('build_manual_reorder_state_token')[1].split('def get_manual_reorder_context')[0]
        assert 'flask' not in src.lower()


# ── Canonical DB safety ───────────────────────────────────────────────────────


class TestCanonicalDbSafety:
    def test_collection_import_worktree_canonical_absent(self):
        _assert_worktree_canonical_absent('collection import check')

    def test_manual_reorder_modules_import_no_worktree_db(self):
        from modules.planlama import arac_manual_reorder_service  # noqa: F401
        from modules.planlama import arac_takip_routes  # noqa: F401
        _assert_worktree_canonical_absent('after manual reorder imports')

    def test_flask_client_setup_no_worktree_db(self):
        with _temp_atp_db():
            _build_flask_client()
            _assert_worktree_canonical_absent('after flask client setup')

    def test_context_get_no_worktree_db(self):
        with _temp_atp_db() as db_path:
            plan_id, _ = _seed_basic_plan(db_path)
            client = _build_flask_client()
            resp = client.get(CONTEXT_URL, query_string={'plan_id': plan_id})
            assert resp.status_code == 200
            _assert_worktree_canonical_absent('after context GET')

    def test_successful_reorder_post_no_worktree_db(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            proposed = [ids[2], ids[0], ids[1]]
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': proposed,
            })
            assert resp.status_code == 200
            _assert_worktree_canonical_absent('after successful reorder POST')

    def test_validation_409_no_worktree_db(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1, durum='BASLADI')
            i2 = _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}']
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': [ids[1], ids[0]],
            })
            assert resp.status_code == 409
            _assert_worktree_canonical_absent('after validation 409')

    def test_conflict_409_no_worktree_db(self):
        with _temp_atp_db() as db_path:
            plan_id, ids = _seed_basic_plan(db_path)
            client = _build_flask_client()
            ctx = client.get(CONTEXT_URL, query_string={'plan_id': plan_id}).get_json()
            client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': [ids[2], ids[0], ids[1]],
            })
            resp = client.post(APPLY_URL, json={
                'plan_id': plan_id,
                'state_token': ctx['state_token'],
                'ordered_item_ids': ids,
            })
            assert resp.status_code == 409
            _assert_worktree_canonical_absent('after conflict 409')

    def test_unauthorized_403_no_worktree_db(self):
        with _temp_atp_db():
            client = _build_flask_client(can_update=False)
            resp = client.post(APPLY_URL, json={'plan_id': 1, 'state_token': 'x', 'ordered_item_ids': []})
            assert resp.status_code == 403
            _assert_worktree_canonical_absent('after unauthorized 403')

    def test_temp_db_under_temp_directory(self):
        with _temp_atp_db() as db_path:
            temp_root = tempfile.gettempdir()
            assert Path(db_path).resolve().as_posix().lower().startswith(
                Path(temp_root).resolve().as_posix().lower(),
            )

    def test_active_connection_not_worktree_canonical(self):
        with _temp_atp_db() as db_path:
            active = _active_mock_db_path()
            assert resolve_path(active) == resolve_path(db_path)
            assert resolve_path(active) != resolve_path(str(_WORKTREE_CANONICAL_DB))

    def test_no_cleanup_deletes_worktree_canonical(self):
        src = inspect.getsource(_u3c_test_canonical_invariant)
        src_module = inspect.getsource(_u3c_module_canonical_guard)
        combined = src + src_module + inspect.getsource(_assert_worktree_canonical_absent)
        assert 'unlink' not in combined
        assert 'remove(' not in combined
        assert 'os.remove' not in combined

    def test_guard_blocks_worktree_canonical_connect(self):
        from tools.nexgen_tmp_db import LiveDbWriteError
        from db import get_conn

        with pytest.raises(LiveDbWriteError):
            import config
            config.Config.MOCK_DB_PATH = str(_WORKTREE_CANONICAL_DB)
            get_conn()


# ── Inactive contract ─────────────────────────────────────────────────────────


class TestInactiveContract:
    def test_context_returns_full_canonical_task_set(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            _seed_plan_item(con, plan_id, t1, 1)
            _seed_plan_item(con, plan_id, t2, 2, durum='IPTAL')
            _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            expected = _pi_ids(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            assert ctx['ordered_item_ids'] == expected
            assert len(ctx['tasks']) == 3

    def test_inactive_tasks_present_in_context(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2, durum='ERTELENDI')
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            inactive = [t for t in ctx['tasks'] if t['task_id'] == f'pi-{i2}'][0]
            assert inactive['can_move'] is False
            assert inactive['lock_reason'] == 'STATUS_INACTIVE'

    def test_ordered_item_ids_is_full_set(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            ids = []
            for i, st in enumerate(['PLANLANDI', 'GIDILEMEDI', 'PLANLANDI']):
                t = _seed_talep(con, suffix=str(i))
                ids.append(_seed_plan_item(con, plan_id, t, i + 1, durum=st))
            con.commit()
            con.close()
            expected = [f'pi-{x}' for x in ids]
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            assert set(ctx['ordered_item_ids']) == set(expected)
            assert len(ctx['ordered_item_ids']) == len(expected)

    def test_hidden_inactive_stays_at_canonical_index(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2, durum='IPTAL')
            i3 = _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            ids = [f'pi-{i1}', f'pi-{i2}', f'pi-{i3}']
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], [ids[0], ids[2], ids[1]])
            assert exc.value.code == 'LOCKED_TASK_MOVE'

    def test_visible_crossing_hidden_inactive_boundary_fails(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            t3 = _seed_talep(con, suffix='c')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_plan_item(con, plan_id, t2, 2, durum='ERTELENDI')
            i3 = _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            ids = _pi_ids(db_path, plan_id)
            from modules.planlama.arac_manual_reorder_service import (
                ManualReorderServiceError,
                apply_manual_reorder,
                get_manual_reorder_context,
            )
            ctx = get_manual_reorder_context(plan_id)
            proposed = [ids[2], ids[1], ids[0]]
            with pytest.raises(ManualReorderServiceError) as exc:
                apply_manual_reorder(USER_ID, plan_id, ctx['state_token'], proposed)
            assert exc.value.code in ('LOCKED_TASK_MOVE', 'SEGMENT_BOUNDARY_CROSS')

    def test_u3d_can_keep_inactive_id_in_draft_array(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            i1 = _seed_plan_item(con, plan_id, t1, 1)
            i2 = _seed_plan_item(con, plan_id, t2, 2, durum='IPTAL')
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            draft = list(ctx['ordered_item_ids'])
            assert draft[1] == f'pi-{i2}'
            draft[0], draft[1] = draft[1], draft[0]
            assert draft != ctx['ordered_item_ids']

    def test_inactive_contract_ok_marker(self):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            t2 = _seed_talep(con, suffix='b')
            _seed_plan_item(con, plan_id, t1, 1)
            _seed_plan_item(con, plan_id, t2, 2, durum='GIDILEMEDI')
            con.commit()
            con.close()
            from modules.planlama.arac_manual_reorder_service import get_manual_reorder_context
            ctx = get_manual_reorder_context(plan_id)
            assert len(ctx['ordered_item_ids']) == 2
            assert all(t['lock_reason'] in (None, 'STATUS_INACTIVE') for t in ctx['tasks'])
            assert sum(1 for t in ctx['tasks'] if t['lock_reason'] == 'STATUS_INACTIVE') == 1

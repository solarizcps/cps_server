# -*- coding: utf-8 -*-
"""U2B — ACIL insert sonrası snapshot/ETA invalidation (temp DB only)."""
from __future__ import annotations

import importlib.util
import inspect
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'
PLAN_DATE = '2026-08-26'
OTHER_DATE = '2026-08-27'
VEHICLE = '45077045'
OTHER_VEHICLE = '45077046'
PLAKA = '34 MOR 049'
NOW = '2026-08-26 10:00:00'
USER_ID = 1

FILOM_FIXTURE = {
    'ok': True,
    'vehicles': [{'id': VEHICLE, 'plate': '34MOR049', 'plate_display': '34 MOR 049', 'driver_name': 'ibrahim'}],
}


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db(*, with_rota: bool = True, with_eta: bool = True):
    tmpdir = tempfile.mkdtemp(prefix='u2b_inval_')
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
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


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
    talep_no = f'U2B-{oncelik}-{suffix}-{con.total_changes}'
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
) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,'AKTIF',?,?,?,?)
        """,
        (plan_date, 'TURKCELL_FILOM', vehicle, plaka, NOW, USER_ID, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_plan_item(
    con: sqlite3.Connection,
    plan_id: int,
    talep_id: int,
    sira: int,
    *,
    durum: str = 'PLANLANDI',
    eta: str | None = None,
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


def _seed_visit(con: sqlite3.Connection, plan_id: int, plan_is_id: int, *, state: str = 'ARRIVED') -> None:
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m, consecutive_inside, consecutive_outside,
            arrived_at, updated_at, created_at
        ) VALUES (?,?,?,?,200,250,0,0,?,?,?)
        """,
        (plan_id, plan_is_id, VEHICLE, state, NOW, NOW, NOW),
    )


def _seed_active_snapshot(con: sqlite3.Connection, plan_id: int) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_plan_rota_snapshot (
            plan_id, route_version, arac_provider, routing_provider,
            geometry_json, geometry_schema, content_hash,
            total_distance_m, total_duration_s, stop_order_json,
            is_active, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
        """,
        (
            plan_id, 1, 'TURKCELL_FILOM', 'internal',
            json.dumps({'type': 'LineString', 'coordinates': [[29.0, 41.0], [29.1, 41.1]]}),
            'geojson_linestring_v1', 'hash1', 1000.0, 600.0,
            json.dumps([{'plan_item_id': 1}]), NOW, USER_ID,
        ),
    )
    return int(cur.lastrowid)


def _active_snapshot(con: sqlite3.Connection, plan_id: int) -> sqlite3.Row | None:
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_rota_snapshot'",
    ).fetchone():
        return None
    return con.execute(
        'SELECT * FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1',
        (plan_id,),
    ).fetchone()


def _etas(db_path: str, plan_id: int) -> list[str | None]:
    con = _conn(db_path)
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
        if 'tahmini_varis_saati' not in cols:
            return []
        rows = con.execute(
            'SELECT tahmini_varis_saati FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (plan_id,),
        ).fetchall()
        return [r['tahmini_varis_saati'] for r in rows]
    finally:
        con.close()


def _acil_payload(**kw) -> dict:
    p = {
        'plan_tarihi': PLAN_DATE,
        'arac_external_id': VEHICLE,
        'firma': 'Acil',
        'adres': 'Adres Istanbul',
        'yapilacak_is': 'Acil Is',
        'latitude': 41.01,
        'longitude': 29.01,
        'oncelik': 'ACIL',
    }
    p.update(kw)
    return p


@pytest.fixture(autouse=True)
def _vehicle_catalog():
    from modules.planlama.arac_vehicle_identity_service import update_filom_vehicle_catalog
    update_filom_vehicle_catalog(FILOM_FIXTURE['vehicles'])
    yield
    update_filom_vehicle_catalog([])


@patch(
    'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    return_value=FILOM_FIXTURE,
)
class TestAcilRouteStateInvalidation:
    def test_acil_deactivates_active_snapshot(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Existing', suffix='e')
            _seed_plan_item(con, plan_id, t1, 1)
            _seed_active_snapshot(con, plan_id)
            con.commit()
            con.close()
            assert _active_snapshot(_conn(db_path), plan_id) is not None
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='snap1'))
            con = _conn(db_path)
            assert _active_snapshot(con, plan_id) is None
            inactive = con.execute(
                'SELECT is_active FROM arac_plan_rota_snapshot WHERE plan_id=?', (plan_id,),
            ).fetchone()
            con.close()
            assert int(inactive['is_active']) == 0

    def test_acil_clears_etas(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='E1', suffix='e1')
            _seed_plan_item(con, plan_id, t1, 1, eta='09:30')
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='eta1'))
            assert all(v is None for v in _etas(db_path, plan_id))

    def test_acil_no_snapshot_no_error(self, _mock):
        with _temp_atp_db() as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='nosnap'))
            assert result['ok'] is True

    def test_acil_eta_already_null_ok(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='n')
            _seed_plan_item(con, plan_id, t1, 1, eta=None)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='nullok'))
            assert all(v is None for v in _etas(db_path, plan_id))

    def test_other_plan_snapshot_preserved(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            target = _seed_plan(con)
            other = _seed_plan(con, vehicle=OTHER_VEHICLE, plaka='34 XYZ 001')
            t1 = _seed_talep(con, yapilacak_is='T', suffix='t')
            _seed_plan_item(con, target, t1, 1)
            _seed_active_snapshot(con, target)
            _seed_active_snapshot(con, other)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='oth1'))
            con = _conn(db_path)
            assert _active_snapshot(con, target) is None
            assert _active_snapshot(con, other) is not None
            con.close()

    def test_other_day_snapshot_preserved(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            target = _seed_plan(con)
            other = _seed_plan(con, plan_date=OTHER_DATE)
            t1 = _seed_talep(con, suffix='d')
            _seed_plan_item(con, target, t1, 1)
            _seed_active_snapshot(con, target)
            _seed_active_snapshot(con, other)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='day'))
            con = _conn(db_path)
            assert _active_snapshot(con, other) is not None
            con.close()

    def test_other_vehicle_snapshot_preserved(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            target = _seed_plan(con)
            other = _seed_plan(con, vehicle=OTHER_VEHICLE, plaka='34 OTH 001')
            t1 = _seed_talep(con, suffix='v')
            _seed_plan_item(con, target, t1, 1)
            _seed_active_snapshot(con, target)
            _seed_active_snapshot(con, other)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='veh'))
            con = _conn(db_path)
            assert _active_snapshot(con, other) is not None
            con.close()

    def test_other_plan_etas_preserved(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            target = _seed_plan(con)
            other = _seed_plan(con, vehicle=OTHER_VEHICLE, plaka='34 OTH 002')
            t1 = _seed_talep(con, suffix='t')
            _seed_plan_item(con, target, t1, 1, eta='08:00')
            ot = _seed_talep(con, yapilacak_is='Other', suffix='o')
            _seed_plan_item(con, other, ot, 1, eta='11:00')
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='oeta'))
            assert _etas(db_path, other) == ['11:00']

    def test_add_job_path_invalidates(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='a')
            _seed_plan_item(con, plan_id, t1, 1, eta='10:00')
            _seed_active_snapshot(con, plan_id)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='addp'))
            con = _conn(db_path)
            assert _active_snapshot(con, plan_id) is None
            con.close()

    def test_assign_to_plan_path_invalidates(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Done', suffix='d')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI', eta='09:00')
            acil_tid = _seed_talep(con, oncelik='ACIL', yapilacak_is='Assign', suffix='as')
            _seed_active_snapshot(con, plan_id)
            con.commit()
            con.close()
            from modules.planlama.arac_takip_repo import assign_to_plan
            assign_to_plan(USER_ID, acil_tid, PLAN_DATE, VEHICLE, PLAKA, None, None, None)
            con = _conn(db_path)
            assert _active_snapshot(con, plan_id) is None
            assert all(v is None for v in _etas(db_path, plan_id))
            con.close()

    @pytest.mark.parametrize('oncelik', ['NORMAL', 'YUKSEK', 'DUSUK'])
    def test_non_acil_preserves_snapshot_and_eta(self, _mock, oncelik):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Keep', suffix='k')
            _seed_plan_item(con, plan_id, t1, 1, eta='12:00')
            _seed_active_snapshot(con, plan_id)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(
                USER_ID,
                _acil_payload(oncelik=oncelik, yapilacak_is=f'{oncelik} Is', client_submit_id=f'na_{oncelik}'),
            )
            con = _conn(db_path)
            assert _active_snapshot(con, plan_id) is not None
            con.close()
            etas = _etas(db_path, plan_id)
            assert '12:00' in etas

    def test_snapshot_failure_rolls_back_all(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='rb')
            _seed_plan_item(con, plan_id, t1, 1, eta='08:15')
            _seed_active_snapshot(con, plan_id)
            con.commit()
            before_items = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0]
            before_eta = _etas(db_path, plan_id)
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            with patch(
                'modules.planlama.arac_plan_rota_snapshot_service.invalidate_active_plan_route_snapshot_conn',
                side_effect=RuntimeError('snap fail'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rbsnap'))
            con = _conn(db_path)
            after_items = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0]
            con.close()
            assert after_items == before_items
            assert _active_snapshot(_conn(db_path), plan_id) is not None
            assert _etas(db_path, plan_id) == before_eta

    def test_eta_clear_failure_rolls_back_all(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='rbe')
            _seed_plan_item(con, plan_id, t1, 1, eta='07:45')
            _seed_active_snapshot(con, plan_id)
            con.commit()
            con.close()
            before_items = _conn(db_path).execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0]
            _conn(db_path).close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            with patch(
                'modules.planlama.arac_takip_repo.clear_plan_item_etas_conn',
                side_effect=RuntimeError('eta fail'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rbeta'))
            after_items = _conn(db_path).execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0]
            _conn(db_path).close()
            assert after_items == before_items
            assert _active_snapshot(_conn(db_path), plan_id) is not None

    def test_assign_rollback_preserves_bekleyen_talep(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, suffix='x')
            _seed_plan_item(con, plan_id, t1, 1)
            acil_tid = _seed_talep(con, oncelik='ACIL', suffix='rb')
            con.commit()
            con.close()
            from modules.planlama.arac_takip_repo import assign_to_plan
            with patch(
                'modules.planlama.arac_plan_rota_snapshot_service.invalidate_active_plan_route_snapshot_conn',
                side_effect=RuntimeError('fail'),
            ):
                with pytest.raises(RuntimeError):
                    assign_to_plan(USER_ID, acil_tid, PLAN_DATE, VEHICLE, PLAKA, None, None, None)
            con = _conn(db_path)
            row = con.execute('SELECT durum FROM arac_is_talebi WHERE id=?', (acil_tid,)).fetchone()
            assigned = con.execute(
                'SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE is_talebi_id=?', (acil_tid,),
            ).fetchone()[0]
            con.close()
            assert row['durum'] == 'BEKLIYOR'
            assert assigned == 0

    def test_visit_state_unchanged_after_acil(self, _mock):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Visited', suffix='v')
            pi1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_visit(con, plan_id, pi1, state='ARRIVED')
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='visit'))
            con = _conn(db_path)
            visit = con.execute(
                'SELECT state, arrived_at FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?', (pi1,),
            ).fetchone()
            con.close()
            assert visit['state'] == 'ARRIVED'
            assert visit['arrived_at'] is not None

    def test_no_route_engine_or_maps_import_in_helpers(self, _mock):
        from modules.planlama import arac_plan_rota_snapshot_service as svc
        src_snap = inspect.getsource(svc.invalidate_active_plan_route_snapshot_conn)
        src_all = inspect.getsource(svc.invalidate_plan_route_state_after_acil_insert_conn)
        from modules.planlama.arac_takip_repo import clear_plan_item_etas_conn
        src_eta = inspect.getsource(clear_plan_item_etas_conn)
        for blob in (src_snap, src_all, src_eta):
            assert 'build_plan_route_dto' not in blob
            assert 'parse_maps_coords' not in blob
            assert 'get_conn(' not in blob
            assert 'commit(' not in blob
            assert 'rollback(' not in blob

    def test_optional_tables_missing_safe_noop(self, _mock):
        with _temp_atp_db(with_rota=False, with_eta=False) as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='opt'))
            assert result['ok'] is True

    def test_snapshot_table_no_row_for_plan(self, _mock):
        with _temp_atp_db() as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='norow'))
            assert result['ok'] is True

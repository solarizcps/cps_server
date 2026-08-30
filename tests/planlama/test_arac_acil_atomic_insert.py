# -*- coding: utf-8 -*-
"""U2A — ACIL atomic safe insert via production add/assign paths (temp DB only)."""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'
PLAN_DATE = '2026-08-26'
VEHICLE = '45077045'
PLAKA = '34 MOR 049'
NOW = '2026-08-26 10:00:00'
USER_ID = 1

FILOM_FIXTURE = {
    'ok': True,
    'vehicles': [
        {
            'id': VEHICLE,
            'plate': '34MOR049',
            'plate_display': '34 MOR 049',
            'driver_name': 'ibrahim',
        },
    ],
}


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_atp_db():
    tmpdir = tempfile.mkdtemp(prefix='u2a_acil_')
    db_path = str(Path(tmpdir) / 'test.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
    ):
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
            firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi,
            created_at, created_by
        ) VALUES (?,?,?,?,1,0,?,?)
        """,
        ('Test Firma', 'Test Adres Istanbul', 41.01, 29.01, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_talep(
    con: sqlite3.Connection,
    *,
    oncelik: str = 'NORMAL',
    durum: str = 'BEKLIYOR',
    yapilacak_is: str = 'Teslimat',
    suffix: str = '',
) -> int:
    loc_id = _seed_location(con)
    talep_no = f'U2A-{oncelik}-{suffix or yapilacak_is[:8]}-{con.total_changes}'
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            kayitli_yer_id, firma_adi, adres, latitude, longitude, yapilacak_is,
            oncelik, durum, save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)
        """,
        (
            talep_no, USER_ID, 'Test User', PLAN_DATE,
            loc_id, 'Test Firma', 'Test Adres', 41.01, 29.01, yapilacak_is,
            oncelik, durum, NOW, USER_ID, NOW, USER_ID,
        ),
    )
    return int(cur.lastrowid)


def _seed_plan(con: sqlite3.Connection) -> int:
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,'AKTIF',?,?,?,?)
        """,
        (PLAN_DATE, 'TURKCELL_FILOM', VEHICLE, PLAKA, NOW, USER_ID, NOW, USER_ID),
    )
    return int(cur.lastrowid)


def _seed_plan_item(
    con: sqlite3.Connection,
    plan_id: int,
    talep_id: int,
    sira: int,
    durum: str = 'PLANLANDI',
) -> int:
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
    state: str,
    arrived_at: str | None = None,
    departed_at: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m,
            consecutive_inside, consecutive_outside,
            arrived_at, departed_at, updated_at, created_at
        ) VALUES (?,?,?,?,200,250,0,0,?,?,?,?)
        """,
        (plan_id, plan_is_id, VEHICLE, state, arrived_at, departed_at, NOW, NOW),
    )


def _ordered_siras(db_path: str, plan_id: int) -> list[int]:
    con = _conn(db_path)
    try:
        rows = con.execute(
            'SELECT sira FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (plan_id,),
        ).fetchall()
        return [int(r['sira']) for r in rows]
    finally:
        con.close()


def _ordered_item_ids(db_path: str, plan_id: int) -> list[int]:
    con = _conn(db_path)
    try:
        rows = con.execute(
            'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (plan_id,),
        ).fetchall()
        return [int(r['id']) for r in rows]
    finally:
        con.close()


def _item_sira(db_path: str, plan_is_id: int) -> int:
    con = _conn(db_path)
    try:
        row = con.execute(
            'SELECT sira FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
        ).fetchone()
        return int(row['sira'])
    finally:
        con.close()


def _counts(db_path: str) -> dict[str, int]:
    con = _conn(db_path)
    try:
        return {
            'talep': con.execute('SELECT COUNT(*) FROM arac_is_talebi').fetchone()[0],
            'plan': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0],
            'item': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0],
        }
    finally:
        con.close()


def _plan_updated_at(db_path: str, plan_id: int) -> str:
    con = _conn(db_path)
    try:
        row = con.execute(
            'SELECT updated_at FROM arac_gunluk_plan WHERE id=?', (plan_id,),
        ).fetchone()
        return str(row['updated_at'])
    finally:
        con.close()


def _acil_payload(**overrides) -> dict:
    payload = {
        'plan_tarihi': PLAN_DATE,
        'arac_external_id': VEHICLE,
        'firma': 'Acil Firma',
        'adres': 'Acil Adres Istanbul',
        'yapilacak_is': 'Acil Is',
        'latitude': 41.02,
        'longitude': 29.02,
        'oncelik': 'ACIL',
    }
    payload.update(overrides)
    return payload


def _non_acil_payload(oncelik: str = 'NORMAL', **overrides) -> dict:
    payload = _acil_payload(oncelik=oncelik, yapilacak_is=f'{oncelik} Is')
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _seed_vehicle_catalog():
    from modules.planlama.arac_vehicle_identity_service import update_filom_vehicle_catalog
    update_filom_vehicle_catalog(FILOM_FIXTURE['vehicles'])
    yield
    update_filom_vehicle_catalog([])


@patch(
    'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    return_value=FILOM_FIXTURE,
)
class TestAcilAtomicInsert:
    # 1–2 empty / all movable
    def test_empty_plan_acil_sira_1(self, _mock_filom):
        with _temp_atp_db() as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='empty1'))
            assert _item_sira(db_path, result['plan_is_id']) == 1

    def test_all_movable_acil_sira_1(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            for i in range(1, 4):
                tid = _seed_talep(con, oncelik='NORMAL', yapilacak_is=f'M{i}', suffix=str(i))
                _seed_plan_item(con, plan_id, tid, i)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='allmov'))
            assert _item_sira(db_path, result['plan_is_id']) == 1
            assert _ordered_siras(db_path, plan_id) == [1, 2, 3, 4]

    # 3 TAMAMLANDI prefix
    def test_tamamlandi_prefix_acil(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Done', suffix='d1')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            t2 = _seed_talep(con, yapilacak_is='M1', suffix='m1')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='tam'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 4 interleaved ARRIVED
    def test_interleaved_arrived(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='A', suffix='a')
            _seed_plan_item(con, plan_id, t1, 1)
            t2 = _seed_talep(con, yapilacak_is='Arrived', suffix='arr')
            pi2 = _seed_plan_item(con, plan_id, t2, 2)
            _seed_visit(con, plan_id, pi2, state='ARRIVED')
            t3 = _seed_talep(con, yapilacak_is='C', suffix='c')
            _seed_plan_item(con, plan_id, t3, 3)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='arr'))
            assert _item_sira(db_path, result['plan_is_id']) == 3

    # 5 BASLADI
    def test_interleaved_basladi(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Started', suffix='s')
            _seed_plan_item(con, plan_id, t1, 1, durum='BASLADI')
            t2 = _seed_talep(con, yapilacak_is='M', suffix='m')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='bas'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 6 DEPARTED_PENDING
    def test_interleaved_departed_pending(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Pend', suffix='p')
            pi1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_visit(con, plan_id, pi1, state='DEPARTED_PENDING', arrived_at=NOW)
            t2 = _seed_talep(con, yapilacak_is='Tail', suffix='t')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='dp'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 7 legacy DEPARTED
    def test_legacy_departed_lock(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Legacy', suffix='leg')
            pi1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_visit(con, plan_id, pi1, state='DEPARTED', arrived_at=NOW, departed_at=NOW)
            t2 = _seed_talep(con, yapilacak_is='Tail', suffix='t2')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='dep'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 8 visit timestamp lock
    def test_visit_timestamp_lock(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Ts', suffix='ts')
            pi1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_visit(con, plan_id, pi1, state='OUTSIDE', arrived_at=NOW)
            t2 = _seed_talep(con, yapilacak_is='Tail', suffix='tt')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='vts'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 9 unknown visit state
    def test_unknown_visit_state_safe_lock(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Unk', suffix='unk')
            pi1 = _seed_plan_item(con, plan_id, t1, 1)
            _seed_visit(con, plan_id, pi1, state='MYSTERY')
            t2 = _seed_talep(con, yapilacak_is='Tail', suffix='t')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='unk'))
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 10 all locked → ACIL at end
    def test_all_locked_acil_at_end(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='L1', suffix='l1')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            t2 = _seed_talep(con, yapilacak_is='L2', suffix='l2')
            pi2 = _seed_plan_item(con, plan_id, t2, 2)
            _seed_visit(con, plan_id, pi2, state='ARRIVED')
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='allock'))
            assert _item_sira(db_path, result['plan_is_id']) == 3

    # 11–13 non-ACIL append
    @pytest.mark.parametrize('oncelik', ['NORMAL', 'YUKSEK', 'DUSUK'])
    def test_non_acil_appends_at_end(self, _mock_filom, oncelik):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='First', suffix='f')
            _seed_plan_item(con, plan_id, t1, 1)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(
                USER_ID,
                _non_acil_payload(oncelik, client_submit_id=f'na_{oncelik}'),
            )
            assert _item_sira(db_path, result['plan_is_id']) == 2

    # 14 relative order preserved
    def test_relative_order_preserved(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            ids = []
            for i in range(1, 4):
                tid = _seed_talep(con, yapilacak_is=f'R{i}', suffix=str(i))
                ids.append(_seed_plan_item(con, plan_id, tid, i))
            con.commit()
            con.close()
            before = _ordered_item_ids(db_path, plan_id)
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rel'))
            after = _ordered_item_ids(db_path, plan_id)
            assert after[1:] == before

    # 15 UNIQUE order
    def test_unique_plan_sira_preserved(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            for i in range(1, 3):
                tid = _seed_talep(con, yapilacak_is=f'U{i}', suffix=str(i))
                _seed_plan_item(con, plan_id, tid, i)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='uniq'))
            siras = _ordered_siras(db_path, plan_id)
            assert len(siras) == len(set(siras))
            assert sorted(siras) == list(range(1, len(siras) + 1))

    # 16–19 rollback
    def test_full_rollback_on_insert_failure(self, _mock_filom):
        with _temp_atp_db() as db_path:
            before = _counts(db_path)
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic, _add_plan_item_conn
            with patch(
                'modules.planlama.arac_add_to_plan_service._add_plan_item_conn',
                side_effect=RuntimeError('simulated insert failure'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rb_full'))
            assert _counts(db_path) == before

    def test_talep_insert_rollback(self, _mock_filom):
        with _temp_atp_db() as db_path:
            before = _counts(db_path)
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic, _create_request_conn
            with patch(
                'modules.planlama.arac_add_to_plan_service._create_request_conn',
                side_effect=RuntimeError('talep fail'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rb_talep'))
            assert _counts(db_path) == before

    def test_plan_item_insert_rollback(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Keep', suffix='k')
            _seed_plan_item(con, plan_id, t1, 1)
            con.commit()
            con.close()
            before_items = _ordered_siras(db_path, plan_id)
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            with patch(
                'modules.planlama.arac_add_to_plan_service._add_plan_item_conn',
                side_effect=RuntimeError('plan item fail'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rb_pi'))
            assert _ordered_siras(db_path, plan_id) == before_items

    def test_plan_updated_at_rollback(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            con.commit()
            con.close()
            before_ts = _plan_updated_at(db_path, plan_id)
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            with patch(
                'modules.planlama.arac_add_to_plan_service._add_plan_item_conn',
                side_effect=RuntimeError('fail'),
            ):
                with pytest.raises(RuntimeError):
                    add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='rb_ts'))
            assert _plan_updated_at(db_path, plan_id) == before_ts

    # 20 add_job path
    def test_add_job_to_plan_atomic_path(self, _mock_filom):
        with _temp_atp_db() as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='path_add'))
            assert result['ok'] is True
            assert _item_sira(db_path, result['plan_is_id']) == 1

    # 21 assign_to_plan path
    def test_assign_to_plan_path(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Existing', suffix='ex')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            acil_tid = _seed_talep(con, oncelik='ACIL', yapilacak_is='Assign Acil', suffix='as')
            con.commit()
            con.close()
            from modules.planlama.arac_takip_repo import assign_to_plan
            assign_to_plan(USER_ID, acil_tid, PLAN_DATE, VEHICLE, PLAKA, None, None, None)
            con = _conn(db_path)
            row = con.execute(
                'SELECT id, sira FROM arac_gunluk_plan_is WHERE is_talebi_id=?', (acil_tid,),
            ).fetchone()
            con.close()
            assert int(row['sira']) == 2

    # 22 parity
    def test_add_and_assign_same_result(self, _mock_filom):
        def _setup(db_path: str, prefix: str) -> int:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is=f'{prefix}_done', suffix=f'{prefix}d')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            t2 = _seed_talep(con, yapilacak_is=f'{prefix}_mov', suffix=f'{prefix}m')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            return plan_id

        with _temp_atp_db() as db_path_a:
            _setup(db_path_a, 'a')
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r_add = add_job_to_plan_atomic(
                USER_ID,
                _acil_payload(firma='Parity A', client_submit_id='parity_add'),
            )
            sira_add = _item_sira(db_path_a, r_add['plan_is_id'])

        with _temp_atp_db() as db_path_b:
            _setup(db_path_b, 'b')
            con = _conn(db_path_b)
            acil_tid = _seed_talep(con, oncelik='ACIL', yapilacak_is='Parity B', suffix='pb')
            con.commit()
            con.close()
            from modules.planlama.arac_takip_repo import assign_to_plan
            assign_to_plan(USER_ID, acil_tid, PLAN_DATE, VEHICLE, PLAKA, None, None, None)
            con = _conn(db_path_b)
            row = con.execute(
                'SELECT sira FROM arac_gunluk_plan_is WHERE is_talebi_id=?', (acil_tid,),
            ).fetchone()
            con.close()
            assert int(row['sira']) == sira_add == 2

    # 23 consecutive ACIL
    def test_two_consecutive_acil(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Done', suffix='d')
            _seed_plan_item(con, plan_id, t1, 1, durum='TAMAMLANDI')
            t2 = _seed_talep(con, yapilacak_is='M', suffix='m')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r1 = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='acil1'))
            assert _item_sira(db_path, r1['plan_is_id']) == 2
            r2 = add_job_to_plan_atomic(
                USER_ID,
                _acil_payload(firma='Acil2', client_submit_id='acil2'),
            )
            assert _item_sira(db_path, r2['plan_is_id']) == 2
            assert _item_sira(db_path, r1['plan_is_id']) == 3
            assert _ordered_siras(db_path, plan_id) == [1, 2, 3, 4]

    # 24 policy loader unique ids
    def test_policy_loader_unique_task_ids(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            for i in range(1, 3):
                tid = _seed_talep(con, yapilacak_is=f'D{i}', suffix=str(i))
                _seed_plan_item(con, plan_id, tid, i)
            con.commit()
            con.close()
            from modules.planlama.arac_takip_repo import _load_plan_items_for_order_policy_conn, get_conn
            con = get_conn()
            con.row_factory = sqlite3.Row
            tasks = _load_plan_items_for_order_policy_conn(con, plan_id)
            con.close()
            ids = [t['plan_item_id'] for t in tasks]
            assert len(ids) == len(set(ids))

    # inactive IPTAL preserved
    def test_inactive_iptal_order_preserved(self, _mock_filom):
        with _temp_atp_db() as db_path:
            con = _conn(db_path)
            plan_id = _seed_plan(con)
            t1 = _seed_talep(con, yapilacak_is='Cancel', suffix='c')
            _seed_plan_item(con, plan_id, t1, 1, durum='IPTAL')
            t2 = _seed_talep(con, yapilacak_is='Active', suffix='a')
            _seed_plan_item(con, plan_id, t2, 2)
            con.commit()
            con.close()
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            result = add_job_to_plan_atomic(USER_ID, _acil_payload(client_submit_id='iptal'))
            assert _item_sira(db_path, result['plan_is_id']) == 2


def test_u1_policy_regression_54_pass():
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/planlama/test_arac_route_order_policy.py', '-q'],
        cwd=str(_APP_DIR.parent),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '54 passed' in proc.stdout

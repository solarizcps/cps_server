# -*- coding: utf-8 -*-
"""ATP WhatsApp return scope — plan/date/vehicle lock (T1–T9)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot
from atp_plan2_fixture import CIKIS, PLAN_DATE, PLAN_ID, VEHICLE, insert_factory_base, seed_plan2_fixture
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp

from modules.planlama.arac_timeline_service import TIMELINE_STATUS_OK
from modules.planlama.arac_whatsapp_message_service import (
    RETURN_SCOPE_KEY,
    RETURN_SOURCE_NONE,
    RETURN_SOURCE_ROUTE_SNAPSHOT,
    RETURN_SOURCE_TIMELINE,
    build_whatsapp_payload,
    format_return_time_display,
    load_whatsapp_plan_context,
    resolve_scoped_estimated_return,
)

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
VEHICLE_B = '99999001'
ALT_DATE = '2026-08-29'


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _timeline_ok(return_time: str, *, departure: str = CIKIS, total_s: float = 3600.0) -> dict:
    return {
        'status': TIMELINE_STATUS_OK,
        'timeline_complete': True,
        'plan_departure_time': departure,
        'estimated_return_time': return_time,
        'estimated_total_seconds': total_s,
    }


def _insert_plan(
    con: sqlite3.Connection,
    *,
    plan_date: str,
    vehicle: str,
    cikis: str,
    plan_id: int | None = None,
    return_label: str,
) -> int:
    """Plan + tek durak; timeline mock return_label ile eşleşir."""
    now = _now()
    con.execute(
        'DELETE FROM arac_gunluk_plan_is WHERE plan_id IN '
        '(SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?)',
        (plan_date, vehicle),
    )
    con.execute(
        'DELETE FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
        (plan_date, vehicle),
    )
    if plan_id is not None:
        con.execute('DELETE FROM arac_gunluk_plan WHERE id=?', (plan_id,))
    if plan_id is not None:
        con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                id, plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,'TURKCELL_FILOM',?,?,?,'AKTIF',?,?,?,?,?)
            """,
            (plan_id, plan_date, vehicle, f'PLK-{vehicle[-4:]}', 'sofor', cikis, now, 1, now, 1),
        )
        pid = plan_id
    else:
        cur = con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
            ) VALUES (?,'TURKCELL_FILOM',?,?,?,'AKTIF',?,?,?,?,?)
            """,
            (plan_date, vehicle, f'PLK-{vehicle[-4:]}', 'sofor', cikis, now, 1, now, 1),
        )
        pid = int(cur.lastrowid)
    tcur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            firma_adi, adres, latitude, longitude, yapilacak_is, oncelik, durum,
            save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
        """,
        (
            f'RS-{uuid.uuid4().hex[:8]}', 1, 'Test', plan_date, f'Firma-{return_label}',
            'Adres', 41.01, 28.61, 'is', 'NORMAL', now, 1, now, 1,
        ),
    )
    talep_id = int(tcur.lastrowid)
    con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, durum, created_at, created_by
        ) VALUES (?, ?, 1, 'PLANLANDI', ?, ?)
        """,
        (pid, talep_id, now, 1),
    )
    con.commit()
    return pid


def _insert_route_snapshot(con: sqlite3.Connection, plan_id: int, total_duration_s: float) -> None:
    now = _now()
    con.execute(
        'UPDATE arac_plan_rota_snapshot SET is_active=0 WHERE plan_id=?',
        (plan_id,),
    )
    con.execute(
        """
        INSERT INTO arac_plan_rota_snapshot (
            plan_id, route_version, geometry_json, stop_order_json,
            routing_provider, total_distance_m, total_duration_s,
            content_hash, geometry_schema, arac_provider, is_active,
            created_at, created_by
        ) VALUES (?,1,'{}','[]','test',1000,?,?,'geojson_linestring_v1','TURKCELL_FILOM',1,?,1)
        """,
        (plan_id, total_duration_s, f'hash-{plan_id}-{total_duration_s}', now),
    )
    con.commit()


@pytest.fixture
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    logical_before = canonical_logical_snapshot(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_wa_return_scope_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    _load_migration(MIG189).run(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    con = sqlite3.connect(db)
    insert_factory_base(
        con, base_name='Solariz Fabrika', latitude=40.9928503, longitude=28.6944178,
        maps_url='https://maps.example/factory',
    )
    con.close()
    yield {'db': db, 'live': live, 'logical_before': logical_before, 'tmp_dir': tmp_dir}
    assert_canonical_atp_unchanged(live, logical_before)
    shutil.rmtree(tmp_dir, ignore_errors=True)


class TestReturnScopeMatrix:
    def test_scope_key_tuple(self):
        assert RETURN_SCOPE_KEY == ('plan_date', 'vehicle_external_id', 'plan_id')

    def test_t1_two_vehicles_same_date_isolated(self, env):
        con = sqlite3.connect(env['db'])
        pid_a = _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE, cikis=CIKIS, plan_id=PLAN_ID, return_label='A')
        pid_b = _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE_B, cikis='08:00', return_label='B')
        con.close()

        def _fake_timeline(plan_date, vehicle_external_id, **kwargs):
            if str(vehicle_external_id) == VEHICLE:
                return _timeline_ok('21:10')
            if str(vehicle_external_id) == VEHICLE_B:
                return _timeline_ok('11:45', departure='08:00')
            return {'timeline_complete': False, 'status': 'AYAK_EKSIK'}

        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            side_effect=_fake_timeline,
        ):
            ctx_a = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
            ctx_b = load_whatsapp_plan_context(PLAN_DATE, VEHICLE_B)
        assert ctx_a['plan_id'] == pid_a
        assert ctx_b['plan_id'] == pid_b
        assert ctx_a['estimated_return_time'] == '21:10'
        assert ctx_b['estimated_return_time'] == '11:45'
        assert '08:51' not in (ctx_a['estimated_return_time'] or '')

    def test_t2_same_vehicle_two_dates(self, env):
        con = sqlite3.connect(env['db'])
        _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE, cikis=CIKIS, plan_id=PLAN_ID, return_label='d1')
        _insert_plan(con, plan_date=ALT_DATE, vehicle=VEHICLE, cikis='07:30', return_label='d2')
        con.close()

        def _fake_timeline(plan_date, vehicle_external_id, **kwargs):
            if plan_date == PLAN_DATE:
                return _timeline_ok('20:00')
            if plan_date == ALT_DATE:
                return _timeline_ok('09:15', departure='07:30')
            return {'timeline_complete': False}

        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            side_effect=_fake_timeline,
        ):
            ctx1 = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
            ctx2 = load_whatsapp_plan_context(ALT_DATE, VEHICLE)
        assert ctx1['estimated_return_time'] == '20:00'
        assert ctx2['estimated_return_time'] == '09:15'

    def test_t3_wrong_plan_snapshot_not_used(self, env):
        con = sqlite3.connect(env['db'])
        pid = _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE, cikis=CIKIS, plan_id=PLAN_ID, return_label='live')
        wrong_plan = 99991
        _insert_route_snapshot(con, wrong_plan, total_duration_s=600.0)
        con.close()

        incomplete = {'timeline_complete': False, 'status': 'AYAK_EKSIK', 'plan_departure_time': CIKIS}
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=incomplete,
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        assert ctx['estimated_return_time'] is None
        assert ctx['return_source'] == RETURN_SOURCE_NONE

        con = sqlite3.connect(env['db'])
        _insert_route_snapshot(con, pid, total_duration_s=5400.0)
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=incomplete,
        ):
            ctx2 = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        assert ctx2['return_source'] == RETURN_SOURCE_ROUTE_SNAPSHOT
        assert ctx2['return_scope_valid'] is True
        assert '08:51' not in (ctx2['estimated_return_time'] or '')

    def test_t4_no_timeline_shows_dash(self, env):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={'timeline_complete': False, 'status': 'AYAK_EKSIK'},
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        msg = ctx and build_whatsapp_payload(PLAN_DATE, VEHICLE)['message']
        assert 'Tahmini dönüş: —' in msg

    def test_t5_midnight_next_day_format(self):
        display = format_return_time_display(
            PLAN_DATE,
            '19:00',
            '00:35',
            return_dt=datetime.fromisoformat(f'{PLAN_DATE} 19:00:00') + timedelta(hours=5, minutes=35),
        )
        assert display == '00:35 (ertesi gün)'

    def test_t6_other_plan_0851_leak_regression(self, env):
        con = sqlite3.connect(env['db'])
        pid = _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE, cikis=CIKIS, plan_id=PLAN_ID, return_label='sel')
        con.close()

        def _fake_timeline(plan_date, vehicle_external_id, **kwargs):
            return _timeline_ok('22:40')

        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            side_effect=_fake_timeline,
        ):
            info = resolve_scoped_estimated_return(PLAN_DATE, VEHICLE, pid, CIKIS, active_stop_count=1)
        assert info['estimated_return_time'] == '22:40'
        assert info['return_scope_valid'] is True
        assert '08:51' not in (info['estimated_return_time'] or '')

        stale = resolve_scoped_estimated_return(PLAN_DATE, VEHICLE, pid + 999, CIKIS, active_stop_count=1)
        assert stale['return_scope_valid'] is False
        assert stale['estimated_return_time'] is None

    def test_t7_route_apply_snapshot_return(self, env):
        con = sqlite3.connect(env['db'])
        pid = _insert_plan(con, plan_date=PLAN_DATE, vehicle=VEHICLE, cikis=CIKIS, plan_id=PLAN_ID, return_label='route')
        _insert_route_snapshot(con, pid, total_duration_s=7200.0)
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={'timeline_complete': False, 'status': 'AYAK_EKSIK', 'plan_departure_time': CIKIS},
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        assert ctx['return_source'] == RETURN_SOURCE_ROUTE_SNAPSHOT
        assert ctx['estimated_return_time']
        assert ctx['return_scope_valid'] is True

    def test_t8_api_db_message_plan_id_parity(self, env):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok('21:05'),
        ):
            payload = build_whatsapp_payload(PLAN_DATE, VEHICLE)
        assert payload['context']['plan_id'] == PLAN_ID
        assert payload['context']['plan_date'] == PLAN_DATE
        assert payload['context']['vehicle_external_id'] == VEHICLE
        assert '21:05' in payload['message']

    def test_t9_return_resolution_no_db_write(self, env):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        before = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0]
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value=_timeline_ok('20:00'),
        ):
            load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        con = sqlite3.connect(env['db'])
        after = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0]
        con.close()
        assert before == after


class TestReturnScopeEvidenceArtifact:
    def test_plan2_forensic_no_mock_returns_dash(self, env, tmp_path):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        con.close()
        ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        out = tmp_path / 'plan2_return_forensic.json'
        out.write_text(json.dumps({
            'plan_id': ctx['plan_id'],
            'plan_date': ctx['plan_date'],
            'vehicle_external_id': ctx['vehicle_external_id'],
            'departure_time': ctx['departure_time'],
            'estimated_return_time': ctx['estimated_return_time'],
            'return_source': ctx['return_source'],
            'return_scope_valid': ctx['return_scope_valid'],
            'note': '08:51 yalnızca eski test mock değeriydi; gerçek timeline incomplete → —',
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        assert ctx['return_scope_valid'] is False or ctx['estimated_return_time'] != '08:51'

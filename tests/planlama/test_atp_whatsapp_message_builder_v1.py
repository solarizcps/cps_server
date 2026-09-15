# -*- coding: utf-8 -*-
"""ATP WhatsApp message builder V2 — temp DB, route apply parity, encoding."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot
from atp_plan2_fixture import CIKIS, PLAN_DATE, PLAKA, SOFOR, VEHICLE, insert_factory_base, seed_plan2_fixture
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp

from modules.planlama.arac_whatsapp_message_service import (
    build_whatsapp_plan_message_v2,
    build_whatsapp_payload,
    filter_active_stops,
    format_coordinate,
    load_whatsapp_plan_context,
    maps_link_from_coordinates,
    resolve_stop_eta,
    resolve_stop_location_link,
    sort_stops_for_whatsapp,
)
from modules.planlama.arac_plan_service import whatsapp_web_url

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
MIG189 = MIGS / '189_planlama_arac_takip_rol32_yetki.py'
FACTORY_NAME = 'Solariz Fabrika'
FACTORY_LAT = 40.9928503
FACTORY_LNG = 28.6944178


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _seed_three_stop_plan(con: sqlite3.Connection) -> dict[str, str | int]:
    now = _now()
    con.execute(
        'DELETE FROM arac_gunluk_plan_is WHERE plan_id IN '
        '(SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?)',
        (PLAN_DATE, VEHICLE),
    )
    con.execute(
        'DELETE FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
        (PLAN_DATE, VEHICLE),
    )
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,?,'AKTIF',?,?,?,?,?)
        """,
        (PLAN_DATE, VEHICLE, PLAKA, SOFOR, CIKIS, now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    names = ('Alpha Co', 'Beta Co', 'Gamma Co')
    task_ids: dict[str, str] = {}
    rows = [
        (41.01, 28.61, '07:17', 'PLANLANDI'),
        (41.02, 28.62, '07:53', 'PLANLANDI'),
        (41.03, 28.63, '08:13', 'PLANLANDI'),
    ]
    for idx, (name, (lat, lng, eta, status)) in enumerate(zip(names, rows), start=1):
        tcur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, latitude, longitude, yapilacak_is, oncelik, durum,
                save_to_master, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
            """,
            (
                f'WA-{uuid.uuid4().hex[:10]}-{idx}', 1, 'Test', PLAN_DATE, name, 'Adres',
                lat, lng, f'Is {idx}', 'NORMAL', now, 1, now, 1,
            ),
        )
        talep_id = int(tcur.lastrowid)
        picur = con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, tahmini_varis_saati, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, talep_id, idx, status, eta, now, 1),
        )
        task_ids[name] = f'pi-{int(picur.lastrowid)}'
    con.commit()
    return {'plan_id': plan_id, **task_ids}


@pytest.fixture
def env():
    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')
    logical_before = canonical_logical_snapshot(live)
    tmp_dir = tempfile.mkdtemp(prefix='atp_whatsapp_builder_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    _load_migration(MIG189).run(db)
    os.environ['CPS_MOCK_DB_PATH'] = db
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    yield {'db': db, 'live': live, 'logical_before': logical_before, 'tmp_dir': tmp_dir}
    assert_canonical_atp_unchanged(live, logical_before)
    shutil.rmtree(tmp_dir, ignore_errors=True)


class TestWhatsAppPureHelpers:
    def test_maps_link_from_coordinates(self):
        link = maps_link_from_coordinates(41.0473976, 28.6385286)
        assert link == 'https://www.google.com/maps?q=41.047398,28.638529'

    def test_resolve_stop_location_link_prefers_coords(self):
        task = {'latitude': 41.0, 'longitude': 29.0, 'location_url': 'https://example.com/old'}
        assert 'google.com/maps?q=41,29' in resolve_stop_location_link(task)

    def test_resolve_stop_location_link_fallback_url(self):
        task = {'location_url': 'https://maps.app.goo.gl/abc'}
        assert resolve_stop_location_link(task) == 'https://maps.app.goo.gl/abc'

    def test_resolve_stop_location_missing(self):
        assert resolve_stop_location_link({}) == 'Konum tanımlanmamış'

    def test_eta_priority(self):
        task = {
            'planned_time': '09:00',
            'istenen_varis_saati': '08:30',
            'eta_time': '08:45',
            'tahmini_varis_saati': '08:17',
        }
        assert resolve_stop_eta(task) == '08:17'

    def test_inactive_filter(self):
        tasks = [
            {'id': '1', 'status': 'PLANLANDI', 'order_no': 1},
            {'id': '2', 'status': 'IPTAL', 'order_no': 2},
            {'id': '3', 'status': 'ERTELENDI', 'order_no': 3},
        ]
        assert len(filter_active_stops(tasks)) == 1

    def test_sort_uses_display_order_no(self):
        tasks = [
            {'id': 'b', 'status': 'PLANLANDI', 'order_no': 2, 'display_order_no': 2},
            {'id': 'a', 'status': 'PLANLANDI', 'order_no': 1, 'display_order_no': 1},
        ]
        ordered = sort_stops_for_whatsapp(tasks)
        assert [t['id'] for t in ordered] == ['a', 'b']

    def test_turkish_and_url_encode_parity(self):
        msg = 'GÜNLÜK ARAÇ PROGRAMI\nŞahin Taban — İş: mal alınacak'
        url = whatsapp_web_url(msg)
        decoded = urllib.parse.unquote(url.split('text=')[1])
        assert decoded == msg

    def test_no_double_encoding(self):
        msg = 'Test mesaj'
        url = whatsapp_web_url(msg)
        assert url.count('%25') == 0


class TestWhatsAppMessageBuilderIntegration:
    def test_plan2_fixture_message_fields(self, env):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        insert_factory_base(
            con, base_name=FACTORY_NAME, latitude=FACTORY_LAT, longitude=FACTORY_LNG,
            maps_url='https://maps.example/factory',
        )
        con.commit()
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={
                'estimated_return_time': '08:51',
                'timeline_complete': True,
                'status': 'HESAPLANDI',
                'plan_departure_time': CIKIS,
                'estimated_total_seconds': 3600.0,
            },
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        assert ctx is not None
        assert ctx['return_scope_valid'] is True
        assert ctx['return_source'] == 'timeline'
        msg = build_whatsapp_plan_message_v2(ctx)
        assert PLAKA in msg
        assert SOFOR in msg
        assert CIKIS in msg
        assert FACTORY_NAME in msg
        assert '08:51' in msg

    def test_route_apply_reorder_parity(self, env):
        con = sqlite3.connect(env['db'])
        ids = _seed_three_stop_plan(con)
        insert_factory_base(
            con, base_name=FACTORY_NAME, latitude=FACTORY_LAT, longitude=FACTORY_LNG,
            maps_url='https://maps.example/factory',
        )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import reorder_plan_items_bulk
        alpha, beta, gamma = 'Alpha Co', 'Beta Co', 'Gamma Co'
        reorder_plan_items_bulk(1, PLAN_DATE, VEHICLE, [ids[gamma], ids[alpha], ids[beta]])
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={
                'estimated_return_time': '09:30',
                'timeline_complete': True,
                'status': 'HESAPLANDI',
                'plan_departure_time': CIKIS,
                'estimated_total_seconds': 3600.0,
            },
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        msg = build_whatsapp_plan_message_v2(ctx)
        assert msg.find(gamma) < msg.find(alpha) < msg.find(beta)
        assert '07:17' in msg and '07:53' in msg and '08:13' in msg

    def test_cancelled_stop_excluded(self, env):
        con = sqlite3.connect(env['db'])
        ids = _seed_three_stop_plan(con)
        con.execute(
            """
            UPDATE arac_gunluk_plan_is SET durum='IPTAL'
            WHERE id=(SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? AND sira=2)
            """,
            (ids['plan_id'],),
        )
        insert_factory_base(
            con, base_name=FACTORY_NAME, latitude=FACTORY_LAT, longitude=FACTORY_LNG,
            maps_url='https://maps.example/factory',
        )
        con.commit()
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={'estimated_return_time': None},
        ):
            ctx = load_whatsapp_plan_context(PLAN_DATE, VEHICLE)
        msg = build_whatsapp_plan_message_v2(ctx)
        assert 'Beta Co' not in msg
        assert 'Alpha Co' in msg and 'Gamma Co' in msg

    def test_payload_roundtrip(self, env):
        con = sqlite3.connect(env['db'])
        seed_plan2_fixture(con, with_coords=True)
        insert_factory_base(
            con, base_name=FACTORY_NAME, latitude=FACTORY_LAT, longitude=FACTORY_LNG,
            maps_url='https://maps.example/factory',
        )
        con.commit()
        con.close()
        with patch(
            'modules.planlama.arac_timeline_service.build_timeline_for_plan',
            return_value={
                'estimated_return_time': '20:15',
                'timeline_complete': True,
                'status': 'HESAPLANDI',
                'plan_departure_time': CIKIS,
                'estimated_total_seconds': 4500.0,
            },
        ):
            payload = build_whatsapp_payload(PLAN_DATE, VEHICLE)
        assert payload and payload['ok']
        assert payload['whatsapp_url'].startswith('https://wa.me/?text=')
        assert format_coordinate(FACTORY_LAT) in urllib.parse.unquote(payload['whatsapp_url'])

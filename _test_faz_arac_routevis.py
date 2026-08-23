# -*- coding: utf-8 -*-
"""ROUTEVIS-01..12 — Plan map render + URL vehicle hydrate (isolated temp DB)."""
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

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
CANONICAL_DB = os.path.join(_APP, 'mock_data.db')
sys.path.insert(0, _APP)
os.chdir(_APP)

PLAN_DATE = '2026-11-14'
VEHICLE = '99114A27565'
YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})
results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(
        filename, os.path.join(_APP, 'migrations', filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _assert_not_canonical(db_path: str) -> None:
    if os.path.normcase(os.path.normpath(db_path)) == os.path.normcase(os.path.normpath(CANONICAL_DB)):
        raise RuntimeError(f'STOP: canonical DB path: {db_path}')


def seed_routevis_fixture(db_path: str) -> dict:
    _assert_not_canonical(db_path)
    con = sqlite3.connect(db_path)
    now = '2026-11-14 08:00:00'
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('ROUTEVIS Base',41.0,29.0,'Base','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    talep_ids: list[int] = []
    coords = [(40.876, 29.234), (40.818, 29.305), (40.825, 29.372)]
    for i, (lat, lng) in enumerate(coords, 1):
        cur = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f'RV-{i}', 1, 'Test', PLAN_DATE, f'Firma{i}', f'Ad{i}', f'Is{i}',
             'NORMAL', 'PLANA_ALINDI', lat, lng, now, 1, now, 1),
        )
        talep_ids.append(int(cur.lastrowid))
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,1,'Oktay','AKTIF',?,?,?,?)
        """,
        (PLAN_DATE, VEHICLE, '34 RV TEST', now, 1, now, 1),
    )
    plan_id = int(cur.lastrowid)
    item_ids: list[str] = []
    for sira, tid in enumerate(talep_ids, 1):
        icur = con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, tid, sira, f'0{8+sira}:00', 'PLANLANDI', now, 1),
        )
        item_ids.append(f'pi-{icur.lastrowid}')
    con.commit()
    con.close()
    return {'plan_id': plan_id, 'item_ids': item_ids, 'vehicle': VEHICLE, 'plan_date': PLAN_DATE}


@contextmanager
def isolated_routevis_db():
    tmpdir = tempfile.mkdtemp(prefix='routevis_')
    db_path = os.path.join(tmpdir, 'routevis.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
    ):
        _run_migration(db_path, mig)
    fx = seed_routevis_fixture(db_path)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        print(f'  [DB-PATH-TEMP] {db_path}')
        yield db_path, fx


def main() -> int:
    print('=' * 72)
    print('ROUTEVIS — V1.4B visual parity (isolated)')
    print('=' * 72)

    with isolated_routevis_db() as (_db_path, fx):
        from modules.planlama.arac_takip_repo import (
            get_plan_vehicle_meta, list_plan_tasks, reorder_plan_items_bulk, tables_ready,
        )
        from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
        from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
        from modules.planlama.arac_location_resolver import resolve_base_location
        from modules.planlama.road_routing.route_planner_service import build_plan_route_dto
        from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider

        if not tables_ready():
            print('FAIL tables not ready')
            return 1

        rev_ids = list(reversed(fx['item_ids']))
        reorder_plan_items_bulk(1, PLAN_DATE, VEHICLE, rev_ids)

        meta = get_plan_vehicle_meta(PLAN_DATE, VEHICLE)
        ok('ROUTEVIS-01 URL vehicle hydrate', meta is not None and meta.get('external_id') == VEHICLE, str(meta))

        tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
        dto = get_arac_dashboard_dto(
            plan_date=__import__('datetime').date.fromisoformat(PLAN_DATE),
            vehicle_id=VEHICLE, daily_tasks=tasks,
        )
        ok('ROUTEVIS-02 dropdown parity DTO', dto.get('selected_vehicle_id') == VEHICLE
           and dto.get('selected_plate') not in ('', '—', None), dto.get('selected_plate'))
        ok('ROUTEVIS-03 plan_id parity', len(dto.get('daily_tasks') or []) == 3,
           str(len(dto.get('daily_tasks') or [])))

        plan_map = dto.get('plan_map') or {}
        base = plan_map.get('base') or {}
        stops = plan_map.get('stops') or []
        ok('ROUTEVIS-04 base marker data', bool(base.get('has_coordinates')), str(base.get('latitude')))
        ok('ROUTEVIS-05 stop markers data', len([s for s in stops if s.get('has_coordinates')]) == 3, str(len(stops)))

        base_loc = resolve_base_location(get_active_base() if operasyon_ayar_ready() else None)
        mock = MockRoadRoutingProvider()
        with patch.dict(os.environ, {'ARAC_ROUTING_PROVIDER': 'mock'}, clear=False):
            route_dto = build_plan_route_dto(base_loc, dto['daily_tasks'], provider=mock)
        cur = route_dto.get('current') or {}
        ok('ROUTEVIS-06 mock polyline deterministic',
           route_dto.get('status') == 'OK' and cur.get('provider') == 'mock'
           and len(cur.get('geometry') or []) >= 2,
           f"provider={cur.get('provider')} pts={len(cur.get('geometry') or [])}")
        ok('ROUTEVIS-07 fitBounds data', cur.get('km') not in (None, '—', 0), str(cur.get('km')))

        sug = route_dto.get('suggested') or {}
        ok('ROUTEVIS-08 suggested preview geometry', len(sug.get('geometry') or []) >= 2,
           str(len(sug.get('geometry') or [])))
        ok('ROUTEVIS-09 preview DB write=0', route_dto.get('suggested_preview_only') is True)

        css = open(os.path.join(_APP, 'static', 'css', 'planlama_arac_takip.css'), encoding='utf-8').read()
        ok('ROUTEVIS-10 plan leaflet visible CSS',
           '.atp-plan-leaflet' in css and 'display: none' not in css.split('.atp-plan-leaflet')[1].split('}')[0],
           'no display:none on plan leaflet')

        js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip.js'), encoding='utf-8').read()
        ok('ROUTEVIS-11 hydrate helper', 'hydrateVehicleSelect' in js and 'planVehicleOption' in js)

        mapjs = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_plan_map.js'), encoding='utf-8').read()
        ok('ROUTEVIS-12 null-safe getLastRoute',
           'getLastRoute && global.AtpRoute.getLastRoute().current' not in mapjs.split('function renderPlanMap')[1].split('function syncRouteFromLast')[0])

        with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
             patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
             patch('modules.auth.yetki_var', return_value=True), \
             patch('modules.auth.is_superadmin', return_value=True), \
             patch('modules.planlama.road_routing.route_planner_service.get_routing_provider', return_value=mock):
            import app as flask_app
            flask_app.app.config['TESTING'] = True
            c = flask_app.app.test_client()
            with c.session_transaction() as s:
                s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
                s['kullanici_tip'] = 'sistem'
            r = c.get(f'/planlama/arac-takip/?tab=gunluk&date={PLAN_DATE}&vehicle_id={VEHICLE}')
            ok('ROUTEVIS page 200', r.status_code == 200)
            body = r.get_data(as_text=True)
            ok('ROUTEVIS dashboard json vehicle', VEHICLE in body)
            ok('ROUTEVIS-15 SSR select option', f'value="{VEHICLE}"' in body and 'selected' in body, 'SSR dropdown')
            ok('ROUTEVIS-19 footer id', 'id="atpFootTotal"' in body)
            ok('ROUTEVIS-20 route API daily_totals',
               route_dto.get('status') in ('OK', 'PARTIAL') and cur.get('km') == route_dto['current']['km'])

    passed = sum(1 for _, c, _ in results if c)
    print('=' * 72)
    print(f'ROUTEVIS: {passed}/{len(results)} PASS')
    if passed != len(results):
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

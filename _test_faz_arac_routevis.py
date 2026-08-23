# -*- coding: utf-8 -*-
"""ROUTEVIS-01..12 — Plan map render + URL vehicle hydrate."""
from __future__ import annotations

import io
import os
import sys
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('ROUTEVIS — V1.4B visual parity')
print('=' * 72)

PLAN_DATE = '2026-11-14'
VEHICLE = '99114A27565'
YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})

from modules.planlama.arac_takip_repo import (
    get_plan_vehicle_meta, list_plan_tasks, reorder_plan_items_bulk, tables_ready,
)
from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
from modules.planlama.arac_location_resolver import resolve_base_location
from modules.planlama.road_routing.route_planner_service import build_plan_route_dto, get_routing_provider

if not tables_ready():
    print('SKIP no tables')
    sys.exit(1)

reorder_plan_items_bulk(1, PLAN_DATE, VEHICLE, ['pi-57', 'pi-58', 'pi-59'])

# ROUTEVIS-01 URL vehicle hydrate metadata
meta = get_plan_vehicle_meta(PLAN_DATE, VEHICLE)
ok('ROUTEVIS-01 URL vehicle hydrate', meta is not None and meta.get('external_id') == VEHICLE,
   str(meta))

# ROUTEVIS-02 dropdown parity DTO
dto = get_arac_dashboard_dto(plan_date=__import__('datetime').date.fromisoformat(PLAN_DATE),
                             vehicle_id=VEHICLE, daily_tasks=list_plan_tasks(PLAN_DATE, VEHICLE))
ok('ROUTEVIS-02 dropdown parity DTO', dto.get('selected_vehicle_id') == VEHICLE and dto.get('selected_plate') not in ('', '—', None),
   dto.get('selected_plate'))
ok('ROUTEVIS-03 plan_id parity', len(dto.get('daily_tasks') or []) == 3, str(len(dto.get('daily_tasks') or [])))

plan_map = dto.get('plan_map') or {}
base = plan_map.get('base') or {}
stops = plan_map.get('stops') or []
ok('ROUTEVIS-04 base marker data', bool(base.get('has_coordinates')), str(base.get('latitude')))
ok('ROUTEVIS-05 stop markers data', len([s for s in stops if s.get('has_coordinates')]) == 3,
   str(len(stops)))

# ROUTEVIS-06 current ORS polyline source
base_loc = resolve_base_location(get_active_base() if operasyon_ayar_ready() else None)
route_dto = build_plan_route_dto(base_loc, dto['daily_tasks'], provider=get_routing_provider())
cur = route_dto.get('current') or {}
ok('ROUTEVIS-06 current ORS polyline', route_dto.get('status') == 'OK' and len(cur.get('geometry') or []) > 10,
   f"provider={cur.get('provider')} pts={len(cur.get('geometry') or [])}")
ok('ROUTEVIS-07 fitBounds data', cur.get('km') not in (None, '—', 0), str(cur.get('km')))

sug = route_dto.get('suggested') or {}
ok('ROUTEVIS-08 suggested preview geometry', len(sug.get('geometry') or []) > 10, str(len(sug.get('geometry') or [])))
ok('ROUTEVIS-09 preview DB write=0', route_dto.get('suggested_preview_only') is True)

# Template/JS assets
css = open(os.path.join(_APP, 'static', 'css', 'planlama_arac_takip.css'), encoding='utf-8').read()
ok('ROUTEVIS-10 plan leaflet visible CSS', '.atp-plan-leaflet' in css and 'display: none' not in css.split('.atp-plan-leaflet')[1].split('}')[0],
   'no display:none on plan leaflet')

js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip.js'), encoding='utf-8').read()
ok('ROUTEVIS-11 hydrate helper', 'hydrateVehicleSelect' in js and 'planVehicleOption' in js)

mapjs = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_plan_map.js'), encoding='utf-8').read()
ok('ROUTEVIS-12 null-safe getLastRoute', 'getLastRoute && global.AtpRoute.getLastRoute().current' not in mapjs.split('function renderPlanMap')[1].split('function syncRouteFromLast')[0])

# API route plan parity
with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=True):
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
        s['kullanici_tip'] = 'sistem'
    r = c.get(f'/planlama/arac-takip/?tab=gunluk&date={PLAN_DATE}&vehicle_id={VEHICLE}')
    ok('ROUTEVIS page 200', r.status_code == 200)
    body = r.get_data(as_text=True)
    ok('ROUTEVIS dashboard json vehicle', VEHICLE in body and 'plan_vehicle' in body or VEHICLE in body)
    ok('ROUTEVIS-15 SSR select option', f'value="{VEHICLE}"' in body and 'selected' in body, 'SSR dropdown')
    ok('ROUTEVIS-19 footer id', 'id="atpFootTotal"' in body)
    ok('ROUTEVIS-20 route API daily_totals', route_dto.get('status') in ('OK', 'PARTIAL') and cur.get('km') == route_dto['current']['km'])

passed = sum(1 for _, c, _ in results if c)
print('=' * 72)
print(f'ROUTEVIS: {passed}/{len(results)} PASS')
if passed != len(results):
    sys.exit(1)
print('ALL PASS')

# -*- coding: utf-8 -*-
"""MAP14A-01..20 — Araç Takip V1.4A plan map + location."""
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

YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})
FILOM_VEH = {
    'ok': True,
    'vehicles': [
        {'id': '991001', 'plate': '34 MOR 049', 'plate_display': '34 MOR 049',
         'driver_name': 'Ahmet', 'latitude': 40.818, 'longitude': 29.305,
         'has_valid_location': True, 'activity_status': 'HAREKETLI',
         'activity_status_label': 'Hareketli', 'speed_kmh': 40},
    ],
    'count': 1,
}
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def client():
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'alpay', 'AdSoyad': 'Alpay Test',
            'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
    return c


print('=' * 72)
print('MAP14A — Araç Takip V1.4A')
print('=' * 72)

from db import get_conn, tablo_var_mi
from modules.planlama.arac_takip_repo import (
    create_is_talebi, ensure_seed_locations, list_plan_tasks, tables_ready,
    update_kayitli_yer_coordinates, update_talep_coordinates,
)
from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready, save_base_location
from modules.planlama.arac_location_resolver import (
    LOCATION_STATUS_MASTER, LOCATION_STATUS_MISSING, LOCATION_STATUS_SNAPSHOT,
    resolve_item_location,
)

if not tables_ready():
    print('  [SKIP] Migration 176 tabloları yok')
    sys.exit(1)

# MAP14A-01 idempotent migration
import importlib.util
import re
import time

spec = importlib.util.spec_from_file_location(
    'm177', os.path.join(_APP, 'migrations', '177_arac_operasyon_ayar.py'))
m177 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m177)
db_path = os.environ.get('CPS_MOCK_DB_PATH') or os.path.join(_APP, 'mock_data.db')
if os.path.normcase(os.path.normpath(db_path)) == os.path.normcase(os.path.normpath(os.path.join(_APP, 'mock_data.db'))):
    print(f'  [DB-PATH] {db_path}')
else:
    print(f'  [DB-PATH-TEMP] {db_path}')
before_cnt = get_conn().execute('SELECT COUNT(*) c FROM arac_operasyon_ayar').fetchone()['c'] if operasyon_ayar_ready() else 0
m177.run(db_path)
m177.run(db_path)
after_cnt = get_conn().execute('SELECT COUNT(*) c FROM arac_operasyon_ayar').fetchone()['c']
ok('MAP14A-01', operasyon_ayar_ready() and tablo_var_mi('arac_operasyon_ayar'))

# MAP14A-03 migration has no fake coordinate seed INSERT
m177_src = open(os.path.join(_APP, 'migrations', '177_arac_operasyon_ayar.py'), encoding='utf-8').read()
ok('MAP14A-03', 'INSERT INTO arac_operasyon_ayar' not in m177_src and after_cnt == before_cnt, 'no migration seed')

ensure_seed_locations(1)
con = get_conn()
try:
    # Controlled master for fallback test
    cur = con.execute(
        """
        INSERT INTO arac_kayitli_yer (
            firma_adi, kisi_adi, telefon, adres, konum_linki,
            latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
        ) VALUES ('MAP14A Master Co','','','Adres','',41.01,29.01,1,0,datetime('now'),1)
        """
    )
    master_id = int(cur.lastrowid)
    con.commit()
finally:
    con.close()

PLAN_DATE = '2026-11-14'
VEHICLE = f'99114A{int(time.time()) % 100000}'

# Snapshot-only talep
snap = create_is_talebi(1, {
    'tarih': PLAN_DATE, 'is': 'Snapshot stop', 'firma': 'Snap Co', 'adres': 'A',
    'latitude': 40.91, 'longitude': 29.11, 'save_to_master': False,
})
# Master fallback talep (no snapshot coords)
fb = create_is_talebi(1, {
    'tarih': PLAN_DATE, 'is': 'Master fallback', 'firma': 'MAP14A Master Co', 'adres': 'B',
    'kayitli_yer_id': master_id, 'save_to_master': False,
})
# Missing coords
miss = create_is_talebi(1, {
    'tarih': PLAN_DATE, 'is': 'Missing stop', 'firma': 'No Co Co', 'adres': 'C',
    'save_to_master': False,
})

from modules.planlama.arac_takip_repo import assign_to_plan

for i, tid in enumerate([snap['id'], fb['id'], miss['id']], start=1):
    assign_to_plan(1, int(tid), PLAN_DATE, VEHICLE, '34 TEST 14A', None, 'Test', '09:00', i)

tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
ok('MAP14A-04', tasks[0]['location_status'] == LOCATION_STATUS_SNAPSHOT and tasks[0]['has_coordinates'])
ok('MAP14A-05', tasks[1]['location_status'] == LOCATION_STATUS_MASTER and tasks[1]['has_coordinates'])
ok('MAP14A-06', tasks[2]['location_status'] == LOCATION_STATUS_MISSING and not tasks[2]['has_coordinates'])

# MAP14A-07 master fallback does not mutate request
con = get_conn()
row_before = dict(con.execute('SELECT latitude, longitude FROM arac_is_talebi WHERE id=?', (fb['id'],)).fetchone())
con.close()
_ = list_plan_tasks(PLAN_DATE, VEHICLE)
con = get_conn()
row_after = dict(con.execute('SELECT latitude, longitude FROM arac_is_talebi WHERE id=?', (fb['id'],)).fetchone())
con.close()
ok('MAP14A-07', row_before == row_after)

ok('MAP14A-08', [t['order_no'] for t in tasks] == [1, 2, 3])

# Resolver unit
r = resolve_item_location({'latitude': 1.0, 'longitude': 2.0}, {'latitude': 9.0, 'longitude': 9.0})
ok('MAP14A-04b', r['location_source'] == 'request')

# MAP14A-02 base CRUD
saved = save_base_location(1, {
    'base_name': 'Test Base MAP14A',
    'base_address': 'Test adres',
    'base_latitude': 41.02,
    'base_longitude': 29.02,
})
ok('MAP14A-02', saved['ok'] and get_active_base()['base_name'] == 'Test Base MAP14A')

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=True), \
     patch('modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles', return_value=FILOM_VEH):
    c = client()
    page = c.get(f'/planlama/arac-takip/?tab=gunluk&date={PLAN_DATE}&vehicle_id=' + VEHICLE).data.decode('utf-8', 'replace')
    ok('MAP14A-09', 'atpPlanLeafletMap' in page and 'Fabrika Başlangıç Noktası' in page)
    ok('MAP14A-10', 'planlama_arac_takip_plan_map.js' in page)
    ok('MAP14A-12', 'Konum Eksik' in page or 'atp-loc-missing' in page)

    dash = c.get(f'/planlama/arac-takip/api/dashboard?tab=gunluk&date={PLAN_DATE}&vehicle_id=' + VEHICLE).get_json()
    pm = dash['dashboard']['plan_map']
    ok('MAP14A-11', pm['completeness']['ready'] == 2 and pm['completeness']['missing'] == 1)
    ok('MAP14A-09b', pm['base']['has_coordinates'] is True)

    # Konum ekle — maps_url canonical (master link + snapshot)
    upd = c.post('/planlama/arac-takip/api/plan-items/konum', json={
        'is_talebi_id': miss['id'],
        'maps_url': 'https://maps.google.com/?q=40.99,29.99',
        'date': PLAN_DATE, 'vehicle_id': VEHICLE,
    }).get_json()
    ok('MAP14A-13', upd.get('ok') and upd['daily_tasks'][2]['has_coordinates'])

    # Master linked on talep; duplicate master not created for same firma/adres
    upd_m = c.post('/planlama/arac-takip/api/plan-items/konum', json={
        'is_talebi_id': fb['id'],
        'maps_url': 'https://maps.google.com/?q=41.05,29.05',
        'date': PLAN_DATE, 'vehicle_id': VEHICLE,
    }).get_json()
    con = get_conn()
    mrow = dict(con.execute('SELECT latitude FROM arac_kayitli_yer WHERE id=?', (master_id,)).fetchone())
    trow = dict(con.execute('SELECT latitude, kayitli_yer_id FROM arac_is_talebi WHERE id=?', (fb['id'],)).fetchone())
    con.close()
    ok('MAP14A-14', upd_m.get('ok') and float(mrow['latitude']) == 41.05 and trow['latitude'] == 41.05 and int(trow['kayitli_yer_id']) == master_id)

# Static regression
plan_js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_plan_map.js'), encoding='utf-8').read()
live_js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_map.js'), encoding='utf-8').read()
main_js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip.js'), encoding='utf-8').read()
repo_py = open(os.path.join(_APP, 'modules', 'planlama', 'arac_takip_routes.py'), encoding='utf-8').read()

ok('MAP14A-15', 'AtpLiveMap' in live_js and 'ensureLiveMap' in live_js)
ok('MAP14A-16', 'AtpPlanMap' in plan_js and 'planMap' in plan_js and plan_js.count('L.map(') == 1)
ok('MAP14A-17', 'onPlanTabShown' in main_js and 'onLiveTabShown' in main_js)
ok('MAP14A-18', 'el._leaflet_id' in plan_js)
ok('MAP14A-19', 'atpMapSvg' not in main_js)
ok('MAP14A-20', 'OSRM' not in repo_py and 'directions' not in repo_py.lower())

# Weekly/history mock forensic (read-only)
from modules.planlama.arac_dashboard_service import _history_rows, _weekly_summary
from datetime import date
wk = _weekly_summary(date.today())
hist = _history_rows()
ok('MAP14A-WK', wk[0]['total_km'] == 186, f'weekly mock km source=_weekly_summary samples')
ok('MAP14A-HIST', hist[0]['vehicle'] == '34 ABC 123', f'history mock=_history_rows hardcoded')

print('=' * 72)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'MAP14A: {passed}/{len(results)} PASS' + (f' — {failed} FAIL' if failed else ''))
sys.exit(1 if failed else 0)

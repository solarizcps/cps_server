# -*- coding: utf-8 -*-
"""REQPOOL-01..18 — Araç Takip V1.3 canonical akış."""
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
YK_READONLY = frozenset({'planlama:can_view'})
MOCK_USERS = [
    {'id': 1, 'display_name': 'Alpay Test', 'kullanici_adi': 'alpay'},
    {'id': 42, 'display_name': 'Altan TERZİ', 'kullanici_adi': 'altan'},
]
FILOM_VEH = {
    'ok': True,
    'vehicles': [
        {'id': '991001', 'plate': '34 MOR 049', 'plate_display': '34 MOR 049', 'driver_name': 'Ahmet'},
        {'id': '991002', 'plate': '34 GFK 183', 'plate_display': '34 GFK 183', 'driver_name': 'Mehmet'},
    ],
    'count': 2,
}
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def client(perms=YK):
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
print('REQPOOL — Araç Takip V1.3')
print('=' * 72)

from modules.planlama.arac_takip_repo import tables_ready, ensure_seed_locations
if not tables_ready():
    print('  [SKIP] Migration 176 tabloları yok — önce migration uygulayın')
    sys.exit(1)

ensure_seed_locations(1)

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=True), \
     patch('modules.planlama.arac_request_user_service.search_cps_users', return_value=MOCK_USERS), \
     patch('modules.planlama.arac_request_user_service.get_cps_user_by_id', side_effect=lambda uid: next((u for u in MOCK_USERS if u['id']==int(uid)), None)), \
     patch('modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles', return_value=FILOM_VEH):
    c = client()

    req1 = c.post('/planlama/arac-takip/api/request', json={
        'tarih': '2026-08-22', 'istenen_saat': '', 'is': 'Evrak teslim',
        'oncelik': 'YUKSEK', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
        'firma': 'AVEL Avrupa Elektrik', 'adres': 'Tuzla', 'telefon': '0532 111 2233',
        'save_to_master': False, 'latitude': 40.81, 'longitude': 29.30,
    }).get_json()
    ok('REQPOOL-01 own BEKLIYOR', req1.get('ok') and req1['request'].get('durum') == 'BEKLIYOR')
    ok('REQPOOL-03 nullable saat', req1['request'].get('istenen_saat') in (None, ''))
    tid1 = req1['request']['id']

    req2 = c.post('/planlama/arac-takip/api/request', json={
        'tarih': '2026-08-22', 'is': 'Başka user', 'oncelik': 'NORMAL',
        'talep_eden_user_id': 42, 'talep_eden_adi': 'Altan TERZİ',
        'firma': 'AVEL Avrupa Elektrik', 'adres': 'Tuzla', 'telefon': '0532 111 2233',
        'save_to_master': False,
    }).get_json()
    ok('REQPOOL-02 other user snapshot', req2['request'].get('talep_eden_adi') == 'Altan TERZİ')

    pool = c.get('/planlama/arac-takip/api/talepler/bekleyen').get_json()
    ok('REQPOOL-06 pool visible', pool.get('ok') and pool.get('count', 0) >= 2)

    plan = c.post('/planlama/arac-takip/api/talepler/plana-al', json={
        'talep_id': tid1,
        'plan_tarihi': '2026-08-22',
        'arac_external_id': '991001',
        'arac_plaka': '34 MOR 049',
        'sofor_id': 1,
        'sofor_adi': 'Alpay Test',
        'planlanan_saat': '09:00',
    }).get_json()
    ok('REQPOOL-09 PLANA_ALINDI', plan.get('ok') and plan['talep'].get('durum') == 'PLANA_ALINDI')
    ok('REQPOOL-10 plan item tx', plan.get('ok') and plan.get('plan_id'))

    dash = c.get('/planlama/arac-takip/api/dashboard?tab=gunluk&date=2026-08-22&vehicle_id=991001').get_json()
    tasks = dash['dashboard']['daily_tasks']
    ok('REQPOOL-11 daily plan shows', len(tasks) >= 1)
    ok('REQPOOL-17 no mock km', dash['dashboard']['daily_tasks'][0].get('distance_km') is None
       or dash['dashboard']['daily_tasks'][0].get('distance_label') == '—')

    dash2 = c.get('/planlama/arac-takip/api/dashboard?tab=gunluk&date=2026-08-22&vehicle_id=991002').get_json()
    ok('REQPOOL-12 wrong vehicle empty/wrong', len(dash2['dashboard']['daily_tasks']) == 0)

    dash3 = c.get('/planlama/arac-takip/api/dashboard?tab=gunluk&date=2026-08-23&vehicle_id=991001').get_json()
    ok('REQPOOL-13 wrong date empty', len(dash3['dashboard']['daily_tasks']) == 0)

    if tasks:
        tid = tasks[0]['id']
        ro = c.post('/planlama/arac-takip/api/reorder', json={
            'date': '2026-08-22', 'vehicle_id': '991001', 'task_id': tid, 'direction': 'down',
        }).get_json()
        ok('REQPOOL-14 reorder ok', ro.get('ok'))

    dup = c.post('/planlama/arac-takip/api/talepler/plana-al', json={
        'talep_id': tid1, 'plan_tarihi': '2026-08-22', 'arac_external_id': '991001', 'arac_plaka': '34 MOR 049',
    }).get_json()
    ok('REQPOOL-15 no duplicate plan item', dup.get('ok') is False or dup.get('error'))

    arac = c.get('/planlama/arac-takip/api/araclar').get_json()
    ok('REQPOOL-08 filom vehicles', arac.get('ok') and len(arac.get('vehicles', [])) >= 2)
    ok('REQPOOL-18 filom regression', arac['vehicles'][0].get('id') == '991001')

with patch('modules.auth.kullanici_yetkileri', return_value=YK_READONLY), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=False):
    c2 = client()
    denied = c2.post('/planlama/arac-takip/api/talepler/plana-al', json={
        'talep_id': 1, 'plan_tarihi': '2026-08-22', 'arac_external_id': '991001', 'arac_plaka': 'x',
    })
    ok('REQPOOL-16 unauthorized plan', denied.status_code == 403)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'REQPOOL SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)

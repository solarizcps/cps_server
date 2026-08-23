# -*- coding: utf-8 -*-
"""REQ-UX-01..08 — Yeni İş Talebi talep eden + saat label fix."""
import io
import os
import sys
import tempfile
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})
MOCK_USERS = [
    {'id': 1, 'display_name': 'Alpay Test', 'kullanici_adi': 'alpay'},
    {'id': 42, 'display_name': 'Altan TERZİ', 'kullanici_adi': 'altan'},
    {'id': 7, 'display_name': 'Halil Yılmaz', 'kullanici_adi': 'halil'},
]
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
print('REQ-UX — Yeni İş Talebi küçük UX fix')
print('=' * 72)

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.planlama.arac_request_user_service.search_cps_users', side_effect=lambda q='', limit=20: [
         u for u in MOCK_USERS
         if not q or q.lower() in u['display_name'].lower() or q.lower() in u['kullanici_adi'].lower()
     ][:limit]), \
     patch('modules.planlama.arac_request_user_service.get_cps_user_by_id', side_effect=lambda uid: next(
         (u for u in MOCK_USERS if u['id'] == int(uid)), None)):
    from modules.planlama import arac_lokasyon_service as loc_svc

    tmp = tempfile.mkdtemp()
    store_file = os.path.join(tmp, 'store.json')
    with patch.object(loc_svc, '_STORE_DIR', tmp), patch.object(loc_svc, '_STORE_FILE', store_file):
        loc_svc.reset_store_for_tests()
        c = client()
        r = c.get('/planlama/arac-takip/')
        html = r.get_data(as_text=True)

        ok('REQ-UX-01 current user automatic', 'atpReqTalepEden' in html and 'Alpay Test' in html
           and 'atpCurrentUserJson' in html)
        ok('REQ-UX-02 own-job default', 'data-mode="own"' in html and 'Kendi İşim' in html)
        import re
        modal_m = re.search(r'id="atpRequestModal".*?</form>', html, re.S)
        modal_html = modal_m.group(0) if modal_m else ''
        ok('REQ-UX-05 no hardcoded user', 'Altan TERZİ' not in modal_html and 'value="42"' not in modal_html)

        usr = c.get('/planlama/arac-takip/api/users/search?q=Altan').get_json()
        ok('REQ-UX-03 another-user search API', usr.get('ok') and any(
            u.get('display_name') == 'Altan TERZİ' for u in usr.get('results', [])))

        req_own = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '09:30', 'is': 'Kendi iş',
            'oncelik': 'NORMAL', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
            'firma': 'AVEL Avrupa Elektrik', 'kisi': 'M', 'telefon': '0532 111 2233',
            'adres': 'Tuzla', 'location_master_id': None, 'save_to_master': False,
            'latitude': 40.81, 'longitude': 29.30,
        }).get_json()
        ok('REQ-UX-04 own persists snapshot', req_own.get('ok')
           and req_own['request'].get('talep_eden_user_id') == 1
           and req_own['request'].get('talep_eden_adi') == 'Alpay Test'
           and req_own['request'].get('istenen_saat') == '09:30')

        req_other = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '14:15', 'is': 'Başka user iş',
            'oncelik': 'YUKSEK', 'talep_eden_user_id': 42, 'talep_eden_adi': 'Altan TERZİ',
            'firma': 'AVEL Avrupa Elektrik', 'kisi': 'M', 'telefon': '0532 111 2233',
            'adres': 'Tuzla', 'save_to_master': False,
            'latitude': 40.81, 'longitude': 29.30,
        }).get_json()
        ok('REQ-UX-03b selected other user persists', req_other['request'].get('talep_eden_user_id') == 42
           and req_other['request'].get('talep_eden_adi') == 'Altan TERZİ')

        modal_part = html.split('id="atpRequestModal"')[1].split('id="atpLocSearch"')[0]
        ok('REQ-UX-06 Saat label + CPS picker', '<label>Saat</label>' in modal_part and 'atp-time-trigger' in modal_part)
        ok('REQ-UX-07 time picker present', 'atpTimePicker' in modal_part and 'type="time"' not in modal_part)
        ok('REQ-UX-08 location UX intact', 'atpLocSearch' in html and 'atpLocCard' in html
           and 'planlama_arac_takip_request.js' in html)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'REQ-UX SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)

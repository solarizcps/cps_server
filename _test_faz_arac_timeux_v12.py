# -*- coding: utf-8 -*-
"""TIMEUX-01..08 — CPS saat seçici (native time input yok)."""
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
print('TIMEUX — CPS saat seçici')
print('=' * 72)

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.planlama.arac_request_user_service.search_cps_users', return_value=[]), \
     patch('modules.planlama.arac_request_user_service.get_cps_user_by_id', return_value=None):
    from modules.planlama import arac_lokasyon_service as loc_svc

    tmp = tempfile.mkdtemp()
    store_file = os.path.join(tmp, 'store.json')
    with patch.object(loc_svc, '_STORE_DIR', tmp), patch.object(loc_svc, '_STORE_FILE', store_file):
        loc_svc.reset_store_for_tests()
        c = client()
        r = c.get('/planlama/arac-takip/')
        html = r.get_data(as_text=True)
        modal = html.split('id="atpRequestModal"')[1].split('id="atpLocSearch"')[0]

        ok('TIMEUX-01 modal opens markup', 'atpRequestModal' in html and 'atpTimePicker' in html)
        ok('TIMEUX-02 date+time aligned markup', 'atp-field-date' in modal and 'atp-field-time' in modal
           and 'atp-time-trigger' in modal)
        ok('TIMEUX-03 no native time input', 'type="time"' not in modal)
        ok('TIMEUX-04 CPS dropdown markup', 'atpTimeDropdown' in modal and 'atpTimeSlots' in modal
           and 'Özel saat' in modal)

        req_slot = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '09:30', 'is': 'Saatli',
            'oncelik': 'NORMAL', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
            'firma': 'AVEL Avrupa Elektrik', 'adres': 'Tuzla', 'telefon': '0532 111 2233',
            'save_to_master': False, 'latitude': 40.81, 'longitude': 29.30,
        }).get_json()
        ok('TIMEUX-05 slot value persisted', req_slot['request'].get('istenen_saat') == '09:30')

        req_custom = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '07:15', 'is': 'Ozel saat',
            'oncelik': 'NORMAL', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
            'firma': 'AVEL Avrupa Elektrik', 'adres': 'Tuzla', 'telefon': '0532 111 2233',
            'save_to_master': False, 'latitude': 40.81, 'longitude': 29.30,
        }).get_json()
        ok('TIMEUX-06 custom HH:MM accepted', req_custom['request'].get('istenen_saat') == '07:15')

        req_empty = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '', 'is': 'Saatsiz',
            'oncelik': 'NORMAL', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
            'firma': 'AVEL Avrupa Elektrik', 'adres': 'Tuzla', 'telefon': '0532 111 2233',
            'save_to_master': False, 'latitude': 40.81, 'longitude': 29.30,
        }).get_json()
        ok('TIMEUX-07 empty time allowed', req_empty.get('ok')
           and req_empty['request'].get('istenen_saat') in ('', None))

        ok('TIMEUX-08 other V1.2 fields intact', 'atpLocSearch' in html and 'atp-req-mode-btn' in html
           and 'atpReqTalepEden' in html and 'planlama_arac_takip_request.js' in html)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'TIMEUX SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)

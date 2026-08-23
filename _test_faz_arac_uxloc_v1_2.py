# -*- coding: utf-8 -*-
"""UXLOC-01..15 — Araç Takip V1.2 Yeni İş Talebi modal + lokasyon UX."""
import io
import json
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
print('UXLOC — Araç Takip V1.2 Yeni İş Talebi')
print('=' * 72)

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
     patch('modules.auth.yetki_var', return_value=True), \
     patch('modules.auth.is_superadmin', return_value=True), \
     patch('modules.planlama.arac_takip_repo.tables_ready', return_value=False):
    from modules.planlama import arac_lokasyon_service as loc_svc

    tmp = tempfile.mkdtemp()
    store_file = os.path.join(tmp, 'store.json')
    with patch.object(loc_svc, '_STORE_DIR', tmp), patch.object(loc_svc, '_STORE_FILE', store_file):
        loc_svc.reset_store_for_tests()
        c = client()
        r = c.get('/planlama/arac-takip/')
        html = r.get_data(as_text=True)

        ok('UXLOC-01 no right drawer', 'atpDrawer' not in html and 'atp-drawer' not in html)
        ok('UXLOC-02 centered modal markup', 'atpRequestModal' in html and 'atp-modal-backdrop' in html)
        ok('UXLOC-03 current user readonly', 'atpReqTalepEden' in html and 'readonly' in html and 'Alpay Test' in html)

        sr = c.get('/planlama/arac-takip/api/locations/search?q=AVEL')
        srj = sr.get_json()
        ok('UXLOC-04 autocomplete API', sr.status_code == 200 and srj.get('ok') and len(srj.get('results', [])) >= 1,
           f"count={len(srj.get('results', []))}")
        avel = srj['results'][0]

        ok('UXLOC-05 hydrate fields in search DTO', all(k in avel for k in ('firma', 'kisi', 'telefon', 'adres')))
        ok('UXLOC-06 location hydrate', avel.get('latitude') is not None and avel.get('longitude') is not None)

        sug = c.get('/planlama/arac-takip/api/locations/suggestions').get_json()
        ok('UXLOC-07 suggestions API', sug.get('ok') and 'recent' in sug and 'frequent' in sug)

        req1 = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '10:00', 'is': 'Montaj test',
            'oncelik': 'NORMAL', 'not': 'ilk',
            'firma': 'Yeni Firma XYZ', 'kisi': 'Ali', 'telefon': '05551112233',
            'adres': 'Gebze, Kocaeli', 'maps_url': 'https://maps.google.com/?q=40.8,29.4',
            'save_to_master': True,
        }).get_json()
        ok('UXLOC-08 new location save', req1.get('ok') and req1['request']['master_action'] == 'created')
        ok('UXLOC-09 save preference stored', req1['request'].get('save_to_master') is True)

        req2 = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '11:00', 'is': 'Snapshot only',
            'oncelik': 'NORMAL',
            'firma': 'Geçici Yer ABC', 'kisi': 'Veli', 'telefon': '05559998877',
            'adres': 'Darıca', 'save_to_master': False,
        }).get_json()
        ok('UXLOC-10 unchecked no master create', req2['request'].get('master_action') == 'none'
           and not req2['request'].get('location_master_id'))

        snap = req2['request'].get('snapshot') or {}
        ok('UXLOC-11 snapshot preserved', snap.get('firma') == 'Geçici Yer ABC' and snap.get('adres') == 'Darıca')

        req3 = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'istenen_saat': '12:00', 'is': 'İkinci ziyaret',
            'oncelik': 'YUKSEK', 'location_master_id': avel['id'],
            'firma': avel['firma'], 'kisi': avel['kisi'], 'telefon': avel['telefon'],
            'adres': avel['adres'], 'latitude': avel['latitude'], 'longitude': avel['longitude'],
            'maps_url': avel.get('maps_url', ''), 'save_to_master': False,
        }).get_json()
        ok('UXLOC-12 re-select saved location', req3.get('ok') and req3['request'].get('location_master_id') == avel['id'])

        dup = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-08-21', 'is': 'Dup test', 'oncelik': 'NORMAL',
            'firma': 'AVEL Avrupa Elektrik', 'kisi': 'X', 'telefon': '0532 111 2233',
            'adres': 'Tuzla OSB, İstanbul', 'save_to_master': True,
        }).get_json()
        ok('UXLOC-13 duplicate control', dup['request'].get('master_action') == 'duplicate_reused')

        with open(store_file, 'r', encoding='utf-8') as fh:
            persisted = json.load(fh)
        ok('UXLOC-14 persist after reload', len(persisted.get('requests', [])) >= 3,
           f"requests={len(persisted.get('requests', []))}")

        ok('UXLOC-15 filom map assets preserved', 'planlama_arac_takip_map.js' in html
           and 'vendor/leaflet' in html and 'atpLeafletMap' in html)

        ok('UXLOC-02b modal script', 'planlama_arac_takip_request.js' in html)
        ok('UXLOC-04b location card UI', 'atpLocCard' in html and 'atpLocSearch' in html)

        sug2 = c.get('/planlama/arac-takip/api/locations/suggestions').get_json()
        recent_ids = [x['id'] for x in sug2.get('recent', [])]
        ok('UXLOC-07b recent after usage', avel['id'] in recent_ids or len(sug2.get('recent', [])) > 0)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'UXLOC SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)

# -*- coding: utf-8 -*-
"""REQV2-01..15 — Yeni İş Talebi UX V2 migration + create/read roundtrip."""
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


def base_loc():
    return {
        'firma': 'REQV2 Test Firma', 'adres': 'Tuzla Test',
        'maps_url': 'https://maps.google.com/?q=40.818,29.305',
        'save_to_master': True,
    }


print('=' * 72)
print('REQV2 — Yeni İş Talebi UX V2')
print('=' * 72)

import importlib.util

m178_path = os.path.join(_APP, 'migrations', '178_arac_is_talebi_ux_v2_fields.py')
spec = importlib.util.spec_from_file_location('m178', m178_path)
m178 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m178)
_db = os.environ.get('CPS_MOCK_DB_PATH') or os.path.join(_APP, 'mock_data.db')
if os.path.normcase(os.path.normpath(_db)) == os.path.normcase(os.path.normpath(os.path.join(_APP, 'mock_data.db'))):
    print(f'  [DB-PATH] {_db}')
else:
    print(f'  [DB-PATH-TEMP] {_db}')
m178.run(_db)

from modules.planlama.arac_takip_repo import ux_v2_columns_ready, get_talep_by_id, list_bekleyen_talepler

ok('REQV2-01 migration', ux_v2_columns_ready())

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True):
    c = client()

    def post_req(extra):
        body = {
            'tarih': '2026-08-22', 'istenen_saat': '10:30', 'is': 'Test iş',
            'oncelik': 'NORMAL', 'not': 'İş detayı metni',
            **base_loc(), **extra,
        }
        return c.post('/planlama/arac-takip/api/request', json=body).get_json()

    j_oktay = post_req({'sofor_secim': 'OKTAY', 'is_turu': 'ALINACAK'})
    ok('REQV2-02 Oktay snapshot', j_oktay.get('ok') and j_oktay['request'].get('sofor_adi_snapshot') == 'Oktay KAŞIKÇI',
       str(j_oktay.get('request', {}).get('sofor_id')))

    j_serhat = post_req({'sofor_secim': 'SERHAT', 'is_turu': 'GONDERILECEK'})
    ok('REQV2-03 Serhat snapshot', j_serhat.get('ok') and j_serhat['request'].get('sofor_adi_snapshot') == 'Serhat GÜLMEN')

    j_diger = post_req({'sofor_secim': 'DIGER', 'sofor_adi': 'Veli Şoför', 'is_turu': 'ZIYARET'})
    ok('REQV2-04 Diğer isim', j_diger.get('ok') and j_diger['request'].get('sofor_adi_snapshot') == 'Veli Şoför')

    ok('REQV2-05 ALINACAK', j_oktay['request'].get('is_turu') == 'ALINACAK')
    ok('REQV2-06 GONDERILECEK', j_serhat['request'].get('is_turu') == 'GONDERILECEK')
    ok('REQV2-07 ZIYARET', j_diger['request'].get('is_turu') == 'ZIYARET')

    j_prod = post_req({
        'sofor_secim': 'OKTAY', 'is_turu': 'GONDERILECEK',
        'urun_malzeme': 'EVA koli', 'miktar': 3, 'miktar_birim': 'Koli',
        'ek_not': 'Ek not satırı',
    })
    req_prod = j_prod.get('request') or {}
    ok('REQV2-08 ürün/miktar/birim', req_prod.get('urun_malzeme') == 'EVA koli'
       and req_prod.get('miktar') == 3.0 and req_prod.get('miktar_birim') == 'Koli')

    ok('REQV2-09 iş detayı', req_prod.get('not') == 'İş detayı metni' and req_prod.get('is_detayi') == 'İş detayı metni')
    ok('REQV2-10 ek not', req_prod.get('ek_not') == 'Ek not satırı')

    sr = c.get('/planlama/arac-takip/api/locations/search?q=AVEL').get_json()
    avel = (sr.get('results') or [{}])[0]
    j_loc = post_req({
        'location_master_id': avel.get('id'), 'firma': avel.get('firma'),
        'adres': avel.get('adres'), 'sofor_secim': 'OKTAY', 'is_turu': 'ZIYARET',
        'save_to_master': False,
    })
    ok('REQV2-11 kayıtlı yer', j_loc.get('ok') and j_loc['request'].get('location_master_id') == int(avel.get('id') or 0))

    j_new = c.post('/planlama/arac-takip/api/locations/from-maps', json={
        'firma': 'REQV2 Yeni Yer', 'adres': 'Gebze',
        'maps_url': 'https://maps.google.com/?q=40.825,29.372',
    }).get_json()
    loc = (j_new.get('location') or {})
    j_maps = post_req({
        'location_master_id': loc.get('id'), 'firma': loc.get('firma'),
        'adres': loc.get('adres'), 'sofor_secim': 'SERHAT', 'is_turu': 'ALINACAK',
        'save_to_master': False,
    })
    ok('REQV2-12 yeni Maps yeri', j_maps.get('ok') and j_new.get('ok')
       and j_maps['request'].get('location_master_id') == int(loc.get('id') or 0))

    tid = req_prod.get('id')
    reread = get_talep_by_id(int(tid)) if tid else None
    ok('REQV2-13 create/read roundtrip', reread and reread.get('sofor_adi_snapshot') == 'Oktay KAŞIKÇI'
       and reread.get('urun_malzeme') == 'EVA koli', str(reread))

    pool = c.get('/planlama/arac-takip/api/talepler/bekleyen').get_json()
    pool_ids = [x['id'] for x in pool.get('talepler', [])]
    ok('REQV2-14 refresh persistence', tid in pool_ids, f'pool={len(pool_ids)}')

    found = next((x for x in pool.get('talepler', []) if x.get('id') == tid), None)
    ok('REQV2-15 pool DTO parity', found and found.get('sofor') == 'Oktay KAŞIKÇI'
       and found.get('is_turu') == 'GONDERILECEK' and found.get('urun_ozet'),
       str({k: found.get(k) for k in ('sofor', 'is_turu_label', 'urun_ozet')} if found else {}))

    html = c.get('/planlama/arac-takip/').get_data(as_text=True)
    ok('REQV2-UI cards', 'Şoför / Kim götürecek?' in html and 'İş Türü / Taşınacak' in html)
    ok('REQV2-UI ek not', 'Ek Not' in html and 'atpReqEkNot' in html)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'REQV2 SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)

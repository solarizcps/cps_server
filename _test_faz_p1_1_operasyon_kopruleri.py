# -*- coding: utf-8 -*-
"""FAZ-P1-1 — Operasyon köprüleri regression testi."""
import io
import os
import sys
import urllib.parse

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('FAZ-P1-1 — OPERASYON KÖPRÜLERİ TEST')
print('=' * 72)

MI = os.path.join(_APP, 'templates', 'nexgen', 'malzeme_ihtiyac_merkezi.html')
SA = os.path.join(_APP, 'templates', 'nexgen', 'satinalma_index.html')
UEM = os.path.join(_APP, 'templates', 'nexgen', 'uretim_emirleri.html')
MPR = os.path.join(_APP, 'templates', 'nexgen', 'mpr_on_calisma.html')
PZM = os.path.join(_APP, 'templates', 'nexgen', 'pazarlama_merkezi.html')
DEPO = os.path.join(_APP, 'templates', 'nexgen', 'depo.html')
ROUTES = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')

mi = open(MI, encoding='utf-8').read()
sa = open(SA, encoding='utf-8').read()
uem = open(UEM, encoding='utf-8').read()
mpr = open(MPR, encoding='utf-8').read()
pzm = open(PZM, encoding='utf-8').read()
depo = open(DEPO, encoding='utf-8').read()
routes = open(ROUTES, encoding='utf-8').read()

ok('01 MI satinalma link kolonu', 'Satın Alma →' in mi and 'mimSatinalmaUrl' in mi)
ok('02 MI url kaynak=mi', "params.set('kaynak', 'mi')" in mi)
ok('03 SA mi kopru banner', 'ngsa-mi-kopru' in sa and 'NGSA_MI_KOPRU' in sa)
ok('04 SA modal prefill', 'ngSipModalAc(prefill)' in sa)
ok('05 routes malzeme route', "def malzeme_ihtiyac_merkezi" in routes)
ok('06 routes satinalma mi_kopru', 'mi_kopru' in routes.split('def satinalma_index')[1].split('def ')[0])
ok('07 UEM tablet rozeti', 'TABLETE GÖNDERİLMEDİ' in uem and 'uem-rozet-tablet-warn' in uem)
ok('08 UEM tablet filtre', '__tablet_bekliyor__' in uem)
ok('09 UEM sonraki adim', 'uemSonrakiAdimGoster' in uem)
ok('10 MPR sonraki adim', 'moSonrakiAdimGoster' in mpr)
ok('11 PZM sonraki adim', 'pzmSonrakiAdimGoster' in pzm)
ok('12 Depo batch kopru', "qs.get('batch')" in depo and 'data-batch' in depo)

import app as flask_app  # noqa: E402
_app = flask_app.app
_app.config['TESTING'] = True
client = _app.test_client()


def login(client_obj, perms=None):
    perms = perms or {}
    with client_obj.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = perms


login(client, {
    'nexgen.plan.view': {'can_view': True},
    'nexgen.satinalma.view': {'can_view': True},
    'nexgen.satinalma.manage': {'can_create': True},
})

r_mi = client.get('/nexgen/malzeme-ihtiyac-merkezi')
ok('13 MI GET 200', r_mi.status_code == 200, str(r_mi.status_code))

r_sa = client.get('/nexgen/satinalma?' + urllib.parse.urlencode({
    'kaynak': 'mi',
    'stok_kod': 'NEX-03-03',
    'plan_ids': '102',
    'siparis_ids': '44',
    'net_eksik_kg': '12.5',
}))
body_sa = r_sa.get_data(as_text=True)
ok('14 SA MI filtre 200', r_sa.status_code == 200, str(r_sa.status_code))
ok('15 SA kopru banner body', 'Malzeme İhtiyaç köprüsü' in body_sa)
ok('16 SA stok kod body', 'NEX-03-03' in body_sa)
ok('17 SA NGSA_MI_KOPRU json', 'NGSA_MI_KOPRU' in body_sa)

login(client, {'nexgen.plan.view': {'can_view': True}, 'nexgen.plan.manage': {'can_manage': True}})
r_uem = client.get('/nexgen/uretim-emirleri')
ok('18 UEM GET 200', r_uem.status_code == 200, str(r_uem.status_code))

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print()
print('=' * 72)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print('=' * 72)
sys.exit(1 if failed else 0)

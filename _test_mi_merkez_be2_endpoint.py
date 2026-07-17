# -*- coding: utf-8 -*-
"""FAZ-MI-MERKEZ-BE-2.1 — mi-merkez/analiz endpoint kapanış testi."""
import hashlib
import io
import json
import os
import sqlite3
import sys
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)
DB = os.path.join(_APP, 'mock_data.db')

import app as flask_app  # noqa: E402
import modules.nexgen.routes as routes_mod  # noqa: E402

_app = flask_app.app
_app.config['TESTING'] = True

results = []
SKIP = 'SKIP'
API = '/nexgen/api/mi-merkez/analiz'

RESPONSE_KEYS = {
    'ok', 'plan_ids', 'ozet', 'plan_ozetleri', 'detay', 'toplu',
    'hesaplanamayan_planlar', 'eslesmemis_rf', 'kalemler', 'yeterli_mi', 'eksik_sayisi',
}
OZET_KEYS = {
    'plan_sayisi', 'basarili_plan_sayisi', 'siparis_sayisi', 'cari_sayisi',
    'toplam_hammadde_kg', 'toplam_net_eksik_kg', 'yeterli_kalem_sayisi',
    'eksik_kalem_sayisi', 'yeterli_mi',
}


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    mark = 'PASS' if cond is True else ('SKIP' if cond is SKIP else 'FAIL')
    print(f'  [{mark}] {name}' + (f' — {detail}' if detail else ''))


def skip(name, detail=''):
    ok(name, SKIP, detail)


def sess_view(client):
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = {'nexgen.plan.view': {'can_view': True}}


def sess_no_perm(client):
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': 2, 'KullaniciAdi': 'guest', 'Tip': 'sistem',
            'RolId': 2, 'RolAd': 'guest', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = {}


def db_counts(con):
    tables = (
        'nexgen_uretim_plan',
        'nexgen_uretim_plan_boyut',
        'nexgen_stok_rezerv',
        'nexgen_stok_hareket',
        'nexgen_satin_alma_siparis',
    )
    out = {}
    for t in tables:
        try:
            out[t] = con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def find_plans(con, n=2):
    rows = con.execute("""
        SELECT id FROM nexgen_uretim_plan
        WHERE durum != 'IPTAL' AND COALESCE(planlanan_kg, 0) > 0
        ORDER BY id DESC LIMIT ?
    """, (n * 5,)).fetchall()
    ok_ids = []
    for r in rows:
        s = routes_mod._mpr_stok_ihtiyac_birlestir(con, r['id'])
        if s.get('ok'):
            ok_ids.append(r['id'])
        if len(ok_ids) >= n:
            break
    return ok_ids


def sum_detay(detay):
    return round(sum(float(d.get('gerekli_kg') or 0) for d in detay if d.get('stok_kart_id')), 6)


def sum_toplu(toplu, field='gerekli_kg'):
    if field == 'net_eksik_kg':
        return round(sum(float(t.get('net_eksik_kg') or 0) for t in toplu), 6)
    return round(sum(float(t.get('gerekli_kg') or t.get('toplam_gerekli_kg') or 0) for t in toplu), 6)


def mutabakat_detay_toplu(payload, tol=0.001):
    detay = payload.get('detay') or []
    toplu = payload.get('toplu') or []
    ds = sum_detay(detay)
    ts = sum_toplu(toplu)
    return abs(ds - ts) <= tol, ds, ts


def mutabakat_ozet_toplu(payload, tol=0.001):
    toplu = payload.get('toplu') or []
    oz = payload.get('ozet') or {}
    ts = sum_toplu(toplu)
    ok_h = abs(float(oz.get('toplam_hammadde_kg') or 0) - ts) <= tol
    ok_n = abs(float(oz.get('toplam_net_eksik_kg') or 0) - sum_toplu(toplu, 'net_eksik_kg')) <= tol
    y = int(oz.get('yeterli_kalem_sayisi') or 0)
    e = int(oz.get('eksik_kalem_sayisi') or 0)
    ok_ye = (y + e) == len(toplu)
    return ok_h and ok_n and ok_ye, ts, y, e, len(toplu)


print('=' * 72)
print('FAZ-MI-MERKEZ-BE-2.1 — ANALİZ ENDPOINT KAPANIŞ TESTİ')
print('=' * 72)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
plans = find_plans(con, 2)
plan_a = plans[0] if plans else None
plan_b = plans[1] if len(plans) > 1 else None
ok('setup planlar', plan_a is not None, f'a={plan_a} b={plan_b}')

client = _app.test_client()

# 1 oturum yok
r = client.post(API, json={'plan_ids': [plan_a] if plan_a else [1]})
ok('01 oturum yok 302', r.status_code == 302, str(r.status_code))

# 2 yetki yok
sess_no_perm(client)
r = client.post(API, json={'plan_ids': [plan_a] if plan_a else [1]})
ok('02 yetki yok 403', r.status_code == 403, (r.get_json() or {}).get('hata', ''))

sess_view(client)

# 3 body yok
r = client.post(API, content_type='application/json')
ok('03 body yok 400', r.status_code == 400)

# 4 geçersiz json
r = client.post(API, data='{bad', content_type='application/json')
ok('04 gecersiz json 400', r.status_code == 400)

# 5 plan_ids yok
r = client.post(API, json={})
ok('05 plan_ids yok', r.status_code == 400 and 'plan_ids' in ((r.get_json() or {}).get('hata') or '').lower())

# 6 liste değil
r = client.post(API, json={'plan_ids': plan_a})
ok('06 plan_ids liste degil', r.status_code == 400)

# 7 boş liste
r = client.post(API, json={'plan_ids': []})
ok('07 bos liste', r.status_code == 400)

# 8-10 tip reddi
for label, val in (('08 bool', True), ('09 string', '91'), ('10 float', 91.0)):
    r = client.post(API, json={'plan_ids': [val]})
    ok(label, r.status_code == 400, (r.get_json() or {}).get('hata', ''))

if plan_a and plan_b:
    # 11 duplicate
    r = client.post(API, json={'plan_ids': [plan_a, plan_a, plan_b]})
    d = r.get_json() or {}
    ok('11 duplicate temiz', r.status_code == 200 and d.get('plan_ids') == [plan_a, plan_b])

    # 12 tek plan
    r = client.post(API, json={'plan_ids': [plan_a]})
    d = r.get_json() or {}
    ok('12 tek plan 200', r.status_code == 200 and d.get('ok') is True)

    # 13 çoklu plan
    r = client.post(API, json={'plan_ids': [plan_a, plan_b]})
    d = r.get_json() or {}
    ok('13 coklu plan 200', r.status_code == 200 and d.get('ok') is True)

    # 14 200 plan
    r = client.post(API, json={'plan_ids': [plan_a] * 200})
    ok('14 200 plan kabul', r.status_code == 200, str(r.status_code))

    # 15 201 plan
    r = client.post(API, json={'plan_ids': [plan_a] * 201})
    d = r.get_json() or {}
    ok('15 201 plan red', r.status_code == 400 and '200 plan' in (d.get('hata') or ''))

    # 16 tamamen geçersiz
    r = client.post(API, json={'plan_ids': [999999881, 999999882]})
    d = r.get_json() or {}
    ok('16 tamamen gecersiz', r.status_code == 400 and d.get('ok') is False)
    ok('16 traceback yok', 'Traceback' not in r.get_data(as_text=True))

    # 17 kısmi başarı
    r = client.post(API, json={'plan_ids': [plan_a, 999999883]})
    d = r.get_json() or {}
    ok('17 kismi 200', r.status_code == 200 and d.get('ok') is True)
    ok('17 kismi hesaplanamayan', len(d.get('hesaplanamayan_planlar') or []) == 1)
    ok('17 kismi detay var', len(d.get('detay') or []) > 0)
    ok('17 kismi toplu var', len(d.get('toplu') or []) > 0)

    # 18 başarılı korunur
    ok('18 basarili plan ozet', d.get('ozet', {}).get('basarili_plan_sayisi') == 1)

    # 19-21 response + mutabakat (tam başarılı çoklu plan)
    r_full = client.post(API, json={'plan_ids': [plan_a, plan_b]})
    d_full = r_full.get_json() or {}
    keys_ok = RESPONSE_KEYS.issubset(set(d_full.keys()))
    ok('19 response ana alanlar', keys_ok, str(set(d_full.keys())))
    ok('19 ozet alanlar', OZET_KEYS.issubset(set((d_full.get('ozet') or {}).keys())))

    m_ok, ds, ts = mutabakat_detay_toplu(d_full)
    ok('20 detay-toplu mutabakat', m_ok, f'd={ds} t={ts}')

    o_ok, _, y, e, tn = mutabakat_ozet_toplu(d_full)
    ok('21 ozet-toplu mutabakat', o_ok, f'y={y} e={e} toplu={tn}')

    # 22 salt okunur
    before = db_counts(con)
    client.post(API, json={'plan_ids': [plan_a, plan_b]})
    after = db_counts(con)
    ok('22 db yazmiyor', before == after, f'{before} -> {after}')

    # 23 exception güvenli
    def _boom(*a, **k):
        raise RuntimeError('test patlama')

    with patch.object(routes_mod, '_mpr_stok_ihtiyac_coklu_plan', _boom):
        r = client.post(API, json={'plan_ids': [plan_a]})
    body = r.get_data(as_text=True)
    ok('23 exception 500', r.status_code == 500)
    ok('23 traceback yok', 'Traceback' not in body and 'test patlama' not in body)

    # 24 idempotent
    p1 = client.post(API, json={'plan_ids': [plan_a, plan_b]}).get_json()
    p2 = client.post(API, json={'plan_ids': [plan_a, plan_b]}).get_json()
    h1 = hashlib.sha256(json.dumps(p1.get('ozet'), sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(p2.get('ozet'), sort_keys=True).encode()).hexdigest()
    ok('24 idempotent', h1 == h2, h1[:12])

    # 25 exclude yok
    r = client.post(API, json={'plan_ids': [plan_a]})
    ok('25 exclude yok', r.status_code == 200)

    # 26 exclude null
    r = client.post(API, json={'plan_ids': [plan_a], 'exclude_batch_kodu': None})
    ok('26 exclude null', r.status_code == 200)

    # 27 exclude helper'a aktarılır
    captured = {}
    real = routes_mod._mpr_stok_ihtiyac_coklu_plan

    def _cap_fn(con, plan_ids, exclude_batch_kodu=None):
        captured['exclude'] = exclude_batch_kodu
        return real(con, plan_ids, exclude_batch_kodu=exclude_batch_kodu)

    with patch.object(routes_mod, '_mpr_stok_ihtiyac_coklu_plan', _cap_fn):
        client.post(API, json={'plan_ids': [plan_a], 'exclude_batch_kodu': 'BATCH-TEST-XYZ'})
    ok('27 exclude aktarim', captured.get('exclude') == 'BATCH-TEST-XYZ', str(captured))

    # 28 exclude yanlış tip → stringe çevrilir
    with patch.object(routes_mod, '_mpr_stok_ihtiyac_coklu_plan', _cap_fn):
        client.post(API, json={'plan_ids': [plan_a], 'exclude_batch_kodu': 12345})
    ok('28 exclude tip guvenli', captured.get('exclude') == '12345', str(captured))

con.close()

print()
print('=' * 72)
print('ÖZET')
print('=' * 72)
passed = sum(1 for _, c, _ in results if c is True)
failed = sum(1 for _, c, _ in results if c is False)
skipped = sum(1 for _, c, _ in results if c is SKIP)
print(f'  PASS={passed}  FAIL={failed}  SKIP={skipped}  TOPLAM={len(results)}')
if failed:
    for name, c, detail in results:
        if c is False:
            print(f'    FAIL: {name} — {detail}')

sys.exit(1 if failed else 0)

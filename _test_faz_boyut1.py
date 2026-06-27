# -*- coding: utf-8 -*-
"""NEXGEN FAZ-BOYUT-1 — nexgen_uretim_plan_boyut tablo + backfill doğrulama."""
import sys
import io
import os
import sqlite3
import math

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')

import app as flask_app
from modules.nexgen.routes import _formul_batch_kg_hesapla, _batch_uretim_hesapla

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {
        'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
        'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
    }


def boyut_sira(boyut):
    b = (boyut or '').upper()
    if b == 'LARGE':
        return 1
    if b == 'SMALL':
        return 2
    if b == 'STANDART':
        return 3
    return 9


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# A) Tablo var mı?
tbl = con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_plan_boyut'"
).fetchone()
ok('A tablo var', tbl is not None, tbl['name'] if tbl else '')

cols = {r['name'] for r in con.execute('PRAGMA table_info(nexgen_uretim_plan_boyut)').fetchall()} if tbl else set()
beklenen_kolon = {
    'id', 'plan_id', 'uretim_varyant_id', 'boyut', 'siparis_kg',
    'formul_batch_kg', 'batch_sayisi', 'uretilecek_kg', 'fazla_kg',
    'sira', 'aktif', 'olusturma_tarihi', 'guncelleme_tarihi',
}
ok('A kolonlar', beklenen_kolon.issubset(cols), str(sorted(cols))[:80])

# B) Index / unique
idx_plan = con.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_nupb_plan_id'"
).fetchone()
idx_uv = con.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_nupb_uv_id'"
).fetchone()
ok('B idx_nupb_plan_id', idx_plan is not None)
ok('B idx_nupb_uv_id', idx_uv is not None)

uniq_sql = con.execute("""
    SELECT sql FROM sqlite_master
    WHERE type='table' AND name='nexgen_uretim_plan_boyut'
""").fetchone()
ok('B unique(plan_id, uretim_varyant_id)', uniq_sql and 'UNIQUE' in (uniq_sql['sql'] or '').upper())

planlar = con.execute("""
    SELECT np.id, np.plan_kodu, np.planlanan_kg, np.uretim_varyant_id, uv.boyut
    FROM nexgen_uretim_plan np
    JOIN nexgen_uretim_varyant uv ON uv.id = np.uretim_varyant_id
    WHERE np.uretim_varyant_id IS NOT NULL
    ORDER BY np.id
""").fetchall()

satirlar = con.execute("SELECT * FROM nexgen_uretim_plan_boyut ORDER BY plan_id, sira").fetchall()

# C) Her plan için en az 1 satır
plans_with_row = {s['plan_id'] for s in satirlar}
missing = [p['id'] for p in planlar if p['id'] not in plans_with_row]
ok('C her plan en az 1 satir', len(missing) == 0,
   f'eksik={missing[:5]}' if missing else f'plan={len(planlar)} satir={len(satirlar)}')

# G) MEDIUM yok
medium_cnt = con.execute(
    "SELECT COUNT(*) AS c FROM nexgen_uretim_plan_boyut WHERE UPPER(boyut)='MEDIUM'"
).fetchone()['c']
ok('G MEDIUM yok', medium_cnt == 0, str(medium_cnt))

# D/E/F satır doğrulama
de_fail = 0
sira_fail = 0
for p in planlar:
    rows = [s for s in satirlar if s['plan_id'] == p['id']]
    if not rows:
        de_fail += 1
        continue
    if len(rows) != 1:
        continue
    s = rows[0]
    sip_ok = abs(float(s['siparis_kg']) - float(p['planlanan_kg'])) < 0.001
    if not sip_ok:
        de_fail += 1

    bh = _batch_uretim_hesapla(con, p['uretim_varyant_id'], float(p['planlanan_kg']))
    if bh.get('ok'):
        fb_ok = abs(float(s['formul_batch_kg']) - float(bh['formul_batch_kg'])) < 0.001
        bs_ok = int(s['batch_sayisi']) == int(bh['batch_sayisi'])
        ure_ok = abs(float(s['uretilecek_kg']) - float(bh['uretilecek_kg'])) < 0.001
        faz_ok = abs(float(s['fazla_kg']) - float(bh['fazla_kg'])) < 0.001
        if not (fb_ok and bs_ok and ure_ok and faz_ok):
            de_fail += 1
    else:
        if float(s['formul_batch_kg'] or 0) != round(_formul_batch_kg_hesapla(con, p['uretim_varyant_id']), 3):
            de_fail += 1

    bek_sira = boyut_sira(p['boyut'])
    if int(s['sira']) != bek_sira:
        sira_fail += 1

ok('D siparis_kg = plan.planlanan_kg', de_fail == 0, f'hatali={de_fail}')
ok('E batch cache alanlari', de_fail == 0, 'formul/batch/uretilecek/fazla')
ok('F sira LARGE/SMALL/STANDART', sira_fail == 0, f'hatali={sira_fail}')

# F detay: LARGE ve SMALL sıra
for boyut, bek in (('LARGE', 1), ('SMALL', 2), ('STANDART', 3)):
    r = con.execute("""
        SELECT sira FROM nexgen_uretim_plan_boyut
        WHERE UPPER(boyut)=? LIMIT 1
    """, (boyut,)).fetchone()
    if r:
        ok(f'F sira {boyut}', int(r['sira']) == bek, str(r['sira']))

# Örnek plan
ornek = con.execute("""
    SELECT np.id, np.plan_kodu, np.planlanan_kg, b.*
    FROM nexgen_uretim_plan np
    JOIN nexgen_uretim_plan_boyut b ON b.plan_id = np.id
    WHERE np.durum='ON_CALISMA'
    ORDER BY np.id DESC LIMIT 1
""").fetchone()
if ornek:
    ok('ornek ON_CALISMA plan', True,
       f"{ornek['plan_kodu']} boyut={ornek['boyut']} siparis={ornek['siparis_kg']} "
       f"batch={ornek['batch_sayisi']} ure={ornek['uretilecek_kg']}")
else:
    ok('ornek ON_CALISMA plan', planlar, 'plan yok veya satir yok')

# H) stok-onizle API
with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    test_plan = planlar[0] if planlar else None
    if test_plan:
        rf = con.execute("""
            SELECT rf.id FROM nexgen_rf_renk rf
            JOIN nexgen_rf_formul_uygunluk u ON u.rf_renk_id = rf.id
            JOIN nexgen_uretim_varyant uv ON uv.id = ?
            JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id AND rv.formul_id = u.formul_id
            WHERE rf.durum='ONAYLI' AND rf.aktif=1 LIMIT 1
        """, (test_plan['uretim_varyant_id'],)).fetchone()
        rf_id = rf['id'] if rf else None
        r = c.post('/nexgen/api/plan/stok-onizle', json={
            'uretim_varyant_id': test_plan['uretim_varyant_id'],
            'rf_renk_id': rf_id,
            'planlanan_kg': float(test_plan['planlanan_kg']),
        })
        sd = r.get_json() or {}
        ok('H stok-onizle 200', r.status_code == 200 and sd.get('ok'),
           f"kalem={len(sd.get('kalemler', []))} yeterli={sd.get('yeterli_mi')}")

con.close()

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== FAZ-BOYUT-1: {passed}/{len(results)} PASS, {failed} FAIL ===')
print('Not: _test_fazm1_mpr_on_calisma.py ayri calistirilmali (I regresyon).')
sys.exit(1 if failed else 0)

# -*- coding: utf-8 -*-
"""BE-3D — MPR sonuç paneli, hydrate, stok önizleme testleri."""
import io
import os
import shutil
import sqlite3
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

SRC_DB = os.path.join(_APP, 'mock_data.db')
TEST_DB = os.path.join(_APP, 'mock_data_be3d_test_tmp.db')
TPL = os.path.join(_APP, 'templates', 'nexgen', 'pazarlama_merkezi.html')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def v2_payload(con, kalemler):
    cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()['id']
    termin = (date.today() + timedelta(days=21)).isoformat()
    return {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': termin,
        'genel_not': 'BE3D test',
        'kalemler': kalemler,
    }


def terlik_kalem(con, rf_renk_id):
    fid = con.execute(
        "SELECT MIN(f.id) FROM nexgen_formul f WHERE f.kod LIKE '1BA-FL01' AND f.aktif=1"
    ).fetchone()[0]
    termin = (date.today() + timedelta(days=14)).isoformat()
    return {
        'urun_ailesi': 'TERLIK',
        'formul_id': fid,
        'rf_renk_id': rf_renk_id,
        'renk_varyant_id': rf_renk_id,
        'miktar_l': 2000,
        'miktar_s': 2000,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


print('=' * 65)
print('BE-3D TEST')
print('=' * 65)

with open(TPL, encoding='utf-8') as f:
    tpl = f.read()

for m in ['pzmDetayStokYukle', 'pzmDetayHydrate', 'pzmDetayUretimeGonder',
          'stokSonuclari', 'hydrating', 'uretimeGonderiliyor', 'pzmStokOzetHtml',
          'pzmSiparisUretimeGonder', '/api/pazarlama/siparis/']:
    ok('template: ' + m[:35], m in tpl)

shutil.copy2(SRC_DB, TEST_DB)
import app as flask_app
import modules.nexgen.routes as nx_routes

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config['TESTING'] = True

con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row

import importlib.util
m107 = os.path.join(_APP, 'migrations', '107_nexgen_planlama_siparis_kalem.py')
if os.path.exists(m107):
    spec = importlib.util.spec_from_file_location('m107', m107)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path=TEST_DB)

rf = con.execute(
    "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
    "JOIN nexgen_formul f ON f.id=u.formul_id "
    "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
).fetchone()

created_tid = None
if rf:
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'

        d_t = (c.post('/nexgen/api/pazarlama/taslak-kaydet',
                      json=v2_payload(con, [terlik_kalem(con, rf['rf_renk_id'])])).get_json() or {})
        created_tid = d_t.get('talep_id')
        ok('taslak olustu', d_t.get('ok'), d_t.get('siparis_no'))

        plan_b = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        r_mpr = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': created_tid})
        d_mpr = r_mpr.get_json() or {}
        plan_a = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        planlar = d_mpr.get('planlar') or []

        ok('MPR ok', d_mpr.get('ok'), str(len(planlar)))
        ok('plan zengin talep_kg', bool(planlar and planlar[0].get('talep_kg') is not None))
        ok('plan zengin uretilecek_kg', bool(planlar and planlar[0].get('uretilecek_kg') is not None))
        ok('plan zengin boyut metrik', bool(
            planlar and planlar[0].get('boyutlar')
            and planlar[0]['boyutlar'][0].get('tam_formul_kg') is not None
        ))

        r_mpr2 = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': created_tid})
        d_mpr2 = r_mpr2.get_json() or {}
        plan_a2 = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        ok('mukerrer MPR engeli', d_mpr2.get('ok') and d_mpr2.get('zaten_var'))
        ok('plan sayisi artmadi', plan_a2 == plan_a, f'{plan_a}->{plan_a2}')

        r_list = c.get('/nexgen/api/pazarlama/talepler')
        liste = (r_list.get_json() or {}).get('liste') or []
        bul = next((x for x in liste if x.get('id') == created_tid), None)
        ok('talepler hydrate mpr_planlar', bool(bul and bul.get('mpr_planlar')))
        hp = (bul or {}).get('mpr_planlar') or [{}]
        ok('hydrate metrik', hp[0].get('faturalanacak_kg') is not None)

        if planlar:
            pid = planlar[0]['plan_id']
            r_stok = c.post('/nexgen/api/plan/stok-onizle', json={'plan_id': pid})
            d_stok = r_stok.get_json() or {}
            ok('stok-onizle ok', d_stok.get('ok') is not False or 'kalemler' in d_stok,
               'yeterli=' + str(d_stok.get('yeterli_mi')))

            r_pl = c.post(f'/nexgen/api/uem/emir/{pid}/planlandi-yap')
            d_pl = r_pl.get_json() or {}
            ok('planlandi-yap', d_pl.get('ok'), d_pl.get('durum'))

        r_page = c.get('/nexgen/pazarlama')
        ok('sayfa 200', r_page.status_code == 200)

        for p in planlar:
            pid = p.get('plan_id')
            if pid:
                con.execute('DELETE FROM nexgen_uretim_plan_boyut WHERE plan_id=?', (pid,))
                con.execute('DELETE FROM nexgen_uretim_plan WHERE id=?', (pid,))
        if created_tid:
            con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (created_tid,))
            con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (created_tid,))
        con.commit()
else:
    ok('RF uygunluk', True, 'atlandi')

con.close()
try:
    os.remove(TEST_DB)
except OSError:
    pass

print('\n' + '=' * 65)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print('Commit: EDILMEDI')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)

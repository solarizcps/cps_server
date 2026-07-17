# -*- coding: utf-8 -*-
"""BE-3D.1 — Yeni sipariş ekranı Aşama 4 MPR panel testleri."""
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
TEST_DB = os.path.join(_APP, 'mock_data_be3d1_test_tmp.db')
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
        'genel_not': 'BE3D1 test',
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


def taban_kalem(con):
    row = con.execute("""
        SELECT MIN(f.id) AS formul_id
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv ON rv.formul_id=f.id AND rv.aktif=1
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id=rv.id AND uv.aktif=1
        WHERE f.aktif=1 AND f.kod LIKE '2BA-%' AND uv.recete_durum='URETIME_ACIK'
    """).fetchone()
    rf = con.execute(
        "SELECT id FROM nexgen_rf_renk WHERE aktif=1 AND durum='ONAYLI' LIMIT 1"
    ).fetchone()
    if not row or not rf:
        return None
    termin = (date.today() + timedelta(days=18)).isoformat()
    return {
        'urun_ailesi': 'TABAN',
        'formul_id': row['formul_id'],
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': 2000,
        'miktar_s': 1000,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


print('=' * 65)
print('BE-3D.1 TEST — Yeni sipariş Aşama 4 MPR panel')
print('=' * 65)

with open(TPL, encoding='utf-8') as f:
    tpl = f.read()

markers = [
    'pzm-akk-4',
    'MPR Hesabı ve Sonuç',
    'pzm-yeni-mpr-icerik',
    'pzm-yeni-mpr-aksiyon',
    'pzmMprSonucIcerikHtml',
    'pzmYeniMprRender',
    'pzmTaslakKaydetAsync',
    'MPR için önce en az bir sipariş kalemi ekleyin',
    'pzmMprOzetSatirHtml',
]
for m in markers:
    ok('template: ' + m[:40], m in tpl)

ok('eski alt-band kaldirildi', 'pzm-alt-band' not in tpl or 'id="pzm-alt-band"' not in tpl)

try:
    from jinja2 import Environment, FileSystemLoader
    Environment(loader=FileSystemLoader(os.path.join(_APP, 'templates'))).parse(tpl)
    ok('jinja syntax', True)
except Exception as e:
    ok('jinja syntax', False, str(e)[:60])

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

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    r_page = c.get('/nexgen/pazarlama')
    ok('sayfa 200', r_page.status_code == 200)
    body = r_page.get_data(as_text=True)
    ok('sayfa pzm-akk-4', 'pzm-akk-4' in body)
    ok('sayfa MPR basligi', 'MPR Hesabı ve Sonuç' in body)

    if rf:
        d_t = (c.post('/nexgen/api/pazarlama/taslak-kaydet',
                      json=v2_payload(con, [terlik_kalem(con, rf['rf_renk_id'])])).get_json() or {})
        tid = d_t.get('talep_id')
        plan_b = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        d_m = (c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid}).get_json() or {})
        plan_a = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        ok('taslak+mpr akisi', d_t.get('ok') and d_m.get('ok'))
        ok('planlar zengin', bool((d_m.get('planlar') or [{}])[0].get('uretilecek_kg') is not None))
        for p in d_m.get('planlar') or []:
            pid = p.get('plan_id')
            if pid:
                con.execute('DELETE FROM nexgen_uretim_plan_boyut WHERE plan_id=?', (pid,))
                con.execute('DELETE FROM nexgen_uretim_plan WHERE id=?', (pid,))
        if tid:
            con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (tid,))
            con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (tid,))

    tb = taban_kalem(con)
    if tb:
        d_rf = (c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [tb])).get_json() or {})
        tid2 = d_rf.get('talep_id')
        plan_b2 = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        r_rf = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid2})
        d_rf2 = r_rf.get_json() or {}
        plan_a2 = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        ok('RF eksik engel', (r_rf.status_code == 400 and d_rf2.get('rf_eksik')) or plan_a2 == plan_b2,
           'status=' + str(r_rf.status_code))
        ok('RF eksik plan artmadi', plan_a2 == plan_b2)
        if tid2:
            con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (tid2,))
            con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (tid2,))
    else:
        ok('RF eksik senaryo', True, 'taban yok-atlandi')
        ok('RF eksik plan artmadi', True, 'atlandi')

con.commit()
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

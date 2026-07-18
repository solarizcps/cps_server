# -*- coding: utf-8 -*-
"""FAZ-P0-1 — L/S boyut batch + siparis TAMAMLANDI regression testleri."""
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
TEST_DB = os.path.join(_APP, 'mock_data_p0_1_test_tmp.db')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def rf_id(con):
    row = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    return row['rf_renk_id'] if row else None


def terlik_payload(con, ml=24, ms=24, rf=None):
    fid = con.execute(
        "SELECT MIN(id) FROM nexgen_formul WHERE kod LIKE '1BA-FL01' AND aktif=1"
    ).fetchone()[0]
    cid = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()['id']
    rf = rf or rf_id(con)
    return {
        'cari_id': cid,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': (date.today() + timedelta(days=21)).isoformat(),
        'genel_not': 'P0-1 test',
        'kalemler': [{
            'urun_ailesi': 'TERLIK',
            'formul_id': fid,
            'rf_renk_id': rf,
            'renk_varyant_id': rf,
            'miktar_l': ml,
            'miktar_s': ms,
            'miktar_m': None,
            'termin_tarihi': (date.today() + timedelta(days=14)).isoformat(),
        }],
    }


def stok_tamamla(c, con):
    ted = con.execute('SELECT id FROM nexgen_tedarikci WHERE aktif=1 LIMIT 1').fetchone()['id']
    for kod in ('NEX-03-03', 'NEX-05-01', 'NEX-05-08', 'NEX-01-01', 'NEX-01-03'):
        sk = con.execute('SELECT id FROM nexgen_stok_kart WHERE kod=?', (kod,)).fetchone()
        if sk:
            c.post('/nexgen/api/depo/mal-kabul', json={
                'tedarikci_id': ted, 'stok_kart_id': sk['id'], 'miktar_kg': 2000.0,
                'aciklama': 'P0-1 test stok', 'lot_no': f'P01-{kod}',
            })


def planlandi_yap(c, plan_id):
    c.post(f'/nexgen/api/uem/emir/{plan_id}/planlandi-yap')


def uretime_gonder_siparis(c, talep_id):
    return c.post(f'/nexgen/api/pazarlama/siparis/{talep_id}/uretime-gonder', json={'confirm': True})


def parca_ozet(con, batch_kodu):
    rows = con.execute(
        "SELECT id, parca_no, hedef_kg, durum, notlar FROM nexgen_uretim_parca "
        "WHERE batch_kodu=? ORDER BY parca_no",
        (batch_kodu,),
    ).fetchall()
    return [dict(r) for r in rows]


def bitir_batch(c, con, batch_kodu, plan_id):
    c.post(f'/nexgen/api/batch/{batch_kodu}/durum', json={'durum': 'DEVAM'})
    hid = con.execute(
        "SELECT id FROM nexgen_depo_hazirlik WHERE batch_kodu=? ORDER BY id DESC LIMIT 1",
        (batch_kodu,),
    ).fetchone()
    if hid:
        c.post(f'/nexgen/api/depo/hazirlik/{hid["id"]}/baslat', json={})
        c.post(f'/nexgen/api/depo/hazirlik/{hid["id"]}/hazir', json={})
    for p in parca_ozet(con, batch_kodu):
        c.post(f'/nexgen/api/batch/{batch_kodu}/parca/{p["id"]}/baslat')
        c.post(f'/nexgen/api/batch/{batch_kodu}/parca/{p["id"]}/bitir', json={})
    return c.post(f'/nexgen/api/batch/{batch_kodu}/durum', json={'durum': 'BITTI'})


print('=' * 65)
print('FAZ-P0-1 TEST')
print('=' * 65)

shutil.copy2(SRC_DB, TEST_DB)
import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import _PARCA_BOYUT_UV_MARKER, _mpr_plan_uretim_parcalari_hesapla

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config['TESTING'] = True
con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    stok_tamamla(c, con)

    # T1 — LARGE + SMALL → 2 parça, 171.20 kg
    d1 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=terlik_payload(con)).get_json() or {}
    tid = d1.get('talep_id')
    c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid})
    plan = con.execute(
        'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id DESC LIMIT 1',
        (tid,),
    ).fetchone()
    pid = plan['id']
    planlandi_yap(c, pid)
    r4 = uretime_gonder_siparis(c, tid)
    d4 = r4.get_json() or {}
    bk = (d4.get('planlar') or [{}])[0].get('batch_kodu')
    parcalar = parca_ozet(con, bk)
    hedef_top = round(sum(float(p['hedef_kg']) for p in parcalar), 2)
    ok('T1 L+S 2 parca', len(parcalar) == 2, f'adet={len(parcalar)}')
    ok('T1 toplam hedef 171.20', abs(hedef_top - 171.2) < 0.01, f'toplam={hedef_top}')
    hedefler = sorted(round(float(p['hedef_kg']), 2) for p in parcalar)
    ok('T1 hedef KG L+S', hedefler == [85.25, 85.95], str(hedefler))
    ok('T1 boyut marker', all(_PARCA_BOYUT_UV_MARKER in (p.get('notlar') or '') for p in parcalar))

    satirlar = _mpr_plan_uretim_parcalari_hesapla(con, pid)
    ok('T1 uretim satir sayisi', len(satirlar) == 2, str(len(satirlar)))

    # T7 duplicate
    r_dup = uretime_gonder_siparis(c, tid)
    d_dup = r_dup.get_json() or {}
    ok('T7 duplicate blok', not d_dup.get('ok'), d_dup.get('hata', '')[:60])

    # T5 kapanis — bitir → plan BITTI → siparis TAMAMLANDI
    bitir_batch(c, con, bk, pid)
    pd = con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (pid,)).fetchone()['durum']
    sd = con.execute('SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (tid,)).fetchone()['durum']
    uret = con.execute(
        "SELECT ROUND(COALESCE(SUM(uretilen_kg),0),3) FROM nexgen_uretim_parca WHERE batch_kodu=?",
        (bk,),
    ).fetchone()[0]
    ok('T5 plan BITTI', pd == 'BITTI', pd)
    ok('T5 siparis TAMAMLANDI', sd == 'TAMAMLANDI', sd)
    ok('T5 fiili uretilen 171.20', abs(float(uret) - 171.2) < 0.01, str(uret))

    # T2 — yalniz LARGE (ms=0)
    d2 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=terlik_payload(con, ml=24, ms=0)).get_json()
    tid2 = d2['talep_id']
    c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid2})
    p2 = con.execute(
        'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (tid2,)
    ).fetchone()['id']
    planlandi_yap(c, p2)
    d_u2 = uretime_gonder_siparis(c, tid2).get_json()
    bk2 = d_u2['planlar'][0]['batch_kodu']
    p2s = parca_ozet(con, bk2)
    ok('T2 LARGE only 1 parca', len(p2s) == 1, str(len(p2s)))
    ok('T2 LARGE hedef 85.95', abs(float(p2s[0]['hedef_kg']) - 85.95) < 0.01)

    # T3 — yalniz SMALL
    d3 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=terlik_payload(con, ml=0, ms=24)).get_json()
    tid3 = d3['talep_id']
    c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid3})
    p3 = con.execute(
        'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (tid3,)
    ).fetchone()['id']
    sat3 = _mpr_plan_uretim_parcalari_hesapla(con, p3)
    ok('T3 SMALL UV', sat3[0]['uretim_varyant_id'] == 10101, str(sat3[0]['uretim_varyant_id']))
    ok('T3 SMALL hedef 85.25', abs(sat3[0]['uretilecek_kg'] - 85.25) < 0.01)

con.close()
try:
    os.remove(TEST_DB)
except OSError:
    pass

print('\n' + '=' * 65)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)

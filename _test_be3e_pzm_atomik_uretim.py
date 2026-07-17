# -*- coding: utf-8 -*-
"""BE-3E — Çok planlı Pazarlama siparişini atomik üretime gönderme testleri."""
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
TEST_DB = os.path.join(_APP, 'mock_data_be3e_test_tmp.db')
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
        'genel_not': 'BE3E test',
        'kalemler': kalemler,
    }


def _rf_kart(con, idx=0):
    rows = con.execute("""
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id, kaynak_arge_test_id
        FROM nexgen_rf_renk
        WHERE aktif=1 AND durum='ONAYLI' ORDER BY rf_kod, id
    """).fetchall()
    from modules.nexgen.cekirdek_gorunum import yeni_secimde_renk_gosterilebilir_mi
    kartlar = [dict(r) for r in rows if yeni_secimde_renk_gosterilebilir_mi(dict(r))]
    if len(kartlar) <= idx:
        return None
    return kartlar[idx]


def terlik_kalem(con, renk_idx=0, ml=1500, ms=1500, rf_renk_id=None):
    fid = con.execute(
        "SELECT MIN(f.id) FROM nexgen_formul f WHERE f.kod LIKE '1BA-FL01' AND f.aktif=1"
    ).fetchone()[0]
    rf = _rf_kart(con, renk_idx) if rf_renk_id is None else {'id': rf_renk_id}
    if not rf:
        return None
    termin = (date.today() + timedelta(days=14)).isoformat()
    return {
        'urun_ailesi': 'TERLIK',
        'formul_id': fid,
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': ml,
        'miktar_s': ms,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


def cok_plan_kalemler(con):
    """İki TERLIK kalemi (aynı geçerli RF) — MPR'de 2 plan üretir."""
    rf_row = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    if not rf_row:
        return None
    rf_id = rf_row['rf_renk_id']
    k1 = terlik_kalem(con, rf_renk_id=rf_id, ml=1200, ms=800)
    k2 = terlik_kalem(con, rf_renk_id=rf_id, ml=600, ms=400)
    return [k for k in (k1, k2) if k]


print('=' * 65)
print('BE-3E TEST — atomik çok planlı üretime gönder')
print('=' * 65)

with open(TPL, encoding='utf-8') as f:
    tpl = f.read()

for m in ['pzmSiparisUretimeGonder', 'Tüm planlar birlikte (atomik)']:
    ok('template: ' + m[:40], m in tpl)

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

rf_rows = con.execute(
    "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
    "JOIN nexgen_formul f ON f.id=u.formul_id "
    "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
).fetchall()

created_tid = None
kalemler = cok_plan_kalemler(con)
if rf_rows and kalemler and len(kalemler) >= 2:

    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'

        d_t = (c.post('/nexgen/api/pazarlama/taslak-kaydet',
                      json=v2_payload(con, kalemler)).get_json() or {})
        created_tid = d_t.get('talep_id')
        ok('taslak olustu', d_t.get('ok'), d_t.get('siparis_no'))

        d_mpr = (c.post('/nexgen/api/pazarlama/mpr-olustur',
                        json={'talep_id': created_tid}).get_json() or {})
        planlar = d_mpr.get('planlar') or []
        ok('MPR ok', d_mpr.get('ok'), d_mpr.get('hata', '')[:60])
        ok('MPR cok plan', len(planlar) >= 2, f'{len(planlar)} plan')

        if not d_mpr.get('ok') or not planlar:
            ok('atomik gonder', False, 'MPR plan yok')
        else:
            plan_ids = [p['plan_id'] for p in planlar if p.get('plan_id')]
            batch_before = con.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0]

            r_no_confirm = c.post(f'/nexgen/api/pazarlama/siparis/{created_tid}/uretime-gonder',
                                  json={})
            d_nc = r_no_confirm.get_json() or {}
            ok('confirm zorunlu', r_no_confirm.status_code == 400 and not d_nc.get('ok'))

            ok('on kontrol ON_CALISMA', plan_ids and all(
                con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (pid,)).fetchone()[0] == 'ON_CALISMA'
                for pid in plan_ids
            ))

            r_send = c.post(f'/nexgen/api/pazarlama/siparis/{created_tid}/uretime-gonder',
                            json={'confirm': True})
            d_send = r_send.get_json() or {}

            if d_send.get('ok'):
                ok('atomik gonder ok', True, f'{d_send.get("plan_sayisi")} plan')
                ok('siparis URETIMDE', d_send.get('durum') == 'URETIMDE')
                hdr = con.execute(
                    'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (created_tid,)
                ).fetchone()
                ok('hdr URETIMDE', hdr and hdr[0] == 'URETIMDE')
                for pid in plan_ids:
                    pd = con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (pid,)).fetchone()
                    ok(f'plan {pid} URETIMDE', pd and pd[0] == 'URETIMDE')
                    bk = con.execute(
                        "SELECT batch_kodu FROM nexgen_uretim_batch WHERE plan_id=? AND durum!='IPTAL'",
                        (pid,),
                    ).fetchone()
                    ok(f'plan {pid} batch', bk is not None, bk[0] if bk else '')
                batch_after = con.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0]
                ok('batch artti', batch_after >= batch_before + len(plan_ids),
                   f'{batch_before}->{batch_after}')
            elif d_send.get('stok_eksik'):
                ok('stok eksik senaryo', True, 'atomik gonderim bloklandi (beklenen)')
                batch_mid = con.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0]
                ok('rollback batch yok', batch_mid == batch_before)
                for pid in plan_ids:
                    pd = con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (pid,)).fetchone()
                    ok(f'rollback plan {pid}', pd and pd[0] == 'ON_CALISMA')
            else:
                ok('atomik gonder', False, d_send.get('hata', '?'))

            for pid in plan_ids:
                bks = con.execute(
                    "SELECT batch_kodu FROM nexgen_uretim_batch WHERE plan_id=?", (pid,)
                ).fetchall()
                for b in bks:
                    con.execute('DELETE FROM nexgen_uretim_parca WHERE batch_kodu=?', (b[0],))
                    con.execute('DELETE FROM nexgen_uretim_batch WHERE batch_kodu=?', (b[0],))
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
print('=' * 65)
sys.exit(0 if failed == 0 else 1)

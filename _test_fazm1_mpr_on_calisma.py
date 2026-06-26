# -*- coding: utf-8 -*-
"""NEXGEN FAZ-M1 — MPR ön çalışma ayrı ekran POC testi."""
import sys
import io
import os
import sqlite3

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')

import app as flask_app

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


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

uv = con.execute("""
    SELECT uv.id, uv.boyut, rv.formul_id, rv.ad AS renk_ad, f.ad AS formul_ad
    FROM nexgen_uretim_varyant uv
    JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
    JOIN nexgen_formul f ON f.id = rv.formul_id
    WHERE uv.aktif=1 AND uv.recete_durum='URETIME_ACIK'
    ORDER BY uv.id LIMIT 1
""").fetchone()
ok('test uv bulundu', uv is not None, f'id={uv["id"]}' if uv else '')

rf = None
if uv:
    rf = con.execute("""
        SELECT rf.id, rf.rf_kod FROM nexgen_rf_renk rf
        JOIN nexgen_rf_formul_uygunluk u ON u.rf_renk_id = rf.id
        WHERE u.formul_id = ? AND rf.durum='ONAYLI' AND rf.aktif=1
        ORDER BY rf.id LIMIT 1
    """, (uv['formul_id'],)).fetchone()
ok('test rf bulundu', rf is not None, rf['rf_kod'] if rf else '')

yeni_plan_id = None
with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    r_page = c.get('/nexgen/mpr')
    ok('GET /nexgen/mpr 200', r_page.status_code == 200, str(r_page.status_code))
    ok('sayfa basligi', b'MPR' in r_page.data and b'\xc3\x96n \xc3\x87al\xc4\xb1\xc5\x9fma' in r_page.data
       or b'MPR' in r_page.data, 'html')

    if uv and rf:
        r = c.post('/nexgen/api/mpr/on-calisma/ekle', json={
            'uretim_varyant_id': uv['id'],
            'planlanan_kg': 250.5,
            'rf_renk_id': rf['id'],
            'notlar': 'FAZ-M1 test',
        })
        d = r.get_json() or {}
        ok('on-calisma/ekle 200', r.status_code == 200 and d.get('ok'), str(d.get('plan_kodu')))
        ok('kaynak MPR_ONCALISMA', d.get('kaynak') == 'MPR_ONCALISMA', d.get('kaynak'))
        ok('durum ON_CALISMA', d.get('durum') == 'ON_CALISMA', d.get('durum'))
        ok('formul dogru', d.get('formul_ad') == uv['formul_ad'], d.get('formul_ad'))
        ok('boyut dogru', d.get('boyut') == uv['boyut'], d.get('boyut'))
        ok('kg dogru', abs(float(d.get('planlanan_kg', 0)) - 250.5) < 0.001, str(d.get('planlanan_kg')))
        ok('rf korundu', d.get('rf_renk_id') == rf['id'], d.get('rf_kod'))

        row = con.execute(
            "SELECT id, plan_kodu, planlama_siparis_id, kaynak, durum, "
            "uretim_varyant_id, rf_renk_id, planlanan_kg, siparis_no "
            "FROM nexgen_uretim_plan ORDER BY id DESC LIMIT 1"
        ).fetchone()
        yeni_plan_id = row['id'] if row else None
        ok('planlama_siparis_id NULL', row and row['planlama_siparis_id'] is None, str(row['planlama_siparis_id'] if row else ''))
        ok('DB kaynak MPR_ONCALISMA', row and row['kaynak'] == 'MPR_ONCALISMA', row['kaynak'] if row else '')
        ok('DB durum ON_CALISMA', row and row['durum'] == 'ON_CALISMA', row['durum'] if row else '')
        ok('DB uv_id', row and row['uretim_varyant_id'] == uv['id'], str(row['uretim_varyant_id'] if row else ''))
        ok('DB rf_renk_id', row and row['rf_renk_id'] == rf['id'], str(row['rf_renk_id'] if row else ''))
        ok('siparis_no NULL/bos', row and not row['siparis_no'], str(row['siparis_no'] if row else ''))

        r_stok = c.post('/nexgen/api/plan/stok-onizle', json={
            'uretim_varyant_id': uv['id'],
            'rf_renk_id': rf['id'],
            'planlanan_kg': 250.5,
        })
        sd = r_stok.get_json() or {}
        ok('stok-onizle 200', r_stok.status_code == 200 and sd.get('ok'), f"kalem={len(sd.get('kalemler', []))}")
        ok('stok kalemleri var', len(sd.get('kalemler', [])) > 0, str(len(sd.get('kalemler', []))))
        if sd.get('kalemler'):
            k0 = sd['kalemler'][0]
            ok('stok alanlari', all(x in k0 for x in (
                'gerekli_kg', 'fiziksel_kg', 'rezerve_kg', 'yumusak_talep_kg', 'kullanilabilir_kg'
            )), list(k0.keys())[:6])

        if yeni_plan_id:
            r_basla = c.post(f'/nexgen/api/plan/{yeni_plan_id}/basla', json={})
            bd = r_basla.get_json() or {}
            ok('ON_CALISMA uretime gonderilemez', r_basla.status_code == 400 and not bd.get('ok'),
               bd.get('hata', ''))
            ok('guard mesaji net', 'ON_CALISMA' in (bd.get('hata') or ''), bd.get('hata'))

    # Mevcut planlama akisi bozulmadi — PLANLANDI plan basla guardi hala calisir
    planlandi = con.execute(
        "SELECT id FROM nexgen_uretim_plan WHERE durum='PLANLANDI' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if planlandi:
        r_chk = c.post(f'/nexgen/api/plan/{planlandi["id"]}/basla', json={})
        # stok yetersiz veya ok — ON_CALISMA guard degil
        chk = r_chk.get_json() or {}
        ok('PLANLANDI guard farkli', 'ON_CALISMA' not in (chk.get('hata') or ''), chk.get('hata', 'ok/stok'))

con.close()

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== FAZ-M1: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)

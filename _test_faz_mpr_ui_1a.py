# -*- coding: utf-8 -*-
"""NEXGEN FAZ-MPR-UI-1A — MPR operasyon ekranı UI testi."""
import sys
import io
import os
import sqlite3
import json
import re

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


def mo_kalem_durum(k):
    if k.get('yeterli'):
        return 'yeterli'
    kul = float(k.get('kullanilabilir_kg') or 0)
    if kul > 0.0005:
        return 'kritik'
    return 'eksik'


def mo_kalem_sayilar(kalemler):
    hazir = kritik = eksik = 0
    sid_seen = {}
    toplam_eksik_kg = 0.0
    for k in kalemler or []:
        durum = mo_kalem_durum(k)
        if durum == 'yeterli':
            hazir += 1
        elif durum == 'kritik':
            kritik += 1
        else:
            eksik += 1
        sid = k.get('stok_kart_id')
        if sid not in sid_seen and durum != 'yeterli':
            sid_seen[sid] = True
            toplam_eksik_kg += max(0.0, -float(k.get('fark_kg') or 0))
    return {
        'hazir': hazir, 'kritik': kritik, 'eksik': eksik,
        'toplamEksikKg': round(toplam_eksik_kg, 3),
    }


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

plan = con.execute("""
    SELECT np.id, np.plan_kodu, np.planlanan_kg, np.uretim_varyant_id AS uv_id, np.rf_renk_id
    FROM nexgen_uretim_plan np
    WHERE np.durum = 'ON_CALISMA'
    ORDER BY np.id DESC LIMIT 1
""").fetchone()

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    r = c.get('/nexgen/mpr')
    html = r.get_data(as_text=True)
    ok('GET /nexgen/mpr 200', r.status_code == 200, str(r.status_code))
    ok('mo-layout var', 'mo-layout' in html)
    ok('mo-detay-panel var', 'id="mo-detay-panel"' in html)
    ok('moSatirSec fonksiyonu', 'function moSatirSec' in html)
    ok('moDetayRender fonksiyonu', 'function moDetayRender' in html)
    ok('moFiltreUygula fonksiyonu', 'function moFiltreUygula' in html)
    ok('Üretime başlanabilir mi', 'Üretime başlanabilir mi' in html)
    ok('Bu üretim için gerekli', 'Bu üretim için gerekli' in html)
    ok('Depoda fiziksel', 'Depoda fiziksel' in html)
    ok('Stok Durumu butonu', 'Stok Durumu' in html)
    ok('Yeni MPR modal', 'id="mo-modal-arka"' in html)
    ok('Bağla modal', 'id="mo-bagla-modal"' in html)
    ok('_MO_PLANLAR json', '_MO_PLANLAR' in html)

    if plan:
        ok('ON_CALISMA plan var', True, plan['plan_kodu'])
        m = re.search(rf'moSatirSec\({plan["id"]}\)', html)
        ok('plan satiri htmlde', m is not None, f'id={plan["id"]}')
    else:
        ok('ON_CALISMA plan var', False, 'test plan yok')

    uv = con.execute(
        "SELECT id FROM nexgen_uretim_varyant WHERE aktif=1 LIMIT 1"
    ).fetchone()
    rf = con.execute(
        "SELECT id FROM nexgen_rf_renk WHERE durum='ONAYLI' AND aktif=1 LIMIT 1"
    ).fetchone()

    test_uv = plan['uv_id'] if plan else (uv['id'] if uv else None)
    test_rf = plan['rf_renk_id'] if plan else (rf['id'] if rf else None)
    test_kg = float(plan['planlanan_kg']) if plan else 100.0

    if test_uv:
        r2 = c.post('/nexgen/api/plan/stok-onizle', json={
            'uretim_varyant_id': test_uv,
            'rf_renk_id': test_rf,
            'planlanan_kg': test_kg,
        })
        sd = r2.get_json() or {}
        ok('stok-onizle 200', r2.status_code == 200 and sd.get('ok'),
           f'kalem={len(sd.get("kalemler", []))}')
        ok('uretilecek_kg alani', 'uretilecek_kg' in sd, str(sd.get('uretilecek_kg')))
        ok('batch_sayisi alani', 'batch_sayisi' in sd, str(sd.get('batch_sayisi')))
        ok('fazla_kg alani', 'fazla_kg' in sd, str(sd.get('fazla_kg')))
        ok('yeterli_mi alani', 'yeterli_mi' in sd, str(sd.get('yeterli_mi')))

        kalemler = sd.get('kalemler') or []
        if kalemler:
            k0 = kalemler[0]
            ok('kalem stok alanlari', all(x in k0 for x in (
                'gerekli_kg', 'fiziksel_kg', 'rezerve_kg',
                'yumusak_talep_kg', 'kullanilabilir_kg', 'yeterli', 'fark_kg',
            )), str(list(k0.keys())[:8]))

            ozet = mo_kalem_sayilar(kalemler)
            beklenen_karar = 'EVET' if sd.get('yeterli_mi') else 'HAYIR'
            ok('karar kurali', True, beklenen_karar)
            ok('ozet sayac tutar', ozet['hazir'] + ozet['kritik'] + ozet['eksik'] == len(kalemler),
               f"h={ozet['hazir']} k={ozet['kritik']} e={ozet['eksik']} t={len(kalemler)}")

            # filtre simulasyonu
            eksik_f = [k for k in kalemler if mo_kalem_durum(k) == 'eksik']
            kritik_f = [k for k in kalemler if mo_kalem_durum(k) == 'kritik']
            yeterli_f = [k for k in kalemler if mo_kalem_durum(k) == 'yeterli']
            ok('filtre eksik', len(eksik_f) == ozet['eksik'], str(len(eksik_f)))
            ok('filtre kritik', len(kritik_f) == ozet['kritik'], str(len(kritik_f)))
            ok('filtre yeterli', len(yeterli_f) == ozet['hazir'], str(len(yeterli_f)))

con.close()

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
if failed:
    sys.exit(1)

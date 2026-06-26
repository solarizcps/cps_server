# -*- coding: utf-8 -*-
"""NEXGEN FAZ-PILOT-1 — MPR → Planlama Siparişi bağlama + uçtan uca pilot."""
import sys
import io
import os
import sqlite3
from datetime import date, timedelta

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')

import app as flask_app
from modules.nexgen.routes import _mpr_stok_ihtiyac_hesapla

_app = flask_app.app
_app.config['TESTING'] = True
results = []
pilot_plan_id = None
pilot_ps_id = None


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
    SELECT uv.id, rv.ad AS renk_ad, uv.boyut, f.ad AS formul_ad
    FROM nexgen_uretim_varyant uv
    JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id
    JOIN nexgen_formul f ON f.id=rv.formul_id
    WHERE f.ad='AYM TABAN' AND rv.ad='RECON RENK 65919' AND uv.boyut='SMALL'
      AND uv.recete_durum='URETIME_ACIK' AND uv.aktif=1
""").fetchone()
ok('pilot uv (RECON SMALL)', uv is not None, f'id={uv["id"]}' if uv else '')

rf = con.execute(
    "SELECT id, rf_kod FROM nexgen_rf_renk WHERE rf_kod='RF-004' AND durum='ONAYLI'"
).fetchone()
ok('pilot rf RF-004', rf is not None, rf['rf_kod'] if rf else '')

cari = con.execute(
    "SELECT id, unvan FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1"
).fetchone()
ok('test cari', cari is not None, cari['unvan'] if cari else '')

termin = (date.today() + timedelta(days=1)).isoformat()

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    # 1) MPR oluştur
    r_mpr = c.post('/nexgen/api/mpr/on-calisma/ekle', json={
        'uretim_varyant_id': uv['id'],
        'rf_renk_id': rf['id'],
        'planlanan_kg': 200,
        'notlar': 'FAZ-PILOT-1 test',
    })
    md = r_mpr.get_json() or {}
    ok('MPR oluştur 200', r_mpr.status_code == 200 and md.get('ok'), md.get('plan_kodu'))
    ok('MPR durum ON_CALISMA', md.get('durum') == 'ON_CALISMA', md.get('durum'))
    pilot_plan_id = md.get('plan_id')

    # 2) Stok analizi
    r_stok = c.post('/nexgen/api/plan/stok-onizle', json={
        'uretim_varyant_id': uv['id'],
        'rf_renk_id': rf['id'],
        'planlanan_kg': 200,
    })
    sd = r_stok.get_json() or {}
    ok('stok yeterli_mi=True', sd.get('yeterli_mi') is True, f"eksik={sd.get('eksik_sayisi')}")
    ok('stok eksik_sayisi=0', sd.get('eksik_sayisi') == 0, str(sd.get('eksik_sayisi')))

    stok_fn = _mpr_stok_ihtiyac_hesapla(con, uv['id'], rf['id'], 200)
    ok('MPR fn yeterli_mi', stok_fn.get('yeterli_mi') is True, str(stok_fn.get('eksik_sayisi')))

    # 3) ON_CALISMA üretime gönderilemez
    r_guard = c.post(f'/nexgen/api/plan/{pilot_plan_id}/basla', json={})
    gd = r_guard.get_json() or {}
    ok('ON_CALISMA basla engellendi', r_guard.status_code == 400 and not gd.get('ok'),
       gd.get('hata', ''))

    # 4) Plan siparişine bağla (yeni header)
    r_bagla = c.post(f'/nexgen/api/mpr/{pilot_plan_id}/siparise-bagla', json={
        'cari_id': cari['id'],
        'termin_tarihi': termin,
        'not': 'FAZ-PILOT-1 bağlama',
        'talep_referansi': 'PILOT-TEST-1',
    })
    bd = r_bagla.get_json() or {}
    ok('siparise-bagla 200', r_bagla.status_code == 200 and bd.get('ok'), bd.get('siparis_no'))
    ok('durum PLANLANDI', bd.get('durum') == 'PLANLANDI', bd.get('durum'))
    ok('planlama_siparis_id dolu', bool(bd.get('planlama_siparis_id')), str(bd.get('planlama_siparis_id')))
    ok('stok ozet yeterli', bd.get('stok_yeterli_mi') is True, str(bd.get('stok_eksik_sayisi')))
    pilot_ps_id = bd.get('planlama_siparis_id')

    row = con.execute(
        "SELECT durum, planlama_siparis_id, siparis_no, musteri_adi, kaynak, cari_id "
        "FROM nexgen_uretim_plan WHERE id=?", (pilot_plan_id,)
    ).fetchone()
    ok('DB durum PLANLANDI', row and row['durum'] == 'PLANLANDI', row['durum'] if row else '')
    ok('DB planlama_siparis_id', row and row['planlama_siparis_id'] == pilot_ps_id,
       str(row['planlama_siparis_id'] if row else ''))
    ok('DB kaynak korundu', row and row['kaynak'] == 'MPR_ONCALISMA', row['kaynak'] if row else '')
    ok('DB siparis_no dolu', row and row['siparis_no'], row['siparis_no'] if row else '')

    # 5) Duplicate bağlama engeli
    r_dup = c.post(f'/nexgen/api/mpr/{pilot_plan_id}/siparise-bagla', json={
        'cari_id': cari['id'], 'termin_tarihi': termin,
    })
    dd = r_dup.get_json() or {}
    ok('duplicate baglama engellendi', r_dup.status_code == 400 and not dd.get('ok'), dd.get('hata'))

    # 6) MPR listesinde görünmez, planlama ekranında görünür
    r_mpr_page = c.get('/nexgen/mpr')
    ok('GET /nexgen/mpr 200', r_mpr_page.status_code == 200, str(r_mpr_page.status_code))
    pk = (md.get('plan_kodu') or '').encode('utf-8')
    ok('MPR sayfasinda plan yok', pk not in r_mpr_page.data, md.get('plan_kodu'))

    r_plan_page = c.get('/nexgen/uretim-plan')
    ok('GET /nexgen/uretim-plan 200', r_plan_page.status_code == 200, str(r_plan_page.status_code))
    ok('Planlama sayfasinda plan var', pk in r_plan_page.data, md.get('plan_kodu'))

    # 7) Planlama stok-onizle = MPR stok-onizle
    r_stok2 = c.post('/nexgen/api/plan/stok-onizle', json={
        'uretim_varyant_id': uv['id'],
        'rf_renk_id': rf['id'],
        'planlanan_kg': 200,
    })
    sd2 = r_stok2.get_json() or {}
    ok('planlama stok yeterli_mi', sd2.get('yeterli_mi') is True, str(sd2.get('eksik_sayisi')))
    ok('stok sonucu ayni', sd.get('yeterli_mi') == sd2.get('yeterli_mi')
       and sd.get('eksik_sayisi') == sd2.get('eksik_sayisi'), 'match')

    # 8) Üretime gönder → depo hazırlık
    r_basla = c.post(f'/nexgen/api/plan/{pilot_plan_id}/basla', json={
        'notlar': 'FAZ-PILOT-1 uretim test',
    })
    basla = r_basla.get_json() or {}
    ok('PLANLANDI basla 200', r_basla.status_code == 200 and basla.get('ok'),
       basla.get('batch_kodu', basla.get('hata')))
    batch_kodu = basla.get('batch_kodu')

    plan_after = con.execute(
        "SELECT durum FROM nexgen_uretim_plan WHERE id=?", (pilot_plan_id,)
    ).fetchone()
    ok('plan durum BASLADI', plan_after and plan_after['durum'] == 'BASLADI',
       plan_after['durum'] if plan_after else '')

    if batch_kodu:
        depo = con.execute(
            "SELECT id, hazirlik_no, durum, plan_id, planlama_siparis_id, batch_kodu "
            "FROM nexgen_depo_hazirlik WHERE batch_kodu=? ORDER BY id DESC LIMIT 1",
            (batch_kodu,),
        ).fetchone()
        ok('depo hazirlik olustu', depo is not None, depo['hazirlik_no'] if depo else '')
        ok('depo plan_id dogru', depo and depo['plan_id'] == pilot_plan_id,
           str(depo['plan_id'] if depo else ''))
        ok('depo ps_id dogru', depo and depo['planlama_siparis_id'] == pilot_ps_id,
           str(depo['planlama_siparis_id'] if depo else ''))
        kalem_n = con.execute(
            "SELECT COUNT(*) c FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?",
            (depo['id'],),
        ).fetchone()[0] if depo else 0
        ok('depo kalemleri var', kalem_n > 0, str(kalem_n))

    # 9) İptal MPR bağlanamaz
    con.execute(
        "INSERT INTO nexgen_uretim_plan "
        "(plan_kodu,kaynak,uretim_varyant_id,planlanan_kg,oncelik_sira,plan_tarihi,durum,created_by) "
        "VALUES ('NP-TEST-IPTAL','MPR_ONCALISMA',?,?,10,date('now'),'IPTAL',1)",
        (uv['id'], 50.0),
    )
    iptal_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    r_iptal = c.post(f'/nexgen/api/mpr/{iptal_id}/siparise-bagla', json={
        'cari_id': cari['id'], 'termin_tarihi': termin,
    })
    idd = r_iptal.get_json() or {}
    ok('IPTAL MPR baglanamaz', r_iptal.status_code == 400 and not idd.get('ok'), idd.get('hata'))

    # 10) planlama-siparis/liste API
    r_liste = c.get('/nexgen/api/planlama-siparis/liste')
    ld = r_liste.get_json() or {}
    ok('planlama siparis liste', r_liste.status_code == 200 and ld.get('ok'),
       f"adet={len(ld.get('liste', []))}")

    # 11) UI bagla butonu
    ok('MPR html bagla butonu', b'Plan Sipari' in r_mpr_page.data
       and b'siparise-bagla' in r_mpr_page.data or b'moBaglaAc' in r_mpr_page.data,
       'ui')

con.close()

passed = sum(1 for _, cnd, _ in results if cnd)
failed = sum(1 for _, cnd, _ in results if not cnd)
print(f'\n=== FAZ-PILOT-1: {passed}/{len(results)} PASS, {failed} FAIL ===')
if pilot_plan_id:
    print(f'Pilot plan_id={pilot_plan_id} ps_id={pilot_ps_id}')
sys.exit(1 if failed else 0)

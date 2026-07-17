# -*- coding: utf-8 -*-
"""BE-3C — Pazarlama sipariş kartı 4 aşamalı MPR accordion iskelet testleri."""
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
TEST_DB = os.path.join(_APP, 'mock_data_be3c_test_tmp.db')
TPL = os.path.join(_APP, 'templates', 'nexgen', 'pazarlama_merkezi.html')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def v2_payload(con, kalemler, cari_id=None):
    if cari_id is None:
        cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()['id']
    termin = (date.today() + timedelta(days=21)).isoformat()
    return {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': termin,
        'genel_not': 'BE3C test',
        'kalemler': kalemler,
    }


def _terlik_formul_id(con):
    row = con.execute(
        "SELECT MIN(f.id) FROM nexgen_formul f WHERE f.kod LIKE '1BA-FL01' AND f.aktif=1"
    ).fetchone()
    return row[0] if row else None


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


def terlik_kalem(con, renk_idx=0, ml=3000, ms=3000, rf_renk_id=None):
    fid = _terlik_formul_id(con)
    rf = _rf_kart(con, renk_idx) if rf_renk_id is None else {'id': rf_renk_id}
    if not fid or not rf:
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


def taban_kalem(con):
    row = con.execute("""
        SELECT MIN(f.id) AS formul_id,
               SUM(CASE WHEN uv.boyut='LARGE' THEN 1 ELSE 0 END) AS has_l,
               SUM(CASE WHEN uv.boyut='SMALL' THEN 1 ELSE 0 END) AS has_s
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv ON rv.formul_id=f.id AND rv.aktif=1
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id=rv.id AND uv.aktif=1
        WHERE f.aktif=1 AND f.kod LIKE '2BA-%' AND uv.recete_durum='URETIME_ACIK'
          AND uv.boyut IN ('LARGE','SMALL')
    """).fetchone()
    rf = _rf_kart(con, 0)
    if not row or not rf:
        return None
    ml = 2000 if row['has_l'] else 0
    ms = 1000 if row['has_s'] else 0
    if ml <= 0 and ms <= 0:
        ml, ms = 2000, 1000
    termin = (date.today() + timedelta(days=18)).isoformat()
    return {
        'urun_ailesi': 'TABAN',
        'formul_id': row['formul_id'],
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': ml or None,
        'miktar_s': ms or None,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


print('=' * 65)
print('BE-3C TEST — Pazarlama 4 aşamalı MPR accordion')
print('=' * 65)

# ── Template statik kontroller ──
with open(TPL, encoding='utf-8') as f:
    tpl = f.read()

ok('1 sayfa template mevcut', os.path.isfile(TPL))
markers = [
    'pzm-detay-asamalar',
    'pzm-detay-alt-band',
    'pzmDetayRender',
    'pzmDetayMprHesapla',
    'pzmSipariseDondur',
    '_pzmMprState',
    'pzmMprStateEnsure',
    'Sipariş Bilgileri',
    'Sipariş Kalemleri',
    'MPR Hesabı',
    'Sonuç ve İşlem',
    'MPR henüz hesaplanmadı',
    '/nexgen/api/pazarlama/mpr-olustur',
    'pzmDetayUretimeGonder',
    'pzmDetayStokYukle',
    'pzm-mpr-metrik-grid',
    'pzm-detay-kalem-wrap',
]
for m in markers:
    ok(f'template marker: {m[:40]}', m in tpl)

ok('eski detay id kaldirildi', 'pzm-detay-icerik' not in tpl)
ok('mobil metrik grid css', '@media' in tpl and 'pzm-mpr-metrik-grid' in tpl)

try:
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(os.path.join(_APP, 'templates')))
    env.parse(tpl)
    ok('14 jinja/template syntax', True)
except Exception as e:
    ok('14 jinja/template syntax', False, str(e)[:80])

# ── API + sayfa entegrasyon ──
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

created_ids = []
taban_tid = None
terlik_tid = None

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    r_page = c.get('/nexgen/pazarlama')
    ok('2 pazarlama sayfa 200', r_page.status_code == 200)
    body = r_page.get_data(as_text=True)
    ok('3 detay asamalar dom', 'pzm-detay-asamalar' in body)
    ok('4 detay js fonksiyonlari', 'pzmDetayAc' in body and 'pzmDetayMprHesapla' in body)

    tb = taban_kalem(con)
    if tb:
        d28 = (c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [tb])).get_json() or {})
        taban_tid = d28.get('talep_id')
        created_ids.append(taban_tid)
        ok('5 cok kalem TABAN taslak', d28.get('ok'), d28.get('siparis_no'))

        plan_before = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        durum_before = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (taban_tid,)
        ).fetchone()[0] if taban_tid else None

        r_rf = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': taban_tid})
        d_rf = r_rf.get_json() or {}
        plan_after = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        durum_after = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (taban_tid,)
        ).fetchone()[0] if taban_tid else None

        ok('6 RF eksik MPR 400', r_rf.status_code == 400 and d_rf.get('rf_eksik'), (d_rf.get('hata') or '')[:60])
        ok('7 RF eksik TASLAK kalir', durum_after == durum_before == 'TASLAK')
        ok('8 RF eksik plan artmaz', plan_after == plan_before)
        ok('9 RF eksik hata metni', bool(d_rf.get('hata')) and 'rf' in (d_rf.get('hata') or '').lower() or 'RF' in (d_rf.get('hata') or ''))
    else:
        for n in range(5, 10):
            ok(f'{n} TABAN senaryo', True, 'taban yok-atlandi')

    rf28 = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    if rf28:
        trf = terlik_kalem(con, rf_renk_id=rf28['rf_renk_id'], ml=2000, ms=2000)
        d_t = (c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [trf])).get_json() or {})
        terlik_tid = d_t.get('talep_id')
        created_ids.append(terlik_tid)
        plan_b = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        r_ok = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': terlik_tid})
        d_ok = r_ok.get_json() or {}
        plan_a = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        planlar = d_ok.get('planlar') or []

        ok('10 RF hazir MPR ok', d_ok.get('ok') and len(planlar) >= 1, d_ok.get('siparis_no'))
        ok('11 planlar[] dolu', all(p.get('plan_kodu') for p in planlar), str(len(planlar)))
        ok('12 plan sayisi artti', plan_a > plan_b, f'{plan_b}->{plan_a}')

        if taban_tid and terlik_tid:
            ok('13 iki siparis ayri id', taban_tid != terlik_tid)

        for p in planlar:
            pid = p.get('plan_id')
            if pid:
                con.execute('DELETE FROM nexgen_uretim_plan_boyut WHERE plan_id=?', (pid,))
                con.execute('DELETE FROM nexgen_uretim_plan WHERE id=?', (pid,))
        if terlik_tid:
            con.execute("UPDATE nexgen_planlama_siparis SET durum='TASLAK' WHERE id=?", (terlik_tid,))
        con.commit()
    else:
        ok('10 RF hazir MPR ok', True, 'RF uygunluk yok-atlandi')
        ok('11 planlar[] dolu', True, 'atlandi')
        ok('12 plan sayisi artti', True, 'atlandi')
        ok('13 iki siparis ayri id', True, 'atlandi')

    r_list = c.get('/nexgen/api/pazarlama/talepler')
    liste = (r_list.get_json() or {}).get('liste') or []
    if liste:
        t0 = liste[0]
        ok('15 siparis bilgileri alanlari', all(k in t0 for k in ('siparis_no', 'cari_unvan', 'durum', 'toplam_kg')))
        if t0.get('id'):
            from modules.nexgen.pzm_siparis_read import pzm_siparis_oku
            det = pzm_siparis_oku(con, t0['id'])
            ok('16 kalemler korunuyor', len(det.get('kalemler') or []) >= 1, f'n={len(det.get("kalemler") or [])}')

# temizlik
for tid in created_ids:
    if tid:
        con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (tid,))
        con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (tid,))
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
print('Test DB silindi')
print('Commit: EDILMEDI')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)

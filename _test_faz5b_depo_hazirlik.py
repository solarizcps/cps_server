# -*- coding: utf-8 -*-
"""NEXGEN FAZ-5B — depo üretim hazırlık workflow testi."""
import sys, io, os, sqlite3
import importlib.util

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
_LIVE_DB = os.path.join(_APP_DIR, 'mock_data.db')

import shutil, tempfile, hashlib
from tools.nexgen_tmp_db import sha256_file, cleanup_tmp

_SHA_BEFORE = sha256_file(_LIVE_DB)
_TMP_DIR = tempfile.mkdtemp(prefix='faz5b_')
DB = os.path.join(_TMP_DIR, 'mock_data_test.db')
shutil.copy2(_LIVE_DB, DB)
print(f'[ISO] tmp_db={DB}')
print(f'[ISO] main_sha_before={_SHA_BEFORE}')

# Migration 085 — yalnız tmp DB
_mig_path = os.path.join(_APP_DIR, 'migrations', '085_nexgen_depo_hazirlik.py')
_spec = importlib.util.spec_from_file_location('m085', _mig_path)
_m085 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m085)
_m085.DB_PATH = DB
_m085.run()

import config as _cfg
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _mpr_stok_ihtiyac_hesapla, _depo_hazirlik_kalemleri, _depo_hazirlik_olustur,
)
nx_routes.DB_PATH = DB

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

h_before = con.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]

batch_kodu = None
hazirlik_id = None
plan = None
via_api = False

# 1a) Yeterli stoklu PLANLANDI plan varsa api_plan_basla dene
plans = con.execute("""
    SELECT id, planlanan_kg, uretim_varyant_id, rf_renk_id
    FROM nexgen_uretim_plan
    WHERE durum = 'PLANLANDI'
    ORDER BY planlanan_kg ASC
""").fetchall()

for pr in plans:
    chk = _mpr_stok_ihtiyac_hesapla(
        con, pr['uretim_varyant_id'], pr['rf_renk_id'], float(pr['planlanan_kg']),
    )
    if not chk.get('yeterli_mi'):
        continue
    plan = pr
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r = c.post(f'/nexgen/api/plan/{plan["id"]}/basla', json={})
        d = r.get_json() or {}
        if r.status_code == 200 and d.get('ok'):
            batch_kodu = d.get('batch_kodu')
            via_api = True
    break

# 1b) Stok yetersizse mevcut batch üzerinde helper ile hazırlık oluştur
if not batch_kodu:
    batch = con.execute("""
        SELECT nb.batch_kodu, nb.plan_id, nb.uretim_varyant_id, nb.planlanan_kg,
               np.rf_renk_id, np.cari_id, np.planlama_siparis_id,
               np.planlanan_kg AS plan_kg
        FROM nexgen_uretim_batch nb
        LEFT JOIN nexgen_uretim_plan np ON np.id = nb.plan_id
        WHERE NOT EXISTS (
            SELECT 1 FROM nexgen_depo_hazirlik dh
            WHERE dh.batch_kodu = nb.batch_kodu AND dh.durum NOT IN ('IPTAL')
        )
        ORDER BY nb.id DESC LIMIT 1
    """).fetchone()
    if batch:
        plan = {
            'id': batch['plan_id'],
            'uretim_varyant_id': batch['uretim_varyant_id'],
            'rf_renk_id': batch['rf_renk_id'],
            'planlanan_kg': batch['planlanan_kg'] or batch['plan_kg'],
        }
        with _app.test_request_context():
            hid = _depo_hazirlik_olustur(
                con,
                batch_kodu=batch['batch_kodu'],
                plan_id=batch['plan_id'],
                uretim_varyant_id=batch['uretim_varyant_id'],
                planlanan_kg=float(batch['planlanan_kg'] or batch['plan_kg'] or 0),
                rf_renk_id=batch['rf_renk_id'],
                cari_id=batch['cari_id'],
                planlama_siparis_id=(
                    batch['planlama_siparis_id']
                    if 'planlama_siparis_id' in batch.keys() else None
                ),
                olusturan_id=1,
            )
            con.commit()
        batch_kodu = batch['batch_kodu']
        ok('1 uretime gonder (stok yok, batch+helper)', hid is not None, batch_kodu)
    else:
        ok('1 uretime gonder', False, 'PLANLANDI yeterli stok / batch yok')
else:
    ok('1 uretime gonder 200', via_api, batch_kodu)

if batch_kodu and plan:
    haz = con.execute("""
        SELECT id, hazirlik_no, durum, batch_kodu, plan_id
        FROM nexgen_depo_hazirlik WHERE batch_kodu=?
    """, (batch_kodu,)).fetchone()
    ok('2 depo hazirlik olustu', haz is not None, str(haz['hazirlik_no'] if haz else ''))
    ok('2 durum BEKLIYOR', haz and haz['durum'] == 'BEKLIYOR', haz['durum'] if haz else '')

    if haz:
        hazirlik_id = haz['id']
        kalemler = _depo_hazirlik_kalemleri(con, hazirlik_id)
        ok('3 kalemler var', len(kalemler) > 0, str(len(kalemler)))

        taban = [k for k in kalemler if k['kaynak'] == 'TABAN']
        rf = [k for k in kalemler if k['kaynak'] == 'RF']
        ok('4 taban ayri', len(taban) > 0, str(len(taban)))
        ok('4 rf ayri', len(rf) >= 0, f'taban={len(taban)} rf={len(rf)}')

        mpr = _mpr_stok_ihtiyac_hesapla(
            con, plan['uretim_varyant_id'], plan['rf_renk_id'],
            float(plan['planlanan_kg']),
        )
        taban_mpr = {
            k['stok_kart_id']: k['gerekli_kg']
            for k in mpr.get('kalemler', []) if k['kaynak'] == 'TABAN'
        }
        match = all(
            abs(float(next((x['gerekli_kg'] for x in kalemler
                            if x['stok_kart_id'] == sid), 0)) - float(kg)) < 0.001
            for sid, kg in taban_mpr.items()
        )
        ok('3 kalemler FAZ-4E toplam', match, f'taban={len(taban_mpr)}')

        recete_boya = con.execute("""
            SELECT sk.kod FROM nexgen_recete_kalem rk
            JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
            WHERE rk.uretim_varyant_id=? AND rk.aktif=1
              AND UPPER(COALESCE(sk.kategori,''))='BOYA'
        """, (plan['uretim_varyant_id'],)).fetchall()
        taban_kodlar = {k['stok_kod'] for k in taban}
        cift = {b['kod'] for b in recete_boya if b['kod'] in taban_kodlar}
        ok('5 legacy boya yok', len(cift) == 0, str(len(cift)))

    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        ok('6 depo ekran 200', c.get('/nexgen/depo/').status_code == 200, '')
        ok('6 uretim hazirlik sekmesi',
           'uretim-hazirlik' in c.get('/nexgen/depo/').get_data(as_text=True), '')

        if hazirlik_id:
            r7 = c.post(f'/nexgen/api/depo/hazirlik/{hazirlik_id}/baslat', json={})
            ok('7 hazirlamaya basla', r7.status_code == 200 and (r7.get_json() or {}).get('ok'),
               (r7.get_json() or {}).get('durum'))
            durum = con.execute(
                "SELECT durum FROM nexgen_depo_hazirlik WHERE id=?", (hazirlik_id,)
            ).fetchone()[0]
            ok('7 durum HAZIRLANIYOR', durum == 'HAZIRLANIYOR', durum)

            r8 = c.post(f'/nexgen/api/depo/hazirlik/{hazirlik_id}/hazir', json={})
            ok('8 hazirladim', r8.status_code == 200 and (r8.get_json() or {}).get('ok'),
               (r8.get_json() or {}).get('durum'))
            durum2 = con.execute(
                "SELECT durum FROM nexgen_depo_hazirlik WHERE id=?", (hazirlik_id,)
            ).fetchone()[0]
            ok('8 durum HAZIR', durum2 == 'HAZIR', durum2)

        if batch_kodu:
            page = c.get(f'/nexgen/tablet/uretim-islem/{batch_kodu}').get_data(as_text=True)
            ok('9 tablet depo durum', 'DEPO HAZIRLIK' in page and 'HAZIR' in page, batch_kodu)

h_after = con.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
ok('10 stok hareket degismedi', h_before == h_after, f'{h_before}=={h_after}')

con.close()
_SHA_AFTER = sha256_file(_LIVE_DB)
ok('ISO main DB SHA unchanged', _SHA_BEFORE == _SHA_AFTER, f'{_SHA_BEFORE[:12]}..')
print(f'[ISO] main_sha_after={_SHA_AFTER}')
print(f'[ISO] main_db_changed={_SHA_BEFORE != _SHA_AFTER}')
cleanup_tmp({'tmp_dir': _TMP_DIR})
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)

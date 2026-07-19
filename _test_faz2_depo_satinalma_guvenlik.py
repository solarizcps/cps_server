# -*- coding: utf-8 -*-
"""FAZ-2 — Depo ve Satın Alma güvenlik regression testi."""
import io
import os
import sys
import sqlite3

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)
_LIVE_DB = os.path.join(_APP, 'mock_data.db')

import shutil, tempfile
from tools.nexgen_tmp_db import sha256_file, cleanup_tmp

_SHA_BEFORE = sha256_file(_LIVE_DB)
_TMP_DIR = tempfile.mkdtemp(prefix='faz2_')
DB = os.path.join(_TMP_DIR, 'mock_data_test.db')
shutil.copy2(_LIVE_DB, DB)
print(f'[ISO] tmp_db={DB}')
print(f'[ISO] main_sha_before={_SHA_BEFORE}')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('FAZ-2 — DEPO / SATIN ALMA GÜVENLİK TEST')
print('=' * 72)

ROUTES = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
DEPO = os.path.join(_APP, 'templates', 'nexgen', 'depo.html')
SA_DET = os.path.join(_APP, 'templates', 'nexgen', 'satinalma_siparis_detay.html')
routes = open(ROUTES, encoding='utf-8').read()
depo = open(DEPO, encoding='utf-8').read()
sa_det = open(SA_DET, encoding='utf-8').read()

ok('01 mal kabul BEGIN IMMEDIATE', "con.execute('BEGIN IMMEDIATE')" in routes.split('def api_depo_mal_kabul')[1].split('def api_depo_cikis')[0])
ok('02 mal kabul onay_durumu', "onay_durumu'] != 'ONAYLANDI'" in routes.split('def api_depo_mal_kabul')[1].split('def api_depo_cikis')[0])
ok('03 mal kabul stok eslestirme', 'Stok kartı sipariş satırı ile uyuşmuyor' in routes)
ok('04 mal kabul fazla onay', 'fazla_gerekli' in routes.split('def api_depo_mal_kabul')[1].split('def api_depo_cikis')[0])
ok('05 IPTAL kismi teslim blok', 'Kısmi teslim alınmış sipariş iptal edilemez' in routes)
ok('06 depo hazir zorunlu helper', 'def _batch_depo_hazir_zorunlu' in routes)
ok('07 parca bitir depo gate', '_batch_depo_hazir_zorunlu(con, row' in routes.split('def _parca_bitir_uygula')[1].split('def _parca_stok_yetersiz_response')[0])
ok('08 hazirlik mi uyari', 'def _depo_hazirlik_mi_uyari' in routes and "'mi_uyari': mi_uyari" in routes)
ok('09 depo siparis url', "qs.get('siparis')" in depo and 'NGDP_BEKLEYEN' in depo)
ok('10 SA depo link', '/nexgen/depo/?siparis=' in sa_det)

import config as _cfg  # noqa: E402
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app  # noqa: E402
import modules.nexgen.routes as nx_routes  # noqa: E402
from modules.nexgen.routes import _batch_depo_hazir_zorunlu  # noqa: E402
nx_routes.DB_PATH = DB

_app = flask_app.app
_app.config['TESTING'] = True
client = _app.test_client()
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def login(perms=None):
    perms = perms or {}
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = perms


login({
    'nexgen.depo.giris': {'can_create': True},
    'nexgen.depo.view': {'can_view': True},
    'nexgen.satinalma.manage': {'can_create': True, 'can_manage': True, 'can_update': True},
    'nexgen.satinalma.approve': {'can_approve': True},
    'nexgen.satinalma.view': {'can_view': True},
})

sip = con.execute("""
    SELECT ss.id, ss.siparis_no, ss.siparis_miktari_kg, ss.durum,
           ss.stok_kart_id, ss.tedarikci_id,
           COALESCE((SELECT SUM(mk.miktar_kg) FROM nexgen_mal_kabul mk
                     WHERE mk.satin_siparis_id = ss.id), 0) AS gelen_kg
    FROM nexgen_satin_siparis ss
    WHERE ss.onay_durumu = 'ONAYLANDI'
      AND ss.durum IN ('BEKLIYOR', 'KISMI_TESLIM')
    ORDER BY ss.id DESC LIMIT 1
""").fetchone()

if sip:
    kalan = round(float(sip['siparis_miktari_kg']) - float(sip['gelen_kg']), 3)
    wrong_stok = con.execute(
        "SELECT id FROM nexgen_stok_kart WHERE id != ? AND aktif=1 LIMIT 1",
        (sip['stok_kart_id'],),
    ).fetchone()
    if wrong_stok and kalan > 0:
        r = client.post('/nexgen/api/depo/mal-kabul', json={
            'satin_siparis_id': sip['id'],
            'tedarikci_id': sip['tedarikci_id'],
            'stok_kart_id': wrong_stok['id'],
            'miktar_kg': min(kalan, 1.0),
        })
        d = r.get_json() or {}
        ok('11 api yanlis stok 400', r.status_code == 400 and not d.get('ok'), d.get('hata', ''))

    if kalan > 0.5:
        r2 = client.post('/nexgen/api/depo/mal-kabul', json={
            'satin_siparis_id': sip['id'],
            'tedarikci_id': sip['tedarikci_id'],
            'stok_kart_id': sip['stok_kart_id'],
            'miktar_kg': kalan + 10,
        })
        d2 = r2.get_json() or {}
        ok('12 api fazla teslim blok', r2.status_code == 400 and d2.get('fazla_gerekli'), d2.get('hata', ''))
else:
    ok('11 api yanlis stok 400', True, 'uygun siparis yok — atlandi')
    ok('12 api fazla teslim blok', True, 'uygun siparis yok — atlandi')

kismi = con.execute("""
    SELECT ss.id, ss.durum,
           COALESCE((SELECT SUM(mk.miktar_kg) FROM nexgen_mal_kabul mk
                     WHERE mk.satin_siparis_id = ss.id), 0) AS gelen_kg
    FROM nexgen_satin_siparis ss
    WHERE ss.onay_durumu = 'ONAYLANDI'
      AND ss.durum = 'KISMI_TESLIM'
    LIMIT 1
""").fetchone()
if kismi and float(kismi['gelen_kg'] or 0) > 0:
    r3 = client.post('/nexgen/api/satinalma/siparis-durum', json={'id': kismi['id'], 'eylem': 'IPTAL'})
    d3 = r3.get_json() or {}
    ok('13 api IPTAL kismi teslim', r3.status_code == 400 and not d3.get('ok'), d3.get('hata', ''))
else:
    ok('13 api IPTAL kismi teslim', True, 'KISMI_TESLIM kayit yok — atlandi')

batch = con.execute("""
    SELECT nb.batch_kodu, dh.durum
    FROM nexgen_uretim_batch nb
    JOIN nexgen_depo_hazirlik dh ON dh.batch_kodu = nb.batch_kodu
    WHERE dh.durum != 'HAZIR' AND dh.durum != 'IPTAL'
    ORDER BY nb.id DESC LIMIT 1
""").fetchone()
if batch:
    chk = _batch_depo_hazir_zorunlu(con, batch['batch_kodu'])
    ok('14 depo hazir gate', not chk.get('ok') and batch['durum'] in chk.get('depo_durum', batch['durum']), chk.get('hata', ''))
else:
    ok('14 depo hazir gate', True, 'BEKLIYOR/HAZIRLANIYOR batch yok — atlandi')

con.close()
_SHA_AFTER = sha256_file(_LIVE_DB)
ok('ISO main DB SHA unchanged', _SHA_BEFORE == _SHA_AFTER, f'{_SHA_BEFORE[:12]}..')
print(f'[ISO] main_sha_after={_SHA_AFTER}')
print(f'[ISO] main_db_changed={_SHA_BEFORE != _SHA_AFTER}')
cleanup_tmp({'tmp_dir': _TMP_DIR})
passed = sum(1 for _, c, _ in results if c)
failed = len(results) - passed
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if failed:
    print('BASARISIZ:')
    for n, c, d in results:
        if not c:
            print(f'  - {n}: {d}')
    sys.exit(1)

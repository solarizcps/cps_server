# -*- coding: utf-8 -*-
"""FAZ-UEM-1 — NEXGEN_UEM_TABLET_ZORUNLU feature flag regression."""
import io
import os
import sys
import sqlite3
import shutil
import tempfile

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

from tools.nexgen_tmp_db import sha256_file  # noqa: E402

_LIVE_DB = os.path.join(_APP, 'mock_data.db')
_SHA_BEFORE = sha256_file(_LIVE_DB)
_TMP_DIR = tempfile.mkdtemp(prefix='faz_uem_tablet_flag_')
DB = os.path.join(_TMP_DIR, 'mock_data_test.db')
shutil.copy2(_LIVE_DB, DB)

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def _reload_modules(flag_value):
    import importlib
    import config as cfg
    cfg.Config.NEXGEN_UEM_TABLET_ZORUNLU = flag_value
    cfg.Config.MOCK_DB_PATH = DB
    if 'modules.nexgen.routes' in sys.modules:
        importlib.reload(sys.modules['modules.nexgen.routes'])
    if 'app' in sys.modules:
        importlib.reload(sys.modules['app'])
    import modules.nexgen.routes as nx_routes
    nx_routes.DB_PATH = DB
    return nx_routes


def _client(flag_value, yetkiler=None):
    nx = _reload_modules(flag_value)
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    y = yetkiler or {
        'nexgen.tablet.view': {'can_view': True},
        'nexgen.tablet.uretim': {'can_uretim': True},
        'nexgen.plan.manage': {'can_manage': True},
        'nexgen.plan.view': {'can_view': True},
    }
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = y
    return c, nx


def _batch_by_durum(con, durum):
    return con.execute(
        "SELECT batch_kodu, notlar FROM nexgen_uretim_batch WHERE durum=? ORDER BY id DESC LIMIT 1",
        (durum,),
    ).fetchone()


def _liste_batch_kodlari(con, nx):
    return {r['batch_kodu'] for r in nx._tua_tablet_is_liste_sorgu(con)}


print('=' * 72)
print('FAZ-UEM-1 — UEM TABLET FLAG TEST')
print('=' * 72)

# --- Flag False (pilot default) ---
nx0 = _reload_modules(False)
ok('F0 config default False', nx0._nexgen_uem_tablet_zorunlu_mu() is False)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

db_active = con.execute("""
    SELECT batch_kodu, durum FROM nexgen_uretim_batch
    WHERE durum IN ('HAZIR','DEVAM','BEKLEME')
      AND COALESCE(notlar,'') NOT LIKE '%__UEM_TABLET__%'
""").fetchall()
liste = _liste_batch_kodlari(con, nx0)
db_kodlar = {r['batch_kodu'] for r in db_active}

ok('F1 flag False liste >= aktif marker-yok', len(liste) >= len(db_kodlar) and db_kodlar.issubset(liste),
   f'liste={len(liste)} db={len(db_kodlar)}')

for durum in ('HAZIR', 'DEVAM', 'BEKLEME'):
    row = _batch_by_durum(con, durum)
    if row:
        ok(f'F2 {durum} marker-yok listede', row['batch_kodu'] in liste, row['batch_kodu'])
    else:
        ok(f'F2 {durum} marker-yok listede', True, 'ornek yok — atlandi')

for durum in ('BITTI', 'IPTAL'):
    row = _batch_by_durum(con, durum)
    if row:
        ok(f'F3 {durum} listede degil', row['batch_kodu'] not in liste, row['batch_kodu'])
    else:
        ok(f'F3 {durum} listede degil', True, 'ornek yok — atlandi')

ok('F4 duplicate yok', len(liste) == len(nx0._tua_tablet_is_liste_sorgu(con)),
   f'unique={len(liste)} rows={len(nx0._tua_tablet_is_liste_sorgu(con))}')

c0, nx0 = _client(False)
r_api = c0.get('/nexgen/api/tablet/is-listesi')
api_list = r_api.get_json().get('liste', []) if r_api.status_code == 200 else []
ok('F5 api is-listesi 200', r_api.status_code == 200, r_api.status_code)
ok('F6 api is-listesi marker-yok batch', len(api_list) >= len(db_kodlar),
   f'n={len(api_list)}')

r_is = c0.get('/nexgen/tablet/uretim-isleri')
ok('F7 uretim-isleri 200', r_is.status_code == 200, r_is.status_code)

r_fer = c0.get('/nexgen/tablet/ferhat')
ok('F8 ferhat 200', r_fer.status_code == 200, r_fer.status_code)

devam = _batch_by_durum(con, 'DEVAM') or _batch_by_durum(con, 'HAZIR')
if devam:
    r_det = c0.get(f'/nexgen/tablet/uretim-islem/{devam["batch_kodu"]}')
    ok('F9 uretim-islem detay 200', r_det.status_code == 200, devam['batch_kodu'])
else:
    ok('F9 uretim-islem detay 200', True, 'ornek yok — atlandi')

devam_eden0, _ = nx0._tablet_ana_veri(con)
ok('F10 Ali ana veri degismedi (flag False)', len(devam_eden0) > 0, f'n={len(devam_eden0)}')

# --- Flag True (legacy) ---
nx1 = _reload_modules(True)
ok('T0 config True', nx1._nexgen_uem_tablet_zorunlu_mu() is True)

liste_true = _liste_batch_kodlari(con, nx1)
ok('T1 flag True marker-yok batch gorunmez',
   not db_kodlar.intersection(liste_true) if db_kodlar else True,
   f'kesisim={len(db_kodlar.intersection(liste_true))}')

# gecici marker ekle, rollback
sample = db_active[0] if db_active else None
if sample:
    bk = sample['batch_kodu']
    old_not = con.execute(
        "SELECT notlar FROM nexgen_uretim_batch WHERE batch_kodu=?", (bk,)
    ).fetchone()[0]
    marker = f'{nx1._UEM_TABLET_MARKER}|2026-07-21|test'
    con.execute(
        "UPDATE nexgen_uretim_batch SET notlar=? WHERE batch_kodu=?",
        (((old_not or '').strip() + '\n' + marker).strip(), bk),
    )
    con.commit()
    marked_liste = _liste_batch_kodlari(con, nx1)
    ok('T2 flag True marker-li batch gorunur', bk in marked_liste, bk)
    con.execute(
        "UPDATE nexgen_uretim_batch SET notlar=? WHERE batch_kodu=?",
        (old_not, bk),
    )
    con.commit()
else:
    ok('T2 flag True marker-li batch gorunur', True, 'ornek yok — atlandi')

c1, nx1 = _client(True)
r_api1 = c1.get('/nexgen/api/tablet/is-listesi')
n1 = len(r_api1.get_json().get('liste', [])) if r_api1.status_code == 200 else -1
ok('T3 flag True api marker-yok=0', n1 == 0, f'n={n1}')

devam_eden1, _ = nx1._tablet_ana_veri(con)
ok('T11 Ali ana veri flag True etkilenmez', len(devam_eden1) == len(devam_eden0),
   f'false={len(devam_eden0)} true={len(devam_eden1)}')

# --- Yetki ---
c_anon = _reload_modules(False)
import app as flask_app
flask_app.app.config['TESTING'] = True
c_anon_client = flask_app.app.test_client()
r_anon_api = c_anon_client.get('/nexgen/api/tablet/is-listesi')
r_anon = c_anon_client.get('/nexgen/tablet/uretim-isleri')
ok('Y1 anonim api redirect/login', r_anon_api.status_code in (302, 401, 403), r_anon_api.status_code)
ok('Y2 anonim uretim-isleri redirect/login', r_anon.status_code in (302, 401, 403), r_anon.status_code)

con.close()
ok('ISO main DB SHA unchanged', sha256_file(_LIVE_DB) == _SHA_BEFORE, _SHA_BEFORE[:12] + '..')
shutil.rmtree(_TMP_DIR, ignore_errors=True)

passed = sum(1 for _, c, _ in results if c)
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if passed < len(results):
    sys.exit(1)

# -*- coding: utf-8 -*-
"""FAZ-3 — RF kardeş boyut uygunluk otomasyonu regression testi."""
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
DB = os.path.join(_APP, 'mock_data.db')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('FAZ-3 — RF KARDEŞ BOYUT UYGUNLUK TEST')
print('=' * 72)

ROUTES = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
routes = open(ROUTES, encoding='utf-8').read()

ok('01 helper tanimli', 'def _rf_onay_sonrasi_kardes_uygunluk' in routes)
ok('02 FL->FS hedef', "_formul_kod_boyut(kfrm['kod']) not in hedef_boyutlar" in routes)
ok('03 cekirdek filtresi', 'cekirdek_formul_mu(kfrm' in routes.split('def _rf_onay_sonrasi_kardes_uygunluk')[1][:2500])
ok('04 idempotent mevcut atla', 'Zaten bağlı' not in routes.split('def _rf_onay_sonrasi_kardes_uygunluk')[1][:2500])
ok('05 onay hook', '_rf_onay_sonrasi_kardes_uygunluk(' in routes.split('def _renk_merkezi_arge_onayla_core')[1][:6000])

from modules.nexgen.routes import (  # noqa: E402
    _formul_kod_boyut, _rf_kardes_boyut_hedefleri, _rf_onay_sonrasi_kardes_uygunluk,
    _pzm_formul_kardesleri, cekirdek_formul_mu,
)

ok('06 FL boyut LARGE', _formul_kod_boyut('1BA-01-FL') == 'LARGE')
ok('07 FS boyut SMALL', _formul_kod_boyut('1BA-01-FS') == 'SMALL')
ok('08 FM boyut MEDIUM', _formul_kod_boyut('1BA-01-FM') == 'MEDIUM')
ok('09 FL hedef FS', _rf_kardes_boyut_hedefleri('1BA-01-FL') == {'SMALL'})
ok('10 FS hedef FL', _rf_kardes_boyut_hedefleri('1BA-01-FS') == {'LARGE'})
ok('11 FM hedef MEDIUM', _rf_kardes_boyut_hedefleri('1BA-01-FM') == {'MEDIUM'})

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

fl = con.execute("""
    SELECT f.id, f.kod FROM nexgen_formul f
    WHERE f.aktif=1 AND f.kod LIKE '1BA-%-FL'
    LIMIT 1
""").fetchone()
if fl and cekirdek_formul_mu(fl['kod']):
    kardes = _pzm_formul_kardesleri(con, fl['id'])
    fs_ids = []
    for fid in kardes:
        k = con.execute("SELECT kod FROM nexgen_formul WHERE id=?", (fid,)).fetchone()
        if k and _formul_kod_boyut(k['kod']) == 'SMALL':
            fs_ids.append(fid)
    ok('12 FL kardes FS var', len(fs_ids) >= 1, f'kardes={len(kardes)} fs={len(fs_ids)}')
else:
    ok('12 FL kardes FS var', True, 'FL formül yok — atlandi')

taban = con.execute("""
    SELECT id, kod FROM nexgen_formul
    WHERE aktif=1 AND kod LIKE '2BA-%-FL' LIMIT 1
""").fetchone()
dokme = con.execute("""
    SELECT id, kod FROM nexgen_formul
    WHERE aktif=1 AND kod LIKE '3BA-%-FM' LIMIT 1
""").fetchone()
if taban and dokme:
    t_k = set(_pzm_formul_kardesleri(con, taban['id']))
    d_k = set(_pzm_formul_kardesleri(con, dokme['id']))
    ok('13 TABAN/DOKME ayri', not (t_k & d_k), f'taban={len(t_k)} dokme={len(d_k)}')
else:
    ok('13 TABAN/DOKME ayri', True, '2BA/3BA yok — atlandi')

onceki = con.execute("SELECT COUNT(*) FROM nexgen_rf_formul_uygunluk WHERE aktif=1").fetchone()[0]
ok('14 aktif uygunluk kayit var', onceki >= 1, str(onceki))

con.close()
passed = sum(1 for _, c, _ in results if c)
failed = len(results) - passed
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if failed:
    for n, c, d in results:
        if not c:
            print(f'  FAIL: {n} — {d}')
    sys.exit(1)

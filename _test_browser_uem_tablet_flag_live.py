# -*- coding: utf-8 -*-
"""FAZ-UEM-1 — lokal browser/API dogrulama (flag False default)."""
import io
import os
import re
import sys
import sqlite3

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

import requests  # noqa: E402
from config import Config  # noqa: E402

BASE = os.environ.get('CPS_BASE_URL', 'http://127.0.0.1:8080')
DB = Config.MOCK_DB_PATH
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('FAZ-UEM-1 — CANLI DOGRULAMA')
print('=' * 72)
print(f'  base={BASE}')
print(f'  NEXGEN_UEM_TABLET_ZORUNLU={Config.NEXGEN_UEM_TABLET_ZORUNLU}')

ok('B0 flag default False', Config.NEXGEN_UEM_TABLET_ZORUNLU is False)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
active = con.execute("""
    SELECT COUNT(*) c FROM nexgen_uretim_batch
    WHERE durum IN ('HAZIR','DEVAM','BEKLEME')
      AND COALESCE(notlar,'') NOT LIKE '%__UEM_TABLET__%'
""").fetchone()['c']
sample = con.execute("""
    SELECT batch_kodu, durum FROM nexgen_uretim_batch
    WHERE durum IN ('HAZIR','DEVAM','BEKLEME')
      AND COALESCE(notlar,'') NOT LIKE '%__UEM_TABLET__%'
    ORDER BY id DESC LIMIT 1
""").fetchone()
admin_pw = con.execute(
    "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1"
).fetchone()['Sifre']
con.close()

s = requests.Session()
s.post(f'{BASE}/giris', data={'kullanici': 'admin', 'sifre': admin_pw}, timeout=10)

r_ana = s.get(f'{BASE}/nexgen/tablet', timeout=15)
m = re.search(r'var _BATCHLER = (\[.*?\]);', r_ana.text, re.S)
batchler = __import__('json').loads(m.group(1)) if m else []
ana_n = len(batchler)

r_api = s.get(f'{BASE}/nexgen/api/tablet/is-listesi', timeout=15)
api_list = r_api.json().get('liste', []) if r_api.headers.get('content-type', '').startswith('application/json') else []
api_n = len(api_list)

r_is = s.get(f'{BASE}/nexgen/tablet/uretim-isleri', timeout=15)
is_n = len(re.findall(r'uretim-islem/([A-Z0-9\-]+)', r_is.text))

r_fer = s.get(f'{BASE}/nexgen/tablet/ferhat', timeout=15)

ok('B1 tablet ana 200', r_ana.status_code == 200, f'_BATCHLER={ana_n}')
ok('B2 api is-listesi >= marker-yok aktif', api_n >= active, f'api={api_n} db={active}')
ok('B3 uretim-isleri kart/link', is_n >= min(active, 1) or active == 0, f'links={is_n}')
ok('B4 ferhat 200', r_fer.status_code == 200, r_fer.status_code)
ok('B5 api 200', r_api.status_code == 200, r_api.status_code)
ok('B6 uretim-isleri 200', r_is.status_code == 200, r_is.status_code)

if sample:
    r_det = s.get(f'{BASE}/nexgen/tablet/uretim-islem/{sample["batch_kodu"]}', timeout=15)
    ok('B7 detay marker-yok 200', r_det.status_code == 200, sample['batch_kodu'])
else:
    ok('B7 detay marker-yok 200', True, 'ornek yok')

passed = sum(1 for _, c, _ in results if c)
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if passed < len(results):
    sys.exit(1)

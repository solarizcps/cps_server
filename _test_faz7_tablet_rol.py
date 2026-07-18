# -*- coding: utf-8 -*-
"""FAZ-7 — Tablet ve rol akışları testi."""
import io, os, sys
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_APP = os.path.join(os.path.dirname(__file__), 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)
routes = open(os.path.join(_APP, 'modules', 'nexgen', 'routes.py'), encoding='utf-8').read()
checks = [
    ('01 ferhat route', "def tablet_ferhat" in routes),
    ('02 ferhat redirect', "redirect(f'/nexgen/tablet/uretim-islem/" in routes),
    ('03 auth ferhat yonlendirme', "'ferhat'" in open(os.path.join(_APP, 'modules', 'auth.py'), encoding='utf-8').read()),
]
print('FAZ-7 TABLET ROLES')
for n, c in checks:
    print(f'  [{"PASS" if c else "FAIL"}] {n}')

import app as flask_app
_app = flask_app.app
_app.config['TESTING'] = True
client = _app.test_client()
with client.session_transaction() as s:
    s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}
    s['kullanici_tip'] = 'sistem'
    s['yetkiler'] = {'nexgen.tablet.view': {'can_view': True}}
r = client.get('/nexgen/tablet/ferhat')
checks.append(('04 ferhat page 200', r.status_code == 200))
for n, c in checks:
    print(f'  [{"PASS" if c else "FAIL"}] {n}')
sys.exit(0 if all(c for _, c in checks) else 1)

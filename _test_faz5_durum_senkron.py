# -*- coding: utf-8 -*-
"""FAZ-5 — Operasyonel durum senkronu testi."""
import io, os, sys
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
routes = open(os.path.join(os.path.dirname(__file__), 'app', 'modules', 'nexgen', 'routes.py'), encoding='utf-8').read()
checks = [
    ('01 gorunen durum helper', 'def _pzm_siparis_gorunen_durum' in routes),
    ('02 plan varken MPR duzelt', 'Plan mevcut' in routes.split('def _pzm_siparis_gorunen_durum')[1][:900]),
    ('03 ON_CALISMA etiket', "'ON_CALISMA': 'Ön Çalışma'" in routes),
    ('04 gorunen_durum alan', "'gorunen_durum'" in routes.split('def _pzm_talep_satir_dict')[1][:1200]),
]
print('FAZ-5 STATUS SYNC')
for n, c in checks:
    print(f'  [{"PASS" if c else "FAIL"}] {n}')
sys.exit(0 if all(c for _, c in checks) else 1)

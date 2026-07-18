# -*- coding: utf-8 -*-
"""FAZ-6 — İzlenebilirlik testi."""
import io, os, sys
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
routes = open(os.path.join(os.path.dirname(__file__), 'app', 'modules', 'nexgen', 'routes.py'), encoding='utf-8').read()
checks = [
    ('01 stok aciklama PZM', 'PZM {pzm_no' in routes.split('def _parca_stok_tuket')[1][:3500]),
    ('02 plan kodu aciklama', 'Plan {plan_kodu' in routes.split('def _parca_stok_tuket')[1][:3500]),
    ('03 mal kabul SA no', 'SA {sip_no or siparis_id}' in routes),
]
print('FAZ-6 TRACEABILITY')
for n, c in checks:
    print(f'  [{"PASS" if c else "FAIL"}] {n}')
sys.exit(0 if all(c for _, c in checks) else 1)

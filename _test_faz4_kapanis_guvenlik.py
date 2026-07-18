# -*- coding: utf-8 -*-
"""FAZ-4 — Üretim kapanış güvenliği regression testi."""
import io
import os
import sys

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


print('=' * 72)
print('FAZ-4 — ÜRETİM KAPANIŞ GÜVENLİK TEST')
print('=' * 72)

ROUTES = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
routes = open(ROUTES, encoding='utf-8').read()

ok('01 batch bitir parca kontrol', 'acik > 0' in routes.split('def _tua_batch_bitir_kontrol')[1][:900])
ok('02 batch zaten bitti', 'Batch zaten tamamlanmış' in routes)
ok('03 parca bitir batch DEVAM', 'batch üretimde olmalı' in routes)
ok('04 parca duplicate WHERE', "durum IN ('DEVAM','HAZIR')" in routes.split('def _parca_bitir_uygula')[1][:2000])
ok('05 batch update durum guard', 'AND durum=?' in routes.split('def api_batch_durum_guncelle')[1][:3500])
ok('06 batch BITTI idempotent', "'idempotent': True" in routes.split('def api_batch_durum_guncelle')[1][:3500])
ok('07 siparis cok plan sync', "NOT IN ('BITTI','IPTAL')" in routes.split('def _pzm_siparis_tamamlandi_sync')[1][:800])
ok('08 faturalanacak fiili', 'uretilen_fiili' in routes.split('def _pzm_mpr_plan_satir_zengin')[1][:4500])
ok('09 depo hazir parca gate', '_batch_depo_hazir_zorunlu' in routes.split('def _parca_bitir_uygula')[1][:800])

passed = sum(1 for _, c, _ in results if c)
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if passed < len(results):
    sys.exit(1)

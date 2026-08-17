# -*- coding: utf-8 -*-
"""T1–T17 Proses miktar/payda parity lock tests. READ-ONLY."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import (
    model_satir_by_canonical, siparis_model_satirlari,
    m_emirler_lazy, merge_plan_korgun, _proses_by_kod, _yuzde,
)

passed, failed = [], []


def ok(l, _=''):
    passed.append(l)
    print(f'  PASS  {l}')


def fail(l, r=''):
    failed.append(l)
    print(f'  FAIL  {l}' + (f' — {r}' if r else ''))


def check(l, c, r=''):
    (ok if c else fail)(l, r)


print('=' * 60)
print('Proses Miktar / Payda Parity — Lock Test Seti')
print('=' * 60)

con = kk._baglan()

S86 = model_satir_by_canonical(con, 33786, 83530, 'CRP-81315-RL', 2336)
S85 = model_satir_by_canonical(con, 33785, 83529, 'CRP-81311RL', 8)
R19 = siparis_model_satirlari(con, 33919)
S19 = next((s for s in (R19.get('satirlar') or []) if s.get('model_kod') == 'CRX-71026-KRK'), None)

enj86 = _proses_by_kod(S86.get('prosesler'), '26')
mon86 = _proses_by_kod(S86.get('prosesler'), '30')
tem86 = _proses_by_kod(S86.get('prosesler'), '35')
enj85 = _proses_by_kod(S85.get('prosesler'), '26')
mon85 = _proses_by_kod(S85.get('prosesler'), '30')
tem85 = _proses_by_kod(S85.get('prosesler'), '35')

# T1–T4
check('T1  M+Y duplicate double-count yok (33786 Montaj hedef<=6000)',
      mon86 and int(mon86.get('hedef_miktar') or 0) <= 6000,
      f"hedef={mon86.get('hedef_miktar') if mon86 else None}")
check('T2  Enjeksiyon Y parçaları toplamı korunur (33786=10000)',
      enj86 and int(enj86.get('hedef_miktar') or 0) == 10000 and enj86.get('emir_seviyesi') == 'Y')
check('T3  Montaj hedefi M mamul (33786≈5000)',
      mon86 and 4500 <= int(mon86.get('hedef_miktar') or 0) <= 5500,
      f"hedef={mon86.get('hedef_miktar')}")
check('T4  Temizleme hedefi M mamul (33786≈5000)',
      tem86 and 4500 <= int(tem86.get('hedef_miktar') or 0) <= 5500,
      f"hedef={tem86.get('hedef_miktar')}")

# T5–T6 gate prosesler
mb86 = _proses_by_kod(S86.get('prosesler'), '28')
check('T5  Monta Başlayacak M seviyesi', mb86 and mb86.get('emir_seviyesi') == 'M')
check('T6  Enjeksiyon Y seviyesi', enj86 and enj86.get('emir_seviyesi') == 'Y')

# T7–T9 33786/33785
check('T7  33786 Montaj yanlış 20k paydayı kullanmaz',
      mon86 and int(mon86.get('hedef_miktar') or 0) < 15000)
check('T8  33786 Temizleme double-count yok',
      tem86 and int(tem86.get('hedef_miktar') or 0) < 8000)
check('T9  33785 emir coverage kaybolmaz', S85 is not None and len(S85.get('prosesler') or []) >= 4)

# T10 33919
if S19:
    mon19 = _proses_by_kod(S19.get('prosesler'), '30')
    enj19 = _proses_by_kod(S19.get('prosesler'), '26')
    check('T10 33919 Monta M seviyesi', mon19 and mon19.get('emir_seviyesi') == 'M')
    check('T10b 33919 Enjeksiyon Y seviyesi', enj19 and enj19.get('emir_seviyesi') == 'Y')
    check('T10c 33919 Temizleme görünür', _proses_by_kod(S19.get('prosesler'), '35') is not None)

# T11–T12
check('T11 yüzde 0–100 cap', _yuzde(9000, 8000) == 100.0)
check('T12 biten emir sayısı', mon85 and mon85.get('biten_emir_sayisi') == 11,
      f"biten_emir={mon85.get('biten_emir_sayisi') if mon85 else None}")

# T13 popup parity
lots = m_emirler_lazy(con, 33786, 83530, 'CRP-81315-RL', 2336)
if lots and S86:
    lk = [p['proses_kod'] for p in lots[0].get('prosesler') or []]
    ak = [p['proses_kod'] for p in S86.get('prosesler') or []]
    check('T13 ana liste-popup sıra parity', lk == ak, f'lot={lk} ana={ak}')

# T14 Model_P regression
check('T14 Model_P rota sıra 33786',
      [p['proses_kod'] for p in S86.get('prosesler') or []] == ['26', '28', '30', '35'])

# T15 archive
check('T15 33785 archive enjeksiyon biten>0',
      enj85 and int(enj85.get('biten') or 0) > 0)

# T16 CRUD
try:
    m = merge_plan_korgun({'id': 1}, S86)
    check('T16 merge_plan_korgun prosesler korunur', 'prosesler' in m and m['prosesler'][0].get('emir_detay'))
except Exception as ex:
    fail('T16', str(ex)[:80])

# T17 git diff
try:
    r = subprocess.run(['git', 'diff', '--check'], cwd=str(Path(__file__).resolve().parents[1]),
                       capture_output=True, text=True, timeout=30)
    check('T17 git diff --check temiz', r.returncode == 0)
except Exception as ex:
    fail('T17', str(ex)[:80])

# 33785 montaj %100
check('33785 Montaj %100', mon85 and mon85.get('yuzde') == 100.0 and mon85.get('durum') == 'BİTTİ')
check('33785 emir_detay var', mon85 and len(mon85.get('emir_detay') or []) == 11)

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    print('FAIL:', failed)
    sys.exit(1)
print('TÜM TESTLER GEÇTİ')

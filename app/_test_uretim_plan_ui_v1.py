# -*- coding: utf-8 -*-
"""UI regression — cari + proses inline first/last. READ-ONLY."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import model_satir_by_canonical, siparis_model_satirlari

passed, failed = [], []


def ok(l, _=''):
    passed.append(l)
    print(f'  PASS  {l}')


def fail(l, r=''):
    failed.append(l)
    print(f'  FAIL  {l}' + (f' — {r}' if r else ''))


def check(l, c, r=''):
    (ok if c else fail)(l, r)


def pick_inline(list_kod, max_slots=6):
    """JS renderProsesInline parity."""
    if len(list_kod) <= max_slots:
        return list_kod, 0
    first, last = list_kod[0], list_kod[-1]
    middle = list_kod[1:-1]
    slots_mid = max(0, max_slots - 2)
    if len(middle) <= slots_mid:
        return list_kod, 0
    vis = [first] + middle[:slots_mid] + [last]
    return vis, len(middle) - slots_mid


print('=' * 60)
print('UI — Cari + Proses Inline Lock')
print('=' * 60)

con = kk._baglan()

# Cari from Korgun
for sip, har, sk, rk in [
    (33786, 83530, 'CRP-81315-RL', 2336),
    (33785, 83529, 'CRP-81311RL', 8),
    (33888, 83874, 'YZM-9900', 15),
]:
    s = model_satir_by_canonical(con, sip, har, sk, rk)
    check(f'Cari dolu sip={sip}', s and (s.get('musteri') or '').strip() not in ('', '-'),
          f"musteri={s.get('musteri') if s else None}")

# 33918 — Temizleme son proses inline'da kalmalı
r18 = siparis_model_satirlari(con, 33918)
s18 = (r18.get('satirlar') or [None])[0]
if s18:
    k18 = [p['proses_kod'] for p in s18.get('prosesler') or []]
    vis, hid = pick_inline(k18, 6)
    check('33918 Temizleme (35) inline görünür', '35' in vis and vis[-1] == '35', f'vis={vis}')
    check('33918 ilk proses görünür', vis[0] == k18[0])
    if hid:
        check('33918 +N ara proses', hid >= 1)
else:
    fail('33918 satır var')

# 33888 sıra
s88 = model_satir_by_canonical(con, 33888, 83874, 'YZM-9900', 15)
k88 = [p['proses_kod'] for p in (s88 or {}).get('prosesler') or []]
check('33888 sıra', k88 == ['26', '50', '28', '35'], f'k={k88}')
vis88, _ = pick_inline(k88, 6)
check('33888 tüm proses inline (4<=6)', vis88 == k88)

# Payda regression — değişmedi
mon86 = next((p for p in (model_satir_by_canonical(con, 33786, 83530, 'CRP-81315-RL', 2336) or {}).get('prosesler') or [] if p['proses_kod']=='30'), None)
check('33786 Montaj hedef 5000', mon86 and int(mon86.get('hedef_miktar') or 0) == 5000)

# git diff
try:
    r = subprocess.run(['git', 'diff', '--check'], cwd=str(Path(__file__).resolve().parents[1]),
                       capture_output=True, text=True, timeout=30)
    check('git diff --check', r.returncode == 0)
except Exception as ex:
    fail('git diff --check', str(ex)[:80])

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    sys.exit(1)

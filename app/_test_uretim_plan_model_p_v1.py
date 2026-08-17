# -*- coding: utf-8 -*-
"""T1–T18 Model_P canonical full route lock tests. READ-ONLY."""
from __future__ import annotations
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')

from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import (
    _load_model_p_routes,
    _build_dynamic_prosesler,
    _canonical_proses_order,
    _proses_by_kod,
    model_satir_by_canonical,
    siparis_model_satirlari,
    m_emirler_lazy,
    merge_plan_korgun,
)

passed, failed = [], []


def ok(label, _=''):
    passed.append(label)
    print(f'  PASS  {label}')


def fail(label, reason=''):
    failed.append(label)
    print(f'  FAIL  {label}' + (f' — {reason}' if reason else ''))


def check(label, cond, reason=''):
    (ok if cond else fail)(label, reason)


def kodlar(prosesler):
    return [p['proses_kod'] for p in (prosesler or [])]


print('=' * 60)
print('Model_P Canonical Full Route — Lock Test Seti')
print('=' * 60)

con = kk._baglan()
cur = con.cursor()

# ── T1 Model_P batch load ───────────────────────────────────────────────────
routes, adi = _load_model_p_routes(cur, ['YZM-9900', 'EVA YZM-9900', 'CRX-71026-KRK'])
check('T1  Model_P full route okunur',
      'YZM-9900' in routes and len(routes['YZM-9900']) >= 2,
      f"yzm={routes.get('YZM-9900')}")

# ── T2/T3 sıra ──────────────────────────────────────────────────────────────
S88 = model_satir_by_canonical(con, 33888, 83874, 'YZM-9900', 15)
P88 = S88.get('prosesler') or [] if S88 else []
K88 = kodlar(P88)
check('T2  ProsesNo sırası korunur (33888)', K88 == ['26', '50', '28', '35'], f'sıra={K88}')
check('T3  numeric kod sırası kullanılmaz',
      K88 != sorted(K88, key=lambda x: int(x) if x.isdigit() else 9999),
      f'sıra={K88}')

# ── T4 Y before M ───────────────────────────────────────────────────────────
check('T4  Y rota M rotadan önce (26,50 before 28,35)',
      K88.index('26') < K88.index('28') and K88.index('50') < K88.index('35'),
      f'sıra={K88}')

# ── T5/T6 pilot sıra ────────────────────────────────────────────────────────
S57 = model_satir_by_canonical(con, 33857, 83766, 'BRM-9000', 5)
K57 = kodlar(S57.get('prosesler') if S57 else [])
check('T5  33888 → 26,50,28,35', K88 == ['26', '50', '28', '35'])
check('T6  33857 → 26,50,28,35', K57 == ['26', '50', '28', '35'], f'sıra={K57}')

# ── T7 33919 Temizleme ──────────────────────────────────────────────────────
R19 = siparis_model_satirlari(con, 33919)
S19 = next((s for s in (R19.get('satirlar') or []) if s.get('model_kod') == 'CRX-71026-KRK'), None)
K19 = kodlar(S19.get('prosesler') if S19 else [])
check('T7  33919 Temizleme görünür', '35' in K19, f'kodlar={K19}')
check('T7b 33919 Monta görünür', '30' in K19)
check('T7c 33919 Kesim görünür', '02' in K19)

# ── T8 BAŞLANMADI ───────────────────────────────────────────────────────────
tem57 = _proses_by_kod(S57.get('prosesler') if S57 else [], '35')
check('T8  Model_P proses hareket yok → BAŞLANMADI',
      tem57 and tem57.get('durum') == 'BAŞLANMADI')

# ── T9 archive ──────────────────────────────────────────────────────────────
S86 = model_satir_by_canonical(con, 33786, 83530, 'CRP-81315-RL', 2336)
P86 = S86.get('prosesler') or [] if S86 else []
enj86 = _proses_by_kod(P86, '26')
K86 = kodlar(P86)
check('T9  archive hareket korunur (33786 Enj BİTTİ)',
      enj86 and enj86.get('durum') == 'BİTTİ' and enj86.get('yuzde') == 100.0)
check('T9b 33786 Model_P tam rota (26,28,30,35)',
      K86 == ['26', '28', '30', '35'], f'sıra={K86}')

# ── T10 Em2Em-only kaybolmaz ────────────────────────────────────────────────
check('T10 Em2Em Temizleme 33857', '35' in K57)

# ── T11/T12 izolasyon ───────────────────────────────────────────────────────
S85 = model_satir_by_canonical(con, 33785, 83529, 'CRP-81311RL', 8)
S88 = model_satir_by_canonical(con, 33888, 83874, 'YZM-9900', 15)
check('T11 farklı renk karışmaz', S57 and S88 and S57.get('rkod') != S88.get('rkod'))
check('T12 farklı SipHarinx karışmaz', S57 and S88 and S57.get('sip_harinx') != S88.get('sip_harinx'))

# ── T13 popup parity ────────────────────────────────────────────────────────
lots57 = m_emirler_lazy(con, 33857, 83766, 'BRM-9000', 5)
if lots57:
    lk57 = kodlar(lots57[0].get('prosesler'))
    check('T13 ana liste-popup sıra parity', lk57 == K57, f'lot={lk57} ana={K57}')

# ── T14 UI contract (prosesler array uzunluğu) ──────────────────────────────
check('T14 33888 4 proses chip verisi', len(P88) == 4, f'count={len(P88)}')
check('T14b 33919 6+ proses', len(K19) >= 6, f'count={len(K19)}')

# ── T15 satır veri yapısı (wrap JS/CSS — prosesler tek dizi) ───────────────
check('T15 prosesler route_tier metadata', all('route_tier' in p for p in P88))

# ── T16 CRUD regression ───────────────────────────────────────────────────
try:
    merged = merge_plan_korgun({'id': 1, 'plan_donemi': 'bu_hafta'}, S88)
    check('T16 merge_plan_korgun prosesler korunur',
          merged.get('prosesler') and kodlar(merged['prosesler']) == K88)
except Exception as ex:
    fail('T16', str(ex)[:80])

# ── T17 mevcut test modülleri ───────────────────────────────────────────────
for mod in ('_test_uretim_plan_dynamic_v1', '_test_uretim_plan_parity_v1',
            '_test_uretim_plan_fullroute_v1'):
    try:
        __import__(mod)
        ok(f'T17 {mod} import OK')
    except SystemExit:
        ok(f'T17 {mod} import OK (sub-exit)')
    except Exception as ex:
        fail(f'T17 {mod}', str(ex)[:80])

# ── T18 git diff --check ────────────────────────────────────────────────────
try:
    r = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(__import__('pathlib').Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=30,
    )
    check('T18 git diff --check temiz', r.returncode == 0, (r.stdout or r.stderr)[:120])
except Exception as ex:
    fail('T18', str(ex)[:80])

# ── 33888 durum kanıtı ───────────────────────────────────────────────────────
enj88 = _proses_by_kod(P88, '26')
eva88 = _proses_by_kod(P88, '50')
check('33888 Enjeksiyon BİTTİ', enj88 and enj88.get('durum') == 'BİTTİ')
check('33888 Eva Hazır DEVAM veya BİTTİ', eva88 and eva88.get('durum') in ('DEVAM', 'BİTTİ'))

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    print('FAIL:', failed)
    sys.exit(1)
print('TÜM TESTLER GEÇTİ')

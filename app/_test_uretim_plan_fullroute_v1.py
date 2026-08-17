# -*- coding: utf-8 -*-
"""T1–T15 Full Route / GetProses parity lock tests. READ-ONLY."""
from __future__ import annotations
import sys
sys.stdout.reconfigure(encoding='utf-8')

from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import (
    _load_getproses_map, _build_dynamic_prosesler, _load_emir_hareket,
    _proses_by_kod, _yuzde, model_satir_by_canonical, siparis_model_satirlari,
    m_emirler_lazy, merge_plan_korgun,
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

print('=' * 60)
print('Full Route / GetProses — Lock Test Seti')
print('=' * 60)

con = kk._baglan()
cur = con.cursor()

# ── T1/T2 GetProses-only ────────────────────────────────────────────────────
# archive parity — cursor kapanmadan önce
M85 = [111636,111639,111642,111643,111644,111645,111646,111647,111648,111649,111650]
Y85 = list(range(111637, 111669))
all85 = M85 + Y85
ph85 = ','.join(['%s'] * len(all85))
cur.execute(f"""
    SELECT SUM(Cikan) FROM Urt_con_gch  WHERE EmirNo IN ({ph85}) AND Proses='26' AND Cikan>0
    UNION ALL
    SELECT SUM(Cikan) FROM Urtx_con_gch WHERE EmirNo IN ({ph85}) AND Proses='26' AND Cikan>0
""", tuple(all85) * 2)
hedef_biten_85 = sum(int(float(r[0] or 0)) for r in cur.fetchall())

S57 = model_satir_by_canonical(con, 33857, 83766, 'BRM-9000', 5)
P57 = S57.get('prosesler') or [] if S57 else []
K57 = [p['proses_kod'] for p in P57]
enj57 = _proses_by_kod(P57, '26')
mon_bas57 = _proses_by_kod(P57, '28')
tem57 = _proses_by_kod(P57, '35')

check('T1  GetProses-only Enjeksiyon (26) görünür', '26' in K57, f'kodlar={K57}')
check('T2  GetProses-only hareket yok → BAŞLANMADI',
      enj57 and enj57.get('durum') == 'BAŞLANMADI' and int(enj57.get('verilen') or 0) > 0,
      f'enj={enj57}')

# ── T3 Em2Em-only (33857 Temizleme) ─────────────────────────────────────────
check('T3  Em2Em-only Temizleme (35) görünür', tem57 and tem57.get('durum') == 'BAŞLANMADI')

# ── T4 hareket-only (33786 archive enjeksiyon) ──────────────────────────────
S86 = model_satir_by_canonical(con, 33786, 83530, 'CRP-81315-RL', 2336)
P86 = S86.get('prosesler') or [] if S86 else []
enj86 = _proses_by_kod(P86, '26')
check('T4  hareket-only Enjeksiyon BİTTİ', enj86 and enj86.get('durum') == 'BİTTİ' and int(enj86.get('biten') or 0) > 0)

# ── T5 duplicate double-count yok ───────────────────────────────────────────
if enj86:
    # 22 Y emir archive biten=10000 toplam; verilen de aynı mertebede olmalı, 2x değil
    check('T5  Enjeksiyon biten makul (<=15000)', int(enj86.get('biten') or 0) <= 15000,
          f"biten={enj86.get('biten')}")

# ── T6/T7 izolasyon ─────────────────────────────────────────────────────────
S85 = model_satir_by_canonical(con, 33785, 83529, 'CRP-81311RL', 8)
check('T6  farklı SipHarinx karışmaz', S57 and S85 and S57['sip_harinx'] != S85['sip_harinx'])
check('T7  33857 SIYAH rkod=5 ayrı satır', S57 and S57.get('rkod') == 5)

# ── T8 33857 tam zincir 26→50→28→35 ─────────────────────────────────────────
check('T8  33857 proses 26/50/28/35', K57 == ['26', '50', '28', '35'], f'sıra={K57}')
check('T8b 33857 Monta Baslayacak BAŞLANMADI',
      mon_bas57 and mon_bas57.get('durum') == 'BAŞLANMADI')

# ── T9 33919 GetProses geri geldi ───────────────────────────────────────────
R19 = siparis_model_satirlari(con, 33919)
S19 = (R19.get('satirlar') or [None])[0]
P19 = S19.get('prosesler') or [] if S19 else []
K19 = [p['proses_kod'] for p in P19]
check('T9  33919 Kesim (02) görünür', '02' in K19, f'kodlar={K19}')
check('T9b 33919 Enjeksiyon (26) görünür', '26' in K19)
check('T9c 33919 Monta (30) görünür', '30' in K19)
check('T9d 33919 yalnız Monta değil', len(P19) >= 4, f'count={len(P19)}')
check('T9e 33919 Temizleme görünür', '35' in K19, f'kodlar={K19}')

# ── T10 33786 archive + GetProses union ─────────────────────────────────────
K86 = [p['proses_kod'] for p in P86]
mon86 = _proses_by_kod(P86, '30')
mon_bas86 = _proses_by_kod(P86, '28')
check('T10 33786 Enjeksiyon 100%', enj86 and enj86.get('yuzde') == 100.0)
check('T10b 33786 Monta Baslayacak DEVAM veya BAŞLANMADI',
      mon_bas86 and mon_bas86.get('durum') in ('DEVAM', 'BAŞLANMADI'))
check('T10c 33786 Monta DEVAM veya BAŞLANMADI',
      mon86 and mon86.get('durum') in ('DEVAM', 'BAŞLANMADI'))
check('T10d 33786 sıra 26/28/30/35', K86 == ['26', '28', '30', '35'], f'sıra={K86}')

S85 = model_satir_by_canonical(con, 33785, 83529, 'CRP-81311RL', 8)
enj85 = _proses_by_kod((S85 or {}).get('prosesler'), '26')
if enj85:
    check('T10e archive biten parity 33785', int(enj85.get('biten') or 0) == hedef_biten_85)

# ── T11/T12 popup parity ────────────────────────────────────────────────────
lots57 = m_emirler_lazy(con, 33857, 83766, 'BRM-9000', 5)
if lots57:
    lk57 = [p['proses_kod'] for p in lots57[0].get('prosesler') or []]
    check('T11 33857 model↔popup parity', lk57 == K57, f'lot={lk57} ana={K57}')
lots86 = m_emirler_lazy(con, 33786, 83530, 'CRP-81315-RL', 2336)
if lots86 and P86:
    lk86 = [p['proses_kod'] for p in lots86[0].get('prosesler') or []]
    check('T12 lot kodları ana satır alt kümesi', set(lk86) <= set(K86), f'lot={lk86} ana={K86}')

# ── T13 dynamic v1 regression import ────────────────────────────────────────
try:
    import _test_uretim_plan_dynamic_v1  # noqa: F401
    ok('T13 dynamic v1 modül import OK')
except Exception as ex:
    fail('T13', str(ex)[:80])

# ── T14 parity v1 regression import ─────────────────────────────────────────
try:
    import _test_uretim_plan_parity_v1  # noqa: F401
    ok('T14 parity v1 modül import OK')
except Exception as ex:
    fail('T14', str(ex)[:80])

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    print('FAIL:', failed)
    sys.exit(1)
print('TÜM TESTLER GEÇTİ')

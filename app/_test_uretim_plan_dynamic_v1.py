# -*- coding: utf-8 -*-
"""T1–T15 Üretim Plan — Dinamik Proses Lock Tests. READ-ONLY."""
from __future__ import annotations
import sys
sys.stdout.reconfigure(encoding='utf-8')

from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import (
    _build_dynamic_prosesler, _load_emir_hareket, _proses_by_kod, _yuzde,
    model_satir_by_canonical, siparis_model_satirlari, merge_plan_korgun,
    m_emirler_lazy, y_emirler_lazy, proses_detay_lazy,
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
print('Üretim Plan Dinamik Proses — Lock Test Seti')
print('=' * 60)

con = kk._baglan()

# ── 33786 pilot ─────────────────────────────────────────────────────────────
S86 = model_satir_by_canonical(con, 33786, 83530, 'CRP-81315-RL', 2336)
P86 = S86.get('prosesler') or [] if S86 else []
K86 = [p['proses_kod'] for p in P86]

check('T1  33786 gerçek prosesleri geliyor', len(P86) >= 2, f'count={len(P86)}')
check('T2  33786 Saya (15) görünmüyor', '15' not in K86, f'kodlar={K86}')
check('T2b 33786 Temizleme (35) Model_P rota', '35' in K86, f'kodlar={K86}')

enj86 = _proses_by_kod(P86, '26')
mon86 = _proses_by_kod(P86, '30')
mon_bas86 = _proses_by_kod(P86, '28')
check('T10 33786 Saya görünmüyor', '15' not in K86)
check('T11 33786 Monta DEVAM veya BAŞLANMADI',
      mon86 and mon86.get('durum') in ('DEVAM', 'BAŞLANMADI'),
      f'montaj={mon86}')
check('T11b 33786 Monta Baslayacak DEVAM veya BAŞLANMADI',
      mon_bas86 and mon_bas86.get('durum') in ('DEVAM', 'BAŞLANMADI'),
      f'monta_bas={mon_bas86}')
check('T12 33786 Enjeksiyon 100%', enj86 and enj86.get('yuzde') == 100.0 and enj86.get('durum') == 'BİTTİ',
      f'enj={enj86}')
check('T12b 33786 full route 26/28/30/35', K86 == ['26', '28', '30', '35'], f'sıra={K86}')

# proses var / hareket yok vs proses yok
check('T3  33786 Montaj verilen>0',
      mon86 and int(mon86.get('verilen') or 0) > 0)
check('T3b 33786 olmayan proses listede yok', '15' not in K86)

# ── 33785 pilot (archive enjeksiyon) ────────────────────────────────────────
S85 = model_satir_by_canonical(con, 33785, 83529, 'CRP-81311RL', 8)
P85 = S85.get('prosesler') or [] if S85 else []
enj85 = _proses_by_kod(P85, '26')
check('T4  33785 Enjeksiyon DEVAM veya BİTTİ', enj85 and enj85.get('durum') in ('DEVAM', 'BİTTİ'),
      f'enj={enj85}')
check('T5  33785 Enjeksiyon biten > 0 (archive parity)', enj85 and int(enj85.get('biten') or 0) > 0,
      f"biten={enj85.get('biten') if enj85 else None}")
check('T5b 33785 Enjeksiyon yuzde > 0', enj85 and float(enj85.get('yuzde') or 0) > 0,
      f"yuzde={enj85.get('yuzde') if enj85 else None}")

# ── renk / harinx izolasyon ─────────────────────────────────────────────────
if S86 and S85:
    check('T7  farklı sipariş proses karışmıyor',
          S86['canonical_key'] != S85['canonical_key'])
    check('T8  farklı SipHarinx karışmıyor',
          S86['sip_harinx'] != S85['sip_harinx'])

# ── 33859 çok prosesli pilot ────────────────────────────────────────────────
R59 = siparis_model_satirlari(con, 33859)
S59 = (R59.get('satirlar') or [None])[0]
P59 = S59.get('prosesler') or [] if S59 else []
check('T1b 33859 4+ proses zinciri', len(P59) >= 4, f'count={len(P59)}')
k59 = [p['proses_kod'] for p in P59]
check('T1c 33859 Em2Em proses 02 Kesim var', '02' in k59, f'kodlar={k59[:8]}')

# ── 33919 regression ────────────────────────────────────────────────────────
R19 = siparis_model_satirlari(con, 33919)
S19 = (R19.get('satirlar') or [None])[0]
P19 = S19.get('prosesler') or [] if S19 else []
K19 = [p['proses_kod'] for p in P19]
check('T13 33919 satır var', S19 is not None)
if S19:
    check('T13b 33919 Kesim+Enjeksiyon+Monta+Temizleme',
          '02' in K19 and '26' in K19 and '30' in K19 and '35' in K19, f'kodlar={K19}')
    check('T13c 33919 genel BAŞLANMADI/GERİDE',
          S19['durum'] in ('BAŞLANMADI', 'GERİDE', 'DEVAM'),
          f"durum={S19['durum']}")

# ── popup parity ────────────────────────────────────────────────────────────
if S86:
    lots = m_emirler_lazy(con, 33786, 83530, 'CRP-81315-RL', 2336)
    check('T9  popup m_lotlar prosesler var', lots and lots[0].get('prosesler'),
          f'lots={len(lots)}')
    if lots:
        lk = [p['proses_kod'] for p in lots[0].get('prosesler') or []]
        check('T9b popup ana liste proses kod parity', lk == K86, f'lot={lk} ana={K86}')

# ── Faz2 CRUD regression ────────────────────────────────────────────────────
try:
    merged = merge_plan_korgun({'id': 1, 'plan_donemi': 'bu_hafta'}, S86)
    check('T14 merge_plan_korgun prosesler korunur', 'prosesler' in merged and len(merged['prosesler']) >= 2)
except Exception as ex:
    fail('T14', str(ex)[:120])

# ── /hedef hareket parity (33785 enj biten) ─────────────────────────────────
M85 = [111636,111639,111642,111643,111644,111645,111646,111647,111648,111649,111650]
Y85 = list(range(111637, 111669))
all85 = M85 + Y85
ph = ','.join(['%s'] * len(all85))
c = con.cursor()
c.execute(f"""
    SELECT SUM(Cikan) FROM Urt_con_gch  WHERE EmirNo IN ({ph}) AND Proses='26' AND Cikan>0
    UNION ALL
    SELECT SUM(Cikan) FROM Urtx_con_gch WHERE EmirNo IN ({ph}) AND Proses='26' AND Cikan>0
""", tuple(all85) * 2)
hedef_biten = sum(int(float(r[0] or 0)) for r in c.fetchall())
if enj85:
    check('T15 /hedef enjeksiyon biten parity (33785)',
          int(enj85.get('biten') or 0) == hedef_biten,
          f"up={enj85.get('biten')} hedef={hedef_biten}")

# ── yuzde cap ───────────────────────────────────────────────────────────────
check('T cap yuzde(9000,8000)=100', _yuzde(9000, 8000) == 100.0)

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    print('FAIL:', failed)
    sys.exit(1)
print('TÜM TESTLER GEÇTİ')

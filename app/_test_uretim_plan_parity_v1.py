# -*- coding: utf-8 -*-
"""
T1–T12  Üretim Plan — Korgun Parity Lock Tests
Pilot: 33785 / CRP-81311RL
READ-ONLY: Korgun'a write yok.
"""
from __future__ import annotations
import sys
sys.stdout.reconfigure(encoding='utf-8')
import math
from collections import defaultdict
from modules.common import korgun as kk
from modules.planlama.uretim_plan_service import (
    _kategori, _load_emir_hareket, siparis_model_satirlari,
    model_satir_by_canonical, _yuzde, _proses_by_kod,
)

# ── Yardımcılar ─────────────────────────────────────────────────────────────
passed = []
failed = []

def ok(label):
    passed.append(label)
    print(f'  PASS  {label}')

def fail(label, reason=''):
    failed.append(label)
    print(f'  FAIL  {label}' + (f' — {reason}' if reason else ''))

def check(label, condition, reason=''):
    if condition:
        ok(label)
    else:
        fail(label, reason)

# ── Sabit veri ──────────────────────────────────────────────────────────────
SIP85   = 33785
HAR85   = 83529
SKOD85  = 'CRP-81311RL'
RKOD85  = 8
M85     = [111636,111639,111642,111643,111644,111645,111646,111647,111648,111649,111650]
Y85_AKT = [111659,111660,111661,111662,111667,111668]          # FisHarinx üzerinden görünür
Y85_ARC = [111637,111638,111640,111641,111651,111652,111653,   # Urtx'te archive
           111654,111655,111656,111657,111658,111663,111664,111665,111666]

print('=' * 60)
print('Üretim Plan Parity — Lock Test Seti')
print('=' * 60)

con = kk._baglan()

def cur():
    return con.cursor()

# ── T1: Urtx_con_gch archive hareketi görünür ───────────────────────────────
all_y = Y85_AKT + Y85_ARC
ph = ','.join(['%s'] * len(all_y))
c = cur()
giren_map, con_by_emir, wait_by_emir = _load_emir_hareket(c, all_y)
arc_biten = sum(
    int(r.get('biten') or 0)
    for en in Y85_ARC
    for r in con_by_emir.get(en, [])
    if str(r.get('Proses', '')).strip() == '26'
)
check('T1  Urtx_con_gch archive enjeksiyon hareketi görünür', arc_biten > 0,
      f'arc_biten={arc_biten}')

# ── T2: Urtx_wait_gch (wait archive) — şu an boş, ama sorgu çalışır ────────
try:
    _, _, wb = _load_emir_hareket(cur(), M85)
    ok('T2  Urtx_wait_gch UNION sorgusu exception atmadı')
except Exception as ex:
    fail('T2', str(ex)[:120])

# ── T3: EVA ATKI doğru kategori ─────────────────────────────────────────────
check('T3  EVA 8100-P-FATK → ATKI (ModelAdi ile)',
      _kategori('EVA 8100-P-FATK', 'ATKI EVA - 8100-P-F PATIK') == 'ATKI',
      _kategori('EVA 8100-P-FATK', 'ATKI EVA - 8100-P-F PATIK'))

# ── T4: EVA GOVDE doğru kategori ────────────────────────────────────────────
check('T4  EVA CRP-F-8100 → GOVDE (ModelAdi ile)',
      _kategori('EVA CRP-F-8100', 'GOVDE CRP-F-8100 PATIK-FILET') == 'GOVDE',
      _kategori('EVA CRP-F-8100', 'GOVDE CRP-F-8100 PATIK-FILET'))

# ── T5: parent M → tüm gerçek Y child metadata bulunur ──────────────────────
satir = siparis_model_satirlari(con, SIP85)
s = (satir.get('satirlar') or [None])[0]
check('T5  siparis_model_satirlari satır döndü', s is not None)
if s:
    check('T5b y_emir_sayisi = 22 (tüm child yakalandı)',
          s['y_emir_sayisi'] == 22,
          f"y_emir_sayisi={s['y_emir_sayisi']}")

# ── T6: başka siparişin M emirleri 33785'in Y emir listesine girmez ─────────
# 33785'in M emirleri 33786'nın M emirlerini kapsamamalı
m86 = [111669,111670,111671,111672,111673,111674,111675,111676,111677,111678,111679]
kesas = set(M85) & set(m86)
check('T6  33785 ve 33786 M emirleri birbirinden bağımsız', len(kesas) == 0,
      f'kesişen={kesas}')
# 33785'in Y emirleri içinde 33786'ya ait Y emir olmamalı
c6 = cur()
c6.execute("""
    SELECT EmirNo_YM FROM Urt_Em2Em
    WHERE EmirNo IN (111636,111639,111642,111643,111644,111645,111646,111647,111648,111649,111650)
""")
y85_set = {int(r[0]) for r in c6.fetchall()}
c6b = cur()
c6b.execute("""
    SELECT EmirNo_YM FROM Urt_Em2Em
    WHERE EmirNo IN (111669,111670,111671,111672,111673,111674,111675,111676,111677,111678,111679)
""")
y86_set = {int(r[0]) for r in c6b.fetchall()}
kesas_y = y85_set & y86_set
check('T6b 33785 ve 33786 Y emirleri birbirinden ayrı', len(kesas_y) == 0,
      f'kesişen Y={kesas_y}')

# ── T7: 33785 enjeksiyon > 0% ───────────────────────────────────────────────
if s:
    enj = _proses_by_kod(s.get('prosesler'), '26') or {}
    check('T7  33785 enjeksiyon BAŞLANMADI değil',
          enj.get('durum') != 'BAŞLANMADI',
          f"durum={enj.get('durum')}")
    check('T7b 33785 enjeksiyon biten > 0',
          int(enj.get('biten') or 0) > 0,
          f"biten={enj.get('biten')}")
    check('T7c 33785 enjeksiyon yuzde > 0',
          float(enj.get('yuzde') or 0) > 0,
          f"yuzde={enj.get('yuzde')}")

# ── T8: /hedef parity — biten değerleri eşleşmeli ───────────────────────────
# Hedef: Urtx_con_gch'den proses=26 Cikan toplamı
all85 = M85 + Y85_AKT + Y85_ARC
ph_all = ','.join(['%s'] * len(all85))
c8 = cur()
c8.execute(f"""
    SELECT SUM(Cikan) FROM Urt_con_gch  WHERE EmirNo IN ({ph_all}) AND Proses='26' AND Cikan>0
    UNION ALL
    SELECT SUM(Cikan) FROM Urtx_con_gch WHERE EmirNo IN ({ph_all}) AND Proses='26' AND Cikan>0
""", tuple(all85) * 2)
hedef_biten = sum(int(float(r[0] or 0)) for r in c8.fetchall())
if s:
    up_biten = int((_proses_by_kod(s.get('prosesler'), '26') or {}).get('biten') or 0)
    check('T8  33785 enjeksiyon biten = hedef biten',
          up_biten == hedef_biten,
          f'up={up_biten} hedef={hedef_biten}')

# ── T9: biten > verilen → yuzde max 100 ─────────────────────────────────────
# _yuzde(biten, verilen): biten=8000, verilen=9000 → %88.9 (normal)
pct_normal = _yuzde(8000, 9000)
check('T9  yuzde normal (8000/9000) < 100', pct_normal < 100, f'pct={pct_normal}')
# biten > verilen anomali → cap 100
pct_cap = _yuzde(9000, 8000)
check('T9b yuzde anomali (9000/8000) = 100.0 cap', pct_cap == 100.0, f'pct_cap={pct_cap}')

# ── T10: 33919 BAŞLANMADI regression ────────────────────────────────────────
r19 = siparis_model_satirlari(con, 33919)
s19 = None
if r19:
    for sx in r19.get('satirlar', []):
        if sx.get('model_kod') and 'CRX' in sx.get('model_kod', ''):
            s19 = sx
            break
    if not s19 and r19.get('satirlar'):
        s19 = r19['satirlar'][0]
if s19:
    enj19 = _proses_by_kod(s19.get('prosesler'), '26')
    check('T10 33919 enjeksiyon yok veya BAŞLANMADI',
          enj19 is None or enj19.get('durum') == 'BAŞLANMADI',
          f"enj={enj19}")
    check('T10b 33919 genel BAŞLANMADI (veya GERİDE)',
          s19['durum'] in ('BAŞLANMADI', 'GERİDE'),
          f"durum={s19['durum']}")
else:
    fail('T10 33919 satır bulunamadı')

# ── T11: popup M/Y/proses parity (y_emirler_lazy) ───────────────────────────
from modules.planlama.uretim_plan_service import y_emirler_lazy
try:
    ys_lazy = y_emirler_lazy(con, 111650)   # son M emir
    biten_lazy = sum(int(y.get('biten') or 0) for y in ys_lazy if y.get('proses_kod') == '26')
    check('T11 y_emirler_lazy — son M emir Y emirleri getirildi', len(ys_lazy) > 0,
          f'y_count={len(ys_lazy)}')
    check('T11b y_emirler_lazy biten > 0', biten_lazy > 0, f'biten={biten_lazy}')
except Exception as ex:
    fail('T11 Exception: ' + str(ex)[:120])

# ── T12: Faz 2 regression — uretim_plan_service import OK ───────────────────
try:
    from modules.planlama.uretim_plan_service import (
        merge_plan_korgun, proses_detay_lazy,
        siparis_model_satirlari, model_satir_by_canonical,
    )
    ok('T12 Faz 2 import regression OK')
except ImportError as ie:
    fail('T12 Import hatası: ' + str(ie))

con.close()

# ── Özet ────────────────────────────────────────────────────────────────────
print()
print('=' * 60)
print(f'PASS: {len(passed)}  FAIL: {len(failed)}')
if failed:
    print('BAŞARISIZ:', failed)
else:
    print('TÜM TESTLER BAŞARILI')
print('=' * 60)

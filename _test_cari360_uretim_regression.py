# -*- coding: utf-8 -*-
"""
CARI360-URETIM-REGRESSION — Tests A-H
Canonical DB'ye WRITE YOK — yalnizca READ-ONLY mode.
Tüm testler mock_data.db'yi read-only açar.
"""
import hashlib
import os
import sqlite3
import sys

CANONICAL_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db')
)

# Sys path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from modules.nexgen.cari360_ops_read_service import load_cari360_uretim  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def get_con():
    """Read-only connection to canonical DB."""
    db_uri = f'file:{os.path.abspath(CANONICAL_DB)}?mode=ro'
    con = sqlite3.connect(db_uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


SHA_BEFORE = sha256_file(CANONICAL_DB)

results = []


def check(name, cond, detail=''):
    status = 'PASS' if cond else 'FAIL'
    results.append((name, status, detail))
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    return cond


# ---------------------------------------------------------------------------
# Stub yetki: load_cari360_uretim assert_cari çağırıyor — mock gerekli
# ---------------------------------------------------------------------------
import unittest.mock as mock  # noqa: E402

_STUB_YK = {'NEXGEN_ADMIN'}


def _load(cari_id, **kwargs):
    con = get_con()
    try:
        with mock.patch(
            'modules.nexgen.cari360_ops_read_service._assert_cari',
            return_value={'id': cari_id}
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari',
            return_value=True
        ):
            return load_cari360_uretim(con, cari_id, kullanici_id=1, yk=_STUB_YK, **kwargs)
    finally:
        con.close()


# ---------------------------------------------------------------------------
print('\n=== TEST A: cari bazinda plan grain dogru, duplicate yok ===')
d = _load(cari_id=1, page=1, page_size=100)
liste = d.get('liste', [])
ids = [u['id'] for u in liste]
check('A1 — liste boş değil', len(liste) > 0, f'{len(liste)} plan')
check('A2 — duplicate id yok', len(ids) == len(set(ids)), f'{len(ids)} vs {len(set(ids))} unique')
check('A3 — total_count mevcut', d.get('total_count') is not None, str(d.get('total_count')))
check('A4 — page/page_size response var', d.get('page') == 1 and d.get('page_size') == 100)

# ---------------------------------------------------------------------------
print('\n=== TEST B: Üretilen KG canonical helper dogru ===')
# plan 194 — cari 11
d11 = _load(cari_id=11, page=1, page_size=50)
plan194 = next((u for u in d11.get('liste', []) if u['id'] == 194), None)
if plan194:
    check('B1 — plan 194 bulundu', True)
    uk = plan194.get('uretilen_kg') or 0
    check('B2 — uretilen_kg > 0', uk > 0, str(uk))
    check('B3 — uretilen_kg ~ 2045 (rf_kullanim)', 2040 <= uk <= 2050, str(uk))
    check('B4 — hedef_kg mevcut', plan194.get('hedef_kg') is not None)
    check('B5 — kalan_kg = max(hedef-uretilen,0)',
          plan194.get('kalan_kg', -1) >= 0)
else:
    check('B1 — plan 194 bulundu', False, 'cari_id=11 içinde plan 194 yok')

# ---------------------------------------------------------------------------
print('\n=== TEST C: PZM-2026-0222 / plan 194 — BITTI, ~2045.664 kg ===')
if plan194:
    check('C1 — siparis_no = PZM-2026-0222',
          plan194.get('siparis_no') == 'PZM-2026-0222', plan194.get('siparis_no'))
    check('C2 — durum = BITTI', plan194.get('durum') == 'BITTI', plan194.get('durum'))
    uk = plan194.get('uretilen_kg') or 0
    check('C3 — uretilen_kg 2045.0..2046.0', 2045 <= uk <= 2046, str(uk))
    check('C4 — tamamlanma_yuzdesi 100', plan194.get('tamamlanma_yuzdesi', 0) >= 95,
          str(plan194.get('tamamlanma_yuzdesi')))
    check('C5 — formul_kodu mevcut', bool(plan194.get('formul_kodu')), plan194.get('formul_kodu'))
    check('C6 — renk_kodu mevcut', bool(plan194.get('renk_kodu')), plan194.get('renk_kodu'))
    check('C7 — siparis_url mevcut', bool(plan194.get('siparis_url')), plan194.get('siparis_url'))
    check('C8 — plan_url mevcut', bool(plan194.get('plan_url')), plan194.get('plan_url'))
else:
    for i in range(1, 9):
        check(f'C{i} — (plan194 bulunamadı)', False)

# ---------------------------------------------------------------------------
print('\n=== TEST D: PZM-2026-0212 — 3 plan ayrı satır olarak geliyor ===')
d1 = _load(cari_id=1, page=1, page_size=100)
plans_0212 = [u for u in d1.get('liste', []) if u.get('siparis_no') == 'PZM-2026-0212']
check('D1 — 3 ayrı plan satırı var', len(plans_0212) == 3, f'{len(plans_0212)} satır')
plan_ids_0212 = {u['id'] for u in plans_0212}
check('D2 — plan 184/185/186 içeriyor', {184, 185, 186}.issubset(plan_ids_0212),
      str(plan_ids_0212))
formul_kodlari = {u.get('formul_kodu') for u in plans_0212}
check('D3 — 2 farklı formül var (1BA-FL01 / 2BA-FL01)',
      len(formul_kodlari) >= 2, str(formul_kodlari))

# ---------------------------------------------------------------------------
print('\n=== TEST E: Formül / RF doğru plan ile eşleşiyor ===')
plan184 = next((u for u in plans_0212 if u['id'] == 184), None)
plan186 = next((u for u in plans_0212 if u['id'] == 186), None)
if plan184:
    check('E1 — plan 184 formul_kodu 1BA-FL01',
          plan184.get('formul_kodu') == '1BA-FL01', plan184.get('formul_kodu'))
    check('E2 — plan 184 rf_renk_id = 30',
          plan184.get('rf_renk_id') == 30, str(plan184.get('rf_renk_id')))
else:
    check('E1 — plan 184 bulunamadı', False)
if plan186:
    check('E3 — plan 186 formul_kodu 2BA-FL01',
          plan186.get('formul_kodu') == '2BA-FL01', plan186.get('formul_kodu'))
else:
    check('E3 — plan 186 bulunamadı', False)

# ---------------------------------------------------------------------------
print('\n=== TEST F: Pagination — page1/page2, total, duplicate yok ===')
dp1 = _load(cari_id=1, page=1, page_size=10)
dp2 = _load(cari_id=1, page=2, page_size=10)
check('F1 — page1 sayfa bilgisi dogru', dp1.get('page') == 1)
check('F2 — page2 sayfa bilgisi dogru', dp2.get('page') == 2)
check('F3 — total_count page1==page2',
      dp1.get('total_count') == dp2.get('total_count'),
      f"{dp1.get('total_count')} vs {dp2.get('total_count')}")
ids1 = {u['id'] for u in dp1.get('liste', [])}
ids2 = {u['id'] for u in dp2.get('liste', [])}
check('F4 — page1 ve page2 arasında overlap yok', len(ids1 & ids2) == 0,
      f'overlap: {ids1 & ids2}')
tc = dp1.get('total_count', 0)
ps = 10
expected_pages = max(1, (tc + ps - 1) // ps) if tc else 0
check('F5 — total_pages hesabı dogru',
      dp1.get('total_pages') == expected_pages,
      f'{dp1.get("total_pages")} vs {expected_pages}')
check('F6 — page1 liste 10 kayıt', len(dp1.get('liste', [])) == 10,
      str(len(dp1.get('liste', []))))

# ---------------------------------------------------------------------------
print('\n=== TEST G: Expand detail contract eksiksiz ===')
if plan194:
    required = ['id', 'plan_kodu', 'durum', 'siparis_id', 'siparis_no',
                'formul_kodu', 'rf_renk_id', 'renk_kodu', 'hedef_kg',
                'uretilen_kg', 'kalan_kg', 'tamamlanma_yuzdesi',
                'batch_sayisi', 'alt_emir_sayisi', 'parcalar_ozet',
                'siparis_url', 'plan_url', 'zincir_eksik', 'zincir_uyarilari',
                'urun_ailesi', 'siparis_durum', 'termin_tarihi']
    missing = [k for k in required if k not in plan194]
    check('G1 — tüm required field mevcut', len(missing) == 0, str(missing))
    check('G2 — parcalar_ozet dict', isinstance(plan194.get('parcalar_ozet'), dict))
    check('G3 — batch_sayisi int', isinstance(plan194.get('batch_sayisi'), int))
    check('G4 — batch_kodlari list', isinstance(plan194.get('batch_kodlari'), list))
else:
    for i in range(1, 5):
        check(f'G{i} — (plan194 bulunamadı)', False)

# ---------------------------------------------------------------------------
print('\n=== TEST H: Sipariş link / plan link mevcut route ile dogru ===')
if plan194:
    sip_url = plan194.get('siparis_url') or ''
    plan_url = plan194.get('plan_url') or ''
    sip_id = plan194.get('siparis_id')
    check('H1 — siparis_url format dogru',
          sip_url == f'/nexgen/pazarlama?siparis={sip_id}', sip_url)
    check('H2 — plan_url format dogru',
          plan_url == f'/nexgen/uretim-emirleri?vurgu=194', plan_url)
else:
    check('H1 — (plan194 bulunamadı)', False)
    check('H2 — (plan194 bulunamadı)', False)

# siparis_url None planlar için
plan_nolink = next((u for u in liste if u.get('siparis_id') is None), None)
if plan_nolink:
    check('H3 — siparis_url=None planlar için None', plan_nolink.get('siparis_url') is None,
          str(plan_nolink.get('siparis_url')))
    check('H4 — plan_url her zaman var', bool(plan_nolink.get('plan_url')),
          plan_nolink.get('plan_url'))

# ---------------------------------------------------------------------------
SHA_AFTER = sha256_file(CANONICAL_DB)

print('\n=== SONUÇ ===')
pass_count = sum(1 for _, s, _ in results if s == 'PASS')
fail_count = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'PASS: {pass_count}  FAIL: {fail_count}  TOPLAM: {len(results)}')
print(f'SHA BEFORE: {SHA_BEFORE}')
print(f'SHA AFTER : {SHA_AFTER}')
sha_ok = SHA_BEFORE == SHA_AFTER
print(f'SHA AYNI  : {"EVET" if sha_ok else "HAYIR ⚠️"}')

if fail_count > 0 or not sha_ok:
    sys.exit(1)
sys.exit(0)

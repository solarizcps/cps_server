# -*- coding: utf-8 -*-
"""
CARI360-URETIM-DOM-TESTS — I-P (UI-03 revision)
Static HTML/JS source verification — no browser needed.
"""
import hashlib
import os
import re
import sys

TEMPLATE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'app', 'templates', 'nexgen', 'cari360_kart.html'
)
CANONICAL_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db'
)

SHA_BEFORE = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()

src = open(TEMPLATE, encoding='utf-8').read()

results = []


def check(name, cond, detail=''):
    status = 'PASS' if cond else 'FAIL'
    results.append((name, status, detail))
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    return cond


# ---------------------------------------------------------------------------
print('\n=== TEST I: Sipariş Durumu var, Üretim Durumu ANA TABLODAN KALDIRILDI ===')
check('I1 — thead "Sipariş Durumu" header VAR', 'Sipariş Durumu' in src)
check('I2 — _urtSipDurumBadge fonksiyonu tanımlı', 'function _urtSipDurumBadge' in src)
check('I3 — u.siparis_durum okunuyor', 'u.siparis_durum' in src)
check('I4 — thead "Üretim Durumu" header YOK', 'Üretim Durumu' not in src,
      'Üretim Durumu hâlâ var' if 'Üretim Durumu' in src else 'OK')
check('I5 — _urtDurumBadge(u.durum) ana satırda YOK', '_urtDurumBadge(u.durum)' not in src,
      '_urtDurumBadge(u.durum) hâlâ var' if '_urtDurumBadge(u.durum)' in src else 'OK')
check('I6 — _urtDurumBadge fonksiyon tanımı korunuyor (expand için)', 'function _urtDurumBadge' in src)

# ---------------------------------------------------------------------------
print('\n=== TEST J: Tarih PLAN\'dan önce ===')
# thead sırasını kontrol et
thead_match = re.search(r'<thead>.*?</thead>', src, re.DOTALL)
if thead_match:
    thead = thead_match.group(0)
    tarih_pos = thead.find('Tarih')
    plan_pos  = thead.find('>Plan<')
    check('J1 — thead Tarih var', tarih_pos != -1)
    check('J2 — thead Plan var', plan_pos != -1)
    check('J3 — Tarih Plan\'dan önce (thead sırası)', tarih_pos < plan_pos,
          f'Tarih@{tarih_pos} Plan@{plan_pos}')
else:
    check('J1', False, 'thead bulunamadı')
    check('J2', False, '')
    check('J3', False, '')

# JS satır render sırası: tarih td, sonra plan td
# "white-space:nowrap" tarih hücresinin, ardından plan_kodu için strong gelmeli
tarih_td_pos  = src.find("plan_tarihi ? u.plan_tarihi.substring(0,10)")
plan_td_pos   = src.find("u.plan_kodu || '—'")
check('J4 — JS satırda tarih td PLAN td\'den önce render', 0 < tarih_td_pos < plan_td_pos,
      f'tarih@{tarih_td_pos} plan@{plan_td_pos}')

# ---------------------------------------------------------------------------
print('\n=== TEST K: renk_ad render korunuyor ===')
check('K1 — _urtRenkCell fonksiyonu tanımlı', 'function _urtRenkCell' in src)
check('K2 — u.renk_ad okunuyor', 'u.renk_ad' in src)
check('K3 — "—" separator ayrıştırma var', "split('—')" in src or "split('\\u2014')" in src or "split('\u2014')" in src or '— ' in src)
check('K4 — _urtRenkCell ana tabloda kullanılıyor', '_urtRenkCell(u)' in src)

# ---------------------------------------------------------------------------
print('\n=== TEST L: İlerleme korunuyor ===')
check('L1 — thead "İlerleme" header var', 'İlerleme' in src)
check('L2 — _urtProgressCell fonksiyonu tanımlı', 'function _urtProgressCell' in src)
check('L3 — _urtProgressCell ana tabloda kullanılıyor', '_urtProgressCell(u.tamamlanma_yuzdesi)' in src)

# ---------------------------------------------------------------------------
print('\n=== TEST M: Expand 4 blok korunuyor ===')
check('M1 — Sipariş Bilgisi blok var', 'Sipariş Bilgisi' in src)
check('M2 — Teknik Bilgi blok var', 'Teknik Bilgi' in src)
check('M3 — Üretim İlerlemesi blok var', 'Üretim İlerlemesi' in src)
check('M4 — Üretim Yapısı blok var', 'Üretim Yapısı' in src)
check('M5 — Siparişe Git link var', 'Siparişe Git' in src)
check('M6 — Üretim Emri Detayı link var', 'Üretim Emri Detayı' in src)

# ---------------------------------------------------------------------------
print('\n=== TEST N: Pagination korunuyor ===')
check('N1 — ckart-uretim-pagination div var', 'ckart-uretim-pagination' in src)
check('N2 — ckartUretimPaginationRender fonksiyonu var', 'function ckartUretimPaginationRender' in src)
check('N3 — ckartUretimGitPage fonksiyonu var', 'window.ckartUretimGitPage' in src)

# ---------------------------------------------------------------------------
print('\n=== TEST O: colspan 13 kalmadı, colspan 12 var ===')
old_c13 = [m.start() for m in re.finditer(r"colspan=['\"]13['\"]", src)]
new_c12 = [m.start() for m in re.finditer(r"colspan=['\"]12['\"]", src)]
check('O1 — eski colspan=13 YOK', len(old_c13) == 0, f'{len(old_c13)} adet kaldı')
check('O2 — yeni colspan=12 VAR', len(new_c12) >= 3, f'{len(new_c12)} adet')

# ---------------------------------------------------------------------------
print('\n=== TEST P: API contract verisi + ikili gösterim ===')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))
try:
    import sqlite3
    import unittest.mock as mock
    from modules.nexgen.cari360_ops_read_service import load_cari360_uretim

    db_uri = f'file:{os.path.abspath(CANONICAL_DB)}?mode=ro'
    con = sqlite3.connect(db_uri, uri=True)
    con.row_factory = sqlite3.Row

    with mock.patch('modules.nexgen.cari360_ops_read_service._assert_cari', return_value={'id': 1}), \
         mock.patch('modules.nexgen.cari360_ops_read_service.can_view_cari', return_value=True):
        d1 = load_cari360_uretim(con, 1, 1, None, page=1, page_size=100)

    with mock.patch('modules.nexgen.cari360_ops_read_service._assert_cari', return_value={'id': 11}), \
         mock.patch('modules.nexgen.cari360_ops_read_service.can_view_cari', return_value=True):
        d11 = load_cari360_uretim(con, 11, 1, None, page=1, page_size=50)
    con.close()

    # PZM-0212 — 3 satır
    plans_0212 = [u for u in d1.get('liste', []) if u.get('siparis_no') == 'PZM-2026-0212']
    check('P1 — PZM-0212 3 plan var', len(plans_0212) == 3, f'{len(plans_0212)} satır')

    # siparis_durum mevcut
    check('P2 — siparis_durum mevcut (PZM-0212)', all(u.get('siparis_durum') for u in plans_0212),
          str([u.get('siparis_durum') for u in plans_0212]))

    # formul_ad mevcut (ikili gösterim için)
    check('P3 — formul_ad mevcut (PZM-0212)', all(u.get('formul_ad') for u in plans_0212),
          str([u.get('formul_ad') for u in plans_0212]))

    # renk_ad mevcut
    check('P4 — renk_ad mevcut (PZM-0212)', all(u.get('renk_ad') is not None for u in plans_0212),
          str([u.get('renk_ad') for u in plans_0212]))

    # plan_tarihi mevcut (Tarih kolonu için)
    check('P5 — plan_tarihi mevcut (PZM-0212)', all(u.get('plan_tarihi') for u in plans_0212),
          str([u.get('plan_tarihi') for u in plans_0212]))

    # PZM-0222 — plan 194
    plan194 = next((u for u in d11.get('liste', []) if u['id'] == 194), None)
    check('P6 — plan 194 bulundu', plan194 is not None)
    if plan194:
        uk = plan194.get('uretilen_kg') or 0
        check('P7 — uretilen_kg 2045..2046', 2045 <= uk <= 2046, str(uk))
        check('P8 — tamamlanma_yuzdesi 100', plan194.get('tamamlanma_yuzdesi') == 100,
              str(plan194.get('tamamlanma_yuzdesi')))
        check('P9 — plan_tarihi mevcut', bool(plan194.get('plan_tarihi')), plan194.get('plan_tarihi'))
        check('P10 — siparis_durum TAMAMLANDI', plan194.get('siparis_durum') == 'TAMAMLANDI',
              plan194.get('siparis_durum'))
except Exception as ex:
    for i in range(1, 11):
        check(f'P{i} — hata', False, str(ex))

# ---------------------------------------------------------------------------
print('\n=== STATIK JS / ÜRÜN-FORMÜL-RENK KORUNMA ===')
check('S1 — _urtUrunCell fonksiyonu tanımlı', 'function _urtUrunCell' in src)
check('S2 — _urtFormulCell fonksiyonu tanımlı', 'function _urtFormulCell' in src)
check('S3 — formul_farkli chip korunuyor', 'formul_farkli' in src)
check('S4 — renk_farkli chip korunuyor', 'renk_farkli' in src)
check('S5 — secondary text (10px) var (ikili gösterim)', 'font-size:10px' in src)
check('S6 — _urtUrunCell ana tabloda kullanılıyor', '_urtUrunCell(u)' in src)
check('S7 — _urtFormulCell ana tabloda kullanılıyor', '_urtFormulCell(u)' in src)

# ---------------------------------------------------------------------------
SHA_AFTER = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()

print('\n=== SONUÇ ===')
pass_c = sum(1 for _, s, _ in results if s == 'PASS')
fail_c = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'PASS: {pass_c}  FAIL: {fail_c}  TOPLAM: {len(results)}')
print(f'SHA BEFORE: {SHA_BEFORE}')
print(f'SHA AFTER : {SHA_AFTER}')
sha_ok = SHA_BEFORE == SHA_AFTER
print(f'SHA AYNI  : {"EVET" if sha_ok else "HAYIR ⚠️"}')

if fail_c > 0 or not sha_ok:
    sys.exit(1)
sys.exit(0)

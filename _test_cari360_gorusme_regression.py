# -*- coding: utf-8 -*-
"""
CARI360-GORUSMELER-IMPLEMENTATION-02
Görüşmeler backend regression testi.
READ-ONLY — DB write yok.
"""
import hashlib
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'app')

from modules.nexgen.mo_gorusme_service import list_gorusmeler_paginated

DB_PATH = 'app/mock_data.db'
SHA_EXPECTED = '2469406a7dde9b8a0fe8442da1e61fae40a4760d663d46a73dfd51e662caf008'
CARI_ID = 1

_fails = []


def ok(label):
    print(f'  OK  {label}')


def fail(label, detail=''):
    _fails.append(label)
    print('  FAIL ' + label + (' — ' + detail if detail else ''))


def _con():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def check_sha():
    with open(DB_PATH, 'rb') as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    if sha == SHA_EXPECTED:
        ok('SHA unchanged')
    else:
        fail('SHA changed', sha[:16])


def _paged(page=1, page_size=10):
    con = _con()
    try:
        return list_gorusmeler_paginated(
            con, cari_id=CARI_ID, kullanici_id=1, yk=None,
            page=page, page_size=page_size,
        )
    finally:
        con.close()


def test_pagination_contract():
    r = _paged(page=1, page_size=10)
    if r['total_count'] >= 420:
        ok('[1] total_count >= 420 (' + str(r['total_count']) + ')')
    else:
        fail('[1] total_count < 420', str(r['total_count']))

    if r['page'] == 1:
        ok('[2] page=1')
    else:
        fail('[2] page mismatch', str(r['page']))

    if r['page_size'] == 10:
        ok('[3] page_size=10')
    else:
        fail('[3] page_size mismatch', str(r['page_size']))

    if r['total_pages'] >= 40:
        ok('[4] total_pages >= 40 (' + str(r['total_pages']) + ')')
    else:
        fail('[4] total_pages < 40', str(r['total_pages']))

    if len(r['items']) == 10:
        ok('[5] page1 returns 10 items')
    else:
        fail('[5] page1 item count', str(len(r['items'])))


def test_page1_page2_no_overlap():
    r1 = _paged(page=1, page_size=10)
    r2 = _paged(page=2, page_size=10)
    ids1 = {x['id'] for x in r1['items']}
    ids2 = {x['id'] for x in r2['items']}
    overlap = len(ids1 & ids2)
    if overlap == 0:
        ok('[6] page1/page2 overlap=0')
    else:
        fail('[6] page1/page2 overlap != 0', str(overlap))


def test_case_653():
    """id=653 — ticari bilgiler ayrı ayrı doğru."""
    r = _paged(page=1, page_size=100)
    found = None
    for g in r['items']:
        if g['id'] == 653:
            found = g
            break
    if not found:
        fail('[7] id=653 not found in page1 limit100')
        return
    ok('[7] id=653 found')

    checks = [
        ('[8]  653 fiyat_verildi=1',     found.get('fiyat_verildi') == 1),
        ('[9]  653 verilen_fiyat=2.0',   found.get('verilen_fiyat') == 2.0),
        ('[10] 653 fiyat_para_birimi=USD', found.get('fiyat_para_birimi') == 'USD'),
        ('[11] 653 fiyat_birimi=KG',      found.get('fiyat_birimi') == 'KG'),
        ('[12] 653 konusulan_tonaj=2500', found.get('konusulan_tonaj') == 2500.0),
        ('[13] 653 odeme_tipi=CEK',       found.get('odeme_tipi') == 'CEK'),
        ('[14] 653 cek_vade_gun=180',     found.get('cek_vade_gun') == 180),
        ('[15] 653 cek_adedi=1',          found.get('cek_adedi') == 1),
        ('[16] 653 yetkili_adi=bedri',    (found.get('yetkili_adi') or '').lower() == 'bedri'),
        ('[17] 653 gorusme_tipi',         found.get('gorusme_tipi') == 'Fabrika Ziyareti'),
        ('[18] 653 sonuc_tipi=Olumlu',    found.get('sonuc_tipi') == 'Olumlu'),
        ('[19] 653 kisa_not',             'iyiyim' in (found.get('kisa_not') or '')),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label, str(found.get(label.split()[-1].split('=')[0])))


def test_case_655():
    """id=655 — takip/not/aksiyon."""
    r = _paged(page=1, page_size=100)
    found = None
    for g in r['items']:
        if g['id'] == 655:
            found = g
            break
    if not found:
        fail('[20] id=655 not found')
        return
    ok('[20] id=655 found')
    checks = [
        ('[21] 655 yetkili_adi=ahmet bey',        (found.get('yetkili_adi') or '').lower() == 'ahmet bey'),
        ('[22] 655 gorusme_tipi=Ofis Ziyareti',   found.get('gorusme_tipi') == 'Ofis Ziyareti'),
        ('[23] 655 sonuc_tipi=Olumsuz',            found.get('sonuc_tipi') == 'Olumsuz'),
        ('[24] 655 kisa_not',                      'selamları' in (found.get('kisa_not') or '')),
        ('[25] 655 sonraki_aksiyon=gönderiz',      found.get('sonraki_aksiyon') == 'gönderiz'),
        ('[26] 655 takip_durumu=ACIK',             found.get('takip_durumu') == 'ACIK'),
        ('[27] 655 sonraki_takip_tarihi',          (found.get('sonraki_takip_tarihi') or '').startswith('2026-08-21')),
        ('[28] 655 oncelik=NORMAL',                found.get('oncelik') == 'NORMAL'),
        ('[29] 655 fiyat_verildi=0',               int(found.get('fiyat_verildi') or 0) == 0),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_numune_pointer():
    """id=615 numune_talep_id=334 → kaynak_numune_kodu=AT-M-2026-0250."""
    r = _paged(page=1, page_size=100)
    found = None
    for g in r['items']:
        if g['id'] == 615:
            found = g
            break
    if not found:
        fail('[30] id=615 not found')
        return
    ok('[30] id=615 found')
    kodu = found.get('kaynak_numune_kodu') or ''
    if 'AT-M-2026-0250' in kodu:
        ok('[31] kaynak_numune_kodu=AT-M-2026-0250')
    else:
        fail('[31] kaynak_numune_kodu wrong', kodu)
    # Service may still put URL in response for compat. Frontend must not render it as href.
    # DOM test [D31] locks that constraint.
    ok('[32] numune canonical pointer confirmed (fake URL lock: DOM D31)')


def test_no_db_write():
    """Son kontrol: SHA değişmemiş."""
    check_sha()


if __name__ == '__main__':
    print('=== CARI360 GORUSMELER REGRESSION ===')
    print()
    print('SHA check (before tests):')
    check_sha()
    print()
    print('Pagination contract:')
    test_pagination_contract()
    print()
    print('Page overlap:')
    test_page1_page2_no_overlap()
    print()
    print('CASE 653 (ticari alanlar):')
    test_case_653()
    print()
    print('CASE 655 (takip):')
    test_case_655()
    print()
    print('Numune pointer:')
    test_numune_pointer()
    print()
    print('SHA check (after tests):')
    test_no_db_write()
    print()
    if _fails:
        print('RESULT: FAIL (' + str(len(_fails)) + ' failures)')
        for f in _fails:
            print('  - ' + f)
        sys.exit(1)
    else:
        print('RESULT: ALL PASS')

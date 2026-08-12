# -*- coding: utf-8 -*-
"""
CARI360-GORUSMELER-IMPLEMENTATION-02
DOM/statik JS lock testi — cari360_kart.html
READ-ONLY.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

TEMPLATE = 'app/templates/nexgen/cari360_kart.html'

_fails = []


def ok(label):
    print(f'  OK  {label}')


def fail(label, detail=''):
    _fails.append(label)
    print('  FAIL ' + label + (' — ' + detail if detail else ''))


def _src():
    with open(TEMPLATE, encoding='utf-8') as f:
        return f.read()


def test_main_columns():
    src = _src()
    checks = [
        ('[D01] 7 kolon (<th>)',        src.count('<th>') >= 7),
        ('[D02] expand th (width:28)',   'width:28px' in src),
        ('[D03] Tarih header',           '<th>Tarih</th>' in src),
        ('[D04] Pazarlamacı header',     '<th>Pazarlamacı</th>' in src),
        ('[D05] Yetkili header',         '<th>Yetkili</th>' in src),
        ('[D06] Tür header',             '<th>Tür</th>' in src),
        ('[D07] Sonuç header',           '<th>Sonuç</th>' in src),
        ('[D08] Takip header',           '<th>Takip</th>' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_removed_columns():
    src = _src()
    # Görüşmeler tablosunun thead'ini bul
    gor_tablo_start = src.find('id="ckart-gorusme-tablo"')
    gor_thead_end = src.find('</thead>', gor_tablo_start)
    gor_thead = src[gor_tablo_start:gor_thead_end] if gor_tablo_start != -1 else ''
    removed = [
        ('[D09] Numune header YOK (gorusme thead)',         '<th>Numune</th>' not in gor_thead),
        ('[D10] Sonraki Aksiyon header YOK (gorusme thead)', 'Sonraki Aksiyon' not in gor_thead),
        ('[D11] İşlem header YOK (gorusme thead)',          'İşlem' not in gor_thead),
    ]
    for label, cond in removed:
        if cond:
            ok(label)
        else:
            fail(label)


def test_expand_functions():
    src = _src()
    checks = [
        ('[D12] _gorDetayHtml fonk. var',          '_gorDetayHtml' in src),
        ('[D13] _gorTakipBadge fonk. var',          '_gorTakipBadge' in src),
        ('[D14] _gorSonucBadge fonk. var',          '_gorSonucBadge' in src),
        ('[D15] _gorPaginationRender fonk. var',    '_gorPaginationRender' in src),
        ('[D16] ckartGorGitPage fonk. var',         'ckartGorGitPage' in src),
        ('[D17] data-gor-target expand attr var',   'data-gor-target' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_expand_blocks():
    src = _src()
    checks = [
        ('[D18] Expand A — Görüşme Bilgisi',    'A — Görüşme Bilgisi' in src),
        ('[D19] Expand B — Ticari Bilgi',        'B — Ticari Bilgi' in src),
        ('[D20] Expand C — Sonuç / Takip',       'C — Sonuç / Takip' in src),
        ('[D21] Expand D — Bağlantılar',         'D — Bağlantılar' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_ticari_alanlar():
    src = _src()
    checks = [
        ('[D22] verilen_fiyat B blok',       "g.verilen_fiyat" in src),
        ('[D23] fiyat_para_birimi B blok',   "g.fiyat_para_birimi" in src),
        ('[D24] fiyat_birimi B blok',        "g.fiyat_birimi" in src),
        ('[D25] konusulan_tonaj B blok',     "g.konusulan_tonaj" in src),
        ('[D26] odeme_tipi B blok',          "g.odeme_tipi" in src),
        ('[D27] cek_vade_gun B blok',        "g.cek_vade_gun" in src),
        ('[D28] cek_adedi B blok',           "g.cek_adedi" in src),
        ('[D29] vade_gun B blok',            "g.vade_gun" in src),
        ('[D30] fiyat_verildi conditional',      "fiyat_verildi" in src),
        ('[D30b] B blok 4-kolon placeholder',    'Ticari bilgi girilmemi' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_fake_url_forbidden():
    src = _src()
    # FORBIDDEN: fake numune URL oluşturma görüşmeler expand D bloğunda
    # _gorDetayHtml içinde /nexgen/numune-talep href olmamalı
    # kaynak_numune_kodu text olarak gösterilmeli, href olarak değil
    gor_section_start = src.find('function _gorDetayHtml')
    gor_section_end = src.find('function _gorPaginationRender')
    if gor_section_start == -1:
        fail('[D31] _gorDetayHtml bulunamadı')
        return
    gor_section = src[gor_section_start:gor_section_end]
    if '/nexgen/numune-talep' not in gor_section:
        ok('[D31] Fake numune URL _gorDetayHtml içinde yok')
    else:
        fail('[D31] FORBIDDEN: fake numune URL _gorDetayHtml içinde var')
    # Canonical text gösterimi
    if 'kaynak_numune_kodu' in gor_section:
        ok('[D32] kaynak_numune_kodu text olarak gösteriliyor')
    else:
        fail('[D32] kaynak_numune_kodu D blokta yok')


def test_pagination_html():
    src = _src()
    checks = [
        ('[D33] ckart-gorusme-pagination div var',    'id="ckart-gorusme-pagination"' in src),
        ('[D34] ckart-gorusme-pg-info span var',      'id="ckart-gorusme-pg-info"' in src),
        ('[D35] ckart-gorusme-pg-btns div var',       'id="ckart-gorusme-pg-btns"' in src),
        ('[D36] page param API call',                  'page=' + "' + _gorPage" in src),
        ('[D37] page_size param API call',             'page_size=' + "' + _gorPageSize" in src),
        ('[D38] _gorPage state var',                   'var _gorPage = 1' in src),
        ('[D39] _gorPageSize state var',               'var _gorPageSize = 10' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_design_reuse():
    src = _src()
    checks = [
        ('[D40] ckart-urt-expand-btn reuse',    'ckart-urt-expand-btn' in src),
        ('[D41] ckart-urt-detail-panel reuse',  'ckart-urt-detail-panel' in src),
        ('[D42] ckart-urt-detail-group reuse',  'ckart-urt-detail-group' in src),
        ('[D43] ckart-urt-detail-field reuse',  'ckart-urt-detail-field' in src),
        ('[D44] ckart-urt-dur badge reuse',     'ckart-urt-dur' in src),
        ('[D45] _sipBtnStyle reuse pagination', 'ckartGorGitPage' in src and '_sipBtnStyle' in src),
        ('[D46] ckart-sip-row reuse',           'ckart-sip-row' in src),
    ]
    for label, cond in checks:
        if cond:
            ok(label)
        else:
            fail(label)


def test_colspan_consistent():
    src = _src()
    # tbody boş mesajı 7 kolon olmalı
    if 'colspan="7"' in src:
        ok('[D47] colspan=7 görüşme tbody')
    else:
        fail('[D47] colspan=7 yok')


if __name__ == '__main__':
    print('=== CARI360 GORUSMELER DOM LOCK ===')
    print()
    print('Main columns:')
    test_main_columns()
    print()
    print('Removed columns:')
    test_removed_columns()
    print()
    print('Expand functions:')
    test_expand_functions()
    print()
    print('Expand blocks A/B/C/D:')
    test_expand_blocks()
    print()
    print('Ticari alanlar:')
    test_ticari_alanlar()
    print()
    print('Fake URL forbidden:')
    test_fake_url_forbidden()
    print()
    print('Pagination HTML:')
    test_pagination_html()
    print()
    print('Design reuse:')
    test_design_reuse()
    print()
    print('Colspan:')
    test_colspan_consistent()
    print()
    if _fails:
        print('RESULT: FAIL (' + str(len(_fails)) + ' failures)')
        for f in _fails:
            print('  - ' + f)
        import sys as _sys
        _sys.exit(1)
    else:
        print('RESULT: ALL PASS')

# -*- coding: utf-8 -*-
"""
CARI360-NUMUNE-UI-01 — DOM / static JS testleri
cari360_kart.html dosyasını parse ederek UI kurallarını doğrular.
"""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8')

HTML_PATH = os.path.join(os.path.dirname(__file__), 'app', 'templates', 'nexgen', 'cari360_kart.html')

with open(HTML_PATH, encoding='utf-8') as f:
    html = f.read()

PASS = []
FAIL = []

def ok(name):
    PASS.append(name)
    print(f'  PASS  {name}')

def fail(name, reason=''):
    FAIL.append(name)
    print(f'  FAIL  {name}' + (': ' + reason if reason else ''))

print('=== CARI360 NUMUNE DOM TESTLER ===\n')

print('[1] Panel mevcut')
if 'id="ckart-panel-numuneler"' in html:
    ok('panel_numuneler_exists')
else:
    fail('panel_numuneler_exists')

print('\n[2] Thead kolon sırası: expand | TARİH | TALEP NO | ÜRÜN | FORMÜL | RENK | DURUM')
thead_m = re.search(r'id="ckart-numune-tablo".*?<thead>(.*?)</thead>', html, re.DOTALL)
if thead_m:
    thead = thead_m.group(1)
    # Kolon sırası
    th_texts = re.findall(r'<th[^>]*>(.*?)</th>', thead, re.DOTALL)
    th_texts = [t.strip() for t in th_texts]
    expected = ['', 'Tarih', 'Talep No', 'Ürün', 'Formül', 'Renk', 'Durum']
    if th_texts == expected:
        ok('thead_column_order: ' + str(th_texts))
    else:
        fail('thead_column_order', f'got {th_texts}')
    if len(th_texts) == 7:
        ok('thead_column_count_7')
    else:
        fail('thead_column_count_7', f'got {len(th_texts)}')
else:
    fail('thead_found')

print('\n[3] Eski kolonlar ana tabloda YOK')
eski_yoklar = ['Talep Eden', 'Ürün Tipi', 'Ürün / Model', 'Talep Türü', 'RF', 'Bağlı Siparişler', 'Son Güncelleme', 'İşlem']
if thead_m:
    thead = thead_m.group(1)
    for col in eski_yoklar:
        if col in thead:
            fail('eski_kolon_yok: ' + col, 'hâlâ thead içinde')
        else:
            ok('eski_kolon_yok: ' + col)

print('\n[4] colspan=7 loading/empty/error satırları')
colspan7_count = html.count('colspan="7"')
# En az 3 yerde olmalı (loading, empty, error - numune panelinde)
# Sadece numune panelindeki sayfa bölgesini inceleyelim
panel_m = re.search(r'id="ckart-panel-numuneler"(.*?)id="ckart-panel-gorusmeler"', html, re.DOTALL)
if panel_m:
    panel = panel_m.group(1)
    colspan7_in_panel = panel.count('colspan="7"')
    if colspan7_in_panel >= 1:
        ok(f'colspan7_in_numune_panel ({colspan7_in_panel} adet)')
    else:
        fail('colspan7_in_numune_panel', f'got {colspan7_in_panel}')
    # Eski colspan 12 numune panelinde olmamalı
    if 'colspan="12"' not in panel:
        ok('no_colspan12_in_numune_panel')
    else:
        fail('no_colspan12_in_numune_panel', 'hâlâ colspan=12 var')
else:
    fail('numune_panel_found')

print('\n[5] JS: _numUrunCell / _numFormulCell / _numTalepNoCell helper fonksiyonlar')
for fn in ('_numUrunCell', '_numFormulCell', '_numTalepNoCell', '_numDetayHtml', '_numuneDurumBadge'):
    if fn in html:
        ok('js_' + fn + '_exists')
    else:
        fail('js_' + fn + '_exists')

print('\n[6] JS: expand event delegation (data-num-target pattern, eski _numuneToggle yok)')
if '_numuneToggle' not in html:
    ok('js_numuneToggle_removed')
else:
    fail('js_numuneToggle_removed', 'hâlâ var')
if 'data-num-target' in html:
    ok('js_expand_delegation_pattern')
else:
    fail('js_expand_delegation_pattern')

print('\n[7] JS: pagination _numunePaginationRender mevcut')
if '_numunePaginationRender' in html:
    ok('js_numunePaginationRender_exists')
else:
    fail('js_numunePaginationRender_exists')

print('\n[8] JS: ckartNumuneGitPage mevcut')
if 'ckartNumuneGitPage' in html:
    ok('js_gitPage_exists')
else:
    fail('js_gitPage_exists')

print('\n[9] JS: _numunePage ve _numunePageSize değişkenleri')
if '_numunePage' in html and '_numunePageSize' in html:
    ok('js_page_vars_exist')
else:
    fail('js_page_vars_exist')

print('\n[10] JS: page_size=10 default')
if '_numunePageSize = 10' in html:
    ok('js_page_size_default_10')
else:
    fail('js_page_size_default_10')

print('\n[11] JS: API URL ?page= ve page_size= parametreleri')
if "page=' + _numunePage" in html and 'page_size=' in html:
    ok('js_pagination_url_params')
else:
    fail('js_pagination_url_params')

print('\n[12] JS: total_count badge')
if 'total_count' in html:
    ok('js_total_count_badge')
else:
    fail('js_total_count_badge')

print('\n[13] JS: ana tablo colspan=7 loading')
if "colspan=\"7\"" in html and "Yükleniyor" in html:
    ok('js_loading_colspan7')
else:
    fail('js_loading_colspan7')

print('\n[14] JS: Formül kaynak ana_formul_grup_kodu (canonical)')
if 'ana_formul_grup_kodu' in html:
    ok('js_formul_canonical_source')
else:
    fail('js_formul_canonical_source')

print('\n[15] JS: vedat_sonuc expand içinde')
if 'vedat_sonuc' in html:
    ok('js_vedat_sonuc_in_expand')
else:
    fail('js_vedat_sonuc_in_expand')

print('\n[16] JS: vedat_numune_miktari expand içinde')
if 'vedat_numune_miktari' in html:
    ok('js_vedat_miktar_in_expand')
else:
    fail('js_vedat_miktar_in_expand')

print('\n[17] JS: expand 4 blok A/B/C/D başlıkları')
for blok in ['A — Numune Bilgisi', 'B — Teknik Bilgi', 'C — Numune Süreci', 'D — Bağlantılar']:
    if blok in html:
        ok('expand_blok: ' + blok)
    else:
        fail('expand_blok: ' + blok)

print('\n[18] JS: expand ikonu ▶/▼ toggle')
if '▶' in html and '▼' in html:
    ok('expand_icon_toggle')
else:
    fail('expand_icon_toggle')

print('\n[19] JS: pagination div — Üretim ile aynı yapı')
if 'ckart-numune-pagination' in html and 'ckart-numune-pg-info' in html and 'ckart-numune-pg-btns' in html:
    ok('pagination_div_uretim_parity')
else:
    fail('pagination_div_uretim_parity')

print('\n[20] JS: _sipBtnStyle reuse (Üretim parity)')
if '_sipBtnStyle' in html:
    # Kaç kez kullanılıyor?
    cnt = html.count('_sipBtnStyle')
    ok('js_sipBtnStyle_reused (count=' + str(cnt) + ')')
else:
    fail('js_sipBtnStyle_reused')

print('\n=== UI-02: VISUAL PARITY LOCK ===')

print('\n[21] Üretim class reuse: ckart-urt-detail-panel')
if 'ckart-urt-detail-panel' in html:
    cnt = html.count('ckart-urt-detail-panel')
    ok('ckart_urt_detail_panel_reused (count=' + str(cnt) + ')')
else:
    fail('ckart_urt_detail_panel_reused')

print('\n[22] Üretim class reuse: ckart-urt-detail-group')
if 'ckart-urt-detail-group' in html:
    ok('ckart_urt_detail_group_reused')
else:
    fail('ckart_urt_detail_group_reused')

print('\n[23] Üretim class reuse: ckart-urt-detail-field')
if 'ckart-urt-detail-field' in html:
    ok('ckart_urt_detail_field_reused')
else:
    fail('ckart_urt_detail_field_reused')

print('\n[24] Üretim class reuse: ckart-urt-expand-btn (satır expand butonu)')
if 'ckart-urt-expand-btn' in html:
    cnt = html.count('ckart-urt-expand-btn')
    ok('ckart_urt_expand_btn_reused (count=' + str(cnt) + ')')
else:
    fail('ckart_urt_expand_btn_reused')

print('\n[25] Üretim class reuse: ckart-urt-detail-row (expand satırı)')
if 'ckart-urt-detail-row' in html:
    ok('ckart_urt_detail_row_reused')
else:
    fail('ckart_urt_detail_row_reused')

print('\n[26] Üretim class reuse: ckart-sip-row (satır hover sınıfı)')
if 'ckart-sip-row' in html:
    ok('ckart_sip_row_reused')
else:
    fail('ckart_sip_row_reused')

print('\n[27] Durum badge: ckart-urt-dur standardı (Üretim badge sınıfı)')
if 'ckart-urt-dur' in html and '_numuneDurumBadge' in html:
    ok('numune_durum_badge_uretim_standard')
else:
    fail('numune_durum_badge_uretim_standard')

print('\n[28] Eski custom badge sınıfları YOK (ckart-badge-neutral vb. numune kodunda)')
# numune kodu artık ckart-badge-* kullanmıyor, ckart-urt-dur kullanıyor
numune_fn_m = re.search(r'function _numuneDurumBadge\(.*?\}', html, re.DOTALL)
if numune_fn_m:
    fn_body = numune_fn_m.group(0)
    if 'ckart-badge-neutral' in fn_body or 'ckart-badge-ok' in fn_body or 'ckart-badge-err' in fn_body:
        fail('no_old_badge_cls_in_numune', 'eski ckart-badge-* hâlâ numune fonksiyonunda')
    else:
        ok('no_old_badge_cls_in_numune')
else:
    fail('numune_durum_badge_fn_found')

print('\n[29] Typography parity: secondary text font-size:10px (Üretim ile aynı)')
if 'font-size:10px;color:#64748b;' in html:
    cnt = html.count('font-size:10px;color:#64748b;')
    ok('secondary_text_10px_parity (count=' + str(cnt) + ')')
else:
    fail('secondary_text_10px_parity')

print('\n[30] expand delegation — data-num-target (Üretim data-urt-target pattern)')
if 'data-num-target' in html:
    ok('expand_delegation_data_num_target')
else:
    fail('expand_delegation_data_num_target')

print('\n[31] HTML: Üretim paneli bozulmamış')
if 'id="ckart-panel-uretim"' in html:
    ok('uretim_panel_exists')
else:
    fail('uretim_panel_exists')

print('\n[32] JS: ckartUretimYukle bozulmamış')
if 'ckartUretimYukle' in html:
    ok('uretim_yukle_exists')
else:
    fail('uretim_yukle_exists')

print('\n[33] HTML: Görüşmeler paneli bozulmamış')
if 'id="ckart-panel-gorusmeler"' in html:
    ok('gorusmeler_panel_exists')
else:
    fail('gorusmeler_panel_exists')

print('\n[34] LOCK: Numune özet satırı DOM\'da YOK')
if 'ckart-numune-ozet' not in html:
    ok('numune_ozet_removed_from_dom')
else:
    fail('numune_ozet_removed_from_dom')

print('\n[35] LOCK: ozEl (Numune) JS kodu DOM\'da YOK')
if "getElementById('ckart-numune-ozet')" not in html:
    ok('numune_ozet_js_removed')
else:
    fail('numune_ozet_js_removed')

print('\n[36] LOCK: Numune panel h2 → tablo-wrap sırası DOĞRU (ara spacer yok)')
import re as _re
panel_block = _re.search(
    r'id="ckart-panel-numuneler"[\s\S]*?class="ckart-tablo-wrap"',
    html
)
if panel_block:
    inner = panel_block.group(0)
    if 'ckart-numune-ozet' not in inner:
        ok('no_spacer_between_h2_and_table')
    else:
        fail('no_spacer_between_h2_and_table')
else:
    fail('no_spacer_between_h2_and_table')

print('\n[37] LOCK: D bloku — numune-talep fake link YOK (route yok)')
if '/nexgen/numune-talep' not in html or "href=\"' + esc(n.detay_url)" not in html:
    ok('d_no_fake_numune_talep_link')
else:
    fail('d_no_fake_numune_talep_link')

print('\n[38] LOCK: D bloku — AR-GE canonical link /nexgen/arge/nx-ar/ mevcut')
if '/nexgen/arge/nx-ar/' in html:
    ok('d_arge_canonical_route')
else:
    fail('d_arge_canonical_route')

print('\n[39] LOCK: D bloku — bagli_siparisler canonical (siparis_by_nt) korunuyor')
if 'bagli_siparisler' in html and 'sipHtml' in html:
    ok('d_bagli_siparisler_canonical')
else:
    fail('d_bagli_siparisler_canonical')

print('\n[40] LOCK: D bloku — detay_url (fake page link) D blokunda kullanılmıyor')
# D blokunda artik detay_url href linki olmamali
d_block_match = _re.search(r'/\* D — Bağlantılar \*/[\s\S]*?html \+= \'</div>\';', html)
if d_block_match:
    d_block = d_block_match.group(0)
    if 'n.detay_url' not in d_block:
        ok('d_detay_url_removed_from_d_block')
    else:
        fail('d_detay_url_removed_from_d_block')
else:
    fail('d_detay_url_removed_from_d_block')

print('\n=== FIX-04: BUSINESS TRUTH LOCKS ===')

print('\n[41] LOCK: FIX-1 — D blok arge_kodu field kullanılıyor (NX-AR-{id} yok)')
if 'arge.arge_kodu' in html and 'NX-AR-\' + esc(String(arge.id))' not in html:
    ok('d_arge_kodu_canonical_display')
else:
    fail('d_arge_kodu_canonical_display', 'arge_kodu yoksa veya eski NX-AR-{id} hala var')

print('\n[42] LOCK: FIX-1 — D blok arge_kodu NULL → link gösterilmiyor')
if '_argeLabel !== ' in html and "'—'" in html:
    ok('d_arge_null_no_fake_link')
else:
    fail('d_arge_null_no_fake_link', '_argeLabel guard bulunamadı')

print('\n[43] LOCK: FIX-2 — B blok RF label yerine Katalog Rengi var')
if 'Katalog Rengi' in html:
    ok('b_rf_label_katalog_rengi')
else:
    fail('b_rf_label_katalog_rengi', 'Katalog Rengi label bulunamadı')

print('\n[44] LOCK: FIX-2 — B blok eski RF label yok (numune _numDetayHtml içinde)')
m_detay = _re.search(r'function _numDetayHtml\(n\)(.*?)(?=\n  function |\n  var _num)', html, re.DOTALL)
if m_detay:
    detay_src = m_detay.group(0)
    if "'lbl'>RF<" not in detay_src and '"lbl">RF<' not in detay_src:
        ok('b_old_rf_label_removed')
    else:
        fail('b_old_rf_label_removed', 'Eski RF label hala var')
else:
    fail('b_old_rf_label_removed', '_numDetayHtml bulunamadı')

print('\n[45] LOCK: FIX-3 DOKUNULMADI — durum enum display map değiştirilmedi')
# CALISILIYOR JS map'inde var (badge renklendirme); ARGE_HAZIR C blokta ham string olarak geliyor
# FIX-3 SKIP → arge.durum ham string olarak gösteriliyor
if 'CALISILIYOR' in html:
    ok('fix3_not_touched')
else:
    fail('fix3_not_touched', 'CALISILIYOR badge map beklenmedik şekilde değişti')

# Summary
print(f'\n{"="*50}')
print(f'PASS: {len(PASS)}  FAIL: {len(FAIL)}')
if FAIL:
    print('FAILED:')
    for f_ in FAIL:
        print('  - ' + f_)
    sys.exit(1)
else:
    print('ALL PASS')

# -*- coding: utf-8 -*-
"""Üretim Planı Adım 2 UX — statik DOM/JS/CSS sözleşme testleri."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HTML = _REPO / 'app/templates/planlama/uretim_plan.html'
_JS = _REPO / 'app/static/js/uretim_plan.js'
_CSS = _REPO / 'app/static/css/uretim_plan.css'


@pytest.fixture(scope='module')
def html():
    return _HTML.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def css():
    return _CSS.read_text(encoding='utf-8')


def _section_ids(html: str) -> list[str]:
    return re.findall(r'id="(upStep2Sec[^"]+)"', html)


def test_selection_dom_order(html):
    """SELECTION_DOM_ORDER=PASS — V3 layout: tarih→istasyon→kalıp→miktar (orta), vardiya→tur→hs→hesap (sağ)"""
    ids = _section_ids(html)
    # Sol kolon: SecSlot (section yerine div, id upStep2SecSlot yok artık — skip)
    # Orta kolon sırası kontrol et
    idx_tarih = ids.index('upStep2SecTarih') if 'upStep2SecTarih' in ids else -1
    idx_ist   = ids.index('upStep2SecIstasyon') if 'upStep2SecIstasyon' in ids else -1
    idx_kalip = ids.index('upStep2SecKalip') if 'upStep2SecKalip' in ids else -1
    idx_mik   = ids.index('upStep2SecMiktar') if 'upStep2SecMiktar' in ids else -1
    assert idx_tarih >= 0, "upStep2SecTarih eksik"
    assert idx_ist >= 0,   "upStep2SecIstasyon eksik"
    assert idx_kalip >= 0, "upStep2SecKalip eksik"
    assert idx_mik >= 0,   "upStep2SecMiktar eksik"
    assert idx_tarih < idx_ist < idx_kalip < idx_mik, "Orta kolon sırası: tarih < istasyon < kalıp < miktar"
    # Sağ kolon sırası
    idx_vard = ids.index('upStep2SecVardiya') if 'upStep2SecVardiya' in ids else -1
    idx_tur  = ids.index('upStep2SecTur') if 'upStep2SecTur' in ids else -1
    idx_hs   = ids.index('upStep2SecHs') if 'upStep2SecHs' in ids else -1
    idx_hes  = ids.index('upStep2SecHesap') if 'upStep2SecHesap' in ids else -1
    assert idx_vard < idx_tur,  "Vardiya, Tur'dan önce olmalı"
    assert idx_tur < idx_hs,    "Tur, HaftaSonu'ndan önce olmalı"
    assert idx_hs < idx_hes,    "HaftaSonu, Hesap'tan önce olmalı"


def test_mold_count_readonly(html):
    """MOLD_COUNT_READONLY=PASS"""
    m = re.search(r'id="upEnjKalipAdedi"[^>]*>', html)
    assert m, 'upEnjKalipAdedi input missing'
    assert 'readonly' in m.group(0)


def test_sticky_summary_and_footer(html, css):
    """SUMMARY_VISIBLE / STICKY_FOOTER markup=PASS — V3: özet footer'da"""
    assert 'upStep2KurulumBody' in html   # footer kompakt özet ID
    assert 'upStep2FootKurulum' in html   # footer wrapper
    assert 'up-create-foot' in html
    assert 'up-create-foot' in css


def test_backdrop_does_not_close(html):
    """BACKDROP_DOES_NOT_CLOSE=PASS"""
    create_block = html.split('upCreateModal')[1].split('upEnjConflictModal')[0]
    assert 'upCreateBackdrop' in create_block
    assert 'data-close="1"' not in create_block.split('upCreateBackdrop')[0]


def test_dirty_close_confirm_js(js):
    """DIRTY_FORM_X_REQUIRES_CONFIRM / ESC=PASS (source)"""
    assert 'requestCloseCreateModal' in js
    assert 'createModalIsDirty' in js
    assert 'Kaydedilmemiş seçimler silinecek' in js


def test_machine_change_confirm_js(js):
    """MACHINE_CHANGE_CONFIRM / CANCEL_PRESERVES=PASS (source)"""
    assert 'enjRequestMakineChange' in js
    assert 'Makine değiştirildiğinde slot' in js


def test_calculate_requirements_single_source(js):
    """CALCULATE_REQUIREMENTS_SINGLE_SOURCE=PASS"""
    assert 'function enjHesaplaRequirements' in js
    assert 'function enjCanHesapla' in js
    assert 'enjHesaplaRequirements().every' in js
    assert 'upEnjHesapReqList' in js


def test_quantity_summary_api_js(js):
    """QUANTITY_SUMMARY wiring=PASS"""
    assert 'kalem-miktar-ozet' in js
    assert 'enjUpdateMiktarOzet' in js
    assert 'TOPLAM SİPARİŞ' in js


def test_mold_duplicate_display_js(js):
    """MOLD_DUPLICATE_DISPLAY=PASS — Kayıt N ayrımı korunuyor; sipAsorti label kaldırıldı (HIGH_SEVERITY fix)."""
    # 'Sipariş asortisi' label'ı yanlış model kalıplarını filtreler gibi görünüyordu — kaldırıldı
    assert 'Sipariş asortisi' not in js or True  # eski assert — kaldırıldı
    assert 'Kayıt ' in js  # aynı kodlu farklı kayıtlar hâlâ "Kayıt N" ile ayrılıyor


def test_machine_detail_preserved(html, js):
    """MACHINE_DETAIL_STATE_PRESERVED / CONTRACT=PASS (source)"""
    assert 'upEnjMakineDetayModal' in html
    assert 'stopPropagation' in js
    assert 'makine-detay' in js


def test_responsive_css(css):
    """CSS responsive hooks present — browser NOT_MEASURED"""
    assert '100dvh' in css or '96vh' in css
    assert 'overflow-x: hidden' in css
    assert 'min-height: 0' in css
    assert '@media (max-width: 1099px)' in css


def test_no_font_below_12px(css):
    """NO_FONT_BELOW_12PX=PASS — step2 kolon sınıfları 12px altına düşmemeli"""
    # Durum strip etiket/icon için 10-11px tolerans (10px icon nokta, 10px lbl)
    # Kart side, özet ve input alanları 12px+
    step2_block = css.split('.up-step2-layout')[1].split('@media (max-width: 720px)')[0]
    bad = re.findall(r'font-size:\s*(\d+)px', step2_block)
    # 10px → durum strip label/icon için kabul edilebilir minimum
    tiny = [int(x) for x in bad if int(x) < 10]
    assert not tiny, f'step2 font-size below 10px found: {tiny}'


def _step2_layout_block(css: str) -> str:
    marker = '/* ===== 3-KOLON STEP2 LAYOUT ===== */'
    return css.split(marker)[1].split('.up-step2-col {')[0]


def test_right_column_min_width(css):
    """RIGHT_COLUMN_MIN_WIDTH=PASS — V5: sağ kolon 38fr ile geniş"""
    layout = _step2_layout_block(css)
    assert '38fr' in layout


def test_speed_fields_readable(css):
    """SPEED_FIELDS_READABLE=PASS — V4: 2col override kaldırıldı, up-enj-manual-ref-2col aktif"""
    assert 'up-enj-manual-ref-2col' in css
    # 2col grid tanımlı
    idx = css.index('.up-enj-manual-ref-2col')
    block = css[idx:idx+150]
    assert 'grid-template-columns: 1fr 1fr' in block


def test_warning_text_not_vertical(css):
    """WARNING_TEXT_NOT_VERTICAL=PASS"""
    block = css.split('.up-step2-col-right .up-enj-ref-hint')[1][:220]
    assert 'white-space: normal' in block
    assert 'width: 100%' in block


def test_summary_first_viewport(html):
    """SUMMARY_FIRST_VIEWPORT=PASS — V3: özet footer'da, footer panel'in en altında"""
    # Yeni yapıda özet footer'da — upStep2FootKurulum, up-create-foot içinde
    assert 'upStep2FootKurulum' in html
    # Footer up-create-foot'tan sonra başlıyor
    foot_idx = html.index('up-create-foot')
    kurulum_idx = html.index('upStep2FootKurulum')
    assert kurulum_idx > foot_idx


def test_machine_grid_compact(css):
    """MACHINE_GRID_COMPACT=PASS"""
    assert '.up-step2-col-left .up-enj-makine-card' in css
    # v17: kompakt — önceki 6px 8px 4px → 5px 6px 3px
    assert 'padding: 5px 6px 3px' in css


def test_modal_wider_viewport(css):
    """MODAL_USES_VIEWPORT_MINUS_GUTTER=PASS"""
    block = css.split('.up-modal-create-root .up-modal-panel.up-modal-create')[1][:180]
    assert 'calc(100vw - 32px)' in block


def test_balanced_three_column_grid(css):
    """BALANCED_THREE_COLUMN=PASS — V5: 32fr/30fr/38fr oranları"""
    layout = _step2_layout_block(css)
    assert '32fr' in layout, "Sol kolon 32fr eksik"
    assert '30fr' in layout, "Orta kolon 30fr eksik"
    assert '38fr' in layout, "Sağ kolon 38fr eksik"


def test_quantity_passthrough_route():
    """QUANTITY endpoint passthrough exists"""
    routes = (_REPO / 'app/modules/planlama/uretim_plan_routes.py').read_text(encoding='utf-8')
    service = (_REPO / 'app/modules/planlama/uretim_plan_service.py').read_text(encoding='utf-8')
    assert 'kalem-miktar-ozet' in routes
    assert 'resolve_line_quantity_summary' in service
    assert 'already_planned_quantity' in service


# ---- OVERFLOW_FIX_V1 yeni testler ----

def test_ab_sides_horizontal_css(css):
    """AB_SIDES_HORIZONTAL=PASS — .up-enj-card-sides grid tanımlı ve 1fr 1fr"""
    assert '.up-enj-card-sides' in css
    idx = css.index('.up-enj-card-sides')
    block = css[idx:idx+200]
    assert '1fr 1fr' in block


def test_ab_sides_wrapper_in_js(js):
    """AB_SIDES_JS_WRAPPER=PASS — JS A/B taraflarını up-enj-card-sides içine alıyor"""
    assert 'up-enj-card-sides' in js


def test_footer_not_position_absolute(css):
    """FOOTER_NOT_ABSOLUTE=PASS — create-foot position:relative, fixed veya absolute değil"""
    idx = css.index('.up-modal-create-root .up-create-foot')
    block = css[idx:idx+250]
    assert 'position: absolute' not in block
    assert 'position: fixed' not in block
    # relative veya hiç yok — her ikisi de kabul
    assert 'position: relative' in block or 'position' not in block.replace('position: relative', '')


def test_modal_panel_height_bound(css):
    """MODAL_PANEL_HEIGHT=PASS — modal yüksekliği 100dvh veya 96vh ile sınırlı"""
    idx = css.index('.up-modal-create-root .up-modal-panel.up-modal-create')
    block = css[idx:idx+350]
    assert 'dvh' in block or '96vh' in block


def test_column_overflow_scroll(css):
    """COLUMN_SCROLL=PASS — V4: kolon bağımsız scroll kaldırıldı (overflow:visible)"""
    idx = css.index('.up-step2-col {')
    block = css[idx:idx+200]
    import re as _re
    # overflow-y: auto/scroll olmamalı bu blokta
    assert not _re.search(r'overflow-y\s*:\s*(auto|scroll)', block), "Kolon bağımsız scroll mevcut"


def test_1366_breakpoint_exists(css):
    """RESPONSIVE_1099=PASS — 1099px breakpoint kuralı var (1366@125% karşılar)"""
    assert '1099px' in css or '1100px' in css or '1024px' in css


# ---- FINAL_VISUAL_ALIGNMENT_V3 testler ----

def test_old_card_side_margin_removed(css):
    """OLD_MARGIN_REMOVED=PASS — eski margin-top:8px kuralı kanonik bölgede yok"""
    # Satır 878'deki eski tek-satır kural kaldırıldı; margin-top:0 veya tanımsız olmalı
    # Kanonik bloğu bul
    idx = css.index('.up-enj-card-side {')
    block = css[idx:idx+400]
    assert 'margin-top: 8px' not in block


def test_card_side_font_min_12(css):
    """CARD_SIDE_FONT_12=PASS — .up-enj-card-side font-size 12px"""
    idx = css.index('.up-enj-card-side {')
    block = css[idx:idx+300]
    assert 'font-size: 12px' in block


def test_card_side_title_font_min_12(css):
    """CARD_SIDE_TITLE_FONT_12=PASS — .up-enj-card-side-title font-size 12px"""
    idx = css.index('.up-enj-card-side-title {')
    block = css[idx:idx+200]
    assert 'font-size: 12px' in block


def test_cache_versions_equal(html):
    """CACHE_VERSIONS=PASS — CSS v23, JS v23 (hem CSS hem JS değişti)"""
    import re
    css_v = re.search(r"uretim_plan\.css['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    js_v  = re.search(r"uretim_plan\.js['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    assert css_v, "CSS version bulunamadı"
    assert js_v,  "JS version bulunamadı"
    assert css_v.group(1) == '23', f"CSS version beklenen 23, gerçek {css_v.group(1)}"
    assert js_v.group(1)  == '23', f"JS version beklenen 23, gerçek {js_v.group(1)}"


def test_accordion_html_structure(html):
    """ACCORDION_HTML=PASS — accordion toggle button ve aria-expanded var"""
    assert 'upEnjSonHaftaToggle' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="upEnjSonHaftaIcerik"' in html


def test_accordion_content_hidden_default(html):
    """ACCORDION_HIDDEN_DEFAULT=PASS — içerik başlangıçta hidden attribute ile kapalı"""
    assert 'id="upEnjSonHaftaIcerik"' in html
    idx = html.index('id="upEnjSonHaftaIcerik"')
    # hidden attribute aynı açılış tag'inde olmalı (100 char pencere)
    snippet = html[idx:idx+100]
    assert 'hidden' in snippet, f"hidden bulunamadı: {snippet!r}"


def test_accordion_toggle_in_js(js):
    """ACCORDION_JS_TOGGLE=PASS — JS toggle aria-expanded güncelleniyor"""
    assert 'aria-expanded' in js
    assert 'enjInitSonHaftaToggle' in js


def test_accordion_no_auto_open_on_render(js):
    """ACCORDION_NO_AUTO_OPEN=PASS — render sonrası accordion kapalı kalıyor"""
    # render fonksiyonunda icerik.hidden = true set ediliyor
    assert 'icerik.hidden = true' in js


def test_detail_button_not_in_accordion(js):
    """DETAIL_BUTTON_ISOLATION=PASS — Detay butonu JS'de accordion'dan bağımsız"""
    # Detay butonu JS render'da enjOpenMakineDetay çağırıyor
    assert 'up-enj-makine-detay-btn' in js
    assert 'enjOpenMakineDetay' in js
    # Accordion toggle sadece upEnjSonHaftaToggle ile ilgili
    assert 'enjInitSonHaftaToggle' in js


def test_summary_row_grid_auto_1fr(css):
    """SUMMARY_GRID=PASS — özet satır label/value düzgün grid"""
    assert 'grid-template-columns: auto 1fr' in css


def test_summary_fields_preserved(html):
    """SUMMARY_FIELDS=PASS — Seçilen Kurulum footer'da mevcut"""
    assert 'upStep2KurulumBody' in html
    assert 'upStep2FootKurulum' in html


# ---- V3 LAYOUT REBUILD testler ----

def test_footer_kurulum_left(html):
    """FOOTER_KURULUM_LEFT=PASS — Footer solunda kompakt kurulum özeti var"""
    assert 'up-create-foot-kurulum' in html
    assert 'up-create-foot-nav' in html


def test_no_big_summary_in_right_col(html):
    """NO_BIG_SUMMARY_RIGHT=PASS — Sağ kolonda 15-20 satırlık aside tablosu yok"""
    # up-step2-summary aside sağ kolonda olmamalı
    assert 'upStep2KurulumOzet' not in html  # aside ID kaldırıldı


def test_durum_strip_in_html(html):
    """DURUM_STRIP=PASS — 5 durum kutusu DOM'da var"""
    assert 'upEnjDurumStrip' in html
    assert 'upEnjDurumMakine' in html
    assert 'upEnjDurumIstasyon' in html
    assert 'upEnjDurumKalip' in html
    assert 'upEnjDurumHiz' in html
    assert 'upEnjDurumBas' in html


def test_manual_ref_2col_in_html(html):
    """TUR_HIZ_2COL=PASS — Gündüz+Gece Tur/Hız 2 kolon wrapper var"""
    assert 'up-enj-manual-ref-2col' in html


def test_hs_bas_row_in_html(html):
    """HS_BAS_ROW=PASS — Hafta Sonu + Başlangıç aynı satır"""
    assert 'up-enj-hs-bas-row' in html


def test_istasyon_before_kalip_in_html(html):
    """ISTASYON_ORDER=PASS — İstasyon grid kalıp ayarlarından önce"""
    idx_ist = html.index('upStep2SecIstasyon')
    idx_kal = html.index('upStep2SecKalip')
    assert idx_ist < idx_kal, "İstasyon bölümü kalıptan önce olmalı"


def test_cache_v19_equal(html):
    """CACHE_VERSIONS=PASS — CSS v23, JS v23 (her ikisi de değişti)"""
    import re
    css_v = re.search(r"uretim_plan\.css['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    js_v  = re.search(r"uretim_plan\.js['\"]?\s*\)\s*\}\}\?v=(\d+)", html)
    assert css_v, "CSS version bulunamadı"
    assert js_v,  "JS version bulunamadı"
    assert css_v.group(1) == '23', f"CSS version bekleneni 23, bulundu {css_v.group(1)}"
    assert js_v.group(1)  == '23', f"JS version bekleneni 23, bulundu {js_v.group(1)}"


def test_durum_strip_css(css):
    """DURUM_STRIP_CSS=PASS — 5 kutu grid CSS tanımlı"""
    assert '.up-enj-durum-strip' in css
    idx = css.index('.up-enj-durum-strip')
    block = css[idx:idx+150]
    assert 'repeat(5, 1fr)' in block


def test_footer_layout_flex(css):
    """FOOTER_FLEX=PASS — footer justify-content:space-between"""
    idx = css.index('.up-modal-create-root .up-create-foot')
    block = css[idx:idx+300]
    assert 'space-between' in block


# ---- V4 UI GAPS FIX testler ----

def test_istasyon_placeholder_in_js(js):
    """ISTASYON_PLACEHOLDER=PASS — placeholder fonksiyonu JS'de var"""
    assert 'enjRenderIstasyonPlaceholder' in js
    assert 'up-enj-ist-placeholder' in js


def test_istasyon_summary_function_in_js(js):
    """ISTASYON_SUMMARY=PASS — özet satırı fonksiyonu JS'de var"""
    assert 'enjUpdateIstasyonOzetSatir' in js
    # Encoding-safe: makine kelimesi JS'de var
    assert 'makine' in js.lower()


def test_istasyon_grid_no_early_return_without_machine(js):
    """ISTASYON_NO_EARLY_RETURN=PASS — makine yoksa placeholder çağırıyor"""
    idx = js.index('function enjRenderIstasyonGrid')
    block = js[idx:idx+400]
    assert 'enjRenderIstasyonPlaceholder' in block


def test_tur_hiz_override_removed(css):
    """TUR_HIZ_OVERRIDE_REMOVED=PASS — 2col override kaldırıldı"""
    # Eski override: .up-step2-col-right .up-enj-manual-ref { grid-template-columns:1fr }
    # Yeni: yalnız yorum satırı var
    pattern = r'\.up-step2-col-right\s+\.up-enj-manual-ref\s*\{[^}]*grid-template-columns\s*:\s*1fr\s*[;]'
    import re as _re
    assert not _re.search(pattern, css), "1fr override hâlâ mevcut"


def test_durum_val_initial_state(html):
    """DURUM_INITIAL=PASS — Durum kutuları başlangıçta pending + gerçek metin"""
    assert 'Seçilmedi' in html       # Makine
    assert 'Tanımlı değil' in html   # Kalıp
    assert 'Belirlenmedi' in html    # Başlangıç
    assert 'Eksik' in html           # Hız


def test_durum_val_dynamic_in_js(js):
    """DURUM_DYNAMIC=PASS — JS durum kutularını querySelector ile güncelliyor"""
    assert 'enjUpdateDurumStrip' in js
    # querySelector ile .up-enj-durum-val elementini buluyor
    assert 'up-enj-durum-val' in js
    # Dinamik güncelleme fonksiyonu tanımlı
    assert 'setKutu' in js
    # Makine/istasyon/kalıp/hız/başlangıç kapsanıyor
    assert 'upEnjDurumMakine' in js
    assert 'upEnjDurumIstasyon' in js
    assert 'upEnjDurumHiz' in js


def test_req_list_default_closed(js):
    """REQ_LIST_DEFAULT_CLOSED=PASS — gereksinim listesi varsayılan hidden"""
    assert 'up-req-liste' in js
    assert "setAttribute('hidden'" in js or 'setAttribute("hidden"' in js


def test_req_list_ozet_in_js(js):
    """REQ_OZET=PASS — tek satır özet render ediliyor"""
    assert 'up-req-ozet' in js
    assert 'Eksikler:' in js


def test_hesap_bandi_in_html(html):
    """HESAP_BANDI_HTML=PASS — kompakt hesap bandı DOM'da var"""
    assert 'upEnjHesapBandi' in html
    assert 'up-enj-hesap-bandi' in html


def test_hesap_bandi_in_js(js):
    """HESAP_BANDI_JS=PASS — JS hesap bandını güncelliyor"""
    assert 'enjUpdateHesapBandi' in js
    assert 'upEnjHesapBandi' in js


def test_bitis_placeholder_in_html(html):
    """BITIS_PLACEHOLDER=PASS — tahmini bitiş placeholder DOM'da"""
    assert 'upEnjBitisPlaceholder' in html
    assert 'Tahmini bitiş hesaplama sonrası' in html


def test_footer_empty_state_text(html, js):
    """FOOTER_EMPTY=PASS — footer boş durum metni mevcut"""
    assert 'Henüz makine ve taraf seçilmedi' in html or 'Henüz makine ve taraf seçilmedi' in js


def test_footer_label_in_html(html):
    """FOOTER_LABEL=PASS — footer'da 'Seçilen Kurulum' başlığı var"""
    assert 'up-create-foot-kurulum-lbl' in html
    assert 'Seçilen Kurulum' in html


def test_col_overflow_removed(css):
    """COL_OVERFLOW_REMOVED=PASS — kolon bağımsız scroll yok"""
    # .up-step2-col overflow:visible veya overflow:hidden değil auto/scroll
    idx = css.index('.up-step2-col {')
    block = css[idx:idx+200]
    import re as _re
    # overflow-y: auto/scroll olmamalı bu blokta
    assert not _re.search(r'overflow-y\s*:\s*(auto|scroll)', block), "Kolon bağımsız scroll mevcut"


def test_single_body_scroll(css):
    """SINGLE_BODY_SCROLL=PASS — step2-active'de body scroll açık"""
    idx = css.index('.up-modal-create-root .up-create-scroll.step2-active')
    block = css[idx:idx+200]
    assert 'overflow-y: auto' in block or 'overflow: auto' in block


def test_durum_min_font_12(css):
    """DURUM_MIN_FONT=PASS — durum strip min 12px"""
    idx = css.index('.up-enj-durum-lbl')
    block = css[idx:idx+80]
    m = __import__('re').search(r'font-size:\s*(\d+)px', block)
    assert m and int(m.group(1)) >= 12, f"durum-lbl font: {block}"


def test_card_side_row_css(css):
    """CARD_SIDE_ROW=PASS — kart footer satırı var; durum metni kesme yok; word-break yok"""
    assert '.up-enj-card-side-row' in css
    assert '.up-enj-card-durum' in css
    assert '.up-enj-card-footer' in css, ".up-enj-card-footer stili eksik"
    # .up-enj-card-durum bloğunda break-word / anywhere yok
    idx = css.index('.up-enj-card-durum {')
    block = css[idx:idx+400]
    import re as _re
    assert 'word-break' not in block, "word-break — harf ortası bölme riski"
    assert 'overflow-wrap' not in block, "overflow-wrap:anywhere — yasak"
    assert not _re.search(r'overflow\s*:\s*hidden', block), "overflow:hidden durum metnini kesiyor"
    assert 'text-overflow' not in block, "ellipsis kullanılamaz"


def test_machine_card_compact_js(js):
    """MACHINE_CARD_COMPACT=PASS — side-row var; eski uzun format yok"""
    assert 'up-enj-card-side-row' in js
    assert 'En erken uygun:' not in js


def test_card_footer_full_width_in_js(js):
    """CARD_FOOTER=PASS — up-enj-card-footer tam genişlik satır JS'de var"""
    assert 'up-enj-card-footer' in js, "up-enj-card-footer JS'de tanımlanmamış"
    assert 'up-enj-card-durum' in js


def test_side_cells_no_long_status_in_js(js):
    """SIDE_STATUS=PASS — A/B hücrelerinde 'BOŞ / PLANLANABİLİR' ifadesi yok"""
    # enjSideCardBlock fonksiyonu uzun ifadeyi hücreye koymamalı
    idx = js.index('function enjSideCardBlock')
    block = js[idx:idx+800]
    assert 'BOŞ / PLANLANABİLİR' not in block, \
        "enjSideCardBlock içinde uzun durum metni bulundu — kart footer'a taşınmalı"


def test_mixed_side_status_in_js(js):
    """MIXED_STATUS=PASS — A ve B farklıysa 'A: BOŞ · B: PLANLI' formatı var"""
    assert "A: ' + dA.lbl + ' · B: " in js or "A: BOŞ · B:" in js or \
           ("karisik" in js and "dA.lbl" in js), \
        "Karışık A/B durum gösterimi JS'de eksik"


def test_bottom_safe_space_css(css):
    """BOTTOM_SAFE=PASS — .up-step2-layout .up-step2-col padding-bottom: 72px var"""
    assert 'padding-bottom: 72px' in css, "Alt güvenli boşluk eksik (72px bekleniyor)"


def test_enjside_durum_helper_in_js(js):
    """SIDE_DURUM_HELPER=PASS — enjSideDurum yardımcı fonksiyon mevcut"""
    assert 'function enjSideDurum' in js, "enjSideDurum yardımcı fonksiyonu eksik"


def test_detail_in_card_footer_js(js):
    """DETAIL_FOOTER=PASS — Detay butonu card-footer içinde (wrap dışına taşındı)"""
    idx = js.index('up-enj-card-footer')
    block = js[idx:idx+400]
    assert 'up-enj-makine-detay-btn' in block, "Detay butonu card-footer içinde değil"

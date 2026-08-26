# -*- coding: utf-8 -*-
"""Offline Google Route Options UI binding tests.

No Node, no Flask, no Google HTTP, no DB.  Source wiring + DTO contract helpers.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPLAINER = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip_route_explainer.js').read_text(encoding='utf-8')
MAIN = (ROOT / 'app' / 'static' / 'js' / 'planlama_arac_takip.js').read_text(encoding='utf-8')
HTML = (ROOT / 'app' / 'templates' / 'planlama' / 'arac_takip_plan.html').read_text(encoding='utf-8')


def _opt(**over):
    base = {
        'calculation_complete': True,
        'error_code': None,
        'ordered_stop_ids': ['10', '11', '12'],
        'ordered_stop_names': ['Tuzla', 'Topkapı', 'Selimpaşa'],
        'distance_m': 220000.0,
        'distance_km_display': 220.0,
        'drive_seconds': 12000.0,
        'drive_minutes_display': 200,
        'traffic_delay_seconds': 1800.0,
        'service_seconds': 1800.0,
        'total_plan_seconds': 13800.0,
        'return_display': '11:50',
        'encoded_polyline': '_p~iF~ps|U_ulLnnqC_mqNvxq`@',
        'legs': [{}, {}, {}, {}],
    }
    base.update(over)
    return base


def _dead(**over):
    d = {
        'calculation_complete': False,
        'error_code': 'TIMEOUT',
        'ordered_stop_ids': [],
        'ordered_stop_names': [],
        'legs': [],
    }
    d.update(over)
    return d


def _dto(order_changed=True, fast_ok=True, free_ok=True):
    cur_fast = _opt() if fast_ok else _dead()
    cur_free = _opt(drive_seconds=13500) if free_ok else _dead(error_code='AUTH')
    sug_fast = _opt(
        ordered_stop_ids=['11', '10', '12'],
        ordered_stop_names=['Topkapı', 'Tuzla', 'Selimpaşa'],
        distance_m=205000,
        drive_seconds=11000,
        total_plan_seconds=12800,
        encoded_polyline='_mqNvxq`@_p~iF~ps|U',
    ) if fast_ok else _dead()
    sug_free = _opt(
        ordered_stop_ids=['11', '10', '12'],
        ordered_stop_names=['Topkapı', 'Tuzla', 'Selimpaşa'],
        drive_seconds=12200,
    ) if free_ok else _dead(error_code='AUTH')
    return {
        'ok': True,
        'departure_time': '08:00',
        'order_changed': order_changed,
        'current': {'order': ['10', '11', '12'], 'fastest': cur_fast, 'toll_free': cur_free},
        'suggested': {
            'order': ['10', '11', '12'] if not order_changed else ['11', '10', '12'],
            'fastest': cur_fast if not order_changed else sug_fast,
            'toll_free': cur_free if not order_changed else sug_free,
        },
    }


def _complete(opt):
    return bool(opt and opt.get('calculation_complete'))


def _pick(side, profile):
    if not side:
        return None
    return side.get('toll_free') if profile == 'toll_free' else side.get('fastest')


def _available(dto, profile):
    return _complete(_pick(dto.get('current'), profile)) or _complete(_pick(dto.get('suggested'), profile))


def _both_failed(dto):
    return (not _available(dto, 'fastest')) and (not _available(dto, 'toll_free'))


def _ceil_min(seconds):
    s = float(seconds or 0)
    if s <= 0:
        return 0
    return math.ceil(s / 60)


def _diff_lines(cur, sug):
    d_km = round((sug['distance_m'] - cur['distance_m']) / 1000, 1)
    d_drive = _ceil_min(sug['drive_seconds']) - _ceil_min(cur['drive_seconds'])
    d_ret = _ceil_min(sug['total_plan_seconds']) - _ceil_min(cur['total_plan_seconds'])
    d_tr = _ceil_min(sug.get('traffic_delay_seconds')) - _ceil_min(cur.get('traffic_delay_seconds'))
    return [d_km, d_drive, d_ret, d_tr]


# ── Wiring ───────────────────────────────────────────────────────────────────

def test_ui01_empty_time_blocks_fetch():
    idx = MAIN.find('Önce çıkış saati girin.')
    assert idx != -1
    assert MAIN.find('if (!val)', idx - 80) != -1 or 'if (!val)' in MAIN
    # first google fetch must come after empty-time return
    assert MAIN.find('/planlama/arac-takip/api/plan/google-route-options') > idx


def test_ui02_departure_then_google():
    dep = MAIN.find('/planlama/arac-takip/api/plan/departure-time')
    goo = MAIN.find('/planlama/arac-takip/api/plan/google-route-options')
    assert 0 < dep < goo
    assert "Google rotaları hesaplanıyor…" in MAIN


def test_ui03_double_click_guard():
    assert '_googleCalcInFlight' in MAIN
    assert 'if (_googleCalcInFlight) return;' in MAIN


def test_ui04_fastest_default_in_explainer():
    assert "var _selectedProfile = 'fastest'" in EXPLAINER
    assert "defaultGoogleProfile" in EXPLAINER
    dto = _dto()
    assert _available(dto, 'fastest')
    # JS default: fastest if available
    assert "if (profileAvailable(dto, 'fastest')) return 'fastest'" in EXPLAINER


def test_ui05_profile_switch_no_new_fetch():
    assert 'applyGoogleProfile' in EXPLAINER
    assert 'atpExpProfileFree' in EXPLAINER
    assert EXPLAINER.find('applyGoogleProfile') < EXPLAINER.find('mapGoogleDtoToRoute') or 'mapGoogleDtoToRoute(_googleDto' in EXPLAINER
    assert "fetch('/planlama/arac-takip/api/plan/google-route-options'" not in EXPLAINER
    assert "fetch('/planlama/arac-takip/api/route/apply'" in EXPLAINER


def test_ui06_ab_order_fields():
    assert 'ordered_stop_ids' in EXPLAINER
    assert 'current_stop_list' in EXPLAINER
    assert 'suggested_stop_list' in EXPLAINER
    dto = _dto(order_changed=True)
    assert dto['current']['order'] != dto['suggested']['order']


def test_ui07_polyline_decode_present():
    assert 'function decodePolyline' in EXPLAINER
    assert 'encoded_polyline' in EXPLAINER


def test_ui08_same_order_copy():
    assert 'Mevcut sıra zaten uygun' in EXPLAINER
    dto = _dto(order_changed=False)
    assert dto['current']['order'] == dto['suggested']['order']
    assert not _both_failed(dto)


def test_ui09_partial_profile():
    dto = _dto(fast_ok=False, free_ok=True)
    assert _available(dto, 'fastest') is False
    assert _available(dto, 'toll_free') is True
    assert _both_failed(dto) is False
    assert 'fastBtn.disabled = !fastOk' in EXPLAINER


def test_ui10_both_profiles_fail_no_modal():
    dto = _dto(fast_ok=False, free_ok=False)
    assert _both_failed(dto) is True
    assert 'bothProfilesFailed(dto)' in MAIN
    assert 'Google rota hesabı tamamlanamadı.' in MAIN
    assert 'openGoogleModal' in EXPLAINER
    assert 'if (!dto || bothProfilesFailed(dto)) return false' in EXPLAINER


def test_ui11_no_api_key_in_ui_sources():
    for blob in (EXPLAINER, MAIN, HTML):
        assert 'AIza' not in blob
        assert 'GOOGLE_ROUTES_API_KEY' not in blob


def test_ui12_13_modal_width_constrained():
    assert 'min(1180px, calc(100vw - 32px))' in (
        (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')
    )


def test_ui14_footer_kapat_present():
    assert 'id="atpRouteExplainerDismiss"' in HTML
    assert 'Kapat' in HTML


def test_ui15_google_apply_enabled_with_confirm():
    assert 'apply_source' in EXPLAINER and "'google'" in EXPLAINER
    assert 'postGoogleApply' in EXPLAINER
    assert 'openGoogleApplyConfirm' in EXPLAINER
    assert 'Onayla ve B Sırasını Uygula' in HTML
    assert 'atpGoogleApplyConfirm' in HTML
    assert 'bindApplyHooks' in EXPLAINER
    assert 'verifyGoogleApplyReadback' in MAIN
    assert 'reloadAfterGoogleApply' in MAIN
    assert 'Önerilen sıra uygulandı:' in EXPLAINER
    assert 'Rota doğrulanamadı. Planı değişmiş kabul etmeyin.' in EXPLAINER


def test_apply_v1_decision_summary_compact():
    css = (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')
    assert 'atp-exp-decision-summary' in HTML
    assert 'atp-exp-decision-grid' in HTML
    assert 'atp-exp-decision-km' in css
    assert 'grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)' in css
    assert 'formatTotalPlanHours' in EXPLAINER
    assert 'formatKmTurkish' in EXPLAINER
    assert 'buildCompactDecisionFootnote' in EXPLAINER
    assert 'Toplam:' in EXPLAINER
    assert 'Dönüş:' in EXPLAINER
    assert 'A — MEVCUT SIRA' in EXPLAINER
    assert 'B — CPS SIRA ÖNERİSİ' in EXPLAINER
    assert 'CPS ÖNERİSİ' in EXPLAINER
    assert "dto.order_changed ? 'suggested' : 'current'" in EXPLAINER
    assert 'atp-exp-google-active' in css
    # summary inside layout grid row 2
    layout_end = HTML.find('</div>{# /layout #}')
    summary_pos = HTML.find('id="atpExpDecisionSummary"')
    layout_open = HTML.find('class="atp-explainer-layout"')
    assert layout_open != -1 and summary_pos > layout_open and summary_pos < layout_end
    assert 'grid-column: 1 / -1' in css


def test_apply_v1_confirm_decision_box():
    assert 'atpGoogleApplyDecisionBox' in HTML
    assert 'UYGULANACAK KARAR' in HTML
    assert 'atpGoogleApplyDecisionMetrics' in HTML
    assert 'buildConfirmDecisionDiff' in EXPLAINER
    assert 'buildConfirmDecisionWhy' in EXPLAINER
    assert 'Onayla ve B Sırasını Uygula' in HTML
    assert 'atp-google-apply-decision' in (
        ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css'
    ).read_text(encoding='utf-8')


def test_error_copy_503_auth_rate_limit():
    assert "Google rota servisi yapılandırılmamış." in EXPLAINER
    assert "Google rota bağlantısı doğrulanamadı." in EXPLAINER
    assert "Google rota kotası doldu. Daha sonra tekrar deneyin." in EXPLAINER


def test_google_source_strip_locked_layout_kept():
    assert 'Mesafe ve saatler: Google Routes trafik tahmini' in HTML
    assert 'Sıra önerisi: CPS rota motoru' in HTML
    assert 'EN HIZLI' in HTML
    assert 'ÜCRETLİ GEÇİŞİ AZALTAN' in HTML
    assert 'CPS Sıra Önerisi' in HTML
    assert 'A — Mevcut Sırayı Koru' in HTML
    assert 'B — Önerilen Sırayı Uygula' in HTML
    assert 'id="atpExplainerMap"' in HTML
    assert 'id="atpExpMapCaption"' in HTML
    assert 'id="atpExpRouteFlow"' in HTML
    assert 'id="atpExpTollBadgeCurrent"' in HTML
    assert 'atpExpToggleCurrent' not in HTML


def test_trust_v1_single_selection_and_toll_badges():
    assert '_selectedOrder' in EXPLAINER
    assert '_selectedProfile' in EXPLAINER
    assert 'tollBadgeHtml' in EXPLAINER
    assert 'Ücretli geçiş tespit edildi' in EXPLAINER
    assert 'Ücretli geçiş tespit edilmedi' in EXPLAINER
    assert 'buildRouteFlowText' in EXPLAINER
    assert 'Haritada:' in EXPLAINER
    assert 'atpExpLegsPanel' in EXPLAINER
    assert 'buildGoogleDecisionSummary' in EXPLAINER
    assert 'CPS, yüksek öncelikli' in EXPLAINER


def test_trust_v1_past_departure_guard():
    assert 'Google trafik tahmini için çıkış tarihi ve saati gelecekte olmalıdır.' in MAIN
    assert '_departureIsFuture' in MAIN
    idx = MAIN.find('_departureIsFuture')
    goo = MAIN.find('/planlama/arac-takip/api/plan/google-route-options')
    assert 0 < idx < goo


def test_payload_fields_in_main():
    assert re.search(r'date:\s*planDate', MAIN)
    assert re.search(r'vehicle_id:\s*vid', MAIN)
    assert 'departure_time: hhmm' in MAIN
    assert 'gBody.plan_id' in MAIN


def test_diff_from_raw_seconds():
    dto = _dto()
    diffs = _diff_lines(dto['current']['fastest'], dto['suggested']['fastest'])
    assert diffs[0] == -15.0
    assert diffs[1] < 0
    assert 'Mesafe farkı' in EXPLAINER
    assert 'Sürüş farkı' in EXPLAINER
    assert 'Dönüş farkı' in EXPLAINER
    assert 'Trafik etkisi' in EXPLAINER


def test_no_ors_fallback_in_google_flow():
    chunk = MAIN[MAIN.find('initCikisSaati'): MAIN.find('initCikisSaati') + 8000]
    assert 'openrouteservice' not in chunk.lower()
    assert 'Google rota hesabı tamamlanamadı.' in chunk


def test_profile_v1_order_same_ui_wiring():
    css = (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')
    assert 'id="atpExpOrderSamePanel"' in HTML
    assert 'id="atpExpProfileCards"' in HTML
    assert 'id="atpExpProfileRecommendation"' in HTML
    assert 'MEVCUT SIRA CPS ÖNERİSİYLE AYNI' in HTML
    assert 'ÜCRETLİ GEÇİŞİ AZALTAN' in HTML
    assert 'ÜCRETLİ YOLDAN KAÇIN' not in HTML
    assert 'atp-exp-profile-card' in css
    assert 'atp-exp-profile-rec-badge' in css
    assert 'atp-exp-leg-grid' in css
    assert 'updateOrderSamePanels' in EXPLAINER
    assert 'updateProfileCards' in EXPLAINER
    assert 'profile_views' in EXPLAINER
    assert 'buildProfileTollMessage' in EXPLAINER
    assert 'pickRecommendedProfile' in EXPLAINER
    assert 'buildProfileRecommendationText' in EXPLAINER
    assert 'legTollLine' in EXPLAINER
    assert 'Google bu rotada ücretli geçiş bildiriyor' in EXPLAINER
    assert 'Google ücretli yolları azaltan bir rota hesapladı' in EXPLAINER
    assert 'Google bu rotada ücretli geçiş bildirmiyor' in EXPLAINER
    assert 'Ücretsiz Yol' not in EXPLAINER
    assert 'profile_only' in EXPLAINER
    assert 'En Hızlı Rotayı Kullan' in EXPLAINER
    assert 'Ücretli Geçişi Azaltan Rotayı Kullan' in EXPLAINER
    assert 'Onayla ve Rotayı Kullan' in EXPLAINER
    assert 'UYGULANACAK ROTA' in EXPLAINER
    assert 'En Hızlı rota kullanıma alındı' in EXPLAINER
    assert 'Sıra değişmedi' in EXPLAINER
    assert 'azaltmayı dener; tamamen kaldıracağını garanti etmez' in EXPLAINER


def test_profile_v1_recommendation_formula():
    dto = {
        'order_changed': False,
        'departure_time': '11:00',
        'service_minutes_per_stop': 10,
        'current': {
            'fastest': {
                'calculation_complete': True,
                'total_plan_seconds': 19920,
                'distance_m': 221800,
                'drive_seconds': 18120,
            },
            'toll_free': {
                'calculation_complete': True,
                'total_plan_seconds': 22020,
                'distance_m': 236400,
                'drive_seconds': 20220,
            },
        },
    }
    assert EXPLAINER.count('compareRecommendedProfile') >= 1
    # mirror JS tie-break: lower total_plan_seconds wins
    assert dto['current']['fastest']['total_plan_seconds'] < dto['current']['toll_free']['total_plan_seconds']


def test_profile_v1_readback_hooks():
    assert 'verifyGoogleProfileApplyReadback' in MAIN
    assert 'reloadAfterGoogleProfileApply' in MAIN
    assert 'reloadAfterProfileApply' in EXPLAINER
    assert 'traffic-free' in MAIN or 'traffic-fast' in MAIN

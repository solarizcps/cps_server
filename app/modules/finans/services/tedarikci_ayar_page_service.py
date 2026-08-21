# -*- coding: utf-8 -*-
"""
tedarikci_ayar_page_service.py
==============================
FAZ 6D — Tedarikçi Ayarları sayfa verisi (batch, filtre, KPI, pagination).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from modules.finans.services.korgun_finance_adapter import (
        COMPANY_LOCATIONS,
        CANONICAL_LOCATION_CODES,
        KorgunFinanceAdapter,
        _parse_location_filter_raw,
    )
    from modules.finans.services.odeme_karar_read_service import normalize_cari_display_name
    from modules.finans.services.odeme_plani_enrichment_service import (
        build_term_dto,
        fetch_supplier_term_map,
    )
    from modules.finans.services import tedarikci_ayar_service as ayar_svc
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import (
        COMPANY_LOCATIONS,
        CANONICAL_LOCATION_CODES,
        KorgunFinanceAdapter,
        _parse_location_filter_raw,
    )
    from app.modules.finans.services.odeme_karar_read_service import normalize_cari_display_name
    from app.modules.finans.services.odeme_plani_enrichment_service import (
        build_term_dto,
        fetch_supplier_term_map,
    )
    from app.modules.finans.services import tedarikci_ayar_service as ayar_svc

VALID_PAGE_SIZES = (10, 20, 50)
VALID_FILTERS = ('tumu', 'ayari_olmayan', 'kritik', 'duzenli_odeme')


def _parse_page(raw: Any, default: int = 1) -> int:
    try:
        return max(1, int(raw or default))
    except (TypeError, ValueError):
        return default


def _parse_page_size(raw: Any, default: int = 50) -> int:
    try:
        size = int(raw or default)
        return size if size in VALID_PAGE_SIZES else default
    except (TypeError, ValueError):
        return default


def _parse_locations(location_filter: Optional[str]) -> List[str]:
    return list(_parse_location_filter_raw(location_filter or None))


def _normalize_search(q: Optional[str]) -> str:
    return (q or '').strip().lower()


def _matches_search(cari_adi: str, cari_kod: str, q: str) -> bool:
    if not q:
        return True
    hay = f'{cari_adi} {cari_kod}'.lower()
    return q in hay


def _build_display_row(
    supplier: Any,
    setting: Dict[str, Any],
    term: Dict[str, Any],
    users_map: Dict[int, str],
) -> Dict[str, Any]:
    loc = supplier.location
    ck = supplier.cari_kod
    has = bool(setting.get('has_settings'))
    loc_label = COMPANY_LOCATIONS.get(loc, {}).get('label', loc)
    cari_adi = normalize_cari_display_name(supplier.cari_adi or setting.get('cari_adi_snapshot') or ck)

    if has:
        cat_display = setting.get('category_label') or setting.get('category_code')
        mode_display = ayar_svc.PAYMENT_MODE_LABELS.get(
            setting.get('payment_mode', ''), setting.get('payment_mode', '—'))
        period_display = ayar_svc.format_period_display(setting) if has else '—'
        pri_display = ayar_svc.PRIORITY_LABELS.get(
            setting.get('priority', 'NORMAL'), setting.get('priority', 'Normal'))
        kritik_display = 'Evet' if setting.get('critical_supplier') else 'Hayır'
        ayar_durumu = 'PASİF' if not setting.get('settings_active', True) else 'AYAR VAR'
        ayar_durumu_class = 'ta-status-passive' if ayar_durumu == 'PASİF' else 'ta-status-ok'
    else:
        cat_display = 'Ayar Yok'
        mode_display = '—'
        period_display = '—'
        pri_display = 'Normal'
        kritik_display = 'Hayır'
        ayar_durumu = 'AYAR YOK'
        ayar_durumu_class = 'ta-status-missing'

    uid = setting.get('responsible_user_id')
    sorumlu = users_map.get(int(uid)) if uid else '—'

    return {
        'location': loc,
        'location_label': loc_label,
        'cari_kod': ck,
        'cari_adi': cari_adi,
        'cari_adi_raw': supplier.cari_adi,
        'cari_sub': f'{ck} · {loc_label}',
        'category_display': cat_display,
        'category_code': setting.get('category_code', 'TANIMSIZ'),
        'payment_mode': setting.get('payment_mode', 'MANUEL'),
        'payment_mode_display': mode_display,
        'payment_period_display': period_display,
        'payment_period': setting.get('payment_period'),
        'payment_day': setting.get('payment_day'),
        'working_term_days': setting.get('working_term_days'),
        'working_term_basis': setting.get('working_term_basis'),
        'priority': setting.get('priority', 'NORMAL'),
        'priority_display': pri_display,
        'critical_display': kritik_display,
        'critical_supplier': bool(setting.get('critical_supplier')),
        'must_not_stop': bool(setting.get('must_not_stop')),
        'recurring_payment': bool(setting.get('recurring_payment')),
        'recurring_amount': setting.get('recurring_amount'),
        'recurring_currency': setting.get('recurring_currency'),
        'partial_payment_allowed': bool(setting.get('partial_payment_allowed')),
        'minimum_payment_amount': setting.get('minimum_payment_amount'),
        'responsible_user_id': uid,
        'responsible_display': sorumlu,
        'responsible_department': setting.get('responsible_department'),
        'payment_working_note': setting.get('payment_working_note'),
        'settings_active': setting.get('settings_active', True),
        'has_settings': has,
        'setting_id': setting.get('id'),
        'ayar_durumu': ayar_durumu,
        'ayar_durumu_class': ayar_durumu_class,
        'korgun_vade_display': term.get('display_short') or term.get('display') or 'Vade tanımlı değil',
        'korgun_vade_source': term.get('source') or 'Korgün',
        'korgun_vade_gun': term.get('vade_gun'),
        'term_readonly': True,
    }


def _apply_filters(
    rows: List[Dict[str, Any]],
    ff: str,
    kategori: Optional[str],
    oncelik: Optional[str],
    aktif_ayar: Optional[str],
    search_q: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not _matches_search(r['cari_adi'], r['cari_kod'], search_q):
            continue
        if ff == 'ayari_olmayan' and r['has_settings']:
            continue
        if ff == 'kritik' and not r['critical_supplier']:
            continue
        if ff == 'duzenli_odeme' and not r['recurring_payment']:
            continue
        if kategori and (not r['has_settings'] or r['category_code'] != kategori):
            continue
        if oncelik and r['priority'] != oncelik:
            continue
        if aktif_ayar == '1' and (not r['has_settings'] or not r['settings_active']):
            continue
        if aktif_ayar == '0' and (not r['has_settings'] or r['settings_active']):
            continue
        out.append(r)
    return out


def _paginate(rows: List[Dict[str, Any]], page: int, page_size: int) -> tuple:
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return rows[start:start + page_size], total, page, total_pages


def _compute_kpi(all_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    total = len(all_rows)
    with_settings = sum(1 for r in all_rows if r['has_settings'])
    without = total - with_settings
    kritik = sum(1 for r in all_rows if r['critical_supplier'])
    duzenli = sum(1 for r in all_rows if r['recurring_payment'])
    return {
        'toplam': total,
        'ayari_olan': with_settings,
        'ayari_olmayan': without,
        'kritik': kritik,
        'duzenli_odeme': duzenli,
    }


def tedarikci_ayarlari_sayfa_verisi(
    location_filter: Optional[str] = None,
    ff: str = 'tumu',
    kategori: Optional[str] = None,
    oncelik: Optional[str] = None,
    aktif_ayar: Optional[str] = None,
    search_q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    force_refresh: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    query_count = 0
    locations = _parse_locations(location_filter or 'SA001')
    if not locations:
        locations = list(CANONICAL_LOCATION_CODES)
    page = _parse_page(page)
    page_size = _parse_page_size(page_size)
    ff = ff if ff in VALID_FILTERS else 'tumu'
    search_norm = _normalize_search(search_q)

    adapter = KorgunFinanceAdapter()
    query_count += 1
    suppliers = adapter.fetch_supplier_master_balances(
        locations=locations,
        force_refresh=force_refresh,
    )

    cari_kods = sorted({s.cari_kod for s in suppliers if s.cari_kod})
    query_count += 1
    settings_map = ayar_svc.fetch_settings_map(locations=locations, db_path=db_path)
    query_count += 1
    term_raw = fetch_supplier_term_map(cari_kods)
    query_count += 1
    categories = ayar_svc.list_categories(db_path=db_path)
    query_count += 1
    users = ayar_svc.list_responsible_users(db_path=db_path)
    users_map = {int(u['Id']): (u['AdSoyad'] or u['KullaniciAdi']) for u in users}

    all_rows: List[Dict[str, Any]] = []
    for s in suppliers:
        key = f'{s.location}|{s.cari_kod}'
        setting = settings_map.get(key) or ayar_svc.build_default_setting_dto(s.location, s.cari_kod)
        term = build_term_dto(term_raw.get(s.cari_kod))
        all_rows.append(_build_display_row(s, setting, term, users_map))

    all_rows.sort(key=lambda r: (r['cari_adi'].lower(), r['cari_kod']))
    kpi = _compute_kpi(all_rows)
    filtered = _apply_filters(all_rows, ff, kategori, oncelik, aktif_ayar, search_norm)
    page_rows, total_filtered, pg_page, pg_total = _paginate(filtered, page, page_size)

    companies = [
        {'code': code, 'label': COMPANY_LOCATIONS[code]['label']}
        for code in CANONICAL_LOCATION_CODES
    ]

    return {
        'companies': companies,
        'location_filter': locations[0] if len(locations) == 1 else (location_filter or ''),
        'locations': locations,
        'rows': page_rows,
        'rows_all_count': len(all_rows),
        'kpi': kpi,
        'categories': categories,
        'users': users,
        'departments': list(ayar_svc.DEPARTMENTS),
        'payment_modes': [
            {'code': c, 'label': ayar_svc.PAYMENT_MODE_LABELS[c]} for c in ayar_svc.PAYMENT_MODES
        ],
        'payment_periods': [
            {'code': c, 'label': ayar_svc.PAYMENT_PERIOD_LABELS[c]} for c in ayar_svc.PAYMENT_PERIODS
        ],
        'priorities': [
            {'code': c, 'label': ayar_svc.PRIORITY_LABELS[c]} for c in ayar_svc.PRIORITIES
        ],
        'currencies': list(ayar_svc.CURRENCIES),
        'working_term_bases': [
            {'code': c, 'label': ayar_svc.WORKING_TERM_BASIS_LABELS[c]}
            for c in ayar_svc.WORKING_TERM_BASES
        ],
        'working_term_day_presets': list(ayar_svc.WORKING_TERM_DAY_PRESETS),
        'filters': {
            'ff': ff,
            'kategori': kategori or '',
            'oncelik': oncelik or '',
            'aktif_ayar': aktif_ayar or '',
            'q': search_q or '',
        },
        'pagination': {
            'page': pg_page,
            'page_size': page_size,
            'total': total_filtered,
            'total_pages': pg_total,
            'valid_sizes': VALID_PAGE_SIZES,
        },
        'query_count': query_count,
        'hata': None,
    }


def tedarikci_ayarlari_sayfa_verisi_safe(**kwargs) -> Dict[str, Any]:
    try:
        return tedarikci_ayarlari_sayfa_verisi(**kwargs)
    except Exception as exc:
        return {
            'companies': [
                {'code': c, 'label': COMPANY_LOCATIONS[c]['label']}
                for c in CANONICAL_LOCATION_CODES
            ],
            'location_filter': kwargs.get('location_filter') or 'SA001',
            'locations': ['SA001'],
            'rows': [],
            'rows_all_count': 0,
            'kpi': {'toplam': 0, 'ayari_olan': 0, 'ayari_olmayan': 0, 'kritik': 0, 'duzenli_odeme': 0},
            'categories': [],
            'users': [],
            'departments': list(ayar_svc.DEPARTMENTS),
            'payment_modes': [],
            'payment_periods': [],
            'priorities': [],
            'currencies': list(ayar_svc.CURRENCIES),
            'working_term_bases': [],
            'working_term_day_presets': [],
            'filters': {
                'ff': kwargs.get('ff', 'tumu'),
                'kategori': kwargs.get('kategori', ''),
                'oncelik': kwargs.get('oncelik', ''),
                'aktif_ayar': kwargs.get('aktif_ayar', ''),
                'q': kwargs.get('search_q', ''),
            },
            'pagination': {
                'page': 1, 'page_size': 50, 'total': 0, 'total_pages': 1,
                'valid_sizes': VALID_PAGE_SIZES,
            },
            'query_count': 0,
            'hata': str(exc),
        }

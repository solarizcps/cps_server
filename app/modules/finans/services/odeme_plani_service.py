# -*- coding: utf-8 -*-
"""
Ödeme Planı Service — P3A.2 canonical canlı borç.

KPI semantiği:
  - toplam_acik_borc → kg_fn_CariHesToplam CROSS APPLY (canlı muhasebe net borcu)
  - vade bucket KPI → yalnız cek_Kart (vadesi bilinen çek yükümlülükleri)
  Cari bakiye toplamı vade bucket'larına DAĞITILMAZ.
  CariBakiye stale snapshot artık ana borç kaynağı değildir.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

try:
    from modules.finans.services.odeme_plani_ops_service import (
        build_iletisim_list_rows,
        build_soz_list_rows,
        format_son_gorusme,
        format_son_odeme_sozu,
        get_cari_parity_maps,
    )
except ImportError:
    from app.modules.finans.services.odeme_plani_ops_service import (
        build_iletisim_list_rows,
        build_soz_list_rows,
        format_son_gorusme,
        format_son_odeme_sozu,
        get_cari_parity_maps,
    )

try:
    from modules.finans.services.odeme_takip_service import fetch_aktif_takip_map
except ImportError:
    from app.modules.finans.services.odeme_takip_service import fetch_aktif_takip_map

try:
    from modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_LOCATIONS,
        DEBT_NET_TOLERANCE,
        KorgunFinanceAdapter,
        SupplierBalanceDTO,
    )
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_LOCATIONS,
        DEBT_NET_TOLERANCE,
        KorgunFinanceAdapter,
        SupplierBalanceDTO,
    )

VALID_TABS = (
    'yukumlulukler',
    'cariler',
    'anlasmalar',
    'odeme_sozleri',
    'arama',
    'odendi',
)

TAB_LABELS = {
    'yukumlulukler': 'Yükümlülükler',
    'cariler': 'Cariler / Tedarikçiler',
    'anlasmalar': 'Anlaşmalar',
    'odeme_sozleri': 'Ödeme Sözleri',
    'arama': 'Aradı / Ödeme Sordu',
    'odendi': 'Ödendi',
}


def _parse_tab(raw: Optional[str]) -> str:
    t = (raw or 'yukumlulukler').strip().lower()
    return t if t in VALID_TABS else 'yukumlulukler'


def _parse_location_filter(raw: Optional[str]) -> Optional[List[str]]:
    if not raw or raw.strip().lower() in ('', 'all', 'tumu', 'tümü'):
        return None
    code = raw.strip().upper()
    if code in COMPANY_LOCATIONS:
        return [code]
    return None


def _vade_bucket_from_date(vade_str: Optional[str], today: date) -> Optional[str]:
    if not vade_str:
        return None
    try:
        vade = datetime.strptime(vade_str[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    diff = (vade - today).days
    if diff < 0:
        return 'vadesi_gecmis'
    if diff == 0:
        return 'bugun'
    if diff <= 7:
        return '7_gun'
    if diff <= 30:
        return '30_gun'
    if diff <= 60:
        return '31_60_gun'
    if diff <= 90:
        return '61_90_gun'
    return 'diger'


def _aggregate_currency(rows: List[SupplierBalanceDTO]) -> Dict[str, Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'tutar': 0.0, 'kalem': 0})
    for r in rows:
        agg[r.para_birimi]['tutar'] += r.bakiye
        agg[r.para_birimi]['kalem'] += 1
    return dict(agg)


def _build_vade_summary(checks: List[Dict[str, Any]], today: date) -> Dict[str, Dict[str, Any]]:
    buckets = {
        'vadesi_gecmis': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '7_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '30_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '31_60_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '61_90_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
    }
    for c in checks:
        bucket = _vade_bucket_from_date(c.get('Vade'), today)
        if bucket not in buckets:
            continue
        pb = c.get('para_birimi') or 'TRY'
        buckets[bucket][pb]['tutar'] += float(c.get('tutar') or 0)
        buckets[bucket][pb]['kalem'] += 1
    return {k: dict(v) for k, v in buckets.items()}


def _kpi_from_currency(
    totals: Dict[str, Dict[str, Any]],
    pb_primary: str = 'TRY',
    *,
    source: str = '',
    semantic: str = '',
) -> Dict[str, Any]:
    primary = totals.get(pb_primary, {'tutar': 0.0, 'kalem': 0})
    others = {k: v for k, v in totals.items() if k != pb_primary and v.get('kalem', 0) > 0}
    return {
        'tutar': primary.get('tutar', 0.0),
        'kalem': primary.get('kalem', 0),
        'para_birimi': pb_primary,
        'diger_pb': others,
        'has_data': primary.get('kalem', 0) > 0 or bool(others),
        'source': source,
        'semantic': semantic,
    }


def _net_is_zero(net: float) -> bool:
    """P3A.10 — kg_fn net exact zero (Decimal, no JS tolerance)."""
    return Decimal(str(net)) == Decimal('0')


CariViewMode = Literal['daily', 'active', 'zero']


def _bakiye_durumu(net: float) -> tuple[str, str]:
    """P3A.9 — canonical net → cari satır durumu."""
    if net > DEBT_NET_TOLERANCE:
        return 'Açık Borç', 'op-st-open'
    if net < -DEBT_NET_TOLERANCE:
        return 'Alacaklıyız', 'op-st-credit'
    return 'Bakiye Yok', 'op-st-neutral'


def _build_yukumluluk_rows(balances: List[SupplierBalanceDTO]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for b in balances:
        rows.append({
            'vade_tarihi': None,
            'vade_label': '—',
            'location': b.location,
            'location_label': b.location_label,
            'cari_kod': b.cari_kod,
            'cari_adi': b.cari_adi,
            'belge_aciklama': 'Canlı Muhasebe Net Borcu (Korgün kg_fn)',
            'tur': 'Bakiye',
            'para_birimi': b.para_birimi,
            'toplam_tutar': b.bakiye,
            'kalan_tutar': b.bakiye,
            'durum': 'Açık Borç',
            'durum_class': 'op-st-open',
            'odendi': '—',
            'canonical_key': b.canonical_key,
        })
    return rows


def _build_cari_rows(
    balances: List[SupplierBalanceDTO],
    soz_map: Optional[Dict[str, Dict[str, Any]]] = None,
    iletisim_map: Optional[Dict[str, Dict[str, Any]]] = None,
    takip_map: Optional[Dict[str, bool]] = None,
    cari_view: CariViewMode = 'daily',
) -> List[Dict[str, Any]]:
    """Cariler/Tedarikçiler — Korgün bakiye + CPS son kayıtlar + aktif takip flag.

    takip_map: canonical_key → bool  (fetch_aktif_takip_map tek queryde yükler, N+1 YOK)
    cari_view:
      daily  — net != 0 (günlük liste, 0 bakiye gizli)
      active — aktif_takip=true (0 bakiye dahil)
      zero   — yalnız net == 0
    """
    soz_map = soz_map or {}
    iletisim_map = iletisim_map or {}
    takip_map = takip_map or {}
    rows: List[Dict[str, Any]] = []
    for b in balances:
        key = b.canonical_key
        aktif_takip = takip_map.get(key, False)
        is_zero = _net_is_zero(b.bakiye)

        if cari_view == 'zero':
            if not is_zero:
                continue
        elif cari_view == 'active':
            if not aktif_takip:
                continue
        else:  # daily — default günlük görünüm
            if is_zero:
                continue
        durum_label, durum_class = _bakiye_durumu(b.bakiye)
        rows.append({
            'location': b.location,
            'location_label': b.location_label,
            'cari_kod': b.cari_kod,
            'cari_adi': b.cari_adi,
            'para_birimi': b.para_birimi,
            'acik_bakiye': b.bakiye,
            'bakiye_durumu': durum_label,
            'bakiye_durum_class': durum_class,
            'kritik': durum_label,
            'kritik_class': durum_class,
            'anlasma_durumu': 'Anlaşma girilmedi',
            'son_odeme_sozu': format_son_odeme_sozu(soz_map.get(key)),
            'son_gorusme': format_son_gorusme(iletisim_map.get(key)),
            'canonical_key': key,
            'aktif_takip': aktif_takip,
        })
    rows.sort(key=lambda r: (r['location'], r['cari_adi'], r['para_birimi']))
    return rows


def _empty_state(tab: str) -> Dict[str, Any]:
    messages = {
        'anlasmalar': 'Ödeme anlaşmaları henüz aktarılmadı.',
        'odeme_sozleri': 'Henüz ödeme sözü kaydı yok.',
        'arama': 'Henüz arama / ödeme sorma kaydı yok.',
        'odendi': 'Henüz ödeme geçmişi kaydı yok.',
    }
    return {
        'empty': True,
        'message': messages.get(tab, 'Kayıt bulunamadı.'),
        'rows': [],
    }


def odeme_plani_sayfa_verisi(
    location_filter: Optional[str] = None,
    active_tab: Optional[str] = None,
    aktif_takip_filter: Optional[bool] = None,
    cari_view: CariViewMode = 'daily',
) -> Dict[str, Any]:
    """P2 ana sayfa — sekmeler + global şirket filtresi."""
    adapter = KorgunFinanceAdapter()
    today = date.today()
    locations = _parse_location_filter(location_filter)
    tab = _parse_tab(active_tab)

    verification = adapter.verify_supplier_rule()
    # P3A.9: supplier master (tüm 320.*) ≠ açık borç (net > 0)
    supplier_master = adapter.fetch_supplier_master_balances(locations=locations)
    debt_balances = adapter.fetch_supplier_balances(locations=locations, positive_only=True)
    checks = adapter.fetch_open_checks(locations=locations)
    supplier_counts = adapter.count_suppliers_by_location(locations=locations, balances=debt_balances)

    currency_totals = _aggregate_currency(debt_balances)
    vade_summary = _build_vade_summary(checks, today)

    kpi = {
        'toplam_acik_borc': _kpi_from_currency(
            currency_totals,
            source='kg_fn',
            semantic='Canlı muhasebe net borcu (kg_fn_CariHesToplam)',
        ),
        'vadesi_gecmis': _kpi_from_currency(
            vade_summary.get('vadesi_gecmis', {}),
            source='cek_Kart',
            semantic='Vadesi geçmiş çek yükümlülüğü',
        ),
        '7_gun': _kpi_from_currency(
            vade_summary.get('7_gun', {}),
            source='cek_Kart',
            semantic='7 gün içinde vadeli çek',
        ),
        '30_gun': _kpi_from_currency(
            vade_summary.get('30_gun', {}),
            source='cek_Kart',
            semantic='30 gün içinde vadeli çek',
        ),
        '31_60_gun': _kpi_from_currency(
            vade_summary.get('31_60_gun', {}),
            source='cek_Kart',
            semantic='31–60 gün vadeli çek',
        ),
        '61_90_gun': _kpi_from_currency(
            vade_summary.get('61_90_gun', {}),
            source='cek_Kart',
            semantic='61–90 gün vadeli çek',
        ),
        'odendi': {
            'tutar': 0.0, 'kalem': 0, 'para_birimi': 'TRY',
            'diger_pb': {}, 'has_data': False,
            'source': 'CPS', 'semantic': 'P5 ödeme geçmişi',
        },
    }

    table_rows: List[Dict[str, Any]] = []
    cari_rows: List[Dict[str, Any]] = []
    soz_rows: List[Dict[str, Any]] = []
    arama_rows: List[Dict[str, Any]] = []
    tab_empty: Optional[Dict[str, Any]] = None

    soz_map, iletisim_map = get_cari_parity_maps(locations)

    # P3A.5: aktif takip map — tek query, N+1 yok
    takip_map = fetch_aktif_takip_map(locations)

    # P3A.10: cari_view UI filtresi (master dataset aynı, yeni kg_fn yok)
    if cari_view not in ('daily', 'active', 'zero'):
        cari_view = 'daily'

    if tab == 'yukumlulukler':
        table_rows = _build_yukumluluk_rows(debt_balances)
    elif tab == 'cariler':
        cari_rows = _build_cari_rows(
            supplier_master, soz_map, iletisim_map, takip_map, cari_view,
        )
    elif tab == 'odeme_sozleri':
        soz_rows = build_soz_list_rows(locations)
        if not soz_rows:
            tab_empty = _empty_state(tab)
    elif tab == 'arama':
        arama_rows = build_iletisim_list_rows(locations)
        if not arama_rows:
            tab_empty = _empty_state(tab)
    elif tab in ('anlasmalar', 'odendi'):
        tab_empty = _empty_state(tab)

    if tab == 'yukumlulukler':
        total_kayit = len(table_rows)
    elif tab == 'cariler':
        total_kayit = len(cari_rows)
    elif tab == 'odeme_sozleri':
        total_kayit = len(soz_rows)
    elif tab == 'arama':
        total_kayit = len(arama_rows)
    else:
        total_kayit = 0

    return {
        'ok': True,
        'p2_phase': True,
        'p3a_phase': True,
        'active_tab': tab,
        'tabs': [{'id': t, 'label': TAB_LABELS[t]} for t in VALID_TABS],
        'location_filter': location_filter or '',
        'aktif_takip_filter': aktif_takip_filter,
        'cari_view': cari_view,
        'companies': [
            {'code': '', 'label': 'Tüm Şirketler'},
        ] + [
            {'code': code, 'label': meta['label']}
            for code, meta in COMPANY_LOCATIONS.items()
        ],
        'verification': asdict(verification),
        'supplier_counts': supplier_counts,
        'supplier_counts_total': sum(supplier_counts.values()),
        'kpi': kpi,
        'table_rows': table_rows,
        'cari_rows': cari_rows,
        'soz_rows': soz_rows,
        'arama_rows': arama_rows,
        'tab_empty': tab_empty,
        'total_kayit': total_kayit,
        'total_kalan_by_pb': currency_totals,
        'korgun_readonly': True,
        'hata': None,
    }


def odeme_plani_sayfa_verisi_safe(
    location_filter: Optional[str] = None,
    active_tab: Optional[str] = None,
    aktif_takip_filter: Optional[bool] = None,
    cari_view: CariViewMode = 'daily',
) -> Dict[str, Any]:
    """Fail-safe wrapper."""
    try:
        return odeme_plani_sayfa_verisi(
            location_filter=location_filter,
            active_tab=active_tab,
            aktif_takip_filter=aktif_takip_filter,
            cari_view=cari_view,
        )
    except Exception as exc:
        tab = _parse_tab(active_tab)
        return {
            'ok': False,
            'p2_phase': True,
            'p3a_phase': True,
            'active_tab': tab,
            'tabs': [{'id': t, 'label': TAB_LABELS[t]} for t in VALID_TABS],
            'location_filter': location_filter or '',
            'aktif_takip_filter': aktif_takip_filter,
            'cari_view': cari_view if cari_view in ('daily', 'active', 'zero') else 'daily',
            'companies': [
                {'code': '', 'label': 'Tüm Şirketler'},
                {'code': 'YN001', 'label': 'NexGen'},
                {'code': 'SA001', 'label': 'Şahin Taban'},
                {'code': 'YP001', 'label': 'Pera AŞ'},
            ],
            'verification': {},
            'supplier_counts': {c: 0 for c in CANONICAL_LOCATION_CODES},
            'supplier_counts_total': 0,
            'kpi': {},
            'table_rows': [],
            'cari_rows': [],
            'soz_rows': [],
            'arama_rows': [],
            'tab_empty': None,
            'can_write': False,
            'total_kayit': 0,
            'total_kalan_by_pb': {},
            'korgun_readonly': True,
            'hata': str(exc),
        }

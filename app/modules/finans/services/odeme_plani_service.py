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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

try:
    from modules.finans.services.odeme_plani_ops_service import (
        build_iletisim_list_rows,
        build_soz_list_rows,
        get_cari_parity_maps,
    )
except ImportError:
    from app.modules.finans.services.odeme_plani_ops_service import (
        build_iletisim_list_rows,
        build_soz_list_rows,
        get_cari_parity_maps,
    )

try:
    from modules.finans.services.odeme_plani_enrichment_service import fetch_enrichment_maps
except ImportError:
    from app.modules.finans.services.odeme_plani_enrichment_service import fetch_enrichment_maps

try:
    from modules.finans.services.odeme_takip_service import fetch_aktif_takip_map
except ImportError:
    from app.modules.finans.services.odeme_takip_service import fetch_aktif_takip_map

try:
    from modules.finans.services.odeme_karar_read_service import (
        build_karar_cari_rows,
        fetch_layer2_maps,
    )
except ImportError:
    from app.modules.finans.services.odeme_karar_read_service import (
        build_karar_cari_rows,
        fetch_layer2_maps,
    )

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


VALID_PAGE_SIZES = (10, 20, 50)


def _parse_page(raw: Optional[str], default: int = 1) -> int:
    try:
        return max(1, int(raw or default))
    except (TypeError, ValueError):
        return default


def _parse_page_size(raw: Optional[str], default: int = 50) -> int:
    try:
        size = int(raw or default)
        return size if size in VALID_PAGE_SIZES else default
    except (TypeError, ValueError):
        return default


def _days_since(iso_date: Optional[str], today: date) -> Optional[int]:
    if not iso_date:
        return None
    try:
        if len(iso_date) >= 10 and iso_date[4] == '-':
            d = datetime.strptime(iso_date[:10], '%Y-%m-%d').date()
        elif '.' in iso_date:
            parts = iso_date.split('.')
            if len(parts) >= 3:
                d = datetime.strptime(f'{parts[2]}-{parts[1]}-{parts[0]}', '%Y-%m-%d').date()
            else:
                return None
        else:
            return None
    except (ValueError, TypeError):
        return None
    return (today - d).days


def _match_date_filter(iso_date: Optional[str], filter_key: str, today: date) -> bool:
    if not filter_key:
        return True
    if filter_key == 'yok':
        return not iso_date
    days = _days_since(iso_date, today)
    if days is None:
        return False
    if filter_key == 'bu_ay':
        return days <= 31
    if filter_key == 'son_30':
        return days <= 30
    if filter_key == 'son_90':
        return days <= 90
    return True


def _norm_bakiye_durum(raw: str) -> str:
    return (raw or '').lower().replace(' ', '_')


def _week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def _promise_in_week(promise_iso: Optional[str], today: date) -> bool:
    if not promise_iso:
        return False
    try:
        d = datetime.strptime(promise_iso[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False
    wk_start, wk_end = _week_bounds(today)
    return wk_start <= d <= wk_end


def _cari_row_visible(row: Dict[str, Any], filters: Dict[str, str], today: date) -> bool:
    """Client rowVisible() ile aynı semantik — server-side filtre."""
    qf = filters.get('qf') or 'tumu'
    cari_adi = (row.get('cari_adi') or '').lower()
    baki_durum = _norm_bakiye_durum(row.get('bakiye_durumu') or '')
    karar = _norm_bakiye_durum(row.get('karar_badge') or '')
    fa_tarih = row.get('fa_tarih') or ''
    alim_tarih = row.get('son_alim_tarih') or ''
    temas_iso = row.get('temas_tarih_iso') or ''
    soz_active = bool(row.get('soz_has_active'))
    soz_overdue = bool(row.get('soz_is_overdue'))
    soz_date = row.get('soz_promise_date') or ''
    vade_has = bool(row.get('vade_has_term'))
    takip = 'aktif' if row.get('aktif_takip') else 'pasif'

    if qf == 'mudahale':
        if 'borç' not in baki_durum and 'borc' not in baki_durum:
            return False
    elif qf == 'acik_borc':
        if 'borç' not in baki_durum and 'borc' not in baki_durum:
            return False
    elif qf == 'alacakli':
        if 'alacak' not in baki_durum:
            return False
    elif qf == 'aktif_takip':
        if takip != 'aktif':
            return False
    elif qf == 'sifir_bakiye':
        if 'yok' not in baki_durum:
            return False

    tedarikci = (filters.get('tedarikci') or '').strip().lower()
    if tedarikci and tedarikci not in cari_adi:
        return False

    bakiye_f = filters.get('bakiye') or ''
    if bakiye_f == 'acik_borc' and 'borç' not in baki_durum and 'borc' not in baki_durum:
        return False
    if bakiye_f == 'alacakli' and 'alacak' not in baki_durum:
        return False
    if bakiye_f == 'sifir' and 'yok' not in baki_durum:
        return False

    karar_f = filters.get('karar') or ''
    if karar_f == 'odeme_yapma' and 'alacak' not in baki_durum:
        return False
    if karar_f == 'acik_borc' and 'borç' not in baki_durum and 'borc' not in baki_durum:
        return False
    if karar_f == 'mudahale' and 'borç' not in baki_durum and 'borc' not in baki_durum:
        return False

    vade_f = filters.get('vade') or ''
    if vade_f == 'vade_yok' and vade_has:
        return False
    if vade_f == 'vade_var' and not vade_has:
        return False

    if not _match_date_filter(fa_tarih, filters.get('odeme') or '', today):
        return False
    if not _match_date_filter(alim_tarih, filters.get('alim') or '', today):
        return False
    if not _match_date_filter(temas_iso, filters.get('temas') or '', today):
        return False

    soz_f = filters.get('soz') or ''
    if soz_f == 'var' and not soz_active:
        return False
    if soz_f == 'yok' and soz_active:
        return False
    if soz_f == 'bu_hafta' and not (soz_active and _promise_in_week(soz_date, today)):
        return False
    if soz_f == 'gecikmis' and not (soz_active and soz_overdue):
        return False
    takip_f = filters.get('takip') or ''
    if takip_f and takip_f != takip:
        return False
    return True


def _apply_cari_row_filters(
    rows: List[Dict[str, Any]],
    filters: Optional[Dict[str, str]],
    today: date,
) -> List[Dict[str, Any]]:
    if not filters:
        return rows
    active = any(
        (filters.get(k) or ('' if k != 'qf' else 'tumu')) not in ('', 'tumu')
        for k in ('qf', 'tedarikci', 'bakiye', 'karar', 'vade', 'odeme', 'alim', 'temas', 'soz', 'takip')
    )
    if not active:
        return rows
    return [r for r in rows if _cari_row_visible(r, filters, today)]


def _paginate_cari_rows(
    rows: List[Dict[str, Any]],
    page: int,
    page_size: int,
) -> tuple[List[Dict[str, Any]], int, int, int]:
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return rows[start:start + page_size], total, page, total_pages


def _filters_active(filters: Optional[Dict[str, str]]) -> bool:
    filters = filters or {}
    return any(
        (filters.get(k) or ('' if k != 'qf' else 'tumu')) not in ('', 'tumu')
        for k in ('qf', 'tedarikci', 'bakiye', 'karar', 'vade', 'odeme', 'alim', 'temas', 'soz', 'takip')
    )


def _is_open_debt_row(row: Dict[str, Any]) -> bool:
    bd = (row.get('bakiye_durumu') or '').lower()
    return 'borç' in bd or 'borc' in bd


def _aggregate_open_debt_from_ui_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Filtered KPI — UI row evreninden SUM(abs(net)) WHERE açık borç."""
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'tutar': 0.0, 'kalem': 0})
    for r in rows:
        if not _is_open_debt_row(r):
            continue
        pb = r.get('para_birimi') or 'TRY'
        agg[pb]['tutar'] += float(r.get('display_bakiye') or 0)
        agg[pb]['kalem'] += 1
    return dict(agg)


def _kpi_debt_kalem_total(totals: Dict[str, Dict[str, Any]]) -> int:
    return sum(int(v.get('kalem') or 0) for v in totals.values())


def _build_filtered_kpi(cari_rows_filtered: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = _aggregate_open_debt_from_ui_rows(cari_rows_filtered)
    debt_kpi = _kpi_from_currency(
        totals,
        source='kg_fn',
        semantic='Filtrelenmiş açık borç evreni (pagination öncesi tam set)',
    )
    debt_kpi['kalem_total'] = _kpi_debt_kalem_total(totals)
    return {
        'active': True,
        'filtered_count': len(cari_rows_filtered),
        'toplam_acik_borc': debt_kpi,
    }


def _parse_cari_filters(raw: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    raw = raw or {}
    return {
        'qf': (raw.get('qf') or 'tumu').strip(),
        'tedarikci': (raw.get('tedarikci') or raw.get('fh_tedarikci') or '').strip(),
        'bakiye': (raw.get('bakiye') or raw.get('fh_bakiye') or '').strip(),
        'karar': (raw.get('karar') or raw.get('fh_karar') or '').strip(),
        'vade': (raw.get('vade') or raw.get('fh_vade') or '').strip(),
        'odeme': (raw.get('odeme') or raw.get('fh_odeme') or '').strip(),
        'alim': (raw.get('alim') or raw.get('fh_alim') or '').strip(),
        'temas': (raw.get('temas') or raw.get('fh_temas') or '').strip(),
        'soz': (raw.get('soz') or raw.get('fh_soz') or '').strip(),
        'takip': (raw.get('takip') or raw.get('fh_takip') or '').strip(),
    }


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


def _aggregate_open_debt_currency(rows: List[SupplierBalanceDTO]) -> Dict[str, Dict[str, Any]]:
    """P1.2B — Toplam Açık Borç: SUM(abs(net)) WHERE net < 0."""
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {'tutar': 0.0, 'kalem': 0})
    for r in rows:
        if r.bakiye >= -DEBT_NET_TOLERANCE:
            continue
        agg[r.para_birimi]['tutar'] += abs(r.bakiye)
        agg[r.para_birimi]['kalem'] += 1
    return dict(agg)


def _build_vade_summary(checks: List[Dict[str, Any]], today: date) -> Dict[str, Dict[str, Any]]:
    """P1.2I — Vade bucket'ları cek_Kart açık çeklerinden.
    
    SEMANTİK UYARI: Bu tutarlar Toplam Açık Borç'un (kg_fn) alt kümesi DEĞİL.
    Açık çekler (mycek=K, iptal=0) kendi bağımsız ticari çek evrenini temsil eder.
    vadesi_gecmis = vade tarihi bugünden önce olan açık çekler.
    7_gun = today <= vade <= today+7
    30_gun = today+8 <= vade <= today+30  (7-gün ile duplicate yok)
    """
    buckets = {
        'vadesi_gecmis': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '7_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '30_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '31_60_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
        '61_90_gun': defaultdict(lambda: {'tutar': 0.0, 'kalem': 0}),
    }
    for c in checks:
        vade_str = c.get('Vade')
        if not vade_str:
            continue
        try:
            vade = datetime.strptime(vade_str[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        diff = (vade - today).days
        # P1.2I — Exclusive buckets: 7_gun ve 30_gun overlap yok
        if diff < 0:
            bucket = 'vadesi_gecmis'
        elif diff <= 7:
            bucket = '7_gun'
        elif diff <= 30:
            bucket = '30_gun'
        elif diff <= 60:
            bucket = '31_60_gun'
        elif diff <= 90:
            bucket = '61_90_gun'
        else:
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
    """P1.2B — 320 tedarikçi: net>0 alacaklıyız, net<0 açık borç."""
    if net > DEBT_NET_TOLERANCE:
        return 'Alacaklıyız', 'op-st-credit'
    if net < -DEBT_NET_TOLERANCE:
        return 'Açık Borç', 'op-st-open'
    return 'Bakiye Yok', 'op-st-neutral'


def _display_bakiye(net: float) -> float:
    if _net_is_zero(net):
        return 0.0
    return abs(net)


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
            'toplam_tutar': abs(b.bakiye),
            'kalan_tutar': abs(b.bakiye),
            'raw_net': b.bakiye,
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
            'display_bakiye': _display_bakiye(b.bakiye),
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
    page: int = 1,
    page_size: int = 10,
    cari_filters: Optional[Dict[str, str]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """P2 ana sayfa — sekmeler + global şirket filtresi."""
    adapter = KorgunFinanceAdapter()
    today = date.today()
    locations = _parse_location_filter(location_filter)
    tab = _parse_tab(active_tab)
    page = _parse_page(str(page))
    page_size = _parse_page_size(str(page_size))
    filters = _parse_cari_filters(cari_filters)

    verification = adapter.verify_supplier_rule()
    # PERF-01: tek kg_fn taraması → master + açık borç projeksiyonu
    supplier_master, debt_balances = adapter.fetch_supplier_balances_bundle(
        locations=locations,
        force_refresh=force_refresh,
    )
    checks = adapter.fetch_open_checks(locations=locations)
    supplier_counts = adapter.count_suppliers_by_location(locations=locations, balances=debt_balances)

    currency_totals = _aggregate_open_debt_currency(debt_balances)
    vade_summary = _build_vade_summary(checks, today)

    kpi = {
        'toplam_acik_borc': _kpi_from_currency(
            currency_totals,
            source='kg_fn',
            semantic='Canlı muhasebe net borcu (kg_fn_CariHesToplam)',
        ),
        # P1.2I — Vade KPI'ları cek_Kart evreninden (açık çekler).
        # Toplam Açık Borç'un (kg_fn) alt kümesi DEĞİL; bağımsız çek yükümlülükleri.
        'vadesi_gecmis': _kpi_from_currency(
            vade_summary.get('vadesi_gecmis', {}),
            source='cek_Kart',
            semantic='Vadesi geçmiş açık çekler (mycek=K, vade < bugün)',
        ),
        '7_gun': _kpi_from_currency(
            vade_summary.get('7_gun', {}),
            source='cek_Kart',
            semantic='Bugün–7 gün arası vadeli açık çekler (vade ≤ today+7)',
        ),
        '30_gun': _kpi_from_currency(
            vade_summary.get('30_gun', {}),
            source='cek_Kart',
            semantic='8–30 gün vadeli açık çekler (today+8 ≤ vade ≤ today+30)',
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
    kpi['toplam_acik_borc']['kalem_total'] = _kpi_debt_kalem_total(currency_totals)

    # P1.2H — Bu Hafta Ödeme Sözü (CPS DB, promise_date bu hafta Pazartesi-Pazar)
    try:
        import sqlite3 as _sqlite3
        from modules.finans.services.odeme_plani_ops_repo import SOZ_TABLO, _tables_ready
        from db import get_conn as _get_conn_cps
        # P1.2I: locations None ise tüm location kodları kullan
        _soz_locs = locations if locations else list(CANONICAL_LOCATION_CODES)
        if _tables_ready():
            _today = today
            _wk_start = _today - timedelta(days=_today.weekday())
            _wk_end = _wk_start + timedelta(days=6)
            _con_cps = _get_conn_cps()
            _cur = _con_cps.cursor()
            _loc_ph = ','.join('?' * len(_soz_locs))
            _cur.execute(
                f"""SELECT COUNT(*) as cnt, SUM(CAST(COALESCE(amount,0) AS REAL)) as toplam
                FROM {SOZ_TABLO}
                WHERE location IN ({_loc_ph})
                  AND status NOT IN ('IPTAL')
                  AND promise_date BETWEEN ? AND ?""",
                (*_soz_locs, str(_wk_start), str(_wk_end)),
            )
            _soz_r = _cur.fetchone()
            _soz_tutar = float(_soz_r[1] or 0)
            _soz_kalem = int(_soz_r[0] or 0)
            _soz_cari = 0
            _cur.execute(
                f"""SELECT COUNT(DISTINCT cari_kod) FROM {SOZ_TABLO}
                WHERE location IN ({_loc_ph})
                  AND status NOT IN ('IPTAL')
                  AND promise_date BETWEEN ? AND ?""",
                (*_soz_locs, str(_wk_start), str(_wk_end)),
            )
            _soz_cari = int((_cur.fetchone() or [0])[0] or 0)
            kpi['bu_hafta_odeme_sozu'] = {
                'tutar': _soz_tutar, 'kalem': _soz_kalem, 'cari': _soz_cari,
                'para_birimi': 'TRY', 'has_data': _soz_kalem > 0,
                'source': 'CPS.finans_odeme_plani_sozu',
                'semantic': 'Bu hafta promise_date olan ödeme sözleri (IPTAL hariç)',
                'hafta_baslangic': str(_wk_start), 'hafta_bitis': str(_wk_end),
            }
        else:
            kpi['bu_hafta_odeme_sozu'] = {
                'tutar': 0, 'kalem': 0, 'cari': 0,
                'para_birimi': 'TRY', 'has_data': False,
                'source': 'CPS', 'semantic': 'Tablo hazır değil',
            }
    except Exception:
        kpi['bu_hafta_odeme_sozu'] = {
            'tutar': 0, 'kalem': 0, 'cari': 0,
            'para_birimi': 'TRY', 'has_data': False,
            'source': 'CPS', 'semantic': 'Hesaplanamadı',
        }

    # P1.2H — Bugün Muhasebe Girişleri (Korgün Banka_Kay.insDT + Cek_Har.insDT)
    try:
        from modules.finans.services.korgun_finance_adapter import _baglan as _kg_baglan, get_finance_location_scope as _gfls
        _kg_con = _kg_baglan()
        _kg_cur = _kg_con.cursor()
        # P1.2I: consolidated scope, locations None ise tüm canonical kodlar
        _muh_locs = locations if locations else list(CANONICAL_LOCATION_CODES)
        _all_locs = list({s for loc in _muh_locs for s in _gfls(loc).split(',')})
        _loc_ph2 = ','.join(['%s'] * len(_all_locs))
        # Bugün girilen banka ödeme fişleri (320.* cariler)
        _kg_cur.execute(
            f"""SELECT COUNT(DISTINCT bk.FisNo) as cnt, ISNULL(SUM(ABS(bt.Tutar)),0) as toplam
            FROM Banka_Kay bk WITH (NOLOCK)
            JOIN BankaTutar bt WITH (NOLOCK) ON bt.FisNo = bk.FisNo
            WHERE CAST(bk.insDT AS DATE) = CAST(GETDATE() AS DATE)
              AND ISNULL(bk.iptal,'') NOT IN ('*')
              AND bk.cmbkod LIKE '320.%%'
              AND bk.Location IN ({_loc_ph2})""",
            _all_locs,
        )
        _bk_r = _kg_cur.fetchone()
        _bk_cnt = int(_bk_r[0] or 0)
        _bk_sum = float(_bk_r[1] or 0)
        # Bugün girilen çek işlemleri (verilen çek, HarTip=0)
        _kg_cur.execute(
            f"""SELECT COUNT(*) as cnt, ISNULL(SUM(ABS(ck.Tutar)),0) as toplam
            FROM Cek_Har ch WITH (NOLOCK)
            JOIN cek_Kart ck WITH (NOLOCK) ON ck.CekNo = ch.Cekinx
            WHERE CAST(ch.insDT AS DATE) = CAST(GETDATE() AS DATE)
              AND ch.HarTip = '0'
              AND ck.CekTip = 'F'
              AND ch.cmb_Kod LIKE '320.%%'""",
        )
        _ck_r = _kg_cur.fetchone()
        _ck_cnt = int(_ck_r[0] or 0)
        _ck_sum = float(_ck_r[1] or 0)
        _kg_con.close()
        _bugun_toplam = _bk_sum + _ck_sum
        _bugun_islem = _bk_cnt + _ck_cnt
        kpi['bugun_muhasebe'] = {
            'tutar': _bugun_toplam, 'kalem': _bugun_islem,
            'banka_cnt': _bk_cnt, 'banka_sum': _bk_sum, 'banka_tutar': _bk_sum,
            'cek_cnt': _ck_cnt, 'cek_sum': _ck_sum, 'cek_tutar': _ck_sum,
            'para_birimi': 'TRY', 'has_data': _bugun_islem > 0,
            'source': 'Banka_Kay.insDT + Cek_Har.insDT',
            'semantic': 'Bugün Korgün\'e girilen banka/çek hareketleri (insDT = bugün)',
        }
    except Exception:
        kpi['bugun_muhasebe'] = {
            'tutar': 0, 'kalem': 0, 'banka_cnt': 0, 'cek_cnt': 0,
            'para_birimi': 'TRY', 'has_data': False,
            'source': 'Korgün', 'semantic': 'Hesaplanamadı',
        }

    table_rows: List[Dict[str, Any]] = []
    cari_rows: List[Dict[str, Any]] = []
    cari_rows_full: List[Dict[str, Any]] = []
    kpi_filtered: Dict[str, Any] = {'active': False}
    soz_rows: List[Dict[str, Any]] = []
    arama_rows: List[Dict[str, Any]] = []
    tab_empty: Optional[Dict[str, Any]] = None
    layer2: Optional[Dict[str, Any]] = None
    vade_term_universe_count = 0

    soz_map, iletisim_map = get_cari_parity_maps(locations)

    # P1.3 FAZ4 — batch enrichment maps (contact + active promise + Korgün vade)
    _enrich_ckods = [b.cari_kod for b in supplier_master]
    contact_map, promise_map, term_map = fetch_enrichment_maps(locations, _enrich_ckods)

    # P3A.5: aktif takip map — tek query, N+1 yok
    takip_map = fetch_aktif_takip_map(locations)

    # P3A.10: cari_view UI filtresi (master dataset aynı, yeni kg_fn yok)
    if cari_view not in ('daily', 'active', 'zero'):
        cari_view = 'daily'

    if tab == 'yukumlulukler':
        table_rows = _build_yukumluluk_rows(debt_balances)
    elif tab == 'cariler':
        layer2 = fetch_layer2_maps(locations=locations, force_refresh=force_refresh)
        cari_rows_all = build_karar_cari_rows(
            supplier_master,
            promise_map=promise_map,
            contact_map=contact_map,
            term_map=term_map,
            takip_map=takip_map,
            cari_view=cari_view,
            layer2=layer2,
            today=today,
        )
        cari_rows_filtered = _apply_cari_row_filters(cari_rows_all, filters, today)
        cari_rows, total_kayit, page, total_pages = _paginate_cari_rows(
            cari_rows_filtered, page, page_size,
        )
        cari_rows_unfiltered_total = len(cari_rows_all)
        vade_term_universe_count = sum(1 for r in cari_rows_all if r.get('vade_has_term'))
        cari_rows_full = cari_rows_filtered
        kpi_filtered = (
            _build_filtered_kpi(cari_rows_filtered)
            if _filters_active(filters) else {'active': False}
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
        total_pages = 1
        cari_rows_unfiltered_total = 0
    elif tab == 'cariler':
        pass  # total_kayit, page, total_pages set above
    elif tab == 'odeme_sozleri':
        total_kayit = len(soz_rows)
        total_pages = 1
        cari_rows_unfiltered_total = 0
    elif tab == 'arama':
        total_kayit = len(arama_rows)
        total_pages = 1
        cari_rows_unfiltered_total = 0
    else:
        total_kayit = 0
        total_pages = 1
        cari_rows_unfiltered_total = 0

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
        'kpi_filtered': kpi_filtered,
        'table_rows': table_rows,
        'cari_rows': cari_rows,
        'cari_rows_full': cari_rows_full if tab == 'cariler' else [],
        'vade_term_universe_count': vade_term_universe_count if tab == 'cariler' else 0,
        'soz_rows': soz_rows,
        'arama_rows': arama_rows,
        'tab_empty': tab_empty,
        'total_kayit': total_kayit,
        'total_kalan_by_pb': currency_totals,
        'korgun_readonly': True,
        'hata': None,
        'karar_layer2_ms': (layer2 or {}).get('elapsed_ms'),
        'karar_query_count': (layer2 or {}).get('query_count'),
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_count': total_kayit,
            'cari_unfiltered_total': cari_rows_unfiltered_total if tab == 'cariler' else 0,
        },
        'cari_filters': filters,
        'perf': {
            'kg_fn_scan_count': 1,
            'layer2_locations': (layer2 or {}).get('queried_locations', []),
            'html_row_count': len(cari_rows) if tab == 'cariler' else len(table_rows),
        },
    }


def odeme_plani_sayfa_verisi_safe(
    location_filter: Optional[str] = None,
    active_tab: Optional[str] = None,
    aktif_takip_filter: Optional[bool] = None,
    cari_view: CariViewMode = 'daily',
    page: int = 1,
    page_size: int = 10,
    cari_filters: Optional[Dict[str, str]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Fail-safe wrapper."""
    try:
        return odeme_plani_sayfa_verisi(
            location_filter=location_filter,
            active_tab=active_tab,
            aktif_takip_filter=aktif_takip_filter,
            cari_view=cari_view,
            page=page,
            page_size=page_size,
            cari_filters=cari_filters,
            force_refresh=force_refresh,
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
            'pagination': {'page': 1, 'page_size': 10, 'total_pages': 1, 'total_count': 0, 'cari_unfiltered_total': 0},
            'cari_filters': _parse_cari_filters(None),
            'perf': {'kg_fn_scan_count': 0, 'layer2_locations': [], 'html_row_count': 0},
        }

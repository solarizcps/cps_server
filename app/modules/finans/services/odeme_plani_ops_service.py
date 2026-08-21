# -*- coding: utf-8 -*-
"""Ödeme Planı P3A — operasyon service (validation + audit + format)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules import audit

try:
    from modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_LOCATIONS,
        KorgunFinanceAdapter,
        _canonical_key,
    )
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_LOCATIONS,
        KorgunFinanceAdapter,
        _canonical_key,
    )

try:
    from modules.finans.services import odeme_plani_ops_repo as repo
except ImportError:
    from app.modules.finans.services import odeme_plani_ops_repo as repo

SOZ_STATUS_LABELS = {
    'ACIK': 'Açık',
    'GERCEKLESTI': 'Gerçekleşti',
    'ERTELENDI': 'Ertelendi',
    'IPTAL': 'İptal',
}

_AUDIT_MODUL = 'finans'
_AUDIT_ALT = 'odeme_plani'


class OdemePlaniOpsError(Exception):
    def __init__(self, message: str, code: str = 'VALIDATION'):
        super().__init__(message)
        self.code = code


def _parse_date(raw: Optional[str], field_name: str) -> str:
    if not raw or not str(raw).strip():
        raise OdemePlaniOpsError(f'{field_name} zorunlu.', 'REQUIRED')
    s = str(raw).strip()[:10]
    try:
        datetime.strptime(s, '%Y-%m-%d')
    except ValueError as exc:
        raise OdemePlaniOpsError(f'{field_name} geçersiz tarih.', 'INVALID_DATE') from exc
    return s


def _parse_amount(raw: Any, required: bool = True) -> Optional[float]:
    if raw is None or raw == '':
        if required:
            raise OdemePlaniOpsError('Tutar zorunlu.', 'REQUIRED')
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError) as exc:
        raise OdemePlaniOpsError('Tutar geçersiz.', 'INVALID_AMOUNT') from exc
    if val <= 0:
        raise OdemePlaniOpsError('Tutar 0\'dan büyük olmalı.', 'INVALID_AMOUNT')
    return val


def _parse_currency(raw: Optional[str], required: bool = True) -> Optional[str]:
    if not raw or not str(raw).strip():
        if required:
            return 'TRY'
        return None
    cur = str(raw).strip().upper()
    if cur not in repo.CURRENCIES:
        raise OdemePlaniOpsError('Para birimi geçersiz.', 'INVALID_CURRENCY')
    return cur


def validate_location(location: Optional[str]) -> str:
    loc = (location or '').strip().upper()
    if loc not in CANONICAL_LOCATION_CODES:
        raise OdemePlaniOpsError('Geçersiz şirket (location).', 'INVALID_LOCATION')
    return loc


def validate_cari_kod(cari_kod: Optional[str]) -> str:
    ck = (cari_kod or '').strip()
    if not ck:
        raise OdemePlaniOpsError('Cari kod zorunlu.', 'REQUIRED')
    return ck


def validate_supplier_canonical(location: str, cari_kod: str) -> Tuple[str, str]:
    """Korgün'de Location+CKod tedarikçi doğrulama — READ-ONLY."""
    loc = validate_location(location)
    ck = validate_cari_kod(cari_kod)
    adapter = KorgunFinanceAdapter()
    if not adapter.supplier_canonical_exists(loc, ck):
        raise OdemePlaniOpsError(
            f'Tedarikçi bulunamadı: {loc}|{ck}',
            'INVALID_CARI',
        )
    info = adapter.get_supplier_info(loc, ck)
    adi = (info or {}).get('cari_adi') or ck
    return loc, adi


def _fmt_money(amount: float, currency: str) -> str:
    sym = {'TRY': '₺', 'USD': '$', 'EUR': '€'}.get(currency, currency + ' ')
    txt = f'{amount:,.0f}'.replace(',', '.')
    return f'{sym}{txt}'


def _fmt_date_tr(iso_date: str) -> str:
    try:
        d = datetime.strptime(iso_date[:10], '%Y-%m-%d')
        return d.strftime('%d.%m.%Y')
    except ValueError:
        return iso_date


def format_son_odeme_sozu(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return '—'
    return f"{_fmt_date_tr(row['promise_date'])} · {_fmt_money(float(row['amount']), row['currency'])}"


def format_son_gorusme(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return '—'
    note = (row.get('note') or '').strip()
    label = note if note else 'Ödeme sordu'
    if len(label) > 40:
        label = label[:37] + '...'
    return f"{_fmt_date_tr(row['contact_at'])} · {label}"


def build_soz_list_rows(
    locations: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    rows = repo.list_sozleri(locations)
    out: List[Dict[str, Any]] = []
    for r in rows:
        loc = r['location']
        out.append({
            'id': r['Id'],
            'location': loc,
            'location_label': COMPANY_LOCATIONS.get(loc, {}).get('label', loc),
            'cari_kod': r['cari_kod'],
            'cari_adi': r['cari_adi_snapshot'],
            'promise_date': r['promise_date'],
            'promise_date_label': _fmt_date_tr(r['promise_date']),
            'amount': float(r['amount']),
            'amount_label': _fmt_money(float(r['amount']), r['currency']),
            'currency': r['currency'],
            'status': r['status'],
            'status_label': SOZ_STATUS_LABELS.get(r['status'], r['status']),
            'note': r.get('note') or '—',
            'created_by': r.get('created_by_name') or r.get('created_by') or '—',
            'canonical_key': _canonical_key(loc, r['cari_kod']),
        })
    return out


def build_iletisim_list_rows(
    locations: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    rows = repo.list_iletisimler(locations)
    out: List[Dict[str, Any]] = []
    for r in rows:
        loc = r['location']
        amt_label = '—'
        if r.get('requested_amount'):
            cur = r.get('currency') or 'TRY'
            amt_label = _fmt_money(float(r['requested_amount']), cur)
        out.append({
            'id': r['Id'],
            'contact_at': r['contact_at'],
            'contact_at_label': _fmt_date_tr(r['contact_at']),
            'location': loc,
            'location_label': COMPANY_LOCATIONS.get(loc, {}).get('label', loc),
            'cari_kod': r['cari_kod'],
            'cari_adi': r['cari_adi_snapshot'],
            'contact_person': r.get('contact_person') or '—',
            'amount_label': amt_label,
            'note': r.get('note') or '—',
            'callback_date': r.get('callback_date') or '—',
            'callback_date_label': (
                _fmt_date_tr(r['callback_date']) if r.get('callback_date') else '—'
            ),
            'created_by': r.get('created_by_name') or r.get('created_by') or '—',
            'canonical_key': _canonical_key(loc, r['cari_kod']),
        })
    return out


def get_cari_parity_maps(
    locations: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Backward-compat — FAZ4: active promise + last contact."""
    try:
        from modules.finans.services.odeme_plani_enrichment_service import (
            fetch_active_promise_map,
            fetch_last_contact_map,
        )
    except ImportError:
        from app.modules.finans.services.odeme_plani_enrichment_service import (
            fetch_active_promise_map,
            fetch_last_contact_map,
        )
    return (
        fetch_active_promise_map(locations),
        fetch_last_contact_map(locations),
    )


def create_soz(
    payload: Dict[str, Any],
    kullanici_adi: str,
) -> Dict[str, Any]:
    loc, cari_adi = validate_supplier_canonical(
        payload.get('location'), payload.get('cari_kod'),
    )
    if payload.get('cari_adi_snapshot'):
        cari_adi = str(payload['cari_adi_snapshot']).strip() or cari_adi
    promise_date = _parse_date(payload.get('promise_date'), 'Söz tarihi')
    amount = _parse_amount(payload.get('amount'), required=True)
    currency = _parse_currency(payload.get('currency'), required=True)
    note = (payload.get('note') or '').strip() or None

    soz_id = repo.insert_soz(
        location=loc,
        cari_kod=payload.get('cari_kod').strip(),
        cari_adi_snapshot=cari_adi,
        promise_date=promise_date,
        amount=amount,
        currency=currency or 'TRY',
        note=note,
        created_by=kullanici_adi,
    )
    audit.log_ekle(
        kullanici_adi, repo.SOZ_TABLO, soz_id,
        aciklama=f'{loc}|{payload.get("cari_kod")} · {promise_date} · {amount} {currency}',
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT,
    )
    return {'ok': True, 'id': soz_id}


def update_soz_status(
    soz_id: int,
    new_status: str,
    kullanici_adi: str,
) -> Dict[str, Any]:
    status = (new_status or '').strip().upper()
    if status not in repo.SOZ_STATUSES:
        raise OdemePlaniOpsError('Geçersiz durum.', 'INVALID_STATUS')
    eski = repo.get_soz(soz_id)
    if not eski:
        raise OdemePlaniOpsError('Kayıt bulunamadı.', 'NOT_FOUND')
    if eski['status'] == status:
        return {'ok': True, 'id': soz_id, 'status': status}
    repo.update_soz_status(soz_id, status, kullanici_adi)
    audit.log(
        kullanici_adi, 'DURUM', repo.SOZ_TABLO, soz_id,
        alan='status', eski=eski['status'], yeni=status,
        aciklama=f"{eski['location']}|{eski['cari_kod']} · {eski['status']} → {status}",
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT,
    )
    return {'ok': True, 'id': soz_id, 'status': status}


def create_iletisim(
    payload: Dict[str, Any],
    kullanici_adi: str,
) -> Dict[str, Any]:
    loc, cari_adi = validate_supplier_canonical(
        payload.get('location'), payload.get('cari_kod'),
    )
    if payload.get('cari_adi_snapshot'):
        cari_adi = str(payload['cari_adi_snapshot']).strip() or cari_adi
    contact_at = _parse_date(payload.get('contact_at'), 'İletişim tarihi')
    requested_amount = _parse_amount(payload.get('requested_amount'), required=False)
    currency = _parse_currency(payload.get('currency'), required=requested_amount is not None)
    callback_date_raw = payload.get('callback_date')
    callback_date = None
    if callback_date_raw and str(callback_date_raw).strip():
        callback_date = _parse_date(callback_date_raw, 'Tekrar ara')

    rec_id = repo.insert_iletisim(
        location=loc,
        cari_kod=payload.get('cari_kod').strip(),
        cari_adi_snapshot=cari_adi,
        contact_at=contact_at,
        contact_person=(payload.get('contact_person') or '').strip() or None,
        phone=(payload.get('phone') or '').strip() or None,
        requested_amount=requested_amount,
        currency=currency,
        note=(payload.get('note') or '').strip() or None,
        callback_date=callback_date,
        created_by=kullanici_adi,
    )
    audit.log_ekle(
        kullanici_adi, repo.ILETISIM_TABLO, rec_id,
        aciklama=f'{loc}|{payload.get("cari_kod")} · {contact_at}',
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT,
    )
    return {'ok': True, 'id': rec_id}

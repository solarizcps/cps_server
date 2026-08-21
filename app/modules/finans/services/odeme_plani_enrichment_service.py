# -*- coding: utf-8 -*-
"""
P1.3 FAZ4 — Ödeme Planı enrichment (READ-ONLY).

Son Temas  → CPS finans_odeme_plani_iletisim
Ödeme Sözü → CPS finans_odeme_plani_sozu (active selection)
Anlaşma/Vade → Korgün Cari_Kart.OdemeVade

Identity: location|cari_kod (canonical_key)
Batch maps — N+1 YASAK.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from modules.finans.services import odeme_plani_ops_repo as repo
except ImportError:
    from app.modules.finans.services import odeme_plani_ops_repo as repo

try:
    from modules.finans.services.korgun_finance_adapter import _baglan as _kg_baglan
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import _baglan as _kg_baglan

# Aktif ödeme sözü — IPTAL ve GERCEKLESTI hariç
_ACTIVE_SOZ_STATUSES = frozenset({'ACIK', 'ERTELENDI'})
_TERMINAL_SOZ_STATUSES = frozenset({'IPTAL', 'GERCEKLESTI'})


def _canonical_key(location: str, cari_kod: str) -> str:
    return f"{location}|{cari_kod}"


def _parse_iso(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        return datetime.strptime(str(d)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _fmt_date_tr(iso_date: str) -> str:
    try:
        return datetime.strptime(iso_date[:10], '%Y-%m-%d').strftime('%d.%m.%Y')
    except ValueError:
        return iso_date


def _fmt_money(amount: float, currency: str) -> str:
    sym = {'TRY': '₺', 'USD': '$', 'EUR': '€'}.get(currency, currency + ' ')
    return f"{sym}{amount:,.0f}".replace(',', '.')


def _relative_days_label(target: date, today: date, *, future_label: str, past_label: str) -> str:
    diff = (target - today).days
    if diff == 0:
        return 'Bugün'
    if diff > 0:
        return f'{diff} gün {future_label}'
    return f'{abs(diff)} gün {past_label}'


def select_active_promise(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """En ilgili aktif ödeme sözü — PROMISE-01."""
    active = [r for r in rows if (r.get('status') or '') not in _TERMINAL_SOZ_STATUSES]
    if not active:
        return None
    today_s = str(date.today())
    future = [r for r in active if (r.get('promise_date') or '') >= today_s]
    if future:
        return min(future, key=lambda r: r.get('promise_date') or '9999')
    overdue = [r for r in active if (r.get('promise_date') or '') < today_s]
    if overdue:
        return max(overdue, key=lambda r: r.get('promise_date') or '')
    return active[0]


def fetch_active_promise_map(
    locations: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """canonical_key → seçilmiş aktif söz kaydı (ham row)."""
    rows = repo.list_sozleri(locations)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        key = _canonical_key(r['location'], r['cari_kod'])
        grouped.setdefault(key, []).append(r)
    return {
        key: chosen for key, grp in grouped.items()
        if (chosen := select_active_promise(grp)) is not None
    }


def fetch_last_contact_map(
    locations: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """canonical_key → son iletişim (finans_odeme_plani_iletisim)."""
    return repo.latest_iletisim_by_canonical(locations)


def fetch_supplier_term_map(
    cari_kods: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """
    cari_kod → {vade_gun, odeme_sekil, source}.
    Korgün Cari_Kart.OdemeVade — READ-ONLY, tek batch query.
    """
    codes = sorted({(c or '').strip() for c in cari_kods if (c or '').strip()})
    if not codes:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        con = _kg_baglan()
        cur = con.cursor()
        chunk = 400
        for i in range(0, len(codes), chunk):
            part = codes[i:i + chunk]
            ph = ','.join(['%s'] * len(part))
            cur.execute(
                f"""
                SELECT LTRIM(RTRIM(CKod)),
                       CAST(ISNULL(OdemeVade, 0) AS FLOAT),
                       LTRIM(RTRIM(ISNULL(OdemeSekil, ''))),
                       CAST(ISNULL(HKGun, 0) AS INT)
                FROM Cari_Kart WITH (NOLOCK)
                WHERE CKod IN ({ph})
                """,
                part,
            )
            for row in cur.fetchall():
                ck = (row[0] or '').strip()
                vade = float(row[1] or 0)
                sekil = (row[2] or '').strip()
                hkgun = int(row[3] or 0)
                term_days = int(vade) if vade > 0 else (hkgun if hkgun > 0 else 0)
                out[ck] = {
                    'vade_gun': term_days if term_days > 0 else None,
                    'odeme_sekil': sekil or None,
                    'source': 'Korgün Cari_Kart',
                    'raw_odeme_vade': vade,
                    'raw_hkgun': hkgun,
                }
        con.close()
    except Exception:
        return {}
    return out


def build_contact_dto(raw: Optional[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    if not raw:
        return {
            'has_contact': False,
            'contact_at': None,
            'contact_at_label': '—',
            'relative_label': '',
            'display': '—',
            'note': None,
            'contact_person': None,
            'source': 'CPS.finans_odeme_plani_iletisim',
        }
    iso = str(raw.get('contact_at') or '')[:10]
    d = _parse_iso(iso)
    note = (raw.get('note') or '').strip() or 'Ödeme sordu'
    rel = _relative_days_label(d, today, future_label='içinde', past_label='önce') if d else ''
    person = (raw.get('contact_person') or '').strip() or None
    display = f"{_fmt_date_tr(iso)}\n{rel}" if d else '—'
    if person:
        display = f"{_fmt_date_tr(iso)}\n{person}\n{rel}" if d else display
    return {
        'has_contact': bool(d),
        'contact_at': iso if d else None,
        'contact_at_label': _fmt_date_tr(iso) if d else '—',
        'relative_label': rel,
        'display': display,
        'display_short': f"{_fmt_date_tr(iso)} · {note[:30]}" if d else '—',
        'note': note,
        'contact_person': person,
        'created_by': raw.get('created_by_name') or raw.get('created_by'),
        'source': 'CPS.finans_odeme_plani_iletisim',
    }


def build_promise_dto(raw: Optional[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    if not raw or (raw.get('status') or '') in _TERMINAL_SOZ_STATUSES:
        return {
            'has_active': False,
            'promise_date': None,
            'promise_date_label': '—',
            'amount': None,
            'currency': 'TRY',
            'amount_label': '—',
            'status': None,
            'is_overdue': False,
            'relative_label': '',
            'display': 'Söz yok',
            'display_short': 'Söz yok',
            'source': 'CPS.finans_odeme_plani_sozu',
        }
    iso = str(raw.get('promise_date') or '')[:10]
    d = _parse_iso(iso)
    amount = float(raw.get('amount') or 0)
    cur = raw.get('currency') or 'TRY'
    overdue = bool(d and d < today)
    if d:
        rel = _relative_days_label(
            d, today,
            future_label='kaldı',
            past_label='gecikti',
        )
    else:
        rel = ''
    amt_lbl = _fmt_money(amount, cur)
    display = f"{_fmt_date_tr(iso)}\n{amt_lbl}\n{rel}" if d else 'Söz yok'
    return {
        'has_active': True,
        'promise_date': iso if d else None,
        'promise_date_label': _fmt_date_tr(iso) if d else '—',
        'amount': amount,
        'currency': cur,
        'amount_label': amt_lbl,
        'status': raw.get('status'),
        'is_overdue': overdue,
        'relative_label': rel,
        'display': display,
        'display_short': f"{_fmt_date_tr(iso)} · {amt_lbl}" if d else 'Söz yok',
        'note': raw.get('note'),
        'source': 'CPS.finans_odeme_plani_sozu',
    }


def build_term_dto(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not raw or not raw.get('vade_gun'):
        return {
            'has_term': False,
            'vade_gun': None,
            'odeme_sekil': None,
            'display': 'Vade tanımlı değil',
            'display_short': 'Vade tanımlı değil',
            'source': None,
        }
    gun = int(raw['vade_gun'])
    sekil = raw.get('odeme_sekil')
    src = raw.get('source') or 'Korgün'
    line2 = sekil if sekil else 'Korgün cari vadesi'
    return {
        'has_term': True,
        'vade_gun': gun,
        'odeme_sekil': sekil,
        'display': f"{gun} gün\n{line2}",
        'display_short': f"{gun} gün · {src}",
        'source': src,
    }


def build_row_enrichment(
    location: str,
    cari_kod: str,
    *,
    contact_map: Optional[Dict[str, Dict[str, Any]]] = None,
    promise_map: Optional[Dict[str, Dict[str, Any]]] = None,
    term_map: Optional[Dict[str, Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Tek cari enrichment DTO — liste + popup ortak."""
    today = today or date.today()
    key = _canonical_key(location, cari_kod)
    contact = build_contact_dto((contact_map or {}).get(key), today)
    promise = build_promise_dto((promise_map or {}).get(key), today)
    term = build_term_dto((term_map or {}).get(cari_kod))
    return {
        'contact': contact,
        'promise': promise,
        'term': term,
        'son_gorusme': contact['display_short'] if contact['has_contact'] else '—',
        'son_odeme_sozu': promise['display_short'] if promise['has_active'] else '—',
        'anlasma_durumu': term['display_short'],
        'temas_tarih_iso': contact.get('contact_at'),
        'soz_has_active': promise['has_active'],
        'soz_promise_date': promise.get('promise_date'),
        'soz_is_overdue': promise.get('is_overdue', False),
        'vade_has_term': term['has_term'],
        'vade_gun': term.get('vade_gun'),
        'vade_source': term.get('source'),
    }


def fetch_row_enrichment(
    location: str,
    cari_kod: str,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Tek cari — popup/detail için 3 batch map (scoped)."""
    today = today or date.today()
    locs = [location] if location else None
    contact_map, promise_map, term_map = fetch_enrichment_maps(locs, [cari_kod])
    return build_row_enrichment(
        location, cari_kod,
        contact_map=contact_map,
        promise_map=promise_map,
        term_map=term_map,
        today=today,
    )


def fetch_enrichment_maps(
    locations: Optional[Sequence[str]],
    cari_kods: Sequence[str],
) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
]:
    """3 batch map — CONTACT + PROMISE + TERM."""
    return (
        fetch_last_contact_map(locations),
        fetch_active_promise_map(locations),
        fetch_supplier_term_map(cari_kods),
    )

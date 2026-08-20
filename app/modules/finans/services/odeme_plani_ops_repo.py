# -*- coding: utf-8 -*-
"""Ödeme Planı P3A — CPS operasyon repo (soz + iletisim)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from db import q, qexec, qone, tablo_var_mi

SOZ_TABLO = 'finans_odeme_plani_sozu'
ILETISIM_TABLO = 'finans_odeme_plani_iletisim'

SOZ_STATUSES = ('ACIK', 'GERCEKLESTI', 'ERTELENDI', 'IPTAL')
CURRENCIES = ('TRY', 'USD', 'EUR')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tables_ready() -> bool:
    return tablo_var_mi(SOZ_TABLO) and tablo_var_mi(ILETISIM_TABLO)


def list_sozleri(
    locations: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    if not _tables_ready():
        return []
    params: List[Any] = []
    where = ''
    if locations:
        ph = ','.join('?' * len(locations))
        where = f' WHERE location IN ({ph}) '
        params.extend(locations)
    return q(
        f"""
        SELECT s.*, k.AdSoyad AS created_by_name
        FROM {SOZ_TABLO} s
        LEFT JOIN sistem_kullanici k ON k.KullaniciAdi = s.created_by
        {where}
        ORDER BY s.promise_date DESC, s.Id DESC
        """,
        tuple(params),
    )


def list_iletisimler(
    locations: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    if not _tables_ready():
        return []
    params: List[Any] = []
    where = ''
    if locations:
        ph = ','.join('?' * len(locations))
        where = f' WHERE location IN ({ph}) '
        params.extend(locations)
    return q(
        f"""
        SELECT i.*, k.AdSoyad AS created_by_name
        FROM {ILETISIM_TABLO} i
        LEFT JOIN sistem_kullanici k ON k.KullaniciAdi = i.created_by
        {where}
        ORDER BY i.contact_at DESC, i.Id DESC
        """,
        tuple(params),
    )


def latest_soz_by_canonical(
    locations: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """canonical_key → en son ödeme sözü."""
    rows = list_sozleri(locations)
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['location']}|{r['cari_kod']}"
        if key not in out:
            out[key] = r
    return out


def latest_iletisim_by_canonical(
    locations: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    rows = list_iletisimler(locations)
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['location']}|{r['cari_kod']}"
        if key not in out:
            out[key] = r
    return out


def get_soz(soz_id: int) -> Optional[Dict[str, Any]]:
    if not _tables_ready():
        return None
    return qone(f'SELECT * FROM {SOZ_TABLO} WHERE Id=?', (soz_id,))


def insert_soz(
    *,
    location: str,
    cari_kod: str,
    cari_adi_snapshot: str,
    promise_date: str,
    amount: float,
    currency: str,
    note: Optional[str],
    created_by: str,
) -> int:
    now = _now()
    return int(qexec(
        f"""
        INSERT INTO {SOZ_TABLO}
            (location, cari_kod, cari_adi_snapshot, promise_date, amount, currency,
             note, status, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'ACIK', ?, ?)
        """,
        (location, cari_kod, cari_adi_snapshot, promise_date, amount, currency,
         note, created_by, now),
    ) or 0)


def update_soz_status(
    soz_id: int,
    new_status: str,
    updated_by: str,
) -> bool:
    eski = get_soz(soz_id)
    if not eski:
        return False
    qexec(
        f"""
        UPDATE {SOZ_TABLO}
        SET status=?, updated_by=?, updated_at=?
        WHERE Id=?
        """,
        (new_status, updated_by, _now(), soz_id),
    )
    return True


def insert_iletisim(
    *,
    location: str,
    cari_kod: str,
    cari_adi_snapshot: str,
    contact_at: str,
    contact_person: Optional[str],
    phone: Optional[str],
    requested_amount: Optional[float],
    currency: Optional[str],
    note: Optional[str],
    callback_date: Optional[str],
    created_by: str,
) -> int:
    now = _now()
    return int(qexec(
        f"""
        INSERT INTO {ILETISIM_TABLO}
            (location, cari_kod, cari_adi_snapshot, contact_at, contact_person, phone,
             requested_amount, currency, note, callback_date, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (location, cari_kod, cari_adi_snapshot, contact_at, contact_person, phone,
         requested_amount, currency, note, callback_date, created_by, now),
    ) or 0)

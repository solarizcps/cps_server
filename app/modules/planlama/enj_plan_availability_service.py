# -*- coding: utf-8 -*-
"""Planlama — Enjeksiyon plan rezervasyon availability (READ uretim_model_plan)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from modules.planlama.enj_kapasite_motor import (
    _check_conflicts,
    _parse_dt,
    find_first_available_start,
)


def _iso(d: datetime) -> str:
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _fmt_kisa(d: datetime | str | None) -> str:
    if not d:
        return '—'
    if isinstance(d, str):
        try:
            d = _parse_dt(d)
        except ValueError:
            return d[:16]
    return d.strftime('%d.%m %H:%M')


def _fmt_tam(d: datetime | str | None) -> str:
    if not d:
        return '—'
    if isinstance(d, str):
        try:
            d = _parse_dt(d)
        except ValueError:
            return d[:16]
    return d.strftime('%d.%m.%Y %H:%M')


def _load_side_plans(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    bas: datetime,
    bit: datetime,
) -> list[dict]:
    rows = con.execute(
        """
        SELECT DISTINCT p.id, p.sip_no, p.mamul_skod, p.renk_adi,
               p.enj_plan_baslangic, p.enj_plan_bitis
          FROM uretim_model_plan p
         WHERE p.aktif = 1
           AND p.enj_makine_id = ?
           AND UPPER(p.enj_slot) = ?
           AND p.enj_plan_baslangic IS NOT NULL
           AND p.enj_plan_bitis IS NOT NULL
           AND p.enj_plan_baslangic <= ?
           AND p.enj_plan_bitis >= ?
         ORDER BY p.enj_plan_baslangic
        """,
        (int(makine_id), slot.upper(), _iso(bit), _iso(bas)),
    ).fetchall()
    return [dict(r) for r in rows]


def _build_gaps(
    plans: list[dict],
    window_bas: datetime,
    window_bit: datetime,
) -> list[dict]:
    """Plan aralıkları arasına BOŞ segmentler ekle."""
    segments: list[dict] = []
    cur = window_bas
    for p in plans:
        try:
            pb = _parse_dt(p['enj_plan_baslangic'])
            pe = _parse_dt(p['enj_plan_bitis'])
        except ValueError:
            continue
        if pb > cur:
            segments.append({
                'tip': 'BOS',
                'bas': _iso(cur),
                'bit': _iso(pb),
                'label': 'BOŞ / PLANLANABİLİR',
            })
        segments.append({
            'tip': 'DOLU',
            'bas': p['enj_plan_baslangic'],
            'bit': p['enj_plan_bitis'],
            'sip_no': p.get('sip_no'),
            'model': p.get('mamul_skod'),
            'renk': p.get('renk_adi'),
            'plan_id': p.get('id'),
            'label': f"{p.get('sip_no')} / {p.get('mamul_skod')}",
        })
        cur = max(cur, pe)
    if cur < window_bit:
        segments.append({
            'tip': 'BOS',
            'bas': _iso(cur),
            'bit': _iso(window_bit),
            'label': 'BOŞ / PLANLANABİLİR',
        })
    return segments


def build_side_availability(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyon_sayisi: int,
    *,
    from_dt: datetime | None = None,
    days: int = 7,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
) -> dict:
    """Tek makine/taraf için plan timeline + ilk uygun."""
    anchor = (from_dt or datetime.now()).replace(second=0, microsecond=0)
    window_bit = anchor + timedelta(days=max(1, int(days)))
    plans = _load_side_plans(con, makine_id, slot, anchor, window_bit)
    timeline = _build_gaps(plans, anchor, window_bit)
    istasyonlar = list(range(1, int(istasyon_sayisi) + 1))
    ilk = find_first_available_start(
        con, int(makine_id), slot.upper(), istasyonlar,
        calisma_modu=calisma_modu,
        hafta_sonu=hafta_sonu,
        hs_vardiya=hs_vardiya,
        from_dt=anchor,
    )
    return {
        'slot': slot.upper(),
        'timeline': timeline[:8],
        'plan_sayisi': len(plans),
        'ilk_uygun': _iso(ilk),
        'ilk_uygun_gosterim': _fmt_kisa(ilk),
        'ilk_uygun_tam': _fmt_tam(ilk),
    }


def build_makine_plan_ozet(
    con: sqlite3.Connection,
    *,
    days: int = 7,
    anchor: datetime | None = None,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
) -> list[dict]:
    rows = con.execute(
        'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE aktif=1 ORDER BY sira'
    ).fetchall()
    out: list[dict] = []
    for m in rows:
        mid = int(m['id'])
        n = int(m['istasyon_sayisi'] or 8)
        sides = {}
        for slot in ('A', 'B'):
            sides[slot] = build_side_availability(
                con, mid, slot, n,
                from_dt=anchor, days=days,
                calisma_modu=calisma_modu,
                hafta_sonu=hafta_sonu,
                hs_vardiya=hs_vardiya,
            )
        out.append({
            'makine_id': mid,
            'makine_kod': m['kod'],
            'istasyon_sayisi': n,
            'A': sides['A'],
            'B': sides['B'],
        })
    return out


def build_istasyon_plan_durum(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyonlar: list[int],
    at_dt: str,
    *,
    haric_plan_id: int | None = None,
) -> list[dict]:
    """Seçilen başlangıç anında istasyon bazlı plan doluluk."""
    try:
        bas = _parse_dt(at_dt)
    except ValueError:
        return [{'istasyon_no': i, 'durum': 'BOS'} for i in istasyonlar]
    bit = bas + timedelta(minutes=1)
    out: list[dict] = []
    for ist in sorted({int(x) for x in istasyonlar}):
        conflicts = _check_conflicts(
            con, int(makine_id), slot.upper(), [ist], bas, bit,
            haric_plan_id=haric_plan_id,
        )
        if conflicts:
            c = conflicts[0]
            out.append({
                'istasyon_no': ist,
                'durum': 'PLANLI',
                'sip_no': c.get('sip_no'),
                'model': c.get('mamul_skod'),
                'renk': c.get('renk_adi'),
                'plan_id': c.get('plan_id'),
                'plan_baslangic': c.get('plan_baslangic'),
                'plan_bitis': c.get('plan_bitis'),
                'bas_gosterim': _fmt_kisa(c.get('plan_baslangic')),
                'bit_gosterim': _fmt_kisa(c.get('plan_bitis')),
            })
        else:
            out.append({'istasyon_no': ist, 'durum': 'BOS'})
    return out


def enrich_conflict_payload(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyonlar: list[int],
    conflicts: list[dict],
    *,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
    from_dt: datetime | None = None,
) -> dict[str, Any]:
    """Conflict popup için zengin payload."""
    mk = con.execute('SELECT kod FROM enj_makine WHERE id=?', (int(makine_id),)).fetchone()
    makine_kod = mk['kod'] if mk else f'M{makine_id}'
    istasyonlar = sorted({int(x) for x in istasyonlar if x is not None})
    ilk = find_first_available_start(
        con, int(makine_id), slot.upper(), istasyonlar,
        calisma_modu=calisma_modu,
        hafta_sonu=hafta_sonu,
        hs_vardiya=hs_vardiya,
        from_dt=from_dt,
    )
    c0 = conflicts[0] if conflicts else {}
    return {
        'makine_kod': makine_kod,
        'makine_id': int(makine_id),
        'slot': slot.upper(),
        'istasyon_no': c0.get('istasyon_no'),
        'cakisan_sip_no': c0.get('sip_no'),
        'cakisan_model': c0.get('mamul_skod'),
        'cakisan_renk': c0.get('renk_adi'),
        'cakisan_plan': f"{c0.get('sip_no')} / {c0.get('mamul_skod')}" if c0 else None,
        'plan_baslangic': c0.get('plan_baslangic'),
        'plan_bitis': c0.get('plan_bitis'),
        'plan_bas_gosterim': _fmt_tam(c0.get('plan_baslangic')),
        'plan_bit_gosterim': _fmt_tam(c0.get('plan_bitis')),
        'ilk_uygun': _iso(ilk),
        'ilk_uygun_gosterim': _fmt_tam(ilk),
        'conflicts': conflicts,
        'mesaj': (
            f"{makine_kod}/{slot.upper()} İST{c0.get('istasyon_no')}, "
            f"{c0.get('sip_no')} planı nedeniyle "
            f"{_fmt_kisa(c0.get('plan_baslangic'))}–{_fmt_kisa(c0.get('plan_bitis'))} arasında dolu. "
            f"İlk uygun: {_fmt_tam(ilk)}."
        ) if c0 else None,
    }

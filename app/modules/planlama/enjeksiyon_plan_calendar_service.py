# -*- coding: utf-8 -*-
"""Planlama — Enjeksiyon plan takvimi READ service (uretim_model_plan.enj_*)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from modules.planlama.enj_kapasite_motor import HAFTA_SONU_KURAL, _parse_dt


TR_GUN = ('PZT', 'SAL', 'ÇAR', 'PER', 'CUM', 'CMT', 'PAZ')
TR_AY = (
    '', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
)


def _dt(val: str | datetime | None) -> datetime | None:
    if not val:
        return None
    try:
        return _parse_dt(val)
    except ValueError:
        return None


def _iso(d: datetime) -> str:
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _iso_date(d: datetime) -> str:
    return d.strftime('%Y-%m-%d')


def _week_start(d: datetime) -> datetime:
    wd = d.weekday()
    return datetime(d.year, d.month, d.day, 0, 0) - timedelta(days=wd)


def _week_label(bas: datetime, bit: datetime) -> str:
    if bas.month == bit.month:
        return f'{bas.day}–{bit.day} {TR_AY[bas.month]} {bas.year}'
    return f'{bas.day} {TR_AY[bas.month]} – {bit.day} {TR_AY[bit.month]} {bit.year}'


def _month_label(d: datetime) -> str:
    return f'{TR_AY[d.month]} {d.year}'


def _plan_select_cols(con: sqlite3.Connection) -> str:
    base = """
        id, sip_no, mamul_skod, renk_adi, miktar,
        enj_makine_id, enj_istasyon_no, enj_slot, enj_kalip_id, enj_kalip_kod,
        enj_aktif_goz, enj_kalip_basi_cift, enj_tur_cift,
        enj_plan_baslangic, enj_plan_bitis, enj_planlanacak_cift
    """
    existing = {r[1] for r in con.execute('PRAGMA table_info(uretim_model_plan)').fetchall()}
    extras = [c for c in (
        'enj_calisma_modu', 'enj_hafta_sonu_calisma', 'enj_kapasite_snapshot',
    ) if c in existing]
    if not extras:
        return base
    return base.replace('enj_planlanacak_cift', 'enj_planlanacak_cift, ' + ', '.join(extras))


def _child_select_sql(con: sqlite3.Connection) -> str:
    existing = {r[1] for r in con.execute('PRAGMA table_info(uretim_model_plan)').fetchall()}
    parts = [
        'p.id', 'p.sip_no', 'p.mamul_skod', 'p.renk_adi', 'p.miktar',
        'p.enj_makine_id', 'c.istasyon_no AS enj_istasyon_no', 'p.enj_slot',
        'p.enj_kalip_id', 'p.enj_kalip_kod', 'p.enj_aktif_goz', 'p.enj_kalip_basi_cift',
        'p.enj_tur_cift', 'p.enj_plan_baslangic', 'p.enj_plan_bitis', 'p.enj_planlanacak_cift',
    ]
    for col in ('enj_calisma_modu', 'enj_hafta_sonu_calisma', 'enj_kapasite_snapshot'):
        if col in existing:
            parts.append(f'p.{col}')
    return ', '.join(parts)


def _load_raw_plans(
    con: sqlite3.Connection,
    makine_id: int,
    bas: datetime,
    bit: datetime,
) -> list[dict]:
    cols = _plan_select_cols(con)
    params = (makine_id, _iso(bit), _iso(bas))
    child_exists = bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='uretim_model_plan_enj_istasyon'"
    ).fetchone())
    out: list[dict] = []

    if child_exists:
        child_sel = _child_select_sql(con)
        child_rows = con.execute(
            f"""
            SELECT {child_sel}
            FROM uretim_model_plan p
            INNER JOIN uretim_model_plan_enj_istasyon c ON c.plan_id = p.id
            WHERE p.aktif = 1
              AND p.enj_makine_id = ?
              AND p.enj_plan_baslangic IS NOT NULL
              AND p.enj_plan_bitis IS NOT NULL
              AND p.enj_plan_baslangic <= ?
              AND p.enj_plan_bitis >= ?
            ORDER BY p.enj_plan_baslangic, c.istasyon_no
            """,
            params,
        ).fetchall()
        out.extend(dict(r) for r in child_rows)

        legacy_rows = con.execute(
            f"""
            SELECT {cols}
            FROM uretim_model_plan
            WHERE aktif = 1
              AND enj_makine_id = ?
              AND enj_istasyon_no IS NOT NULL
              AND enj_plan_baslangic IS NOT NULL
              AND enj_plan_bitis IS NOT NULL
              AND enj_plan_baslangic <= ?
              AND enj_plan_bitis >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM uretim_model_plan_enj_istasyon c
                   WHERE c.plan_id = uretim_model_plan.id
              )
            ORDER BY enj_plan_baslangic, enj_istasyon_no
            """,
            params,
        ).fetchall()
        out.extend(dict(r) for r in legacy_rows)
        return out

    rows = con.execute(
        f"""
        SELECT {cols}
        FROM uretim_model_plan
        WHERE aktif = 1
          AND enj_makine_id = ?
          AND enj_plan_baslangic IS NOT NULL
          AND enj_plan_bitis IS NOT NULL
          AND enj_plan_baslangic <= ?
          AND enj_plan_bitis >= ?
        ORDER BY enj_plan_baslangic, enj_istasyon_no
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _confidence_label(snapshot_raw) -> str | None:
    if not snapshot_raw:
        return None
    try:
        snap = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
        c = (snap or {}).get('confidence')
        if not c:
            return None
        return {'DUSUK': 'DÜŞÜK', 'ORTA': 'ORTA', 'YUKSEK': 'YÜKSEK'}.get(str(c).upper(), str(c))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _group_plans(rows: list[dict], makine_kod: str | None = None) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (
            r.get('enj_makine_id'),
            (r.get('enj_slot') or '').upper(),
            r.get('enj_plan_baslangic'),
            r.get('enj_plan_bitis'),
            r.get('sip_no') or '',
            r.get('mamul_skod') or '',
        )
        if key not in groups:
            groups[key] = {
                'plan_ids': [],
                'siparis_no': r.get('sip_no'),
                'model': r.get('mamul_skod'),
                'renk': r.get('renk_adi'),
                'miktar': r.get('miktar'),
                'slot': (r.get('enj_slot') or '').upper(),
                'kalip': r.get('enj_kalip_kod'),
                'kalip_id': r.get('enj_kalip_id'),
                'kalip_adedi': r.get('enj_aktif_goz'),
                'kalip_basi_cift': r.get('enj_kalip_basi_cift'),
                'tur_basi_cift': r.get('enj_tur_cift'),
                'plan_baslangic': r.get('enj_plan_baslangic'),
                'plan_bitis': r.get('enj_plan_bitis'),
                'planlanan_cift': r.get('enj_planlanacak_cift'),
                'calisma_modu': r.get('enj_calisma_modu'),
                'hafta_sonu_calisma': r.get('enj_hafta_sonu_calisma'),
                'confidence': _confidence_label(r.get('enj_kapasite_snapshot')),
                'makine_kod': makine_kod,
                'istasyonlar': [],
            }
        g = groups[key]
        g['plan_ids'].append(r['id'])
        ist = int(r.get('enj_istasyon_no') or 0)
        if ist and ist not in g['istasyonlar']:
            g['istasyonlar'].append(ist)
    out = []
    for g in groups.values():
        g['istasyonlar'] = sorted(g['istasyonlar'])
        g['plan_id'] = g['plan_ids'][0]
        g['group_key'] = '|'.join(str(x) for x in (
            g['slot'], g['plan_baslangic'], g['plan_bitis'], g['siparis_no'],
        ))
        out.append(g)
    return sorted(out, key=lambda x: x.get('plan_baslangic') or '')


def _weekend_disabled_zones(
    bas: datetime,
    bit: datetime,
    hafta_sonu: str = 'HAYIR',
) -> list[dict]:
    """Kural A: Cuma gece Cmt07 devam; Cmt07+ ve Pazar calisma yok."""
    zones: list[dict] = []
    if hafta_sonu == 'EVET':
        return zones
    cur = _week_start(bas)
    end = bit + timedelta(days=1)
    while cur < end:
        wd = cur.weekday()
        if wd == 5:
            z_bas = datetime(cur.year, cur.month, cur.day, 7, 0)
            z_bit = datetime(cur.year, cur.month, cur.day, 23, 59, 59) + timedelta(seconds=1)
            if wd == 5:
                z_bit = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
            zones.append({
                'bas': _iso(z_bas),
                'bit': _iso(z_bit),
                'tip': 'CALISMA_YOK',
                'label': 'ÇALIŞMA YOK',
            })
        elif wd == 6:
            z_bas = datetime(cur.year, cur.month, cur.day, 0, 0)
            z_bit = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
            zones.append({
                'bas': _iso(z_bas),
                'bit': _iso(z_bit),
                'tip': 'CALISMA_YOK',
                'label': 'ÇALIŞMA YOK',
            })
        cur += timedelta(days=1)
    return zones


def _pct_in_range(t: datetime, win_bas: datetime, win_bit: datetime) -> float:
    total = (win_bit - win_bas).total_seconds()
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (t - win_bas).total_seconds() / total * 100))


def _block_position(plan_bas: datetime, plan_bit: datetime, win_bas: datetime, win_bit: datetime) -> dict:
    left = _pct_in_range(max(plan_bas, win_bas), win_bas, win_bit)
    right = _pct_in_range(min(plan_bit, win_bit), win_bas, win_bit)
    width = max(0.5, right - left)
    return {'left_pct': round(left, 3), 'width_pct': round(width, 3)}


def _attach_live_forecast(con: sqlite3.Connection, plan: dict, include_live: bool) -> None:
    plan['guncel_tahmini_bitis'] = None
    plan['sapma_durum'] = None
    plan['sapma_gosterim'] = None
    plan['gercek_bitis'] = None
    if not include_live:
        return
    try:
        from modules.planlama.enj_canli_tahmin_motor import hesapla_canli_tahmin
        mk = con.execute(
            'SELECT kod FROM enj_makine WHERE id=?', (plan.get('_makine_id'),),
        ).fetchone()
        if not mk:
            return
        r = hesapla_canli_tahmin(con, {
            'makine_kod': mk['kod'],
            'slot': plan['slot'],
            'taraf': plan['slot'],
            'kalip_adedi': plan.get('kalip_adedi'),
            'kalip_basi_cift': plan.get('kalip_basi_cift'),
            'tur_basi_cift': plan.get('tur_basi_cift'),
            'planlanan_toplam_cift': plan.get('planlanan_cift') or 960,
            'plan_tur_toplam': 120,
            'plan_tur_referansi': 60,
            'plan_baslangic': plan['plan_baslangic'],
            'original_plan_bitis': plan['plan_bitis'],
            'calisma_modu': 'GUNDUZ',
            'hafta_sonu_calisma': 'HAYIR',
            'pilot_scope': {'allow_empty_gercek': True},
        })
        if r.get('ok'):
            plan['guncel_tahmini_bitis'] = r.get('guncel_tahmini_bitis')
            plan['sapma_durum'] = r.get('sapma_durum')
            plan['sapma_gosterim'] = r.get('sapma_gosterim')
            plan['gercek_bitis'] = r.get('gercek_bitis')
            if r.get('guncel_tahmini_bitis'):
                pb = _dt(plan['plan_bitis'])
                gb = _dt(r['guncel_tahmini_bitis'])
                if pb and gb:
                    plan['marker_pct'] = _pct_in_range(
                        gb, _dt(plan['plan_baslangic']) or pb, pb,
                    )
    except Exception:
        pass


def _build_rows(istasyon_sayisi: int, view: str) -> list[dict]:
    rows: list[dict] = []
    if view == '3_ay':
        for slot in ('A', 'B'):
            rows.append({
                'key': f'SIDE-{slot}',
                'label': f'{slot} TARAFI',
                'istasyon_no': None,
                'slot': slot,
                'side_only': True,
            })
        return rows
    for n in range(1, istasyon_sayisi + 1):
        for slot in ('A', 'B'):
            rows.append({
                'key': f'{n}-{slot}',
                'label': f'İST{n} {slot}',
                'istasyon_no': n,
                'slot': slot,
                'side_only': False,
            })
    return rows


def _day_columns(bas: datetime, bit: datetime) -> list[dict]:
    cols: list[dict] = []
    cur = datetime(bas.year, bas.month, bas.day)
    while cur <= bit:
        cols.append({
            'key': _iso_date(cur),
            'label': TR_GUN[cur.weekday()],
            'alt': str(cur.day),
            'date': _iso_date(cur),
        })
        cur += timedelta(days=1)
    return cols


def _week_columns(bas: datetime) -> list[dict]:
    cols: list[dict] = []
    for i in range(7):
        d = bas + timedelta(days=i)
        cols.append({
            'key': _iso_date(d),
            'label': TR_GUN[d.weekday()],
            'alt': str(d.day),
            'date': _iso_date(d),
            'segments': [
                {'key': 'gunduz', 'label': 'G', 'bas_saat': 7, 'bit_saat': 17},
                {'key': 'gece', 'label': 'G', 'bas_saat': 17, 'bit_saat': 7},
            ],
        })
    return cols


def _month_week_columns(year: int, month: int) -> list[dict]:
    first = datetime(year, month, 1)
    if month == 12:
        last = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = datetime(year, month + 1, 1) - timedelta(days=1)
    cols: list[dict] = []
    cur = first
    while cur <= last:
        cols.append({
            'key': _iso_date(cur),
            'label': str(cur.day),
            'date': _iso_date(cur),
            'weekday': TR_GUN[cur.weekday()],
        })
        cur += timedelta(days=1)
    return cols


def _iso_week_num(d: datetime) -> int:
    return d.isocalendar()[1]


def _3month_week_columns(bas: datetime) -> list[dict]:
    cols: list[dict] = []
    cur = _week_start(bas)
    end = bas + timedelta(days=90)
    seen: set[int] = set()
    while cur < end:
        wn = _iso_week_num(cur)
        if wn not in seen:
            seen.add(wn)
            cols.append({
                'key': f'W{wn}',
                'label': f'{wn}. HAFTA',
                'week': wn,
                'bas': _iso_date(cur),
            })
        cur += timedelta(days=7)
    return cols


def build_calendar(
    con: sqlite3.Connection,
    makine_kod: str,
    view: str = 'bu_hafta',
    anchor: str | None = None,
    include_live: bool = False,
) -> dict:
    mk = con.execute(
        'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE kod=? AND aktif=1',
        (makine_kod,),
    ).fetchone()
    if not mk:
        return {'ok': False, 'hata': 'Makine bulunamadi'}

    makine_id = int(mk['id'])
    ist = int(mk['istasyon_sayisi'])
    now = datetime.now().replace(second=0, microsecond=0)
    try:
        anchor_dt = _parse_dt(anchor) if anchor else now
    except ValueError:
        anchor_dt = now

    if view == 'bu_hafta':
        win_bas = _week_start(anchor_dt)
        win_bit = win_bas + timedelta(days=6, hours=23, minutes=59)
        columns = _week_columns(win_bas)
        period_label = _week_label(win_bas, win_bas + timedelta(days=6))
        nav_prev = _iso_date(win_bas - timedelta(days=7))
        nav_next = _iso_date(win_bas + timedelta(days=7))
    elif view == 'bu_ay':
        win_bas = datetime(anchor_dt.year, anchor_dt.month, 1)
        if anchor_dt.month == 12:
            win_bit = datetime(anchor_dt.year + 1, 1, 1) - timedelta(seconds=1)
        else:
            win_bit = datetime(anchor_dt.year, anchor_dt.month + 1, 1) - timedelta(seconds=1)
        columns = _month_week_columns(win_bas.year, win_bas.month)
        period_label = _month_label(win_bas)
        if win_bas.month == 1:
            nav_prev = _iso_date(datetime(win_bas.year - 1, 12, 1))
        else:
            nav_prev = _iso_date(datetime(win_bas.year, win_bas.month - 1, 1))
        if win_bas.month == 12:
            nav_next = _iso_date(datetime(win_bas.year + 1, 1, 1))
        else:
            nav_next = _iso_date(datetime(win_bas.year, win_bas.month + 1, 1))
    elif view == '3_ay':
        win_bas = datetime(anchor_dt.year, anchor_dt.month, 1)
        win_bit = win_bas + timedelta(days=89, hours=23, minutes=59)
        columns = _3month_week_columns(win_bas)
        period_label = f'{TR_AY[win_bas.month]}–{TR_AY[min(12, win_bas.month + 2)]} {win_bas.year}'
        nav_prev = _iso_date(win_bas - timedelta(days=90))
        nav_next = _iso_date(win_bas + timedelta(days=90))
    else:
        return {'ok': False, 'hata': 'Gecersiz view'}

    raw = _load_raw_plans(con, makine_id, win_bas, win_bit)
    plans = _group_plans(raw, makine_kod=makine_kod)
    for p in plans:
        p['_makine_id'] = makine_id
        pb = _dt(p['plan_baslangic'])
        pe = _dt(p['plan_bitis'])
        if pb and pe:
            p['block'] = _block_position(pb, pe, win_bas, win_bit + timedelta(hours=1))
        _attach_live_forecast(con, p, include_live)

    disabled = _weekend_disabled_zones(win_bas, win_bit)
    disabled_pct = []
    for z in disabled:
        zb = _dt(z['bas'])
        ze = _dt(z['bit'])
        if zb and ze:
            disabled_pct.append({
                **z,
                **_block_position(zb, ze, win_bas, win_bit + timedelta(hours=1)),
            })

    rows = _build_rows(ist, view)
    row_blocks: dict[str, list] = {r['key']: [] for r in rows}

    for plan in plans:
        slot = plan['slot']
        istasyonlar = plan.get('istasyonlar') or []
        pb = _dt(plan['plan_baslangic'])
        pe = _dt(plan['plan_bitis'])
        if not pb or not pe:
            continue
        block = plan.get('block') or _block_position(pb, pe, win_bas, win_bit + timedelta(hours=1))
        live_pct = None
        if plan.get('guncel_tahmini_bitis'):
            gb = _dt(plan['guncel_tahmini_bitis'])
            if gb:
                live_pct = _pct_in_range(gb, win_bas, win_bit + timedelta(hours=1))

        if view == '3_ay':
            key = f'SIDE-{slot}'
            if key in row_blocks:
                row_blocks[key].append({**plan, 'block': block, 'live_marker_pct': live_pct, 'continuation': True})
            continue

        for i, ist_no in enumerate(istasyonlar):
            rk = f'{ist_no}-{slot}'
            if rk not in row_blocks:
                continue
            row_blocks[rk].append({
                **plan,
                'block': block,
                'live_marker_pct': live_pct,
                'continuation': i > 0,
                'show_label': i == 0,
            })

    return {
        'ok': True,
        'view': view,
        'makine_kod': makine_kod,
        'makine_id': makine_id,
        'istasyon_sayisi': ist,
        'hafta_sonu_kural': HAFTA_SONU_KURAL,
        'period': {
            'bas': _iso(win_bas),
            'bit': _iso(win_bit),
            'label': period_label,
            'nav_prev': nav_prev,
            'nav_next': nav_next,
            'anchor': _iso_date(anchor_dt),
        },
        'columns': columns,
        'rows': rows,
        'row_blocks': row_blocks,
        'disabled_zones': disabled_pct,
        'plans': plans,
        'plan_count': len(plans),
        'empty': len(plans) == 0,
        'empty_message': 'Bu dönemde yayınlanmış enjeksiyon planı yok.',
    }

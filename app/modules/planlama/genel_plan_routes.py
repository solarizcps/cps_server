# -*- coding: utf-8 -*-
"""Planlama > Genel Planlama — APS master UI adapter (C1-R)."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from db import get_conn
from modules.auth import yetki_gerekli
from modules.planlama.aps_enj_timeline_service import load_enj_timeline_payload

genel_plan_bp = Blueprint(
    'genel_plan_bp',
    __name__,
    url_prefix='/planlama/genel-plan',
)

_TR_AY = (
    '', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
)
_TR_GUN = ('PZT', 'SAL', 'ÇAR', 'PER', 'CUM', 'CMT', 'PAZ')


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


def _iso(d: datetime) -> str:
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _iso_date(d: datetime) -> str:
    return d.strftime('%Y-%m-%d')


def _week_start(d: datetime) -> datetime:
    wd = d.weekday()
    return datetime(d.year, d.month, d.day) - timedelta(days=wd)


def _pct(t: datetime, win_bas: datetime, win_bit: datetime) -> float:
    total = (win_bit - win_bas).total_seconds()
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (t - win_bas).total_seconds() / total * 100.0))


def _block(plan_bas: datetime, plan_bit: datetime, win_bas: datetime, win_bit: datetime) -> dict:
    left = _pct(max(plan_bas, win_bas), win_bas, win_bit)
    right = _pct(min(plan_bit, win_bit), win_bas, win_bit)
    width = max(0.3, right - left)
    return {'left_pct': round(left, 3), 'width_pct': round(width, 3)}


def _load_plans(con, makine_id: int, win_bas: datetime, win_bit: datetime) -> list[dict]:
    """Canonical planları window içinde yükle — child table öncelikli."""
    params = (makine_id, _iso(win_bit), _iso(win_bas))

    child_exists = bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='uretim_model_plan_enj_istasyon'"
    ).fetchone())

    raw: list[dict] = []

    if child_exists:
        rows = con.execute(
            """
            SELECT
                p.id, p.sip_no, p.mamul_skod, p.renk_adi, p.miktar, p.termin,
                p.enj_makine_id, p.enj_slot, p.enj_kalip_id, p.enj_kalip_kod,
                p.enj_aktif_goz, p.enj_kalip_basi_cift, p.enj_tur_cift,
                p.enj_plan_baslangic, p.enj_plan_bitis, p.enj_planlanacak_cift,
                p.enj_calisma_modu,
                c.istasyon_no
            FROM uretim_model_plan p
            INNER JOIN uretim_model_plan_enj_istasyon c ON c.plan_id = p.id
            WHERE p.aktif = 1
              AND p.enj_makine_id = ?
              AND p.enj_plan_baslangic IS NOT NULL
              AND p.enj_plan_bitis IS NOT NULL
              AND p.enj_plan_baslangic <= ?
              AND p.enj_plan_bitis   >= ?
            ORDER BY p.enj_plan_baslangic, c.istasyon_no
            """,
            params,
        ).fetchall()
        for r in rows:
            raw.append(dict(r))

        # Legacy plans (no child rows)
        legacy = con.execute(
            """
            SELECT
                p.id, p.sip_no, p.mamul_skod, p.renk_adi, p.miktar, p.termin,
                p.enj_makine_id, p.enj_slot, p.enj_kalip_id, p.enj_kalip_kod,
                p.enj_aktif_goz, p.enj_kalip_basi_cift, p.enj_tur_cift,
                p.enj_plan_baslangic, p.enj_plan_bitis, p.enj_planlanacak_cift,
                p.enj_calisma_modu,
                p.enj_istasyon_no AS istasyon_no
            FROM uretim_model_plan p
            WHERE p.aktif = 1
              AND p.enj_makine_id = ?
              AND p.enj_istasyon_no IS NOT NULL
              AND p.enj_plan_baslangic IS NOT NULL
              AND p.enj_plan_bitis IS NOT NULL
              AND p.enj_plan_baslangic <= ?
              AND p.enj_plan_bitis   >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM uretim_model_plan_enj_istasyon c2
                  WHERE c2.plan_id = p.id
              )
            ORDER BY p.enj_plan_baslangic, p.enj_istasyon_no
            """,
            params,
        ).fetchall()
        for r in legacy:
            raw.append(dict(r))
    else:
        rows = con.execute(
            """
            SELECT
                p.id, p.sip_no, p.mamul_skod, p.renk_adi, p.miktar, p.termin,
                p.enj_makine_id, p.enj_slot, p.enj_kalip_id, p.enj_kalip_kod,
                p.enj_aktif_goz, p.enj_kalip_basi_cift, p.enj_tur_cift,
                p.enj_plan_baslangic, p.enj_plan_bitis, p.enj_planlanacak_cift,
                p.enj_calisma_modu,
                p.enj_istasyon_no AS istasyon_no
            FROM uretim_model_plan p
            WHERE p.aktif = 1
              AND p.enj_makine_id = ?
              AND p.enj_plan_baslangic IS NOT NULL
              AND p.enj_plan_bitis IS NOT NULL
              AND p.enj_plan_baslangic <= ?
              AND p.enj_plan_bitis   >= ?
            ORDER BY p.enj_plan_baslangic
            """,
            params,
        ).fetchall()
        for r in rows:
            raw.append(dict(r))

    # Group by plan_id + slot + baslangic
    groups: dict[int, dict] = {}
    for r in raw:
        pid = r['id']
        if pid not in groups:
            groups[pid] = {
                'plan_id': pid,
                'sip_no': r['sip_no'],
                'model': r['mamul_skod'],
                'renk': r['renk_adi'],
                'miktar': r['miktar'],
                'termin': r.get('termin'),
                'makine_id': r['enj_makine_id'],
                'slot': (r['enj_slot'] or '').upper(),
                'kalip_id': r['enj_kalip_id'],
                'kalip_kod': r['enj_kalip_kod'],
                'aktif_goz': r['enj_aktif_goz'],
                'kalip_basi_cift': r['enj_kalip_basi_cift'],
                'tur_cift': r['enj_tur_cift'],
                'baslangic': r['enj_plan_baslangic'],
                'bitis': r['enj_plan_bitis'],
                'planlanacak_cift': r['enj_planlanacak_cift'],
                'calisma_modu': r.get('enj_calisma_modu'),
                'istasyonlar': [],
            }
        ist = r.get('istasyon_no')
        if ist is not None:
            ist = int(ist)
            if ist not in groups[pid]['istasyonlar']:
                groups[pid]['istasyonlar'].append(ist)

    for g in groups.values():
        g['istasyonlar'] = sorted(g['istasyonlar'])

    return sorted(groups.values(), key=lambda x: x.get('baslangic') or '')


def _window(view: str, anchor_dt: datetime) -> tuple[datetime, datetime, str, str, str]:
    """Returns (win_bas, win_bit, period_label, nav_prev, nav_next)."""
    if view == 'bu_hafta':
        win_bas = _week_start(anchor_dt)
        win_bit = win_bas + timedelta(days=6, hours=23, minutes=59)
        b = win_bas
        e = win_bas + timedelta(days=6)
        if b.month == e.month:
            lbl = f'{b.day}–{e.day} {_TR_AY[b.month]} {b.year}'
        else:
            lbl = f'{b.day} {_TR_AY[b.month]} – {e.day} {_TR_AY[e.month]} {e.year}'
        prev = _iso_date(win_bas - timedelta(days=7))
        nxt = _iso_date(win_bas + timedelta(days=7))
    elif view == 'bu_ay':
        win_bas = datetime(anchor_dt.year, anchor_dt.month, 1)
        if anchor_dt.month == 12:
            win_bit = datetime(anchor_dt.year + 1, 1, 1) - timedelta(seconds=1)
        else:
            win_bit = datetime(anchor_dt.year, anchor_dt.month + 1, 1) - timedelta(seconds=1)
        lbl = f'{_TR_AY[win_bas.month]} {win_bas.year}'
        if win_bas.month == 1:
            prev = _iso_date(datetime(win_bas.year - 1, 12, 1))
        else:
            prev = _iso_date(datetime(win_bas.year, win_bas.month - 1, 1))
        if win_bas.month == 12:
            nxt = _iso_date(datetime(win_bas.year + 1, 1, 1))
        else:
            nxt = _iso_date(datetime(win_bas.year, win_bas.month + 1, 1))
    elif view == '3_ay':
        win_bas = datetime(anchor_dt.year, anchor_dt.month, 1)
        win_bit = win_bas + timedelta(days=89, hours=23, minutes=59)
        m2 = win_bas.month + 2
        y2 = win_bas.year + (m2 - 1) // 12
        m2 = ((m2 - 1) % 12) + 1
        lbl = f'{_TR_AY[win_bas.month]}–{_TR_AY[m2]} {win_bas.year}'
        prev = _iso_date(win_bas - timedelta(days=90))
        nxt = _iso_date(win_bas + timedelta(days=90))
    else:
        win_bas = _week_start(anchor_dt)
        win_bit = win_bas + timedelta(days=6, hours=23, minutes=59)
        lbl = 'Bu Hafta'
        prev = _iso_date(win_bas - timedelta(days=7))
        nxt = _iso_date(win_bas + timedelta(days=7))
    return win_bas, win_bit, lbl, prev, nxt


def _day_columns(win_bas: datetime, win_bit: datetime, view: str) -> list[dict]:
    cols: list[dict] = []
    cur = datetime(win_bas.year, win_bas.month, win_bas.day)
    if view == '3_ay':
        # Haftalık group
        seen: set = set()
        while cur <= win_bit:
            wn = cur.isocalendar()[1]
            if wn not in seen:
                seen.add(wn)
                cols.append({
                    'key': f'W{wn}',
                    'label': f'{wn}. HAFTA',
                    'date': _iso_date(cur),
                    'left_pct': round(_pct(cur, win_bas, win_bit + timedelta(hours=1)), 3),
                    'width_pct': round(min(100.0 / max(len(cols) + 1, 1), 7.0 / (89.0) * 100), 3),
                })
            cur += timedelta(days=7)
        # Recompute widths evenly
        n = len(cols)
        for i, c in enumerate(cols):
            wk_bas = _parse_dt(c['date'])
            wk_bit = wk_bas + timedelta(days=6, hours=23, minutes=59) if wk_bas else None
            c['left_pct'] = round(_pct(wk_bas, win_bas, win_bit + timedelta(hours=1)), 3) if wk_bas else 0.0
            c['width_pct'] = round(min(100.0 - c['left_pct'], 7 / 90 * 100), 3)
    else:
        while cur <= win_bit:
            wd = cur.weekday()
            cols.append({
                'key': _iso_date(cur),
                'label': _TR_GUN[wd],
                'alt': str(cur.day),
                'date': _iso_date(cur),
                'is_weekend': wd >= 5,
                'left_pct': round(_pct(cur, win_bas, win_bit + timedelta(hours=1)), 3),
            })
            cur += timedelta(days=1)
    return cols


@genel_plan_bp.route('/')
@yetki_gerekli('planlama', 'can_view')
def genel_plan_sayfa():
    return render_template('planlama/genel_plan.html', pilot_sip=33917, pilot_model='CRX-71024-KRK')


@genel_plan_bp.route('/api/timeline')
@yetki_gerekli('planlama', 'can_view')
def api_timeline():
    """READ-ONLY canonical plan timeline.

    Query params:
      makine_id  — integer, optional (omit = tüm makineler)
      view       — bu_hafta | bu_ay | 3_ay  (default: bu_hafta)
      anchor     — YYYY-MM-DD (default: bugün)
    """
    view = (request.args.get('view') or 'bu_hafta').strip()
    anchor_raw = request.args.get('anchor', '')
    makine_id_raw = request.args.get('makine_id', '')

    now = datetime.now().replace(second=0, microsecond=0)
    anchor_dt = _parse_dt(anchor_raw) or now

    win_bas, win_bit, period_label, nav_prev, nav_next = _window(view, anchor_dt)
    columns = _day_columns(win_bas, win_bit, view)

    con = get_conn()
    try:
        # All active machines
        makineler = con.execute(
            'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE aktif=1 ORDER BY sira, id'
        ).fetchall()
        mak_map = {m['id']: dict(m) for m in makineler}

        # Filter by makine_id if given
        if makine_id_raw:
            try:
                filter_ids = [int(makine_id_raw)]
            except ValueError:
                filter_ids = [m['id'] for m in makineler]
        else:
            filter_ids = [m['id'] for m in makineler]

        # Resource rows: one per (makine, slot)
        resource_rows: list[dict] = []
        for mid in filter_ids:
            mk = mak_map.get(mid)
            if not mk:
                continue
            for slot in ('A', 'B'):
                resource_rows.append({
                    'resource_key': f"{mk['kod']}-{slot}",
                    'makine_id': mid,
                    'makine_kod': mk['kod'],
                    'slot': slot,
                    'istasyon_sayisi': mk['istasyon_sayisi'],
                })

        # Load plans per machine
        all_plans: list[dict] = []
        for mid in filter_ids:
            mk = mak_map.get(mid)
            if not mk:
                continue
            plans = _load_plans(con, mid, win_bas, win_bit)
            for p in plans:
                p['makine_kod'] = mk['kod']
                p['resource_key'] = f"{mk['kod']}-{p['slot']}"
                pb = _parse_dt(p['baslangic'])
                pe = _parse_dt(p['bitis'])
                if pb and pe:
                    p['block'] = _block(pb, pe, win_bas, win_bit + timedelta(hours=1))
                    p['dur_hours'] = round((pe - pb).total_seconds() / 3600, 2)
                all_plans.append(p)

        return jsonify({
            'ok': True,
            'view': view,
            'period': {
                'bas': _iso(win_bas),
                'bit': _iso(win_bit),
                'label': period_label,
                'nav_prev': nav_prev,
                'nav_next': nav_next,
                'anchor': _iso_date(anchor_dt),
            },
            'columns': columns,
            'resource_rows': resource_rows,
            'plans': all_plans,
            'plan_count': len(all_plans),
        })
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:300]}), 500
    finally:
        con.close()


@genel_plan_bp.route('/api/enj-timeline', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_timeline():
    """APS ENJ timeline — same data contract as aps_pilot_bp, under genel-plan URL prefix."""
    con = get_conn()
    demo_multi = request.args.get('demo_multi', '').lower() in ('1', 'true', 'yes')
    try:
        payload = load_enj_timeline_payload(con, demo_multi=demo_multi)
        return jsonify({'ok': True, **payload})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:300]}), 500
    finally:
        con.close()

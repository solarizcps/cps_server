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


_SLOTS = ('A', 'B')
_CHILD_TABLO = 'uretim_model_plan_enj_istasyon'


def _child_tablosu_var(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_CHILD_TABLO,),
    ).fetchone())


def _parse_istasyon_nos(raw) -> list[int]:
    if raw is None or raw == '':
        return []
    if isinstance(raw, int):
        return [raw] if raw > 0 else []
    s = str(raw).strip()
    if not s:
        return []
    out: set[int] = set()
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
            if n > 0:
                out.add(n)
        except ValueError:
            continue
    return sorted(out)


def _plans_overlap(plan_bas: datetime, plan_bit: datetime,
                   win_bas: datetime, win_bit: datetime) -> bool:
    return plan_bas < win_bit and win_bas < plan_bit


def _load_side_reservations(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    win_bas: datetime,
    win_bit: datetime,
) -> list[dict]:
    """Aktif plan rezervasyonları — child + legacy (NOT EXISTS), istasyon bazlı."""
    slot = slot.upper()
    child_exists = _child_tablosu_var(con)
    by_key: dict[tuple[int, int], dict] = {}

    def _add(pid, ist_no, row):
        key = (int(pid), int(ist_no))
        if key in by_key:
            return
        try:
            pb = _parse_dt(row['enj_plan_baslangic'])
            pe = _parse_dt(row['enj_plan_bitis']) if row['enj_plan_bitis'] else pb + timedelta(hours=1)
        except ValueError:
            return
        if not _plans_overlap(pb, pe, win_bas, win_bit):
            return
        by_key[key] = {
            'plan_id': int(pid),
            'istasyon_no': int(ist_no),
            'slot': slot,
            'sip_no': row['sip_no'],
            'sip_harinx': row['sip_harinx'] if 'sip_harinx' in row.keys() else None,
            'mamul_skod': row['mamul_skod'],
            'rkod': row['rkod'] if 'rkod' in row.keys() else 0,
            'model_adi': row['model_adi'] if 'model_adi' in row.keys() else None,
            'renk_adi': row['renk_adi'],
            'enj_kalip_id': row['enj_kalip_id'] if 'enj_kalip_id' in row.keys() else None,
            'enj_kalip_kod': row['enj_kalip_kod'] if 'enj_kalip_kod' in row.keys() else None,
            'enj_planlanacak_cift': row['enj_planlanacak_cift'] if 'enj_planlanacak_cift' in row.keys() else None,
            'enj_calisma_modu': row['enj_calisma_modu'] if 'enj_calisma_modu' in row.keys() else None,
            'enj_plan_baslangic': row['enj_plan_baslangic'],
            'enj_plan_bitis': row['enj_plan_bitis'],
            'plan_bas_gosterim': _fmt_tam(row['enj_plan_baslangic']),
            'plan_bit_gosterim': _fmt_tam(row['enj_plan_bitis']),
        }

    if child_exists:
        rows = con.execute(
            f"""
            SELECT p.id, p.sip_no, p.sip_harinx, p.mamul_skod, p.rkod, p.model_adi, p.renk_adi,
                   p.enj_kalip_id, p.enj_kalip_kod, p.enj_planlanacak_cift, p.enj_calisma_modu,
                   p.enj_plan_baslangic, p.enj_plan_bitis, c.istasyon_no
              FROM uretim_model_plan p
              JOIN {_CHILD_TABLO} c ON c.plan_id = p.id
             WHERE p.aktif = 1
               AND c.enj_makine_id = ?
               AND c.enj_slot = ?
               AND p.enj_plan_baslangic IS NOT NULL
               AND p.enj_plan_baslangic <= ?
               AND COALESCE(p.enj_plan_bitis, p.enj_plan_baslangic) >= ?
            """,
            (int(makine_id), slot, _iso(win_bit), _iso(win_bas)),
        ).fetchall()
        for row in rows:
            _add(row['id'], row['istasyon_no'], row)

    q_legacy = """
        SELECT id, sip_no, sip_harinx, mamul_skod, rkod, model_adi, renk_adi,
               enj_kalip_id, enj_kalip_kod, enj_planlanacak_cift, enj_calisma_modu,
               enj_plan_baslangic, enj_plan_bitis, enj_istasyon_no
          FROM uretim_model_plan
         WHERE aktif = 1
           AND enj_makine_id = ?
           AND UPPER(enj_slot) = ?
           AND enj_plan_baslangic IS NOT NULL
           AND enj_plan_baslangic <= ?
           AND COALESCE(enj_plan_bitis, enj_plan_baslangic) >= ?
    """
    params_legacy = [int(makine_id), slot, _iso(win_bit), _iso(win_bas)]
    if child_exists:
        q_legacy += f"""
           AND NOT EXISTS (
               SELECT 1 FROM {_CHILD_TABLO} c WHERE c.plan_id = uretim_model_plan.id
           )
        """
    for row in con.execute(q_legacy, params_legacy).fetchall():
        for ist_no in _parse_istasyon_nos(row['enj_istasyon_no']):
            _add(row['id'], ist_no, row)

    return list(by_key.values())


def _resolve_anchor_window(
    plan_baslangic: str | None,
    plan_bitis: str | None,
) -> tuple[datetime | None, datetime | None]:
    if not plan_baslangic:
        return None, None
    try:
        bas = _parse_dt(plan_baslangic)
    except ValueError:
        return None, None
    if plan_bitis:
        try:
            bit = _parse_dt(plan_bitis)
        except ValueError:
            bit = bas + timedelta(minutes=1)
    else:
        bit = bas + timedelta(minutes=1)
    if bit <= bas:
        bit = bas + timedelta(minutes=1)
    return bas, bit


def _station_planned_status(
    reservation: dict | None,
    *,
    anchor_bas: datetime,
    anchor_bit: datetime,
    secim_bas: datetime | None,
    secim_bit: datetime | None,
) -> str:
    if not reservation:
        return 'BOS'
    try:
        pb = _parse_dt(reservation['enj_plan_baslangic'])
        pe = _parse_dt(reservation['enj_plan_bitis']) if reservation['enj_plan_bitis'] else pb + timedelta(hours=1)
    except ValueError:
        return 'BOS'
    if not _plans_overlap(pb, pe, anchor_bas, anchor_bit):
        return 'BOS'
    if secim_bas and secim_bit and _plans_overlap(pb, pe, secim_bas, secim_bit):
        return 'CAKISAN'
    return 'PLANLI'


def build_side_planned_block(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyon_sayisi: int,
    *,
    anchor_bas: datetime,
    anchor_bit: datetime,
    secim_bas: datetime | None = None,
    secim_bit: datetime | None = None,
    asorti_map: dict | None = None,
) -> dict:
    """Seçilen tarih penceresinde planlı istasyon özeti."""
    reservations = _load_side_reservations(
        con, int(makine_id), slot, anchor_bas, anchor_bit,
    )
    by_ist: dict[int, dict] = {}
    for r in reservations:
        by_ist[int(r['istasyon_no'])] = r

    stations: list[dict] = []
    planned_count = 0
    for no in range(1, int(istasyon_sayisi) + 1):
        res = by_ist.get(no)
        durum = _station_planned_status(
            res,
            anchor_bas=anchor_bas,
            anchor_bit=anchor_bit,
            secim_bas=secim_bas,
            secim_bit=secim_bit,
        )
        if durum in ('PLANLI', 'CAKISAN'):
            planned_count += 1
        row = {
            'istasyon_no': no,
            'slot': slot.upper(),
            'durum': durum,
        }
        if res and durum != 'BOS':
            ak = (asorti_map or {}).get(
                (int(res['sip_no']), int(res.get('sip_harinx') or 0),
                 str(res['mamul_skod']), int(res.get('rkod') or 0)),
            )
            row.update({
                'sip_no': res.get('sip_no'),
                'model': res.get('mamul_skod') or res.get('model_adi'),
                'renk': res.get('renk_adi'),
                'kalip_kod': res.get('enj_kalip_kod'),
                'planlanacak_cift': res.get('enj_planlanacak_cift'),
                'plan_baslangic': res.get('enj_plan_baslangic'),
                'plan_bitis': res.get('enj_plan_bitis'),
                'plan_bas_gosterim': res.get('plan_bas_gosterim'),
                'plan_bit_gosterim': res.get('plan_bit_gosterim'),
                'calisma_modu': res.get('enj_calisma_modu'),
                'asorti': ak if ak else None,
            })
        stations.append(row)

    total = int(istasyon_sayisi)
    return {
        'planned_count': planned_count,
        'available_count': max(0, total - planned_count),
        'total_count': total,
        'stations': stations,
    }


def build_makine_detay(
    con: sqlite3.Connection,
    makine_id: int,
    *,
    plan_baslangic: str | None = None,
    plan_bitis: str | None = None,
    secim_baslangic: str | None = None,
    secim_bitis: str | None = None,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
    asorti_map: dict | None = None,
    include_stations: bool = True,
) -> dict | None:
    """Makine kart/detay — fiziksel + planlı ayrı sayım."""
    mk = con.execute(
        'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE id=? AND aktif=1',
        (int(makine_id),),
    ).fetchone()
    if not mk:
        return None

    mid = int(mk['id'])
    n = int(mk['istasyon_sayisi'] or 8)
    anchor_bas, anchor_bit = _resolve_anchor_window(plan_baslangic, plan_bitis)
    secim_bas, secim_bit = _resolve_anchor_window(secim_baslangic, secim_bitis)
    if secim_bas and not secim_bitis:
        secim_bit = secim_bas + timedelta(minutes=1)

    from modules.planlama.enj_kapasite_read_service import build_side_physical_block

    sides: dict[str, dict] = {}
    for slot in _SLOTS:
        physical = build_side_physical_block(con, mid, slot, n)
        planned = {
            'planned_count': 0,
            'available_count': n,
            'total_count': n,
            'stations': [] if include_stations else None,
            'plan_tarih_secilmedi': anchor_bas is None,
        }
        if anchor_bas and anchor_bit:
            planned = build_side_planned_block(
                con, mid, slot, n,
                anchor_bas=anchor_bas,
                anchor_bit=anchor_bit,
                secim_bas=secim_bas,
                secim_bit=secim_bit,
                asorti_map=asorti_map,
            )
            if not include_stations:
                planned['stations'] = None
        elif include_stations:
            planned['stations'] = []

        istasyonlar = list(range(1, n + 1))

        # A) Base first available — bağımsız, plan anchor'ından etkilenmez
        base_first_avail = None
        base_first_disp = None
        base_first_disp_tam = None
        try:
            base_ilk = find_first_available_start(
                con, mid, slot, istasyonlar,
                calisma_modu=calisma_modu,
                hafta_sonu=hafta_sonu,
                hs_vardiya=hs_vardiya,
                from_dt=None,
            )
            base_first_avail = _iso(base_ilk)
            base_first_disp = _fmt_kisa(base_ilk)
            base_first_disp_tam = _fmt_tam(base_ilk)
        except RuntimeError:
            pass

        # Geriye uyumluluk: first_available seçili anchor penceresinden (Machine Detail vb.)
        first_avail = None
        first_disp = None
        if anchor_bas:
            try:
                ilk = find_first_available_start(
                    con, mid, slot, istasyonlar,
                    calisma_modu=calisma_modu,
                    hafta_sonu=hafta_sonu,
                    hs_vardiya=hs_vardiya,
                    from_dt=anchor_bas,
                )
                first_avail = _iso(ilk)
                first_disp = _fmt_tam(ilk)
            except RuntimeError:
                pass

        sides[slot] = {
            'physical': {
                'occupied_count': physical['occupied_count'],
                'empty_count': physical['empty_count'],
                'total_count': physical['total_count'],
                'stations': physical['stations'] if include_stations else None,
                'snapshot_at': physical.get('snapshot_at'),
                'snapshot_tarih': physical.get('snapshot_tarih'),
                'snapshot_vardiya': physical.get('snapshot_vardiya'),
            },
            'planned': planned,
            'base_first_available': base_first_avail,
            'base_first_available_gosterim': base_first_disp,
            'base_first_available_tam': base_first_disp_tam,
            'first_available': first_avail,
            'first_available_gosterim': first_disp,
        }

    anchor_out = {
        'baslangic': plan_baslangic,
        'bitis': plan_bitis,
        'secim_baslangic': secim_baslangic,
        'secim_bitis': secim_bitis,
    }
    return {
        'makine': {
            'id': mid,
            'kod': mk['kod'],
            'istasyon_sayisi': n,
        },
        'anchor': anchor_out,
        'sides': sides,
    }


def build_makine_slot_ozet_all(
    con: sqlite3.Connection,
    *,
    plan_baslangic: str | None = None,
    plan_bitis: str | None = None,
    secim_baslangic: str | None = None,
    secim_bitis: str | None = None,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
) -> list[dict]:
    """M1–M4 kart özeti — istasyon satırı olmadan hafif sayım."""
    rows = con.execute(
        'SELECT id FROM enj_makine WHERE aktif=1 ORDER BY sira, kod',
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        det = build_makine_detay(
            con, int(r['id']),
            plan_baslangic=plan_baslangic,
            plan_bitis=plan_bitis,
            secim_baslangic=secim_baslangic,
            secim_bitis=secim_bitis,
            calisma_modu=calisma_modu,
            hafta_sonu=hafta_sonu,
            hs_vardiya=hs_vardiya,
            include_stations=False,
        )
        if det:
            out.append({
                'makine_id': det['makine']['id'],
                'makine_kod': det['makine']['kod'],
                'istasyon_sayisi': det['makine']['istasyon_sayisi'],
                'A': det['sides']['A'],
                'B': det['sides']['B'],
            })
    return out

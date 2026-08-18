# -*- coding: utf-8 -*-
"""APS P4A — Enjeksiyon yönetici timeline read-model (legacy uretim_model_plan, no write)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.planlama.aps_plan_pilot_service import load_legacy_enj_plan
from modules.planlama.aps_resource_calendar_service import get_working_windows
from modules.planlama.aps_calendar_contract import enj_slot_calendar, WEEKEND_HAYIR, WEEKEND_EVET_ONAYLI
from modules.planlama.aps_resource_keys import enj_resource_key

LEGACY_PLAN_TABLE = 'uretim_model_plan'
MACHINES = ('M1', 'M2', 'M3', 'M4')
SLOTS = ('A', 'B')

PROCESS_ENJ = {
    'id': 'proc-ENJ',
    'process_code': 'ENJ',
    'process_name': 'ENJEKSİYON',
    'color': 'enj',
    'enabled': True,
}


def _build_processes() -> list[dict[str, Any]]:
    """Generic process contract — P4A.2 yalnız ENJ aktif."""
    return [dict(PROCESS_ENJ)]


def _makine_row_id(makine: str) -> str:
    return f'mak-{makine.upper()}'


def _build_resource_tree() -> list[dict[str, Any]]:
    """Resource rows: proc-ENJ → mak-M1..4 → M1-A/M1-B (P5.1 hierarchy)."""
    rows: list[dict[str, Any]] = []
    proc_id = PROCESS_ENJ['id']
    mk_num = {'M1': '1', 'M2': '2', 'M3': '3', 'M4': '4'}
    for mk in MACHINES:
        num = mk_num.get(mk, mk.lstrip('M'))
        rows.append({
            'id': _makine_row_id(mk),
            'label': f'MAKİNE {num}',
            'display_name': f'MAKİNE {num}',
            'parent_process': proc_id,
            'process_code': 'ENJ',
            'kind': 'machine',
            'makine': mk,
            'slot': None,
            'enabled': True,
            'open': True,
        })
        for slot in SLOTS:
            rows.append({
                'id': _resource_row_id(mk, slot),
                'label': slot,
                'display_name': f'{mk} / {slot}',
                'parent_process': proc_id,
                'process_code': 'ENJ',
                'kind': 'slot',
                'makine': mk,
                'slot': slot,
                'enabled': True,
                'resource_key_prefix': enj_resource_key(mk, slot, 1).rsplit(':', 1)[0],
                'parent_machine': _makine_row_id(mk),
            })
    return rows


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _plan_status(row: dict) -> str:
    """V1 — kanıt yoksa PLANLANDI."""
    return 'PLANLANDI'


def _resource_row_id(makine: str, slot: str) -> str:
    return f'{makine}-{slot.upper()}'


def _legacy_plan_to_block(con: sqlite3.Connection, legacy: dict) -> dict[str, Any] | None:
    bas = legacy.get('enj_plan_baslangic')
    bit = legacy.get('enj_plan_bitis')
    if not bas or not bit:
        return None
    makine = legacy.get('_makine_kod') or 'M1'
    slot = (legacy.get('enj_slot') or 'A').upper()
    ist_nos = sorted({
        int(c.get('istasyon_no') or 0)
        for c in (legacy.get('_children') or [])
        if c.get('istasyon_no')
    })
    ist_label = f'İST{ist_nos[0]}–{ist_nos[-1]}' if len(ist_nos) > 1 else (
        f'İST{ist_nos[0]}' if ist_nos else 'İST1–8'
    )
    tur_cift = legacy.get('enj_tur_cift')
    kalip_basi = legacy.get('enj_kalip_basi_cift')
    miktar = legacy.get('enj_planlanacak_cift') or legacy.get('miktar') or 0
    gerekli_tur = None
    if tur_cift and float(tur_cift) > 0:
        gerekli_tur = int(float(miktar) / float(tur_cift) + 0.999)

    cari = ''
    try:
        row = con.execute(
            'SELECT cari_unvan FROM uretim_model_plan WHERE id=?',
            (int(legacy.get('id')),),
        ).fetchone()
        if row and row[0]:
            cari = row[0]
    except sqlite3.Error:
        pass

    snap = legacy.get('enj_kapasite_snapshot')
    kapasite_ref = 'manual_publish'
    if snap:
        try:
            s = json.loads(snap) if isinstance(snap, str) else snap
            kapasite_ref = s.get('kaynak') or s.get('reference_mode') or 'publish_snapshot'
        except (json.JSONDecodeError, TypeError):
            kapasite_ref = 'publish_snapshot'

    pid = int(legacy.get('id'))
    return {
        'id': f'plan-{pid}',
        'plan_id': pid,
        'resource_id': _resource_row_id(makine, slot),
        'makine': makine,
        'slot': slot,
        'start': bas,
        'end': bit,
        'status': _plan_status(legacy),
        'sip_no': legacy.get('sip_no'),
        'mamul_skod': legacy.get('mamul_skod'),
        'renk': legacy.get('renk_adi') or legacy.get('renk'),
        'miktar': float(miktar or 0),
        'musteri': cari or legacy.get('cari_unvan') or '',
        'kalip': legacy.get('enj_kalip_kod') or '',
        'kalip_adedi': legacy.get('enj_aktif_goz'),
        'aktif_goz': legacy.get('enj_aktif_goz'),
        'tur_cift': tur_cift,
        'gerekli_tur': gerekli_tur,
        'istasyonlar': ist_label,
        'istasyon_nos': ist_nos or list(range(1, 9)),
        'calisma_modu': legacy.get('enj_calisma_modu') or 'GUNDUZ_GECE',
        'hafta_sonu': legacy.get('enj_hafta_sonu_calisma') or 'HAYIR',
        'kapasite_kaynak': kapasite_ref,
        'process_code': 'ENJ',
        'process_name': 'ENJEKSİYON',
        'label_short': ' · '.join(filter(None, [
            str(legacy.get('sip_no') or ''),
            legacy.get('mamul_skod') or '',
            f"{int(float(miktar or 0))} ÇİFT",
            legacy.get('enj_kalip_kod') or '',
        ])),
    }


def _build_calendar_windows(
    view_start: str,
    view_end: str,
    *,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
) -> list[dict[str, str]]:
    """P2 calendar contract — ENJ slot working windows (read-only)."""
    ww = WEEKEND_HAYIR if (hafta_sonu or 'HAYIR').upper() != 'EVET' else WEEKEND_EVET_ONAYLI
    cal = enj_slot_calendar(
        'M1', 'A',
        calisma_modu=calisma_modu or 'GUNDUZ_GECE',
        weekend_work=ww,
        hafta_sonu_kural='A',
    )
    rs = f'{view_start} 00:00:00'
    re = f'{view_end} 23:59:59'
    windows = get_working_windows(cal, rs, re)
    return [
        {'start': w.start.strftime('%Y-%m-%d %H:%M:%S'), 'end': w.end.strftime('%Y-%m-%d %H:%M:%S'), 'source': w.source}
        for w in windows
    ]


def _demo_multi_plan() -> dict[str, Any]:
    """Browser-only synthetic 2nd block on M1/A — DB write yok."""
    return {
        'id': 'plan-demo-multi',
        'plan_id': 0,
        'resource_id': 'M1-A',
        'makine': 'M1',
        'slot': 'A',
        'start': '2026-08-19 07:00:00',
        'end': '2026-08-19 15:00:00',
        'status': 'PLANLANDI',
        'sip_no': 99999,
        'mamul_skod': 'DEMO-MULTI',
        'renk': 'DEMO',
        'miktar': 500.0,
        'musteri': 'DEMO',
        'kalip': 'DEMO',
        'kalip_adedi': 8,
        'aktif_goz': 8,
        'tur_cift': 16,
        'gerekli_tur': 32,
        'istasyonlar': 'İST1–8',
        'istasyon_nos': list(range(1, 9)),
        'calisma_modu': 'GUNDUZ_GECE',
        'hafta_sonu': 'HAYIR',
        'kapasite_kaynak': 'demo_multi_preview',
        'process_code': 'ENJ',
        'process_name': 'ENJEKSİYON',
        'label_short': '99999 · DEMO-MULTI · 500 ÇİFT · DEMO',
        'demo_only': True,
    }


def load_enj_timeline_payload(con: sqlite3.Connection, *, demo_multi: bool = False) -> dict[str, Any]:
    """READ-only Enj timeline — legacy uretim_model_plan."""
    resources = _build_resource_tree()
    plans: list[dict[str, Any]] = []

    source = 'legacy_plan_read'
    if not _table_exists(con, LEGACY_PLAN_TABLE):
        source = 'static_p1_pilot'
    else:
        rows = con.execute(
            f"""
            SELECT id FROM {LEGACY_PLAN_TABLE}
             WHERE aktif = 1
               AND enj_plan_baslangic IS NOT NULL
               AND enj_plan_bitis IS NOT NULL
             ORDER BY enj_plan_baslangic, id
            """,
        ).fetchall()
        for row in rows:
            legacy = load_legacy_enj_plan(con, int(row[0]))
            if not legacy:
                continue
            block = _legacy_plan_to_block(con, legacy)
            if block:
                plans.append(block)

    if not plans:
        legacy = load_legacy_enj_plan(con, 199) if _table_exists(con, LEGACY_PLAN_TABLE) else None
        if legacy:
            block = _legacy_plan_to_block(con, legacy)
            if block:
                plans.append(block)

    if not plans:
        from modules.planlama.aps_pilot_data_service import PILOT_33917_STATIC
        enj = PILOT_33917_STATIC.get('enj_detail') or {}
        plans.append({
            'id': 'plan-199',
            'plan_id': 199,
            'resource_id': 'M1-A',
            'makine': enj.get('makine') or 'M1',
            'slot': enj.get('slot') or 'A',
            'start': enj.get('plan_baslangic'),
            'end': enj.get('plan_bitis'),
            'status': 'PLANLANDI',
            'sip_no': enj.get('sip_no') or 33917,
            'mamul_skod': enj.get('model') or 'CRX-71024-KRK',
            'renk': enj.get('renk') or 'MAVI',
            'miktar': float(enj.get('miktar') or 3000),
            'musteri': '',
            'kalip': enj.get('kalip') or '21M5',
            'kalip_adedi': 8,
            'aktif_goz': 8,
            'tur_cift': 16,
            'gerekli_tur': 188,
            'istasyonlar': enj.get('istasyonlar') or 'İST1–8',
            'istasyon_nos': list(range(1, 9)),
            'calisma_modu': 'GUNDUZ_GECE',
            'hafta_sonu': 'HAYIR',
            'kapasite_kaynak': 'static_p1_pilot',
            'process_code': 'ENJ',
            'process_name': 'ENJEKSİYON',
            'label_short': '33917 · CRX-71024-KRK · 3000 ÇİFT · 21M5',
        })
        source = 'static_p1_pilot'
    elif plans:
        source = 'legacy_plan_read'

    view_start = '2026-08-17'
    view_end = '2026-08-23'
    if plans:
        view_start = min(p['start'][:10] for p in plans if p.get('start'))
        view_end = max(p['end'][:10] for p in plans if p.get('end'))

    if demo_multi:
        plans.append(_demo_multi_plan())

    cal_mod = 'GUNDUZ_GECE'
    cal_hs = 'HAYIR'
    if plans:
        cal_mod = plans[0].get('calisma_modu') or cal_mod
        cal_hs = plans[0].get('hafta_sonu') or cal_hs

    return {
        'processes': _build_processes(),
        'resources': resources,
        'plans': plans,
        'calendar_windows': _build_calendar_windows(view_start, view_end, calisma_modu=cal_mod, hafta_sonu=cal_hs),
        'view_start': view_start,
        'view_end': view_end,
        'scope': 'enj_only',
        'source': source,
        'pilot_sip': 33917,
        'pilot_model': 'CRX-71024-KRK',
        'demo_multi': demo_multi,
    }

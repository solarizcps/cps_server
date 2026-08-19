# -*- coding: utf-8 -*-
"""APS P1.5 — pilot read payload (33917). DB read or in-memory fallback, no write."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.planlama.aps_plan_pilot_service import (
    HEADER_TABLE,
    OPERATION_TABLE,
    PILOT_33917,
    RESERVATION_TABLE,
    fetch_plan_bundle,
)
from modules.planlama.aps_resource_keys import enj_resource_key

# P1 pilot kanıt — canonical DB migration olmadan da UI proof çalışır.
PILOT_33917_STATIC: dict[str, Any] = {
    'header': {
        'id': 1,
        'sip_no': 33917,
        'sip_harinx': 83972,
        'mamul_skod': 'CRX-71024-KRK',
        'rkod': 424,
        'plan_donemi': 'gelecek_hafta',
        'oncelik': 3,
        'rev_no': 1,
        'aktif': 1,
    },
    'operations': [
        {'id': 1, 'sequence_no': 1, 'proses_kod': '26', 'proses_adi': 'Enjeksiyon',
         'operation_type': 'enjeksiyon', 'status': 'SCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': '2026-08-18 07:00:00', 'plan_bitis': '2026-08-19 00:10:56',
         'original_plan_bitis': '2026-08-19 00:10:56', 'guncel_tahmini_bitis': '2026-08-19 00:10:56',
         'depends_on_operation_id': None, 'lag_minutes': 0},
        {'id': 2, 'sequence_no': 2, 'proses_kod': '02', 'proses_adi': 'Kesim',
         'operation_type': 'kesim', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 1, 'lag_minutes': 0},
        {'id': 3, 'sequence_no': 3, 'proses_kod': '15', 'proses_adi': 'Saya',
         'operation_type': 'saya', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 2, 'lag_minutes': 0},
        {'id': 4, 'sequence_no': 4, 'proses_kod': '08', 'proses_adi': 'Digital - Serigrafi - Flok -',
         'operation_type': 'baski', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 3, 'lag_minutes': 0},
        {'id': 5, 'sequence_no': 5, 'proses_kod': '28', 'proses_adi': 'Monta Baslayacak',
         'operation_type': 'montaj_bas', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 4, 'lag_minutes': 0},
        {'id': 6, 'sequence_no': 6, 'proses_kod': '30', 'proses_adi': 'Monta',
         'operation_type': 'montaj', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 5, 'lag_minutes': 0},
        {'id': 7, 'sequence_no': 7, 'proses_kod': '35', 'proses_adi': 'Temizleme',
         'operation_type': 'temizleme', 'status': 'UNSCHEDULED', 'planned_qty': 3000,
         'plan_baslangic': None, 'plan_bitis': None, 'depends_on_operation_id': 6, 'lag_minutes': 0},
    ],
    'reservations': [
        {
            'id': i,
            'operation_id': 1,
            'resource_type': 'ENJ_ISTASYON',
            'resource_key': enj_resource_key('M1', 'A', i),
            'location': 'SOLARIZ',
            'slot': 'A',
            'unit_no': i,
            'reserve_baslangic': '2026-08-18 07:00:00',
            'reserve_bitis': '2026-08-19 00:10:56',
            'status': 'ACTIVE',
        }
        for i in range(1, 9)
    ],
    'enj_detail': {
        'model': 'CRX-71024-KRK',
        'renk': 'MAVI',
        'sip_no': 33917,
        'miktar': 3000,
        'makine': 'M1',
        'slot': 'A',
        'istasyonlar': 'İST1–8',
        'kalip': '21M5',
        'plan_baslangic': '2026-08-18 07:00:00',
        'plan_bitis': '2026-08-19 00:10:56',
    },
    'chain': ['26', '02', '15', '08', '28', '30', '35'],
    'source': 'static_p1_pilot',
}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def load_pilot_33917_payload(con: sqlite3.Connection) -> dict[str, Any]:
    """READ-only — APS tabloları varsa DB'den, yoksa static P1 pilot."""
    if not _table_exists(con, HEADER_TABLE):
        out = dict(PILOT_33917_STATIC)
        out['source'] = 'static_p1_pilot'
        return out

    row = con.execute(
        f"""
        SELECT id FROM {HEADER_TABLE}
         WHERE sip_no=? AND sip_harinx=? AND mamul_skod=? AND rkod=? AND aktif=1
         ORDER BY id DESC LIMIT 1
        """,
        (
            PILOT_33917['sip_no'],
            PILOT_33917['sip_harinx'],
            PILOT_33917['mamul_skod'],
            PILOT_33917['rkod'],
        ),
    ).fetchone()
    if not row:
        out = dict(PILOT_33917_STATIC)
        out['source'] = 'static_p1_pilot'
        return out

    bundle = fetch_plan_bundle(con, int(row[0]))
    enj = next(
        (o for o in bundle['operations'] if o.get('proses_kod') == '26'),
        None,
    )
    params = {}
    if enj and enj.get('params_json'):
        try:
            params = json.loads(enj['params_json'])
        except json.JSONDecodeError:
            params = {}

    out = {
        'header': bundle['header'],
        'operations': bundle['operations'],
        'reservations': bundle['reservations'],
        'enj_detail': {
            'model': bundle['header'].get('mamul_skod'),
            'renk': 'MAVI',
            'sip_no': bundle['header'].get('sip_no'),
            'miktar': enj.get('planned_qty') if enj else 3000,
            'makine': params.get('makine_kod') or 'M1',
            'slot': params.get('enj_slot') or 'A',
            'istasyonlar': 'İST1–8',
            'kalip': params.get('enj_kalip_kod') or '21M5',
            'plan_baslangic': enj.get('plan_baslangic') if enj else None,
            'plan_bitis': enj.get('plan_bitis') if enj else None,
        },
        'chain': [o['proses_kod'] for o in bundle['operations']],
        'source': 'aps_db_read',
    }
    return out


def build_synthetic_blocks(count: int, *, seed_start: str = '2026-08-18 07:00:00') -> dict[str, Any]:
    """Browser-only perf dataset — DB write yok."""
    n = max(1, min(int(count), 500))
    tasks = []
    base_ts = seed_start
    for i in range(1, n + 1):
        proses = str(26 + (i % 10))
        tasks.append({
            'id': f'syn-{i}',
            'proses_kod': proses,
            'text': f'SYN-{i:04d} · Proses {proses}',
            'start_date': base_ts,
            'duration_minutes': 60 + (i % 120),
            'resource_key': enj_resource_key('M1', 'A', (i % 8) + 1),
            'status': 'SCHEDULED',
        })
    return {'count': n, 'tasks': tasks, 'source': 'synthetic_browser_only'}

# -*- coding: utf-8 -*-
"""APS V1 P1 — pilot seed: Korgun Model_P sırası + plan 199 Enj adaptor (TMP only)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.planlama.aps_resource_keys import (
    OPERATION_SCHEDULED,
    OPERATION_UNSCHEDULED,
    RESOURCE_TYPE_ENJ,
    RESERVATION_ACTIVE,
    enj_resource_key,
    operation_type_for_proses,
)
from modules.planlama.uretim_plan_service import model_satir_by_canonical

HEADER_TABLE = 'uretim_plan_header'
OPERATION_TABLE = 'uretim_plan_operation'
RESERVATION_TABLE = 'uretim_plan_resource_reservation'
LEGACY_PLAN_TABLE = 'uretim_model_plan'
LEGACY_CHILD_TABLE = 'uretim_model_plan_enj_istasyon'

PILOT_33917 = {
    'sip_no': 33917,
    'sip_harinx': 83972,
    'mamul_skod': 'CRX-71024-KRK',
    'rkod': 424,
    'legacy_plan_id': 199,
}


def load_korgun_proses_chain(korgun_con, sip_no: int, sip_harinx: int,
                             mamul_skod: str, rkod: int) -> list[dict]:
    """Model_P canonical sıra — numeric proses_kod sırası kullanılmaz."""
    satir = model_satir_by_canonical(
        korgun_con, sip_no, sip_harinx, mamul_skod, rkod,
    )
    if not satir:
        return []
    prosesler = satir.get('prosesler') or []
    chain = []
    for idx, p in enumerate(prosesler, start=1):
        chain.append({
            'sequence_no': idx,
            'proses_kod': str(p.get('proses_kod', '')).strip(),
            'proses_adi': p.get('proses_adi') or '',
            'proses_no': p.get('proses_no'),
            'route_tier': p.get('route_tier'),
            'durum': p.get('durum'),
        })
    return chain


def _row_get(row, key, idx=0):
    if isinstance(row, sqlite3.Row):
        return row[key]
    return row[idx]


def load_legacy_enj_plan(con: sqlite3.Connection, plan_id: int) -> dict | None:
    row = con.execute(
        f'SELECT * FROM {LEGACY_PLAN_TABLE} WHERE id=?', (int(plan_id),),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    children = con.execute(
        f'SELECT * FROM {LEGACY_CHILD_TABLE} WHERE plan_id=? ORDER BY istasyon_no',
        (int(plan_id),),
    ).fetchall()
    makine_kod = 'M1'
    if d.get('enj_makine_id'):
        mk = con.execute(
            'SELECT kod FROM enj_makine WHERE id=?', (int(d['enj_makine_id']),),
        ).fetchone()
        if mk:
            makine_kod = _row_get(mk, 'kod', 0)
    d['_makine_kod'] = makine_kod
    d['_children'] = [dict(c) for c in children]
    return d


def create_plan_header(
    con: sqlite3.Connection,
    *,
    sip_no: int,
    sip_harinx: int,
    mamul_skod: str,
    rkod: int,
    plan_donemi: str,
    oncelik: int = 3,
    rev_no: int = 1,
    supersedes_plan_id: int | None = None,
    created_by: int | None = None,
) -> int:
    cur = con.execute(
        f"""
        INSERT INTO {HEADER_TABLE}
            (sip_no, sip_harinx, mamul_skod, rkod, plan_donemi, oncelik,
             aktif, rev_no, supersedes_plan_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            int(sip_no), int(sip_harinx), mamul_skod, int(rkod or 0),
            plan_donemi, int(oncelik), int(rev_no),
            supersedes_plan_id, created_by,
        ),
    )
    return int(cur.lastrowid)


def seed_operations_from_chain(
    con: sqlite3.Connection,
    plan_id: int,
    chain: list[dict],
    planned_qty: float,
) -> list[int]:
    op_ids: list[int] = []
    prev_id: int | None = None
    for step in chain:
        pk = step['proses_kod']
        cur = con.execute(
            f"""
            INSERT INTO {OPERATION_TABLE}
                (plan_id, sequence_no, proses_kod, proses_adi, operation_type,
                 planned_qty, status, depends_on_operation_id, lag_minutes,
                 params_json, revision_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 1)
            """,
            (
                int(plan_id),
                int(step['sequence_no']),
                pk,
                step.get('proses_adi') or '',
                operation_type_for_proses(pk),
                float(planned_qty),
                OPERATION_UNSCHEDULED,
                prev_id,
                json.dumps({
                    'model_p_proses_no': step.get('proses_no'),
                    'route_tier': step.get('route_tier'),
                    'korgun_durum': step.get('durum'),
                }, ensure_ascii=False),
            ),
        )
        oid = int(cur.lastrowid)
        op_ids.append(oid)
        prev_id = oid
    return op_ids


def map_legacy_enj_to_operation(
    con: sqlite3.Connection,
    operation_id: int,
    legacy: dict,
) -> int:
    """Plan 199 Enj → APS operation + İST1–8 reservations. Legacy tabloya WRITE yok."""
    plan_bas = legacy.get('enj_plan_baslangic')
    plan_bit = legacy.get('enj_plan_bitis')
    params = {
        'legacy_plan_id': legacy.get('id'),
        'enj_makine_id': legacy.get('enj_makine_id'),
        'enj_slot': legacy.get('enj_slot'),
        'enj_kalip_id': legacy.get('enj_kalip_id'),
        'enj_kalip_kod': legacy.get('enj_kalip_kod'),
        'enj_aktif_goz': legacy.get('enj_aktif_goz'),
        'enj_kalip_basi_cift': legacy.get('enj_kalip_basi_cift'),
        'enj_tur_cift': legacy.get('enj_tur_cift'),
        'enj_calisma_modu': legacy.get('enj_calisma_modu'),
        'enj_planlanacak_cift': legacy.get('enj_planlanacak_cift'),
        'makine_kod': legacy.get('_makine_kod'),
    }
    con.execute(
        f"""
        UPDATE {OPERATION_TABLE}
           SET planned_qty = ?,
               plan_baslangic = ?,
               plan_bitis = ?,
               original_plan_bitis = ?,
               guncel_tahmini_bitis = ?,
               status = ?,
               params_json = ?,
               kapasite_snapshot = ?,
               updated_at = datetime('now','localtime')
         WHERE id = ?
        """,
        (
            legacy.get('enj_planlanacak_cift') or legacy.get('miktar'),
            plan_bas,
            plan_bit,
            plan_bit,
            plan_bit,
            OPERATION_SCHEDULED,
            json.dumps(params, ensure_ascii=False),
            legacy.get('enj_kapasite_snapshot'),
            int(operation_id),
        ),
    )
    makine_kod = legacy.get('_makine_kod') or 'M1'
    slot = legacy.get('enj_slot') or 'A'
    reservation_ids = []
    for child in legacy.get('_children') or []:
        ist = int(child.get('istasyon_no') or 0)
        rk = enj_resource_key(makine_kod, slot, ist)
        cur = con.execute(
            f"""
            INSERT INTO {RESERVATION_TABLE}
                (operation_id, resource_type, resource_key, location, slot, unit_no,
                 reserve_baslangic, reserve_bitis, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(operation_id),
                RESOURCE_TYPE_ENJ,
                rk,
                'SOLARIZ',
                slot,
                ist,
                plan_bas,
                plan_bit,
                RESERVATION_ACTIVE,
            ),
        )
        reservation_ids.append(int(cur.lastrowid))
    return len(reservation_ids)


def seed_pilot_33917(
    sqlite_con: sqlite3.Connection,
    korgun_con,
    *,
    plan_donemi: str = 'gelecek_hafta',
    legacy_plan_id: int = 199,
) -> dict[str, Any]:
    p = PILOT_33917
    chain = load_korgun_proses_chain(
        korgun_con, p['sip_no'], p['sip_harinx'], p['mamul_skod'], p['rkod'],
    )
    if not chain:
        raise RuntimeError('33917 Korgun proses zinciri okunamadı')

    legacy = load_legacy_enj_plan(sqlite_con, legacy_plan_id)
    if not legacy:
        raise RuntimeError(f'Legacy plan {legacy_plan_id} TMP DB\'de yok')

    plan_id = create_plan_header(
        sqlite_con,
        sip_no=p['sip_no'],
        sip_harinx=p['sip_harinx'],
        mamul_skod=p['mamul_skod'],
        rkod=p['rkod'],
        plan_donemi=plan_donemi or legacy.get('plan_donemi') or 'gelecek_hafta',
        oncelik=int(legacy.get('oncelik') or 3),
    )
    qty = float(legacy.get('miktar') or legacy.get('enj_planlanacak_cift') or 3000)
    op_ids = seed_operations_from_chain(sqlite_con, plan_id, chain, qty)

    enj_op_id = None
    for oid, step in zip(op_ids, chain):
        if step['proses_kod'] == '26':
            enj_op_id = oid
            break
    if not enj_op_id:
        raise RuntimeError('Enjeksiyon (26) operation oluşturulamadı')

    res_count = map_legacy_enj_to_operation(sqlite_con, enj_op_id, legacy)
    sqlite_con.commit()

    return {
        'plan_id': plan_id,
        'operation_ids': op_ids,
        'enj_operation_id': enj_op_id,
        'reservation_count': res_count,
        'proses_chain': chain,
        'legacy_plan_id': legacy_plan_id,
    }


def fetch_plan_bundle(con: sqlite3.Connection, plan_id: int) -> dict:
    header = con.execute(
        f'SELECT * FROM {HEADER_TABLE} WHERE id=?', (int(plan_id),),
    ).fetchone()
    ops = con.execute(
        f'SELECT * FROM {OPERATION_TABLE} WHERE plan_id=? ORDER BY sequence_no',
        (int(plan_id),),
    ).fetchall()
    reservations = []
    for op in ops:
        oid = op['id'] if isinstance(op, sqlite3.Row) else op[0]
        rows = con.execute(
            f'SELECT * FROM {RESERVATION_TABLE} WHERE operation_id=? ORDER BY unit_no',
            (int(oid),),
        ).fetchall()
        reservations.extend([dict(r) for r in rows])
    return {
        'header': dict(header) if header else None,
        'operations': [dict(o) for o in ops],
        'reservations': reservations,
    }

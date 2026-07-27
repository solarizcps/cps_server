# -*- coding: utf-8 -*-
"""Gerçek üretim KG okuma — nexgen_rf_kullanim tek kaynak."""
from __future__ import annotations

import sqlite3


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def uretilen_kg_siparis(con: sqlite3.Connection, planlama_siparis_id: int) -> float:
    """
    planlama_siparis_id için rf_kullanim toplamı.

    Öncelik:
    1) nexgen_uretim_plan.planlama_siparis_id join
    2) Aynı siparis_no'lu planlarda planlama_siparis_id kopuk/boş ise siparis_no join
    """
    if not _tablo_var(con, 'nexgen_rf_kullanim'):
        return 0.0
    if not planlama_siparis_id:
        return 0.0

    siparis_no = None
    if _tablo_var(con, 'nexgen_planlama_siparis'):
        ps = con.execute(
            'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?',
            (planlama_siparis_id,),
        ).fetchone()
        if ps:
            siparis_no = (ps['siparis_no'] or '').strip() or None

    plan_cols: list[str] = []
    if _tablo_var(con, 'nexgen_uretim_plan'):
        plan_cols = [
            c[1] for c in con.execute('PRAGMA table_info(nexgen_uretim_plan)').fetchall()
        ]

    kg = 0.0
    if 'planlama_siparis_id' in plan_cols:
        row = con.execute(
            """
            SELECT ROUND(COALESCE(SUM(k.miktar_kg), 0), 3) AS kg
            FROM nexgen_rf_kullanim k
            JOIN nexgen_uretim_plan np ON np.id = k.siparis_id
            WHERE k.aktif = 1 AND np.planlama_siparis_id = ?
            """,
            (planlama_siparis_id,),
        ).fetchone()
        kg = float(row['kg'] or 0) if row else 0.0

    if kg > 0.001:
        return kg

    if siparis_no and 'siparis_no' in plan_cols:
        row = con.execute(
            """
            SELECT ROUND(COALESCE(SUM(k.miktar_kg), 0), 3) AS kg
            FROM nexgen_rf_kullanim k
            JOIN nexgen_uretim_plan np ON np.id = k.siparis_id
            WHERE k.aktif = 1
              AND np.siparis_no = ?
              AND (
                    np.planlama_siparis_id IS NULL
                    OR np.planlama_siparis_id = ?
                    OR np.planlama_siparis_id != ?
              )
            """,
            (siparis_no, planlama_siparis_id, planlama_siparis_id),
        ).fetchone()
        kg = float(row['kg'] or 0) if row else 0.0

    return kg if kg > 0.001 else 0.0

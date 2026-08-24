# -*- coding: utf-8 -*-
"""Plan kalem geofence ziyaret durumu — GPS P3."""
from __future__ import annotations

import json
import sqlite3

from modules.planlama.arac_takip_repo import get_conn


def geofence_tables_ready() -> bool:
    con = get_conn()
    try:
        return bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_is_ziyaret_durum'",
        ).fetchone())
    finally:
        con.close()


def get_visit_state(plan_is_id: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            'SELECT * FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?',
            (plan_is_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def upsert_visit_state(row: dict) -> dict:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        existing = con.execute(
            'SELECT id FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?',
            (row['plan_is_id'],),
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE arac_plan_is_ziyaret_durum SET
                    state=?, consecutive_inside=?, consecutive_outside=?,
                    arrived_at=?, departed_at=?, dwell_seconds=?,
                    last_gps_snapshot_id=?, result_status=?, updated_at=?
                WHERE plan_is_id=?
                """,
                (
                    row['state'], row['consecutive_inside'], row['consecutive_outside'],
                    row.get('arrived_at'), row.get('departed_at'), row.get('dwell_seconds'),
                    row.get('last_gps_snapshot_id'), row.get('result_status'), row['updated_at'],
                    row['plan_is_id'],
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO arac_plan_is_ziyaret_durum (
                    plan_id, plan_is_id, arac_external_id, kayitli_yer_id,
                    state, geofence_radius_m, exit_radius_m,
                    consecutive_inside, consecutive_outside,
                    arrived_at, departed_at, dwell_seconds,
                    last_gps_snapshot_id, result_status, updated_at, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row['plan_id'], row['plan_is_id'], row['arac_external_id'],
                    row.get('kayitli_yer_id'),
                    row['state'], row.get('geofence_radius_m', 200),
                    row.get('exit_radius_m', 250),
                    row['consecutive_inside'], row['consecutive_outside'],
                    row.get('arrived_at'), row.get('departed_at'), row.get('dwell_seconds'),
                    row.get('last_gps_snapshot_id'), row.get('result_status'),
                    row['updated_at'], row['created_at'],
                ),
            )
        con.commit()
        return get_visit_state(int(row['plan_is_id'])) or row
    finally:
        con.close()


def event_exists(plan_is_id: int, olay_turu: str) -> bool:
    con = get_conn()
    try:
        n = con.execute(
            """
            SELECT COUNT(*) FROM arac_plan_olay
            WHERE plan_is_id=? AND olay_turu=?
            """,
            (plan_is_id, olay_turu),
        ).fetchone()[0]
        return int(n) > 0
    finally:
        con.close()


def insert_geofence_event(
    *,
    plan_id: int,
    plan_is_id: int | None,
    arac_external_id: str,
    olay_turu: str,
    mesaj: str,
    metadata: dict | None,
    olay_zamani: str | None,
    created_at: str,
) -> int:
    con = get_conn()
    try:
        cur = con.execute(
            """
            INSERT INTO arac_plan_olay (
                plan_id, plan_is_id, arac_external_id, olay_turu, mesaj,
                metadata_json, olay_zamani, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                plan_id, plan_is_id, arac_external_id, olay_turu, mesaj,
                json.dumps(metadata or {}, ensure_ascii=False),
                olay_zamani, created_at,
            ),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()

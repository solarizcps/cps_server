# -*- coding: utf-8 -*-
"""Plan rota uyum durumu + olay kaydı (GPS P2)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.planlama.arac_takip_repo import get_conn


def deviation_tables_ready() -> bool:
    con = get_conn()
    try:
        return bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_rota_uyum_durum'",
        ).fetchone())
    finally:
        con.close()


def get_deviation_state(plan_id: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            'SELECT * FROM arac_rota_uyum_durum WHERE plan_id=?', (plan_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def upsert_deviation_state(row: dict[str, Any]) -> dict:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        existing = con.execute(
            'SELECT id FROM arac_rota_uyum_durum WHERE plan_id=?', (row['plan_id'],),
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE arac_rota_uyum_durum SET
                    arac_external_id=?, route_snapshot_id=?, state=?,
                    last_gps_snapshot_id=?, last_gps_timestamp=?,
                    current_deviation_m=?, max_deviation_m=?,
                    consecutive_outside=?, consecutive_inside=?,
                    deviation_started_at=?, recovered_at=?, updated_at=?
                WHERE plan_id=?
                """,
                (
                    row['arac_external_id'], row.get('route_snapshot_id'), row['state'],
                    row.get('last_gps_snapshot_id'), row.get('last_gps_timestamp'),
                    row.get('current_deviation_m'), row.get('max_deviation_m'),
                    row.get('consecutive_outside', 0), row.get('consecutive_inside', 0),
                    row.get('deviation_started_at'), row.get('recovered_at'), row['updated_at'],
                    row['plan_id'],
                ),
            )
            row_id = int(existing['id'])
        else:
            cur = con.execute(
                """
                INSERT INTO arac_rota_uyum_durum (
                    plan_id, arac_external_id, route_snapshot_id, state,
                    last_gps_snapshot_id, last_gps_timestamp,
                    current_deviation_m, max_deviation_m,
                    consecutive_outside, consecutive_inside,
                    deviation_started_at, recovered_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row['plan_id'], row['arac_external_id'], row.get('route_snapshot_id'),
                    row['state'], row.get('last_gps_snapshot_id'), row.get('last_gps_timestamp'),
                    row.get('current_deviation_m'), row.get('max_deviation_m'),
                    row.get('consecutive_outside', 0), row.get('consecutive_inside', 0),
                    row.get('deviation_started_at'), row.get('recovered_at'), row['updated_at'],
                ),
            )
            row_id = int(cur.lastrowid)
        con.commit()
        out = get_deviation_state(row['plan_id']) or {}
        out['id'] = row_id
        return out
    finally:
        con.close()


def count_plan_events(plan_id: int, olay_turu: str) -> int:
    con = get_conn()
    try:
        return con.execute(
            'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_id=? AND olay_turu=?',
            (plan_id, olay_turu),
        ).fetchone()[0]
    finally:
        con.close()


def insert_plan_event(
    *,
    plan_id: int,
    arac_external_id: str,
    olay_turu: str,
    mesaj: str,
    metadata: dict | None = None,
    olay_zamani: str | None = None,
    created_at: str,
    created_by: int | None = None,
) -> int:
    con = get_conn()
    try:
        cur = con.execute(
            """
            INSERT INTO arac_plan_olay (
                plan_id, arac_external_id, olay_turu, mesaj,
                metadata_json, olay_zamani, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                plan_id, arac_external_id, olay_turu, mesaj,
                json.dumps(metadata or {}, ensure_ascii=False),
                olay_zamani, created_at, created_by,
            ),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def get_gps_snapshot_by_id(snapshot_id: int) -> dict | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            'SELECT * FROM arac_gps_snapshot WHERE id=?', (snapshot_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def list_new_gps_snapshots_since(last_id: int = 0, limit: int = 200) -> list[dict]:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT * FROM arac_gps_snapshot
            WHERE id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (last_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()

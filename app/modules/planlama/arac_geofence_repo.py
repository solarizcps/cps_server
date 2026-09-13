# -*- coding: utf-8 -*-
"""Plan kalem geofence ziyaret durumu — GPS P3."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

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
        return get_visit_state_conn(con, plan_is_id)
    finally:
        con.close()


def get_visit_state_conn(con: sqlite3.Connection, plan_is_id: int) -> dict | None:
    con.row_factory = sqlite3.Row
    row = con.execute(
        'SELECT * FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?',
        (plan_is_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_visit_state(row: dict) -> dict:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        upsert_visit_state_conn(con, row)
        con.commit()
        return get_visit_state_conn(con, int(row['plan_is_id'])) or row
    finally:
        con.close()


def upsert_visit_state_conn(con: sqlite3.Connection, row: dict) -> None:
    existing = con.execute(
        'SELECT id FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?',
        (row['plan_is_id'],),
    ).fetchone()
    exit_m = row.get('exit_radius_m', 300)
    enter_m = row.get('geofence_radius_m', 200)
    if existing:
        con.execute(
            """
            UPDATE arac_plan_is_ziyaret_durum SET
                state=?, consecutive_inside=?, consecutive_outside=?,
                arrived_at=?, departed_at=?, dwell_seconds=?,
                last_gps_snapshot_id=?, result_status=?, updated_at=?,
                exit_radius_m=?, geofence_radius_m=?
            WHERE plan_is_id=?
            """,
            (
                row['state'], row['consecutive_inside'], row['consecutive_outside'],
                row.get('arrived_at'), row.get('departed_at'), row.get('dwell_seconds'),
                row.get('last_gps_snapshot_id'), row.get('result_status'), row['updated_at'],
                exit_m, enter_m,
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
                row['state'], enter_m, exit_m,
                row['consecutive_inside'], row['consecutive_outside'],
                row.get('arrived_at'), row.get('departed_at'), row.get('dwell_seconds'),
                row.get('last_gps_snapshot_id'), row.get('result_status'),
                row['updated_at'], row['created_at'],
            ),
        )


def event_exists(plan_is_id: int, olay_turu: str) -> bool:
    con = get_conn()
    try:
        return event_exists_conn(con, plan_is_id, olay_turu)
    finally:
        con.close()


def event_exists_conn(con: sqlite3.Connection, plan_is_id: int, olay_turu: str) -> bool:
    n = con.execute(
        """
        SELECT COUNT(*) FROM arac_plan_olay
        WHERE plan_is_id=? AND olay_turu=?
        """,
        (plan_is_id, olay_turu),
    ).fetchone()[0]
    return int(n) > 0


def geofence_metadata_event_exists_conn(
    con: sqlite3.Connection,
    plan_is_id: int,
    olay_turu: str,
    metadata_kind: str,
) -> bool:
    rows = con.execute(
        """
        SELECT metadata_json FROM arac_plan_olay
        WHERE plan_is_id=? AND olay_turu=?
        """,
        (plan_is_id, olay_turu),
    ).fetchall()
    for (raw,) in rows:
        try:
            meta = json.loads(raw or '{}')
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
        if meta.get('geofence_kind') == metadata_kind:
            return True
    return False


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
        eid = insert_geofence_event_conn(
            con,
            plan_id=plan_id,
            plan_is_id=plan_is_id,
            arac_external_id=arac_external_id,
            olay_turu=olay_turu,
            mesaj=mesaj,
            metadata=metadata,
            olay_zamani=olay_zamani,
            created_at=created_at,
        )
        con.commit()
        return eid
    finally:
        con.close()


def insert_geofence_event_conn(
    con: sqlite3.Connection,
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
    return int(cur.lastrowid)


@contextmanager
def geofence_write_transaction() -> Iterator[sqlite3.Connection]:
    """Single connection with BEGIN IMMEDIATE — caller commits or rollbacks."""
    con = get_conn()
    con.row_factory = sqlite3.Row
    con.execute('BEGIN IMMEDIATE')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

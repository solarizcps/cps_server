# -*- coding: utf-8 -*-
"""RM snapshot satır arama — web GET Korgün çağırmaz."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .rm_config import DIRECTION_PAYABLE, DIRECTION_RECEIVABLE, get_rm_path
from .rm_db import get_active_snapshot_id, get_snapshot_header, open_readonly


def _parse_enrichment(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def lookup_snapshot_row(
    direction: str,
    location: str,
    cari_kod: str,
    para_birimi: str = "TRY",
    rm_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Aktif snapshot'tan tek cari satırı + published_at meta.
    Bulunamazsa None.
    """
    db_path = rm_path or get_rm_path()
    loc = (location or "").strip().upper()
    ck = (cari_kod or "").strip()
    pb = (para_birimi or "TRY").strip().upper()

    with open_readonly(db_path) as conn:
        if conn is None:
            return None
        snap_id = get_active_snapshot_id(conn, direction)
        if not snap_id:
            return None
        hdr = get_snapshot_header(conn, snap_id)
        row = conn.execute(
            """
            SELECT *
            FROM rm_snapshot_row
            WHERE snapshot_id = ? AND location = ? AND cari_kod = ? AND para_birimi = ?
            LIMIT 1
            """,
            (snap_id, loc, ck, pb),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT *
                FROM rm_snapshot_row
                WHERE snapshot_id = ? AND location = ? AND cari_kod = ?
                ORDER BY ABS(CAST(net AS REAL)) DESC
                LIMIT 1
                """,
                (snap_id, loc, ck),
            ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT *
                FROM rm_snapshot_row
                WHERE snapshot_id = ? AND cari_kod = ? AND para_birimi = ?
                ORDER BY ABS(CAST(net AS REAL)) DESC
                LIMIT 1
                """,
                (snap_id, ck, pb),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        enrich = _parse_enrichment(data.get("enrichment_json"))
        return {
            "row": data,
            "enrichment": enrich,
            "snapshot_id": snap_id,
            "published_at": hdr["published_at"] if hdr else None,
            "direction": direction,
        }


def lookup_receivable_row(
    location: str,
    cari_kod: str,
    para_birimi: str = "TRY",
    rm_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return lookup_snapshot_row(DIRECTION_RECEIVABLE, location, cari_kod, para_birimi, rm_path)


def lookup_payable_row(
    location: str,
    cari_kod: str,
    para_birimi: str = "TRY",
    rm_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return lookup_snapshot_row(DIRECTION_PAYABLE, location, cari_kod, para_birimi, rm_path)

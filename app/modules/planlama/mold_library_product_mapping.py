# -*- coding: utf-8 -*-
"""PHASE_7L — Onaylı ürün-kalıp bağlantıları (preview additive)."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any

RELATION_TYPES = frozenset({
    "EXACT_MODEL",
    "APPROVED_ALIAS",
    "SUMMER_WINTER_SHARED_MOLD",
    "MANUAL_APPROVED",
})


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(code: str) -> str:
    return (code or "").strip().upper()


def _family_code(order_model_code: str) -> str:
    """Strip known variant suffixes — never auto-apply without user approval."""
    c = _norm(order_model_code)
    for suffix in ("-KRK", "-KURK", "-YAZ", "-WINTER"):
        if c.endswith(suffix):
            return c[: -len(suffix)]
    return c


def table_exists(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mold_library_product_mapping'"
    ).fetchone()
    return bool(row)


def list_active_for_order(con: sqlite3.Connection, order_model_code: str) -> list[dict]:
    if not table_exists(con):
        return []
    rows = con.execute(
        """SELECT m.*, ml.model_code AS library_model_code, ml.visible_mold_code
           FROM mold_library_product_mapping m
           JOIN mold_library_mold ml ON ml.library_uuid = m.mold_library_uuid
           WHERE m.is_active=1 AND UPPER(m.order_model_code)=?
           ORDER BY m.created_at DESC""",
        (_norm(order_model_code),),
    ).fetchall()
    return [dict(r) for r in rows]


def approved_uuid_set(con: sqlite3.Connection, order_model_code: str) -> set[str]:
    return {r["mold_library_uuid"] for r in list_active_for_order(con, order_model_code)}


def has_approved_mapping(con: sqlite3.Connection, order_model_code: str, library_uuid: str) -> bool:
    if not table_exists(con):
        return False
    row = con.execute(
        """SELECT 1 FROM mold_library_product_mapping
           WHERE is_active=1 AND UPPER(order_model_code)=? AND mold_library_uuid=?""",
        (_norm(order_model_code), library_uuid),
    ).fetchone()
    return bool(row)


def _audit_mapping(
    con: sqlite3.Connection,
    *,
    library_uuid: str,
    action: str,
    actor: str,
    before: dict | None,
    after: dict | None,
    reason: str | None,
) -> None:
    con.execute(
        """INSERT INTO mold_library_audit
           (mold_library_uuid, action, changed_at, changed_by, change_reason, before_json, after_json)
           VALUES (?,?,?,?,?,?,?)""",
        (
            library_uuid,
            action,
            _now(),
            actor,
            reason,
            __import__("json").dumps(before, ensure_ascii=False) if before else None,
            __import__("json").dumps(after, ensure_ascii=False) if after else None,
        ),
    )


def create_mapping(
    con: sqlite3.Connection,
    *,
    order_model_code: str,
    mold_library_uuid: str,
    relation_type: str,
    product_variant: str = "",
    approved_by: str,
    approval_reason: str | None = None,
) -> dict:
    """Explicit user-approved mapping only — idempotent on unique key."""
    if not table_exists(con):
        raise RuntimeError("mold_library_product_mapping tablosu mevcut değil — migration 195 gerekli.")
    rt = (relation_type or "MANUAL_APPROVED").strip().upper()
    if rt not in RELATION_TYPES:
        raise ValueError(f"Geçersiz relation_type: {relation_type}")
    om = _norm(order_model_code)
    if not om:
        raise ValueError("order_model_code zorunludur.")
    lib = con.execute(
        "SELECT library_uuid, model_code, visible_mold_code FROM mold_library_mold WHERE library_uuid=? AND is_archived=0",
        (mold_library_uuid,),
    ).fetchone()
    if not lib:
        raise ValueError("Kalıp kütüphane kaydı bulunamadı.")
    pv = (product_variant or "").strip()
    fam = _family_code(om)
    existing = con.execute(
        """SELECT * FROM mold_library_product_mapping
           WHERE UPPER(order_model_code)=? AND mold_library_uuid=? AND product_variant=?""",
        (om, mold_library_uuid, pv),
    ).fetchone()
    ts = _now()
    if existing:
        ex = dict(existing)
        if ex.get("is_active"):
            return ex
        con.execute(
            """UPDATE mold_library_product_mapping SET is_active=1, relation_type=?, approved_by=?,
               approval_reason=?, updated_at=? WHERE id=?""",
            (rt, approved_by, approval_reason, ts, ex["id"]),
        )
        row = con.execute("SELECT * FROM mold_library_product_mapping WHERE id=?", (ex["id"],)).fetchone()
        after = dict(row)
        _audit_mapping(con, library_uuid=mold_library_uuid, action="PRODUCT_MAPPING_REACTIVATE",
                       actor=approved_by, before=ex, after=after, reason=approval_reason)
        return after

    con.execute(
        """INSERT INTO mold_library_product_mapping
           (order_model_code, normalized_product_family_code, mold_library_uuid, relation_type,
            product_variant, approved_by, approval_reason, is_active, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,1,?,?)""",
        (om, fam or None, mold_library_uuid, rt, pv, approved_by, approval_reason, ts, ts),
    )
    row = con.execute(
        "SELECT * FROM mold_library_product_mapping WHERE rowid=last_insert_rowid()"
    ).fetchone()
    after = dict(row)
    _audit_mapping(con, library_uuid=mold_library_uuid, action="PRODUCT_MAPPING_CREATE",
                   actor=approved_by, before=None, after=after, reason=approval_reason)
    return after


def recommend_reason(
    con: sqlite3.Connection,
    *,
    order_model_code: str,
    library_uuid: str,
    library_model_code: str,
) -> tuple[bool, str | None]:
    """Return (is_recommended, reason_label)."""
    om = _norm(order_model_code)
    lm = _norm(library_model_code)
    if om and lm == om:
        return True, "Tam model eşleşmesi"
    if has_approved_mapping(con, om, library_uuid):
        rows = list_active_for_order(con, om)
        for r in rows:
            if r["mold_library_uuid"] == library_uuid:
                rt = r.get("relation_type") or "MANUAL_APPROVED"
                labels = {
                    "EXACT_MODEL": "Tam model eşleşmesi",
                    "APPROVED_ALIAS": "Onaylı ürün-kalıp bağlantısı",
                    "SUMMER_WINTER_SHARED_MOLD": "Onaylı yazlık/kürklü ortak kalıp",
                    "MANUAL_APPROVED": "Onaylı ürün-kalıp bağlantısı",
                }
                return True, labels.get(rt, "Onaylı bağlantı")
    return False, None

# -*- coding: utf-8 -*-
"""Enjeksiyon kurulum read adapter — SINGLE_LEGACY parent projection vs child canonical."""
from __future__ import annotations

import json
import sqlite3

KURULUM_TABLO = "uretim_model_plan_enj_kurulum"
ISTASYON_TABLO = "uretim_model_plan_enj_kurulum_istasyon"

CAPACITY_SOURCES_CONFIRMED = frozenset({
    "OPERATION_REPORT_7D_CONFIRMED",
    "OPERATION_REPORT_30D_CONFIRMED",
    "OPERATION_REPORT_90D_CONFIRMED",
    "MANUAL_CONFIRMED",
})

CAPACITY_SOURCE_NONE = "NONE"


def _kurulum_tablosu_var(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (KURULUM_TABLO,),
    ).fetchone())


def _parent_has_enj(parent: dict) -> bool:
    return bool(parent.get("enj_makine_id")) and (parent.get("enj_slot") or "").upper() in ("A", "B")


def _parse_snapshot(raw) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def project_single_legacy(parent: dict) -> dict:
    """Parent enj_* alanlarından tek kurulum projeksiyonu."""
    snap = _parse_snapshot(parent.get("enj_kapasite_snapshot"))
    return {
        "projection_mode": "SINGLE_LEGACY",
        "kurulum_id": None,
        "plan_id": parent.get("id"),
        "kurulum_sira": 1,
        "durum": "AKTIF" if parent.get("aktif") else "IPTAL",
        "aktif": int(parent.get("aktif") or 0),
        "enj_makine_id": parent.get("enj_makine_id"),
        "enj_slot": (parent.get("enj_slot") or "").upper() or None,
        "mold_library_uuid": parent.get("mold_library_uuid"),
        "enj_kalip_id": parent.get("enj_kalip_id"),
        "enj_kalip_kod": parent.get("enj_kalip_kod"),
        "kullanilan_kalip_adedi": None,
        "kalip_ici_cift": parent.get("enj_kalip_basi_cift"),
        "tur_basi_cift": parent.get("enj_tur_cift"),
        "kurulum_ayrilan_cift": parent.get("enj_planlanacak_cift"),
        "enj_calisma_modu": parent.get("enj_calisma_modu"),
        "gunduz_tur": snap.get("manual_reference_gunduz") if snap else None,
        "gece_tur": snap.get("manual_reference_gece") if snap else None,
        "hafta_sonu_calisma": parent.get("enj_hafta_sonu_calisma"),
        "capacity_source_gunduz": CAPACITY_SOURCE_NONE,
        "capacity_source_gece": CAPACITY_SOURCE_NONE,
        "plan_baslangic": parent.get("enj_plan_baslangic") or parent.get("plan_baslangic"),
        "plan_bitis": parent.get("enj_plan_bitis") or parent.get("plan_bitis"),
        "tahmini_bitis": parent.get("enj_plan_bitis"),
        "kapasite_snapshot_json": parent.get("enj_kapasite_snapshot"),
        "mold_library_snapshot_json": parent.get("mold_library_snapshot_json"),
        "enj_istasyonlar": parent.get("enj_istasyonlar") or [],
    }


def _child_row_to_dict(row: sqlite3.Row | dict) -> dict:
    d = dict(row)
    d["projection_mode"] = "MULTI_SETUP"
    d["kurulum_id"] = d.pop("id", None)
    return d


def resolve_plan_kurulumlar(
    con: sqlite3.Connection,
    plan_id: int,
    parent_row: dict | None = None,
) -> list[dict]:
    """Child yoksa SINGLE_LEGACY; child varsa child kanonik."""
    if parent_row is None:
        row = con.execute(
            "SELECT * FROM uretim_model_plan WHERE id=?", (int(plan_id),)
        ).fetchone()
        if row is None:
            return []
        parent_row = dict(row)

    if not _kurulum_tablosu_var(con):
        if not _parent_has_enj(parent_row):
            return []
        legacy = project_single_legacy(parent_row)
        if parent_row.get("enj_istasyonlar"):
            legacy["enj_istasyonlar"] = parent_row["enj_istasyonlar"]
        return [legacy]

    children = con.execute(
        f"""
        SELECT * FROM {KURULUM_TABLO}
         WHERE plan_id=? AND aktif=1
         ORDER BY kurulum_sira ASC, id ASC
        """,
        (int(plan_id),),
    ).fetchall()

    if not children:
        if not _parent_has_enj(parent_row):
            return []
        legacy = project_single_legacy(parent_row)
        if parent_row.get("enj_istasyonlar"):
            legacy["enj_istasyonlar"] = parent_row["enj_istasyonlar"]
        return [legacy]

    out = [_child_row_to_dict(c) for c in children]
    for kur in out:
        kid = kur.get("kurulum_id")
        if kid and _istasyon_tablosu_var(con):
            ist = con.execute(
                f"""
                SELECT istasyon_no FROM {ISTASYON_TABLO}
                 WHERE kurulum_id=? ORDER BY istasyon_no
                """,
                (int(kid),),
            ).fetchall()
            kur["enj_istasyonlar"] = [int(r[0]) for r in ist]
    return out


def _istasyon_tablosu_var(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (ISTASYON_TABLO,),
    ).fetchone())


def capacity_source_is_confirmed(source: str | None) -> bool:
    return (source or "") in CAPACITY_SOURCES_CONFIRMED

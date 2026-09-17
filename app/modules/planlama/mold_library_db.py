# -*- coding: utf-8 -*-
"""Mold Library — preview DB CRUD, import, audit (PHASE_5)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Config
from modules.planlama.mold_library_normalize import (
    build_business_key,
    derive_product_family_variant,
    normalize_fixture,
    normalize_product_type,
    normalize_record,
    normalize_seri_row,
)

SOURCE_SHA256 = "2AC3D6EA38E31EC700809A72761E18A53D48919254E96C390530B1EFA898CAC1"
FIXTURE_PATH = Path(r"C:\CPS_RECOVERY\MOLD_LIBRARY_PHASE_3_20260911_140505\fixture\mold_library_fixture.json")
LEGACY_MATRIX_PATH = Path(r"C:\CPS_RECOVERY\MOLD_LIBRARY_PHASE_1B_20260911_135434\legacy_match_matrix_v1b.json")
# Phase 3 assets/images is the canonical source for fixture images
PHASE3_ASSETS_DIR = Path(r"C:\CPS_RECOVERY\MOLD_LIBRARY_PHASE_3_20260911_140505\assets\images")
STATIC_KALIP_DIR = Path(__file__).resolve().parents[2] / "static" / "kalip_gorseller"

import os as _os
# MOLD_LIBRARY_IMAGE_DIR env var allows 42A7+ runtime isolation without code restart
_RUNTIME_IMAGE_DIR_ENV = _os.environ.get("MOLD_LIBRARY_IMAGE_DIR", "").strip()
RUNTIME_IMAGE_DIR = (
    Path(_RUNTIME_IMAGE_DIR_ENV)
    if _RUNTIME_IMAGE_DIR_ENV
    else Path(__file__).resolve().parents[2] / "runtime" / "mold_library_images"
)

POLI_ACTIVE = False
PLAN_SELECTION_ENABLED = (
    _os.environ.get("MOLD_LIBRARY_PLAN_SELECTION_ENABLED", "true").lower() == "true"
)  # PHASE_6C: preview pilot aktif (env var MOLD_LIBRARY_PLAN_SELECTION_ENABLED)


def db_path() -> str:
    return Config.MOCK_DB_PATH


def runtime_image_dir() -> Path:
    # Re-read env each call so MOLD_LIBRARY_IMAGE_DIR override takes effect without restart
    env_dir = _os.environ.get("MOLD_LIBRARY_IMAGE_DIR", "").strip()
    d = Path(env_dir) if env_dir else (Path(__file__).resolve().parents[2] / "runtime" / "mold_library_images")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _column_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def _audit(con: sqlite3.Connection, uuid_: str, action: str, user: str, reason: str | None,
           before: dict | None, after: dict | None, changes: dict | None = None) -> None:
    con.execute(
        """INSERT INTO mold_library_audit
           (mold_library_uuid, action, changed_at, changed_by, change_reason,
            before_json, after_json, field_changes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            uuid_, action, _now(), user, reason,
            json.dumps(before, ensure_ascii=False) if before else None,
            json.dumps(after, ensure_ascii=False) if after else None,
            json.dumps(changes, ensure_ascii=False) if changes else None,
        ),
    )


def _field_diff(before: dict, after: dict) -> dict:
    changes = {}
    for k in sorted(set(before.keys()) | set(after.keys())):
        if k.startswith("_"):
            continue
        bv, av = before.get(k), after.get(k)
        if bv != av:
            changes[k] = {"before": bv, "after": av}
    return changes


def _resolve_source_image(asset: str | None) -> Path | None:
    if not asset:
        return None
    fname = Path(asset).name
    # Security: reject path traversal
    if ".." in fname or "/" in fname or "\\" in fname:
        return None
    # Allowed extensions only
    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    if Path(fname).suffix.lower() not in allowed:
        return None
    # Priority 1: static/kalip_gorseller (production drop-in)
    p = STATIC_KALIP_DIR / fname
    if p.is_file():
        return p
    # Priority 2: Phase 3 assets/images (recovery source, fixture seed)
    p2 = PHASE3_ASSETS_DIR / fname
    if p2.is_file():
        return p2
    return None


def _store_image_file(content: bytes, ext: str, sha: str) -> tuple[str, str]:
    """Returns (storage_key, absolute_path). Dedup by sha256 filename."""
    runtime_image_dir()
    key = f"{sha[:16]}{ext.lower()}"
    dest = RUNTIME_IMAGE_DIR / key
    if not dest.is_file():
        dest.write_bytes(content)
    return key, str(dest)


def _copy_import_image(rec: dict, lib_uuid: str) -> tuple[str | None, str | None, str | None]:
    img = rec.get("image") or {}
    sha = img.get("media_sha256") or img.get("image_sha256")
    asset = rec.get("image_asset")
    src = _resolve_source_image(asset)
    if not src and img.get("display_asset"):
        src = _resolve_source_image(img.get("display_asset"))
    if not src:
        return None, None, None
    content = src.read_bytes()
    sha = sha or hashlib.sha256(content).hexdigest().upper()
    key, _ = _store_image_file(content, src.suffix, sha)
    return key, src.name, sha


def _load_series(con: sqlite3.Connection, lib_uuid: str) -> list[dict]:
    rows = con.execute(
        """SELECT display_order, numara_asorti, kalip_adedi, cevrim_basina_cikis_cift, source_col
           FROM mold_library_series WHERE mold_library_uuid=? ORDER BY display_order""",
        (lib_uuid,),
    ).fetchall()
    return [
        {
            "col": r["source_col"],
            "seri_label": r["numara_asorti"],
            "goz_adet": r["kalip_adedi"],
            "kalip_adedi": r["kalip_adedi"],
            "kalip_cikisi_row": r["cevrim_basina_cikis_cift"],
        }
        for r in rows
    ]


def _load_primary_image(con: sqlite3.Connection, lib_uuid: str) -> sqlite3.Row | None:
    return con.execute(
        """SELECT storage_key, original_filename, sha256, mime_type
           FROM mold_library_image WHERE mold_library_uuid=? AND is_primary=1
           ORDER BY display_order LIMIT 1""",
        (lib_uuid,),
    ).fetchone()


def _row_to_record(row: sqlite3.Row, seri: list[dict], img: sqlite3.Row | None) -> dict:
    rec = {
        "library_uuid": row["library_uuid"],
        "source_seq": row["source_seq"] if row["source_seq"] is not None else row["id"],
        "source_row_main": row["source_main_row"],
        "model_kod": row["model_code"],
        "visible_mold_code": row["visible_mold_code"],
        "envanter_kod": row["inventory_code"],
        "product_category": row["product_category"] or row["product_variant"],
        "product_type_raw": row["product_type_raw"],
        "product_family": row["product_family"],
        "product_variant": row["product_variant"],
        "asorti": row["assortment"],
        "durum": row["working_status"],
        "material_group": row["material_group"],
        "component_role": row["component_role"],
        "component_role_source": row["component_role_source"],
        "separate_upper_mold": (None if row["separate_upper_mold"] is None else bool(row["separate_upper_mold"])),
        "cift_miktari": row["pairs_per_cycle"],
        "gramaj_gr": row["weight_grams"],
        "gramaj_ref_numara": row["weight_reference_size"],
        "pisirme_suresi_sn": row["cooking_time_seconds"] if "cooking_time_seconds" in row.keys() else None,
        "cycle_time_dk": row["cycle_time_minutes"],
        "not": row["note"],
        "review_status": row["review_status"],
        "activation_block_reason": row["activation_block_reason"],
        "legacy_enj_kalip_id": row["legacy_enj_kalip_id"],
        "is_archived": bool(row["is_archived"]),
        "row_version": row["row_version"],
        "source_file_sha256": row["source_file_sha256"],
        "record_origin": "IMPORTED" if row["source_file_sha256"] == SOURCE_SHA256 else "FORM",
        "is_test_record": str(row["visible_mold_code"] or "").startswith("ADEM-E2E-")
            or str(row["model_code"] or "").startswith("ADEM-E2E-"),
        "business_key": row["business_key"],
        "seri_dagilimi": seri,
    }
    if img:
        rec["image_storage_key"] = img["storage_key"]
        rec["image_sha256"] = img["sha256"]
        rec["image_asset"] = img["storage_key"]
    elif row["image_present"]:
        rec["image_present_flag"] = True
    return normalize_record(rec)


def list_records(*, include_archived: bool = False) -> list[dict]:
    con = _connect()
    try:
        q = "SELECT * FROM mold_library_mold"
        if not include_archived:
            q += " WHERE is_archived=0"
        q += " ORDER BY COALESCE(source_seq, id)"
        rows = con.execute(q).fetchall()
        out = []
        for row in rows:
            seri = _load_series(con, row["library_uuid"])
            img = _load_primary_image(con, row["library_uuid"])
            out.append(_row_to_record(row, seri, img))
        return out
    finally:
        con.close()


def get_record_by_uuid(lib_uuid: str) -> dict | None:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM mold_library_mold WHERE library_uuid=?", (lib_uuid,)).fetchone()
        if not row:
            return None
        seri = _load_series(con, lib_uuid)
        img = _load_primary_image(con, lib_uuid)
        return _row_to_record(row, seri, img)
    finally:
        con.close()


def get_record_by_source_seq(source_seq: int) -> dict | None:
    con = _connect()
    try:
        row = con.execute(
            "SELECT * FROM mold_library_mold WHERE source_seq=? OR (source_seq IS NULL AND id=?)",
            (source_seq, source_seq),
        ).fetchone()
        if not row:
            return None
        seri = _load_series(con, row["library_uuid"])
        img = _load_primary_image(con, row["library_uuid"])
        return _row_to_record(row, seri, img)
    finally:
        con.close()


def get_audit_trail(lib_uuid: str, limit: int = 50) -> list[dict]:
    con = _connect()
    try:
        rows = con.execute(
            """SELECT id, action, changed_at, changed_by, change_reason, field_changes
               FROM mold_library_audit WHERE mold_library_uuid=?
               ORDER BY id DESC LIMIT ?""",
            (lib_uuid, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _series_missing_qty(seri: list) -> bool:
    """True when any series row lacks verified kalıp adedi (Excel goz_adet or DB kalip_adedi)."""
    if not seri:
        return False
    for s in seri:
        if s.get("kalip_adedi") is None and s.get("goz_adet") is None:
            return True
    return False


def _classify_activation(rec: dict) -> tuple[str, str | None]:
    review_reasons: list[str] = []
    planning_block: list[str] = []
    library_ok = bool(rec.get("model_kod") and rec.get("visible_mold_code") and rec.get("material_group") == "EVA")
    if not library_ok:
        review_reasons.append("missing_basic_identity")
    if not rec.get("product_category"):
        review_reasons.append("missing_product_category")
    if rec.get("component_role") == "UNRESOLVED":
        review_reasons.append("component_role_not_evidence_backed")
    if not rec.get("legacy_enj_kalip_id"):
        review_reasons.append("no_legacy_mapping")
    if _series_missing_qty(rec.get("seri_dagilimi") or []):
        review_reasons.append("missing_series_qty")
    ws = rec.get("durum")
    planning_ok = library_ok and ws == "AKTIF"
    if ws != "AKTIF":
        planning_block.append("not_active_status")
        planning_ok = False
    if rec.get("component_role") == "UNRESOLVED":
        planning_block.append("component_role_not_evidence_backed")
        planning_ok = False
    if not rec.get("legacy_enj_kalip_id"):
        planning_block.append("no_legacy_mapping")
        planning_ok = False
    if review_reasons:
        return "REVIEW_REQUIRED", ";".join(sorted(set(review_reasons + planning_block))) or None
    if planning_ok:
        return "READY_FOR_PLANNING", None
    if library_ok:
        return "READY_FOR_LIBRARY", ";".join(sorted(set(planning_block))) or None
    return "REVIEW_REQUIRED", ";".join(sorted(set(review_reasons + planning_block))) or None


def _classify_activation_db(mold: dict, series: list[dict]) -> tuple[str, str | None]:
    """DB row + series rows → same activation rules as fixture import."""
    rec = {
        "model_kod": mold.get("model_code"),
        "visible_mold_code": mold.get("visible_mold_code"),
        "material_group": mold.get("material_group"),
        "product_category": mold.get("product_category"),
        "component_role": mold.get("component_role"),
        "legacy_enj_kalip_id": mold.get("legacy_enj_kalip_id"),
        "durum": mold.get("working_status"),
        "seri_dagilimi": [
            {"goz_adet": s.get("kalip_adedi"), "kalip_adedi": s.get("kalip_adedi")}
            for s in series
        ],
    }
    return _classify_activation(rec)


def reconcile_import_activation_status(
    con: sqlite3.Connection | None = None,
    *,
    user: str = "system_reconcile",
) -> dict[str, Any]:
    """Idempotent — re-evaluate review_status for all Excel-import molds from live DB series."""
    own_con = con is None
    if own_con:
        con = _connect()
    updated = 0
    samples: list[dict] = []
    try:
        if own_con:
            con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            "SELECT * FROM mold_library_mold WHERE source_file_sha256=?",
            (SOURCE_SHA256,),
        ).fetchall()
        for row in rows:
            mold = dict(row)
            uid = mold["library_uuid"]
            series = [
                dict(s)
                for s in con.execute(
                    """SELECT kalip_adedi FROM mold_library_series
                       WHERE mold_library_uuid=? ORDER BY display_order""",
                    (uid,),
                ).fetchall()
            ]
            status, block = _classify_activation_db(mold, series)
            cur_status = mold.get("review_status")
            cur_block = mold.get("activation_block_reason")
            if cur_status != status or (cur_block or None) != (block or None):
                con.execute(
                    """UPDATE mold_library_mold SET review_status=?, activation_block_reason=?,
                       updated_at=datetime('now'), updated_by=?
                       WHERE library_uuid=?""",
                    (status, block, user, uid),
                )
                updated += 1
                if mold.get("visible_mold_code") == "TR-24B11":
                    samples.append({
                        "library_uuid": uid,
                        "before": {"review_status": cur_status, "block": cur_block},
                        "after": {"review_status": status, "block": block},
                    })
        if own_con:
            con.commit()
    except Exception:
        if own_con:
            con.rollback()
        raise
    finally:
        if own_con:
            con.close()
    return {"checked": len(rows) if rows else 0, "updated": updated, "samples": samples}


def import_initial_records(*, user: str = "system_import") -> dict[str, Any]:
    """Idempotent ilk import — fixture + PHASE_1B normalize."""
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    records = normalize_fixture(raw.get("records", []))
    legacy_matrix = {
        r["source_row_main"]: r
        for r in json.loads(LEGACY_MATRIX_PATH.read_text(encoding="utf-8"))["records"]
    }

    con = _connect()
    inserted = series_n = images_n = legacy_n = 0
    reconcile_result: dict[str, Any] = {"checked": 0, "updated": 0}
    try:
        con.execute("BEGIN IMMEDIATE")
        for rec in records:
            existing = con.execute(
                "SELECT library_uuid, row_version FROM mold_library_mold WHERE source_file_sha256=? AND source_main_row=?",
                (SOURCE_SHA256, rec["source_row_main"]),
            ).fetchone()
            if existing:
                lib_uuid = existing["library_uuid"]
                continue

            raw_cat, norm_cat = normalize_product_type(rec.get("product_category"))
            family, variant = derive_product_family_variant(norm_cat)
            review_status, block = _classify_activation(rec)
            sep = rec.get("separate_upper_mold")
            sep_val = None if sep is None else (1 if sep else 0)
            bkey = build_business_key(
                rec.get("material_group", "EVA"), rec.get("model_kod", ""),
                rec.get("visible_mold_code", ""), variant or norm_cat, rec.get("asorti", ""),
            )
            lib_uuid = str(uuid.uuid4())
            con.execute(
                """INSERT INTO mold_library_mold (
                    library_uuid, material_group, legacy_enj_kalip_id, model_code, inventory_code,
                    visible_mold_code, product_type_raw, product_category, product_family, product_variant,
                    component_role, component_role_source, assortment, working_status,
                    separate_upper_mold, pairs_per_cycle, weight_reference_size, weight_grams,
                    cycle_time_minutes, note, image_present, source_file_sha256, source_main_row,
                    source_seq, business_key, review_status, activation_block_reason,
                    created_by, updated_by
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lib_uuid, rec.get("material_group") or "EVA", rec.get("legacy_enj_kalip_id"),
                    rec.get("model_kod"), rec.get("envanter_kod"), rec.get("visible_mold_code"),
                    raw_cat, variant or norm_cat, family, variant,
                    rec.get("component_role"), rec.get("component_role_source"),
                    rec.get("asorti"), rec.get("durum"), sep_val,
                    rec.get("cift_miktari"), rec.get("gramaj_ref_numara"), rec.get("gramaj_gr"),
                    rec.get("cycle_time_dk"), rec.get("not"),
                    1 if rec.get("image_asset") or (rec.get("image") or {}).get("matched") else 0,
                    SOURCE_SHA256, rec["source_row_main"], rec.get("source_seq"), bkey,
                    review_status, block, user, user,
                ),
            )
            inserted += 1

            for i, s in enumerate(rec.get("seri_dagilimi") or [], 1):
                norm_s = normalize_seri_row(s, rec)
                con.execute(
                    """INSERT OR IGNORE INTO mold_library_series
                       (mold_library_uuid, display_order, numara_asorti, kalip_adedi,
                        cevrim_basina_cikis_cift, source_col)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        lib_uuid, i, norm_s.get("numara_asorti") or norm_s.get("seri_label"),
                        norm_s.get("kalip_adedi"), norm_s.get("kalip_cikisi") or rec.get("cift_miktari"),
                        s.get("col"),
                    ),
                )
                series_n += 1

            if rec.get("image_asset") or (rec.get("image") or {}).get("matched"):
                key, orig, sha = _copy_import_image(rec, lib_uuid)
                if key:
                    con.execute(
                        """INSERT OR IGNORE INTO mold_library_image
                           (mold_library_uuid, storage_key, original_filename, sha256,
                            display_order, is_primary, source_anchor, match_method)
                           VALUES (?,?,?,?,1,1,?,?)""",
                        (
                            lib_uuid, key, orig, sha, str(rec["source_row_main"]),
                            (rec.get("image") or {}).get("match_method"),
                        ),
                    )
                    images_n += 1

            leg_id = rec.get("legacy_enj_kalip_id")
            if leg_id:
                leg_info = legacy_matrix.get(rec["source_row_main"], {})
                con.execute(
                    """INSERT OR IGNORE INTO mold_library_legacy_map
                       (mold_library_uuid, legacy_enj_kalip_id, match_status, match_evidence)
                       VALUES (?,?,?,?)""",
                    (
                        lib_uuid, leg_id,
                        leg_info.get("match_status", "LEGACY_EXACT_ONE_TO_ONE"),
                        json.dumps(leg_info.get("match_evidence", {}), ensure_ascii=False),
                    ),
                )
                legacy_n += 1

            _audit(con, lib_uuid, "IMPORT", user, "Initial EVA import", None, rec, None)

        reconcile_result = reconcile_import_activation_status(con, user=user)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    counts = snapshot_counts()
    return {
        "inserted_molds": inserted,
        "series_rows_touched": series_n,
        "images_touched": images_n,
        "legacy_maps_touched": legacy_n,
        "activation_reconcile": reconcile_result,
        **counts,
    }


def snapshot_counts() -> dict[str, int]:
    con = _connect()
    try:
        return {
            "mold_count": con.execute("SELECT COUNT(*) FROM mold_library_mold WHERE is_archived=0").fetchone()[0],
            "series_count": con.execute("SELECT COUNT(*) FROM mold_library_series").fetchone()[0],
            "image_count": con.execute("SELECT COUNT(*) FROM mold_library_image").fetchone()[0],
            "legacy_map_count": con.execute("SELECT COUNT(*) FROM mold_library_legacy_map").fetchone()[0],
            "missing_kalip_adedi": con.execute(
                "SELECT COUNT(*) FROM mold_library_series WHERE kalip_adedi IS NULL"
            ).fetchone()[0],
        }
    finally:
        con.close()


def create_mold(payload: dict, user: str, image_content: bytes | None = None,
                image_ext: str | None = None, image_sha: str | None = None) -> dict:
    mat = (payload.get("material_group") or "EVA").strip().upper()
    if mat == "POLI" and not POLI_ACTIVE:
        pass  # library-only, allowed
    is_draft = bool(payload.get("is_draft", False))
    model_kod = (payload.get("model_kod") or "").strip()
    mold_code = (payload.get("visible_mold_code") or "").strip()
    raw_cat = (payload.get("product_category") or "").strip()
    raw_stored, product_cat = normalize_product_type(raw_cat) if raw_cat else ("", "")
    family, variant = derive_product_family_variant(product_cat) if product_cat else ("", "")
    durum = "TASLAK" if is_draft else (payload.get("durum") or "AKTIF").strip().upper()
    asorti_bas, asorti_bit = payload.get("asorti_bas"), payload.get("asorti_bit")
    asorti = (f"{asorti_bas}-{asorti_bit}" if asorti_bas and asorti_bit else payload.get("asorti", "")).strip()
    lib_uuid = str(uuid.uuid4())
    bkey = f"DRAFT|{lib_uuid}" if is_draft else build_business_key(mat, model_kod, mold_code, product_cat, asorti)
    review_st = "REVIEW_REQUIRED" if is_draft else "READY_FOR_LIBRARY"
    src_sha = f"FORM_{lib_uuid[:16]}"

    con = _connect()
    try:
        dup = con.execute(
            "SELECT library_uuid FROM mold_library_mold WHERE business_key=? AND is_archived=0",
            (bkey,),
        ).fetchone()
        if dup and not is_draft:
            raise ValueError("DUPLICATE")

        con.execute("BEGIN IMMEDIATE")
        atki = payload.get("separate_upper_mold")
        pisirme = payload.get("pisirme_suresi_sn")
        pisirme_val = float(pisirme) if pisirme not in (None, "") else None
        insert_cols = [
            "library_uuid", "material_group", "model_code", "visible_mold_code", "product_type_raw",
            "product_category", "product_family", "product_variant", "assortment", "working_status",
            "separate_upper_mold", "pairs_per_cycle", "weight_reference_size", "weight_grams",
            "cycle_time_minutes", "note", "image_present", "source_file_sha256", "source_main_row",
            "business_key", "review_status", "created_by", "updated_by",
        ]
        insert_vals: list[Any] = [
            lib_uuid, mat, model_kod, mold_code, raw_stored, product_cat, family, variant,
            asorti, durum,
            (int(atki) if atki not in (None, "") else None),
            float(payload["cift_miktari"]) if payload.get("cift_miktari") is not None else None,
            (payload.get("gramaj_ref_numara") or "").strip() or None,
            float(payload["gramaj_gr"]) if payload.get("gramaj_gr") is not None else None,
            float(payload["cycle_time_dk"]) if payload.get("cycle_time_dk") is not None else None,
            (payload.get("not") or "").strip() or None,
            1 if image_content else 0, src_sha, 0, bkey, review_st, user, user,
        ]
        if _column_exists(con, "mold_library_mold", "cooking_time_seconds"):
            idx = insert_cols.index("cycle_time_minutes") + 1
            for i, col in enumerate(["cooking_time_seconds", "cooking_time_source", "cooking_time_unit"]):
                insert_cols.insert(idx + i, col)
            insert_vals.insert(idx, pisirme_val)
            insert_vals.insert(idx + 1, "FORM" if pisirme_val is not None else None)
            insert_vals.insert(idx + 2, "seconds" if pisirme_val is not None else None)
        placeholders = ",".join("?" * len(insert_cols))
        con.execute(
            f"INSERT INTO mold_library_mold ({', '.join(insert_cols)}) VALUES ({placeholders})",
            tuple(insert_vals),
        )
        for i, sr in enumerate(payload.get("seri_rows") or [], 1):
            lbl = str(sr.get("size_label", "")).strip()
            if not lbl:
                continue
            qty = sr.get("mold_quantity") or sr.get("kalip_adedi")
            cikis = sr.get("output_pair") or sr.get("kalip_cikisi_row")
            con.execute(
                """INSERT INTO mold_library_series
                   (mold_library_uuid, display_order, numara_asorti, kalip_adedi, cevrim_basina_cikis_cift)
                   VALUES (?,?,?,?,?)""",
                (lib_uuid, i, lbl, int(qty) if qty else None, int(cikis) if cikis else None),
            )
        if image_content and image_ext and image_sha:
            key, _ = _store_image_file(image_content, image_ext, image_sha)
            con.execute(
                """INSERT INTO mold_library_image
                   (mold_library_uuid, storage_key, original_filename, sha256, is_primary)
                   VALUES (?,?,?,?,1)""",
                (lib_uuid, key, payload.get("image_original_name"), image_sha),
            )
        next_seq = con.execute(
            "SELECT COALESCE(MAX(source_seq), 0) + 1 FROM mold_library_mold"
        ).fetchone()[0]
        con.execute(
            "UPDATE mold_library_mold SET source_seq=? WHERE library_uuid=?",
            (next_seq, lib_uuid),
        )
        con.commit()
        after = get_record_by_uuid(lib_uuid)
        con2 = _connect()
        try:
            _audit(con2, lib_uuid, "CREATE", user, payload.get("change_reason"), None, after)
            con2.commit()
        finally:
            con2.close()
        return after or {"library_uuid": lib_uuid}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def update_mold(source_seq: int, payload: dict, user: str,
                image_content: bytes | None = None, image_ext: str | None = None,
                image_sha: str | None = None, remove_image: bool = False) -> dict:
    before = get_record_by_source_seq(source_seq)
    if not before:
        raise ValueError("NOT_FOUND")
    lib_uuid = before["library_uuid"]
    expected_ver = payload.get("row_version")
    if expected_ver is not None and int(expected_ver) != int(before.get("row_version", 1)):
        raise ValueError("VERSION_CONFLICT")

    raw_cat = (payload.get("product_category") or before.get("product_category") or "").strip()
    raw_stored, norm_cat = normalize_product_type(raw_cat)
    family, variant = derive_product_family_variant(norm_cat)
    asorti_bas, asorti_bit = payload.get("asorti_bas"), payload.get("asorti_bit")
    asorti = (f"{asorti_bas}-{asorti_bit}" if asorti_bas and asorti_bit else payload.get("asorti", before.get("asorti", ""))).strip()
    mat = (payload.get("material_group") or before.get("material_group") or "EVA").upper()
    model_kod = (payload.get("model_kod") or before.get("model_kod") or "").strip()
    mold_code = (payload.get("visible_mold_code") or before.get("visible_mold_code") or "").strip()
    new_durum = (payload.get("durum") or before.get("durum") or "AKTIF").upper()
    completing_draft = before.get("durum") == "TASLAK" and new_durum != "TASLAK"
    bkey = build_business_key(mat, model_kod, mold_code, norm_cat, asorti)
    if before.get("durum") == "TASLAK" and new_durum == "TASLAK":
        bkey = before.get("business_key") or f"DRAFT|{lib_uuid}"

    con = _connect()
    try:
        dup = con.execute(
            "SELECT source_seq FROM mold_library_mold WHERE business_key=? AND library_uuid<>? AND is_archived=0",
            (bkey, lib_uuid),
        ).fetchone()
        if dup:
            raise ValueError("DUPLICATE")

        con.execute("BEGIN IMMEDIATE")
        atki = payload.get("separate_upper_mold")
        review_st = "READY_FOR_LIBRARY" if completing_draft else None
        review_sql = ", review_status=?" if review_st else ""
        pisirme = payload.get("pisirme_suresi_sn")
        if pisirme is not None and pisirme != "":
            pisirme_val = float(pisirme)
        else:
            pisirme_val = before.get("pisirme_suresi_sn")
        note_val = (payload.get("not") or before.get("not") or "").strip() or None
        upd_params = [
            mat, model_kod, mold_code, raw_stored, norm_cat, family, variant, asorti,
            new_durum,
            (None if atki in (None, "") else int(atki)),
            float(payload["cift_miktari"]) if payload.get("cift_miktari") is not None else before.get("cift_miktari"),
            (payload.get("gramaj_ref_numara") or before.get("gramaj_ref_numara") or "").strip() or None,
            float(payload["gramaj_gr"]) if payload.get("gramaj_gr") is not None else before.get("gramaj_gr"),
            float(payload["cycle_time_dk"]) if payload.get("cycle_time_dk") is not None else before.get("cycle_time_dk"),
        ]
        cooking_sql = ""
        if _column_exists(con, "mold_library_mold", "cooking_time_seconds"):
            cooking_sql = ", cooking_time_seconds=?, cooking_time_source=?, cooking_time_unit=?"
            upd_params.extend([
                pisirme_val,
                "FORM" if pisirme_val is not None else None,
                "seconds" if pisirme_val is not None else None,
            ])
        upd_params.extend([note_val, bkey, _now(), user])
        if review_st:
            upd_params.append(review_st)
        upd_params.append(lib_uuid)
        con.execute(
            f"""UPDATE mold_library_mold SET
                material_group=?, model_code=?, visible_mold_code=?, product_type_raw=?,
                product_category=?, product_family=?, product_variant=?, assortment=?,
                working_status=?, separate_upper_mold=?, pairs_per_cycle=?,
                weight_reference_size=?, weight_grams=?, cycle_time_minutes=?{cooking_sql}, note=?,
                business_key=?, updated_at=?, updated_by=?, row_version=row_version+1
                {review_sql}
               WHERE library_uuid=?""",
            tuple(upd_params),
        )
        seri_rows = payload.get("seri_rows")
        if seri_rows is not None:
            con.execute("DELETE FROM mold_library_series WHERE mold_library_uuid=?", (lib_uuid,))
            for i, sr in enumerate(seri_rows, 1):
                lbl = str(sr.get("size_label") or sr.get("numara") or "").strip()
                if not lbl:
                    continue
                qty = sr.get("mold_quantity") or sr.get("kalip_adedi")
                cikis = sr.get("output_pair") or sr.get("kalip_cikisi_row")
                con.execute(
                    """INSERT INTO mold_library_series
                       (mold_library_uuid, display_order, numara_asorti, kalip_adedi, cevrim_basina_cikis_cift)
                       VALUES (?,?,?,?,?)""",
                    (lib_uuid, i, lbl, int(qty) if qty else None, int(cikis) if cikis else None),
                )
        old_img = _load_primary_image(con, lib_uuid)
        old_key = old_img["storage_key"] if old_img else None
        if remove_image:
            con.execute("DELETE FROM mold_library_image WHERE mold_library_uuid=?", (lib_uuid,))
            con.execute("UPDATE mold_library_mold SET image_present=0 WHERE library_uuid=?", (lib_uuid,))
        elif image_content and image_ext and image_sha:
            con.execute("DELETE FROM mold_library_image WHERE mold_library_uuid=?", (lib_uuid,))
            key, _ = _store_image_file(image_content, image_ext, image_sha)
            con.execute(
                """INSERT INTO mold_library_image
                   (mold_library_uuid, storage_key, original_filename, sha256, is_primary)
                   VALUES (?,?,?,?,1)""",
                (lib_uuid, key, payload.get("image_original_name"), image_sha),
            )
            con.execute("UPDATE mold_library_mold SET image_present=1 WHERE library_uuid=?", (lib_uuid,))

        con.commit()
        if old_key:
            refs = con.execute(
                "SELECT COUNT(*) FROM mold_library_image WHERE storage_key=?", (old_key,)
            ).fetchone()[0]
            if refs == 0:
                orphan_path = RUNTIME_IMAGE_DIR / old_key
                if orphan_path.is_file():
                    orphan_path.unlink()
        after = get_record_by_uuid(lib_uuid)
        changes = _field_diff(before, after or {})
        if seri_rows is not None:
            changes["seri_dagilimi"] = {"before": before.get("seri_dagilimi"), "after": after.get("seri_dagilimi")}
        con2 = _connect()
        try:
            _audit(con2, lib_uuid, "UPDATE", user, payload.get("change_reason"), before, after, changes)
            con2.commit()
        finally:
            con2.close()
        return after or {}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def archive_mold(source_seq: int, user: str, reason: str) -> dict:
    before = get_record_by_source_seq(source_seq)
    if not before:
        raise ValueError("NOT_FOUND")
    lib_uuid = before["library_uuid"]
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """UPDATE mold_library_mold SET is_archived=1, archive_reason=?, archived_at=?, archived_by=?,
               business_key='ARCHIVED|' || library_uuid,
               updated_at=?, updated_by=?, row_version=row_version+1 WHERE library_uuid=?""",
            (reason, _now(), user, _now(), user, lib_uuid),
        )
        con.commit()
        after = get_record_by_uuid(lib_uuid)
        con2 = _connect()
        try:
            _audit(con2, lib_uuid, "ARCHIVE", user, reason, before, after)
            con2.commit()
        finally:
            con2.close()
        return after or {}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _business_key_from_record(rec: dict) -> str:
    mat = (rec.get("material_group") or "EVA").upper()
    model = (rec.get("model_kod") or "").strip()
    mold = (rec.get("visible_mold_code") or "").strip()
    cat = (rec.get("product_category") or rec.get("product_variant") or "").strip()
    asorti = (rec.get("asorti") or "").strip()
    _, norm_cat = normalize_product_type(cat)
    return build_business_key(mat, model, mold, norm_cat, asorti)


def restore_mold(source_seq: int, user: str, reason: str) -> dict:
    before = get_record_by_source_seq(source_seq)
    if not before:
        raise ValueError("NOT_FOUND")
    if not before.get("is_archived"):
        return before
    lib_uuid = before["library_uuid"]
    bkey = _business_key_from_record(before)
    con = _connect()
    try:
        dup = con.execute(
            "SELECT source_seq FROM mold_library_mold WHERE business_key=? AND is_archived=0 AND library_uuid<>?",
            (bkey, lib_uuid),
        ).fetchone()
        if dup:
            con2 = _connect()
            try:
                _audit(
                    con2, lib_uuid, "RESTORE_BLOCKED", user, reason, before, before,
                    {"conflict_active_source_seq": dup["source_seq"], "business_key": bkey},
                )
                con2.commit()
            finally:
                con2.close()
            raise ValueError(f"RESTORE_CONFLICT|{dup['source_seq']}")
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """UPDATE mold_library_mold SET is_archived=0, archive_reason=NULL, archived_at=NULL, archived_by=NULL,
               business_key=?, updated_at=?, updated_by=?, row_version=row_version+1 WHERE library_uuid=?""",
            (bkey, _now(), user, lib_uuid),
        )
        con.commit()
        after = get_record_by_uuid(lib_uuid)
        changes = _field_diff(before, after or {})
        con2 = _connect()
        try:
            _audit(con2, lib_uuid, "RESTORE", user, reason, before, after, changes)
            con2.commit()
        finally:
            con2.close()
        return after or {}
    except ValueError:
        raise
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def build_fixture_payload() -> dict:
    records = list_records(include_archived=False)
    imported = [r for r in records if r.get("record_origin") == "IMPORTED" and not r.get("is_test_record")]
    return {
        "meta": {
            "source_sha256": SOURCE_SHA256,
            "preview_mold_library_active": True,
            "poli_active": POLI_ACTIVE,
            "plan_selection_enabled": PLAN_SELECTION_ENABLED,
            "dual_write_enabled": False,
            "library_record_count": len(records),
            "imported_record_count": len(imported),
            "imported_series_count": sum(len(r.get("seri_dagilimi") or []) for r in imported),
        },
        "records": records,
    }


def image_file_path(storage_key: str) -> Path | None:
    if not storage_key or ".." in storage_key or "/" in storage_key or "\\" in storage_key:
        return None
    # Use dynamic runtime_image_dir() so env override is respected
    p = runtime_image_dir() / storage_key
    return p if p.is_file() else None

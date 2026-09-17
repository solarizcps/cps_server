# -*- coding: utf-8 -*-
"""Mold Library → Plan Oluştur guarded selection gates (PHASE_6B)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any

IMPORT_SHA = "2AC3D6EA38E31EC700809A72761E18A53D48919254E96C390530B1EFA898CAC1"

# Preview pilot default true when env set; production default false.
MOLD_LIBRARY_PLAN_SELECTION_ENABLED = os.environ.get(
    "MOLD_LIBRARY_PLAN_SELECTION_ENABLED", "true"
).lower() in ("1", "true", "yes")


BLOCK_MSG = {
    "output_pair_conflict": "Çevrim çıkış bilgisi doğrulanmalı",
    "missing_setup_goz": "Aktif göz/setup bilgisi eksik",
    "missing_series_qty": "Kalıp adedi eksik (bir veya daha fazla numara grubu doğrulanmamış)",
    "review_required": "Kütüphane kaydı inceleme bekliyor",
    "model_mismatch": "Sipariş modeliyle uyumlu değil",
    "asorti_mismatch": "Sipariş asortisiyle uyumlu değil",
    "poli_not_active": "Poli planlama henüz aktif değil",
    "missing_kbc": "Çevrim başına çıkış (çift) tanımlı değil",
    "no_legacy_map": "Kalıp Master eşleşmesi bulunamadı — bağlantı doğrulanmalı",
    "inactive_status": "Kalıp kaydı aktif değil (durum: beklemede veya pasif)",
    "draft_status": "Kalıp taslak durumda — henüz onaylanmamış",
    "archived": "Kalıp arşivlenmiş — aktif kütüphanede değil",
    "component_unresolved": "Kalıp bileşen rolü doğrulanmamış (GOVDE / ATKI / TASLAK ayrımı belirsiz)",
    "legacy_inactive": "Kalıp Master kaydı pasif veya bulunamadı",
}


def _library_image_url(storage_key: str | None) -> str | None:
    """Return image URL only when runtime file exists — avoid 404 requests."""
    if not storage_key:
        return None
    from modules.planlama import mold_library_db as mldb

    key = str(storage_key).strip()
    if not key or not mldb.image_file_path(key):
        return None
    return f"/planlama/aktif-kaliplar/gorsel/{key}"


def _row_dict(row) -> dict:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    raise TypeError("Expected mapping row")


def _int_kbc(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _parse_range(text: str) -> tuple[int, int] | None:
    if not text:
        return None
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", str(text).strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        a, b = b, a
    return a, b


def _parse_size_tokens(text: str) -> set[int]:
    """Parse asorti/numara tokens — slash groups and singles; no left/right tire rule."""
    out: set[int] = set()
    if not text:
        return out
    s = str(text).strip()
    rng = _parse_range(s)
    if rng:
        out.update(range(rng[0], rng[1] + 1))
        return out
    for part in re.split(r"[/,\s]+", s):
        part = part.strip()
        if not part:
            continue
        sub = _parse_range(part)
        if sub:
            out.update(range(sub[0], sub[1] + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


def asorti_compatible(mold_assortment: str, series_rows: list[dict], order_asorti: str | None) -> bool:
    if not (order_asorti or "").strip():
        return True
    order_tokens = _parse_size_tokens(order_asorti)
    if not order_tokens:
        return True
    mold_rng = _parse_range(mold_assortment or "")
    if mold_rng and any(mold_rng[0] <= t <= mold_rng[1] for t in order_tokens):
        return True
    for sr in series_rows:
        lbl = sr.get("numara_asorti") or ""
        ser_tokens = _parse_size_tokens(lbl)
        if ser_tokens & order_tokens:
            return True
    return False


def _has_setup_goz_evidence(con: sqlite3.Connection, kalip_id: int) -> bool:
    row = con.execute(
        """SELECT 1 FROM enj_ab_setup
           WHERE kalip_id=? AND COALESCE(aktif_goz_sayisi, 0) > 0 LIMIT 1""",
        (kalip_id,),
    ).fetchone()
    return bool(row)


def _load_series(con: sqlite3.Connection, lib_uuid: str) -> list[dict]:
    rows = con.execute(
        """SELECT display_order, numara_asorti, kalip_adedi, cevrim_basina_cikis_cift, source_col
           FROM mold_library_series WHERE mold_library_uuid=? ORDER BY display_order""",
        (lib_uuid,),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def _physical_mold_total(series: list[dict]) -> int | None:
    if not series:
        return None
    if any(s.get("kalip_adedi") is None for s in series):
        return None
    return sum(int(s["kalip_adedi"]) for s in series)


_ACTIVATION_BLOCK_TR = {
    "component_role_not_evidence_backed": "Bileşen rolü (GOVDE/ATKI) kanıt kaynağıyla doğrulanmamış",
    "no_legacy_mapping": "Kalıp Master eşleşmesi bulunamadı",
    "missing_series_qty": "Kalıp adedi eksik (bir veya daha fazla numara grubu)",
    "missing_kbc": "Çevrim başına çıkış (çift) tanımlı değil",
    "review_required": "Kütüphane kaydı inceleme sürecinde",
    "stale_review": "İnceleme durumu güncel değil — yeniden değerlendirme gerekli",
}

_BLOCK_CODE_TR = {
    "component_unresolved": "Bileşen rolü doğrulanmamış (GOVDE / ATKI ayrımı belirsiz)",
    "no_legacy_map": "Kalıp Master eşleşmesi bulunamadı",
    "missing_series_qty": "Kalıp adedi eksik (bir veya daha fazla numara grubu doğrulanmamış)",
    "missing_kbc": "Çevrim başına çıkış (çift) tanımlı değil",
    "review_required": "Kütüphane kaydı inceleme bekliyor",
    "legacy_inactive": "Kalıp Master kaydı pasif",
    "output_pair_conflict": "Çevrim çıkış bilgisi doğrulanmalı",
    "model_mismatch": "Sipariş modeliyle uyumlu değil",
    "asorti_mismatch": "Sipariş asortisiyle uyumlu değil",
    "missing_setup_goz": "Aktif göz/setup bilgisi eksik",
}


def _parse_activation_block(raw: str, block_code: str | None) -> list[str]:
    """PHASE_7I: Parse activation_block_reason into specific Turkish messages."""
    msgs: list[str] = []
    if raw:
        for part in raw.split(";"):
            part = part.strip()
            if part in _ACTIVATION_BLOCK_TR:
                msgs.append(_ACTIVATION_BLOCK_TR[part])
            elif part:
                msgs.append(part)
    if not msgs and block_code and block_code in _BLOCK_CODE_TR:
        msgs.append(_BLOCK_CODE_TR[block_code])
    return msgs


def _has_approved_output_pair(con: sqlite3.Connection, library_uuid: str) -> bool:
    """PHASE_7H: Returns True if this UUID has a valid Adem approval in mold_library_output_verification."""
    try:
        row = con.execute(
            """SELECT verified_pairs_per_cycle FROM mold_library_output_verification
               WHERE mold_library_uuid=? AND verification_status='APPROVED'""",
            (library_uuid,),
        ).fetchone()
        return row is not None
    except Exception:
        # Table may not exist in older DBs — fail open (treat as no approval)
        return False


def evaluate_static_gates(
    mold: dict,
    series: list[dict],
    enj_kalip: dict | None,
    con: sqlite3.Connection | None = None,
) -> tuple[bool, list[str], str | None]:
    """Static readiness gates (order-independent). Returns (selectable, reasons, primary_code).

    PHASE_7H: con is used for approval-aware output_pair_conflict gate only.
    Passing con=None preserves pre-7H behavior.
    """
    reasons: list[str] = []
    code: str | None = None

    def block(c: str):
        nonlocal code
        if c not in reasons:
            reasons.append(BLOCK_MSG[c])
        if not code:
            code = c

    if (mold.get("material_group") or "").upper() == "POLI":
        block("poli_not_active")
        return False, reasons, code
    if mold.get("is_archived"):
        block("archived")
        return False, reasons, code
    if (mold.get("working_status") or "").upper() == "TASLAK":
        block("draft_status")
        return False, reasons, code
    if (mold.get("working_status") or "").upper() != "AKTIF":
        block("inactive_status")
        return False, reasons, code
    if mold.get("review_status") == "REVIEW_REQUIRED":
        block("review_required")
        return False, reasons, code
    if mold.get("component_role") == "UNRESOLVED":
        block("component_unresolved")
        return False, reasons, code
    if any(s.get("kalip_adedi") is None for s in series):
        block("missing_series_qty")
        return False, reasons, code
    lib_kbc = _int_kbc(mold.get("pairs_per_cycle"))
    if not lib_kbc or lib_kbc <= 0:
        block("missing_kbc")
        return False, reasons, code
    leg_id = mold.get("legacy_enj_kalip_id")
    if not leg_id:
        block("no_legacy_map")
        return False, reasons, code
    if not enj_kalip or not enj_kalip.get("aktif"):
        block("legacy_inactive")
        return False, reasons, code
    leg_kbc = _int_kbc(enj_kalip.get("kalip_basi_cift"))
    if leg_kbc and lib_kbc != leg_kbc:
        # PHASE_7H: approval-aware check — if Adem approved this UUID, skip output_pair_conflict block
        lib_uuid = mold.get("library_uuid", "")
        approved = con is not None and bool(lib_uuid) and _has_approved_output_pair(con, lib_uuid)
        if not approved:
            block("output_pair_conflict")
            return False, reasons, code
        # Approved — output_pair_conflict bypassed for this UUID only
    if mold.get("review_status") != "READY_FOR_PLANNING":
        block("review_required")
        return False, reasons, code
    return True, reasons, code


def evaluate_order_gates(
    mold: dict,
    series: list[dict],
    order_model_code: str,
    order_asorti: str | None,
    con: sqlite3.Connection | None = None,
) -> tuple[bool, list[str], str | None]:
    # PHASE_7N: Model kodu uyuşmazlığı bloke değil.
    # PHASE_7N1: Asorti uyumsuzluğu da artık hard block değil — bilgi uyarısına dönüştürüldü.
    # Korgün'den yalnız genel asorti kodu geliyor; numara bazlı dağılım yok.
    # Planlamacı kalıp numaralarını ekranda görerek kendi kararını verir.
    return True, [], None


def asorti_advisory(
    mold: dict,
    series: list[dict],
    order_asorti: str | None,
) -> str | None:
    """Asorti uyumsuzluğu varsa amber bilgi uyarısı döner; bloke etmez."""
    if not order_asorti:
        return None
    if not asorti_compatible(mold.get("assortment") or "", series, order_asorti):
        return "Numara/asorti farklı olabilir — seçmeden önce kontrol edin."
    return None


def _series_coverage_class(series_tokens: set[int], order_tokens: set[int]) -> str:
    if not order_tokens:
        return "neutral"
    if not series_tokens:
        return "neutral"
    if series_tokens & order_tokens:
        return "covered"
    return "outside_order"


def build_series_display(series: list[dict], order_asorti: str | None) -> dict:
    """PHASE_7L: Vertical series/qty lines — source-driven, no invented distribution."""
    order_tokens = _parse_size_tokens(order_asorti or "")
    has_detail = bool((order_asorti or "").strip() and order_tokens)
    lines: list[dict] = []
    for s in series:
        label = (s.get("numara_asorti") or "—").strip()
        qty = s.get("kalip_adedi")
        ser_tokens = _parse_size_tokens(label)
        lines.append({
            "numara_asorti": label,
            "kalip_adedi": qty,
            "kalip_adedi_label": f"{int(qty)} adet" if qty is not None else "Adet doğrulanmalı",
            "missing_qty": qty is None,
            "coverage": _series_coverage_class(ser_tokens, order_tokens),
        })
    note = None
    if not has_detail:
        note = "Asorti aralığı uyumlu; numara bazlı sipariş dağılımı bulunmuyor."
    return {"lines": lines, "order_size_detail_available": has_detail, "coverage_note": note}


def build_physical_summary(series: list[dict]) -> dict:
    """Verified total or 'En az X' when any series qty is NULL — never default missing to 0/1."""
    if not series:
        return {
            "verified_total": None,
            "display_total": None,
            "label": "Fiziksel kalıp adedi doğrulanmalı",
            "missing_series_count": 0,
            "min_verified_total": None,
        }
    missing = [s for s in series if s.get("kalip_adedi") is None]
    verified = [s for s in series if s.get("kalip_adedi") is not None]
    if missing:
        min_sum = sum(int(s["kalip_adedi"]) for s in verified) if verified else None
        label = f"En az {min_sum} adet" if min_sum is not None else "Fiziksel kalıp adedi doğrulanmalı"
        return {
            "verified_total": None,
            "display_total": None,
            "label": label,
            "missing_series_count": len(missing),
            "min_verified_total": min_sum,
        }
    total = sum(int(s["kalip_adedi"]) for s in series)
    return {
        "verified_total": total,
        "display_total": total,
        "label": f"{total} adet",
        "missing_series_count": 0,
        "min_verified_total": total,
    }


def _load_machine_side_capacity(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT kod, istasyon_sayisi FROM enj_makine WHERE aktif=1 ORDER BY sira, id"""
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = _row_dict(r)
        cap = int(d.get("istasyon_sayisi") or 0)
        if cap <= 0:
            continue
        mk = d.get("kod") or "?"
        out.append({"machine": mk, "slot": "A", "capacity": cap, "label": f"{mk} / A Tarafı"})
        out.append({"machine": mk, "slot": "B", "capacity": cap, "label": f"{mk} / B Tarafı"})
    return out


def build_placement_recommendation(
    con: sqlite3.Connection,
    physical_summary: dict,
) -> dict:
    """Advisory placement only — does not auto-select stations."""
    missing = physical_summary.get("missing_series_count") or 0
    total = physical_summary.get("verified_total")
    if missing or total is None or total <= 0:
        return {
            "available": False,
            "reason": "Fiziksel kalıp adedi tam doğrulanmadığı için yerleşim önerisi üretilemiyor.",
            "primary": [],
            "alternatives": [],
        }
    sides = _load_machine_side_capacity(con)
    if not sides:
        return {"available": False, "reason": "Makine kapasitesi bulunamadı.", "primary": [], "alternatives": []}

    # Group by machine for capacity awareness
    machine_caps: dict[str, int] = {}
    for s in sides:
        machine_caps.setdefault(s["machine"], 0)
        machine_caps[s["machine"]] += s["capacity"]
    side_cap = sides[0]["capacity"] if sides else 0  # capacity per side (A or B)

    remaining = int(total)
    primary: list[dict] = []
    for side in sides:
        if remaining <= 0:
            break
        use = min(remaining, side["capacity"])
        if use <= 0:
            continue
        # Terminology: only say "tam" if use equals that side's full capacity
        if use == side["capacity"]:
            side_label = f"{side['label']} tam dolabilir ({use} istasyon)"
        else:
            side_label = f"{side['label']}: {use}/{side['capacity']} istasyon kullanılabilir"
        primary.append({
            "machine": side["machine"],
            "slot": side["slot"],
            "stations": use,
            "capacity": side["capacity"],
            "full_side": use == side["capacity"],
            "label": side_label,
        })
        remaining -= use

    alternatives: list[str] = []
    if remaining > 0:
        alternatives.append(
            f"Kalan {remaining} kalıp başka zaman veya başka makinede kullanılabilir"
        )
    # Check if a single machine's A+B fully fits
    for mk, cap in machine_caps.items():
        if total == cap:
            alternatives.insert(0, f"{mk} / A+B bir makine tam dolabilir ({cap} istasyon)")
        elif total < cap and len(primary) <= 2:
            # already covered by primary
            pass
    # Check if two machines fit exactly
    if len(machine_caps) >= 2:
        total_cap_2 = sum(list(machine_caps.values())[:2])
        if total == total_cap_2:
            machines = list(machine_caps.keys())[:2]
            alternatives.append(f"{machines[0]} ve {machines[1]} iki makine tam dolabilir ({total} istasyon)")

    return {
        "available": True,
        "physical_total": total,
        "primary": primary,
        "alternatives": alternatives,
        "max_station_hint": min(total, sum(s["capacity"] for s in sides)),
    }


def build_library_snapshot(
    mold: dict,
    series: list[dict],
    *,
    selected_series_label: str | None = None,
    legacy_id: int | None = None,
    order_model_code: str | None = None,
) -> dict:
    return {
        "library_uuid": mold["library_uuid"],
        "model_code": mold.get("model_code"),
        "visible_mold_code": mold.get("visible_mold_code"),
        "material_group": mold.get("material_group") or "EVA",
        "product_family": mold.get("product_family"),
        "product_variant": mold.get("product_variant"),
        "assortment": mold.get("assortment"),
        "pairs_per_cycle": mold.get("pairs_per_cycle"),
        "selected_series_label": selected_series_label,
        "series_summary": [
            {
                "numara_asorti": s.get("numara_asorti"),
                "kalip_adedi": s.get("kalip_adedi"),
                "cevrim_basina_cikis_cift": s.get("cevrim_basina_cikis_cift"),
            }
            for s in series
        ],
        "readiness_status": mold.get("review_status"),
        "legacy_enj_kalip_id": legacy_id or mold.get("legacy_enj_kalip_id"),
        # PHASE_7N: serbest seçim kaydı — master bağlantı oluşturmaz
        "selection_method": "MANUAL_LIBRARY_SELECTION",
        "order_model_code": order_model_code or None,
        "selected_mold_model_code": mold.get("model_code"),
        "selected_mold_code": mold.get("visible_mold_code"),
        "snapshot_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def mold_to_list_item(
    con: sqlite3.Connection,
    mold: dict,
    *,
    order_model_code: str,
    order_asorti: str | None,
    include_non_model: bool = False,  # PHASE_7N: artık kullanılmıyor, geriye dönük uyumluluk için tutuluyor
) -> dict | None:
    # PHASE_7N: mapping modülü artık seçim filtresinde kullanılmıyor
    lib_uuid = mold["library_uuid"]
    series = _load_series(con, lib_uuid)
    enj_kalip = None
    if mold.get("legacy_enj_kalip_id"):
        r = con.execute(
            "SELECT id, kalip_kod, model_kod, kalip_basi_cift, aktif FROM enj_kalip WHERE id=?",
            (mold["legacy_enj_kalip_id"],),
        ).fetchone()
        enj_kalip = _row_dict(r) if r else None

    static_ok, static_reasons, static_code = evaluate_static_gates(mold, series, enj_kalip, con=con)
    order_ok, order_reasons, order_code = evaluate_order_gates(
        mold, series, order_model_code, order_asorti, con=con
    )

    selectable = static_ok and order_ok
    reasons = static_reasons + [r for r in order_reasons if r not in static_reasons]
    block_code = order_code or static_code

    img = con.execute(
        """SELECT storage_key FROM mold_library_image
           WHERE mold_library_uuid=? AND is_primary=1 ORDER BY display_order LIMIT 1""",
        (lib_uuid,),
    ).fetchone()

    leg_kbc = _int_kbc(enj_kalip.get("kalip_basi_cift")) if enj_kalip else None
    lib_kbc = _int_kbc(mold.get("pairs_per_cycle"))
    phys_summary = build_physical_summary(series)
    series_display = build_series_display(series, order_asorti)
    placement = build_placement_recommendation(con, phys_summary)
    cook = mold.get("cooking_time_seconds")
    weight_g = mold.get("weight_grams")
    weight_ref = mold.get("weight_reference_size")
    info_warnings: list[str] = []
    if cook is None:
        info_warnings.append("Pişme süresi doğrulanmalı")
    if weight_g is None:
        info_warnings.append("Gramaj doğrulanmalı")
    # PHASE_7N1: Asorti farkı varsa amber uyarı (hard block değil)
    asorti_warn = asorti_advisory(mold, series, order_asorti)
    if asorti_warn:
        info_warnings.append(asorti_warn)

    return {
        "library_uuid": lib_uuid,
        "visible_mold_code": mold.get("visible_mold_code"),
        "model_code": mold.get("model_code"),
        "product_family": mold.get("product_family"),
        "product_variant": mold.get("product_variant"),
        "assortment": mold.get("assortment"),
        "pairs_per_cycle": lib_kbc,
        "physical_mold_total": phys_summary.get("display_total"),
        "physical_mold_label": phys_summary.get("label"),
        "physical_mold_summary": phys_summary,
        "max_station_hint": placement.get("max_station_hint"),
        "series": series,
        "series_display": series_display,
        "placement_recommendation": placement,
        "cooking_time_seconds": cook,
        "cooking_time_label": f"{int(cook)} sn" if cook is not None else None,
        "weight_grams": weight_g,
        "weight_reference_size": weight_ref,
        "weight_label": f"{int(weight_g)} g" if weight_g is not None else None,
        "info_warnings": info_warnings,
        "working_status": mold.get("working_status"),
        "review_status": mold.get("review_status"),
        "legacy_enj_kalip_id": mold.get("legacy_enj_kalip_id"),
        "legacy_kalip_basi_cift": leg_kbc,
        "output_pair_conflict": bool(
            leg_kbc and lib_kbc and lib_kbc != leg_kbc
            and not _has_approved_output_pair(con, lib_uuid)
        ),
        "selectable": selectable,
        "block_reasons": reasons,
        "block_code": block_code,
        "activation_block_detail": _parse_activation_block(
            mold.get("activation_block_reason") or "", block_code
        ),
        "image_url": _library_image_url(_row_dict(img)["storage_key"]) if img else None,
        "has_image": bool(img and _library_image_url(_row_dict(img)["storage_key"])),
    }


def list_for_plan(
    con: sqlite3.Connection,
    order_model_code: str,
    order_asorti: str | None = None,
) -> dict[str, Any]:
    rows = con.execute(
        """SELECT * FROM mold_library_mold
           WHERE source_file_sha256=? AND is_archived=0
           ORDER BY COALESCE(source_seq, id)""",
        (IMPORT_SHA,),
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        mold = _row_dict(row)
        item = mold_to_list_item(
            con,
            mold,
            order_model_code=order_model_code,
            order_asorti=order_asorti,
            include_non_model=True,
        )
        if item:
            items.append(item)
    selectable = [i for i in items if i.get("selectable")]
    blocked = [i for i in items if not i.get("selectable")]
    return {
        "source": "ACTIVE_MOLDS_LIBRARY",
        "plan_source_label": "Aktif Kalıplar",
        "kaliplar": items,
        "selectable_count": len(selectable),
        "blocked_count": len(blocked),
        # PHASE_7N: recommended tab kaldırıldı; alanlar geriye dönük uyumluluk için sıfır
        "recommended_count": 0,
        "selectable": selectable,
        "blocked": blocked,
        "recommended": [],
        "order_size_detail_available": bool(
            order_asorti and _parse_size_tokens(order_asorti or "")
        ),
    }


def count_static_selectable(con: sqlite3.Connection) -> dict[str, int]:
    """Gate counts without order context — verification helper."""
    rows = con.execute(
        """SELECT * FROM mold_library_mold
           WHERE source_file_sha256=? AND is_archived=0""",
        (IMPORT_SHA,),
    ).fetchall()
    counts = {
        "total": len(rows),
        "selectable": 0,
        "output_pair_conflict": 0,
        "review_blocked": 0,
        "missing_quantity": 0,
        "poli": 0,
        "missing_setup": 0,
    }
    conflicts: list[dict] = []
    for row in rows:
        mold = _row_dict(row)
        series = _load_series(con, mold["library_uuid"])
        enj_kalip = None
        if mold.get("legacy_enj_kalip_id"):
            r = con.execute(
                "SELECT kalip_basi_cift, aktif FROM enj_kalip WHERE id=?",
                (mold["legacy_enj_kalip_id"],),
            ).fetchone()
            enj_kalip = _row_dict(r) if r else None
        if (mold.get("material_group") or "").upper() == "POLI":
            counts["poli"] += 1
            continue
        lib_kbc = _int_kbc(mold.get("pairs_per_cycle"))
        leg_kbc = _int_kbc(enj_kalip.get("kalip_basi_cift")) if enj_kalip else None
        if lib_kbc and leg_kbc and lib_kbc != leg_kbc:
            # PHASE_7H: approval-aware — approved UUIDs no longer count as blocked
            if not _has_approved_output_pair(con, mold["library_uuid"]):
                counts["output_pair_conflict"] += 1
                conflicts.append({
                    "library_uuid": mold["library_uuid"],
                    "model_code": mold.get("model_code"),
                    "visible_mold_code": mold.get("visible_mold_code"),
                    "library_pairs_per_cycle": lib_kbc,
                    "legacy_kalip_basi_cift": leg_kbc,
                    "decision_status": "PENDING_ADEM_REVIEW",
                })
        if any(s.get("kalip_adedi") is None for s in series):
            counts["missing_quantity"] += 1
        if mold.get("review_status") == "REVIEW_REQUIRED":
            counts["review_blocked"] += 1
        static_ok, _, _ = evaluate_static_gates(mold, series, enj_kalip, con=con)
        if static_ok:
            counts["selectable"] += 1
    return {"counts": counts, "output_pair_conflicts": conflicts}


def validate_library_plan_save(
    con: sqlite3.Connection,
    payload: dict,
    *,
    order_model_code: str,
    order_asorti: str | None,
) -> dict:
    """Server-side gate — reject bypass. Returns validated snapshot dict."""
    lib_uuid = (payload.get("mold_library_uuid") or "").strip()
    if not lib_uuid:
        raise ValueError("Library planında mold_library_uuid zorunludur.")
    row = con.execute(
        "SELECT * FROM mold_library_mold WHERE library_uuid=? AND is_archived=0",
        (lib_uuid,),
    ).fetchone()
    if not row:
        raise ValueError("Seçilen kütüphane kalıbı bulunamadı.")
    mold = _row_dict(row)
    series = _load_series(con, lib_uuid)
    enj_kalip = None
    if mold.get("legacy_enj_kalip_id"):
        r = con.execute(
            "SELECT id, kalip_kod, model_kod, kalip_basi_cift, aktif FROM enj_kalip WHERE id=?",
            (mold["legacy_enj_kalip_id"],),
        ).fetchone()
        enj_kalip = _row_dict(r) if r else None
    # PHASE_7N: Yalnız static gate'ler zorunlu; model kodu uyuşmazlığı bloke etmez.
    static_ok, reasons, _ = evaluate_static_gates(mold, series, enj_kalip, con=con)
    if not static_ok:
        raise ValueError("; ".join(reasons) or "Kalıp seçilemez.")
    snap = build_library_snapshot(
        mold,
        series,
        selected_series_label=payload.get("selected_series_label"),
        legacy_id=mold.get("legacy_enj_kalip_id"),
        order_model_code=order_model_code,
    )
    client_snap = payload.get("mold_library_snapshot_json")
    if isinstance(client_snap, str):
        try:
            client_snap = json.loads(client_snap)
        except json.JSONDecodeError:
            client_snap = None
    if client_snap and client_snap.get("library_uuid") != lib_uuid:
        raise ValueError("Snapshot library_uuid uyuşmuyor.")
    return snap

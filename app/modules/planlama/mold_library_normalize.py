# -*- coding: utf-8 -*-
"""Mold Library — merkezi normalizasyon (PHASE_4B_V2 / PHASE_4C / PHASE_4D)."""
from __future__ import annotations

import re
from typing import Any


def tr_lower(s: str) -> str:
    if not s:
        return ""
    out = []
    for ch in s.strip():
        if ch == "İ":
            out.append("i")
        elif ch == "I":
            out.append("ı")
        elif ch == "Ş":
            out.append("ş")
        elif ch == "Ğ":
            out.append("ğ")
        elif ch == "Ü":
            out.append("ü")
        elif ch == "Ö":
            out.append("ö")
        elif ch == "Ç":
            out.append("ç")
        else:
            out.append(ch.lower())
    return "".join(out)


def tr_upper_first(s: str) -> str:
    if not s:
        return ""
    low = tr_lower(s)
    first = low[0]
    if first == "i":
        head = "İ"
    elif first == "ı":
        head = "I"
    else:
        head = first.upper()
    return head + low[1:]


def tr_title_word(word: str) -> str:
    if not word:
        return ""
    w = word.strip()
    if tr_lower(w) == "eva":
        return "EVA"
    return tr_upper_first(w)


def normalize_title_segment(seg: str) -> str:
    s = seg.strip()
    if not s:
        return ""
    if "/" in s and " - " not in s:
        return " / ".join(normalize_title_segment(p.strip()) for p in s.split("/") if p.strip())
    return tr_title_word(s)


def normalize_product_type(raw: str | None) -> tuple[str, str]:
    """Returns (product_type_raw, product_type_normalized)."""
    if not raw:
        return "", ""
    raw_clean = raw.strip()
    s = re.sub(r"\s*-\s*", " - ", raw_clean)
    s = re.sub(r"\s+", " ", s).strip()
    if " - " in s:
        parts = [normalize_title_segment(p) for p in s.split(" - ") if p.strip()]
        normalized = " - ".join(parts)
    elif " " in s:
        normalized = " ".join(tr_title_word(w) for w in s.split() if w.strip())
    else:
        normalized = normalize_title_segment(s)
    return raw_clean, normalized


def derive_product_family_variant(normalized: str) -> tuple[str, str]:
    """Ana aile + tabloda gösterilecek alt varyant."""
    norm = (normalized or "").strip()
    if not norm:
        return "", ""
    low = tr_lower(norm)

    if low.startswith("patik") or low == "patik":
        return "Patik", norm
    if low.startswith("filet zenne"):
        return "Filet", norm
    if low.startswith("filet"):
        return "Filet", norm
    if "eva taban" in low:
        return "EVA Taban", norm
    if low.startswith("bebe"):
        return "Bebe", norm
    if low.startswith("fuspet") or low.startswith("füspet") or low.startswith("fuşpet"):
        return "Fuspet", norm
    if low.startswith("merdane"):
        return "Merdane", norm
    if low == "zenne":
        return "Zenne", norm

    if " - " in norm:
        return norm.split(" - ", 1)[0], norm
    return norm, norm


def family_filter_key(family: str) -> str:
    return tr_lower(family or "")


def compose_product_type(family: str, variant: str = "") -> str:
    fam = (family or "").strip()
    var = (variant or "").strip()
    if not fam:
        return ""
    if not var or tr_lower(var) == tr_lower(fam):
        _, norm = normalize_product_type(fam)
        return norm
    if tr_lower(var).startswith(tr_lower(fam)):
        _, norm = normalize_product_type(var)
        return norm
    _, norm = normalize_product_type(f"{fam} - {var}")
    return norm


def _parse_kalip_adedi(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def normalize_seri_row(seri: dict, record: dict) -> dict:
    """Excel adet satırı → kalip_adedi; numara/asorti ham korunur."""
    raw_label = (seri.get("seri_label") or seri.get("numara_asorti") or "").strip()
    kalip_adedi = seri.get("kalip_adedi")
    if kalip_adedi is None:
        kalip_adedi = _parse_kalip_adedi(seri.get("goz_adet"))
    cift_row = seri.get("kalip_cikisi_row")
    cift = cift_row if cift_row is not None else record.get("cift_miktari")
    return {
        **seri,
        "seri_label": raw_label,
        "numara_asorti": raw_label,
        "numara_asorti_display": raw_label or "—",
        "kalip_adedi": kalip_adedi,
        "kalip_adedi_source": "excel_adet_row" if kalip_adedi is not None else "UNRESOLVED",
        "kalip_cikisi": cift,
    }


def _record_physical_mold_total(seri: list[dict]) -> tuple[int | None, bool]:
    if not seri:
        return None, False
    total = 0
    for s in seri:
        q = s.get("kalip_adedi")
        if q is None:
            return None, False
        total += int(q)
    return total, True


def normalize_record(record: dict) -> dict:
    raw_cat, norm_cat = normalize_product_type(record.get("product_category"))
    family, variant = derive_product_family_variant(norm_cat)
    seri = [normalize_seri_row(s, record) for s in (record.get("seri_dagilimi") or [])]
    total, complete = _record_physical_mold_total(seri)
    out = dict(record)
    out["product_type_raw"] = raw_cat
    out["product_category"] = variant or norm_cat
    out["product_type_normalized"] = variant or norm_cat
    out["product_family"] = family
    out["product_variant"] = variant or norm_cat
    out["product_family_key"] = family_filter_key(family)
    out["seri_dagilimi"] = seri
    out["physical_mold_total_record"] = total
    out["physical_mold_total_complete"] = complete
    return out


def normalize_fixture(records: list[dict]) -> list[dict]:
    return [normalize_record(r) for r in records]


def build_business_key(mat: str, model: str, mold: str, cat: str, asorti: str) -> str:
    _, norm_cat = normalize_product_type(cat)
    return f"{mat}|{model}|{mold}|{norm_cat}|{asorti}"


def forensic_product_families(records: list[dict]) -> dict[str, Any]:
    norm = normalize_fixture(records)
    families: dict[str, list[str]] = {}
    false_assign = 0
    for r in norm:
        fam = r.get("product_family") or ""
        var = r.get("product_variant") or ""
        if fam and var and not (var == fam or tr_lower(var).startswith(tr_lower(fam))):
            false_assign += 1
        families.setdefault(fam or "Belirsiz", []).append(var)

    patik_vars = sorted(set(families.get("Patik", [])))
    filet_vars = sorted(set(families.get("Filet", [])))

    qty1 = qty2 = qtygt2 = qty_missing = 0
    auto_default = 0
    physical_total = 0
    physical_complete_records = 0
    for r in norm:
        for s in r.get("seri_dagilimi", []):
            q = s.get("kalip_adedi")
            if q is None:
                qty_missing += 1
            elif q == 1:
                qty1 += 1
            elif q == 2:
                qty2 += 1
            elif q > 2:
                qtygt2 += 1
            if s.get("goz_adet") is not None and q is None:
                auto_default += 1
        if r.get("physical_mold_total_complete"):
            physical_complete_records += 1
            physical_total += r.get("physical_mold_total_record") or 0

    return {
        "PRODUCT_FAMILY_COUNT": len(families),
        "PATIK_FAMILY_RECORD_COUNT": len(families.get("Patik", [])),
        "PATIK_VARIANT_COUNTS": {v: families.get("Patik", []).count(v) for v in patik_vars},
        "FILET_FAMILY_RECORD_COUNT": len(families.get("Filet", [])),
        "FILET_VARIANT_COUNTS": {v: families.get("Filet", []).count(v) for v in filet_vars},
        "FALSE_FAMILY_ASSIGNMENT_COUNT": false_assign,
        "MOLD_LIBRARY_RECORD_COUNT": len(norm),
        "RECORDS_WITH_QUANTITY_1": qty1,
        "RECORDS_WITH_QUANTITY_2": qty2,
        "RECORDS_WITH_QUANTITY_GT_2": qtygt2,
        "MOLD_QUANTITY_MISSING_COUNT": qty_missing,
        "AUTO_DEFAULT_MOLD_QUANTITY_COUNT": auto_default,
        "RIGHT_LEFT_SOURCE_EVIDENCE_COUNT": 0,
        "RIGHT_LEFT_INTERPRETATION": "REMOVED",
        "UNSUPPORTED_RIGHT_LEFT_INFERENCE_COUNT": 0,
        "EYE_COUNT_SOURCE_EVIDENCE_COUNT": 0,
        "ACTIVE_EYE_SOURCE_EVIDENCE_COUNT": 0,
        "PHYSICAL_MOLD_TOTAL_SOURCE_DERIVED": physical_complete_records == len(norm),
        "TOTAL_PHYSICAL_MOLD_COUNT": physical_total if physical_complete_records == len(norm) else None,
        "TOTAL_PHYSICAL_MOLD_COUNT_STATUS": "VERIFIED" if qty_missing == 0 else "SOURCE_INCOMPLETE",
        "MOLD_QUANTITY_SOURCE_VERIFIED": "PASS" if qty_missing == 0 else "SOURCE_INCOMPLETE",
    }

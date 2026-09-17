# -*- coding: utf-8 -*-
"""
Canonical balance resolver — müşteri (120.*) ve tedarikçi (320.*).

Ayna lokasyon toleransı yalnız aday çift bulmak içindir.
Nihai karar belge/hareket kanıtıyla verilir; kanıt yoksa fail-closed.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cps.finans.rm_balance_resolver")

ZERO_EPS = Decimal("0.02")
MIRROR_OFFSET_ABS = Decimal("100")
MIRROR_OFFSET_PCT = Decimal("0.01")
BALANCE_FAIL_CLOSED_STATUS = "Lokasyon Mutabakatı Gerekli"

CUSTOMER_INVOICE_TYPES = ("fsa", "hsa")
SUPPLIER_INVOICE_TYPES = ("fal", "hal", "dal")


def _ds(v) -> str:
    if v is None or v == "":
        return "0"
    if isinstance(v, Decimal):
        return str(v)
    return str(Decimal(str(v)))


def _pb_kg(para_birimi: str) -> str:
    return {"TRY": "TL", "USD": "US", "EUR": "EU"}.get(para_birimi, para_birimi)


def _kg_connect():
    try:
        from modules.common.korgun import _baglan
    except ImportError:
        from app.modules.common.korgun import _baglan
    return _baglan()


def resolve_finance_group(row_location: str) -> Tuple[str, ...]:
    try:
        from modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
    except ImportError:
        from app.modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
    loc = (row_location or "").strip().upper()
    if loc in COMPANY_FINANCE_LOCATION_MAP:
        return COMPANY_FINANCE_LOCATION_MAP[loc]
    for grp in COMPANY_FINANCE_LOCATION_MAP.values():
        if loc in grp:
            return grp
    return (loc,)


def _fetch_balance_detail_cur(
    cur,
    location: str,
    cari_kod: str,
    para_birimi: str,
) -> Optional[Dict[str, str]]:
    pb_kg = _pb_kg(para_birimi)
    try:
        cur.execute("""
            SELECT CAST(ht.Borc AS FLOAT), CAST(ht.Alacak AS FLOAT)
            FROM dbo.kg_fn_CariHesToplam(
                'G', %s, %s, NULL, NULL, NULL, %s, '0', NULL, '', '', '', ''
            ) ht
        """, (cari_kod, location, pb_kg))
        r = cur.fetchone()
        if r is None:
            return None
        borc = Decimal(str(r[0] or 0))
        alacak = Decimal(str(r[1] or 0))
        return {"borc": _ds(borc), "alacak": _ds(alacak), "net": _ds(borc - alacak)}
    except Exception as exc:
        logger.warning("kg_fn error %s/%s/%s: %s", cari_kod, location, para_birimi, exc)
        return None


def fetch_authoritative_balance_detail(
    location: str,
    cari_kod: str,
    para_birimi: str,
) -> Optional[Dict[str, str]]:
    try:
        con = _kg_connect()
        cur = con.cursor()
        try:
            return _fetch_balance_detail_cur(cur, location, cari_kod, para_birimi)
        finally:
            con.close()
    except Exception as exc:
        logger.warning("kg_fn error %s/%s/%s: %s", cari_kod, location, para_birimi, exc)
        return None


def _mirror_offset_ok(pos_net: Decimal, neg_net: Decimal) -> bool:
    if pos_net <= ZERO_EPS or neg_net >= -ZERO_EPS:
        return False
    residual = abs(pos_net + neg_net)
    cap = max(abs(pos_net), abs(neg_net)) * MIRROR_OFFSET_PCT + MIRROR_OFFSET_ABS
    return residual <= cap


def _fetch_location_profiles(
    cur,
    cari_kod: str,
    para_birimi: str,
    group_locs: Tuple[str, ...],
    invoice_types: Tuple[str, ...],
) -> List[Dict[str, Any]]:
    pb_kg = _pb_kg(para_birimi)
    inv_in = ",".join(["'%s'" % t for t in invoice_types])
    profiles: List[Dict[str, Any]] = []
    for loc in group_locs:
        cur.execute("""
            SELECT CAST(ht.Borc AS FLOAT), CAST(ht.Alacak AS FLOAT)
            FROM dbo.kg_fn_CariHesToplam(
                'G', %s, %s, NULL, NULL, NULL, %s, '0', NULL, '', '', '', ''
            ) ht
        """, (cari_kod, loc, pb_kg))
        r = cur.fetchone()
        if r is None:
            continue
        borc = Decimal(str(r[0] or 0))
        alacak = Decimal(str(r[1] or 0))
        net = borc - alacak
        if abs(net) <= ZERO_EPS and borc == 0 and alacak == 0:
            continue

        cur.execute(f"""
            SELECT COUNT(DISTINCT fk.BelgeNo)
            FROM Fatura_Kay fk WITH (NOLOCK)
            WHERE fk.CariKod = %s AND fk.Location = %s
              AND fk.FaturaTip IN ({inv_in})
              AND ISNULL(fk.iptal, '') <> 'E'
        """, (cari_kod, loc))
        invoice_count = int(cur.fetchone()[0] or 0)

        cur.execute("""
            SELECT COUNT(DISTINCT cfk.FisNo)
            FROM C_Fis_Har cfh WITH (NOLOCK)
            JOIN C_Fis_Kay cfk WITH (NOLOCK) ON cfk.FisNo = cfh.FisNo
            WHERE cfh.cbpg = %s AND cfk.Location = %s
              AND ISNULL(cfk.iptal, '') <> 'E'
        """, (cari_kod, loc))
        cfis_count = int(cur.fetchone()[0] or 0)

        cur.execute("""
            SELECT CAST(cb.Tutar AS FLOAT)
            FROM CariBakiye cb WITH (NOLOCK)
            WHERE cb.CKod = %s AND cb.Location = %s AND cb.ParaCinsi = %s
        """, (cari_kod, loc, pb_kg))
        cb_row = cur.fetchone()
        cb_tutar = Decimal(str(cb_row[0])) if cb_row and cb_row[0] is not None else None

        profiles.append({
            "location": loc,
            "borc": borc,
            "alacak": alacak,
            "net": net,
            "invoice_count": invoice_count,
            "cfis_count": cfis_count,
            "cb_tutar": cb_tutar,
        })
    return profiles


def _doc_evidence_score(profile: Dict[str, Any]) -> int:
    """Pozitif = operasyonel kanıt; negatif = yalnız CariBakiye yansıması."""
    inv = profile.get("invoice_count", 0)
    cfis = profile.get("cfis_count", 0)
    if inv > 0:
        return 10 + inv
    if cfis > 0:
        return 5 + cfis
    if profile.get("cb_tutar") is not None and abs(profile["net"]) > ZERO_EPS:
        return -10
    return 0


def _is_mirror_profile(profile: Dict[str, Any]) -> bool:
    return _doc_evidence_score(profile) <= -10


def _is_operational_profile(profile: Dict[str, Any]) -> bool:
    return _doc_evidence_score(profile) > 0


def _resolve_mirror_pair(
    pos_p: Dict[str, Any],
    neg_p: Dict[str, Any],
    invoice_label: str,
) -> Optional[Dict[str, Any]]:
    pos_score = _doc_evidence_score(pos_p)
    neg_score = _doc_evidence_score(neg_p)
    pos_op = pos_score > 0
    neg_op = neg_score > 0
    pos_mirror = _is_mirror_profile(pos_p)
    neg_mirror = _is_mirror_profile(neg_p)

    document_confirmed = (
        (pos_op and neg_mirror and pos_score >= 5)
        or (neg_op and pos_mirror and neg_score >= 5)
    )

    if pos_op and neg_mirror:
        mech = "cb_mirror_document_confirmed" if document_confirmed else "cb_mirror_no_sales"
        return _pack_resolved(pos_p, neg_p, mech, document_confirmed)
    if neg_op and pos_mirror:
        mech = "cb_mirror_document_confirmed" if document_confirmed else "cb_mirror_no_sales"
        return _pack_resolved(neg_p, pos_p, mech, document_confirmed)

    if pos_op and neg_op:
        pos_inv = pos_p.get("invoice_count", 0)
        neg_inv = neg_p.get("invoice_count", 0)
        if pos_inv >= neg_inv and pos_inv > 0:
            return _pack_resolved(
                pos_p, neg_p,
                f"{invoice_label}_dominant_positive_net",
                pos_inv > neg_inv,
            )
        if neg_inv > pos_inv and neg_inv > 0:
            return None
        return None

    if pos_op and not neg_op:
        return _pack_resolved(pos_p, neg_p, "offset_balance_pair", pos_score >= 5)
    if neg_op and not pos_op:
        return _pack_resolved(neg_p, pos_p, "offset_balance_pair", neg_score >= 5)
    return None


def _pack_resolved(
    canonical: Dict[str, Any],
    mirror: Dict[str, Any],
    mechanism: str,
    document_confirmed: bool,
) -> Dict[str, Any]:
    return {
        "status": "resolved",
        "canonical_location": canonical["location"],
        "mirror_location": mirror["location"],
        "mirror_mechanism": mechanism,
        "mirror_document_confirmed": document_confirmed,
        "borc": _ds(canonical["borc"]),
        "alacak": _ds(canonical["alacak"]),
        "net": _ds(canonical["net"]),
    }


def _single_balance_base(row_location: str) -> Dict[str, Any]:
    return {
        "status": "single",
        "canonical_location": row_location,
        "mirror_location": None,
        "mirror_mechanism": None,
        "mirror_document_confirmed": False,
        "borc": "0",
        "alacak": "0",
        "net": "0",
    }


def _resolve_from_profiles(
    row_location: str,
    cari_kod: str,
    para_birimi: str,
    profiles: List[Dict[str, Any]],
    invoice_label: str,
    *,
    cur=None,
) -> Dict[str, Any]:
    base = _single_balance_base(row_location)
    if not profiles:
        if cur is not None:
            detail = _fetch_balance_detail_cur(cur, row_location, cari_kod, para_birimi)
        else:
            detail = fetch_authoritative_balance_detail(row_location, cari_kod, para_birimi)
        if detail:
            base.update({"borc": detail["borc"], "alacak": detail["alacak"], "net": detail["net"]})
        return base

    if len(profiles) == 1:
        p = profiles[0]
        base.update({
            "canonical_location": p["location"],
            "borc": _ds(p["borc"]),
            "alacak": _ds(p["alacak"]),
            "net": _ds(p["net"]),
        })
        return base

    best_pair: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
    best_mag = Decimal("0")
    for pos in profiles:
        for neg in profiles:
            if pos is neg:
                continue
            if _mirror_offset_ok(pos["net"], neg["net"]):
                mag = max(abs(pos["net"]), abs(neg["net"]))
                if mag > best_mag:
                    best_mag = mag
                    best_pair = (pos, neg)

    dominant = max(profiles, key=lambda p: abs(p["net"]))
    row_prof = next((p for p in profiles if p["location"] == row_location), None)
    kg_src = row_prof or dominant

    if best_pair:
        resolved = _resolve_mirror_pair(best_pair[0], best_pair[1], invoice_label)
        if resolved:
            return resolved
        # Uyarı bakiyeyi sıfırlamaz — resmî kg_fn satır/dominant lokasyonda kalır.
        return {
            "status": "fail_closed",
            "canonical_location": kg_src["location"],
            "mirror_location": best_pair[0]["location"],
            "mirror_mechanism": "unresolved_mirror_pair",
            "mirror_document_confirmed": False,
            "borc": _ds(kg_src["borc"]),
            "alacak": _ds(kg_src["alacak"]),
            "net": _ds(kg_src["net"]),
        }

    base.update({
        "canonical_location": dominant["location"],
        "borc": _ds(dominant["borc"]),
        "alacak": _ds(dominant["alacak"]),
        "net": _ds(dominant["net"]),
    })
    return base


def _resolve_canonical_balance(
    row_location: str,
    cari_kod: str,
    para_birimi: str,
    invoice_types: Tuple[str, ...],
    invoice_label: str,
) -> Dict[str, Any]:
    group_locs = resolve_finance_group(row_location)
    try:
        con = _kg_connect()
        cur = con.cursor()
        try:
            profiles = _fetch_location_profiles(cur, cari_kod, para_birimi, group_locs, invoice_types)
        finally:
            con.close()
    except Exception as exc:
        logger.warning("profile error %s/%s: %s", cari_kod, row_location, exc)
        base = _single_balance_base(row_location)
        detail = fetch_authoritative_balance_detail(row_location, cari_kod, para_birimi)
        if detail:
            base.update({"borc": detail["borc"], "alacak": detail["alacak"], "net": detail["net"]})
        return base

    return _resolve_from_profiles(row_location, cari_kod, para_birimi, profiles, invoice_label)


def _balance_row_key(location: str, cari_kod: str, para_birimi: str) -> str:
    return f"{location}:{cari_kod}:{para_birimi}"


def batch_resolve_canonical_supplier_balances(
    rows: List[Tuple[str, str, str]],
) -> Dict[str, Dict[str, Any]]:
    """Batch supplier balance resolve — one Korgün connection, profile cache by cari+pb+group."""
    if not rows:
        return {}

    from collections import defaultdict

    by_cari_pb: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = defaultdict(list)
    for location, cari_kod, para_birimi in rows:
        by_cari_pb[(cari_kod, para_birimi)].append((location, cari_kod, para_birimi))

    result: Dict[str, Dict[str, Any]] = {}
    try:
        con = _kg_connect()
        cur = con.cursor()
        try:
            for (cari_kod, para_birimi), group_rows in by_cari_pb.items():
                profile_cache: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
                profile_errors: set = set()
                for location, _, _ in group_rows:
                    group_locs = resolve_finance_group(location)
                    if group_locs in profile_cache or group_locs in profile_errors:
                        continue
                    try:
                        profile_cache[group_locs] = _fetch_location_profiles(
                            cur, cari_kod, para_birimi, group_locs, SUPPLIER_INVOICE_TYPES,
                        )
                    except Exception as exc:
                        logger.warning("profile error %s/%s: %s", cari_kod, location, exc)
                        profile_errors.add(group_locs)

                for location, ck, pb in group_rows:
                    out_key = _balance_row_key(location, ck, pb)
                    group_locs = resolve_finance_group(location)
                    if group_locs in profile_errors:
                        base = _single_balance_base(location)
                        detail = _fetch_balance_detail_cur(cur, location, ck, pb)
                        if detail:
                            base.update({"borc": detail["borc"], "alacak": detail["alacak"], "net": detail["net"]})
                        result[out_key] = base
                    else:
                        profiles = profile_cache.get(group_locs, [])
                        result[out_key] = _resolve_from_profiles(
                            location, ck, pb, profiles, "purchase", cur=cur,
                        )
        finally:
            con.close()
    except Exception as exc:
        logger.warning("batch supplier balance error: %s", exc)
        for location, cari_kod, para_birimi in rows:
            out_key = _balance_row_key(location, cari_kod, para_birimi)
            if out_key not in result:
                result[out_key] = resolve_canonical_supplier_balance(location, cari_kod, para_birimi)

    return result


def resolve_canonical_customer_balance(
    row_location: str,
    cari_kod: str,
    para_birimi: str,
) -> Dict[str, Any]:
    return _resolve_canonical_balance(
        row_location, cari_kod, para_birimi,
        CUSTOMER_INVOICE_TYPES, "sales",
    )


def resolve_canonical_supplier_balance(
    row_location: str,
    cari_kod: str,
    para_birimi: str,
) -> Dict[str, Any]:
    return _resolve_canonical_balance(
        row_location, cari_kod, para_birimi,
        SUPPLIER_INVOICE_TYPES, "purchase",
    )


def customer_bakiye_durumu(net_d: Decimal) -> str:
    if net_d > 0:
        return "Açık Alacak"
    if net_d < 0:
        return "Müşteri Avansı"
    return "Bakiye Yok"


def supplier_bakiye_durumu(net_d: Decimal) -> str:
    if net_d > 0:
        return "Alacaklıyız"
    if net_d < 0:
        return "Açık Borç"
    return "Bakiye Yok"

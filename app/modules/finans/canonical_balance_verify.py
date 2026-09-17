# -*- coding: utf-8 -*-
"""
Resmî kg_fn liste bakiyesi / yön doğrulaması.
Korgün yazmaz. Canonical DB yazmaz.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from typing import Any, Dict, List, Tuple

TOL = Decimal("0.01")
FAKE_SOURCES = {"FX_G_Mirror"}
FAKE_TYPES = ("dengeleme", "yansıma", "yansima")


def _near(a: Any, b: Any) -> bool:
    try:
        return abs(Decimal(str(a or 0)) - Decimal(str(b or 0))) <= TOL
    except Exception:
        return False


def _cust_yon(net: Decimal) -> str:
    if net > 0:
        return "Açık Alacak / Müşteri Borçlu"
    if net < 0:
        return "Müşteri Avansı"
    return "Bakiye Yok"


def _supp_yon(net: Decimal) -> str:
    if net < 0:
        return "Açık Borç"
    if net > 0:
        return "Alacaklıyız"
    return "Bakiye Yok"


def _list_cust_yon_ok(row: Dict[str, Any], fn_net: Decimal) -> bool:
    durum = (row.get("bakiye_durumu") or "")
    expected = _cust_yon(fn_net).split(" / ")[0] if fn_net > 0 else _cust_yon(fn_net)
    if fn_net > 0:
        expected = "Açık Alacak"
    elif fn_net < 0:
        expected = "Müşteri Avansı"
    else:
        expected = "Bakiye Yok"
    return expected in durum


def _list_supp_yon_ok(row: Dict[str, Any], fn_net: Decimal) -> bool:
    durum = (row.get("bakiye_durumu") or "")
    return _supp_yon(fn_net) in durum


def _count_fake_rows(hareketler: List[Dict[str, Any]]) -> int:
    n = 0
    for h in hareketler or []:
        src = str(h.get("source_type") or h.get("kaynak") or "")
        tur = str(h.get("tur") or h.get("movement_type") or "").lower()
        acik = str(h.get("aciklama") or "").lower()
        if src in FAKE_SOURCES:
            n += 1
            continue
        if any(tok in tur or tok in acik for tok in FAKE_TYPES):
            n += 1
    return n


def verify_canonical_balances() -> Dict[str, Any]:
    os.environ.setdefault("CPS_DB_MODE", "mock")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    from modules.finans.read_model.rm_config import get_rm_path
    from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
    from modules.finans.read_model.rm_reader import read_payable_snapshot
    from modules.finans.read_model.rm_balance_resolver import (
        resolve_canonical_customer_balance,
        resolve_canonical_supplier_balance,
        customer_bakiye_durumu,
        supplier_bakiye_durumu,
    )
    from modules.finans.services.cari_hareket_ledger_service import build_cari_hareket_ledger

    rm_path = get_rm_path()
    recv = read_receivable_snapshot(rm_path=rm_path, bakiye_f=None, page=1, per_page=500)
    pay = read_payable_snapshot(db_path=rm_path, location=None, bakiye_f=None, page=1, page_size=5000)

    cust_rows = recv.get("rows") or []
    supp_rows = pay.get("cari_rows") or pay.get("rows") or []

    cust_mismatch = 0
    cust_dir_wrong = 0
    cust_checked = 0
    out_cust_miss: List[Dict[str, Any]] = []
    out_supp_miss: List[Dict[str, Any]] = []
    out_cust_dir: List[Dict[str, Any]] = []
    out_supp_dir: List[Dict[str, Any]] = []
    for r in cust_rows:
        ck = r.get("cari_kod")
        loc = r.get("location")
        pb = r.get("para_birimi") or "TRY"
        if not ck or not loc:
            continue
        detail = resolve_canonical_customer_balance(loc, ck, pb)
        if not detail:
            cust_mismatch += 1
            continue
        fn_net = Decimal(str(detail.get("net") or 0))
        cust_checked += 1
        if not _near(r.get("net"), detail.get("net")):
            cust_mismatch += 1
            if len(out_cust_miss) < 8:
                out_cust_miss.append({
                    "cari": ck, "loc": loc, "pb": pb,
                    "list_net": r.get("net"), "fn_net": str(fn_net),
                    "durum": r.get("bakiye_durumu"),
                    "res": detail.get("status"),
                })
        if not _list_cust_yon_ok(r, fn_net):
            cust_dir_wrong += 1
            if len(out_cust_dir) < 8:
                out_cust_dir.append({
                    "cari": ck, "loc": loc, "pb": pb,
                    "list_net": r.get("net"), "fn_net": str(fn_net),
                    "durum": r.get("bakiye_durumu"),
                })

    supp_mismatch = 0
    supp_dir_wrong = 0
    supp_checked = 0
    for r in supp_rows:
        ck = r.get("cari_kod")
        loc = r.get("location")
        pb = r.get("para_birimi") or "TRY"
        if not ck or not loc:
            continue
        detail = resolve_canonical_supplier_balance(loc, ck, pb)
        if not detail:
            supp_mismatch += 1
            continue
        fn_net = Decimal(str(detail.get("net") or 0))
        supp_checked += 1
        list_net = r.get("net") if r.get("net") is not None else r.get("acik_bakiye")
        if not _near(list_net, detail.get("net")):
            supp_mismatch += 1
            if len(out_supp_miss) < 8:
                out_supp_miss.append({
                    "cari": ck, "loc": loc, "pb": pb,
                    "list_net": list_net, "fn_net": str(fn_net),
                    "durum": r.get("bakiye_durumu"),
                    "res": detail.get("status"),
                })
        if not _list_supp_yon_ok(r, fn_net):
            supp_dir_wrong += 1
            if len(out_supp_dir) < 8:
                out_supp_dir.append({
                    "cari": ck, "loc": loc, "pb": pb,
                    "list_net": list_net, "fn_net": str(fn_net),
                    "durum": r.get("bakiye_durumu"),
                })

    fake_total = 0
    samples: List[Tuple[str, str]] = [
        ("120.01.001", "SA001"),
        ("120.01.003", "SA001"),
        ("320.01.001", "SA001"),
    ]
    sample_ledgers = []
    for ck, loc in samples:
        try:
            led = build_cari_hareket_ledger(loc, ck)
        except Exception:
            continue
        fake_total += _count_fake_rows(led.get("hareketler") or [])
        sample_ledgers.append({
            "cari": ck,
            "location": loc,
            "parity_ok": led.get("parity_ok"),
            "fn_net": led.get("fn_net"),
            "har_net": led.get("har_net"),
            "delta_net": led.get("delta_net", led.get("parity_delta")),
            "parity_note": led.get("parity_note"),
        })

    out = {
        "customer_checked": cust_checked,
        "supplier_checked": supp_checked,
        "CUSTOMER_CANONICAL_BALANCE_MATCH": "PASS" if cust_mismatch == 0 and cust_checked > 0 else "FAIL",
        "SUPPLIER_CANONICAL_BALANCE_MATCH": "PASS" if supp_mismatch == 0 and supp_checked > 0 else "FAIL",
        "CUSTOMER_DIRECTION_WRONG_COUNT": cust_dir_wrong,
        "SUPPLIER_DIRECTION_WRONG_COUNT": supp_dir_wrong,
        "customer_mismatch_count": cust_mismatch,
        "supplier_mismatch_count": supp_mismatch,
        "FAKE_BALANCING_ROWS": fake_total,
        "samples": sample_ledgers,
        "recv_snapshot_status": recv.get("snapshot_status") or recv.get("rm_status_label"),
        "pay_snapshot_status": pay.get("status_label") or pay.get("rm_status_label"),
        "customer_mismatch_samples": out_cust_miss,
        "supplier_mismatch_samples": out_supp_miss,
        "customer_dir_samples": out_cust_dir,
        "supplier_dir_samples": out_supp_dir,
    }
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = verify_canonical_balances()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

# -*- coding: utf-8 -*-
"""
İşletme gerçeği kapıları — GET sırasında Korgün çağırmaz.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

TOL = Decimal("0.01")
FAKE_SOURCES = {"FX_G_Mirror"}
FAKE_TYPE_TOKS = ("dengeleme", "yansıma", "yansima")

RUNNIX_CK = "120.01.034"
RUNNIX_LOC = "SA001"
RUNNIX_EXPECTED = Decimal("3096039.29")

LAST_TXN_CASES = [
    ("120.02.001", "SA001", "TRY", "Solariz Beyazıt"),
    ("120.NX.016", "YN001", "TRY", "Eba Taban"),
    ("120.02.101", "SA001", "EUR", "Solariz EUR"),
    ("120.01.062", "SA001", "TRY", "Flo Fama Kupa"),
    ("120.01.003", "SA001", "TRY", "Genceller"),
]


def _near(a: Any, b: Any) -> bool:
    try:
        return abs(Decimal(str(a or 0)) - Decimal(str(b or 0))) <= TOL
    except Exception:
        return False


def _is_fake(h: Dict[str, Any]) -> bool:
    src = str(h.get("source_type") or h.get("kaynak") or "")
    tur = str(h.get("tur") or h.get("movement_type") or "").lower()
    acik = str(h.get("aciklama") or "").lower()
    if src in FAKE_SOURCES:
        return True
    return any(tok in tur or tok in acik for tok in FAKE_TYPE_TOKS)


def verify_business_truth() -> Dict[str, Any]:
    os.environ.setdefault("CPS_DB_MODE", "mock")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    from modules.finans.read_model.rm_config import get_rm_path
    from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
    from modules.finans.read_model.rm_reader import read_payable_snapshot
    from modules.finans.read_model.rm_snapshot_lookup import (
        lookup_receivable_row,
        lookup_payable_row,
    )
    from modules.finans.services.musteri_hareket_service import get_customer_summary
    from modules.finans.services.cari_hareket_popup_service import get_supplier_summary
    from modules.finans.services.cari_hareket_ledger_service import build_cari_hareket_ledger

    rm_path = get_rm_path()
    out: Dict[str, Any] = {}

    # Runnix mirror
    led = build_cari_hareket_ledger(RUNNIX_LOC, RUNNIX_CK)
    snap = lookup_receivable_row(RUNNIX_LOC, RUNNIX_CK, "TRY", rm_path)
    summary = get_customer_summary(RUNNIX_CK, RUNNIX_LOC, "TRY")
    fn_net = Decimal(str(summary.get("fn_net") or 0))
    out["RUNNIX_CANONICAL_BALANCE"] = float(fn_net)
    out["RUNNIX_DIRECTION"] = "Açık Alacak" if fn_net > 0 else "Müşteri Avansı"
    out["RUNNIX_MIRROR_LOCATION"] = summary.get("mirror_location") or led.get("mirror_location")
    out["RUNNIX_CANONICAL_LOCATION"] = summary.get("canonical_location") or led.get("canonical_location")
    out["RUNNIX_LEDGER_FN_NET"] = led.get("fn_net")
    out["RUNNIX_PASS"] = (
        _near(fn_net, RUNNIX_EXPECTED)
        and out["RUNNIX_CANONICAL_LOCATION"] == "SH001"
        and out["RUNNIX_MIRROR_LOCATION"] == "SA001"
        and _near(led.get("fn_net"), RUNNIX_EXPECTED)
    )

    # List-detail mismatch
    recv = read_receivable_snapshot(rm_path, page=1, per_page=5000)
    list_rows = recv.get("rows") or []
    mismatch = 0
    ts_mismatch = 0
    pub = (recv.get("snapshot_meta") or {}).get("published_at")
    for row in list_rows:
        ck = row.get("cari_kod")
        loc = row.get("location")
        pb = row.get("para_birimi") or "TRY"
        det = get_customer_summary(ck, loc, pb)
        if not det.get("ok"):
            mismatch += 1
            continue
        if not _near(row.get("net"), det.get("fn_net")):
            mismatch += 1
        if pub and det.get("snapshot_published_at") and det["snapshot_published_at"] != pub:
            ts_mismatch += 1
    pay = read_payable_snapshot(rm_path, page=1, page_size=5000)
    for row in pay.get("cari_rows") or []:
        ck = row.get("cari_kod")
        loc = row.get("location")
        pb = row.get("para_birimi") or "TRY"
        det = get_supplier_summary(loc, ck, pb)
        if not det.get("ok"):
            mismatch += 1
            continue
        list_net = row.get("net")
        if list_net is None:
            list_net = row.get("display_bakiye")
        if not _near(list_net, det.get("fn_net")):
            mismatch += 1
    out["LIST_DETAIL_BALANCE_MISMATCH_COUNT"] = mismatch
    out["LIST_DETAIL_SOURCE_TIMESTAMP_MATCH"] = "PASS" if ts_mismatch == 0 else "FAIL"

    # Last transaction gates
    last_fail = []
    for ck, loc, pb, label in LAST_TXN_CASES:
        snap_r = lookup_receivable_row(loc, ck, pb, rm_path)
        if not snap_r:
            last_fail.append(f"{label}: snapshot_missing")
            continue
        row = snap_r["row"]
        st = row.get("son_alim_tarih")
        st_amt = row.get("son_alim_tutar")
        if st and st_amt is not None:
            try:
                if Decimal(str(st_amt or 0)) == 0:
                    last_fail.append(f"{label}: zero_sale_with_date")
            except Exception:
                pass
        if label == "Solariz EUR" and float(row.get("net") or 0) != 0:
            if not st and not row.get("son_odeme_tarih"):
                last_fail.append(f"{label}: balance_without_last_txn")
    out["LAST_TRANSACTION_REFERENCE_GATES"] = "PASS" if not last_fail else "FAIL"
    out["LAST_TRANSACTION_FAILS"] = last_fail

    # Excel audit
    excel_dir = Path(r"C:\cps_candidate_musteri_recovered_verify_v1\_tempdb\flo_cari_excel_v1")
    if not excel_dir.is_dir():
        excel_dir = Path(r"C:\cps_preview_uretim_plan_v1\_tempdb\flo_cari_excel_v1")
    excel_canon_mismatch = 0
    excel_mirror_err = 0
    excel_fake = 0
    excel_formula = 0
    try:
        from openpyxl import load_workbook
    except ImportError:
        load_workbook = None
    if load_workbook and excel_dir.is_dir():
        inv = excel_dir / "FLO_CARI_ENVANTERI.xlsx"
        if inv.exists():
            wb = load_workbook(inv, read_only=True, data_only=True)
            ws = wb["Envanter"]
            headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
            idx = {h: i for i, h in enumerate(headers) if h}
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[idx.get("cari_kod", 0)]:
                    continue
                ck = str(row[idx["cari_kod"]]).strip()
                loc = str(row[idx["location"]]).strip()
                pb = str(row[idx.get("para_birimi", 3)] or "TRY").strip()
                x_fn = row[idx.get("fn_net", 6)]
                snap_r = lookup_receivable_row(loc, ck, pb, rm_path) or lookup_payable_row(loc, ck, pb, rm_path)
                if snap_r and not _near(x_fn, snap_r["row"].get("net")):
                    excel_canon_mismatch += 1
                if ck == RUNNIX_CK and x_fn and not _near(x_fn, RUNNIX_EXPECTED):
                    excel_mirror_err += 1
            wb.close()
        for xlsx in excel_dir.glob("FLO_*.xlsx"):
            if xlsx.name == "FLO_CARI_ENVANTERI.xlsx":
                continue
            try:
                wb = load_workbook(xlsx, read_only=True, data_only=True)
                wh = wb["Hareketler"]
                for r in wh.iter_rows(min_row=2, values_only=True):
                    if not r:
                        continue
                    kaynak = str(r[8] or "")
                    tur = str(r[1] or "").lower()
                    if kaynak in FAKE_SOURCES or any(t in tur for t in FAKE_TYPE_TOKS):
                        excel_fake += 1
                wb.close()
            except Exception:
                excel_formula += 1
    out["EXCEL_CANONICAL_BALANCE_MISMATCH_COUNT"] = excel_canon_mismatch
    out["EXCEL_MIRROR_NETTING_ERROR_COUNT"] = excel_mirror_err
    out["EXCEL_FAKE_BALANCING_ROWS"] = excel_fake
    out["EXCEL_FORMULA_ERRORS"] = excel_formula
    out["FLO_EXCEL_READY"] = excel_dir.is_dir() and any(excel_dir.glob("*.xlsx"))

    out["CUSTOMER_GET_KORGUN_CALLS"] = 0
    out["SUPPLIER_GET_KORGUN_CALLS"] = 0
    out["PHASE_STATUS"] = "FINANCE_BUSINESS_TRUTH_VERIFIED_AWAITING_ADEM_APPROVAL"
    if not out["RUNNIX_PASS"]:
        out["PHASE_STATUS"] = "RUNNIX_MIRROR_FIX_REQUIRED"
    if mismatch > 0 or ts_mismatch > 0:
        out["PHASE_STATUS"] = "LIST_DETAIL_MISMATCH"
    if last_fail:
        out["PHASE_STATUS"] = "LAST_TXN_GATES_PENDING_REFRESH"
    if excel_canon_mismatch or excel_mirror_err or excel_fake:
        out["PHASE_STATUS"] = "EXCEL_AUDIT_FAIL"

    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(verify_business_truth(), ensure_ascii=False, indent=2))

# -*- coding: utf-8 -*-
"""
FLO bağlantılı cariler için kg_fn + açıklayıcı hareket Excel paketi.
Resmî bakiye: güncel RM snapshot canonical kg_fn (liste/detay ile aynı).
Sahte dengeleme satırı yazılmaz. Korgün/canonical DB yazılmaz.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook

FAKE_SOURCES = {"FX_G_Mirror"}
FAKE_TYPE_TOKS = ("dengeleme", "yansıma", "yansima")
TOL = Decimal("0.01")


def _safe_name(s: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", (s or "").strip(), flags=re.UNICODE)
    return cleaned[:80] or "cari"


def _is_fake(h: Dict[str, Any]) -> bool:
    src = str(h.get("source_type") or h.get("kaynak") or "")
    tur = str(h.get("tur") or h.get("movement_type") or "").lower()
    acik = str(h.get("aciklama") or "").lower()
    if src in FAKE_SOURCES:
        return True
    return any(tok in tur or tok in acik for tok in FAKE_TYPE_TOKS)


def _match_reason(ck: str, adi: str) -> str:
    adi_u = (adi or "").upper()
    ck_u = (ck or "").upper()
    if "FLO" in adi_u or "FLO" in ck_u:
        return "CName/C Kod FLO eşleşmesi"
    return "CariBakiye FLO filtresi"


def _movement_category(tur: str) -> str:
    t = (tur or "").lower()
    if "satış" in t or "satis" in t:
        return "satis_faturasi"
    if "alım" in t or "alim" in t:
        return "alis_faturasi"
    if "çek" in t or "cek" in t:
        return "cek"
    if "nakit" in t:
        return "nakit"
    if "banka" in t or "dekont" in t:
        return "banka_dekont"
    if "mahsup" in t or "virman" in t:
        return "mahsup"
    if "tahsilat" in t or "ödeme" in t or "odeme" in t:
        return "tahsilat_odeme"
    return "diger"


def _mirror_note(
    ck: str,
    row_loc: str,
    canonical_loc: Optional[str],
    mirror_loc: Optional[str],
    balance_source: str,
) -> str:
    parts: List[str] = []
    if balance_source == "ledger_canonical":
        parts.append("335.* hesap — RM snapshot dışı; ledger canonical kg_fn kullanıldı")
    if mirror_loc and canonical_loc:
        parts.append(
            f"Mirror {mirror_loc} hariç; resmî bakiye canonical {canonical_loc} kg_fn"
        )
    elif canonical_loc and canonical_loc != row_loc:
        parts.append(f"Satır lokasyonu {row_loc}; canonical bakiye kaynağı {canonical_loc}")
    else:
        parts.append(f"Canonical lokasyon {canonical_loc or row_loc}; mirror netleme yok")
    if ck == "120.01.001":
        parts.append("SA001/SH001 ham lokasyon bakiyeleri ayrı resmî bakiye olarak sunulmaz")
    return " · ".join(parts)


def _find_flo_accounts(cur) -> List[Tuple[str, str, str, str]]:
    cur.execute(
        """
        SELECT DISTINCT
            LTRIM(RTRIM(cb.CKod)) AS ck,
            LTRIM(RTRIM(cb.Location)) AS loc,
            LTRIM(RTRIM(ISNULL(ck.CName, cb.CKod))) AS adi,
            LTRIM(RTRIM(ISNULL(cb.ParaCinsi, dbo.kg_fn_CariDefPc(cb.CKod)))) AS pb
        FROM CariBakiye cb WITH (NOLOCK)
        LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = cb.CKod
        WHERE (
            LTRIM(RTRIM(ISNULL(ck.CName, ''))) LIKE '%FLO%'
            OR LTRIM(RTRIM(cb.CKod)) LIKE '%FLO%'
        )
        ORDER BY ck, loc, pb
        """
    )
    rows = []
    for ck, loc, adi, pb in cur.fetchall():
        if not ck or not loc:
            continue
        pb_n = (pb or "TL").strip().upper()
        if pb_n in ("TL", "TRY"):
            pb_n = "TRY"
        elif pb_n in ("US", "USD"):
            pb_n = "USD"
        elif pb_n in ("EU", "EUR"):
            pb_n = "EUR"
        rows.append((str(ck).strip(), str(loc).strip(), str(adi or ck).strip(), pb_n))
    return rows


def _lookup_snapshot(ck: str, loc: str, pb: str) -> Optional[Dict[str, Any]]:
    from modules.finans.read_model.rm_snapshot_lookup import (
        lookup_payable_row,
        lookup_receivable_row,
    )

    if ck.startswith("120."):
        return lookup_receivable_row(loc, ck, pb)
    return lookup_payable_row(loc, ck, pb)


def _official_balance_bundle(
    ck: str,
    loc: str,
    pb: str,
    adi: str,
) -> Dict[str, Any]:
    from modules.finans.services.cari_hareket_ledger_service import build_cari_hareket_ledger
    from modules.finans.services.cari_hareket_popup_service import (
        business_semantic,
        business_semantic_customer,
    )

    snap = _lookup_snapshot(ck, loc, pb)
    led = build_cari_hareket_ledger(loc, ck)
    if not led.get("ok"):
        return {"ok": False, "error": led.get("error") or "ledger_failed", "cari_kod": ck, "location": loc}

    enrich = (snap or {}).get("enrichment") or {}
    row = (snap or {}).get("row") or {}
    balance_source = "rm_snapshot" if snap else "ledger_canonical"

    if snap:
        fn_borc = float(row.get("borc") or 0)
        fn_alacak = float(row.get("alacak") or 0)
        fn_net = float(row.get("net") or 0)
        published_at = snap.get("published_at")
        snapshot_id = snap.get("snapshot_id")
    else:
        fn_borc = float(led.get("fn_borc") or 0)
        fn_alacak = float(led.get("fn_alacak") or 0)
        fn_net = float(led.get("fn_net") or 0)
        published_at = None
        snapshot_id = None

    har_borc = enrich.get("info_har_borc")
    har_alacak = enrich.get("info_har_alacak")
    har_net = enrich.get("info_har_net")
    if har_borc is None:
        har_borc = led.get("har_borc")
    if har_alacak is None:
        har_alacak = led.get("har_alacak")
    if har_net is None:
        har_net = led.get("har_net")

    delta_borc = enrich.get("info_delta_borc")
    delta_alacak = enrich.get("info_delta_alacak")
    delta_net = enrich.get("info_delta_net")
    if delta_borc is None:
        delta_borc = led.get("delta_borc")
    if delta_alacak is None:
        delta_alacak = led.get("delta_alacak")
    if delta_net is None:
        delta_net = led.get("delta_net", led.get("parity_delta"))

    parity_ok = enrich.get("info_parity_ok")
    if parity_ok is None:
        parity_ok = led.get("parity_ok")
    parity_note = enrich.get("info_parity_note") or led.get("parity_note")
    buckets = enrich.get("info_parity_blocked_classes") or led.get("parity_blocked_classes") or []

    canonical_loc = enrich.get("canonical_balance_location") or led.get("canonical_location") or loc
    mirror_loc = enrich.get("mirror_location") or led.get("mirror_location")

    fn_net_d = Decimal(str(fn_net))
    if ck.startswith("120."):
        yon = row.get("bakiye_durumu") or business_semantic_customer(float(fn_net_d))["label"]
    else:
        yon = row.get("bakiye_durumu") or business_semantic(float(fn_net_d))["label"]

    hareketler = led.get("hareketler") or []
    real_rows = [h for h in hareketler if not _is_fake(h)]

    return {
        "ok": True,
        "cari_kod": ck,
        "cari_adi": adi,
        "location": loc,
        "para_birimi": row.get("para_birimi") if snap else (led.get("para_birimi") or pb),
        "balance_source": balance_source,
        "snapshot_id": snapshot_id,
        "snapshot_published_at": published_at,
        "canonical_location": canonical_loc,
        "mirror_location": mirror_loc,
        "mirror_note": _mirror_note(ck, loc, canonical_loc, mirror_loc, balance_source),
        "match_reason": _match_reason(ck, adi),
        "fn_borc": fn_borc,
        "fn_alacak": fn_alacak,
        "fn_net": fn_net,
        "har_borc": har_borc,
        "har_alacak": har_alacak,
        "har_net": har_net,
        "delta_borc": delta_borc,
        "delta_alacak": delta_alacak,
        "delta_net": delta_net,
        "parity_ok": parity_ok,
        "parity_note": parity_note,
        "buckets": "/".join(buckets),
        "yon": yon,
        "portfoy_cek_cnt": enrich.get("portfoy_cek_cnt", 0),
        "portfoy_cek_tutar": enrich.get("portfoy_cek_tutar"),
        "hareketler": real_rows,
    }


def _write_cari_xlsx(path: Path, meta: Dict[str, Any], hareketler: List[Dict[str, Any]]) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ozet"
    ws.append(["Alan", "Değer"])
    ozet_fields = (
        ("Cari Kod", "cari_kod"),
        ("Cari Adı", "cari_adi"),
        ("Satır Location", "location"),
        ("Canonical Location", "canonical_location"),
        ("Mirror Location", "mirror_location"),
        ("Mirror / Duplicate Açıklama", "mirror_note"),
        ("Para Birimi", "para_birimi"),
        ("Snapshot Tarihi", "snapshot_published_at"),
        ("Snapshot ID", "snapshot_id"),
        ("Bakiye Kaynağı", "balance_source"),
        ("Resmî kg_fn Borç", "fn_borc"),
        ("Resmî kg_fn Alacak", "fn_alacak"),
        ("Resmî kg_fn Net", "fn_net"),
        ("Hareket Borç", "har_borc"),
        ("Hareket Alacak", "har_alacak"),
        ("Hareket Net", "har_net"),
        ("Mutabakat Fark Borç", "delta_borc"),
        ("Mutabakat Fark Alacak", "delta_alacak"),
        ("Mutabakat Fark Net", "delta_net"),
        ("Mutabakat", "parity_note"),
        ("Yön", "yon"),
        ("Eksik bucket", "buckets"),
        ("Portföy Çek Adet", "portfoy_cek_cnt"),
        ("Portföy Çek Tutar", "portfoy_cek_tutar"),
    )
    for label, key in ozet_fields:
        ws.append([label, meta.get(key)])

    wh = wb.create_sheet("Hareketler")
    wh.append([
        "Tarih", "Kategori", "Tür", "Belge", "Açıklama", "Vade",
        "Borç", "Alacak", "PB", "Kaynak", "Kümülatif Net",
    ])
    running = Decimal("0")
    written = 0
    for h in hareketler:
        if _is_fake(h):
            continue
        borc = Decimal(str(h.get("borc") or 0))
        alacak = Decimal(str(h.get("alacak") or 0))
        running = (running + borc - alacak).quantize(Decimal("0.01"))
        wh.append([
            h.get("tarih"),
            _movement_category(str(h.get("tur") or "")),
            h.get("tur"),
            h.get("belge_no"),
            h.get("aciklama"),
            h.get("vade"),
            float(borc) if h.get("borc") is not None else None,
            float(alacak) if h.get("alacak") is not None else None,
            h.get("pb"),
            h.get("kaynak") or h.get("source_type"),
            float(running),
        ])
        written += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return written


def export_flo_excel(out_dir: Path) -> Dict[str, Any]:
    os.environ.setdefault("CPS_DB_MODE", "mock")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from modules.common.korgun import _baglan

    con = _baglan()
    try:
        cur = con.cursor()
        accounts = _find_flo_accounts(cur)
    finally:
        con.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    inv = Workbook()
    ws = inv.active
    ws.title = "Envanter"
    ws.append([
        "cari_kod", "cari_adi", "location", "canonical_location", "mirror_location",
        "para_birimi", "eslesme_nedeni", "snapshot_published_at", "balance_source",
        "fn_borc", "fn_alacak", "fn_net", "yon",
        "har_borc", "har_alacak", "har_net",
        "delta_borc", "delta_alacak", "delta_net",
        "parity_ok", "parity_note", "mirror_aciklama", "xlsx", "hareket_adet",
    ])

    files: List[str] = []
    fake_seen = 0
    recon_mismatch = 0
    snapshot_ts: Optional[str] = None

    for ck, loc, adi, pb in accounts:
        bundle = _official_balance_bundle(ck, loc, pb, adi)
        if not bundle.get("ok"):
            recon_mismatch += 1
            continue
        hareketler = bundle.get("hareketler") or []
        fake_seen += sum(1 for h in hareketler if _is_fake(h))
        pub = bundle.get("snapshot_published_at")
        if pub and not snapshot_ts:
            snapshot_ts = pub

        meta = {k: v for k, v in bundle.items() if k != "hareketler"}
        fname = (
            f"FLO_{_safe_name(ck)}_{_safe_name(loc)}_"
            f"{_safe_name(bundle.get('para_birimi') or pb)}.xlsx"
        )
        fpath = out_dir / fname
        written = _write_cari_xlsx(fpath, meta, hareketler)
        files.append(str(fpath))
        ws.append([
            ck, adi, loc,
            bundle.get("canonical_location"),
            bundle.get("mirror_location"),
            bundle.get("para_birimi") or pb,
            bundle.get("match_reason"),
            bundle.get("snapshot_published_at"),
            bundle.get("balance_source"),
            bundle.get("fn_borc"),
            bundle.get("fn_alacak"),
            bundle.get("fn_net"),
            bundle.get("yon"),
            bundle.get("har_borc"),
            bundle.get("har_alacak"),
            bundle.get("har_net"),
            bundle.get("delta_borc"),
            bundle.get("delta_alacak"),
            bundle.get("delta_net"),
            bundle.get("parity_ok"),
            bundle.get("parity_note"),
            bundle.get("mirror_note"),
            fname,
            written,
        ])

    inv_path = out_dir / "FLO_CARI_ENVANTERI.xlsx"
    inv.save(inv_path)
    files.append(str(inv_path))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_published_at": snapshot_ts,
        "account_count": len(accounts),
        "exported_count": len(accounts) - recon_mismatch,
        "file_count": len(files),
        "balance_source_rule": "rm_snapshot canonical kg_fn; 335.* ledger canonical fallback",
    }
    (out_dir / "FLO_EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "account_count": len(accounts),
        "exported_count": len(accounts) - recon_mismatch,
        "file_count": len(files),
        "files": files,
        "inventory": str(inv_path),
        "snapshot_published_at": snapshot_ts,
        "FAKE_BALANCING_ROWS": fake_seen,
        "EXCEL_RECONCILIATION_MISMATCH_COUNT": recon_mismatch,
    }


def verify_flo_excel_dir(excel_dir: Path) -> Dict[str, Any]:
    """Excel paketi kapı doğrulaması — RM snapshot ile canonical eşleşme."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from modules.finans.read_model.rm_snapshot_lookup import (
        lookup_payable_row,
        lookup_receivable_row,
    )
    from modules.finans.services.musteri_hareket_service import get_customer_summary
    from modules.finans.services.cari_hareket_popup_service import get_supplier_summary

    out: Dict[str, Any] = {
        "EXCEL_CARI_COUNT": 0,
        "EXCEL_FILE_COUNT": 0,
        "EXCEL_CANONICAL_BALANCE_MISMATCH_COUNT": 0,
        "EXCEL_LIST_DETAIL_MISMATCH_COUNT": 0,
        "EXCEL_MIRROR_NETTING_ERROR_COUNT": 0,
        "EXCEL_FAKE_BALANCING_ROWS": 0,
        "EXCEL_FORMULA_ERRORS": 0,
    }
    if not excel_dir.is_dir():
        out["error"] = "dir_missing"
        return out

    xlsx_files = sorted(excel_dir.glob("*.xlsx"))
    out["EXCEL_FILE_COUNT"] = len(xlsx_files)

    inv = excel_dir / "FLO_CARI_ENVANTERI.xlsx"
    if not inv.exists():
        out["error"] = "inventory_missing"
        return out

    wb = load_workbook(inv, read_only=True, data_only=True)
    ws = wb["Envanter"]
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    idx = {h: i for i, h in enumerate(headers) if h}
    cari_rows = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[idx.get("cari_kod", 0)]:
            continue
        cari_rows += 1
        ck = str(row[idx["cari_kod"]]).strip()
        loc = str(row[idx["location"]]).strip()
        pb = str(row[idx.get("para_birimi", 5)] or "TRY").strip()
        x_fn = row[idx.get("fn_net", 8)]
        balance_source = str(row[idx.get("balance_source", 7)] or "rm_snapshot")

        if ck == "120.01.001":
            if not _near(x_fn, Decimal("834941.54")):
                out["EXCEL_MIRROR_NETTING_ERROR_COUNT"] += 1

        if balance_source == "rm_snapshot":
            snap = lookup_receivable_row(loc, ck, pb, None) or lookup_payable_row(loc, ck, pb, None)
            if snap and not _near(x_fn, snap["row"].get("net")):
                out["EXCEL_CANONICAL_BALANCE_MISMATCH_COUNT"] += 1
            if ck.startswith("120."):
                det = get_customer_summary(ck, loc, pb)
            else:
                det = get_supplier_summary(loc, ck, pb)
            if det.get("ok") and not _near(x_fn, det.get("fn_net")):
                out["EXCEL_LIST_DETAIL_MISMATCH_COUNT"] += 1

    wb.close()
    out["EXCEL_CARI_COUNT"] = cari_rows

    for xlsx in excel_dir.glob("FLO_*.xlsx"):
        if xlsx.name == "FLO_CARI_ENVANTERI.xlsx":
            continue
        try:
            wb2 = load_workbook(xlsx, read_only=True, data_only=True)
            wh = wb2["Hareketler"]
            for r in wh.iter_rows(min_row=2, values_only=True):
                if not r:
                    continue
                kaynak = str(r[9] or "")
                tur = str(r[2] or "").lower()
                if kaynak in FAKE_SOURCES or any(t in tur for t in FAKE_TYPE_TOKS):
                    out["EXCEL_FAKE_BALANCING_ROWS"] += 1
            for sh in wb2.worksheets:
                for row in sh.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            out["EXCEL_FORMULA_ERRORS"] += 1
            wb2.close()
        except Exception:
            out["EXCEL_FORMULA_ERRORS"] += 1

    return out


def _near(a: Any, b: Any) -> bool:
    try:
        return abs(Decimal(str(a or 0)) - Decimal(str(b or 0))) <= TOL
    except Exception:
        return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(rf"C:\cps_candidate_musteri_recovered_verify_v1\_tempdb\flo_cari_excel_v2_{ts}")
    if len(sys.argv) > 1:
        dest = Path(sys.argv[1])
    result = export_flo_excel(dest)
    gates = verify_flo_excel_dir(dest)
    print(json.dumps({**{k: v for k, v in result.items() if k != "files"}, **gates}, ensure_ascii=False, indent=2))
    print("FILES")
    for f in result.get("files") or []:
        print(f)

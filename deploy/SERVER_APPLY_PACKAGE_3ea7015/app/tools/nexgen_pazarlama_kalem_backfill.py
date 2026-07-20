# -*- coding: utf-8 -*-
"""Pazarlama sipariş kalem backfill — yalnız __PZM_V1__/V2__ header'lar."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any

PZM_V1 = "__PZM_V1__"
PZM_V2 = "__PZM_V2__"
PZM_LIKE = "__PZM_V%"


def _utf8_main() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _connect(db: str, ro: bool = False) -> sqlite3.Connection:
    if ro:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _payload_v1(ref: str) -> dict | None:
    if not ref or not str(ref).startswith(PZM_V1):
        return None
    try:
        return json.loads(str(ref)[len(PZM_V1):])
    except Exception:
        return None


def _payload_v2_meta(ref: str) -> dict | None:
    if not ref or not str(ref).startswith(PZM_V2):
        return None
    try:
        return json.loads(str(ref)[len(PZM_V2):])
    except Exception:
        return None


def _boyut_to_miktar(boyut_miktar: dict) -> tuple[float, float, float]:
    ml = ms = mm = 0.0
    if not isinstance(boyut_miktar, dict):
        return ml, ms, mm
    for b, v in boyut_miktar.items():
        key = (b or "").upper()
        if key == "MEDIUM":
            key = "STANDART"
        try:
            kg = round(float(v), 3)
        except (TypeError, ValueError):
            continue
        if kg <= 0:
            continue
        if key == "LARGE":
            ml = kg
        elif key == "SMALL":
            ms = kg
        elif key == "STANDART":
            mm = kg
    return ml, ms, mm


def _try_parse_notlar(notlar: str | None) -> dict | None:
    if not notlar:
        return None
    s = str(notlar).strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception:
            return None
    return None


def _kalemler_from_v1(hdr: sqlite3.Row) -> list[dict[str, Any]] | None:
    payload = _payload_v1(hdr["talep_referansi"])
    if not payload:
        return None
    if not payload.get("formul_id") and not payload.get("urun_ailesi"):
        return None
    ml, ms, mm = _boyut_to_miktar(payload.get("boyut_miktar") or {})
    if ml <= 0 and ms <= 0 and mm <= 0:
        return None
    return [{
        "sira_no": 1,
        "urun_ailesi": (payload.get("urun_ailesi") or "TERLIK").strip().upper(),
        "formul_id": payload.get("formul_id"),
        "formul_ad": payload.get("formul_ad"),
        "renk_varyant_id": payload.get("renk_varyant_id"),
        "renk_ad": payload.get("renk_ad"),
        "rf_renk_id": payload.get("rf_renk_id"),
        "miktar_l": ml,
        "miktar_s": ms,
        "miktar_m": mm,
        "termin_tarihi": payload.get("termin_tarihi") or hdr["termin_tarihi"],
        "notlar": payload.get("notlar") or hdr["notlar"],
        "legacy_kaynak": 1,
    }]


def _kalemler_from_plans(con: sqlite3.Connection, ps_id: int, hdr: sqlite3.Row) -> list[dict[str, Any]] | None:
    plans = con.execute(
        """
        SELECT p.id AS plan_id, p.planlanan_kg, p.termin_tarihi, p.rf_renk_id,
               uv.boyut, f.id AS formul_id, f.ad AS formul_ad, f.urun_ailesi,
               rv.id AS renk_varyant_id, rf.rf_kod, rf.ad AS rf_ad
        FROM nexgen_uretim_plan p
        JOIN nexgen_uretim_varyant uv ON uv.id = p.uretim_varyant_id
        JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
        JOIN nexgen_formul f ON f.id = rv.formul_id
        LEFT JOIN nexgen_rf_renk rf ON rf.id = p.rf_renk_id
        WHERE p.planlama_siparis_id=?
        ORDER BY p.id
        """,
        (ps_id,),
    ).fetchall()
    if not plans:
        return None

    kalemler: list[dict[str, Any]] = []
    for i, p in enumerate(plans, start=1):
        boyut = (p["boyut"] or "").upper()
        kg = round(float(p["planlanan_kg"] or 0), 3)
        if kg <= 0:
            continue
        ml = ms = mm = 0.0
        if boyut == "LARGE":
            ml = kg
        elif boyut == "SMALL":
            ms = kg
        else:
            mm = kg
        aile = (p["urun_ailesi"] or "").upper()
        if aile in ("DÖKME", "DOKME"):
            aile = "DOKME"
        elif aile.startswith("TER"):
            aile = "TERLIK"
        elif not aile:
            aile = "TERLIK"
        renk_ad = p["rf_ad"] or ""
        if p["rf_kod"]:
            renk_ad = f"{p['rf_kod']} — {renk_ad}".strip(" —")
        kalemler.append({
            "sira_no": i,
            "urun_ailesi": aile,
            "formul_id": p["formul_id"],
            "formul_ad": p["formul_ad"],
            "renk_varyant_id": p["renk_varyant_id"],
            "renk_ad": renk_ad or None,
            "rf_renk_id": p["rf_renk_id"],
            "miktar_l": ml,
            "miktar_s": ms,
            "miktar_m": mm,
            "termin_tarihi": p["termin_tarihi"] or hdr["termin_tarihi"],
            "notlar": hdr["notlar"],
            "uretim_plan_id": p["plan_id"],
            "legacy_kaynak": 1,
        })
    return kalemler or None


def _kalemler_from_v2(con: sqlite3.Connection, hdr: sqlite3.Row) -> list[dict[str, Any]] | None:
    meta = _payload_v2_meta(hdr["talep_referansi"])
    if not meta:
        return None
    extra = _try_parse_notlar(hdr["notlar"])
    if extra and isinstance(extra.get("kalemler"), list):
        out = []
        for i, k in enumerate(extra["kalemler"], start=1):
            if not k.get("formul_id"):
                continue
            out.append({
                "sira_no": int(k.get("sira_no") or i),
                "urun_ailesi": (k.get("urun_ailesi") or "TERLIK").upper(),
                "formul_id": k.get("formul_id"),
                "formul_ad": k.get("formul_ad"),
                "renk_varyant_id": k.get("renk_varyant_id"),
                "renk_ad": k.get("renk_ad"),
                "rf_renk_id": k.get("rf_renk_id"),
                "miktar_l": float(k.get("miktar_l") or 0),
                "miktar_s": float(k.get("miktar_s") or 0),
                "miktar_m": float(k.get("miktar_m") or 0),
                "termin_tarihi": k.get("termin_tarihi") or hdr["termin_tarihi"],
                "notlar": k.get("notlar"),
                "legacy_kaynak": 1,
            })
        if out:
            return out
    return _kalemler_from_plans(con, int(hdr["id"]), hdr)


def analyze(con: sqlite3.Connection) -> dict[str, Any]:
    total = con.execute("SELECT COUNT(*) FROM nexgen_planlama_siparis").fetchone()[0]
    pzm_like = con.execute(
        "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE talep_referansi LIKE ?",
        (PZM_LIKE,),
    ).fetchone()[0]
    empty_ref = con.execute(
        "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE COALESCE(talep_referansi,'')=''"
    ).fetchone()[0]
    kalem_count = con.execute("SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem").fetchone()[0]

    headers = con.execute(
        """
        SELECT id, siparis_no, termin_tarihi, notlar, talep_referansi
        FROM nexgen_planlama_siparis
        WHERE talep_referansi LIKE ?
        ORDER BY id
        """,
        (PZM_LIKE,),
    ).fetchall()

    candidates = []
    unresolved = []
    for hdr in headers:
        ps_id = int(hdr["id"])
        mevcut = con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?",
            (ps_id,),
        ).fetchone()[0]
        if mevcut > 0:
            continue
        ref = str(hdr["talep_referansi"] or "")
        kalemler = None
        if ref.startswith(PZM_V1):
            kalemler = _kalemler_from_v1(hdr)
        elif ref.startswith(PZM_V2):
            kalemler = _kalemler_from_v2(con, hdr)
        if kalemler:
            candidates.append({"header_id": ps_id, "siparis_no": hdr["siparis_no"], "kalem_count": len(kalemler)})
        else:
            unresolved.append({"header_id": ps_id, "siparis_no": hdr["siparis_no"], "reason": "UNRESOLVED"})

    return {
        "total_headers": int(total),
        "pzm_like_count": int(pzm_like),
        "empty_ref_count": int(empty_ref),
        "kalem_count": int(kalem_count),
        "pzm_without_kalem": len(candidates) + len(unresolved),
        "backfill_candidates": candidates,
        "unresolved_headers": unresolved,
        "root_cause": "UI filters talep_referansi LIKE '__PZM_V%' — empty-ref headers invisible",
    }


def _insert_kalemler(con: sqlite3.Connection, ps_id: int, kalemler: list[dict[str, Any]]) -> int:
    inserted = 0
    for k in kalemler:
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis_kalem
                (planlama_siparis_id, sira_no, urun_ailesi, formul_id, formul_ad,
                 renk_varyant_id, renk_ad, rf_renk_id,
                 miktar_l, miktar_s, miktar_m,
                 termin_tarihi, notlar, uretim_plan_id, durum, legacy_kaynak)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AKTIF', ?
            WHERE NOT EXISTS (
                SELECT 1 FROM nexgen_planlama_siparis_kalem
                WHERE planlama_siparis_id=? AND sira_no=?
            )
            """,
            (
                ps_id, k["sira_no"], k["urun_ailesi"], k.get("formul_id"), k.get("formul_ad"),
                k.get("renk_varyant_id"), k.get("renk_ad"), k.get("rf_renk_id"),
                k.get("miktar_l", 0), k.get("miktar_s", 0), k.get("miktar_m", 0),
                k.get("termin_tarihi"), k.get("notlar"), k.get("uretim_plan_id"),
                k.get("legacy_kaynak", 1),
                ps_id, k["sira_no"],
            ),
        )
        if con.total_changes:
            inserted += 1
    return inserted


def apply_backfill(con: sqlite3.Connection, dry_run: bool = True) -> dict[str, Any]:
    rep = analyze(con)
    actions = []
    total_insert = 0
    for item in rep["backfill_candidates"]:
        hdr = con.execute(
            "SELECT id, siparis_no, termin_tarihi, notlar, talep_referansi FROM nexgen_planlama_siparis WHERE id=?",
            (item["header_id"],),
        ).fetchone()
        ref = str(hdr["talep_referansi"] or "")
        if ref.startswith(PZM_V1):
            kalemler = _kalemler_from_v1(hdr)
        else:
            kalemler = _kalemler_from_v2(con, hdr)
        if not kalemler:
            continue
        if dry_run:
            actions.append({"header_id": item["header_id"], "action": "WOULD_INSERT", "kalem": len(kalemler)})
            total_insert += len(kalemler)
        else:
            n = _insert_kalemler(con, int(hdr["id"]), kalemler)
            actions.append({"header_id": item["header_id"], "action": "INSERTED", "kalem": n})
            total_insert += n
    return {"dry_run": dry_run, "inserted_kalem": total_insert, "actions": actions, "check": rep}


def verify(con: sqlite3.Connection) -> dict[str, Any]:
    rep = analyze(con)
    ok = len(rep["backfill_candidates"]) == 0 or all(
        con.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?",
            (c["header_id"],),
        ).fetchone()[0] > 0
        for c in rep["backfill_candidates"]
    )
    return {"ok": ok, **rep}


def main(argv: list[str] | None = None) -> int:
    _utf8_main()
    ap = argparse.ArgumentParser(description="Pazarlama kalem backfill")
    ap.add_argument("--db", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    db = os.path.abspath(args.db)
    if args.check or (not args.dry_run and not args.apply and not args.verify):
        con = _connect(db, ro=True)
        try:
            rep = analyze(con)
        finally:
            con.close()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    if args.verify:
        con = _connect(db, ro=True)
        try:
            rep = verify(con)
        finally:
            con.close()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep["ok"] else 1

    con = _connect(db, ro=args.dry_run and not args.apply)
    try:
        if args.apply:
            con.execute("BEGIN IMMEDIATE")
        rep = apply_backfill(con, dry_run=not args.apply)
        if args.apply:
            con.commit()
    except Exception:
        if args.apply:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

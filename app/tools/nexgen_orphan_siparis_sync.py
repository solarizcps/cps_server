# -*- coding: utf-8 -*-
"""Orphan sipariş senkron audit / kontrollü apply.

Varsayılan: DRY-RUN (yazmaz).
Apply: --apply ve isteğe bağlı --siparis-id / --siparis-no

Kurallar (_PZM_DURUMLAR / _pzm_siparis_tamamlandi_sync ile uyumlu):
  - Açık plan varsa → SKIP
  - Plan yoksa → REVIEW_REQUIRED
  - Tüm planlar IPTAL → önerilen IPTAL (APPLY_SAFE)
  - En az bir BITTI, açık yok → önerilen TAMAMLANDI (APPLY_SAFE)
  - Diğer kapalı kombinasyonlar → REVIEW_REQUIRED

Canlı DB'ye kullanıcı onayı olmadan --apply çalıştırmayın.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)
CLOSED_SIPARIS = frozenset({"IPTAL", "TAMAMLANDI"})
OPEN_PLAN_EXCLUDE = ("BITTI", "IPTAL")


def _classify(mevcut_durum: str, plan_sayisi: int, bitti: int, iptal: int, acik: int):
    if mevcut_durum in CLOSED_SIPARIS:
        return "SKIP", None, "siparis_zaten_kapali"
    if plan_sayisi <= 0:
        return "REVIEW_REQUIRED", None, "plan_yok_otomatik_kapanmaz"
    if acik > 0:
        return "SKIP", None, "acik_plan_var"
    if bitti <= 0 and iptal == plan_sayisi:
        return "APPLY_SAFE", "IPTAL", "tum_planlar_iptal"
    if bitti > 0 and acik == 0:
        return "APPLY_SAFE", "TAMAMLANDI", "en_az_bir_bitti_acik_yok"
    return "REVIEW_REQUIRED", None, "belirsiz_plan_kombinasyonu"


def audit(con: sqlite3.Connection, siparis_ids=None, siparis_nos=None):
    sql = """
    SELECT s.id, s.siparis_no, s.durum AS mevcut_durum,
           COALESCE((
             SELECT COUNT(*) FROM nexgen_uretim_plan p
             WHERE p.planlama_siparis_id=s.id
           ), 0) AS plan_sayisi,
           COALESCE((
             SELECT SUM(CASE WHEN p.durum='BITTI' THEN 1 ELSE 0 END)
             FROM nexgen_uretim_plan p WHERE p.planlama_siparis_id=s.id
           ), 0) AS bitti_plan,
           COALESCE((
             SELECT SUM(CASE WHEN p.durum='IPTAL' THEN 1 ELSE 0 END)
             FROM nexgen_uretim_plan p WHERE p.planlama_siparis_id=s.id
           ), 0) AS iptal_plan,
           COALESCE((
             SELECT SUM(CASE WHEN p.durum NOT IN ('BITTI','IPTAL') THEN 1 ELSE 0 END)
             FROM nexgen_uretim_plan p WHERE p.planlama_siparis_id=s.id
           ), 0) AS acik_plan
    FROM nexgen_planlama_siparis s
    WHERE s.durum NOT IN ('TAMAMLANDI','IPTAL')
      AND EXISTS (
        SELECT 1 FROM nexgen_uretim_plan p WHERE p.planlama_siparis_id=s.id
      )
      AND NOT EXISTS (
        SELECT 1 FROM nexgen_uretim_plan p
        WHERE p.planlama_siparis_id=s.id AND p.durum NOT IN ('BITTI','IPTAL')
      )
    """
    rows = [dict(r) for r in con.execute(sql).fetchall()]
    out = []
    for r in rows:
        if siparis_ids and int(r["id"]) not in siparis_ids:
            continue
        if siparis_nos and str(r["siparis_no"]) not in siparis_nos:
            continue
        karar, onerilen, neden = _classify(
            r["mevcut_durum"],
            int(r["plan_sayisi"]),
            int(r["bitti_plan"]),
            int(r["iptal_plan"]),
            int(r["acik_plan"]),
        )
        r["onerilen_durum"] = onerilen
        r["karar"] = karar
        r["neden"] = neden
        r["degisecek_kolonlar"] = "durum,guncelleme_tarihi" if onerilen else None
        out.append(r)
    return out


def apply_safe(con: sqlite3.Connection, rows, siparis_ids=None):
    """Yalnız APPLY_SAFE satırları günceller. Transaction içinde."""
    applied = []
    for r in rows:
        if r["karar"] != "APPLY_SAFE" or not r["onerilen_durum"]:
            continue
        if siparis_ids is not None and int(r["id"]) not in siparis_ids:
            continue
        cur = con.execute(
            """
            UPDATE nexgen_planlama_siparis
               SET durum=?,
                   guncelleme_tarihi=datetime('now','localtime')
             WHERE id=? AND durum=? AND durum NOT IN ('IPTAL','TAMAMLANDI')
            """,
            (r["onerilen_durum"], r["id"], r["mevcut_durum"]),
        )
        if cur.rowcount:
            applied.append({
                "id": r["id"],
                "siparis_no": r["siparis_no"],
                "eski": r["mevcut_durum"],
                "yeni": r["onerilen_durum"],
            })
    return applied


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Orphan sipariş sync (default dry-run)")
    p.add_argument("--db", default=DEFAULT_DB, help="DB yolu")
    p.add_argument("--apply", action="store_true", help="APPLY_SAFE kayıtları yaz (default: dry-run)")
    p.add_argument("--siparis-id", type=int, action="append", default=None,
                   help="Yalnız bu id (çoklu verilebilir)")
    p.add_argument("--siparis-no", action="append", default=None,
                   help="Yalnız bu siparis_no (çoklu)")
    p.add_argument("--ro", action="store_true", help="Salt okunur URI (dry-run için önerilir)")
    args = p.parse_args(argv)

    db = os.path.abspath(args.db)
    if args.apply and args.ro:
        print("HATA: --apply ile --ro birlikte kullanılamaz")
        return 2
    if args.apply and not args.siparis_id and not args.siparis_no:
        # Güvenlik: apply için en az bir filtre zorunlu (canlı toplu apply engeli)
        print("HATA: --apply için --siparis-id veya --siparis-no zorunlu")
        return 2

    uri = f"file:{db}?mode=ro" if (args.ro or not args.apply) else None
    if uri and not args.apply:
        con = sqlite3.connect(uri, uri=True)
    else:
        con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    ids = set(args.siparis_id) if args.siparis_id else None
    nos = set(args.siparis_no) if args.siparis_no else None
    rows = audit(con, siparis_ids=ids, siparis_nos=nos)

    print(f"MODE={'APPLY' if args.apply else 'DRY_RUN'} db={db}")
    print(f"ORPHAN_CANDIDATE_COUNT {len(rows)}")
    print(
        "siparis_id\tsiparis_no\tmevcut_durum\tplan_sayisi\t"
        "bitti_plan\tiptal_plan\tacik_plan\tonerilen_durum\tkarar\tneden"
    )
    for r in rows:
        print(
            f"{r['id']}\t{r['siparis_no']}\t{r['mevcut_durum']}\t{r['plan_sayisi']}\t"
            f"{r['bitti_plan']}\t{r['iptal_plan']}\t{r['acik_plan']}\t"
            f"{r['onerilen_durum']}\t{r['karar']}\t{r['neden']}"
        )

    if not args.apply:
        print("DRY_RUN_ONLY — no writes")
        con.close()
        return 0

    apply_ids = ids
    if nos and not ids:
        apply_ids = {int(r["id"]) for r in rows if r["siparis_no"] in nos}
    try:
        applied = apply_safe(con, rows, siparis_ids=apply_ids)
        con.commit()
    except Exception as e:
        con.rollback()
        print(f"APPLY_FAIL {e}")
        con.close()
        return 1
    print(f"APPLIED_COUNT {len(applied)}")
    for a in applied:
        print(f"APPLIED id={a['id']} {a['siparis_no']}: {a['eski']} -> {a['yeni']}")
    # idempotent ikinci geçiş
    rows2 = audit(con, siparis_ids=apply_ids, siparis_nos=nos)
    applied2 = apply_safe(con, rows2, siparis_ids=apply_ids)
    con.commit()
    print(f"SECOND_PASS_APPLIED {len(applied2)} (expect 0)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

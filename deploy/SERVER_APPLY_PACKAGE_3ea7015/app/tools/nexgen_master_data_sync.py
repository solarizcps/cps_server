# -*- coding: utf-8 -*-
"""9 çekirdek NexGen master data export / check / apply / verify."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORE_CODES = (
    "1BA-FL01", "1BA-FS01", "1BA-FL02", "1BA-FS02", "1BA-FL03", "1BA-FS03",
    "2BA-FL01", "2BA-FS01", "3BA-FM01",
)

ENTITY_ORDER = (
    "nexgen_stok_kart",
    "nexgen_formul",
    "nexgen_renk_varyant",
    "nexgen_uretim_varyant",
    "nexgen_recete_kalem",
    "nexgen_rf_formul_uygunluk",
)

FORBIDDEN_ENTITY_PREFIXES = (
    "nexgen_planlama_siparis",
    "nexgen_uretim_plan",
    "nexgen_uretim_batch",
    "nexgen_stok_hareket",
    "nexgen_arge",
    "sistem_kullanici",
)

FORMUL_UPDATE_COLS = (
    "ad", "aciklama", "durum", "onay_durumu", "notlar", "aktif", "urun_ailesi",
)
STOK_UPDATE_COLS = (
    "ad", "kategori", "birim", "minimum_stok", "kritik_stok", "aciklama",
    "aktif", "renk", "alt_kategori", "kalite_sinifi", "shore_degeri", "notlar",
)


def _utf8_main() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _connect(db: str, ro: bool = False) -> sqlite3.Connection:
    if ro:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(db, timeout=120)
    con.row_factory = sqlite3.Row
    return con


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _checksum(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _core_formul_ids(con: sqlite3.Connection) -> list[int]:
    ph = ",".join("?" * len(CORE_CODES))
    rows = con.execute(
        f"SELECT id FROM nexgen_formul WHERE kod IN ({ph}) ORDER BY kod",
        CORE_CODES,
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _collect_dependency_ids(con: sqlite3.Connection) -> dict[str, set[int]]:
    fids = _core_formul_ids(con)
    if len(fids) != len(CORE_CODES):
        missing = set(CORE_CODES) - {
            r["kod"]
            for r in con.execute(
                f"SELECT kod FROM nexgen_formul WHERE kod IN ({','.join('?' * len(CORE_CODES))})",
                CORE_CODES,
            ).fetchall()
        }
        raise RuntimeError(f"Kaynak DB eksik çekirdek formül: {sorted(missing)}")

    rv_ids: set[int] = set()
    uv_ids: set[int] = set()
    rk_ids: set[int] = set()
    sk_ids: set[int] = set()
    uy_ids: set[int] = set()

    ph = ",".join("?" * len(fids))
    for r in con.execute(
        f"SELECT id FROM nexgen_renk_varyant WHERE formul_id IN ({ph})",
        fids,
    ):
        rv_ids.add(int(r["id"]))

    if rv_ids:
        ph_rv = ",".join("?" * len(rv_ids))
        for r in con.execute(
            f"SELECT id FROM nexgen_uretim_varyant WHERE renk_varyant_id IN ({ph_rv})",
            list(rv_ids),
        ):
            uv_ids.add(int(r["id"]))

    if uv_ids:
        ph_uv = ",".join("?" * len(uv_ids))
        for r in con.execute(
            f"""
            SELECT id, stok_kart_id FROM nexgen_recete_kalem
            WHERE uretim_varyant_id IN ({ph_uv}) AND aktif=1
            """,
            list(uv_ids),
        ):
            rk_ids.add(int(r["id"]))
            if r["stok_kart_id"]:
                sk_ids.add(int(r["stok_kart_id"]))

    if _table_exists(con, "nexgen_rf_formul_uygunluk"):
        for r in con.execute(
            f"SELECT id FROM nexgen_rf_formul_uygunluk WHERE formul_id IN ({ph}) AND aktif=1",
            fids,
        ):
            uy_ids.add(int(r["id"]))

    return {
        "nexgen_formul": set(fids),
        "nexgen_renk_varyant": rv_ids,
        "nexgen_uretim_varyant": uv_ids,
        "nexgen_recete_kalem": rk_ids,
        "nexgen_stok_kart": sk_ids,
        "nexgen_rf_formul_uygunluk": uy_ids,
    }


def _formul_kod(con: sqlite3.Connection, fid: int) -> str | None:
    r = con.execute("SELECT kod FROM nexgen_formul WHERE id=?", (fid,)).fetchone()
    return r["kod"] if r else None


def _rv_natural_key(con: sqlite3.Connection, rv_id: int) -> str:
    row = con.execute(
        """
        SELECT rv.kod, rv.ad, f.kod AS formul_kod
        FROM nexgen_renk_varyant rv
        JOIN nexgen_formul f ON f.id = rv.formul_id
        WHERE rv.id=?
        """,
        (rv_id,),
    ).fetchone()
    if not row:
        return f"rv:{rv_id}"
    part = (row["kod"] or row["ad"] or str(rv_id)).strip()
    return f"{row['formul_kod']}|{part}"


def _uv_natural_key(con: sqlite3.Connection, uv_id: int) -> str:
    row = con.execute(
        """
        SELECT uv.boyut, rv.kod AS rv_kod, rv.ad AS rv_ad, f.kod AS formul_kod
        FROM nexgen_uretim_varyant uv
        JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
        JOIN nexgen_formul f ON f.id = rv.formul_id
        WHERE uv.id=?
        """,
        (uv_id,),
    ).fetchone()
    if not row:
        return f"uv:{uv_id}"
    rv_part = (row["rv_kod"] or row["rv_ad"] or "").strip()
    return f"{row['formul_kod']}|{rv_part}|{(row['boyut'] or '').upper()}"


def _rk_natural_key(con: sqlite3.Connection, rk_id: int) -> str:
    row = con.execute(
        """
        SELECT rk.sira, rk.miktar_kg, sk.kod AS stok_kod, uv.id AS uv_id
        FROM nexgen_recete_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        JOIN nexgen_uretim_varyant uv ON uv.id = rk.uretim_varyant_id
        WHERE rk.id=?
        """,
        (rk_id,),
    ).fetchone()
    if not row:
        return f"rk:{rk_id}"
    uv_key = _uv_natural_key(con, int(row["uv_id"]))
    return f"{uv_key}|{row['stok_kod']}|{row['sira']}|{round(float(row['miktar_kg'] or 0), 6)}"


def _uy_natural_key(con: sqlite3.Connection, uy_id: int) -> str:
    row = con.execute(
        """
        SELECT rf.rf_kod, f.kod AS formul_kod
        FROM nexgen_rf_formul_uygunluk u
        JOIN nexgen_rf_renk rf ON rf.id = u.rf_renk_id
        JOIN nexgen_formul f ON f.id = u.formul_id
        WHERE u.id=?
        """,
        (uy_id,),
    ).fetchone()
    if not row:
        return f"uy:{uy_id}"
    return f"{row['rf_kod']}|{row['formul_kod']}"


def _entity_dependencies(entity_type: str, payload: dict[str, Any]) -> list[str]:
    deps: list[str] = []
    if entity_type == "nexgen_renk_varyant":
        deps.append(f"nexgen_formul:{payload.get('formul_kod')}")
    elif entity_type == "nexgen_uretim_varyant":
        deps.append(f"nexgen_renk_varyant:{payload.get('renk_varyant_key')}")
    elif entity_type == "nexgen_recete_kalem":
        deps.append(f"nexgen_uretim_varyant:{payload.get('uretim_varyant_key')}")
        deps.append(f"nexgen_stok_kart:{payload.get('stok_kod')}")
    elif entity_type == "nexgen_rf_formul_uygunluk":
        deps.append(f"nexgen_formul:{payload.get('formul_kod')}")
        deps.append(f"nexgen_rf_renk:{payload.get('rf_kod')}")
    return [d for d in deps if d.split(":", 1)[-1]]


def export_package(source_db: str) -> dict[str, Any]:
    con = _connect(source_db, ro=True)
    try:
        ids = _collect_dependency_ids(con)
        records: list[dict[str, Any]] = []

        for sk_id in sorted(ids["nexgen_stok_kart"]):
            row = _row_dict(con.execute("SELECT * FROM nexgen_stok_kart WHERE id=?", (sk_id,)).fetchone())
            if not row:
                continue
            payload = {k: row[k] for k in row if k != "id"}
            payload["stok_kod"] = row["kod"]
            rec = {
                "entity_type": "nexgen_stok_kart",
                "source_id": sk_id,
                "natural_key": row["kod"],
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": [],
            }
            records.append(rec)

        for fid in sorted(ids["nexgen_formul"], key=lambda x: _formul_kod(con, x) or ""):
            row = _row_dict(con.execute("SELECT * FROM nexgen_formul WHERE id=?", (fid,)).fetchone())
            if not row:
                continue
            payload = {k: row[k] for k in row if k != "id"}
            payload["formul_kod"] = row["kod"]
            rec = {
                "entity_type": "nexgen_formul",
                "source_id": fid,
                "natural_key": row["kod"],
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": [],
            }
            records.append(rec)

        for rv_id in sorted(ids["nexgen_renk_varyant"]):
            row = _row_dict(con.execute("SELECT * FROM nexgen_renk_varyant WHERE id=?", (rv_id,)).fetchone())
            if not row:
                continue
            fk = _formul_kod(con, int(row["formul_id"]))
            nk = _rv_natural_key(con, rv_id)
            payload = {k: row[k] for k in row if k != "id"}
            payload["formul_kod"] = fk
            payload["renk_varyant_key"] = nk
            rec = {
                "entity_type": "nexgen_renk_varyant",
                "source_id": rv_id,
                "natural_key": nk,
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": _entity_dependencies("nexgen_renk_varyant", payload),
            }
            records.append(rec)

        for uv_id in sorted(ids["nexgen_uretim_varyant"]):
            row = _row_dict(con.execute("SELECT * FROM nexgen_uretim_varyant WHERE id=?", (uv_id,)).fetchone())
            if not row:
                continue
            nk = _uv_natural_key(con, uv_id)
            rv_nk = _rv_natural_key(con, int(row["renk_varyant_id"]))
            payload = {k: row[k] for k in row if k != "id"}
            payload["renk_varyant_key"] = rv_nk
            payload["uretim_varyant_key"] = nk
            rec = {
                "entity_type": "nexgen_uretim_varyant",
                "source_id": uv_id,
                "natural_key": nk,
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": _entity_dependencies("nexgen_uretim_varyant", payload),
            }
            records.append(rec)

        for rk_id in sorted(ids["nexgen_recete_kalem"]):
            row = _row_dict(con.execute("SELECT * FROM nexgen_recete_kalem WHERE id=?", (rk_id,)).fetchone())
            if not row:
                continue
            sk = con.execute("SELECT kod FROM nexgen_stok_kart WHERE id=?", (row["stok_kart_id"],)).fetchone()
            nk = _rk_natural_key(con, rk_id)
            payload = {k: row[k] for k in row if k != "id"}
            payload["stok_kod"] = sk["kod"] if sk else None
            payload["uretim_varyant_key"] = _uv_natural_key(con, int(row["uretim_varyant_id"]))
            rec = {
                "entity_type": "nexgen_recete_kalem",
                "source_id": rk_id,
                "natural_key": nk,
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": _entity_dependencies("nexgen_recete_kalem", payload),
            }
            records.append(rec)

        for uy_id in sorted(ids["nexgen_rf_formul_uygunluk"]):
            row = _row_dict(
                con.execute("SELECT * FROM nexgen_rf_formul_uygunluk WHERE id=?", (uy_id,)).fetchone()
            )
            if not row:
                continue
            rf = con.execute("SELECT rf_kod FROM nexgen_rf_renk WHERE id=?", (row["rf_renk_id"],)).fetchone()
            fk = _formul_kod(con, int(row["formul_id"]))
            nk = _uy_natural_key(con, uy_id)
            payload = {k: row[k] for k in row if k != "id"}
            payload["rf_kod"] = rf["rf_kod"] if rf else None
            payload["formul_kod"] = fk
            rec = {
                "entity_type": "nexgen_rf_formul_uygunluk",
                "source_id": uy_id,
                "natural_key": nk,
                "payload": payload,
                "checksum": _checksum(payload),
                "dependencies": _entity_dependencies("nexgen_rf_formul_uygunluk", payload),
            }
            records.append(rec)

        counts: dict[str, int] = {}
        for rec in records:
            counts[rec["entity_type"]] = counts.get(rec["entity_type"], 0) + 1

        return {
            "package_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_db": os.path.abspath(source_db),
            "core_codes": list(CORE_CODES),
            "entity_counts": counts,
            "record_count": len(records),
            "records": records,
        }
    finally:
        con.close()


def _load_package(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for rec in data.get("records", []):
        et = rec.get("entity_type", "")
        if any(et.startswith(p) for p in FORBIDDEN_ENTITY_PREFIXES if p != "nexgen_planlama_siparis"):
            if et not in ENTITY_ORDER:
                raise ValueError(f"Paket yasak entity içeriyor: {et}")
    return data


def _resolve_target_id(
    con: sqlite3.Connection,
    entity_type: str,
    natural_key: str,
    payload: dict[str, Any],
    id_maps: dict[str, dict[Any, int]],
) -> int | None:
    if entity_type == "nexgen_stok_kart":
        r = con.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (natural_key,)).fetchone()
        return int(r["id"]) if r else None
    if entity_type == "nexgen_formul":
        r = con.execute("SELECT id FROM nexgen_formul WHERE kod=?", (natural_key,)).fetchone()
        return int(r["id"]) if r else None
    if entity_type == "nexgen_renk_varyant":
        fk = payload.get("formul_kod")
        fid = id_maps["nexgen_formul"].get(fk)
        if not fid:
            r = con.execute("SELECT id FROM nexgen_formul WHERE kod=?", (fk,)).fetchone()
            fid = int(r["id"]) if r else None
        if not fid:
            return None
        part = natural_key.split("|", 1)[-1]
        r = con.execute(
            """
            SELECT id FROM nexgen_renk_varyant
            WHERE formul_id=? AND (kod=? OR ad=?)
            LIMIT 1
            """,
            (fid, part, part),
        ).fetchone()
        return int(r["id"]) if r else None
    if entity_type == "nexgen_uretim_varyant":
        rv_key = payload.get("renk_varyant_key")
        boyut = (payload.get("boyut") or "").upper()
        rv_id = _resolve_target_id(con, "nexgen_renk_varyant", rv_key, {"formul_kod": rv_key.split("|")[0]}, id_maps)
        if not rv_id:
            return None
        r = con.execute(
            "SELECT id FROM nexgen_uretim_varyant WHERE renk_varyant_id=? AND UPPER(boyut)=?",
            (rv_id, boyut),
        ).fetchone()
        return int(r["id"]) if r else None
    if entity_type == "nexgen_recete_kalem":
        uv_key = payload.get("uretim_varyant_key")
        stok_kod = payload.get("stok_kod")
        uv_id = _resolve_target_id(
            con, "nexgen_uretim_varyant", uv_key,
            {"renk_varyant_key": "|".join(uv_key.split("|")[:2]), "boyut": uv_key.split("|")[-1]},
            id_maps,
        )
        sk = con.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (stok_kod,)).fetchone()
        if not uv_id or not sk:
            return None
        r = con.execute(
            """
            SELECT id FROM nexgen_recete_kalem
            WHERE uretim_varyant_id=? AND stok_kart_id=? AND sira=? AND aktif=1
            LIMIT 1
            """,
            (uv_id, sk["id"], payload.get("sira")),
        ).fetchone()
        return int(r["id"]) if r else None
    if entity_type == "nexgen_rf_formul_uygunluk":
        rf_kod = payload.get("rf_kod")
        fk = payload.get("formul_kod")
        rf = con.execute("SELECT id FROM nexgen_rf_renk WHERE rf_kod=?", (rf_kod,)).fetchone()
        fid = id_maps["nexgen_formul"].get(fk) or con.execute(
            "SELECT id FROM nexgen_formul WHERE kod=?", (fk,)
        ).fetchone()
        if not rf or not fid:
            return None
        fid_val = fid["id"] if hasattr(fid, "keys") else fid
        r = con.execute(
            """
            SELECT id FROM nexgen_rf_formul_uygunluk
            WHERE rf_renk_id=? AND formul_id=? AND aktif=1
            LIMIT 1
            """,
            (rf["id"], fid_val),
        ).fetchone()
        return int(r["id"]) if r else None
    return None


def _payload_checksum_match(con: sqlite3.Connection, entity_type: str, target_id: int, checksum: str) -> bool:
    # Basit karşılaştırma: hedef satırın yeniden checksum'ı paket ile aynı mı
    table = entity_type
    row = _row_dict(con.execute(f"SELECT * FROM {table} WHERE id=?", (target_id,)).fetchone())
    if not row:
        return False
    payload = {k: row[k] for k in row if k != "id"}
    if entity_type == "nexgen_stok_kart":
        payload["stok_kod"] = row.get("kod")
    elif entity_type == "nexgen_formul":
        payload["formul_kod"] = row.get("kod")
    return _checksum(payload) == checksum


def _plan_apply(package: dict[str, Any], target_db: str, write: bool) -> dict[str, Any]:
    con = _connect(target_db, ro=not write)
    summary = {"INSERT": 0, "UPDATE": 0, "SKIP": 0, "CONFLICT": 0, "ERROR": 0}
    actions: list[dict[str, Any]] = []
    id_maps: dict[str, dict[Any, int]] = {t: {} for t in ENTITY_ORDER}

    try:
        if write:
            con.execute("BEGIN IMMEDIATE")

        for rec in package.get("records", []):
            entity_type = rec["entity_type"]
            natural_key = rec["natural_key"]
            payload = rec["payload"]
            source_id = rec["source_id"]
            checksum = rec["checksum"]

            try:
                target_id = _resolve_target_id(con, entity_type, natural_key, payload, id_maps)

                if target_id is None:
                    if not write:
                        summary["INSERT"] += 1
                        actions.append({
                            "entity_type": entity_type,
                            "natural_key": natural_key,
                            "action": "INSERT",
                        })
                        continue

                    cols: list[str] = []
                    vals: list[Any] = []
                    if entity_type == "nexgen_stok_kart":
                        row_payload = {k: payload[k] for k in payload if k != "stok_kod"}
                        cols = list(row_payload.keys())
                        vals = [row_payload[c] for c in cols]
                    elif entity_type == "nexgen_formul":
                        row_payload = {k: payload[k] for k in payload if k != "formul_kod"}
                        cols = list(row_payload.keys())
                        vals = [row_payload[c] for c in cols]
                    elif entity_type == "nexgen_renk_varyant":
                        fk = payload["formul_kod"]
                        fid = id_maps["nexgen_formul"].get(fk) or con.execute(
                            "SELECT id FROM nexgen_formul WHERE kod=?", (fk,)
                        ).fetchone()["id"]
                        cols = ["formul_id", "kod", "ad", "renk", "notlar", "aktif", "olusturma_tarihi"]
                        vals = [
                            fid, payload.get("kod"), payload.get("ad"), payload.get("renk"),
                            payload.get("notlar"), payload.get("aktif", 1), payload.get("olusturma_tarihi"),
                        ]
                    elif entity_type == "nexgen_uretim_varyant":
                        rv_key = payload["renk_varyant_key"]
                        rv_id = _resolve_target_id(
                            con, "nexgen_renk_varyant", rv_key,
                            {"formul_kod": rv_key.split("|")[0]}, id_maps,
                        )
                        cols = [
                            "renk_varyant_id", "boyut", "ad", "onay_durumu", "onaylayan_id",
                            "onay_tarihi", "onay_notu", "kaynak_varyant_id", "notlar", "aktif",
                            "olusturma_tarihi", "recete_durum", "formul_batch_kg", "rev_no",
                        ]
                        vals = [rv_id] + [payload.get(c) for c in cols[1:]]
                    elif entity_type == "nexgen_recete_kalem":
                        uv_id = _resolve_target_id(
                            con, "nexgen_uretim_varyant", payload["uretim_varyant_key"],
                            {
                                "renk_varyant_key": "|".join(payload["uretim_varyant_key"].split("|")[:2]),
                                "boyut": payload["uretim_varyant_key"].split("|")[-1],
                            },
                            id_maps,
                        )
                        sk = con.execute(
                            "SELECT id FROM nexgen_stok_kart WHERE kod=?", (payload["stok_kod"],)
                        ).fetchone()
                        cols = [
                            "uretim_varyant_id", "stok_kart_id", "sira", "miktar_kg",
                            "aciklama", "aktif", "olusturma_tarihi",
                        ]
                        vals = [
                            uv_id, sk["id"], payload.get("sira"), payload.get("miktar_kg"),
                            payload.get("aciklama"), payload.get("aktif", 1), payload.get("olusturma_tarihi"),
                        ]
                    elif entity_type == "nexgen_rf_formul_uygunluk":
                        rf = con.execute(
                            "SELECT id FROM nexgen_rf_renk WHERE rf_kod=?", (payload["rf_kod"],)
                        ).fetchone()
                        fid = id_maps["nexgen_formul"].get(payload["formul_kod"])
                        cols = [
                            "rf_renk_id", "formul_id", "kaynak_arge_test_id", "durum",
                            "ilk_talep_cari_id", "shore_hedef", "shore_sonuc", "renk_sonucu",
                            "numune_sonucu", "aciklama", "olusturma_tarihi", "onay_tarihi",
                            "aktif", "uretim_kodu", "ana_formul_kodu", "renk_kodu",
                        ]
                        vals = [rf["id"], fid] + [payload.get(c) for c in cols[2:]]
                    else:
                        summary["ERROR"] += 1
                        continue

                    sql = f"INSERT INTO {entity_type} ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})"
                    cur = con.execute(sql, vals)
                    target_id = int(cur.lastrowid)
                    summary["INSERT"] += 1
                    actions.append({
                        "entity_type": entity_type,
                        "natural_key": natural_key,
                        "action": "INSERT",
                        "target_id": target_id,
                    })
                else:
                    if _payload_checksum_match(con, entity_type, target_id, checksum):
                        summary["SKIP"] += 1
                        actions.append({
                            "entity_type": entity_type,
                            "natural_key": natural_key,
                            "action": "SKIP",
                            "target_id": target_id,
                        })
                    else:
                        upd_cols = []
                        if entity_type == "nexgen_formul":
                            upd_cols = FORMUL_UPDATE_COLS
                        elif entity_type == "nexgen_stok_kart":
                            upd_cols = STOK_UPDATE_COLS
                        elif entity_type in (
                            "nexgen_renk_varyant", "nexgen_uretim_varyant",
                            "nexgen_recete_kalem", "nexgen_rf_formul_uygunluk",
                        ):
                            upd_cols = [k for k in payload if k not in (
                                "formul_kod", "stok_kod", "renk_varyant_key",
                                "uretim_varyant_key", "rf_kod",
                            ) and not k.endswith("_id") or k in ("aktif", "recete_durum", "miktar_kg", "sira")]

                        if write and upd_cols:
                            sets = ", ".join(f"{c}=?" for c in upd_cols if c in payload)
                            args = [payload[c] for c in upd_cols if c in payload]
                            if sets:
                                con.execute(
                                    f"UPDATE {entity_type} SET {sets} WHERE id=?",
                                    (*args, target_id),
                                )
                                summary["UPDATE"] += 1
                                actions.append({
                                    "entity_type": entity_type,
                                    "natural_key": natural_key,
                                    "action": "UPDATE",
                                    "target_id": target_id,
                                })
                            else:
                                summary["CONFLICT"] += 1
                                actions.append({
                                    "entity_type": entity_type,
                                    "natural_key": natural_key,
                                    "action": "CONFLICT",
                                    "target_id": target_id,
                                })
                        elif not write:
                            summary["UPDATE"] += 1
                            actions.append({
                                "entity_type": entity_type,
                                "natural_key": natural_key,
                                "action": "UPDATE",
                                "target_id": target_id,
                            })
                        else:
                            summary["CONFLICT"] += 1
                            actions.append({
                                "entity_type": entity_type,
                                "natural_key": natural_key,
                                "action": "CONFLICT",
                                "target_id": target_id,
                            })

                if entity_type == "nexgen_formul":
                    id_maps["nexgen_formul"][natural_key] = target_id
                    id_maps["nexgen_formul"][source_id] = target_id
                elif entity_type == "nexgen_stok_kart":
                    id_maps["nexgen_stok_kart"][natural_key] = target_id
                    id_maps["nexgen_stok_kart"][source_id] = target_id
                elif entity_type == "nexgen_renk_varyant":
                    id_maps["nexgen_renk_varyant"][natural_key] = target_id
                elif entity_type == "nexgen_uretim_varyant":
                    id_maps["nexgen_uretim_varyant"][natural_key] = target_id

            except Exception as exc:
                summary["ERROR"] += 1
                actions.append({
                    "entity_type": entity_type,
                    "natural_key": natural_key,
                    "action": "ERROR",
                    "error": str(exc),
                })
                if write:
                    raise

        if write:
            if summary["CONFLICT"] > 0 or summary["ERROR"] > 0:
                con.execute("ROLLBACK")
                summary["rolled_back"] = True
            else:
                con.commit()
                summary["committed"] = True
    except Exception:
        if write:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
        raise
    finally:
        con.close()

    return {"summary": summary, "actions": actions, "id_maps": {k: len(v) for k, v in id_maps.items()}}


def verify_target(target_db: str) -> dict[str, Any]:
    con = _connect(target_db, ro=True)
    try:
        missing = []
        empty_recete = []
        for kod in CORE_CODES:
            f = con.execute(
                "SELECT id, aktif FROM nexgen_formul WHERE kod=? AND aktif=1",
                (kod,),
            ).fetchone()
            if not f:
                missing.append(kod)
                continue
            rk = con.execute(
                """
                SELECT COUNT(*) c FROM nexgen_recete_kalem rk
                JOIN nexgen_uretim_varyant uv ON uv.id = rk.uretim_varyant_id
                JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
                WHERE rv.formul_id=? AND rk.aktif=1
                """,
                (f["id"],),
            ).fetchone()["c"]
            if rk <= 0:
                empty_recete.append(kod)

        ok = len(missing) == 0 and len(empty_recete) == 0
        return {
            "ok": ok,
            "missing_codes": missing,
            "empty_recete_codes": empty_recete,
            "aktif_core_count": len(CORE_CODES) - len(missing),
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    _utf8_main()
    ap = argparse.ArgumentParser(description="NexGen çekirdek master data sync")
    ap.add_argument("--source-db", help="Kaynak DB (export)")
    ap.add_argument("--export-package", help="Export JSON yolu")
    ap.add_argument("--target-db", help="Hedef DB")
    ap.add_argument("--package", help="Paket JSON yolu")
    ap.add_argument("--check", action="store_true", help="Paket + hedef ön kontrol")
    ap.add_argument("--dry-run", action="store_true", help="Yazmadan plan")
    ap.add_argument("--apply", action="store_true", help="Uygula (transaction)")
    ap.add_argument("--verify", action="store_true", help="9 çekirdek verify")
    args = ap.parse_args(argv)

    if args.export_package:
        if not args.source_db:
            print("HATA: --source-db gerekli", file=sys.stderr)
            return 2
        pkg = export_package(os.path.abspath(args.source_db))
        out = Path(args.export_package)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK export {pkg['record_count']} records -> {out}")
        print("entity_counts", pkg["entity_counts"])
        return 0

    if args.verify:
        if not args.target_db:
            print("HATA: --target-db gerekli", file=sys.stderr)
            return 2
        res = verify_target(os.path.abspath(args.target_db))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    if not args.target_db or not args.package:
        print("HATA: --target-db ve --package gerekli", file=sys.stderr)
        return 2

    pkg = _load_package(os.path.abspath(args.package))
    target = os.path.abspath(args.target_db)

    if args.check:
        res = verify_target(target)
        plan = _plan_apply(pkg, target, write=False)
        print(json.dumps({"verify": res, "dry_summary": plan["summary"]}, ensure_ascii=False, indent=2))
        return 0 if res["ok"] or plan["summary"]["INSERT"] > 0 else 1

    if args.dry_run:
        plan = _plan_apply(pkg, target, write=False)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["summary"]["ERROR"] == 0 else 1

    if args.apply:
        plan = _plan_apply(pkg, target, write=True)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if plan["summary"].get("rolled_back"):
            return 1
        v = verify_target(target)
        return 0 if v["ok"] else 1

    print("HATA: --check, --dry-run, --apply veya --verify seçin", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""NexGen server DB salt-okuma profil export — şifre/operasyon içeriği yok."""
from __future__ import annotations

import argparse
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

TABLE_MAP = {
    "formul": "nexgen_formul",
    "recete_kalem": "nexgen_recete_kalem",
    "rf_renk": "nexgen_rf_renk",
    "rf_kalem": "nexgen_rf_kalem",
    "planlama_siparis": "nexgen_planlama_siparis",
    "planlama_siparis_kalem": "nexgen_planlama_siparis_kalem",
    "uretim_plan": "nexgen_uretim_plan",
    "batch": "nexgen_uretim_batch",
    "stok_hareket": "nexgen_stok_hareket",
}

USER_LOOKUP = (
    ("Ali", "ali"),
    ("Vedat", "vedat"),
    ("Ferhat", "ferhat"),
)

NEXGEN_PERM_CODES = (
    "nexgen.tablet.view",
    "nexgen.tablet.uretim",
    "nexgen.view",
    "nexgen.recete.view",
    "nexgen.recete.create",
)


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _schema_migration_max(con: sqlite3.Connection) -> int | None:
    if not _table_exists(con, "schema_migrations"):
        return None
    row = con.execute(
        "SELECT MAX(CAST(version AS INTEGER)) FROM schema_migrations"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _integrity_check(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        msg = con.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": msg == "ok", "detail": str(msg)}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _table_counts(con: sqlite3.Connection) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for key, table in TABLE_MAP.items():
        if _table_exists(con, table):
            out[key] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        else:
            out[key] = None
    return out


def _core_formul_status(con: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kod in CORE_CODES:
        row = con.execute(
            "SELECT id, kod, ad, aktif, durum, urun_ailesi FROM nexgen_formul WHERE kod=?",
            (kod,),
        ).fetchone()
        if not row:
            out[kod] = {"present": False, "aktif": False}
            continue
        fid = row["id"]
        rk = con.execute(
            """
            SELECT COUNT(*) c FROM nexgen_recete_kalem rk
            JOIN nexgen_uretim_varyant uv ON uv.id = rk.uretim_varyant_id
            JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
            WHERE rv.formul_id=? AND rk.aktif=1
            """,
            (fid,),
        ).fetchone()["c"]
        out[kod] = {
            "present": True,
            "aktif": bool(row["aktif"]),
            "id": fid,
            "ad": row["ad"],
            "durum": row["durum"],
            "urun_ailesi": row["urun_ailesi"],
            "recete_kalem_aktif": int(rk),
        }
    aktif = [
        k for k, v in out.items()
        if v.get("present") and v.get("aktif")
    ]
    return {
        "by_code": out,
        "aktif_count": len(aktif),
        "aktif_codes": aktif,
        "missing": [k for k in CORE_CODES if not out.get(k, {}).get("present")],
    }


def _talep_referansi_groups(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(con, "nexgen_planlama_siparis"):
        return []
    rows = con.execute(
        """
        SELECT COALESCE(talep_referansi, '') AS ref, COUNT(*) AS c
        FROM nexgen_planlama_siparis
        GROUP BY ref
        ORDER BY c DESC, ref
        LIMIT 50
        """
    ).fetchall()
    return [{"talep_referansi": r["ref"], "count": int(r["c"])} for r in rows]


def _pzm_filter_count(con: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(con, "nexgen_planlama_siparis"):
        return {"pzm_like": 0, "empty_ref": 0, "total": 0}
    total = con.execute("SELECT COUNT(*) FROM nexgen_planlama_siparis").fetchone()[0]
    pzm = con.execute(
        "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE talep_referansi LIKE ?",
        ("__PZM_V%",),
    ).fetchone()[0]
    empty = con.execute(
        "SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE COALESCE(talep_referansi,'')=''"
    ).fetchone()[0]
    return {"total": int(total), "pzm_like": int(pzm), "empty_ref": int(empty)}


def _role_permission_summary(con: sqlite3.Connection) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if not _table_exists(con, "sistem_kullanici"):
        return summary

    for label, login in USER_LOOKUP:
        user = con.execute(
            """
            SELECT Id, KullaniciAdi, AdSoyad, RolId, Rol, Aktif
            FROM sistem_kullanici
            WHERE LOWER(KullaniciAdi)=LOWER(?)
            LIMIT 1
            """,
            (login,),
        ).fetchone()
        if not user:
            summary[label] = {"found": False}
            continue

        perms: dict[str, dict[str, bool]] = {}
        if user["RolId"] and _table_exists(con, "sistem_rol_yetki"):
            rows = con.execute(
                """
                SELECT y.Kod,
                       COALESCE(ry.can_view,0) AS can_view,
                       COALESCE(ry.can_create,0) AS can_create,
                       COALESCE(ry.can_update,0) AS can_update,
                       COALESCE(ry.can_delete,0) AS can_delete,
                       COALESCE(ry.can_manage,0) AS can_manage,
                       COALESCE(ry.Gorebilir,0) AS Gorebilir,
                       COALESCE(ry.Duzenleyebilir,0) AS Duzenleyebilir
                FROM sistem_rol_yetki ry
                JOIN sistem_yetki y ON y.Id = ry.YetkiId
                WHERE ry.RolId=?
                """,
                (user["RolId"],),
            ).fetchall()
            for r in rows:
                kod = r["Kod"]
                if not any(kod == p or kod.startswith(p.split(".")[0]) for p in NEXGEN_PERM_CODES):
                    if not kod.startswith("nexgen"):
                        continue
                perms[kod] = {
                    "can_view": bool(r["can_view"] or r["Gorebilir"]),
                    "can_create": bool(r["can_create"]),
                    "can_update": bool(r["can_update"] or r["Duzenleyebilir"]),
                    "can_delete": bool(r["can_delete"]),
                    "can_manage": bool(r["can_manage"]),
                }

        summary[label] = {
            "found": True,
            "id": user["Id"],
            "kullanici_adi": user["KullaniciAdi"],
            "ad_soyad": user["AdSoyad"],
            "rol_id": user["RolId"],
            "rol": user["Rol"],
            "aktif": bool(user["Aktif"]),
            "nexgen_permissions": perms,
            "tablet_view": bool(
                perms.get("nexgen.tablet.view", {}).get("can_view")
            ),
        }
    return summary


def build_profile(db_path: str) -> dict[str, Any]:
    con = _connect(db_path)
    try:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": os.path.abspath(db_path),
            "schema_migrations_max": _schema_migration_max(con),
            "integrity_check": _integrity_check(con),
            "table_counts": _table_counts(con),
            "core_formul": _core_formul_status(con),
            "talep_referansi_groups": _talep_referansi_groups(con),
            "pzm_filter": _pzm_filter_count(con),
            "role_permissions": _role_permission_summary(con),
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    ap = argparse.ArgumentParser(description="NexGen server DB profile export")
    ap.add_argument("--db", required=True, help="SQLite DB yolu")
    ap.add_argument("--out", required=True, help="JSON çıktı dosyası")
    args = ap.parse_args(argv)

    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"HATA: DB yok: {db}", file=sys.stderr)
        return 2

    profile = build_profile(db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK profile -> {out_path}")
    print(
        f"schema_max={profile['schema_migrations_max']} "
        f"core_aktif={profile['core_formul']['aktif_count']} "
        f"pzm_like={profile['pzm_filter']['pzm_like']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

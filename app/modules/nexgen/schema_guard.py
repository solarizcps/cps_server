# -*- coding: utf-8 -*-
"""FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1 — runtime schema guard."""
from __future__ import annotations

from flask import jsonify


def _cols(con, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _table(con, name: str) -> bool:
    try:
        return bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
        )
    except Exception:
        return False


def missing_for_renk_merkezi(con) -> list[str]:
    miss = []
    if not _table(con, "nexgen_rf_renk"):
        miss.append("tablo:nexgen_rf_renk")
        return miss
    cols = _cols(con, "nexgen_rf_renk")
    if "aktif_rev_no" not in cols:
        miss.append("migration:098(nexgen_rf_renk.aktif_rev_no)")
    return miss


def missing_for_tablet_arge(con) -> list[str]:
    miss = []
    if not _table(con, "nexgen_arge_test"):
        miss.append("tablo:nexgen_arge_test")
        return miss
    cols = _cols(con, "nexgen_arge_test")
    for c in ("calisma_tipi", "formul_grup_adi", "renk_kodu", "saha_testi_gerekli_mi"):
        if c not in cols:
            miss.append(f"migration:106(nexgen_arge_test.{c})")
            break
    return miss


def missing_for_pazarlama(con) -> list[str]:
    miss = []
    if not _table(con, "nexgen_planlama_siparis"):
        miss.append("tablo:nexgen_planlama_siparis")
    # 107 opsiyonel ama v2 için gerekli — yoksa schema_partial
    if not _table(con, "nexgen_planlama_siparis_kalem"):
        miss.append("migration:107(nexgen_planlama_siparis_kalem)")
    return miss


def schema_not_ready_json(missing: list[str], feature: str):
    """Kontrollü 503 — boş liste ile karıştırılmaz."""
    codes = []
    for m in missing:
        if m.startswith("migration:"):
            codes.append(m.split("(")[0].replace("migration:", ""))
    uniq = sorted(set(codes)) or ["?"]
    msg = (
        f"NexGen veritabanı şeması güncel değil ({feature}). "
        f"Eksik migration: {', '.join(uniq)}"
    )
    return jsonify({
        "ok": False,
        "error": "SCHEMA_NOT_READY",
        "hata": msg,
        "feature": feature,
        "missing": missing,
        "migrations": uniq,
    }), 503


def schema_not_ready_html_flash(missing: list[str], feature: str) -> str:
    codes = []
    for m in missing:
        if m.startswith("migration:"):
            codes.append(m.split("(")[0].replace("migration:", ""))
    uniq = sorted(set(codes)) or ["?"]
    return (
        f"NexGen veritabanı şeması güncel değil ({feature}). "
        f"Eksik migration: {', '.join(uniq)}"
    )

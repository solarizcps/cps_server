# -*- coding: utf-8 -*-
"""Gerçek posting fazı öncesi preflight gate — P1."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parent.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from modules.nexgen.finans_cari_gecis_service import reconciliation_ozet
from modules.nexgen.finans_cari_har_write_guard import scan_pass, unauthorized_writes
from modules.nexgen.finans_core_schema import f1_core_schema_ok


def evaluate_posting_gate(db_path: str | None = None) -> dict[str, Any]:
    db = db_path or os.path.normpath(os.path.join(APP, 'mock_data.db'))
    reasons: list[str] = []
    rec: dict[str, Any] = {}

    guard_ok, bad = scan_pass(APP)
    if not guard_ok:
        for b in bad[:10]:
            reasons.append(f'UNAUTHORIZED_CARI_HAR_WRITE:{b["file"]}:{b["line"]}')

    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rec = reconciliation_ozet(con)
        if rec.get('finans_kart_eksik_aktif', 0) != 0:
            reasons.append('FINANS_KART_EKSIK')
        if rec.get('baglanti_eksik_aktif', 0) != 0:
            reasons.append('BAGLANTI_EKSIK')
        if rec.get('resolver_hatasi', 0) != 0:
            reasons.append('RESOLVER_HATASI')
        ok_schema, schema_msg = f1_core_schema_ok(con)
        if not ok_schema:
            reasons.append(f'SCHEMA_FAIL:{schema_msg}')
    finally:
        con.close()

    ready = len(reasons) == 0
    return {
        'FINANS_POSTING_GATE_READY': ready,
        'reasons': reasons,
        'unauthorized_write_count': len(bad) if not guard_ok else 0,
        'reconciliation': rec,
    }


if __name__ == '__main__':
    result = evaluate_posting_gate()
    print('FINANS_POSTING_GATE_READY=' + str(result['FINANS_POSTING_GATE_READY']).lower())
    for r in result.get('reasons') or []:
        print('FAIL:', r)
    raise SystemExit(0 if result['FINANS_POSTING_GATE_READY'] else 1)

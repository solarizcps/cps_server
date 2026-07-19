# -*- coding: utf-8 -*-
"""FAZ-RENK-MERKEZI-HATA-1 — detay NX-AR pigment + rf=None crash fix (tmp DB)."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "app"))

from flask import Flask  # noqa: E402
from tools.nexgen_tmp_db import cleanup_tmp, tmp_db_context  # noqa: E402
from modules.nexgen.nx_ar_service import CANONICAL_CREATE_PAYLOAD_DOC, create_nx_ar  # noqa: E402
from modules.nexgen import routes as nx_routes  # noqa: E402


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def main():
    real = os.path.join(ROOT, "app", "mock_data.db")
    with tmp_db_context(real, prefix="rm_hata1_test_") as info:
        tmp = info["tmp_db"]
        import importlib.util

        mig = os.path.join(
            ROOT, "app", "migrations", "109_nx_ar_onay_enjeksiyon_alanlari.py"
        )
        spec = importlib.util.spec_from_file_location("m109", mig)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.run(tmp).get("ok")

        con = sqlite3.connect(tmp)
        con.row_factory = sqlite3.Row
        boya = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kategori='BOYA' AND aktif=1 LIMIT 1"
        ).fetchone()["id"]
        p = copy.deepcopy(CANONICAL_CREATE_PAYLOAD_DOC)
        p["hedef_renk_adi"] = "HATA1-FIX"
        p["renk_bilesenleri"] = [
            {"stok_kart_id": boya, "ad": "Pigment", "kg": 0.01, "stok_kodu": "P"}
        ]
        for k in p["deneme"]["kalemler"]:
            k["stok_kart_id"] = boya
        out = create_nx_ar(con, p, 1)
        tid = out["arge_test_id"]
        assert not out.get("rf")
        con.close()

        nx_routes.DB_PATH = tmp
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "t"
        fn = _unwrap(nx_routes.api_rm_detay)

        with app.test_request_context(
            f"/nexgen/api/renk-merkezi/detay?arge_test_id={tid}"
        ):
            resp = fn()
            if isinstance(resp, tuple):
                body, status = resp[0], resp[1]
            else:
                body, status = resp, 200
            if hasattr(body, "get_json"):
                data = body.get_json()
                status = body.status_code
            else:
                data = body
            assert status == 200, (status, data)
            assert data.get("ok") is True
            assert data.get("ozet", {}).get("kart_tipi") == "NX_AR"
            assert (data.get("pigment_ozet") or {}).get("kalem_sayisi", 0) >= 1
            assert data["ozet"].get("revizyon_id") == 1
            assert data.get("calisma", {}).get("test_no")
            print(
                "DETAY_OK",
                data["calisma"]["test_no"],
                "pig",
                data["pigment_ozet"]["kalem_sayisi"],
                "rev",
                data["ozet"]["revizyon_id"],
            )

        # 404 path
        with app.test_request_context(
            "/nexgen/api/renk-merkezi/detay?arge_test_id=99999999"
        ):
            resp = fn()
            if isinstance(resp, tuple):
                body, status = resp[0], resp[1]
            else:
                body, status = resp, getattr(resp, "status_code", 200)
            data = body.get_json() if hasattr(body, "get_json") else body
            assert status == 404 and data.get("ok") is False
            print("DETAY_404_OK", data.get("hata"))

        print("SHA_BEFORE", info["sha_before"][:16])
    assert not info["main_db_changed"]
    print("SHA_AFTER", info["sha_after"][:16], "CHANGED", info["main_db_changed"])
    cleanup_tmp(info)
    print("ALL_OK FAZ-RENK-MERKEZI-HATA-1")


if __name__ == "__main__":
    main()

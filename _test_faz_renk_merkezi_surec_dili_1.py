# -*- coding: utf-8 -*-
"""FAZ-RENK-MERKEZI-SUREC-DILI-1 — AR-GE karar + süreç dili (tmp DB)."""
from __future__ import annotations

import copy
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "app"))

from tools.nexgen_tmp_db import cleanup_tmp, tmp_db_context  # noqa: E402
from modules.nexgen.nx_ar_service import (  # noqa: E402
    CANONICAL_CREATE_PAYLOAD_DOC,
    NxArError,
    create_nx_ar,
    saha_karar_kaydet,
)


UI_FILES = [
    os.path.join(ROOT, "app", "templates", "nexgen", "renk_merkezi.html"),
    os.path.join(ROOT, "app", "templates", "nexgen", "tablet_arge_enjeksiyon_denemeleri.html"),
    os.path.join(ROOT, "app", "templates", "nexgen", "tablet_arge_enjeksiyon_deneme.html"),
    os.path.join(ROOT, "app", "templates", "nexgen", "modul01_musteri_renk.html"),
    os.path.join(ROOT, "app", "templates", "nexgen", "nx_ar_detay.html"),
]

FORBIDDEN_UI = [
    "Ferhat'a gönder",
    "Ferhat saha sonucu",
    "Ferhat sonucu",
    "Ferhat bekliyor",
    "Ferhat denemesi",
    "Ferhat formu",
    "Ferhat formunu",
    "Ferhat kuyruğuna",
    "Ferhat testi",
    "SAHA TESTİ (FERHAT)",
    "Saha Testi (Ferhat)",
]

REQUIRED_UI = [
    "Enjeksiyon Denemesine Gönder",
    "Onaya Gönder",
    "Karar Vermeden Bırak",
    "Enjeksiyon Deneme Sonucu",
]


def _con(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _payload(boya_id, ad="SUREC-DILI"):
    p = copy.deepcopy(CANONICAL_CREATE_PAYLOAD_DOC)
    p["hedef_renk_adi"] = ad
    p["saha_testi_gerekli_mi"] = 0
    for k in p["deneme"]["kalemler"]:
        k["stok_kart_id"] = boya_id
    return p


def main():
    # UI grep
    for path in UI_FILES:
        text = open(path, encoding="utf-8").read()
        for bad in FORBIDDEN_UI:
            assert bad not in text, f"FORBIDDEN in {os.path.basename(path)}: {bad}"
    rm = open(UI_FILES[0], encoding="utf-8").read()
    for good in REQUIRED_UI:
        assert good in rm, f"MISSING in renk_merkezi: {good}"
    print("UI_GREP_OK")

    real = os.path.join(ROOT, "app", "mock_data.db")
    with tmp_db_context(real, prefix="rm_surec_dili_") as info:
        tmp = info["tmp_db"]
        import importlib.util

        mig = os.path.join(
            ROOT, "app", "migrations", "109_nx_ar_onay_enjeksiyon_alanlari.py"
        )
        spec = importlib.util.spec_from_file_location("m109", mig)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.run(tmp).get("ok")

        con = _con(tmp)
        boya = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kategori='BOYA' AND aktif=1 LIMIT 1"
        ).fetchone()["id"]

        # A) Onaya Gönder
        a = create_nx_ar(con, _payload(boya, "A-ONAYA"), 1)
        tid_a = a["arge_test_id"]
        at_a = a["test_no"]
        out = saha_karar_kaydet(con, tid_a, {"karar": "ONAYA_GONDER"}, 1)
        assert out["durum"] == "ONAY_BEKLIYOR"
        assert out["test_no"] == at_a
        assert int(out.get("saha_testi_gerekli_mi") or 0) == 0
        assert (
            con.execute(
                "SELECT COUNT(*) FROM nexgen_arge_test WHERE id=? AND durum='FERHAT_BEKLIYOR'",
                (tid_a,),
            ).fetchone()[0]
            == 0
        )
        print("A_ONAYA_OK", at_a)

        # B) Enjeksiyon — neden zorunlu
        b = create_nx_ar(con, _payload(boya, "B-ENJ"), 1)
        tid_b = b["arge_test_id"]
        at_b = b["test_no"]
        try:
            saha_karar_kaydet(con, tid_b, {"karar": "ENJEKSIYON"}, 1)
            raise SystemExit("FAIL neden yok kabul")
        except NxArError as e:
            assert e.status == 400
        outb = saha_karar_kaydet(
            con,
            tid_b,
            {"karar": "ENJEKSIYON", "saha_testi_nedeni": "YENI_RENK"},
            1,
        )
        assert outb["durum"] == "FERHAT_BEKLIYOR"  # DB enum korunur
        assert outb["test_no"] == at_b
        # duplicate
        outb2 = saha_karar_kaydet(
            con,
            tid_b,
            {"karar": "ENJEKSIYON", "saha_testi_nedeni": "YENI_RENK"},
            1,
        )
        assert outb2["durum"] == "FERHAT_BEKLIYOR"
        assert outb2["test_no"] == at_b
        n_enj = con.execute(
            "SELECT COUNT(*) FROM nexgen_arge_test WHERE test_no=?", (at_b,)
        ).fetchone()[0]
        assert n_enj == 1
        print("B_ENJEKSIYON_OK", at_b)

        # C) Karar Vermeden Bırak
        c0 = create_nx_ar(con, _payload(boya, "C-BIRAK"), 1)
        tid_c = c0["arge_test_id"]
        at_c = c0["test_no"]
        outc = saha_karar_kaydet(con, tid_c, {"karar": "BIRAK"}, 1)
        assert outc["durum"] == "ARGE_HAZIR"
        assert outc["test_no"] == at_c
        outc2 = saha_karar_kaydet(con, tid_c, {"karar": "BIRAK"}, 1)
        assert outc2["durum"] == "ARGE_HAZIR"
        olay_n = con.execute(
            """
            SELECT COUNT(*) FROM nexgen_arge_olay
            WHERE arge_test_id=? AND olay_tipi='SAHA_KARAR_BIRAK'
            """,
            (tid_c,),
        ).fetchone()[0]
        assert olay_n >= 2
        # BIRAK RED/REV değil
        assert (
            con.execute(
                "SELECT durum FROM nexgen_arge_test WHERE id=?", (tid_c,)
            ).fetchone()[0]
            == "ARGE_HAZIR"
        )
        print("C_BIRAK_OK", at_c, "olay", olay_n)

        # D) UI etiket eşlemesi
        from modules.nexgen.routes import _nx_ar_durum_etiketi

        e1 = _nx_ar_durum_etiketi("FERHAT_BEKLIYOR")
        e2 = _nx_ar_durum_etiketi("DENEMEDE")
        assert "Ferhat" not in e1 and "Ferhat" not in e2
        assert "ENJEKSİYON" in e1 and "BEKLİYOR" in e1
        assert "ENJEKSİYON" in e2 and "DEVAM" in e2
        print("D_ETIKET_OK", e1, "|", e2)

        # E) Onaya sonrası sessizce ARGE_HAZIR'e dönmez
        try:
            saha_karar_kaydet(con, tid_a, {"karar": "BIRAK"}, 1)
            raise SystemExit("FAIL BIRAK from ONAY_BEKLIYOR")
        except NxArError as e:
            assert e.status == 409
        assert (
            con.execute(
                "SELECT durum FROM nexgen_arge_test WHERE id=?", (tid_a,)
            ).fetchone()[0]
            == "ONAY_BEKLIYOR"
        )
        print("E_NO_SILENT_REVERT_OK")

        con.close()
        print("SHA_BEFORE", info["sha_before"][:16])
    assert not info["main_db_changed"]
    print("SHA_AFTER", info["sha_after"][:16], "CHANGED", info["main_db_changed"])

    # Enjeksiyon modülü diff=0 (working tree relative check via git)
    import subprocess

    r = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--",
            "app/modules/enjeksiyon",
            "app/templates/enjeksiyon",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert not (r.stdout or "").strip(), r.stdout
    print("ENJEKSIYON_DIFF_0_OK")
    cleanup_tmp(info)
    print("ALL_OK FAZ-RENK-MERKEZI-SUREC-DILI-1")


if __name__ == "__main__":
    main()

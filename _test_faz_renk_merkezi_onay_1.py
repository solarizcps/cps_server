# -*- coding: utf-8 -*-
"""FAZ-RENK-MERKEZI-ONAY-1 — tmp_db_context workflow tests (live DB yazılmaz)."""
from __future__ import annotations

import copy
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "app"))

from tools.nexgen_tmp_db import cleanup_tmp, tmp_db_context  # noqa: E402
from modules.nexgen.nx_ar_service import (  # noqa: E402
    CANONICAL_CREATE_PAYLOAD_DOC,
    NxArError,
    create_nx_ar,
    ferhat_ac,
    ferhat_bekleyen_liste,
    ferhat_sonuc_kaydet,
    get_nx_ar,
    saha_karar_kaydet,
    yonetim_karar,
)

REAL_DB = os.path.join(ROOT, "app", "mock_data.db")
MIG109 = os.path.join(ROOT, "app", "migrations", "109_nx_ar_onay_enjeksiyon_alanlari.py")


def _con(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _apply_109(tmp_db):
    import importlib.util

    spec = importlib.util.spec_from_file_location("mig109", MIG109)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.run(tmp_db)
    assert out.get("ok"), out
    print("MIG109_OK", out.get("kolon"), out.get("tablo"))


def _boya_stok(con) -> int:
    r = con.execute(
        "SELECT id FROM nexgen_stok_kart WHERE kategori='BOYA' AND aktif=1 LIMIT 1"
    ).fetchone()
    assert r, "BOYA stok yok"
    return int(r["id"])


def _payload(boya_id: int, tip="YENI_RF", hedef="ONAY-TEST-RENK"):
    p = copy.deepcopy(CANONICAL_CREATE_PAYLOAD_DOC)
    p["calisma_tipi"] = tip
    p["hedef_renk_adi"] = hedef
    p["saha_testi_gerekli_mi"] = 0
    for k in p["deneme"]["kalemler"]:
        k["stok_kart_id"] = boya_id
    return p


def _boyut_payload(boyutlar, karar="BASARILI"):
    items = []
    for b in boyutlar:
        items.append(
            {
                "boyut": b,
                "shore_sonuc": 42,
                "pisme_suresi_dk": 3.5,
                "enjeksiyon_saniye": 12,
                "yogunluk": 0.25,
                "kalip_sonucu": "OK",
                "renk_sonucu": "OK",
                "kalite_sorunu_var": 0,
                "basarili_mi": 1 if karar == "BASARILI" else 0,
                "saha_notu": "test",
            }
        )
    return {
        "ferhat_genel_karar": karar,
        "ferhat_genel_not": None if karar == "BASARILI" else "revizyon notu",
        "boyut_sonuclar": items,
    }


def main():
    assert os.path.isfile(REAL_DB)
    with tmp_db_context(REAL_DB, prefix="faz_rm_onay1_") as info:
        tmp = info["tmp_db"]
        _apply_109(tmp)
        con = _con(tmp)
        boya = _boya_stok(con)

        # 1) AT-R saha hayır → onay → renk kodu
        out = create_nx_ar(con, _payload(boya, "YENI_RF", "TEST-R-HAYIR"), 1)
        tid = out["arge_test_id"]
        assert out["durum"] == "ARGE_HAZIR"
        assert (out.get("test_no") or "").startswith("AT-R-")
        saha_karar_kaydet(con, tid, {"saha_testi_gerekli_mi": 0}, 1)
        g = get_nx_ar(con, tid)
        assert g["durum"] == "ONAY_BEKLIYOR"
        onay = yonetim_karar(con, tid, {"karar": "ONAY"}, 1)
        assert onay["durum"] == "ONAYLANDI"
        assert onay.get("renk_kodu")
        assert onay.get("rf") and onay["rf"].get("rf_kod")
        kod1 = onay["renk_kodu"]
        print("AT_R_HAYIR_OK", out["test_no"], kod1, onay["rf"]["rf_kod"])

        # 2) AT-R saha evet → Ferhat → onay
        out2 = create_nx_ar(con, _payload(boya, "YENI_RF", "TEST-R-EVET"), 1)
        tid2 = out2["arge_test_id"]
        saha_karar_kaydet(
            con,
            tid2,
            {"saha_testi_gerekli_mi": 1, "saha_testi_nedeni": "YENI_RENK"},
            1,
        )
        g2 = get_nx_ar(con, tid2)
        assert g2["durum"] == "FERHAT_BEKLIYOR"
        lst = ferhat_bekleyen_liste(con)
        assert any(i["arge_test_id"] == tid2 for i in lst["items"])
        ferhat_ac(con, tid2, 1)
        assert get_nx_ar(con, tid2)["durum"] == "DENEMEDE"
        ferhat_sonuc_kaydet(
            con, tid2, _boyut_payload(g2["boyutlar"], "BASARILI"), 1
        )
        assert get_nx_ar(con, tid2)["durum"] == "ONAY_BEKLIYOR"
        onay2 = yonetim_karar(con, tid2, {"karar": "ONAY"}, 1)
        assert onay2["durum"] == "ONAYLANDI"
        assert int(onay2["renk_kodu"]) > int(kod1)
        print("AT_R_EVET_OK", out2["test_no"], onay2["renk_kodu"])

        # 3) Ferhat RED → onay engeli
        out3 = create_nx_ar(con, _payload(boya, "YENI_RF", "TEST-R-RED"), 1)
        tid3 = out3["arge_test_id"]
        saha_karar_kaydet(
            con,
            tid3,
            {"saha_testi_gerekli_mi": 1, "saha_testi_nedeni": "KALIP_RISKI"},
            1,
        )
        g3 = get_nx_ar(con, tid3)
        ferhat_ac(con, tid3, 1)
        ferhat_sonuc_kaydet(con, tid3, _boyut_payload(g3["boyutlar"], "RED"), 1)
        assert get_nx_ar(con, tid3)["durum"] == "REDDEDILDI"
        try:
            yonetim_karar(con, tid3, {"karar": "ONAY"}, 1)
            raise SystemExit("FAIL red sonra onay")
        except NxArError as e:
            assert e.status == 409
            print("FERHAT_RED_BLOCK_OK", e.kod)

        # 4) Yönetim revizyon
        out4 = create_nx_ar(con, _payload(boya, "MUSTERI_RENK", "TEST-M-REV"), 1)
        tid4 = out4["arge_test_id"]
        assert (out4.get("test_no") or "").startswith("AT-M-")
        saha_karar_kaydet(con, tid4, {"saha_testi_gerekli_mi": 0}, 1)
        yonetim_karar(con, tid4, {"karar": "REVIZYON", "neden": "renk tonu"}, 1)
        assert get_nx_ar(con, tid4)["durum"] == "REVIZYON_GEREKLI"
        print("AT_M_REV_OK", out4["test_no"])

        # 5) AT-F formül onayı (kullanıcı kodu)
        pf = _payload(boya, "YENI_FORMUL", "TEST-F")
        # benzersiz formül kodu
        fk = "1BA-TEST-ONAY1"
        while con.execute(
            "SELECT 1 FROM nexgen_formul WHERE kod=? COLLATE NOCASE", (fk,)
        ).fetchone():
            fk = fk + "X"
        out5 = create_nx_ar(con, pf, 1)
        tid5 = out5["arge_test_id"]
        assert (out5.get("test_no") or "").startswith("AT-F-")
        saha_karar_kaydet(con, tid5, {"saha_testi_gerekli_mi": 0}, 1)
        try:
            yonetim_karar(con, tid5, {"karar": "ONAY"}, 1)
            raise SystemExit("FAIL formul kodsuz onay")
        except NxArError as e:
            assert e.status == 400
        onayf = yonetim_karar(
            con,
            tid5,
            {"karar": "ONAY", "formul_kod": fk, "formul_ad": "Onay Test Formul"},
            1,
        )
        assert onayf["durum"] == "ONAYLANDI"
        assert con.execute(
            "SELECT 1 FROM nexgen_formul WHERE kod=?", (fk,)
        ).fetchone()
        print("AT_F_OK", out5["test_no"], fk)

        # 6) NX-AR UI gizlilik — get payload'da arge_kodu var ama test_no AT
        g5 = get_nx_ar(con, tid5)
        assert g5["test_no"].startswith("AT-")
        assert g5["arge_kodu"].startswith("NX-AR-")
        assert g5.get("olaylar") is not None
        print("PAYLOAD_OK olay", len(g5.get("olaylar") or []))

        # 7) Enjeksiyon diff = 0 (dosya dokunulmamışlık bu testte git ile dışarıda)
        print("SHA_BEFORE", info["sha_before"][:16])
        con.close()

    print("SHA_AFTER", info["sha_after"][:16])
    print("MAIN_DB_CHANGED", info["main_db_changed"])
    assert not info["main_db_changed"]
    cleanup_tmp(info)
    print("ALL_OK FAZ-RENK-MERKEZI-ONAY-1")


if __name__ == "__main__":
    main()

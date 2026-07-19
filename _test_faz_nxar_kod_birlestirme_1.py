# -*- coding: utf-8 -*-
"""FAZ-NXAR-KOD-BIRLESTIRME-1 — AT ana kimlik, NX-AR sistem referansı (tmp DB)."""
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, "app")
sys.path.insert(0, _APP)
os.chdir(_APP)

from tools.nexgen_tmp_db import sha256_file, cleanup_tmp

_LIVE = os.path.join(_APP, "mock_data.db")
_SHA0 = sha256_file(_LIVE)
_TMP = tempfile.mkdtemp(prefix="nxar_kod_")
TEST_DB = os.path.join(_TMP, "mock_data_test.db")
shutil.copy2(_LIVE, TEST_DB)

import config as _cfg
_cfg.Config.MOCK_DB_PATH = TEST_DB

import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.nx_ar_service import create_nx_ar
from modules.nexgen.cekirdek_gorunum import formul_secim_gruplari_hazirla

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config["TESTING"] = True
results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


print("=" * 72)
print("FAZ-NXAR-KOD-BIRLESTIRME-1")
print(f"sha0={_SHA0}")
print("=" * 72)

# UI: eşit ağırlık string yok
print("\n[UI]")
rm = open(os.path.join(_APP, "templates", "nexgen", "renk_merkezi.html"), encoding="utf-8").read()
m1 = open(os.path.join(_APP, "templates", "nexgen", "modul01_musteri_renk.html"), encoding="utf-8").read()
m2 = open(os.path.join(_APP, "templates", "nexgen", "modul02_yeni_rf.html"), encoding="utf-8").read()
nx = open(os.path.join(_APP, "templates", "nexgen", "nx_ar_detay.html"), encoding="utf-8").read()
al = open(os.path.join(_APP, "templates", "nexgen", "arge_liste.html"), encoding="utf-8").read()

ok("RM esit agirlik yok", " · '+k.arge_kodu" not in rm and "test_no + (k.arge_kodu" not in rm)
ok("RM Sistem Referansı", "Sistem Referansı" in rm)
ok("RM AT ana kart", "k.test_no || k.arge_kodu" in rm or "kart.test_no" in rm)
ok("M02 Sistem Referansı", "Sistem Referansı" in m2)
ok("M02 esit · yok", "' · '+S._kaydedilen_arge_kodu" not in m2)
ok("M01 test_no ana", "d.test_no || d.arge_kodu" in m1)
ok("M01 Sistem Referansı", "Sistem Referansı" in m1)
ok("NX detay AT baslik", "kart.test_no or kart.arge_kodu" in nx)
ok("NX detay etiket Çalışma", "Çalışma Kodu" in nx)
ok("Liste AT uste", "t.test_no or t.arge_kodu" in al)
ok("Liste Sistem Referansı", "Sistem Referansı" in al)

con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row
uv_rows = [dict(r) for r in con.execute("""
    SELECT uv.id, uv.boyut, rv.id AS rv_id, rv.ad AS renk_ad,
           f.id AS formul_id, f.kod AS formul_kod, f.ad AS formul_ad, f.urun_ailesi
    FROM nexgen_uretim_varyant uv
    JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id AND rv.aktif=1
    JOIN nexgen_formul f ON f.id=rv.formul_id AND f.aktif=1
    WHERE uv.aktif=1 AND f.kod LIKE '1BA-F%'
""").fetchall()]
gruplar = formul_secim_gruplari_hazirla(uv_rows)
ls = [g for g in gruplar if len(g.get("secenekler") or []) >= 2]
cari = con.execute("SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1").fetchone()

def _kaynak(g):
    kaynak = []
    for i, s in enumerate(g["secenekler"]):
        if s["boyut"] in ("LARGE", "SMALL", "MEDIUM"):
            kaynak.append({
                "boyut": s["boyut"],
                "kaynak_uretim_varyant_id": s["uv_id"],
                "sira_no": i + 1,
            })
    return kaynak

created = {}
if ls:
    g0 = ls[0]
    ana = "1BA"
    for s in g0["secenekler"]:
        m = re.match(r"^(1BA|2BA|3BA)", s["formul_kod"] or "")
        if m:
            ana = m.group(1)
            break
    for tip, label, hedef in [
        ("YENI_RF", "rf", "KOD BIRLESTIR RF"),
        ("YENI_FORMUL", "formul", "KOD BIRLESTIR FML"),
        ("MUSTERI_RENK", "musteri", "KOD BIRLESTIR MUS"),
    ]:
        print(f"\n[CREATE {tip}]")
        out = create_nx_ar(con, {
            "calisma_tipi": tip,
            "cari_id": cari["id"] if cari else None,
            "ana_formul_grup_kodu": ana,
            "formul_grup_adi": g0["baslik"],
            "hedef_renk_adi": hedef,
            "talep_referansi": "TALEP-KB1" if tip == "MUSTERI_RENK" else None,
            "saha_testi_gerekli_mi": 0,
            "kaynak_uvler": _kaynak(g0),
            "deneme": {"numune_orani": 10},
        }, kullanici_id=1)
        created[label] = out
        ok(f"{label} ok", out.get("ok") is True, out.get("arge_kodu"))
        ok(f"{label} AT var", bool(re.match(r"^AT-[RFM]-\d{4}-\d{4}$", out.get("test_no") or "")), out.get("test_no"))
        ok(f"{label} NX-AR var", (out.get("arge_kodu") or "").startswith("NX-AR-"), out.get("arge_kodu"))

# Lookup / barkod AT
print("\n[LOOKUP]")
with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {"Id": 1, "KullaniciAdi": "admin", "Tip": "sistem", "RolId": 1, "Aktif": 1}
        s["kullanici_tip"] = "sistem"
    if created.get("rf"):
        tn = created["rf"]["test_no"]
        ak = created["rf"]["arge_kodu"]
        r = c.get(f"/nexgen/tablet/barkod?kod={tn}")
        ok("AT barkod", r.status_code < 500, str(r.status_code))
        # NX-AR barkod route mevcut haliyle AT- prefix bekler — arama RM üzerinden
        rj = c.get(f"/nexgen/api/renk-merkezi/liste?q={tn}").get_json() or {}
        kartlar = rj.get("kartlar") or []
        mine = [k for k in kartlar if k.get("test_no") == tn]
        ok("RM AT arama", len(mine) >= 1, f"n={len(mine)}")
        if mine:
            ok("RM kart AT ana alan", mine[0].get("test_no") == tn)
            ok("RM kart NX alan", mine[0].get("arge_kodu") == ak)
        rj2 = c.get(f"/nexgen/api/renk-merkezi/liste?q={ak}").get_json() or {}
        mine2 = [k for k in (rj2.get("kartlar") or []) if k.get("arge_kodu") == ak]
        ok("RM NX-AR arama", len(mine2) >= 1, f"n={len(mine2)}")
        # detay route
        tid = created["rf"]["arge_test_id"]
        rd = c.get(f"/nexgen/arge/nx-ar/{tid}")
        ok("detay sayfa", rd.status_code < 500, str(rd.status_code))
        html = rd.get_data(as_text=True)
        ok("detay AT gorunur", tn in html)
        ok("detay Sistem Referansı", "Sistem Referansı" in html and ak in html)
        # eski AT
        eski = con.execute(
            "SELECT test_no FROM nexgen_arge_test WHERE test_no LIKE 'AT-2026-%' LIMIT 1"
        ).fetchone()
        if eski:
            re_ = c.get(f"/nexgen/tablet/barkod?kod={eski['test_no']}")
            ok("eski AT barkod", re_.status_code < 500, str(re_.status_code))
        else:
            ok("eski AT barkod", True, "skip")

_SHA1 = sha256_file(_LIVE)
ok("Ana DB SHA", _SHA0 == _SHA1, f"{_SHA0[:12]}…")

con.close()
fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"PASS_COUNT/TOTAL={len(results)-len(fails)}/{len(results)}")
for n, c, d in results:
    if not c:
        print("FAIL", n, d)
cleanup_tmp({"tmp_dir": _TMP})
sys.exit(1 if fails else 0)

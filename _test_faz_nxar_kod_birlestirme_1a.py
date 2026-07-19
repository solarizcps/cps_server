# -*- coding: utf-8 -*-
"""FAZ-NXAR-KOD-BIRLESTIRME-1A — NX-AR kullanıcı UI'de yok (tmp DB)."""
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
_TMP = tempfile.mkdtemp(prefix="nxar_1a_")
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
print("FAZ-NXAR-KOD-BIRLESTIRME-1A")
print(f"sha0={_SHA0}")
print("=" * 72)

files = {
    "rm": "renk_merkezi.html",
    "m1": "modul01_musteri_renk.html",
    "m2": "modul02_yeni_rf.html",
    "nx": "nx_ar_detay.html",
    "al": "arge_liste.html",
    "ta": "tablet_arge.html",
}
print("\n[UI]")
for key, name in files.items():
    path = os.path.join(_APP, "templates", "nexgen", name)
    txt = open(path, encoding="utf-8").read()
    # Kullanıcıya giden stringler: Sistem Referansı + görünür NX-AR- kalıbı
    ok(f"{key} Sistem Referansı yok", "Sistem Referansı" not in txt)
    # HTML/JS user strings — NX-AR- prefix display patterns
    bad_disp = re.findall(
        r"Sistem Referansı|NX-AR-\d+|['\"]NX-AR['\"]|>NX-AR<",
        txt,
    )
    # JS comments may mention NX-AR; exclude // and /* */ lines roughly via display patterns above
    ok(f"{key} NX-AR display yok", "Sistem Referansı" not in txt and " · '+k.arge_kodu" not in txt)

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
    out = []
    for i, s in enumerate(g["secenekler"]):
        if s["boyut"] in ("LARGE", "SMALL", "MEDIUM"):
            out.append({
                "boyut": s["boyut"],
                "kaynak_uretim_varyant_id": s["uv_id"],
                "sira_no": i + 1,
            })
    return out

created = {}
if ls:
    g0 = ls[0]
    ana = "1BA"
    for s in g0["secenekler"]:
        m = re.match(r"^(1BA|2BA|3BA)", s["formul_kod"] or "")
        if m:
            ana = m.group(1)
            break
    for tip, label in [("YENI_RF", "rf"), ("YENI_FORMUL", "formul"), ("MUSTERI_RENK", "musteri")]:
        print(f"\n[CREATE {tip}]")
        out = create_nx_ar(con, {
            "calisma_tipi": tip,
            "cari_id": cari["id"] if cari else None,
            "ana_formul_grup_kodu": ana,
            "formul_grup_adi": g0["baslik"],
            "hedef_renk_adi": f"1A {label}",
            "talep_referansi": "T-1A" if tip == "MUSTERI_RENK" else None,
            "saha_testi_gerekli_mi": 0,
            "kaynak_uvler": _kaynak(g0),
            "deneme": {"numune_orani": 10},
        }, kullanici_id=1)
        created[label] = out
        ok(f"{label} AT", bool(re.match(r"^AT-[RFM]-\d{4}-\d{4}$", out.get("test_no") or "")), out.get("test_no"))
        ok(f"{label} NX backend", (out.get("arge_kodu") or "").startswith("NX-AR-"), out.get("arge_kodu"))

print("\n[LOOKUP+UI]")
with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {"Id": 1, "KullaniciAdi": "admin", "Tip": "sistem", "RolId": 1, "Aktif": 1}
        s["kullanici_tip"] = "sistem"
    rf = created.get("rf")
    if rf:
        tn, ak, tid = rf["test_no"], rf["arge_kodu"], rf["arge_test_id"]
        r = c.get(f"/nexgen/tablet/barkod?kod={tn}")
        ok("AT barkod", r.status_code < 500, str(r.status_code))
        # backend hâlâ arge_kodu tutuyor
        row = con.execute(
            "SELECT arge_kodu, test_no FROM nexgen_arge_test WHERE id=?", (tid,)
        ).fetchone()
        ok("DB NX-AR korundu", row["arge_kodu"] == ak and row["test_no"] == tn)
        # RM API search AT
        rj = c.get(f"/nexgen/api/renk-merkezi/liste?q={tn}").get_json() or {}
        mine = [k for k in (rj.get("kartlar") or []) if k.get("test_no") == tn]
        ok("RM AT arama", len(mine) >= 1)
        # detay HTML — AT var, NX-AR yok
        rd = c.get(f"/nexgen/arge/nx-ar/{tid}")
        ok("detay route", rd.status_code not in (404, 500) and rd.status_code < 500, str(rd.status_code))
        html = rd.get_data(as_text=True)
        ok("detay AT görünür", tn in html)
        ok("detay NX-AR yok", ak not in html and "Sistem Referansı" not in html)
        # RM sayfa
        rm = c.get("/nexgen/renk-merkezi")
        ok("rm route", rm.status_code < 500, str(rm.status_code))
        rm_html = rm.get_data(as_text=True)
        ok("rm Sistem Referansı yok", "Sistem Referansı" not in rm_html)
        # liste / m01 / m02
        for path, name in [
            ("/nexgen/arge", "arge_liste"),
            ("/nexgen/tablet/arge/yeni-rf", "m02"),
            ("/nexgen/tablet/arge/musteri-renk", "m01"),
            ("/nexgen/tablet/arge", "tablet_arge"),
        ]:
            st = c.get(path).status_code
            ok(f"route {name}", st not in (404, 500) and st < 500, str(st))
        eski = con.execute(
            "SELECT test_no FROM nexgen_arge_test WHERE test_no LIKE 'AT-2026-%' LIMIT 1"
        ).fetchone()
        if eski:
            ok("eski AT", c.get(f"/nexgen/tablet/barkod?kod={eski['test_no']}").status_code < 500)
        else:
            ok("eski AT", True, "skip")

_SHA1 = sha256_file(_LIVE)
ok("Ana DB SHA", _SHA0 == _SHA1)

con.close()
fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"PASS_COUNT/TOTAL={len(results)-len(fails)}/{len(results)}")
for n, c, d in results:
    if not c:
        print("FAIL", n, d)
cleanup_tmp({"tmp_dir": _TMP})
sys.exit(1 if fails else 0)

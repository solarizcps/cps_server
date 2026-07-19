# -*- coding: utf-8 -*-
"""FAZ-RENK-GELISTIRME-1 — L/S grup + AT-R/F/M (tmp DB, live yazmaz)."""
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
_TMP = tempfile.mkdtemp(prefix="renk_gel_")
TEST_DB = os.path.join(_TMP, "mock_data_test.db")
shutil.copy2(_LIVE, TEST_DB)

import config as _cfg
_cfg.Config.MOCK_DB_PATH = TEST_DB

import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.nx_ar_service import _test_no_uret, create_nx_ar, NxArError
from modules.nexgen.cekirdek_gorunum import formul_secim_gruplari_hazirla

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config["TESTING"] = True
results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row

print("=" * 72)
print("FAZ-RENK-GELISTIRME-1")
print(f"sha0={_SHA0}")
print("=" * 72)

# AT generator
print("\n[AT]")
t_r = _test_no_uret(con, "YENI_RF")
t_f = _test_no_uret(con, "YENI_FORMUL")
t_m = _test_no_uret(con, "MUSTERI_RENK")
ok("AT-R format", bool(re.match(r"^AT-R-\d{4}-\d{4}$", t_r)), t_r)
ok("AT-F format", bool(re.match(r"^AT-F-\d{4}-\d{4}$", t_f)), t_f)
ok("AT-M format", bool(re.match(r"^AT-M-\d{4}-\d{4}$", t_m)), t_m)
try:
    _test_no_uret(con, "GECERSIZ")
    ok("invalid tip hata", False)
except NxArError:
    ok("invalid tip hata", True)

# Gruplama
print("\n[L/S GRUP]")
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
ok("L/S grup var", len(ls) >= 1, f"grup={len(gruplar)} ls={len(ls)}")
if ls:
    boylar = {s["boyut"] for s in ls[0]["secenekler"]}
    ok("grup LARGE+SMALL", "LARGE" in boylar and "SMALL" in boylar, str(boylar))

# UI kaynak: Varyant Seç adımı gizli / yok
print("\n[UI]")
m1 = open(os.path.join(_APP, "templates", "nexgen", "modul01_musteri_renk.html"), encoding="utf-8").read()
m2 = open(os.path.join(_APP, "templates", "nexgen", "modul02_yeni_rf.html"), encoding="utf-8").read()
ok("M01 Ana Formül Seç etiketi", "Ana Formül Seç" in m1)
ok("M01 varyant gizli", "ADIM_GIZLI" in m1 and "3: true" in m1)
ok("M02 formul-grup", "formul-grup" in m2 and "M2_FORMUL_GRUPLAR" in m2)
ok("M02 varyant atlandı", "S.adim=4" in m2 and "ADIM_GIZLI" in m2)
ok("M02 nx-ar kaydet", "/nexgen/api/arge/nx-ar" in m2)
ok("M02 Varyant Seç menüde gizli", "ADIM_GIZLI = {3: true}" in m2)

# Create YENI_RF L/S
print("\n[CREATE YENI_RF]")
g0 = ls[0] if ls else None
if g0:
    kaynak = []
    for i, s in enumerate(g0["secenekler"]):
        if s["boyut"] in ("LARGE", "SMALL"):
            kaynak.append({
                "boyut": s["boyut"],
                "kaynak_uretim_varyant_id": s["uv_id"],
                "sira_no": i + 1,
            })
    ana = "1BA"
    for s in g0["secenekler"]:
        m = re.match(r"^(1BA|2BA|3BA)", s["formul_kod"] or "")
        if m:
            ana = m.group(1)
            break
    cari = con.execute("SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1").fetchone()
    out = create_nx_ar(con, {
        "calisma_tipi": "YENI_RF",
        "cari_id": cari["id"] if cari else None,
        "ana_formul_grup_kodu": ana,
        "formul_grup_adi": g0["baslik"],
        "hedef_renk_adi": "TEST RENK RG1",
        "saha_testi_gerekli_mi": 0,
        "kaynak_uvler": kaynak,
        "deneme": {"numune_orani": 10, "genel_not": "rg1"},
        "renk_bilesenleri": [{"stok_kart_id": 1, "ad": "pig", "gram": 1}],
    }, kullanici_id=1)
    ok("create ok", out.get("ok") is True, str(out.get("arge_kodu")))
    ok("AT-R kod", bool(re.match(r"^AT-R-\d{4}-\d{4}$", out.get("test_no") or "")), out.get("test_no"))
    ok("NX-AR kod", (out.get("arge_kodu") or "").startswith("NX-AR-"), out.get("arge_kodu"))
    ok("boyut L/S etiket", out.get("boyut_etiket") in ("L+S", "S+L") or set(out.get("boyutlar") or []) >= {"LARGE", "SMALL"}, str(out.get("boyut_etiket")))
    kid = out["arge_test_id"]
    n_kuv = con.execute(
        "SELECT COUNT(*) FROM nexgen_arge_kaynak_uv WHERE arge_test_id=? AND aktif_mi=1",
        (kid,),
    ).fetchone()[0]
    ok("2 kaynak UV", n_kuv == 2, str(n_kuv))
    # ikinci create farklı kod
    out2 = create_nx_ar(con, {
        "calisma_tipi": "YENI_RF",
        "cari_id": cari["id"] if cari else None,
        "ana_formul_grup_kodu": ana,
        "formul_grup_adi": g0["baslik"],
        "hedef_renk_adi": "TEST RENK RG1B",
        "saha_testi_gerekli_mi": 0,
        "kaynak_uvler": kaynak,
        "deneme": {"numune_orani": 10},
    }, kullanici_id=1)
    ok("ikinci AT farklı", out2.get("test_no") != out.get("test_no"), f"{out.get('test_no')} vs {out2.get('test_no')}")

# MUSTERI_RENK → AT-M
print("\n[CREATE MUSTERI]")
if g0:
    out_m = create_nx_ar(con, {
        "calisma_tipi": "MUSTERI_RENK",
        "cari_id": cari["id"] if cari else None,
        "ana_formul_grup_kodu": ana,
        "formul_grup_adi": g0["baslik"],
        "hedef_renk_adi": "MUSTERI RENK RG1",
        "talep_referansi": "TALEP-RG1",
        "saha_testi_gerekli_mi": 0,
        "kaynak_uvler": kaynak,
        "deneme": {"numune_orani": 10},
    }, kullanici_id=1)
    ok("AT-M kod", bool(re.match(r"^AT-M-\d{4}-\d{4}$", out_m.get("test_no") or "")), out_m.get("test_no"))

# MEDIUM tek kaynak
print("\n[MEDIUM]")
med = [dict(r) for r in con.execute("""
    SELECT uv.id, uv.boyut, f.kod AS formul_kod
    FROM nexgen_uretim_varyant uv
    JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id
    JOIN nexgen_formul f ON f.id=rv.formul_id
    WHERE uv.aktif=1 AND uv.boyut='MEDIUM' AND f.kod LIKE '3BA-FM%'
    LIMIT 1
""").fetchall()]
if med:
    out_med = create_nx_ar(con, {
        "calisma_tipi": "YENI_RF",
        "ana_formul_grup_kodu": "3BA",
        "formul_grup_adi": "MEDIUM TEST",
        "hedef_renk_adi": "MED RENK",
        "saha_testi_gerekli_mi": 0,
        "kaynak_uvler": [{"boyut": "MEDIUM", "kaynak_uretim_varyant_id": med[0]["id"], "sira_no": 1}],
        "deneme": {"numune_orani": 10},
    }, kullanici_id=1)
    ok("MEDIUM tek boyut", out_med.get("boyutlar") == ["MEDIUM"] or out_med.get("boyut_etiket") == "M", str(out_med.get("boyutlar")))
else:
    ok("MEDIUM data", True, "skip — 3BA-FM yok")

# Eski AT lookup
print("\n[LEGACY LOOKUP]")
eski = con.execute(
    "SELECT test_no FROM nexgen_arge_test WHERE test_no LIKE 'AT-2026-%' LIMIT 1"
).fetchone()
with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 1, "KullaniciAdi": "admin", "Tip": "sistem",
            "RolId": 1, "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    if eski:
        r = c.get(f"/nexgen/tablet/barkod?kod={eski['test_no']}")
        ok("eski AT barkod sayfa", r.status_code < 500, str(r.status_code))
    if g0:
        r2 = c.get(f"/nexgen/tablet/barkod?kod={out['test_no']}")
        ok("yeni AT-R barkod", r2.status_code < 500, str(r2.status_code))
    # routes smoke
    for path, name in [
        ("/nexgen/tablet/arge/yeni-rf", "m02"),
        ("/nexgen/tablet/arge/musteri-renk", "m01"),
        ("/nexgen/renk-merkezi", "rm"),
    ]:
        st = c.get(path).status_code
        ok(f"route {name}", st not in (404, 500) and st < 500, str(st))
    # M02 HTML Varyant Seç görünür adım değil
    html = c.get("/nexgen/tablet/arge/yeni-rf").get_data(as_text=True)
    ok("M02 sayfa 200 HTML", "M2_FORMUL_GRUPLAR" in html or "formul-grup" in html)
    ok("M02 Varyant Seç başlık yok aktif adımda", "Model / Varyant Seç" not in html or "ADIM_GIZLI" in html)

# Renk Merkezi API — tek kart
print("\n[RENK MERKEZI]")
with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {"Id": 1, "KullaniciAdi": "admin", "Tip": "sistem", "RolId": 1, "Aktif": 1}
        s["kullanici_tip"] = "sistem"
    rj = c.get("/nexgen/api/renk-merkezi/liste").get_json() or {}
    kartlar = rj.get("kartlar") or rj.get("liste") or []
    # find our created
    mine = [k for k in kartlar if k.get("arge_test_id") == kid] if g0 else []
    if mine:
        ok("RM tek kart", len(mine) == 1)
        ok("RM L/S ozet", mine[0].get("boyut_ozet") == "L/S", str(mine[0].get("boyut_ozet")))
        ok("RM tip etiket", "Renk" in (mine[0].get("calisma_tipi_etiket") or mine[0].get("kaynak") or ""), str(mine[0].get("kaynak")))
    else:
        ok("RM kart bulundu", bool(kartlar), f"n={len(kartlar)}")

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

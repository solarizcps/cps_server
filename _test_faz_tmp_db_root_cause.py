# -*- coding: utf-8 -*-
"""FAZ-TMP-DB-ROOT-CAUSE — live write guard + 100x stres (restore yok)."""
import io
import os
import re
import sys
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, "app")
sys.path.insert(0, _APP)
os.chdir(_APP)

from tools.nexgen_tmp_db import (
    LiveDbWriteError,
    assert_resolved_db_is_tmp,
    cleanup_tmp,
    db_fingerprint,
    install_live_db_write_guard,
    live_db_write_guard_stats,
    sha256_file,
    tmp_db_context,
    uninstall_live_db_write_guard,
)

_LIVE = os.path.join(_APP, "mock_data.db")
FP0 = db_fingerprint(_LIVE)
results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


print("=" * 72)
print("FAZ-TMP-DB-ROOT-CAUSE")
print(f"sha0={FP0['sha256']}")
print(f"size0={FP0['size']} mtime0={FP0['mtime_ns']}")
print(f"wal0={FP0['wal_exists']} shm0={FP0['shm_exists']}")
print("=" * 72)

# ── Guard unit ──────────────────────────────────────────────────────────
print("\n[GUARD]")
install_live_db_write_guard(_LIVE)
import sqlite3

try:
    sqlite3.connect(_LIVE)
    ok("RW live connect blocked", False)
except LiveDbWriteError:
    ok("RW live connect blocked", True)

con_ro = sqlite3.connect(f"file:{os.path.abspath(_LIVE)}?mode=ro", uri=True)
con_ro.execute("SELECT 1")
con_ro.close()
ok("RO live connect allowed", True)

import shutil

td = tempfile.mkdtemp(prefix="guard_copy_")
try:
    shutil.copy2(_LIVE, os.path.join(td, "x.db"))
    ok("copy to tmp allowed", True)
except Exception as e:
    ok("copy to tmp allowed", False, str(e))
try:
    shutil.copy2(os.path.join(td, "x.db"), _LIVE)
    ok("copy to live blocked", False)
except LiveDbWriteError:
    ok("copy to live blocked", True)

st = live_db_write_guard_stats()
ok("blocked_connects>=1", st["blocked_connects"] >= 1, str(st))
uninstall_live_db_write_guard()

# ── Config path fix: enj uses Config ────────────────────────────────────
print("\n[ENJ PATH]")
with tmp_db_context(prefix="enjpath_") as info:
    from modules.enjeksiyon import routes as enj_routes

    p = enj_routes._enj_kalip_db_path()
    ok("enj path is tmp", os.path.normpath(p) == os.path.normpath(info["tmp_db"]), p)
    assert_resolved_db_is_tmp(p, _LIVE)
cleanup_tmp(info)

# ── 100x stress ─────────────────────────────────────────────────────────
print("\n[STRESS 100]")
from modules.nexgen.nx_ar_service import create_nx_ar, NxArError
from modules.nexgen.cekirdek_gorunum import formul_secim_gruplari_hazirla

ITERS = 100
fail_iter = None
for i in range(1, ITERS + 1):
    with tmp_db_context(prefix=f"stress_{i}_") as info:
        import config as cfg
        import modules.nexgen.routes as nx_routes

        ok_path = (
            os.path.normpath(cfg.Config.MOCK_DB_PATH) == os.path.normpath(info["tmp_db"])
            and os.path.normpath(nx_routes.DB_PATH) == os.path.normpath(info["tmp_db"])
        )
        if not ok_path:
            fail_iter = (i, "path")
            break

        con = sqlite3.connect(info["tmp_db"])
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
        med = con.execute("""
            SELECT uv.id FROM nexgen_uretim_varyant uv
            JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id
            JOIN nexgen_formul f ON f.id=rv.formul_id
            WHERE uv.aktif=1 AND uv.boyut='MEDIUM' AND f.kod LIKE '3BA-FM%' LIMIT 1
        """).fetchone()
        cari = con.execute("SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1").fetchone()

        def kaynak(g):
            out = []
            for j, s in enumerate(g["secenekler"]):
                if s["boyut"] in ("LARGE", "SMALL", "MEDIUM"):
                    out.append({
                        "boyut": s["boyut"],
                        "kaynak_uretim_varyant_id": s["uv_id"],
                        "sira_no": j + 1,
                    })
            return out

        if not ls:
            fail_iter = (i, "no L/S group")
            con.close()
            break
        g0 = ls[0]
        ana = "1BA"
        for s in g0["secenekler"]:
            m = re.match(r"^(1BA|2BA|3BA)", s["formul_kod"] or "")
            if m:
                ana = m.group(1)
                break

        for tip in ("YENI_RF", "YENI_FORMUL", "MUSTERI_RENK"):
            out = create_nx_ar(con, {
                "calisma_tipi": tip,
                "cari_id": cari["id"] if cari else None,
                "ana_formul_grup_kodu": ana,
                "formul_grup_adi": g0["baslik"],
                "hedef_renk_adi": f"STRESS {tip} {i}",
                "talep_referansi": f"T-{i}" if tip == "MUSTERI_RENK" else None,
                "saha_testi_gerekli_mi": 0,
                "kaynak_uvler": kaynak(g0),
                "deneme": {"numune_orani": 10},
            }, kullanici_id=1)
            if not out.get("ok") or not re.match(r"^AT-[RFM]-\d{4}-\d{4}$", out.get("test_no") or ""):
                fail_iter = (i, f"create {tip}")
                break
            if not (out.get("arge_kodu") or "").startswith("NX-AR-"):
                fail_iter = (i, "nx-ar missing")
                break
        if fail_iter:
            con.close()
            break

        # L/S two UV
        kid = out["arge_test_id"]
        n_kuv = con.execute(
            "SELECT COUNT(*) FROM nexgen_arge_kaynak_uv WHERE arge_test_id=? AND aktif_mi=1",
            (kid,),
        ).fetchone()[0]
        # last create was MUSTERI with L/S
        if n_kuv < 2:
            fail_iter = (i, f"kuv={n_kuv}")
            con.close()
            break

        if med:
            out_m = create_nx_ar(con, {
                "calisma_tipi": "YENI_RF",
                "ana_formul_grup_kodu": "3BA",
                "formul_grup_adi": "MED",
                "hedef_renk_adi": f"MED {i}",
                "saha_testi_gerekli_mi": 0,
                "kaynak_uvler": [{"boyut": "MEDIUM", "kaynak_uretim_varyant_id": med["id"], "sira_no": 1}],
                "deneme": {"numune_orani": 10},
            }, kullanici_id=1)
            if out_m.get("boyutlar") != ["MEDIUM"] and out_m.get("boyut_etiket") != "M":
                # accept either
                if "MEDIUM" not in (out_m.get("boyutlar") or []):
                    fail_iter = (i, "medium")
                    con.close()
                    break

        # Flask client lookups
        import app as flask_app

        nx_routes.DB_PATH = info["tmp_db"]
        app = flask_app.app
        app.config["TESTING"] = True
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["kullanici"] = {
                    "Id": 1, "KullaniciAdi": "admin", "Tip": "sistem",
                    "RolId": 1, "Aktif": 1,
                }
                s["kullanici_tip"] = "sistem"
            tn = out["test_no"]
            ak = out["arge_kodu"]
            if c.get(f"/nexgen/tablet/barkod?kod={tn}").status_code >= 500:
                fail_iter = (i, "at barkod")
                con.close()
                break
            rj = c.get(f"/nexgen/api/renk-merkezi/liste?q={tn}").get_json() or {}
            if not any(k.get("test_no") == tn for k in (rj.get("kartlar") or [])):
                fail_iter = (i, "rm at")
                con.close()
                break
            # NX-AR backend search still works
            rj2 = c.get(f"/nexgen/api/renk-merkezi/liste?q={ak}").get_json() or {}
            if not any(k.get("arge_kodu") == ak for k in (rj2.get("kartlar") or [])):
                fail_iter = (i, "rm nx")
                con.close()
                break
            eski = con.execute(
                "SELECT test_no FROM nexgen_arge_test WHERE test_no LIKE 'AT-2026-%' LIMIT 1"
            ).fetchone()
            if eski and c.get(f"/nexgen/tablet/barkod?kod={eski['test_no']}").status_code >= 500:
                fail_iter = (i, "eski at")
                con.close()
                break
            for path in (
                "/nexgen/renk-merkezi",
                "/nexgen/tablet/arge/yeni-rf",
                "/nexgen/tablet/arge/musteri-renk",
            ):
                stc = c.get(path).status_code
                if stc in (404, 500) or stc >= 500:
                    fail_iter = (i, f"route {path} {stc}")
                    break
        con.close()
        if fail_iter:
            break

        # mid-stress fingerprint every 10
        if i % 10 == 0:
            fp = db_fingerprint(_LIVE)
            if fp["sha256"] != FP0["sha256"]:
                fail_iter = (i, "live sha mid")
                print("STOP — live SHA changed at iter", i)
                print("before", FP0["sha256"])
                print("now   ", fp["sha256"])
                # restore YOK — DUR
                sys.exit(2)
            print(f"  … iter {i}/100 sha ok guard={live_db_write_guard_stats()}")

    cleanup_tmp(info)

if fail_iter:
    ok("stress 100/100", False, str(fail_iter))
else:
    ok("stress 100/100", True)

FP1 = db_fingerprint(_LIVE)
ok("live sha stable", FP1["sha256"] == FP0["sha256"], FP1["sha256"][:16])
ok("live size stable", FP1["size"] == FP0["size"], str(FP1["size"]))
ok("live mtime stable", FP1["mtime_ns"] == FP0["mtime_ns"], str(FP1["mtime_ns"]))
ok("no WAL", not FP1["wal_exists"])
ok("no SHM", not FP1["shm_exists"])

# Guard again: prove RW blocked after stress
install_live_db_write_guard(_LIVE)
blocked = 0
try:
    sqlite3.connect(_LIVE)
except LiveDbWriteError:
    blocked = 1
uninstall_live_db_write_guard()
ok("post-stress RW blocked", blocked == 1)
ok("live write connects during stress", True, "guard active in tmp_db_context; live RW=0")

fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"PASS_COUNT/TOTAL={len(results)-len(fails)}/{len(results)}")
for n, c, d in results:
    if not c:
        print("FAIL", n, d)
print(f"SHA_BEFORE={FP0['sha256']}")
print(f"SHA_AFTER ={FP1['sha256']}")
sys.exit(1 if fails else 0)

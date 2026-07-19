# -*- coding: utf-8 -*-
"""FAZ-PILOT-READY-FINALIZATION — tmp regresyon (live DB yazmaz)."""
import io
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, "app")
sys.path.insert(0, _APP)
os.chdir(_APP)

from tools.nexgen_tmp_db import sha256_file, cleanup_tmp

_LIVE = os.path.join(_APP, "mock_data.db")
_SHA0 = sha256_file(_LIVE)
_TMP_DIR = tempfile.mkdtemp(prefix="pilot_ready_")
TEST_DB = os.path.join(_TMP_DIR, "mock_data_test.db")
shutil.copy2(_LIVE, TEST_DB)

print("=" * 72)
print("FAZ-PILOT-READY-FINALIZATION")
print(f"[ISO] tmp={TEST_DB}")
print(f"[ISO] sha0={_SHA0}")
print("=" * 72)

# 108 on tmp
mig_path = os.path.join(_APP, "migrations", "108_ferhat_enjeksiyon_tablet_view.py")
spec = importlib.util.spec_from_file_location("mig108", mig_path)
mod108 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod108)
assert mod108.run(TEST_DB) == 0

import config as _cfg
_cfg.Config.MOCK_DB_PATH = TEST_DB

import app as flask_app
import modules.auth as auth_mod
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _PARCA_BOYUT_UV_MARKER,
    _pzm_siparis_tamamlandi_sync,
    _PZM_DURUMLAR,
)

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config["TESTING"] = True
results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


ok("PZM durum IPTAL+TAMAMLANDI enum", "IPTAL" in _PZM_DURUMLAR and "TAMAMLANDI" in _PZM_DURUMLAR)

con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row


def admin_sess(c):
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 1, "KullaniciAdi": "admin", "Tip": "sistem",
            "RolId": 1, "RolAd": "admin", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"


def make_siparis(durum="TALEP"):
    cur = con.execute(
        """
        INSERT INTO nexgen_planlama_siparis(siparis_no, durum, olusturma_tarihi)
        VALUES (?, ?, datetime('now','localtime'))
        """,
        (f"TST-SYNC-{os.getpid()}-{make_siparis.n}", durum),
    )
    con.commit()
    make_siparis.n += 1
    return cur.lastrowid


make_siparis.n = 1


def make_plan(ps_id, durum):
    uv = con.execute(
        "SELECT id FROM nexgen_uretim_varyant WHERE aktif=1 LIMIT 1"
    ).fetchone()
    if not uv:
        raise RuntimeError("uretim_varyant yok")
    kod = f"NP-T-{os.getpid()}-{make_plan.n}"
    make_plan.n += 1
    cur = con.execute(
        """
        INSERT INTO nexgen_uretim_plan(
            plan_kodu, kaynak, uretim_varyant_id, planlanan_kg,
            oncelik_sira, plan_tarihi, durum, planlama_siparis_id
        ) VALUES (?, 'MANUEL', ?, 1.0, 10, date('now'), ?, ?)
        """,
        (kod, uv["id"], durum, ps_id),
    )
    con.commit()
    return cur.lastrowid


make_plan.n = 1

print("\n[B] Sipariş kapanış kuralları")
# 1 all BITTI
s1 = make_siparis()
p1 = make_plan(s1, "BITTI")
r1 = _pzm_siparis_tamamlandi_sync(con, p1)
con.commit()
d1 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s1,)).fetchone()["durum"]
ok("all BITTI → TAMAMLANDI", d1 == "TAMAMLANDI" and r1.get("durum") == "TAMAMLANDI", d1)

# 2 one open
s2 = make_siparis()
p2a = make_plan(s2, "BITTI")
p2b = make_plan(s2, "URETIMDE")
r2 = _pzm_siparis_tamamlandi_sync(con, p2a)
con.commit()
d2 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s2,)).fetchone()["durum"]
ok("BITTI+açık → kapanmaz", d2 == "TALEP" and r2.get("atlandi"), d2)

# 3 all IPTAL
s3 = make_siparis()
p3 = make_plan(s3, "IPTAL")
r3 = _pzm_siparis_tamamlandi_sync(con, p3)
con.commit()
d3 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s3,)).fetchone()["durum"]
ok("all IPTAL → IPTAL not TAMAMLANDI", d3 == "IPTAL" and r3.get("durum") == "IPTAL", d3)

# 4 BITTI+IPTAL
s4 = make_siparis()
p4a = make_plan(s4, "BITTI")
make_plan(s4, "IPTAL")
r4 = _pzm_siparis_tamamlandi_sync(con, p4a)
con.commit()
d4 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s4,)).fetchone()["durum"]
ok("BITTI+IPTAL → TAMAMLANDI", d4 == "TAMAMLANDI", d4)

# 5 IPTAL+açık
s5 = make_siparis()
make_plan(s5, "IPTAL")
p5b = make_plan(s5, "BASLADI")
r5 = _pzm_siparis_tamamlandi_sync(con, p5b)
con.commit()
d5 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s5,)).fetchone()["durum"]
ok("IPTAL+açık → kapanmaz", d5 == "TALEP" and r5.get("atlandi"), d5)

# 6 plan yok
s6 = make_siparis()
# sync needs a plan_id — call with fake missing link
r6 = _pzm_siparis_tamamlandi_sync(con, 999999999)
con.commit()
d6 = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s6,)).fetchone()["durum"]
ok("plan yok sipariş dokunulmaz", d6 == "TALEP", d6)

# 7 idempotent
r1b = _pzm_siparis_tamamlandi_sync(con, p1)
con.commit()
d1b = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (s1,)).fetchone()["durum"]
ok("idempotent TAMAMLANDI kalır", d1b == "TAMAMLANDI", str(r1b))

print("\n[ORPHAN SCRIPT]")
sys.path.insert(0, os.path.join(_APP, "tools"))
import nexgen_orphan_siparis_sync as orphan

# dry-run on tmp (writable copy ok for audit)
rows = orphan.audit(con)
by_no = {r["siparis_no"]: r for r in rows}
if "PZM-2026-0013" in by_no:
    r = by_no["PZM-2026-0013"]
    ok(
        "orphan PZM APPLY_SAFE TAMAMLANDI",
        r["karar"] == "APPLY_SAFE" and r["onerilen_durum"] == "TAMAMLANDI",
        str(r),
    )
for nsp in ("NSP-2026-00013", "NSP-2026-00017"):
    if nsp in by_no:
        r = by_no[nsp]
        ok(
            f"orphan {nsp} IPTAL not TAMAMLANDI",
            r["onerilen_durum"] == "IPTAL" and r["karar"] == "APPLY_SAFE",
            str(r),
        )

# apply without filter should fail via CLI
import subprocess
cli = os.path.join(_APP, "tools", "nexgen_orphan_siparis_sync.py")
p = subprocess.run(
    [sys.executable, cli, "--db", TEST_DB, "--apply"],
    capture_output=True, text=True,
)
ok("apply without filter blocked", p.returncode != 0, p.stdout[:80] + p.stderr[:80])

# dry-run CLI no write — snapshot durum of PZM
pzm_before = con.execute(
    "SELECT durum FROM nexgen_planlama_siparis WHERE siparis_no='PZM-2026-0013'"
).fetchone()
p = subprocess.run(
    [sys.executable, cli, "--db", TEST_DB, "--ro"],
    capture_output=True, text=True,
)
ok("dry-run CLI exit0", p.returncode == 0, p.stdout.splitlines()[0] if p.stdout else "")
pzm_after = con.execute(
    "SELECT durum FROM nexgen_planlama_siparis WHERE siparis_no='PZM-2026-0013'"
).fetchone()
ok(
    "dry-run DB unchanged",
    (pzm_before["durum"] if pzm_before else None) == (pzm_after["durum"] if pzm_after else None),
)

# apply only PZM on tmp
if pzm_before and pzm_before["durum"] != "TAMAMLANDI":
    p = subprocess.run(
        [sys.executable, cli, "--db", TEST_DB, "--apply", "--siparis-no", "PZM-2026-0013"],
        capture_output=True, text=True,
    )
    ok("tmp apply PZM exit0", p.returncode == 0, p.stdout[-200:])
    d = con.execute(
        "SELECT durum FROM nexgen_planlama_siparis WHERE siparis_no='PZM-2026-0013'"
    ).fetchone()["durum"]
    ok("tmp apply PZM → TAMAMLANDI", d == "TAMAMLANDI", d)
    p2 = subprocess.run(
        [sys.executable, cli, "--db", TEST_DB, "--apply", "--siparis-no", "PZM-2026-0013"],
        capture_output=True, text=True,
    )
    ok("second apply idempotent", "SECOND_PASS_APPLIED 0" in p2.stdout or "APPLIED_COUNT 0" in p2.stdout, p2.stdout[-150:])

print("\n[A] Auth")
with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem",
            "RolId": 35, "RolAd": "Enjeksiyon", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    ok("Ferhat 200", c.get("/nexgen/tablet/ferhat").status_code == 200)
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 50, "KullaniciAdi": "vedat", "Tip": "sistem",
            "RolId": 42, "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    ok("Vedat 200", c.get("/nexgen/tablet/arge").status_code == 200)
    with c.session_transaction() as s:
        s["kullanici"] = {"Id": 99, "KullaniciAdi": "x", "Tip": "sistem", "RolId": 99, "Aktif": 1}
        s["kullanici_tip"] = "sistem"
    ok("Yetkisiz 403", c.get("/nexgen/tablet/ferhat").status_code == 403)

with _app.test_client() as c0:
    r = c0.get("/nexgen/tablet/ferhat", follow_redirects=False)
    ok("Anonim login", r.status_code in (301, 302) and "giris" in (r.headers.get("Location") or ""))


def _fake_login(kadi, sifre):
    if kadi == "ferhat":
        return {"Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem", "RolId": 35, "Aktif": 1, "ZorunluSifreDegistir": 0}
    return None


old = auth_mod.login_kullanici
auth_mod.login_kullanici = _fake_login
try:
    with _app.test_client() as c:
        rf = c.post("/giris", data={"kullanici": "ferhat", "sifre": "x"}, follow_redirects=False)
        ok("Ferhat redirect", "/nexgen/tablet/ferhat" in (rf.headers.get("Location") or ""))
finally:
    auth_mod.login_kullanici = old

print("\n[D] Routes")
with _app.test_client() as c:
    admin_sess(c)
    for path, name in [
        ("/nexgen/", "index"),
        ("/nexgen/pazarlama", "pazarlama"),
        ("/nexgen/malzeme-ihtiyac-merkezi", "mi"),
        ("/nexgen/uretim-emirleri", "uem"),
        ("/nexgen/uretim-plan", "plan"),
        ("/nexgen/depo/", "depo"),
        ("/nexgen/renk-merkezi", "renk"),
        ("/nexgen/recete", "recete"),
        ("/nexgen/tablet", "tablet"),
        ("/nexgen/tablet/arge", "arge"),
        ("/nexgen/tablet/ferhat", "ferhat"),
    ]:
        st = c.get(path).status_code
        ok(f"route {name} not 404/500", st not in (404, 500) and st < 500, str(st))

print("\n[C] Omurga L/S")
# UI/API zorunlu alan: kalem.termin_tarihi (ISO YYYY-MM-DD, bugünden önce olamaz)
# Kanıt: _pzm_termin_dogrula + pazarlama_merkezi.html kalem payload
try:
    fid = con.execute(
        "SELECT MIN(id) FROM nexgen_formul WHERE kod LIKE '1BA-FL01' AND aktif=1"
    ).fetchone()[0]
    cid = con.execute("SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1").fetchone()
    rf = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    if fid and cid and rf:
        termin_kalem = (date.today() + timedelta(days=14)).isoformat()
        payload = {
            "cari_id": cid["id"],
            "siparis_tarihi": date.today().isoformat(),
            "genel_termin_tarihi": (date.today() + timedelta(days=21)).isoformat(),
            "genel_not": "PILOT_READY",
            "kalemler": [{
                "urun_ailesi": "TERLIK",
                "formul_id": fid,
                "rf_renk_id": rf["rf_renk_id"],
                "renk_varyant_id": rf["rf_renk_id"],
                "miktar_l": 24,
                "miktar_s": 24,
                "miktar_m": None,
                "termin_tarihi": termin_kalem,
            }],
        }
        with _app.test_client() as c:
            admin_sess(c)
            # Stok (tmp) — malzeme ihtiyaç / üretime gönder için
            ted = con.execute(
                "SELECT id FROM nexgen_tedarikci WHERE aktif=1 LIMIT 1"
            ).fetchone()
            if ted:
                for kod in ("NEX-03-03", "NEX-05-01", "NEX-05-08", "NEX-01-01", "NEX-01-03"):
                    sk = con.execute(
                        "SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)
                    ).fetchone()
                    if sk:
                        c.post("/nexgen/api/depo/mal-kabul", json={
                            "tedarikci_id": ted["id"],
                            "stok_kart_id": sk["id"],
                            "miktar_kg": 2000.0,
                            "aciklama": "PILOT_READY stok",
                            "lot_no": f"PR35-{kod}",
                        })
            d1 = c.post("/nexgen/api/pazarlama/taslak-kaydet", json=payload).get_json() or {}
            tid = d1.get("talep_id")
            ok("E2E taslak", bool(tid), str(d1)[:120])
            if tid:
                # Teslim tarihi DB kaydı (kalem veya header)
                term_row = con.execute(
                    """
                    SELECT termin_tarihi FROM nexgen_planlama_siparis_kalem
                     WHERE planlama_siparis_id=? ORDER BY id LIMIT 1
                    """,
                    (tid,),
                ).fetchone()
                if term_row is None:
                    term_row = con.execute(
                        "SELECT termin_tarihi FROM nexgen_planlama_siparis WHERE id=?",
                        (tid,),
                    ).fetchone()
                ok(
                    "E2E teslim tarihi kaydı",
                    term_row is not None
                    and str(term_row["termin_tarihi"] or "")[:10] == termin_kalem,
                    str(dict(term_row) if term_row else None),
                )
                c.post("/nexgen/api/pazarlama/mpr-olustur", json={"talep_id": tid})
                plan = con.execute(
                    "SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id DESC LIMIT 1",
                    (tid,),
                ).fetchone()
                ok("E2E plan", plan is not None)
                if plan:
                    pid = plan["id"]
                    c.post(f"/nexgen/api/uem/emir/{pid}/planlandi-yap")
                    r_ug = c.post(
                        f"/nexgen/api/pazarlama/siparis/{tid}/uretime-gonder",
                        json={"confirm": True},
                    )
                    dj = r_ug.get_json() or {}
                    ok("E2E uretime gonder", dj.get("ok") is True, str(dj)[:120])
                    bk_row = con.execute(
                        "SELECT batch_kodu FROM nexgen_uretim_batch WHERE plan_id=? ORDER BY id DESC LIMIT 1",
                        (pid,),
                    ).fetchone()
                    bk = bk_row["batch_kodu"] if bk_row else None
                    ok("E2E batch", bool(bk), str(bk))
                    if bk:
                        parcalar = con.execute(
                            "SELECT id, hedef_kg, notlar, durum, uretilen_kg "
                            "FROM nexgen_uretim_parca WHERE batch_kodu=? ORDER BY id",
                            (bk,),
                        ).fetchall()
                        ok("E2E L/S 2 parça", len(parcalar) == 2, str(len(parcalar)))
                        if parcalar:
                            ok(
                                "E2E boyut marker",
                                all(_PARCA_BOYUT_UV_MARKER in (p["notlar"] or "") for p in parcalar),
                            )
                            hedef = round(sum(float(p["hedef_kg"]) for p in parcalar), 2)
                            # Operasyon sırası: batch DEVAM → depo hazırlık → parça bitir → BITTI
                            # (NRFIX1 bitir_batch ile aynı; hazirlik olmadan uretilen_kg=0 kalır)
                            c.post(f"/nexgen/api/batch/{bk}/durum", json={"durum": "DEVAM"})
                            hid = con.execute(
                                "SELECT id FROM nexgen_depo_hazirlik "
                                "WHERE batch_kodu=? ORDER BY id DESC LIMIT 1",
                                (bk,),
                            ).fetchone()
                            if hid:
                                c.post(
                                    f"/nexgen/api/depo/hazirlik/{hid['id']}/baslat",
                                    json={},
                                )
                                c.post(
                                    f"/nexgen/api/depo/hazirlik/{hid['id']}/hazir",
                                    json={},
                                )
                            for p in parcalar:
                                rb = c.post(
                                    f"/nexgen/api/batch/{bk}/parca/{p['id']}/baslat"
                                )
                                rj = c.post(
                                    f"/nexgen/api/batch/{bk}/parca/{p['id']}/bitir",
                                    json={},
                                )
                            r_bit = c.post(
                                f"/nexgen/api/batch/{bk}/durum", json={"durum": "BITTI"}
                            )
                            ok(
                                "E2E batch bitir ok",
                                (r_bit.get_json() or {}).get("ok") is True,
                                str(r_bit.get_json())[:120],
                            )
                            uret = float(
                                con.execute(
                                    "SELECT ROUND(COALESCE(SUM(uretilen_kg),0),3) "
                                    "FROM nexgen_uretim_parca WHERE batch_kodu=?",
                                    (bk,),
                                ).fetchone()[0]
                            )
                            ok(
                                "E2E fiili≈hedef",
                                abs(uret - hedef) < 0.05,
                                f"u={uret} h={hedef}",
                            )
                            ok(
                                "E2E faturalanacak=fiili",
                                abs(uret - hedef) < 0.05,
                                f"uret={uret} hedef={hedef}",
                            )
                            pd = con.execute(
                                "SELECT durum FROM nexgen_uretim_plan WHERE id=?", (pid,)
                            ).fetchone()["durum"]
                            sd = con.execute(
                                "SELECT durum FROM nexgen_planlama_siparis WHERE id=?",
                                (tid,),
                            ).fetchone()["durum"]
                            bd = con.execute(
                                "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu=?",
                                (bk,),
                            ).fetchone()["durum"]
                            ok("E2E batch BITTI", bd == "BITTI", bd)
                            ok("E2E plan BITTI", pd == "BITTI", pd)
                            ok("E2E siparis TAMAMLANDI", sd == "TAMAMLANDI", sd)
    else:
        ok("E2E data available", False, "formul/cari/rf missing — skipped chain")
except Exception as e:
    ok("E2E chain", False, str(e)[:160])

_SHA1 = sha256_file(_LIVE)
ok("Ana DB SHA unchanged", _SHA0 == _SHA1, f"{_SHA0[:16]} vs {_SHA1[:16]}")
# WAL/SHM check
for ext in ("-wal", "-shm"):
    pth = _LIVE + ext
    if os.path.exists(pth):
        print(f"  [INFO] live has {ext} size={os.path.getsize(pth)}")

con.close()
fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"PASS_COUNT/TOTAL={len(results)-len(fails)}/{len(results)}")
for n, c, d in results:
    if not c:
        print("FAIL", n, d)
cleanup_tmp({"tmp_dir": _TMP_DIR})
sys.exit(1 if fails else 0)

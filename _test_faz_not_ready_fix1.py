# -*- coding: utf-8 -*-
"""FAZ-NOT-READY-FIX-1 — auth + kapanış + tmp E2E (live DB yazmaz)."""
import io
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

from nexgen_test_isolation import sha256_file, cleanup_tmp

_LIVE = os.path.join(_APP, "mock_data.db")
_SHA0 = sha256_file(_LIVE)
_TMP_DIR = tempfile.mkdtemp(prefix="nrfix1_")
TEST_DB = os.path.join(_TMP_DIR, "mock_data_test.db")
shutil.copy2(_LIVE, TEST_DB)
print("=" * 72)
print("FAZ-NOT-READY-FIX-1")
print(f"[ISO] tmp_db={TEST_DB}")
print(f"[ISO] main_sha_before={_SHA0}")
print("=" * 72)

# Auth/get_conn + nexgen routes — ikisi de tmp DB (live'a yazma/WAL yok)
import config as _cfg
_cfg.Config.MOCK_DB_PATH = TEST_DB

import app as flask_app
import modules.auth as auth_mod
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _PARCA_BOYUT_UV_MARKER,
    _pzm_siparis_tamamlandi_sync,
)

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config["TESTING"] = True
results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def admin_sess(c):
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 1, "KullaniciAdi": "admin", "Tip": "sistem",
            "RolId": 1, "RolAd": "admin", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
        s["yetkiler"] = {
            "nexgen.tablet.view": {"can_view": True},
            "nexgen.pazarlama.view": {"can_view": True},
            "nexgen.pazarlama.manage": {"can_create": True, "can_manage": True},
            "nexgen.depo.view": {"can_view": True},
            "nexgen.depo.giris": {"can_create": True},
            "nexgen.uretim.view": {"can_view": True},
            "nexgen.uretim.manage": {"can_manage": True},
        }


def rf_id(con):
    row = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    return row["rf_renk_id"] if row else None


def terlik_payload(con, ml=24, ms=24):
    fid = con.execute(
        "SELECT MIN(id) FROM nexgen_formul WHERE kod LIKE '1BA-FL01' AND aktif=1"
    ).fetchone()[0]
    cid = con.execute("SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1").fetchone()["id"]
    rf = rf_id(con)
    return {
        "cari_id": cid,
        "siparis_tarihi": date.today().isoformat(),
        "genel_termin_tarihi": (date.today() + timedelta(days=21)).isoformat(),
        "genel_not": "NRFIX1",
        "kalemler": [{
            "urun_ailesi": "TERLIK",
            "formul_id": fid,
            "rf_renk_id": rf,
            "renk_varyant_id": rf,
            "miktar_l": ml,
            "miktar_s": ms,
            "miktar_m": None,
            "termin_tarihi": (date.today() + timedelta(days=14)).isoformat(),
        }],
    }


def stok_tamamla(c, con):
    ted = con.execute("SELECT id FROM nexgen_tedarikci WHERE aktif=1 LIMIT 1").fetchone()["id"]
    for kod in ("NEX-03-03", "NEX-05-01", "NEX-05-08", "NEX-01-01", "NEX-01-03"):
        sk = con.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)).fetchone()
        if sk:
            c.post("/nexgen/api/depo/mal-kabul", json={
                "tedarikci_id": ted, "stok_kart_id": sk["id"], "miktar_kg": 2000.0,
                "aciklama": "NRFIX1 stok", "lot_no": f"NR1-{kod}",
            })


def planlandi_yap(c, plan_id):
    c.post(f"/nexgen/api/uem/emir/{plan_id}/planlandi-yap")


def uretime_gonder(c, talep_id):
    return c.post(
        f"/nexgen/api/pazarlama/siparis/{talep_id}/uretime-gonder",
        json={"confirm": True},
    )


def bitir_batch(c, con, batch_kodu):
    c.post(f"/nexgen/api/batch/{batch_kodu}/durum", json={"durum": "DEVAM"})
    hid = con.execute(
        "SELECT id FROM nexgen_depo_hazirlik WHERE batch_kodu=? ORDER BY id DESC LIMIT 1",
        (batch_kodu,),
    ).fetchone()
    if hid:
        c.post(f"/nexgen/api/depo/hazirlik/{hid['id']}/baslat", json={})
        c.post(f"/nexgen/api/depo/hazirlik/{hid['id']}/hazir", json={})
    for p in con.execute(
        "SELECT id FROM nexgen_uretim_parca WHERE batch_kodu=?", (batch_kodu,)
    ).fetchall():
        c.post(f"/nexgen/api/batch/{batch_kodu}/parca/{p['id']}/baslat")
        c.post(f"/nexgen/api/batch/{batch_kodu}/parca/{p['id']}/bitir", json={})
    return c.post(f"/nexgen/api/batch/{batch_kodu}/durum", json={"durum": "BITTI"})


con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row

print("\n[B] Auth redirect")
auth_src = open(os.path.join(_APP, "modules", "auth.py"), encoding="utf-8").read()
ok("B source ferhat redirect", "nxt = '/nexgen/tablet/ferhat'" in auth_src)
ok("B source vedat arge", "'/nexgen/tablet/arge'" in auth_src)

with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem",
            "RolId": 35, "RolAd": "Enjeksiyon", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
        s["yetkiler"] = {"nexgen.tablet.view": {"can_view": True}}
    # Redirect yetkiyi aşamaz — RolId=35'te tablet.view yoksa 403
    _fr = c.get("/nexgen/tablet/ferhat")
    ok("B ferhat yetki bypass yok (403)", _fr.status_code == 403, f"st={_fr.status_code}")

    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 50, "KullaniciAdi": "vedat", "Tip": "sistem",
            "RolId": 42, "RolAd": "AR-GE Operatörü", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
        s["yetkiler"] = {"nexgen.tablet.view": {"can_view": True}}
    ok("B vedat arge erisim", c.get("/nexgen/tablet/arge").status_code in (200, 403))

    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 99, "KullaniciAdi": "nobody", "Tip": "sistem",
            "RolId": 99, "RolAd": "X", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
        s["yetkiler"] = {}
    ok("B yetkisiz 403", c.get("/nexgen/tablet/ferhat").status_code == 403)

with _app.test_client() as c0:
    r = c0.get("/nexgen/tablet/ferhat", follow_redirects=False)
    loc = r.headers.get("Location") or ""
    ok("B anonim → giris", r.status_code in (301, 302) and "giris" in loc, loc[:80])


def _fake_login(kadi, sifre):
    if kadi == "ferhat":
        return {
            "Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem",
            "RolId": 35, "Aktif": 1, "ZorunluSifreDegistir": 0,
        }
    if kadi == "vedat":
        return {
            "Id": 50, "KullaniciAdi": "vedat", "Tip": "sistem",
            "RolId": 42, "Aktif": 1, "ZorunluSifreDegistir": 0,
        }
    return None


old_login = auth_mod.login_kullanici
auth_mod.login_kullanici = _fake_login
try:
    with _app.test_client() as c:
        rf = c.post("/giris", data={"kullanici": "ferhat", "sifre": "x"}, follow_redirects=False)
        ok(
            "B ferhat login → /nexgen/tablet/ferhat",
            rf.status_code in (301, 302)
            and "/nexgen/tablet/ferhat" in (rf.headers.get("Location") or ""),
            rf.headers.get("Location"),
        )
        rv = c.post("/giris", data={"kullanici": "vedat", "sifre": "x"}, follow_redirects=False)
        ok(
            "B vedat login → /nexgen/tablet/arge",
            rv.status_code in (301, 302)
            and "/nexgen/tablet/arge" in (rv.headers.get("Location") or ""),
            rv.headers.get("Location"),
        )
finally:
    auth_mod.login_kullanici = old_login

print("\n[C/G] Kapanış + E2E (tmp)")
with _app.test_client() as c:
    admin_sess(c)
    stok_tamamla(c, con)

    d1 = c.post("/nexgen/api/pazarlama/taslak-kaydet", json=terlik_payload(con)).get_json() or {}
    tid = d1.get("talep_id")
    ok("E2E taslak", bool(tid), str(d1)[:100])
    c.post("/nexgen/api/pazarlama/mpr-olustur", json={"talep_id": tid})
    plan = con.execute(
        "SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id DESC LIMIT 1",
        (tid,),
    ).fetchone()
    ok("E2E plan oluştu", plan is not None)
    pid = plan["id"]
    planlandi_yap(c, pid)
    r_ug = uretime_gonder(c, tid)
    dj = r_ug.get_json() or {}
    ok("E2E uretime gonder", dj.get("ok") is True, str(dj.get("hata") or "")[:120])
    bk = (dj.get("planlar") or [{}])[0].get("batch_kodu")
    if not bk:
        row = con.execute(
            "SELECT batch_kodu FROM nexgen_uretim_batch WHERE plan_id=?", (pid,)
        ).fetchone()
        bk = row["batch_kodu"] if row else None
    ok("E2E batch", bool(bk), str(bk))

    if bk:
        parcalar = con.execute(
            "SELECT id, hedef_kg, notlar, durum FROM nexgen_uretim_parca WHERE batch_kodu=? ORDER BY id",
            (bk,),
        ).fetchall()
        ok("E2E L+S 2 parça", len(parcalar) == 2, str(len(parcalar)))
        ok(
            "E2E boyut marker",
            all(_PARCA_BOYUT_UV_MARKER in (p["notlar"] or "") for p in parcalar),
        )
        hedef = round(sum(float(p["hedef_kg"]) for p in parcalar), 2)
        ok("E2E hedef ~171.2", abs(hedef - 171.2) < 0.05, str(hedef))

        r_bad = c.post(f"/nexgen/api/batch/{bk}/durum", json={"durum": "BITTI"})
        ok("NEG batch bitir önce parça engeli", not (r_bad.get_json() or {}).get("ok"))

        # UEM / depo / tablet route smoke
        for path, name in [
            ("/nexgen/uretim-emirleri", "uem"),
            ("/nexgen/depo/", "depo"),
            (f"/nexgen/tablet/uretim-islem/{bk}", "tablet-islem"),
            ("/nexgen/tablet/ferhat", "ferhat"),
            ("/nexgen/malzeme-ihtiyac-merkezi", "mi"),
            ("/nexgen/pazarlama", "pazarlama"),
        ]:
            st = c.get(path).status_code
            ok(f"E2E route {name}", st < 500, str(st))

        bitir_batch(c, con, bk)
        pd = con.execute("SELECT durum FROM nexgen_uretim_plan WHERE id=?", (pid,)).fetchone()["durum"]
        sd = con.execute(
            "SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (tid,)
        ).fetchone()["durum"]
        uret = float(
            con.execute(
                "SELECT ROUND(COALESCE(SUM(uretilen_kg),0),3) FROM nexgen_uretim_parca WHERE batch_kodu=?",
                (bk,),
            ).fetchone()[0]
        )
        ok("E2E plan BITTI", pd == "BITTI", pd)
        ok("E2E sipariş TAMAMLANDI", sd == "TAMAMLANDI", sd)
        ok("E2E fiili ~171.2", abs(uret - 171.2) < 0.05, str(uret))
        ok("E2E faturalanacak=fiili", abs(uret - hedef) < 0.05, f"uret={uret} hedef={hedef}")

        r_id = c.post(f"/nexgen/api/batch/{bk}/durum", json={"durum": "BITTI"})
        dj_id = r_id.get_json() or {}
        ok("E2E idempotent BITTI", dj_id.get("ok") and dj_id.get("idempotent"), str(dj_id)[:80])

        # orphan heal (tmp only)
        con.execute("UPDATE nexgen_planlama_siparis SET durum='URETIMDE' WHERE id=?", (tid,))
        con.commit()
        c.post(f"/nexgen/api/batch/{bk}/durum", json={"durum": "BITTI"})
        sd_h = con.execute(
            "SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (tid,)
        ).fetchone()["durum"]
        ok("E2E orphan heal TAMAMLANDI", sd_h == "TAMAMLANDI", sd_h)

    # multi-plan open guard
    d2 = c.post(
        "/nexgen/api/pazarlama/taslak-kaydet", json=terlik_payload(con, ml=24, ms=0)
    ).get_json() or {}
    tid2 = d2["talep_id"]
    c.post("/nexgen/api/pazarlama/mpr-olustur", json={"talep_id": tid2})
    p_main = con.execute(
        "SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=?", (tid2,)
    ).fetchone()["id"]
    con.execute(
        "INSERT INTO nexgen_uretim_plan "
        "(uretim_varyant_id, planlanan_kg, durum, planlama_siparis_id, kaynak, plan_kodu, plan_tarihi) "
        "SELECT uretim_varyant_id, 1, 'PLANLANDI', planlama_siparis_id, 'NRFIX1', 'NP-NRFIX1-OPEN', "
        "COALESCE(plan_tarihi, date('now')) "
        "FROM nexgen_uretim_plan WHERE id=?",
        (p_main,),
    )
    con.execute("UPDATE nexgen_uretim_plan SET durum='BITTI' WHERE id=?", (p_main,))
    con.commit()
    sync = _pzm_siparis_tamamlandi_sync(con, p_main)
    con.commit()
    sd_m = con.execute(
        "SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (tid2,)
    ).fetchone()["durum"]
    ok("NEG açık plan varken kapanmaz", sd_m != "TAMAMLANDI", f"{sd_m} {sync}")
    con.execute(
        "UPDATE nexgen_uretim_plan SET durum='BITTI' WHERE planlama_siparis_id=?", (tid2,)
    )
    con.commit()
    _pzm_siparis_tamamlandi_sync(con, p_main)
    con.commit()
    sd_m2 = con.execute(
        "SELECT durum FROM nexgen_planlama_siparis WHERE id=?", (tid2,)
    ).fetchone()["durum"]
    ok("C tüm planlar → TAMAMLANDI", sd_m2 == "TAMAMLANDI", sd_m2)

    sync_bad = _pzm_siparis_tamamlandi_sync(con, 99999999)
    ok("C orphan plan güvenli", sync_bad.get("ok") is True, str(sync_bad))

con.close()
_SHA1 = sha256_file(_LIVE)
ok("ISO main DB SHA unchanged", _SHA0 == _SHA1, _SHA0[:16])
print(f"[ISO] main_sha_after={_SHA1}")
print(f"[ISO] main_db_changed={_SHA0 != _SHA1}")
cleanup_tmp({"tmp_dir": _TMP_DIR})

print("\n" + "=" * 72)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f"SONUC: {passed} PASS / {failed} FAIL")
for n, c, d in results:
    if not c:
        print(f"  FAIL: {n} — {d}")
print("=" * 72)
sys.exit(0 if failed == 0 else 1)

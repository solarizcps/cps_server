# -*- coding: utf-8 -*-
"""FAZ migration 108 — Ferhat tablet.view (live DB yazmaz)."""
import io
import importlib.util
import os
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
_TMP_DIR = tempfile.mkdtemp(prefix="mig108_")
TEST_DB = os.path.join(_TMP_DIR, "mock_data_test.db")
shutil.copy2(_LIVE, TEST_DB)

print("=" * 72)
print("MIGRATION 108 TMP TESTS")
print(f"[ISO] tmp={TEST_DB}")
print(f"[ISO] main_sha_before={_SHA0}")
print("=" * 72)

mig_path = os.path.join(_APP, "migrations", "108_ferhat_enjeksiyon_tablet_view.py")
spec = importlib.util.spec_from_file_location("mig108", mig_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

results = []


def ok(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def count35(db):
    con = sqlite3.connect(db)
    n = con.execute(
        """
        SELECT COUNT(*) FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id=ry.YetkiId
        WHERE ry.RolId=35 AND y.Kod='nexgen.tablet.view' AND ry.can_view=1
        """
    ).fetchone()[0]
    con.close()
    return n


def other_tablet_view(db):
    con = sqlite3.connect(db)
    n = con.execute(
        """
        SELECT COUNT(*) FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id=ry.YetkiId
        WHERE y.Kod='nexgen.tablet.view' AND ry.RolId<>35
        """
    ).fetchone()[0]
    con.close()
    return n


ok("pre count Rol35=0", count35(TEST_DB) == 0, str(count35(TEST_DB)))
other0 = other_tablet_view(TEST_DB)
ok("mig108 run#1", mod.run(TEST_DB) == 0)
ok("post count Rol35=1", count35(TEST_DB) == 1)
ok("other roles unchanged after #1", other_tablet_view(TEST_DB) == other0, f"{other0}")
ok("mig108 run#2 idempotent", mod.run(TEST_DB) == 0)
ok("post#2 count still 1", count35(TEST_DB) == 1)
ok("other roles unchanged after #2", other_tablet_view(TEST_DB) == other0)

# rollback yalnız 35
ok("rollback", mod.rollback(TEST_DB) == 0)
ok("after rollback count=0", count35(TEST_DB) == 0)
ok("other roles after rollback unchanged", other_tablet_view(TEST_DB) == other0)
ok("re-apply after rollback", mod.run(TEST_DB) == 0)
ok("re-apply count=1", count35(TEST_DB) == 1)

import config as _cfg

_cfg.Config.MOCK_DB_PATH = TEST_DB
import app as flask_app
import modules.auth as auth_mod
import modules.nexgen.routes as nx_routes

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config["TESTING"] = True

with _app.test_client() as c:
    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem",
            "RolId": 35, "RolAd": "Enjeksiyon", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    ok("Ferhat route 200", c.get("/nexgen/tablet/ferhat").status_code == 200)

    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 50, "KullaniciAdi": "vedat", "Tip": "sistem",
            "RolId": 42, "RolAd": "AR-GE Operatörü", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    ok("Vedat arge 200", c.get("/nexgen/tablet/arge").status_code == 200)

    with c.session_transaction() as s:
        s["kullanici"] = {
            "Id": 99, "KullaniciAdi": "nobody", "Tip": "sistem",
            "RolId": 99, "RolAd": "X", "Aktif": 1,
        }
        s["kullanici_tip"] = "sistem"
    ok("Yetkisiz 403", c.get("/nexgen/tablet/ferhat").status_code == 403)

with _app.test_client() as c0:
    r = c0.get("/nexgen/tablet/ferhat", follow_redirects=False)
    loc = r.headers.get("Location") or ""
    ok("Anonim giris", r.status_code in (301, 302) and "giris" in loc, loc[:60])


def _fake_login(kadi, sifre):
    if kadi == "ferhat":
        return {
            "Id": 38, "KullaniciAdi": "ferhat", "Tip": "sistem",
            "RolId": 35, "Aktif": 1, "ZorunluSifreDegistir": 0,
        }
    return None


old = auth_mod.login_kullanici
auth_mod.login_kullanici = _fake_login
try:
    with _app.test_client() as c:
        rf = c.post("/giris", data={"kullanici": "ferhat", "sifre": "x"}, follow_redirects=False)
        ok(
            "Ferhat login redirect",
            rf.status_code in (301, 302)
            and "/nexgen/tablet/ferhat" in (rf.headers.get("Location") or ""),
            rf.headers.get("Location"),
        )
finally:
    auth_mod.login_kullanici = old

live_n = count35(_LIVE) if False else sqlite3.connect(
    f"file:{_LIVE}?mode=ro", uri=True
).execute(
    """
    SELECT COUNT(*) FROM sistem_rol_yetki ry
    JOIN sistem_yetki y ON y.Id=ry.YetkiId
    WHERE ry.RolId=35 AND y.Kod='nexgen.tablet.view'
    """
).fetchone()[0]
ok("LIVE Rol35 tablet.view=0 (no apply)", live_n == 0, str(live_n))

_SHA1 = sha256_file(_LIVE)
ok("Ana DB SHA unchanged", _SHA0 == _SHA1)

fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"SONUC: {len(results)-len(fails)}/{len(results)} PASS")
for n, c, d in results:
    if not c:
        print("FAIL", n, d)
cleanup_tmp({"tmp_dir": _TMP_DIR})
sys.exit(1 if fails else 0)

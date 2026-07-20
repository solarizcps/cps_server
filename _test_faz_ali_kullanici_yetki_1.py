# -*- coding: utf-8 -*-
"""FAZ-ALI-KULLANICI-YETKI-VE-SERVER-HAZIRLIK-1 — MOCK smoke (şifre loglanmaz)."""
from __future__ import annotations

import os
import secrets
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)
os.chdir(APP)

# Geçici şifre — sadece bu process; stdout'a yazılmaz
_PW = "AliOp" + secrets.token_hex(4)

from tools.nexgen_create_operator_user import main as create_main  # noqa: E402


def _ok(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def run():
    results = []
    rc = create_main(["--username", "ali", "--password", _PW, "--reset-password"])
    results.append(_ok("create_operator_user", rc == 0, f"rc={rc}"))

    from app import app  # noqa: E402

    client = app.test_client()

    # Login
    r = client.post(
        "/giris",
        data={"kullanici": "ali", "sifre": _PW},
        follow_redirects=False,
    )
    loc = r.headers.get("Location") or ""
    # İlk girişte ZorunluSifreDegistir=1 olabilir → /sifre-degistir; aksi /nexgen/tablet
    login_ok = r.status_code in (302, 303) and (
        loc.rstrip("/").endswith("/nexgen/tablet") or "sifre-degistir" in loc
    )
    results.append(_ok("login_redirect_op", login_ok, f"{r.status_code} {loc}"))
    # Test için zorunlu şifre değiştirmeyi session'da kapat (yalnız client session)
    with client.session_transaction() as sess:
        if sess.get("kullanici"):
            sess["kullanici"]["ZorunluSifreDegistir"] = 0

    # İzinli
    r = client.get("/nexgen/tablet", follow_redirects=False)
    results.append(_ok("GET /nexgen/tablet", r.status_code == 200, str(r.status_code)))

    # Yasak yönetim / arge / ferhat — tip_guard redirect veya 403
    for path, label in (
        ("/yonetim/", "yonetim"),
        ("/finans/", "finans"),
        ("/nexgen/", "nexgen_hub"),
        ("/nexgen/tablet/arge", "arge_hub"),
        ("/nexgen/tablet/arge/musteri-renk", "arge_musteri"),
        ("/nexgen/tablet/ferhat", "ferhat"),
        ("/nexgen/pazarlama", "pazarlama"),
        ("/nexgen/stok", "stok"),
        ("/nexgen/depo", "depo"),
    ):
        r = client.get(path, follow_redirects=False)
        blocked = r.status_code in (302, 303, 403)
        if r.status_code in (302, 303):
            loc = r.headers.get("Location") or ""
            blocked = "/nexgen/tablet" in loc or "/giris" in loc
        results.append(_ok(f"block {label}", blocked, str(r.status_code)))

    # API arge — 403 (allowlist veya arge backend guard)
    r = client.get("/nexgen/api/tablet/arge/formul-onizle", follow_redirects=False)
    results.append(_ok("API arge 403", r.status_code == 403, str(r.status_code)))

    # can_uretim tag smoke (session içinde)
    with client.session_transaction() as sess:
        u = sess.get("kullanici")
    from modules.auth import kullanici_yetkileri, yetki_var  # noqa: E402
    from flask import g

    with app.test_request_context("/"):
        # session'dan kullanıcıyı g'ye bağla
        with client.session_transaction() as sess:
            pass
        # yeniden login state ile
        pass

    # yetki seti DB üzerinden
    import sqlite3
    from config import Config

    con = sqlite3.connect(Config.MOCK_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM sistem_kullanici WHERE lower(KullaniciAdi)='ali'"
    ).fetchone()
    con.close()
    udict = dict(row)
    yk = kullanici_yetkileri(udict)
    results.append(_ok("yetki tablet.view", "nexgen.tablet.view:can_view" in yk))
    results.append(_ok("yetki tablet.uretim", "nexgen.tablet.uretim:can_view" in yk))
    results.append(_ok("yetki NO recete.view", "nexgen.recete.view:can_view" not in yk))
    results.append(_ok("yetki NO yonetim", "nexgen.yonetim.manage:can_manage" not in yk))

    with app.test_request_context("/"):
        from flask import session as fs

        fs["kullanici"] = udict
        g.yetkiler = None
        results.append(_ok("yetki_var can_uretim", yetki_var("nexgen.tablet.uretim", "can_uretim")))
        results.append(_ok("yetki_var arge_ops False", not (
            yetki_var("nexgen.recete.view", "can_view")
            or yetki_var("nexgen.recete.create", "can_create")
            or yetki_var("nexgen.yonetim.manage", "can_manage")
        )))

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\nSONUÇ: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())

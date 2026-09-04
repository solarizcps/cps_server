# -*- coding: utf-8 -*-
"""Repeat route isolation block — five iterations in one guarded pytest session."""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _make_client():
    import app as flask_app

    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


def _admin_session(client):
    with client.session_transaction() as sess:
        sess["kullanici"] = {
            "Id": 1,
            "KullaniciAdi": "admin",
            "AdSoyad": "Admin",
            "Tip": "sistem",
            "RolId": 1,
            "Aktif": 1,
            "AuthVersion": 1,
        }


@contextmanager
def _route_ctx(*, permissions: set[str] | None = None, superadmin: bool = False):
    perms = set(permissions if permissions is not None else {"*"})

    def _yetki_var(kod, action="can_view"):
        if "*" in perms:
            return True
        return (kod + ":" + action) in perms

    def _kullanici_yetkileri(_user_dict):
        return set(perms)

    patches = [
        patch("app.sistem_session_gecerli_mi", return_value=True),
        patch("app.kullanici_yetkileri", side_effect=_kullanici_yetkileri),
        patch("modules.auth.kullanici_yetkileri", side_effect=_kullanici_yetkileri),
        patch("modules.auth.yetki_var", side_effect=_yetki_var),
        patch("modules.auth.is_superadmin", return_value=superadmin),
        patch("modules.yonetim.routes.yetki_var", side_effect=_yetki_var),
        patch("modules.yonetim.routes.is_superadmin", return_value=superadmin),
    ]
    for item in patches:
        item.start()
    try:
        yield
    finally:
        for item in patches:
            item.stop()


@pytest.mark.parametrize("run_idx", range(5))
def test_route_block_repeat_t12_t14(run_idx, route_db_isolation):
    import config
    from tools.atp_test_db_guard import is_canonical_path

    assert route_db_isolation.get("active") is True
    assert not is_canonical_path(config.Config.MOCK_DB_PATH)

    client = _make_client()
    resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code in (302, 303)
    assert "/giris" in (resp.location or "")

    _admin_session(client)
    with _route_ctx(permissions={"yonetim:can_view"}, superadmin=False):
        resp = client.get(
            "/yonetim/surum-gecmisi?modul=nexgen.mo&faz=NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1"
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Detay görünümü için Audit Log yetkisi" in body

    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get(
            "/yonetim/surum-gecmisi?modul=nexgen.mo&faz=NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1"
        )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "v1.3.0" in body
    assert "ad5fd303" in body

    import services.release_history_service as service_mod

    service_mod = importlib.reload(service_mod)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=planlama.atp&faz=ATP_GPS_GEOFENCE_P3")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Test Edilen Kurallar" in body

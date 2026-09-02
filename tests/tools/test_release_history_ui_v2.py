# -*- coding: utf-8 -*-
"""CPS release history read-only UI tests (V2)."""
from __future__ import annotations

import importlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
VALIDATOR = ROOT / "tools" / "validate_release_history.py"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _copy_canonical_fixture(tmp: Path) -> None:
    for rel in (
        "docs/release-history/schema.toml",
        "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml",
        "changes/fragments/nexgen.mo.NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.release",
    ):
        src = ROOT / rel
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


@pytest.fixture()
def fixture_root():
    tmp = Path(tempfile.mkdtemp(prefix="cps_rh_ui_v2_"))
    _copy_canonical_fixture(tmp)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def service_mod():
    import services.release_history_service as mod
    return importlib.reload(mod)


def test_t1_valid_canonical_record_load_pass(fixture_root, service_mod):
    records, skipped = service_mod.load_release_records(fixture_root)
    assert skipped == 0
    assert len(records) == 1
    assert records[0].module == "nexgen.mo"
    assert records[0].version == "v1.3.0"


def test_t2_module_aggregation_pass(fixture_root, service_mod):
    ctx = service_mod.build_page_context(fixture_root)
    assert ctx["summary"]["total_modules"] == 1
    assert ctx["modules"][0].module_label == "Müşteri Operasyonu"
    assert ctx["modules"][0].current_version == "v1.3.0"


def test_t3_current_local_deployment_fields_pass(fixture_root, service_mod):
    ctx = service_mod.build_page_context(fixture_root)
    item = ctx["modules"][0]
    assert item.local_version == "v1.3.0"
    assert "Server aktarımı" in item.deploy_label


def test_t4_invalid_toml_safe_skip_pass(fixture_root, service_mod):
    bad = fixture_root / "changes/records/nexgen.mo/BROKEN.toml"
    bad.write_text("this is not valid toml [[[\n", encoding="utf-8")
    records, skipped = service_mod.load_release_records(fixture_root)
    assert len(records) == 1
    assert skipped >= 1


def test_t5_absolute_sensitive_path_output_blocked(fixture_root, service_mod):
    record = fixture_root / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml"
    text = record.read_text(encoding="utf-8")
    text = text.replace(
        "app/modules/nexgen/musteri_pazarlama_routes.py",
        "C:\\\\Users\\\\LENOVO\\\\_audit_out\\\\secret.db",
    )
    record.write_text(text, encoding="utf-8")
    records, _ = service_mod.load_release_records(fixture_root)
    assert records
    assert all("_audit_out" not in path for path in records[0].changed_files)
    assert all("C:" not in path and "Users" not in path for path in records[0].changed_files)


def test_t6_unknown_module_blocked(fixture_root, service_mod):
    record = fixture_root / "changes/records/unknown.mod/PHASE_X.toml"
    record.parent.mkdir(parents=True, exist_ok=True)
    base = (ROOT / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml").read_text(encoding="utf-8")
    record.write_text(base.replace("nexgen.mo", "unknown.mod").replace(
        "NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1", "PHASE_X"
    ), encoding="utf-8")
    frag = fixture_root / "changes/fragments/unknown.mod.PHASE_X.release"
    frag.write_text("x\n", encoding="utf-8")
    records, skipped = service_mod.load_release_records(fixture_root)
    assert all(r.module != "unknown.mod" for r in records)
    assert skipped >= 1


def test_t7_path_traversal_impossible(fixture_root, service_mod):
    detail = service_mod.find_record([], "../../../etc", "PASSWD")
    assert detail is None
    detail2 = service_mod.find_record([], "nexgen.mo", "../BAD")
    assert detail2 is None


def test_t8_empty_record_directory_graceful(tmp_path, service_mod):
    (tmp_path / "changes/records").mkdir(parents=True)
    (tmp_path / "docs/release-history").mkdir(parents=True)
    shutil.copy2(ROOT / "docs/release-history/schema.toml", tmp_path / "docs/release-history/schema.toml")
    records, skipped = service_mod.load_release_records(tmp_path)
    assert records == []
    assert skipped == 0
    ctx = service_mod.build_page_context(tmp_path)
    assert ctx["summary"]["total_records"] == 0


def test_t9_filter_module_and_status(fixture_root, service_mod):
    ctx = service_mod.build_page_context(fixture_root, module_query="müşteri", status="KILITLI")
    assert len(ctx["modules"]) == 1
    ctx_empty = service_mod.build_page_context(fixture_root, status="TASLAK")
    assert ctx_empty["modules"] == []


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

    patches = [
        patch("app.sistem_session_gecerli_mi", return_value=True),
        patch("app.kullanici_yetkileri", return_value=perms),
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


def test_t10_authorized_route_200():
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 200


def test_t11_unauthorized_route_403():
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions=set(), superadmin=False):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 403


def test_t12_unauthenticated_redirect():
    client = _make_client()
    resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code in (302, 303)
    assert "/giris" in (resp.location or "")


def test_t13_detail_permission_guard():
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"yonetim:can_view"}, superadmin=False):
        resp = client.get(
            "/yonetim/surum-gecmisi?modul=nexgen.mo&faz=NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1"
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Detay görünümü için Audit Log yetkisi" in body
    assert "Kilitli Kurallar" not in body


def test_t14_template_output_contains_bootstrap_fields():
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get(
            "/yonetim/surum-gecmisi?modul=nexgen.mo&faz=NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1"
        )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "v1.3.0" in body
    assert "KILITLI" in body or "Kilitli" in body
    assert "ad5fd303" in body
    assert "T1-T22" in body
    assert "_audit_out" not in body
    assert "C:\\\\Users" not in body


def test_t15_v1_validator_still_passes():
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "VALIDATOR PASS" in proc.stdout


def test_t16_v1_pytest_suite_still_passes():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_validate_release_history_v1.py", "-q"],
        cwd=str(ROOT / "tests" / "tools"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_t17_no_db_write_on_page_load():
    db_path = APP / "mock_data.db"
    if not db_path.is_file():
        pytest.skip("canonical db not present")
    before = db_path.stat().st_mtime
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 200
    after = db_path.stat().st_mtime
    assert after == before

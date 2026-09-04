# -*- coding: utf-8 -*-
"""CPS release history read-only UI tests (V2)."""
from __future__ import annotations

import importlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from release_history_test_git import (
    MOCK_HEAD,
    MOCK_ORIGIN,
    NEXGEN_RECORD_SHA,
    PUSHED_RECORD_SHA,
    UNKNOWN_RECORD_SHA,
    mock_git_cache,
)

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


def test_t3_current_local_deployment_fields_pass(fixture_root, service_mod, monkeypatch):
    git = mock_git_cache(
        base=fixture_root,
        head=MOCK_HEAD,
        origin=MOCK_ORIGIN,
        head_set={NEXGEN_RECORD_SHA},
        origin_set=set(),
    )
    monkeypatch.setattr(service_mod, "GitEvidenceCache", lambda base=None: git)
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    ctx = service_mod.build_page_context(fixture_root)
    item = ctx["modules"][0]
    assert item.local_version == "v1.3.0"
    assert item.push_status_auto == "LOCAL_COMMITTED_NOT_PUSHED"
    assert item.push_status_label == "Yerelde commitli · Push yapılmadı"
    assert item.deployment_status == "LOCAL_COMMITTED_NOT_PUSHED"
    assert item.deploy_label == "Deploy edilmedi"


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


def test_t10_authorized_route_200(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 200


def test_t11_unauthorized_route_403(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions=set(), superadmin=False):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 403


def test_t12_unauthenticated_redirect(route_db_isolation):
    import config
    from tools.atp_test_db_guard import is_canonical_path

    assert route_db_isolation.get("active") is True
    assert not is_canonical_path(config.Config.MOCK_DB_PATH)
    client = _make_client()
    resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code in (302, 303)
    assert "/giris" in (resp.location or "")


def test_t13_detail_permission_guard(route_db_isolation):
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


def test_t14_template_output_contains_bootstrap_fields(route_db_isolation):
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
    assert "Commit Bekleyen" in body
    assert "Sürüm Zaman Çizelgesi" in body or "Toplam Kayıt" in body
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


def test_t17_no_db_write_on_page_load(route_db_isolation):
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


def _canonical_toml_text() -> str:
    return (ROOT / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml").read_text(encoding="utf-8")


def _write_bulk_record(fixture_root: Path, phase: str) -> None:
    text = _canonical_toml_text().replace("NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1", phase)
    path = fixture_root / "changes/records/nexgen.mo" / f"{phase}.toml"
    path.write_text(text, encoding="utf-8")
    frag = fixture_root / "changes/fragments" / f"nexgen.mo.{phase}.release"
    frag.write_text("x\n", encoding="utf-8")


def test_t18_symlink_record_skipped(fixture_root, service_mod, monkeypatch):
    target = fixture_root / "changes/records/nexgen.mo/SYMLINK.toml"
    target.write_text("placeholder\n", encoding="utf-8")
    original = Path.is_symlink

    def _is_symlink(self):
        if self.name == "SYMLINK.toml":
            return True
        return original(self)

    monkeypatch.setattr(Path, "is_symlink", _is_symlink)
    records, skipped = service_mod.load_release_records(fixture_root)
    assert all(r.phase_code != "SYMLINK" for r in records)
    assert skipped >= 1


def test_t19_resolved_path_outside_root_skipped(fixture_root, service_mod, monkeypatch):
    outside = fixture_root / "outside_secret.toml"
    outside.write_text("outside\n", encoding="utf-8")
    escape = fixture_root / "changes/records/nexgen.mo/OUTSIDE.toml"
    escape.write_text("escape\n", encoding="utf-8")
    original = Path.resolve

    def _resolve(self):
        if self.name == "OUTSIDE.toml":
            return outside.resolve()
        return original(self)

    monkeypatch.setattr(Path, "resolve", _resolve)
    records, skipped = service_mod.load_release_records(fixture_root)
    assert all(r.phase_code != "OUTSIDE" for r in records)
    assert skipped >= 1
    body = service_mod.build_page_context(fixture_root)
    rendered = str(body)
    assert "outside_secret" not in rendered


def test_t20_oversized_toml_skipped(fixture_root, service_mod):
    huge_phase = "HUGE_TOML"
    path = fixture_root / "changes/records/nexgen.mo" / f"{huge_phase}.toml"
    payload = _canonical_toml_text().replace("NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1", huge_phase)
    path.write_text(payload, encoding="utf-8")
    with path.open("ab") as handle:
        handle.write(b"#" + b"x" * (service_mod.MAX_TOML_BYTES + 1))
    records, skipped = service_mod.load_release_records(fixture_root)
    assert all(r.phase_code != huge_phase for r in records)
    assert skipped >= 1
    assert len(records) == 1


def test_t21_max_records_limit_deterministic(fixture_root, service_mod):
    for i in range(service_mod.MAX_RECORDS):
        _write_bulk_record(fixture_root, f"BULK_{i:04d}")
    records, skipped = service_mod.load_release_records(fixture_root)
    assert len(records) == service_mod.MAX_RECORDS
    assert skipped >= 1
    phases = {r.phase_code for r in records}
    assert "NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1" not in phases
    assert "BULK_0000" in phases
    assert f"BULK_{service_mod.MAX_RECORDS - 1:04d}" in phases


def test_t22_long_text_truncated_safely(fixture_root, service_mod):
    record = fixture_root / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml"
    long_text = "A" * (service_mod.MAX_TEXT_LENGTH + 500)
    text = record.read_text(encoding="utf-8")
    text = text.replace(
        "Doğrudan Sipariş Talebi onay ve planlama akışı kilitlendi.",
        long_text,
    )
    record.write_text(text, encoding="utf-8")
    records, skipped = service_mod.load_release_records(fixture_root)
    assert skipped == 0
    assert len(records) == 1
    assert len(records[0].title) == service_mod.MAX_TEXT_LENGTH


def test_t23_list_items_capped_safely(fixture_root, service_mod):
    record = fixture_root / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml"
    items = ",\n".join(f'  "item {i}"' for i in range(service_mod.MAX_LIST_ITEMS + 1))
    text = record.read_text(encoding="utf-8")
    text = re.sub(
        r"changes = \[.*?\]",
        f"changes = [\n{items}\n]",
        text,
        count=1,
        flags=re.DOTALL,
    )
    record.write_text(text, encoding="utf-8")
    records, skipped = service_mod.load_release_records(fixture_root)
    assert skipped == 0
    assert len(records) == 1
    assert len(records[0].changes) == service_mod.MAX_LIST_ITEMS


def test_t24_normal_canonical_record_still_loads(fixture_root, service_mod):
    records, skipped = service_mod.load_release_records(fixture_root)
    assert skipped == 0
    assert len(records) == 1
    assert records[0].phase_code == "NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1"


def _write_deploy_kpi_record(
    fixture_root: Path,
    *,
    module: str,
    phase_code: str,
    version: str,
    push_status: str,
    deployment_status: str,
    commit_sha: str = NEXGEN_RECORD_SHA,
) -> None:
    text = _canonical_toml_text()
    text = (
        text.replace("nexgen.mo", module)
        .replace("NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1", phase_code)
        .replace("v1.3.0", version)
        .replace(NEXGEN_RECORD_SHA, commit_sha)
        .replace('push_status = "LOCAL_COMMITTED_NOT_PUSHED"', f'push_status = "{push_status}"')
        .replace(
            'deployment_status = "LOCAL_COMMITTED_NOT_PUSHED"',
            f'deployment_status = "{deployment_status}"',
        )
    )
    record_dir = fixture_root / "changes" / "records" / module
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{phase_code}.toml"
    record_path.write_text(text, encoding="utf-8")
    frag = fixture_root / "changes" / "fragments" / f"{module}.{phase_code}.release"
    frag.write_text(f"{phase_code} deploy fixture\n", encoding="utf-8")


def _copy_deploy_kpi_fixture(tmp: Path) -> None:
    _copy_canonical_fixture(tmp)
    _write_deploy_kpi_record(
        tmp,
        module="nexgen.mo",
        phase_code="DEPLOY_KPI_WAIT_A",
        version="v1.0.0",
        push_status="LOCAL_COMMITTED_NOT_PUSHED",
        deployment_status="LOCAL_COMMITTED_NOT_PUSHED",
    )
    _write_deploy_kpi_record(
        tmp,
        module="cps.release.history",
        phase_code="DEPLOY_KPI_WAIT_B",
        version="v1.0.0",
        push_status="PUSHED_NOT_DEPLOYED",
        deployment_status="PUSHED_NOT_DEPLOYED",
        commit_sha=PUSHED_RECORD_SHA,
    )
    for idx, module in enumerate(("planlama.atp", "server", "test.infra"), start=1):
        _write_deploy_kpi_record(
            tmp,
            module=module,
            phase_code=f"DEPLOY_KPI_UNKNOWN_{idx}",
            version="v1.0.0",
            push_status="DEPLOYMENT_UNKNOWN",
            deployment_status="DEPLOYMENT_UNKNOWN",
            commit_sha=UNKNOWN_RECORD_SHA,
        )


def test_t25_deploy_kpi_counts_local_vs_unknown(service_mod, tmp_path, monkeypatch):
    fixture_root = tmp_path / "deploy_kpi_fixture"
    _copy_deploy_kpi_fixture(fixture_root)

    git = mock_git_cache(
        base=fixture_root,
        head=MOCK_HEAD,
        origin=MOCK_ORIGIN,
        head_set={NEXGEN_RECORD_SHA, PUSHED_RECORD_SHA},
        origin_set={PUSHED_RECORD_SHA},
        unknown_refs={UNKNOWN_RECORD_SHA},
    )
    monkeypatch.setattr(service_mod, "GitEvidenceCache", lambda base=None: git)
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)

    records, skipped = service_mod.load_release_records(fixture_root)
    ctx = service_mod.build_page_context(fixture_root)
    summary = ctx["summary"]

    assert skipped == 0
    assert summary["total_records"] == len(records)
    assert summary["deploy_waiting_modules"] == 2
    assert summary["deploy_unknown_modules"] == 3

    _write_deploy_kpi_record(
        fixture_root,
        module="finans",
        phase_code="DEPLOY_KPI_EXTRA",
        version="v1.0.0",
        push_status="DEPLOYMENT_UNKNOWN",
        deployment_status="DEPLOYMENT_UNKNOWN",
    )
    records_after_add, skipped_after_add = service_mod.load_release_records(fixture_root)
    ctx_after_add = service_mod.build_page_context(fixture_root)
    assert skipped_after_add == 0
    assert len(records_after_add) == len(records) + 1
    assert ctx_after_add["summary"]["total_records"] == len(records_after_add)

    bad = fixture_root / "changes/records/finans/BROKEN.toml"
    bad.write_text("invalid toml [[[\n", encoding="utf-8")
    records_after_bad, skipped_after_bad = service_mod.load_release_records(fixture_root)
    ctx_after_bad = service_mod.build_page_context(fixture_root)
    assert skipped_after_bad >= 1
    assert len(records_after_bad) == len(records_after_add)
    assert ctx_after_bad["summary"]["total_records"] == len(records_after_bad)

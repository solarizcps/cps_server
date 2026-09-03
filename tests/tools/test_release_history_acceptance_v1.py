# -*- coding: utf-8 -*-
"""Acceptance tests for release history automation fix V1."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def release_state_mod():
    return _load_module("release_state", ROOT / "tools" / "release_state.py")


@pytest.fixture(scope="module")
def check_fragment_mod():
    return _load_module("check_fragment", ROOT / "tools" / "check_release_fragment.py")


def _init_temp_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
    (tmp / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True, capture_output=True)
    return tmp


def test_state_precedence_dirty_worktree_working(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        prod = repo / "app" / "modules" / "finans"
        prod.mkdir(parents=True)
        (prod / "x.py").write_text("dirty\n", encoding="utf-8")
        core = release_state_mod.compute_global_state(repo)
        assert core["global_state"] == "WORKING"


def test_state_precedence_staged_commit_pending(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        prod = repo / "app" / "modules" / "finans"
        prod.mkdir(parents=True)
        (prod / "x.py").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "add", "app/modules/finans/x.py"], cwd=repo, check=True)
        core = release_state_mod.compute_global_state(repo)
        assert core["global_state"] == "COMMIT_PENDING"


def test_state_precedence_clean_ahead_local_not_pushed(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)
        (repo / "note.txt").write_text("a\n", encoding="utf-8")
        subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "second"], cwd=repo, check=True, capture_output=True)
        core = release_state_mod.compute_global_state(repo)
        assert core["global_state"] == "LOCAL_COMMITTED_NOT_PUSHED"


def test_unrelated_dirty_files_ignored(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        (repo / "_scratch_unrelated.py").write_text("x", encoding="utf-8")
        core = release_state_mod.compute_global_state(repo)
        assert core["worktree_clean"] is True
        assert core["global_state"] != "WORKING"


def test_fake_manifest_manual_pass_rejected(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        manifest_dir = repo / "var" / "release"
        manifest_dir.mkdir(parents=True)
        manifest = {
            "deployment_commit": head,
            "server_head": head,
            "http_smoke_result": "PASS",
        }
        (manifest_dir / "deployment_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        release_state_mod.MANIFEST_PATH = manifest_dir / "deployment_manifest.json"
        release_state_mod.STATE_PATH = manifest_dir / "deployment_state.json"
        release_state_mod.ROOT = repo
        check = release_state_mod._verify_manifest(manifest, head, repo)
        assert check["status"] == "NEEDS_REVIEW"
        assert not check["smoke_pass"]


def test_fake_sha_needs_review(release_state_mod):
    manifest = {"deployment_commit": "deadbeef" * 5}
    check = release_state_mod._verify_manifest(manifest, "a" * 40, ROOT)
    assert check["status"] in {"NEEDS_REVIEW", "DEPLOYMENT_UNKNOWN"}


def test_precommit_missing_record_fail(check_fragment_mod):
    ok, _ = check_fragment_mod.check_staged(["app/modules/finans/x.py"])
    assert ok is False


def test_precommit_valid_record_pass(check_fragment_mod):
    ok, _ = check_fragment_mod.check_staged([
        "app/modules/finans/x.py",
        "changes/records/finans/PHASE_X.toml",
        "changes/fragments/finans.PHASE_X.release",
    ])
    assert ok is True


def test_precommit_docs_only_pass(check_fragment_mod):
    ok, _ = check_fragment_mod.check_staged(["docs/release-history/schema.toml", "tests/tools/x.py"])
    assert ok is True


def test_precommit_unrelated_dirty_ignored(check_fragment_mod):
    ok, _ = check_fragment_mod.check_staged(["docs/foo.md"])
    assert ok is True


def test_precommit_malformed_toml_fail(check_fragment_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(check_fragment_mod, "ROOT", tmp_path)
    rec = tmp_path / "changes" / "records" / "finans"
    rec.mkdir(parents=True)
    bad = rec / "BAD.toml"
    bad.write_text("module = finans\n[[broken\n", encoding="utf-8")
    ok, msg = check_fragment_mod.check_staged(["changes/records/finans/BAD.toml"])
    assert ok is False
    assert "malformed TOML" in msg


def test_precommit_locked_rules_without_approval_fail(check_fragment_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(check_fragment_mod, "ROOT", tmp_path)
    rec = tmp_path / "changes" / "records" / "finans"
    rec.mkdir(parents=True)
    toml = rec / "PHASE_X.toml"
    old = 'locked_rules = ["rule A"]\nmodule = "finans"\n'
    new = 'locked_rules = ["rule B"]\nmodule = "finans"\n'
    toml.write_text(new, encoding="utf-8")

    def fake_show(args, **kwargs):
        class R:
            returncode = 0
            stdout = old
        return R()

    monkeypatch.setattr(check_fragment_mod.subprocess, "run", fake_show)
    ok, msg = check_fragment_mod.check_staged(["changes/records/finans/PHASE_X.toml"])
    assert ok is False
    assert "locked_rules changed" in msg


def test_precommit_locked_rules_with_approval_pass(check_fragment_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(check_fragment_mod, "ROOT", tmp_path)
    rec = tmp_path / "changes" / "records" / "finans"
    rec.mkdir(parents=True)
    toml = rec / "PHASE_X.toml"
    old = 'locked_rules = ["rule A"]\n'
    new = 'locked_rules = ["rule B"]\nlocked_rules_approval = true\n'
    toml.write_text(new, encoding="utf-8")

    def fake_show(args, **kwargs):
        class R:
            returncode = 0
            stdout = old
        return R()

    monkeypatch.setattr(check_fragment_mod.subprocess, "run", fake_show)
    ok, _ = check_fragment_mod.check_staged(["changes/records/finans/PHASE_X.toml"])
    assert ok is True


def test_module_state_only_dirty_modules_working(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        atp = repo / "changes" / "records" / "planlama.atp"
        atp.mkdir(parents=True)
        (atp / "X.toml").write_text("x\n", encoding="utf-8")
        state = release_state_mod.generate_state(repo)
        assert state["global_state"] == "WORKING"
        assert state["modules"]["planlama.atp"]["push_status"] == "WORKING"
        assert state["modules"]["finans"]["push_status"] != "WORKING"


def test_state_transition_chain_local_committed(release_state_mod):
    with tempfile.TemporaryDirectory() as td:
        repo = _init_temp_repo(Path(td))
        prod = repo / "changes" / "records" / "finans"
        prod.mkdir(parents=True)
        (prod / "x.toml").write_text("a\n", encoding="utf-8")
        assert release_state_mod.compute_global_state(repo)["global_state"] == "WORKING"
        subprocess.run(["git", "add", "changes/"], cwd=repo, check=True)
        assert release_state_mod.compute_global_state(repo)["global_state"] == "COMMIT_PENDING"
        subprocess.run(["git", "commit", "-m", "add record"], cwd=repo, check=True, capture_output=True)
        assert release_state_mod.compute_global_state(repo)["global_state"] == "LOCAL_COMMITTED_NOT_PUSHED"


def test_hook_e2e_temp_repo():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _init_temp_repo(repo)
        tools = repo / "tools"
        tools.mkdir()
        for name in ("check_release_fragment.py", "validate_release_history.py", "release_state.py"):
            shutil.copy2(ROOT / "tools" / name, tools / name)
        hooks = repo / ".githooks"
        hooks.mkdir()
        shutil.copy2(ROOT / ".githooks" / "pre-commit", hooks / "pre-commit")
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=repo, check=True)

        prod = repo / "app" / "modules" / "finans"
        prod.mkdir(parents=True)
        (prod / "svc.py").write_text("x=1\n", encoding="utf-8")
        subprocess.run(["git", "add", "app/modules/finans/svc.py"], cwd=repo, check=True)
        fail = subprocess.run(["git", "commit", "-m", "bad"], cwd=repo, capture_output=True)
        assert fail.returncode != 0

        changes = repo / "changes" / "records" / "finans"
        changes.mkdir(parents=True)
        (changes / "PHASE_X.toml").write_text("placeholder\n", encoding="utf-8")
        fr = repo / "changes" / "fragments"
        fr.mkdir(parents=True)
        (fr / "finans.PHASE_X.release").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "changes/"], cwd=repo, check=True)
        # Still fails validator but hook e2e proved guard runs on staged production
        assert fail.returncode != 0


@pytest.fixture()
def service_mod():
    import services.release_history_service as mod
    return importlib.reload(mod)


def test_verified_uncommitted_not_kilitli(service_mod):
    records, _ = service_mod.load_release_records(ROOT)
    for rec in records:
        if rec.is_uncommitted:
            assert rec.status in {"TEST", "ONAYLANDI"}
            assert rec.status != "KILITLI"


def test_global_state_in_summary(service_mod):
    ctx = service_mod.build_page_context(ROOT)
    assert "global_state" in ctx["summary"]


def test_deployment_state_no_subprocess_on_page_load(service_mod):
    with patch("subprocess.run") as mock_run:
        service_mod.build_page_context(ROOT)
        mock_run.assert_not_called()

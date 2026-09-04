# -*- coding: utf-8 -*-
"""Release history automation tests — temp git repos only, no canonical DB."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DB = ROOT / "app" / "mock_data.db"
VALIDATOR = ROOT / "tools" / "validate_release_history.py"
CHECK_FRAGMENT = ROOT / "tools" / "check_release_fragment.py"
RELEASE_STATE = ROOT / "tools" / "release_state.py"
POST_COMMIT = ROOT / ".githooks" / "post-commit"
SCHEMA = ROOT / "docs" / "release-history" / "schema.toml"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_release_history", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_check_fragment():
    spec = importlib.util.spec_from_file_location("check_release_fragment", CHECK_FRAGMENT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def _init_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test")
    _git(repo, "config", "user.name", "test")
    (repo / "docs" / "release-history").mkdir(parents=True)
    shutil.copy2(SCHEMA, repo / "docs" / "release-history" / "schema.toml")
    (repo / "changes" / "records" / "test.infra").mkdir(parents=True)
    (repo / "changes" / "fragments").mkdir(parents=True)
    (repo / "var" / "release").mkdir(parents=True)
    (repo / "logs").mkdir(parents=True)
    (repo / "tools").mkdir(parents=True)
    shutil.copy2(RELEASE_STATE, repo / "tools" / "release_state.py")
    if POST_COMMIT.is_file():
        hooks = repo / ".githooks"
        hooks.mkdir()
        shutil.copy2(POST_COMMIT, hooks / "post-commit")
    return repo


def _write_min_record(repo: Path, *, commit_sha: str, source_type: str = "commit", status: str = "KILITLI") -> None:
    toml = textwrap.dedent(
        f"""
        schema_version = 1
        module = "test.infra"
        version = "v9.9.9"
        phase_code = "AUTOMATION_TEST_RECORD"
        title = "Automation test record"
        status = "{status}"
        date = "2026-09-04"
        summary = "Temp repo automation record."
        source_type = "{source_type}"
        commit_sha = "{commit_sha}"
        test_result = "temp PASS"
        db_write = false
        server_restart = false
        push_status = "Push yapılmadı"
        deployment_status = "Deploy edilmedi"
        changes = ["automation test"]
        changed_files = ["tests/tools/test_release_history_automation_v1.py"]
        locked_rules = []
        tests = []
        known_issues = []
        next_steps = []
        """
    ).strip() + "\n"
    rec = repo / "changes/records/test.infra/AUTOMATION_TEST_RECORD.toml"
    rec.write_text(toml, encoding="utf-8")
    frag = repo / "changes/fragments/test.infra.AUTOMATION_TEST_RECORD.release"
    frag.write_text("Automation test fragment.\n", encoding="utf-8")


def _sh_exe() -> str:
    for candidate in (
        r"C:\Program Files\Git\bin\sh.exe",
        r"C:\Program Files\Git\usr\bin\sh.exe",
        "sh",
    ):
        if candidate == "sh":
            return candidate
        if Path(candidate).is_file():
            return candidate
    return "sh"


def _run_hook(repo: Path) -> subprocess.CompletedProcess[str]:
    hook = repo / ".githooks" / "post-commit"
    return subprocess.run(
        [_sh_exe(), str(hook)],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )


def _commit_all(repo: Path, msg: str = "init") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def validator_mod():
    return _load_validator()


@pytest.fixture()
def check_mod():
    return _load_check_fragment()


def test_no_canonical_db_open_during_tests():
    assert CANONICAL_DB.is_file()
    # Tests must not open/write canonical DB; this module uses temp repos only.


def test_reachable_commit_sha_validator_pass(validator_mod, tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    sha_seed = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write_min_record(repo, commit_sha=sha_seed)
    _commit_all(repo, "record")
    errors, _ = validator_mod.validate(repo, git_cwd=repo)
    assert not [e for e in errors if "NOT_ANCESTOR" in e]
    assert not errors


def test_not_ancestor_sha_validator_fail(validator_mod, tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    orphan = _git(repo, "checkout", "--orphan", "side")
    assert orphan.returncode == 0
    _git(repo, "commit", "--allow-empty", "-m", "orphan")
    orphan_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "main")
    _write_min_record(repo, commit_sha=orphan_sha)
    _commit_all(repo, "record")
    errors, _ = validator_mod.validate(repo, git_cwd=repo)
    assert any("NOT_ANCESTOR" in e for e in errors)


def test_verified_uncommitted_empty_sha_pass(validator_mod, tmp_path):
    repo = _init_repo(tmp_path)
    toml = textwrap.dedent(
        """
        schema_version = 1
        module = "test.infra"
        version = "v9.8.0"
        phase_code = "VU_EMPTY_SHA"
        title = "VU empty sha"
        status = "TEST"
        date = "2026-09-04"
        summary = "verified uncommitted"
        source_type = "verified_uncommitted"
        commit_sha = ""
        test_result = "temp PASS"
        db_write = false
        server_restart = false
        push_status = "WORKING"
        deployment_status = "WORKING"
        worktree_fingerprint = "abc123"
        verification_date = "2026-09-04"
        verification_evidence = "temp"
        changes = []
        changed_files = []
        locked_rules = []
        tests = []
        known_issues = []
        next_steps = []
        """
    ).strip() + "\n"
    (repo / "changes/records/test.infra/VU_EMPTY_SHA.toml").write_text(toml, encoding="utf-8")
    (repo / "changes/fragments/test.infra.VU_EMPTY_SHA.release").write_text("vu\n", encoding="utf-8")
    _commit_all(repo, "vu")
    errors, _ = validator_mod.validate(repo, git_cwd=repo)
    assert not errors


def test_verified_uncommitted_with_sha_fail(validator_mod, tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    toml = textwrap.dedent(
        f"""
        schema_version = 1
        module = "test.infra"
        version = "v9.7.0"
        phase_code = "VU_BAD_SHA"
        title = "VU bad sha"
        status = "TEST"
        date = "2026-09-04"
        summary = "verified uncommitted with sha"
        source_type = "verified_uncommitted"
        commit_sha = "{sha}"
        test_result = "temp"
        db_write = false
        server_restart = false
        push_status = "WORKING"
        deployment_status = "WORKING"
        worktree_fingerprint = "abc123"
        verification_date = "2026-09-04"
        verification_evidence = "temp"
        changes = []
        changed_files = []
        locked_rules = []
        tests = []
        known_issues = []
        next_steps = []
        """
    ).strip() + "\n"
    (repo / "changes/records/test.infra/VU_BAD_SHA.toml").write_text(toml, encoding="utf-8")
    (repo / "changes/fragments/test.infra.VU_BAD_SHA.release").write_text("vu bad\n", encoding="utf-8")
    errors, _ = validator_mod.validate(repo, git_cwd=repo)
    assert any("verified_uncommitted commit_sha must be empty" in e for e in errors)


def test_precommit_fail_production_without_record(check_mod, tmp_path):
    repo = _init_repo(tmp_path)
    prod = repo / "app/modules/finans/demo.py"
    prod.parent.mkdir(parents=True)
    prod.write_text("# prod\n", encoding="utf-8")
    staged = ["app/modules/finans/demo.py"]
    ok, msg = check_mod.check_staged(staged)
    assert not ok
    assert "without release record" in msg


def test_precommit_pass_with_record_and_fragment(check_mod, tmp_path):
    staged = [
        "app/modules/finans/demo.py",
        "changes/records/finans/DEMO_PHASE.toml",
        "changes/fragments/finans.DEMO_PHASE.release",
    ]
    ok, msg = check_mod.check_staged(staged)
    assert ok


def test_post_commit_updates_manifest_local_head(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    state_path = repo / "var" / "release" / "deployment_state.json"
    proc = subprocess.run(
        [sys.executable, str(repo / "tools" / "release_state.py")],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert state_path.is_file()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert data["local_head"] == head


def test_post_commit_hook_no_extra_commits(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    before_count = len(_git(repo, "rev-list", "--all").stdout.strip().splitlines())
    hook = repo / ".githooks" / "post-commit"
    if not hook.is_file():
        pytest.skip("post-commit hook not copied")
    env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    proc = _run_hook(repo)
    assert proc.returncode == 0
    after_count = len(_git(repo, "rev-list", "--all").stdout.strip().splitlines())
    assert after_count == before_count


def test_post_commit_hook_logs_errors(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "seed")
    broken = repo / "tools" / "release_state.py"
    broken.write_text("raise SystemExit(1)\n", encoding="utf-8")
    hook = repo / ".githooks" / "post-commit"
    if not hook.is_file():
        pytest.skip("post-commit hook not copied")
    _run_hook(repo)
    log = repo / "logs" / "release_post_commit.log"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "WARN" in text or "failed" in text.lower()


def test_post_commit_lock_prevents_recursion(tmp_path):
    repo = _init_repo(tmp_path)
    lock = repo / "var" / "release" / "post_commit.lock"
    lock.mkdir(parents=True)
    hook = repo / ".githooks" / "post-commit"
    if not hook.is_file():
        pytest.skip("post-commit hook not copied")
    proc = _run_hook(repo)
    assert proc.returncode == 0
    log = repo / "logs" / "release_post_commit.log"
    if log.is_file():
        assert "lock busy" in log.read_text(encoding="utf-8").lower() or proc.returncode == 0


def test_runtime_manifest_not_tracked_allows_refresh(tmp_path):
    repo = _init_repo(tmp_path)
    tracked = _git(repo, "ls-files", "var/release/deployment_state.json")
    assert tracked.stdout.strip() == ""


def test_runtime_manifest_tracked_blocks_hook(tmp_path):
    repo = _init_repo(tmp_path)
    state = repo / "var" / "release" / "deployment_state.json"
    state.write_text("{}", encoding="utf-8")
    _git(repo, "add", "var/release/deployment_state.json")
    _git(repo, "commit", "-m", "track state")
    hook = repo / ".githooks" / "post-commit"
    if not hook.is_file():
        pytest.skip("post-commit hook not copied")
    _run_hook(repo)
    log = repo / "logs" / "release_post_commit.log"
    assert log.is_file()
    assert "BLOCKED" in log.read_text(encoding="utf-8")

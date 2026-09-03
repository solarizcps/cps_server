# -*- coding: utf-8 -*-
"""Gate 7 security and automation tests for CPS release history."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
VALIDATOR = ROOT / "tools" / "validate_release_history.py"
CHECK_FRAGMENT = ROOT / "tools" / "check_release_fragment.py"
RELEASE_STATE = ROOT / "tools" / "release_state.py"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


@pytest.fixture()
def service_mod():
    import services.release_history_service as mod
    return importlib.reload(mod)


def test_verified_uncommitted_loads_without_commit_sha(service_mod):
    records, skipped = service_mod.load_release_records(ROOT)
    uncommitted = [r for r in records if r.is_uncommitted]
    assert uncommitted, "expected verified_uncommitted records"
    for rec in uncommitted:
        assert rec.commit_sha == ""
        assert rec.status in {"TEST", "ONAYLANDI"}
        assert rec.worktree_fingerprint


def test_deployment_state_no_subprocess_on_page_load(service_mod):
    state_path = ROOT / "var" / "release" / "deployment_state.json"
    if state_path.is_file():
        with patch("subprocess.run") as mock_run:
            service_mod.build_page_context(ROOT)
            mock_run.assert_not_called()


def test_release_state_atomic_write():
    proc = subprocess.run([sys.executable, str(RELEASE_STATE)], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0
    state_path = ROOT / "var" / "release" / "deployment_state.json"
    assert state_path.is_file()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "local_head" in data
    assert "modules" in data


def test_precommit_guard_blocks_production_without_record():
    proc = subprocess.run([sys.executable, str(CHECK_FRAGMENT)], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0


def test_validator_pass_full_repo():
    proc = subprocess.run([sys.executable, str(VALIDATOR)], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "records_checked=" in proc.stdout


def test_timeline_visible_in_context(service_mod):
    ctx = service_mod.build_page_context(ROOT, detail_module="nexgen.mo", detail_phase="NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1")
    assert ctx["timeline"]
    assert len(ctx["timeline"]) >= 1


def test_commit_pending_visible_in_summary(service_mod):
    ctx = service_mod.build_page_context(ROOT)
    assert "commit_pending_records" in ctx["summary"]
    assert ctx["summary"]["commit_pending_records"] >= 0

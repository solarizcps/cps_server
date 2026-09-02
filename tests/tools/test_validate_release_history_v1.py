# -*- coding: utf-8 -*-
"""CPS release history validator tests (V1)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "tools" / "validate_release_history.py"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_release_history", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _copy_fixture_tree() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="cps_rh_v1_"))
    for rel in (
        "docs/release-history/schema.toml",
        "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml",
        "changes/fragments/nexgen.mo.NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.release",
    ):
        src = ROOT / rel
        dst = tmp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return tmp


@pytest.fixture(scope="module")
def validator_mod():
    return _load_validator_module()


def test_t1_validator_pass_on_canonical_repo(validator_mod):
    errors, info = validator_mod.validate(ROOT)
    assert not errors, errors
    assert any("VALIDATOR" not in line and "record OK" in line for line in info)


def test_t2_duplicate_module_version_fails(validator_mod):
    tmp = _copy_fixture_tree()
    try:
        dup = tmp / "changes/records/nexgen.mo/DUP_VERSION.toml"
        dup.write_text(
            (ROOT / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml")
            .read_text(encoding="utf-8")
            .replace(
                "NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1",
                "NEXGEN_DIRECT_SIPARIS_DUP_VERSION_V1",
            ),
            encoding="utf-8",
        )
        frag = tmp / "changes/fragments/nexgen.mo.NEXGEN_DIRECT_SIPARIS_DUP_VERSION_V1.release"
        frag.write_text("duplicate version fixture\n", encoding="utf-8")
        errors, _ = validator_mod.validate(tmp)
        assert any("duplicate module+version" in err for err in errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_t3_missing_required_field_fails(validator_mod):
    tmp = _copy_fixture_tree()
    try:
        record = tmp / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml"
        text = record.read_text(encoding="utf-8")
        text = text.replace("commit_sha = ", "# commit_sha = ")
        record.write_text(text, encoding="utf-8")
        errors, _ = validator_mod.validate(tmp)
        assert any("missing required field 'commit_sha'" in err for err in errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_t4_absolute_path_fails(validator_mod):
    tmp = _copy_fixture_tree()
    try:
        record = tmp / "changes/records/nexgen.mo/NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.toml"
        text = record.read_text(encoding="utf-8")
        text = text.replace(
            "app/modules/nexgen/musteri_pazarlama_routes.py",
            "C:\\\\Solariz_CPS_SERVER\\\\app\\\\modules\\\\nexgen\\\\musteri_pazarlama_routes.py",
        )
        record.write_text(text, encoding="utf-8")
        errors, _ = validator_mod.validate(tmp)
        assert any("forbidden path" in err for err in errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_t5_missing_fragment_fails(validator_mod):
    tmp = _copy_fixture_tree()
    try:
        frag = tmp / "changes/fragments/nexgen.mo.NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.release"
        frag.unlink()
        errors, _ = validator_mod.validate(tmp)
        assert any("missing matching fragment" in err for err in errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_t6_validator_script_exit_zero():
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "VALIDATOR PASS" in proc.stdout


def test_t7_towncrier_build_temp_output():
    venv_py = Path(tempfile.gettempdir()) / "cps_towncrier_smoke_v1" / "Scripts" / "python.exe"
    if not venv_py.is_file():
        pytest.skip("isolated towncrier venv not present")
    tmp = Path(tempfile.mkdtemp(prefix="cps_tc_build_"))
    try:
        shutil.copy2(ROOT / "towncrier.toml", tmp / "towncrier.toml")
        dst_frag = tmp / "changes" / "fragments"
        dst_frag.mkdir(parents=True)
        shutil.copy2(
            ROOT / "changes/fragments/nexgen.mo.NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.release",
            dst_frag / "nexgen.mo.NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1.release",
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [str(venv_py), "-m", "towncrier", "build", "--version", "1.3.0", "--draft"],
            cwd=str(tmp),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Sipariş Talebi" in proc.stdout or "Geliştirmeler" in proc.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_t8_cps_release_history_module_in_allowlist(validator_mod):
    schema_path = ROOT / "docs/release-history/schema.toml"
    text = schema_path.read_text(encoding="utf-8")
    assert "cps.release.history" in text
    errors, _ = validator_mod.validate(ROOT)
    assert not any("cps.release.history" in err and "not in allowlist" in err for err in errors)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only validator for CPS release history TOML records and Towncrier fragments."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "release-history" / "schema.toml"
RECORDS_DIR = ROOT / "changes" / "records"
FRAGMENTS_DIR = ROOT / "changes" / "fragments"


def _load_schema() -> dict:
    with SCHEMA_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _is_forbidden_path(value: str, forbidden_tokens: list[str]) -> bool:
    text = value.strip()
    if not text:
        return True
    if re.match(r"^[A-Za-z]:\\", text):
        return True
    if text.startswith("/") and not text.startswith("app/"):
        return True
    if text.startswith("\\"):
        return True
    lowered = text.replace("\\", "/").lower()
    for token in forbidden_tokens:
        if token.replace("\\", "/").lower() in lowered:
            return True
    return False


def validate(root: Path | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, info_messages)."""
    base = root or ROOT
    schema = _load_schema()
    required_fields: list[str] = schema["required_fields"]["fields"]
    list_fields: list[str] = schema["list_fields"]["fields"]
    status_values: set[str] = set(schema["status_enum"]["values"])
    allowlist: set[str] = set(schema["module_allowlist"]["modules"])
    fragment_cfg = schema["fragment"]
    type_extension = fragment_cfg["type_extension"]
    sha_pattern = re.compile(schema["validation"]["commit_sha_pattern"])
    forbidden_tokens: list[str] = schema["validation"]["forbidden_path_tokens"]
    optional_list_fields: list[str] = list(schema.get("optional_list_fields", {}).get("fields", []))

    errors: list[str] = []
    info: list[str] = []
    records_dir = base / "changes" / "records"
    fragments_dir = base / "changes" / "fragments"

    if not records_dir.is_dir():
        errors.append(f"Missing records directory: {records_dir}")
        return errors, info

    record_paths = sorted(records_dir.glob("**/*.toml"))
    if not record_paths:
        errors.append(f"No TOML records found under {records_dir}")
        return errors, info

    seen_module_version: set[tuple[str, str]] = set()
    seen_module_phase: set[tuple[str, str]] = set()

    for record_path in record_paths:
        rel = record_path.relative_to(base)
        try:
            data = _load_toml(record_path)
        except Exception as exc:  # noqa: BLE001 - surface parse errors
            errors.append(f"{rel}: invalid TOML ({exc})")
            continue

        for field in required_fields:
            if field not in data:
                errors.append(f"{rel}: missing required field '{field}'")

        for field in list_fields:
            if field not in data:
                errors.append(f"{rel}: missing required list field '{field}'")
            elif not isinstance(data[field], list):
                errors.append(f"{rel}: field '{field}' must be a list")

        module = data.get("module")
        version = data.get("version")
        phase_code = data.get("phase_code")
        status = data.get("status")
        commit_sha = data.get("commit_sha")

        if module is not None and module not in allowlist:
            errors.append(f"{rel}: module '{module}' not in allowlist")

        if status is not None and status not in status_values:
            errors.append(f"{rel}: invalid status '{status}'")

        if commit_sha is not None and not sha_pattern.match(str(commit_sha)):
            errors.append(f"{rel}: invalid commit_sha '{commit_sha}'")

        def _git_commit_exists(sha: str) -> bool:
            if base != ROOT:
                return True
            proc = subprocess.run(
                ["git", "cat-file", "-t", sha],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            return proc.returncode == 0 and proc.stdout.strip() == "commit"

        if commit_sha is not None and sha_pattern.match(str(commit_sha)):
            if not _git_commit_exists(str(commit_sha)):
                errors.append(f"{rel}: commit_sha not found in git: {commit_sha}")

        for opt_field in optional_list_fields:
            values = data.get(opt_field)
            if values is None:
                continue
            if not isinstance(values, list):
                errors.append(f"{rel}: optional field '{opt_field}' must be a list")
                continue
            for item in values:
                if not isinstance(item, str):
                    errors.append(f"{rel}: {opt_field} entries must be strings")
                    continue
                if not sha_pattern.match(item):
                    errors.append(f"{rel}: invalid {opt_field} sha '{item}'")
                    continue
                if not _git_commit_exists(item):
                    errors.append(f"{rel}: {opt_field} sha not found in git: {item}")

        if module is not None and version is not None:
            key = (str(module), str(version))
            if key in seen_module_version:
                errors.append(f"{rel}: duplicate module+version ({module}, {version})")
            seen_module_version.add(key)

        if module is not None and phase_code is not None:
            key = (str(module), str(phase_code))
            if key in seen_module_phase:
                errors.append(f"{rel}: duplicate module+phase_code ({module}, {phase_code})")
            seen_module_phase.add(key)

        for field in list_fields:
            values = data.get(field)
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, str):
                    errors.append(f"{rel}: {field} entries must be strings")
                    continue
                if _is_forbidden_path(item, forbidden_tokens):
                    errors.append(f"{rel}: forbidden path or token in {field}: {item!r}")

        for field in ("summary", "evidence_summary", "root_cause", "migration"):
            value = data.get(field)
            if isinstance(value, str) and _is_forbidden_path(value, forbidden_tokens):
                errors.append(f"{rel}: forbidden path or token in {field}")

        if module and phase_code:
            fragment = fragments_dir / f"{module}.{phase_code}.{type_extension}"
            if not fragment.is_file():
                errors.append(
                    f"{rel}: missing matching fragment {fragment.relative_to(base)}"
                )
            else:
                info.append(f"fragment parity OK: {fragment.relative_to(base)}")

        info.append(f"record OK: {rel} [{module} {version} {status}]")

    return errors, info


def main() -> int:
    errors, info = validate()
    for line in info:
        print(line)
    if errors:
        print("VALIDATOR FAIL", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("VALIDATOR PASS")
    print(f"  records_checked={sum(1 for line in info if line.startswith('record OK:'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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





def _git_run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git_commit_exists(sha: str, git_cwd: Path) -> bool:
    if not sha:
        return False
    proc = _git_run(["cat-file", "-t", sha], git_cwd)
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


def _git_head(git_cwd: Path) -> str:
    proc = _git_run(["rev-parse", "HEAD"], git_cwd)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_is_ancestor(ancestor: str, descendant: str, git_cwd: Path) -> bool | None:
    if not ancestor or not descendant:
        return None
    proc = _git_run(["merge-base", "--is-ancestor", ancestor, descendant], git_cwd)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def validate(root: Path | None = None, *, git_cwd: Path | None = None) -> tuple[list[str], list[str]]:

    """Return (errors, info_messages)."""

    base = root or ROOT

    git_base = git_cwd or base

    if git_cwd is None and base != ROOT and (base / ".git").is_dir():

        git_base = base

    elif git_cwd is None:

        git_base = ROOT

    schema = _load_schema()

    required_fields: list[str] = schema["required_fields"]["fields"]

    list_fields: list[str] = schema["list_fields"]["fields"]

    status_values: set[str] = set(schema["status_enum"]["values"])

    allowlist: set[str] = set(schema["module_allowlist"]["modules"])

    source_types: set[str] = set(schema.get("source_type_enum", {}).get("values", ["commit"]))

    vu_required: list[str] = list(schema.get("verified_uncommitted_required", {}).get("fields", []))

    vu_status: set[str] = set(schema.get("verified_uncommitted_status_enum", {}).get("values", {"TEST", "ONAYLANDI"}))

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

    head_sha = _git_head(git_base) if (git_base / ".git").is_dir() else ""

    for record_path in record_paths:

        rel = record_path.relative_to(base)

        try:

            data = _load_toml(record_path)

        except Exception as exc:  # noqa: BLE001 - surface parse errors

            errors.append(f"{rel}: invalid TOML ({exc})")

            continue



        source_type = str(data.get("source_type", "commit"))

        if source_type not in source_types:

            errors.append(f"{rel}: invalid source_type '{source_type}'")



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

        commit_sha = str(data.get("commit_sha", "")).strip()



        if module is not None and module not in allowlist:

            errors.append(f"{rel}: module '{module}' not in allowlist")



        if status is not None and status not in status_values:

            errors.append(f"{rel}: invalid status '{status}'")



        if source_type == "verified_uncommitted":

            if status not in vu_status:

                errors.append(f"{rel}: verified_uncommitted status must be TEST or ONAYLANDI, got '{status}'")

            if status == "KILITLI":

                errors.append(f"{rel}: verified_uncommitted cannot be KILITLI")

            for vu_field in vu_required:

                if not str(data.get(vu_field, "")).strip():

                    errors.append(f"{rel}: verified_uncommitted missing '{vu_field}'")

            if commit_sha:

                errors.append(f"{rel}: verified_uncommitted commit_sha must be empty")

        else:

            if not commit_sha:

                errors.append(f"{rel}: commit source requires commit_sha")

            elif not sha_pattern.match(commit_sha):

                errors.append(f"{rel}: invalid commit_sha '{commit_sha}'")

            elif not _git_commit_exists(commit_sha, git_base):

                errors.append(f"{rel}: commit_sha not found in git: {commit_sha}")

            elif head_sha:

                ancestor = _git_is_ancestor(commit_sha, head_sha, git_base)

                if ancestor is False:

                    msg = f"{rel}: commit_sha NOT_ANCESTOR of HEAD ({commit_sha[:12]}.. vs {head_sha[:12]}..)"

                    if status == "KILITLI":

                        errors.append(msg)

                    else:

                        errors.append(msg)

                elif ancestor is None:

                    errors.append(f"{rel}: cannot verify commit_sha ancestry for HEAD")



        if source_type == "commit" and commit_sha and sha_pattern.match(commit_sha):

            pass  # already checked above



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

                if opt_field == "related_commits" or opt_field == "deploy_events":

                    if opt_field == "related_commits" and not sha_pattern.match(item):

                        errors.append(f"{rel}: invalid {opt_field} sha '{item}'")

                    elif opt_field == "related_commits" and not _git_commit_exists(item, git_base):

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



        for field in ("summary", "evidence_summary", "root_cause", "migration", "verification_evidence", "current_work"):

            value = data.get(field)

            if isinstance(value, str) and value.strip() and _is_forbidden_path(value, forbidden_tokens):

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

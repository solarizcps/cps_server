#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-commit guard: staged production changes require matching release record.

Only inspects `git diff --cached` — unrelated dirty worktree files are ignored.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(os.environ.get("CPS_REPO_ROOT", Path(__file__).resolve().parents[1]))

PRODUCTION_PREFIXES = (
    "app/modules/",
    "app/templates/",
    "app/static/",
    "app/migrations/",
)

EXEMPT_EXACT = frozenset({
    "app/services/release_history_service.py",
})

EXEMPT_PREFIXES = (
    "docs/",
    "tests/",
    "changes/",
    "tools/validate_release_history.py",
    "tools/release_state.py",
    "tools/check_release_fragment.py",
    "tools/record_deploy_event.py",
    "tools/deploy_cps_with_release_state.ps1",
    "AGENTS.md",
)


def _staged_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _head_file_content(path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _is_production(path: str) -> bool:
    if path in EXEMPT_EXACT:
        return False
    return any(path.startswith(p) for p in PRODUCTION_PREFIXES)


def _is_exempt(path: str) -> bool:
    if path in EXEMPT_EXACT:
        return True
    if any(path.startswith(p) for p in EXEMPT_PREFIXES):
        return True
    if path.endswith(".md") and path.startswith("docs/"):
        return True
    return False


def _has_release_metadata(staged: list[str]) -> bool:
    for path in staged:
        if path.startswith("changes/records/") and path.endswith(".toml"):
            return True
        if path.startswith("changes/fragments/") and path.endswith(".release"):
            return True
    return False


def _parse_locked_rules(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    rules = data.get("locked_rules")
    if not isinstance(rules, list):
        return []
    return [str(r).strip() for r in rules if str(r).strip()]


def _has_locked_rules_approval(text: str) -> bool:
    try:
        data = tomllib.loads(text)
    except Exception:
        return False
    if data.get("locked_rules_approval") is True:
        return True
    approved_by = str(data.get("approved_by", "")).strip()
    breaking = data.get("breaking_rules")
    return bool(approved_by) and isinstance(breaking, list) and len(breaking) > 0


def _check_staged_toml(staged: list[str]) -> tuple[bool, str]:
    record_paths = [p for p in staged if p.startswith("changes/records/") and p.endswith(".toml")]
    for path in record_paths:
        full = ROOT / path
        if not full.is_file():
            continue
        text = full.read_text(encoding="utf-8")
        try:
            tomllib.loads(text)
        except Exception as exc:
            return False, f"malformed TOML in staged record {path}: {exc}"

        new_rules = _parse_locked_rules(text)
        old_text = _head_file_content(path)
        if old_text is None:
            continue
        old_rules = _parse_locked_rules(old_text)
        if new_rules != old_rules and not _has_locked_rules_approval(text):
            return False, (
                f"locked_rules changed in {path} without locked_rules_approval or approved_by+breaking_rules"
            )
    return True, "toml ok"


def check_staged(staged: list[str] | None = None) -> tuple[bool, str]:
    staged = staged if staged is not None else _staged_files()
    if not staged:
        return True, "no staged files"

    toml_ok, toml_msg = _check_staged_toml(staged)
    if not toml_ok:
        return False, f"PRECOMMIT GUARD FAIL: {toml_msg}"

    production = [p for p in staged if _is_production(p) and not _is_exempt(p)]
    if not production:
        return True, "no staged production files"

    if _has_release_metadata(staged):
        return True, "release metadata present"

    msg = (
        "PRECOMMIT GUARD FAIL: staged production without release record/fragment. "
        f"Files: {', '.join(production[:5])}"
    )
    return False, msg


def main() -> int:
    ok, msg = check_staged()
    if ok:
        return 0
    print(msg, file=sys.stderr)
    print("Ekleyin: changes/records/<module>/<PHASE>.toml + changes/fragments/<module>.<PHASE>.release", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

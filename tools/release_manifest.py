# -*- coding: utf-8 -*-
"""Release manifest — load, validate, and create deploy manifests."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REQUIRED_FIELDS = [
    'release_id',
    'module',
    'base_commit',
    'tested_commit',
    'target_branch',
    'allowed_files',
    'forbidden_paths',
    'schema_contract',
    'required_migrations',
    'test_result',
    'test_pass_count',
    'test_fail_count',
    'created_at',
    'pilot_baseline',
]

FULL_HASH_LEN = 40


class ManifestError(Exception):
    pass


def load_manifest(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ManifestError(f'Manifest file not found: {p}')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ManifestError(f'Manifest JSON parse error: {exc}') from exc
    return data


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f'missing field: {field}')

    if errors:
        return errors  # stop early — further checks need the fields

    # commit hash length checks — no abbreviations
    for field in ('tested_commit', 'base_commit', 'pilot_baseline'):
        val = manifest.get(field, '')
        if not isinstance(val, str) or len(val) != FULL_HASH_LEN:
            errors.append(
                f'{field} must be a 40-char full hash, got: {val!r}'
            )

    # test_result must be PASS
    if manifest.get('test_result') != 'PASS':
        errors.append(
            f'test_result must be PASS, got: {manifest.get("test_result")!r}'
        )

    # test_fail_count must be 0
    fail_count = manifest.get('test_fail_count', -1)
    if int(fail_count) != 0:
        errors.append(f'test_fail_count must be 0, got: {fail_count}')

    # allowed_files must be non-empty list
    if not isinstance(manifest.get('allowed_files'), list) or not manifest['allowed_files']:
        errors.append('allowed_files must be a non-empty list')

    # forbidden_paths must be list (may be empty)
    if not isinstance(manifest.get('forbidden_paths'), list):
        errors.append('forbidden_paths must be a list')

    # schema_contract must be an absolute path or relative that exists from repo root
    contract = manifest.get('schema_contract', '')
    if not contract:
        errors.append('schema_contract must not be empty')

    # required_migrations must be list
    if not isinstance(manifest.get('required_migrations'), list):
        errors.append('required_migrations must be a list')

    return errors


def require_valid_manifest(manifest: dict[str, Any]) -> None:
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestError('Manifest validation failed:\n  ' + '\n  '.join(errors))


def create_manifest(
    *,
    release_id: str,
    module: str,
    base_commit: str,
    tested_commit: str,
    target_branch: str,
    allowed_files: list[str],
    forbidden_paths: list[str],
    schema_contract: str,
    required_migrations: list[str],
    test_result: str,
    test_pass_count: int,
    test_fail_count: int,
    pilot_baseline: str,
) -> dict[str, Any]:
    return {
        'release_id': release_id,
        'module': module,
        'base_commit': base_commit,
        'tested_commit': tested_commit,
        'target_branch': target_branch,
        'allowed_files': allowed_files,
        'forbidden_paths': forbidden_paths,
        'schema_contract': schema_contract,
        'required_migrations': required_migrations,
        'test_result': test_result,
        'test_pass_count': test_pass_count,
        'test_fail_count': test_fail_count,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'pilot_baseline': pilot_baseline,
    }


def save_manifest(manifest: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

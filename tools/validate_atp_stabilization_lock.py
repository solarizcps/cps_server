#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed ATP production stabilization lock validator."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs' / 'atp-lock' / 'atp_stabilization_manifest.sha256'
TOUCHPOINTS = ROOT / 'docs' / 'atp-lock' / 'atp_touchpoints.sha256'
INVENTORY = ROOT / 'docs' / 'atp-lock' / 'atp_inventory.json'

FORBIDDEN_MANIFEST_RE = re.compile(
    r'(\.env$|\.dpapi$|mock_data\.db$|/logs/|__pycache__|\.pyc$|/var/release|/secrets/)',
    re.I,
)

FORBIDDEN_FILENAME_RE = re.compile(
    r'(^\.env$|\.dpapi$|secret|password|credentials)',
    re.I,
)

ALLOWLIST_PREFIXES = (
    'docs/atp-lock/atp_stabilization_manifest.sha256',
)

# Directories scanned for undeclared new ATP dependencies (resolved from ROOT at runtime).
WATCH_DIR_REL = (
    'app/modules/planlama',
    'app/static/js',
    'app/static/css',
    'app/tools',
    'tests/planlama',
)

WATCH_FILE_PATTERNS = (
    re.compile(r'^app/modules/planlama/arac_.*\.py$'),
    re.compile(r'^app/modules/planlama/arac_operasyonu/.*'),
    re.compile(r'^app/modules/planlama/road_routing/.*'),
    re.compile(r'^app/static/(js|css)/planlama_arac_takip.*'),
    re.compile(r'^app/tools/arac_gps_.*\.py$'),
    re.compile(r'^app/tools/atp_.*\.py$'),
    re.compile(r'^tests/planlama/(test_atp_|test_arac_|test_filom_|test_google_route|test_planlama_arac_takip|atp_|conftest\.py|_parity_helper\.py)'),
    re.compile(r'^app/migrations/.*arac.*\.py$'),
    re.compile(r'^app/migrations/189_planlama_arac_takip.*\.py$'),
    re.compile(r'^Start-Arac-GPS-Worker\.ps1$'),
    re.compile(r'^app/templates/planlama/arac_takip_plan\.html$'),
)


def _norm(rel: str) -> str:
    return rel.replace('\\', '/')


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _parse_manifest() -> tuple[str, dict[str, str]]:
    if not MANIFEST.is_file():
        raise FileNotFoundError(f'missing manifest: {MANIFEST}')
    baseline = ''
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding='utf-8').splitlines():
        if line.startswith('# lock_baseline_commit='):
            baseline = line.split('=', 1)[1].strip()
            continue
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f'invalid manifest line: {line!r}')
        rel, digest = parts
        rel = _norm(rel)
        if FORBIDDEN_MANIFEST_RE.search(rel):
            raise ValueError(f'forbidden path in manifest: {rel}')
        if FORBIDDEN_FILENAME_RE.search(Path(rel).name):
            raise ValueError(f'forbidden token in manifest filename: {rel}')
        entries[rel] = digest.lower()
    if not baseline:
        raise ValueError('manifest missing lock_baseline_commit header')
    return baseline, entries


def _parse_touchpoints() -> list[dict]:
    if not TOUCHPOINTS.is_file():
        raise FileNotFoundError(f'missing touchpoints: {TOUCHPOINTS}')
    items: list[dict] = []
    for line in TOUCHPOINTS.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) != 4:
            raise ValueError(f'invalid touchpoint line: {line!r}')
        path, label, span, digest = parts
        item = {'path': _norm(path), 'label': label, 'digest': digest.lower()}
        if span.startswith('L') and '-L' in span:
            a, b = span[1:].split('-L', 1)
            item['start_line'] = int(a)
            item['end_line'] = int(b)
        else:
            item['block'] = True
        items.append(item)
    return items


def _verify_touchpoints(errors: list[str]) -> None:
    for tp in _parse_touchpoints():
        path = ROOT / tp['path']
        if not path.is_file():
            errors.append(f'touchpoint file missing: {tp["path"]}')
            continue
        lines = path.read_text(encoding='utf-8').splitlines()
        if tp.get('block'):
            if tp['label'] == 'nexgen_manifest_arac_migration_block':
                text = _extract_nexgen_arac_block(lines)
                actual = _sha256_text(text)
                if actual != tp['digest']:
                    errors.append(
                        f'touchpoint hash mismatch: {tp["path"]} [{tp["label"]}]',
                    )
            continue
        snippet = '\n'.join(lines[tp['start_line'] - 1:tp['end_line']]) + '\n'
        actual = _sha256_text(snippet)
        if actual != tp['digest']:
            errors.append(
                f'touchpoint hash mismatch: {tp["path"]} [{tp["label"]}] '
                f'L{tp["start_line"]}-L{tp["end_line"]}',
            )


def _extract_nexgen_arac_block(lines: list[str]) -> str:
    marker = '176_arac_takip_v13'
    start_idx = next(i for i, line in enumerate(lines) if marker in line)
    end_idx = next(
        i for i, line in enumerate(lines[start_idx:], start_idx)
        if '188_arac_plan_is_zaman_alanlari' in line
    )
    while end_idx < len(lines) and lines[end_idx].strip() != '),':
        end_idx += 1
    block = lines[start_idx:end_idx + 1]
    return '\n'.join(block).strip() + '\n'


def _discover_watch_files() -> set[str]:
    found: set[str] = set()
    root_files = [
        ROOT / 'Start-Arac-GPS-Worker.ps1',
        ROOT / 'Register-Arac-GPS-Worker-Task.ps1',
    ]
    for path in root_files:
        if path.is_file():
            found.add(_norm(str(path.relative_to(ROOT))))

    for rel_dir in WATCH_DIR_REL:
        base = ROOT / rel_dir
        if not base.is_dir():
            continue
        for path in base.rglob('*'):
            if not path.is_file():
                continue
            rel = _norm(str(path.relative_to(ROOT)))
            if FORBIDDEN_MANIFEST_RE.search(rel):
                continue
            if any(p.match(rel) for p in WATCH_FILE_PATTERNS):
                found.add(rel)
    return found


def validate_atp_lock(*, strict_new_deps: bool = True) -> tuple[list[str], int]:
    errors: list[str] = []
    try:
        baseline, entries = _parse_manifest()
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)], 0

    for rel, expected in entries.items():
        if any(rel.startswith(p) for p in ALLOWLIST_PREFIXES):
            continue
        path = ROOT / rel
        if not path.is_file():
            errors.append(f'missing manifest file: {rel}')
            continue
        actual = _sha256_file(path)
        if actual != expected:
            errors.append(f'hash mismatch: {rel}')

    _verify_touchpoints(errors)

    if strict_new_deps:
        discovered = _discover_watch_files()
        manifest_set = set(entries.keys())
        extra = sorted(discovered - manifest_set)
        for rel in extra:
            errors.append(f'review-required undeclared ATP dependency: {rel}')

    return errors, len(entries)


def main() -> int:
    errors, checked = validate_atp_lock()
    if errors:
        print('ATP_STABILIZATION_LOCK=FAIL', file=sys.stderr)
        for err in errors:
            print(f'  - {err}', file=sys.stderr)
        print(f'  ATP_FILES_CHECKED={checked}', file=sys.stderr)
        print('  ATP_DIFF=nonzero', file=sys.stderr)
        return 1

    print('ATP_STABILIZATION_LOCK=PASS')
    print(f'ATP_FILES_CHECKED={checked}')
    print('ATP_DIFF=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forensic ATP inventory + SHA256 manifest generator (baseline 21b8a21)."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = '21b8a2100ba34db92172f300f246c2a67b319e94'
# Fixed stamp — manifest body hashes are content-derived; header stamp is stable for determinism.
GENERATED_AT_UTC = '2026-09-07T08:00:00Z'
MANIFEST_PATH = ROOT / 'docs' / 'atp-lock' / 'atp_stabilization_manifest.sha256'
TOUCHPOINTS_PATH = ROOT / 'docs' / 'atp-lock' / 'atp_touchpoints.sha256'
INVENTORY_PATH = ROOT / 'docs' / 'atp-lock' / 'atp_inventory.json'

MANIFEST_EXCLUDE = {
    'docs/atp-lock/atp_stabilization_manifest.sha256',
}

INVENTORY_EXCLUDE = MANIFEST_EXCLUDE | {
    'docs/atp-lock/atp_inventory.json',
}

FORBIDDEN_PATH_RE = re.compile(
    r'(\.env$|\.dpapi$|mock_data\.db$|/logs/|__pycache__|\.pyc$|/var/|/screenshots/)',
    re.I,
)

SEED_FILES = [
    'app/modules/planlama/arac_takip_routes.py',
    'app/templates/planlama/arac_takip_plan.html',
    'app/modules/planlama/arac_operasyonu/services/turkcell_filom_adapter.py',
    'app/tools/arac_gps_poll_worker.py',
    'app/tools/arac_gps_poll_once.py',
    'Start-Arac-GPS-Worker.ps1',
    'Register-Arac-GPS-Worker-Task.ps1',
]

ATP_MODULE_PREFIXES = (
    'modules.planlama.arac_',
    'modules.planlama.arac_operasyonu',
    'modules.planlama.road_routing.',
)

MIGRATION_GLOB = 'app/migrations/*arac*'
MIGRATION_GLOB2 = 'app/migrations/189_planlama_arac_takip_rol32_yetki.py'

TEST_PATTERNS = (
    'tests/planlama/test_atp_*.py',
    'tests/planlama/test_arac_*.py',
    'tests/planlama/test_filom_*.py',
    'tests/planlama/test_google_route*.py',
    'tests/planlama/test_google_routes_*.py',
    'tests/planlama/test_planlama_arac_takip*.js',
    'tests/planlama/atp_*.py',
    'tests/planlama/_parity_helper.py',
    'tests/planlama/conftest.py',
)

LOCK_TOOLING_PREFIXES = (
    'tools/build_atp_lock_manifest.py',
    'tools/validate_atp_stabilization_lock.py',
    'docs/atp-lock/',
    'tests/tools/test_atp_stabilization_lock_v1.py',
)

TOUCHPOINT_SPECS = [
    ('app/app.py', 38, 73, 'blueprint_registration'),
    ('app/templates/base.html', 51, 51, 'sidebar_context_arac_takip'),
    ('app/templates/base.html', 1242, 1242, 'sidebar_link_arac_takip'),
]

NEXGEN_ARAC_MARKER = '176_arac_takip_v13'


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


def _module_to_path(module: str) -> str | None:
    if not module.startswith('modules.'):
        return None
    rel = 'app/' + module.replace('.', '/') + '.py'
    candidate = ROOT / rel
    if candidate.is_file():
        return _norm(rel)
    pkg_init = ROOT / ('app/' + module.replace('.', '/') + '/__init__.py')
    if pkg_init.is_file():
        return _norm(str(pkg_init.relative_to(ROOT)))
    return None


def _imports_in_file(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


def _trace_python_closure(seed_paths: set[str]) -> set[str]:
    queue = list(seed_paths)
    seen: set[str] = set()
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = ROOT / rel
        if not path.is_file() or not rel.endswith('.py'):
            continue
        for mod in _imports_in_file(path):
            if not any(mod.startswith(p) for p in ATP_MODULE_PREFIXES):
                continue
            resolved = _module_to_path(mod)
            if resolved and resolved not in seen:
                queue.append(resolved)
            parts = mod.split('.')
            for i in range(len(parts), 2, -1):
                sub = '.'.join(parts[:i])
                resolved = _module_to_path(sub)
                if resolved and resolved not in seen:
                    queue.append(resolved)
    return seen


def _static_from_template(template_rel: str) -> set[str]:
    path = ROOT / template_rel
    if not path.is_file():
        return set()
    text = path.read_text(encoding='utf-8')
    out: set[str] = set()
    for m in re.finditer(r"filename=['\"]((?:css|js)/planlama_arac_takip[^'\"]+)['\"]", text):
        out.add(_norm(f'app/static/{m.group(1)}'))
    return out


def _glob_paths(pattern: str) -> set[str]:
    return {_norm(str(p.relative_to(ROOT))) for p in ROOT.glob(pattern)}


def _extra_locked() -> list[str]:
    candidates = [
        'app/tools/atp_test_db_guard.py',
        'tools/build_atp_lock_manifest.py',
        'tools/validate_atp_stabilization_lock.py',
        'docs/atp-lock/ATP_STABILIZATION_LOCK_POLICY.md',
        'docs/atp-lock/ENFORCEMENT.md',
        'docs/atp-lock/atp_touchpoints.sha256',
        'tests/tools/test_atp_stabilization_lock_v1.py',
    ]
    return [c for c in candidates if (ROOT / c).is_file()]


def _nexgen_arac_block_hash() -> tuple[str, str]:
    path = ROOT / 'app/migrations/nexgen_manifest.py'
    lines = path.read_text(encoding='utf-8').splitlines()
    start_idx = next(i for i, line in enumerate(lines) if NEXGEN_ARAC_MARKER in line)
    end_idx = next(
        i for i, line in enumerate(lines[start_idx:], start_idx)
        if '188_arac_plan_is_zaman_alanlari' in line
    )
    while end_idx < len(lines) and lines[end_idx].strip() != '),':
        end_idx += 1
    block = lines[start_idx:end_idx + 1]
    text = '\n'.join(block).strip() + '\n'
    return 'nexgen_manifest_arac_migration_block', _sha256_text(text)


def _categorize_disjoint(all_files: set[str]) -> dict[str, list[str]]:
    lock_tooling = sorted(
        f for f in all_files
        if any(f == p or f.startswith(p) for p in LOCK_TOOLING_PREFIXES)
    )
    lock_set = set(lock_tooling)

    worker_ps1 = sorted(f for f in all_files if f.endswith('.ps1'))
    worker_py = sorted(
        f for f in all_files
        if f in {'app/tools/arac_gps_poll_worker.py', 'app/tools/arac_gps_poll_once.py', 'app/tools/atp_test_db_guard.py'}
    )
    worker_set = set(worker_ps1) | set(worker_py)

    migrations = sorted(f for f in all_files if f.startswith('app/migrations/') and 'arac' in f)
    mig_set = set(migrations)

    static_assets = sorted(
        f for f in all_files
        if '/static/css/planlama_arac_takip' in f or '/static/js/planlama_arac_takip' in f
    )
    static_set = set(static_assets)

    ui_template = sorted(f for f in all_files if f == 'app/templates/planlama/arac_takip_plan.html')
    ui_set = set(ui_template)

    tests = sorted(
        f for f in all_files
        if f.startswith('tests/planlama/') and f not in lock_set
    )
    test_set = set(tests)

    python_services = sorted(
        f for f in all_files
        if f not in lock_set and f not in worker_set and f not in mig_set
        and f not in static_set and f not in ui_set and f not in test_set
    )

    categories = {
        'python_services': python_services,
        'ui_template': ui_template,
        'static_assets': static_assets,
        'migrations': migrations,
        'worker_ps1': worker_ps1,
        'worker_py': worker_py,
        'tests_planlama': tests,
        'lock_tooling': lock_tooling,
    }
    covered = set().union(*categories.values())
    assert covered == all_files, f'uncategorized: {sorted(all_files - covered)}'
    assert sum(len(v) for v in categories.values()) == len(all_files)
    return categories


def build_inventory() -> dict:
    seeds = {_norm(p) for p in SEED_FILES}
    py_closure = _trace_python_closure(seeds)
    static_assets = _static_from_template('app/templates/planlama/arac_takip_plan.html')
    static_assets |= _glob_paths('app/static/css/planlama_arac_takip*.css')
    static_assets |= _glob_paths('app/static/js/planlama_arac_takip*.js')

    migrations = _glob_paths(MIGRATION_GLOB) | _glob_paths(MIGRATION_GLOB2)

    tests: set[str] = set()
    for pat in TEST_PATTERNS:
        tests |= _glob_paths(pat)

    files = set(seeds) | py_closure | static_assets | migrations | tests | set(_extra_locked())
    files = {f for f in files if not FORBIDDEN_PATH_RE.search(f)}
    files -= MANIFEST_EXCLUDE

    missing = sorted(f for f in files if not (ROOT / f).is_file())
    if missing:
        raise SystemExit(f'Missing inventory files: {missing[:5]} (+{len(missing) - 5})')

    hashes = {rel: _sha256_file(ROOT / rel) for rel in sorted(files)}
    categories = _categorize_disjoint(files)

    touchpoints = []
    for path, start, end, label in TOUCHPOINT_SPECS:
        lines = (ROOT / path).read_text(encoding='utf-8').splitlines()
        snippet = '\n'.join(lines[start - 1:end]) + '\n'
        touchpoints.append({
            'path': _norm(path),
            'label': label,
            'start_line': start,
            'end_line': end,
            'sha256': _sha256_text(snippet),
        })
    tp_label, tp_hash = _nexgen_arac_block_hash()
    touchpoints.append({
        'path': 'app/migrations/nexgen_manifest.py',
        'label': tp_label,
        'sha256': tp_hash,
    })

    manifest_membership = {
        'atp_stabilization_manifest.sha256': 'EXCLUDED (self-reference forbidden)',
        'atp_inventory.json': 'EXCLUDED (forensic metadata; volatile generated_at in JSON only)',
        'atp_touchpoints.sha256': 'INCLUDED' if 'docs/atp-lock/atp_touchpoints.sha256' in hashes else 'MISSING',
        'tools/validate_atp_stabilization_lock.py': 'INCLUDED',
        'tools/build_atp_lock_manifest.py': 'INCLUDED',
        'docs/atp-lock/ATP_STABILIZATION_LOCK_POLICY.md': 'INCLUDED',
        'docs/atp-lock/ENFORCEMENT.md': 'INCLUDED',
    }

    return {
        'baseline_commit': BASELINE_COMMIT,
        'generated_at_utc': GENERATED_AT_UTC,
        'unique_file_count': len(files),
        'touchpoint_count': len(touchpoints),
        'category_counts': {k: len(v) for k, v in categories.items()},
        'categories_disjoint': categories,
        'overlaps': 'none — categories are pairwise disjoint partitions of unique_file_count',
        'manifest_self_reference': manifest_membership,
        'seed_files': sorted(seeds),
        'files': hashes,
        'touchpoints': touchpoints,
    }


def write_outputs(inventory: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f'# ATP stabilization lock manifest\n'
        f'# lock_baseline_commit={BASELINE_COMMIT}\n'
        f'# generated_at_utc={GENERATED_AT_UTC}\n'
        f'# file_count={len(inventory["files"])}\n'
    )
    body = ''.join(f'{rel} {digest}\n' for rel, digest in inventory['files'].items())
    MANIFEST_PATH.write_text(header + body, encoding='utf-8')

    tp_header = (
        f'# ATP shared-file touchpoints (line-range hashes)\n'
        f'# lock_baseline_commit={BASELINE_COMMIT}\n'
    )
    tp_lines = []
    for tp in inventory['touchpoints']:
        if 'start_line' in tp:
            tp_lines.append(
                f'{tp["path"]}\t{tp["label"]}\tL{tp["start_line"]}-L{tp["end_line"]}\t{tp["sha256"]}\n',
            )
        else:
            tp_lines.append(f'{tp["path"]}\t{tp["label"]}\tblock\t{tp["sha256"]}\n')
    TOUCHPOINTS_PATH.write_text(tp_header + ''.join(tp_lines), encoding='utf-8')

    INVENTORY_PATH.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {MANIFEST_PATH} ({len(inventory["files"])} files)')
    print(f'Wrote {TOUCHPOINTS_PATH} ({len(inventory["touchpoints"])} touchpoints)')
    print(f'Wrote {INVENTORY_PATH}')


def main() -> int:
    inventory = build_inventory()
    write_outputs(inventory)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

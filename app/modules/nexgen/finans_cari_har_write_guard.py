# -*- coding: utf-8 -*-
"""Cari_Har write statik güvenlik taraması — P1 tek yazar kuralı."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

ALLOWED_PRODUCTION_WRITE_FILES = {
    'app/modules/nexgen/financial_posting_service.py',
}

EXCLUDED_PATH_PARTS = (
    '/backup/',
    '\\backup\\',
    'init_mock_db.py',
    'seed_performans.py',
    'migrations/',
    'migrations\\',
    '_test_',
    'tools/finans_1f1_posting_rollback.py',
    'tools\\finans_1f1_posting_rollback.py',
    'tools/finans_cari_demo_db_build.py',
    'tools\\finans_cari_demo_db_build.py',
    'yedekler/',
    'yedekler\\',
)

WRITE_PATTERNS = (
    re.compile(r'INSERT\s+INTO\s+Cari_Har\b', re.I),
    re.compile(r'UPDATE\s+Cari_Har\b', re.I),
    re.compile(r'DELETE\s+FROM\s+Cari_Har\b', re.I),
    re.compile(r'REPLACE\s+INTO\s+Cari_Har\b', re.I),
)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path).replace('\\', '/')


def _excluded(rel: str) -> bool:
    return any(p.replace('\\', '/') in rel.replace('\\', '/') for p in EXCLUDED_PATH_PARTS)


def scan_cari_har_writes(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or (ROOT / 'app')
    hits: list[dict[str, Any]] = []
    for path in base.rglob('*.py'):
        rel = _rel(path)
        if _excluded(rel):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pat in WRITE_PATTERNS:
                if pat.search(line):
                    hits.append({
                        'file': rel,
                        'line': i,
                        'snippet': stripped[:120],
                        'allowed': rel in ALLOWED_PRODUCTION_WRITE_FILES,
                    })
                    break
    return hits


def unauthorized_writes(hits: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    items = hits if hits is not None else scan_cari_har_writes()
    return [h for h in items if not h.get('allowed')]


def scan_pass(root: Path | None = None) -> tuple[bool, list[dict[str, Any]]]:
    scan_root = root or (ROOT / 'app')
    bad = unauthorized_writes(scan_cari_har_writes(scan_root))
    return len(bad) == 0, bad

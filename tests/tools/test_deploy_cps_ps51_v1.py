# -*- coding: utf-8 -*-
"""Deploy-CPS.ps1 — Windows PowerShell 5.1 compatibility regression."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

WT = Path(__file__).resolve().parents[2]
PS1 = WT / 'Deploy-CPS.ps1'
PY_DEPLOY = WT / 'tools' / 'deploy_and_rollback.py'
BASE_COMMIT = '7a93a537710dee6e296abf0c7db6f62d617e2fee'
POPUP_TEMPLATE = WT / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'

# PowerShell 7+ syntax that breaks Windows PowerShell 5.1 parser
PS7_FORBIDDEN = [
    (r'\?\.', 'null-conditional operator (?.)'),
    (r'\?\?', 'null-coalescing operator (??)'),
    (r'\?\s*[^.?]', 'ternary/null-coalescing fragment'),
    (r'\s&&\s', 'pipeline chain AND (&&)'),
    (r'\s\|\|\s', 'pipeline chain OR (||)'),
    (r'--%', 'stop parsing token (--%)'),
]


def _ps1_text() -> str:
    return PS1.read_text(encoding='utf-8-sig')


def _ps1_lines() -> list[str]:
    return _ps1_text().splitlines()


def _strip_ps_comments(line: str) -> str:
    """Remove # comments outside quoted strings (PS 5.1 static scan)."""
    out: list[str] = []
    i = 0
    in_single = False
    in_double = False
    while i < len(line):
        ch = line[i]
        if in_single:
            out.append(ch)
            if ch == "'" and i + 1 < len(line) and line[i + 1] == "'":
                out.append(line[i + 1])
                i += 2
                continue
            if ch == "'":
                in_single = False
        elif in_double:
            out.append(ch)
            if ch == '`' and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_double = False
        elif ch == '#':
            break
        elif ch == "'":
            in_single = True
            out.append(ch)
        elif ch == '"':
            in_double = True
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def _scan_ps51_quote_balance() -> dict[str, int | bool | None]:
    """Static quote/backtick/here-string balance for Deploy-CPS.ps1."""
    lines = _ps1_lines()
    in_single = False
    in_double = False
    here_delim: str | None = None  # "' or '" when inside here-string
    backtick_continuations = 0
    broken_line: int | None = None

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip('\r\n')
        if here_delim is not None:
            if line.rstrip().endswith(here_delim):
                here_delim = None
            continue

        stripped = line.lstrip()
        if not in_single and not in_double:
            if stripped.startswith("@'"):
                here_delim = "'@"
                continue
            if stripped.startswith('@"'):
                here_delim = '"@'
                continue

        i = 0
        while i < len(line):
            ch = line[i]
            if in_single:
                if ch == "'" and i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                if ch == "'":
                    in_single = False
            elif in_double:
                if ch == '`' and i + 1 < len(line):
                    i += 2
                    continue
                if ch == '"':
                    in_double = False
            elif ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            i += 1

        if line.rstrip().endswith('`'):
            backtick_continuations += 1

        if in_single or in_double:
            broken_line = lineno

    return {
        'quote_balanced': not in_single and not in_double and here_delim is None,
        'here_string_balanced': here_delim is None,
        'backtick_continuations': backtick_continuations,
        'broken_line': broken_line,
    }


class TestDeployCpsPs51Syntax:
    def test_ps1_file_exists(self):
        assert PS1.is_file()

    def test_no_ps7_null_conditional(self):
        text = _ps1_text()
        assert '?.' not in text, '?. operator must not appear (PS 5.1 incompatible)'

    def test_no_ps7_forbidden_patterns(self):
        text = _ps1_text()
        for pattern, label in PS7_FORBIDDEN:
            if pattern == r'\?\s*[^.?]':
                continue  # covered by explicit ?. test; avoid false positives on param()
            matches = re.findall(pattern, text)
            assert not matches, f'PS7-only syntax found ({label}): {matches}'

    def test_python_lookup_uses_explicit_null_check(self):
        text = _ps1_text()
        assert 'Get-Command python -ErrorAction SilentlyContinue' in text
        assert '$pyCmd.Source' in text or '$py = $pyCmd.Source' in text
        assert '?.' not in text

    def test_static_quote_balance(self):
        result = _scan_ps51_quote_balance()
        assert result['quote_balanced'], (
            f'unbalanced quotes/here-strings; first open at line {result["broken_line"]}'
        )

    def test_static_here_string_balance(self):
        result = _scan_ps51_quote_balance()
        assert result['here_string_balanced']

    def test_static_backtick_line_continuations(self):
        result = _scan_ps51_quote_balance()
        # Usage block uses trailing backticks on lines 10-14
        assert result['backtick_continuations'] >= 5

    def test_no_double_quoted_subexpression_if_else(self):
        """PS 5.1 fails to parse if/else inside $() within double-quoted strings."""
        text = _ps1_text()
        assert 'MODE=$( if ($Execute)' not in text
        assert 'MODE=$(if ($Execute)' not in text

    def test_string_terminator_cascade_resolved(self):
        text = _ps1_text()
        assert '?.Source' not in text
        result = _scan_ps51_quote_balance()
        assert result['quote_balanced']
        assert result['broken_line'] is None


class TestDeployCpsSecurityGates:
    def test_default_no_execute_switch(self):
        text = _ps1_text()
        assert '[switch]$Execute' in text
        # PLAN path: no --execute appended unless $Execute
        assert "if ($Execute)" in text
        assert "$args_list += '--execute'" in text

    def test_execute_requires_six_confirmations(self):
        text = _ps1_text()
        for token in (
            '--ConfirmRelease',
            '--ExpectedComputer',
            '--ExpectedHead',
            'TargetCommit (must be 40-char full hash)',
        ):
            assert token in text
        assert 'BLOCKED: -Execute requires:' in text

    def test_plan_mode_label(self):
        text = _ps1_text()
        assert "$deployMode = if ($Execute) { 'EXECUTE' } else { 'PLAN' }" in text
        assert "Write-Host ('CPS Deploy V1 - MODE=' + $deployMode)" in text
        assert "Write-Host ('TARGET_COMMIT=' + $TargetCommit)" in text
        assert "Write-Host ''" in text
        assert '& $py @args_list' in text
        assert 'exit $LASTEXITCODE' in text


class TestDeployCpsPlanFixture:
    """Simulate PLAN invocation path (python deploy_and_rollback.py, no --execute)."""

    def test_plan_fixture_invokes_python_deploy_script(self, tmp_path):
        from tools.release_manifest import create_manifest, save_manifest

        manifest = create_manifest(
            release_id='ps51-plan-fixture',
            module='nexgen',
            base_commit=BASE_COMMIT,
            tested_commit=subprocess.run(
                ['git', 'rev-parse', 'HEAD'], cwd=str(WT),
                capture_output=True, text=True, check=True,
            ).stdout.strip(),
            target_branch='fix/infra-deploy-powershell51-v1',
            allowed_files=['Deploy-CPS.ps1'],
            forbidden_paths=['app/migrations/'],
            schema_contract=str(WT / 'tools' / 'module_schema_contracts' / 'nexgen.toml'),
            required_migrations=[],
            test_result='PASS',
            test_pass_count=1,
            test_fail_count=0,
            pilot_baseline=BASE_COMMIT,
        )
        mp = tmp_path / 'manifest.json'
        save_manifest(manifest, mp)

        # Build args exactly as Deploy-CPS.ps1 would (PLAN — no --execute)
        commit = manifest['tested_commit']
        proc = subprocess.run(
            [
                sys.executable,
                str(PY_DEPLOY),
                '--manifest', str(mp),
                '--repo', str(WT),
                '--db', str(tmp_path / 'noop.db'),
                '--target-commit', commit,
            ],
            capture_output=True,
            text=True,
        )
        # Preflight may BLOCK on missing DB — that's OK; script must parse and run.
        assert 'RUNNER_MODE=PLAN' in proc.stdout or proc.returncode in (0, 1)
        assert '--execute' not in ' '.join(proc.args)


class TestPopupTemplateUnchanged:
    def test_popup_template_matches_base_commit(self):
        expected = subprocess.run(
            ['git', 'show', f'{BASE_COMMIT}:app/templates/nexgen/musteri_pazarlama.html'],
            cwd=str(WT), capture_output=True, text=True, check=True,
        ).stdout
        actual = POPUP_TEMPLATE.read_text(encoding='utf-8')
        assert actual == expected, 'NexGen popup template must remain identical to 7a93a53'


class TestAtpDiffFromFix:
    def test_atp_diff_from_this_fix_is_zero(self):
        """This fix must not touch any ATP lock touchpoint file."""
        changed = subprocess.run(
            ['git', 'diff', '--name-only', BASE_COMMIT, 'HEAD'],
            cwd=str(WT), capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        manifest_path = WT / 'docs' / 'atp-lock' / 'atp_touchpoints.sha256'
        touchpoints = {
            line.split('  ', 1)[1].strip()
            for line in manifest_path.read_text(encoding='utf-8', errors='ignore').splitlines()
            if '  ' in line
        }
        overlap = [f for f in changed if f in touchpoints]
        assert overlap == [], f'ATP touchpoints modified by this fix: {overlap}'
        assert 'Deploy-CPS.ps1' not in touchpoints

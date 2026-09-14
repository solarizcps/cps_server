# -*- coding: utf-8 -*-
"""ATP unified zero-failure gate runner (committed infrastructure)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANONICAL = Path(r'C:\Solariz_CPS_SERVER\app\mock_data.db')
OUT = Path(tempfile.gettempdir()) / 'atp_unified_suite_v1.json'


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(cmd: list[str], *, cwd: Path | None = None) -> dict:
    p = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    return {
        'cmd': cmd,
        'exit_code': p.returncode,
        'stdout_tail': '\n'.join(p.stdout.splitlines()[-8:]),
        'stderr_tail': '\n'.join(p.stderr.splitlines()[-8:]),
    }


def main() -> int:
    before = _sha(CANONICAL)
    results: dict[str, object] = {
        'suites': {},
        'required_fail_count': 0,
        'required_error_count': 0,
        'tests_skipped_by_this_phase': 0,
    }

    steps = [
        ('P0_MATRIX', [sys.executable, str(ROOT / '_test_atp_p0_matrix.py')]),
        ('GPS_P1', [sys.executable, str(ROOT / '_test_faz_arac_gps_p1.py')]),
        ('GPS_P2', [sys.executable, str(ROOT / '_test_faz_arac_gps_p2.py')]),
        ('GPS_P3', [sys.executable, str(ROOT / '_test_faz_arac_gps_p3.py')]),
        ('GPS_HARDENING', [sys.executable, str(ROOT / '_test_arac_gps_task_hardening.py')]),
        ('GPS_MASTER_ROUTEVIS', [sys.executable, str(ROOT / '_test_faz_arac_routevis.py')]),
        ('WHATSAPP_REAL', [sys.executable, str(ROOT / '_test_atp_whatsapp_real_endpoint_v1.py')]),
        ('ACTIVE_SNAPSHOT', [sys.executable, str(ROOT / '_test_atp_active_snapshot_v1.py')]),
        (
            'URGENT_MATRIX',
            [
                sys.executable,
                '-m',
                'pytest',
                'tests/planlama/test_atp_urgent_stop_order_v1.py',
                'tests/planlama/test_arac_acil_atomic_insert.py',
                'tests/planlama/test_arac_acil_route_state_invalidation.py',
                '-q',
                '--tb=no',
            ],
        ),
        (
            'HISTORY_COMPACT',
            [sys.executable, '-m', 'pytest', 'tests/planlama/test_atp_past_plans_history_v1.py', '-q', '--tb=no'],
        ),
        (
            'REGISTRY_DEDUPE',
            [sys.executable, '-m', 'pytest', 'tests/planlama/test_atp_live_vehicle_dedupe_v1.py', '-q', '--tb=no'],
        ),
        (
            'FILOM_REDIRECT',
            [sys.executable, '-m', 'pytest', 'tests/planlama/test_filom_register_redirect_v1.py', '-q', '--tb=no'],
        ),
        ('ATP_FULL_REGRESSION', [sys.executable, '-m', 'pytest', 'tests/planlama/', '-q', '--tb=no']),
    ]

    for name, cmd in steps:
        r = _run(cmd)
        ok = r['exit_code'] == 0
        results['suites'][name] = {'pass': ok, **r}
        if not ok:
            results['required_fail_count'] = int(results['required_fail_count']) + 1

    after = _sha(CANONICAL)
    results['canonical_db_hash_unchanged'] = before == after
    results['all_pass'] = (
        results['required_fail_count'] == 0 and results['required_error_count'] == 0
    )
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        json.dumps(
            {k: results[k] for k in ('required_fail_count', 'required_error_count', 'all_pass', 'canonical_db_hash_unchanged')},
            indent=2,
        )
    )
    for name, data in results['suites'].items():
        print(f"{name}: {'PASS' if data['pass'] else 'FAIL'}")
    return 0 if results['all_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

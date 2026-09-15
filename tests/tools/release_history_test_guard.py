# -*- coding: utf-8 -*-
"""Preflight guards for release-history route / DB isolation tests."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

CANONICAL_DB = Path(__file__).resolve().parents[2] / "app" / "mock_data.db"
RELEASE_HISTORY_TEST_MODULES = (
    "test_release_history_ui_v2",
    "test_release_history_inline_detail_ui_v1",
    "test_release_history_route_repeat_v1",
)
GPS_WORKER_MARKER = "arac_gps_poll_worker.py"
GPS_SUPERVISOR_MARKER = "arac_gps_log_supervisor"
GPS_LOCK_NAMES = ("arac_gps_poll_worker.lock",)


def _release_history_suite_requested(config) -> bool:
    args = [str(a) for a in getattr(config, "args", [])]
    if not args:
        return False
    joined = " ".join(args).replace("\\", "/")
    return any(name in joined for name in RELEASE_HISTORY_TEST_MODULES)


def assert_port_8080_closed() -> None:
    """Fail fast when live CPS worker would race canonical DB during route tests."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 8080))
    except (ConnectionRefusedError, OSError):
        return
    finally:
        probe.close()
    pytest.fail(
        "Port 8080 is open. Stop the CPS server before running release-history "
        "tests (use _start_8080_clean.ps1 only after tests complete)."
    )


def _gps_lock_paths() -> list[Path]:
    paths: list[Path] = []
    temp = os.environ.get("TEMP", "").strip()
    if temp:
        paths.append(Path(temp))
    paths.append(Path(r"C:\Windows\TEMP"))
    seen: set[str] = set()
    out: list[Path] = []
    for base in paths:
        key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        for name in GPS_LOCK_NAMES:
            candidate = base / name
            if candidate.is_file():
                out.append(candidate)
    return out


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        raw = lock_path.read_text(encoding="ascii", errors="ignore").strip()
        if raw.isdigit():
            return int(raw)
    except OSError:
        return None
    return None


def _powershell_json(script: str) -> list[dict]:
    if sys.platform != "win32":
        return []
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []


def find_active_gps_worker_processes() -> list[dict]:
    """Return GPS supervisor/worker processes without stopping them."""
    ps = rf"""
$items = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{
    $_.CommandLine -and $_.CommandLine -notlike '*Get-CimInstance*' -and (
        $_.CommandLine -like '*{GPS_WORKER_MARKER}*' -or
        $_.CommandLine -like '*{GPS_SUPERVISOR_MARKER}*'
    )
}} | ForEach-Object {{
    $items += [ordered]@{{
        pid = [int]$_.ProcessId
        ppid = [int]$_.ParentProcessId
        name = $_.Name
        command_line = $_.CommandLine
        source = 'command_line'
    }}
}}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | ForEach-Object {{
    $child = $_
    if ($child.CommandLine -and ($child.CommandLine -match 'pytest|test_release_history')) {{ return }}
    $supervisor = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)" -ErrorAction SilentlyContinue
    if (-not $supervisor -or $supervisor.Name -ne 'python.exe') {{ return }}
    if ($supervisor.CommandLine -and ($supervisor.CommandLine -match 'pytest|test_release_history')) {{ return }}
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId=$($supervisor.ParentProcessId)" -ErrorAction SilentlyContinue
    if (-not $launcher -or $launcher.Name -ne 'powershell.exe') {{ return }}
    $childEmpty = [string]::IsNullOrWhiteSpace($child.CommandLine)
    $superEmpty = [string]::IsNullOrWhiteSpace($supervisor.CommandLine)
    if (-not ($childEmpty -and $superEmpty)) {{ return }}
    foreach ($p in @($child, $supervisor)) {{
        $items += [ordered]@{{
            pid = [int]$p.ProcessId
            ppid = [int]$p.ParentProcessId
            name = $p.Name
            command_line = $p.CommandLine
            source = 'fallback_chain'
        }}
    }}
}}
$items | ConvertTo-Json -Compress
"""
    found = _powershell_json(ps)
    seen = {int(item.get("pid", 0)) for item in found if item.get("pid")}

    for lock_path in _gps_lock_paths():
        lock_pid = _read_lock_pid(lock_path)
        if not lock_pid or lock_pid in seen:
            continue
        probe = _powershell_json(
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={lock_pid}' -ErrorAction SilentlyContinue; "
            "if ($p) { [ordered]@{ pid=[int]$p.ProcessId; ppid=[int]$p.ParentProcessId; "
            f"name=$p.Name; command_line=$p.CommandLine; source='lock:{lock_path}' }} | ConvertTo-Json -Compress"
        )
        for item in probe:
            pid = int(item.get("pid", 0))
            if pid and pid not in seen:
                found.append(item)
                seen.add(pid)

    return found


def assert_gps_worker_stopped() -> None:
    """Fail fast when canonical GPS poll worker is active."""
    active = find_active_gps_worker_processes()
    if not active:
        return
    lines = []
    for item in active:
        pid = item.get("pid")
        ppid = item.get("ppid")
        source = item.get("source", "unknown")
        cmd = str(item.get("command_line") or "")[:160]
        lines.append(f"  PID={pid} PPID={ppid} source={source} cmd={cmd!r}")
    pytest.fail(
        "GPS worker/supervisor is active and writes canonical mock_data.db every 60s. "
        "Stop it with Stop-Arac-GPS-Worker.ps1 before release-history tests.\n"
        + "\n".join(lines)
    )


def assert_temp_db_bound() -> None:
    """Route tests must never open RW connections to canonical mock_data.db."""
    from tools.atp_test_db_guard import is_canonical_path

    import config

    bound = os.environ.get("CPS_MOCK_DB_PATH", "").strip()
    if not bound:
        pytest.fail(
            "CPS_MOCK_DB_PATH is unset during route_db_isolation. "
            "Temp DB binding failed before Flask/app import."
        )
    if is_canonical_path(bound) or is_canonical_path(config.Config.MOCK_DB_PATH):
        pytest.fail(
            f"Route test bound to canonical DB (CPS_MOCK_DB_PATH={bound!r}, "
            f"Config.MOCK_DB_PATH={config.Config.MOCK_DB_PATH!r})."
        )
    if not Path(bound).is_file():
        pytest.fail(f"Route test temp DB missing: {bound!r}")


def pytest_sessionstart(session) -> None:
    if _release_history_suite_requested(session.config):
        assert_port_8080_closed()
        assert_gps_worker_stopped()

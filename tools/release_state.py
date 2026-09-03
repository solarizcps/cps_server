#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""File-based deployment state generator with correct precedence.

Precedence (highest first):
  WORKING / COMMIT_PENDING — relevant dirty or staged production/history
  DEPLOY_FAILED — manifest deploy_failed
  DEPLOYED_VERIFIED — manifest SHA = server_head + smoke PASS + git-valid SHA
  PUSHED_NOT_DEPLOYED — clean worktree, HEAD synced with upstream, manifest behind
  LOCAL_COMMITTED_NOT_PUSHED — clean worktree, HEAD ahead of upstream
  DEPLOYMENT_UNKNOWN — fallback

Does NOT push or deploy automatically.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "var" / "release"
STATE_PATH = STATE_DIR / "deployment_state.json"
MANIFEST_PATH = STATE_DIR / "deployment_manifest.json"

PRODUCTION_PREFIXES = (
    "app/modules/",
    "app/templates/",
    "app/static/",
    "app/migrations/",
)

HISTORY_PREFIXES = (
    "changes/records/",
    "changes/fragments/",
)

HISTORY_SERVICE_FILES = frozenset({
    "app/services/release_history_service.py",
})

RELEVANT_PREFIXES = PRODUCTION_PREFIXES + HISTORY_PREFIXES

MODULES = (
    "nexgen.mo", "nexgen.numune", "nexgen.etiket", "planlama.atp", "planlama.aps",
    "finans", "cari360", "ajanda", "test.infra", "cps.release.history",
    "uretim.enjeksiyon", "server",
)

# Gate / history tooling paths map to cps.release.history (not every module).
_HISTORY_TOOL_PREFIXES = (
    "tools/release_state.py",
    "tools/record_deploy_event.py",
    "tools/check_release_fragment.py",
    "tools/deploy_cps_with_release_state.ps1",
    "tools/install_release_hooks.ps1",
    "tools/validate_release_history.py",
    "tools/cps_gate2_backfill_generate.py",
    "tools/cps_gate3_verified_uncommitted_generate.py",
    "tools/commit_classification_report.py",
    "tools/audit_commit_inventory.py",
    "tools/audit_gate_manifest.py",
    ".githooks/",
    "docs/release-history/",
    "tests/tools/test_release_history",
    "AGENTS.md",
    "docs/AI_DEVELOPMENT_RULES.md",
    ".cursorrules",
)

GLOBAL_WORKING = "WORKING"
GLOBAL_COMMIT_PENDING = "COMMIT_PENDING"
GLOBAL_LOCAL_NOT_PUSHED = "LOCAL_COMMITTED_NOT_PUSHED"
GLOBAL_PUSHED_NOT_DEPLOYED = "PUSHED_NOT_DEPLOYED"
GLOBAL_DEPLOYED_VERIFIED = "DEPLOYED_VERIFIED"
GLOBAL_DEPLOY_FAILED = "DEPLOY_FAILED"
GLOBAL_UNKNOWN = "DEPLOYMENT_UNKNOWN"
GLOBAL_NEEDS_REVIEW = "NEEDS_REVIEW"


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _git_commit_exists(sha: str, cwd: Path | None = None) -> bool:
    if not sha or not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        return False
    proc = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "commit"


def _resolve_full_sha(sha: str, cwd: Path | None = None) -> str:
    if not sha:
        return ""
    full = _run_git(["rev-parse", sha], cwd=cwd)
    return full or sha


def _local_head(cwd: Path | None = None) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=cwd)


def _is_noise_path(path: str) -> bool:
    norm = _normalize_path(path)
    if ".bak_" in norm or norm.endswith(".bak"):
        return True
    return False


def _is_relevant_path(path: str) -> bool:
    if _is_noise_path(path):
        return False
    if path in HISTORY_SERVICE_FILES:
        return True
    return any(path.startswith(p) for p in RELEVANT_PREFIXES)


def _path_to_modules_for_state(path: str) -> set[str]:
    """Map paths to modules for per-module WORKING — history/gate scope only."""
    if _is_noise_path(path):
        return set()
    norm = _normalize_path(path)
    if norm.startswith("changes/records/") or norm.startswith("changes/fragments/"):
        return _path_to_modules(path)
    if norm in HISTORY_SERVICE_FILES or norm.endswith("surum_gecmisi.html"):
        return {"cps.release.history"}
    if any(norm.startswith(p) for p in _HISTORY_TOOL_PREFIXES):
        return {"cps.release.history"}
    return set()


def _files_by_module(paths: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {m: [] for m in MODULES}
    for path in paths:
        mods = _path_to_modules_for_state(path)
        if not mods:
            continue
        for mod in mods:
            if mod in grouped:
                grouped[mod].append(path)
    return grouped


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _path_to_modules(path: str) -> set[str]:
    """Map a relevant file path to one or more release-history modules."""
    norm = _normalize_path(path)
    modules: set[str] = set()

    if norm.startswith("changes/records/"):
        parts = norm.split("/")
        if len(parts) >= 3 and parts[2]:
            modules.add(parts[2])
        return modules

    if norm.startswith("changes/fragments/"):
        name = norm.rsplit("/", 1)[-1]
        if "." in name:
            modules.add(name.split(".", 1)[0])
        return modules

    if norm in HISTORY_SERVICE_FILES or norm.endswith("surum_gecmisi.html"):
        modules.add("cps.release.history")
        return modules

    if any(norm.startswith(p) for p in _HISTORY_TOOL_PREFIXES):
        modules.add("cps.release.history")
        return modules

    module_dirs = {
        "app/modules/finans/": "finans",
        "app/modules/cari360/": "cari360",
        "app/modules/nexgen_mo/": "nexgen.mo",
        "app/modules/nexgen_mo": "nexgen.mo",
        "app/modules/nexgen/": "nexgen.numune",
        "app/modules/planlama_atp/": "planlama.atp",
        "app/modules/planlama_aps/": "planlama.aps",
        "app/modules/ajanda/": "ajanda",
        "app/modules/uretim_enjeksiyon/": "uretim.enjeksiyon",
        "app/templates/yonetim/": "yonetim",
        "app/templates/nexgen_mo/": "nexgen.mo",
        "app/templates/planlama_atp/": "planlama.atp",
        "app/templates/planlama_aps/": "planlama.aps",
        "app/templates/cari360/": "cari360",
        "app/templates/finans/": "finans",
    }
    for prefix, mod in module_dirs.items():
        if norm.startswith(prefix):
            modules.add(mod)
            return modules

    return modules


def _files_by_module(paths: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {m: [] for m in MODULES}
    for path in paths:
        mods = _path_to_modules(path)
        if not mods:
            continue
        for mod in mods:
            if mod in grouped:
                grouped[mod].append(path)
    return grouped


def _module_state(
    mod: str,
    *,
    global_state: str,
    manifest_status: str,
    mod_staged: list[str],
    mod_dirty: list[str],
    core: dict[str, Any],
) -> tuple[str, str]:
    """Per-module push/deployment state; only dirty modules inherit WORKING/COMMIT_PENDING."""
    if mod_staged:
        return GLOBAL_COMMIT_PENDING, f"staged: {len(mod_staged)}"
    if mod_dirty:
        return GLOBAL_WORKING, f"dirty: {len(mod_dirty)}"

    # No module-local changes: never inherit global WORKING/COMMIT_PENDING.
    if global_state in {GLOBAL_WORKING, GLOBAL_COMMIT_PENDING}:
        upstream = core.get("git", {})
        if core.get("worktree_clean") is False:
            # Global dirty from other modules; this module stays at deploy sync state.
            if upstream.get("synced") == "1":
                return GLOBAL_PUSHED_NOT_DEPLOYED, "no module-local changes; global worktree dirty elsewhere"
            if int(upstream.get("ahead") or 0) > 0:
                return GLOBAL_LOCAL_NOT_PUSHED, "no module-local changes; local ahead"
        if manifest_status == GLOBAL_DEPLOYED_VERIFIED:
            return manifest_status, "no module-local changes; deploy verified"
        if manifest_status == GLOBAL_DEPLOY_FAILED:
            return GLOBAL_DEPLOY_FAILED, core["manifest_check"].get("reason", "")
        return GLOBAL_PUSHED_NOT_DEPLOYED, "no module-local changes"

    if global_state in {GLOBAL_DEPLOY_FAILED, GLOBAL_DEPLOYED_VERIFIED, GLOBAL_PUSHED_NOT_DEPLOYED, GLOBAL_LOCAL_NOT_PUSHED}:
        if global_state == GLOBAL_DEPLOYED_VERIFIED:
            return manifest_status, core["manifest_check"].get("reason", "")
        return global_state, core.get("global_state_reason", "")

    if global_state == GLOBAL_UNKNOWN:
        return GLOBAL_UNKNOWN, "no module-local changes; global unknown"

    return global_state, core.get("global_state_reason", "")


def _porcelain_paths(cwd: Path | None = None) -> list[tuple[str, str]]:
    out = _run_git(["status", "--porcelain", "-uall"], cwd=cwd)
    if not out:
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if _is_relevant_path(path):
            rows.append((xy, path))
    return rows


def _staged_relevant_files(cwd: Path | None = None) -> list[str]:
    out = _run_git(["diff", "--cached", "--name-only"], cwd=cwd)
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip() and _is_relevant_path(line.strip())]


def _dirty_relevant_unstaged(cwd: Path | None = None) -> list[str]:
    dirty: list[str] = []
    for xy, path in _porcelain_paths(cwd):
        if xy[0] == "?" or xy[1] != " ":
            dirty.append(path)
    return dirty


def _relevant_worktree_clean(cwd: Path | None = None) -> bool:
    return not _porcelain_paths(cwd)


def _upstream_info(cwd: Path | None = None) -> dict[str, str]:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd) or "main"
    upstream = _run_git(["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"], cwd=cwd)
    if not upstream:
        return {"branch": branch, "upstream": "", "ahead": "0", "behind": "0", "synced": "0"}
    counts = _run_git(["rev-list", "--left-right", "--count", f"{upstream}...HEAD"], cwd=cwd)
    ahead, behind = "0", "0"
    if counts:
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = parts[0], parts[1]
    synced = "1" if ahead == "0" and behind == "0" else "0"
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "synced": synced,
    }


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _verify_manifest(manifest: dict[str, Any], local_head: str, cwd: Path | None = None) -> dict[str, Any]:
    """Return manifest verification result; never trust hand-written PASS alone."""
    deployed_sha = str(manifest.get("deployment_commit", "")).strip()
    server_head = str(manifest.get("server_head", "")).strip()
    smoke = str(manifest.get("http_smoke_result", "")).strip().upper()
    smoke_code = manifest.get("http_smoke_status_code")
    smoke_url = str(manifest.get("http_smoke_url", "")).strip()

    result = {
        "valid_sha": False,
        "sha_resolved": "",
        "server_head_match": False,
        "smoke_pass": False,
        "status": GLOBAL_UNKNOWN,
        "reason": "",
    }

    if manifest.get("deploy_failed"):
        result["status"] = GLOBAL_DEPLOY_FAILED
        result["reason"] = str(manifest.get("deploy_failed_reason", "deploy_failed flag set"))
        return result

    if not deployed_sha:
        result["reason"] = "no deployment_commit"
        return result

    if not _git_commit_exists(deployed_sha, cwd=cwd):
        result["status"] = GLOBAL_NEEDS_REVIEW
        result["reason"] = "deployment_commit not found in git"
        return result

    resolved = _resolve_full_sha(deployed_sha, cwd=cwd)
    result["valid_sha"] = True
    result["sha_resolved"] = resolved

    if server_head:
        server_resolved = _resolve_full_sha(server_head, cwd=cwd)
        result["server_head_match"] = server_resolved == resolved
    else:
        result["server_head_match"] = resolved == _resolve_full_sha(local_head, cwd=cwd)

    smoke_ok = smoke == "PASS" and smoke_code == 200 and bool(smoke_url)
    result["smoke_pass"] = smoke_ok

    if result["server_head_match"] and smoke_ok:
        result["status"] = GLOBAL_DEPLOYED_VERIFIED
        result["reason"] = "manifest SHA matches server_head with HTTP 200 smoke"
    elif smoke == "PASS" and not smoke_ok:
        result["status"] = GLOBAL_NEEDS_REVIEW
        result["reason"] = "manual PASS without smoke_url/status_code evidence"
    elif result["valid_sha"] and not result["server_head_match"]:
        result["status"] = GLOBAL_PUSHED_NOT_DEPLOYED
        result["reason"] = "manifest SHA valid but server_head mismatch"
    else:
        result["status"] = GLOBAL_NEEDS_REVIEW
        result["reason"] = "manifest incomplete"

    return result


def compute_global_state(cwd: Path | None = None) -> dict[str, Any]:
    cwd = cwd or ROOT
    local_head = _local_head(cwd)
    upstream = _upstream_info(cwd)
    manifest = _load_manifest()
    manifest_check = _verify_manifest(manifest, local_head, cwd=cwd)

    staged = _staged_relevant_files(cwd)
    dirty_unstaged = _dirty_relevant_unstaged(cwd)
    worktree_clean = _relevant_worktree_clean(cwd)

    global_state = GLOBAL_UNKNOWN
    reason = ""

    if staged:
        global_state = GLOBAL_COMMIT_PENDING
        reason = f"staged relevant files: {len(staged)}"
    elif dirty_unstaged:
        global_state = GLOBAL_WORKING
        reason = f"dirty relevant files: {len(dirty_unstaged)}"
    elif manifest_check["status"] == GLOBAL_DEPLOY_FAILED:
        global_state = GLOBAL_DEPLOY_FAILED
        reason = manifest_check["reason"]
    elif manifest_check["status"] == GLOBAL_DEPLOYED_VERIFIED and worktree_clean:
        global_state = GLOBAL_DEPLOYED_VERIFIED
        reason = manifest_check["reason"]
    elif worktree_clean and upstream.get("synced") == "1":
        if manifest_check["status"] in {GLOBAL_PUSHED_NOT_DEPLOYED, GLOBAL_NEEDS_REVIEW}:
            global_state = GLOBAL_PUSHED_NOT_DEPLOYED
            reason = "HEAD synced with upstream; deploy manifest behind or unverified"
        elif manifest_check["status"] == GLOBAL_DEPLOYED_VERIFIED:
            global_state = GLOBAL_DEPLOYED_VERIFIED
            reason = manifest_check["reason"]
        else:
            global_state = GLOBAL_PUSHED_NOT_DEPLOYED
            reason = "HEAD synced with upstream; no verified deploy manifest"
    elif worktree_clean and int(upstream.get("ahead") or 0) > 0:
        global_state = GLOBAL_LOCAL_NOT_PUSHED
        reason = f"clean worktree; ahead of upstream by {upstream.get('ahead')}"
    elif worktree_clean and not upstream.get("upstream"):
        global_state = GLOBAL_LOCAL_NOT_PUSHED
        reason = "clean worktree; no upstream configured (local not pushed)"
    elif not worktree_clean:
        global_state = GLOBAL_WORKING
        reason = "relevant worktree not clean"
    else:
        global_state = GLOBAL_UNKNOWN
        reason = "insufficient git/deploy evidence"

    return {
        "global_state": global_state,
        "global_state_reason": reason,
        "local_head": local_head,
        "git": upstream,
        "worktree_clean": worktree_clean,
        "staged_relevant_files": staged,
        "dirty_relevant_files": dirty_unstaged,
        "manifest_check": manifest_check,
        "manual_post_deploy_command_required": False,
    }


def generate_state(cwd: Path | None = None) -> dict[str, Any]:
    cwd = cwd or ROOT
    core = compute_global_state(cwd)
    global_state = core["global_state"]
    manifest_status = core["manifest_check"]["status"]

    staged_by_mod = _files_by_module(core["staged_relevant_files"])
    dirty_by_mod = _files_by_module(core["dirty_relevant_files"])

    modules: dict[str, dict[str, str]] = {}
    for mod in MODULES:
        mod_staged = staged_by_mod.get(mod, [])
        mod_dirty = dirty_by_mod.get(mod, [])
        push_status, mod_reason = _module_state(
            mod,
            global_state=global_state,
            manifest_status=manifest_status,
            mod_staged=mod_staged,
            mod_dirty=mod_dirty,
            core=core,
        )
        if push_status in {GLOBAL_WORKING, GLOBAL_COMMIT_PENDING}:
            deploy_status = push_status
        elif global_state in {GLOBAL_WORKING, GLOBAL_COMMIT_PENDING}:
            deploy_status = manifest_status
        else:
            deploy_status = manifest_status if push_status == GLOBAL_DEPLOYED_VERIFIED else push_status
        modules[mod] = {
            "push_status": push_status,
            "deployment_status": deploy_status,
            "local_head": (core.get("local_head") or "")[:8],
            "state_reason": mod_reason,
            "dirty_files": len(mod_dirty),
            "staged_files": len(mod_staged),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global_state": global_state,
        "global_state_reason": core["global_state_reason"],
        "local_head": core["local_head"],
        "git": core["git"],
        "worktree_clean": core["worktree_clean"],
        "manifest_status": manifest_status,
        "manifest_check": core["manifest_check"],
        "modules": modules,
        "staged_relevant_files": core["staged_relevant_files"],
        "dirty_relevant_files": core["dirty_relevant_files"],
        "manual_post_deploy_command_required": False,
    }


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def http_smoke(url: str, timeout: float = 5.0) -> tuple[bool, int, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            return code == 200, code, "PASS" if code == 200 else f"HTTP_{code}"
    except urllib.error.HTTPError as exc:
        return False, exc.code, f"HTTP_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, 0, f"ERR:{type(exc).__name__}"


def write_verified_manifest(
    *,
    deployment_commit: str | None = None,
    server_head: str | None = None,
    target_server: str = "CPS-LOCAL",
    deployed_by: str = "",
    server_restart: bool = False,
    smoke_url: str = "http://127.0.0.1:8080/giris",
    rollback_commit: str = "",
) -> dict[str, Any]:
    """Validate SHA, run HTTP smoke, write atomic manifest. Raises on failure."""
    cwd = ROOT
    commit = deployment_commit or _local_head(cwd)
    if not _git_commit_exists(commit, cwd=cwd):
        raise ValueError(f"deployment_commit not found in git: {commit}")

    resolved = _resolve_full_sha(commit, cwd=cwd)
    server = _resolve_full_sha(server_head or commit, cwd=cwd)
    if server != resolved:
        raise ValueError("server_head must match deployment_commit")

    ok, code, smoke_label = http_smoke(smoke_url)
    manifest: dict[str, Any] = {
        "deployment_commit": resolved,
        "server_head": server,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
        "target_server": target_server,
        "deployed_by": deployed_by or os.environ.get("USERNAME", ""),
        "server_restart": bool(server_restart),
        "http_smoke_url": smoke_url,
        "http_smoke_status_code": code,
        "http_smoke_result": "PASS" if ok else "FAIL",
        "deploy_failed": not ok,
        "deploy_failed_reason": "" if ok else smoke_label,
        "rollback_commit": rollback_commit or "",
    }
    if not ok:
        atomic_write(MANIFEST_PATH, manifest)
        raise RuntimeError(f"HTTP smoke failed: {smoke_label}")

    atomic_write(MANIFEST_PATH, manifest)
    return manifest


def main() -> int:
    state = generate_state()
    atomic_write(STATE_PATH, state)
    print(f"STATE_WRITTEN {STATE_PATH}")
    print(f"  global_state={state.get('global_state')}")
    print(f"  local_head={(state.get('local_head') or '')[:8]}")
    print(f"  reason={state.get('global_state_reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

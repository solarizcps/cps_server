# -*- coding: utf-8 -*-
"""Read-only CPS release history loader with deployment state cache."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "release-history" / "schema.toml"
DEPLOYMENT_STATE_PATH = REPO_ROOT / "var" / "release" / "deployment_state.json"

MODULE_LABELS: dict[str, str] = {
    "nexgen.mo": "Müşteri Operasyonu",
    "nexgen.numune": "NexGen Numune",
    "nexgen.etiket": "NexGen Etiket Basım",
    "planlama.atp": "Araç Takip",
    "planlama.aps": "APS Genel Plan",
    "planlama.other": "Planlama Diğer",
    "finans": "Finans",
    "cari360": "Cari360",
    "ajanda": "Ajanda",
    "yonetim": "Yönetim",
    "uretim.enjeksiyon": "Üretim Enjeksiyon",
    "uretim.tablet": "Üretim Tablet",
    "server": "Server",
    "test.infra": "Test Altyapısı",
}

STATUS_LABELS: dict[str, str] = {
    "TASLAK": "Taslak",
    "TEST": "Test",
    "ONAYLANDI": "Onaylandı",
    "KILITLI": "Kilitli",
    "GERI_ALINDI": "Geri Alındı",
}

PUSH_STATUS_LABELS: dict[str, str] = {
    "WORKING": "Çalışılıyor",
    "COMMIT_PENDING": "Commit bekliyor (staged)",
    "TESTED": "Test edildi",
    "LOCAL_COMMITTED_NOT_PUSHED": "Commit bekliyor · Push yapılmadı",
    "PUSHED_NOT_DEPLOYED": "Push yapıldı · Deploy bekliyor",
    "DEPLOYED_VERIFIED": "Canlıda doğrulandı",
    "DEPLOY_FAILED": "Deploy başarısız",
    "DEPLOYMENT_UNKNOWN": "Deploy bilinmiyor",
    "NEEDS_REVIEW": "İnceleme gerekli",
}

DEPLOY_WAIT_STATUSES = frozenset({
    "LOCAL_COMMITTED_NOT_PUSHED",
    "PUSHED_NOT_DEPLOYED",
})

DEPLOY_UNKNOWN_STATUSES = frozenset({
    "DEPLOYMENT_UNKNOWN",
})

COMMITTED_SOURCE = "commit"
UNCOMMITTED_SOURCE = "verified_uncommitted"

MAX_RECORDS = 1000
MAX_TOML_BYTES = 256 * 1024
MAX_TEXT_LENGTH = 20_000
MAX_LIST_ITEMS = 500


@dataclass
class ReleaseRecord:
    module: str
    version: str
    phase_code: str
    title: str
    status: str
    date: str
    summary: str
    source_type: str
    commit_sha: str
    commit_short: str
    test_result: str
    push_status: str
    deployment_status: str
    deploy_label: str
    live_version: str
    local_version: str
    root_cause: str
    migration: str
    evidence_summary: str
    current_work: str
    worktree_fingerprint: str
    verification_date: str
    verification_evidence: str
    changes: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    locked_rules: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    related_commits: list[str] = field(default_factory=list)
    deploy_events: list[str] = field(default_factory=list)

    @property
    def is_uncommitted(self) -> bool:
        return self.source_type == UNCOMMITTED_SOURCE

    @property
    def status_display(self) -> str:
        if self.is_uncommitted:
            return "Commit bekliyor"
        return STATUS_LABELS.get(self.status, self.status)


@dataclass
class ModuleSummary:
    module: str
    module_label: str
    current_version: str
    live_version: str
    local_version: str
    version_count: int
    latest_phase: str
    last_completed_phase: str
    latest_title: str
    status: str
    date: str
    commit_short: str
    test_result: str
    test_status_label: str
    deploy_label: str
    deployment_status: str
    push_status_auto: str
    push_status_label: str
    current_work: str
    next_step: str
    commit_pending_count: int
    record_count: int


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_TOML_BYTES:
            return None
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError:
        return None


def _records_root(base: Path) -> Path | None:
    records_dir = base / "changes" / "records"
    if not records_dir.is_dir():
        return None
    try:
        return records_dir.resolve()
    except OSError:
        return None


def _is_safe_record_path(path: Path, records_root: Path) -> bool:
    try:
        if path.name.startswith("."):
            return False
        if path.suffix.lower() != ".toml":
            return False
        if path.is_symlink():
            return False
        if not path.is_file():
            return False
        resolved = path.resolve()
        resolved.relative_to(records_root)
        return True
    except (OSError, ValueError):
        return False


def _collect_record_paths(records_dir: Path, records_root: Path) -> tuple[list[Path], int]:
    skipped = 0
    safe_paths: list[Path] = []
    for path in sorted(records_dir.glob("**/*.toml")):
        try:
            rel_parts = path.relative_to(records_dir).parts
        except ValueError:
            skipped += 1
            continue
        if ".." in rel_parts:
            skipped += 1
            continue
        if not _is_safe_record_path(path, records_root):
            skipped += 1
            continue
        safe_paths.append(path)
    overflow = max(0, len(safe_paths) - MAX_RECORDS)
    if overflow:
        skipped += overflow
        safe_paths = safe_paths[:MAX_RECORDS]
    return safe_paths, skipped


def _is_forbidden_path(value: str, forbidden_tokens: list[str]) -> bool:
    text = (value or "").strip()
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


def _sanitize_text(value: Any, forbidden_tokens: list[str]) -> str:
    text = str(value or "").strip()
    if _is_forbidden_path(text, forbidden_tokens):
        return ""
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
    return text


def _sanitize_list(values: Any, forbidden_tokens: list[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for item in values:
        if len(out) >= MAX_LIST_ITEMS:
            break
        if not isinstance(item, str):
            continue
        clean = _sanitize_text(item, forbidden_tokens)
        if clean:
            out.append(clean)
    return out


def _version_key(version: str) -> tuple[int, ...]:
    nums = [int(part) for part in re.findall(r"\d+", version or "")]
    return tuple(nums or [0])


def _short_sha(value: str) -> str:
    text = (value or "").strip()
    return text[:8] if text else "—"


def _deploy_label(deployment_status: str, push_status: str, source_type: str = COMMITTED_SOURCE) -> str:
    if source_type == UNCOMMITTED_SOURCE:
        return "Commit bekliyor · Doğrulanmış working tree"
    dep = (deployment_status or "").strip().upper()
    push = (push_status or "").strip().upper()
    if dep == "DEPLOYED_VERIFIED":
        return "Sunucuda doğrulandı"
    if dep in DEPLOY_WAIT_STATUSES or push in DEPLOY_WAIT_STATUSES:
        return "Yerelde hazır · Server aktarımı bekliyor"
    if dep in DEPLOY_UNKNOWN_STATUSES or push in DEPLOY_UNKNOWN_STATUSES:
        return "Deploy durumu bilinmiyor"
    if dep == "DEPLOY_FAILED":
        return "Deploy başarısız"
    if dep == "NEEDS_REVIEW":
        return "İnceleme gerekli"
    if push_status:
        return PUSH_STATUS_LABELS.get(push, push.replace("_", " "))
    return "—"


def _module_deploy_pending(item: ModuleSummary) -> bool:
    dep = (item.deployment_status or "").upper()
    push = (item.push_status_auto or "").upper()
    if push in {"WORKING", "COMMIT_PENDING", "LOCAL_COMMITTED_NOT_PUSHED"}:
        return True
    return dep in DEPLOY_WAIT_STATUSES or item.commit_pending_count > 0


def _module_deploy_unknown(item: ModuleSummary) -> bool:
    dep = (item.deployment_status or "").upper()
    push = (item.push_status_auto or "").upper()
    return dep in DEPLOY_UNKNOWN_STATUSES and push not in DEPLOY_WAIT_STATUSES


def _module_label(module: str) -> str:
    return MODULE_LABELS.get(module, module)


def _record_from_toml(data: dict[str, Any], forbidden_tokens: list[str]) -> ReleaseRecord | None:
    source_type = str(data.get("source_type", COMMITTED_SOURCE))
    required = (
        "module", "version", "phase_code", "title", "status", "date",
        "summary", "test_result", "push_status",
    )
    for key in required:
        if key not in data:
            return None
    if source_type == COMMITTED_SOURCE and "commit_sha" not in data:
        return None

    module = str(data["module"])
    phase_code = str(data["phase_code"])
    if not re.fullmatch(r"[a-z0-9.]+", module):
        return None
    if not re.fullmatch(r"[A-Z0-9_]+", phase_code):
        return None

    commit_sha = str(data.get("commit_sha", "")).strip()
    deployment_status = _sanitize_text(data.get("deployment_status", ""), forbidden_tokens)
    push_status = _sanitize_text(data.get("push_status", ""), forbidden_tokens)
    live_version = _sanitize_text(data.get("live_version", ""), forbidden_tokens) or "—"
    local_version = _sanitize_text(data.get("local_version", ""), forbidden_tokens) or str(data["version"])

    return ReleaseRecord(
        module=module,
        version=str(data["version"]),
        phase_code=phase_code,
        title=_sanitize_text(data.get("title", ""), forbidden_tokens),
        status=str(data["status"]),
        date=str(data["date"]),
        summary=_sanitize_text(data.get("summary", ""), forbidden_tokens),
        source_type=source_type,
        commit_sha=commit_sha,
        commit_short=_short_sha(commit_sha),
        test_result=_sanitize_text(data.get("test_result", ""), forbidden_tokens),
        push_status=push_status,
        deployment_status=deployment_status,
        deploy_label=_deploy_label(deployment_status, push_status, source_type),
        live_version=live_version,
        local_version=local_version,
        root_cause=_sanitize_text(data.get("root_cause", ""), forbidden_tokens),
        migration=_sanitize_text(data.get("migration", ""), forbidden_tokens),
        evidence_summary=_sanitize_text(data.get("evidence_summary", ""), forbidden_tokens),
        current_work=_sanitize_text(data.get("current_work", ""), forbidden_tokens),
        worktree_fingerprint=_sanitize_text(data.get("worktree_fingerprint", ""), forbidden_tokens),
        verification_date=_sanitize_text(data.get("verification_date", ""), forbidden_tokens),
        verification_evidence=_sanitize_text(data.get("verification_evidence", ""), forbidden_tokens),
        changes=_sanitize_list(data.get("changes"), forbidden_tokens),
        changed_files=_sanitize_list(data.get("changed_files"), forbidden_tokens),
        locked_rules=_sanitize_list(data.get("locked_rules"), forbidden_tokens),
        tests=_sanitize_list(data.get("tests"), forbidden_tokens),
        known_issues=_sanitize_list(data.get("known_issues"), forbidden_tokens),
        next_steps=_sanitize_list(data.get("next_steps"), forbidden_tokens),
        related_commits=_sanitize_list(data.get("related_commits"), forbidden_tokens),
        deploy_events=_sanitize_list(data.get("deploy_events"), forbidden_tokens),
    )


def load_deployment_state(base: Path | None = None) -> dict[str, Any]:
    """Read cached deployment state (no subprocess). Returns empty dict if missing."""
    path = (base or REPO_ROOT) / "var" / "release" / "deployment_state.json"
    if not path.is_file():
        return {}
    try:
        if path.stat().st_size > 512 * 1024:
            return {}
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_release_records(base: Path | None = None) -> tuple[list[ReleaseRecord], int]:
    root = base or REPO_ROOT
    schema = _load_schema()
    allowlist = set(schema["module_allowlist"]["modules"])
    status_values = set(schema["status_enum"]["values"])
    forbidden_tokens = list(schema["validation"]["forbidden_path_tokens"])
    sha_pattern = re.compile(schema["validation"]["commit_sha_pattern"])
    vu_status = set(schema.get("verified_uncommitted_status_enum", {}).get("values", {"TEST", "ONAYLANDI"}))

    records_root = _records_root(root)
    if records_root is None:
        return [], 0

    records_dir = root / "changes" / "records"
    candidate_paths, skipped = _collect_record_paths(records_dir, records_root)
    valid: list[ReleaseRecord] = []

    for path in candidate_paths:
        try:
            data = _load_toml(path)
            if data is None:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        record = _record_from_toml(data, forbidden_tokens)
        if not record:
            skipped += 1
            continue
        if record.module not in allowlist:
            skipped += 1
            continue
        if record.status not in status_values:
            skipped += 1
            continue

        if record.source_type == UNCOMMITTED_SOURCE:
            if record.status not in vu_status:
                skipped += 1
                continue
        else:
            if not record.commit_sha or not sha_pattern.match(record.commit_sha):
                skipped += 1
                continue

        valid.append(record)

    valid.sort(key=lambda item: (item.date, _version_key(item.version), item.phase_code), reverse=True)
    return valid, skipped


def _resolve_push_status(
    module: str,
    record: ReleaseRecord,
    deploy_state: dict[str, Any],
    *,
    uncommitted_count: int = 0,
) -> str:
    modules_state = deploy_state.get("modules", {})
    if isinstance(modules_state, dict) and module in modules_state:
        val = str(modules_state[module].get("push_status", "")).strip().upper()
        if val and val not in {"", "DEPLOYMENT_UNKNOWN"}:
            return val

    global_state = str(deploy_state.get("global_state", "")).strip().upper()
    if uncommitted_count > 0 or record.is_uncommitted:
        if global_state == "COMMIT_PENDING":
            return "COMMIT_PENDING"
        return "WORKING"
    if global_state in {
        "WORKING", "COMMIT_PENDING", "LOCAL_COMMITTED_NOT_PUSHED",
        "PUSHED_NOT_DEPLOYED", "DEPLOYED_VERIFIED", "DEPLOY_FAILED", "NEEDS_REVIEW",
    }:
        return global_state
    push = (record.push_status or "").upper()
    if push and push != "DEPLOYMENT_UNKNOWN":
        return push
    return "DEPLOYMENT_UNKNOWN"


def aggregate_modules(records: list[ReleaseRecord], deploy_state: dict[str, Any] | None = None) -> list[ModuleSummary]:
    deploy_state = deploy_state or {}
    grouped: dict[str, list[ReleaseRecord]] = {}
    for record in records:
        grouped.setdefault(record.module, []).append(record)

    summaries: list[ModuleSummary] = []
    for module, items in grouped.items():
        items.sort(key=lambda item: (item.date, _version_key(item.version), item.phase_code), reverse=True)
        latest = items[0]
        committed = [r for r in items if not r.is_uncommitted]
        uncommitted = [r for r in items if r.is_uncommitted]
        current = max(items, key=lambda item: (_version_key(item.version), item.date, item.phase_code))
        last_completed = committed[0] if committed else latest
        current_work_rec = uncommitted[0] if uncommitted else None
        current_work = current_work_rec.current_work if current_work_rec else "—"
        if current_work == "—" and latest.status in {"TASLAK", "TEST"}:
            current_work = latest.title
        next_step = latest.next_steps[0] if latest.next_steps else "—"
        push_auto = _resolve_push_status(module, latest, deploy_state, uncommitted_count=len(uncommitted))
        summaries.append(
            ModuleSummary(
                module=module,
                module_label=_module_label(module),
                current_version=current.version,
                live_version=latest.live_version,
                local_version=latest.local_version or latest.version,
                version_count=len(items),
                latest_phase=latest.phase_code,
                last_completed_phase=last_completed.phase_code if not last_completed.is_uncommitted else (committed[0].phase_code if committed else "—"),
                latest_title=latest.title,
                status=latest.status if not uncommitted else uncommitted[0].status,
                date=latest.date,
                commit_short=latest.commit_short,
                test_result=latest.test_result,
                test_status_label=latest.test_result[:40] + ("…" if len(latest.test_result) > 40 else ""),
                deploy_label=_deploy_label(latest.deployment_status, push_auto, latest.source_type),
                deployment_status=latest.deployment_status or push_auto,
                push_status_auto=push_auto,
                push_status_label=PUSH_STATUS_LABELS.get(push_auto, push_auto.replace("_", " ")),
                current_work=current_work,
                next_step=next_step,
                commit_pending_count=len(uncommitted),
                record_count=len(items),
            )
        )

    summaries.sort(key=lambda item: item.module_label.lower())
    return summaries


def build_summary_counts(
    records: list[ReleaseRecord],
    modules: list[ModuleSummary],
    deploy_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deploy_state = deploy_state or {}
    locked_modules = sum(1 for item in modules if item.status == "KILITLI")
    in_progress = sum(1 for item in modules if item.status in {"TASLAK", "TEST"} or item.commit_pending_count > 0)
    deploy_waiting = sum(1 for item in modules if _module_deploy_pending(item))
    deploy_unknown = sum(1 for item in modules if _module_deploy_unknown(item))
    push_waiting = sum(1 for item in modules if item.push_status_auto == "LOCAL_COMMITTED_NOT_PUSHED")
    commit_pending = sum(item.commit_pending_count for item in modules)
    live_current = sum(1 for item in modules if item.push_status_auto == "DEPLOYED_VERIFIED")
    open_issues = sum(len(record.known_issues) for record in records)
    global_state = str(deploy_state.get("global_state", "")).upper()
    return {
        "total_modules": len(modules),
        "global_state": global_state,
        "locked_modules": locked_modules,
        "in_progress_modules": in_progress,
        "commit_pending_modules": sum(1 for m in modules if m.commit_pending_count > 0),
        "commit_pending_records": commit_pending,
        "deploy_waiting_modules": deploy_waiting,
        "deploy_unknown_modules": deploy_unknown,
        "push_waiting_modules": push_waiting,
        "live_current_modules": live_current,
        "open_issues": open_issues,
        "total_records": len(records),
        "invalid_records": 0,
    }


def filter_modules(
    modules: list[ModuleSummary],
    *,
    module_query: str = "",
    status: str = "",
    deployment: str = "",
) -> list[ModuleSummary]:
    query = (module_query or "").strip().lower()
    status = (status or "").strip().upper()
    deployment = (deployment or "").strip().upper()

    filtered: list[ModuleSummary] = []
    for item in modules:
        if query and query not in item.module.lower() and query not in item.module_label.lower():
            continue
        if status and item.status != status:
            continue
        if deployment:
            dep_val = (item.deployment_status or "").upper()
            push_val = (item.push_status_auto or "").upper()
            if deployment == "LOCAL_WAIT" and not _module_deploy_pending(item):
                continue
            if deployment == "COMMIT_PENDING" and item.commit_pending_count <= 0:
                continue
            if deployment == "DEPLOYMENT_UNKNOWN" and not _module_deploy_unknown(item):
                continue
            if deployment == "PUSH_WAIT" and push_val != "LOCAL_COMMITTED_NOT_PUSHED":
                continue
            if deployment not in {"LOCAL_WAIT", "DEPLOYMENT_UNKNOWN", "COMMIT_PENDING", "PUSH_WAIT"} and dep_val != deployment:
                continue
        filtered.append(item)
    return filtered


def find_record(records: list[ReleaseRecord], module: str | None, phase_code: str | None) -> ReleaseRecord | None:
    if not module or not phase_code:
        return None
    if not re.fullmatch(r"[a-z0-9.]+", module):
        return None
    if not re.fullmatch(r"[A-Z0-9_]+", phase_code):
        return None
    for record in records:
        if record.module == module and record.phase_code == phase_code:
            return record
    return None


def module_timeline(records: list[ReleaseRecord], module: str | None) -> list[ReleaseRecord]:
    if not module or not re.fullmatch(r"[a-z0-9.]+", module):
        return []
    items = [r for r in records if r.module == module]
    items.sort(key=lambda item: (item.date, _version_key(item.version), item.phase_code), reverse=True)
    return items


def build_page_context(
    base: Path | None = None,
    *,
    module_query: str = "",
    status: str = "",
    deployment: str = "",
    detail_module: str | None = None,
    detail_phase: str | None = None,
) -> dict[str, Any]:
    root = base or REPO_ROOT
    deploy_state = load_deployment_state(root)
    records, skipped = load_release_records(root)
    modules = aggregate_modules(records, deploy_state)
    counts = build_summary_counts(records, modules, deploy_state)
    counts["invalid_records"] = skipped

    filtered_modules = filter_modules(
        modules,
        module_query=module_query,
        status=status,
        deployment=deployment,
    )

    detail = find_record(records, detail_module, detail_phase)
    timeline = module_timeline(records, detail_module) if detail_module else []

    return {
        "summary": counts,
        "modules": filtered_modules,
        "all_modules": modules,
        "records": records,
        "detail": detail,
        "timeline": timeline,
        "deploy_state": deploy_state,
        "filters": {
            "module_query": module_query or "",
            "status": status or "",
            "deployment": deployment or "",
        },
        "status_options": list(STATUS_LABELS.keys()),
        "status_labels": STATUS_LABELS,
        "module_labels": MODULE_LABELS,
        "push_status_labels": PUSH_STATUS_LABELS,
    }

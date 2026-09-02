# -*- coding: utf-8 -*-
"""Read-only CPS release history loader (stdlib tomllib only)."""
from __future__ import annotations

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

MODULE_LABELS: dict[str, str] = {
    "nexgen.mo": "Müşteri Operasyonu",
    "nexgen.etiket": "NexGen Etiket Basım",
    "planlama.atp": "Araç Takip",
    "planlama.aps": "APS Genel Plan",
    "finans": "Finans",
    "cari360": "Cari360",
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

DEPLOY_WAIT_STATUSES = frozenset({
    "LOCAL_COMMITTED_NOT_PUSHED",
    "LOCAL_READY_FOR_MONDAY_DEPLOY",
})

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
    changes: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    locked_rules: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class ModuleSummary:
    module: str
    module_label: str
    current_version: str
    live_version: str
    local_version: str
    latest_phase: str
    latest_title: str
    status: str
    date: str
    commit_short: str
    test_result: str
    deploy_label: str
    deployment_status: str
    next_step: str
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
    return text[:8] if text else ""


def _deploy_label(deployment_status: str, push_status: str) -> str:
    if deployment_status in DEPLOY_WAIT_STATUSES or push_status in DEPLOY_WAIT_STATUSES:
        return "Yerelde hazır · Server aktarımı bekliyor"
    if deployment_status:
        return deployment_status.replace("_", " ")
    if push_status:
        return push_status.replace("_", " ")
    return "—"


def _module_label(module: str) -> str:
    return MODULE_LABELS.get(module, module)


def _record_from_toml(data: dict[str, Any], forbidden_tokens: list[str]) -> ReleaseRecord | None:
    required = (
        "module", "version", "phase_code", "title", "status", "date",
        "summary", "commit_sha", "test_result", "push_status",
    )
    for key in required:
        if key not in data:
            return None

    module = str(data["module"])
    phase_code = str(data["phase_code"])
    if not re.fullmatch(r"[a-z0-9.]+", module):
        return None
    if not re.fullmatch(r"[A-Z0-9_]+", phase_code):
        return None

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
        commit_sha=str(data["commit_sha"]),
        commit_short=_short_sha(str(data["commit_sha"])),
        test_result=_sanitize_text(data.get("test_result", ""), forbidden_tokens),
        push_status=push_status,
        deployment_status=deployment_status,
        deploy_label=_deploy_label(deployment_status, push_status),
        live_version=live_version,
        local_version=local_version,
        root_cause=_sanitize_text(data.get("root_cause", ""), forbidden_tokens),
        migration=_sanitize_text(data.get("migration", ""), forbidden_tokens),
        evidence_summary=_sanitize_text(data.get("evidence_summary", ""), forbidden_tokens),
        changes=_sanitize_list(data.get("changes"), forbidden_tokens),
        changed_files=_sanitize_list(data.get("changed_files"), forbidden_tokens),
        locked_rules=_sanitize_list(data.get("locked_rules"), forbidden_tokens),
        tests=_sanitize_list(data.get("tests"), forbidden_tokens),
        known_issues=_sanitize_list(data.get("known_issues"), forbidden_tokens),
        next_steps=_sanitize_list(data.get("next_steps"), forbidden_tokens),
    )


def load_release_records(base: Path | None = None) -> tuple[list[ReleaseRecord], int]:
    """Return valid records and skipped invalid record count."""
    root = base or REPO_ROOT
    schema = _load_schema()
    allowlist = set(schema["module_allowlist"]["modules"])
    status_values = set(schema["status_enum"]["values"])
    forbidden_tokens = list(schema["validation"]["forbidden_path_tokens"])
    sha_pattern = re.compile(schema["validation"]["commit_sha_pattern"])

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
        if not sha_pattern.match(record.commit_sha):
            skipped += 1
            continue

        valid.append(record)

    valid.sort(key=lambda item: (item.date, _version_key(item.version), item.phase_code), reverse=True)
    return valid, skipped


def aggregate_modules(records: list[ReleaseRecord]) -> list[ModuleSummary]:
    grouped: dict[str, list[ReleaseRecord]] = {}
    for record in records:
        grouped.setdefault(record.module, []).append(record)

    summaries: list[ModuleSummary] = []
    for module, items in grouped.items():
        items.sort(key=lambda item: (item.date, _version_key(item.version), item.phase_code), reverse=True)
        latest = items[0]
        current = max(items, key=lambda item: (_version_key(item.version), item.date, item.phase_code))
        next_step = latest.next_steps[0] if latest.next_steps else "—"
        summaries.append(
            ModuleSummary(
                module=module,
                module_label=_module_label(module),
                current_version=current.version,
                live_version=latest.live_version,
                local_version=latest.local_version or latest.version,
                latest_phase=latest.phase_code,
                latest_title=latest.title,
                status=latest.status,
                date=latest.date,
                commit_short=latest.commit_short,
                test_result=latest.test_result,
                deploy_label=latest.deploy_label,
                deployment_status=latest.deployment_status,
                next_step=next_step,
                record_count=len(items),
            )
        )

    summaries.sort(key=lambda item: item.module_label.lower())
    return summaries


def build_summary_counts(records: list[ReleaseRecord], modules: list[ModuleSummary]) -> dict[str, int]:
    locked_modules = sum(1 for item in modules if item.status == "KILITLI")
    in_progress = sum(1 for item in modules if item.status in {"TASLAK", "TEST"})
    deploy_waiting = sum(
        1 for item in modules
        if item.deployment_status in DEPLOY_WAIT_STATUSES or "Server aktarımı" in item.deploy_label
    )
    open_issues = sum(len(record.known_issues) for record in records)
    return {
        "total_modules": len(modules),
        "locked_modules": locked_modules,
        "in_progress_modules": in_progress,
        "deploy_waiting_modules": deploy_waiting,
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
            push_like = "LOCAL" in dep_val or dep_val in DEPLOY_WAIT_STATUSES
            if deployment == "LOCAL_WAIT" and not push_like and "Server aktarımı" not in item.deploy_label:
                continue
            if deployment not in {"LOCAL_WAIT"} and dep_val != deployment:
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


def build_page_context(
    base: Path | None = None,
    *,
    module_query: str = "",
    status: str = "",
    deployment: str = "",
    detail_module: str | None = None,
    detail_phase: str | None = None,
) -> dict[str, Any]:
    records, skipped = load_release_records(base)
    modules = aggregate_modules(records)
    counts = build_summary_counts(records, modules)
    counts["invalid_records"] = skipped

    filtered_modules = filter_modules(
        modules,
        module_query=module_query,
        status=status,
        deployment=deployment,
    )

    detail = find_record(records, detail_module, detail_phase)
    status_options = list(STATUS_LABELS.keys())

    return {
        "summary": counts,
        "modules": filtered_modules,
        "all_modules": modules,
        "records": records,
        "detail": detail,
        "filters": {
            "module_query": module_query or "",
            "status": status or "",
            "deployment": deployment or "",
        },
        "status_options": status_options,
        "status_labels": STATUS_LABELS,
        "module_labels": MODULE_LABELS,
    }

# -*- coding: utf-8 -*-
"""Read-only CPS release history loader with deployment state cache."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

LIFECYCLE_COMMIT_PENDING = "COMMIT_PENDING"
LIFECYCLE_LOCAL_NOT_PUSHED = "LOCAL_COMMITTED_NOT_PUSHED"
LIFECYCLE_PUSHED_NOT_DEPLOYED = "PUSHED_NOT_DEPLOYED"
LIFECYCLE_DEPLOYED_VERIFIED = "DEPLOYED_VERIFIED"
LIFECYCLE_DEPLOY_FAILED = "DEPLOY_FAILED"
LIFECYCLE_DEPLOYMENT_UNKNOWN = "DEPLOYMENT_UNKNOWN"
LIFECYCLE_NEEDS_REVIEW = "NEEDS_REVIEW"
LIFECYCLE_WORKING = "WORKING"

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

UNCOMMITTED_PUSH_LABEL = "Commit bekliyor · Push yapılmadı"

PRODUCTION_STAGED_PREFIXES = (
    "app/modules/",
    "app/templates/",
    "app/static/",
    "app/migrations/",
)

PUSH_STATUS_LABELS: dict[str, str] = {
    "WORKING": "Çalışılıyor",
    "COMMIT_PENDING": "Commit bekliyor · Push yapılmadı",
    "TESTED": "Test edildi",
    "LOCAL_COMMITTED_NOT_PUSHED": "Yerelde commitli · Push yapılmadı",
    "PUSHED_NOT_DEPLOYED": "Push yapıldı",
    "DEPLOYED_VERIFIED": "Push yapıldı",
    "DEPLOY_FAILED": "Push durumu bilinmiyor",
    "DEPLOYMENT_UNKNOWN": "Push durumu bilinmiyor",
    "NEEDS_REVIEW": "Push durumu inceleme bekliyor",
}

DEPLOY_STATUS_LABELS: dict[str, str] = {
    "WORKING": "Deploy edilmedi",
    "COMMIT_PENDING": "Deploy edilmedi",
    "LOCAL_COMMITTED_NOT_PUSHED": "Deploy edilmedi",
    "PUSHED_NOT_DEPLOYED": "Push yapıldı · Deploy bekliyor",
    "DEPLOYED_VERIFIED": "Canlıda doğrulandı",
    "DEPLOY_FAILED": "Deploy başarısız",
    "DEPLOYMENT_UNKNOWN": "Deploy durumu bilinmiyor",
    "NEEDS_REVIEW": "Deploy durumu inceleme bekliyor",
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
    last_completed_title: str
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


def _is_staged_production_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    if not normalized:
        return False
    return any(normalized.startswith(prefix) for prefix in PRODUCTION_STAGED_PREFIXES)


def _has_staged_production_files(base: Path | None = None) -> bool:
    root = base or REPO_ROOT
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    return any(_is_staged_production_path(line) for line in proc.stdout.splitlines())


def _rules_heading(record: ReleaseRecord | None) -> str:
    if not record:
        return "Kilitli kurallar"
    if record.is_uncommitted or record.status == "TEST":
        return "Test Edilen Kurallar"
    if record.status == "KILITLI":
        return "Kilitli Kurallar"
    return "Kilitli kurallar"


def _git_rev_parse(ref: str, base: Path | None = None) -> str:
    if not ref:
        return ""
    proc = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=base or REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_is_ancestor(ancestor: str, descendant: str, base: Path | None = None) -> bool | None:
    if not ancestor or not descendant:
        return None
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=base or REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _git_head(base: Path | None = None) -> str:
    return _git_rev_parse("HEAD", base)


def _git_origin_main(base: Path | None = None) -> str:
    root = base or REPO_ROOT
    for ref in ("origin/main", "refs/remotes/origin/main"):
        resolved = _git_rev_parse(ref, root)
        if resolved:
            return resolved
    return ""


@dataclass
class GitEvidenceCache:
    base: Path = REPO_ROOT
    _head: str | None = field(default=None, init=False, repr=False)
    _origin_main: str | None = field(default=None, init=False, repr=False)
    _origin_loaded: bool = field(default=False, init=False, repr=False)
    _reachable: dict[str, set[str] | None] = field(default_factory=dict, init=False, repr=False)
    _sha_cache: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def resolve_sha(self, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if text in self._sha_cache:
            return self._sha_cache[text]
        if re.fullmatch(r"[0-9a-fA-F]{40}", text):
            normalized = text.lower()
            self._sha_cache[text] = normalized
            return normalized
        full = _git_rev_parse(text, self.base) or text
        self._sha_cache[text] = full
        return full

    def head(self) -> str:
        if self._head is None:
            self._head = _git_head(self.base)
        return self._head

    def origin_main(self) -> str:
        if not self._origin_loaded:
            self._origin_main = _git_origin_main(self.base)
            self._origin_loaded = True
        return self._origin_main or ""

    def _reachable_commits(self, ref: str) -> set[str] | None:
        full = _git_rev_parse(ref, self.base) or ref
        if full in self._reachable:
            return self._reachable[full]
        proc = subprocess.run(
            ["git", "rev-list", full],
            cwd=self.base,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            self._reachable[full] = None
            return None
        commits = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
        commits.add(full)
        self._reachable[full] = commits
        return commits

    def is_ancestor(self, ancestor: str, descendant: str) -> bool | None:
        anc = self.resolve_sha(ancestor)
        desc = self.resolve_sha(descendant)
        if not anc or not desc:
            return None
        reachable = self._reachable_commits(desc)
        if reachable is None:
            return None
        return anc in reachable


def _normalize_sha(value: str, git: GitEvidenceCache) -> str:
    return git.resolve_sha(value)


def _is_deploy_state_stale(deploy_state: dict[str, Any], git: GitEvidenceCache) -> bool:
    if not deploy_state:
        return True
    manifest_head = _normalize_sha(str(deploy_state.get("local_head", "")), git)
    current_head = git.head()
    if not current_head:
        return True
    if not manifest_head:
        return True
    return manifest_head != current_head


def _manifest_deploy_verified_for_record(
    deploy_state: dict[str, Any],
    record_sha: str,
    git: GitEvidenceCache,
) -> bool:
    if not deploy_state or not record_sha:
        return False
    manifest_check = deploy_state.get("manifest_check")
    if not isinstance(manifest_check, dict):
        return False
    if str(manifest_check.get("status", "")).upper() != LIFECYCLE_DEPLOYED_VERIFIED:
        return False
    if not manifest_check.get("smoke_pass"):
        return False
    manifest_sha = _normalize_sha(str(manifest_check.get("sha_resolved", "")), git)
    record_full = _normalize_sha(record_sha, git)
    if not manifest_sha or not record_full:
        return False
    covered = git.is_ancestor(record_full, manifest_sha)
    return covered is True


def resolve_record_lifecycle_state(
    record: ReleaseRecord,
    deploy_state: dict[str, Any],
    git: GitEvidenceCache,
) -> str:
    if record.is_uncommitted or not (record.commit_sha or "").strip():
        return LIFECYCLE_COMMIT_PENDING

    record_sha = _normalize_sha(record.commit_sha, git)
    head = git.head()
    if not record_sha or not head:
        return LIFECYCLE_DEPLOYMENT_UNKNOWN

    on_head = git.is_ancestor(record_sha, head)
    if on_head is False:
        return LIFECYCLE_NEEDS_REVIEW
    if on_head is None:
        return LIFECYCLE_DEPLOYMENT_UNKNOWN

    if _manifest_deploy_verified_for_record(deploy_state, record_sha, git):
        return LIFECYCLE_DEPLOYED_VERIFIED

    origin_main = git.origin_main()
    if origin_main:
        on_origin = git.is_ancestor(record_sha, origin_main)
        if on_origin is False:
            return LIFECYCLE_LOCAL_NOT_PUSHED
        if on_origin is None:
            return LIFECYCLE_DEPLOYMENT_UNKNOWN
        if on_origin is True:
            return LIFECYCLE_PUSHED_NOT_DEPLOYED

    return LIFECYCLE_LOCAL_NOT_PUSHED


def _module_lifecycle_state(
    module: str,
    latest: ReleaseRecord,
    deploy_state: dict[str, Any],
    git: GitEvidenceCache,
    *,
    uncommitted_count: int = 0,
) -> str:
    if uncommitted_count > 0:
        return LIFECYCLE_COMMIT_PENDING
    if not _is_deploy_state_stale(deploy_state, git):
        modules_state = deploy_state.get("modules", {})
        if isinstance(modules_state, dict) and module in modules_state:
            val = str(modules_state[module].get("push_status", "")).strip().upper()
            if val in {
                LIFECYCLE_WORKING,
                LIFECYCLE_COMMIT_PENDING,
                LIFECYCLE_LOCAL_NOT_PUSHED,
                LIFECYCLE_PUSHED_NOT_DEPLOYED,
                LIFECYCLE_DEPLOYED_VERIFIED,
                LIFECYCLE_DEPLOY_FAILED,
                LIFECYCLE_NEEDS_REVIEW,
            }:
                return val
    return resolve_record_lifecycle_state(latest, deploy_state, git)


def format_push_status_label(lifecycle: str) -> str:
    key = (lifecycle or "").strip().upper()
    return PUSH_STATUS_LABELS.get(key, "Push durumu bilinmiyor")


def format_deploy_status_label(lifecycle: str) -> str:
    key = (lifecycle or "").strip().upper()
    return DEPLOY_STATUS_LABELS.get(key, "Deploy durumu bilinmiyor")


def _format_push_status_label(
    push_auto: str,
    *,
    uncommitted_count: int = 0,
    production_staged: bool = False,
) -> str:
    if uncommitted_count > 0:
        return UNCOMMITTED_PUSH_LABEL
    if push_auto == LIFECYCLE_COMMIT_PENDING and production_staged:
        return PUSH_STATUS_LABELS[LIFECYCLE_COMMIT_PENDING]
    return format_push_status_label(push_auto)


def _deploy_label(
    lifecycle: str,
    *,
    source_type: str = COMMITTED_SOURCE,
) -> str:
    if source_type == UNCOMMITTED_SOURCE:
        return DEPLOY_STATUS_LABELS[LIFECYCLE_COMMIT_PENDING]
    return format_deploy_status_label(lifecycle)


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
        deploy_label=format_deploy_status_label(LIFECYCLE_DEPLOYMENT_UNKNOWN),
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
    git: GitEvidenceCache,
    *,
    uncommitted_count: int = 0,
) -> str:
    return _module_lifecycle_state(
        module,
        record,
        deploy_state,
        git,
        uncommitted_count=uncommitted_count,
    )


def aggregate_modules(
    records: list[ReleaseRecord],
    deploy_state: dict[str, Any] | None = None,
    *,
    base: Path | None = None,
) -> list[ModuleSummary]:
    deploy_state = deploy_state or {}
    git = GitEvidenceCache(base=base or REPO_ROOT)
    production_staged = _has_staged_production_files(base)
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
        if committed:
            last_completed = committed[0]
            last_completed_phase = last_completed.phase_code
            last_completed_title = last_completed.title or last_completed.summary or "—"
        else:
            last_completed_phase = "—"
            last_completed_title = "—"
        current_work_rec = uncommitted[0] if uncommitted else None
        if current_work_rec:
            current_work = current_work_rec.current_work or current_work_rec.title or "—"
        else:
            current_work = "—"
        next_step = latest.next_steps[0] if latest.next_steps else "—"
        lifecycle = _module_lifecycle_state(
            module,
            latest,
            deploy_state,
            git,
            uncommitted_count=len(uncommitted),
        )
        deploy_source = UNCOMMITTED_SOURCE if uncommitted else latest.source_type
        summaries.append(
            ModuleSummary(
                module=module,
                module_label=_module_label(module),
                current_version=current.version,
                live_version=latest.live_version,
                local_version=latest.local_version or latest.version,
                version_count=len(items),
                latest_phase=latest.phase_code,
                last_completed_phase=last_completed_phase,
                last_completed_title=last_completed_title,
                latest_title=latest.title,
                status=latest.status if not uncommitted else uncommitted[0].status,
                date=latest.date,
                commit_short=latest.commit_short,
                test_result=latest.test_result,
                test_status_label=latest.test_result[:40] + ("…" if len(latest.test_result) > 40 else ""),
                deploy_label=_deploy_label(lifecycle, source_type=deploy_source),
                deployment_status=lifecycle,
                push_status_auto=lifecycle,
                push_status_label=_format_push_status_label(
                    lifecycle,
                    uncommitted_count=len(uncommitted),
                    production_staged=production_staged,
                ),
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
        "open_issues_unit": "madde",
        "open_issues_semantics": "Tüm kayıtlardaki known_issues maddelerinin toplamı",
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


def build_record_phase_panel(
    record: ReleaseRecord,
    deploy_state: dict[str, Any],
    git: GitEvidenceCache,
    lifecycle_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    if record.is_uncommitted or not (record.commit_sha or "").strip():
        lifecycle = LIFECYCLE_COMMIT_PENDING
    else:
        sha_key = _normalize_sha(record.commit_sha, git)
        if lifecycle_cache is not None and sha_key in lifecycle_cache:
            lifecycle = lifecycle_cache[sha_key]
        else:
            lifecycle = resolve_record_lifecycle_state(record, deploy_state, git)
            if lifecycle_cache is not None and sha_key:
                lifecycle_cache[sha_key] = lifecycle
    return {
        "phase_code": record.phase_code,
        "heading": _rules_heading(record),
        "rules": list(record.locked_rules)[:8],
        "known_issues": list(record.known_issues)[:8],
        "source_type": record.source_type,
        "status": record.status,
        "lifecycle": lifecycle,
        "commit_short": record.commit_short,
        "commit_pending": record.is_uncommitted,
        "push_status_label": format_push_status_label(lifecycle),
        "deploy_status_label": format_deploy_status_label(lifecycle),
    }


def _selected_rules_panel(
    record: ReleaseRecord | None,
    deploy_state: dict[str, Any] | None = None,
    git: GitEvidenceCache | None = None,
    lifecycle_cache: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not record:
        return None
    state = deploy_state or {}
    cache = git or GitEvidenceCache()
    return build_record_phase_panel(record, state, cache, lifecycle_cache)


def build_module_selected_rules(
    records: list[ReleaseRecord],
    detail_module: str | None,
    detail_phase: str | None,
    deploy_state: dict[str, Any] | None = None,
    git: GitEvidenceCache | None = None,
    lifecycle_cache: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    if not detail_module or not detail_phase:
        return {}
    selected = find_record(records, detail_module, detail_phase)
    panel = _selected_rules_panel(selected, deploy_state, git, lifecycle_cache)
    if not panel:
        return {}
    return {detail_module: panel}


def build_module_phase_rules_index(
    records: list[ReleaseRecord],
    visible_modules: Iterable[str] | None,
    deploy_state: dict[str, Any],
    git: GitEvidenceCache,
    lifecycle_cache: dict[str, str] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    allowed = set(visible_modules) if visible_modules is not None else None
    index: dict[str, dict[str, dict[str, Any]]] = {}
    cache = lifecycle_cache if lifecycle_cache is not None else {}
    for record in records:
        if allowed is not None and record.module not in allowed:
            continue
        if not re.fullmatch(r"[a-z0-9.]+", record.module):
            continue
        if not re.fullmatch(r"[A-Z0-9_]+", record.phase_code):
            continue
        index.setdefault(record.module, {})[record.phase_code] = build_record_phase_panel(
            record,
            deploy_state,
            git,
            cache,
        )
    return index


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
    git = GitEvidenceCache(base=root)
    head_ref = git.head()
    if head_ref:
        git._reachable_commits(head_ref)
    origin_ref = git.origin_main()
    if origin_ref:
        git._reachable_commits(origin_ref)
    records, skipped = load_release_records(root)
    modules = aggregate_modules(records, deploy_state, base=root)
    counts = build_summary_counts(records, modules, deploy_state)
    counts["invalid_records"] = skipped
    deploy_state_stale = _is_deploy_state_stale(deploy_state, git)

    filtered_modules = filter_modules(
        modules,
        module_query=module_query,
        status=status,
        deployment=deployment,
    )

    detail = find_record(records, detail_module, detail_phase)
    timeline = module_timeline(records, detail_module) if detail_module else []
    module_timelines = {m.module: module_timeline(records, m.module) for m in filtered_modules}
    lifecycle_cache: dict[str, str] = {}
    module_selected_rules = build_module_selected_rules(
        records,
        detail_module,
        detail_phase,
        deploy_state,
        git,
        lifecycle_cache,
    )
    visible_module_ids = [m.module for m in filtered_modules]
    module_phase_rules = build_module_phase_rules_index(
        records,
        visible_module_ids,
        deploy_state,
        git,
        lifecycle_cache,
    )

    return {
        "summary": counts,
        "modules": filtered_modules,
        "all_modules": modules,
        "records": records,
        "detail": detail,
        "detail_phase": detail_phase or "",
        "timeline": timeline,
        "module_timelines": module_timelines,
        "module_selected_rules": module_selected_rules,
        "module_phase_rules": module_phase_rules,
        "open_module": detail_module or "",
        "deploy_state": deploy_state,
        "deploy_state_stale": deploy_state_stale,
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

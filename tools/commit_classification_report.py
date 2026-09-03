#!/usr/bin/env python3
"""Report commit classification coverage for 30-day window."""
from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_log():
    out = subprocess.check_output(
        ["git", "log", "--since=2026-08-01", "--until=2026-09-03", "--format=%H|%h|%s"],
        cwd=ROOT, text=True,
    )
    for line in out.splitlines():
        if "|" in line:
            full, short, subj = line.split("|", 2)
            yield full.strip(), short.strip(), subj.strip()


def covered_shas() -> dict[str, str]:
    primary: set[str] = set()
    related: set[str] = set()
    for path in (ROOT / "changes" / "records").rglob("*.toml"):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        sha = str(data.get("commit_sha", "")).strip()
        if sha and re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            primary.add(subprocess.check_output(["git", "rev-parse", sha], cwd=ROOT, text=True).strip())
        for rc in data.get("related_commits", []) or []:
            related.add(subprocess.check_output(["git", "rev-parse", rc], cwd=ROOT, text=True).strip())
    return {"primary": primary, "related": related}


def main():
    commits = list(git_log())
    cov = covered_shas()
    primary = cov["primary"]
    related = cov["related"]
    excluded = {"9941cdc", "7962220"}  # meta history commits

    classified_primary = 0
    classified_related = 0
    unclassified = []

    for full, short, subj in commits:
        if full in primary:
            classified_primary += 1
        elif full in related:
            classified_related += 1
        elif short in excluded or full.startswith(tuple(excluded)):
            pass
        else:
            unclassified.append((short, subj))

    print(f"WINDOW_COMMITS={len(commits)}")
    print(f"PRIMARY={classified_primary}")
    print(f"RELATED={classified_related}")
    print(f"EXCLUDED_META={len(commits) - classified_primary - classified_related - len(unclassified)}")
    print(f"UNCLASSIFIED={len(unclassified)}")
    print(f"TOTAL_CLASSIFIED={classified_primary + classified_related}")
    for short, subj in unclassified[:15]:
        print(f"  ? {short} {subj[:60]}")


if __name__ == "__main__":
    main()

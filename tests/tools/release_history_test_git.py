# -*- coding: utf-8 -*-
"""GitEvidenceCache test doubles for release-history service tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def mock_git_cache(
    *,
    base: Path,
    head: str,
    origin: str,
    head_set: set[str],
    origin_set: set[str],
    unknown_refs: set[str] | None = None,
) -> Any:
    """Minimal GitEvidenceCache stand-in with controllable ancestry."""
    unknown = {s.lower() for s in (unknown_refs or set())}

    class _Cache:
        def __init__(self) -> None:
            self.base = base

        def head(self) -> str:
            return head

        def origin_main(self) -> str:
            return origin

        def resolve_sha(self, value: str) -> str:
            return (value or "").strip().lower()

        def _reachable_commits(self, ref: str) -> set[str] | None:
            ref = (ref or "").lower()
            if ref in unknown:
                return None
            if ref == head.lower():
                return {s.lower() for s in head_set}
            if ref == origin.lower():
                return {s.lower() for s in origin_set}
            return set()

        def is_ancestor(self, ancestor: str, descendant: str) -> bool | None:
            anc = self.resolve_sha(ancestor)
            if anc in unknown:
                return None
            desc = self.resolve_sha(descendant)
            reachable = self._reachable_commits(desc)
            if reachable is None:
                return None
            return anc in reachable

    return _Cache()


NEXGEN_RECORD_SHA = "ad5fd3034497c6d5a1fea18b433c910b976b806f"
PUSHED_RECORD_SHA = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
UNKNOWN_RECORD_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MOCK_HEAD = "cccccccccccccccccccccccccccccccccccccccc"
MOCK_ORIGIN = "dddddddddddddddddddddddddddddddddddddddd"

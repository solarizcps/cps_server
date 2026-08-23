# -*- coding: utf-8 -*-
"""In-process route cache — 15 minute TTL."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

_TTL_SEC = 15 * 60
_LOCK = threading.Lock()
_STORE: dict[str, tuple[float, Any]] = {}


def _round_coord(v: float) -> float:
    return round(float(v), 5)


def make_cache_key(provider: str, profile: str, points: list[tuple[float, float]]) -> str:
    payload = {
        'provider': provider,
        'profile': profile,
        'points': [[_round_coord(a), _round_coord(b)] for a, b in points],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def cache_get(key: str) -> Any | None:
    now = time.time()
    with _LOCK:
        row = _STORE.get(key)
        if not row:
            return None
        expires, value = row
        if expires <= now:
            del _STORE[key]
            return None
        return value


def cache_set(key: str, value: Any) -> None:
    with _LOCK:
        _STORE[key] = (time.time() + _TTL_SEC, value)


def cache_clear() -> None:
    with _LOCK:
        _STORE.clear()

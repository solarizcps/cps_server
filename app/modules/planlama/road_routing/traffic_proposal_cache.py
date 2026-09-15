# -*- coding: utf-8 -*-
"""R07 traffic proposal cache — 5 min TTL, single-flight dedupe."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_TTL_SEC = 300
_LOCK = threading.Lock()
_STORE: dict[str, tuple[float, Any]] = {}
_INFLIGHT: dict[str, threading.Event] = {}
_INFLIGHT_RESULT: dict[str, Any] = {}


def get_cached(key: str) -> Any | None:
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


def set_cached(key: str, value: Any) -> None:
    with _LOCK:
        _STORE[key] = (time.time() + _TTL_SEC, value)


def single_flight(key: str, fn: Callable[[], Any]) -> tuple[Any, bool]:
    """Run fn once per key; concurrent callers wait. Returns (value, cache_hit)."""
    cached = get_cached(key)
    if cached is not None:
        return cached, True

    with _LOCK:
        cached = _STORE.get(key)
        if cached and cached[0] > time.time():
            return cached[1], True
        if key in _INFLIGHT:
            ev = _INFLIGHT[key]
            is_leader = False
        else:
            ev = threading.Event()
            _INFLIGHT[key] = ev
            is_leader = True

    if not is_leader:
        ev.wait(timeout=120)
        with _LOCK:
            if key in _INFLIGHT_RESULT:
                return _INFLIGHT_RESULT[key], False
            row = _STORE.get(key)
            if row and row[0] > time.time():
                return row[1], True
        return fn(), False

    try:
        value = fn()
        set_cached(key, value)
        with _LOCK:
            _INFLIGHT_RESULT[key] = value
        return value, False
    finally:
        with _LOCK:
            ev = _INFLIGHT.pop(key, None)
            if ev:
                ev.set()
            _INFLIGHT_RESULT.pop(key, None)


def cache_clear() -> None:
    with _LOCK:
        _STORE.clear()
        _INFLIGHT.clear()
        _INFLIGHT_RESULT.clear()

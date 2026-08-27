# -*- coding: utf-8 -*-
"""CPS HTTP server single-instance guard — Windows mutex + port probe."""
from __future__ import annotations

import errno
import os
import socket
import sys
import threading
from typing import Callable

# Port -> OS handle (Windows) or token; kept alive for process lifetime.
_active_handles: dict[int, object] = {}

# Non-Windows fallback locks (tests / dev only).
_fallback_locks: dict[int, threading.Lock] = {}
_fallback_held: set[int] = set()


class CpsSingleInstanceError(RuntimeError):
    """Raised when a second CPS HTTP instance must not start."""


def is_reloader_child() -> bool:
    """True for Werkzeug reloader worker processes only."""
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        return True
    try:
        from werkzeug.serving import is_running_from_reloader

        return bool(is_running_from_reloader())
    except Exception:
        return False


def _mutex_name(port: int) -> str:
    return f'Global\\SOLARIZ_CPS_HTTP_{int(port)}'


def _port_has_listener(
    host: str,
    port: int,
    timeout: float,
    *,
    connect_fn: Callable[[tuple[str, int], float], None] | None = None,
) -> bool:
    """Return True if something accepts TCP connections on host:port."""
    connect = connect_fn
    if connect is None:
        def connect(addr: tuple[str, int], tmo: float) -> None:
            with socket.create_connection(addr, timeout=tmo):
                return

    try:
        connect((host, int(port)), timeout)
        return True
    except ConnectionRefusedError:
        return False
    except TimeoutError:
        return False
    except OSError as exc:
        win_code = getattr(exc, 'winerror', None)
        if exc.errno in (errno.ETIMEDOUT, errno.ECONNREFUSED, errno.ECONNABORTED):
            return False
        if win_code in (10061, 10060):  # WSAECONNREFUSED, WSAETIMEDOUT
            return False
        raise CpsSingleInstanceError(
            f'Port probe failed for {host}:{port}: {exc}'
        ) from exc


def _acquire_mutex(port: int) -> object:
    if sys.platform == 'win32':
        return _acquire_mutex_windows(port)
    return _acquire_mutex_fallback(port)


def _acquire_mutex_windows(port: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    name = _mutex_name(port)
    handle = create_mutex(None, False, name)
    if not handle:
        err = ctypes.get_last_error()
        raise CpsSingleInstanceError(f'CreateMutexW failed for {name!r} (winerror={err})')

    already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if already_exists:
        close_handle(handle)
        raise CpsSingleInstanceError(
            f'CPS single-instance mutex already held ({name})'
        )

    return int(handle)


def _acquire_mutex_fallback(port: int) -> str:
    lock = _fallback_locks.setdefault(port, threading.Lock())
    if not lock.acquire(blocking=False):
        raise CpsSingleInstanceError(
            f'CPS single-instance mutex already held ({_mutex_name(port)})'
        )
    token = f'fallback-{port}-{id(lock)}'
    _fallback_held.add(port)
    return token


def _release_handle(port: int) -> None:
    handle = _active_handles.pop(port, None)
    if handle is None:
        return
    if sys.platform == 'win32':
        import ctypes

        ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle(handle)
    else:
        lock = _fallback_locks.get(port)
        if lock and port in _fallback_held:
            lock.release()
            _fallback_held.discard(port)


def release_cps_single_instance(port: int) -> None:
    """Release guard resources for *port* (test cleanup helper)."""
    _release_handle(port)


def acquire_cps_single_instance_or_raise(
    port: int,
    *,
    host: str = '127.0.0.1',
    connect_timeout: float = 0.5,
    connect_fn: Callable[[tuple[str, int], float], None] | None = None,
) -> None:
    """
    Acquire single-instance guard for CPS HTTP *port*.

    Reloader child processes skip all checks. Parent processes take a global
    mutex then verify the local TCP port is not already accepting connections.
    """
    if is_reloader_child():
        return

    port = int(port)
    handle: object | None = None
    try:
        handle = _acquire_mutex(port)
        if _port_has_listener(host, port, connect_timeout, connect_fn=connect_fn):
            raise CpsSingleInstanceError(
                f'Port {port} is already in use; CPS startup blocked.'
            )
        _active_handles[port] = handle
        handle = None
    finally:
        if handle is not None:
            if sys.platform == 'win32':
                import ctypes

                ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle(handle)
            else:
                lock = _fallback_locks.get(port)
                if lock and port in _fallback_held:
                    lock.release()
                    _fallback_held.discard(port)

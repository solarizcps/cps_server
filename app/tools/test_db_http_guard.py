# -*- coding: utf-8 -*-
"""HTTP write guard — block test traffic to live Flask :8080."""
from __future__ import annotations

import inspect
import os
from typing import Any
from urllib.parse import urlparse

LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST = 'LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST'
_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

_HTTP_GUARD: dict[str, Any] | None = None


class LiveHttpWriteError(RuntimeError):
    CODE = LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST

    def __init__(self, message: str, *, url: str | None = None, method: str | None = None):
        self.url = url
        self.method = method
        super().__init__(message)


def http_guard_is_active() -> bool:
    return _HTTP_GUARD is not None


def _script_hint() -> str:
    for frame in inspect.stack()[2:10]:
        fn = frame.filename or ''
        if 'test_db_http_guard.py' in fn or 'test_db_guard.py' in fn:
            continue
        if '_test_' in fn or '_browser_' in fn or os.sep + 'tests' + os.sep in fn:
            return fn
    return '<unknown>'


def _normalize_base(url: str) -> str:
    u = urlparse(url.strip())
    host = (u.hostname or '').lower()
    port = u.port
    if port is None:
        port = 443 if u.scheme == 'https' else 80
    return f'{u.scheme}://{host}:{port}'.lower()


def _is_live_host_port(host: str, port: int, live_port: int) -> bool:
    h = (host or '').lower()
    return port == live_port and h in ('127.0.0.1', 'localhost', '::1')


def _should_block(url: str, method: str, *, live_port: int, allowed_bases: tuple[str, ...]) -> bool:
    m = (method or 'GET').upper()
    if m not in _WRITE_METHODS:
        return False
    u = urlparse(url)
    host = (u.hostname or '').lower()
    port = u.port
    if port is None:
        port = 443 if u.scheme == 'https' else 80
    if not _is_live_host_port(host, port, live_port):
        return False
    base = _normalize_base(url)
    for allowed in allowed_bases:
        if base.startswith(_normalize_base(allowed)):
            return False
        if url.startswith(allowed.rstrip('/')):
            return False
    return True


def _forbidden(url: str, method: str) -> LiveHttpWriteError:
    return LiveHttpWriteError(
        f'{LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST}: {method} blocked for live HTTP endpoint. '
        f'url={url!r} script={_script_hint()}. '
        f'Use tools.nexgen_tmp_db.browser_test_server_context() with temp DB.',
        url=url,
        method=method,
    )


def install_live_http_write_guard(
    *,
    live_port: int = 8080,
    allowed_base_urls: tuple[str, ...] = (),
) -> dict[str, Any]:
    global _HTTP_GUARD
    if _HTTP_GUARD is not None:
        if allowed_base_urls:
            existing = set(_HTTP_GUARD.get('allowed_bases') or ())
            existing.update(allowed_base_urls)
            _HTTP_GUARD['allowed_bases'] = tuple(existing)
        return _HTTP_GUARD

    import urllib.request

    allowed = tuple(allowed_base_urls)
    state: dict[str, Any] = {
        'live_port': live_port,
        'allowed_bases': allowed,
        'blocked': 0,
        'real_urlopen': urllib.request.urlopen,
    }

    def guarded_urlopen(*args, **kwargs):
        url = args[0] if args else kwargs.get('fullurl') or kwargs.get('url')
        method = 'GET'
        data = kwargs.get('data')
        if len(args) > 1 and args[1] is not None:
            data = args[1]
        if isinstance(url, urllib.request.Request):
            method = (getattr(url, 'method', None) or url.get_method() or 'GET').upper()
            req_url = url.full_url
        else:
            req_url = str(url)
            if data is not None:
                method = 'POST'
        if _should_block(req_url, method, live_port=live_port, allowed_bases=state['allowed_bases']):
            state['blocked'] += 1
            raise _forbidden(req_url, method)
        return state['real_urlopen'](*args, **kwargs)

    urllib.request.urlopen = guarded_urlopen  # type: ignore[assignment]

    try:
        import requests

        real_session_request = requests.Session.request
        real_api_request = requests.api.request

        def guarded_session_request(self, method, url, *args, **kwargs):
            if _should_block(str(url), str(method), live_port=live_port, allowed_bases=state['allowed_bases']):
                state['blocked'] += 1
                raise _forbidden(str(url), str(method).upper())
            return real_session_request(self, method, url, *args, **kwargs)

        def guarded_api_request(method, url, **kwargs):
            if _should_block(str(url), str(method), live_port=live_port, allowed_bases=state['allowed_bases']):
                state['blocked'] += 1
                raise _forbidden(str(url), str(method).upper())
            return real_api_request(method, url, **kwargs)

        requests.Session.request = guarded_session_request  # type: ignore[assignment]
        requests.api.request = guarded_api_request  # type: ignore[assignment]
        state['requests_patched'] = True
        state['real_session_request'] = real_session_request
        state['real_api_request'] = real_api_request
    except ImportError:
        state['requests_patched'] = False

    _HTTP_GUARD = state
    return state


def uninstall_live_http_write_guard() -> None:
    global _HTTP_GUARD
    if not _HTTP_GUARD:
        return
    import urllib.request

    urllib.request.urlopen = _HTTP_GUARD['real_urlopen']  # type: ignore[assignment]
    if _HTTP_GUARD.get('requests_patched'):
        import requests

        requests.Session.request = _HTTP_GUARD['real_session_request']  # type: ignore[assignment]
        requests.api.request = _HTTP_GUARD['real_api_request']  # type: ignore[assignment]
    _HTTP_GUARD = None


def allow_http_base_url(base_url: str) -> None:
    if not _HTTP_GUARD:
        install_live_http_write_guard(allowed_base_urls=(base_url,))
        return
    bases = set(_HTTP_GUARD.get('allowed_bases') or ())
    bases.add(base_url.rstrip('/'))
    _HTTP_GUARD['allowed_bases'] = tuple(bases)

# -*- coding: utf-8 -*-
"""Cari Kart demo DB bağlamı — izole demo_finans.db, production fail-closed."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from config import Config

ENV_DEMO_DB = 'FINANS_CARI_DEMO_DB'
ENV_DEMO_MODE = 'FINANS_CARI_DEMO_MODE'
ENV_DEMO_ALLOWED = 'FINANS_CARI_DEMO_ALLOWED'


def demo_db_path() -> str | None:
    path = (os.environ.get(ENV_DEMO_DB) or '').strip()
    if path and os.path.isfile(path):
        return os.path.abspath(path)
    return None


def demo_mode_allowed() -> bool:
    if os.environ.get(ENV_DEMO_ALLOWED, '').lower() == '1':
        return True
    return bool(getattr(Config, 'DEBUG', False))


def demo_mode_requested(*, query_demo: str | None = None, env_flag: bool | None = None) -> bool:
    if query_demo == '1':
        return True
    if env_flag is True:
        return True
    return os.environ.get(ENV_DEMO_MODE, '').lower() == '1'


def resolve_demo_active(*, query_demo: str | None = None) -> bool:
    if not demo_mode_allowed():
        return False
    if not demo_mode_requested(query_demo=query_demo):
        return False
    return demo_db_path() is not None


def finans_db_connect(db_fn, request=None) -> tuple[sqlite3.Connection, dict[str, Any]]:
    """Ana DB veya demo DB — production'da demo fail-closed."""
    meta: dict[str, Any] = {'demo_modu': False, 'demo_db': None}
    qdemo = None
    if request is not None:
        qdemo = (request.args.get('demo') or '').strip()
    if resolve_demo_active(query_demo=qdemo):
        path = demo_db_path()
        assert path
        con = sqlite3.connect(path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON')
        meta['demo_modu'] = True
        meta['demo_db'] = path
        return con, meta
    return db_fn(), meta


def demo_badge_payload(meta: dict[str, Any]) -> dict[str, Any] | None:
    if meta.get('demo_modu'):
        return {'etiket': 'DEMO VERİ', 'demo_modu': True}
    return None
